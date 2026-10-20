#!/usr/bin/env python3
"""
scripts/audit_t3/chk04_repeatability.py:
P4-BLIND-AUDIT-CHK-04 Year-by-Year Phase Repeatability & Null Hypothesis Testing.

Statutory & Mandate Context:
- Mandate: docs/audit/P4-BLIND-AUDIT-CHK-04_开发端指导_20261021.md
- Specification: docs/audit/P4-BLIND-AUDIT-CHK-04_逐年相位可重复性_任务书_20261021.md
- Scope: KORD, KMIA x tmax x 2000-2018 (strictly training window).
- Task A: Backfill KMIA 2000-2018 x 4 phases mean_raw_ratio into year-phase panel.
- Task B: Null hypothesis repeatability testing across 19-year x 4-phase units.
- Absolute Red Lines:
  - NO model construction, NO fitting of multipliers.
  - NO modification of a/b/c/d or c_train.
  - NO retraining, NO writing to pkl or manifest.json.
  - NO reading of 2019 data.
  - Pure raw values and code-lowered boolean results; pass/fail conclusions left to reviewer.
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
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.airgap import verify_year_whitelist

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("chk04_repeatability")

GHCN_DIR = PROJECT_ROOT / "data" / "processed" / "truth_ghcn_daily"
GEFS_DIR = PROJECT_ROOT / "data" / "processed" / "gefs_factors"
if not GEFS_DIR.exists():
    GEFS_DIR = PROJECT_ROOT / "data" / "processed" / "calib-dataset-v2.0" / "gefs_factors"

MANIFEST_FILE = PROJECT_ROOT / "data" / "models" / "manifest.json"
EVIDENCE_DIR = PROJECT_ROOT / "evidence" / "audit_t3"

OUT_PANEL_CSV = EVIDENCE_DIR / "p4blind_chk04_year_phase_panel.csv"
OUT_REPEATABILITY_CSV = EVIDENCE_DIR / "p4blind_chk04_repeatability.csv"

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
    verify_year_whitelist(years, f"chk04_repeatability_load_data({station})")

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
    """Load model parameters from manifest.json."""
    data = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    return data.get("models", {})


def compute_station_year_phase_panel(
    station: str,
    manifest_models: Dict[str, Dict[str, Any]],
) -> pd.DataFrame:
    """Compute year-by-year mean_raw_ratio for all 4 phases across 2000-2018."""
    logger.info("Computing year x phase panel for station: %s", station)
    df_ghcn, df_gefs = load_station_training_data(station, TRAIN_YEARS)

    cell_dfs = {}
    for season in SEASONS:
        for lead in LEADS:
            cdf = extract_cell_dataset(df_ghcn, df_gefs, season, "Max", lead)
            m_key = f"{station}_{season}_Max_lead{lead}h.pkl"
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

    st_full = pd.concat(list(cell_dfs.values()), ignore_index=True)

    rows = []
    for year in TRAIN_YEARS:
        year_sub = st_full[st_full["year"] == year]
        for phase_h in [0, 6, 12, 18]:
            p_sub = year_sub[year_sub["phase_h"] == phase_h]
            cell_rrs = []
            for (s, l), cdf in p_sub.groupby(["season", "lead"]):
                if len(cdf) > 1:
                    r_var = float(np.var(cdf["resid_calib"], ddof=1))
                    s_m2 = float(np.mean(cdf["sig_raw_sq"]))
                    if s_m2 > 0:
                        cell_rrs.append(r_var / s_m2)

            mean_rr = float(np.mean(cell_rrs)) if cell_rrs else float("nan")
            rows.append({
                "station": station,
                "phase_h": phase_h,
                "year": year,
                "mean_raw_ratio": round(mean_rr, 6) if not math.isnan(mean_rr) else None,
            })

    return pd.DataFrame(rows)


def analyze_station_repeatability(
    station: str,
    df_station_panel: pd.DataFrame,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Perform null hypothesis repeatability diagnostics on year-phase panel for a station."""
    piv = df_station_panel.pivot(index="year", columns="phase_h", values="mean_raw_ratio")
    # Rank descending: 1 = highest mean_raw_ratio, 4 = lowest
    ranks = piv.rank(axis=1, ascending=False)

    stats_list = []
    for phase_h in [0, 6, 12, 18]:
        vals = piv[phase_h]
        p_ranks = ranks[phase_h]
        top_years = int((p_ranks == 1).sum())
        bottom_years = int((p_ranks == 4).sum())
        mean_val = float(vals.mean())
        std_val = float(vals.std(ddof=1))

        stats_list.append({
            "station": station,
            "phase_h": phase_h,
            "mean": round(mean_val, 6),
            "std": round(std_val, 6),
            "top_years": top_years,
            "bottom_years": bottom_years,
        })

    df_rep = pd.DataFrame(stats_list)
    df_rep["rank"] = df_rep["mean"].rank(ascending=False).astype(int)

    # Compute max difference and noise ratios
    means = {row["phase_h"]: row["mean"] for row in stats_list}
    stds = {row["phase_h"]: row["std"] for row in stats_list}
    max_phase = max(means, key=means.get)
    min_phase = min(means, key=means.get)
    max_diff = means[max_phase] - means[min_phase]

    pooled_std = math.sqrt(float(np.mean([s ** 2 for s in stds.values()])))
    diff_to_std_ratio = max_diff / pooled_std if pooled_std > 0 else float("nan")

    # Null hypothesis H0 p-values (binomial test assuming uniform random ranks p=0.25)
    max_top_count = max(row["top_years"] for row in stats_list)
    max_bottom_count = max(row["bottom_years"] for row in stats_list)
    p_val_top = float(stats.binom.sf(max_top_count - 1, 19, 0.25))
    p_val_bottom = float(stats.binom.sf(max_bottom_count - 1, 19, 0.25))

    # Code-lowered boolean results (thresholds from mandate / standard significance)
    h0_top_rejected = bool(max_top_count >= 10)  # threshold >= 10 years out of 19 (p < 0.005)
    h0_bottom_rejected = bool(max_bottom_count >= 10)
    repeatability_signal_to_noise_gt_1 = bool(diff_to_std_ratio >= 1.0)

    diag_info = {
        "station": station,
        "max_phase": max_phase,
        "min_phase": min_phase,
        "max_diff": round(max_diff, 6),
        "pooled_std": round(pooled_std, 6),
        "diff_to_std_ratio": round(diff_to_std_ratio, 6),
        "max_top_count": max_top_count,
        "max_bottom_count": max_bottom_count,
        "p_val_top": round(p_val_top, 8),
        "p_val_bottom": round(p_val_bottom, 8),
        "h0_top_rejected": h0_top_rejected,
        "h0_bottom_rejected": h0_bottom_rejected,
        "repeatability_signal_to_noise_gt_1": repeatability_signal_to_noise_gt_1,
    }

    return df_rep, diag_info


