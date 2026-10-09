#!/usr/bin/env python3
"""
scripts/diag_p6_heavytail.py

Work Order: P6-HEAVYTAIL-DIAG (厚尾归因拆层与机制诊断四件套)
Read-only inspection of KORD 42h (and control lead times 12h..36h) training and validation artifacts.

Strict Requirements:
1. Zero modifications to production scripts or frozen baseline artifacts.
2. Pre-registered thresholds codified as frozen constants.
3. Two-step mechanical assertions: Observed vs. Threshold -> Conclusion.
"""

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
from scipy import stats

from scripts.run_p6_fullgrid_tmax import load_station_training_data
from src.modeling.resampling import BlockCrossValidator, DEFAULT_SEED

# --- PRE-REGISTERED FROZEN CONSTANTS (Do NOT alter post-hoc) ---
# Diagnostic 1: Frontal Conditioning
PRE_REG_DIAG1_CALM_KURT_CEILING = 1.00
PRE_REG_DIAG1_DIFF_SUPPORTED = 0.50
PRE_REG_DIAG1_DIFF_NOT_SUPPORTED = 0.20

# Diagnostic 2: Sigma_eff Dispersion Calibration Ratio
PRE_REG_DIAG2_RATIO_MIN = 0.85
PRE_REG_DIAG2_RATIO_MAX = 1.15

# Diagnostic 3: Leave-One-Out Extreme Day Sensitivity
PRE_REG_DIAG3_SPARSE_MAX_DROPS = 3
PRE_REG_DIAG3_OVERALL_MIN_DROPS = 5
PRE_REG_DIAG3_KURT_THRESHOLD = 1.00

# Diagnostic 4: Seasonal Composition Bias
PRE_REG_DIAG4_MAX_TRANSITION_SEASON_DIFF = 0.15  # 15%

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = PROJECT_ROOT / "evidence"
FULLGRID_DIR = EVIDENCE_DIR / "fullgrid_tmax"
CELLS_DIR = FULLGRID_DIR / "cells"


def compute_delta_t24_threshold(df_ghcn: pd.DataFrame, quantile: float = 0.75) -> float:
    """Computes the 75th percentile of |Delta T24| as the objective frontal threshold."""
    df_sorted = df_ghcn.sort_values("target_date").reset_index(drop=True)
    delta_t24 = (df_sorted["tmax_f"] - df_sorted["tmax_f"].shift(1)).abs()
    threshold = float(delta_t24.quantile(quantile))
    return threshold


def reconstruct_fold_training_residuals(
    full_df: pd.DataFrame,
    lead_hour: int,
    round_id: int,
    train_df: pd.DataFrame,
    cell_dir: Path,
) -> pd.DataFrame:
    """
    Reconstructs exact bitwise training residuals and standardized z-scores
    using saved fold model parameters.
    """
    model_path = cell_dir / f"cv_fold_{round_id}_model.json"
    if not model_path.exists():
        raise FileNotFoundError(f"Model file not found: {model_path}")

    with open(model_path, "r", encoding="utf-8") as fp:
        m_json = json.load(fp)

    model_info = m_json.get("model", m_json)
    emos_dict = model_info.get("seasonal_emos_params", {})
    c_train_dict = model_info.get("seasonal_c_train", {})

    train_work = train_df.copy().sort_values("target_date").reset_index(drop=True)
    mu_raw = np.zeros(len(train_work))
    sig_raw = np.zeros(len(train_work))

    for idx, row in train_work.iterrows():
        s = row["season"]
        a, b, c, d = emos_dict.get(s, (0.0, 1.0, 0.90, 0.1))
        m = a + b * row["ens_mean"]
        v = (c ** 2) + (d ** 2) * row["ens_var"]
        mu_raw[idx] = m
        sig_raw[idx] = math.sqrt(max(0.90 ** 2, v))

    train_work["mu_raw"] = mu_raw
    train_work["sig_raw"] = sig_raw
    train_work["resid_raw"] = train_work["obs_tmax_f"] - train_work["mu_raw"]
    train_work["b30"] = train_work["resid_raw"].shift(1).rolling(30, min_periods=10).mean().fillna(0.0)
    train_work["mu_calib"] = train_work["mu_raw"] + train_work["b30"]
    train_work["resid_calib"] = train_work["obs_tmax_f"] - train_work["mu_calib"]
    c_series = train_work["season"].map(c_train_dict).fillna(1.0)
    train_work["sig_eff"] = train_work["sig_raw"] * c_series
    train_work["z"] = train_work["resid_calib"] / train_work["sig_eff"]

    return train_work


