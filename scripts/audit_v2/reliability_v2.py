#!/usr/bin/env python3
"""
scripts/audit_v2/reliability_v2.py:
P4-BLIND-AUDIT-V2R01 Category 2 V2.0 Evaluation Ruler Upgrade (Read-Only Offline Diagnosis).

Statutory & Mandate Context:
- Mandate: docs/audit/P4-BLIND-AUDIT-V2R01_V2尺子升级_开发任务单_20261021.md (including §11 Rulings)
- Proposal: docs/audit/第二类_V2尺子升级_方案书_20261021.md
- Scope: 2019 dual-station (KORD, KMIA) x 11 leads (12h-72h) = 22 frozen settlement cells.
- Core Principle: Change only the evaluation ruler, NEVER retrain the model, NO writing to pkl/manifest.
- Tasks:
  - Task A (Q2+Q3): s_oos N_eff dynamic asymmetric F-bands (Finf & Fstd side-by-side, continuous float neff).
  - Task B (Q4): KS + Cramér-von Mises (CvM) dual uniformity test under Scheme B (reject only if both p < 0.05).
  - Task C (Q5): Fixed 2°F bracket ladder ECE (Scheme A: daily local ladder with 100% coverage) + bin sensitivity.
  - Task D (Q6): PIT variance (ref 1/12) + 10-bin histogram proportion description (pit_hist_b01..b10).
- Pure raw values and code-lowered booleans emitted; pass/fail verdicts left to reviewer.
"""

import argparse
import hashlib
import json
import logging
import math
from pathlib import Path
import sys
from typing import Any, Callable, Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd
import scipy.stats as stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.metrics.calibration_audit import compute_weighted_ece
from src.utils.airgap import verify_year_whitelist

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reliability_v2")

AUDIT_ARRAYS_FILE = PROJECT_ROOT / "data" / "processed" / "audit_arrays" / "2019_oos_p4_settlement_arrays.parquet"
V1_STATS_FILE = PROJECT_ROOT / "evidence" / "p4_2019_settlement_statistics.csv"
CLIMATE_CALIB_FILE = PROJECT_ROOT / "evidence" / "p4_active10_climate_calibration.json"
MANIFEST_FILE = PROJECT_ROOT / "data" / "models" / "manifest.json"

EVIDENCE_V2_DIR = PROJECT_ROOT / "evidence" / "audit_v2"
OUT_METRICS_CSV = EVIDENCE_V2_DIR / "p4blind_v2r01_metrics.csv"
OUT_COMPARISON_CSV = EVIDENCE_V2_DIR / "p4blind_v2r01_comparison.csv"

LEADS = [12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72]
STATIONS = ["KORD", "KMIA"]


def construct_model_cdf(
    mu: float,
    sigma: float,
    family: str,
    shape_params: Dict[str, Any],
) -> Callable[[float], float]:
    """Construct analytical cumulative distribution function (CDF) for predictive distribution."""
    sig_safe = max(1e-6, float(sigma))

    if family == "johnsonsu" and shape_params and "gamma" in shape_params:
        g = float(shape_params["gamma"])
        d = float(shape_params["delta"])
        xi = float(shape_params["xi"])
        lam = float(shape_params["lambda"])

        def cdf_johnson(x: float) -> float:
            z_std = (x - mu) / sig_safe
            arg = (z_std - xi) / lam
            val = g + d * math.asinh(arg)
            return float(stats.norm.cdf(val))

        return cdf_johnson

    def cdf_gaussian(x: float) -> float:
        return float(stats.norm.cdf((x - mu) / sig_safe))

    return cdf_gaussian


def compute_equal_freq_ece(
    predicted_probs: Sequence[float],
    actual_hits: Sequence[int],
    num_bins: int = 10,
) -> float:
    """Compute quantile-based Equal-Frequency ECE (optional auxiliary check per §11-Q2)."""
    p_arr = np.asarray(predicted_probs, dtype=np.float64)
    y_arr = np.asarray(actual_hits, dtype=np.int32)
    if len(p_arr) == 0:
        return 0.0

    quantiles = np.linspace(0.0, 1.0, num_bins + 1)
    bin_edges = np.quantile(p_arr, quantiles)
    # Deduplicate edges if identical quantiles occur
    bin_edges = np.unique(bin_edges)
    if len(bin_edges) < 2:
        return float(abs(np.mean(p_arr) - np.mean(y_arr)))

    total_samples = len(p_arr)
    weighted_err = 0.0

    for i in range(len(bin_edges) - 1):
        low, high = bin_edges[i], bin_edges[i + 1]
        mask = (p_arr >= low) & (p_arr <= high) if i == len(bin_edges) - 2 else (p_arr >= low) & (p_arr < high)
        count = int(np.sum(mask))
        if count > 0:
            mean_pred = float(np.mean(p_arr[mask]))
            hit_rate = float(np.mean(y_arr[mask]))
            weighted_err += abs(mean_pred - hit_rate) * count

    return float(weighted_err / total_samples)


def evaluate_cell_v2(
    cell_name: str,
    df_cell: pd.DataFrame,
    climate_calib: Dict[str, Any],
) -> Dict[str, Any]:
    """Evaluate V2.0 metrics for a single settlement cell across Tasks A, B, C, D."""
    station, lead_str, _ = cell_name.split("_")
    lead_hours = int(lead_str.replace("h", ""))

    # Ensure chronological order
    df_cell = df_cell.sort_values("target_date").reset_index(drop=True)
    n = len(df_cell)
    y_obs = df_cell["tmax_f"].to_numpy(dtype=np.float64)
    mu_calib = df_cell["mu_calib"].to_numpy(dtype=np.float64)
    sig_calib = df_cell["sigma_calib"].to_numpy(dtype=np.float64)
    pit_u = df_cell["pit_u"].to_numpy(dtype=np.float64)

    # ---------------------------------------------------------
    # Task A (Q2 + Q3): s_oos and N_eff Dynamic Asymmetric F-Bands
    # ---------------------------------------------------------
    e = y_obs - mu_calib
    s_oos = float(np.var(e, ddof=1) / np.mean(sig_calib ** 2))

    if len(e) > 1:
        corr_val = float(np.corrcoef(e[:-1], e[1:])[0, 1])
        rho1 = float(np.clip(corr_val, 0.0, 0.99))
    else:
        rho1 = 0.0

    neff = float(n * (1.0 - rho1) / (1.0 + rho1))

    # Float neff passed directly per Ruling Q4
    finf_lo = float(stats.chi2.ppf(0.025, neff) / neff)
    finf_hi = float(stats.chi2.ppf(0.975, neff) / neff)
    finf_in = bool(finf_lo <= s_oos <= finf_hi)

    fstd_lo = float(stats.f.ppf(0.025, neff, n - 1))
    fstd_hi = float(stats.f.ppf(0.975, neff, n - 1))
    fstd_in = bool(fstd_lo <= s_oos <= fstd_hi)

    # ---------------------------------------------------------
    # Task B (Q4): KS + CvM Dual Uniformity Test (Scheme B)
    # ---------------------------------------------------------
    ks_res = stats.kstest(pit_u, "uniform")
    ks_stat = float(ks_res.statistic)
    ks_p = float(ks_res.pvalue)

    cvm_res = stats.cramervonmises(pit_u, "uniform")
    cvm_stat = float(cvm_res.statistic)
    cvm_p = float(cvm_res.pvalue)

    # Scheme B: Reject only if BOTH are strictly significant (p < 0.05)
    reject_uniform = bool((ks_p < 0.05) and (cvm_p < 0.05))

    # ---------------------------------------------------------
    # Task C (Q5): Fixed 2°F Bracket Ladder ECE + Bin Sensitivity
    # ---------------------------------------------------------
    # Scheme A (Ruling Q1): Daily local 2°F ladder with 100% full coverage
    probs_2f: List[float] = []
    hits_2f: List[int] = []

    # Scheme B (V1 baseline): 7 discrete 1°F brackets around round(mu)
    probs_7bin_v1: List[float] = []
    hits_7bin_v1: List[int] = []

    sum_probs_dev_list: List[float] = []

    for i in range(n):
        season = df_cell.at[i, "season"]
        st_season = climate_calib.get(station, {}).get("seasons", {}).get(season, {})
        family = st_season.get("selected_family", "gaussian")
        shape_p = st_season.get("shape_params", {}) or {}

        cdf_fn = construct_model_cdf(mu_calib[i], sig_calib[i], family, shape_p)

        c0 = int(round(mu_calib[i]))
        y_i = y_obs[i]

        # 1. Fixed 2°F Ladder (Polymarket US architecture: 9 interior 2°F brackets + 2 catch-alls)
        # Center bracket: [c0 - 1, c0 + 1)
        # 4 brackets left: [c0 - 3, c0 - 1), [c0 - 5, c0 - 3), [c0 - 7, c0 - 5), [c0 - 9, c0 - 7)
        # 4 brackets right: [c0 + 1, c0 + 3), [c0 + 3, c0 + 5), [c0 + 5, c0 + 7), [c0 + 7, c0 + 9)
        # Left catch-all: [-inf, c0 - 9)
        # Right catch-all: [c0 + 9, +inf)
        lower_bound = c0 - 9
        upper_bound = c0 + 9

        day_probs = []
        day_hits = []

        # Left catch-all
        p_left = float(np.clip(cdf_fn(lower_bound), 0.0, 1.0))
        h_left = 1 if y_i < lower_bound else 0
        day_probs.append(p_left)
        day_hits.append(h_left)

        # 9 interior 2°F brackets
        for k in range(9):
            b_lo = lower_bound + 2 * k
            b_hi = b_lo + 2
            p_k = float(np.clip(cdf_fn(b_hi) - cdf_fn(b_lo), 0.0, 1.0))
            h_k = 1 if (b_lo <= y_i < b_hi) else 0
            day_probs.append(p_k)
            day_hits.append(h_k)

        # Right catch-all
        p_right = float(np.clip(1.0 - cdf_fn(upper_bound), 0.0, 1.0))
        h_right = 1 if y_i >= upper_bound else 0
        day_probs.append(p_right)
        day_hits.append(h_right)

        sum_probs = sum(day_probs)
        sum_probs_dev_list.append(abs(sum_probs - 1.0))

        probs_2f.extend(day_probs)
        hits_2f.extend(day_hits)

        # 2. V1 7-bin ±3°F recreation
        for k_v1 in range(-3, 4):
            bk = c0 + k_v1
            p_v1 = float(max(0.0, cdf_fn(bk + 0.5) - cdf_fn(bk - 0.5)))
            h_v1 = 1 if (bk - 0.5 <= y_i < bk + 0.5) else 0
            probs_7bin_v1.append(p_v1)
            hits_7bin_v1.append(h_v1)

    # Compute ECEs under different binning specifications
    ece_2f = compute_weighted_ece(probs_2f, hits_2f, num_bins=20)
    ece_7bin_v1 = compute_weighted_ece(probs_7bin_v1, hits_7bin_v1, num_bins=20)
    ece_bins10 = compute_weighted_ece(probs_2f, hits_2f, num_bins=10)
    ece_bins20 = compute_weighted_ece(probs_2f, hits_2f, num_bins=20)  # equal-width 20-bin on 2°F ladder

    ece_set = [ece_2f, ece_7bin_v1, ece_bins10, ece_bins20]
    ece_range = float(max(ece_set) - min(ece_set))

    # Optional auxiliary true equal-frequency quantile ECE per §11-Q2
    ece_eqfreq_q10 = compute_equal_freq_ece(probs_2f, hits_2f, num_bins=10)

    # ---------------------------------------------------------
    # Task D (Q6): PIT Variance and 10-Bin Histogram Proportions
    # ---------------------------------------------------------
    pit_mean = float(np.mean(pit_u))
    pit_var = float(np.var(pit_u, ddof=1))

    hist_counts, _ = np.histogram(pit_u, bins=10, range=(0.0, 1.0))
    hist_props = hist_counts / float(n)

    res: Dict[str, Any] = {
        "station": station,
        "lead_hours": lead_hours,
        "cell": cell_name,
        "n": n,
        "s_oos": round(s_oos, 6),
        "rho1": round(rho1, 6),
        "neff": round(neff, 4),
        "finf_lo": round(finf_lo, 4),
        "finf_hi": round(finf_hi, 4),
        "finf_in": finf_in,
        "fstd_lo": round(fstd_lo, 4),
        "fstd_hi": round(fstd_hi, 4),
        "fstd_in": fstd_in,
        "ks_stat": round(ks_stat, 6),
        "ks_p": round(ks_p, 6),
        "cvm_stat": round(cvm_stat, 6),
        "cvm_p": round(cvm_p, 6),
        "reject_uniform": reject_uniform,
        "ece_2f": round(ece_2f, 6),
        "ece_7bin_v1": round(ece_7bin_v1, 6),
        "ece_bins10": round(ece_bins10, 6),
        "ece_bins20": round(ece_bins20, 6),
        "ece_range": round(ece_range, 6),
        "pit_mean": round(pit_mean, 6),
        "pit_var": round(pit_var, 6),
        "max_prob_dev": max(sum_probs_dev_list),
        "ece_eqfreq_q10": round(ece_eqfreq_q10, 6),
    }

    # Add 10 proportion columns pit_hist_b01..b10 (Ruling Q5)
    for b_idx, prop in enumerate(hist_props, start=1):
        res[f"pit_hist_b{b_idx:02d}"] = round(float(prop), 6)

    return res


