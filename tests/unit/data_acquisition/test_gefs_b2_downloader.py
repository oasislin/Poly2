#!/usr/bin/env python3
"""Unit tests for GEFS B2 batch downloader and dashboard logging compatibility."""

from datetime import datetime
from pathlib import Path
import re
import struct
import tempfile
from unittest.mock import MagicMock
import pytest

from scripts.dashboard import _parse_latest_progress, _extract_metadata_header
from scripts.download_gefs_b2 import (
    format_progress_line,
    _format_heartbeat_progress,
    load_state,
    update_state,
    is_valid_grib2_slice,
    download_single_slice,
    _download_slice_with_backoff,
    _download_day_with_self_healing,
    SliceResult,
    SliceDownloadTask,
    B2_SHORT_WINDOW,
    B2_LONG_WINDOW,
)
from src.data_acquisition.gefs_fetcher import GEFSFetcher, _send_with_retry


def _make_dummy_grib2(msg_count: int, payload_len: int = 650_000, embed_7777: bool = False) -> bytes:
    chunks = []
    for _ in range(msg_count):
        payload = b"A" * (payload_len // 2) + (b"7777" if embed_7777 else b"XXXX") + b"B" * (payload_len // 2)
        tot = 16 + len(payload) + 4
        header = b"GRIB\x00\x00\x00\x02" + struct.pack(">Q", tot)
        chunks.append(header + payload + b"7777")
    return b"".join(chunks)


class TestGEFSB2DownloaderAndDashboard:
    """Contract tests for B2 downloader and dashboard parsing."""

    def test_b2_fxx_windows(self):
        assert B2_SHORT_WINDOW == [12, 18]
        assert B2_LONG_WINDOW == [60, 66, 72, 78]

    def test_b2_search_regex_patterns(self):
        fetcher = GEFSFetcher()
        search_short = fetcher._build_search("tmax_2m", B2_SHORT_WINDOW)
        assert "6-12 hour max fcst" in search_short
        assert "12-18 hour max fcst" in search_short

        search_long = fetcher._build_search("tmin_2m", B2_LONG_WINDOW)
        assert "54-60 hour min fcst" in search_long
        assert "60-66 hour min fcst" in search_long
        assert "66-72 hour min fcst" in search_long
        assert "72-78 hour min fcst" in search_long

    def test_dashboard_can_parse_progress_line(self):
        results = [
            SliceResult(
                slice_idx=1, member_label="c00", var_name="tmax",
                window_label="12-18h", subset_hash="89efe92a",
                size_bytes=2_200_000, speed_kbps=350, is_new=True
            ),
            SliceResult(
                slice_idx=2, member_label="p01", var_name="tmin",
                window_label="60-78h", subset_hash="89efc49f",
                size_bytes=2_250_000, speed_kbps=410, is_new=False
            ),
        ]
        line = format_progress_line(
            station_label="ALL",
            target_dt_str="2000-01-01",
            day_idx=1,
            total_days=365,
            elapsed_sec=14,
            slice_results=results,
        )
        assert "[PROGRESS] ALL 2000-01-01 (1/365 0.3%) [已耗时 14s] |" in line
        assert "#01_c00[tmax:12-18h:89efe92a]" in line

        parsed = _parse_latest_progress(line)
        assert parsed is not None
        assert parsed["station"] == "ALL"
        assert parsed["target_date"] == "2000-01-01"
        assert parsed["elapsed_seconds"] == 14
        assert "#01_c00" in parsed["members"]
        assert parsed["members"]["#01_c00"]["var"] == "tmax"
        assert parsed["members"]["#01_c00"]["window"] == "12-18h"
        assert parsed["members"]["#01_c00"]["subset"] == "89efe92a"
        assert parsed["members"]["#01_c00"]["speed_kb"] == 350
        assert parsed["members"]["#02_p01"]["speed_kb"] == 410

    def test_heartbeat_progress_formatting(self):
        from scripts.download_gefs_b2 import _active_slices, _active_slices_lock
        with _active_slices_lock:
            _active_slices.clear()

        # 1. Empty progress test
        line_idle = _format_heartbeat_progress("2000-01-01", 1, 365, 10)
        assert "[PROGRESS] B2_UNION 2000-01-01" in line_idle
        assert "Connecting" in line_idle

        # 2. Populated progress test
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(b"X" * 1_000_000)
            tmp.flush()
            with _active_slices_lock:
                _active_slices["#01_c00"] = {
                    "idx": 1,
                    "mem": "c00",
                    "var": "tmax",
                    "win": "12-18h",
                    "subset": "89efe92a",
                    "path": Path(tmp.name),
                    "expected_bytes": 1_460_000,
                    "start_t": 0.0,
                }
            line_active = _format_heartbeat_progress("2000-01-01", 1, 365, 15)
            with _active_slices_lock:
                _active_slices.clear()

        assert "#01_c00[tmax:12-18h:89efe92a]" in line_active

        parsed = _parse_latest_progress(line_active)
        assert parsed is not None
        assert "#01_c00" in parsed["members"]
        assert parsed["members"]["#01_c00"]["subset"] == "89efe92a"

    def test_dashboard_can_parse_metadata_header(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_p = Path(tmp_dir) / "test.log"
            log_p.write_text(
                "# METADATA: pid=12345 start_year=2000 end_year=2019 stations=ALL started_at=2026-09-08T00:00:00\n"
            )
            pid, yr_range, stations = _extract_metadata_header(log_p)
            assert pid == 12345
            assert yr_range == "2000~2019 年"
            assert stations == "ALL"

    def test_state_persistence_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_p = Path(tmp_dir) / "state.csv"
            update_state(state_p, "20000101", "done")
            update_state(state_p, "20000102", "done")

            st = load_state(state_p)
            assert st.get("20000101") == "done"
            assert st.get("20000102") == "done"
            assert "20000103" not in st

    def test_is_valid_grib2_slice_checks(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            f_valid = Path(tmp_dir) / "valid_short.grib2"
            f_valid.write_bytes(_make_dummy_grib2(2, embed_7777=True))
            assert is_valid_grib2_slice(f_valid, expected_messages=2) is True
            assert is_valid_grib2_slice(f_valid, expected_messages=4) is False

            # High compression valid file: e.g. 844KB for 2 messages (~400KB/msg like 2000-01-29 p03)
            f_compressed = Path(tmp_dir) / "compressed_valid.grib2"
            f_compressed.write_bytes(_make_dummy_grib2(2, payload_len=400_000, embed_7777=True))
            assert is_valid_grib2_slice(f_compressed, expected_messages=2) is True

            f_truncated = Path(tmp_dir) / "truncated.grib2"
            # 1.5MB but truncated midway (does not end with 7777 at expected offset)
            f_truncated.write_bytes(b"GRIB\x00\x00\x00\x02" + struct.pack(">Q", 2_000_000) + b"A" * 1_500_000)
            assert is_valid_grib2_slice(f_truncated, expected_messages=2) is False

            f_missing = Path(tmp_dir) / "nonexistent.grib2"
            assert is_valid_grib2_slice(f_missing, expected_messages=2) is False

            f_empty = Path(tmp_dir) / "empty.grib2"
            f_empty.write_bytes(b"")
            assert is_valid_grib2_slice(f_empty, expected_messages=2) is False

    def test_download_single_slice_skips_existing_valid(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            f = Path(tmp_dir) / "slice.grib2"
            f.write_bytes(_make_dummy_grib2(2, embed_7777=True))

            mock_h = MagicMock()
            mock_h.member = 0
            mock_h.variable_level = "tmax_2m"
            meta = {"idx": 1, "mem": "c00", "var": "tmax", "win": "12-18h", "subset": "89efe92a"}

            res = download_single_slice(mock_h, "pattern", f, expected_messages=2, meta=meta, max_retries=3)
            assert res.is_new is False
            assert res.size_bytes == f.stat().st_size
            assert res.subset_hash == "89efe92a"
            mock_h.download.assert_not_called()

    def test_download_single_slice_redownloads_truncated_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            f = Path(tmp_dir) / "slice.grib2"
            f.write_bytes(b"GRIB\x00\x00\x00\x02" + struct.pack(">Q", 2_000_000) + b"A" * 1_500_000)

            mock_h = MagicMock()
            mock_h.member = 0
            mock_h.variable_level = "tmax_2m"
            meta = {"idx": 1, "mem": "c00", "var": "tmax", "win": "12-18h", "subset": "89efe92a"}

            def fake_download(*args, **kwargs):
                f.write_bytes(_make_dummy_grib2(2, embed_7777=True))

            mock_h.download.side_effect = fake_download
            res = download_single_slice(mock_h, "pattern", f, expected_messages=2, meta=meta, max_retries=3)
            assert res.is_new is True
            assert res.subset_hash == "89efe92a"
            mock_h.download.assert_called_once()

    def test_send_with_retry_recovers_from_transient_ssl_error(self, monkeypatch):
        import requests
        calls = 0

        def fake_orig_send(session, request, **kwargs):
            nonlocal calls
            calls += 1
            if calls < 2:
                raise requests.exceptions.SSLError("Mock SSL: UNEXPECTED_EOF_WHILE_READING")
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            return mock_resp

        monkeypatch.setattr("src.data_acquisition.gefs_fetcher._orig_session_send", fake_orig_send)
        session = requests.Session()
        req = requests.Request("HEAD", "https://mock.s3.amazonaws.com").prepare()
        resp = _send_with_retry(session, req, {}, max_retries=3)
        assert resp.status_code == 200
        assert calls == 2

    def test_download_slice_with_backoff_retries_herbie_init_failure(self, monkeypatch, tmp_path):
        from unittest.mock import patch
        import requests

        f = tmp_path / "slice.grib2"
        f.write_bytes(_make_dummy_grib2(2, embed_7777=True))

        herbie_inits = 0

        class MockFailingHerbie:
            def __init__(self, *args, **kwargs):
                nonlocal herbie_inits
                herbie_inits += 1
                if herbie_inits < 2:
                    raise requests.exceptions.SSLError("Mock TLS EOF on Herbie init")

            def get_localFilePath(self, search):
                return f

            def download(self, search=None, overwrite=True):
                pass

        monkeypatch.setattr("scripts.download_gefs_b2.Herbie", MockFailingHerbie)

        mock_fetcher = MagicMock()
        mock_fetcher.build_search.return_value = "search_pattern"

        task = SliceDownloadTask(1, datetime(2000, 1, 1), "tmax_2m", 0, [12, 18], str(tmp_path), 3, mock_fetcher)
        meta = {"idx": 1, "mem": "c00", "var": "tmax", "win": "12-18h", "subset": ""}

        res = _download_slice_with_backoff(task, meta, "tmax", "c00", "12-18h")
        assert res.slice_idx == 1
        assert herbie_inits == 2
