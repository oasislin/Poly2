#!/usr/bin/env python3
"""
scripts/audit_t3/chk05_phase_multiplier_loyo.py:
P4-BLIND-AUDIT-CHK-05 Phase-Specific Scalar Multiplier LOYO Comparison (OOS Power Gate)
and Daily z² Descriptive Summary Table.

Statutory & Mandate Context:
- Mandate: docs/audit/P4-BLIND-AUDIT-CHK-05_开发端指导_20261021.md
- Specification: docs/audit/P4-BLIND-AUDIT-CHK-05_分相位乘子LOYO对照_任务书_20261021.md
- Scope: KORD, KMIA x tmax x 2000-2018 (strictly training window).
- Task A: 19-fold Leave-One-Year-Out (LOYO) comparison (Arm B Baseline vs Arm A Phase Multiplier).
- Task B: Daily z² descriptive table (by station x phase, with year-clustered std, no daily p-values).
- Absolute Red Lines:
  - NO retraining of production models (a, b, c, d frozen).
  - NO writing to data/models/*.pkl or manifest.json.
  - NO modification of production c_train.
  - NO reading of 2019 data.
  - Pure raw values emitted with code-lowered boolean criteria; pass/fail left to reviewer.
"""

import argparse
import hashlib
import json
import logging
import math
from pathlib import Path
import sys
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.airgap import verify_year_whitelist

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("chk05_phase_multiplier_loyo")

GHCN_DIR = PROJECT_ROOT / "data" / "processed" / "truth_ghcn_daily"
GEFS_DIR = PROJECT_ROOT / "data" / "processed" / "gefs_factors"
if not GEFS_DIR.exists():
    GEFS_DIR = PROJECT_ROOT / "data" / "processed" / "calib-dataset-v2.0" / "gefs_factors"

MANIFEST_FILE = PROJECT_ROOT / "data" / "models" / "manifest.json"
CLIMATE_CALIB_FILE = PROJECT_ROOT / "evidence" / "p4_active10_climate_calibration.json"
EVIDENCE_DIR = PROJECT_ROOT / "evidence" / "audit_t3"

OUT_LOYO_FOLDS_CSV = EVIDENCE_DIR / "p4blind_chk05_loyo_folds.csv"
OUT_DAILY_Z2_CSV = EVIDENCE_DIR / "p4blind_chk05_daily_z2.csv"

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

INV_SQRT_PI = 1.0 / math.sqrt(math.pi)
Z_Q05 = -1.6448536269514722
Z_Q95 = 1.6448536269514722


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
    verify_year_whitelist(years, f"chk05_load_data({station})")

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


