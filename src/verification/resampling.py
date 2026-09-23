"""
Block Resampling & Cross-Validation Splitter for Time Series Calibration Verification.

Specifications (ADR / P3 alignment):
- 30-day contiguous chronological blocks
- 10% blocks held out per evaluation round (without replacement)
- 20 evaluation rounds
- Fixed reproducible pseudo-random seed: 20260923
- Hard assertion of zero date leakage between held-out test block and training complement
- Reusable split manifest saved at evidence/cv_split_blocks_20rounds.json
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Set
import numpy as np


def generate_30day_blocks(dates: List[str]) -> List[List[str]]:
    """
    Partition chronologically sorted dates into contiguous 30-day blocks.

    Parameters
    ----------
    dates : List[str]
        List of distinct date strings ('YYYY-MM-DD').

    Returns
    -------
    List[List[str]]
        List of blocks, each containing up to 30 consecutive dates.
    """
    sorted_dates = sorted(list(set(dates)))
    block_size = 30
    blocks = [sorted_dates[i : i + block_size] for i in range(0, len(sorted_dates), block_size)]
    return blocks


def generate_cv_split_manifest(
    dates: List[str],
    n_rounds: int = 20,
    holdout_frac: float = 0.10,
    seed: int = 20260923,
) -> List[Dict[str, Any]]:
    """
    Generate reproducible 20-round block CV split manifest.

    Parameters
    ----------
    dates : List[str]
        All available training dates.
    n_rounds : int, default 20
        Number of cross-validation rounds.
    holdout_frac : float, default 0.10
        Fraction of blocks held out per round (10%).
    seed : int, default 20260923
        Fixed random seed.

    Returns
    -------
    List[Dict[str, Any]]
        List of round split dictionaries.
    """
    blocks = generate_30day_blocks(dates)
    n_blocks = len(blocks)
    k_holdout = max(1, int(round(n_blocks * holdout_frac)))

    rng = np.random.RandomState(seed)
    rounds_manifest = []

    for r in range(n_rounds):
        test_block_indices = sorted(rng.choice(n_blocks, size=k_holdout, replace=False).tolist())
        test_dates_set: Set[str] = set()
        for idx in test_block_indices:
            test_dates_set.update(blocks[idx])

        test_dates = sorted(list(test_dates_set))
        train_dates = sorted(list(set(dates) - test_dates_set))

        # Hard assertion of zero leakage
        overlap = set(test_dates).intersection(set(train_dates))
        assert len(overlap) == 0, f"Round {r} data leakage detected: {len(overlap)} overlapping dates!"

        rounds_manifest.append({
            "round_idx": r,
            "seed": seed,
            "k_holdout_blocks": k_holdout,
            "test_block_indices": test_block_indices,
            "test_dates": test_dates,
            "train_dates": train_dates,
            "n_test_dates": len(test_dates),
            "n_train_dates": len(train_dates),
        })

    return rounds_manifest


def get_or_create_cv_manifest(
    manifest_path: Path,
    dates: List[str],
    n_rounds: int = 20,
    holdout_frac: float = 0.10,
    seed: int = 20260923,
) -> List[Dict[str, Any]]:
    """
    Load existing CV manifest or generate and save if absent.
    """
    manifest_path = Path(manifest_path)
    if manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        # Validate that rounds match
        if len(manifest) == n_rounds:
            return manifest

    manifest = generate_cv_split_manifest(dates, n_rounds=n_rounds, holdout_frac=holdout_frac, seed=seed)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest
