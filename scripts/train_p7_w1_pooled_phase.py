#!/usr/bin/env python3
"""
scripts/train_p7_w1_pooled_phase.py:
Retrains the 240 phase-stratified pooled fallback models (valley / peak / transition)
across Active 10 stations x 4 seasons x 2 targets for Work Order P7-W1-POOLPHASE.

Statutory Principles:
1. Strict Airgap: Purely derived from 2000-01-01 through 2018-12-31 (whitelist enforced). Zero 2019 access.
2. 3 Discrete Phase Clusters (LT):
   - valley: 00:00 - 08:00 LT
   - peak: 13:00 - 20:00 LT
   - transition: 08:00 - 13:00 LT & 20:00 - 24:00 LT
3. Active 10 Stations: KORD, KLGA, KATL, KDAL, KSEA, KLAX, KHOU, KMIA, KSFO, KAUS
4. Two-Stage Distribution Selection (JSU-GATE):
   - |skewness| > 0.40 -> Johnson SU
   - kurtosis_fisher > 1.00 -> EVT-Hybrid
   - Delta_BIC < -10.0 significance threshold
   - Tie-breaker: EVT if |Delta_BIC_jsu - Delta_BIC_evt| <= 2.0
5. Dual-Track Disk Persistence (C-2):
   - Persists 240 cluster models: {st}_{sea}_{var}_lead6h_{cluster}.pkl
   - Persists 80 default models: {st}_{sea}_{var}_lead6h.pkl
     * Eastern & Central 7 stations: defaults to valley model
     * Pacific 3 stations: defaults to transition model
   - Registers all assets in data/models/manifest.json
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import math
from pathlib import Path
import pickle
import sys
from typing import Any, Dict, List, Optional, Tuple, Union
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy import optimize, stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data_processing.constants import STATION_METADATA
from src.modeling.gaussian_emos import GaussianEMOS
from src.utils.airgap import verify_year_whitelist

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("p7_w1_train")

STATIONS = ["KORD", "KLGA", "KATL", "KDAL", "KSEA", "KLAX", "KHOU", "KMIA", "KSFO", "KAUS"]
SEASONS = ["Winter", "Spring", "Summer", "Autumn"]
VARIABLES = ["Max", "Min"]
CLUSTERS = ["valley", "peak", "transition"]
LEAD_HOURS = [12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72, 78]

DATA_DIR = PROJECT_ROOT / "data" / "processed" / "calib-dataset-v2.0"
GHCN_DIR = PROJECT_ROOT / "data" / "processed" / "truth_ghcn_daily"
MODELS_DIR = PROJECT_ROOT / "data" / "models"
EVIDENCE_DIR = PROJECT_ROOT / "evidence"
SIGMA_INST_PHYSICAL_FLOOR = 0.90  # NOAA ASOS PRT floor


def compute_sha256(file_path: Path) -> str:
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest()


def get_season(month: int) -> str:
    if month in (12, 1, 2):
        return "Winter"
    elif month in (3, 4, 5):
        return "Spring"
    elif month in (6, 7, 8):
        return "Summer"
    else:
        return "Autumn"


def get_cluster(hour: int) -> str:
    if 0 <= hour <= 8:
        return "valley"
    elif 13 <= hour <= 20:
        return "peak"
    else:
        return "transition"


def load_station_training_data(station: str, years: range = range(2000, 2019)) -> Tuple[pd.DataFrame, pd.DataFrame]:
    verify_year_whitelist(years, f"load_station_training_data({station})")

    ghcn_file = GHCN_DIR / f"{station}.parquet"
    if not ghcn_file.exists():
        raise FileNotFoundError(f"GHCN truth file {ghcn_file} not found!")

    df_ghcn = pd.read_parquet(ghcn_file)
    df_ghcn["target_date"] = pd.to_datetime(df_ghcn["target_date"]).dt.date
    df_ghcn = df_ghcn[df_ghcn["year"].isin(years)].copy()
    df_ghcn["station"] = station
    df_ghcn["month"] = pd.to_datetime(df_ghcn["target_date"]).apply(lambda d: d.month)
    df_ghcn["season"] = df_ghcn["month"].apply(get_season)

    gefs_frames = []
    for y in years:
        gefs_file = DATA_DIR / "gefs_factors" / station / f"{y}.parquet"
        if not gefs_file.exists():
            continue
        gefs_frames.append(pd.read_parquet(gefs_file))

    df_gefs = pd.concat(gefs_frames, ignore_index=True)
    df_gefs["target_date"] = pd.to_datetime(df_gefs["target_date"]).dt.date
    df_gefs["temp_f"] = (df_gefs["value_K"] - 273.15) * 1.8 + 32.0

    return df_ghcn, df_gefs


def extract_matched_cluster_data(
    df_ghcn: pd.DataFrame,
    df_gefs: pd.DataFrame,
    station: str,
    season: str,
    variable: str,
) -> Dict[str, pd.DataFrame]:
    """Extract and partition all GEFS forecast records into the 3 phase clusters."""
    var_lower = "tmax" if variable == "Max" else "tmin"
    obs_col = "tmax_f" if variable == "Max" else "tmin_f"

    obs_sub = df_ghcn[df_ghcn["season"] == season][["target_date", obs_col, "season"]].dropna()
    obs_sub = obs_sub.rename(columns={obs_col: "obs_temp_f"})

    gefs_sub = df_gefs[(df_gefs["variable"] == var_lower) & (df_gefs["lead_hours"].isin(LEAD_HOURS))].copy()
    if gefs_sub.empty:
        return {c: pd.DataFrame() for c in CLUSTERS}

    tz_str = STATION_METADATA[station]["timezone"]
    tz = ZoneInfo(tz_str)

    # Compute ensemble stats per (init_date, target_date, lead_hours)
    ens_stats = gefs_sub.groupby(["init_date", "target_date", "lead_hours"])["temp_f"].agg(
        ens_mean="mean",
        ens_var=lambda x: float(np.var(x, ddof=1)) if len(x) > 1 else 0.0,
    ).reset_index()

    merged = pd.merge(obs_sub, ens_stats, on="target_date", how="inner").dropna()

    # Determine local verification hour
    # init_date is UTC 00Z
    init_utc = pd.to_datetime(merged["init_date"].astype(str) + " 00:00:00+00:00", utc=True)
    valid_utc = init_utc + pd.to_timedelta(merged["lead_hours"], unit="h")
    valid_loc = valid_utc.dt.tz_convert(tz)
    merged["local_hour"] = valid_loc.dt.hour
    merged["phase_cluster"] = merged["local_hour"].apply(get_cluster)

    cluster_dfs = {}
    for c in CLUSTERS:
        c_sub = merged[merged["phase_cluster"] == c].copy()
        cluster_dfs[c] = c_sub.sort_values("target_date").reset_index(drop=True)

    return cluster_dfs


def fit_emos_crps(
    df: pd.DataFrame,
    sigma_floor: float = SIGMA_INST_PHYSICAL_FLOOR,
) -> Tuple[float, float, float, float]:
    """Fit EMOS parameters (a, b, c, d) via 5-guess multi-start L-BFGS-B minimizing CRPS."""
    ens_m = df["ens_mean"].to_numpy(dtype=np.float64)
    ens_v = df["ens_var"].to_numpy(dtype=np.float64)
    y_true = df["obs_temp_f"].to_numpy(dtype=np.float64)

    def crps_loss(params):
        a, b, c, d = params
        mu = a + b * ens_m
        var = (c ** 2) + (d ** 2) * ens_v
        sig = np.maximum(1e-6, np.sqrt(var))
        z = (y_true - mu) / sig
        crps = sig * (z * (2 * stats.norm.cdf(z) - 1) + 2 * stats.norm.pdf(z) - 1.0 / np.sqrt(np.pi))
        return float(np.mean(crps))

    init_a = float(np.mean(y_true) - np.mean(ens_m))
    init_b = 1.0
    init_c = float(max(sigma_floor, np.std(y_true - ens_m)))
    init_d = 0.5
    bounds = [(-50.0, 50.0), (0.0, 3.0), (sigma_floor, 20.0), (0.0, 3.0)]

    guesses = [
        [init_a, init_b, init_c, init_d],
        [0.0, 1.0, 2.0, 0.5],
        [-2.0, 1.05, 3.0, 0.8],
        [2.0, 0.95, 1.5, 0.3],
        [init_a * 0.5, 1.0, sigma_floor, 0.2],
    ]

    best_res = None
    best_loss = float("inf")

    for g in guesses:
        try:
            res = optimize.minimize(
                crps_loss,
                x0=g,
                bounds=bounds,
                method="L-BFGS-B",
                options={"maxiter": 1000, "ftol": 1e-9, "gtol": 1e-7},
            )
            if res.success and res.fun < best_loss:
                best_loss = res.fun
                best_res = res
        except Exception:
            continue

    if best_res is not None:
        return tuple(float(x) for x in best_res.x)

    return (0.0, 1.0, sigma_floor, 0.1)


def run_jsu_gate_selection(
    residuals: np.ndarray,
    std_sigma: np.ndarray,
) -> Tuple[str, Dict[str, Any], float]:
    """Run statutory two-stage BIC family selection (JSU-GATE)."""
    z_scores = (residuals / std_sigma).dropna() if hasattr(residuals, "dropna") else residuals / std_sigma
    z_scores = z_scores[~np.isnan(z_scores) & ~np.isinf(z_scores)]
    n_samples = len(z_scores)

    if n_samples < 50:
        return "gaussian", {}, 0.0

    skew_val = float(stats.skew(z_scores))
    kurt_fisher = float(stats.kurtosis(z_scores, fisher=True, bias=False))

    jsu_triggered = abs(skew_val) > 0.40
    evt_triggered = kurt_fisher > 1.0

    bic_gauss = 0.0 - 2.0 * float(np.sum(stats.norm.logpdf(z_scores)))
    bic_jsu = None
    bic_evt = None
    jsu_fit_params = None
    evt_fit_params = None

    if jsu_triggered:
        try:
            gamma, delta, xi, lam = stats.johnsonsu.fit(z_scores)
            loglik_jsu = float(np.sum(stats.johnsonsu.logpdf(z_scores, gamma, delta, loc=xi, scale=lam)))
            bic_jsu = 4.0 * math.log(n_samples) - 2.0 * loglik_jsu
            jsu_fit_params = {"gamma": gamma, "delta": delta, "xi": xi, "lambda": lam}
        except Exception:
            bic_jsu = None

    if evt_triggered:
        try:
            u_l = float(np.percentile(z_scores, 5.0))
            u_r = float(np.percentile(z_scores, 95.0))
            ex_l = - (z_scores[z_scores < u_l] - u_l)
            ex_r = z_scores[z_scores > u_r] - u_r
            c_l, loc_l, scale_l = stats.genpareto.fit(ex_l, floc=0.0)
            c_r, loc_r, scale_r = stats.genpareto.fit(ex_r, floc=0.0)
            loglik_evt = float(np.sum(stats.norm.logpdf(z_scores[(z_scores >= u_l) & (z_scores <= u_r)])))
            loglik_evt += float(np.sum(stats.genpareto.logpdf(ex_l, c_l, scale=scale_l))) + float(len(ex_l) * math.log(0.05))
            loglik_evt += float(np.sum(stats.genpareto.logpdf(ex_r, c_r, scale=scale_r))) + float(len(ex_r) * math.log(0.05))
            bic_evt = 4.0 * math.log(n_samples) - 2.0 * loglik_evt
            evt_fit_params = {
                "u_left": u_l, "u_right": u_r,
                "gpd_left": {"shape_xi": c_l, "scale_beta": scale_l},
                "gpd_right": {"shape_xi": c_r, "scale_beta": scale_r},
            }
        except Exception:
            bic_evt = None

    selected_family = "gaussian"
    winner_shape_params = {}
    delta_bic_winner = 0.0

    delta_jsu = (bic_jsu - bic_gauss) if bic_jsu is not None else 0.0
    delta_evt = (bic_evt - bic_gauss) if bic_evt is not None else 0.0

    if jsu_triggered and evt_triggered and bic_jsu is not None and bic_evt is not None:
        if abs(delta_jsu - delta_evt) <= 2.0:
            if delta_evt < -10.0:
                selected_family = "evt_hybrid"
                winner_shape_params = evt_fit_params
                delta_bic_winner = delta_evt
        elif delta_evt < delta_jsu and delta_evt < -10.0:
            selected_family = "evt_hybrid"
            winner_shape_params = evt_fit_params
            delta_bic_winner = delta_evt
        elif delta_jsu <= delta_evt and delta_jsu < -10.0:
            selected_family = "johnsonsu"
            winner_shape_params = jsu_fit_params
            delta_bic_winner = delta_jsu
    elif jsu_triggered and bic_jsu is not None and delta_jsu < -10.0:
        selected_family = "johnsonsu"
        winner_shape_params = jsu_fit_params
        delta_bic_winner = delta_jsu
    elif evt_triggered and bic_evt is not None and delta_evt < -10.0:
        selected_family = "evt_hybrid"
        winner_shape_params = evt_fit_params
        delta_bic_winner = delta_evt

    return selected_family, winner_shape_params, delta_bic_winner


def retrain_phase_matrix() -> Dict[str, Any]:
    logger.info("================================================================================")
    logger.info("  STARTING P7-W1-B PHASE-STRATIFIED 240-MODEL RETRAINING                        ")
    logger.info("  Spec: docs/w1_poolphase_preregistration.md (Rev.2 + Rev.3-Addendum)           ")
    logger.info("================================================================================")

    verify_year_whitelist(range(2000, 2019), "W1-B Main Entry")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing manifest to update
    manifest_path = MODELS_DIR / "manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    all_trained_models: Dict[str, Any] = {}
    audit_summary: Dict[str, Any] = {}

    for st_idx, station in enumerate(STATIONS, 1):
        logger.info("[%d/10] Loading data for Station %s...", st_idx, station)
        df_ghcn, df_gefs = load_station_training_data(station)

        for season in SEASONS:
            for variable in VARIABLES:
                cluster_dfs = extract_matched_cluster_data(df_ghcn, df_gefs, station, season, variable)

                # Combined df for fallback if needed
                combined_df = pd.concat([cluster_dfs[c] for c in CLUSTERS if not cluster_dfs[c].empty], ignore_index=True)

                for cluster in CLUSTERS:
                    c_df = cluster_dfs[cluster]
                    is_sparse = len(c_df) < 100

                    if not is_sparse:
                        training_df = c_df
                        fallback_status = "INDEPENDENT_CLUSTER"
                        fallback_level = 0
                    else:
                        training_df = combined_df if len(combined_df) >= 100 else c_df
                        fallback_status = "POOLED-CLUSTER-FALLBACK"
                        fallback_level = 1

                    # 1. Fit EMOS
                    if not training_df.empty:
                        a, b, c, d = fit_emos_crps(training_df)
                        mu_pred = a + b * training_df["ens_mean"].to_numpy()
                        sig_raw2 = (c ** 2) + (d ** 2) * training_df["ens_var"].to_numpy()
                        resid = training_df["obs_temp_f"].to_numpy() - mu_pred
                        var_emp = float(np.var(resid, ddof=1))
                        mean_sig2 = float(np.mean(sig_raw2))
                        c_train = math.sqrt(var_emp / mean_sig2) if mean_sig2 > 0 else 1.0
                        c_train = float(np.clip(c_train, 0.85, 1.35))

                        # JSU-GATE
                        sig_eff = np.sqrt(sig_raw2 * (c_train ** 2))
                        family, shape_params, delta_bic = run_jsu_gate_selection(resid, sig_eff)
                    else:
                        # Level 3 prior baseline
                        a, b, c, d = 0.0, 1.0, SIGMA_INST_PHYSICAL_FLOOR, 0.1
                        c_train = 1.0
                        family = "gaussian"
                        shape_params = {}
                        delta_bic = 0.0
                        fallback_status = "POOLED-FALLBACK-L3"
                        fallback_level = 3

                    # Construct Model Object
                    model_obj = GaussianEMOS(a=a, b=b, c=c, d=d)
                    metadata = {
                        "station_id": station,
                        "season": season,
                        "target_type": variable.lower(),
                        "lead_hours": 6,
                        "phase_cluster": cluster,
                        "node_status": "PHASE-CLUSTER-PRIMARY",
                        "is_pooled_fallback": True,
                        "fallback_level": fallback_level,
                        "sample_count": len(c_df),
                        "saved_at": datetime.now(timezone.utc).isoformat(),
                        "c_train": c_train,
                        "selected_family": family,
                        "shape_params": shape_params,
                        "version": "2.2.0-phase",
                        "work_order": "P7-W1-POOLPHASE",
                        "params": {"a": a, "b": b, "c": c, "d": d},
                    }

                    # Save Cluster Model
                    cluster_filename = f"{station}_{season}_{variable}_lead6h_{cluster}.pkl"
                    cluster_path = MODELS_DIR / cluster_filename
                    with open(cluster_path, "wb") as pf:
                        pickle.dump({"model": model_obj, "metadata": metadata}, pf)

                    c_sha = compute_sha256(cluster_path)
                    all_trained_models[cluster_filename] = {
                        "path": str(cluster_path),
                        "sha256": c_sha,
                        "metadata": metadata,
                    }

                    # Register in manifest
                    manifest_data["models"][cluster_filename] = {
                        "station": station,
                        "variable": variable.lower(),
                        "season": season,
                        "lead_hours": 6,
                        "phase_cluster": cluster,
                        "status": "PHASE-CLUSTER-PRIMARY",
                        "sha256": c_sha,
                        "size_bytes": cluster_path.stat().st_size,
                        "params": {"a": a, "b": b, "c": c, "d": d},
                        "c_train": c_train,
                        "distribution": family,
                        "shape_params": shape_params,
                    }

                # Save C-2 Default Fallback Model
                # Eastern & Central 7 stations -> valley; Western 3 stations -> transition
                default_cluster = "transition" if station in ["KSEA", "KLAX", "KSFO"] else "valley"
                chosen_source = MODELS_DIR / f"{station}_{season}_{variable}_lead6h_{default_cluster}.pkl"
                with open(chosen_source, "rb") as sf:
                    source_payload = pickle.load(sf)

                default_filename = f"{station}_{season}_{variable}_lead6h.pkl"
                default_path = MODELS_DIR / default_filename
                default_meta = dict(source_payload["metadata"])
                default_meta["default_routing_source"] = default_cluster
                default_meta["node_status"] = "PHASE-CLUSTER-FAILSAFE"

                with open(default_path, "wb") as df_out:
                    pickle.dump({"model": source_payload["model"], "metadata": default_meta}, df_out)

                d_sha = compute_sha256(default_path)
                manifest_data["models"][default_filename] = {
                    "station": station,
                    "variable": variable.lower(),
                    "season": season,
                    "lead_hours": 6,
                    "default_phase_cluster": default_cluster,
                    "status": "PHASE-CLUSTER-FAILSAFE",
                    "sha256": d_sha,
                    "size_bytes": default_path.stat().st_size,
                    "params": default_meta["params"],
                    "c_train": default_meta["c_train"],
                    "distribution": default_meta["selected_family"],
                    "shape_params": default_meta.get("shape_params", {}),
                }

    # Update Manifest
    manifest_data["manifest_version"] = "2.2.0-phase"
    manifest_data["version"] = "2.2.0-phase"
    manifest_data["total_models"] = len(manifest_data["models"])
    manifest_data["statutory_trading_nodes_count"] = 720
    manifest_data["auxiliary_nodes_count"] = 160
    manifest_data["phase_cluster_primary_count"] = 240
    manifest_data["phase_cluster_failsafe_count"] = 80
    manifest_data["status_vocabulary"] = {
        "STATUTORY_TRADING_MASTER": "720 statutory trading master nodes (Phase 1.5)",
        "AUXILIARY_POOLED_FALLBACK": "160 auxiliary continuity nodes at lead 12h (Phase 1.5)",
        "PHASE-CLUSTER-PRIMARY": "240 diurnal phase cluster primary nodes at lead 6h (valley/peak/transition) (P7-W1)",
        "PHASE-CLUSTER-FAILSAFE": "80 standard-named lead 6h failsafe fallback nodes pointing to robust dominant cluster (P7-W1)",
    }
    manifest_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    manifest_data["work_order"] = "P7-W1-POOLPHASE"
    manifest_data["adjudication_ruling"] = "P7-W1-B-C5-RULING-R1"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    # Generate P7 W1 Model Inventory Audit CSV (1200 nodes)
    old_inv_path = EVIDENCE_DIR / "model_inventory_audit.csv"
    p7_inv_path = EVIDENCE_DIR / "p7_w1_model_inventory_audit.csv"
    inventory_rows = []
    if old_inv_path.exists():
        df_old_inv = pd.read_csv(old_inv_path)
        for _, row in df_old_inv.iterrows():
            m_fn = row["model_filename"].replace("data/models/", "")
            # Only keep master and auxiliary nodes from old inventory
            if row["status"] in ["STATUTORY_TRADING_MASTER", "AUXILIARY_POOLED_FALLBACK"]:
                inventory_rows.append(row.to_dict())

    # Add 240 primary and 80 failsafe models
    for m_fn, m_info in manifest_data["models"].items():
        if m_info["status"] in ["PHASE-CLUSTER-PRIMARY", "PHASE-CLUSTER-FAILSAFE"]:
            inventory_rows.append({
                "station": m_info["station"],
                "target_type": "Max" if m_info["variable"] == "max" else "Min",
                "lead_hour": f"lead{m_info['lead_hours']}h" if m_info["status"] == "PHASE-CLUSTER-FAILSAFE" else f"lead6h_{m_info['phase_cluster']}",
                "season": m_info["season"],
                "model_filename": f"data/models/{m_fn}",
                "archived_path": "ACTIVE_PRODUCTION_MODEL",
                "training_window": "2000-2018",
                "fitting_script_version": "scripts/train_p7_w1_pooled_phase.py (P7-W1-POOLPHASE, P7-W1-B-C5-RULING-R1)",
                "file_sha256": m_info["sha256"],
                "status": m_info["status"],
            })

    df_p7_inv = pd.DataFrame(inventory_rows)
    df_p7_inv.to_csv(p7_inv_path, index=False)
    logger.info("Saved P7-W1 Model Inventory Audit (%d rows): %s", len(df_p7_inv), p7_inv_path)

    logger.info("Successfully trained and persisted 240 phase cluster models + 80 default fallback models.")
    return all_trained_models


if __name__ == "__main__":
    retrain_phase_matrix()