def compute_gaussian_crps_pointwise(y: np.ndarray, mu: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """Compute Gneiting (2005) closed-form Gaussian CRPS."""
    sig_safe = np.maximum(1e-6, sigma)
    z = (y - mu) / sig_safe
    return sig_safe * (z * (2 * stats.norm.cdf(z) - 1.0) + 2 * stats.norm.pdf(z) - INV_SQRT_PI)


def precalculate_quantile_bounds(climate_calib: Dict[str, Any], station: str) -> Dict[str, Tuple[float, float]]:
    """Analytical standardized quantile bounds for Johnson SU / Gaussian 90% coverage."""
    z_bounds: Dict[str, Tuple[float, float]] = {}
    for season in SEASONS:
        st_season = climate_calib.get(station, {}).get("seasons", {}).get(season, {})
        fam = st_season.get("selected_family", "gaussian")
        shp = st_season.get("shape_params", {}) or {}

        if fam == "johnsonsu" and "gamma" in shp:
            g = float(shp["gamma"])
            d = float(shp["delta"])
            xi = float(shp["xi"])
            lam = float(shp["lambda"])
            z_low = xi + lam * math.sinh((Z_Q05 - g) / d)
            z_high = xi + lam * math.sinh((Z_Q95 - g) / d)
        else:
            z_low = Z_Q05
            z_high = Z_Q95
        z_bounds[season] = (z_low, z_high)
    return z_bounds


def build_station_processed_cells(
    station: str,
    manifest_models: Dict[str, Dict[str, Any]],
) -> pd.DataFrame:
    """Load and process all 44 cells (4 seasons x 11 leads) for a station across 2000-2018."""
    logger.info("Building processed cell records for %s (2000-2018)...", station)
    df_ghcn, df_gefs = load_station_training_data(station, TRAIN_YEARS)

    cell_dfs = []
    for season in SEASONS:
        for lead in LEADS:
            cdf = extract_cell_dataset(df_ghcn, df_gefs, season, "Max", lead)
            m_key = f"{station}_{season}_Max_lead{lead}h.pkl"
            p = manifest_models[m_key]["params"]
            a, b, c, d = float(p["a"]), float(p["b"]), float(p["c"]), float(p["d"])
            c_tr = float(manifest_models[m_key].get("c_train", 1.0))

            ens_m = cdf["ens_mean"].to_numpy(dtype=np.float64)
            ens_v = cdf["ens_var"].to_numpy(dtype=np.float64)
            obs_y = cdf["obs_temp_f"].to_numpy(dtype=np.float64)

            mu_raw = a + b * ens_m
            res_raw = obs_y - mu_raw
            b30 = pd.Series(res_raw).shift(1).rolling(30, min_periods=10).mean().fillna(0.0).to_numpy()

            cdf["mu_calib"] = mu_raw + b30
            cdf["resid_calib"] = obs_y - cdf["mu_calib"]
            cdf["sig_raw"] = np.maximum(1e-6, np.sqrt(c * c + d * d * ens_v))
            cdf["sig_raw_sq"] = c * c + d * d * ens_v
            cdf["c_train"] = c_tr
            cdf["phase_h"] = lead % 24
            cdf["lead"] = lead
            cdf["season"] = season
            cdf["z2"] = (cdf["resid_calib"] ** 2) / cdf["sig_raw_sq"]

            cell_dfs.append(cdf)

    full_df = pd.concat(cell_dfs, ignore_index=True)
    full_df["station"] = station
    full_df["year"] = pd.to_datetime(full_df["target_date"]).apply(lambda d: d.year)
    return full_df


def run_loyo_comparison(
    station_dfs: Dict[str, pd.DataFrame],
    climate_calib: Dict[str, Any],
) -> pd.DataFrame:
    """
    Task A: 19-Fold Leave-One-Year-Out (LOYO) Comparison (Arm B Baseline vs Arm A Phase Multiplier).
    Outputs side-by-side metrics: s_oos, CRPS, 90% coverage and boolean improvement indicators.
    """
    logger.info("=== Running Task A: 19-Fold Leave-One-Year-Out (LOYO) Comparison ===")
    rows = []

    for station in STATIONS:
        full_df = station_dfs[station]
        z_bounds = precalculate_quantile_bounds(climate_calib, station)

        for holdout_year in TRAIN_YEARS:
            train_sub = full_df[full_df["year"] != holdout_year]
            test_sub = full_df[full_df["year"] == holdout_year]

            # 1. Estimate training fold cell raw_ratios (holdout year strictly excluded)
            cell_rrs: Dict[Tuple[str, int], float] = {}
            for (s, l), cdf in train_sub.groupby(["season", "lead"]):
                v = float(np.var(cdf["resid_calib"], ddof=1))
                m = float(np.mean(cdf["sig_raw_sq"]))
                cell_rrs[(s, l)] = v / m if m > 0 else 1.0

            # 2. Phase-specific scalar multiplier k_p = median(cell raw_ratios in phase p)
            k_p: Dict[int, float] = {}
            for p in [0, 6, 12, 18]:
                p_rrs = [cell_rrs[(s, l)] for (s, l) in cell_rrs if l % 24 == p]
                k_p[p] = float(np.median(p_rrs)) if p_rrs else 1.0

            # 3. Test set observations and predictions
            y_test = test_sub["obs_temp_f"].to_numpy(dtype=np.float64)
            mu_test = test_sub["mu_calib"].to_numpy(dtype=np.float64)
            res_test = test_sub["resid_calib"].to_numpy(dtype=np.float64)
            sig_raw = test_sub["sig_raw"].to_numpy(dtype=np.float64)
            var_res = float(np.var(res_test, ddof=1))

            # Arm B (Baseline): frozen production scalar c_train from manifest
            sig_base = sig_raw * test_sub["c_train"].to_numpy(dtype=np.float64)
            s_oos_base = float(var_res / np.mean(sig_base ** 2))
            crps_base = float(np.mean(compute_gaussian_crps_pointwise(y_test, mu_test, sig_base)))

            # Arm A (Phase Multiplier): effective sigma = sig_raw * sqrt(k_p)
            k_vec = np.array([k_p[int(p)] for p in test_sub["phase_h"]], dtype=np.float64)
            sig_phase = sig_raw * np.sqrt(k_vec)
            s_oos_phase = float(var_res / np.mean(sig_phase ** 2))
            crps_phase = float(np.mean(compute_gaussian_crps_pointwise(y_test, mu_test, sig_phase)))

            # Vectorized 90% coverage
            cov_base_hits = []
            cov_phase_hits = []
            for s in SEASONS:
                mask = (test_sub["season"] == s).to_numpy()
                if not np.any(mask):
                    continue
                z_l, z_h = z_bounds[s]
                y_s = y_test[mask]
                mu_s = mu_test[mask]
                sb_s = sig_base[mask]
                sp_s = sig_phase[mask]
                cov_base_hits.append((mu_s + sb_s * z_l <= y_s) & (y_s <= mu_s + sb_s * z_h))
                cov_phase_hits.append((mu_s + sp_s * z_l <= y_s) & (y_s <= mu_s + sp_s * z_h))

            cov_base = float(np.mean(np.concatenate(cov_base_hits)))
            cov_phase = float(np.mean(np.concatenate(cov_phase_hits)))

            # Lowered boolean criteria
            crps_improved = bool(crps_phase < crps_base)
            s_oos_improved = bool(abs(s_oos_phase - 1.0) < abs(s_oos_base - 1.0))
            cov_improved = bool(abs(cov_phase - 0.90) <= abs(cov_base - 0.90))

            rows.append({
                "station": station,
                "fold_year": holdout_year,
                "s_oos_base": round(s_oos_base, 6),
                "s_oos_phase": round(s_oos_phase, 6),
                "crps_base": round(crps_base, 6),
                "crps_phase": round(crps_phase, 6),
                "cov_base": round(cov_base, 6),
                "cov_phase": round(cov_phase, 6),
                "crps_improved": crps_improved,
                "s_oos_improved": s_oos_improved,
                "cov_improved": cov_improved,
            })

    df_loyo = pd.DataFrame(rows)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    df_loyo.to_csv(OUT_LOYO_FOLDS_CSV, index=False)
    logger.info("Saved LOYO folds CSV to %s (%d rows)", OUT_LOYO_FOLDS_CSV, len(df_loyo))
    return df_loyo


def run_daily_z2_table(station_dfs: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Task B: Daily z² Descriptive Summary Table.
    Outputs station x phase: n, mean_z2, std_cluster_year (sample std of 19 yearly mean values).
    """
    logger.info("=== Running Task B: Daily z² Descriptive Summary Table ===")
    rows = []

    for station in STATIONS:
        full_df = station_dfs[station]
        for p in [0, 6, 12, 18]:
            p_sub = full_df[full_df["phase_h"] == p]
            n_count = len(p_sub)
            mean_z2 = float(np.mean(p_sub["z2"]))

            yearly_means = p_sub.groupby("year")["z2"].mean()
            std_cluster = float(np.std(yearly_means, ddof=1))

            rows.append({
                "station": station,
                "phase_h": p,
                "n": n_count,
                "mean_z2": round(mean_z2, 6),
                "std_cluster_year": round(std_cluster, 6),
            })

    df_z2 = pd.DataFrame(rows)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    df_z2.to_csv(OUT_DAILY_Z2_CSV, index=False)
    logger.info("Saved daily z² summary CSV to %s (%d rows)", OUT_DAILY_Z2_CSV, len(df_z2))
    return df_z2


def compute_file_sha256(filepath: Path) -> str:
    """Compute standard SHA-256 hex digest for a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="CHK-05 Phase Multiplier LOYO Comparison and Daily z² Table.")
    parser.add_argument("--run-all", action="store_true", help="Execute complete LOYO and Daily z2 pipelines.")
    parser.add_argument("--run-loyo", action="store_true", help="Run Task A LOYO comparison.")
    parser.add_argument("--run-daily-z2", action="store_true", help="Run Task B Daily z2 table.")
    args = parser.parse_args()

    if not (args.run_all or args.run_loyo or args.run_daily_z2):
        args.run_all = True

    manifest_models = json.loads(MANIFEST_FILE.read_text(encoding="utf-8")).get("models", {})
    climate_calib = json.loads(CLIMATE_CALIB_FILE.read_text(encoding="utf-8"))

    station_dfs = {st: build_station_processed_cells(st, manifest_models) for st in STATIONS}

    df_loyo = None
    df_z2 = None

    if args.run_all or args.run_loyo:
        df_loyo = run_loyo_comparison(station_dfs, climate_calib)

    if args.run_all or args.run_daily_z2:
        df_z2 = run_daily_z2_table(station_dfs)

    print("\n" + "=" * 80)
    print("P4-BLIND-AUDIT-CHK-05 EXECUTION SUMMARY")
    print("=" * 80)

    if df_loyo is not None:
        print("\n--- Task A: LOYO Comparison Summary (19 Folds per Station) ---")
        for st in STATIONS:
            st_loyo = df_loyo[df_loyo["station"] == st]
            crps_win = int(st_loyo["crps_improved"].sum())
            soos_win = int(st_loyo["s_oos_improved"].sum())
            cov_win = int(st_loyo["cov_improved"].sum())
            mean_crps_b = float(st_loyo["crps_base"].mean())
            mean_crps_p = float(st_loyo["crps_phase"].mean())
            mean_soos_b = float(st_loyo["s_oos_base"].mean())
            mean_soos_p = float(st_loyo["s_oos_phase"].mean())
            mean_cov_b = float(st_loyo["cov_base"].mean())
            mean_cov_p = float(st_loyo["cov_phase"].mean())

            print(f"Station {st}:")
            print(f"  CRPS Improved Folds   : {crps_win} / 19 (Mean Base: {mean_crps_b:.6f} -> Phase: {mean_crps_p:.6f})")
            print(f"  s_oos Improved Folds  : {soos_win} / 19 (Mean Base: {mean_soos_b:.6f} -> Phase: {mean_soos_p:.6f})")
            print(f"  Cov90 Improved Folds  : {cov_win} / 19 (Mean Base: {mean_cov_b:.6f} -> Phase: {mean_cov_p:.6f})")

    if df_z2 is not None:
        print("\n--- Task B: Daily z² Summary Table ---")
        print(df_z2.to_string(index=False))

    print("\n--- Output Artifacts & Checksums ---")
    script_path = Path(__file__).resolve()
    print(f"Script SHA-256    : {compute_file_sha256(script_path)}  ({script_path.relative_to(PROJECT_ROOT)})")
    if OUT_LOYO_FOLDS_CSV.exists():
        print(f"LOYO Folds SHA-256: {compute_file_sha256(OUT_LOYO_FOLDS_CSV)}  ({OUT_LOYO_FOLDS_CSV.relative_to(PROJECT_ROOT)})")
    if OUT_DAILY_Z2_CSV.exists():
        print(f"Daily z² SHA-256  : {compute_file_sha256(OUT_DAILY_Z2_CSV)}  ({OUT_DAILY_Z2_CSV.relative_to(PROJECT_ROOT)})")

    print("\n--- Key Input Artifacts Checksums ---")
    print(f"Manifest SHA-256  : {compute_file_sha256(MANIFEST_FILE)}")
    for st in STATIONS:
        tf = GHCN_DIR / f"{st}.parquet"
        print(f"Truth {st} SHA-256 : {compute_file_sha256(tf)}")


if __name__ == "__main__":
    main()
