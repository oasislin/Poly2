#!/usr/bin/env python3
"""Contract and unit tests for GEFS Parquet persistence, Manifest, and Gate V2/V5/V6 validation.

Implements Gate V2 (coverage assertion), Gate V5/V6 (physical bounds & tmax>=tmin),
and C2 (Parquet partitioning {station}/{year}.parquet and Manifest provenance).
"""

from datetime import date
import json
import os
from pathlib import Path
import tempfile
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from src.pipeline.gefs_extract import (
    compute_file_sha256,
    extract_day_to_dataframe,
    extract_station_year,
    extract_batch,
    get_station_coords,
    save_station_year_parquet,
    validate_physical_bounds,
    validate_coverage_dimensions,
    assert_golden_samples_gate,
    merge_datasets_defensively,
    ManifestManager,
    ExtractionArtifact,
    DEFAULT_12_STATIONS,
)

COLD_STORAGE_ROOT = Path(os.getenv("GEFS_DATA_ROOT", "/Volumes/EricSSD/Poly RawData/gefs_reforecast"))
EXTERNAL_SSD_DAY_20040101 = COLD_STORAGE_ROOT / "20040101"


class TestGateV5V6PhysicalBounds:
    """Gate V5 / V6: Verify temperature interval [-60, +60] C (213.15K - 333.15K), NaN, Inf, and TMAX >= TMIN."""

    def test_valid_temperatures_pass(self):
        df = pd.DataFrame({
            "init_date": ["2004-01-01", "2004-01-01"],
            "station": ["KORD", "KORD"],
            "member": ["c00", "c00"],
            "lead_hours": [24, 24],
            "variable": ["tmax", "tmin"],
            "value_K": [280.0, 275.0],
        })
        validate_physical_bounds(df)

    def test_temperature_below_lower_bound_raises(self):
        df = pd.DataFrame({
            "value_K": [212.0, 280.0],
        })
        with pytest.raises(ValueError, match="Gate V6 Violation.*outside"):
            validate_physical_bounds(df)

    def test_temperature_above_upper_bound_raises(self):
        df = pd.DataFrame({
            "value_K": [334.0, 280.0],
        })
        with pytest.raises(ValueError, match="Gate V6 Violation.*outside"):
            validate_physical_bounds(df)

    def test_nan_raises_error(self):
        df = pd.DataFrame({"value_K": [np.nan, 280.0]})
        with pytest.raises(ValueError, match="Gate V6 Violation.*NaN or Inf"):
            validate_physical_bounds(df)

    def test_inf_raises_error(self):
        df = pd.DataFrame({"value_K": [np.inf, 280.0]})
        with pytest.raises(ValueError, match="Gate V6 Violation.*NaN or Inf"):
            validate_physical_bounds(df)

    def test_tmax_lower_than_tmin_raises_error(self):
        df = pd.DataFrame({
            "init_date": ["2004-01-01", "2004-01-01"],
            "station": ["KORD", "KORD"],
            "member": ["c00", "c00"],
            "lead_hours": [24, 24],
            "variable": ["tmax", "tmin"],
            "value_K": [270.0, 275.0],  # tmax < tmin
        })
        with pytest.raises(ValueError, match="Gate V6 Violation: TMAX < TMIN"):
            validate_physical_bounds(df)


class TestGateV2CoverageDimensions:
    """Gate V2: Dimension completeness validation."""

    def test_full_dimensions_pass(self):
        stations = ["KORD", "KLGA"]
        members = ["c00", "p01"]
        variables = ["tmax", "tmin"]
        fxx_steps = [24, 48]

        records = []
        for s in stations:
            for m in members:
                for v in variables:
                    for f in fxx_steps:
                        records.append({
                            "station": s, "member": m, "variable": v, "lead_hours": f,
                            "value_K": 280.0
                        })
        df = pd.DataFrame(records)
        res = validate_coverage_dimensions(
            df,
            expected_stations=stations,
            expected_members=members,
            expected_vars=variables,
            expected_fxx=fxx_steps,
        )
        assert res["stations"] == 2
        assert res["members"] == 2
        assert res["variables"] == 2
        assert res["lead_hours"] == [24, 48]

    def test_missing_station_raises(self):
        df = pd.DataFrame({
            "station": ["KORD"], "member": ["c00"], "variable": ["tmax"], "lead_hours": [24],
            "value_K": [280.0]
        })
        with pytest.raises(ValueError, match="Missing stations.*KLGA"):
            validate_coverage_dimensions(df, expected_stations=["KORD", "KLGA"], expected_members=["c00"])

    def test_missing_member_raises(self):
        df = pd.DataFrame({
            "station": ["KORD"], "member": ["c00"], "variable": ["tmax"], "lead_hours": [24],
            "value_K": [280.0]
        })
        with pytest.raises(ValueError, match="Missing members.*p01"):
            validate_coverage_dimensions(df, expected_stations=["KORD"], expected_members=["c00", "p01"])


