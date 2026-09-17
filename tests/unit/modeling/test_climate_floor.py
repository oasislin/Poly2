#!/usr/bin/env python3
"""
Unit tests for ClimateFloor reconstruction module (Phase 1.5 Task 05).

Verifies:
1. Strict Out-Of-Sample (OOS) enforcement: 2019+ data strictly blocked.
2. Active 11 station universe enforcement: banned stations rejected.
3. Daily extreme aggregation with timezone projection and ADR-0009 full-report retention.
4. 31-day circular sliding window mathematical correctness across all 366 DOYs.
5. Periodic circular Gaussian smoothing seamless continuity across Dec 31 -> Jan 1.
6. Absolute variance floor (1.5°F) and physical plausibility gates [1.5, 8.0]°F.
7. Serialization and deserialization parity (Parquet and JSON).
8. Downstream ClimatologyCalculator integration compatibility.
"""

from datetime import date, datetime
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.data_processing.constants import ACTIVE_11_STATIONS
from src.modeling.climate_floor import (
    DAYS_IN_LEAP_YEAR,
    DEFAULT_HALF_WINDOW_DAYS,
    DEFAULT_SMOOTH_SIGMA_DAYS,
    DEFAULT_WINDOW_DAYS,
    FLOOR_ABS_MIN_F,
    FLOOR_PHYSICAL_MAX_F,
    FLOOR_PHYSICAL_MIN_F,
    TRAIN_END_YEAR,
    TRAIN_START_YEAR,
    ClimateFloorBuilder,
    ClimateFloorConfig,
    ClimateFloorPoint,
    ClimateFloorRegistry,
    ClimateFloorTable,
    aggregate_daily_extremes,
    apply_circular_smoothing,
    compute_raw_sliding_climatology,
    enforce_variance_floor_and_gates,
    load_station_raw_observations,
    resolve_day_of_year,
    validate_station_id,
    validate_year_range,
)
from src.modeling.climatology import ClimatologyCalculator


@pytest.fixture
def synthetic_daily_observations():
    """Generate 19 years (2000-2018) of synthetic local daily extremes for testing."""
    dates = pd.date_range("2000-01-01", "2018-12-31", freq="D")
    n = len(dates)
    doy = dates.dayofyear.values

    # Seasonal sinusoidal pattern: peak high in July (~day 200), trough in January
    np.random.seed(42)
    tmax = 70.0 + 20.0 * np.sin(2 * np.pi * (doy - 105) / 365.25) + np.random.normal(0, 3.0, n)
    tmin = tmax - 15.0 + np.random.normal(0, 2.0, n)

    df = pd.DataFrame({
        "station": "KORD",
        "local_date": dates.strftime("%Y-%m-%d"),
        "tmax": tmax,
        "tmin": tmin,
        "obs_count": 50,
        "month": dates.month,
        "day": dates.day,
        "doy": [
            [0, 31, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335][m - 1] + d
            for m, d in zip(dates.month, dates.day)
        ],
    })
    return df


class TestClimateFloorOOSDiscipline:
    """Test strict Out-Of-Sample (OOS) enforcement."""

    def test_oos_boundary_rejection(self):
        # 2018 is valid
        validate_year_range(2000, 2018)

        # 2019+ must raise ValueError
        with pytest.raises(ValueError, match="violates OOS boundary"):
            validate_year_range(2000, 2019)

        with pytest.raises(ValueError, match="violates OOS boundary"):
            validate_year_range(2000, 2026)

    def test_start_year_after_end_year_raises(self):
        with pytest.raises(ValueError, match="cannot be greater than end_year"):
            validate_year_range(2015, 2010)

    def test_loader_rejects_oos_years(self):
        with pytest.raises(ValueError, match="violates OOS boundary"):
            load_station_raw_observations("KORD", end_year=2019)


class TestStationUniverseValidation:
    """Test active 11 station universe enforcement."""

    def test_all_11_active_stations_pass(self):
        for st in ACTIVE_11_STATIONS:
            assert validate_station_id(st) == st
            assert validate_station_id(st.lower()) == st

    def test_banned_stations_fail_immediately(self):
        banned = ["KDCA", "ZSPD", "EGLC", "KDEN", "KJFK", "UNKNOWN"]
        for st in banned:
            with pytest.raises(ValueError, match="not in active 11 stations"):
                validate_station_id(st)


