"""
Unit tests for SPEC-RELIABILITY-001: Reliability Check by Probability Strata.
Tests following TDD methodology across all 4 tickets.
"""

import math
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scipy import stats

from scripts.standalone_reliability_check import (
    compute_evt_variance,
    evaluate_station_cdf,
    expand_prediction_records,
    build_global_reliability_table,
    build_stratified_warning_table,
    compute_brier_skill_scores,
)

# Test fixtures
@pytest.fixture
def mock_station_params():
    r6_params = {
        "johnsonsu_parameters": {
            "gamma": 0.7645691412470903,
            "delta": 1.668232534241755,
            "xi": 0.7016806459852685,
            "lambda": 1.2322473920735264,
        }
    }
    r7_params = {
        "stations": {
            "KORD": {
                "u_left": -1.5339,
                "u_right": 1.6649,
                "gpd_left": {"shape_xi": -0.00615, "scale_beta": 0.4385},
                "gpd_right": {"shape_xi": 0.07907, "scale_beta": 0.6241},
            },
            "KMIA": {
                "u_left": -1.8048,
                "u_right": 1.4000,
                "gpd_left": {"shape_xi": -0.0738, "scale_beta": 0.9555},
                "gpd_right": {"shape_xi": -0.0750, "scale_beta": 0.4077},
            },
            "KSFO": {
                "u_left": -1.563972,
                "u_right": 1.736368,
                "gpd_left": {"shape_xi": -0.104036, "scale_beta": 0.722802},
                "gpd_right": {"shape_xi": 0.285897, "scale_beta": 0.697425},
            },
        }
    }
    return r6_params, r7_params


@pytest.fixture
def sample_training_df():
    rows = [
        # KORD day
        {
            "date": "2005-06-15",
            "station": "KORD",
            "year": 2005,
            "month": 6,
            "season": "Summer",
            "obs_tmax_f": 82.0,
            "is_nan_obs": False,
            "mu_forecast": 80.0,
            "sigma_forecast": 3.5,
        },
        # KMIA day
        {
            "date": "2010-07-20",
            "station": "KMIA",
            "year": 2010,
            "month": 7,
            "season": "Summer",
            "obs_tmax_f": 91.0,
            "is_nan_obs": False,
            "mu_forecast": 89.5,
            "sigma_forecast": 2.2,
        },
        # KSFO day
        {
            "date": "2015-08-10",
            "station": "KSFO",
            "year": 2015,
            "month": 8,
            "season": "Summer",
            "obs_tmax_f": 74.0,
            "is_nan_obs": False,
            "mu_forecast": 68.0,
            "sigma_forecast": 4.0,
        },
    ]
    return pd.DataFrame(rows)


# ==============================================================================
# Ticket 01 Tests: Record Expansion & Distribution CDFs
# ==============================================================================

def test_evaluate_station_cdf_monotonicity(mock_station_params):
    r6_params, r7_params = mock_station_params
    mu = 75.0
    sigma_eff = 3.0

    # Test KORD (Normal), KMIA (Johnson SU), KSFO (EVT)
    eval_points = np.linspace(50.0, 100.0, 50)
    for st in ["KORD", "KMIA", "KSFO"]:
        cdfs = [evaluate_station_cdf(st, y, mu, sigma_eff, r6_params, r7_params) for y in eval_points]
        # Monotonically non-decreasing
        assert all(cdfs[i] <= cdfs[i+1] + 1e-9 for i in range(len(cdfs)-1))
        # Within [0, 1]
        assert all(0.0 <= p <= 1.0 for p in cdfs)
        assert cdfs[0] < 0.05
        assert cdfs[-1] > 0.95


def test_expand_prediction_records_properties(sample_training_df, mock_station_params):
    r6_params, r7_params = mock_station_params
    expanded = expand_prediction_records(sample_training_df, r6_params, r7_params)

    # 3 days * 7 bins = 21 records
    assert len(expanded) == 3 * 7
    expected_cols = {"date", "station", "year", "month", "season", "bin_idx", "p_pred", "hit", "bin_lower", "bin_upper"}
    assert expected_cols.issubset(set(expanded.columns))

    # For each day:
    # 1. sum of p_pred should be 1.0
    # 2. sum of hit should be exactly 1
    for date, grp in expanded.groupby(["station", "date"]):
        assert math.isclose(grp["p_pred"].sum(), 1.0, abs_tol=1e-5)
        assert math.isclose(grp["hit"].sum(), 1.0, abs_tol=1e-5)
        assert (grp["p_pred"] >= 0.0).all()
        assert (grp["p_pred"] <= 1.0).all()


# ==============================================================================
# Ticket 02 Tests: Global 20-Strata Table & Stratified Warning Matrix
# ==============================================================================

def test_compute_binomial_ci_half_width_wilson():
    from scripts.standalone_reliability_check import compute_binomial_ci_half_width
    # Wald case
    w_wald = compute_binomial_ci_half_width(0.5, 100, z=1.96)
    assert math.isclose(w_wald, 1.96 * math.sqrt(0.25 / 100), abs_tol=1e-6)

    # Boundary case: f = 0, n = 1 (Wilson score correction)
    w_wilson = compute_binomial_ci_half_width(0.0, 1, z=1.96)
    expected_wilson = (1.96**2) / (1 + 1.96**2)
    assert math.isclose(w_wilson, expected_wilson, abs_tol=1e-6)
    assert w_wilson > 0.79  # Large width for n=1 prevents false positive alarm!

    # f = 1
    w_wilson_1 = compute_binomial_ci_half_width(1.0, 10, z=1.96)
    assert w_wilson_1 > 0.0


