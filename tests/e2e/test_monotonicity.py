"""
tests/e2e/test_monotonicity.py: End-to-End Verification for GATE-L2-02
Specification: specs/p5_layer2_scenarios.md §2.2 (GATE-L2-02: 区间一致性显式断言)

Validates:
1. Empirical hit frequency weak monotonicity: f_{i+1} >= f_i - 1e-4 across merged decision bins.
2. Wilson 95% confidence interval coverage rate: >= 90% (0.90) across decision bins.
3. Consecutive miscalibration penalty: triggers CONSECUTIVE-MISCALIBRATION-ALARM when adjacent bins are out of CI.
"""

import numpy as np
import pandas as pd
import pytest

from scripts.standalone_reliability_check import (
    build_dual_track_reliability_table,
    check_monotonicity_and_coverage,
)


def _generate_calibrated_dataset(n_samples: int = 50000, seed: int = 20260923) -> pd.DataFrame:
    """Generate 50,000 synthetic calibrated probabilistic prediction events."""
    rng = np.random.default_rng(seed)
    p_pred = rng.uniform(0.01, 0.99, size=n_samples)
    hit = rng.binomial(1, p_pred).astype(np.float64)
    return pd.DataFrame({"p_pred": p_pred, "hit": hit})


def _generate_miscalibrated_dataset(n_samples: int = 50000, seed: int = 20260923) -> pd.DataFrame:
    """Generate miscalibrated prediction events with inverted probability and out-of-CI bias."""
    rng = np.random.default_rng(seed)
    p_pred = rng.uniform(0.01, 0.99, size=n_samples)
    # Strongly inverted hit frequency (high predicted probability has low outcome rate)
    hit = rng.binomial(1, 1.0 - p_pred).astype(np.float64)
    return pd.DataFrame({"p_pred": p_pred, "hit": hit})


def test_gate_l2_02_calibrated_monotonicity_and_coverage():
    """
    GATE-L2-02 Assertion 1 & 2:
    On well-calibrated stream (50,000 events):
    - Monotonicity violations == 0 (tolerance <= 1e-4)
    - Wilson 95% CI coverage rate >= 90% (0.90)
    """
    df_cal = _generate_calibrated_dataset(50000, seed=20260923)
    res = build_dual_track_reliability_table(df_cal, num_bins=20, min_n_per_bin=30)
    decision_table = res["decision_table"]

    audit = check_monotonicity_and_coverage(decision_table)

    # 1. Monotonicity assertion
    assert audit["violations"] == 0, f"Expected 0 monotonicity violations, got {audit['violations']}"

    # 2. Wilson coverage rate assertion
    assert audit["coverage_rate"] >= 0.90, f"Expected coverage >= 0.90, got {audit['coverage_rate']:.4f}"

    # 3. No consecutive miscalibration alarms
    assert "CONSECUTIVE-MISCALIBRATION-ALARM" not in audit["alarms"]
    assert audit["passed"] is True


def test_gate_l2_02_miscalibrated_detection_and_consecutive_alarm():
    """
    GATE-L2-02 Assertion 3:
    On miscalibrated/inverted stream:
    - Must detect monotonicity violations
    - Coverage rate drops below 90%
    - Must trigger CONSECUTIVE-MISCALIBRATION-ALARM
    """
    df_mis = _generate_miscalibrated_dataset(50000, seed=20260923)
    res = build_dual_track_reliability_table(df_mis, num_bins=20, min_n_per_bin=30)
    decision_table = res["decision_table"]

    audit = check_monotonicity_and_coverage(decision_table)

    assert audit["violations"] > 0
    assert audit["coverage_rate"] < 0.90
    assert "CONSECUTIVE-MISCALIBRATION-ALARM" in audit["alarms"]
    assert audit["passed"] is False