def run_diagnostic_1(
    kord_42h_folds: List[pd.DataFrame],
    delta_t24_threshold: float,
) -> Dict[str, Any]:
    """
    Diagnostic 1: Frontal Conditioning Kurtosis Test.
    Splits residuals into Calm (|Delta T24| < threshold) vs Frontal (|Delta T24| >= threshold).
    """
    calm_kurts = []
    front_kurts = []
    diffs = []

    for df_fold in kord_42h_folds:
        calm_z = df_fold[df_fold["delta_t24"] < delta_t24_threshold]["z"].dropna().to_numpy()
        front_z = df_fold[df_fold["delta_t24"] >= delta_t24_threshold]["z"].dropna().to_numpy()

        k_calm = float(stats.kurtosis(calm_z, fisher=True, bias=False))
        k_front = float(stats.kurtosis(front_z, fisher=True, bias=False))

        calm_kurts.append(k_calm)
        front_kurts.append(k_front)
        diffs.append(k_front - k_calm)

    mean_calm = float(np.mean(calm_kurts))
    mean_front = float(np.mean(front_kurts))
    mean_diff = float(np.mean(diffs))

    # Pre-registered mechanical evaluation
    if mean_calm < PRE_REG_DIAG1_CALM_KURT_CEILING and mean_diff > PRE_REG_DIAG1_DIFF_SUPPORTED:
        decision = "SUPPORTED"
        desc = "假说受支持：平静日峰度 < 1.0 且锋面子集显著更高（差值 > 0.5），可写入封盘文档结论层"
    elif mean_calm >= PRE_REG_DIAG1_CALM_KURT_CEILING:
        decision = "PARTIALLY_SUPPORTED_INSUFFICIENT"
        desc = "假说部分支持但不足以完全解释：平静日子集峰度仍 >= 1.0，提示存在更基础的机制（非仅由锋面主导）"
    elif abs(mean_diff) < PRE_REG_DIAG1_DIFF_NOT_SUPPORTED:
        decision = "NOT_SUPPORTED"
        desc = "假说未获支持：两子集峰度无显著差异（差值 < 0.2），不得写入封盘文档结论层，挂账机制未明"
    else:
        decision = "INCONCLUSIVE"
        desc = "检验结果处于临界区间"

    return {
        "diagnostic_id": "DIAG_1_FRONTAL_CONDITIONING",
        "threshold_delta_t24": delta_t24_threshold,
        "calm_kurtosis_mean": mean_calm,
        "calm_kurtosis_min": float(np.min(calm_kurts)),
        "calm_kurtosis_max": float(np.max(calm_kurts)),
        "front_kurtosis_mean": mean_front,
        "front_kurtosis_min": float(np.min(front_kurts)),
        "front_kurtosis_max": float(np.max(front_kurts)),
        "kurtosis_diff_mean": mean_diff,
        "decision": decision,
        "decision_description": desc,
        "calm_exceeds_threshold": bool(mean_calm >= PRE_REG_DIAG1_CALM_KURT_CEILING),
    }


