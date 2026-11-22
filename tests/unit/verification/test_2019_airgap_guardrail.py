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
    enforce_training_dataframe_seal,
    enforce_training_year_seal,
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


def test_airgap_sanitizes_with_audit_trail_and_logging(tmp_path, monkeypatch, caplog):
    """Verify that sanitize_dataframe explicitly logs and records all stripped 2019 rows."""
    test_auth_path = tmp_path / "preregistered_2019_authorization.flag"
    monkeypatch.setattr("src.utils.airgap.AUTHORIZATION_FLAG_FILE", test_auth_path)
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


def test_training_seal_blocks_2019_even_when_oos_flag_authorized(tmp_path, monkeypatch):
    """Verify training seal unconditionally rejects 2019+ even when flag STATUS=AUTHORIZED."""
    valid_flag = {
        "preregistration_id": "PR-2026-001",
        "authorized_by": "Review Committee",
        "allowed_scope": ["KORD", "KMIA"],
        "frozen_gate_thresholds": {
            "ks_p_value_min": 0.05,
            "weighted_ece_7bin_max": 0.05,
            "variance_ratio_s_oos_bounds": [0.85, 1.15],
            "pit_mean_bounds": [0.46, 0.54],
            "coverage_90_bounds": [0.83, 0.95],
        },
        "status": "AUTHORIZED",
    }
    test_auth_path = tmp_path / "preregistered_2019_authorization.flag"
    test_auth_path.write_text(json.dumps(valid_flag), encoding="utf-8")
    monkeypatch.setattr("src.utils.airgap.AUTHORIZATION_FLAG_FILE", test_auth_path)

    # OOS path permits 2019 under authorized flag (invariant preserved)
    assert is_2019_authorized() is True
    verify_year_whitelist(2019, source_description="oos_readonly_check")

    # Training seal MUST reject 2019+ and out-of-window years unconditionally
    assert enforce_training_year_seal(range(2000, 2019), "valid_train") == list(range(2000, 2019))
    for bad_years in ([2019], range(2000, 2020), 2019, [2020], [1999], []):
        with pytest.raises(AirgapViolationError, match="TRAINING AIRGAP VIOLATION"):
            enforce_training_year_seal(bad_years, source_description="unit_test")

    df_bad_year = pd.DataFrame({"year": [2018, 2019], "target_date": ["2018-12-31", "2019-01-01"]})
    with pytest.raises(AirgapViolationError, match="TRAINING AIRGAP VIOLATION"):
        enforce_training_dataframe_seal(df_bad_year, source_description="df_bad_year")

    df_bad_date = pd.DataFrame({"target_date": ["2018-12-31", "2019-01-01"], "val": [1.0, 2.0]})
    with pytest.raises(AirgapViolationError, match="TRAINING AIRGAP VIOLATION"):
        enforce_training_dataframe_seal(df_bad_date, year_col=None, date_col="target_date")


def test_retraining_entrypoints_reject_2019_under_live_authorized_flag():
    """Verify all training entrypoints and loaders reject 2019 under active AUTHORIZED flag."""
    from scripts import fit_training_variance_factors, retrain_p4_active10_matrix, train_p7_w1_pooled_phase
    from src.modeling.matrix_trainer import MatrixTrainer

    if AUTHORIZATION_FLAG_FILE.exists():
        assert is_2019_authorized() is True

    with pytest.raises(AirgapViolationError, match="TRAINING AIRGAP VIOLATION"):
        retrain_p4_active10_matrix.load_station_training_data("KORD", years=[2019])
    with pytest.raises(AirgapViolationError, match="TRAINING AIRGAP VIOLATION"):
        retrain_p4_active10_matrix.main(years=range(2000, 2020))

    with pytest.raises(AirgapViolationError, match="TRAINING AIRGAP VIOLATION"):
        train_p7_w1_pooled_phase.load_station_training_data("KORD", years=[2019])
    with pytest.raises(AirgapViolationError, match="TRAINING AIRGAP VIOLATION"):
        train_p7_w1_pooled_phase.retrain_phase_matrix(years=range(2000, 2020))

    with pytest.raises(AirgapViolationError, match="TRAINING AIRGAP VIOLATION"):
        fit_training_variance_factors.load_station_training_data("KORD", years=[2019])

    with pytest.raises(AirgapViolationError, match="TRAINING AIRGAP VIOLATION"):
        MatrixTrainer(stations=["KORD"], train_start_year=2000, train_end_year=2019)

    trainer = MatrixTrainer(stations=["KORD"], train_start_year=2000, train_end_year=2018)
    df_slice_2019 = pd.DataFrame({
        "target_date": ["2019-07-32"] * 5,
        "ensemble_mean": [80.0] * 5,
        "ensemble_variance": [2.0] * 5,
        "observed_temp": [80.0] * 5,
    })
    with pytest.raises(AirgapViolationError, match="TRAINING AIRGAP VIOLATION"):
        trainer.train_slice("KORD", "Summer", "max", 24, df_slice_2019)

    # Legitimate 2018 load (whose GEFS parquet includes Dec 29-31 inits with 2019-01-01..03 targets) still succeeds
    df_ghcn, df_gefs = retrain_p4_active10_matrix.load_station_training_data("KORD", years=[2018])
    cell_df = retrain_p4_active10_matrix.extract_cell_dataset(df_ghcn, df_gefs, "Winter", "Max", 72)
    assert not cell_df.empty
    assert pd.to_datetime(cell_df["target_date"]).dt.year.max() == 2018
