#!/usr/bin/env python3
"""Golden sample contract tests for GEFS station feature extractor.

Implements Gate V4 (GEFS-WI-v1.1 §4, ADR-0008 D3):
Verifies zero-error reproduction of historical golden sample values
on real external SSD reforecast data (2004-01-01).
"""

import os
from pathlib import Path
import pytest
import numpy as np
import pandas as pd

from src.pipeline.gefs_extract import (
    get_station_coords,
    parse_grib_filename,
    extract_day_to_dataframe,
    resolve_station_id,
    assert_golden_samples_gate,
    DEFAULT_12_STATIONS,
)

COLD_STORAGE_ROOT = Path(os.getenv("GEFS_DATA_ROOT", "/Volumes/EricSSD/Poly RawData/gefs_reforecast"))
EXTERNAL_SSD_DAY_20040101 = COLD_STORAGE_ROOT / "20040101"


class TestResolveStationId:
    """Contract tests for station identifier and city resolution."""

    def test_resolve_icao_code(self):
        assert resolve_station_id("KORD") == "KORD"
        assert resolve_station_id("kord") == "KORD"
        assert resolve_station_id("ZSPD") == "ZSPD"

    def test_resolve_city_name(self):
        assert resolve_station_id("chicago") == "KORD"
        assert resolve_station_id("Chicago") == "KORD"
        assert resolve_station_id("shanghai") == "ZSPD"
        assert resolve_station_id("seattle") == "KSEA"

    def test_unknown_identifier_raises_key_error(self):
        with pytest.raises(KeyError, match="not found in STATION_METADATA"):
            resolve_station_id("UNKNOWN_CITY_XYZ")


class TestParseGribFilename:
    """Contract tests for filename parsing and AppleDouble shadow filtering."""

    def test_valid_reforecast_subset(self):
        fn = "subset_aaefc1fa__tmax_2m_2004010100_p03.grib2"
        meta = parse_grib_filename(fn)
        assert meta is not None
        assert meta["prefix"] == "subset_aaefc1fa"
        assert meta["variable"] == "tmax"
        assert meta["init_date"] == "2004-01-01"
        assert meta["cycle"] == 0
        assert meta["member"] == "p03"

    def test_valid_control_member(self):
        fn = "subset_89ef3872__tmin_2m_2000010100_c00.grib2"
        meta = parse_grib_filename(fn)
        assert meta is not None
        assert meta["variable"] == "tmin"
        assert meta["member"] == "c00"

    def test_reject_appledouble_shadow_file(self):
        fn = "._subset_aaefc1fa__tmax_2m_2004010100_p03.grib2"
        meta = parse_grib_filename(fn)
        assert meta is None

    def test_reject_idx_file(self):
        fn = "subset_aaefc1fa__tmax_2m_2004010100_p03.grib2.idx"
        meta = parse_grib_filename(fn)
        assert meta is None

    def test_reject_unrelated_file(self):
        fn = "random_notes.txt"
        meta = parse_grib_filename(fn)
        assert meta is None


class TestGetStationCoords:
    """Contract tests for coordinate lookup and longitude normalization."""

    def test_default_12_stations_coverage(self):
        coords = get_station_coords()
        assert len(coords) == 12
        for st in DEFAULT_12_STATIONS:
            assert st in coords
            lat, lon = coords[st]
            assert -90.0 <= lat <= 90.0
            assert 0.0 <= lon < 360.0

    def test_include_zspd(self):
        coords = get_station_coords(include_zspd=True)
        assert "ZSPD" in coords
        assert len(coords) == 13
        lat, lon = coords["ZSPD"]
        assert round(lat, 2) == 31.15
        assert round(lon, 2) == 121.80

    def test_longitude_normalization_negative_to_positive(self):
        coords = get_station_coords(["KORD"])
        lat, lon = coords["KORD"]
        assert round(lat, 2) == 41.97
        # -87.90 lon in [0, 360) is 360 - 87.90 = 272.10
        assert round(lon, 2) == 272.10


