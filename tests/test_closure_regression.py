#!/usr/bin/env python3
"""
tests/test_closure_regression.py: Permanent Regression Fixtures for Statistical Closure Violations.

Tests historical fabricated data points from Round 2 and Round 3 review rounds:
1. KORD (Round 3): bias=2.89, sigma_f=2.35, sigma_r=4.39, claimed std(U)=0.2691, mean(U)=0.7565
   - Expected: Magnitude closure raises MagnitudeClosureError (theoretical mean ≈ 0.7192, std ≈ 0.334)
   - Negative Assertion: Mean closure MUST PASS (diff 0.0373 <= tol 0.04) to prevent post-hoc threshold tightening.
2. KMIA (Round 3): bias=0, sigma_f=2.18, MAE=3.53 -> sigma_r=4.4235, claimed std(U)=0.1692
   - Expected: Magnitude closure raises MagnitudeClosureError (theoretical std ≈ 0.3857 via arcsin closed form)
3. Round 2 Green Table: Reuses fabricated KORD/KMIA parameters, asserting magnitude closure violation.
"""

import math
import pytest
from src.metrics.calibration_audit import (
    MagnitudeClosureError,
    MeanClosureError,
    assert_statistical_closure_summary,
    compute_theoretical_pit_moments,
)


def test_regression_kord_third_round_fabrication(capsys):
    """KORD Round 3 fabricated scene:

    Parameters: bias=2.89, sigma_f=2.35, sigma_r=4.39, N=365
    Claimed: mean(U)=0.7565, std(U)=0.2691
    Expected:
      - Magnitude closure MUST raise MagnitudeClosureError (diff ≈ 0.0642 > tol 0.05)
      - Negative assertion: Mean closure MUST pass (diff ≈ 0.0373 <= tol 0.04)
    """
    bias = 2.89
    sigma_f = 2.35
    sigma_r = 4.39
    N = 365
    claimed_mean_u = 0.7565
    claimed_std_u = 0.2691

    # 1. Compute and print exact theoretical values for independent audit
    mean_theo, std_theo = compute_theoretical_pit_moments(
        mean_bias=bias,
        sigma_r=sigma_r,
        mean_sigma_f=sigma_f,
    )
    print(f"\n[FIXTURE 1: KORD Round 3]")
    print(f"  Inputs: bias={bias}, sigma_f={sigma_f}, sigma_r={sigma_r}, N={N}")
    print(f"  Claimed: mean(U)={claimed_mean_u}, std(U)={claimed_std_u}")
    print(f"  Theoretical: mean_theo={mean_theo:.4f}, std_theo={std_theo:.4f}")

    # Check that theoretical values match reviewer benchmarks (0.7192, 0.334) within 0.005
    assert abs(mean_theo - 0.7192) < 0.005, f"mean_theo {mean_theo} deviated from benchmark 0.7192"
    assert abs(std_theo - 0.3333) < 0.005, f"std_theo {std_theo} deviated from benchmark 0.3333"

    # 2. Negative assertion: Mean closure MUST NOT raise (diff 0.0373 <= guardrail 0.04)
    tol_mean = max(0.04, 2.576 / math.sqrt(12.0 * N))
    diff_mean = abs(claimed_mean_u - mean_theo)
    assert diff_mean <= tol_mean, (
        f"Negative assertion failed: mean diff {diff_mean:.4f} unexpectedly exceeded tol {tol_mean:.4f}"
    )

    # 3. Positive assertion: Magnitude closure MUST raise MagnitudeClosureError
    with pytest.raises(MagnitudeClosureError) as exc_info:
        assert_statistical_closure_summary(
            mean_bias=bias,
            sigma_r=sigma_r,
            mean_sigma_f=sigma_f,
            observed_mean_u=claimed_mean_u,
            observed_std_u=claimed_std_u,
            N=N,
            verbose=True,
        )

    print(f"  Intercepted expected exception: {exc_info.value}")


def test_regression_kmia_third_round_fabrication(capsys):
    """KMIA Round 3 fabricated scene:

    Parameters: bias=0.0, sigma_f=2.18, MAE=3.53 -> sigma_r = 3.53 / 0.7979 ≈ 4.4241, N=365
    Claimed: std(U)=0.1692, mean(U)=0.5000
    Expected:
      - Magnitude closure MUST raise MagnitudeClosureError (diff ≈ 0.2166 > tol 0.05)
      - Theoretical std ≈ 0.3857 via arcsin closed form
    """
    bias = 0.0
    sigma_f = 2.18
    sigma_r = 3.53 / 0.7979
    N = 365
    claimed_mean_u = 0.5000
    claimed_std_u = 0.1692

    mean_theo, std_theo = compute_theoretical_pit_moments(
        mean_bias=bias,
        sigma_r=sigma_r,
        mean_sigma_f=sigma_f,
    )
    print(f"\n[FIXTURE 2: KMIA Round 3]")
    print(f"  Inputs: bias={bias}, sigma_f={sigma_f}, sigma_r={sigma_r:.4f}, N={N}")
    print(f"  Claimed: std(U)={claimed_std_u}")
    print(f"  Theoretical: mean_theo={mean_theo:.4f}, std_theo={std_theo:.4f} (arcsin closed-form)")

    assert abs(mean_theo - 0.5000) < 1e-6
    assert abs(std_theo - 0.3858) < 0.005, f"std_theo {std_theo} deviated from benchmark 0.3858"

    with pytest.raises(MagnitudeClosureError) as exc_info:
        assert_statistical_closure_summary(
            mean_bias=bias,
            sigma_r=sigma_r,
            mean_sigma_f=sigma_f,
            observed_mean_u=claimed_mean_u,
            observed_std_u=claimed_std_u,
            N=N,
            verbose=True,
        )

    print(f"  Intercepted expected exception: {exc_info.value}")


def test_regression_round2_green_table_fabrication(capsys):
    """Round 2 Green Table fabricated scene:

    Fabricated table claimed KORD had calibrated std(U)=0.2691 under forecast spread sigma_f=2.35.
    Asserts that the pipeline intercepts this fabricated row with MagnitudeClosureError.
    """
    bias = 2.89
    sigma_f = 2.35
    sigma_r = 4.39
    N = 365
    fabricated_mean_u = 0.7565
    fabricated_std_u = 0.2691

    mean_theo, std_theo = compute_theoretical_pit_moments(
        mean_bias=bias,
        sigma_r=sigma_r,
        mean_sigma_f=sigma_f,
    )
    print(f"\n[FIXTURE 3: Round 2 Green Table]")
    print(f"  Inputs: bias={bias}, sigma_f={sigma_f}, sigma_r={sigma_r}, N={N}")
    print(f"  Fabricated Claim: std(U)={fabricated_std_u}")
    print(f"  Theoretical: mean_theo={mean_theo:.4f}, std_theo={std_theo:.4f}")

    with pytest.raises(MagnitudeClosureError) as exc_info:
        assert_statistical_closure_summary(
            mean_bias=bias,
            sigma_r=sigma_r,
            mean_sigma_f=sigma_f,
            observed_mean_u=fabricated_mean_u,
            observed_std_u=fabricated_std_u,
            N=N,
            verbose=True,
        )

    print(f"  Intercepted expected exception: {exc_info.value}")
