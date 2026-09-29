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
from typing import Dict, Any, Tuple, List, Optional, Union

import numpy as np
import pandas as pd
from scipy import stats, integrate

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.verification.settlement import compute_settlement_hit_probability
from src.verification.resampling import get_or_create_cv_manifest
from src.modeling.resampling import evaluate_evt_tail_cdf

DEFAULT_TRAIN_PARQUET = PROJECT_ROOT / "data" / "processed" / "audit_arrays" / "2000_2018_training_arrays.parquet"
DEFAULT_R6_JSON = PROJECT_ROOT / "evidence" / "r6_kmia_parameters.json"
DEFAULT_R7_JSON = PROJECT_ROOT / "evidence" / "r7_tail_parameters.json"
DEFAULT_CV_MANIFEST = PROJECT_ROOT / "evidence" / "cv_split_blocks_20rounds.json"
DEFAULT_OUT_GLOBAL = PROJECT_ROOT / "evidence" / "reliability_check_main_global.csv"
DEFAULT_OUT_STRATIFIED = PROJECT_ROOT / "evidence" / "reliability_check_stratified_station_season.csv"
DEFAULT_OUT_BRIER = PROJECT_ROOT / "evidence" / "reliability_check_brier_skill.csv"
DEFAULT_OUT_DECISION = PROJECT_ROOT / "evidence" / "reliability_check_decision_track.csv"
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


class DataAssetError(ValueError):
    """Raised when input dataset lacks required columns or requested stations."""
    pass


def validate_and_adapt_input_dataset(
    df: pd.DataFrame,
    requested_stations: List[str],
    target_obs_col: str,
) -> pd.DataFrame:
    """
    Validates input dataset columns and stations.
    Raises DataAssetError with human-readable diagnostic messages on mismatch (Section 2.4).
    """
    if target_obs_col not in df.columns:
        available_cols = sorted(list(df.columns))
        raise DataAssetError(
            f"Input arrays missing required column '{target_obs_col}'. Available columns: {available_cols}"
        )

    mandatory_cols = ["station", "date", "year", "month", "mu_forecast", "sigma_forecast", "is_nan_obs"]
    for col in mandatory_cols:
        if col not in df.columns:
            available_cols = sorted(list(df.columns))
            raise DataAssetError(
                f"Input arrays missing required column '{col}'. Available columns: {available_cols}"
            )

    available_stations = sorted(list(df["station"].unique()))
    missing_stations = [st for st in requested_stations if st not in available_stations]
    if missing_stations:
        raise DataAssetError(
            f"Requested station '{missing_stations[0]}' not found in input dataset. Available stations: {available_stations}"
        )

    return df[df["station"].isin(requested_stations)].copy()


def apply_benjamini_hochberg_fdr(p_values: np.ndarray) -> np.ndarray:
    """
    Compute Benjamini-Hochberg (BH) false discovery rate (FDR) adjusted q-values (Section 2.2).
    Formula: q_{(i)} = min_{k >= i} (m * p_{(k)} / k)
    Returns q-values aligned with original input order.
    """
    p_arr = np.asarray(p_values, dtype=np.float64)
    m = len(p_arr)
    if m == 0:
        return np.array([], dtype=np.float64)

    order = np.argsort(p_arr)
    sorted_p = p_arr[order]

    ranks = np.arange(1, m + 1, dtype=np.float64)
    raw_q = (sorted_p * m) / ranks

    # Monotonicity adjustment backwards: q_(i) = min_{k >= i} raw_q_k
    adjusted_q = np.minimum.accumulate(raw_q[::-1])[::-1]
    adjusted_q = np.clip(adjusted_q, 0.0, 1.0)

    # Invert sorting order back to original
    orig_q = np.empty_like(adjusted_q)
    orig_q[order] = adjusted_q
    return orig_q


def compute_pit_effect_size(pit_values: np.ndarray) -> Tuple[float, bool]:
    """
    Compute PIT effect size D_effect = max_j |F_hat_PIT(u_j) - u_j| against Uniform[0, 1] (Section 2.2).
    Flags EFFECT-SIZE-ALERT if D_effect > 0.08.
    """
    clean_pit = np.asarray(pit_values, dtype=np.float64)
    clean_pit = clean_pit[~np.isnan(clean_pit)]
    n = len(clean_pit)
    if n == 0:
        return 0.0, False

    sorted_pit = np.sort(np.clip(clean_pit, 0.0, 1.0))
    d_plus = np.max((np.arange(1, n + 1) / n) - sorted_pit)
    d_minus = np.max(sorted_pit - (np.arange(0, n) / n))
    d_effect = float(max(d_plus, d_minus))
    has_alert = bool(d_effect > 0.08)
    return d_effect, has_alert


