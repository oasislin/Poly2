"""
Unit, Contract, and Quality Gate Tests for IEM Adapter (Phase 1.5 Task 02).
"""

import gzip
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import requests

from src.data_processing.constants import ACTIVE_11_STATIONS, STATION_METADATA
from src.pipeline.iem_adapter import (
    IemAdapter,
    IemAdapterConfig,
    compute_file_sha256,
    get_git_commit_sha,
    parse_metar_dry_bulb,
    parse_metar_extreme_remarks,
)


MOCK_IEM_CSV_KORD = """station,valid,tmpc,tmpf,dwpc,metar
KORD,2024-06-01 06:51,18.00,64.40,11.00,KORD 010651Z 02005KT 10SM CLR 18/11 A2994 RMK AO2 SLP136 T01830111
KORD,2024-06-01 09:51,17.00,62.60,11.00,KORD 010951Z 01005KT 10SM CLR 17/11 A2995 RMK AO2 SLP139 T01720111
KORD,2024-06-01 12:51,20.00,68.00,12.00,KORD 011251Z 04008KT 10SM CLR 20/12 A2992 RMK AO2 SLP130 T02000122
KORD,2024-06-01 15:51,25.00,77.00,13.00,KORD 011551Z 08008KT 10SM FEW040 25/13 A2997 RMK AO2 SLP144 10256 20167 T02560133
KORD,2024-06-01 18:51,28.00,82.40,14.00,KORD 011851Z 11010KT 10SM FEW050 28/14 A2995 RMK AO2 SLP138 402890167 T02890139
KORD,2024-06-01 21:51,26.00,78.80,13.00,KORD 012151Z 10008KT 10SM CLR 26/13 A2996 RMK AO2 SLP135 T02610133
"""

MOCK_IEM_CSV_DEGRADED = """station,valid,tmpc,tmpf,dwpc,metar
KORD,2024-06-01 06:51,18.00,64.40,11.00,KORD 010651Z 02005KT 10SM CLR 18/11 A2994 RMK AO2
KORD,2024-06-01 12:51,20.00,68.00,12.00,KORD 011251Z 04008KT 10SM CLR 20/12 A2992 RMK AO2
"""


class TestMetarParsingContract:
    """Contract tests for METAR text decoding with exact 0.1°C precision."""

    def test_parse_dry_bulb_temperatures(self):
        assert parse_metar_dry_bulb("KORD 010051Z 20/12 A2992") == 20.0
        assert parse_metar_dry_bulb("METAR KORD 010051Z M05/M10 A2992") == -5.0
        assert parse_metar_dry_bulb("KORD 010051Z 00/M02 A2992") == 0.0
        assert parse_metar_dry_bulb("INVALID_MSG_WITHOUT_TEMP") is None

    def test_parse_t_group_high_precision(self):
        # T02890139 -> Temp +28.9°C, Dewpoint +13.9°C
        rem = parse_metar_extreme_remarks("RMK AO2 T02890139")
        assert rem["temp_high_res"] == 28.9
        assert rem["dewpoint_high_res"] == 13.9

        # T10561122 -> Temp -5.6°C, Dewpoint -12.2°C
        rem_neg = parse_metar_extreme_remarks("RMK AO2 T10561122")
        assert rem_neg["temp_high_res"] == -5.6
        assert rem_neg["dewpoint_high_res"] == -12.2

        # T00000000 -> Temp 0.0°C, Dewpoint 0.0°C (must not be None or falsy)
        rem_zero = parse_metar_extreme_remarks("RMK AO2 T00000000")
        assert rem_zero["temp_high_res"] == 0.0
        assert rem_zero["dewpoint_high_res"] == 0.0

    def test_parse_6h_and_24h_extremes(self):
        rem = parse_metar_extreme_remarks("RMK AO2 10256 20167 402890167")
        assert rem["temp_6h_max"] == 25.6
        assert rem["temp_6h_min"] == 16.7
        assert rem["temp_24h_max"] == 28.9
        assert rem["temp_24h_min"] == 16.7


