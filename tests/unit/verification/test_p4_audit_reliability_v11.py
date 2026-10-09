"""
tests/unit/verification/test_p4_audit_reliability_v11.py:
Verification suite for P4-AUDIT-RELIABILITY v1.1 11-bin audit slicing logic and synthetic calibrated streams.
"""

import math
import numpy as np
import pandas as pd
import pytest
from scipy import stats

from src.prediction.discrete_bin_engine import (
    DiscreteBinEngine,
    settle_half_up,
)


def test_synthetic_calibrated_stream_audit_slicing():
    """
    Verify that a synthetic stream with known properties correctly generates
    11-bin records with valid tradeable window flags, probability simplex,
    and single-source hit indicators.
    """
    n_days = 50
    rng = np.random.default_rng(20260923)

    mu_arr = rng.uniform(50.0, 80.0, size=n_days)
    sigma_arr = rng.uniform(2.0, 4.0, size=n_days)
    obs_arr = rng.normal(loc=mu_arr, scale=sigma_arr)

    records = []
    for i in range(n_days):
        mu_i = float(mu_arr[i])
        sig_i = float(sigma_arr[i])
        obs_i = float(obs_arr[i])

        bins = DiscreteBinEngine.generate_2deg_adsorbed_bins(mu=mu_i)
        assert len(bins) == 11

        def cdf_fn(x: float) -> float:
            return float(stats.norm.cdf(x, loc=mu_i, scale=sig_i))

        probs = DiscreteBinEngine.calculate_2deg_bin_probabilities(bins, cdf_fn=cdf_fn)
        assert abs(sum(probs) - 1.0) < 1e-12

        hits = []
        for b in bins:
            is_hit = 1.0 if (b.lower_bound_f <= obs_i < b.upper_bound_f) else 0.0
            hits.append(is_hit)
            records.append({
                "day_idx": i,
                "bin_idx": b.bin_index,
                "bin_label": b.label,
                "p_pred": probs[b.bin_index],
                "hit": is_hit,
                "is_tradeable_window": b.is_tradeable_window,
            })
        assert sum(hits) == 1.0, f"Exactly one bin must hit per day, got {sum(hits)}"

    df_records = pd.DataFrame(records)
    assert len(df_records) == n_days * 11
    # Exactly 9 bins per day in-window
    assert df_records["is_tradeable_window"].sum() == n_days * 9


def test_audit_window_slicing_dimension_separation():
    """Verify that in-window and full-distribution slices partition correctly without data leakage."""
    n_days = 20
    records = []
    for i in range(n_days):
        bins = DiscreteBinEngine.generate_2deg_adsorbed_bins(mu=70.0 + i)
        for b in bins:
            records.append({
                "day_idx": i,
                "bin_idx": b.bin_index,
                "is_tradeable_window": b.is_tradeable_window,
            })
    df = pd.DataFrame(records)

    df_window = df[df["is_tradeable_window"] == True]
    df_tail = df[df["is_tradeable_window"] == False]

    assert len(df_window) == n_days * 9
    assert len(df_tail) == n_days * 2
    assert set(df_window.index).isdisjoint(set(df_tail.index))
    assert set(df_window["bin_idx"].unique()) == set(range(1, 10))
    assert set(df_tail["bin_idx"].unique()) == {0, 10}


def test_wilson_score_interval_formula_invariants():
    """Verify Wilson confidence interval half-width mathematical bounds."""
    from scripts.standalone_reliability_check import compute_binomial_ci_half_width

    for n in [10, 50, 200, 1000]:
        for k in range(0, n + 1, max(1, n // 10)):
            p_hat = k / n
            half_w = compute_binomial_ci_half_width(p_hat, n, z=1.96)
            ci_lo = max(0.0, p_hat - half_w)
            ci_hi = min(1.0, p_hat + half_w)
            assert 0.0 <= ci_lo <= ci_hi <= 1.0
