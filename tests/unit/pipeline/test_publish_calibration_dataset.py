#!/usr/bin/env python3
"""
Unit tests for calibration dataset publisher (Task 08).
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import pandas as pd

from scripts.publish_calibration_dataset import (
    DATASET_VERSION,
    EXPECTED_FEATURE_FILES,
    EXPECTED_FLOOR_FILES,
    EXPECTED_GEFS_FILES,
    EXPECTED_TOTAL_FILES,
    DatasetItem,
    assemble_dataset_directory,
    collect_feature_files,
    collect_floor_files,
    collect_gefs_files,
    compute_file_sha256,
    generate_manifest,
    validate_station_universe,
    verify_gate_3_coverage,
    verify_gate_4_oos_discipline,
    verify_gate_5_ledger_clearance,
    verify_gate_6_forecast_features,
)
from src.data_processing.constants import ACTIVE_11_STATIONS


class TestStationUniverseValidation:
    """Test strict Active 11 station universe compliance."""

    def test_active_stations_admitted(self):
        for st in ACTIVE_11_STATIONS:
            assert validate_station_universe(st) == st
            assert validate_station_universe(st.lower()) == st

    def test_prohibited_stations_rejected(self):
        for prohibited in ("KDCA", "KDEN", "ZSPD"):
            with pytest.raises(ValueError, match="not in ACTIVE_11_STATIONS"):
                validate_station_universe(prohibited)

    def test_arbitrary_station_rejected(self):
        with pytest.raises(ValueError, match="not in ACTIVE_11_STATIONS"):
            validate_station_universe("KJFK")


class TestGateVerifications:
    """Test logic for acceptance gates."""

    def test_gate_3_coverage_passes_when_all_present(self):
        features = [
            DatasetItem(station=st, path=Path(f"/tmp/{st}_{yr}.parquet"), component="features", year=yr)
            for st in ACTIVE_11_STATIONS
            for yr in range(2000, 2027)
        ]
        assert len(features) == EXPECTED_FEATURE_FILES
        res = verify_gate_3_coverage(features)
        assert res["status"] == "PASS"
        assert res["missing_station_years_count"] == 0

    def test_gate_3_coverage_fails_when_missing(self):
        features = [
            DatasetItem(station=st, path=Path(f"/tmp/{st}_{yr}.parquet"), component="features", year=yr)
            for st in ACTIVE_11_STATIONS
            for yr in range(2000, 2026)
        ]
        res = verify_gate_3_coverage(features)
        assert res["status"] == "FAIL"
        assert res["missing_station_years_count"] == len(ACTIVE_11_STATIONS)

    def test_gate_4_oos_discipline(self, tmp_path):
        floors = []
        for st in ACTIVE_11_STATIONS:
            p = tmp_path / f"{st}_climate_floor.parquet"
            # 732 rows = 366 max + 366 min
            df = pd.DataFrame({"target_type": ["max"] * 366 + ["min"] * 366, "day_of_year": list(range(1, 367)) * 2})
            df.to_parquet(p)
            floors.append(DatasetItem(station=st, path=p, component="climate_floor", year=None))
        res = verify_gate_4_oos_discipline(floors)
        assert res["status"] == "PASS"
        assert res["oos_leakage_detected"] is False

    def test_gate_5_ledger_clearance(self):
        res = verify_gate_5_ledger_clearance()
        assert res["status"] == "PASS"
        assert res["unresolved_count"] == 0
        assert res["total_items"] == 8
        assert "PENDING-01" in res["ledger_details"]
        assert res["ledger_details"]["PENDING-01"] == "ATTACHED_PHASE2"

    def test_gate_6_forecast_features(self, tmp_path):
        gefs = []
        for st in ACTIVE_11_STATIONS:
            for yr in range(2000, 2020):
                p = tmp_path / f"{st}_{yr}.parquet"
                df = pd.DataFrame({
                    "init_date": ["2010-01-01"],
                    "target_date": ["2010-01-02"],
                    "station": [st],
                    "variable": ["tmax_2m"],
                    "member": ["c00"],
                    "lead_hours": [24],
                    "value_K": [280.0],
                })
                df.to_parquet(p)
                gefs.append(DatasetItem(station=st, path=p, component="gefs_factors", year=yr))
        assert len(gefs) == EXPECTED_GEFS_FILES
        res = verify_gate_6_forecast_features(gefs)
        assert res["status"] == "PASS"
        assert res["v1_to_v13_gates_passed"] == 13


class TestAssemblyAndManifest:
    """Test directory assembly and manifest serialization."""

    def test_assembly_and_manifest(self, tmp_path):
        src_dir = tmp_path / "src"
        out_dir = tmp_path / "out"
        src_dir.mkdir()
        out_dir.mkdir()

        # Create minimal dummy files
        dummy_df = pd.DataFrame({"col": [1, 2, 3]})
        dummy_pq = src_dir / "test.parquet"
        dummy_df.to_parquet(dummy_pq)

        features = [DatasetItem(station="KORD", path=dummy_pq, component="features", year=2020)]
        floors = [DatasetItem(station="KORD", path=dummy_pq, component="climate_floor", year=None)]
        gefs = [DatasetItem(station="KORD", path=dummy_pq, component="gefs_factors", year=2010)]

        all_items = features + floors + gefs
        assemble_dataset_directory(out_dir, all_items)
        assert (out_dir / "features" / "KORD" / "2020.parquet").is_symlink()
        assert (out_dir / "climate_floor" / "KORD_climate_floor.parquet").is_symlink()
        assert (out_dir / "gefs_factors" / "KORD" / "2010.parquet").is_symlink()

        gates = {"dummy_gate": {"status": "PASS"}}
        manifest = generate_manifest(out_dir, features, floors, gefs, gates)

        assert manifest["version"] == DATASET_VERSION
        assert manifest["total_files"] == 3
        assert manifest["total_rows"] == 9
        assert (out_dir / "manifest.json").exists()

        with open(out_dir / "manifest.json", "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["total_files"] == 3
        rel_key = "features/KORD/2020.parquet"
        assert rel_key in loaded["files"]
        assert loaded["files"][rel_key]["sha256"] == compute_file_sha256(dummy_pq)
        # Check provenance quadruple
        entry = loaded["files"][rel_key]
        assert "timestamp" in entry
        assert "git_commit_sha" in entry
        assert "source_path" in entry
        assert "sha256" in entry
