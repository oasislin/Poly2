#!/usr/bin/env python3
"""
Unit tests for ModelRegistry and unified model inference facade (Ticket 2.2-06 / Issue #19).

Verifies:
1. Standardized model persistence file naming: {StationID}_{Season}_{Max|Min}_lead{Hours}h.pkl.
2. Saving and loading GaussianEMOS model and associated metadata (diagnostics, degradation status).
3. Batch persistence of MatrixScorecard and full dense 6h-grid.
4. Model inventory listing as DataFrame.
5. get_model and predict facade methods with automatic season mapping, interpolation, and degradation routing.
"""

from datetime import date
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.modeling.climatology import ClimatologyCalculator
from src.modeling.degradation import DegradationDecision
from src.modeling.emos_trainer import ModelTrainingDiagnostics
from src.modeling.gaussian_emos import GaussianEMOS
from src.modeling.interpolator import LeadTimeInterpolator
from src.modeling.matrix_trainer import MatrixScorecard
from src.modeling.registry import ModelRegistry


@pytest.fixture
def temp_registry_dir(tmp_path):
    """Temporary model directory for registry tests."""
    model_dir = tmp_path / "models" / "emos"
    model_dir.mkdir(parents=True, exist_ok=True)
    return model_dir


class TestModelRegistryPersistence:
    """Test saving, loading, and file naming conventions."""

    def test_save_and_load_single_model_standard_naming(self, temp_registry_dir):
        registry = ModelRegistry(base_dir=temp_registry_dir)
        model = GaussianEMOS(a=0.3, b=0.95, c=0.1, d=0.85)
        diag = ModelTrainingDiagnostics(
            success=True,
            params=(0.3, 0.95, 0.1, 0.85),
            crps_in_sample=1.2,
            crps_raw_ensemble=1.8,
            crps_climatology=2.5,
            crpss_vs_raw=0.33,
            crpss_vs_clim=0.52,
            n_iterations=20,
            n_evaluations=30,
            grad_norm=1e-6,
            restarts_used=0,
            sample_count=300,
        )
        decision = DegradationDecision(level=1, is_degraded=False, reason="Healthy")

        # Save model
        saved_path = registry.save_model(
            model=model,
            station_id="ZSPD",
            season="Winter",
            target_type="max",
            lead_hours=30,
            diagnostics=diag,
            decision=decision,
        )

        expected_filename = "ZSPD_Winter_Max_lead30h.pkl"
        assert saved_path.name == expected_filename
        assert saved_path.exists()

        # Load model back
        loaded_model, metadata = registry.load_model(
            station_id="ZSPD",
            season="Winter",
            target_type="max",
            lead_hours=30,
        )

        assert np.isclose(loaded_model.a, 0.3)
        assert np.isclose(loaded_model.b, 0.95)
        assert np.isclose(loaded_model.c, 0.1)
        assert np.isclose(loaded_model.d, 0.85)
        assert metadata["station_id"] == "ZSPD"
        assert metadata["season"] == "Winter"
        assert metadata["target_type"] == "max"
        assert metadata["lead_hours"] == 30
        assert metadata["diagnostics"]["crps_in_sample"] == 1.2

    def test_save_scorecard_and_inventory(self, temp_registry_dir):
        registry = ModelRegistry(base_dir=temp_registry_dir)
        
        # Build mock scorecard with 4 models
        models = {}
        for lead in [6, 30, 54]:
            m = GaussianEMOS(a=0.1 * lead, b=1.0, c=0.2, d=0.8)
            d = ModelTrainingDiagnostics(
                success=True, params=(0.1 * lead, 1.0, 0.2, 0.8),
                crps_in_sample=1.0, crps_raw_ensemble=1.5, crps_climatology=2.0,
                crpss_vs_raw=0.33, crpss_vs_clim=0.5, n_iterations=10, n_evaluations=15,
                grad_norm=1e-6, restarts_used=0, sample_count=100
            )
            dec = DegradationDecision(level=1, is_degraded=False, reason="Healthy")
            models[("ZSPD", "Winter", "max", lead)] = (m, d, dec)

        scorecard = MatrixScorecard(models=models)
        registry.save_scorecard(scorecard, build_dense_grid=True)

        inventory = registry.list_inventory()
        assert isinstance(inventory, pd.DataFrame)
        # Should contain saved anchors + interpolated 6h grid
        assert len(inventory) >= 3
        assert "ZSPD_Winter_Max_lead30h.pkl" in inventory["filename"].values