def pit_to_bin(pit: float) -> int:
    """
    Route scalar PIT probability into 1 of 20 statutory bins [1..20].
    Bins are 0.05-wide with edge-inclusive-left routing [0, 0.05), [0.05, 0.10)... [0.95, 1.0].
    """
    val = float(pit)
    if math.isnan(val) or math.isinf(val) or val < 0.0 or val > 1.0:
        raise DataAssetError(f"DataAssetError: PIT value {val} out of valid range [0, 1]")
    edges = np.round(np.arange(0.05, 1.0, 0.05), 2)
    return int(np.searchsorted(edges, val, side="right")) + 1


def route_pit_value(pit: Any) -> int:
    """
    Defensive input sentinel for single PIT routing (S1).
    Validates empty, nan, and bounds.
    Spec Revision #4 Annex B1: 0.35 routes legally to bin 8 ([0.35, 0.40)).
    """
    if pit is None or (isinstance(pit, str) and pit.strip() == ""):
        raise DataAssetError("empty_input: PIT value cannot be empty")
    try:
        val = float(pit)
    except Exception as e:
        raise DataAssetError(f"DataAssetError: invalid non-numeric PIT value '{pit}'") from e
    if math.isnan(val) or math.isinf(val) or val < 0.0 or val > 1.0:
        raise DataAssetError(f"DataAssetError: invalid PIT value {val} out of bounds or NaN/inf")
    return pit_to_bin(val)


def check_stream_degeneracy(pits: Union[List[float], np.ndarray], tol: float = 1e-9) -> None:
    """
    Check if a stream of PIT values has collapsed variance (all identical values).
    Spec Revision #4 Annex B2: Triggers degenerate exception on zero-variance stream (N > 1).
    """
    if len(pits) > 1:
        first = float(pits[0])
        if all(abs(float(p) - first) <= tol for p in pits):
            raise DataAssetError("degenerate: zero variance / collapsed variance stream detected")



def wilson_interval(k: int, n: int, confidence: float = 0.95) -> Tuple[float, float]:
    """
    Compute Wilson score confidence interval [ci_lower, ci_upper] at specified confidence.
    """
    if n <= 0:
        return 0.0, 1.0
    z = 1.96 if abs(confidence - 0.95) < 1e-5 else stats.norm.ppf((1.0 + confidence) / 2.0)
    p_hat = k / n
    denom = 1.0 + (z**2) / n
    center = (p_hat + (z**2) / (2.0 * n)) / denom
    half_width = (z * math.sqrt((p_hat * (1.0 - p_hat) / n) + (z**2) / (4.0 * (n**2)))) / denom
    return center - half_width, center + half_width


def compute_pit(obs: float, mu: float, sigma: float, seed: int = 42) -> float:
    """
    Standardized PIT calculation with +/- 0.05°F discretization jitter.
    """
    rng = np.random.default_rng(seed)
    eps = rng.uniform(-0.05, 0.05)
    z = (obs + eps - mu) / sigma
    return float(stats.norm.cdf(z))


def weighted_ece(buckets: List[Dict[str, Any]]) -> float:
    """
    Calculate sample-size weighted Expected Calibration Error (ECE).
    """
    total_n = sum(b.get("n", 0) for b in buckets)
    if total_n == 0:
        return 0.0
    weighted_sum = sum(b.get("n", 0) * abs(b.get("dev", b.get("abs_diff", 0.0))) for b in buckets)
    return float(weighted_sum / total_n)


def brier_skill_score(bs_model: float, bs_clim: float) -> float:
    """
    Compute Brier Skill Score (BSS) relative to climatology baseline.
    """
    if bs_clim <= 0.0:
        return 0.0
    return float(1.0 - (bs_model / bs_clim))


