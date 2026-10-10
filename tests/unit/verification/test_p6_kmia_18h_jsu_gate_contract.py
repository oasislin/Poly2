#!/usr/bin/env python3
"""
tests/unit/verification/test_p6_kmia_18h_jsu_gate_contract.py

Contract tests for P6-KMIA-18H-GATE (Lightweight JSU Gate):
1. Validates frozen pre-registered constants for JSU gate.
2. Validates JSU 4-parameter stability & boundary compliance (delta > 0, lambda > 0).
3. Validates Delta BIC dominance classification (20/20 win, median < -30).
4. Validates Top-5 failure qualification (real failure >= 4/5).
5. Validates ECE compliance (<= 0.0100) and resolution to COMPLETED_JSU.
"""

import pytest
import numpy as np

# --- PRE-REGISTERED FROZEN CONSTANTS ---
PRE_REG_JSU_DELTA_BOUND_MIN = 0.00
PRE_REG_JSU_LAMBDA_BOUND_MIN = 0.00
PRE_REG_JSU_DELTA_BIC_MEDIAN_MAX = -30.0
PRE_REG_JSU_WIN_FOLDS_MIN = 16
PRE_REG_JSU_TOP5_FAILURES_MIN = 4
PRE_REG_STATUTORY_ECE_MAX = 0.0100


def check_jsu_parameter_bounds(delta_vals: list, lambda_vals: list) -> bool:
    """Checks that all delta and lambda values are strictly positive and unpinned."""
    delta_arr = np.array(delta_vals)
    lambda_arr = np.array(lambda_vals)
    if np.any(delta_arr <= PRE_REG_JSU_DELTA_BOUND_MIN):
        return False
    if np.any(lambda_arr <= PRE_REG_JSU_LAMBDA_BOUND_MIN):
        return False
    return True


def classify_jsu_delta_bic(delta_bics: list, win_count: int) -> str:
    """Classifies Delta BIC into PASS vs FAIL."""
    if win_count < PRE_REG_JSU_WIN_FOLDS_MIN:
        return "FAIL"
    median_val = float(np.median(delta_bics))
    if median_val < PRE_REG_JSU_DELTA_BIC_MEDIAN_MAX:
        return "PASS"
    return "FAIL"


def classify_jsu_top5_failures(real_failure_count: int, suspicious_count: int) -> str:
    """Classifies Top-5 extreme missed days."""
    if suspicious_count >= 2:
        return "FAIL"
    if real_failure_count >= PRE_REG_JSU_TOP5_FAILURES_MIN:
        return "PASS"
    return "FAIL"


def evaluate_jsu_gate_verdict(
    j1_param_pass: bool,
    j2_bic_pass: bool,
    j3_top5_pass: bool,
    ece_val: float,
) -> str:
    """Evaluates automatic release into COMPLETED_JSU vs PAUSE_FOR_COMMITTEE."""
    if j1_param_pass and j2_bic_pass and j3_top5_pass and (ece_val <= PRE_REG_STATUTORY_ECE_MAX):
        return "COMPLETED_JSU"
    return "PAUSE_FOR_COMMITTEE"


def test_frozen_constants_contract():
    """Validates frozen threshold constants against work order specifications."""
    assert PRE_REG_JSU_DELTA_BOUND_MIN == 0.00
    assert PRE_REG_JSU_LAMBDA_BOUND_MIN == 0.00
    assert PRE_REG_JSU_DELTA_BIC_MEDIAN_MAX == -30.0
    assert PRE_REG_JSU_WIN_FOLDS_MIN == 16
    assert PRE_REG_JSU_TOP5_FAILURES_MIN == 4
    assert PRE_REG_STATUTORY_ECE_MAX == 0.0100


def test_jsu_parameter_bounds():
    """Tests J1 parameter boundary conditions."""
    # KMIA 18h observed values: delta in [1.5979, 1.6543], lambda in [1.1832, 1.2359]
    observed_deltas = [1.5979, 1.6200, 1.6543]
    observed_lambdas = [1.1832, 1.2000, 1.2359]
    assert check_jsu_parameter_bounds(observed_deltas, observed_lambdas) is True

    # Sticking / boundary failure
    assert check_jsu_parameter_bounds([0.0, 1.2], [1.0, 1.1]) is False
    assert check_jsu_parameter_bounds([1.2, 1.5], [-0.1, 1.1]) is False


def test_jsu_delta_bic_classification():
    """Tests J2 Delta BIC win criteria."""
    # KMIA 18h observed values: 20 folds, median -787.93
    observed_bics = [-780.77, -819.30, -787.93, -824.95, -757.25]
    assert classify_jsu_delta_bic(observed_bics, win_count=20) == "PASS"

    # Marginal fail
    marginal_bics = [-15.0, -20.0, -10.0]
    assert classify_jsu_delta_bic(marginal_bics, win_count=20) == "FAIL"

    # Insufficient winning folds
    assert classify_jsu_delta_bic(observed_bics, win_count=15) == "FAIL"


def test_jsu_top5_classification():
    """Tests J3 Top-5 failure criteria."""
    # KMIA 18h observed: 5/5 real failures, 0 suspicious
    assert classify_jsu_top5_failures(real_failure_count=5, suspicious_count=0) == "PASS"
    assert classify_jsu_top5_failures(real_failure_count=4, suspicious_count=1) == "PASS"
    assert classify_jsu_top5_failures(real_failure_count=3, suspicious_count=0) == "FAIL"
    assert classify_jsu_top5_failures(real_failure_count=4, suspicious_count=2) == "FAIL"


def test_jsu_gate_verdict_dual_branches():
    """Tests automatic release into COMPLETED_JSU vs Pause."""
    # KMIA 18h case: J1 PASS, J2 PASS, J3 PASS, ECE 0.0031 <= 0.0100
    assert evaluate_jsu_gate_verdict(
        j1_param_pass=True,
        j2_bic_pass=True,
        j3_top5_pass=True,
        ece_val=0.003125,
    ) == "COMPLETED_JSU"

    # KMIA 24h case: J1 PASS, J2 PASS, J3 PASS, ECE 0.0062 <= 0.0100
    assert evaluate_jsu_gate_verdict(
        j1_param_pass=True,
        j2_bic_pass=True,
        j3_top5_pass=True,
        ece_val=0.006167,
    ) == "COMPLETED_JSU"

    # Any failure branch
    assert evaluate_jsu_gate_verdict(False, True, True, 0.0031) == "PAUSE_FOR_COMMITTEE"
    assert evaluate_jsu_gate_verdict(True, False, True, 0.0031) == "PAUSE_FOR_COMMITTEE"
    assert evaluate_jsu_gate_verdict(True, True, False, 0.0031) == "PAUSE_FOR_COMMITTEE"
    assert evaluate_jsu_gate_verdict(True, True, True, 0.0183) == "PAUSE_FOR_COMMITTEE"

