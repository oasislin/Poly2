#!/usr/bin/env python3
"""
scripts/standalone_reliability_check.py: Standalone Reliability Check by Probability Strata.
Specification: SPEC-RELIABILITY-001 (ADR-0017 Gate 2 Diagnostic View).

Zero internal project dependencies. Standard library + numpy, pandas, scipy.
Third-party verifiable.

Reads:
  - data/processed/audit_arrays/2000_2018_training_arrays.parquet
  - evidence/r6_kmia_parameters.json
  - evidence/r7_tail_parameters.json

Outputs:
  - evidence/reliability_check_main_global.csv (20 strata global pooling)
  - evidence/reliability_check_stratified_station_season.csv (12 station x season slices)
  - evidence/reliability_check_brier_skill.csv (Model vs. Climate Brier Skill Score)
"""

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Dict, Any, Tuple, List, Optional

import numpy as np
import pandas as pd
from scipy import stats, integrate

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TRAIN_PARQUET = PROJECT_ROOT / "data" / "processed" / "audit_arrays" / "2000_2018_training_arrays.parquet"
DEFAULT_R6_JSON = PROJECT_ROOT / "evidence" / "r6_kmia_parameters.json"
DEFAULT_R7_JSON = PROJECT_ROOT / "evidence" / "r7_tail_parameters.json"
DEFAULT_OUT_GLOBAL = PROJECT_ROOT / "evidence" / "reliability_check_main_global.csv"
DEFAULT_OUT_STRATIFIED = PROJECT_ROOT / "evidence" / "reliability_check_stratified_station_season.csv"
DEFAULT_OUT_BRIER = PROJECT_ROOT / "evidence" / "reliability_check_brier_skill.csv"


# ==============================================================================
# Ticket 01: EVT Variance, Station CDFs & Record Expansion
# ==============================================================================

def compute_evt_variance(station_params: Dict[str, Any]) -> float:
    """Compute theoretical variance factor of hybrid core + EVT GPD tail model."""
    u_l = station_params["u_left"]
    u_r = station_params["u_right"]
    xi_l = station_params["gpd_left"]["shape_xi"]
    beta_l = station_params["gpd_left"]["scale_beta"]
    xi_r = station_params["gpd_right"]["shape_xi"]
    beta_r = station_params["gpd_right"]["scale_beta"]

    # 1. Left tail integral
    def f_left(x):
        return (u_l - x)**2 * 0.05 * (1.0 / beta_l) * (1.0 + xi_l * x / beta_l)**(-1.0 / xi_l - 1.0)
    x_max_l = -beta_l / xi_l if xi_l < 0 else 50.0
    m2_l, _ = integrate.quad(f_left, 0, x_max_l * 0.9999)

    # 2. Right tail integral
    def f_right(x):
        return (u_r + x)**2 * 0.05 * (1.0 / beta_r) * (1.0 + xi_r * x / beta_r)**(-1.0 / xi_r - 1.0)
    x_max_r = -beta_r / xi_r if xi_r < 0 else 50.0
    m2_r, _ = integrate.quad(f_right, 0, x_max_r * 0.9999)

    # 3. Core (Gaussian baseline)
    def f_core(z):
        return z**2 * stats.norm.pdf(z)
    m2_core, _ = integrate.quad(f_core, u_l, u_r)

    var_evt = float(m2_l + m2_core + m2_r)
    return var_evt