def compute_file_sha256(filepath: Path) -> str:
    """Compute standard SHA-256 hex digest for a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def run_v2_evaluation() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Execute complete V2.0 evaluation pipeline on all 22 cells."""
    logger.info("=== Running P4-BLIND-AUDIT-V2R01 V2.0 Ruler Upgrade Evaluation ===")

    # Verify input data
    verify_year_whitelist([2019], "run_v2_evaluation")
    if not AUDIT_ARRAYS_FILE.exists():
        raise FileNotFoundError(f"Missing required audit arrays file: {AUDIT_ARRAYS_FILE}")
    if not V1_STATS_FILE.exists():
        raise FileNotFoundError(f"Missing V1 settlement statistics file: {V1_STATS_FILE}")

    df_arrays = pd.read_parquet(AUDIT_ARRAYS_FILE)
    df_v1 = pd.read_csv(V1_STATS_FILE)
    climate_calib = json.loads(CLIMATE_CALIB_FILE.read_text(encoding="utf-8"))

    metrics_rows = []
    cells_order = []
    for st in STATIONS:
        for lead in LEADS:
            cells_order.append(f"{st}_{lead}h_tmax")

    for cell in cells_order:
        df_cell = df_arrays[df_arrays["cell"] == cell]
        if df_cell.empty:
            logger.warning("No data found for cell %s", cell)
            continue
        m_dict = evaluate_cell_v2(cell, df_cell, climate_calib)
        metrics_rows.append(m_dict)

    df_metrics = pd.DataFrame(metrics_rows)

    # Build comparison dataframe against V1
    comp_rows = []
    v1_map = {row["cell"]: row for _, row in df_v1.iterrows()}

    for _, row_m in df_metrics.iterrows():
        cell = row_m["cell"]
        row_v1 = v1_map.get(cell, {})

        v1_s_oos_pass = bool(row_v1.get("s_oos_pass", False))
        v2_finf_in = bool(row_m["finf_in"])
        v2_fstd_in = bool(row_m["fstd_in"])

        v1_ks_pass = bool(row_v1.get("ks_pass", False))
        v2_reject_uniform = bool(row_m["reject_uniform"])
        v2_uniform_not_reject = not v2_reject_uniform

        # Changed status indicator flags
        s_oos_rescued_by_fstd = bool((not v1_s_oos_pass) and v2_fstd_in)
        s_oos_rescued_by_finf = bool((not v1_s_oos_pass) and v2_finf_in)
        uniform_rescued = bool((not v1_ks_pass) and v2_uniform_not_reject)

        comp_rows.append({
            "station": row_m["station"],
            "lead_hours": row_m["lead_hours"],
            "cell": cell,
            "v1_s_oos": float(row_v1.get("s_oos", float("nan"))),
            "v1_s_oos_pass": v1_s_oos_pass,
            "v2_s_oos": row_m["s_oos"],
            "v2_neff": row_m["neff"],
            "v2_finf_lo": row_m["finf_lo"],
            "v2_finf_hi": row_m["finf_hi"],
            "v2_finf_in": v2_finf_in,
            "v2_fstd_lo": row_m["fstd_lo"],
            "v2_fstd_hi": row_m["fstd_hi"],
            "v2_fstd_in": v2_fstd_in,
            "s_oos_rescued_by_finf": s_oos_rescued_by_finf,
            "s_oos_rescued_by_fstd": s_oos_rescued_by_fstd,
            "v1_ks_stat": float(row_v1.get("ks_stat", float("nan"))),
            "v1_ks_p_val": float(row_v1.get("ks_p_val", float("nan"))),
            "v1_ks_pass": v1_ks_pass,
            "v2_cvm_stat": row_m["cvm_stat"],
            "v2_cvm_p": row_m["cvm_p"],
            "v2_reject_uniform": v2_reject_uniform,
            "uniform_rescued": uniform_rescued,
            "v1_ece_7bin": float(row_v1.get("ece_7bin", float("nan"))),
            "v1_ece_pass": bool(row_v1.get("ece_7bin_pass", False)),
            "v2_ece_2f": row_m["ece_2f"],
            "v2_ece_range": row_m["ece_range"],
            "v1_pit_mean": float(row_v1.get("pit_mean", float("nan"))),
            "v1_pit_mean_pass": bool(row_v1.get("pit_mean_pass", False)),
            "v2_pit_var": row_m["pit_var"],
            "v1_coverage_90": float(row_v1.get("coverage_90", float("nan"))),
            "v1_coverage_90_pass": bool(row_v1.get("coverage_90_pass", False)),
            "v1_all_gates_pass": bool(row_v1.get("all_gates_pass", False)),
        })

    df_comp = pd.DataFrame(comp_rows)

    # Save CSVs
    EVIDENCE_V2_DIR.mkdir(parents=True, exist_ok=True)
    df_metrics.to_csv(OUT_METRICS_CSV, index=False)
    df_comp.to_csv(OUT_COMPARISON_CSV, index=False)
    logger.info("Saved V2 metrics CSV to %s (%d rows)", OUT_METRICS_CSV, len(df_metrics))
    logger.info("Saved V2 comparison CSV to %s (%d rows)", OUT_COMPARISON_CSV, len(df_comp))

    return df_metrics, df_comp


