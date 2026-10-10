#!/usr/bin/env python3
"""
scripts/check_r1_unit_and_rounding.py: R-1 Unit Convention and Rounding Exclusion Script.

Mandated by Review Committee R-1 Directive:
- Evaluates raw METAR text: parses integer dry-bulb temperature (Body) vs 0.1°C RMK T-group (High-Res).
- Computes empirical difference: Body vs High-Res across all reports for KORD, KMIA, KSFO (2019).
- Computes daily Tmax difference: Daily Tmax (Body) vs Daily Tmax (High-Res) and All-Reports vs Hourly-Only.
- Outputs purely numeric statistics to stdout without narrative embellishments.
"""

import gzip
from pathlib import Path
import re
import sys
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_IEM_DIR = PROJECT_ROOT / "data" / "raw" / "iem"
FEATURES_DIR = PROJECT_ROOT / "data" / "processed" / "calib-dataset-v2.0" / "features"
GEFS_DIR = PROJECT_ROOT / "data" / "processed" / "calib-dataset-v2.0" / "gefs_factors"
STATIONS = ["KORD", "KMIA", "KSFO"]


def parse_metar_body_temp_c(metar_text: str):
    if not isinstance(metar_text, str):
        return None
    match = re.search(r"(?:^|\s)(M?\d{2})\/(M?\d{2})(?=\s|$)", metar_text)
    if not match:
        return None
    raw_t = match.group(1)
    return -float(raw_t[1:]) if raw_t.startswith("M") else float(raw_t)


def parse_metar_t_group_c(metar_text: str):
    if not isinstance(metar_text, str):
        return None
    match = re.search(r"(?:^|\s)T([01])(\d{3})", metar_text)
    if not match:
        return None
    sign_char = match.group(1)
    val = float(match.group(2)) / 10.0
    return -val if sign_char == "1" else val


def main():
    print("================================================================================")
    print("  R-1 EXCLUSION CHECK: METAR BODY ROUNDED VS RMK T-GROUP FULL PRECISION (2019)  ")
    print("================================================================================")

    for station in STATIONS:
        gz_file = RAW_IEM_DIR / station / "2019.csv.gz"
        if not gz_file.exists():
            print(f"Error: {gz_file} does not exist", file=sys.stderr)
            continue

        with gzip.open(gz_file, "rt") as f:
            df_raw = pd.read_csv(f)

        df_raw["body_c"] = df_raw["metar"].apply(parse_metar_body_temp_c)
        df_raw["t_c"] = df_raw["metar"].apply(parse_metar_t_group_c)

        valid_mask = (~df_raw["body_c"].isna()) & (~df_raw["t_c"].isna())
        valid_df = df_raw[valid_mask].copy()

        body_c = valid_df["body_c"].values
        t_c = valid_df["t_c"].values
        diff_c = body_c - t_c
        diff_f = diff_c * 1.8

        df_raw["valid_dt"] = pd.to_datetime(df_raw["valid"])
        df_raw["date"] = df_raw["valid_dt"].dt.date
        daily_body_c = df_raw.groupby("date")["body_c"].max()
        daily_t_c = df_raw.groupby("date")["t_c"].max()
        daily_diff_f = (daily_body_c - daily_t_c) * 1.8

        # Load processed features
        feat_file = FEATURES_DIR / station / "2019.parquet"
        df_feat = pd.read_parquet(feat_file)
        tmax_all_f = df_feat["tmax_daily_all_reports_f"].values
        tmax_hr_f = df_feat["tmax_daily_hourly_only_f"].values
        diff_speci_f = tmax_all_f - tmax_hr_f

        # Load GEFS 18h tmax
        gefs_file = GEFS_DIR / station / "2019.parquet"
        df_gefs = pd.read_parquet(gefs_file)
        df_gefs["target_date"] = pd.to_datetime(df_gefs["target_date"]).dt.date
        tmax_18h = df_gefs[(df_gefs["variable"] == "tmax") & (df_gefs["lead_hours"] == 18)].copy()
        tmax_18h["temp_f"] = (tmax_18h["value_K"] - 273.15) * 1.8 + 32.0
        gefs_mean_df = tmax_18h.groupby("target_date")["temp_f"].mean().reset_index()

        df_feat["target_date"] = pd.to_datetime(df_feat["target_date"]).dt.date
        merged = pd.merge(df_feat, gefs_mean_df, on="target_date", how="inner")
        bias_all_reports = (merged["tmax_daily_all_reports_f"] - merged["temp_f"]).values
        bias_hourly_only = (merged["tmax_daily_hourly_only_f"] - merged["temp_f"]).values

        print(f"\n--- Station: {station} ---")
        print(f"Total RAW METAR Records Evaluated: {len(df_raw)}")
        print(f"Paired (Body & T-Group) Records: {len(valid_df)} ({len(valid_df)/len(df_raw)*100:.2f}%)")
        print("Record-Level Difference (Body - High-Res):")
        print(f"  Mean Difference (°C): {np.mean(diff_c):.6f}")
        print(f"  Mean Difference (°F): {np.mean(diff_f):.6f}")
        print(f"  Mean Absolute Difference (°F): {np.mean(np.abs(diff_f)):.6f}")
        print(f"  Std Difference (°F): {np.std(diff_f):.6f}")
        print("Daily Tmax Difference (Max Body - Max High-Res):")
        print(f"  Mean Daily Difference (°F): {np.mean(daily_diff_f):.6f}")
        print(f"  Mean Absolute Daily Difference (°F): {np.mean(np.abs(daily_diff_f)):.6f}")
        print("Daily Dataset Comparison (All-Reports vs Hourly-Only):")
        print(f"  Mean Difference (All-Reports - Hourly-Only) (°F): {np.mean(diff_speci_f):.6f}")
        print("Raw GEFS Uncalibrated Cold Bias (2019 OOS):")
        print(f"  Raw Cold Bias using All-Reports (°F): {np.mean(bias_all_reports):.6f}")
        print(f"  Raw Cold Bias using Hourly-Only (°F): {np.mean(bias_hourly_only):.6f}")


if __name__ == "__main__":
    main()