def evaluate_station_cdf(
    station: str,
    y: float,
    mu: float,
    sigma_eff: float,
    r6_params: Dict[str, Any],
    r7_params: Dict[str, Any],
) -> float:
    """Evaluate cumulative distribution function F(y) for a given station."""
    if math.isinf(y):
        return 1.0 if y > 0 else 0.0

    z = (y - mu) / sigma_eff

    if station == "KMIA":
        # R-6 Johnson SU transformation
        jsu_p = r6_params["johnsonsu_parameters"]
        gamma = jsu_p["gamma"]
        delta = jsu_p["delta"]
        xi = jsu_p["xi"]
        lam = jsu_p["lambda"]
        z_norm = gamma + delta * np.arcsinh((z - xi) / lam)
        return float(stats.norm.cdf(z_norm))
    elif station == "KSFO":
        # R-7 EVT GPD Hybrid CDF
        st_p = r7_params["stations"]["KSFO"]
        u_l = st_p["u_left"]
        u_r = st_p["u_right"]
        xi_l = st_p["gpd_left"]["shape_xi"]
        beta_l = st_p["gpd_left"]["scale_beta"]
        xi_r = st_p["gpd_right"]["shape_xi"]
        beta_r = st_p["gpd_right"]["scale_beta"]

        if z < u_l:
            excess = u_l - z
            val = 1.0 + xi_l * excess / beta_l
            if val <= 0:
                return 0.0
            return float(0.05 * (val ** (-1.0 / xi_l)))
        elif z > u_r:
            excess = z - u_r
            val = 1.0 + xi_r * excess / beta_r
            if val <= 0:
                return 1.0
            return float(1.0 - 0.05 * (val ** (-1.0 / xi_r)))
        else:
            return float(stats.norm.cdf(z))
    else:
        # KORD (and standard default): Standard Gaussian Normal
        return float(stats.norm.cdf(z))


def expand_prediction_records(
    df: pd.DataFrame,
    r6_params: Dict[str, Any],
    r7_params: Dict[str, Any],
) -> pd.DataFrame:
    """
    Expand training window station-day records into (p_pred, hit) pairs across 7 discrete bins.
    """
    valid = df[~df["is_nan_obs"]].copy()

    # Precompute kappa_evt for each station
    kappa_evt_map = {}
    for st in ["KORD", "KMIA", "KSFO"]:
        if st in r7_params["stations"]:
            var_f = compute_evt_variance(r7_params["stations"][st])
            kappa_evt_map[st] = float(np.sqrt(var_f))
        else:
            kappa_evt_map[st] = 1.0

    records = []
    for _, row in valid.iterrows():
        st = row["station"]
        date_str = str(row["date"])
        year = int(row["year"])
        month = int(row["month"])
        season = str(row["season"])
        obs_y = float(row["obs_tmax_f"])
        mu = float(row["mu_forecast"])
        sig_base = float(row["sigma_forecast"])

        kappa_evt = kappa_evt_map.get(st, 1.0)
        sig_eff = sig_base * kappa_evt

        c0 = int(round(mu))
        bin_bounds = [
            (-np.inf, c0 - 5.5),
            (c0 - 5.5, c0 - 3.5),
            (c0 - 3.5, c0 - 1.5),
            (c0 - 1.5, c0 + 1.5),
            (c0 + 1.5, c0 + 3.5),
            (c0 + 3.5, c0 + 5.5),
            (c0 + 5.5, np.inf),
        ]

        # Calculate CDF at each boundary
        cdfs = [evaluate_station_cdf(st, b[1], mu, sig_eff, r6_params, r7_params) for b in bin_bounds]

        # Calculate interval probabilities
        p_bins = np.zeros(7, dtype=np.float64)
        p_bins[0] = cdfs[0]
        for k in range(1, 6):
            p_bins[k] = cdfs[k] - cdfs[k - 1]
        p_bins[6] = 1.0 - cdfs[5]

        # Simplex projection & normalization
        p_bins = np.clip(p_bins, 0.0, 1.0)
        sum_p = np.sum(p_bins)
        if sum_p > 0:
            p_bins /= sum_p
        else:
            p_bins = np.full(7, 1.0 / 7.0)

        # Hit determination with discrete interval [lb, ub)
        # Observational resolution is preserved; interval half-open
        for k in range(7):
            lb, ub = bin_bounds[k]
            hit = 1 if (obs_y >= lb and obs_y < ub) else 0
            records.append({
                "date": date_str,
                "station": st,
                "year": year,
                "month": month,
                "season": season,
                "bin_idx": k,
                "bin_lower": lb,
                "bin_upper": ub,
                "p_pred": float(p_bins[k]),
                "hit": hit,
            })

    return pd.DataFrame(records)


# ==============================================================================
# Ticket 02: Global 20-Strata Pooling & Stratified 12-Cell Matrix
# ==============================================================================

