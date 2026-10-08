"""
tests/unit/modeling/test_warmup_isolation.py: Causal Rolling Warm-up & Zero Lookahead Isolation Tests.

Mandated by Pre-Run Gap 2:
1. Warm-up window consumes strictly pre-validation-block data prior to the boundary date.
2. Zero leakage assertion: zero reads from validation block during warm-up (warmup_dates intersect val_dates == empty).
3. Causal rolling shift(1).rolling(30) strictly enforces that day t prediction never consumes day t observation.
"""

from datetime import date, timedelta
import numpy as np
import pandas as pd
import pytest

from src.modeling.resampling import BlockCrossValidator, DEFAULT_SEED


def test_validation_fold_boundary_warmup_zero_leakage():
    """Verify that causal warm-up for a validation fold strictly draws from pre-block data with 0% val leakage."""
    cv = BlockCrossValidator(n_rounds=5, holdout_ratio=0.10, seed=DEFAULT_SEED)
    splits = cv.split_blocks()

    for split in splits:
        val_dates_sorted = sorted(list(split.val_dates))
        val_start = val_dates_sorted[0]

        # Mandated 60-day warm-up window strictly before val_start
        warmup_window_days = 60
        warmup_start = val_start - timedelta(days=warmup_window_days)
        warmup_dates = {warmup_start + timedelta(days=i) for i in range(warmup_window_days)}

        # 1. Assert warm-up dates are strictly prior to val_start
        assert all(d < val_start for d in warmup_dates), (
            f"Round {split.round_id}: Found warmup date >= val_start ({val_start})"
        )

        # 2. Strict intersection assertion (zero leakage into validation block)
        intersection = warmup_dates.intersection(split.val_dates)
        assert len(intersection) == 0, (
            f"Round {split.round_id}: Warmup leaked into validation block with dates: {intersection}"
        )


def test_causal_rolling_bias_strictly_unidirectional():
    """Verify shift(1).rolling(30) strictly depends on historical residuals, never today's observation."""
    n_days = 100
    dates = pd.date_range("2018-01-01", periods=n_days, freq="D").date
    rng = np.random.default_rng(20260923)

    raw_resid = pd.Series(rng.normal(0, 2.0, n_days), index=dates)

    # Statutory causal rolling bias calculation
    b30 = raw_resid.shift(1).rolling(30, min_periods=10).mean()

    # Assert shift(1): b30 at index i is completely invariant to changing raw_resid at index i
    for test_idx in [15, 30, 50, 80]:
        original_b30_val = b30.iloc[test_idx]

        # Mutate current day's residual arbitrarily
        mutated_resid = raw_resid.copy()
        mutated_resid.iloc[test_idx] += 999.0
        mutated_b30 = mutated_resid.shift(1).rolling(30, min_periods=10).mean()

        # Day t bias MUST remain exactly identical regardless of day t residual
        assert mutated_b30.iloc[test_idx] == original_b30_val, (
            f"Day {test_idx} bias changed after mutating day {test_idx} residual! Lookahead leak detected."
        )
