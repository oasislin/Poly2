#!/usr/bin/env python3
"""
scripts/audit_t3/offline_t3_detection.py:
T3 Phase 1 Offline Detection Pipeline (E8-a & E8-b).

Statutory & Mandate Context:
- Mandate: docs/audit/开发端工作指导_V1封盘与T3检测_20261020.md
- Specification: docs/audit/T3-第三类重训检测_开发端任务书_20261020.md
- Target Scope: KORD and KMIA only (2 stations x 4 seasons).
- Boundary: Strictly offline, restricted to 2000-2018 training data.
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
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy import optimize, stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.airgap import verify_year_whitelist

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("offline_t3_detection")

GHCN_DIR = PROJECT_ROOT / "data" / "processed" / "truth_ghcn_daily"
GEFS_DIR = PROJECT_ROOT / "data" / "processed" / "gefs_factors"
if not GEFS_DIR.exists():
    GEFS_DIR = PROJECT_ROOT / "data" / "processed" / "calib-dataset-v2.0" / "gefs_factors"

EVIDENCE_DIR = PROJECT_ROOT / "evidence" / "audit_t3"
CLIMATE_CALIB_FILE = PROJECT_ROOT / "evidence" / "p4_active10_climate_calibration.json"

OUT_E8A_CSV = EVIDENCE_DIR / "t3_e8a_anchor_raw.csv"
OUT_E8B_CSV = EVIDENCE_DIR / "t3_e8b_rolling_loyo.csv"

STATIONS = ["KORD", "KMIA"]
SEASONS = ["Winter", "Spring", "Summer", "Autumn"]
SIGMA_INST_PHYSICAL_FLOOR = 0.90
INV_SQRT_PI = 1.0 / math.sqrt(math.pi)
SQRT_2_OVER_PI = math.sqrt(2.0 / math.pi)


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
    verify_year_whitelist(years, f"audit_t3_load_data({station})")

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
    """Extract and merge matched observation and ensemble forecast records for anchor cell."""
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


def fit_emos_cell(cell_df: pd.DataFrame) -> Tuple[float, float, float, float]:
    """Fit Gaussian EMOS parameters (a, b, c, d) using statutory CRPS loss and 5 multi-start guesses."""
    ens_m = cell_df["ens_mean"].to_numpy(dtype=np.float64)
    ens_v = cell_df["ens_var"].to_numpy(dtype=np.float64)
    y_true = cell_df["obs_temp_f"].to_numpy(dtype=np.float64)

    def crps_loss(params):
        a, b, c, d = params
        mu = a + b * ens_m
        var = (c ** 2) + (d ** 2) * ens_v
        sig = np.maximum(1e-6, np.sqrt(var))
        z = (y_true - mu) / sig
        crps = sig * (z * (2 * stats.norm.cdf(z) - 1) + 2 * stats.norm.pdf(z) - INV_SQRT_PI)
        return float(np.mean(crps))

    init_a = float(np.mean(y_true) - np.mean(ens_m))
    bounds = [(-50.0, 50.0), (0.0, 3.0), (SIGMA_INST_PHYSICAL_FLOOR, 20.0), (0.0, 3.0)]
    guesses = [
        [init_a, 1.0, float(max(SIGMA_INST_PHYSICAL_FLOOR, np.std(y_true - ens_m))), 0.5],
        [0.0, 1.0, 2.0, 0.5],
        [-2.0, 1.05, 3.0, 0.8],
        [2.0, 0.95, 1.5, 0.3],
        [init_a * 0.5, 1.0, SIGMA_INST_PHYSICAL_FLOOR, 0.2],
    ]

    best_res, best_loss = None, float("inf")
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
                best_loss, best_res = res.fun, res
        except Exception:
            continue

    if best_res is not None:
        return tuple(float(x) for x in best_res.x)
    return (0.0, 1.0, SIGMA_INST_PHYSICAL_FLOOR, 0.1)


def compute_gaussian_crps_pointwise(y: np.ndarray, mu: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """Compute Gneiting (2005) closed-form Gaussian CRPS."""
    sig_safe = np.maximum(1e-6, sigma)
    z = (y - mu) / sig_safe
    return sig_safe * (z * (2 * stats.norm.cdf(z) - 1.0) + 2 * stats.norm.pdf(z) - INV_SQRT_PI)


def compute_exact_90_coverage_bounds(
    mu: float,
    sigma: float,
    family: str,
    shape_params: Dict[str, Any],
) -> Tuple[float, float]:
    """Analytical 5% and 95% quantile bounds for non-Gaussian/Gaussian models."""
    z_q05 = -1.6448536269514722
    z_q95 = 1.6448536269514722

    if family == "johnsonsu":
        g = float(shape_params["gamma"])
        d = float(shape_params["delta"])
        xi = float(shape_params["xi"])
        lam = float(shape_params["lambda"])
        z_low = xi + lam * math.sinh((z_q05 - g) / d)
        z_high = xi + lam * math.sinh((z_q95 - g) / d)
    else:
        z_low = z_q05
        z_high = z_q95

    return mu + sigma * z_low, mu + sigma * z_high


def run_e8a_detection() -> pd.DataFrame:
    """E8-a: Anchor c_train pre-clip raw value recalculation over full 2000-2018 window."""
    logger.info("=== Running E8-a: Anchor c_train Raw Value Recalculation (2000-2018) ===")
    training_years = list(range(2000, 2019))
    rows = []

    for station in STATIONS:
        df_ghcn, df_gefs = load_station_training_data(station, training_years)
        for season in SEASONS:
            cell_18h = extract_cell_dataset(df_ghcn, df_gefs, season, "Max", 18)
            anchor_lead = 18
            if len(cell_18h) < 100:
                cell_18h = extract_cell_dataset(df_ghcn, df_gefs, season, "Max", 24)
                anchor_lead = 24

            a, b, c, d = fit_emos_cell(cell_18h)
            mu_raw = a + b * cell_18h["ens_mean"].to_numpy(dtype=np.float64)
            sig_raw = np.maximum(1e-6, np.sqrt(c * c + d * d * cell_18h["ens_var"].to_numpy(dtype=np.float64)))
            resid_raw = cell_18h["obs_temp_f"].to_numpy(dtype=np.float64) - mu_raw

            b30 = pd.Series(resid_raw).shift(1).rolling(30, min_periods=10).mean().fillna(0.0).to_numpy()
            mu_calib = mu_raw + b30
            resid_calib = cell_18h["obs_temp_f"].to_numpy(dtype=np.float64) - mu_calib

            var_resid = float(np.var(resid_calib, ddof=1))
            mean_sig2 = float(np.mean(sig_raw ** 2))
            c_val_raw = math.sqrt(var_resid / mean_sig2)
            c_val_clipped = float(np.clip(c_val_raw, 0.85, 1.35))
            hit_bound = bool(c_val_clipped == 0.85 or c_val_clipped == 1.35)

            rows.append({
                "station": station,
                "season": season,
                "anchor_lead": anchor_lead,
                "n": len(cell_18h),
                "c_train_val_raw": round(c_val_raw, 6),
                "c_train_clipped": round(c_val_clipped, 6),
                "hit_bound": hit_bound,
            })

    df_e8a = pd.DataFrame(rows)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    df_e8a.to_csv(OUT_E8A_CSV, index=False)
    hit_count = int(df_e8a["hit_bound"].sum())
    logger.info("Saved E8-a CSV to %s", OUT_E8A_CSV)
    logger.info("E8-a Boundary Hit Count: %d / 8", hit_count)
    return df_e8a


def run_e8b_detection() -> pd.DataFrame:
    """E8-b: Leave-one-year-out rolling comparison (2000-2018) for Variant A vs Variant B."""
    logger.info("=== Running E8-b: Leave-One-Year-Out Rolling Comparison (2000-2018) ===")
    all_years = list(range(2000, 2019))
    climate_calib = json.loads(CLIMATE_CALIB_FILE.read_text(encoding="utf-8"))
    rows = []

    for station in STATIONS:
        df_ghcn_full, df_gefs_full = load_station_training_data(station, all_years)
        df_ghcn_full["year"] = pd.to_datetime(df_ghcn_full["target_date"]).apply(lambda d: d.year)

        for season in SEASONS:
            st_season_info = climate_calib[station]["seasons"].get(season, {})
            family = st_season_info.get("selected_family", "gaussian")
            shape_p = st_season_info.get("shape_params", {}) or {}

            c18_full = extract_cell_dataset(df_ghcn_full, df_gefs_full, season, "Max", 18)
            c18_full["year"] = pd.to_datetime(c18_full["target_date"]).apply(lambda d: d.year)

            for holdout_year in all_years:
                train_df = c18_full[c18_full["year"] != holdout_year].copy().reset_index(drop=True)
                test_df = c18_full[c18_full["year"] == holdout_year].copy().reset_index(drop=True)

                if len(test_df) == 0:
                    continue

                # 1. Fit EMOS on training set
                a, b, c, d = fit_emos_cell(train_df)
                train_mu_raw = a + b * train_df["ens_mean"].to_numpy(dtype=np.float64)
                train_sig_raw = np.maximum(1e-6, np.sqrt(c * c + d * d * train_df["ens_var"].to_numpy(dtype=np.float64)))
                train_resid_raw = train_df["obs_temp_f"].to_numpy(dtype=np.float64) - train_mu_raw
                train_b30 = pd.Series(train_resid_raw).shift(1).rolling(30, min_periods=10).mean().fillna(0.0).to_numpy()
                train_resid_calib = train_df["obs_temp_f"].to_numpy(dtype=np.float64) - (train_mu_raw + train_b30)

                var_resid = float(np.var(train_resid_calib, ddof=1))
                mean_sig2 = float(np.mean(train_sig_raw ** 2))
                c_raw = math.sqrt(var_resid / mean_sig2)
                c_clipped = float(np.clip(c_raw, 0.85, 1.35))

                # 2. Evaluate on holdout year
                test_mu_raw = a + b * test_df["ens_mean"].to_numpy(dtype=np.float64)
                test_sig_raw = np.maximum(1e-6, np.sqrt(c * c + d * d * test_df["ens_var"].to_numpy(dtype=np.float64)))
                test_resid_raw = test_df["obs_temp_f"].to_numpy(dtype=np.float64) - test_mu_raw
                test_b30 = pd.Series(test_resid_raw).shift(1).rolling(30, min_periods=10).mean().fillna(0.0).to_numpy()
                test_mu_calib = test_mu_raw + test_b30
                test_resid_calib = test_df["obs_temp_f"].to_numpy(dtype=np.float64) - test_mu_calib

                for variant_label, c_factor in [("Variant_A_Clipped", c_clipped), ("Variant_B_Unclipped", c_raw)]:
                    sig_eff = test_sig_raw * c_factor
                    s_oos = float(np.var(test_resid_calib, ddof=1) / np.mean(sig_eff ** 2))
                    crps_vals = compute_gaussian_crps_pointwise(test_df["obs_temp_f"].to_numpy(dtype=np.float64), test_mu_calib, sig_eff)
                    crps_mean = float(np.mean(crps_vals))

                    cov_hits = []
                    y_test = test_df["obs_temp_f"].to_numpy(dtype=np.float64)
                    for i in range(len(y_test)):
                        l_q, h_q = compute_exact_90_coverage_bounds(test_mu_calib[i], sig_eff[i], family, shape_p)
                        cov_hits.append(1.0 if (l_q <= y_test[i] <= h_q) else 0.0)
                    cov_mean = float(np.mean(cov_hits))

                    rows.append({
                        "variant": variant_label,
                        "holdout_year": holdout_year,
                        "station": station,
                        "season": season,
                        "s_oos": round(s_oos, 6),
                        "crps": round(crps_mean, 6),
                        "coverage_90": round(cov_mean, 6),
                    })

    df_e8b = pd.DataFrame(rows)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    df_e8b.to_csv(OUT_E8B_CSV, index=False)
    logger.info("Saved E8-b CSV to %s (total rows: %d)", OUT_E8B_CSV, len(df_e8b))
    return df_e8b


def main():
    parser = argparse.ArgumentParser(description="T3 Phase 1 Offline Detection Pipeline")
    parser.add_argument("--run-all", action="store_true", help="Run both E8-a and E8-b detection")
    parser.add_argument("--e8a", action="store_true", help="Run E8-a anchor raw recomputation")
    parser.add_argument("--e8b", action="store_true", help="Run E8-b rolling LOYO comparison")
    args = parser.parse_args()

    if not (args.run_all or args.e8a or args.e8b):
        parser.print_help()
        sys.exit(1)

    if args.run_all or args.e8a:
        df_e8a = run_e8a_detection()
        print("\n--- E8-a Results Summary ---")
        print(df_e8a.to_string(index=False))

    if args.run_all or args.e8b:
        df_e8b = run_e8b_detection()
        print("\n--- E8-b Results Summary (Sample Head 10) ---")
        print(df_e8b.head(10).to_string(index=False))
        print("\n--- E8-b Results Summary (Sample Tail 10) ---")
        print(df_e8b.tail(10).to_string(index=False))

    logger.info("T3 Phase 1 Detection completed successfully.")
    sys.exit(0)


if __name__ == "__main__":
    main()
