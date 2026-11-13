#!/usr/bin/env python3
"""
scripts/compute_p8_oos_and_shape_calibration.py:
P8-ALGO-REVIEW G-9 / G-10 Statutory Recalibration Engine:
1. s_oos re-estimation across all 22 statutory grid cells using 2000-2018 20-fold Block-CV OOF residuals.
2. Fifth dimension (shape distance Δ = ECE_family - ECE_moment_matched_gaussian) calibration across
   16 strata (station x season x early/late period), dual-track reported (inw & w20), with date-clustered Bootstrap 95% CI.
"""

from datetime import date
import json
import math
from pathlib import Path
import sys
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy import integrate, stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_p6_fullgrid_tmax import (
    EVIDENCE_DIR,
    STRATA_EDGES,
    construct_true_model_cdf,
    harvest_cell_daily_records,
)
from src.modeling.resampling import evaluate_evt_tail_pdf
from src.prediction.discrete_bin_engine import DiscreteBinEngine

AUTHORIZED_STATIONS = ["KORD", "KMIA"]
AUTHORIZED_LEAD_HOURS = [12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72]
SEASONS = ["Winter", "Spring", "Summer", "Autumn"]


def get_season(dt_str: str) -> str:
    """Derive meteorological season from ISO date string YYYY-MM-DD."""
    m = int(dt_str[5:7])
    if m in (12, 1, 2):
        return "Winter"
    elif m in (3, 4, 5):
        return "Spring"
    elif m in (6, 7, 8):
        return "Summer"
    return "Autumn"


def get_period(lead: int) -> str:
    """Derive period stratum: early (<= 30h) vs late (> 30h)."""
    return "early" if lead <= 30 else "late"


def compute_moments_z(family: str, shape_params: Dict[str, Any]) -> Tuple[float, float]:
    """Compute E[Z] and Std(Z) = sqrt(Var(Z)) for standardized variable Z."""
    if family == "gaussian" or not shape_params:
        return 0.0, 1.0
    elif family == "johnsonsu":
        g = float(shape_params["gamma"])
        d = float(shape_params["delta"])
        xi = float(shape_params["xi"])
        lam = float(shape_params["lambda"])
        m, v = stats.johnsonsu.stats(a=g, b=d, loc=xi, scale=lam, moments="mv")
        return float(m), float(math.sqrt(max(1e-8, float(v))))
    elif family == "evt_hybrid":
        mean_z, _ = integrate.quad(
            lambda z: z * evaluate_evt_tail_pdf(z, shape_params), -25.0, 25.0
        )
        sq_z, _ = integrate.quad(
            lambda z: z**2 * evaluate_evt_tail_pdf(z, shape_params), -25.0, 25.0
        )
        var_z = max(1e-8, sq_z - mean_z**2)
        return float(mean_z), float(math.sqrt(var_z))
    return 0.0, 1.0


def compute_ece_inw(p_arr: np.ndarray, y_arr: np.ndarray) -> float:
    """Compute in-window 8-strata sample-size weighted ECE."""
    n = len(p_arr)
    if n == 0:
        return 0.0
    w_ece = 0.0
    for s_idx in range(len(STRATA_EDGES) - 1):
        lo, hi = STRATA_EDGES[s_idx], STRATA_EDGES[s_idx + 1]
        mask = (p_arr >= lo) & (p_arr <= hi) if s_idx == len(STRATA_EDGES) - 2 else (p_arr >= lo) & (p_arr < hi)
        cnt = int(np.sum(mask))
        if cnt > 0:
            mp = float(np.mean(p_arr[mask]))
            obs_r = float(np.mean(y_arr[mask]))
            w_ece += (cnt / n) * abs(mp - obs_r)
    return float(w_ece)


def compute_ece_w20(p_arr: np.ndarray, y_arr: np.ndarray) -> float:
    """Compute full 11-bin 20-equal-width bins sample-size weighted ECE."""
    n = len(p_arr)
    if n == 0:
        return 0.0
    bin_edges = np.linspace(0.0, 1.0, 21)
    w_ece = 0.0
    for i in range(20):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        mask = (p_arr >= lo) & (p_arr <= hi) if i == 19 else (p_arr >= lo) & (p_arr < hi)
        cnt = int(np.sum(mask))
        if cnt > 0:
            mp = float(np.mean(p_arr[mask]))
            obs_r = float(np.mean(y_arr[mask]))
            w_ece += (cnt / n) * abs(mp - obs_r)
    return float(w_ece)


