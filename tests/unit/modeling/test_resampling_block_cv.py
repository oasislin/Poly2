"""
tests/unit/modeling/test_resampling_block_cv.py: Unit tests for 30-Day Block-CV Engine.

Verifies:
1. Block partitioning produces contiguous, non-overlapping 30-day blocks.
2. 20 rounds of 90%/10% splits are deterministic with seed=20260923.
3. Zero temporal leakage: train and val date sets are disjoint for all 20 rounds.
4. Airgap enforcement: 2019 dates trigger AirgapViolationError.
5. In-loop refitting: fit_fn is invoked exactly once per round with training data.
"""

from datetime import date, timedelta
import numpy as np
import pandas as pd
import pytest

from src.modeling.resampling import (
    BlockCrossValidator,
    DEFAULT_SEED,
    partition_into_30day_blocks,
    run_block_cv,
)
from src.utils.airgap import AirgapViolationError


def test_partition_into_30day_blocks_structure():
    """Verify 30-day block partition covers full 2000-2018 date range without gaps."""
    start = date(2000, 1, 1)
    end = date(2018, 12, 31)
    blocks = partition_into_30day_blocks(start, end, block_days=30)

    # 19 years: 365 * 19 + 5 leap days = 6940 days -> ceil(6940 / 30) = 232 blocks
    total_days = (end - start).days + 1
    assert len(blocks) == int(np.ceil(total_days / 30))

    # Verify continuity
    for i in range(len(blocks) - 1):
        assert blocks[i].end_date + timedelta(days=1) == blocks[i + 1].start_date
        assert blocks[i].duration_days == 30

    # Final block may have <= 30 days
    assert blocks[-1].duration_days <= 30
    assert blocks[-1].end_date == end


def test_block_cv_zero_leakage_and_determinism():
    """Verify 20 rounds have 0% date leakage and are 100% deterministic."""
    cv1 = BlockCrossValidator(n_rounds=20, holdout_ratio=0.10, seed=DEFAULT_SEED)
    splits1 = cv1.split_blocks()

    cv2 = BlockCrossValidator(n_rounds=20, holdout_ratio=0.10, seed=DEFAULT_SEED)
    splits2 = cv2.split_blocks()

    assert len(splits1) == 20

    for r in range(20):
        s1 = splits1[r]
        s2 = splits2[r]

        # Check determinism across instances with same seed
        assert s1.val_block_ids == s2.val_block_ids
        assert s1.train_block_ids == s2.train_block_ids

        # Check disjointness (zero leakage)
        assert len(s1.train_dates.intersection(s1.val_dates)) == 0

        # Check holdout ratio (roughly 10% blocks)
        total_b = len(s1.train_block_ids) + len(s1.val_block_ids)
        assert total_b == cv1.n_blocks
        ratio = len(s1.val_block_ids) / total_b
        assert 0.08 <= ratio <= 0.12


def test_block_cv_airgap_guardrail_rejection():
    """Verify Block-CV raises AirgapViolationError if 2019 is included."""
    # Attempting to define validator covering 2019
    with pytest.raises(AirgapViolationError):
        BlockCrossValidator(
            start_date=date(2000, 1, 1),
            end_date=date(2019, 12, 31),
        )

    # Attempting to partition covering 2019
    with pytest.raises(AirgapViolationError):
        partition_into_30day_blocks(
            start_date=date(2018, 1, 1),
            end_date=date(2019, 1, 31),
        )

    # Attempting to split dataframe containing 2019 rows
    df_with_2019 = pd.DataFrame({
        "target_date": [date(2018, 12, 30), date(2018, 12, 31), date(2019, 1, 1)],
        "value": [1.0, 2.0, 3.0],
    })
    cv = BlockCrossValidator(
        start_date=date(2018, 1, 1),
        end_date=date(2018, 12, 31),
    )
    with pytest.raises(AirgapViolationError):
        list(cv.split_dataframe(df_with_2019))


def test_run_block_cv_in_loop_refitting():
    """Verify refitting is executed strictly inside each fold of the sampling loop."""
    # Create synthetic daily data for 2017-2018 (730 days)
    dates = pd.date_range("2017-01-01", "2018-12-31", freq="D").date
    df = pd.DataFrame({
        "target_date": dates,
        "x": np.linspace(10, 50, len(dates)),
        "y": np.linspace(12, 52, len(dates)) + np.random.normal(0, 0.5, len(dates)),
    })

    fit_call_count = 0
    fit_sample_sizes = []

    def mock_fit(train_df: pd.DataFrame):
        nonlocal fit_call_count
        fit_call_count += 1
        fit_sample_sizes.append(len(train_df))
        # Simple slope/intercept fit
        slope = float(np.mean(train_df["y"] / train_df["x"]))
        return {"slope": slope}

    def mock_eval(model: dict, val_df: pd.DataFrame):
        pred = val_df["x"] * model["slope"]
        mae = float(np.mean(np.abs(val_df["y"] - pred)))
        return {"val_mae": mae}

    results = run_block_cv(
        df=df,
        fit_fn=mock_fit,
        eval_fn=mock_eval,
        date_col="target_date",
        n_rounds=5,
        holdout_ratio=0.10,
        seed=DEFAULT_SEED,
    )

    # Assert model was refit inside the loop for EVERY round
    assert fit_call_count == 5
    assert len(results["round_results"]) == 5
    assert "val_mae" in results["summary"]
    assert results["summary"]["val_mae"]["mean"] > 0.0