def run_diagnostic_2(kord_42h_folds: List[pd.DataFrame]) -> Dict[str, Any]:
    """
    Diagnostic 2: Sigma_eff Dispersion Calibration Ratio Test.
    Tests Var(resid) / Mean(sig_eff^2) in [0.85, 1.15].
    Also checks 4 quartiles of sigma_eff.
    """
    fold_ratios = []
    quartile_ratios = {f"Q{q}": [] for q in range(1, 5)}

    for df_fold in kord_42h_folds:
        var_resid = float(np.var(df_fold["resid_calib"], ddof=1))
        mean_sig2 = float(np.mean(df_fold["sig_eff"] ** 2))
        ratio = var_resid / mean_sig2 if mean_sig2 > 0 else 0.0
        fold_ratios.append(ratio)

        # Quartile breakdown
        if len(df_fold["sig_eff"].unique()) >= 4:
            q_bins = pd.qcut(df_fold["sig_eff"], q=4, labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop")
            for q_label in ["Q1", "Q2", "Q3", "Q4"]:
                sub = df_fold[q_bins == q_label]
                if len(sub) > 1:
                    v_sub = float(np.var(sub["resid_calib"], ddof=1))
                    m_sub = float(np.mean(sub["sig_eff"] ** 2))
                    r_sub = v_sub / m_sub if m_sub > 0 else 0.0
                    quartile_ratios[q_label].append(r_sub)

    mean_ratio = float(np.mean(fold_ratios))
    min_ratio = float(np.min(fold_ratios))
    max_ratio = float(np.max(fold_ratios))

    q_means = {k: float(np.mean(v)) for k, v in quartile_ratios.items() if len(v) > 0}

    in_band = bool(PRE_REG_DIAG2_RATIO_MIN <= mean_ratio <= PRE_REG_DIAG2_RATIO_MAX)
    if in_band:
        decision = "PASS_EXCLUDE_SCALE_MISCALIBRATION"
        desc = "匹配良好：方差比在 [0.85, 1.15] 内，排除尺度误标，厚尾属真实形状特性"
    else:
        decision = "FAIL_SCALE_DEGRADATION"
        desc = "系统性偏离：方差比超出 [0.85, 1.15]，提示 sigma_eff 校准出现退化，厚尾部分来自尺度异方差未吸收"

    return {
        "diagnostic_id": "DIAG_2_DISPERSION_CALIBRATION",
        "mean_variance_ratio": mean_ratio,
        "min_variance_ratio": min_ratio,
        "max_variance_ratio": max_ratio,
        "quartile_variance_ratios": q_means,
        "decision": decision,
        "decision_description": desc,
        "in_band": in_band,
    }


def run_diagnostic_3(kord_42h_folds: List[pd.DataFrame]) -> Dict[str, Any]:
    """
    Diagnostic 3: Leave-One-Out Extreme Day Sensitivity Test.
    Drops top 1, 3, 5, 10 absolute z samples in each fold.
    """
    drop_levels = [0, 1, 3, 5, 10]
    results_by_drop = {k: [] for k in drop_levels}

    for df_fold in kord_42h_folds:
        z_arr = df_fold["z"].dropna().to_numpy()
        abs_z = np.abs(z_arr)
        sort_order = np.argsort(abs_z)

        results_by_drop[0].append(float(stats.kurtosis(z_arr, fisher=True, bias=False)))
        for k in [1, 3, 5, 10]:
            z_trimmed = z_arr[sort_order[:-k]]
            results_by_drop[k].append(float(stats.kurtosis(z_trimmed, fisher=True, bias=False)))

    drop_means = {k: float(np.mean(results_by_drop[k])) for k in drop_levels}
    drop_mins = {k: float(np.min(results_by_drop[k])) for k in drop_levels}
    drop_maxs = {k: float(np.max(results_by_drop[k])) for k in drop_levels}

    # Pre-registered evaluation
    if drop_means[PRE_REG_DIAG3_SPARSE_MAX_DROPS] < PRE_REG_DIAG3_KURT_THRESHOLD:
        decision = "SPARSE_EXTREME_DOMINATED"
        desc = "稀疏极端日支配：剔除 <= 3 个样本峰度即跌破 1.0，属非连续厚尾，易受个别异常日影响"
    elif drop_means[PRE_REG_DIAG3_OVERALL_MIN_DROPS] > PRE_REG_DIAG3_KURT_THRESHOLD:
        decision = "DISTRIBUTION_OVERALL_FAT_TAIL"
        desc = "分布整体厚尾：剔除 5 个以上样本峰度仍 > 1.0，属系统性分布特征"
    else:
        decision = "TRANSITIONAL_BOUNDARY"
        desc = f"临界转折：剔除 3 个样本峰度仍为 {drop_means[3]:.4f} > 1.0，但剔除 5 个样本降至 {drop_means[5]:.4f} <= 1.0"

    return {
        "diagnostic_id": "DIAG_3_LEAVE_OUT_SENSITIVITY",
        "drop_means": drop_means,
        "drop_mins": drop_mins,
        "drop_maxs": drop_maxs,
        "decision": decision,
        "decision_description": desc,
    }


def run_diagnostic_4(
    kord_42h_train_dfs: List[pd.DataFrame],
    kord_42h_val_dfs: List[pd.DataFrame],
    evt_winner_folds: List[int] = [1, 10, 11, 16],
) -> Dict[str, Any]:
    """
    Diagnostic 4: Fold Seasonal Composition Test.
    Compares transition season (Spring + Autumn) ratio between EVT folds and Gaussian folds.
    """
    train_trans_ratios = []
    val_trans_ratios = []

    for r in range(len(kord_42h_train_dfs)):
        tr = kord_42h_train_dfs[r]
        vl = kord_42h_val_dfs[r]

        tr_ratio = len(tr[tr["season"].isin(["Spring", "Autumn"])]) / len(tr)
        vl_ratio = len(vl[vl["season"].isin(["Spring", "Autumn"])]) / len(vl)

        train_trans_ratios.append(tr_ratio)
        val_trans_ratios.append(vl_ratio)

    evt_mask = [r in evt_winner_folds for r in range(20)]
    gauss_mask = [r not in evt_winner_folds for r in range(20)]

    tr_evt = [train_trans_ratios[i] for i in range(20) if evt_mask[i]]
    tr_gauss = [train_trans_ratios[i] for i in range(20) if gauss_mask[i]]

    vl_evt = [val_trans_ratios[i] for i in range(20) if evt_mask[i]]
    vl_gauss = [val_trans_ratios[i] for i in range(20) if gauss_mask[i]]

    diff_tr = abs(float(np.mean(tr_evt)) - float(np.mean(tr_gauss)))
    diff_vl = abs(float(np.mean(vl_evt)) - float(np.mean(vl_gauss)))

    passed_tr = diff_tr <= PRE_REG_DIAG4_MAX_TRANSITION_SEASON_DIFF
    passed_vl = diff_vl <= PRE_REG_DIAG4_MAX_TRANSITION_SEASON_DIFF

    if passed_tr and passed_vl:
        decision = "PASS_EXCLUDE_SEASONAL_BIAS"
        desc = "排除季节构成偶然偏倚：触发折与未触发折过渡季比例差值 <= 15%"
    else:
        decision = "FAIL_SEASONAL_MIX_CONTRIBUTION"
        desc = "季节混合为贡献因素：触发折与未触发折过渡季比例差值 > 15%"

    return {
        "diagnostic_id": "DIAG_4_SEASONAL_COMPOSITION",
        "evt_folds": evt_winner_folds,
        "train_evt_transition_ratio": float(np.mean(tr_evt)),
        "train_gauss_transition_ratio": float(np.mean(tr_gauss)),
        "train_diff": diff_tr,
        "val_evt_transition_ratio": float(np.mean(vl_evt)),
        "val_gauss_transition_ratio": float(np.mean(vl_gauss)),
        "val_diff": diff_vl,
        "decision": decision,
        "decision_description": desc,
        "passed": bool(passed_tr and passed_vl),
    }


def execute_full_diagnostic_suite(target_lead_hours: List[int] = [42, 66]) -> Dict[str, Any]:
    """Executes the full heavy-tail diagnostic suite for specified lead hours."""
    print("Loading KORD observation and forecast datasets...")
    df_ghcn, df_gefs = load_station_training_data("KORD")
    df_ghcn_sorted = df_ghcn.sort_values("target_date").reset_index(drop=True)
    df_ghcn_sorted["delta_t24"] = (df_ghcn_sorted["tmax_f"] - df_ghcn_sorted["tmax_f"].shift(1)).abs()

    delta_t24_threshold = compute_delta_t24_threshold(df_ghcn)
    print(f"Computed |Delta T24| 75th percentile threshold: {delta_t24_threshold:.4f} °F")

    obs_sub = df_ghcn_sorted[["target_date", "tmax_f", "season", "month", "delta_t24"]].dropna().rename(
        columns={"tmax_f": "obs_tmax_f"}
    )

    cv = BlockCrossValidator(n_rounds=20, holdout_ratio=0.10, seed=DEFAULT_SEED)

    lead_results = {}
    for lh in target_lead_hours:
        print(f"\n================ Processing Lead Hour {lh}h ================")
        gefs_lh = df_gefs[(df_gefs["variable"] == "tmax") & (df_gefs["lead_hours"] == lh)].copy()
        ens_stats_lh = gefs_lh.groupby("target_date")["temp_f"].agg(
            ens_mean="mean",
            ens_var=lambda x: float(np.var(x, ddof=1)) if len(x) > 1 else 0.0,
        ).reset_index()

        full_lh = pd.merge(obs_sub, ens_stats_lh, on="target_date", how="inner").dropna().sort_values("target_date").reset_index(drop=True)
        cell_dir = CELLS_DIR / f"KORD_{lh}h"

        lh_training_reconstructed = []
        lh_val_dfs = []

        print(f"Reconstructing 20 folds bitwise training residuals for KORD {lh}h...")
        for round_id, train_df, val_df in cv.split_dataframe(full_lh, date_col="target_date"):
            recon_df = reconstruct_fold_training_residuals(
                full_df=full_lh,
                lead_hour=lh,
                round_id=round_id,
                train_df=train_df,
                cell_dir=cell_dir,
            )
            lh_training_reconstructed.append(recon_df)
            lh_val_dfs.append(val_df)

        # Determine EVT-winning folds for this lead
        evt_folds_lh = []
        for r_id in range(20):
            m_path = cell_dir / f"cv_fold_{r_id}_model.json"
            if m_path.exists():
                with open(m_path) as fp:
                    mj = json.load(fp)
                if mj.get("model", {}).get("selected_family") == "evt_hybrid":
                    evt_folds_lh.append(r_id)

        res_diag1 = run_diagnostic_1(lh_training_reconstructed, delta_t24_threshold)
        res_diag2 = run_diagnostic_2(lh_training_reconstructed)
        res_diag3 = run_diagnostic_3(lh_training_reconstructed)
        res_diag4 = run_diagnostic_4(lh_training_reconstructed, lh_val_dfs, evt_winner_folds=evt_folds_lh) if evt_folds_lh else {
            "diagnostic_id": "DIAG_4_SEASONAL_COMPOSITION",
            "evt_folds": [],
            "decision": "NOT_APPLICABLE_NO_EVT_WINNERS",
            "decision_description": "本格 20 折无一被 EVT 录取（全部为高斯获胜），不存在折间 EVT 季节构成偏差",
            "passed": True,
        }

        lead_results[f"{lh}h"] = {
            "lead_hour": lh,
            "evt_winner_folds": evt_folds_lh,
            "diag_1": res_diag1,
            "diag_2": res_diag2,
            "diag_3": res_diag3,
            "diag_4": res_diag4,
        }

    # Control group lead times
    control_summary = {}
    for lh in [12, 18, 24, 30, 36]:
        gefs_lh = df_gefs[(df_gefs["variable"] == "tmax") & (df_gefs["lead_hours"] == lh)].copy()
        ens_stats_lh = gefs_lh.groupby("target_date")["temp_f"].agg(
            ens_mean="mean",
            ens_var=lambda x: float(np.var(x, ddof=1)) if len(x) > 1 else 0.0,
        ).reset_index()
        full_lh = pd.merge(obs_sub, ens_stats_lh, on="target_date", how="inner").dropna().sort_values("target_date").reset_index(drop=True)
        cdir = CELLS_DIR / f"KORD_{lh}h" if lh != 18 else EVIDENCE_DIR

        lh_kurts = []
        lh_calm_kurts = []
        lh_front_kurts = []
        for r_id, tr_df, _ in cv.split_dataframe(full_lh, date_col="target_date"):
            m_path = cdir / f"cv_fold_{r_id}_model.json"
            if not m_path.exists():
                continue
            rec_df = reconstruct_fold_training_residuals(full_lh, lh, r_id, tr_df, cdir)
            all_z = rec_df["z"].dropna().to_numpy()
            calm_z = rec_df[rec_df["delta_t24"] < delta_t24_threshold]["z"].dropna().to_numpy()
            front_z = rec_df[rec_df["delta_t24"] >= delta_t24_threshold]["z"].dropna().to_numpy()
            lh_kurts.append(float(stats.kurtosis(all_z, fisher=True, bias=False)))
            lh_calm_kurts.append(float(stats.kurtosis(calm_z, fisher=True, bias=False)))
            lh_front_kurts.append(float(stats.kurtosis(front_z, fisher=True, bias=False)))

        if lh_kurts:
            control_summary[f"{lh}h"] = {
                "all_kurtosis_mean": float(np.mean(lh_kurts)),
                "calm_kurtosis_mean": float(np.mean(lh_calm_kurts)),
                "front_kurtosis_mean": float(np.mean(lh_front_kurts)),
                "diff_mean": float(np.mean(lh_front_kurts) - np.mean(lh_calm_kurts)),
            }

    results = {
        "station": "KORD",
        "diagnostic_suite": "P6-HEAVYTAIL-DIAG",
        "delta_t24_threshold": delta_t24_threshold,
        "lead_hours_analyzed": target_lead_hours,
        "leads": lead_results,
        "control_lead_times": control_summary,
    }

    output_path = EVIDENCE_DIR / "p6_heavytail_diag_results.json"
    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump(results, fp, indent=2, ensure_ascii=False)
    print(f"Saved diagnostic results to {output_path}")

    return results


if __name__ == "__main__":
    execute_full_diagnostic_suite()
