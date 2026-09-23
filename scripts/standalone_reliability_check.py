#!/usr/bin/env python3
"""
scripts/standalone_reliability_check.py: Standalone Reliability Check by Probability Strata.
Specification: SPEC-RELIABILITY-001 (ADR-0017 Gate 2 Diagnostic View).

Zero internal project dependencies. Standard library + numpy, pandas, scipy.
Third-party verifiable.
"""

import argparse
import json
import math
from pathlib import Path
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
# Helper Utilities: Math, Intervals & Persistence
# ==============================================================================

def _integrate_gpd_tail(u: float, beta: float, xi: float, is_right_tail: bool) -> float:
    """Helper to integrate tail variance component under Generalized Pareto Distribution."""
    sign = 1.0 if is_right_tail else -1.0

    def integrand(x):
        val = u + sign * x
        return (val**2) * 0.05 * (1.0 / beta) * (1.0 + xi * x / beta)**(-1.0 / xi - 1.0)

    x_max = -beta / xi if xi < 0 else 50.0
    integral_val, _ = integrate.quad(integrand, 0, x_max * 0.9999)
    return float(integral_val)


def compute_binomial_ci_half_width(empirical_freq: float, n_count: int, z: float = 1.96) -> float:
    """
    Compute binomial 95% confidence half-width.
    Uses standard Wald interval when 0 < f < 1, and Wilson score interval when f in {0, 1}.
    """
    if n_count <= 0:
        return float(np.nan)
    variance_term = empirical_freq * (1.0 - empirical_freq)
    if variance_term > 0:
        return float(z * math.sqrt(variance_term / n_count))
    # Wilson score interval boundary distance for boundary empirical frequencies
    # Plausible interval width from boundary: z^2 / (n + z^2)
    return float((z**2) / (n_count + z**2))


def _save_dataframe(df: pd.DataFrame, out_path: Optional[Path]) -> None:
    """Helper to persist DataFrame to disk if path is provided."""
    if out_path is not None:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)


# ==============================================================================
# Ticket 01: EVT Variance, Station CDFs & Record Expansion
# ==============================================================================

def compute_evt_variance(station_params: Dict[str, Any]) -> float:
    """Compute theoretical variance factor of hybrid core + EVT GPD tail model."""
    u_l = station_params["u_left"]
    u_r = station_params["u_right"]
    gpd_l = station_params["gpd_left"]
    gpd_r = station_params["gpd_right"]

    m2_left = _integrate_gpd_tail(u_l, gpd_l["scale_beta"], gpd_l["shape_xi"], is_right_tail=False)
    m2_right = _integrate_gpd_tail(u_r, gpd_r["scale_beta"], gpd_r["shape_xi"], is_right_tail=True)

    def f_core(z):
        return z**2 * stats.norm.pdf(z)

    m2_core, _ = integrate.quad(f_core, u_l, u_r)
    return float(m2_left + m2_core + m2_right)


def _evaluate_evt_tail_cdf(z: float, st_params: Dict[str, Any]) -> float:
    """Evaluate hybrid core Gaussian + EVT GPD tail cumulative distribution function."""
    u_l, u_r = st_params["u_left"], st_params["u_right"]
    xi_l, beta_l = st_params["gpd_left"]["shape_xi"], st_params["gpd_left"]["scale_beta"]
    xi_r, beta_r = st_params["gpd_right"]["shape_xi"], st_params["gpd_right"]["scale_beta"]

    if z < u_l:
        val = 1.0 + xi_l * (u_l - z) / beta_l
        return 0.0 if val <= 0 else float(0.05 * (val ** (-1.0 / xi_l)))
    elif z > u_r:
        val = 1.0 + xi_r * (z - u_r) / beta_r
        return 1.0 if val <= 0 else float(1.0 - 0.05 * (val ** (-1.0 / xi_r)))
    return float(stats.norm.cdf(z))


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
        p = r6_params["johnsonsu_parameters"]
        z_norm = p["gamma"] + p["delta"] * np.arcsinh((z - p["xi"]) / p["lambda"])
        return float(stats.norm.cdf(z_norm))
    elif station == "KSFO":
        return _evaluate_evt_tail_cdf(z, r7_params["stations"]["KSFO"])
    return float(stats.norm.cdf(z))


