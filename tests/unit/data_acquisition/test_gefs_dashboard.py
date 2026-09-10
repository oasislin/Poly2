"""Unit tests for GEFS Dashboard backend logic and metrics aggregation.

Validates:
1. _read_state_csv_dates: parses valid 8-digit date strings, filters non-done/corrupted lines
2. _load_b2_completed_dates: dynamic multi-year state CSV discovery and deduplication
3. _count_in_flight_slices: real-time in-flight slice counting, non-rollback boundary <= 20,
   completed_dates exclusion (anti-double-counting)
4. _extract_active_dates: worker progress parsing and stdout worker active date inference
5. scan_matrix: MatrixScanResult namedtuple, slice-first calculation (146,100 total slices),
   backward-compatibility keys (sh_cnt, den_cnt)
6. scan_recent_files & _format_file_item: mtime descending sort and formatting
"""

import time
from datetime import datetime
from pathlib import Path
import pytest

from scripts.dashboard import (
    SLICES_PER_DAY,
    COLD_STORAGE_ROOT,
    MatrixScanResult,
    _read_state_csv_dates,
    _load_b2_completed_dates,
    _count_in_flight_slices,
    _extract_active_dates,
    _format_file_item,
    scan_matrix,
    scan_recent_files,
)


class TestGEFSDashboardStateLoading:
    """Test state CSV loading, date extraction and multi-file discovery."""

    def test_read_state_csv_dates_filters_correctly(self, tmp_path):
        state_csv = tmp_path / "gefs_b2_download_state_2010.csv"
        state_csv.write_text(
            "# comment header\n"
            "20100101,done,2026-09-08T01:00:00\n"
            "20100102,failed,2026-09-08T01:05:00\n"
            "20100103,done,2026-09-08T01:10:00\n"
            "invalid_date,done,2026-09-08T01:15:00\n"
            "20100104,pending\n"
            "20100105,done\n"
            "\n"
        )
        dates = _read_state_csv_dates(state_csv)
        assert dates == ["20100101", "20100103", "20100105"]

    def test_read_state_csv_dates_nonexistent_file(self, tmp_path):
        nonexistent = tmp_path / "does_not_exist.csv"
        assert _read_state_csv_dates(nonexistent) == []

    def test_load_b2_completed_dates_aggregates_multiple_csvs(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "gefs_b2_download_state_2000.csv").write_text("20000101,done\n20000102,done\n")
        (data_dir / "gefs_b2_download_state_2010.csv").write_text("20100101,done\n20000102,done\n")
        (data_dir / "other.csv").write_text("19990101,done\n")  # should be ignored

        completed = _load_b2_completed_dates(data_dir)
        assert completed == {"20000101", "20000102", "20100101"}


class TestGEFSInFlightSliceCounting:
    """Test in-flight slice counting on disk and boundary condition handling."""

    def test_count_in_flight_slices_boundary_twenty_and_double_count_guard(self, tmp_path):
        storage_root = tmp_path / "storage"
        storage_root.mkdir()

        # Date 1: 5 slices downloaded, not in completed_dates
        d1 = storage_root / "20100101"
        d1.mkdir()
        for i in range(5):
            (d1 / f"slice_{i}.grib2").write_bytes(b"data")
        (d1 / "slice_0.idx").write_bytes(b"index")  # idx should be ignored
        (d1 / "._slice_1.grib2").write_bytes(b"shadow")  # mac shadow should be ignored

        # Date 2: 20 slices downloaded, not yet flushed to CSV (boundary test: must not rollback!)
        d2 = storage_root / "20100102"
        d2.mkdir()
        for i in range(20):
            (d2 / f"slice_{i}.grib2").write_bytes(b"data")

        # Date 3: 20 slices downloaded, but ALREADY in completed_dates (must not double count!)
        d3 = storage_root / "20100103"
        d3.mkdir()
        for i in range(20):
            (d3 / f"slice_{i}.grib2").write_bytes(b"data")

        completed_dates = {"20100103"}
        active_dates = {"20100101", "20100102", "20100103"}

        in_flight = _count_in_flight_slices(active_dates, completed_dates, storage_root)
        # 20100101 contributes 5 slices, 20100102 contributes 20 slices, 20100103 contributes 0
        assert in_flight == {"2010": 25}

    def test_count_in_flight_caps_at_max_slices_per_day(self, tmp_path):
        storage_root = tmp_path / "storage"
        d = storage_root / "20100101"
        d.mkdir(parents=True)
        for i in range(25):  # more than SLICES_PER_DAY
            (d / f"slice_{i}.grib2").write_bytes(b"data")

        in_flight = _count_in_flight_slices({"20100101"}, set(), storage_root)
        assert in_flight == {"2010": SLICES_PER_DAY}


