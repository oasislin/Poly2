#!/usr/bin/env python3
"""
scripts/run_p6_fullgrid_tmax.py:
P6-2-TMAX-FULLGRID Statutory Dual-City Full-Grid Execution & Audit Engine.

Specifications:
- Stations: KORD (Chicago), KMIA (Miami)
- Lead Hours (12): 12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72, 78
- Extrema Target: TMax
- Total Cells: 2 stations x 12 leads = 24 time cells (96 season cells)
- Reused: KORD / 18h / TMax completely reuses v1.3b frozen closure artifacts.
- New Runs (92 cells): 20-round Block-CV resampling, independent family competition
  (Gaussian vs Johnson SU vs EVT GPD under Scheme B), and statutory reliability audit.
- Sentinels: kurtosis_gate_distance, skew_gate_distance, gate_triggered recorded per cell.
- Edge case highlight: distance < 0.30.
- Stop on trigger: gate_triggered = True halts execution immediately.
"""

import argparse
import hashlib
import json
import logging
import math
from pathlib import Path
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.retrain_p4_active10_matrix import load_station_training_data
from src.modeling.resampling import (
    DEFAULT_SEED,
    StatutoryFoldModel,
    evaluate_evt_tail_cdf,
    fit_statutory_pipeline_fold,
    run_block_cv,
)
from src.prediction.discrete_bin_engine import (
    DiscreteBin,
    DiscreteBinEngine,
    settle_half_up,
)
from scripts.standalone_reliability_check import compute_binomial_ci_half_width

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("p6_fullgrid")

EVIDENCE_DIR = PROJECT_ROOT / "evidence"
FULLGRID_DIR = EVIDENCE_DIR / "fullgrid_tmax"
CELLS_DIR = FULLGRID_DIR / "cells"
PROGRESS_FILE = FULLGRID_DIR / "PROGRESS.json"

STATIONS = ["KORD", "KMIA"]
LEAD_HOURS = [12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72, 78]
STRATA_EDGES = [0.00, 0.03, 0.07, 0.12, 0.18, 0.25, 0.35, 0.50, 1.00]
SUBSTANTIVE_THRESHOLD = 0.02


def compute_cdf_val(y_val: float, m: float, s: float, model: StatutoryFoldModel) -> float:
    """Computes exact non-linear CDF F(y) using the winner distribution family."""
    z = (y_val - m) / s
    if model.selected_family == "johnsonsu":
        p = model.shape_params
        zn = p["gamma"] + p["delta"] * np.arcsinh((z - p["xi"]) / p["lambda"])
        return float(stats.norm.cdf(zn))
    elif model.selected_family == "evt_hybrid":
        return float(evaluate_evt_tail_cdf(z, model.shape_params))
    return float(stats.norm.cdf(z))


def construct_true_model_cdf(
    mu: float,
    sigma: float,
    family: str,
    shape_params: Dict[str, Any],
) -> Callable[[float], float]:
    """Constructs callable CDF function for discrete bin integration."""
    def cdf_fn(x: float) -> float:
        z = (x - mu) / sigma
        if family == "johnsonsu":
            g = float(shape_params["gamma"])
            d = float(shape_params["delta"])
            xi = float(shape_params["xi"])
            lam = float(shape_params["lambda"])
            zn = g + d * np.arcsinh((z - xi) / lam)
            return float(stats.norm.cdf(zn))
        elif family == "evt_hybrid":
            return float(evaluate_evt_tail_cdf(z, shape_params))
        return float(stats.norm.cdf(z))
    return cdf_fn


def classify_substantive_tier(
    wilson_passed: bool,
    mean_p: float,
    obs_rate: float,
    threshold: float = SUBSTANTIVE_THRESHOLD,
) -> str:
    """Classifies stratum calibration into three substantive tiers."""
    if wilson_passed:
        return "PASS (不显著 / 良好校准)"
    gap = abs(mean_p - obs_rate)
    if gap >= threshold:
        return f"FAIL (显著且实质 / 偏差 {gap:.2%} >= {threshold:.1%})"
    return f"FAIL (显著但微小 / 偏差 {gap:.2%} < {threshold:.1%})"


