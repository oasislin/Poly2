#!/usr/bin/env python3
"""
scripts/standalone_reliability_check.py: Standalone Reliability Check by Probability Strata.
Specification: SPEC-RELIABILITY-001 (ADR-0017 Gate 2 Diagnostic View).

Industrial overhaul according to P5 14-question audit findings and transformation order:
- R1: Sigma Collapse Hard Sentinel (PhysicsViolationError, floor=0.90°F)
- R2: Configuration-driven Distribution Mapping (decoupled from hardcoded branch)
- R3: Settlement Jitter Single Source of Truth (compute_settlement_hit_probability)
- R4: Block Cross-Validation (CV) Engine (30-day blocks, 20 rounds, seed=20260923)
- R5: Three-Mode State Machine (insample, cv, blind)
- R6: Dimension Parameterization & Universe Admission Gatekeeper
- R7: Output Enhancements (WARNING_LOW_N, NO_DATA, Out-of-CI Rate, Metadata Headers, Delete KSFO Summer Highlight)
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Dict, Any, Tuple, List, Optional

import numpy as np
import pandas as pd
from scipy import stats, integrate

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.verification.settlement import compute_settlement_hit_probability
from src.verification.resampling import get_or_create_cv_manifest

DEFAULT_TRAIN_PARQUET = PROJECT_ROOT / "data" / "processed" / "audit_arrays" / "2000_2018_training_arrays.parquet"
DEFAULT_R6_JSON = PROJECT_ROOT / "evidence" / "r6_kmia_parameters.json"
DEFAULT_R7_JSON = PROJECT_ROOT / "evidence" / "r7_tail_parameters.json"
DEFAULT_CV_MANIFEST = PROJECT_ROOT / "evidence" / "cv_split_blocks_20rounds.json"
DEFAULT_OUT_GLOBAL = PROJECT_ROOT / "evidence" / "reliability_check_main_global.csv"
DEFAULT_OUT_STRATIFIED = PROJECT_ROOT / "evidence" / "reliability_check_stratified_station_season.csv"
DEFAULT_OUT_BRIER = PROJECT_ROOT / "evidence" / "reliability_check_brier_skill.csv"
AUTH_FLAG_PATH = PROJECT_ROOT / "evidence" / "preregistered_2019_authorization.flag"

# R1: Physical Noise Floor
SIGMA_PHYS_FLOOR = 0.90  # ASOS PRT-1088 sensor noise floor (°F)

# R2: Default Configuration Mapping
DEFAULT_MAPPING_CONFIG: Dict[str, str] = {
    "KMIA": "johnsonsu",
    "KSFO": "evt",
    "KORD": "gaussian",
}


class PhysicsViolationError(ValueError):
    """Raised when forecast sigma collapses below physical sensor noise floor."""
    pass


def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    if not path.exists():
        return "MISSING"
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest()


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


def compute_wilson_ci(hits: float, n_count: int, confidence: float = 0.95) -> Tuple[float, float, float]:
    """
    Compute Wilson score confidence interval [ci_lower, ci_upper] and half-width.
    Safe across all boundary conditions (n=0, f=0, f=1).
    """
    if n_count <= 0:
        return float(np.nan), float(np.nan), float(np.nan)

    z = float(stats.norm.ppf(1.0 - (1.0 - confidence) / 2.0))
    p_hat = float(hits / n_count)
    z2 = z * z
    denom = 1.0 + z2 / n_count
    center = (p_hat + z2 / (2.0 * n_count)) / denom
    margin = (z / denom) * math.sqrt((p_hat * (1.0 - p_hat) / n_count) + (z2 / (4.0 * n_count * n_count)))

    ci_lower = max(0.0, center - margin)
    ci_upper = min(1.0, center + margin)
    ci_half_width = (ci_upper - ci_lower) / 2.0
    return float(ci_lower), float(ci_upper), float(ci_half_width)


def compute_binomial_ci_half_width(empirical_freq: float, n_count: int, z: float = 1.96) -> float:
    """
    Compute binomial 95% confidence half-width.
    Uses standard Wald interval when 0 < f < 1, and Wilson boundary formula when f in {0, 1}.
    """
    if n_count <= 0:
        return float(np.nan)
    variance_term = empirical_freq * (1.0 - empirical_freq)
    if variance_term > 0:
        return float(z * math.sqrt(variance_term / n_count))
    return float((z**2) / (n_count + z**2))


def save_dataframe_with_metadata(
    df: pd.DataFrame,
    out_path: Optional[Path],
    metadata: Dict[str, Any],
) -> None:
    """Persist DataFrame to disk prefixed with standardized metadata comment headers."""
    if out_path is None:
        return
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for k, v in metadata.items():
            f.write(f"# {k}: {v}\n")
        df.to_csv(f, index=False)


# ==============================================================================
# R1 & R2: EVT Variance, Station CDFs & Record Expansion
# ==============================================================================

def compute_evt_variance(station_params: Dict[str, Any]) -> float:
    """Compute theoretical variance factor of hybrid core + EVT GPD tail model."""
    if not station_params or "u_left" not in station_params:
        return 1.0
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
    mapping_config: Optional[Dict[str, str]] = None,
) -> float:
    """
    Evaluate cumulative distribution function F(y) for a given station.
    
    R1: Strict physics floor on sigma_eff. Collapsed variance raises PhysicsViolationError.
    R2: Configuration-driven mapping.
    """
    if math.isinf(y):
        return 1.0 if y > 0 else 0.0

    # R1: Physical Floor Tripwire
    if sigma_eff < SIGMA_PHYS_FLOOR:
        raise PhysicsViolationError(
            f"sigma_eff={sigma_eff:.3e} < floor {SIGMA_PHYS_FLOOR}°F — "
            "collapsed variance, refusing to emit degenerate probabilities"
        )

    z = (y - mu) / sigma_eff
    cfg = mapping_config or DEFAULT_MAPPING_CONFIG
    dist_family = cfg.get(station, "gaussian")

    if dist_family == "johnsonsu":
        p = r6_params["johnsonsu_parameters"]
        z_norm = p["gamma"] + p["delta"] * np.arcsinh((z - p["xi"]) / p["lambda"])
        return float(stats.norm.cdf(z_norm))
    elif dist_family == "evt":
        st_evt = r7_params.get("stations", {}).get(station)
        if st_evt is not None:
            return _evaluate_evt_tail_cdf(z, st_evt)
        return float(stats.norm.cdf(z))
    elif dist_family == "gaussian":
        return float(stats.norm.cdf(z))
    else:
        raise ValueError(f"Unknown distribution family '{dist_family}' for station {station}")


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
    mapping_config: Optional[Dict[str, str]] = None,
    binning_scheme: str = "statutory_7bin",
    target_obs_col: str = "obs_tmax_f",
) -> List[Dict[str, Any]]:
    """Expand a single station-day into (p_pred, hit) bracket records using single-source hit arbitration."""
    st = row["station"]
    obs_y = float(row[target_obs_col])
    mu = float(row["mu_forecast"])
    sig_eff = float(row["sigma_forecast"]) * kappa_evt_map.get(st, 1.0)

    bounds = _compute_bracket_bounds(st, mu, scheme=binning_scheme)
    num_bins = len(bounds)

    cdfs = [evaluate_station_cdf(st, b[1], mu, sig_eff, r6_params, r7_params, mapping_config) for b in bounds]
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
        # R3: Single source of truth for discretization jitter
        hit_prob = compute_settlement_hit_probability(obs_y, lb, ub, jitter_half_width=0.05)
        records.append({
            "date": str(row["date"]),
            "station": st,
            "year": int(row["year"]),
            "month": int(row["month"]),
            "season": str(row.get("season", "Unknown")),
            "bin_idx": k,
            "bin_lower": lb,
            "bin_upper": ub,
            "p_pred": float(p_bins[k]),
            "hit": float(hit_prob),
        })
    return records


def expand_prediction_records(
    df: pd.DataFrame,
    r6_params: Dict[str, Any],
    r7_params: Dict[str, Any],
    mapping_config: Optional[Dict[str, str]] = None,
    binning_scheme: str = "statutory_7bin",
    target_obs_col: str = "obs_tmax_f",
) -> pd.DataFrame:
    """Expand station-day records into (p_pred, hit) pairs."""
    valid = df[~df["is_nan_obs"]].copy()

    cfg = mapping_config or DEFAULT_MAPPING_CONFIG
    kappa_evt_map = {}
    for st, fam in cfg.items():
        if fam == "evt" and "stations" in r7_params and st in r7_params["stations"]:
            kappa_evt_map[st] = float(np.sqrt(compute_evt_variance(r7_params["stations"][st])))
        else:
            kappa_evt_map[st] = 1.0

    all_records = []
    for _, row in valid.iterrows():
        all_records.extend(
            _expand_day_records(row, kappa_evt_map, r6_params, r7_params, cfg, binning_scheme, target_obs_col)
        )
    return pd.DataFrame(all_records)


# ==============================================================================
# R7: Global Reliability Table & Stratified Warning Matrix
# ==============================================================================

def compute_table_meta_metrics(table_df: pd.DataFrame) -> Dict[str, Any]:
    """Compute out-of-CI rate vs theoretical 5% expectation."""
    valid = table_df[table_df["sample_count_n"] > 0]
    total_valid = len(valid)
    if total_valid == 0:
        return {"total_valid_strata": 0, "out_of_ci_count": 0, "out_of_ci_rate": 0.0, "expected_rate": 0.05}
    out_cnt = int(valid["is_outside_ci"].sum())
    rate = float(out_cnt / total_valid)
    return {
        "total_valid_strata": total_valid,
        "out_of_ci_count": out_cnt,
        "out_of_ci_rate": rate,
        "expected_rate": 0.05,
    }


def build_global_reliability_table(
    df_expanded: pd.DataFrame,
    num_bins: int = 20,
) -> Tuple[pd.DataFrame, float]:
    """
    Build global reliability table pooling all (p_pred, hit) records into equal-width strata.
    Enforces R7: WARNING_LOW_N, NO_DATA, Wilson Score intervals, and Out-of-CI flags.
    """
    if df_expanded.empty:
        edges = np.linspace(0.0, 1.0, num_bins + 1)
        rows = []
        for b in range(num_bins):
            low_e, high_e = edges[b], edges[b + 1]
            rows.append({
                "stratum_id": b + 1,
                "stratum_range": f"[{low_e:.2f}, {high_e:.2f}{']' if b == num_bins - 1 else ')'}",
                "sample_count_n": 0,
                "mean_pred_prob": np.nan,
                "empirical_hit_freq": np.nan,
                "abs_bias": np.nan,
                "ci_lower": np.nan,
                "ci_upper": np.nan,
                "ci_95_half_width": np.nan,
                "is_outside_ci": False,
                "warning_low_n": False,
                "label": "NO_DATA",
            })
        return pd.DataFrame(rows), 0.0

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
            ci_low, ci_high, ci_half = compute_wilson_ci(float(np.sum(h_arr[mask])), stratum_count, confidence=0.95)
            is_outside = bool(mean_pred_prob < ci_low or mean_pred_prob > ci_high)
            weighted_err_sum += abs_bias * stratum_count
            is_low_n = bool(0 < stratum_count < 30)
            label_str = "WARNING_LOW_N" if is_low_n else "NORMAL"
        else:
            mean_pred_prob = float(np.nan)
            empirical_hit_freq = float(np.nan)
            abs_bias = float(np.nan)
            ci_low = float(np.nan)
            ci_high = float(np.nan)
            ci_half = float(np.nan)
            is_outside = False
            is_low_n = False
            label_str = "NO_DATA"

        rows.append({
            "stratum_id": b + 1,
            "stratum_range": range_str,
            "sample_count_n": stratum_count,
            "mean_pred_prob": mean_pred_prob,
            "empirical_hit_freq": empirical_hit_freq,
            "abs_bias": abs_bias,
            "ci_lower": ci_low,
            "ci_upper": ci_high,
            "ci_95_half_width": ci_half,
            "is_outside_ci": is_outside,
            "warning_low_n": is_low_n,
            "label": label_str,
        })

    weighted_ece = float(weighted_err_sum / n_total) if n_total > 0 else 0.0
    return pd.DataFrame(rows), weighted_ece


def build_stratified_warning_table(
    df_expanded: pd.DataFrame,
    num_bins: int = 10,
    stations: Optional[List[str]] = None,
    seasons: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Build stratified warning table across station x season cells."""
    target_stations = stations or ["KORD", "KMIA", "KSFO"]
    target_seasons = seasons or ["Winter", "Spring", "Summer", "Autumn"]

    all_stratified_rows = []
    for st in target_stations:
        for se in target_seasons:
            sub = df_expanded[(df_expanded["station"] == st) & (df_expanded["season"] == se)]
            table_df, _ = build_global_reliability_table(sub, num_bins=num_bins)
            table_df.insert(0, "station", st)
            table_df.insert(1, "season", se)
            all_stratified_rows.append(table_df)

    return pd.concat(all_stratified_rows, ignore_index=True) if all_stratified_rows else pd.DataFrame()


