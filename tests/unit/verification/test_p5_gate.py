"""
tests/unit/verification/test_p5_gate.py: Unit Tests for P5 Mainline Wiring Thin Layer.
Specification: specs/p5_layer2_scenarios.md & Task D (主线接线层测试)

Covers:
1. GateReport schema, dataclass immutability, and serialization.
2. Input validation and error defense (empty, invalid schema, physics violation).
3. Calibrated model stream passing reliability gate (passed == True).
4. Degenerate zero-variance stream interception (passed == False, is_degenerate == True).
5. Miscalibrated prediction stream gate rejection (passed == False).
"""

import numpy as np
import pandas as pd
import pytest

from src.verification.p5_gate import GateReport, run_reliability_gate


def test_gate_report_contract_and_immutability():
    """Verify GateReport contract, immutability, and to_dict serialization."""
    report = GateReport(
        passed=True,
        weighted_ece=0.012,
        ece_ci_lower=0.009,
        ece_ci_upper=0.015,
        bss=0.15,
        ks_stat=0.02,
        ks_pvalue=0.45,
        wilson_coverage_rate=0.95,
        is_degenerate=False,
        error_message=None,
        s_ladder_status={"S1_input_defense": True, "S2_calibration_ece": True},
        metadata={"sample_count": 5000},
    )

    # Immutability check
    with pytest.raises(Exception):
        report.passed = False  # frozen dataclass prevents mutation

    # Serialization check
    d = report.to_dict()
    assert d["passed"] is True
    assert d["weighted_ece"] == 0.012
    assert d["is_degenerate"] is False
    assert d["s_ladder_status"]["S1_input_defense"] is True


def test_gate_input_validation_defense():
    """Verify defensive handling of empty input, invalid columns, and physics collapse."""
    # 1. Empty DataFrame
    rep_empty = run_reliability_gate(pd.DataFrame())
    assert rep_empty.passed is False
    assert "Input validation failure" in str(rep_empty.error_message)

    # 2. Invalid schema (missing required columns)
    rep_invalid = run_reliability_gate(pd.DataFrame({"colA": [1, 2, 3]}))
    assert rep_invalid.passed is False
    assert "Input validation failure" in str(rep_invalid.error_message)

    # 3. Physics noise floor violation (sigma < 0.90°F)
    df_phys = pd.DataFrame({
        "obs": [70.0, 71.0],
        "mu": [70.0, 71.0],
        "sigma": [0.80, 0.70],  # Below 0.90 PRT sensor noise floor
    })
    rep_phys = run_reliability_gate(df_phys)
    assert rep_phys.passed is False
    assert "0.90" in str(rep_phys.error_message)


def test_gate_calibrated_stream_passes():
    """Verify calibrated predictions pass the reliability gate with high scores."""
    n = 50000
    rng = np.random.default_rng(20260923)
    p_pred = rng.uniform(0.01, 0.99, size=n)

    hit = rng.binomial(1, p_pred).astype(np.float64)


    df_cal = pd.DataFrame({"p_pred": p_pred, "hit": hit})
    report = run_reliability_gate(df_cal, config={"max_ece": 0.05, "min_coverage": 0.90})

    assert report.passed is True
    assert report.is_degenerate is False
    assert report.weighted_ece <= 0.05
    assert report.wilson_coverage_rate >= 0.90
    assert report.error_message is None
    assert all(report.s_ladder_status.values())


def test_gate_degenerate_stream_intercepted():
    """Verify that degenerate zero-variance stream is intercepted and reflected in GateReport."""
    n = 1000
    # Stream of all identical constant values (variance = 0)
    df_deg = pd.DataFrame({
        "p_pred": [0.35] * n,
        "hit": [1.0] * n,
    })

    report = run_reliability_gate(df_deg)

    assert report.passed is False
    assert report.is_degenerate is True
    assert "degenerate: zero variance" in str(report.error_message)
    assert report.s_ladder_status["S1_input_defense"] is False


def test_gate_miscalibrated_stream_rejected():
    """Verify that strongly miscalibrated stream fails the gate."""
    n = 10000
    rng = np.random.default_rng(20260923)
    p_pred = rng.uniform(0.05, 0.95, size=n)
    # Inverted outcomes
    hit = rng.binomial(1, 1.0 - p_pred).astype(np.float64)

    df_mis = pd.DataFrame({"p_pred": p_pred, "hit": hit})
    report = run_reliability_gate(df_mis)

    assert report.passed is False
    assert report.is_degenerate is False
    assert report.s_ladder_status["S3_monotonicity"] is False or report.s_ladder_status["S2_calibration_ece"] is False