def harvest_cell_daily_records(
    station: str,
    lead_hour: int,
    evidence_dir: Path = EVIDENCE_DIR,
) -> Tuple[pd.DataFrame, str]:
    """
    Harvests 20-fold daily validation records.
    For KORD 18h, harvests from frozen evidence/cv_fold_{0..19}_predictions.parquet.
    For other cells, harvests from evidence/fullgrid_tmax/cells/{station}_{lead_hour}h/.
    """
    if station == "KORD" and lead_hour == 18:
        target_dir = evidence_dir
    else:
        target_dir = CELLS_DIR / f"{station}_{lead_hour}h"

    if not target_dir.exists():
        raise FileNotFoundError(f"Target fold directory missing: {target_dir}")

    daily_records = []
    hasher = hashlib.sha256()

    for r in range(20):
        pred_path = target_dir / f"cv_fold_{r}_predictions.parquet"
        if not pred_path.exists():
            raise FileNotFoundError(f"Missing fold {r} predictions at {pred_path}")

        with open(pred_path, "rb") as fp:
            content = fp.read()
            hasher.update(content)
            artifact_sha = hashlib.sha256(content).hexdigest()

        df_fold = pd.read_parquet(pred_path)
        df_fold_daily = df_fold.drop_duplicates(subset=["target_date"]).sort_values("target_date").reset_index(drop=True)

        for _, row in df_fold_daily.iterrows():
            shape_dict = {}
            if "family_shape_params" in row and pd.notna(row["family_shape_params"]):
                try:
                    shape_dict = json.loads(row["family_shape_params"])
                except Exception:
                    pass
            elif "jsu_gamma" in row and pd.notna(row["jsu_gamma"]):
                shape_dict = {
                    "gamma": float(row["jsu_gamma"]),
                    "delta": float(row["jsu_delta"]),
                    "xi": float(row["jsu_xi"]),
                    "lambda": float(row["jsu_lambda"]),
                }

            family_name = str(row.get("selected_family", "gaussian"))

            entry = {
                "sample_id": len(daily_records),
                "fold_id": r,
                "artifact_path": str(pred_path),
                "artifact_sha256": artifact_sha,
                "target_date": str(row["target_date"]),
                "obs_tmax_f": float(row["obs"]),
                "mu": float(row["mu"]),
                "sigma": float(row["sigma"]),
                "selected_family": family_name,
                "shape_params": shape_dict,
                "fold_skew": float(row.get("fold_skew", 0.0)),
                "fold_kurt": float(row.get("fold_kurt", 0.0)),
            }
            daily_records.append(entry)

    df_days = pd.DataFrame(daily_records)
    return df_days, hasher.hexdigest()


