#!/usr/bin/env python3
"""
scripts/p2_p3_process_and_lock_ghcn.py: P-2 Ingestion/QC and P-3 Version Locking Pipeline.

Executes:
1. P-2: Parses raw GHCN-Daily CSVs (2000-2019), aligns target_date (LST 00:00-23:59),
        converts TMAX tenths of °C to °F (tmax_f = tenths/10 * 1.8 + 32.0),
        generates QC stdout and writes to independent layer data/processed/truth_ghcn_daily/{station}.parquet.
        Compares with METAR double-track (All-Reports and Hourly-Only).
2. P-3: Computes SHA256 checksums, locks local mirror manifest to evidence/p3_truth_manifest.json.
"""

import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_GHCN_DIR = PROJECT_ROOT / "data" / "raw" / "ghcn_daily"
OUT_GHCN_DIR = PROJECT_ROOT / "data" / "processed" / "truth_ghcn_daily"
FEATURES_DIR = PROJECT_ROOT / "data" / "processed" / "calib-dataset-v2.0" / "features"
EVIDENCE_DIR = PROJECT_ROOT / "evidence"

STATIONS = {
    "KORD": "USW00094846",
    "KLGA": "USW00014732",
    "KATL": "USW00013874",
    "KDAL": "USW00013960",
    "KSEA": "USW00024233",
    "KLAX": "USW00023174",
    "KHOU": "USW00012918",
    "KMIA": "USW00012839",
    "KSFO": "USW00023234",
    "KAUS": "USW00013904",
}