class TestModelRegistryQueryFacade:
    """Test get_model and predict inference facade."""

    def test_get_model_with_date_and_interpolation(self, temp_registry_dir):
        registry = ModelRegistry(base_dir=temp_registry_dir)
        
        # Save anchor models at 6h, 30h, 54h for ZSPD Summer Max
        m6 = GaussianEMOS(a=0.0, b=1.0, c=0.2, d=0.8)
        m30 = GaussianEMOS(a=1.0, b=0.9, c=0.4, d=1.0)
        m54 = GaussianEMOS(a=2.0, b=0.8, c=0.6, d=1.2)
        diag = ModelTrainingDiagnostics(
            success=True, params=(0, 1, 0, 1), crps_in_sample=1.0, crps_raw_ensemble=1.0,
            crps_climatology=1.0, crpss_vs_raw=0.0, crpss_vs_clim=0.0, n_iterations=1,
            n_evaluations=1, grad_norm=0, restarts_used=0, sample_count=100
        )
        dec = DegradationDecision(level=1, is_degraded=False, reason="Healthy")

        registry.save_model(m6, "ZSPD", "Summer", "max", 6, diag, dec)
        registry.save_model(m30, "ZSPD", "Summer", "max", 30, diag, dec)
        registry.save_model(m54, "ZSPD", "Summer", "max", 54, diag, dec)

        # 1. Query exact anchor with date "2019-07-15" (Month 7 -> Summer)
        model_30 = registry.get_model("ZSPD", target_date="2019-07-15", target_type="max", lead_hours=30)
        assert np.isclose(model_30.a, 1.0)

        # 2. Query intermediate non-anchor 18h (interpolated between 6h and 30h)
        model_18 = registry.get_model("ZSPD", target_date="2019-07-15", target_type="max", lead_hours=18)
        assert np.isclose(model_18.a, 0.5)  # halfway between 0.0 and 1.0

    def test_predict_facade(self, temp_registry_dir):
        registry = ModelRegistry(base_dir=temp_registry_dir)
        m30 = GaussianEMOS(a=0.5, b=0.9, c=0.2, d=1.0)
        diag = ModelTrainingDiagnostics(
            success=True, params=(0.5, 0.9, 0.2, 1.0), crps_in_sample=1.0, crps_raw_ensemble=1.0,
            crps_climatology=1.0, crpss_vs_raw=0.0, crpss_vs_clim=0.0, n_iterations=1,
            n_evaluations=1, grad_norm=0, restarts_used=0, sample_count=100
        )
        dec = DegradationDecision(level=1, is_degraded=False, reason="Healthy")
        registry.save_model(m30, "ZSPD", "Winter", "max", 30, diag, dec)

        pred_dist = registry.predict(
            station_id="ZSPD",
            target_date="2019-01-15",  # Winter
            target_type="max",
            lead_hours=30,
            ensemble_mean=10.0,
            ensemble_variance=1.0,
            sigma_clim_squared=4.0,
        )

        assert isinstance(pred_dist, GaussianEMOS)
        # mu = 0.5 + 0.9 * 10 = 9.5
        # sigma^2 = 0.04 + 1.0 * 1.0 + 4.0 = 5.04 -> sigma = sqrt(5.04)
        assert np.isclose(pred_dist.mu, 9.5)
        assert np.isclose(pred_dist.sigma, np.sqrt(5.04))