class TestStationUniverseEnforcement:
    """Verify that only 11 active US trading stations are admitted."""

    def test_active_11_stations_membership(self):
        expected_11 = {
            "KORD", "KLGA", "KATL", "KDAL", "KSEA",
            "KLAX", "KHOU", "KMIA", "KSFO", "KBKF", "KAUS"
        }
        assert set(ACTIVE_11_STATIONS) == expected_11

    def test_rejected_stations_raise_error(self, tmp_path):
        adapter = IemAdapter(config=IemAdapterConfig(storage_dir=tmp_path))
        for banned in ["KDCA", "ZSPD", "EGLC", "KDEN", "UNKNOWN"]:
            with pytest.raises(ValueError, match="not in active 11 stations"):
                adapter.fetch_station_year(banned, 2024)


class TestGate1TGroupCoverage:
    """Verify Quality Gate 1: daily T-group coverage >= 99% or flagged as degraded."""

    def test_gate1_passes_when_high_coverage(self, tmp_path):
        adapter = IemAdapter(config=IemAdapterConfig(storage_dir=tmp_path))
        records = adapter.parse_csv_observations(MOCK_IEM_CSV_KORD, station="KORD")
        assert len(records) == 6
        daily_df, pass_gate = adapter.evaluate_gate1_coverage(records, station="KORD")

        assert pass_gate is True
        assert len(daily_df) == 1
        day_row = daily_df.iloc[0]
        assert day_row["t_group_coverage_pct"] == 100.0
        assert day_row["quality_flag"] == "nominal"
        assert day_row["gate_1_passed"]
        # Check temperature values: max is 28.9°C -> 84.02°F
        assert day_row["daily_tmax_c"] == 28.9
        assert pytest.approx(day_row["daily_tmax_f"], 0.01) == 84.02

    def test_gate1_fails_and_tags_degraded_when_missing_t_group(self, tmp_path):
        adapter = IemAdapter(config=IemAdapterConfig(storage_dir=tmp_path))
        records = adapter.parse_csv_observations(MOCK_IEM_CSV_DEGRADED, station="KORD")
        daily_df, pass_gate = adapter.evaluate_gate1_coverage(records, station="KORD")

        assert pass_gate is False
        assert len(daily_df) == 1
        day_row = daily_df.iloc[0]
        assert day_row["t_group_coverage_pct"] == 0.0
        assert day_row["quality_flag"] == "degraded"
        assert not day_row["gate_1_passed"]