def merge_small_bins(
    counts: List[int],
    min_n: int = 30,
    p_bar: Optional[Union[List[float], np.ndarray]] = None,
) -> Union[List[List[int]], Tuple[List[Any], bool]]:
    """
    T2 adaptive merge sequence for bins with sample count < min_n (spec §2.1).
    Conventions:
      C1: Process the leftmost small bin (count < min_n) in each round.
      C2: If |Δp̄| between left and right neighbors ties within 1e-9 tolerance, merge into left neighbor.
      C3: When p_bar is None, initialize midpoints p̄ᵢ = 0.05 * i + 0.025. After merge, update p̄ by sample-weighted mean.
      Boundary: If total sample N < min_n, return ([], False) without initiating merge loop.
    Returns:
      merges: list of merged pairs [left_idx, right_idx].
    """
    curr_counts = list(counts)
    total_n = sum(curr_counts)
    if total_n < min_n:
        return [], False

    if p_bar is None:
        curr_p = [0.05 * i + 0.025 for i in range(len(curr_counts))]
    else:
        if len(p_bar) != len(curr_counts):
            raise ValueError(f"p_bar length {len(p_bar)} does not match counts length {len(curr_counts)}")
        curr_p = [float(p) for p in p_bar]

    merges: List[List[int]] = []
    while True:
        # C1: leftmost small bin
        low_idx = None
        for i, c in enumerate(curr_counts):
            if c < min_n:
                low_idx = i
                break

        if low_idx is None or len(curr_counts) <= 1:
            break

        target_p = curr_p[low_idx]
        left_delta = abs(target_p - curr_p[low_idx - 1]) if low_idx > 0 else float("inf")
        right_delta = abs(target_p - curr_p[low_idx + 1]) if low_idx < len(curr_counts) - 1 else float("inf")

        # C2: |Δp̄| tie-break (tol 1e-9) to left neighbor
        if abs(left_delta - right_delta) <= 1e-9:
            partner = low_idx - 1
        elif left_delta < right_delta:
            partner = low_idx - 1
        else:
            partner = low_idx + 1

        i_min = min(low_idx, partner)
        i_max = max(low_idx, partner)
        merges.append([i_min, i_max])

        # C3: weighted average p_bar update
        c1, c2 = curr_counts[i_min], curr_counts[i_max]
        p1, p2 = curr_p[i_min], curr_p[i_max]
        new_c = c1 + c2
        new_p = (c1 * p1 + c2 * p2) / new_c if new_c > 0 else (p1 + p2) / 2.0

        curr_counts[i_min] = new_c
        curr_p[i_min] = new_p
        curr_counts.pop(i_max)
        curr_p.pop(i_max)

    return merges


def route_stream(csv_path: str, check_degeneracy: bool = False) -> Dict[str, Any]:
    """
    Parse CSV stream of PIT values, route into 20 bins, and extract invariants.
    If check_degeneracy is True, raises DataAssetError on zero-variance streams (Spec Revision #4 Annex B2).
    """
    import csv as _csv
    pits = []
    edges = np.round(np.arange(0.05, 1.0, 0.05), 2)
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = _csv.DictReader(f)
        for r in reader:
            val = float(r["pit"])
            if val < 0.0 or val > 1.0 or math.isnan(val):
                raise DataAssetError(f"Stream PIT out of bounds: {val}")
            pits.append(val)

    if check_degeneracy:
        check_stream_degeneracy(pits)

    counts = [0] * 20
    for p in pits:
        b = int(np.searchsorted(edges, p, side="right"))
        counts[b] += 1

    sorted_pits = sorted(pits)
    first_last_sorted = [int(np.searchsorted(edges, p, side="right")) + 1 for p in sorted_pits]

    return {
        "row_count": len(pits),
        "counts": counts,
        "first_last_bin_of_sorted": first_last_sorted,
    }


def analyze_pit_stream(csv_path: str) -> Dict[str, Any]:
    """
    Stream analysis entry point enforcing stream-level degeneracy validation (Spec Revision #4 Annex B2).
    """
    return route_stream(csv_path, check_degeneracy=True)



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


# EVT GPD tail CDF evaluation canonicalized in src/modeling/resampling.py
_evaluate_evt_tail_cdf = evaluate_evt_tail_cdf


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
    """Build stratified warning table across station x season cells with power warnings (Section 3.2)."""
    target_stations = stations or ["KORD", "KMIA", "KSFO"]
    target_seasons = seasons or ["Winter", "Spring", "Summer", "Autumn"]

    all_stratified_rows = []
    for st in target_stations:
        for se in target_seasons:
            sub = df_expanded[(df_expanded["station"] == st) & (df_expanded["season"] == se)]
            table_df, _ = build_global_reliability_table(sub, num_bins=num_bins)
            table_df.insert(0, "station", st)
            table_df.insert(1, "season", se)

            # Section 3.2: Statistical Power Warning
            n_cell = len(sub)
            is_low_power = bool(n_cell < 500)
            delta_mds = float(2.8 / math.sqrt(n_cell)) if n_cell > 0 else np.nan
            table_df["low_power"] = is_low_power
            table_df["delta_mds"] = delta_mds

            all_stratified_rows.append(table_df)

    return pd.concat(all_stratified_rows, ignore_index=True) if all_stratified_rows else pd.DataFrame()