# ==============================================================================
# Climatology Baseline & Brier Skill Score Calculation
# ==============================================================================

def _build_loyo_climatology_cache(
    valid_raw: pd.DataFrame,
    target_obs_col: str = "obs_tmax_f",
) -> Tuple[Dict[Tuple[str, int, int], np.ndarray], Dict[Tuple[str, int], np.ndarray]]:
    """Precompute Leave-One-Year-Out sorted observations cache."""
    clim_lookup: Dict[Tuple[str, int], Dict[int, np.ndarray]] = {}
    all_by_st_mo: Dict[Tuple[str, int], np.ndarray] = {}

    for (st, mo), grp in valid_raw.groupby(["station", "month"]):
        clim_lookup[(st, mo)] = {}
        all_obs = []
        for yr, y_grp in grp.groupby("year"):
            arr = np.sort(y_grp[target_obs_col].to_numpy(dtype=np.float64))
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
    target_obs_col: str = "obs_tmax_f",
    stations_list: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Compute Brier Scores for Model and LOYO Climatology, and Brier Skill Score (BSS)."""
    valid_raw = df_train_raw[~df_train_raw["is_nan_obs"]].copy()
    loyo_pool_cache, all_by_st_mo = _build_loyo_climatology_cache(valid_raw, target_obs_col)

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
    active_stations = stations_list or ["KORD", "KMIA", "KSFO"]
    for st in active_stations:
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
# R4: Parameter Refitting & Cross-Validation Engine
# ==============================================================================

def refit_parameters_on_subset(
    df_train_sub: pd.DataFrame,
    mapping_config: Dict[str, str],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Refit R-6 (Johnson SU) and R-7 (EVT) parameters strictly on training complement.
    Ensures zero data leakage during cross-validation rounds.
    """
    r6_out: Dict[str, Any] = {"johnsonsu_parameters": {}}
    for st, family in mapping_config.items():
        if family == "johnsonsu":
            sub_st = df_train_sub[(df_train_sub["station"] == st) & (~df_train_sub["is_nan_obs"])]
            if len(sub_st) > 50:
                z_raw = (sub_st["resid_calibrated"] / sub_st["sigma_forecast"]).to_numpy()
                gamma, delta, xi, lam = stats.johnsonsu.fit(z_raw)
                r6_out["johnsonsu_parameters"] = {
                    "gamma": float(gamma),
                    "delta": float(delta),
                    "xi": float(xi),
                    "lambda": float(lam),
                }
            else:
                r6_out["johnsonsu_parameters"] = {
                    "gamma": 0.0, "delta": 1.0, "xi": 0.0, "lambda": 1.0
                }

    r7_out: Dict[str, Any] = {"stations": {}}
    for st, family in mapping_config.items():
        if family == "evt":
            sub_st = df_train_sub[(df_train_sub["station"] == st) & (~df_train_sub["is_nan_obs"])]
            if len(sub_st) > 50:
                z_raw = (sub_st["resid_calibrated"] / sub_st["sigma_forecast"]).to_numpy()
                u_l = float(np.percentile(z_raw, 5))
                u_r = float(np.percentile(z_raw, 95))
                z_left_excess = u_l - z_raw[z_raw < u_l]
                z_right_excess = z_raw[z_raw > u_r] - u_r
                fit_l = stats.genpareto.fit(z_left_excess, floc=0)
                fit_r = stats.genpareto.fit(z_right_excess, floc=0)
                r7_out["stations"][st] = {
                    "u_left": u_l,
                    "u_right": u_r,
                    "gpd_left": {"shape_xi": float(fit_l[0]), "scale_beta": float(fit_l[2])},
                    "gpd_right": {"shape_xi": float(fit_r[0]), "scale_beta": float(fit_r[2])},
                }
            else:
                r7_out["stations"][st] = {
                    "u_left": -1.645, "u_right": 1.645,
                    "gpd_left": {"shape_xi": 0.0, "scale_beta": 0.5},
                    "gpd_right": {"shape_xi": 0.0, "scale_beta": 0.5},
                }
        else:
            r7_out["stations"][st] = {}

    return r6_out, r7_out