class TestModelRegistryJSONAndManifest:
    """Production-grade tests for 200-model JSON persistence, manifest generation, and tamper-evident verification."""

    def test_save_and_load_model_json(self, temp_registry_dir):
        from src.modeling.registry import ManifestVerificationError
        registry = ModelRegistry(base_dir=temp_registry_dir)

        model = GaussianEMOS(a=0.31234567, b=0.98765432, c=0.12345678, d=0.87654321)
        diag = ModelTrainingDiagnostics(
            success=True,
            params=(0.31234567, 0.98765432, 0.12345678, 0.87654321),
            crps_in_sample=1.23456,
            crps_raw_ensemble=1.87654,
            crps_climatology=2.46810,
            crpss_vs_raw=0.3421,
            crpss_vs_clim=0.4998,
            n_iterations=25,
            n_evaluations=36,
            grad_norm=1.2e-7,
            restarts_used=0,
            sample_count=365,
            warnings=["Minor iteration notice"],
        )
        decision = DegradationDecision(level=1, is_degraded=False, reason="Healthy")

        # Save model in JSON format
        json_path = registry.save_model_json(
            model=model,
            station_id="KORD",
            season="Winter",
            target_type="max",
            lead_hours=48,
            diagnostics=diag,
            decision=decision,
        )

        expected_relpath = Path("emos") / "KORD" / "max_Winter_48h.json"
        assert json_path.relative_to(temp_registry_dir) == expected_relpath
        assert json_path.exists()

        # Load back
        loaded_model, metadata = registry.load_model_json(
            station_id="KORD",
            season="Winter",
            target_type="max",
            lead_hours=48,
        )

        assert np.isclose(loaded_model.a, 0.31234567)
        assert np.isclose(loaded_model.b, 0.98765432)
        assert np.isclose(loaded_model.c, 0.12345678)
        assert np.isclose(loaded_model.d, 0.87654321)

        assert metadata["station"] == "KORD"
        assert metadata["variable"] == "max"
        assert metadata["season"] == "Winter"
        assert metadata["lead_hours"] == 48
        assert metadata["health_grade"] == "WARNING"
        assert metadata["decision"]["level"] == 1
        assert metadata["decision"]["is_degraded"] is False
        assert metadata["diagnostics"]["sample_count"] == 365
        assert "saved_at" in metadata
        assert metadata["format_version"] == "2.0.0"

    def test_save_200_models_matrix_and_manifest(self, temp_registry_dir):
        from src.data_processing.constants import ACTIVE_10_STATIONS
        from src.modeling.partitioner import DatasetPartitioner, SEASONS, TRAIN_START_YEAR, TRAIN_END_YEAR

        registry = ModelRegistry(base_dir=temp_registry_dir)
        partitioner = DatasetPartitioner()

        models = {}
        for station in ACTIVE_10_STATIONS:
            for season in SEASONS:
                for target_type in ["max", "min"]:
                    lead_nodes = partitioner.get_station_lead_nodes(station, season=season, target_type=target_type)
                    for lead in lead_nodes:
                        m = GaussianEMOS(a=0.1, b=0.9, c=0.05, d=0.95)
                        diag = ModelTrainingDiagnostics(
                            success=True,
                            params=(0.1, 0.9, 0.05, 0.95),
                            crps_in_sample=1.0,
                            crps_raw_ensemble=1.5,
                            crps_climatology=2.0,
                            crpss_vs_raw=0.33,
                            crpss_vs_clim=0.5,
                            n_iterations=10,
                            n_evaluations=15,
                            grad_norm=1e-6,
                            restarts_used=0,
                            sample_count=300,
                        )
                        dec = DegradationDecision(level=1, is_degraded=False, reason="Healthy")
                        models[(station, season, target_type, lead)] = (m, diag, dec)

        scorecard = MatrixScorecard(models=models)
        assert len(scorecard.models) == 200

        # Persist full scorecard as JSON with manifest
        saved_paths, manifest_path = registry.save_scorecard_json(scorecard)

        assert len(saved_paths) == 200
        assert manifest_path.exists()
        assert manifest_path.name == "manifest.json"

        # Check manifest contents
        import json
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        assert manifest["manifest_version"] == "2.0.0"
        assert manifest["train_start_year"] == TRAIN_START_YEAR
        assert manifest["train_end_year"] == TRAIN_END_YEAR
        assert manifest["station_count"] == 10
        assert manifest["total_models"] == 200
        assert set(manifest["station_universe"]) == set(ACTIVE_10_STATIONS)
        assert len(manifest["models"]) == 200

        # Verify manifest entry keys
        sample_key = "emos/KORD/max_Winter_48h.json"
        assert sample_key in manifest["models"]
        sample_entry = manifest["models"][sample_key]
        assert "sha256" in sample_entry
        assert len(sample_entry["sha256"]) == 64
        assert sample_entry["station"] == "KORD"
        assert sample_entry["variable"] == "max"

    def test_verify_and_load_manifest_success_and_fail_closed(self, temp_registry_dir):
        from src.data_processing.constants import ACTIVE_10_STATIONS
        from src.modeling.partitioner import DatasetPartitioner, SEASONS
        from src.modeling.registry import ManifestVerificationError

        registry = ModelRegistry(base_dir=temp_registry_dir)
        partitioner = DatasetPartitioner()

        models = {}
        for station in ACTIVE_10_STATIONS:
            for season in SEASONS:
                for target_type in ["max", "min"]:
                    lead_nodes = partitioner.get_station_lead_nodes(station, season=season, target_type=target_type)
                    for lead in lead_nodes:
                        m = GaussianEMOS(a=0.1, b=0.9, c=0.05, d=0.95)
                        diag = ModelTrainingDiagnostics(
                            success=True,
                            params=(0.1, 0.9, 0.05, 0.95),
                            crps_in_sample=1.0,
                            crps_raw_ensemble=1.5,
                            crps_climatology=2.0,
                            crpss_vs_raw=0.33,
                            crpss_vs_clim=0.5,
                            n_iterations=10,
                            n_evaluations=15,
                            grad_norm=1e-6,
                            restarts_used=0,
                            sample_count=300,
                        )
                        dec = DegradationDecision(level=1, is_degraded=False, reason="Healthy")
                        models[(station, season, target_type, lead)] = (m, diag, dec)

        scorecard = MatrixScorecard(models=models)
        registry.save_scorecard_json(scorecard)

        # 1. Normal verification passes
        verified_manifest = registry.verify_and_load_manifest()
        assert verified_manifest["total_models"] == 200

        # 2. Tampering injection test: alter a byte in one JSON file
        target_file = temp_registry_dir / "emos" / "KORD" / "max_Winter_48h.json"
        import json
        with open(target_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["parameters"]["a"] = 999.999  # Tamper parameter
        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        # Verification must fail-closed immediately!
        with pytest.raises(ManifestVerificationError) as exc_info:
            registry.verify_and_load_manifest()
        assert "tampered" in str(exc_info.value).lower() or "mismatch" in str(exc_info.value).lower()

        # 3. Missing file test
        target_file.unlink()
        with pytest.raises(ManifestVerificationError) as exc_info_missing:
            registry.verify_and_load_manifest()
        assert "missing" in str(exc_info_missing.value).lower() or "not found" in str(exc_info_missing.value).lower()

    def test_get_model_json_compatibility(self, temp_registry_dir):
        registry = ModelRegistry(base_dir=temp_registry_dir)
        m = GaussianEMOS(a=0.45, b=0.88, c=0.15, d=0.92)
        diag = ModelTrainingDiagnostics(
            success=True, params=(0.45, 0.88, 0.15, 0.92), crps_in_sample=1.0, crps_raw_ensemble=1.0,
            crps_climatology=1.0, crpss_vs_raw=0.0, crpss_vs_clim=0.0, n_iterations=1,
            n_evaluations=1, grad_norm=0, restarts_used=0, sample_count=100
        )
        dec = DegradationDecision(level=1, is_degraded=False, reason="Healthy")

        # Save via new JSON method
        registry.save_model_json(
            model=m,
            station_id="KORD",
            season="Winter",
            target_type="max",
            lead_hours=48,
            diagnostics=diag,
            decision=dec,
        )

        # get_model should seamlessly resolve and load it
        loaded = registry.get_model("KORD", target_date="2019-01-15", target_type="max", lead_hours=48)
        assert np.isclose(loaded.a, 0.45)
        assert np.isclose(loaded.b, 0.88)

    def test_inventory_with_json_and_pkl(self, temp_registry_dir):
        registry = ModelRegistry(base_dir=temp_registry_dir)
        m = GaussianEMOS(a=0.1, b=1.0, c=0.1, d=1.0)
        diag = ModelTrainingDiagnostics(
            success=True, params=(0.1, 1.0, 0.1, 1.0), crps_in_sample=1.0, crps_raw_ensemble=1.0,
            crps_climatology=1.0, crpss_vs_raw=0.0, crpss_vs_clim=0.0, n_iterations=1,
            n_evaluations=1, grad_norm=0, restarts_used=0, sample_count=100
        )
        dec = DegradationDecision(level=1, is_degraded=False, reason="Healthy")

        # 1. Save one PKL model
        registry.save_model(m, "ZSPD", "Winter", "max", 30, diag, dec)
        # 2. Save one JSON model
        registry.save_model_json(m, "KORD", "Winter", "max", 48, diag, dec)

        df_inv = registry.list_inventory()
        assert len(df_inv) == 2
        assert set(df_inv["format"].values) == {"pkl", "json"}
        assert "KORD" in df_inv["station_id"].values
        assert "ZSPD" in df_inv["station_id"].values

    def test_pipeline_cli_dry_run(self):
        from src.modeling.pipeline import main
        ret = main(["--dry-run", "--stations", "KORD", "KLGA", "--model-dir", "data/models"])
        assert ret == 0


