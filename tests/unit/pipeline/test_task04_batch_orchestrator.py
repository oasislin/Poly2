"""
Unit tests for Task 04 batch orchestrator and precision auditor scripts.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.audit_iem_precision_sample import _independent_parse_t_group
from scripts.fetch_all_iem_observations import (
    _validate_requested_stations,
    run_batch_fetch,
)
from src.data_processing.constants import ACTIVE_11_STATIONS


def test_station_universe_validation():
    # Valid active stations pass
    validated = _validate_requested_stations(["kord", "KLGA", "KAUS"])
    assert validated == ["KORD", "KLGA", "KAUS"]

    # All 11 active stations pass
    all_val = _validate_requested_stations(list(ACTIVE_11_STATIONS))
    assert len(all_val) == 11

    # Banned stations fail immediately
    for banned in ["KDCA", "ZSPD", "EGLC", "KDEN", "UNKNOWN"]:
        with pytest.raises(ValueError, match="not in active 11 stations"):
            _validate_requested_stations([banned])


def test_dry_run_batch_fetch(tmp_path):
    stats, errors = run_batch_fetch(
        stations=["KORD", "KLGA"],
        start_year=2020,
        end_year=2024,
        out_dir=tmp_path,
        dry_run=True,
    )
    assert stats.total_requested == 10  # 2 stations * 5 years
    assert len(errors) == 0


def test_independent_t_group_parser():
    # Positive temp and dewpoint: T02830250 -> 28.3°C, 25.0°C
    t, d = _independent_parse_t_group("METAR KORD 010051Z RMK AO2 T02830250")
    assert t == 28.3
    assert d == 25.0

    # Negative temp and dewpoint: T10501120 -> -5.0°C, -12.0°C
    t_neg, d_neg = _independent_parse_t_group("METAR KORD 010051Z RMK AO2 T10501120")
    assert t_neg == -5.0
    assert d_neg == -12.0

    # Missing T-group
    t_none, d_none = _independent_parse_t_group("METAR KORD 010051Z RMK AO2")
    assert t_none is None
    assert d_none is None


@patch("src.pipeline.iem_adapter.IemAdapter.fetch_station_year")
def test_batch_fetch_error_containment(mock_fetch, tmp_path):
    # Mock first year failure, second year success
    mock_artifact = MagicMock()
    mock_artifact.row_count = 100
    mock_artifact.quality_flag = "nominal"
    mock_artifact.manifest_entry = {"sha256": "abc12345"}

    mock_fetch.side_effect = [
        RuntimeError("Temporary Network Failure"),
        mock_artifact,
    ]

    stats, errors = run_batch_fetch(
        stations=["KORD"],
        start_year=2023,
        end_year=2024,
        out_dir=tmp_path,
        rate_limit=0.0,
        force=True,
        dry_run=False,
    )

    assert stats.total_requested == 2
    assert stats.successful_count == 1
    assert stats.failed_count == 1
    assert len(errors) == 1
    assert errors[0]["station"] == "KORD"
    assert errors[0]["year"] == 2023
    assert (tmp_path / "fetch_errors.json").exists()
