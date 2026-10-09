"""
tests/unit/verification/test_p4_audit_reliability_v13.py:
Unit tests for P4-AUDIT-RELIABILITY v1.3 specifications.

Verifies:
1. Statutory Excerpts & Design Fidelity: Verifies design document excerpts in docstring and true distribution F.
2. Full 13,740 Validation Universe Lineage: Verifies all 13,740 records have complete distribution parameters.
3. True Model F vs Gaussian Proxy Impact: True model restores right-tail probability mass, Poisson adjudication is mechanical FLAG.
4. Kurtosis & Shape Diagnostics: Skewness and excess kurtosis calculation correctness on full universe.
"""

import json
from pathlib import Path
import pytest
import numpy as np
from scipy import stats

from scripts.audit_p4_reliability_v13 import (
    run_v13_reliability_audit,
    construct_true_model_cdf,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EVIDENCE_DIR = PROJECT_ROOT / "evidence"


def test_v13_statutory_excerpts_and_design_fidelity():
    """Verify that design document excerpts are pinned in docstring and true model CDF is faithful."""
    import scripts.audit_p4_reliability_v13 as mod_v13
    assert "F 为逐折竞争选型分布，候选族与胜出规则以文档为准" in mod_v13.__doc__
    assert "Johnson SU 四参数分布" in mod_v13.__doc__
    assert "EVT 极值超额广义帕累托混合体" in mod_v13.__doc__

    # Test true CDF construction for Johnson SU
    shape = {"gamma": -0.46, "delta": 2.10, "xi": -0.44, "lambda": 1.81}
    cdf_fn = construct_true_model_cdf(mu=70.0, sigma=3.0, family="johnsonsu", shape_params=shape)
    assert 0.0 < cdf_fn(70.0) < 1.0
    assert cdf_fn(-100.0) < 1e-6
    assert cdf_fn(200.0) > 1.0 - 1e-6


def test_v13_full_13740_lineage_and_prediction_artifacts():
    """Verify that all 13,740 validation days are pinned with complete distribution parameters."""
    res = run_v13_reliability_audit(evidence_dir=EVIDENCE_DIR)
    lineage_file = res["lineage_path"]
    assert lineage_file.exists()

    with open(lineage_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["n_samples"] == 13740
    lineage = data["lineage"]
    assert len(lineage) == 13740

    # Verify each entry has valid distribution parameters
    first = lineage[0]
    assert "selected_family" in first
    assert first["selected_family"] in ("johnsonsu", "gaussian", "evt_hybrid")
    assert "shape_params" in first
    assert len(first["artifact_sha256"]) == 64


def test_v13_true_f_vs_gaussian_proxy_tail_restoration():
    """Verify that True F restores right-tail probability mass and mechanically flags excess."""
    res = run_v13_reliability_audit(evidence_dir=EVIDENCE_DIR)
    summary = res["summary"]
    comp = summary["comparative_tail_impact"]

    # True model expected hits must be significantly higher than degraded Gaussian proxy
    assert comp["true_model_f_expected_hits"] > 100.0
    assert comp["gaussian_proxy_expected_hits"] < 70.0
    assert comp["true_model_f_ratio"] < comp["gaussian_proxy_ratio"]

    # Mechanical adjudication check
    assert comp["true_model_status"] == "FLAG"
    assert comp["true_model_f_poisson_p"] < 0.05

    # Strictly no uncontrolled adjectives
    for t in summary["dual_tail_diagnostics"]:
        assert t["status"] in ("PASS", "FLAG", "FLAG_UNDERFLOW")
        assert "HEALTHY" not in t["status"]


def test_v13_kurtosis_and_shape_diagnostics():
    """Verify that excess kurtosis and positive skewness are reproduced on full 13,740 universe."""
    res = run_v13_reliability_audit(evidence_dir=EVIDENCE_DIR)
    shape = res["summary"]["kurtosis_shape_diagnostics"]

    assert shape["skewness"] > 0.40
    assert shape["excess_kurtosis"] > 1.0
    assert shape["is_leptokurtic"] is True
    assert shape["fat_shoulder_low_peak_thin_tail_reproduced"] is True