class TestGoldenSampleV4Contract:
    """Gate V4: Hard contract test on real 2004-01-01 GEFS reforecast data."""

    @pytest.mark.skipif(
        not EXTERNAL_SSD_DAY_20040101.exists(),
        reason="External SSD volume /Volumes/EricSSD not mounted or 20040101 absent"
    )
    def test_zero_error_reproduction_20040101(self):
        """Zero-error reproduction test for ZSPD and KORD on 20040101.

        Golden benchmarks:
        - ZSPD p03 (tmax_2m, 24h) = 282.53 K (historical benchmark)
        - KORD c00 (tmin_2m, 24h) = 277.31 K (nearest grid point 42.0N, 272.0E)
        - KORD p03 (tmin_2m, 24h) = 277.34 K (nearest grid point 42.0N, 272.0E)
        - KORD c00 (tmax_2m, 24h) = 278.81 K (nearest grid point 42.0N, 272.0E)
        - KORD p03 (tmax_2m, 24h) = 278.79 K (nearest grid point 42.0N, 272.0E)
        """
        station_coords = get_station_coords(stations=["KORD"], include_zspd=True)
        df = extract_day_to_dataframe(EXTERNAL_SSD_DAY_20040101, station_coords, max_workers=4)

        assert not df.empty, "Extracted dataframe should not be empty for 20040101"
        expected_cols = {"init_date", "target_date", "station", "variable", "member", "lead_hours", "value_K", "vintage"}
        assert expected_cols.issubset(df.columns)

        # 1. ZSPD Golden Sample Assertion: p03, tmax, 24h == 282.53 K (tolerance < 0.005 K per spec)
        row_zspd = df[(df["station"] == "ZSPD") & (df["member"] == "p03") & (df["variable"] == "tmax") & (df["lead_hours"] == 24)]
        assert len(row_zspd) == 1, f"Expected 1 record for ZSPD p03 tmax 24h, found {len(row_zspd)}"
        val_zspd_k = float(row_zspd["value_K"].iloc[0])
        assert abs(val_zspd_k - 282.53) < 0.005, f"ZSPD golden mismatch: got {val_zspd_k:.4f}, expected 282.53"

        # 2. KORD Golden Sample Assertions (24h, tolerance < 0.005 K per spec)
        # KORD tmin c00 (24h): ~277.31 K (nearest grid point 42.0N, 272.0E)
        row_kord_min_c00 = df[(df["station"] == "KORD") & (df["member"] == "c00") & (df["variable"] == "tmin") & (df["lead_hours"] == 24)]
        assert len(row_kord_min_c00) == 1
        assert abs(float(row_kord_min_c00["value_K"].iloc[0]) - 277.31) < 0.005

        # KORD tmin p03 (24h): ~277.335 K (nearest grid point 42.0N, 272.0E)
        row_kord_min_p03 = df[(df["station"] == "KORD") & (df["member"] == "p03") & (df["variable"] == "tmin") & (df["lead_hours"] == 24)]
        assert len(row_kord_min_p03) == 1
        assert abs(float(row_kord_min_p03["value_K"].iloc[0]) - 277.335) < 0.005

        # KORD tmax c00 (24h): ~278.81 K (nearest grid point 42.0N, 272.0E)
        row_kord_max_c00 = df[(df["station"] == "KORD") & (df["member"] == "c00") & (df["variable"] == "tmax") & (df["lead_hours"] == 24)]
        assert len(row_kord_max_c00) == 1
        assert abs(float(row_kord_max_c00["value_K"].iloc[0]) - 278.81) < 0.005

        # KORD tmax p03 (24h): ~278.79 K (nearest grid point 42.0N, 272.0E)
        row_kord_max_p03 = df[(df["station"] == "KORD") & (df["member"] == "p03") & (df["variable"] == "tmax") & (df["lead_hours"] == 24)]
        assert len(row_kord_max_p03) == 1
        assert abs(float(row_kord_max_p03["value_K"].iloc[0]) - 278.79) < 0.005
