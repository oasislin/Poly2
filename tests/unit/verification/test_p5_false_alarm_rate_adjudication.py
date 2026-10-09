"""
tests/unit/verification/test_p5_false_alarm_rate_adjudication.py:
Task A: Empirical False Alarm Rate (Type I Error) Adjudication Suite for P5 Gate under Small-Sample CV Folds.

Mandated by P4-PHASE2-R1 Task A:
1. Monte Carlo N >= 1000 simulations under exact fold sample sizes and binning structures.
2. Measure False Alarm Rate (percentage of perfectly calibrated models falsely rejected by S4 / S5).
3. Mechanical Decision Rule:
   - If False Alarm Rate >= 15% -> Proves statistical over-sensitivity / miscalibration of the metric on thin samples (Branch B).
   - If False Alarm Rate < 5%  -> Refutes false alarm hypothesis; 3/20 failures treated as true defects.
   - Between 5% and 15%        -> Report for review.
"""

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from src.verification.p5_gate import run_reliability_gate


def test_adjudicate_s4_wilson_coverage_false_alarm_rate_on_3bins():
    """
    Scenario 1: S4 Wilson coverage false alarm rate on 3 adaptive decision bins (K=3).
    When adaptive binning merges sparse strata into K=3 bins, nominal 95% CIs mean that
    with probability 1 - 0.95^3 ~ 14.3%, at least 1 bin falls outside 95% CI by pure chance.
    A single miss drops coverage to 2/3 = 66.7%, instantly failing the 90% threshold!
    """
    n_sims = 1000
    n_samples_per_fold = 4800  # matches 690 days * 7 bins
    rng = np.random.default_rng(20260923)

    s4_failed_count = 0
    s4_coverages = []

    for _ in range(n_sims):
        # Perfectly calibrated discrete event stream across K=3 bins
        # e.g., probabilities centered in 3 dominant brackets [0.05, 0.15, 0.30]
        p_candidates = np.array([0.05, 0.15, 0.30])
        bin_assignments = rng.choice(3, size=n_samples_per_fold, p=[0.40, 0.35, 0.25])
        p_preds = p_candidates[bin_assignments]

        # Strictly draw true outcomes from Bernoulli(p_preds) -> 100% perfectly calibrated
        hits = rng.binomial(1, p_preds).astype(np.float64)
        pits = rng.uniform(0.001, 0.999, size=n_samples_per_fold)

        df_sim = pd.DataFrame({
            "p_pred": p_preds,
            "hit": hits,
            "pit": pits,
        })

        # Run gate with default config (min_coverage=0.90)
        rep = run_reliability_gate(df_sim)
        s4_coverages.append(rep.wilson_coverage_rate)
        if not rep.s_ladder_status["S4_wilson_coverage"]:
            s4_failed_count += 1

    false_alarm_rate_s4 = s4_failed_count / n_sims
    mean_coverage = float(np.mean(s4_coverages))
    print(f"\n[Task A1 Result: S4 3-Bin Scenario]")
    print(f"Total Simulations: {n_sims}")
    print(f"S4 False Alarm Rate (Type I Error): {false_alarm_rate_s4:.2%}")
    print(f"Mean Wilson Coverage: {mean_coverage:.4f}")

    # Mechanical assertion: Verified against task-722 empirical baseline (13.80%)
    # and mathematical expectation 1 - 0.95^3 = 14.26%.
    assert 0.10 <= false_alarm_rate_s4 <= 0.18, (
        f"S4 False Alarm Rate {false_alarm_rate_s4:.2%} outside expected CI [10%, 18%]"
    )


def test_adjudicate_single_fold_gate_overall_false_alarm_rate():
    """
    Scenario 2: Overall single-fold GateReport false alarm rate across 1000 Monte Carlo runs.
    Evaluates probability that a 100% perfectly calibrated forecast is rejected by S1..S5
    under single-fold sample sizes (N=690 days / 4830 events).
    """
    n_sims = 1000
    n_days = 690
    rng = np.random.default_rng(20260923)

    gate_failed_count = 0
    reasons = {"S2": 0, "S3": 0, "S4": 0, "S5": 0}

    for _ in range(n_sims):
        # 1. Perfectly calibrated continuous forecast
        mu = rng.uniform(30.0, 85.0, size=n_days)
        sigma = rng.uniform(2.0, 4.5, size=n_days)
        obs = rng.normal(loc=mu, scale=sigma, size=n_days)

        # PIT values from true distribution
        z = (obs - mu) / sigma
        pit = stats.norm.cdf(z)

        # 7-bin discretization
        all_p = []
        all_h = []
        all_pit = []
        for i in range(n_days):
            m_i, s_i, y_i, pit_i = mu[i], sigma[i], obs[i], pit[i]
            c0 = int(round(m_i))
            for k in range(-3, 4):
                bk = c0 + k
                p_k = float(stats.norm.cdf((bk + 0.5 - m_i) / s_i) - stats.norm.cdf((bk - 0.5 - m_i) / s_i))
                p_k = max(0.0, min(1.0, p_k))
                h_k = 1.0 if (bk - 0.5 <= y_i < bk + 0.5) else 0.0
                all_p.append(p_k)
                all_h.append(h_k)
                all_pit.append(pit_i)

        df_fold = pd.DataFrame({"p_pred": all_p, "hit": all_h, "pit": all_pit})
        rep = run_reliability_gate(df_fold)

        if not rep.passed:
            gate_failed_count += 1
            for k_step in ["S2_calibration_ece", "S3_monotonicity", "S4_wilson_coverage", "S5_ks_goodness"]:
                if not rep.s_ladder_status[k_step]:
                    reasons[k_step[:2]] += 1

    overall_far = gate_failed_count / n_sims
    print(f"\n[Task A2 Result: Single-Fold Overall Gate]")
    print(f"Total Simulations: {n_sims}")
    print(f"Overall Gate False Alarm Rate: {overall_far:.2%}")
    print(f"Failure Breakdown: {reasons}")

    # Mechanical assertion: Verified against task-722 empirical baseline (4.70%)
    assert 0.02 <= overall_far <= 0.08, (
        f"Overall False Alarm Rate {overall_far:.2%} outside expected CI [2%, 8%]"
    )
