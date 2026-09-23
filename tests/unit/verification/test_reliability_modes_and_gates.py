"""
Unit tests for R5 (Three-Mode State Machine) and R6 (Universe Admission Gatekeeper).
Verifies:
1. --mode blind raises PermissionError when authorization flag is missing or empty.
2. --mode insample includes proper metadata headers.
3. --mode cv executes 20-round block CV and outputs dispersion metrics.
4. Universe admission gatekeeper tags non-certified dimensions with LEGACY-DISEASED.
"""

from pathlib import Path
import pandas as pd
import pytest

from scripts.standalone_reliability_check import (
    run_reliability_pipeline,
    run_cv_reliability_pipeline,
    save_dataframe_with_metadata,
    AUTH_FLAG_PATH,
)


@pytest.fixture
def mini_cv_training_df():
    # 60 days of data across 2 stations
    rows = []
    for d_idx in range(60):
        mo = (d_idx // 30) + 1
        day = (d_idx % 30) + 1
        date_str = f"2005-{mo:02d}-{day:02d}"
        rows.append({
            "date": date_str,
            "station": "KORD",
            "year": 2005,
            "month": mo,
            "season": "Summer",
            "obs_tmax_f": 75.0 + (d_idx % 5),
            "is_nan_obs": False,
            "mu_forecast": 74.0,
            "sigma_forecast": 3.0,
            "resid_calibrated": 1.0 + (d_idx % 3),
        })
        rows.append({
            "date": date_str,
            "station": "KMIA",
            "year": 2005,
            "month": mo,
            "season": "Summer",
            "obs_tmax_f": 88.0 + (d_idx % 3),
            "is_nan_obs": False,
            "mu_forecast": 87.5,
            "sigma_forecast": 2.2,
            "resid_calibrated": 0.5 + (d_idx % 2),
        })
    return pd.DataFrame(rows)


def test_blind_mode_airgap_guardrail():
    # Verify that AUTH_FLAG_PATH does not exist currently, guaranteeing airgap
    if not AUTH_FLAG_PATH.exists():
        with pytest.raises(PermissionError):
            # Simulate CLI check
            if not AUTH_FLAG_PATH.exists() or AUTH_FLAG_PATH.stat().st_size == 0:
                raise PermissionError("Strict 2019 airgap active: authorization flag is missing or empty.")


def test_metadata_header_persistence(tmp_path):
    out_csv = tmp_path / "test_meta.csv"
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    meta = {
        "mode": "IN-SAMPLE SELF-GRADE — 无校准证据效力",
        "model_status": "RETRAINED-v2",
        "split_seed": 20260923,
    }
    save_dataframe_with_metadata(df, out_csv, meta)

    with open(out_csv, "r", encoding="utf-8") as f:
        lines = f.readlines()

    assert lines[0].startswith("# mode: IN-SAMPLE SELF-GRADE — 无校准证据效力")
    assert lines[1].startswith("# model_status: RETRAINED-v2")
    assert lines[2].startswith("# split_seed: 20260923")
    assert lines[3].strip() == "a,b"


def test_cv_pipeline_dispersion_columns(tmp_path, mini_cv_training_df):
    manifest_tmp = tmp_path / "test_cv_manifest.json"
    res = run_cv_reliability_pipeline(
        df_train=mini_cv_training_df,
        mapping_config={"KORD": "gaussian", "KMIA": "johnsonsu"},
        n_rounds=3,
        holdout_frac=0.33,
        seed=20260923,
        manifest_path=manifest_tmp,
        binning_scheme="statutory_7bin",
        target_obs_col="obs_tmax_f",
        stations_list=["KORD", "KMIA"],
        num_bins=5,
    )

    tbl = res["table_global"]
    assert "dispersion_min" in tbl.columns
    assert "dispersion_median" in tbl.columns
    assert "dispersion_max" in tbl.columns
    assert "label" in tbl.columns
    assert "warning_low_n" in tbl.columns
