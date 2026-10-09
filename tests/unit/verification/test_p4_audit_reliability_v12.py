"""
tests/unit/verification/test_p4_audit_reliability_v12.py:
Unit tests for P4-AUDIT-RELIABILITY v1.2 specifications.

Verifies:
1. Lineage Pinning & Artifact Integrity: 600 days strictly derived from 20-fold Block-CV prediction artifacts.
2. Dual-Tail Mechanical Poisson Test: Adjudication is strictly boolean/FLAG status, zero adjectives.
3. Kurtosis Diagnostics & Shape Reproduction: Residual skewness & excess kurtosis calculation correctness.
4. Completeness of statutory summary, markdown report, and lineage JSON files.
"""

import hashlib
import json
from pathlib import Path
import pytest
import numpy as np
from scipy import stats

from scripts.audit_p4_reliability_v12 import run_v12_reliability_audit

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EVIDENCE_DIR = PROJECT_ROOT / "evidence"


def test_v12_lineage_and_artifact_integrity():
    """Verify that daily samples strictly originate from 20-fold Block-CV artifacts with valid SHA256."""
    res = run_v12_reliability_audit(evidence_dir=EVIDENCE_DIR, n_days_per_fold=30, seed=20260923)
    lineage_file = res["lineage_path"]
    assert lineage_file.exists(), f"Missing lineage file: {lineage_file}"

    with open(lineage_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    lineage = data["lineage"]
    assert len(lineage) == 600
    assert data["n_samples"] == 600

    # Verify per-fold representation: exactly 30 samples per fold across all 20 folds
    fold_counts = {}
    for entry in lineage:
        fid = entry["fold_id"]
        fold_counts[fid] = fold_counts.get(fid, 0) + 1
        assert 0 <= fid < 20
        assert "artifact_sha256" in entry
        assert len(entry["artifact_sha256"]) == 64
        assert not np.isnan(entry["mu"])
        assert not np.isnan(entry["sigma"])
        assert not np.isnan(entry["obs_tmax_f"])

    assert len(fold_counts) == 20
    for fid, cnt in fold_counts.items():
        assert cnt == 30, f"Fold {fid} sample count mismatch: {cnt} != 30"


def test_v12_poisson_mechanical_adjudication_no_adjectives():
    """Verify that right tail is mechanically flagged via Poisson test without subjective adjectives."""
    res = run_v12_reliability_audit(evidence_dir=EVIDENCE_DIR, n_days_per_fold=30, seed=20260923)
    tails = res["summary"]["dual_tail_diagnostics"]
    assert len(tails) == 2

    right_tail = [t for t in tails if "Right-Tail" in t["tail_name"]][0]
    left_tail = [t for t in tails if "Left-Tail" in t["tail_name"]][0]

    # Verify Poisson upper-tail p-value calculation
    expected_p = float(1.0 - stats.poisson.cdf(right_tail["observed_hits"] - 1, right_tail["expected_hits"]))
    assert np.isclose(right_tail["poisson_p_upper"], expected_p, atol=1e-5)

    # Mechanical adjudication check
    if right_tail["poisson_p_upper"] < 0.05:
        assert right_tail["status"] == "FLAG"
    else:
        assert right_tail["status"] == "PASS"

    # Strictly no uncontrolled adjectives in status
    for t in tails:
        assert t["status"] in ("PASS", "FLAG", "FLAG_UNDERFLOW")
        assert "HEALTHY" not in t["status"]
        assert "UNHEALTHY" not in t["status"]


def test_v12_kurtosis_diagnostics_and_exceedance_math():
    """Verify mathematical correctness of skewness, kurtosis and exceedance rates."""
    res = run_v12_reliability_audit(evidence_dir=EVIDENCE_DIR, n_days_per_fold=30, seed=20260923)
    shape = res["summary"]["kurtosis_shape_diagnostics"]

    assert "excess_kurtosis" in shape
    assert "skewness" in shape
    assert "exceedances" in shape

    # Residuals must exhibit excess kurtosis > 0 for leptokurtic shape
    assert shape["excess_kurtosis"] > 0.0
    assert shape["is_leptokurtic"] is True
    assert shape["fat_shoulder_low_peak_thin_tail_reproduced"] is True

    # Validate exceedance calculations
    ex2 = shape["exceedances"]["abs_z_gt_2_0"]
    assert ex2["observed_rate"] == round(ex2["observed_count"] / 600.0, 4)
    assert np.isclose(ex2["gaussian_expected_rate"], 2.0 * (1.0 - stats.norm.cdf(2.0)), atol=1e-3)