def _compute_bracket_bounds(station: str, mu: float, scheme: str = "statutory_7bin") -> List[Tuple[float, float]]:
    """Generate bracket boundaries for statutory 7-bin or 2°F climate grid."""
    if scheme == "climate_2deg":
        ranges = {
            "KORD": (-20.0, 110.0),
            "KMIA": (30.0, 105.0),
            "KSFO": (30.0, 110.0),
        }
        low, high = ranges.get(station, (-20.0, 110.0))
        edges = list(np.arange(low, high + 2.0, 2.0))
        bounds = [(-np.inf, edges[0])]
        for i in range(len(edges) - 1):
            bounds.append((edges[i], edges[i + 1]))
        bounds.append((edges[-1], np.inf))
        return bounds

    # Default statutory 7-bin centered on round(mu)
    c0 = int(round(mu))
    return [
        (-np.inf, c0 - 5.5),
        (c0 - 5.5, c0 - 3.5),
        (c0 - 3.5, c0 - 1.5),
        (c0 - 1.5, c0 + 1.5),
        (c0 + 1.5, c0 + 3.5),
        (c0 + 3.5, c0 + 5.5),
        (c0 + 5.5, np.inf),
    ]


def _expand_day_records(
    row: pd.Series,
    kappa_evt_map: Dict[str, float],
    r6_params: Dict[str, Any],
    r7_params: Dict[str, Any],
    binning_scheme: str = "statutory_7bin",
) -> List[Dict[str, Any]]:
    """Expand a single station-day into (p_pred, hit) bracket records."""
    st = row["station"]
    obs_y = float(row["obs_tmax_f"])
    mu = float(row["mu_forecast"])
    sig_eff = float(row["sigma_forecast"]) * kappa_evt_map.get(st, 1.0)

    bounds = _compute_bracket_bounds(st, mu, scheme=binning_scheme)
    num_bins = len(bounds)

    cdfs = [evaluate_station_cdf(st, b[1], mu, sig_eff, r6_params, r7_params) for b in bounds]
    p_bins = np.zeros(num_bins, dtype=np.float64)
    p_bins[0] = cdfs[0]
    for k in range(1, num_bins - 1):
        p_bins[k] = cdfs[k] - cdfs[k - 1]
    p_bins[num_bins - 1] = 1.0 - cdfs[num_bins - 2]

    p_bins = np.clip(p_bins, 0.0, 1.0)
    total_p = np.sum(p_bins)
    p_bins = p_bins / total_p if total_p > 0 else np.full(num_bins, 1.0 / num_bins)

    records = []
    for k in range(num_bins):
        lb, ub = bounds[k]
        hit = 1 if (obs_y >= lb and obs_y < ub) else 0
        records.append({
            "date": str(row["date"]),
            "station": st,
            "year": int(row["year"]),
            "month": int(row["month"]),
            "season": str(row["season"]),
            "bin_idx": k,
            "bin_lower": lb,
            "bin_upper": ub,
            "p_pred": float(p_bins[k]),
            "hit": hit,
        })
    return records


def expand_prediction_records(
    df: pd.DataFrame,
    r6_params: Dict[str, Any],
    r7_params: Dict[str, Any],
    binning_scheme: str = "statutory_7bin",
) -> pd.DataFrame:
    """Expand training window station-day records into (p_pred, hit) pairs."""
    valid = df[~df["is_nan_obs"]].copy()

    kappa_evt_map = {}
    for st in ["KORD", "KMIA", "KSFO"]:
        if st in r7_params["stations"]:
            kappa_evt_map[st] = float(np.sqrt(compute_evt_variance(r7_params["stations"][st])))
        else:
            kappa_evt_map[st] = 1.0

    all_records = []
    for _, row in valid.iterrows():
        all_records.extend(_expand_day_records(row, kappa_evt_map, r6_params, r7_params, binning_scheme))
    return pd.DataFrame(all_records)


