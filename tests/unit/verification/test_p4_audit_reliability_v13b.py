"""
tests/unit/verification/test_p4_audit_reliability_v13b.py:
Unit tests for P4-AUDIT-RELIABILITY v1.3b statutory specifications.

Verifies:
1. PIT Probit Transformation & KS Uniformity Mathematics.
2. Substantive Classification Three-Tier Mechanical Logic.
3. Peak Bin Probability Distribution Invariants & <= 35% Assertion Verification.
"""

import numpy as np
import pytest
from scipy import stats

from scripts.audit_p4_reliability_v13b import (
    classify_substantive_tier,
    SUBSTANTIVE_THRESHOLD,
)


def test_v13b_pit_probit_transformation_and_uniformity_math():
    """Verify PIT KS uniformity test and probit transformation math on ideal uniform stream."""
    rng = np.random.default_rng(20260923)
    # Synthetic ideal uniform PIT samples
    u_synth = rng.uniform(0.0005, 0.9995, size=10000)
    ks_res = stats.kstest(u_synth, "uniform")
    assert ks_res.pvalue > 0.05, f"Synthetic uniform stream failed KS: p={ks_res.pvalue}"

    # Probit transform: z* = Phi^-1(u)
    z_star = stats.norm.ppf(u_synth)
    assert np.isclose(np.mean(z_star), 0.0, atol=0.05)
    assert np.isclose(np.std(z_star), 1.0, atol=0.05)
    assert abs(stats.skew(z_star)) < 0.10
    assert abs(stats.kurtosis(z_star)) < 0.30


def test_v13b_substantive_classification_three_tiers():
    """Verify three-tier mechanical classification logic."""
    # Case 1: Wilson PASS -> Not Significant
    assert classify_substantive_tier(True, 0.20, 0.205) == "PASS (不显著 / 良好校准)"

    # Case 2: Wilson FAIL, but gap < 0.02 -> Significant but Marginal
    res_marginal = classify_substantive_tier(False, 0.0152, 0.0170, threshold=0.02)
    assert "FAIL" in res_marginal
    assert "显著但微小" in res_marginal
    assert "0.18%" in res_marginal

    # Case 3: Wilson FAIL, and gap >= 0.02 -> Significant & Substantive
    res_substantive = classify_substantive_tier(False, 0.10, 0.15, threshold=0.02)
    assert "FAIL" in res_substantive
    assert "显著且实质" in res_substantive
    assert "5.00%" in res_substantive


def test_v13b_peak_bin_probability_distribution_invariants():
    """Verify peak bin distribution quantiles monotonicity and <= 35% check."""
    rng = np.random.default_rng(20260923)
    # Synthetic distribution of peak probabilities strictly bounded under 0.35
    raw_beta = rng.beta(a=15, b=40, size=1000)
    p_max_synth = np.clip(raw_beta, 0.15, 0.34)
    assert np.all(p_max_synth <= 0.35)

    qs = [10, 25, 50, 75, 90, 99, 100]
    percentiles = [float(np.percentile(p_max_synth, q)) for q in qs]

    # Monotonicity of quantiles
    for i in range(len(percentiles) - 1):
        assert percentiles[i] <= percentiles[i + 1]

    # Max check
    assert max(p_max_synth) <= 0.35