def test_build_global_reliability_table():
    # Synthetic expanded records
    np.random.seed(42)
    n = 1000
    p = np.random.uniform(0.0, 1.0, size=n)
    # Generate hits close to p with slight noise
    hit = (np.random.uniform(0.0, 1.0, size=n) < p).astype(int)
    df_exp = pd.DataFrame({"p_pred": p, "hit": hit})

    table_df, weighted_ece = build_global_reliability_table(df_exp, num_bins=20)

    # 1. Must have exactly 20 strata
    assert len(table_df) == 20
    assert table_df["sample_count_n"].sum() == n

    # 2. Check required columns
    required_cols = [
        "stratum_id",
        "stratum_range",
        "sample_count_n",
        "mean_pred_prob",
        "empirical_hit_freq",
        "abs_bias",
        "ci_95_half_width",
        "is_outside_ci",
    ]
    for col in required_cols:
        assert col in table_df.columns

    # 3. Weighted ECE consistency
    manual_ece = (table_df["sample_count_n"] * table_df["abs_bias"].fillna(0)).sum() / n
    assert math.isclose(weighted_ece, manual_ece, abs_tol=1e-7)
    assert weighted_ece >= 0.0


def test_build_global_reliability_table_empty_strata():
    # Test dataset with predictions only in [0.1, 0.2]
    df_exp = pd.DataFrame({"p_pred": [0.15, 0.16], "hit": [0, 1]})
    table_df, weighted_ece = build_global_reliability_table(df_exp, num_bins=20)

    # Strata with 0 samples must have NaN for metrics
    empty_strata = table_df[table_df["sample_count_n"] == 0]
    assert len(empty_strata) > 0
    assert empty_strata["mean_pred_prob"].isna().all()
    assert empty_strata["empirical_hit_freq"].isna().all()
    assert empty_strata["abs_bias"].isna().all()
    assert (empty_strata["is_outside_ci"] == False).all()


def test_build_stratified_warning_table():
    # Synthetic records with 3 stations and 4 seasons
    stations = ["KORD", "KMIA", "KSFO"]
    seasons = ["Winter", "Spring", "Summer", "Autumn"]
    rows = []
    for st in stations:
        for se in seasons:
            for _ in range(50):
                p = 0.25
                h = 1 if np.random.rand() < 0.25 else 0
                rows.append({"station": st, "season": se, "p_pred": p, "hit": h})
    df_exp = pd.DataFrame(rows)

    strat_df = build_stratified_warning_table(df_exp, num_bins=10)

    # 12 slices * 10 strata = 120 rows
    assert len(strat_df) == 12 * 10
    # KSFO Summer must exist
    ksfo_summer = strat_df[(strat_df["station"] == "KSFO") & (strat_df["season"] == "Summer")]
    assert len(ksfo_summer) == 10


# ==============================================================================
# Ticket 03 Tests: Climatology Baseline & Brier Skill Score
# ==============================================================================

def test_compute_brier_skill_scores(sample_training_df, mock_station_params):
    r6_params, r7_params = mock_station_params
    # Expand 3 sample days
    df_exp = expand_prediction_records(sample_training_df, r6_params, r7_params)

    # df_train_raw with additional historical days in different years to form climatology
    extra_rows = [
        {"station": "KORD", "year": 2004, "month": 6, "obs_tmax_f": 79.0, "is_nan_obs": False},
        {"station": "KORD", "year": 2006, "month": 6, "obs_tmax_f": 85.0, "is_nan_obs": False},
        {"station": "KMIA", "year": 2009, "month": 7, "obs_tmax_f": 90.0, "is_nan_obs": False},
        {"station": "KMIA", "year": 2011, "month": 7, "obs_tmax_f": 92.0, "is_nan_obs": False},
        {"station": "KSFO", "year": 2014, "month": 8, "obs_tmax_f": 70.0, "is_nan_obs": False},
        {"station": "KSFO", "year": 2016, "month": 8, "obs_tmax_f": 76.0, "is_nan_obs": False},
    ]
    df_raw = pd.concat([sample_training_df, pd.DataFrame(extra_rows)], ignore_index=True)

    bss_df = compute_brier_skill_scores(df_exp, df_raw)

    assert not bss_df.empty
    expected_cols = [
        "scope_type",
        "scope_name",
        "sample_count_n",
        "bs_model",
        "bs_clim",
        "brier_skill_score",
        "is_skillful",
    ]
    for col in expected_cols:
        assert col in bss_df.columns

    # Must include Global and Station rows
    scope_names = set(bss_df["scope_name"].tolist())
    assert "Global" in scope_names
    assert "KORD" in scope_names
    assert "KMIA" in scope_names
    assert "KSFO" in scope_names


# ==============================================================================
# Ticket 04 Tests: End-to-End Pipeline & Bitwise Determinism
# ==============================================================================

def test_run_reliability_pipeline(tmp_path, sample_training_df, mock_station_params):
    from scripts.standalone_reliability_check import run_reliability_pipeline

    r6_params, r7_params = mock_station_params
    out_global = tmp_path / "global.csv"
    out_strat = tmp_path / "strat.csv"
    out_brier = tmp_path / "brier.csv"

    res = run_reliability_pipeline(
        df_train=sample_training_df,
        r6_params=r6_params,
        r7_params=r7_params,
        out_global_path=out_global,
        out_stratified_path=out_strat,
        out_brier_path=out_brier,
    )

    assert out_global.exists()
    assert out_strat.exists()
    assert out_brier.exists()

    # Verify bitwise reproducibility
    content1 = out_global.read_text()
    _ = run_reliability_pipeline(
        df_train=sample_training_df,
        r6_params=r6_params,
        r7_params=r7_params,
        out_global_path=out_global,
        out_stratified_path=out_strat,
        out_brier_path=out_brier,
    )
    content2 = out_global.read_text()
    assert content1 == content2