# ==============================================================================
# Ticket 02: Global 20-Strata Pooling & Stratified 12-Cell Matrix
# ==============================================================================

def build_global_reliability_table(
    df_expanded: pd.DataFrame,
    num_bins: int = 20,
) -> Tuple[pd.DataFrame, float]:
    """Build global reliability table pooling all (p_pred, hit) records into equal-width strata."""
    p_arr = df_expanded["p_pred"].to_numpy(dtype=np.float64)
    h_arr = df_expanded["hit"].to_numpy(dtype=np.float64)
    n_total = len(p_arr)

    edges = np.linspace(0.0, 1.0, num_bins + 1)
    bin_idx = np.clip(np.digitize(p_arr, edges) - 1, 0, num_bins - 1)

    rows = []
    weighted_err_sum = 0.0

    for b in range(num_bins):
        low_e, high_e = edges[b], edges[b + 1]
        range_str = f"[{low_e:.2f}, {high_e:.2f}{']' if b == num_bins - 1 else ')'}"

        mask = bin_idx == b
        stratum_count = int(np.sum(mask))

        if stratum_count > 0:
            mean_pred_prob = float(np.mean(p_arr[mask]))
            empirical_hit_freq = float(np.mean(h_arr[mask]))
            abs_bias = float(abs(mean_pred_prob - empirical_hit_freq))
            ci_half = compute_binomial_ci_half_width(empirical_hit_freq, stratum_count, z=1.96)
            is_outside = bool(abs_bias > ci_half)
            weighted_err_sum += abs_bias * stratum_count
        else:
            mean_pred_prob = float(np.nan)
            empirical_hit_freq = float(np.nan)
            abs_bias = float(np.nan)
            ci_half = float(np.nan)
            is_outside = False

        rows.append({
            "stratum_id": b + 1,
            "stratum_range": range_str,
            "sample_count_n": stratum_count,
            "mean_pred_prob": mean_pred_prob,
            "empirical_hit_freq": empirical_hit_freq,
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
    """Build 12-cell stratified warning table (3 stations x 4 seasons)."""
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

    return pd.concat(all_stratified_rows, ignore_index=True) if all_stratified_rows else pd.DataFrame()


# ==============================================================================
# Ticket 03: Climatology Baseline & Brier Skill Score Calculation
# ==============================================================================

def _build_loyo_climatology_cache(valid_raw: pd.DataFrame) -> Tuple[Dict[Tuple[str, int, int], np.ndarray], Dict[Tuple[str, int], np.ndarray]]:
    """Precompute Leave-One-Year-Out sorted observations cache."""
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

    loyo_pool_cache: Dict[Tuple[str, int, int], np.ndarray] = {}
    for (st, mo), yr_dict in clim_lookup.items():
        all_yrs = list(yr_dict.keys())
        for yr in all_yrs:
            other_arrs = [yr_dict[y] for y in all_yrs if y != yr]
            loyo_pool_cache[(st, mo, yr)] = np.sort(np.concatenate(other_arrs)) if other_arrs else yr_dict[yr]

    return loyo_pool_cache, all_by_st_mo


def _compute_record_climatological_prob(
    st: str,
    mo: int,
    yr: int,
    lb: float,
    ub: float,
    loyo_pool_cache: Dict[Tuple[str, int, int], np.ndarray],
    all_by_st_mo: Dict[Tuple[str, int], np.ndarray],
) -> float:
    """Compute leave-one-year-out climatological probability for a single bracket."""
    pool = loyo_pool_cache.get((st, mo, yr))
    if pool is None or len(pool) == 0:
        pool = all_by_st_mo.get((st, mo), np.array([]))
    if len(pool) > 0:
        i_low = np.searchsorted(pool, lb, side="left")
        i_high = np.searchsorted(pool, ub, side="left")
        return float((i_high - i_low) / len(pool))
    return 1.0 / 7.0


def compute_brier_skill_scores(
    df_expanded: pd.DataFrame,
    df_train_raw: pd.DataFrame,
) -> pd.DataFrame:
    """Compute Brier Scores for Model and LOYO Climatology, and Brier Skill Score (BSS)."""
    valid_raw = df_train_raw[~df_train_raw["is_nan_obs"]].copy()
    loyo_pool_cache, all_by_st_mo = _build_loyo_climatology_cache(valid_raw)

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
        p_clims[i] = _compute_record_climatological_prob(
            stations[i], months[i], years[i], lbs[i], ubs[i], loyo_pool_cache, all_by_st_mo
        )

    sq_err_model = (p_preds - hits) ** 2
    sq_err_clim = (p_clims - hits) ** 2

    scopes = [("Global", "Global", np.ones(n_records, dtype=bool))]
    for st in ["KORD", "KMIA", "KSFO"]:
        scopes.append(("Station", st, stations == st))
    for se in ["Winter", "Spring", "Summer", "Autumn"]:
        scopes.append(("Season (Auxiliary)", se, seasons == se))

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
    binning_scheme: str = "statutory_7bin",
) -> Dict[str, Any]:
    """Execute the complete reliability check pipeline."""
    df_expanded = expand_prediction_records(df_train, r6_params, r7_params, binning_scheme=binning_scheme)
    table_global, weighted_ece = build_global_reliability_table(df_expanded, num_bins=20)
    table_stratified = build_stratified_warning_table(df_expanded, num_bins=10)
    table_brier = compute_brier_skill_scores(df_expanded, df_train)

    _save_dataframe(table_global, out_global_path)
    _save_dataframe(table_stratified, out_stratified_path)
    _save_dataframe(table_brier, out_brier_path)

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
    parser.add_argument("--train-parquet", type=Path, default=DEFAULT_TRAIN_PARQUET, help="Path to 2000-2018 parquet.")
    parser.add_argument("--r6-json", type=Path, default=DEFAULT_R6_JSON, help="Path to R-6 KMIA parameters.")
    parser.add_argument("--r7-json", type=Path, default=DEFAULT_R7_JSON, help="Path to R-7 tail parameters.")
    parser.add_argument("--binning-scheme", type=str, default="statutory_7bin", choices=["statutory_7bin", "climate_2deg"], help="Binning scheme.")
    parser.add_argument("--out-global", type=Path, default=DEFAULT_OUT_GLOBAL, help="Output path for global CSV.")
    parser.add_argument("--out-stratified", type=Path, default=DEFAULT_OUT_STRATIFIED, help="Output path for stratified CSV.")
    parser.add_argument("--out-brier", type=Path, default=DEFAULT_OUT_BRIER, help="Output path for Brier CSV.")

    args = parser.parse_args()

    print("================================================================================")
    print("      SPEC-RELIABILITY-001: RELIABILITY CHECK BY PROBABILITY STRATA            ")
    print("================================================================================")
    if not args.train_parquet.exists():
        raise FileNotFoundError(f"{args.train_parquet} not found.")

    df_train = pd.read_parquet(args.train_parquet)
    with open(args.r6_json, "r", encoding="utf-8") as f:
        r6_params = json.load(f)
    with open(args.r7_json, "r", encoding="utf-8") as f:
        r7_params = json.load(f)

    res = run_reliability_pipeline(
        df_train=df_train,
        r6_params=r6_params,
        r7_params=r7_params,
        out_global_path=args.out_global,
        out_stratified_path=args.out_stratified,
        out_brier_path=args.out_brier,
        binning_scheme=args.binning_scheme,
    )

    print(f"\n[Artifact 1] Global Reliability Table (20 Strata): {args.out_global}")
    print(f"Global Weighted ECE: {res['weighted_ece']:.4%}")
    print(res["table_global"].to_string(index=False))

    print(f"\n[Artifact 2] Stratified Warning Table (12 Cells): {args.out_stratified}")
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