class TestParquetPartitioningAndManifest:
    """C2: Parquet schema, partitioning {station}/{year}.parquet, and ManifestManager."""

    def test_save_station_year_parquet_layout_and_types(self):
        df = pd.DataFrame({
            "init_date": ["2004-01-01"],
            "target_date": ["2004-01-02"],
            "station": ["KORD"],
            "variable": ["tmax"],
            "member": ["p03"],
            "lead_hours": [24],
            "value_K": [278.79],
            "vintage": ["reforecast"],
        })
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_base = Path(tmp_dir)
            art = save_station_year_parquet(df, out_base, "KORD", 2004)

            expected_rel_path = "KORD/2004.parquet"
            assert art.parquet_rel_path == expected_rel_path
            assert (out_base / expected_rel_path).exists()
            assert art.row_count == 1
            assert art.lead_hours_steps == [24]
            assert art.size_bytes > 0
            assert art.sha256 == compute_file_sha256(out_base / expected_rel_path)

            # Read back and verify types
            df_read = pd.read_parquet(out_base / expected_rel_path)
            assert list(df_read.columns) == [
                "init_date", "target_date", "station", "variable",
                "member", "lead_hours", "value_K", "vintage"
            ]
            assert df_read["value_K"].iloc[0] == pytest.approx(278.79, abs=1e-3)

    def test_manifest_manager_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_base = Path(tmp_dir)
            manifest_file = out_base / "manifest.json"
            mgr = ManifestManager(manifest_file, source_path="/dummy/path", golden_result="PASS")

            art = ExtractionArtifact(
                station="KORD",
                year=2004,
                parquet_rel_path="KORD/2004.parquet",
                size_bytes=1234,
                sha256="fake_sha256",
                row_count=100,
                lead_hours_steps=[24, 48],
            )
            mgr.record_artifact(art)
            mgr.save()

            assert manifest_file.exists()
            with open(manifest_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            assert data["version"] == "1.0"
            assert data["golden_sample_verification"] == "PASS"
            assert data["total_station_years"] == 1
            assert data["total_rows"] == 100
            assert "KORD/2004.parquet" in data["files"]
            entry = data["files"]["KORD/2004.parquet"]
            assert entry["station"] == "KORD"
            assert entry["sha256"] == "fake_sha256"

    @pytest.mark.skipif(
        not EXTERNAL_SSD_DAY_20040101.exists(),
        reason="External SSD volume /Volumes/EricSSD not mounted"
    )
    def test_extract_station_year_and_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_base = Path(tmp_dir)
            fake_input = out_base / "raw"
            fake_input.mkdir()
            (fake_input / "20040101").symlink_to(EXTERNAL_SSD_DAY_20040101)

            # 1. First run: extracts
            art1 = extract_station_year(
                input_dir=fake_input,
                out_dir=out_base,
                station="KORD",
                year=2004,
                fxx_filter={24},
                force=False,
                max_workers=2,
            )
            assert art1 is not None
            assert (out_base / "KORD" / "2004.parquet").exists()

            # 2. Second run without force: skips (idempotent)
            art2 = extract_station_year(
                input_dir=fake_input,
                out_dir=out_base,
                station="KORD",
                year=2004,
                fxx_filter={24},
                force=False,
                max_workers=2,
            )
            assert art2 is None

            # 3. Third run with force: re-extracts
            art3 = extract_station_year(
                input_dir=fake_input,
                out_dir=out_base,
                station="KORD",
                year=2004,
                fxx_filter={24},
                force=True,
                max_workers=2,
            )
            assert art3 is not None


class TestExtractBatchDryRunAndGoldenGate:
    """Contract tests for dry-run pre-scan and golden sample gate edge cases."""

    def test_golden_gate_missing_dir_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            assert_golden_samples_gate(Path("/nonexistent/path/for/gate"))

    @pytest.mark.skipif(
        not EXTERNAL_SSD_DAY_20040101.exists(),
        reason="External SSD volume /Volumes/EricSSD not mounted",
    )
    def test_dry_run_batch_does_not_write_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_base = Path(tmp_dir)
            fake_input = out_base / "raw"
            fake_input.mkdir()
            (fake_input / "20040101").symlink_to(EXTERNAL_SSD_DAY_20040101)

            res = extract_batch(
                input_dir=fake_input,
                out_dir=out_base / "out",
                stations=["chicago"],
                years=[2004],
                fxx_filter={24},
                dry_run=True,
            )
            assert res["dry_run"] is True
            assert res["stations"] == ["KORD"]
            assert res["audit_v1"]["complete_days_v1"] >= 1
            assert res["estimated_rows"] > 0
            assert not (out_base / "out").exists()


class TestMergeDatasetsDefensively:
    """Contract tests for merge_datasets_defensively (Spec line 27)."""

    def test_merge_empty_list_returns_empty_dataset(self):
        ds = merge_datasets_defensively([])
        assert isinstance(ds, xr.Dataset)
        assert len(ds.data_vars) == 0

    def test_merge_single_dataset_returns_self(self):
        ds_in = xr.Dataset({"tmax": (["x"], [1.0, 2.0])})
        ds_out = merge_datasets_defensively([ds_in])
        assert ds_out is ds_in

    def test_merge_with_overriding_attributes(self):
        ds1 = xr.Dataset(
            {"tmax": (["x"], [1.0, 2.0])},
            coords={"x": [0, 1]},
            attrs={"GRIB_edition": 2, "source": "NOAA"},
        )
        ds2 = xr.Dataset(
            {"tmin": (["x"], [0.5, 1.5])},
            coords={"x": [0, 1]},
            attrs={"GRIB_edition": 2, "source": "DifferentSource"},
        )
        merged = merge_datasets_defensively([ds1, ds2])
        assert "tmax" in merged
        assert "tmin" in merged
        assert set(merged.coords.keys()) == {"x"}