class TestDailyExtremesAggregation:
    """Test timezone projection and daily extreme aggregation."""

    def test_timezone_boundary_projection(self):
        # KORD is America/Chicago (UTC-6 in winter, UTC-5 in summer)
        # 2015-01-02 03:00 UTC is 2015-01-01 21:00 CST (belongs to 2015-01-01 local date)
        # 2015-01-02 08:00 UTC is 2015-01-02 02:00 CST (belongs to 2015-01-02 local date)
        records = [
            {"station": "KORD", "valid_utc": "2015-01-02 03:00:00", "temp_f": 30.0},
            {"station": "KORD", "valid_utc": "2015-01-02 04:00:00", "temp_f": 32.0},
            {"station": "KORD", "valid_utc": "2015-01-02 08:00:00", "temp_f": 20.0},
        ]
        df_obs = pd.DataFrame(records)
        daily = aggregate_daily_extremes(df_obs, station="KORD", min_daily_obs=1)

        assert len(daily) == 2
        d1 = daily[daily["local_date"] == "2015-01-01"].iloc[0]
        assert d1["tmax"] == 32.0
        assert d1["tmin"] == 30.0
        assert d1["obs_count"] == 2

        d2 = daily[daily["local_date"] == "2015-01-02"].iloc[0]
        assert d2["tmax"] == 20.0
        assert d2["tmin"] == 20.0
        assert d2["obs_count"] == 1

    def test_partial_boundary_day_filtration(self):
        # 2000-01-01 02:00 UTC is 1999-12-31 20:00 CST -> belongs to 1999, should be filtered
        # 2000-01-01 10:00 UTC is 2000-01-01 04:00 CST -> belongs to 2000
        records = [
            {"station": "KORD", "valid_utc": "2000-01-01 02:00:00", "temp_f": 25.0},
            {"station": "KORD", "valid_utc": "2000-01-01 10:00:00", "temp_f": 28.0},
        ]
        df_obs = pd.DataFrame(records)
        daily = aggregate_daily_extremes(df_obs, station="KORD", min_daily_obs=1)
        assert len(daily) == 1
        assert daily.iloc[0]["local_date"] == "2000-01-01"


class TestCircularSlidingWindowAndSmoothing:
    """Test 31-day window climatology and circular Gaussian smoothing."""

    def test_compute_raw_sliding_climatology(self, synthetic_daily_observations):
        mu_raw, sigma_raw, counts = compute_raw_sliding_climatology(
            synthetic_daily_observations, target_type="max", window_days=31
        )
        assert len(mu_raw) == 366
        assert len(sigma_raw) == 366
        assert len(counts) == 366

        # 19 years * 31 days approx 570-589 samples
        assert (counts >= 550).all()
        assert (counts <= 600).all()
        assert (sigma_raw > 0).all()

    def test_circular_smoothing_seamless_boundary(self):
        """Verify seamless wrap-around continuity across Dec 31 (day 366) -> Jan 1 (day 1)."""
        # Create a synthetic 366-day signal with small random noise
        x = np.linspace(0, 2 * np.pi, 366, endpoint=False)
        signal = 3.0 + 1.0 * np.cos(x) + np.random.normal(0, 0.2, 366)

        smoothed = apply_circular_smoothing(signal, sigma_days=7.0)
        assert len(smoothed) == 366

        # Boundary step between day 366 and day 1 should be smooth and negligible
        boundary_step = abs(smoothed[365] - smoothed[0])
        interior_step_1 = abs(smoothed[1] - smoothed[0])
        interior_step_last = abs(smoothed[365] - smoothed[364])

        # Step at boundary is commensurate with internal daily steps
        assert boundary_step < 0.15
        assert boundary_step <= max(interior_step_1, interior_step_last) * 2.0

    def test_variance_floor_and_physical_gates(self):
        # Value below floor (e.g. 1.0°F) must be elevated to 1.5°F
        raw_sigmas = np.array([1.0, 1.2, 1.5, 2.5, 4.0])
        floored = enforce_variance_floor_and_gates(
            raw_sigmas, station="KORD", target_type="max", floor_abs_min=1.5
        )
        assert floored[0] == 1.5
        assert floored[1] == 1.5
        assert floored[2] == 1.5
        assert floored[3] == 2.5

        # Value exceeding physical maximum (15.0°F) must raise ValueError
        bad_sigmas = np.array([1.5, 3.0, 16.5])
        with pytest.raises(ValueError, match="Physical plausibility gate violated"):
            enforce_variance_floor_and_gates(bad_sigmas, station="KORD", target_type="max")


