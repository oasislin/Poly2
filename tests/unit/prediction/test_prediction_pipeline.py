#!/usr/bin/env python3
"""
Unit tests for PredictionPipeline (Ticket 3.5-01 / Issue #30).

Verifies:
1. End-to-end pipeline execution:
   Input features -> StaticPredictor -> DynamicCorrector -> ConstraintEnforcer -> BinConverter.
2. Complete PredictionRecord structure and metadata.
3. Database persistence: writing prediction records to SQLite and querying back.
4. Unobserved flow (no real-time temp) vs Observed flow (active dynamic truncation).
5. Batch DataFrame prediction and persistence.
6. Settlement winning bin determination via pipeline record.
"""

from datetime import datetime, timezone
import json
import sqlite3
import numpy as np
import pandas as pd
import pytest

from src.modeling.gaussian_emos import GaussianEMOS
from src.prediction.bin_converter import BinConverter, MarketBin
from src.prediction.constraint_enforcer import ConstraintEnforcer
from src.prediction.discrete_bin_engine import DiscreteBin
from src.prediction.dynamic_corrector import DynamicCorrector
from src.prediction.prediction_pipeline import PredictionPipeline, PredictionRecord
from src.prediction.static_predictor import StaticPredictor, StaticPredictionResult


class MockRegistry:
    """Mock registry providing anchor models for ZSPD and KDEN."""

    def __init__(self):
        self.models = {
            ("ZSPD", "Jja", "max", 30): GaussianEMOS(a=1.0, b=0.95, c=0.4, d=0.8),
            ("ZSPD", "Djf", "min", 24): GaussianEMOS(a=-1.0, b=1.05, c=0.5, d=0.6),
            ("KDEN", "Jja", "max", 30): GaussianEMOS(a=0.0, b=1.0, c=0.3, d=0.7),
            ("KORD", "Jja", "max", 30): GaussianEMOS(a=0.0, b=1.0, c=0.4, d=0.8),
            ("KMIA", "Jja", "max", 30): GaussianEMOS(a=0.0, b=1.0, c=0.4, d=0.8),
        }

    def get_model(self, station_id, target_date, target_type, lead_hours):
        month = pd.to_datetime(target_date).month
        season = "Jja" if month in [6, 7, 8] else ("Djf" if month in [12, 1, 2] else "Mam")
        int_lead = int(round(lead_hours))
        return self.models.get((station_id.upper(), season, target_type.lower(), int_lead), GaussianEMOS(a=0.0, b=1.0, c=0.0, d=1.0))

    def predict(self, station_id, target_date, target_type, lead_hours, ensemble_mean, ensemble_variance, sigma_clim_squared):
        month = pd.to_datetime(target_date).month
        season = "Jja" if month in [6, 7, 8] else ("Djf" if month in [12, 1, 2] else "Mam")
        anchors = {
            k[3]: m for k, m in self.models.items()
            if k[0] == station_id.upper() and k[1] == season and k[2] == target_type.lower()
        }
        from src.modeling.interpolator import LeadTimeInterpolator
        return LeadTimeInterpolator().predict_distribution(
            target_type=target_type,
            lead_hours=lead_hours,
            ensemble_mean=ensemble_mean,
            ensemble_variance=ensemble_variance,
            sigma_clim_squared=sigma_clim_squared,
            anchor_models=anchors,
        )


class MockClimatology:
    def get_climatology_variance(self, station_id, target_type, target_date):
        return 4.0


@pytest.fixture
def pipeline(tmp_path):
    db_file = tmp_path / "test_predictions.db"
    return PredictionPipeline(
        model_registry=MockRegistry(),
        climatology_calculator=MockClimatology(),
        db_path=db_file,
    )