class TestGEFSActiveDatesExtraction:
    """Test active dates extraction from worker logs and stdout fallback."""

    def test_extract_active_dates_from_workers_with_progress(self):
        workers = [
            {
                "is_alive": True,
                "latest_progress": {"target_date": "2010-01-05"},
                "year_range": "2010 年",
            },
            {
                "is_alive": True,
                "latest_progress": {"target_date": "20120110"},
                "year_range": "2012 年",
            },
            {
                "is_alive": False,
                "latest_progress": {"target_date": "20140101"},
                "year_range": "2014 年",
            },
        ]
        dates = _extract_active_dates(workers)
        assert dates == {"20100105", "20120110"}

    def test_extract_active_dates_stdout_worker_fallback(self):
        workers = [
            {
                "is_alive": True,
                "latest_progress": None,
                "year_range": "2010 年",
            },
            {
                "is_alive": True,
                "latest_progress": None,
                "year_range": "2011~2011 年",
            },
        ]
        completed = {"20100101", "20100102", "20100103"}  # 2010 completed up to 01-03
        dates = _extract_active_dates(workers, completed)
        # 2010 should deduce 20100104; 2011 has no completed dates so deduces 20110101
        assert "20100104" in dates
        assert "20110101" in dates


class TestGEFSScanMatrix:
    """Test matrix calculations, namedtuple interface, and backward compatibility."""

    def test_scan_matrix_totals_and_unpacking(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # 1 day completed in 2000 (leap: 366 days = 7320 slices)
        (data_dir / "gefs_b2_download_state_2000.csv").write_text("20000101,done\n")

        in_flight = {"2000": 7}
        result = scan_matrix(in_flight, data_dir)

        # NamedTuple attribute access
        assert isinstance(result, MatrixScanResult)
        assert result.completed_days == 1
        assert result.expected_days == 7305  # 20 years (2000-2019)
        assert result.expected_slices == 7305 * 20  # 146,100
        assert result.completed_slices == 20 + 7  # 27

        # 5-tuple unpacking compatibility
        summary, done_s, exp_s, done_d, exp_d = result
        assert done_s == 27
        assert exp_s == 146100
        assert done_d == 1
        assert exp_d == 7305
        assert len(summary) == 20

        # Backward compatibility keys in summary
        item_2000 = next(it for it in summary if it["year"] == 2000)
        assert item_2000["total_slices"] == 366 * 20
        assert item_2000["completed_slices"] == 27
        assert item_2000["in_flight"] == 7
        assert "sh_cnt" in item_2000
        assert "den_cnt" in item_2000
        assert item_2000["status"] == "in_progress"


class TestGEFSRecentFiles:
    """Test recent files scanning, mtime sorting, and string formatting."""

    def test_format_file_item(self):
        p = Path("20100105/subset_test.grib2")
        now = time.time()
        item = _format_file_item(now - 15, 2_250_000, p, now)
        assert item["name"] == "subset_test.grib2"
        assert item["path"] == "20100105/subset_test.grib2"
        assert item["size_mb"] == 2.15
        assert item["age_str"] == "15秒前"

        item_old = _format_file_item(now - 150, 1024 * 500, p, now)
        assert item_old["age_str"] == "2分30秒前"

    def test_scan_recent_files_sorts_by_mtime_descending(self, tmp_path):
        storage_root = tmp_path / "storage"
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "gefs_b2_download_state_2010.csv").write_text("20100101,done\n")

        d1 = storage_root / "20100101"
        d1.mkdir(parents=True)
        f_old = d1 / "old_slice.grib2"
        f_old.write_bytes(b"old")

        d2 = storage_root / "20100102"
        d2.mkdir(parents=True)
        f_new = d2 / "new_slice.grib2"
        f_new.write_bytes(b"new")

        # Set explicit modification times
        t_now = time.time()
        import os
        os.utime(f_old, (t_now - 200, t_now - 200))
        os.utime(f_new, (t_now - 5, t_now - 5))

        recent = scan_recent_files(
            active_dates={"20100102"},
            storage_root=storage_root,
            data_dir=data_dir,
            limit=5,
        )

        assert len(recent) == 2
        # Newest file must appear first regardless of directory name sorting
        assert recent[0]["name"] == "new_slice.grib2"
        assert recent[1]["name"] == "old_slice.grib2"