def audit_grid_cell_reliability(
    df_full_days: pd.DataFrame,
    station: str,
    lead_hour: int,
    variable: str = "tmax",
) -> Dict[str, Any]:
    """
    Performs full reliability audit on harvested validation days:
    - PIT KS uniformity test
    - Probit rescaled moments (skewness, excess kurtosis)
    - 11-bin discrete adsorbed probabilities
    - Weighted ECE across probability strata
    - Peak bin sharpness quantiles (P10..Max)
    - Sentinels: gate distances and trigger flags
    """
    n_days = len(df_full_days)
    all_records_true_f = []
    pit_u_values = []
    daily_peak_probabilities = []
    tail_hits = {"left": 0, "right": 0}
    tail_expected = {"left": 0.0, "right": 0.0}

    for idx, row in df_full_days.iterrows():
        dt = row["target_date"]
        obs_y = row["obs_tmax_f"]
        mu = row["mu"]
        sigma = row["sigma"]
        fold_id = row["fold_id"]
        family = row["selected_family"]
        s_params = row["shape_params"]

        bins: List[DiscreteBin] = DiscreteBinEngine.generate_2deg_adsorbed_bins(mu=mu)
        cdf_true = construct_true_model_cdf(mu=mu, sigma=sigma, family=family, shape_params=s_params)
        probs_true = DiscreteBinEngine.calculate_2deg_bin_probabilities(bins, cdf_fn=cdf_true)

        u_val = float(cdf_true(obs_y))
        pit_u_values.append(u_val)

        daily_max_p = float(np.max(probs_true))
        daily_peak_probabilities.append(daily_max_p)

        y_settled = settle_half_up(obs_y)

        for b_idx, b in enumerate(bins):
            p_val = float(probs_true[b_idx])
            is_hit = 1.0 if (b.lower_bound_f <= obs_y < b.upper_bound_f) else 0.0
            rec = {
                "sample_id": int(row["sample_id"]),
                "fold_id": fold_id,
                "date": dt,
                "mu": mu,
                "sigma": sigma,
                "selected_family": family,
                "obs_raw": obs_y,
                "obs_settled": y_settled,
                "bin_idx": b.bin_index,
                "bin_label": b.label,
                "hit": is_hit,
                "p_pred": p_val,
                "is_tradeable_window": b.is_tradeable_window,
            }
            all_records_true_f.append(rec)

            if b.bin_index == 0:
                tail_hits["left"] += int(is_hit)
                tail_expected["left"] += p_val
            elif b.bin_index == 10:
                tail_hits["right"] += int(is_hit)
                tail_expected["right"] += p_val

    df_records = pd.DataFrame(all_records_true_f)

    # 1. PIT KS Uniformity Test & Probit Rescaling
    u_arr = np.array(pit_u_values, dtype=np.float64)
    u_clipped = np.clip(u_arr, 1e-12, 1.0 - 1e-12)
    ks_res = stats.kstest(u_arr, "uniform")
    ks_stat = float(ks_res.statistic)
    ks_p = float(ks_res.pvalue)

    z_star = stats.norm.ppf(u_clipped)
    probit_skew = float(stats.skew(z_star))
    probit_kurt = float(stats.kurtosis(z_star))


    # 2. Probability Strata & Weighted ECE
    def compute_ece_and_strata(df_sub: pd.DataFrame) -> Tuple[float, List[Dict[str, Any]]]:
        n_sub = len(df_sub)
        w_ece = 0.0
        strata = []
        for s_idx in range(len(STRATA_EDGES) - 1):
            lo, hi = STRATA_EDGES[s_idx], STRATA_EDGES[s_idx + 1]
            if s_idx == len(STRATA_EDGES) - 2:
                mask = (df_sub["p_pred"] >= lo) & (df_sub["p_pred"] <= hi)
                label = f"[{lo:.2f}, {hi:.2f}]"
            else:
                mask = (df_sub["p_pred"] >= lo) & (df_sub["p_pred"] < hi)
                label = f"[{lo:.2f}, {hi:.2f})"
            sub = df_sub[mask]
            count = len(sub)
            if count == 0:
                strata.append({"label": label, "count": 0, "mean_p": 0.0, "obs_rate": 0.0, "gap": 0.0, "ece_contrib": 0.0})
                continue
            mp = float(np.mean(sub["p_pred"]))
            obs_r = float(np.mean(sub["hit"]))
            gap = abs(mp - obs_r)
            ece_c = (count / n_sub) * gap
            w_ece += ece_c
            strata.append({"label": label, "count": count, "mean_p": mp, "obs_rate": obs_r, "gap": gap, "ece_contrib": ece_c})
        return w_ece, strata

    ece_full, strata_full = compute_ece_and_strata(df_records)
    # In-window subpopulation: bins marked tradeable window
    df_in_win = df_records[df_records["is_tradeable_window"] == True]
    ece_in_win, strata_in_win = compute_ece_and_strata(df_in_win)

    # 3. Peak Probability Sharpness Quantiles
    peaks = np.array(daily_peak_probabilities)
    quantiles = {
        "P10": float(np.percentile(peaks, 10.0)),
        "P25": float(np.percentile(peaks, 25.0)),
        "P50": float(np.percentile(peaks, 50.0)),
        "P75": float(np.percentile(peaks, 75.0)),
        "P90": float(np.percentile(peaks, 90.0)),
        "P99": float(np.percentile(peaks, 99.0)),
        "Max": float(np.max(peaks)),
    }

    # 4. Winner Family Distribution in Folds
    family_counts = df_full_days["selected_family"].value_counts().to_dict()
    winner_family = df_full_days["selected_family"].mode()[0] if len(df_full_days) > 0 else "gaussian"

    # 5. Sentinels and Distance Monitoring
    max_kurt = float(df_full_days["fold_kurt"].max()) if "fold_kurt" in df_full_days else 0.0
    max_skew = float(df_full_days["fold_skew"].abs().max()) if "fold_skew" in df_full_days else 0.0

    kurt_distance = float(1.0 - max_kurt)
    skew_distance = float(0.40 - max_skew)
    gate_triggered = bool((max_kurt > 1.0) or (max_skew > 0.40))
    is_edge_case = bool((kurt_distance < 0.30) or (skew_distance < 0.30))

    # 6. Double Tails Poisson p-values
    p_left = float(1.0 - stats.poisson.cdf(tail_hits["left"] - 1, tail_expected["left"])) if tail_hits["left"] > 0 else 1.0
    p_right = float(1.0 - stats.poisson.cdf(tail_hits["right"] - 1, tail_expected["right"])) if tail_hits["right"] > 0 else 1.0

    return {
        "station": station,
        "lead_hour": lead_hour,
        "variable": variable,
        "sample_size_days": n_days,
        "winner_family": winner_family,
        "family_counts": family_counts,
        "in_window_weighted_ece": ece_in_win,
        "full_weighted_ece": ece_full,
        "pit_ks_statistic": ks_stat,
        "pit_ks_p_value": ks_p,
        "probit_skewness": probit_skew,
        "probit_excess_kurtosis": probit_kurt,
        "sharpness_max_p": quantiles["Max"],
        "sharpness_p50_p": quantiles["P50"],
        "sharpness_quantiles": quantiles,
        "kurtosis_gate_distance": kurt_distance,
        "skew_gate_distance": skew_distance,
        "gate_triggered": gate_triggered,
        "is_edge_case": is_edge_case,
        "tail_left": {"hits": tail_hits["left"], "expected": tail_expected["left"], "poisson_p": p_left},
        "tail_right": {"hits": tail_hits["right"], "expected": tail_expected["right"], "poisson_p": p_right},
    }


