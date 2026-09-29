#!/usr/bin/env python3
"""
scripts/export_audit_arrays.py: Export Full Machine-Readable Audit Arrays for 2000-2018 & 2019 OOS (D-1).

Generates:
1. data/processed/audit_arrays/2000_2018_training_arrays.parquet (+ head20 CSV)
2. data/processed/audit_arrays/2019_oos_evaluation_arrays.parquet (+ head20 CSV)

All arrays include complete fields specified by Review Directive v3 D-1.
"""

import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Dict, Any, Sequence

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.metrics.calibration_audit import SIGMA_INST_PHYSICAL_FLOOR

STATIONS = ["KORD", "KMIA", "KSFO"]
DATA_DIR = PROJECT_ROOT / "data" / "processed" / "calib-dataset-v2.0"
GHCN_DIR = PROJECT_ROOT / "data" / "processed" / "truth_ghcn_daily"
OUT_DIR = PROJECT_ROOT / "data" / "processed" / "audit_arrays"
EVIDENCE_DIR = PROJECT_ROOT / "evidence"


def compute_sha256(file_path: Path) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()


def get_season(month: int) -> str:
    if month in (12, 1, 2):
        return "Winter"
    elif month in (3, 4, 5):
        return "Spring"
    elif month in (6, 7, 8):
        return "Summer"
    else:
        return "Autumn"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    params_path = EVIDENCE_DIR / "training_variance_factors.json"
    if not params_path.exists():
        raise FileNotFoundError(f"{params_path} not found. Run scripts/fit_training_variance_factors.py first.")

    with open(params_path, "r", encoding="utf-8") as f:
        training_meta = json.load(f)

    all_train_records = []
    all_oos_records = []

    for station in STATIONS:
        st_meta = training_meta[station]
        c_train = st_meta["frozen_c_train"]
        fitted_seasons = st_meta["seasonal_parameters"]

        # Load full GHCN truth
        df_ghcn = pd.read_parquet(GHCN_DIR / f"{station}.parquet")
        df_ghcn["date_str"] = df_ghcn["target_date"].astype(str)
        df_ghcn["target_date"] = pd.to_datetime(df_ghcn["target_date"]).dt.date
        df_ghcn["month"] = pd.to_datetime(df_ghcn["target_date"]).apply(lambda d: d.month)
        df_ghcn["year"] = pd.to_datetime(df_ghcn["target_date"]).apply(lambda d: d.year)
        df_ghcn["season"] = df_ghcn["month"].apply(get_season)

        # Load GEFS 2000-2019
        gefs_frames = []
        for y in range(2000, 2020):
            gefs_file = DATA_DIR / "gefs_factors" / station / f"{y}.parquet"
            if not gefs_file.exists():
                continue
            df_gefs = pd.read_parquet(gefs_file)
            df_gefs["target_date"] = pd.to_datetime(df_gefs["target_date"]).dt.date
            tmax_18h = df_gefs[(df_gefs["variable"] == "tmax") & (df_gefs["lead_hours"] == 18)].copy()
            tmax_18h["temp_f"] = (tmax_18h["value_K"] - 273.15) * 1.8 + 32.0
            stats_df = tmax_18h.groupby("target_date")["temp_f"].agg(
                ens_mean="mean",
                ens_var=lambda x: float(np.var(x, ddof=1)) if len(x) > 1 else 0.0,
            ).reset_index()
            gefs_frames.append(stats_df)

        df_gefs_all = pd.concat(gefs_frames, ignore_index=True)

        # Outer join on GEFS to preserve all target dates (including NaN obs in KSFO 2018)
        merged = pd.merge(df_gefs_all, df_ghcn, on="target_date", how="left").sort_values("target_date").reset_index(drop=True)
        merged["obs_tmax_f"] = merged["tmax_f"]
        merged["is_nan_obs"] = merged["obs_tmax_f"].isna()

        # Compute mu_raw and sigma_raw
        mu_raw = []
        sig_raw = []
        for _, row in merged.iterrows():
            s = row["season"]
            p = fitted_seasons[s]
            m = p["a"] + p["b"] * row["ens_mean"]
            v = (p["c"] ** 2) + (p["d"] ** 2) * row["ens_var"]
            sig = math.sqrt(max(SIGMA_INST_PHYSICAL_FLOOR ** 2, v))
            mu_raw.append(m)
            sig_raw.append(sig)

        merged["mu_raw"] = mu_raw
        merged["sigma_raw"] = sig_raw
        merged["resid_raw"] = merged["obs_tmax_f"] - merged["mu_raw"]

        # Strictly causal trailing bias with window=30 days and shift(1)
        # For dates where obs is NaN, resid_raw is NaN. Rolling mean naturally skips NaN.
        merged["window_state"] = merged["resid_raw"].shift(1).rolling(window=30, min_periods=10).mean().fillna(0.0)
        merged["mu_forecast"] = merged["mu_raw"] + merged["window_state"]
        merged["sigma_forecast"] = merged["sigma_raw"] * c_train
        merged["c_train_applied"] = c_train
        merged["resid_calibrated"] = merged["obs_tmax_f"] - merged["mu_forecast"]

        # Calculate exact CDF pit_value
        pit_vals = []
        for _, row in merged.iterrows():
            if row["is_nan_obs"]:
                pit_vals.append(np.nan)
            else:
                z = (row["obs_tmax_f"] - row["mu_forecast"]) / row["sigma_forecast"]
                pit_vals.append(float(stats.norm.cdf(z)))
        merged["pit_value"] = pit_vals

        # Select final columns
        cols = [
            "date_str",
            "station",
            "year",
            "month",
            "season",
            "obs_tmax_f",
            "is_nan_obs",
            "ens_mean",
            "ens_var",
            "mu_raw",
            "mu_forecast",
            "sigma_raw",
            "sigma_forecast",
            "c_train_applied",
            "resid_raw",
            "resid_calibrated",
            "window_state",
            "pit_value",
        ]
        clean_df = merged[cols].rename(columns={"date_str": "date"}).copy()

        train_segment = clean_df[clean_df["year"] < 2019].copy()
        oos_segment = clean_df[clean_df["year"] == 2019].copy()

        all_train_records.append(train_segment)
        all_oos_records.append(oos_segment)

    df_train_all = pd.concat(all_train_records, ignore_index=True)
    df_oos_all = pd.concat(all_oos_records, ignore_index=True)

    train_parquet = OUT_DIR / "2000_2018_training_arrays.parquet"
    train_head_csv = OUT_DIR / "2000_2018_training_arrays_head20.csv"
    oos_parquet = OUT_DIR / "2019_oos_evaluation_arrays.parquet"
    oos_head_csv = OUT_DIR / "2019_oos_evaluation_arrays_head20.csv"

    df_train_all.to_parquet(train_parquet, index=False)
    df_train_all.head(20).to_csv(train_head_csv, index=False)
    df_oos_all.to_parquet(oos_parquet, index=False)
    df_oos_all.head(20).to_csv(oos_head_csv, index=False)

    print(f"Exported training arrays: {train_parquet} (N={len(df_train_all)}) | SHA256: {compute_sha256(train_parquet)}")
    print(f"Exported OOS arrays:      {oos_parquet} (N={len(df_oos_all)}) | SHA256: {compute_sha256(oos_parquet)}")


if __name__ == "__main__":
    main()