def run_pipeline() -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """Execute complete CHK-04 pipeline."""
    logger.info("=== Running P4-BLIND-AUDIT-CHK-04 Pipeline ===")
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    manifest_models = load_manifest_model_params()

    # Task A: Compute 2000-2018 year-phase panels for both stations
    kord_panel = compute_station_year_phase_panel("KORD", manifest_models)
    kmia_panel = compute_station_year_phase_panel("KMIA", manifest_models)
    full_panel = pd.concat([kord_panel, kmia_panel], ignore_index=True)

    full_panel.to_csv(OUT_PANEL_CSV, index=False)
    logger.info("Saved Year-Phase Panel CSV to %s (rows: %d)", OUT_PANEL_CSV, len(full_panel))

    # Task B: Repeatability analysis for KORD and KMIA
    kord_rep, kord_diag = analyze_station_repeatability("KORD", kord_panel)
    kmia_rep, kmia_diag = analyze_station_repeatability("KMIA", kmia_panel)
    full_rep = pd.concat([kord_rep, kmia_rep], ignore_index=True)

    full_rep.to_csv(OUT_REPEATABILITY_CSV, index=False)
    logger.info("Saved Repeatability CSV to %s (rows: %d)", OUT_REPEATABILITY_CSV, len(full_rep))

    summary_diag = {"KORD": kord_diag, "KMIA": kmia_diag}
    return full_panel, full_rep, summary_diag


def main():
    parser = argparse.ArgumentParser(description="P4-BLIND-AUDIT-CHK-04 Repeatability Pipeline")
    parser.add_argument("--run-all", action="store_true", help="Run full CHK-04 diagnostics")
    args = parser.parse_args()

    full_panel, full_rep, summary_diag = run_pipeline()

    print("\n=== Year-Phase Panel Sample (KORD Head 8) ===")
    print(full_panel[full_panel["station"] == "KORD"].head(8).to_string(index=False))

    print("\n=== Year-Phase Panel Sample (KMIA Head 8 - Backfilled) ===")
    print(full_panel[full_panel["station"] == "KMIA"].head(8).to_string(index=False))

    print("\n=== Full Repeatability Table (p4blind_chk04_repeatability.csv) ===")
    print(full_rep.to_string(index=False))

    print("\n=== Lowered Boolean Diagnostic Summary ===")
    for st, diag in summary_diag.items():
        print(f"\n[{st}]")
        print(f"  Max Phase = {diag['max_phase']}h (mean={full_rep[(full_rep['station']==st)&(full_rep['phase_h']==diag['max_phase'])]['mean'].values[0]})")
        print(f"  Min Phase = {diag['min_phase']}h (mean={full_rep[(full_rep['station']==st)&(full_rep['phase_h']==diag['min_phase'])]['mean'].values[0]})")
        print(f"  Max Diff across Phases = {diag['max_diff']}")
        print(f"  Pooled Interannual Std = {diag['pooled_std']}")
        print(f"  Diff / Std Ratio = {diag['diff_to_std_ratio']} (ratio >= 1.0: {diag['repeatability_signal_to_noise_gt_1']})")
        print(f"  Top Years Count = {diag['max_top_count']} / 19 (H0 p-value = {diag['p_val_top']:.2e}, H0 rejected: {diag['h0_top_rejected']})")
        print(f"  Bottom Years Count = {diag['max_bottom_count']} / 19 (H0 p-value = {diag['p_val_bottom']:.2e}, H0 rejected: {diag['h0_bottom_rejected']})")

    logger.info("P4-BLIND-AUDIT-CHK-04 completed successfully.")
    sys.exit(0)


if __name__ == "__main__":
    main()
