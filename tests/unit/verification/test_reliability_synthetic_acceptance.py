"""
Synthetic End-to-End Acceptance Tests (Section IV Mandate):
1. Perfect Calibration Test: Synthesized Bernoulli true outcomes match p_pred. Asserts strata fall within 95% Wilson CI.
2. Deliberate Miscalibration Test: Under-dispersed model (sigma_pred = 0.5 * sigma_true). Asserts detection of coverage collapse and CI violations.
3. Collapse Sentinel Test: Pathological variance (sigma_eff < 0.90°F). Asserts PhysicsViolationError fatal exception.
"""

import math
import numpy as np
import pandas as pd
import pytest
from scipy import stats

from scripts.standalone_reliability_check import (
    PhysicsViolationError,
    SIGMA_PHYS_FLOOR,
    evaluate_station_cdf,
    expand_prediction_records,
    build_global_reliability_table,
    compute_table_meta_metrics,
)


def test_synthetic_perfect_calibration():
    """
    Test 1: Perfect Calibration Verification.
    Generates N=100,000 synthetic observations where y ~ Bernoulli(p_pred).
    Asserts empirical frequency f_hat falls within 95% Wilson CI across strata.
    """
    rng = np.random.RandomState(42)
    n_samples = 100_000
    p_preds = rng.uniform(0.01, 0.99, size=n_samples)
    hits = rng.binomial(1, p_preds)

    df_synth = pd.DataFrame({
        "p_pred": p_preds,
        "hit": hits,
    })

    table_global, weighted_ece = build_global_reliability_table(df_synth, num_bins=20)
    meta = compute_table_meta_metrics(table_global)

    # In a perfectly calibrated large-sample dataset, weighted ECE should be negligible (< 0.005)
    assert weighted_ece < 0.005, f"Weighted ECE too high for perfect calibration: {weighted_ece:.4f}"

    # Nominal 95% CI means out-of-CI rate should not exceed 10% (nominally 5%)
    assert meta["out_of_ci_rate"] <= 0.10, f"Too many out-of-CI violations: {meta['out_of_ci_rate']:.1%}"
    # All strata must have valid sample counts
    assert (table_global["sample_count_n"] > 1000).all()


def test_synthetic_deliberate_miscalibration():
    """
    Test 2: Deliberate Miscalibration & Overconfidence Verification.
    Generates synthetic data with true variance sigma=4.0°F, but forecast model assumes
    under-dispersed sigma=2.0°F (50% under-dispersion, severe overconfidence).
    Asserts that the tool stably detects severe CI violations (> 30% out-of-CI rate).
    """
    rng = np.random.RandomState(12345)
    n_days = 2000
    mu_true = 75.0
    sigma_true = 4.0
    sigma_underdispersed = 2.0  # Pathological overconfidence

    obs_temps = rng.normal(loc=mu_true, scale=sigma_true, size=n_days)
    dates = [f"2005-{((i // 28) % 12) + 1:02d}-{(i % 28) + 1:02d}" for i in range(n_days)]

    df_days = pd.DataFrame({
        "date": dates,
        "station": "KORD",
        "year": 2005,
        "month": 6,
        "season": "Summer",
        "obs_tmax_f": obs_temps,
        "is_nan_obs": False,
        "mu_forecast": mu_true,
        "sigma_forecast": sigma_underdispersed,
    })

    r6_dummy = {"johnsonsu_parameters": {"gamma": 0.0, "delta": 1.0, "xi": 0.0, "lambda": 1.0}}
    r7_dummy = {"stations": {}}
    cfg = {"KORD": "gaussian"}

    expanded = expand_prediction_records(
        df_days,
        r6_params=r6_dummy,
        r7_params=r7_dummy,
        mapping_config=cfg,
        binning_scheme="statutory_7bin",
    )

    table_global, weighted_ece = build_global_reliability_table(expanded, num_bins=20)
    meta = compute_table_meta_metrics(table_global)

    # Overconfidence must be flagged: weighted ECE should be noticeably elevated
    assert weighted_ece > 0.03, f"Failed to detect miscalibration: ECE={weighted_ece:.4f}"
    # Tool must detect significant out-of-CI violations (significantly > nominal 5%)
    assert meta["out_of_ci_rate"] >= 0.30, (
        f"Out-of-CI rate too low ({meta['out_of_ci_rate']:.1%}) for severe 50% under-dispersion!"
    )


def test_synthetic_collapse_sentinel():
    """
    Test 3: Collapse Sentinel (R1 Verification).
    Feeds a collapsed forecast variance sigma_eff < 0.90°F (e.g. c=1e-7, sigma=0.001°F).
    Asserts that PhysicsViolationError is raised immediately, refusing silent truncation.
    """
    r6_dummy = {"johnsonsu_parameters": {"gamma": 0.0, "delta": 1.0, "xi": 0.0, "lambda": 1.0}}
    r7_dummy = {"stations": {}}

    # Direct function call with collapsed sigma
    with pytest.raises(PhysicsViolationError) as exc_info:
        evaluate_station_cdf(
            station="KORD",
            y=70.0,
            mu=70.0,
            sigma_eff=0.0001,  # Collapsed variance
            r6_params=r6_dummy,
            r7_params=r7_dummy,
        )

    assert "floor 0.9" in str(exc_info.value)
    assert "collapsed variance" in str(exc_info.value)

    # End-to-end pipeline check with collapsed sigma in dataframe
    df_collapsed = pd.DataFrame([{
        "date": "2005-06-15",
        "station": "KORD",
        "year": 2005,
        "month": 6,
        "season": "Summer",
        "obs_tmax_f": 75.0,
        "is_nan_obs": False,
        "mu_forecast": 75.0,
        "sigma_forecast": 0.50,  # Below 0.90°F floor
    }])

    with pytest.raises(PhysicsViolationError):
        expand_prediction_records(
            df_collapsed,
            r6_params=r6_dummy,
            r7_params=r7_dummy,
            mapping_config={"KORD": "gaussian"},
        )
