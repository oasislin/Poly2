"""
src/modeling/resampling.py: 30-Day Block Cross-Validation (Block-CV) Engine.

Mandated by R2 Mainline Protocol & P3 Specification:
1. Block Resampling Unit: 30 consecutive calendar days per block (breaking meteorological
   temporal autocorrelation / synoptic scale persistence).
2. Data Boundary: Strictly restricted to 2000-01-01 through 2018-12-31.
   2019 data is strictly airgapped and forbidden.
3. Protocol:
   - 20 rounds of Monte Carlo Block-CV.
   - 10% holdout blocks for validation, 90% blocks for fitting.
   - Deterministic pseudo-random seed locked to 20260923.
4. Refitting Constraint: Model refitting MUST be invoked strictly inside the sampling loop.
   Pre-fitting outside the fold and running inference-only is strictly prohibited.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import math
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Set, Tuple, Union
import numpy as np
import pandas as pd

from src.utils.airgap import AirgapViolationError, SEALED_YEAR, verify_year_whitelist


DEFAULT_SEED = 20260923
DEFAULT_BLOCK_DAYS = 30
DEFAULT_N_ROUNDS = 20
DEFAULT_HOLDOUT_RATIO = 0.10
TRAIN_START_DATE = date(2000, 1, 1)
TRAIN_END_DATE = date(2018, 12, 31)


@dataclass(frozen=True)
class CalendarBlock:
    """A contiguous calendar time block for resampling."""
    block_id: int
    start_date: date
    end_date: date
    duration_days: int
    dates: Tuple[date, ...] = field(repr=False)

    def contains_date(self, d: date) -> bool:
        return self.start_date <= d <= self.end_date


@dataclass
class BlockCVSplit:
    """A single split (fold) in Block Cross-Validation."""
    round_id: int
    train_block_ids: List[int]
    val_block_ids: List[int]
    train_dates: Set[date] = field(repr=False)
    val_dates: Set[date] = field(repr=False)


def partition_into_30day_blocks(
    start_date: date = TRAIN_START_DATE,
    end_date: date = TRAIN_END_DATE,
    block_days: int = DEFAULT_BLOCK_DAYS,
) -> List[CalendarBlock]:
    """
    Partition the date range [start_date, end_date] into contiguous non-overlapping blocks of `block_days`.
    The final block may have <= block_days to capture remaining tail days.
    """
    if start_date > end_date:
        raise ValueError(f"start_date ({start_date}) must be <= end_date ({end_date})")

    # Airgap assertion: neither boundary can be 2019
    if start_date.year == SEALED_YEAR or end_date.year == SEALED_YEAR:
        raise AirgapViolationError(
            f"Cannot create cross-validation blocks in sealed year {SEALED_YEAR}!"
        )

    blocks: List[CalendarBlock] = []
    curr_start = start_date
    block_id = 0

    while curr_start <= end_date:
        curr_end = min(curr_start + timedelta(days=block_days - 1), end_date)
        # Verify no 2019 date slips in
        if curr_start.year == SEALED_YEAR or curr_end.year == SEALED_YEAR:
            raise AirgapViolationError(f"Block crosses into sealed year {SEALED_YEAR}!")

        # Enumerate dates in block
        block_dates_list = []
        d = curr_start
        while d <= curr_end:
            block_dates_list.append(d)
            d += timedelta(days=1)

        b = CalendarBlock(
            block_id=block_id,
            start_date=curr_start,
            end_date=curr_end,
            duration_days=len(block_dates_list),
            dates=tuple(block_dates_list),
        )
        blocks.append(b)
        block_id += 1
        curr_start = curr_end + timedelta(days=1)

    return blocks


class BlockCrossValidator:
    """
    30-Day Block Cross-Validation Splitter for 2000-2018 Training Data.
    Generates 20 rounds of 90% fit / 10% holdout blocks using fixed seed.
    """

    def __init__(
        self,
        n_rounds: int = DEFAULT_N_ROUNDS,
        holdout_ratio: float = DEFAULT_HOLDOUT_RATIO,
        block_days: int = DEFAULT_BLOCK_DAYS,
        start_date: date = TRAIN_START_DATE,
        end_date: date = TRAIN_END_DATE,
        seed: int = DEFAULT_SEED,
    ):
        if n_rounds <= 0:
            raise ValueError(f"n_rounds must be > 0, got {n_rounds}")
        if not (0.0 < holdout_ratio < 1.0):
            raise ValueError(f"holdout_ratio must be in (0, 1), got {holdout_ratio}")
        if start_date.year > 2018 or end_date.year >= 2019:
            raise AirgapViolationError(
                f"BlockCrossValidator date range [{start_date}, {end_date}] touches or exceeds {SEALED_YEAR}!"
            )

        self.n_rounds = n_rounds
        self.holdout_ratio = holdout_ratio
        self.block_days = block_days
        self.start_date = start_date
        self.end_date = end_date
        self.seed = seed

        # Precompute blocks
        self.blocks = partition_into_30day_blocks(
            start_date=self.start_date,
            end_date=self.end_date,
            block_days=self.block_days,
        )
        self.n_blocks = len(self.blocks)
        self.n_val_blocks = max(1, int(round(self.n_blocks * self.holdout_ratio)))

    def split_blocks(self) -> List[BlockCVSplit]:
        """Generate list of 20 deterministic BlockCVSplit splits."""
        rng = np.random.default_rng(self.seed)
        splits: List[BlockCVSplit] = []

        all_block_ids = np.arange(self.n_blocks)

        for round_id in range(self.n_rounds):
            # Select random 10% of block IDs without replacement
            val_block_ids_arr = rng.choice(
                all_block_ids,
                size=self.n_val_blocks,
                replace=False,
            )
            val_block_ids_set = set(val_block_ids_arr.tolist())
            train_block_ids_set = set(all_block_ids.tolist()) - val_block_ids_set

            # Enumerate exact dates
            val_dates: Set[date] = set()
            for bid in val_block_ids_set:
                val_dates.update(self.blocks[bid].dates)

            train_dates: Set[date] = set()
            for bid in train_block_ids_set:
                train_dates.update(self.blocks[bid].dates)

            # Mathematical orthogonality assertion: zero date leakage
            leakage = val_dates.intersection(train_dates)
            assert len(leakage) == 0, f"Critical leakage detected between train and val: {leakage}"

            splits.append(
                BlockCVSplit(
                    round_id=round_id,
                    train_block_ids=sorted(list(train_block_ids_set)),
                    val_block_ids=sorted(list(val_block_ids_set)),
                    train_dates=train_dates,
                    val_dates=val_dates,
                )
            )

        return splits

    def split_dataframe(
        self,
        df: pd.DataFrame,
        date_col: str = "target_date",
    ) -> Iterator[Tuple[int, pd.DataFrame, pd.DataFrame]]:
        """
        Yields (round_id, train_df, val_df) for each of the 20 rounds.
        Guarantees zero 2019 contamination and zero train/val overlap.
        """
        if df.empty:
            raise ValueError("Input DataFrame is empty")
        if date_col not in df.columns:
            raise KeyError(f"Date column '{date_col}' not found in dataframe")

        # Convert date column to python date objects
        dates_series = pd.to_datetime(df[date_col]).dt.date

        # Check year whitelist on dataframe
        years = pd.to_datetime(df[date_col]).dt.year.unique()
        verify_year_whitelist(years, "BlockCrossValidator.split_dataframe")

        splits = self.split_blocks()

        for split in splits:
            val_mask = dates_series.isin(split.val_dates)
            train_mask = dates_series.isin(split.train_dates)

            train_df = df[train_mask].copy().reset_index(drop=True)
            val_df = df[val_mask].copy().reset_index(drop=True)

            # Re-verify zero index/date overlap
            val_date_set = set(pd.to_datetime(val_df[date_col]).dt.date.unique())
            train_date_set = set(pd.to_datetime(train_df[date_col]).dt.date.unique())
            overlap = val_date_set.intersection(train_date_set)
            assert len(overlap) == 0, f"Round {split.round_id} has {len(overlap)} overlapping dates!"

            yield split.round_id, train_df, val_df


def run_block_cv(
    df: pd.DataFrame,
    fit_fn: Callable[[pd.DataFrame], Any],
    eval_fn: Callable[[Any, pd.DataFrame], Dict[str, float]],
    date_col: str = "target_date",
    n_rounds: int = DEFAULT_N_ROUNDS,
    holdout_ratio: float = DEFAULT_HOLDOUT_RATIO,
    seed: int = DEFAULT_SEED,
) -> Dict[str, Any]:
    """
    Executes 20-round Block-CV loop.
    CRITICAL CONSTRAINT: Model refitting (fit_fn) is called STRICTLY inside each round.
    """
    # Enforce airgap on dataset
    years = pd.to_datetime(df[date_col]).dt.year.unique()
    verify_year_whitelist(years, "run_block_cv input dataframe")

    cv = BlockCrossValidator(
        n_rounds=n_rounds,
        holdout_ratio=holdout_ratio,
        seed=seed,
    )

    round_results: List[Dict[str, Any]] = []

    for round_id, train_df, val_df in cv.split_dataframe(df, date_col=date_col):
        # 1. Refit model STRICTLY inside the loop on train_df (90% blocks)
        model = fit_fn(train_df)

        # 2. Evaluate model on val_df (10% holdout blocks)
        metrics = eval_fn(model, val_df)

        result_entry = {
            "round_id": round_id,
            "train_samples": len(train_df),
            "val_samples": len(val_df),
            **metrics,
        }
        round_results.append(result_entry)

    # Aggregate metric summary across rounds
    metric_keys = [k for k in round_results[0].keys() if k not in ("round_id", "train_samples", "val_samples")]
    summary: Dict[str, Dict[str, float]] = {}

    for k in metric_keys:
        vals = [r[k] for r in round_results if isinstance(r[k], (int, float)) and not math.isnan(r[k])]
        if vals:
            summary[k] = {
                "mean": float(np.mean(vals)),
                "std": float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0,
                "min": float(np.min(vals)),
                "max": float(np.max(vals)),
            }

    return {
        "n_rounds": n_rounds,
        "seed": seed,
        "holdout_ratio": holdout_ratio,
        "round_results": round_results,
        "summary": summary,
    }