def build_dual_track_reliability_table(
    df_expanded: pd.DataFrame,
    num_bins: int = 20,
    min_n_per_bin: int = 30,
    bootstrap_samples: int = 1000,
    seed: int = 20260923,
) -> Dict[str, Any]:
    """
    Dual-Track Hybrid Binning Engine (Specification Section 2.1 & 3.3):
    1. Decision Track (主轨): Merges bins with n < 30 into nearest p_bar neighbor.
       Flags WIDE-BIN if merged delta_p > 0.15. Wilson score CI for coverage.
    2. Benchmark Track (辅轨): Fixed 20 equal-width bins for global ECE.
       1,000 deterministic bootstrap CI for weighted ECE.
    """
    table_benchmark, weighted_ece = build_global_reliability_table(df_expanded, num_bins=num_bins)

    # 1. Benchmark Track: 1,000 deterministic bootstrap resamples for ECE 95% CI (Section 3.3)
    if not df_expanded.empty and len(df_expanded) >= 30:
        p_all = df_expanded["p_pred"].to_numpy(dtype=np.float64)
        h_all = df_expanded["hit"].to_numpy(dtype=np.float64)
        n_tot = len(p_all)
        edges = np.linspace(0.0, 1.0, num_bins + 1)
        bin_ids = np.clip(np.digitize(p_all, edges) - 1, 0, num_bins - 1)

        rng = np.random.default_rng(seed)
        boot_eces = np.empty(bootstrap_samples, dtype=np.float64)
        for b_i in range(bootstrap_samples):
            idx = rng.integers(0, n_tot, size=n_tot)
            b_bins = bin_ids[idx]
            b_p = p_all[idx]
            b_h = h_all[idx]
            counts = np.bincount(b_bins, minlength=num_bins)
            sum_p = np.bincount(b_bins, weights=b_p, minlength=num_bins)
            sum_h = np.bincount(b_bins, weights=b_h, minlength=num_bins)
            m = counts > 0
            err = np.abs(sum_p[m] / counts[m] - sum_h[m] / counts[m])
            boot_eces[b_i] = np.sum(err * counts[m]) / n_tot

        ece_ci_lower = float(np.percentile(boot_eces, 2.5))
        ece_ci_upper = float(np.percentile(boot_eces, 97.5))
    else:
        ece_ci_lower = float(weighted_ece)
        ece_ci_upper = float(weighted_ece)

    # 2. Decision Track (自适应合并迭代)
    if df_expanded.empty or len(df_expanded) < min_n_per_bin:
        decision_df = table_benchmark.copy()
        decision_df["track"] = "decision"
        decision_df["bin_width"] = 1.0 / num_bins
        decision_df["merged_sub_bins"] = [str(i + 1) for i in range(len(decision_df))]
        return {
            "decision_table": decision_df,
            "benchmark_table": table_benchmark,
            "weighted_ece": weighted_ece,
            "ece_ci_lower": ece_ci_lower,
            "ece_ci_upper": ece_ci_upper,
        }

    p_arr = df_expanded["p_pred"].to_numpy(dtype=np.float64)
    h_arr = df_expanded["hit"].to_numpy(dtype=np.float64)
    edges = np.linspace(0.0, 1.0, num_bins + 1)

    class CandidateBin:
        def __init__(self, b_idx: int, low: float, high: float):
            self.low = low
            self.high = high
            self.sub_bins = [b_idx + 1]
            if b_idx == num_bins - 1:
                mask = (p_arr >= low) & (p_arr <= high)
            else:
                mask = (p_arr >= low) & (p_arr < high)
            self.p_vals = list(p_arr[mask])
            self.h_vals = list(h_arr[mask])

        @property
        def n(self) -> int:
            return len(self.p_vals)

        @property
        def mean_p(self) -> float:
            return float(np.mean(self.p_vals)) if self.n > 0 else (self.low + self.high) / 2.0

        @property
        def width(self) -> float:
            return self.high - self.low

        def merge_with(self, other: "CandidateBin"):
            self.low = min(self.low, other.low)
            self.high = max(self.high, other.high)
            self.sub_bins.extend(other.sub_bins)
            self.p_vals.extend(other.p_vals)
            self.h_vals.extend(other.h_vals)

    bins: List[CandidateBin] = [CandidateBin(i, edges[i], edges[i + 1]) for i in range(num_bins)]

    while True:
        low_idx = None
        for i, b in enumerate(bins):
            if b.n < min_n_per_bin:
                low_idx = i
                break

        if low_idx is None or len(bins) <= 1:
            break

        target = bins[low_idx]
        neighbors = []
        if low_idx > 0:
            neighbors.append((low_idx - 1, abs(target.mean_p - bins[low_idx - 1].mean_p)))
        if low_idx < len(bins) - 1:
            neighbors.append((low_idx + 1, abs(target.mean_p - bins[low_idx + 1].mean_p)))

        neighbors.sort(key=lambda x: x[1])
        partner_idx = neighbors[0][0]

        i_left = min(low_idx, partner_idx)
        i_right = max(low_idx, partner_idx)
        bins[i_left].merge_with(bins[i_right])
        bins.pop(i_right)

    dec_rows = []
    for s_idx, b in enumerate(bins):
        n_c = b.n
        mean_p = float(np.mean(b.p_vals)) if n_c > 0 else np.nan
        emp_h = float(np.mean(b.h_vals)) if n_c > 0 else np.nan
        abs_bias = float(abs(mean_p - emp_h)) if n_c > 0 else np.nan
        ci_low, ci_high, ci_half = compute_wilson_ci(float(np.sum(b.h_vals)), n_c, confidence=0.95)
        is_outside = bool(mean_p < ci_low or mean_p > ci_high) if n_c > 0 else False
        is_wide = bool(b.width > 0.15)
        label = "WIDE-BIN" if is_wide else "NORMAL"

        dec_rows.append({
            "track": "decision",
            "stratum_id": s_idx + 1,
            "stratum_range": f"[{b.low:.2f}, {b.high:.2f}]",
            "bin_width": float(b.width),
            "merged_sub_bins": ",".join(str(x) for x in b.sub_bins),
            "sample_count_n": n_c,
            "mean_pred_prob": mean_p,
            "empirical_hit_freq": emp_h,
            "abs_bias": abs_bias,
            "ci_lower": ci_low,
            "ci_upper": ci_high,
            "ci_95_half_width": ci_half,
            "is_outside_ci": is_outside,
            "warning_low_n": False,
            "label": label,
        })

    decision_df = pd.DataFrame(dec_rows)
    return {
        "decision_table": decision_df,
        "benchmark_table": table_benchmark,
        "weighted_ece": weighted_ece,
        "ece_ci_lower": ece_ci_lower,
        "ece_ci_upper": ece_ci_upper,
    }


