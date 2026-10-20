#!/usr/bin/env python3
"""
scripts/audit_t3/phase_attribution.py:
P4-BLIND-AUDIT-CHK-03 Lead 24h Phase Attribution Read-Only Diagnosis.

Statutory & Mandate Context:
- Mandate: docs/audit/P4-BLIND-AUDIT-CHK-03_开发端指导_20261021.md
- Specification: docs/audit/P4-BLIND-AUDIT-CHK-03_相位归因_任务书_20261021.md
- Scope: KORD, KMIA x tmax x 2000-2018.
- UTC Phase Definition: Phase = lead_hours % 24
  - Phase  0h = {24, 48, 72}
  - Phase  6h = {30, 54}
  - Phase 12h = {12, 36, 60}
  - Phase 18h = {18, 42, 66}
- Absolute Red Lines:
  - NO retraining of production models.
  - NO modification of model parameters.
  - NO writing to pkl or manifest.json.
  - NO reading of 2019 data.
  - Pure raw values emitted without subjective pass/fail conclusions.
"""

import argparse
import json
import logging
import math
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy import optimize, stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.airgap import verify_year_whitelist

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("phase_attribution")

GHCN_DIR = PROJECT_ROOT / "data" / "processed" / "truth_ghcn_daily"
GEFS_DIR = PROJECT_ROOT / "data" / "processed" / "gefs_factors"
if not GEFS_DIR.exists():
    GEFS_DIR = PROJECT_ROOT / "data" / "processed" / "calib-dataset-v2.0" / "gefs_factors"

MANIFEST_FILE = PROJECT_ROOT / "data" / "models" / "manifest.json"
EVIDENCE_DIR = PROJECT_ROOT / "evidence" / "audit_t3"

OUT_PHASE_GROUP_CSV = EVIDENCE_DIR / "p4blind_chk03_phase_group.csv"
OUT_YEAR_PHASE_CSV = EVIDENCE_DIR / "p4blind_chk03_year_phase.csv"

STATIONS = ["KORD", "KMIA"]
SEASONS = ["Winter", "Spring", "Summer", "Autumn"]
LEADS = [12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72]
TRAIN_YEARS = list(range(2000, 2019))

PHASE_MAP = {
    0: [24, 48, 72],
    6: [30, 54],
    12: [12, 36, 60],
    18: [18, 42, 66],
}
PHASE_LEADS_STR = {
    0: "24,48,72",
    6: "30,54",
    12: "12,36,60",
    18: "18,42,66",
}

INV_SQRT_PI = 1.0 / math.sqrt(math.pi)


def get_season(month: int) -> str:
    """Climatological season mapping."""
    if month in (12, 1, 2):
        return "Winter"
    elif month in (3, 4, 5):
        return "Spring"
    elif month in (6, 7, 8):
        return "Summer"
    return "Autumn"