def build_global_reliability_table(
    df_expanded: pd.DataFrame,
    num_bins: int = 20,
) -> Tuple[pd.DataFrame, float]:
    """
    Build global reliability table pooling all (p_pred, hit) records into equal-width strata.
    """
    p_arr = df_expanded["p_pred"].to_numpy(dtype=np.float64)
    h_arr = df_expanded["hit"].to_numpy(dtype=np.float64)
    n_total = len(p_arr)

    edges = np.linspace(0.0, 1.0, num_bins + 1)
    bin_idx = np.clip(np.digitize(p_arr, edges) - 1, 0, num_bins - 1)

    rows = []
    weighted_err_sum = 0.0

    for b in range(num_bins):
        low_e = edges[b]
        high_e = edges[b + 1]
        range_str = f"[{low_e:.2f}, {high_e:.2f}{']' if b == num_bins - 1 else ')'}"

        mask = bin_idx == b
        cnt = int(np.sum(mask))

        if cnt > 0:
            m_p = float(np.mean(p_arr[mask]))
            m_h = float(np.mean(h_arr[mask]))
            abs_bias = float(abs(m_p - m_h))
            # Standard binomial 95% confidence half-width
            ci_half = float(1.96 * math.sqrt(max(0.0, m_h * (1.0 - m_h)) / cnt))
            is_outside = bool(abs_bias > ci_half)
            weighted_err_sum += abs_bias * cnt
        else:
            m_p = float((low_e + high_e) / 2.0)
            m_h = 0.0
            abs_bias = 0.0
            ci_half = 0.0
            is_outside = False

        rows.append({
            "stratum_id": b + 1,
            "stratum_range": range_str,
            "sample_count_n": cnt,
            "mean_pred_prob": m_p,
            "empirical_hit_freq": m_h,
            "abs_bias": abs_bias,
            "ci_95_half_width": ci_half,
            "is_outside_ci": is_outside,
        })

    weighted_ece = float(weighted_err_sum / n_total) if n_total > 0 else 0.0
    return pd.DataFrame(rows), weighted_ece


def build_stratified_warning_table(
    df_expanded: pd.DataFrame,
    num_bins: int = 10,
) -> pd.DataFrame:
    """
    Build 12-cell stratified warning table (3 stations x 4 seasons).
    Focuses on detecting local sub-group bias dilution (e.g. KSFO Summer).
    """
    stations = ["KORD", "KMIA", "KSFO"]
    seasons = ["Winter", "Spring", "Summer", "Autumn"]

    all_stratified_rows = []

    for st in stations:
        for se in seasons:
            sub = df_expanded[(df_expanded["station"] == st) & (df_expanded["season"] == se)]
            table_df, _ = build_global_reliability_table(sub, num_bins=num_bins)
            table_df.insert(0, "station", st)
            table_df.insert(1, "season", se)
            all_stratified_rows.append(table_df)

    if all_stratified_rows:
        return pd.concat(all_stratified_rows, ignore_index=True)
    return pd.DataFrame()


# ==============================================================================
# Ticket 03: Climatology Baseline & Brier Skill Score Calculation
# ==============================================================================