def run_cv_reliability_pipeline(
    df_train: pd.DataFrame,
    mapping_config: Optional[Dict[str, str]] = None,
    n_rounds: int = 20,
    holdout_frac: float = 0.10,
    seed: int = 20260923,
    manifest_path: Optional[Path] = None,
    binning_scheme: str = "statutory_7bin",
    target_obs_col: str = "obs_tmax_f",
    stations_list: Optional[List[str]] = None,
    num_bins: int = 20,
) -> Dict[str, Any]:
    """
    Execute 20-round block Cross-Validation (R4).
    Each round refits parameters on 90% complement and predicts on 10% held-out blocks.
    Strictly asserts zero date leakage.
    """
    cfg = mapping_config or DEFAULT_MAPPING_CONFIG
    m_path = manifest_path or DEFAULT_CV_MANIFEST
    valid_dates = sorted(list(df_train["date"].astype(str).unique()))

    manifest = get_or_create_cv_manifest(
        manifest_path=m_path,
        dates=valid_dates,
        n_rounds=n_rounds,
        holdout_frac=holdout_frac,
        seed=seed,
    )

    all_round_eval_records = []
    round_table_list = []

    for round_meta in manifest:
        r_idx = round_meta["round_idx"]
        test_dates = set(round_meta["test_dates"])
        train_dates = set(round_meta["train_dates"])

        # Hard assertion of zero leakage
        overlap = test_dates.intersection(train_dates)
        assert len(overlap) == 0, f"Leakage detected in round {r_idx}: {overlap}"

        df_round_train = df_train[df_train["date"].astype(str).isin(train_dates)].copy()
        df_round_test = df_train[df_train["date"].astype(str).isin(test_dates)].copy()

        # Refit on training complement
        r6_refit, r7_refit = refit_parameters_on_subset(df_round_train, cfg)

        # Expand test block predictions
        df_round_expanded = expand_prediction_records(
            df_round_test,
            r6_params=r6_refit,
            r7_params=r7_refit,
            mapping_config=cfg,
            binning_scheme=binning_scheme,
            target_obs_col=target_obs_col,
        )
        df_round_expanded["cv_round"] = r_idx
        all_round_eval_records.append(df_round_expanded)

        tbl_r, _ = build_global_reliability_table(df_round_expanded, num_bins=num_bins)
        tbl_r["round_idx"] = r_idx
        round_table_list.append(tbl_r)

    pooled_eval_df = pd.concat(all_round_eval_records, ignore_index=True)
    table_global, weighted_ece = build_global_reliability_table(pooled_eval_df, num_bins=num_bins)

    # Compute inter-round dispersion across 20 rounds
    all_rounds_df = pd.concat(round_table_list, ignore_index=True)
    dispersion_min = []
    dispersion_median = []
    dispersion_max = []

    for s_id in table_global["stratum_id"]:
        sub_s = all_rounds_df[(all_rounds_df["stratum_id"] == s_id) & (all_rounds_df["sample_count_n"] > 0)]
        if not sub_s.empty:
            f_vals = sub_s["empirical_hit_freq"].to_numpy()
            dispersion_min.append(float(np.min(f_vals)))
            dispersion_median.append(float(np.median(f_vals)))
            dispersion_max.append(float(np.max(f_vals)))
        else:
            dispersion_min.append(np.nan)
            dispersion_median.append(np.nan)
            dispersion_max.append(np.nan)

    table_global["dispersion_min"] = dispersion_min
    table_global["dispersion_median"] = dispersion_median
    table_global["dispersion_max"] = dispersion_max

    table_stratified = build_stratified_warning_table(
        pooled_eval_df,
        num_bins=10,
        stations=stations_list,
    )
    table_brier = compute_brier_skill_scores(
        pooled_eval_df,
        df_train,
        target_obs_col=target_obs_col,
        stations_list=stations_list,
    )

    return {
        "df_expanded": pooled_eval_df,
        "table_global": table_global,
        "weighted_ece": weighted_ece,
        "table_stratified": table_stratified,
        "table_brier": table_brier,
        "manifest": manifest,
    }