def check_monotonicity_and_coverage(decision_table: pd.DataFrame) -> Dict[str, Any]:
    """
    Audit decision track reliability table against GATE-L2-02 criteria:
    1. Weak monotonicity of empirical hit frequency: f_{i+1} >= f_i - 1e-4.
    2. Wilson 95% CI coverage rate >= 90%.
    3. Consecutive out-of-CI alarm if two adjacent bins are outside CI.
    """
    valid = decision_table[decision_table["sample_count_n"] > 0].copy()
    if valid.empty:
        return {"passed": True, "coverage_rate": 1.0, "monotonicity_violations": 0, "alarms": []}

    f_vals = valid["empirical_hit_freq"].to_numpy(dtype=np.float64)
    is_outside = valid["is_outside_ci"].to_numpy(dtype=bool)

    diffs = np.diff(f_vals)
    violations = int(np.sum(diffs < -1e-4))

    coverage_rate = float(np.mean(~is_outside))

    alarms = []
    has_consecutive = False
    for i in range(len(is_outside) - 1):
        if is_outside[i] and is_outside[i + 1]:
            has_consecutive = True
            break
    if has_consecutive:
        alarms.append("CONSECUTIVE-MISCALIBRATION-ALARM")

    passed = (violations == 0) and (coverage_rate >= 0.90) and (not has_consecutive)
    return {
        "passed": bool(passed),
        "violations": violations,
        "coverage_rate": coverage_rate,
        "alarms": alarms,
    }



# ==============================================================================
# Climatology Baseline & Brier Skill Score Calculation (Section 2.3)
# ==============================================================================

def _vectorized_settlement_hit_probability(pool: np.ndarray, lb: float, ub: float, jitter: float = 0.05) -> float:
    """Compute empirical settlement hit probability over pool with +/- 0.05°F jitter."""
    if len(pool) == 0:
        return 1.0 / 7.0
    if math.isinf(lb):
        frac_low = 0.0
    else:
        frac_low = float(np.mean(np.clip((lb + jitter - pool) / (2.0 * jitter), 0.0, 1.0)))
    if math.isinf(ub):
        frac_high = 0.0
    else:
        frac_high = float(np.mean(np.clip((pool - (ub - jitter)) / (2.0 * jitter), 0.0, 1.0)))
    return float(max(0.0, min(1.0, 1.0 - frac_low - frac_high)))