def main():
    parser = argparse.ArgumentParser(description="P4-BLIND-AUDIT-V2R01 Category 2 V2.0 Ruler Upgrade Evaluation.")
    parser.add_argument("--run", action="store_true", help="Execute complete V2.0 ruler evaluation.")
    args = parser.parse_args()

    df_metrics, df_comp = run_v2_evaluation()

    print("\n" + "=" * 80)
    print("P4-BLIND-AUDIT-V2R01 EXECUTION SUMMARY (V2.0 RULER UPGRADE)")
    print("=" * 80)

    print("\n--- Key Changes: s_oos F-Bands vs V1 Fixed Band ---")
    finf_passes = int(df_comp["v2_finf_in"].sum())
    fstd_passes = int(df_comp["v2_fstd_in"].sum())
    v1_soos_passes = int(df_comp["v1_s_oos_pass"].sum())
    print(f"  V1 Fixed [0.85, 1.15] Pass Count: {v1_soos_passes} / 22")
    print(f"  V2 Finf Asymmetric In Count    : {finf_passes} / 22 (Rescued: {int(df_comp['s_oos_rescued_by_finf'].sum())})")
    print(f"  V2 Fstd Asymmetric In Count    : {fstd_passes} / 22 (Rescued: {int(df_comp['s_oos_rescued_by_fstd'].sum())})")

    print("\n--- Key Changes: Uniformity (KS vs KS+CvM Scheme B) ---")
    v1_ks_passes = int(df_comp["v1_ks_pass"].sum())
    v2_not_reject = int((~df_comp["v2_reject_uniform"]).sum())
    rescued_uniform = int(df_comp["uniform_rescued"].sum())
    print(f"  V1 KS Pass Count               : {v1_ks_passes} / 22")
    print(f"  V2 Uniform Not Rejected Count  : {v2_not_reject} / 22 (Rescued: {rescued_uniform})")

    print("\n--- ECE Comparison (V1 7-bin ±3°F vs V2 2°F Ladder) ---")
    mean_ece_v1 = float(df_comp["v1_ece_7bin"].mean())
    mean_ece_2f = float(df_comp["v2_ece_2f"].mean())
    mean_ece_range = float(df_comp["v2_ece_range"].mean())
    print(f"  Mean V1 7-bin ECE              : {mean_ece_v1:.4f} ({mean_ece_v1*100:.2f}%)")
    print(f"  Mean V2 2°F Ladder ECE         : {mean_ece_2f:.4f} ({mean_ece_2f*100:.2f}%)")
    print(f"  Mean ECE Sensitivity Range     : {mean_ece_range:.4f} ({mean_ece_range*100:.2f}%)")

    print("\n--- Artifact Checksums ---")
    script_path = Path(__file__).resolve()
    print(f"Script SHA-256    : {compute_file_sha256(script_path)}  ({script_path.relative_to(PROJECT_ROOT)})")
    print(f"Metrics SHA-256   : {compute_file_sha256(OUT_METRICS_CSV)}  ({OUT_METRICS_CSV.relative_to(PROJECT_ROOT)})")
    print(f"Comparison SHA-256: {compute_file_sha256(OUT_COMPARISON_CSV)}  ({OUT_COMPARISON_CSV.relative_to(PROJECT_ROOT)})")
    print(f"Arrays SHA-256    : {compute_file_sha256(AUDIT_ARRAYS_FILE)}  ({AUDIT_ARRAYS_FILE.relative_to(PROJECT_ROOT)})")
    print(f"V1 Stats SHA-256  : {compute_file_sha256(V1_STATS_FILE)}  ({V1_STATS_FILE.relative_to(PROJECT_ROOT)})")


if __name__ == "__main__":
    main()
