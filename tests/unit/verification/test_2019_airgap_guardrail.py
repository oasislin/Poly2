"""
tests/unit/verification/test_2019_airgap_guardrail.py: Test 2019 Out-Of-Sample Airgap Hard Guardrail.
"""

import json
from pathlib import Path
import pandas as pd
import pytest

from src.utils.airgap import (
    AUTHORIZATION_FLAG_FILE,
    REQUIRED_GATE_FIELDS,
    AirgapViolationError,
    filter_safe_years,
    get_sanitization_audit_log,
    is_2019_authorized,
    reset_sanitization_audit_log,
    sanitize_dataframe,
    verify_file_path,
    verify_year_whitelist,
)


def test_airgap_allows_training_window_2000_2018():
    """Verify that any years within 2000-2018 pass without error."""
    verify_year_whitelist(2018, source_description="unit_test")
    verify_year_whitelist(range(2000, 2019), source_description="unit_test")
    safe = filter_safe_years([2000, 2005, 2018])
    assert safe == [2000, 2005, 2018]


def test_airgap_strictly_blocks_unauthorized_2019_access(tmp_path, monkeypatch):
    """Verify that attempting to access 2019 raises AirgapViolationError when unauthorized."""
    test_auth_path = tmp_path / "preregistered_2019_authorization.flag"
    monkeypatch.setattr("src.utils.airgap.AUTHORIZATION_FLAG_FILE", test_auth_path)

    assert not is_2019_authorized()

    # Single integer 2019
    with pytest.raises(AirgapViolationError, match="AIRGAP VIOLATION"):
        verify_year_whitelist(2019, source_description="test_source")

    # Sequence containing 2019
    with pytest.raises(AirgapViolationError, match="AIRGAP VIOLATION"):
        verify_year_whitelist([2018, 2019], source_description="test_source")

    # via filter_safe_years
    with pytest.raises(AirgapViolationError, match="AIRGAP VIOLATION"):
        filter_safe_years([2019], source_description="test_source")


def test_airgap_strictly_blocks_2019_file_paths(tmp_path, monkeypatch):
    """Verify that attempting to access 2019 file paths raises AirgapViolationError when unauthorized."""
    test_auth_path = tmp_path / "preregistered_2019_authorization.flag"
    monkeypatch.setattr("src.utils.airgap.AUTHORIZATION_FLAG_FILE", test_auth_path)

    # GEFS 2019 parquet
    with pytest.raises(AirgapViolationError, match="AIRGAP VIOLATION"):
        verify_file_path("data/processed/calib-dataset-v2.0/gefs_factors/KORD/2019.parquet")

    # Audit arrays 2019 parquet
    with pytest.raises(AirgapViolationError, match="AIRGAP VIOLATION"):
        verify_file_path("data/processed/audit_arrays/2019_oos_active10_arrays.parquet")

    # Non-2019 file paths must pass
    verify_file_path("data/processed/calib-dataset-v2.0/gefs_factors/KORD/2018.parquet")
    verify_file_path("data/processed/truth_ghcn_daily/KORD.parquet")


def test_airgap_sanitizes_unauthorized_dataframe(tmp_path, monkeypatch):
    """Verify that a full GHCN dataframe has 2019 rows stripped when unauthorized."""
    test_auth_path = tmp_path / "preregistered_2019_authorization.flag"
    monkeypatch.setattr("src.utils.airgap.AUTHORIZATION_FLAG_FILE", test_auth_path)

    # Mixed dataframe
    df = pd.DataFrame({
        "year": [2017, 2018, 2019],
        "tmax_f": [75.0, 80.0, 85.0],
    })
    cleaned = sanitize_dataframe(df, year_col="year")
    assert len(cleaned) == 2
    assert 2019 not in cleaned["year"].values

    # Pure 2019 dataframe -> raises
    df_pure_2019 = pd.DataFrame({
        "year": [2019, 2019],
        "tmax_f": [85.0, 86.0],
    })
    with pytest.raises(AirgapViolationError, match="AIRGAP VIOLATION: Entire dataframe"):
        sanitize_dataframe(df_pure_2019, year_col="year")


def test_airgap_sanitizes_with_audit_trail_and_logging(caplog):
    """Verify that sanitize_dataframe explicitly logs and records all stripped 2019 rows."""
    reset_sanitization_audit_log()
    df = pd.DataFrame({
        "year": [2016, 2017, 2018, 2019, 2019],
        "tmax_f": [70.0, 72.0, 75.0, 80.0, 81.0],
    })

    with caplog.at_level("WARNING"):
        cleaned = sanitize_dataframe(df, year_col="year", source_description="ghcn_multi_year_load")

    assert len(cleaned) == 3
    audit = get_sanitization_audit_log()
    assert audit["total_sanitized_rows"] == 2
    assert len(audit["events"]) == 1
    assert audit["events"][0]["rows_sanitized"] == 2
    assert audit["events"][0]["source_description"] == "ghcn_multi_year_load"

    # Verify log entry is captured
    assert "AIRGAP SANITIZATION: Stripped 2 rows belonging to sealed year 2019" in caplog.text


def test_airgap_requires_embedded_gate_thresholds_in_flag(tmp_path, monkeypatch):
    """Verify that authorization flag must embed frozen gate threshold specifications."""
    test_auth_path = tmp_path / "preregistered_2019_authorization.flag"
    monkeypatch.setattr("src.utils.airgap.AUTHORIZATION_FLAG_FILE", test_auth_path)

    # Missing frozen gate thresholds -> rejected
    incomplete_flag = {
        "preregistration_id": "PR-2026-001",
        "authorized_by": "Committee",
        "allowed_scope": ["KORD"],
        "status": "AUTHORIZED",
    }
    test_auth_path.write_text(json.dumps(incomplete_flag), encoding="utf-8")
    assert not is_2019_authorized()
    with pytest.raises(AirgapViolationError):
        verify_year_whitelist(2019)

    # Full specification with embedded gate thresholds -> authorized
    valid_flag = {
        "preregistration_id": "PR-2026-001",
        "authorized_by": "Review Committee",
        "allowed_scope": ["KORD", "KLGA", "KATL"],
        "frozen_gate_thresholds": {
            "ks_p_value_min": 0.05,
            "weighted_ece_7bin_max": 0.030,
            "variance_ratio_s_oos_bounds": [0.85, 1.15],
            "pit_mean_bounds": [0.46, 0.54],
            "coverage_90_bounds": [0.83, 0.95],
        },
        "status": "AUTHORIZED",
    }
    test_auth_path.write_text(json.dumps(valid_flag), encoding="utf-8")
    assert is_2019_authorized()

    # Now allowed
    verify_year_whitelist(2019)
    verify_file_path("data/processed/calib-dataset-v2.0/gefs_factors/KORD/2019.parquet")