def compute_brier_skill_scores(
    df_expanded: pd.DataFrame,
    df_train_raw: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute Brier Scores for Model and LOYO Climatological Baseline, and Brier Skill Score (BSS).
    BSS = 1 - BS_model / BS_clim.
    """
    # 1. Precompute LOYO climatological pools by (station, month, year)
    valid_raw = df_train_raw[~df_train_raw["is_nan_obs"]].copy()
    
    # Map: (station, month) -> {year: array of observations}
    clim_lookup: Dict[Tuple[str, int], Dict[int, np.ndarray]] = {}
    all_by_st_mo: Dict[Tuple[str, int], np.ndarray] = {}

    for (st, mo), grp in valid_raw.groupby(["station", "month"]):
        clim_lookup[(st, mo)] = {}
        all_obs = []
        for yr, y_grp in grp.groupby("year"):
            arr = np.sort(y_grp["obs_tmax_f"].to_numpy(dtype=np.float64))
            clim_lookup[(st, mo)][int(yr)] = arr
            all_obs.append(arr)
        if all_obs:
            all_by_st_mo[(st, mo)] = np.sort(np.concatenate(all_obs))

    # Pre-build LOYO pools: (station, month, year) -> sorted array of obs
    loyo_pool_cache: Dict[Tuple[str, int, int], np.ndarray] = {}
    for (st, mo), yr_dict in clim_lookup.items():
        all_yrs = list(yr_dict.keys())
        for yr in all_yrs:
            other_arrs = [yr_dict[y] for y in all_yrs if y != yr]
            if other_arrs:
                loyo_pool_cache[(st, mo, yr)] = np.sort(np.concatenate(other_arrs))
            else:
                loyo_pool_cache[(st, mo, yr)] = yr_dict[yr]

    # 2. Compute p_clim for each expanded record
    p_preds = df_expanded["p_pred"].to_numpy(dtype=np.float64)
    hits = df_expanded["hit"].to_numpy(dtype=np.float64)
    stations = df_expanded["station"].to_numpy()
    months = df_expanded["month"].to_numpy(dtype=int)
    years = df_expanded["year"].to_numpy(dtype=int)
    seasons = df_expanded["season"].to_numpy()
    lbs = df_expanded["bin_lower"].to_numpy(dtype=np.float64)
    ubs = df_expanded["bin_upper"].to_numpy(dtype=np.float64)

    n_records = len(df_expanded)
    p_clims = np.zeros(n_records, dtype=np.float64)

    for i in range(n_records):
        st = stations[i]
        mo = months[i]
        yr = years[i]
        lb = lbs[i]
        ub = ubs[i]

        pool = loyo_pool_cache.get((st, mo, yr))
        if pool is None or len(pool) == 0:
            pool = all_by_st_mo.get((st, mo), np.array([]))

        if len(pool) > 0:
            # Count elements in [lb, ub) using binary search
            i_low = np.searchsorted(pool, lb, side="left")
            i_high = np.searchsorted(pool, ub, side="left")
            cnt = i_high - i_low
            p_clims[i] = cnt / len(pool)
        else:
            p_clims[i] = 1.0 / 7.0

    sq_err_model = (p_preds - hits) ** 2
    sq_err_clim = (p_clims - hits) ** 2

    # 3. Aggregate across scopes: Global, Stations, Seasons
    scopes = []
    # Global
    scopes.append(("Global", "Global", np.ones(n_records, dtype=bool)))
    # By Station
    for st in ["KORD", "KMIA", "KSFO"]:
        scopes.append(("Station", st, stations == st))
    # By Season
    for se in ["Winter", "Spring", "Summer", "Autumn"]:
        scopes.append(("Season", se, seasons == se))

    bss_rows = []
    for scope_type, scope_name, mask in scopes:
        cnt = int(np.sum(mask))
        if cnt > 0:
            bs_m = float(np.mean(sq_err_model[mask]))
            bs_c = float(np.mean(sq_err_clim[mask]))
            bss = float(1.0 - (bs_m / bs_c)) if bs_c > 0 else 0.0
            is_skill = bool(bss > 0.0)
        else:
            bs_m, bs_c, bss, is_skill = 0.0, 0.0, 0.0, False

        bss_rows.append({
            "scope_type": scope_type,
            "scope_name": scope_name,
            "sample_count_n": cnt,
            "bs_model": bs_m,
            "bs_clim": bs_c,
            "brier_skill_score": bss,
            "is_skillful": is_skill,
        })

    return pd.DataFrame(bss_rows)


# ==============================================================================
# Ticket 04: Full Pipeline Runner & Standalone CLI
# ==============================================================================

def run_reliability_pipeline(
    df_train: pd.DataFrame,
    r6_params: Dict[str, Any],
    r7_params: Dict[str, Any],
    out_global_path: Optional[Path] = None,
    out_stratified_path: Optional[Path] = None,
    out_brier_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Execute the complete reliability check pipeline."""
    # 1. Expand records into (p_pred, hit) pairs
    df_expanded = expand_prediction_records(df_train, r6_params, r7_params)

    # 2. Build global 20-strata reliability table
    table_global, weighted_ece = build_global_reliability_table(df_expanded, num_bins=20)

    # 3. Build stratified 12-cell warning table
    table_stratified = build_stratified_warning_table(df_expanded, num_bins=10)

    # 4. Compute Brier Skill Scores
    table_brier = compute_brier_skill_scores(df_expanded, df_train)

    # 5. Save artifacts if paths provided
    if out_global_path is not None:
        out_global_path = Path(out_global_path)
        out_global_path.parent.mkdir(parents=True, exist_ok=True)
        table_global.to_csv(out_global_path, index=False)

    if out_stratified_path is not None:
        out_stratified_path = Path(out_stratified_path)
        out_stratified_path.parent.mkdir(parents=True, exist_ok=True)
        table_stratified.to_csv(out_stratified_path, index=False)

    if out_brier_path is not None:
        out_brier_path = Path(out_brier_path)
        out_brier_path.parent.mkdir(parents=True, exist_ok=True)
        table_brier.to_csv(out_brier_path, index=False)

    return {
        "df_expanded": df_expanded,
        "table_global": table_global,
        "weighted_ece": weighted_ece,
        "table_stratified": table_stratified,
        "table_brier": table_brier,
    }


def main():
    parser = argparse.ArgumentParser(
        description="SPEC-RELIABILITY-001: Standalone Reliability Check by Probability Strata."
    )
    parser.add_argument(
        "--train-parquet",
        type=Path,
        default=DEFAULT_TRAIN_PARQUET,
        help="Path to 2000-2018 training arrays parquet.",
    )
    parser.add_argument(
        "--r6-json",
        type=Path,
        default=DEFAULT_R6_JSON,
        help="Path to R-6 KMIA parameters JSON.",
    )
    parser.add_argument(
        "--r7-json",
        type=Path,
        default=DEFAULT_R7_JSON,
        help="Path to R-7 tail parameters JSON.",
    )
    parser.add_argument(
        "--out-global",
        type=Path,
        default=DEFAULT_OUT_GLOBAL,
        help="Output path for global 20-strata CSV.",
    )
    parser.add_argument(
        "--out-stratified",
        type=Path,
        default=DEFAULT_OUT_STRATIFIED,
        help="Output path for stratified 12-cell CSV.",
    )
    parser.add_argument(
        "--out-brier",
        type=Path,
        default=DEFAULT_OUT_BRIER,
        help="Output path for Brier Skill Score CSV.",
    )

    args = parser.parse_args()

    print("================================================================================")
    print("      SPEC-RELIABILITY-001: RELIABILITY CHECK BY PROBABILITY STRATA            ")
    print("================================================================================")
    print(f"Loading training data: {args.train_parquet}")
    if not args.train_parquet.exists():
        raise FileNotFoundError(f"{args.train_parquet} not found.")

    df_train = pd.read_parquet(args.train_parquet)
    print(f"Loaded {len(df_train)} rows across stations: {df_train['station'].unique().tolist()}")

    with open(args.r6_json, "r", encoding="utf-8") as f:
        r6_params = json.load(f)
    with open(args.r7_json, "r", encoding="utf-8") as f:
        r7_params = json.load(f)

    print("Executing full reliability pipeline...")
    res = run_reliability_pipeline(
        df_train=df_train,
        r6_params=r6_params,
        r7_params=r7_params,
        out_global_path=args.out_global,
        out_stratified_path=args.out_stratified,
        out_brier_path=args.out_brier,
    )

    print(f"\n[Artifact 1] Global Reliability Table (20 Strata): {args.out_global}")
    print(f"Global Weighted ECE: {res['weighted_ece']:.4%}")
    print(res["table_global"].to_string(index=False))

    print(f"\n[Artifact 2] Stratified Warning Table (12 Cells): {args.out_stratified}")
    # Print KSFO Summer as priority highlight
    ksfo_summer = res["table_stratified"][
        (res["table_stratified"]["station"] == "KSFO") & (res["table_stratified"]["season"] == "Summer")
    ]
    print("\nHighlight: KSFO Summer Diagnostic View:")
    print(ksfo_summer.to_string(index=False))

    print(f"\n[Artifact 3] Brier Skill Score Summary: {args.out_brier}")
    print(res["table_brier"].to_string(index=False))
    print("\nExecution complete. All artifacts generated successfully.")


if __name__ == "__main__":
    main()