def load_station_training_data(station: str, years: Sequence[int]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Load GHCN truth and GEFS factors for specified training years."""
    verify_year_whitelist(years, f"phase_attribution_load_data({station})")

    ghcn_file = GHCN_DIR / f"{station}.parquet"
    df_ghcn = pd.read_parquet(ghcn_file)
    df_ghcn["target_date"] = pd.to_datetime(df_ghcn["target_date"]).dt.date
    df_ghcn = df_ghcn[df_ghcn["year"].isin(years)].copy()
    df_ghcn["station"] = station
    df_ghcn["month"] = pd.to_datetime(df_ghcn["target_date"]).apply(lambda d: d.month)
    df_ghcn["season"] = df_ghcn["month"].apply(get_season)
    df_ghcn["year"] = df_ghcn["target_date"].apply(lambda d: d.year)

    gefs_frames = []
    for y in years:
        f = GEFS_DIR / station / f"{y}.parquet"
        if f.exists():
            gefs_frames.append(pd.read_parquet(f))
    df_gefs = pd.concat(gefs_frames, ignore_index=True)
    df_gefs["target_date"] = pd.to_datetime(df_gefs["target_date"]).dt.date
    df_gefs["temp_f"] = (df_gefs["value_K"] - 273.15) * 1.8 + 32.0
    df_gefs["year"] = df_gefs["target_date"].apply(lambda d: d.year)

    return df_ghcn, df_gefs


def extract_cell_dataset(
    df_ghcn: pd.DataFrame,
    df_gefs: pd.DataFrame,
    season: str,
    variable: str,
    lead_hour: int,
) -> pd.DataFrame:
    """Extract and merge matched observation and ensemble forecast records for cell."""
    var_lower = "tmax" if variable == "Max" else "tmin"
    obs_col = "tmax_f" if variable == "Max" else "tmin_f"

    obs_sub = df_ghcn[df_ghcn["season"] == season][["target_date", "year", obs_col, "season"]].dropna()
    obs_sub = obs_sub.rename(columns={obs_col: "obs_temp_f"})

    gefs_sub = df_gefs[(df_gefs["variable"] == var_lower) & (df_gefs["lead_hours"] == lead_hour)].copy()
    if gefs_sub.empty:
        return pd.DataFrame()

    ens_stats = gefs_sub.groupby("target_date")["temp_f"].agg(
        ens_mean="mean",
        ens_var=lambda x: float(np.var(x, ddof=1)) if len(x) > 1 else 0.0,
    ).reset_index()

    merged = pd.merge(obs_sub, ens_stats, on="target_date", how="inner").dropna()
    return merged.sort_values("target_date").reset_index(drop=True)


def load_manifest_model_params() -> Dict[str, Dict[str, Any]]:
    """Load model parameters and c_train from manifest.json."""
    data = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    return data.get("models", {})


def crps_loss_objective(
    params: Sequence[float],
    ens_m: np.ndarray,
    ens_v: np.ndarray,
    y_true: np.ndarray,
) -> float:
    """EMOS CRPS loss objective."""
    a, b, c, d = params
    mu = a + b * ens_m
    sig = np.maximum(1e-6, np.sqrt(c * c + d * d * ens_v))
    z = (y_true - mu) / sig
    crps = sig * (z * (2.0 * stats.norm.cdf(z) - 1.0) + 2.0 * stats.norm.pdf(z) - INV_SQRT_PI)
    return float(np.mean(crps))


def compute_all_cell_raw_ratios(
    df_ghcn_dict: Dict[str, pd.DataFrame],
    df_gefs_dict: Dict[str, pd.DataFrame],
    manifest_models: Dict[str, Dict[str, Any]],
) -> Dict[Tuple[str, str, int], float]:
    """Compute raw_ratio = resid_var / mean(c^2 + d^2 * ens_var) for all 88 cells."""
    cell_raw_ratios: Dict[Tuple[str, str, int], float] = {}

    for station in STATIONS:
        df_ghcn = df_ghcn_dict[station]
        df_gefs = df_gefs_dict[station]

        for season in SEASONS:
            for lead in LEADS:
                m_key = f"{station}_{season}_Max_lead{lead}h.pkl"
                m_entry = manifest_models.get(m_key)
                if not m_entry:
                    continue

                p = m_entry["params"]
                a, b, c, d = float(p["a"]), float(p["b"]), float(p["c"]), float(p["d"])

                cell_df = extract_cell_dataset(df_ghcn, df_gefs, season, "Max", lead)
                if cell_df.empty:
                    continue

                ens_mean = cell_df["ens_mean"].to_numpy(dtype=np.float64)
                ens_var = cell_df["ens_var"].to_numpy(dtype=np.float64)
                obs_y = cell_df["obs_temp_f"].to_numpy(dtype=np.float64)

                mu_raw = a + b * ens_mean
                resid_raw = obs_y - mu_raw
                b30 = pd.Series(resid_raw).shift(1).rolling(30, min_periods=10).mean().fillna(0.0).to_numpy()
                mu_calib = mu_raw + b30
                resid_calib = obs_y - mu_calib

                resid_var = float(np.var(resid_calib, ddof=1))
                sigma_raw_mean2 = float(np.mean(c * c + d * d * ens_var))
                rr = resid_var / sigma_raw_mean2 if sigma_raw_mean2 > 0 else float("nan")

                cell_raw_ratios[(station, season, lead)] = rr

    return cell_raw_ratios


def build_phase_group_table(cell_raw_ratios: Dict[Tuple[str, str, int], float]) -> pd.DataFrame:
    """
    Build p4blind_chk03_phase_group.csv:
    Schema: station,phase_h,leads,season,raw_ratio,group_mean,group_range,cv
    """
    # 1. Compute seasonal raw_ratio per (station, phase_h, season)
    seasonal_phase_rrs: Dict[Tuple[str, int, str], float] = {}
    lead_clustering_info: Dict[Tuple[str, int, str], Dict[str, float]] = {}

    for station in STATIONS:
        for phase_h, phase_leads in PHASE_MAP.items():
            for season in SEASONS:
                rrs = [cell_raw_ratios.get((station, season, l), float("nan")) for l in phase_leads]
                valid_rrs = [x for x in rrs if not math.isnan(x)]
                if valid_rrs:
                    mean_val = float(np.mean(valid_rrs))
                    range_val = float(np.ptp(valid_rrs)) if len(valid_rrs) > 1 else 0.0
                    cv_val = float(np.std(valid_rrs, ddof=1) / mean_val) if len(valid_rrs) > 1 else 0.0
                    seasonal_phase_rrs[(station, phase_h, season)] = mean_val
                    lead_clustering_info[(station, phase_h, season)] = {
                        "mean": mean_val,
                        "range": range_val,
                        "cv": cv_val,
                    }

    # 2. Compute cross-season statistics per (station, phase_h)
    rows = []
    for station in STATIONS:
        for phase_h in [0, 6, 12, 18]:
            leads_str = PHASE_LEADS_STR[phase_h]
            cross_season_vals = [seasonal_phase_rrs.get((station, phase_h, s), float("nan")) for s in SEASONS]
            valid_cs = [x for x in cross_season_vals if not math.isnan(x)]

            group_mean = float(np.mean(valid_cs)) if valid_cs else float("nan")
            group_range = float(np.ptp(valid_cs)) if len(valid_cs) > 1 else 0.0
            cv = float(np.std(valid_cs, ddof=1) / group_mean) if (len(valid_cs) > 1 and group_mean > 0) else 0.0

            for season in SEASONS:
                rr = seasonal_phase_rrs.get((station, phase_h, season), float("nan"))
                rows.append({
                    "station": station,
                    "phase_h": phase_h,
                    "leads": leads_str,
                    "season": season,
                    "raw_ratio": round(rr, 6),
                    "group_mean": round(group_mean, 6),
                    "group_range": round(group_range, 6),
                    "cv": round(cv, 6),
                })

    df = pd.DataFrame(rows)
    return df


def build_year_phase_loyo_table(
    df_ghcn_dict: Dict[str, pd.DataFrame],
    df_gefs_dict: Dict[str, pd.DataFrame],
    manifest_models: Dict[str, Dict[str, Any]],
) -> pd.DataFrame:
    """
    Build p4blind_chk03_year_phase.csv:
    Schema: station,phase_h,year,mean_raw_ratio
    KORD: Evaluated yearly across 2000-2018 under LOYO / training data.
    KMIA: Left blank per instruction ('KMIA 无 LOYO 则留空并注明').
    """
    logger.info("Computing KORD year-by-year phase stability across 19 years...")

    # Load all KORD cell datasets with residuals and variances
    kord_ghcn = df_ghcn_dict["KORD"]
    kord_gefs = df_gefs_dict["KORD"]

    cell_dfs = {}
    for season in SEASONS:
        for lead in LEADS:
            cdf = extract_cell_dataset(kord_ghcn, kord_gefs, season, "Max", lead)
            m_key = f"KORD_{season}_Max_lead{lead}h.pkl"
            p = manifest_models[m_key]["params"]
            a, b, c, d = float(p["a"]), float(p["b"]), float(p["c"]), float(p["d"])

            ens_mean = cdf["ens_mean"].to_numpy(dtype=np.float64)
            ens_var = cdf["ens_var"].to_numpy(dtype=np.float64)
            obs_y = cdf["obs_temp_f"].to_numpy(dtype=np.float64)

            mu_raw = a + b * ens_mean
            resid_raw = obs_y - mu_raw
            b30 = pd.Series(resid_raw).shift(1).rolling(30, min_periods=10).mean().fillna(0.0).to_numpy()
            cdf["resid_calib"] = obs_y - (mu_raw + b30)
            cdf["sig_raw_sq"] = c * c + d * d * ens_var
            cdf["lead"] = lead
            cdf["phase_h"] = lead % 24
            cdf["season"] = season
            cell_dfs[(season, lead)] = cdf

    kord_full = pd.concat(list(cell_dfs.values()), ignore_index=True)

    rows = []

    # 1. KORD: Compute mean_raw_ratio per phase per year
    for year in TRAIN_YEARS:
        year_sub = kord_full[kord_full["year"] == year]
        for phase_h in [0, 6, 12, 18]:
            p_sub = year_sub[year_sub["phase_h"] == phase_h]
            # Average of cell raw ratios belonging to this phase in this year
            cell_rrs = []
            for (s, l), cdf in p_sub.groupby(["season", "lead"]):
                if len(cdf) > 1:
                    r_var = float(np.var(cdf["resid_calib"], ddof=1))
                    s_m2 = float(np.mean(cdf["sig_raw_sq"]))
                    if s_m2 > 0:
                        cell_rrs.append(r_var / s_m2)

            mean_rr = float(np.mean(cell_rrs)) if cell_rrs else float("nan")
            rows.append({
                "station": "KORD",
                "phase_h": phase_h,
                "year": year,
                "mean_raw_ratio": round(mean_rr, 6) if not math.isnan(mean_rr) else None,
            })

    # 2. KMIA: Leave blank per mandate ('KMIA 无 LOYO 则留空并注明')
    for year in TRAIN_YEARS:
        for phase_h in [0, 6, 12, 18]:
            rows.append({
                "station": "KMIA",
                "phase_h": phase_h,
                "year": year,
                "mean_raw_ratio": None,
            })

    df = pd.DataFrame(rows)
    return df


def run_phase_attribution() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Execute complete CHK-03 phase attribution pipeline."""
    logger.info("=== Running P4-BLIND-AUDIT-CHK-03 Phase Attribution Pipeline ===")
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    manifest_models = load_manifest_model_params()

    df_ghcn_dict = {}
    df_gefs_dict = {}
    for st in STATIONS:
        logger.info("Loading training data for %s (2000-2018)...", st)
        ghcn, gefs = load_station_training_data(st, TRAIN_YEARS)
        df_ghcn_dict[st] = ghcn
        df_gefs_dict[st] = gefs

    # Compute cell raw ratios
    logger.info("Computing raw_ratio for all 88 cells...")
    cell_raw_ratios = compute_all_cell_raw_ratios(df_ghcn_dict, df_gefs_dict, manifest_models)

    # 1. Phase group table
    logger.info("Generating Phase Group Table (p4blind_chk03_phase_group.csv)...")
    df_phase_group = build_phase_group_table(cell_raw_ratios)
    df_phase_group.to_csv(OUT_PHASE_GROUP_CSV, index=False)
    logger.info("Saved Phase Group CSV to %s (rows: %d)", OUT_PHASE_GROUP_CSV, len(df_phase_group))

    # 2. Year phase table
    logger.info("Generating Year Phase Table (p4blind_chk03_year_phase.csv)...")
    df_year_phase = build_year_phase_loyo_table(df_ghcn_dict, df_gefs_dict, manifest_models)
    df_year_phase.to_csv(OUT_YEAR_PHASE_CSV, index=False)
    logger.info("Saved Year Phase CSV to %s (rows: %d)", OUT_YEAR_PHASE_CSV, len(df_year_phase))

    return df_phase_group, df_year_phase


def main():
    parser = argparse.ArgumentParser(description="P4-BLIND-AUDIT-CHK-03 Phase Attribution Pipeline")
    parser.add_argument("--run-all", action="store_true", help="Run full CHK-03 phase diagnosis")
    args = parser.parse_args()

    df_group, df_year = run_phase_attribution()

    print("\n--- Phase Group Summary (KORD) ---")
    print(df_group[df_group["station"] == "KORD"].to_string(index=False))

    print("\n--- Phase Group Summary (KMIA) ---")
    print(df_group[df_group["station"] == "KMIA"].to_string(index=False))

    print("\n--- KORD Year x Phase Summary (Head 12) ---")
    kord_y = df_year[df_year["station"] == "KORD"]
    print(kord_y.head(12).to_string(index=False))

    print("\n--- KMIA Year x Phase (Sample Head 8, Note: Left Blank per Mandate) ---")
    kmia_y = df_year[df_year["station"] == "KMIA"]
    print(kmia_y.head(8).to_string(index=False))

    logger.info("P4-BLIND-AUDIT-CHK-03 completed successfully.")
    sys.exit(0)


if __name__ == "__main__":
    main()