class TestPredictionPipelineExecution:
    """Test full four-stage prediction execution and persistence."""

    def test_single_prediction_end_to_end_shanghai_max(self, pipeline):
        """Execute full end-to-end pipeline for Shanghai Summer Max temperature."""
        # GEFS features: ens_mean=30.0, ens_var=2.0
        # Observation at 12:00: T_now = 28.5°C
        record = pipeline.predict_single(
            station_id="ZSPD",
            target_date="2019-07-15",
            target_type="max",
            lead_time_hours=30,
            ensemble_mean=30.0,
            ensemble_variance=2.0,
            current_temp=28.5,
            observation_time="12:00",
            save_to_db=True,
        )

        assert isinstance(record, PredictionRecord)
        assert record.station_id == "ZSPD"
        assert record.target_date == "2019-07-15"
        assert record.target_type == "max"
        assert np.isclose(record.predicted_mu, 29.5, atol=1e-5)
        # ADR-0015 §2.1: sigma^2 = c^2 + d^2 * ens_var = 0.4^2 + 0.8^2 * 2.0 = 1.44 (clim addend abolished)
        assert np.isclose(record.predicted_sigma, np.sqrt(1.44), atol=1e-5)
        assert record.is_truncated is True
        assert record.is_physically_constrained is True

        # Check market bins
        assert len(record.market_bins) == 7
        total_p = sum(b.probability for b in record.market_bins)
        assert np.isclose(total_p, 1.0, atol=1e-6)

        # Check persistence in SQLite
        history_df = pipeline.get_history("ZSPD", target_date="2019-07-15")
        assert len(history_df) == 1
        assert history_df.iloc[0]["station_id"] == "ZSPD"
        assert np.isclose(history_df.iloc[0]["predicted_mu"], 29.5, atol=1e-5)
        assert "bin_probabilities" in history_df.columns

    def test_single_prediction_denver_fahrenheit(self, pipeline):
        """Denver KDEN prediction should produce Fahrenheit discrete market bins."""
        record = pipeline.predict_single(
            station_id="KDEN",
            target_date="2019-07-15",
            target_type="max",
            lead_time_hours=30,
            ensemble_mean=25.0,  # 25°C ≈ 77°F
            ensemble_variance=2.0,
            current_temp=22.0,
            save_to_db=True,
        )

        assert record.station_id == "KDEN"
        assert len(record.market_bins) > 0
        assert record.market_bins[0].unit == "F"
        total_p = sum(b.probability for b in record.market_bins)
        assert np.isclose(total_p, 1.0, atol=1e-6)

    def test_active10_station_uses_statutory_2deg_grid(self, pipeline):
        """KORD/KMIA operate natively in °F and land on the statutory 2°F adsorbed grid, never on 1°C bins."""
        record = pipeline.predict_single(
            station_id="KORD",
            target_date="2019-07-15",
            target_type="max",
            lead_time_hours=30,
            ensemble_mean=77.0,  # native °F -> center even bin 76-78°F
            ensemble_variance=2.0,
            current_temp=None,
            save_to_db=False,
        )

        bins = record.market_bins
        assert len(bins) == 11
        assert all(isinstance(b, DiscreteBin) for b in bins)
        assert bins[0].bin_type == "lte" and bins[-1].bin_type == "gte"
        # Even-integer 2°F grid with half-degree continuity edges
        assert bins[0].upper_bound_f == pytest.approx(67.5)
        assert bins[-1].lower_bound_f == pytest.approx(85.5)
        window = bins[1:-1]
        assert all(b.upper_bound_f - b.lower_bound_f == pytest.approx(2.0) for b in window)
        assert all(b.step_size == 2.0 for b in window)
        assert np.isclose(sum(b.probability for b in bins), 1.0, atol=1e-9)

        # Settlement uses the °F edges directly, no double °C<->°F conversion
        idx, winner = record.get_winning_bin(observed_temp=77.0, unit="F")
        assert winner.label == "76-78°F"
        assert idx == 5

    def test_active10_kmia_native_fahrenheit_constrained_and_truncated(self, pipeline):
        """KMIA native °F prediction with dynamic truncation + physical bounds must center near 88°F, never 188-192°F."""
        record = pipeline.predict_single(
            station_id="KMIA",
            target_date="2019-07-15",
            target_type="max",
            lead_time_hours=30,
            ensemble_mean=85.0,  # native °F
            ensemble_variance=2.0,
            current_temp=86.0,  # native °F at 12:00 (delta_t = 3h, KMIA Summer r_warm = 6.3°F/h -> T_max = 104.9°F)
            observation_time="12:00",
            save_to_db=False,
        )

        assert np.isclose(record.predicted_mu, 85.0, atol=1e-6)
        assert record.is_truncated is True
        assert record.is_physically_constrained is True
        assert np.isclose(record.constrained_distribution.t_min_possible, 86.0, atol=1e-6)
        assert np.isclose(record.constrained_distribution.t_max_possible, 86.0 + 6.3 * 3.0, atol=1e-6)

        bins = record.market_bins
        assert len(bins) == 11
        # Bins must center around 84-86°F (no 188-192°F double conversion)
        assert bins[5].label == "84-86°F"
        assert np.isclose(sum(b.probability for b in bins), 1.0, atol=1e-9)
        # Dynamic truncation at 86.0°F zeroes <= 85.5°F bins and leaves surviving probability >= 86°F
        assert bins[5].lower_bound_f == pytest.approx(83.5)
        assert bins[5].upper_bound_f == pytest.approx(85.5)
        assert bins[5].probability == pytest.approx(0.0, abs=1e-9)
        assert bins[6].label == "86-88°F"
        assert bins[6].probability > 0.3

    def test_unobserved_static_flow(self, pipeline):
        """When current_temp is omitted, pipeline generates base forecast + discrete bins without truncation."""
        record = pipeline.predict_single(
            station_id="ZSPD",
            target_date="2019-07-15",
            target_type="max",
            lead_time_hours=30,
            ensemble_mean=30.0,
            ensemble_variance=2.0,
            current_temp=None,
            save_to_db=False,
        )

        assert record.is_truncated is False
        assert record.is_physically_constrained is False
        assert len(record.market_bins) == 7
        assert np.isclose(sum(b.probability for b in record.market_bins), 1.0, atol=1e-6)

    def test_batch_predictions_execution(self, pipeline):
        """Batch execution over DataFrame of dates."""
        df = pd.DataFrame({
            "station_id": ["ZSPD", "ZSPD"],
            "target_date": ["2019-07-15", "2019-07-16"],
            "target_type": ["max", "max"],
            "lead_time_hours": [30, 30],
            "ensemble_mean": [30.0, 31.0],
            "ensemble_variance": [2.0, 2.5],
            "current_temp": [28.0, 29.0],
            "sigma_clim_squared": [4.0, 4.0],
        })

        out_df = pipeline.predict_batch(df, save_to_db=True)

        assert len(out_df) == 2
        assert "predicted_mu" in out_df.columns
        assert "bin_probabilities" in out_df.columns

        # Verify 2 records in database
        db_records = pipeline.get_history("ZSPD")
        assert len(db_records) >= 2

    def test_winning_bin_determination_from_record(self, pipeline):
        """Determine settlement winning bin from PredictionRecord."""
        record = pipeline.predict_single(
            station_id="ZSPD",
            target_date="2019-07-15",
            target_type="max",
            lead_time_hours=30,
            ensemble_mean=30.0,
            ensemble_variance=2.0,
            current_temp=28.5,
        )

        # Ground truth observation is 30.2°C
        win_idx, win_bin = record.get_winning_bin(observed_temp=30.2, unit="C")
        assert win_bin.label == "30°C"
        assert win_bin.contains(30.2, "C")


    def test_predict_single_forwards_three_real_time_inputs_and_station_state(self, pipeline):
        """PredictionPipeline passes separated extreme_m, instant_x_t, and t_local to DynamicCorrector."""
        from datetime import datetime, timezone
        from src.prediction.monotonic_confluence import MonotonicConfluenceEngine, ObservationPacket

        engine = MonotonicConfluenceEngine()
        t_obs = datetime(2019, 7, 15, 20, 0, tzinfo=timezone.utc)
        engine.ingest(
            ObservationPacket(
                station_id="KMIA",
                timestamp_utc=t_obs,
                temp_c=None,
                temp_f=89.0,
                source_type="iem_metar",
                is_speci=False,
            )
        )
        state = engine.ingest(
            ObservationPacket(
                station_id="KMIA",
                timestamp_utc=t_obs,
                temp_c=None,
                temp_f=84.0,
                source_type="iem_metar",
                is_speci=False,
            )
        )

        record = pipeline.predict_single(
            station_id="KMIA",
            target_date="2019-07-15",
            target_type="max",
            lead_time_hours=30,
            ensemble_mean=88.0,
            ensemble_variance=2.0,
            station_state=state,
            t_local="15:30",
            save_to_db=False,
        )
        assert record.dynamic_distribution.extreme_m == pytest.approx(89.0)
        assert record.dynamic_distribution.instant_x_t == pytest.approx(84.0)
        assert record.dynamic_distribution.t_local_hour == pytest.approx(15.5)
        assert record.dynamic_distribution.mu_r_result is not None
        assert record.dynamic_distribution.mu_r_result.mu_r < 0.0