def _build_smoothed_loyo_climatology_cache(
    valid_raw: pd.DataFrame,
    target_obs_col: str = "obs_tmax_f",
) -> Dict[Tuple[str, int, int], np.ndarray]:
    """
    Build 15-day rolling window (+/- 7 calendar days) LOYO climatology observation pools (Section 2.3).
    Circular wrap around 365 days.
    Key: (station, day_of_year, year) -> sorted numpy array of historical observations.
    """
    df = valid_raw.copy()
    if "date" in df.columns:
        dt = pd.to_datetime(df["date"], errors="coerce")
        fallback_doy = (df["month"].to_numpy().astype(int) - 1) * 30 + 15
        doy = np.where(dt.notna(), dt.dt.dayofyear.to_numpy(), fallback_doy)
        doy = np.clip(doy, 1, 365)
    else:
        # Fallback if date is not present (e.g., month-only unit test)
        doy = np.clip((df["month"].to_numpy().astype(int) - 1) * 30 + 15, 1, 365)

    df["_doy"] = doy

    lookup: Dict[Tuple[str, int, int], np.ndarray] = {}
    for (st, d, yr), grp in df.groupby(["station", "_doy", "year"]):
        lookup[(st, int(d), int(yr))] = grp[target_obs_col].to_numpy(dtype=np.float64)

    stations = df["station"].unique()
    years_by_st = {st: sorted(list(df[df["station"] == st]["year"].unique())) for st in stations}

    smoothed_cache: Dict[Tuple[str, int, int], np.ndarray] = {}

    for st in stations:
        st_years = years_by_st[st]
        doy_yr_obs = {}
        for d in range(1, 366):
            for yr in st_years:
                arr = lookup.get((st, d, yr))
                if arr is not None and len(arr) > 0:
                    doy_yr_obs[(d, yr)] = arr

        for d in range(1, 366):
            window_days = [((d - 1 + offset) % 365) + 1 for offset in range(-7, 8)]
            # Pre-collect by year in window
            yr_window_obs = {}
            for yr in st_years:
                arrs = [doy_yr_obs[(wd, yr)] for wd in window_days if (wd, yr) in doy_yr_obs]
                if arrs:
                    yr_window_obs[yr] = np.concatenate(arrs)

            for yr in st_years:
                other_obs = [yr_window_obs[y] for y in st_years if y != yr and y in yr_window_obs]
                if other_obs:
                    smoothed_cache[(st, d, yr)] = np.sort(np.concatenate(other_obs))
                elif yr in yr_window_obs:
                    # Only self available fallback
                    smoothed_cache[(st, d, yr)] = np.sort(yr_window_obs[yr])
                else:
                    smoothed_cache[(st, d, yr)] = np.array([], dtype=np.float64)

    return smoothed_cache