class TestFullTableAndRegistry:
    """Test ClimateFloorTable, serialization, and ClimateFloorRegistry."""

    def test_table_build_and_serialization(self, synthetic_daily_observations, tmp_path):
        builder = ClimateFloorBuilder()
        table = builder.build_station_target_floor(
            synthetic_daily_observations, station="KORD", target_type="max"
        )
        assert len(table.points) == 366
        assert table.station == "KORD"
        assert table.target_type == "max"

        # Check point properties
        p1 = table.get_point(1)
        assert p1.day_of_year == 1
        assert p1.sigma_clim >= 1.5
        assert p1.variance_clim == round(p1.sigma_clim ** 2, 4)

        # Registry export to JSON and Parquet
        registry = ClimateFloorRegistry()
        registry.register_table(table)

        json_file = tmp_path / "climate_floor_test.json"
        registry.save_to_json(json_file)
        loaded_reg = ClimateFloorRegistry.load_from_json(json_file)

        mu, sigma = loaded_reg.get_climatology("KORD", "max", 1)
        assert mu == p1.mu_clim
        assert sigma == p1.sigma_clim

        var = loaded_reg.get_variance_floor("KORD", "max", "2026-01-01")
        assert np.isclose(var, p1.variance_clim)

        # Parquet export and reload
        pq_dir = tmp_path / "parquet_floors"
        registry.save_to_parquet_dir(pq_dir)
        loaded_pq_reg = ClimateFloorRegistry.load_from_parquet_dir(pq_dir)
        mu_pq, sigma_pq = loaded_pq_reg.get_climatology("KORD", "max", 1)
        assert mu_pq == p1.mu_clim
        assert sigma_pq == p1.sigma_clim


class TestDownstreamClimatologyCalculatorIntegration:
    """Test backward compatibility integration with ClimatologyCalculator."""

    def test_climatology_calculator_loads_floor_registry(self, synthetic_daily_observations):
        builder = ClimateFloorBuilder()
        table_max = builder.build_station_target_floor(
            synthetic_daily_observations, station="KORD", target_type="max"
        )
        table_min = builder.build_station_target_floor(
            synthetic_daily_observations, station="KORD", target_type="min"
        )

        reg = ClimateFloorRegistry()
        reg.register_table(table_max)
        reg.register_table(table_min)

        calc = ClimatologyCalculator().load_from_floor_registry(reg)

        # Query by date string
        mu_max, sigma_max = calc.get_climatology("KORD", "max", "2026-07-15")
        mu_min, sigma_min = calc.get_climatology("KORD", "min", "2026-07-15")

        assert mu_max > mu_min
        assert sigma_max >= 1.5
        assert sigma_min >= 1.5

        # Query variance floor
        var_max = calc.get_climatology_variance("KORD", "max", "2026-07-15")
        assert np.isclose(var_max, sigma_max ** 2)


class TestRebuildCLIOrchestrator:
    """Test batch CLI orchestration script functions."""

    def test_cli_station_validation(self):
        from scripts.rebuild_climate_floor import validate_requested_stations

        assert validate_requested_stations(["KORD", "klga"]) == ["KORD", "KLGA"]
        with pytest.raises(ValueError, match="not in active 11 stations"):
            validate_requested_stations(["KDCA"])

    def test_run_batch_rebuild_kord_dry_run(self, tmp_path):
        from scripts.rebuild_climate_floor import run_batch_rebuild

        # Run fast 3-year test on real KORD data
        reg, stats = run_batch_rebuild(
            stations=["KORD"],
            raw_dir=Path("data/raw/iem"),
            output_dir=tmp_path / "climate_floor",
            config_out=tmp_path / "climate_floor.json",
            start_year=2000,
            end_year=2002,
            dry_run=False,
        )

        assert "KORD" in stats
        assert "max" in stats["KORD"]
        assert "min" in stats["KORD"]
        assert (tmp_path / "climate_floor" / "KORD_climate_floor.parquet").exists()
        assert (tmp_path / "climate_floor.json").exists()
        assert (tmp_path / "climate_floor" / "manifest.json").exists()


class TestGovernanceContractADR0010:
    """Governance contract tests enforcing ADR-0010 physical bound derivation rules."""

    def test_floor_physical_max_governance_contract(self):
        """ADR-0010 Guardrail: FLOOR_PHYSICAL_MAX_F must bound empirical max without undue slack."""
        # 1. Must strictly accommodate highest observed winter sigma across 11 stations (Denver 13.74°F)
        assert FLOOR_PHYSICAL_MAX_F >= 13.74, (
            f"FLOOR_PHYSICAL_MAX_F ({FLOOR_PHYSICAL_MAX_F}) 严禁低于丹佛实测极值 13.74°F！"
            "否则将硬性截断大陆性真实物理方差。详情参见 docs/adr/ADR-0010。"
        )
        # 2. Safety margin must be controlled (between 1.0°F and 3.0°F, currently 1.26°F)
        empirical_max_denver = 13.74
        slack = FLOOR_PHYSICAL_MAX_F - empirical_max_denver
        assert 1.0 <= slack <= 3.0, (
            f"FLOOR_PHYSICAL_MAX_F 安全裕度 ({slack:.2f}°F) 超出合法范围 [1.0, 3.0] °F！"
            "门禁过松或过紧。详情参见 docs/adr/ADR-0010。"
        )
        # 3. Floor minimum must prevent collapse
        assert FLOOR_PHYSICAL_MIN_F == FLOOR_ABS_MIN_F == 1.5, (
            "FLOOR_PHYSICAL_MIN_F 与 FLOOR_ABS_MIN_F 必须精确对齐为 1.5°F。"
        )


