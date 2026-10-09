"""
src/verification/p5_gate.py: Formal Entry Point & Public Contract for P5 Reliability Gate.
Specification: ADR-0017 & specs/p5_layer2_scenarios.md (Task D: 主线接线层).

Core Contract:
Mainline training and inference pipelines interact exclusively with `run_reliability_gate`
and consume `GateReport`. No internal P5 pure functions or helper scripts should be directly
imported by callers outside verification.
"""

from dataclasses import dataclass, field
import math
from pathlib import Path
import sys
from typing import Dict, Any, Optional, Union, List

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.standalone_reliability_check import (
    build_dual_track_reliability_table,
    check_monotonicity_and_coverage,
    check_stream_degeneracy,
    brier_skill_score,
    compute_pit_effect_size,
    DataAssetError,
    PhysicsViolationError,
)



@dataclass(frozen=True)
class GateReport:
    """
    Statutory Contract Report returned by P5 reliability gate.
    Mainline training pipeline relies solely on this schema.
    """
    passed: bool
    weighted_ece: float
    ece_ci_lower: float
    ece_ci_upper: float
    bss: float
    ks_stat: float
    ks_pvalue: float
    wilson_coverage_rate: float
    is_degenerate: bool
    error_message: Optional[str] = None
    s_ladder_status: Dict[str, bool] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert gate report into dictionary for logging and serialization."""
        return {
            "passed": self.passed,
            "weighted_ece": self.weighted_ece,
            "ece_ci_lower": self.ece_ci_lower,
            "ece_ci_upper": self.ece_ci_upper,
            "bss": self.bss,
            "ks_stat": self.ks_stat,
            "ks_pvalue": self.ks_pvalue,
            "wilson_coverage_rate": self.wilson_coverage_rate,
            "is_degenerate": self.is_degenerate,
            "error_message": self.error_message,
            "s_ladder_status": dict(self.s_ladder_status),
            "metadata": dict(self.metadata),
        }


def _extract_prediction_df(
    predictions: Union[pd.DataFrame, Dict[str, Any]],
) -> pd.DataFrame:
    """Normalize input predictions into DataFrame containing (p_pred, hit)."""
    if isinstance(predictions, pd.DataFrame):
        df = predictions.copy()
    elif isinstance(predictions, dict):
        df = pd.DataFrame(predictions)
    else:
        raise DataAssetError(f"Unsupported predictions type: {type(predictions)}. Expected DataFrame or dict.")

    if df.empty:
        raise DataAssetError("Input predictions dataset cannot be empty.")

    # Format A: Direct p_pred and hit columns (preserves optional continuous pit track for S5)
    if "p_pred" in df.columns and "hit" in df.columns:
        cols = ["p_pred", "hit"]
        if "pit" in df.columns:
            cols.append("pit")
        return df[cols].copy()

    # Format B: Forecast parameter columns (obs, mu, sigma)
    obs_col = next((c for c in ["obs", "obs_tmax_f", "obs_tmin_f"] if c in df.columns), None)
    mu_col = next((c for c in ["mu", "mu_forecast"] if c in df.columns), None)
    sigma_col = next((c for c in ["sigma", "sigma_forecast"] if c in df.columns), None)

    if obs_col and mu_col and sigma_col:
        obs = df[obs_col].to_numpy(dtype=np.float64)
        mu = df[mu_col].to_numpy(dtype=np.float64)
        sigma = df[sigma_col].to_numpy(dtype=np.float64)

        if np.any(sigma < 0.90):
            raise PhysicsViolationError("Forecast sigma collapsed below physical noise floor 0.90°F.")

        # Compute standard PIT and event probability
        z = (obs - mu) / sigma
        pit = stats.norm.cdf(z)
        hit = (obs >= mu).astype(np.float64)
        return pd.DataFrame({"p_pred": pit, "hit": hit})

    raise DataAssetError(
        f"Predictions DataFrame must contain either ('p_pred', 'hit') or ('obs', 'mu', 'sigma'). "
        f"Available columns: {sorted(list(df.columns))}"
    )


def run_reliability_gate(
    predictions: Union[pd.DataFrame, Dict[str, Any]],
    reference: Optional[pd.DataFrame] = None,
    config: Optional[Dict[str, Any]] = None,
) -> GateReport:
    """
    Execute P5 reliability gate auditing model training quality against calibrated thresholds.

    Args:
        predictions: DataFrame or dict containing model predictions ('p_pred', 'hit') or ('obs', 'mu', 'sigma').
        reference: Optional reference dataset for baseline comparison.
        config: Optional configuration overrides (e.g. max_ece, min_coverage, max_ks_stat).

    Returns:
        GateReport: Structured, immutable statutory audit report.
    """
    cfg = config or {}
    max_ece = float(cfg.get("max_ece", 0.05))
    min_coverage = float(cfg.get("min_coverage", 0.90))
    min_bss = float(cfg.get("min_bss", 0.0))
    max_ks_stat = float(cfg.get("max_ks_stat", 0.08))


    # 1. Parse and validate input dataset
    try:
        df_pred = _extract_prediction_df(predictions)
    except Exception as e:
        return GateReport(
            passed=False,
            weighted_ece=1.0,
            ece_ci_lower=1.0,
            ece_ci_upper=1.0,
            bss=-1.0,
            ks_stat=1.0,
            ks_pvalue=0.0,
            wilson_coverage_rate=0.0,
            is_degenerate=False,
            error_message=f"Input validation failure: {str(e)}",
            s_ladder_status={
                "S1_input_defense": False,
                "S2_calibration_ece": False,
                "S3_monotonicity": False,
                "S4_wilson_coverage": False,
                "S5_ks_goodness": False,
            },
        )

    p_arr = df_pred["p_pred"].to_numpy(dtype=np.float64)
    h_arr = df_pred["hit"].to_numpy(dtype=np.float64)

    # 2. Stream-level degeneracy tripwire (Spec Revision #4 Annex B2)
    try:
        check_stream_degeneracy(p_arr)
    except DataAssetError as de:
        return GateReport(
            passed=False,
            weighted_ece=1.0,
            ece_ci_lower=1.0,
            ece_ci_upper=1.0,
            bss=-1.0,
            ks_stat=1.0,
            ks_pvalue=0.0,
            wilson_coverage_rate=0.0,
            is_degenerate=True,
            error_message=str(de),
            s_ladder_status={
                "S1_input_defense": False,
                "S2_calibration_ece": False,
                "S3_monotonicity": False,
                "S4_wilson_coverage": False,
                "S5_ks_goodness": False,
            },
            metadata={"row_count": len(p_arr)},
        )

    # 3. Dual-track binning & table construction
    dual_res = build_dual_track_reliability_table(df_pred, num_bins=20, min_n_per_bin=30)
    decision_table = dual_res["decision_table"]
    weighted_ece = float(dual_res["weighted_ece"])
    ece_ci_lower = float(dual_res["ece_ci_lower"])
    ece_ci_upper = float(dual_res["ece_ci_upper"])

    # 4. Monotonicity & Wilson coverage audit (GATE-L2-02)
    mono_res = check_monotonicity_and_coverage(decision_table)
    wilson_coverage = float(mono_res["coverage_rate"])
    monotonicity_violations = int(mono_res["violations"])

    # 5. Brier Skill Score calculation
    bs_model = float(np.mean((p_arr - h_arr) ** 2))
    p_clim = float(np.mean(h_arr))
    bs_clim = float(np.mean((p_clim - h_arr) ** 2))
    bss_val = float(brier_skill_score(bs_model, bs_clim))

    # 6. KS goodness-of-fit & PIT effect size (Section 2.2)
    pit_eval = df_pred["pit"].to_numpy(dtype=np.float64) if "pit" in df_pred.columns else p_arr
    ks_res = stats.kstest(pit_eval, "uniform")
    ks_stat = float(ks_res.statistic)
    ks_pvalue = float(ks_res.pvalue)
    d_effect, alert = compute_pit_effect_size(pit_eval)

    # 7. S-Ladder pass predicates
    s1_pass = True
    s2_pass = bool(weighted_ece <= max_ece)
    s3_pass = bool(monotonicity_violations == 0)
    s4_pass = bool(wilson_coverage >= min_coverage and not mono_res["alarms"])
    s5_pass = bool(not alert and ks_stat <= max_ks_stat)


    s_ladder = {
        "S1_input_defense": s1_pass,
        "S2_calibration_ece": s2_pass,
        "S3_monotonicity": s3_pass,
        "S4_wilson_coverage": s4_pass,
        "S5_ks_goodness": s5_pass,
    }

    overall_pass = bool(all(s_ladder.values()) and bss_val >= min_bss)

    return GateReport(
        passed=overall_pass,
        weighted_ece=weighted_ece,
        ece_ci_lower=ece_ci_lower,
        ece_ci_upper=ece_ci_upper,
        bss=bss_val,
        ks_stat=ks_stat,
        ks_pvalue=ks_pvalue,
        wilson_coverage_rate=wilson_coverage,
        is_degenerate=False,
        error_message=None if overall_pass else "Reliability gate thresholds not satisfied",
        s_ladder_status=s_ladder,
        metadata={
            "sample_count": len(df_pred),
            "monotonicity_violations": monotonicity_violations,
            "alarms": mono_res["alarms"],
            "decision_bins_count": len(decision_table),
        },
    )
