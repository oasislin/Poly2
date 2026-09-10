#!/usr/bin/env python3
"""Unit tests for GEFS B1 gap downloader script."""

from pathlib import Path
import tempfile
from unittest.mock import MagicMock
import pytest

import struct

from scripts.download_gefs_b1_gaps import (
    download_single_slice,
    verify_gap_dates_completion,
    B1_DEFAULT_GAP_DATES,
)


def _make_dummy_grib2(msg_count: int, payload_len: int = 650_000, embed_7777: bool = False) -> bytes:
    chunks = []
    for _ in range(msg_count):
        payload = b"A" * (payload_len // 2) + (b"7777" if embed_7777 else b"XXXX") + b"B" * (payload_len // 2)
        tot = 16 + len(payload) + 4
        header = b"GRIB\x00\x00\x00\x02" + struct.pack(">Q", tot)
        chunks.append(header + payload + b"7777")
    return b"".join(chunks)


class TestGEFSB1GapDownloader:
    """Contract tests for B1 gap downloading and verification."""

    def test_default_gap_dates_list(self):
        assert "20191231" in B1_DEFAULT_GAP_DATES
        assert "20011231" in B1_DEFAULT_GAP_DATES
        assert "20040328" in B1_DEFAULT_GAP_DATES
        assert len(B1_DEFAULT_GAP_DATES) == 7

    def test_download_single_slice_skips_valid_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir) / "test.grib2"
            p.write_bytes(_make_dummy_grib2(3, embed_7777=True))

            mock_h = MagicMock()
            downloaded = download_single_slice(mock_h, "search_pattern", p)
            assert downloaded is False
            mock_h.download.assert_not_called()

    def test_download_single_slice_downloads_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir) / "test.grib2"

            mock_h = MagicMock()

            def fake_download(*args, **kwargs):
                p.write_bytes(_make_dummy_grib2(3, embed_7777=True))

            mock_h.download.side_effect = fake_download
            downloaded = download_single_slice(mock_h, "search_pattern", p)
            assert downloaded is True
            mock_h.download.assert_called_once()

    def test_verify_gap_dates_completion(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            day_p = root / "gefs_reforecast" / "20191231"
            day_p.mkdir(parents=True)

            # Incomplete: 19 files
            for i in range(19):
                f = day_p / f"test_{i}.grib2"
                f.write_bytes(_make_dummy_grib2(3, embed_7777=True))
            assert verify_gap_dates_completion(root, ["20191231"]) is False

            # Add 20th file
            f20 = day_p / "test_19.grib2"
            f20.write_bytes(_make_dummy_grib2(3, embed_7777=True))
            assert verify_gap_dates_completion(root, ["20191231"]) is True

            # Redundant: 21 files (still valid and covered)
            f21 = day_p / "test_20.grib2"
            f21.write_bytes(_make_dummy_grib2(3, embed_7777=True))
            assert verify_gap_dates_completion(root, ["20191231"]) is True

