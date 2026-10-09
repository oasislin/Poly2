#!/usr/bin/env python3
"""
tests/unit/verification/test_p6_kmia_gate_contract.py

Contract tests for P6-KMIA-GATE work order:
1. Validates frozen pre-registered constants for KMIA retrospective gate audit.
2. Validates Delta_BIC categorization logic (Overwhelming vs Marginal).
3. Validates top-5 extreme failure classification logic (Real failure >= 4/5).
4. Validates combined gate resolution logic (Automatic Release vs Pause).
"""

import pytest
import numpy as np
import pandas as pd

# --- PRE-REGISTERED FROZEN CONSTANTS ---
PRE_REG_KMIA_YEARS_MIN = 30.0
PRE_REG_KMIA_MISSING_TOTAL_MAX = 0.05
PRE_REG_KMIA_MISSING_SINGLE_YEAR_MAX = 0.15
PRE_REG_KMIA_RELOCATION_MAX = 0
PRE_REG_KMIA_DELTA_BIC_OVERWHELMING_MEDIAN = -30.0
PRE_REG_KMIA_DELTA_BIC_OVERWHELMING_MIN = -20.0
PRE_REG_KMIA_XI_BOUND_MAX = 0.50
PRE_REG_KMIA_BETA_BOUND_MIN = 0.00
PRE_REG_KMIA_TOP5_REAL_FAILURES_MIN = 4  # >= 4/5


def classify_delta_bic_tier(delta_bics: list) -> str:
    """Classifies Delta BIC into Overwhelming vs Marginal tiers."""
    median_val = float(np.median(delta_bics))
    min_val = float(np.min(delta_bics))
    max_val = float(np.max(delta_bics))

    if median_val < PRE_REG_KMIA_DELTA_BIC_OVERWHELMING_MEDIAN and min_val < PRE_REG_KMIA_DELTA_BIC_OVERWHELMING_MIN:
        # Also check if any single fold is above -12
        if max_val > -12.0:
            return "MARGINAL"
        return "OVERWHELMING"
    return "MARGINAL"


def classify_top5_failures(real_failure_count: int, suspicious_count: int) -> str:
    """Classifies top-5 failure assessment."""
    if suspicious_count >= 2:
        return "FAIL"
    if real_failure_count >= PRE_REG_KMIA_TOP5_REAL_FAILURES_MIN:
        return "PASS"
    return "FAIL"


def evaluate_kmia_gate_verdict(
    matter1_all_pass: bool,
    delta_bic_tier: str,
    top5_verdict: str,
    evidence_consistent: bool,
) -> str:
    """Evaluates the automatic dual-branch gate decision."""
    if (
        matter1_all_pass
        and delta_bic_tier == "OVERWHELMING"
        and top5_verdict == "PASS"
        and evidence_consistent
    ):
        return "AUTOMATIC_RELEASE"
    return "PAUSE_FOR_COMMITTEE"


def test_frozen_constants_contract():
    """Validates frozen threshold constants against work order specifications."""
    assert PRE_REG_KMIA_YEARS_MIN == 30.0
    assert PRE_REG_KMIA_MISSING_TOTAL_MAX == 0.05
    assert PRE_REG_KMIA_MISSING_SINGLE_YEAR_MAX == 0.15
    assert PRE_REG_KMIA_RELOCATION_MAX == 0
    assert PRE_REG_KMIA_DELTA_BIC_OVERWHELMING_MEDIAN == -30.0
    assert PRE_REG_KMIA_DELTA_BIC_OVERWHELMING_MIN == -20.0
    assert PRE_REG_KMIA_XI_BOUND_MAX == 0.50
    assert PRE_REG_KMIA_BETA_BOUND_MIN == 0.00
    assert PRE_REG_KMIA_TOP5_REAL_FAILURES_MIN == 4


def test_delta_bic_tier_classification():
    """Tests Overwhelming vs Marginal classification of Delta BIC."""
    # Synthetic overwhelming case
    overwhelming_bics = [-280.0, -290.0, -300.0, -310.0, -270.0]
    assert classify_delta_bic_tier(overwhelming_bics) == "OVERWHELMING"

    # Synthetic marginal case (median above -30)
    marginal_bics = [-15.0, -18.0, -22.0, -25.0, -11.0]
    assert classify_delta_bic_tier(marginal_bics) == "MARGINAL"

    # Edge case: median low enough but one fold sticks out above -12
    edge_bics = [-50.0, -60.0, -70.0, -80.0, -10.0]
    assert classify_delta_bic_tier(edge_bics) == "MARGINAL"


def test_top5_classification_branches():
    """Tests PASS/FAIL branches of top-5 extreme failure classification."""
    assert classify_top5_failures(real_failure_count=5, suspicious_count=0) == "PASS"
    assert classify_top5_failures(real_failure_count=4, suspicious_count=1) == "PASS"
    assert classify_top5_failures(real_failure_count=3, suspicious_count=1) == "FAIL"
    assert classify_top5_failures(real_failure_count=3, suspicious_count=2) == "FAIL"


def test_gate_verdict_dual_branches():
    """Tests automatic release vs pause decision tree."""
    # All satisfied -> AUTOMATIC_RELEASE
    assert evaluate_kmia_gate_verdict(
        matter1_all_pass=True,
        delta_bic_tier="OVERWHELMING",
        top5_verdict="PASS",
        evidence_consistent=True,
    ) == "AUTOMATIC_RELEASE"

    # Any failure -> PAUSE_FOR_COMMITTEE
    assert evaluate_kmia_gate_verdict(
        matter1_all_pass=False,
        delta_bic_tier="OVERWHELMING",
        top5_verdict="PASS",
        evidence_consistent=True,
    ) == "PAUSE_FOR_COMMITTEE"

    assert evaluate_kmia_gate_verdict(
        matter1_all_pass=True,
        delta_bic_tier="MARGINAL",
        top5_verdict="PASS",
        evidence_consistent=True,
    ) == "PAUSE_FOR_COMMITTEE"

    assert evaluate_kmia_gate_verdict(
        matter1_all_pass=True,
        delta_bic_tier="OVERWHELMING",
        top5_verdict="FAIL",
        evidence_consistent=True,
    ) == "PAUSE_FOR_COMMITTEE"

    assert evaluate_kmia_gate_verdict(
        matter1_all_pass=True,
        delta_bic_tier="OVERWHELMING",
        top5_verdict="PASS",
        evidence_consistent=False,
    ) == "PAUSE_FOR_COMMITTEE"
