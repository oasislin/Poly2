"""
tests/unit/verification/test_p5_contract_adjudication_probe.py:
Contract Adjudication Probe Suite for P5 Gate Input Semantics.

Mandated by P4-PHASE2-R0 Task A1:
1. Probe 1 (0.25 Identity): Synthesize mathematically perfect continuous forecast (y ~ N(mu, sigma^2)).
   Asserts weighted ECE falls strictly in [0.23, 0.27] (0.25 +/- 0.02) when fed via Format B (obs, mu, sigma).
   Mechanically proves that the 0.26 ECE observed in fold_00 is an invariant mathematical artifact
   of pairing continuous PIT with a step indicator I(obs >= mu), NOT model miscalibration.
2. Probe 2 (S5 Routing): Synthesize discrete event stream with genuine PIT column.
   Asserts that Format A preserves the 'pit' column so S5 evaluates continuous uniform calibration
   instead of falsely testing discrete event probabilities p_pred against Uniform(0, 1).
"""

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from src.verification.p5_gate import run_reliability_gate, _extract_prediction_df


def test_probe_perfect_continuous_forecast_ece_identity():
    """
    Task A1: Mathematically prove ECE == 0.25 +/- 0.02 for perfect continuous forecasts under Format B.
    
    Mathematical proof:
    If y ~ N(mu, sigma^2), then z = (y - mu) / sigma ~ N(0, 1).
    Format B computes:
      p_pred = Phi(z) ~ Uniform(0, 1)
      hit = I(y >= mu) = I(z >= 0) = I(p_pred >= 0.5)
    In each bin b centered at p_b:
      For p_b >= 0.5: hit == 1.0, |p_b - f_b| = 1 - p_b
      For p_b < 0.5:  hit == 0.0, |p_b - f_b| = p_b - 0
    Integrating over p in [0, 1]:
      E[ECE] = int_0^0.5 p dp + int_0.5^1 (1 - p) dp = 0.125 + 0.125 = 0.2500.
    """
    n_samples = 100_000
    rng = np.random.default_rng(20260923)

    mu_true = rng.uniform(40.0, 85.0, size=n_samples)
    sigma_true = rng.uniform(2.0, 5.0, size=n_samples)
    # Strictly draw observations from the true forecast distribution (100% perfect calibration)
    obs_perfect = rng.normal(loc=mu_true, scale=sigma_true, size=n_samples)

    df_perfect = pd.DataFrame({
        "obs": obs_perfect,
        "mu": mu_true,
        "sigma": sigma_true,
    })

    report = run_reliability_gate(df_perfect)

    # Mechanical verification of 0.25 identity
    print(f"\n[A1 Probe Result] Perfect continuous forecast weighted ECE = {report.weighted_ece:.5f}")
    assert 0.23 <= report.weighted_ece <= 0.27, (
        f"Expected weighted ECE in 0.25 +/- 0.02, but got {report.weighted_ece:.5f}"
    )


def test_probe_format_a_preserves_pit_column_for_s5_evaluation():
    """
    Task A3 & Branch B Pre-Fix Test:
    When a discrete event stream (p_pred, hit) is fed with a genuine PIT column,
    _extract_prediction_df must preserve 'pit' so S5 evaluates PIT uniformity,
    rather than falling back to testing discrete p_pred against Uniform(0, 1).
    """
    n_events = 50_000
    rng = np.random.default_rng(20260923)

    # Well-calibrated discrete stream over full domain
    p_pred = rng.uniform(0.01, 0.99, size=n_events)
    hit = rng.binomial(1, p_pred).astype(np.float64)

    # Genuine uniform PIT values from underlying continuous distribution
    pit = rng.uniform(0.001, 0.999, size=n_events)

    df_dual = pd.DataFrame({
        "p_pred": p_pred,
        "hit": hit,
        "pit": pit,
    })

    extracted = _extract_prediction_df(df_dual)
    assert "pit" in extracted.columns, "Format A stripped 'pit' column from input DataFrame!"

    report = run_reliability_gate(df_dual)
    assert report.s_ladder_status["S5_ks_goodness"] is True, (
        f"S5 KS test failed unexpectedly: ks_stat={report.ks_stat}, error={report.error_message}"
    )
    assert report.passed is True, f"Gate failed: {report.error_message}"