YEARS = list(range(2000, 2020))


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main():
    print("================================================================================")
    print("  P-2 & P-3 DATA PIPELINE: VALIDATION, INGESTION & VERSION LOCKING (10 STATIONS) ")
    print("================================================================================")

    OUT_GHCN_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    qc_lines = []
    qc_lines.append("=== P-2 QUALITY CONTROL & DUAL-TRACK COMPARISON REPORT ===")
    qc_lines.append("Truth Source Layer: data/processed/truth_ghcn_daily/")
    qc_lines.append("Target Window: 2000-01-01 to 2019-12-31 (20 Full Years, 7305 Calendar Days)")
    qc_lines.append("-" * 80)

    p3_manifest = {
        "dataset_name": "GHCN-Daily Truth Layer (NCEI)",
        "window_years": "2000-2019",
        "fetch_date": "2026-09-23",
        "truth_source": "ghcn_daily",
        "files": {},
    }

    comparison_summary = []

    for st, ghcn_id in STATIONS.items():
        raw_csv = RAW_GHCN_DIR / f"{st}_{ghcn_id}.csv"
        assert raw_csv.exists(), f"Missing raw CSV for {st}: {raw_csv}"

        print(f"\nProcessing {st} ({ghcn_id})...")
        df_raw = pd.read_csv(raw_csv, low_memory=False)

        # Filter DATE for 2000 to 2019
        df_raw["target_date"] = pd.to_datetime(df_raw["DATE"])
        mask = (df_raw["target_date"] >= "2000-01-01") & (df_raw["target_date"] <= "2019-12-31")
        sub = df_raw[mask].copy()

        # Check total days
        expected_days = 7305  # 5 leap years (2000, 2004, 2008, 2012, 2016)
        actual_days = len(sub)
        missing_records = expected_days - actual_days

        # Check missing TMAX
        tmax_missing = sub["TMAX"].isna().sum()

        # Parse TMAX and TMIN
        # GHCN-Daily TMAX is in tenths of degrees C (e.g. 214 = 21.4°C)
        sub["tmax_c"] = sub["TMAX"] / 10.0
        sub["tmin_c"] = sub["TMIN"] / 10.0 if "TMIN" in sub.columns else np.nan

        # Convert to Fahrenheit: F = C * 1.8 + 32.0
        sub["tmax_f"] = np.round(sub["tmax_c"] * 1.8 + 32.0, 4)
        sub["tmin_f"] = np.round(sub["tmin_c"] * 1.8 + 32.0, 4) if "TMIN" in sub.columns else np.nan

        # CLI Integer Rounding equivalent (NWS CLI reports rounded to integer °F)
        # Using nullable Int64 to gracefully handle missing values without IntCastingNaNError
        sub["tmax_f_cli_rounded"] = np.round(sub["tmax_f"]).astype("Int64")

        # Structure final DataFrame
        out_df = pd.DataFrame({
            "station": st,
            "ghcn_id": ghcn_id,
            "target_date": sub["target_date"].dt.strftime("%Y-%m-%d"),
            "year": sub["target_date"].dt.year,
            "month": sub["target_date"].dt.month,
            "day": sub["target_date"].dt.day,
            "tmax_c": sub["tmax_c"],
            "tmin_c": sub["tmin_c"],
            "tmax_f": sub["tmax_f"],
            "tmin_f": sub["tmin_f"],
            "tmax_f_cli_rounded": sub["tmax_f_cli_rounded"],
            "tmax_attributes": sub["TMAX_ATTRIBUTES"] if "TMAX_ATTRIBUTES" in sub.columns else "",
            "truth_source": "ghcn_daily",
        }).sort_values("target_date").reset_index(drop=True)

        out_parquet = OUT_GHCN_DIR / f"{st}.parquet"
        out_df.to_parquet(out_parquet, index=False)
        sha = compute_sha256(out_parquet)

        p3_manifest["files"][st] = {
            "ghcn_id": ghcn_id,
            "parquet_file": f"{st}.parquet",
            "sha256": sha,
            "row_count": len(out_df),
            "expected_days": expected_days,
            "missing_count": int(tmax_missing),
            "completeness_pct": round((len(out_df) - int(tmax_missing)) / expected_days * 100, 2),
        }

        # Compare with existing METAR features layer (for available stations e.g. KORD, KMIA, KSFO, etc.)
        feat_obs_all = []
        feat_obs_hr = []
        feat_dates = []

        feat_dir = FEATURES_DIR / st
        if feat_dir.exists():
            for y in YEARS:
                f_p = feat_dir / f"{y}.parquet"
                if f_p.exists():
                    f_df = pd.read_parquet(f_p)
                    f_df["target_date"] = pd.to_datetime(f_df["target_date"]).dt.strftime("%Y-%m-%d")
                    feat_obs_all.append(f_df[["target_date", "tmax_daily_all_reports_f", "tmax_daily_hourly_only_f"]])

        if feat_obs_all:
            full_feat = pd.concat(feat_obs_all, ignore_index=True)
            merged_cmp = pd.merge(out_df, full_feat, on="target_date", how="inner")
            diff_all = merged_cmp["tmax_f"] - merged_cmp["tmax_daily_all_reports_f"]
            diff_hr = merged_cmp["tmax_f"] - merged_cmp["tmax_daily_hourly_only_f"]

            mean_diff_all = float(diff_all.mean())
            mean_diff_hr = float(diff_hr.mean())
            mean_abs_diff_all = float(diff_all.abs().mean())

            print(
                f"  {st}: N={len(out_df)} | Missing={tmax_missing} | "
                f"Mean(GHCN - METAR_All) = {mean_diff_all:+.3f}°F | "
                f"Mean(GHCN - METAR_Hourly) = {mean_diff_hr:+.3f}°F | "
                f"MeanAbs = {mean_abs_diff_all:.3f}°F"
            )
            comparison_summary.append({
                "station": st,
                "ghcn_id": ghcn_id,
                "row_count": len(out_df),
                "completeness_pct": f"{p3_manifest['files'][st]['completeness_pct']}%",
                "diff_vs_metar_all": f"{mean_diff_all:+.3f}°F",
                "diff_vs_metar_hourly": f"{mean_diff_hr:+.3f}°F",
                "sha256_prefix": sha[:12],
            })
        else:
            print(f"  {st}: N={len(out_df)} | Missing={tmax_missing} (METAR feature dir not found)")
            comparison_summary.append({
                "station": st,
                "ghcn_id": ghcn_id,
                "row_count": len(out_df),
                "completeness_pct": f"{p3_manifest['files'][st]['completeness_pct']}%",
                "diff_vs_metar_all": "N/A",
                "diff_vs_metar_hourly": "N/A",
                "sha256_prefix": sha[:12],
            })

    # Save P-3 Manifest
    manifest_path = EVIDENCE_DIR / "p3_truth_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(p3_manifest, f, indent=2)
    print(f"\nP-3 Manifest Saved: {manifest_path}")

    # Build P-2 QC Markdown Summary
    qc_md = []
    qc_md.append("# P-2 质控与双轨对比汇总表 (GHCN-Daily vs METAR Dual-Track QC)")
    qc_md.append("\n- 训练/回测窗口: 2000-01-01 至 2019-12-31 (20 全年)")
    qc_md.append("- 存储路径: `data/processed/truth_ghcn_daily/{station}.parquet`")
    qc_md.append("- 版本锁定清单: `evidence/p3_truth_manifest.json`")
    qc_md.append("\n| 站点 | GHCN 台站 ID | 总记录数 | 完整度 | 相比 METAR All 均值差 | 相比 METAR Hourly 均值差 | SHA256 前缀 |")
    qc_md.append("| :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for c in comparison_summary:
        qc_md.append(
            f"| **{c['station']}** | `{c['ghcn_id']}` | {c['row_count']} | {c['completeness_pct']} | "
            f"**{c['diff_vs_metar_all']}** | **{c['diff_vs_metar_hourly']}** | `{c['sha256_prefix']}...` |"
        )
    qc_md_text = "\n".join(qc_md)
    (EVIDENCE_DIR / "p2_qc_summary.md").write_text(qc_md_text, encoding="utf-8")
    print("\n" + qc_md_text)


if __name__ == "__main__":
    main()
