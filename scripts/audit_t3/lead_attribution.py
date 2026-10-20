#!/usr/bin/env python3
"""
scripts/audit_t3/lead_attribution.py:
T3 Phase 2 Lead Dimension Attribution Diagnosis (D-1 & D-2).

Statutory & Mandate Context:
- Mandate: docs/audit/开发端指导_T3阶段二_20261021.md
- Specification: docs/audit/T3-阶段二_lead维归因诊断_开发端任务书_20261021.md
- Scope: KORD, KMIA x tmax x 4 seasons x lead 12..72h.
- Input data: Strictly restricted to 2000-2018 training window.
- Parameters: Read from data/models/manifest.json (models container).
- Absolute Red Lines:
  - NO retraining of production models.
  - NO writing to data/models/*.pkl or manifest.json.
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
logger = logging.getLogger("lead_attribution")

GHCN_DIR = PROJECT_ROOT / "data" / "processed" / "truth_ghcn_daily"
GEFS_DIR = PROJECT_ROOT / "data" / "processed" / "gefs_factors"
if not GEFS_DIR.exists():
    GEFS_DIR = PROJECT_ROOT / "data" / "processed" / "calib-dataset-v2.0" / "gefs_factors"

MANIFEST_FILE = PROJECT_ROOT / "data" / "models" / "manifest.json"
EVIDENCE_DIR = PROJECT_ROOT / "evidence" / "audit_t3"

OUT_D1_CSV = EVIDENCE_DIR / "t3_d1_lead_attribution.csv"
OUT_SEQ_CSV = EVIDENCE_DIR / "t3_d1_lead_sequence.csv"

STATIONS = ["KORD", "KMIA"]
SEASONS = ["Winter", "Spring", "Summer", "Autumn"]
LEADS = [12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72]
TRAIN_YEARS = list(range(2000, 2019))
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
    verify_year_whitelist(years, f"lead_attribution_load_data({station})")

    ghcn_file = GHCN_DIR / f"{station}.parquet"
    df_ghcn = pd.read_parquet(ghcn_file)
    df_ghcn["target_date"] = pd.to_datetime(df_ghcn["target_date"]).dt.date
    df_ghcn = df_ghcn[df_ghcn["year"].isin(years)].copy()
    df_ghcn["station"] = station
    df_ghcn["month"] = pd.to_datetime(df_ghcn["target_date"]).apply(lambda d: d.month)
    df_ghcn["season"] = df_ghcn["month"].apply(get_season)

    gefs_frames = []
    for y in years:
        f = GEFS_DIR / station / f"{y}.parquet"
        if f.exists():
            gefs_frames.append(pd.read_parquet(f))
    df_gefs = pd.concat(gefs_frames, ignore_index=True)
    df_gefs["target_date"] = pd.to_datetime(df_gefs["target_date"]).dt.date
    df_gefs["temp_f"] = (df_gefs["value_K"] - 273.15) * 1.8 + 32.0

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

    obs_sub = df_ghcn[df_ghcn["season"] == season][["target_date", obs_col, "season"]].dropna()
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


def compute_kord_loyo_noise_band(
    df_ghcn: pd.DataFrame,
    df_gefs: pd.DataFrame,
    season: str,
    manifest_models: Dict[str, Dict[str, Any]],
) -> Dict[int, float]:
    """Compute KORD fold-to-fold standard deviation of delta_raw_ratio across 19 LOYO folds."""
    logger.info("Computing KORD %s LOYO fold noise band (19 folds)...", season)
    df_ghcn_copy = df_ghcn.copy()
    df_ghcn_copy["year"] = pd.to_datetime(df_ghcn_copy["target_date"]).apply(lambda d: d.year)

    cell_dfs = {}
    for lead in LEADS:
        cdf = extract_cell_dataset(df_ghcn_copy, df_gefs, season, "Max", lead)
        cdf["year"] = pd.to_datetime(cdf["target_date"]).apply(lambda d: d.year)
        cell_dfs[lead] = cdf

    fold_delta_rr: Dict[int, List[float]] = {lead: [] for lead in LEADS[1:]}

    for holdout_year in TRAIN_YEARS:
        fold_raw_ratios: Dict[int, float] = {}
        for lead in LEADS:
            cdf = cell_dfs[lead]
            train_sub = cdf[cdf["year"] != holdout_year].copy().reset_index(drop=True)
            if len(train_sub) < 50:
                continue

            # Warm start from manifest params
            k = f"KORD_{season}_Max_lead{lead}h.pkl"
            init_p = manifest_models.get(k, {}).get("params", {"a": 0.0, "b": 1.0, "c": 2.0, "d": 0.5})
            x0 = [init_p["a"], init_p["b"], init_p["c"], init_p["d"]]

            ens_m = train_sub["ens_mean"].to_numpy(dtype=np.float64)
            ens_v = train_sub["ens_var"].to_numpy(dtype=np.float64)
            y_true = train_sub["obs_temp_f"].to_numpy(dtype=np.float64)

            bounds = [(-50.0, 50.0), (0.0, 3.0), (0.90, 20.0), (0.0, 3.0)]
            try:
                res = optimize.minimize(
                    crps_loss_objective,
                    x0=x0,
                    args=(ens_m, ens_v, y_true),
                    method="L-BFGS-B",
                    bounds=bounds,
                    options={"maxiter": 500, "ftol": 1e-7},
                )
                if res.success:
                    fa, fb, fc, fd = res.x
                else:
                    fa, fb, fc, fd = x0
            except Exception:
                fa, fb, fc, fd = x0

            mu_raw = fa + fb * ens_m
            resid_raw = y_true - mu_raw
            b30 = pd.Series(resid_raw).shift(1).rolling(30, min_periods=10).mean().fillna(0.0).to_numpy()
            mu_calib = mu_raw + b30
            resid_calib = y_true - mu_calib

            var_resid = float(np.var(resid_calib, ddof=1))
            sig_mean2 = float(np.mean(fc * fc + fd * fd * ens_v))
            fold_raw_ratios[lead] = var_resid / sig_mean2 if sig_mean2 > 0 else float("nan")

        for idx, lead in enumerate(LEADS[1:], start=1):
            prev_lead = LEADS[idx - 1]
            if lead in fold_raw_ratios and prev_lead in fold_raw_ratios:
                d_rr = fold_raw_ratios[lead] - fold_raw_ratios[prev_lead]
                fold_delta_rr[lead].append(d_rr)

    lead_noise_std: Dict[int, float] = {}
    for lead in LEADS[1:]:
        vals = fold_delta_rr[lead]
        lead_noise_std[lead] = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0

    return lead_noise_std


def run_lead_attribution(compute_noise_band: bool = True) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Execute D-1 and D-2 lead attribution diagnosis across all 88 cells."""
    logger.info("=== Running T3 Phase 2 Lead Attribution Diagnosis (2000-2018) ===")
    manifest_models = load_manifest_model_params()
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    d1_rows = []
    seq_rows = []

    for station in STATIONS:
        logger.info("Processing station: %s", station)
        df_ghcn, df_gefs = load_station_training_data(station, TRAIN_YEARS)

        for season in SEASONS:
            noise_band_dict: Dict[int, float] = {}
            if compute_noise_band and station == "KORD":
                noise_band_dict = compute_kord_loyo_noise_band(df_ghcn, df_gefs, season, manifest_models)

            prev_raw_ratio: Optional[float] = None
            prev_d: Optional[float] = None

            for lead in LEADS:
                m_key = f"{station}_{season}_Max_lead{lead}h.pkl"
                if m_key not in manifest_models:
                    logger.warning("Model key %s not found in manifest!", m_key)
                    continue

                m_entry = manifest_models[m_key]
                p = m_entry["params"]
                a = float(p["a"])
                b = float(p["b"])
                c = float(p["c"])
                d = float(p["d"])
                c_train = float(m_entry.get("c_train", float("nan")))

                cell_df = extract_cell_dataset(df_ghcn, df_gefs, season, "Max", lead)
                if cell_df.empty:
                    logger.warning("No data for %s %s lead %dh", station, season, lead)
                    continue

                ens_mean = cell_df["ens_mean"].to_numpy(dtype=np.float64)
                ens_var = cell_df["ens_var"].to_numpy(dtype=np.float64)
                obs_y = cell_df["obs_temp_f"].to_numpy(dtype=np.float64)

                mu_raw = a + b * ens_mean
                resid_raw = obs_y - mu_raw
                b30 = pd.Series(resid_raw).shift(1).rolling(30, min_periods=10).mean().fillna(0.0).to_numpy()
                mu_calib = mu_raw + b30
                resid_calib = obs_y - mu_calib

                ens_var_mean = float(np.mean(ens_var))
                resid_var = float(np.var(resid_calib, ddof=1))
                sigma_raw_mean2 = float(np.mean(c * c + d * d * ens_var))
                raw_ratio = resid_var / sigma_raw_mean2 if sigma_raw_mean2 > 0 else float("nan")

                delta_d = (d - prev_d) if prev_d is not None else float("nan")
                delta_rr = (raw_ratio - prev_raw_ratio) if prev_raw_ratio is not None else float("nan")

                fold_std = noise_band_dict.get(lead, float("nan")) if station == "KORD" else float("nan")

                d1_rows.append({
                    "station": station,
                    "season": season,
                    "lead": lead,
                    "a": round(a, 6),
                    "b": round(b, 6),
                    "c": round(c, 6),
                    "d": round(d, 6),
                    "delta_d": round(delta_d, 6) if not math.isnan(delta_d) else None,
                    "c_train": round(c_train, 6),
                    "ens_var_mean": round(ens_var_mean, 6),
                    "resid_var": round(resid_var, 6),
                    "sigma_raw_mean2": round(sigma_raw_mean2, 6),
                    "raw_ratio": round(raw_ratio, 6),
                })

                seq_rows.append({
                    "station": station,
                    "season": season,
                    "lead": lead,
                    "raw_ratio": round(raw_ratio, 6),
                    "delta_raw_ratio": round(delta_rr, 6) if not math.isnan(delta_rr) else None,
                    "delta_raw_ratio_fold_std": round(fold_std, 6) if not math.isnan(fold_std) else None,
                    "d": round(d, 6),
                    "delta_d": round(delta_d, 6) if not math.isnan(delta_d) else None,
                    "ens_var_mean": round(ens_var_mean, 6),
                    "resid_var": round(resid_var, 6),
                    "sigma_raw_mean2": round(sigma_raw_mean2, 6),
                    "c_train": round(c_train, 6),
                })

                prev_raw_ratio = raw_ratio
                prev_d = d

    df_d1 = pd.DataFrame(d1_rows)
    df_seq = pd.DataFrame(seq_rows)

    df_d1.to_csv(OUT_D1_CSV, index=False)
    df_seq.to_csv(OUT_SEQ_CSV, index=False)

    logger.info("Saved D-1 CSV to %s (rows: %d)", OUT_D1_CSV, len(df_d1))
    logger.info("Saved Lead Sequence CSV to %s (rows: %d)", OUT_SEQ_CSV, len(df_seq))

    return df_d1, df_seq


def main():
    parser = argparse.ArgumentParser(description="T3 Phase 2 Lead Attribution Diagnosis")
    parser.add_argument("--run-all", action="store_true", help="Run full D-1 and D-2 lead attribution diagnosis")
    parser.add_argument("--no-noise-band", action="store_true", help="Skip KORD LOYO noise band calculation")
    args = parser.parse_args()

    compute_noise = not args.no_noise_band
    df_d1, df_seq = run_lead_attribution(compute_noise_band=compute_noise)

    print("\n--- D-1 Lead Attribution Summary (Sample Head 10) ---")
    print(df_d1.head(10).to_string(index=False))

    print("\n--- D-1 Lead Attribution Summary (Sample Tail 10) ---")
    print(df_d1.tail(10).to_string(index=False))

    print("\n--- Lead Sequence Summary (KORD Winter) ---")
    kord_w = df_seq[(df_seq["station"] == "KORD") & (df_seq["season"] == "Winter")]
    print(kord_w.to_string(index=False))

    logger.info("T3 Phase 2 Lead Attribution Diagnosis completed successfully.")
    sys.exit(0)


if __name__ == "__main__":
    main()