def main():
    print("=" * 80)
    print("Step 1: Recalculating s_oos on 2000-2018 20-fold Block-CV OOF residuals...")
    print("=" * 80)

    contract_path = PROJECT_ROOT / "data/contracts/physical_param_contract.json"
    with open(contract_path, "r", encoding="utf-8") as f:
        contract_raw = json.load(f)
    old_cells = contract_raw["cells"]

    soos_results = {}
    harvested_data = {}

    for st in AUTHORIZED_STATIONS:
        for lead in AUTHORIZED_LEAD_HOURS:
            cell_key = f"{st}_{lead}h"
            df_days, sha = harvest_cell_daily_records(st, lead, EVIDENCE_DIR)
            harvested_data[cell_key] = df_days

            resid = df_days["obs_tmax_f"].to_numpy() - df_days["mu"].to_numpy()
            var_resid = float(np.var(resid, ddof=1))
            mean_sig2 = float(np.mean(df_days["sigma"].to_numpy() ** 2))
            s_oos_new = float(var_resid / mean_sig2)
            c_new = float(math.sqrt(max(1.0, s_oos_new)))

            old_soos = float(old_cells[cell_key]["s_oos"])
            old_c = float(math.sqrt(max(1.0, old_soos)))

            soos_results[cell_key] = {
                "cell": cell_key,
                "station": st,
                "lead_hours": lead,
                "n_records": len(df_days),
                "n_unique_days": int(df_days["target_date"].nunique()),
                "var_resid": var_resid,
                "mean_sig2": mean_sig2,
                "s_oos_old": old_soos,
                "s_oos_new": s_oos_new,
                "diff_soos": s_oos_new - old_soos,
                "rel_diff_soos": (s_oos_new - old_soos) / old_soos,
                "c_old": old_c,
                "c_new": c_new,
                "diff_c": c_new - old_c,
            }

    print(f"{'Cell':<10} | {'Old s_oos':<10} | {'New s_oos':<10} | {'Diff':<9} | {'RelDiff':<9} | {'Old c':<8} | {'New c':<8} | {'Diff c':<8}")
    print("-" * 85)
    for k in sorted(soos_results.keys()):
        r = soos_results[k]
        print(f"{r['cell']:<10} | {r['s_oos_old']:10.6f} | {r['s_oos_new']:10.6f} | {r['diff_soos']:9.6f} | {r['rel_diff_soos']:8.2%} | {r['c_old']:8.6f} | {r['c_new']:8.6f} | {r['diff_c']:8.6f}")

    print("\n" + "=" * 80)
    print("Step 2: Processing 11-bin probabilities for Family vs Moment-Matched Gaussian...")
    print("=" * 80)

    # Cache moment calculations for (family, json(shape_params))
    moment_cache: Dict[str, Tuple[float, float]] = {}

    all_day_records = []

    for cell_key, df_days in harvested_data.items():
        st = soos_results[cell_key]["station"]
        lead = soos_results[cell_key]["lead_hours"]
        c_factor = soos_results[cell_key]["c_new"]
        period = get_period(lead)

        n_rows = len(df_days)
        mu_arr = df_days["mu"].to_numpy()
        sig_arr = df_days["sigma"].to_numpy()
        obs_arr = df_days["obs_tmax_f"].to_numpy()
        target_dates = df_days["target_date"].to_list()
        families = df_days["selected_family"].to_list()
        shape_params_list = df_days["shape_params"].to_list()

        sig_adj_arr = sig_arr * c_factor

        # 10 internal cut points per row: shape (10, n_rows)
        center_even = 2.0 * np.floor((mu_arr + 0.5) / 2.0)
        e_start = center_even - 8.0
        j_steps = np.arange(10, dtype=np.float64)[:, None]
        cuts = (e_start - 0.5) + 2.0 * j_steps  # shape (10, n_rows)

        # Vectorized hit determination: bin_idx in 0..10
        # searchsorted along column: for each row, find which cut boundary obs falls into
        hit_bin_idx = np.zeros(n_rows, dtype=np.int32)
        for i in range(n_rows):
            hit_bin_idx[i] = int(np.searchsorted(cuts[:, i], obs_arr[i], side="right"))

        # Compute probabilities for Family and Gaussian
        for i in range(n_rows):
            dt = target_dates[i]
            season = get_season(dt)
            fam = families[i]
            sp = shape_params_list[i]

            sp_key = f"{fam}_{json.dumps(sp, sort_keys=True)}"
            if sp_key not in moment_cache:
                moment_cache[sp_key] = compute_moments_z(fam, sp)
            mean_z, std_z = moment_cache[sp_key]

            mu_0 = mu_arr[i]
            sig_adj = sig_adj_arr[i]
            mu_gauss = mu_0 + sig_adj * mean_z
            sig_gauss = sig_adj * std_z

            row_cuts = cuts[:, i]

            # Family CDF at 10 cut points
            cdf_fam_fn = construct_true_model_cdf(mu=mu_0, sigma=sig_adj, family=fam, shape_params=sp)
            F_fam = np.array([cdf_fam_fn(x) for x in row_cuts], dtype=np.float64)
            p_fam = np.empty(11, dtype=np.float64)
            p_fam[0] = F_fam[0]
            p_fam[1:10] = F_fam[1:] - F_fam[:-1]
            p_fam[10] = 1.0 - F_fam[-1]
            p_fam = np.maximum(0.0, p_fam)
            sum_fam = np.sum(p_fam)
            if sum_fam > 1e-12:
                p_fam /= sum_fam

            # Moment-matched Gaussian CDF at 10 cut points
            z_g = (row_cuts - mu_gauss) / max(1e-8, sig_gauss)
            F_g = stats.norm.cdf(z_g)
            p_g = np.empty(11, dtype=np.float64)
            p_g[0] = F_g[0]
            p_g[1:10] = F_g[1:] - F_g[:-1]
            p_g[10] = 1.0 - F_g[-1]
            p_g = np.maximum(0.0, p_g)
            sum_g = np.sum(p_g)
            if sum_g > 1e-12:
                p_g /= sum_g

            h_idx = hit_bin_idx[i]

            entry = {
                "station": st,
                "season": season,
                "period": period,
                "lead_hours": lead,
                "target_date": dt,
                "family": fam,
                "p_family": p_fam,
                "p_gauss": p_g,
                "hit_idx": h_idx,
            }
            all_day_records.append(entry)

    print(f"Total processed day-lead records: {len(all_day_records)}")

    # Convert to slice groups
    df_all = pd.DataFrame(all_day_records)

    print("\n" + "=" * 80)
    print("Step 3: Calculating Δ across 16 strata with Date-Clustered Bootstrap 95% CI...")
    print("=" * 80)

    calibration_rows = []
    rng = np.random.default_rng(20260923)

    for st in AUTHORIZED_STATIONS:
        for s in SEASONS:
            for period in ["early", "late"]:
                sub_df = df_all[(df_all["station"] == st) & (df_all["season"] == s) & (df_all["period"] == period)]
                n_rows = len(sub_df)
                unique_dates = sorted(sub_df["target_date"].unique())
                n_days = len(unique_dates)

                if n_rows == 0:
                    continue

                # Collect family summary
                fam_dist = sub_df["family"].value_counts().to_dict()
                fam_str = "/".join(f"{k}({v})" for k, v in sorted(fam_dist.items()))

                # Assemble array of probabilities and hits for point estimate
                # 11 bins per row -> total rows * 11 bins
                # In-window: bin indices 1..9 (9 bins)
                p_fam_all = np.vstack(sub_df["p_family"].to_list())  # shape (n_rows, 11)
                p_g_all = np.vstack(sub_df["p_gauss"].to_list())      # shape (n_rows, 11)
                h_indices = sub_df["hit_idx"].to_numpy()               # shape (n_rows,)

                # Hit matrix
                hit_matrix = np.zeros((n_rows, 11), dtype=np.int32)
                for r in range(n_rows):
                    hit_matrix[r, h_indices[r]] = 1

                # 1) inw: bins 1..9
                p_fam_inw = p_fam_all[:, 1:10].flatten()
                p_g_inw = p_g_all[:, 1:10].flatten()
                hit_inw = hit_matrix[:, 1:10].flatten()

                ece_fam_inw = compute_ece_inw(p_fam_inw, hit_inw)
                ece_g_inw = compute_ece_inw(p_g_inw, hit_inw)
                delta_inw = ece_fam_inw - ece_g_inw

                # 2) w20: all 11 bins
                p_fam_w20 = p_fam_all.flatten()
                p_g_w20 = p_g_all.flatten()
                hit_w20 = hit_matrix.flatten()

                ece_fam_w20 = compute_ece_w20(p_fam_w20, hit_w20)
                ece_g_w20 = compute_ece_w20(p_g_w20, hit_w20)
                delta_w20 = ece_fam_w20 - ece_g_w20

                # 3) Date-clustered Bootstrap (1000 resamples)
                # Group records by target_date for fast lookup
                date_to_indices: Dict[str, List[int]] = {}
                sub_dates = sub_df["target_date"].to_list()
                for r_idx, d in enumerate(sub_dates):
                    date_to_indices.setdefault(d, []).append(r_idx)

                n_boot = 1000
                boot_delta_inw = np.empty(n_boot, dtype=np.float64)
                boot_delta_w20 = np.empty(n_boot, dtype=np.float64)

                date_arr = np.array(unique_dates)

                for b in range(n_boot):
                    sampled_dates = rng.choice(date_arr, size=n_days, replace=True)
                    sampled_r_indices = []
                    for sd in sampled_dates:
                        sampled_r_indices.extend(date_to_indices[sd])
                    idx_arr = np.array(sampled_r_indices, dtype=np.int32)

                    # inw
                    b_pf_inw = p_fam_all[idx_arr, 1:10].flatten()
                    b_pg_inw = p_g_all[idx_arr, 1:10].flatten()
                    b_h_inw = hit_matrix[idx_arr, 1:10].flatten()
                    b_delta_inw = compute_ece_inw(b_pf_inw, b_h_inw) - compute_ece_inw(b_pg_inw, b_h_inw)
                    boot_delta_inw[b] = b_delta_inw

                    # w20
                    b_pf_w20 = p_fam_all[idx_arr, :].flatten()
                    b_pg_w20 = p_g_all[idx_arr, :].flatten()
                    b_h_w20 = hit_matrix[idx_arr, :].flatten()
                    b_delta_w20 = compute_ece_w20(b_pf_w20, b_h_w20) - compute_ece_w20(b_pg_w20, b_h_w20)
                    boot_delta_w20[b] = b_delta_w20

                ci_inw_lo = float(np.percentile(boot_delta_inw, 2.5))
                ci_inw_hi = float(np.percentile(boot_delta_inw, 97.5))
                ci_w20_lo = float(np.percentile(boot_delta_w20, 2.5))
                ci_w20_hi = float(np.percentile(boot_delta_w20, 97.5))

                calibration_rows.append({
                    "station": st,
                    "season": s,
                    "period": period,
                    "family": fam_str,
                    "n_rows": n_rows,
                    "n_days": n_days,
                    "ece_fam_inw": ece_fam_inw,
                    "ece_g_inw": ece_g_inw,
                    "delta_inw": delta_inw,
                    "ci_inw_lo": ci_inw_lo,
                    "ci_inw_hi": ci_inw_hi,
                    "ece_fam_w20": ece_fam_w20,
                    "ece_g_w20": ece_g_w20,
                    "delta_w20": delta_w20,
                    "ci_w20_lo": ci_w20_lo,
                    "ci_w20_hi": ci_w20_hi,
                })

    df_calib = pd.DataFrame(calibration_rows)
    print("\n--- Calibration Results Summary ---")
    for _, r in df_calib.iterrows():
        print(f"{r['station']} {r['season']:<6} {r['period']:<5} | n={r['n_rows']:5d}/{r['n_days']:4d} | Δ_inw={r['delta_inw']:+8.5f} [{r['ci_inw_lo']:+8.5f}, {r['ci_inw_hi']:+8.5f}] | Δ_w20={r['delta_w20']:+8.5f} [{r['ci_w20_lo']:+8.5f}, {r['ci_w20_hi']:+8.5f}]")

    # Output CSV and MD
    evidence_csv_path = PROJECT_ROOT / "evidence/p8_algo_shape_distance_calibration_20261113.csv"
    df_calib.to_csv(evidence_csv_path, index=False)
    print(f"\nCSV written to: {evidence_csv_path}")

    return soos_results, df_calib


if __name__ == "__main__":
    main()