def compute_brier_skill_scores(
    df_expanded: pd.DataFrame,
    df_train_raw: pd.DataFrame,
    target_obs_col: str = "obs_tmax_f",
    stations_list: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Compute Brier Scores for Model and Smoothed LOYO Climatology, and Brier Skill Score (BSS)."""
    valid_raw = df_train_raw[~df_train_raw["is_nan_obs"]].copy()
    loyo_cache = _build_smoothed_loyo_climatology_cache(valid_raw, target_obs_col)

    if "date" in df_expanded.columns:
        dt_exp = pd.to_datetime(df_expanded["date"], errors="coerce")
        fallback_doy = (df_expanded["month"].to_numpy().astype(int) - 1) * 30 + 15
        doy_exp = np.where(dt_exp.notna(), dt_exp.dt.dayofyear.to_numpy(), fallback_doy)
        doy_exp = np.clip(doy_exp, 1, 365)
    else:
        doy_exp = np.clip((df_expanded["month"].to_numpy().astype(int) - 1) * 30 + 15, 1, 365)

    p_preds = df_expanded["p_pred"].to_numpy(dtype=np.float64)
    hits = df_expanded["hit"].to_numpy(dtype=np.float64)
    stations = df_expanded["station"].to_numpy()
    years = df_expanded["year"].to_numpy(dtype=int)
    seasons = df_expanded["season"].to_numpy()
    lbs = df_expanded["bin_lower"].to_numpy(dtype=np.float64)
    ubs = df_expanded["bin_upper"].to_numpy(dtype=np.float64)

    n_records = len(df_expanded)
    p_clims = np.zeros(n_records, dtype=np.float64)

    for i in range(n_records):
        pool = loyo_cache.get((stations[i], doy_exp[i], years[i]), np.array([], dtype=np.float64))
        p_clims[i] = _vectorized_settlement_hit_probability(pool, lbs[i], ubs[i], jitter=0.05)

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

def _fit_johnsonsu_multistart(z_data: np.ndarray) -> Tuple[float, float, float, float]:
    """Fit Johnson SU parameters using 5 deterministic initial guesses to maximize log-likelihood (Section 3.1)."""
    z_clean = z_data[~np.isnan(z_data)]
    if len(z_clean) < 10:
        return 0.0, 1.0, 0.0, 1.0

    std_z = float(np.std(z_clean))
    if std_z <= 0:
        std_z = 1.0
    mean_z = float(np.mean(z_clean))
    med_z = float(np.median(z_clean))

    candidates = []
    try:
        cand1 = stats.johnsonsu.fit(z_clean)
        candidates.append(cand1)
    except Exception:
        pass

    guesses = [
        (0.0, 1.0, med_z, std_z),
        (-0.5, 1.2, mean_z, std_z),
        (0.5, 1.2, mean_z, std_z),
        (0.0, 0.8, med_z, std_z),
        (-0.2, 1.5, med_z, std_z * 0.9),
    ]

    for g, d, x, l in guesses:
        try:
            cand = stats.johnsonsu.fit(z_clean, floc=x, fscale=l)
            candidates.append(cand)
        except Exception:
            candidates.append((g, d, x, l))

    best_ll = -np.inf
    best_params = (0.0, 1.0, 0.0, 1.0)
    for g, d, x, l in candidates:
        if d <= 0 or l <= 0:
            continue
        try:
            ll = float(np.sum(stats.johnsonsu.logpdf(z_clean, g, d, loc=x, scale=l)))
            if np.isfinite(ll) and ll > best_ll:
                best_ll = ll
                best_params = (float(g), float(d), float(x), float(l))
        except Exception:
            continue

    return best_params


def _fit_evt_parameters(z_data: np.ndarray) -> Dict[str, Any]:
    """Fit EVT generalized Pareto parameters on 5% and 95% tails (Section 3.1)."""
    z_clean = z_data[~np.isnan(z_data)]
    if len(z_clean) < 20:
        return {
            "u_left": -1.645, "u_right": 1.645,
            "gpd_left": {"shape_xi": 0.0, "scale_beta": 0.5},
            "gpd_right": {"shape_xi": 0.0, "scale_beta": 0.5},
        }
    u_l = float(np.percentile(z_clean, 5.0))
    u_r = float(np.percentile(z_clean, 95.0))
    ex_l = - (z_clean[z_clean < u_l] - u_l)
    ex_r = z_clean[z_clean > u_r] - u_r

    c_l, _, scale_l = stats.genpareto.fit(ex_l, floc=0.0) if len(ex_l) >= 5 else (0.0, 0.0, 0.5)
    c_r, _, scale_r = stats.genpareto.fit(ex_r, floc=0.0) if len(ex_r) >= 5 else (0.0, 0.0, 0.5)

    return {
        "u_left": u_l,
        "u_right": u_r,
        "gpd_left": {"shape_xi": float(c_l), "scale_beta": float(scale_l)},
        "gpd_right": {"shape_xi": float(c_r), "scale_beta": float(scale_r)},
    }


def refit_parameters_on_subset(
    df_train_sub: pd.DataFrame,
    mapping_config: Dict[str, str],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Refit R-6 (Johnson SU) and R-7 (EVT) parameters strictly on training complement.
    Ensures zero data leakage during cross-validation rounds.
    Strictly restricted to 3 statutory families: 'gaussian', 'johnsonsu', 'evt'.
    """
    r6_out: Dict[str, Any] = {"johnsonsu_parameters": {}}
    r7_out: Dict[str, Any] = {"stations": {}}
    for st, family in mapping_config.items():
        if family not in {"gaussian", "johnsonsu", "evt"}:
            raise ValueError(
                f"Invalid distribution family '{family}' for station {st}. "
                "Allowed families are strictly: ['gaussian', 'johnsonsu', 'evt']"
            )

        if family == "johnsonsu":
            sub_st = df_train_sub[(df_train_sub["station"] == st) & (~df_train_sub["is_nan_obs"])]
            if len(sub_st) > 50:
                z_raw = (sub_st["resid_calibrated"] / sub_st["sigma_forecast"]).to_numpy()
                gamma, delta, xi, lam = _fit_johnsonsu_multistart(z_raw)
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

        elif family == "evt":
            sub_st = df_train_sub[(df_train_sub["station"] == st) & (~df_train_sub["is_nan_obs"])]
            if len(sub_st) > 50:
                z_raw = (sub_st["resid_calibrated"] / sub_st["sigma_forecast"]).to_numpy()
                r7_out["stations"][st] = _fit_evt_parameters(z_raw)
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
    dual_res = build_dual_track_reliability_table(pooled_eval_df, num_bins=num_bins)
    table_global = dual_res["benchmark_table"]
    table_decision = dual_res["decision_table"]
    weighted_ece = dual_res["weighted_ece"]
    ece_ci_lower = dual_res["ece_ci_lower"]
    ece_ci_upper = dual_res["ece_ci_upper"]

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
        "table_decision": table_decision,
        "weighted_ece": weighted_ece,
        "ece_ci_lower": ece_ci_lower,
        "ece_ci_upper": ece_ci_upper,
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
    out_decision_path: Optional[Path] = None,
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
    dual_res = build_dual_track_reliability_table(df_expanded, num_bins=20)
    table_global = dual_res["benchmark_table"]
    table_decision = dual_res["decision_table"]
    weighted_ece = dual_res["weighted_ece"]
    ece_ci_lower = dual_res["ece_ci_lower"]
    ece_ci_upper = dual_res["ece_ci_upper"]

    table_stratified = build_stratified_warning_table(df_expanded, num_bins=10, stations=stations_list)
    table_brier = compute_brier_skill_scores(df_expanded, df_train, target_obs_col=target_obs_col, stations_list=stations_list)

    meta = dict(metadata_headers or {})
    meta["ece_ci_95"] = f"[{ece_ci_lower:.4%}, {ece_ci_upper:.4%}]"

    save_dataframe_with_metadata(table_global, out_global_path, meta)
    if out_decision_path:
        save_dataframe_with_metadata(table_decision, out_decision_path, meta)
    save_dataframe_with_metadata(table_stratified, out_stratified_path, meta)
    save_dataframe_with_metadata(table_brier, out_brier_path, meta)

    return {
        "df_expanded": df_expanded,
        "table_global": table_global,
        "table_decision": table_decision,
        "weighted_ece": weighted_ece,
        "ece_ci_lower": ece_ci_lower,
        "ece_ci_upper": ece_ci_upper,
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
    parser.add_argument("--out-decision", type=Path, default=DEFAULT_OUT_DECISION, help="Output path for decision track CSV.")
    parser.add_argument("--out-stratified", type=Path, default=DEFAULT_OUT_STRATIFIED, help="Output path for stratified CSV.")
    parser.add_argument("--out-brier", type=Path, default=DEFAULT_OUT_BRIER, help="Output path for Brier CSV.")
    parser.add_argument("--synthetic-suite", type=Path, default=None, help="Path to synthetic stream CSV for determinism test.")
    parser.add_argument("--out", type=Path, default=None, help="Output path for synthetic suite execution.")

    args = parser.parse_args()

    if args.synthetic_suite is not None:
        import csv as _csv
        res = route_stream(str(args.synthetic_suite), check_degeneracy=True)
        out_target = args.out if args.out is not None else Path("synthetic_out.csv")
        with open(out_target, "w", newline="", encoding="utf-8") as f:
            writer = _csv.writer(f)
            writer.writerow(["bin_idx", "count"])
            for b_i, c in enumerate(res["counts"]):
                writer.writerow([b_i + 1, c])
        print(f"Synthetic suite processed {res['row_count']} rows -> {out_target}")
        return

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
    # R6 & Section 2.4: Robust Input Defense & Adapter
    df_train = validate_and_adapt_input_dataset(
        df_train,
        requested_stations=stations_list,
        target_obs_col=target_obs_col,
    )

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
        metadata_block["ece_ci_95"] = f"[{res['ece_ci_lower']:.4%}, {res['ece_ci_upper']:.4%}]"
        save_dataframe_with_metadata(res["table_global"], args.out_global, metadata_block)
        save_dataframe_with_metadata(res["table_decision"], args.out_decision, metadata_block)
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
            out_decision_path=args.out_decision,
            binning_scheme=args.binning_scheme,
            mode=args.mode,
            model_status=model_status,
            target_obs_col=target_obs_col,
            stations_list=stations_list,
            metadata_headers=metadata_block,
        )

    print(f"\n[Artifact 1] Global Reliability Benchmark Table: {args.out_global}")
    print(f"Global Weighted ECE: {res['weighted_ece']:.4%} (95% Bootstrap CI: [{res['ece_ci_lower']:.4%}, {res['ece_ci_upper']:.4%}])")
    meta_m = compute_table_meta_metrics(res["table_global"])
    print(f"Out-of-CI Rate vs Expected: {meta_m['out_of_ci_count']}/{meta_m['total_valid_strata']} ({meta_m['out_of_ci_rate']:.1%}) vs nominal 5.0%")
    print(res["table_global"].to_string(index=False))

    print(f"\n[Artifact 1b] Decision Track Reliability Table: {args.out_decision}")
    meta_d = compute_table_meta_metrics(res["table_decision"])
    print(f"Decision Track Out-of-CI Rate: {meta_d['out_of_ci_count']}/{meta_d['total_valid_strata']} ({meta_d['out_of_ci_rate']:.1%})")
    wide_count = int((res["table_decision"]["label"] == "WIDE-BIN").sum())
    print(f"Wide Bins (delta_p > 0.15): {wide_count}/{len(res['table_decision'])}")
    print(res["table_decision"].to_string(index=False))

    print(f"\n[Artifact 2] Stratified Warning Table: {args.out_stratified}")
    meta_s = compute_table_meta_metrics(res["table_stratified"])
    print(f"Stratified Out-of-CI Rate vs Expected: {meta_s['out_of_ci_count']}/{meta_s['total_valid_strata']} ({meta_s['out_of_ci_rate']:.1%}) vs nominal 5.0%")

    print(f"\n[Artifact 3] Brier Skill Score Summary: {args.out_brier}")
    print(res["table_brier"].to_string(index=False))
    print("\nExecution complete. All artifacts generated successfully without selective display.")


if __name__ == "__main__":
    main()
