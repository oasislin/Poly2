"""
Unit tests for Block Resampling and Cross-Validation Splitter (R4).
Verifies:
1. Contiguous 30-day block partitioning
2. 20-round generation with seed=20260923
3. Zero-date leakage assertion between test block and training complement
4. Reusable manifest serialization
"""

import json
from pathlib import Path
import pytest
from src.verification.resampling import (
    generate_30day_blocks,
    generate_cv_split_manifest,
    get_or_create_cv_manifest,
)


@pytest.fixture
def synthetic_training_dates():
    # 300 days (10 blocks of 30 days)
    dates = [f"2005-{m:02d}-{d:02d}" for m in range(1, 11) for d in range(1, 31)]
    return sorted(dates)


def test_generate_30day_blocks(synthetic_training_dates):
    blocks = generate_30day_blocks(synthetic_training_dates)
    assert len(blocks) == 10
    for b in blocks:
        assert len(b) == 30
    assert blocks[0][0] == synthetic_training_dates[0]
    assert blocks[-1][-1] == synthetic_training_dates[-1]


def test_cv_split_zero_leakage_and_reproducibility(synthetic_training_dates):
    manifest_1 = generate_cv_split_manifest(
        synthetic_training_dates, n_rounds=20, holdout_frac=0.10, seed=20260923
    )
    manifest_2 = generate_cv_split_manifest(
        synthetic_training_dates, n_rounds=20, holdout_frac=0.10, seed=20260923
    )

    assert len(manifest_1) == 20
    # Deterministic reproducibility
    assert manifest_1 == manifest_2

    # Check zero leakage across all 20 rounds
    for r in manifest_1:
        test_dates = set(r["test_dates"])
        train_dates = set(r["train_dates"])
        assert len(test_dates) > 0
        assert len(train_dates) > 0
        overlap = test_dates.intersection(train_dates)
        assert len(overlap) == 0, f"Round {r['round_idx']} leakage detected!"
        assert test_dates.union(train_dates) == set(synthetic_training_dates)


def test_get_or_create_cv_manifest_persistence(tmp_path, synthetic_training_dates):
    manifest_file = tmp_path / "cv_manifest.json"
    assert not manifest_file.exists()

    m1 = get_or_create_cv_manifest(manifest_file, synthetic_training_dates, n_rounds=5, seed=20260923)
    assert manifest_file.exists()
    assert len(m1) == 5

    m2 = get_or_create_cv_manifest(manifest_file, synthetic_training_dates, n_rounds=5, seed=20260923)
    assert m1 == m2