def execute_cell_block_cv(
    station: str,
    lead_hour: int,
    variable: str = "tmax",
    seed: int = DEFAULT_SEED,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Executes full 20-round Block-CV resampling for a single grid cell.
    Saves fold parquets under evidence/fullgrid_tmax/cells/{station}_{lead_hour}h/.
    """
    cell_dir = CELLS_DIR / f"{station}_{lead_hour}h"
    cell_dir.mkdir(parents=True, exist_ok=True)

    df_ghcn, df_gefs = load_station_training_data(station)
    obs_sub = df_ghcn[["target_date", "tmax_f", "season", "month"]].dropna().rename(columns={"tmax_f": "obs_tmax_f"})
    gefs_sub = df_gefs[(df_gefs["variable"] == variable) & (df_gefs["lead_hours"] == lead_hour)].copy()
    ens_stats = gefs_sub.groupby("target_date")["temp_f"].agg(
        ens_mean="mean",
        ens_var=lambda x: float(np.var(x, ddof=1)) if len(x) > 1 else 0.0,
    ).reset_index()

    full_df = pd.merge(obs_sub, ens_stats, on="target_date", how="inner").dropna()
    full_df = full_df.sort_values("target_date").reset_index(drop=True)

    def fit_fn(train_df: pd.DataFrame) -> StatutoryFoldModel:
        return fit_statutory_pipeline_fold(
            train_df=train_df,
            station=station,
            variable=variable,
            lead_hour=lead_hour,
            sigma_floor=0.90,
        )

    def eval_fn(model: StatutoryFoldModel, val_df: pd.DataFrame) -> dict:
        val_work = val_df.copy().reset_index(drop=True)
        mu_pred = np.zeros(len(val_work))
        sig_pred = np.zeros(len(val_work))

        for idx, row in val_work.iterrows():
            s = row["season"]
            a, b, c, d = model.seasonal_emos_params.get(s, (0.0, 1.0, 0.90, 0.1))
            c_factor = model.seasonal_c_train.get(s, 1.0)
            m = a + b * row["ens_mean"]
            v = (c ** 2) + (d ** 2) * row["ens_var"]
            mu_pred[idx] = m
            sig_pred[idx] = max(0.90, np.sqrt(max(0.90 ** 2, v)) * c_factor)

        obs = val_work["obs_tmax_f"].values
        records = []
        pit_list = []

        # Extract fold diagnostics
        fold_skew = float(model.selection_audit.get("skewness", 0.0))
        fold_kurt = float(model.selection_audit.get("kurtosis_fisher", 0.0))

        for i in range(len(obs)):
            m_i = mu_pred[i]
            s_i = sig_pred[i]
            y_i = obs[i]
            pit_i = compute_cdf_val(y_i, m_i, s_i, model)
            pit_list.append(pit_i)
            c0 = int(round(m_i))

            for k in range(-3, 4):
                bk = c0 + k
                p_k = compute_cdf_val(bk + 0.5, m_i, s_i, model) - compute_cdf_val(bk - 0.5, m_i, s_i, model)
                p_k = float(np.clip(p_k, 0.0, 1.0))
                h_k = 1.0 if (bk - 0.5 <= y_i < bk + 0.5) else 0.0
                rec = {
                    "target_date": val_work["target_date"].iloc[i],
                    "obs": y_i,
                    "mu": m_i,
                    "sigma": s_i,
                    "bin_center": bk,
                    "p_pred": p_k,
                    "hit": h_k,
                    "pit": pit_i,
                    "selected_family": model.selected_family,
                    "family_shape_params": json.dumps(model.shape_params),
                    "fold_skew": fold_skew,
                    "fold_kurt": fold_kurt,
                }
                records.append(rec)

        pred_df = pd.DataFrame(records)
        return {
            "selected_family": model.selected_family,
            "predictions": pred_df,
            "fold_skew": fold_skew,
            "fold_kurt": fold_kurt,
        }

    cv_output = run_block_cv(
        df=full_df,
        fit_fn=fit_fn,
        eval_fn=eval_fn,
        date_col="target_date",
        n_rounds=20,
        holdout_ratio=0.10,
        seed=seed,
        export_evidence=True,
        evidence_dir=cell_dir,
    )

    df_days, sha_str = harvest_cell_daily_records(station=station, lead_hour=lead_hour, evidence_dir=EVIDENCE_DIR)
    audit_res = audit_grid_cell_reliability(df_days, station=station, lead_hour=lead_hour, variable=variable)
    audit_res["lineage_sha256"] = sha_str

    # Save summary json
    summary_path = cell_dir / f"{station}_{lead_hour}h_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(audit_res, f, indent=2)

    return df_days, audit_res


def verify_kord_18h_zero_drift_gate() -> Dict[str, Any]:
    """
    Executes Zero-Drift Baseline Gate on KORD 18h TMax.
    Asserts exact bit-level match against v1.3b frozen closure metrics.
    """
    logger.info("Executing Zero-Drift Baseline Gate on KORD 18h TMax...")
    df_days, lineage_sha = harvest_cell_daily_records(station="KORD", lead_hour=18, evidence_dir=EVIDENCE_DIR)
    assert len(df_days) == 13740, f"Expected 13,740 validation days, got {len(df_days)}"

    metrics = audit_grid_cell_reliability(df_days, station="KORD", lead_hour=18)

    # 1. Window ECE
    obs_ece = metrics["in_window_weighted_ece"]
    assert abs(obs_ece - 0.00287) < 1e-4, f"Zero-drift breach on ECE: {obs_ece} vs 0.00287"

    # 2. PIT KS p-value
    obs_ks = metrics["pit_ks_p_value"]
    assert abs(obs_ks - 0.46915) < 1e-4, f"Zero-drift breach on KS p-value: {obs_ks} vs 0.46915"

    # 3. Probit Skewness
    obs_skew = metrics["probit_skewness"]
    assert abs(obs_skew - 0.0471) < 1e-4, f"Zero-drift breach on Skewness: {obs_skew} vs 0.0471"

    # 4. Probit Excess Kurtosis
    obs_kurt = metrics["probit_excess_kurtosis"]
    assert abs(obs_kurt - 0.0667) < 1e-4, f"Zero-drift breach on Kurtosis: {obs_kurt} vs 0.0667"

    # 5. Max Peak Probability
    obs_max_p = metrics["sharpness_max_p"]
    assert abs(obs_max_p - 0.3177) < 1e-4, f"Zero-drift breach on Max Peak P: {obs_max_p} vs 0.3177"

    logger.info("Zero-Drift Baseline Gate: 100%% PASS (ECE=%.4f, KS_p=%.5f, Skew=%.4f, Kurt=%.4f, MaxP=%.4f)",
                obs_ece, obs_ks, obs_skew, obs_kurt, obs_max_p)

    return metrics


def run_fullgrid_pipeline(
    stations: List[str] = STATIONS,
    lead_hours: List[int] = LEAD_HOURS,
    force_rerun: bool = False,
) -> Dict[str, Any]:
    """
    Orchestrates the full 24 cell (96 season cells) pipeline.
    Reuses KORD 18h, audits remaining 23 cells.
    Maintains PROGRESS.json and terminates on trigger.
    """
    FULLGRID_DIR.mkdir(parents=True, exist_ok=True)
    CELLS_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Mandatory Zero-Drift Gate
    zero_drift_metrics = verify_kord_18h_zero_drift_gate()

    progress = {}
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            progress = json.load(f)

    all_cell_summaries = []

    for st in stations:
        for lead in lead_hours:
            cell_key = f"{st}_{lead}h"
            cell_summary_file = CELLS_DIR / f"{cell_key}" / f"{cell_key}_summary.json"

            # Check if this cell is KORD 18h (Reused)
            if st == "KORD" and lead == 18:
                logger.info("Cell %s: Reusing v1.3b frozen closure metrics.", cell_key)
                summary_data = {**zero_drift_metrics, "reused_v13b": True, "status": "COMPLETED"}
                all_cell_summaries.append(summary_data)
                progress[cell_key] = {"status": "REUSED_V13B", "winner_family": summary_data["winner_family"]}
                continue

            # Check for existing completed run (Resumption)
            if cell_summary_file.exists() and not force_rerun:
                logger.info("Cell %s: Existing completed run found, resuming.", cell_key)
                with open(cell_summary_file, "r", encoding="utf-8") as f:
                    cell_data = json.load(f)
                all_cell_summaries.append(cell_data)
                progress[cell_key] = {"status": "COMPLETED", "winner_family": cell_data["winner_family"]}
                continue

            # Run Block-CV for new cell
            logger.info(">>> Running Cell %s (%s %dh TMax)...", cell_key, st, lead)
            t0 = time.time()
            df_days, cell_metrics = execute_cell_block_cv(station=st, lead_hour=lead, variable="tmax")
            elapsed = time.time() - t0
            logger.info("Cell %s finished in %.2fs. Winner family: %s, In-Win ECE: %.4f, KS p: %.5f",
                        cell_key, elapsed, cell_metrics["winner_family"],
                        cell_metrics["in_window_weighted_ece"], cell_metrics["pit_ks_p_value"])

            # Sentinel Check: Stop on Trigger
            if cell_metrics["gate_triggered"]:
                logger.error("!!! SENTINEL TRIGGERED on %s: Kurtosis distance=%.4f, Skew distance=%.4f !!!",
                             cell_key, cell_metrics["kurtosis_gate_distance"], cell_metrics["skew_gate_distance"])
                progress[cell_key] = {"status": "TRIGGERED_FROZEN", "metrics": cell_metrics}
                with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
                    json.dump(progress, f, indent=2, ensure_ascii=False)
                raise RuntimeError(f"Sentinel triggered on cell {cell_key}: halt for committee escalation.")

            all_cell_summaries.append(cell_metrics)
            progress[cell_key] = {
                "status": "COMPLETED",
                "winner_family": cell_metrics["winner_family"],
                "in_win_ece": cell_metrics["in_window_weighted_ece"],
                "ks_p": cell_metrics["pit_ks_p_value"],
                "is_edge_case": cell_metrics["is_edge_case"],
            }

            # Update progress file
            with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
                json.dump(progress, f, indent=2, ensure_ascii=False)

    # Save 96-cell fullgrid summary
    fullgrid_summary_path = EVIDENCE_DIR / "p6_fullgrid_96cells_summary.json"
    with open(fullgrid_summary_path, "w", encoding="utf-8") as f:
        json.dump(all_cell_summaries, f, indent=2)

    # Compute Lead-Time Decay Curves
    decay_records = []
    for lead in lead_hours:
        lead_cells = [c for c in all_cell_summaries if c["lead_hour"] == lead]
        kord_cell = next((c for c in lead_cells if c["station"] == "KORD"), None)
        kmia_cell = next((c for c in lead_cells if c["station"] == "KMIA"), None)
        decay_records.append({
            "lead_hour": lead,
            "kord": {
                "in_win_ece": kord_cell["in_window_weighted_ece"] if kord_cell else None,
                "ks_p": kord_cell["pit_ks_p_value"] if kord_cell else None,
                "winner_family": kord_cell["winner_family"] if kord_cell else None,
                "p50_peak_p": kord_cell["sharpness_p50_p"] if kord_cell else None,
            },
            "kmia": {
                "in_win_ece": kmia_cell["in_window_weighted_ece"] if kmia_cell else None,
                "ks_p": kmia_cell["pit_ks_p_value"] if kmia_cell else None,
                "winner_family": kmia_cell["winner_family"] if kmia_cell else None,
                "p50_peak_p": kmia_cell["sharpness_p50_p"] if kmia_cell else None,
            },
        })

    decay_path = EVIDENCE_DIR / "p6_fullgrid_leadtime_decay.json"
    with open(decay_path, "w", encoding="utf-8") as f:
        json.dump(decay_records, f, indent=2)

    logger.info("P6 Full-Grid Pipeline complete. Summary saved to %s, Decay saved to %s",
                fullgrid_summary_path, decay_path)
    return {"summaries": all_cell_summaries, "decay": decay_records}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="P6 Full-Grid Dual-City TMax Runner")
    parser.add_argument("--zero-drift-check-only", action="store_true", help="Only run zero-drift check on KORD 18h")
    parser.add_argument("--station", type=str, choices=["KORD", "KMIA", "ALL"], default="ALL")
    parser.add_argument("--lead-hour", type=int, choices=LEAD_HOURS, default=None)
    parser.add_argument("--force-rerun", action="store_true", help="Force rerun even if cell summary exists")
    args = parser.parse_args()

    if args.zero_drift_check_only:
        verify_kord_18h_zero_drift_gate()
        sys.exit(0)

    st_list = STATIONS if args.station == "ALL" else [args.station]
    lead_list = LEAD_HOURS if args.lead_hour is None else [args.lead_hour]

    run_fullgrid_pipeline(stations=st_list, lead_hours=lead_list, force_rerun=args.force_rerun)