# ==============================================================================
# Pipeline Runner & CLI
# ==============================================================================

def run_reliability_pipeline(
    df_train: pd.DataFrame,
    r6_params: Dict[str, Any],
    r7_params: Dict[str, Any],
    mapping_config: Optional[Dict[str, str]] = None,
    out_global_path: Optional[Path] = None,
    out_stratified_path: Optional[Path] = None,
    out_brier_path: Optional[Path] = None,
    binning_scheme: str = "statutory_7bin",
    mode: str = "insample",
    model_status: str = "RETRAINED-v2",
    target_obs_col: str = "obs_tmax_f",
    stations_list: Optional[List[str]] = None,
    metadata_headers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute the complete reliability check pipeline."""
    cfg = mapping_config or DEFAULT_MAPPING_CONFIG
    df_expanded = expand_prediction_records(
        df_train,
        r6_params,
        r7_params,
        mapping_config=cfg,
        binning_scheme=binning_scheme,
        target_obs_col=target_obs_col,
    )
    table_global, weighted_ece = build_global_reliability_table(df_expanded, num_bins=20)
    table_stratified = build_stratified_warning_table(df_expanded, num_bins=10, stations=stations_list)
    table_brier = compute_brier_skill_scores(df_expanded, df_train, target_obs_col=target_obs_col, stations_list=stations_list)

    meta = metadata_headers or {}
    save_dataframe_with_metadata(table_global, out_global_path, meta)
    save_dataframe_with_metadata(table_stratified, out_stratified_path, meta)
    save_dataframe_with_metadata(table_brier, out_brier_path, meta)

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
    parser.add_argument("--mode", type=str, default="cv", choices=["insample", "cv", "blind"],
                        help="Execution mode: insample (self-test only), cv (cross-validation), blind (2019 airgapped)")
    parser.add_argument("--train-parquet", type=Path, default=DEFAULT_TRAIN_PARQUET, help="Path to 2000-2018 parquet.")
    parser.add_argument("--r6-json", type=Path, default=DEFAULT_R6_JSON, help="Path to R-6 KMIA parameters.")
    parser.add_argument("--r7-json", type=Path, default=DEFAULT_R7_JSON, help="Path to R-7 tail parameters.")
    parser.add_argument("--mapping-config", type=Path, default=None, help="Optional JSON path for distribution mapping.")
    parser.add_argument("--binning-scheme", type=str, default="statutory_7bin", choices=["statutory_7bin", "climate_2deg"])
    parser.add_argument("--stations", type=str, default="KORD,KMIA,KSFO", help="Comma-separated station list.")
    parser.add_argument("--target-type", type=str, default="Max", choices=["Max", "Min"], help="Target temperature type.")
    parser.add_argument("--lead-hour", type=int, default=18, help="Lead hour (e.g. 18).")
    parser.add_argument("--model-status", type=str, default="AUTO", help="Model status tag (RETRAINED-v2 / LEGACY-DISEASED).")
    parser.add_argument("--out-global", type=Path, default=DEFAULT_OUT_GLOBAL, help="Output path for global CSV.")
    parser.add_argument("--out-stratified", type=Path, default=DEFAULT_OUT_STRATIFIED, help="Output path for stratified CSV.")
    parser.add_argument("--out-brier", type=Path, default=DEFAULT_OUT_BRIER, help="Output path for Brier CSV.")

    args = parser.parse_args()

    print("================================================================================")
    print("      SPEC-RELIABILITY-001: RELIABILITY CHECK BY PROBABILITY STRATA            ")
    print("================================================================================")

    # R5: Blind Mode Airgap Sentinel
    if args.mode == "blind":
        if not AUTH_FLAG_PATH.exists() or AUTH_FLAG_PATH.stat().st_size == 0:
            raise PermissionError(
                f"Strict 2019 airgap active: authorization flag '{AUTH_FLAG_PATH}' is missing or empty. "
                "Blind evaluation on 2019 data is strictly blocked."
            )

    # R5: Mode Banner
    mode_banners = {
        "insample": "IN-SAMPLE SELF-GRADE — 无校准证据效力",
        "cv": "INTERNAL CV DIAGNOSTIC — 受迭代选择影响，仅供方向参考",
        "blind": "BLIND 2019 OUT-OF-SAMPLE VERIFICATION — 法定独立复算",
    }
    banner = mode_banners[args.mode]
    print(f"MODE: [{args.mode.upper()}] - {banner}")

    # R6: Dimension & Universe Admission Gatekeeper
    stations_list = [s.strip() for s in args.stations.split(",") if s.strip()]
    target_obs_col = "obs_tmax_f" if args.target_type == "Max" else "obs_tmin_f"

    model_status = args.model_status
    if model_status == "AUTO":
        if set(stations_list) <= {"KORD", "KMIA", "KSFO"} and args.target_type == "Max" and args.lead_hour == 18:
            model_status = "RETRAINED-v2"
        else:
            model_status = "LEGACY-DISEASED"

    if model_status == "LEGACY-DISEASED":
        print("WARNING: Active dimension not fully certified. Output tagged with [LEGACY-DISEASED].")

    # Load Distribution Mapping
    if args.mapping_config and args.mapping_config.exists():
        with open(args.mapping_config, "r", encoding="utf-8") as f:
            mapping_cfg = json.load(f)
    else:
        mapping_cfg = DEFAULT_MAPPING_CONFIG

    if not args.train_parquet.exists():
        raise FileNotFoundError(f"{args.train_parquet} not found.")

    df_train = pd.read_parquet(args.train_parquet)
    # Filter to requested stations
    df_train = df_train[df_train["station"].isin(stations_list)].copy()

    # Tool source hash
    tool_hash = compute_file_sha256(Path(__file__).resolve())
    r6_hash = compute_file_sha256(args.r6_json)
    r7_hash = compute_file_sha256(args.r7_json)

    metadata_block = {
        "mode": banner,
        "model_status": model_status,
        "stations": ",".join(stations_list),
        "target_type": args.target_type,
        "lead_hour": args.lead_hour,
        "r6_hash": r6_hash,
        "r7_hash": r7_hash,
        "split_seed": 20260923,
        "tool_source_hash": tool_hash,
    }

    if args.mode == "cv":
        res = run_cv_reliability_pipeline(
            df_train=df_train,
            mapping_config=mapping_cfg,
            n_rounds=20,
            holdout_frac=0.10,
            seed=20260923,
            binning_scheme=args.binning_scheme,
            target_obs_col=target_obs_col,
            stations_list=stations_list,
            num_bins=20,
        )
        save_dataframe_with_metadata(res["table_global"], args.out_global, metadata_block)
        save_dataframe_with_metadata(res["table_stratified"], args.out_stratified, metadata_block)
        save_dataframe_with_metadata(res["table_brier"], args.out_brier, metadata_block)
    else:
        with open(args.r6_json, "r", encoding="utf-8") as f:
            r6_params = json.load(f)
        with open(args.r7_json, "r", encoding="utf-8") as f:
            r7_params = json.load(f)

        res = run_reliability_pipeline(
            df_train=df_train,
            r6_params=r6_params,
            r7_params=r7_params,
            mapping_config=mapping_cfg,
            out_global_path=args.out_global,
            out_stratified_path=args.out_stratified,
            out_brier_path=args.out_brier,
            binning_scheme=args.binning_scheme,
            mode=args.mode,
            model_status=model_status,
            target_obs_col=target_obs_col,
            stations_list=stations_list,
            metadata_headers=metadata_block,
        )

    print(f"\n[Artifact 1] Global Reliability Table: {args.out_global}")
    print(f"Global Weighted ECE: {res['weighted_ece']:.4%}")
    meta_m = compute_table_meta_metrics(res["table_global"])
    print(f"Out-of-CI Rate vs Expected: {meta_m['out_of_ci_count']}/{meta_m['total_valid_strata']} ({meta_m['out_of_ci_rate']:.1%}) vs nominal 5.0%")
    print(res["table_global"].to_string(index=False))

    print(f"\n[Artifact 2] Stratified Warning Table: {args.out_stratified}")
    meta_s = compute_table_meta_metrics(res["table_stratified"])
    print(f"Stratified Out-of-CI Rate vs Expected: {meta_s['out_of_ci_count']}/{meta_s['total_valid_strata']} ({meta_s['out_of_ci_rate']:.1%}) vs nominal 5.0%")

    print(f"\n[Artifact 3] Brier Skill Score Summary: {args.out_brier}")
    print(res["table_brier"].to_string(index=False))
    print("\nExecution complete. All artifacts generated successfully without selective display.")


if __name__ == "__main__":
    main()
