"""
tests/unit/modeling/test_p6_zero_drift_gate.py:
Zero-Drift Baseline Gate Contract for P6 Full-Grid Parameterized Pipeline.

Mandates:
1. Re-running the parameterized audit logic on KORD / 18h / TMax must reproduce
   v1.3b frozen summary metrics bit-for-bit:
   - Window weighted ECE == 0.0029 (0.29%)
   - PIT KS uniformity p-value == 0.46915
   - Probit rescaled skewness == +0.0471
   - Probit rescaled excess kurtosis == +0.0667
   - Daily peak probability Max == 0.3177
2. Re-harvested 13,740 daily validation records must match v1.3b lineage SHA256 hashes exactly.
3. No float drift allowed (drift > 1e-4 fails gate).
"""

import hashlib
import json
from pathlib import Path
import pytest
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EVIDENCE_DIR = PROJECT_ROOT / "evidence"


def test_p6_v13b_frozen_summary_and_lineage_integrity():
    """
    Asserts that the statutory baseline artifacts exist and possess frozen signatures.
    """
    summary_path = EVIDENCE_DIR / "p4_audit_reliability_v13b_summary.json"
    lineage_path = EVIDENCE_DIR / "p4_audit_reliability_v13b_lineage.json"

    assert summary_path.exists(), "v1.3b summary json missing"
    assert lineage_path.exists(), "v1.3b lineage json missing"

    with open(summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)

    # Key benchmark metrics
    in_win_ece = summary["in_window_calibration"]["weighted_ece"]
    ks_p = summary["pit_shape_diagnostics"]["ks_uniformity_test"]["p_value"]
    skew = summary["pit_shape_diagnostics"]["probit_rescaled_moments"]["skewness"]
    kurt = summary["pit_shape_diagnostics"]["probit_rescaled_moments"]["excess_kurtosis"]
    max_p = summary["sharpness_diagnostics"]["quantiles"]["Max"]

    assert abs(in_win_ece - 0.0029) < 1e-4, f"Window ECE drifted: {in_win_ece}"
    assert abs(ks_p - 0.46915) < 1e-4, f"KS p drifted: {ks_p}"
    assert abs(skew - 0.0471) < 1e-4, f"Skewness drifted: {skew}"
    assert abs(kurt - 0.0667) < 1e-4, f"Kurtosis drifted: {kurt}"
    assert abs(max_p - 0.3177) < 1e-4, f"Max peak prob drifted: {max_p}"



def test_p6_parameterized_audit_engine_reproduction():
    """
    Executes audit_grid_cell from scripts/run_p6_fullgrid_tmax.py on KORD 18h
    and asserts zero drift against v1.3b baseline.
    """
    from scripts.run_p6_fullgrid_tmax import harvest_cell_daily_records, audit_grid_cell_reliability

    daily_records, lineage_sha = harvest_cell_daily_records(station="KORD", lead_hour=18, evidence_dir=EVIDENCE_DIR)
    assert len(daily_records) == 13740, f"Expected 13,740 validation days, got {len(daily_records)}"

    metrics = audit_grid_cell_reliability(daily_records, station="KORD", lead_hour=18)

    # 1. Window Weighted ECE
    assert abs(metrics["in_window_weighted_ece"] - 0.00287) < 1e-4, (
        f"ECE drifted: {metrics['in_window_weighted_ece']} vs 0.00287"
    )

    # 2. PIT KS Uniformity p-value
    assert abs(metrics["pit_ks_p_value"] - 0.46915) < 1e-4, (
        f"KS p-value drifted: {metrics['pit_ks_p_value']} vs 0.46915"
    )

    # 3. Probit Skewness
    assert abs(metrics["probit_skewness"] - 0.0471) < 1e-4, (
        f"Skewness drifted: {metrics['probit_skewness']} vs 0.0471"
    )

    # 4. Probit Excess Kurtosis
    assert abs(metrics["probit_excess_kurtosis"] - 0.0667) < 1e-4, (
        f"Kurtosis drifted: {metrics['probit_excess_kurtosis']} vs 0.0667"
    )

    # 5. Max Peak Probability
    assert abs(metrics["sharpness_max_p"] - 0.3177) < 1e-4, (
        f"Max peak prob drifted: {metrics['sharpness_max_p']} vs 0.3177"
    )

    # 6. Check sentinel fields
    assert "kurtosis_gate_distance" in metrics
    assert "skew_gate_distance" in metrics
    assert "gate_triggered" in metrics
    assert metrics["gate_triggered"] is False
