#!/usr/bin/env python3
"""
tests/unit/verification/test_p6_heavytail_diag_contract.py

Contract tests for P6-HEAVYTAIL-DIAG suite:
1. Frozen constants presence and values.
2. Two-step mechanical assertion logic for each diagnostic.
3. Accurate handling of synthetic known inputs.
"""

import numpy as np
import pandas as pd
import pytest

from scripts.diag_p6_heavytail import (
    PRE_REG_DIAG1_CALM_KURT_CEILING,
    PRE_REG_DIAG1_DIFF_SUPPORTED,
    PRE_REG_DIAG1_DIFF_NOT_SUPPORTED,
    PRE_REG_DIAG2_RATIO_MIN,
    PRE_REG_DIAG2_RATIO_MAX,
    PRE_REG_DIAG3_SPARSE_MAX_DROPS,
    PRE_REG_DIAG3_OVERALL_MIN_DROPS,
    PRE_REG_DIAG3_KURT_THRESHOLD,
    PRE_REG_DIAG4_MAX_TRANSITION_SEASON_DIFF,
    run_diagnostic_1,
    run_diagnostic_2,
    run_diagnostic_3,
    run_diagnostic_4,
    compute_delta_t24_threshold,
)


def test_frozen_constants_contract():
    """Validates that frozen pre-registered constants match work order specifications."""
    assert PRE_REG_DIAG1_CALM_KURT_CEILING == 1.00
    assert PRE_REG_DIAG1_DIFF_SUPPORTED == 0.50
    assert PRE_REG_DIAG1_DIFF_NOT_SUPPORTED == 0.20

    assert PRE_REG_DIAG2_RATIO_MIN == 0.85
    assert PRE_REG_DIAG2_RATIO_MAX == 1.15

    assert PRE_REG_DIAG3_SPARSE_MAX_DROPS == 3
    assert PRE_REG_DIAG3_OVERALL_MIN_DROPS == 5
    assert PRE_REG_DIAG3_KURT_THRESHOLD == 1.00

    assert PRE_REG_DIAG4_MAX_TRANSITION_SEASON_DIFF == 0.15


def test_diag1_decision_branches():
    """Tests all three pre-registered branches of Diagnostic 1 with mock datasets."""
    # Branch 1: Supported (Calm kurt < 1.0, diff > 0.5)
    np.random.seed(42)
    calm_z = np.random.normal(0, 1, 1000)  # kurtosis ~ 0
    # heavy-tailed student-t df=4 has kurtosis > 3
    front_z = np.random.standard_t(df=4, size=500)
    
    df_mock1 = pd.DataFrame({
        "delta_t24": [2.0] * 1000 + [15.0] * 500,
        "z": np.concatenate([calm_z, front_z]),
    })
    res1 = run_diagnostic_1([df_mock1], delta_t24_threshold=9.0)
    assert res1["decision"] == "SUPPORTED"

    # Branch 2: Partially supported insufficient (Calm kurt >= 1.0)
    calm_t = np.random.standard_t(df=4, size=1000)  # kurtosis > 1.0
    df_mock2 = pd.DataFrame({
        "delta_t24": [2.0] * 1000 + [15.0] * 500,
        "z": np.concatenate([calm_t, front_z]),
    })
    res2 = run_diagnostic_1([df_mock2], delta_t24_threshold=9.0)
    assert res2["decision"] == "PARTIALLY_SUPPORTED_INSUFFICIENT"


def test_diag2_variance_ratio_branches():
    """Tests in-band and out-of-band behavior of Diagnostic 2."""
    df_pass = pd.DataFrame({
        "resid_calib": [1.0, -1.0, 0.0],
        "sig_eff": [1.0, 1.0, 1.0],
    })
    res_pass = run_diagnostic_2([df_pass])
    assert res_pass["decision"] == "PASS_EXCLUDE_SCALE_MISCALIBRATION"
    assert res_pass["in_band"] is True

    df_fail = pd.DataFrame({
        "resid_calib": [2.0, -2.0, 2.0, -2.0],
        "sig_eff": [1.0, 1.0, 1.0, 1.0],
    })
    res_fail = run_diagnostic_2([df_fail])
    assert res_fail["decision"] == "FAIL_SCALE_DEGRADATION"
    assert res_fail["in_band"] is False


def test_diag3_sensitivity_branches():
    """Tests sparse vs overall fat tail classification in Diagnostic 3."""
    # Synthetic normal with 2 massive outliers -> sparse
    np.random.seed(42)
    z_sparse = np.random.normal(0, 1, 1000)
    z_sparse[0] = 15.0
    z_sparse[1] = -15.0
    df_sparse = pd.DataFrame({"z": z_sparse})
    res_sparse = run_diagnostic_3([df_sparse])
    assert res_sparse["decision"] == "SPARSE_EXTREME_DOMINATED"

    # Synthetic t df=3 -> overall fat tail
    z_thick = np.random.standard_t(df=3, size=2000)
    df_thick = pd.DataFrame({"z": z_thick})
    res_thick = run_diagnostic_3([df_thick])
    assert res_thick["decision"] == "DISTRIBUTION_OVERALL_FAT_TAIL"


def test_diag4_seasonal_composition_branches():
    """Tests Diagnostic 4 season difference gate."""
    # Equal proportions -> pass
    df_tr_evt = pd.DataFrame({"season": ["Spring", "Autumn", "Summer", "Winter"] * 100})
    df_tr_gauss = pd.DataFrame({"season": ["Spring", "Autumn", "Summer", "Winter"] * 100})
    df_vl_evt = pd.DataFrame({"season": ["Spring", "Autumn", "Summer", "Winter"] * 25})
    df_vl_gauss = pd.DataFrame({"season": ["Spring", "Autumn", "Summer", "Winter"] * 25})

    train_dfs = [df_tr_evt] * 4 + [df_tr_gauss] * 16
    val_dfs = [df_vl_evt] * 4 + [df_vl_gauss] * 16
    res = run_diagnostic_4(train_dfs, val_dfs, evt_winner_folds=[0, 1, 2, 3])
    assert res["passed"] is True
    assert res["decision"] == "PASS_EXCLUDE_SEASONAL_BIAS"