class TestGate2DualSourceConsistency:
    """Verify Quality Gate 2: comparison against NWS WRH daily extreme reference."""

    def test_gate2_passes_within_threshold(self, tmp_path):
        adapter = IemAdapter(config=IemAdapterConfig(storage_dir=tmp_path, reports_dir=tmp_path))
        # Daily summary: TMAX = 84.02°F
        daily_df = pd.DataFrame([{
            "station": "KORD",
            "local_date": "2024-06-01",
            "daily_tmax_f": 84.02,
            "daily_tmin_f": 62.96,
            "quality_flag": "nominal",
        }])

        # WRH reference: 84.10°F (diff = 0.08°F <= 0.2°F)
        wrh_reference = pd.DataFrame([{
            "station": "KORD",
            "local_date": "2024-06-01",
            "wrh_tmax_f": 84.10,
            "wrh_tmin_f": 63.00,
        }])

        discrepancies = adapter.evaluate_gate2_wrh_consistency(daily_df, wrh_reference)
        assert len(discrepancies) == 0

    def test_gate2_alerts_and_logs_when_exceeding_threshold(self, tmp_path):
        adapter = IemAdapter(config=IemAdapterConfig(storage_dir=tmp_path, reports_dir=tmp_path))
        daily_df = pd.DataFrame([{
            "station": "KORD",
            "local_date": "2024-06-01",
            "daily_tmax_f": 84.02,
            "daily_tmin_f": 62.96,
            "quality_flag": "nominal",
        }])

        # WRH reference: 84.50°F (diff = 0.48°F > 0.2°F)
        wrh_reference = pd.DataFrame([{
            "station": "KORD",
            "local_date": "2024-06-01",
            "wrh_tmax_f": 84.50,
            "wrh_tmin_f": 62.96,
        }])

        discrepancies = adapter.evaluate_gate2_wrh_consistency(daily_df, wrh_reference)
        assert len(discrepancies) == 1
        disc = discrepancies[0]
        assert disc["station"] == "KORD"
        assert disc["local_date"] == "2024-06-01"
        assert disc["variable"] == "TMAX"
        assert pytest.approx(disc["delta_f"], 0.01) == 0.48
        assert disc["severity"] == "WARNING"

        # Check that audit log file was created
        log_file = tmp_path / "dual_source_discrepancies.jsonl"
        assert log_file.exists()
        with open(log_file, "r") as f:
            lines = f.readlines()
            assert len(lines) >= 1
            payload = json.loads(lines[-1])
            assert payload["delta_f"] > 0.2
            assert "iem_raw_metars" in payload

    def test_gate2_skips_cleanly_when_no_wrh(self, tmp_path):
        adapter = IemAdapter(config=IemAdapterConfig(storage_dir=tmp_path))
        daily_df = pd.DataFrame([{
            "station": "KORD",
            "local_date": "2005-06-01",
            "daily_tmax_f": 80.0,
            "daily_tmin_f": 60.0,
            "quality_flag": "nominal",
        }])
        discrepancies = adapter.evaluate_gate2_wrh_consistency(daily_df, wrh_reference=None)
        assert len(discrepancies) == 0

    def test_context_manager_closes_session(self, tmp_path):
        with IemAdapter(config=IemAdapterConfig(storage_dir=tmp_path)) as adapter:
            assert adapter.session is not None
        # Verify close method called without error
        adapter.close()

    def test_extract_calendar_day_max_local_time(self):
        from src.data_acquisition.observation_adapter import ObservationRecord
        adapter = IemAdapter()
        # 2024-06-01 04:00 UTC = 2024-05-31 23:00 CDT (Day 1: 20°C)
        # 2024-06-01 12:00 UTC = 2024-06-01 07:00 CDT (Day 2: 28°C)
        records = [
            ObservationRecord(
                timestamp=datetime(2024, 6, 1, 4, 0, tzinfo=timezone.utc),
                temp_c=20.0,
            ),
            ObservationRecord(
                timestamp=datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc),
                temp_c=28.0,
            ),
        ]
        peak = adapter.extract_calendar_day_max(records, timezone_str="America/Chicago")
        assert peak == 28.0



class TestGate3ProvenanceAndPersistence:
    """Verify Quality Gate 3: Provenance 4-tuple and manifest persistence."""

    @patch("src.pipeline.iem_adapter.IemAdapter._execute_http_download")
    def test_full_pipeline_persistence_and_manifest(self, mock_download, tmp_path):
        mock_download.return_value = MOCK_IEM_CSV_KORD
        adapter = IemAdapter(config=IemAdapterConfig(storage_dir=tmp_path))

        artifact = adapter.fetch_station_year("KORD", 2024)

        # 1. Check parquet file exists
        parquet_path = tmp_path / "KORD" / "2024.parquet"
        assert parquet_path.exists()
        df = pd.read_parquet(parquet_path)
        assert len(df) == 6
        assert "t_group_parsed" in df.columns
        assert "quality_flag" in df.columns
        assert "temp_c" in df.columns
        assert "temp_f" in df.columns
        assert "usage" in df.columns
        assert (df["usage"] == "training-ready").all()
        assert (df["vintage"] == "era2").all()

        # 2. Check raw csv.gz archive exists
        raw_archive = tmp_path / "KORD" / "2024.csv.gz"
        assert raw_archive.exists()
        with gzip.open(raw_archive, "rt") as f:
            content = f.read()
            assert "station,valid,tmpc,tmpf,dwpc,metar" in content

        # 3. Check manifest.json has provenance 4-tuple
        manifest_path = tmp_path / "manifest.json"
        assert manifest_path.exists()
        with open(manifest_path, "r") as f:
            meta = json.load(f)

        assert meta["version"] == "1.0"
        assert "timestamp" in meta
        assert "git_commit_sha" in meta
        file_entry = meta["files"]["KORD/2024.parquet"]
        assert "sha256" in file_entry
        assert len(file_entry["sha256"]) == 64
        assert "source_url" in file_entry
        assert "mesonet.agron.iastate.edu" in file_entry["source_url"]
        assert file_entry["row_count"] == 6
        assert file_entry["quality_flag"] == "nominal"

    @patch("src.pipeline.iem_adapter.IemAdapter._execute_http_download")
    def test_resumption_skips_existing_files_and_re_downloads_on_hash_mismatch(self, mock_download, tmp_path):
        mock_download.return_value = MOCK_IEM_CSV_KORD
        adapter = IemAdapter(config=IemAdapterConfig(storage_dir=tmp_path))

        # First run: downloads and creates files
        adapter.fetch_station_year("KORD", 2024)
        assert mock_download.call_count == 1

        # Second run without force: skips download (validated by sha256)
        adapter.fetch_station_year("KORD", 2024, force=False)
        assert mock_download.call_count == 1  # Not incremented!

        # Tamper with the parquet file to simulate corruption
        parquet_path = tmp_path / "KORD" / "2024.parquet"
        with open(parquet_path, "ab") as f:
            f.write(b"corrupt")

        # Third run: hash mismatch triggers re-download even without force
        adapter.fetch_station_year("KORD", 2024, force=False)
        assert mock_download.call_count == 2



class TestNetworkResilienceAndRetry:
    """Test retry on HTTP 502/503/timeout with exponential backoff."""

    @patch("src.pipeline.iem_adapter.requests.Session.get")
    def test_retry_on_server_error(self, mock_get, tmp_path):
        resp_err = MagicMock()
        resp_err.status_code = 503
        resp_err.raise_for_status.side_effect = requests.HTTPError("Service Unavailable")

        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.text = MOCK_IEM_CSV_KORD

        mock_get.side_effect = [resp_err, resp_ok]

        config = IemAdapterConfig(
            storage_dir=tmp_path,
            max_retries=3,
            backoff_base=0.01,
            rate_limit_delay=0.0,
        )
        adapter = IemAdapter(config=config)
        records = adapter.parse_csv_observations(
            adapter._execute_http_download(adapter._build_query_params("KORD", 2024)),
            station="KORD",
        )
        assert len(records) == 6
        assert mock_get.call_count == 2


@pytest.mark.skipif(
    os.getenv("RUN_NETWORK_TESTS") != "1",
    reason="Requires RUN_NETWORK_TESTS=1 to run live IEM ASOS API smoke test",
)
def test_live_network_iem_kord(tmp_path):
    """Live network smoke test against real IEM ASOS API for KORD (anchor station)."""
    config = IemAdapterConfig(storage_dir=tmp_path, rate_limit_delay=1.0)
    adapter = IemAdapter(config=config)

    # Fetch 2024 data (or recent day)
    artifact = adapter.fetch_station_year(
        station="KORD",
        year=2024,
        start_month=6,
        start_day=1,
        end_month=6,
        end_day=2,
    )
    assert artifact.parquet_path.exists()
    df = pd.read_parquet(artifact.parquet_path)
    assert len(df) > 0

    # Ensure T-group parsed
    t_parsed_count = df["t_group_parsed"].sum()
    assert t_parsed_count / len(df) >= 0.95  # Live KORD should have very high T-group coverage
    assert artifact.manifest_entry["sha256"] == compute_file_sha256(artifact.parquet_path)
