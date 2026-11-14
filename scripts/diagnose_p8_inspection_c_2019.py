#!/usr/bin/env python3
"""
Read-Only Diagnostic Suite for P8-ALGO Inspection C (2019 Replay):
Evaluates Owner Pre-Registered Diagnostic Rules 1, 2, 3 & W2 22-Cell Scorecard.

Strict compliance:
- Zero recalibration, zero src/ edits, zero F-2 LOCKED touches, 2019 read-only consumption.
- Task 2:
    (a) Exact Continuous CRPS_bridge vs CRPS_native (and 11-bin RPS) pooled + 16 strata
    (b) Half-hour time-slice profile 06:00-20:00 (29 slices) + 06:00-07:00 construction check
    (c) Exact additive Atom vs Continuous Tail decomposition of ECE_bridge / Delta_bridge
    (d) Binning sensitivity: current 2F fixed grid vs Split-Atom 12-event vs Anchor-aligned grid
- Task 3:
    (1) 2019 vs 608-day pre-2019 per-bucket empirical lock-in rate & prediction comparison
    (2) KORD Spring cloud-cooling / below-anchor frequency: 2019 vs 2016/2017/2018 range
    (3) Afternoon cooling intensity & post-14:00 warming: 2019 vs 2016-2018 climate trend
- Task 4:
    Full 22-cell W2 4-Dimension Scorecard (Bias, CRPSS vs 2000-2018 Clim, Cov90, ECE_w20 & ECE_inw)
- Code-computed booleans for Pre-Registered Rules 1 / 2 / 3.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy import integrate, special, stats

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.calibrate_p8_mu_r_cooling_drift import (
    load_608day_snapshot_frame,
    eval_piecewise_linear_and_deriv,
)
from scripts.compute_p8_oos_and_shape_calibration import (
    AUTHORIZED_LEAD_HOURS,
    AUTHORIZED_STATIONS,
    SEASONS,
    STRATA_EDGES,
    compute_ece_inw,
    compute_ece_w20,
    compute_moments_z,
    get_period,
    get_season,
)
from scripts.run_p8_inspection_a_eta_calibration import (
    POSITION_BUCKETS,
    PRE2019_YEARS,
    SIGMA_INST_PHYSICAL_FLOOR,
    T_GRID,
    classify_position_bucket,
    format_hour,
    load_clean_pre2019_5min,
)
from scripts.run_p8_inspection_c_2019_replay import (
    CLIMATE_CALIB_PATH,
    CONTRACT_PATH,
    ETA_CAL_CSV,
    GHCN_DIR,
    MANIFEST_PATH,
    bracket_hit_index,
    build_2019_cell_priors,
    evaluate_11_bracket_probs_prior,
    load_clean_2019_5min,
)
from src.modeling.climatology import ClimatologyCalculator
from src.prediction.discrete_bin_engine import settle_half_up
from src.prediction.dynamic_corrector import (
    _DEFAULT_COOLING_DRIFT_ARTIFACT,
    Proposal1CoolingDriftMuRHook,
)

OUT_JSON = PROJECT_ROOT / "evidence" / "p8_inspection_c_diagnostics_20261114.json"
OUT_REPORT_MD = PROJECT_ROOT / "evidence" / "p8_inspection_c_diagnostics_report_20261114.md"
OUT_CRPS_CSV = PROJECT_ROOT / "evidence" / "p8_inspection_c_crps_16strata_20261114.csv"
OUT_TIMESLICE_CSV = PROJECT_ROOT / "evidence" / "p8_inspection_c_timeslice_29_20261114.csv"
OUT_W2_CSV = PROJECT_ROOT / "evidence" / "p8_inspection_c_w2_scorecard_22cells_20261114.csv"


def gaussian_crps_exact(y: np.ndarray, mu: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """Closed-form Gaussian CRPS."""
    s = np.maximum(sigma, 1e-8)
    z = (y - mu) / s
    pdf_z = np.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    cdf_z = special.ndtr(z)
    return s * (z * (2.0 * cdf_z - 1.0) + 2.0 * pdf_z - 1.0 / math.sqrt(math.pi))


def _antideriv_phi2(u: np.ndarray) -> np.ndarray:
    """Exact antiderivative of Phi(u)^2: u*Phi(u)^2 + 2*Phi(u)*phi(u) - Phi(u*sqrt(2))/sqrt(pi)."""
    phi_u = special.ndtr(u)
    pdf_u = np.exp(-0.5 * u * u) / math.sqrt(2.0 * math.pi)
    return u * (phi_u**2) + 2.0 * phi_u * pdf_u - special.ndtr(u * math.sqrt(2.0)) / math.sqrt(math.pi)


def bridge_crps_exact(
    y: np.ndarray,
    anchor: np.ndarray,
    mu_r: np.ndarray,
    sigma_rem: np.ndarray,
) -> np.ndarray:
    """Exact closed-form CRPS for rectified-Gaussian bridge X = anchor + max(0, N(mu_r, sigma_rem^2))."""
    s = np.maximum(sigma_rem, 1e-8)
    z0 = -mu_r / s
    z = (y - anchor - mu_r) / s
    i_z0 = _antideriv_phi2(z0)
    i_neg_z0 = _antideriv_phi2(-z0)
    i_z = _antideriv_phi2(z)
    i_neg_z = _antideriv_phi2(-z)

    crps_ge = s * ((i_z - i_z0) + i_neg_z)
    crps_lt = np.maximum(0.0, anchor - y) + s * i_neg_z0
    return np.where(y >= anchor, crps_ge, crps_lt)


class StandardizedJSUCRPSLookup:
    """Precomputed high-precision CRPS lookup for Y = mu_0 + sigma_0 * Z (Z ~ JSU)."""

    def __init__(self, sp: Dict[str, Any], u_max: float = 16.0, step: float = 0.002) -> None:
        g, d, xi, lam = float(sp["gamma"]), float(sp["delta"]), float(sp["xi"]), float(sp["lambda"])
        self.grid = np.arange(-u_max, u_max + 0.5 * step, step, dtype=float)
        cdf = stats.johnsonsu.cdf(self.grid, g, d, loc=xi, scale=lam)
        f2 = cdf**2
        omf2 = (1.0 - cdf) ** 2
        # Left cumulative integral of F(u)^2 from -u_max to z
        left = np.empty_like(self.grid)
        left[0] = 0.0
        left[1:] = np.cumsum(0.5 * (f2[:-1] + f2[1:]) * step)
        # Right cumulative integral of (1-F(u))^2 from z to +u_max
        right = np.empty_like(self.grid)
        right[-1] = 0.0
        right[:-1] = np.cumsum(0.5 * (omf2[:-1] + omf2[1:])[::-1] * step)[::-1]
        self.crps_z = left + right
        self.u_min = float(self.grid[0])
        self.u_max = float(self.grid[-1])
        self.step = step
        self.sp = sp

    def eval_crps(self, y: np.ndarray, mu0: np.ndarray, sigma0: np.ndarray) -> np.ndarray:
        z = (y - mu0) / np.maximum(sigma0, 1e-8)
        base = np.interp(np.clip(z, self.u_min, self.u_max), self.grid, self.crps_z)
        # Linear tail correction outside [-u_max, +u_max] (essentially never reached)
        extra = np.where(z > self.u_max, z - self.u_max, np.where(z < self.u_min, self.u_min - z, 0.0))
        return sigma0 * (base + extra)


def verify_crps_formulas(jsu_sample_sp: Dict[str, Any]) -> Dict[str, float]:
    """Cross-verify analytical bridge CRPS and JSU lookup against scipy.integrate.quad."""
    # Bridge check
    max_br_err = 0.0
    for y_val, anc, mr, sr in [(82.3, 80.0, -1.2, 2.1), (80.0, 80.0, -1.2, 2.1), (79.6, 80.0, 0.5, 1.8), (75.0, 68.0, 6.2, 3.0)]:
        exact = float(bridge_crps_exact(np.array([y_val]), np.array([anc]), np.array([mr]), np.array([sr]))[0])
        def _integrand(x: float) -> float:
            f = 0.0 if x < anc else float(special.ndtr((x - anc - mr) / sr))
            ind = 1.0 if x >= y_val else 0.0
            return (f - ind) ** 2
        q_val, _ = integrate.quad(_integrand, min(y_val, anc) - 10.0 * sr, max(y_val, anc + mr) + 12.0 * sr, points=[anc, y_val])
        max_br_err = max(max_br_err, abs(exact - q_val))

    # JSU check
    lookup = StandardizedJSUCRPSLookup(jsu_sample_sp)
    g, d, xi, lam = float(jsu_sample_sp["gamma"]), float(jsu_sample_sp["delta"]), float(jsu_sample_sp["xi"]), float(jsu_sample_sp["lambda"])
    max_jsu_err = 0.0
    for z_val in [-2.5, 0.0, 1.8]:
        val = float(lookup.eval_crps(np.array([z_val]), np.array([0.0]), np.array([1.0]))[0])
        q_val, _ = integrate.quad(
            lambda x: (float(stats.johnsonsu.cdf(x, g, d, loc=xi, scale=lam)) - (1.0 if x >= z_val else 0.0)) ** 2,
            -16.0, 16.0, points=[z_val]
        )
        max_jsu_err = max(max_jsu_err, abs(val - q_val))

    assert max_br_err < 1e-6, f"Bridge CRPS formula mismatch vs quad: {max_br_err}"
    assert max_jsu_err < 5e-4, f"JSU CRPS lookup mismatch vs quad: {max_jsu_err}"
    return {"max_bridge_crps_err_vs_quad": max_br_err, "max_jsu_crps_err_vs_quad": max_jsu_err}


def compute_additive_ece_decomp_inw(
    p_arr: np.ndarray,
    y_arr: np.ndarray,
    groups: np.ndarray,
) -> Dict[str, Any]:
    """Exact 100%-additive decomposition of inw ECE across bracket groups (0=below, 1=atom, 2=above)."""
    n = len(p_arr)
    ece_total = compute_ece_inw(p_arr, y_arr)
    contrib = {0: 0.0, 1: 0.0, 2: 0.0}
    abs_gap_mass = {0: 0.0, 1: 0.0, 2: 0.0}
    counts = {g: int(np.sum(groups == g)) for g in (0, 1, 2)}

    for s_idx in range(len(STRATA_EDGES) - 1):
        lo, hi = STRATA_EDGES[s_idx], STRATA_EDGES[s_idx + 1]
        mask = (p_arr >= lo) & (p_arr <= hi) if s_idx == len(STRATA_EDGES) - 2 else (p_arr >= lo) & (p_arr < hi)
        cnt = int(np.sum(mask))
        if cnt == 0:
            continue
        sgn = 1.0 if float(np.mean(p_arr[mask]) - np.mean(y_arr[mask])) >= 0.0 else -1.0
        for g in (0, 1, 2):
            mg = mask & (groups == g)
            cg = int(np.sum(mg))
            if cg > 0:
                diff_g = float(np.mean(p_arr[mg]) - np.mean(y_arr[mg]))
                contrib[g] += sgn * (cg / n) * diff_g
                abs_gap_mass[g] += (cg / n) * abs(diff_g)

    group_ece = {g: compute_ece_inw(p_arr[groups == g], y_arr[groups == g]) for g in (0, 1, 2)}
    return {
        "ece_total": round(ece_total, 6),
        "sum_check": round(contrib[0] + contrib[1] + contrib[2], 6),
        "contrib_below": round(contrib[0], 6),
        "contrib_atom": round(contrib[1], 6),
        "contrib_above": round(contrib[2], 6),
        "share_below_pct": round(100.0 * contrib[0] / max(ece_total, 1e-12), 2),
        "share_atom_pct": round(100.0 * contrib[1] / max(ece_total, 1e-12), 2),
        "share_above_pct": round(100.0 * contrib[2] / max(ece_total, 1e-12), 2),
        "standalone_ece_below": round(group_ece[0], 6),
        "standalone_ece_atom": round(group_ece[1], 6),
        "standalone_ece_above": round(group_ece[2], 6),
        "n_below": counts[0],
        "n_atom": counts[1],
        "n_above": counts[2],
    }


def compute_additive_ece_decomp_w20(
    p_arr: np.ndarray,
    y_arr: np.ndarray,
    groups: np.ndarray,
) -> Dict[str, Any]:
    """Exact 100%-additive decomposition of w20 ECE across bracket groups (0=below, 1=atom, 2=above)."""
    n = len(p_arr)
    ece_total = compute_ece_w20(p_arr, y_arr)
    bin_edges = np.linspace(0.0, 1.0, 21)
    contrib = {0: 0.0, 1: 0.0, 2: 0.0}
    for i in range(20):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        mask = (p_arr >= lo) & (p_arr <= hi) if i == 19 else (p_arr >= lo) & (p_arr < hi)
        cnt = int(np.sum(mask))
        if cnt == 0:
            continue
        sgn = 1.0 if float(np.mean(p_arr[mask]) - np.mean(y_arr[mask])) >= 0.0 else -1.0
        for g in (0, 1, 2):
            mg = mask & (groups == g)
            cg = int(np.sum(mg))
            if cg > 0:
                diff_g = float(np.mean(p_arr[mg]) - np.mean(y_arr[mg]))
                contrib[g] += sgn * (cg / n) * diff_g
    return {
        "ece_total": round(ece_total, 6),
        "contrib_below": round(contrib[0], 6),
        "contrib_atom": round(contrib[1], 6),
        "contrib_above": round(contrib[2], 6),
        "share_below_pct": round(100.0 * contrib[0] / max(ece_total, 1e-12), 2),
        "share_atom_pct": round(100.0 * contrib[1] / max(ece_total, 1e-12), 2),
        "share_above_pct": round(100.0 * contrib[2] / max(ece_total, 1e-12), 2),
    }


def grade_w2_cell(
    ece_val: float,
    bias_val: float,
    crpss_val: float,
    cov90_val: float,
) -> Tuple[str, str, str, str, str, float]:
    """Evaluate MODEL_SCORECARD.md#L13-L16 4-dimension tiers strictly in code."""
    d1 = "GREEN" if ece_val <= 0.0100 else ("YELLOW" if ece_val <= 0.0200 else "RED")
    ab = abs(bias_val)
    d2 = "GREEN" if ab <= 0.50 else ("YELLOW" if ab <= 1.00 else "RED")
    d3 = "GREEN" if crpss_val >= 0.150 else ("YELLOW" if crpss_val >= 0.050 else "RED")
    if 0.85 <= cov90_val <= 0.95:
        d4 = "GREEN"
    elif (0.80 <= cov90_val < 0.85) or (0.95 < cov90_val <= 0.97):
        d4 = "YELLOW"
    else:
        d4 = "RED"

    rank = {"GREEN": 2, "YELLOW": 1, "RED": 0}
    inv_rank = {2: "GREEN", 1: "YELLOW", 0: "RED"}
    scale_map = {"GREEN": 1.0, "YELLOW": 0.5, "RED": 0.0}
    overall = inv_rank[min(rank[d1], rank[d2], rank[d3], rank[d4])]
    return d1, d2, d3, d4, overall, scale_map[overall]


def main() -> int:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract_cells = contract["cells"]
    manifest_models = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["models"]
    climate_calib = json.loads(CLIMATE_CALIB_PATH.read_text(encoding="utf-8"))
    eta_df = pd.read_csv(ETA_CAL_CSV)
    eta_map = {(str(r.station), str(r.season), float(r.t_hour)): float(r.eta_calibrated) for r in eta_df.itertuples()}

    r2_cal = json.loads((PROJECT_ROOT / "evidence" / "p8_mu_r_rho_released_calibration_20261114.json").read_text(encoding="utf-8"))
    hook = Proposal1CoolingDriftMuRHook.from_calibration_artifact()
    assert _DEFAULT_COOLING_DRIFT_ARTIFACT.name == "p8_mu_r_rho_released_calibration_20261114.json"

    # Moment & JSU CRPS lookup precomputation
    moment_map: Dict[Tuple[str, str], Tuple[str, Dict[str, Any], float, float]] = {}
    jsu_lookups: Dict[Tuple[str, str], StandardizedJSUCRPSLookup] = {}
    sample_sp = None
    for st in AUTHORIZED_STATIONS:
        for seas in SEASONS:
            info = climate_calib[st]["seasons"][seas]
            fam = str(info.get("selected_family", "gaussian"))
            sp = info.get("shape_params", {}) or {}
            ez, stdz = compute_moments_z(fam, sp)
            moment_map[(st, seas)] = (fam, sp, ez, stdz)
            if fam == "johnsonsu":
                jsu_lookups[(st, seas)] = StandardizedJSUCRPSLookup(sp)
                if sample_sp is None:
                    sample_sp = sp

    crps_formula_checks = verify_crps_formulas(sample_sp)

    # Fit strict 2000-2018 ClimatologyCalculator per station
    clim_calc = ClimatologyCalculator(train_start_year=2000, train_end_year=2018)
    for st in AUTHORIZED_STATIONS:
        ghcn_st = pd.read_parquet(GHCN_DIR / f"{st}.parquet").copy()
        ghcn_st["date"] = pd.to_datetime(ghcn_st["target_date"]).dt.strftime("%Y-%m-%d")
        ghcn_st = ghcn_st.rename(columns={"tmax_f": "temp_max"})
        ghcn_st["temp_min"] = ghcn_st["temp_max"]
        clim_calc.fit(ghcn_st, station_id=st, target_types=["max"])

    # Load clean 2019 5-min data
    day_summaries: Dict[Tuple[str, float], pd.DataFrame] = {}
    iem_2019: Dict[str, pd.DataFrame] = {}
    for st in AUTHORIZED_STATIONS:
        sub, _ = load_clean_2019_5min(st)
        iem_2019[st] = sub
        tfin_all = sub.groupby("local_date")["temp_f"].max()
        for h in T_GRID:
            hf = float(h)
            s_h = sub[sub["hour_f"] <= hf + 1e-9].sort_values("local_dt")
            agg = s_h.groupby("local_date").agg(mt=("temp_f", "max"), xt=("temp_f", "last"))
            agg["tfin_all"] = agg.index.map(tfin_all)
            day_summaries[(st, hf)] = agg

    # Collectors
    # 1. CRPS & RPS & Native ECE & W2 collectors
    strata_crps: Dict[Tuple[str, str, str], Dict[str, List[float]]] = {
        (st, seas, per): {"crps_nat": [], "crps_br": [], "crps_br_rawmt": [], "crps_mm": [], "rps_nat": [], "rps_br": []}
        for st in AUTHORIZED_STATIONS
        for seas in SEASONS
        for per in ("early", "late")
    }
    w2_cell_rows: List[Dict[str, Any]] = []

    # 2. Time-slice (29 slices) collectors (pooled + by station + KMIA Summer)
    slice_acc: Dict[float, Dict[str, List[Any]]] = {
        float(h): {
            "br_p": [], "br_h": [],
            "kord_p": [], "kord_h": [],
            "kmia_p": [], "kmia_h": [],
            "kmia_sum_p": [], "kmia_sum_h": [],
            "crps_nat": [], "crps_br": [],
            "mu_shift_vs_mu0": [], "sqrt_eta": [],
            "p_atom": [], "emp_atom_raw": [], "emp_atom_settle": [],
        }
        for h in T_GRID
    }

    # 3. Group decomposition (all 11-bin evals) & Binning sensitivity collectors
    all_br_p, all_br_h, all_br_g, all_br_st, all_br_seas, all_br_per = [], [], [], [], [], []
    # Split-atom 12-event & anchor-aligned evaluators (also per-stratum!)
    bin_sens: Dict[Tuple[str, str, str], Dict[str, List[float]]] = {
        (st, seas, per): {
            "nat_p": [], "nat_h": [],
            "fixed_p": [], "fixed_h": [],
            "split_raw_p": [], "split_raw_h": [],
            "split_set_p": [], "split_set_h": [],
            "anchor_set_p": [], "anchor_set_h": [],
        }
        for st in AUTHORIZED_STATIONS
        for seas in SEASONS
        for per in ("early", "late")
    }

    for st in AUTHORIZED_STATIONS:
        valid_5min_dates = set(iem_2019[st]["local_date"].unique())
        for lead in AUTHORIZED_LEAD_HOURS:
            per = get_period(lead)
            df19 = build_2019_cell_priors(st, lead, manifest_models, climate_calib, contract_cells)
            df19 = df19[df19["target_date"].isin(valid_5min_dates)].copy().reset_index(drop=True)

            dates_arr = df19["target_date"].tolist()
            seas_arr = df19["season"].tolist()
            mu0_arr = df19["mu_0"].to_numpy(dtype=float)
            s0_arr = df19["sigma_0"].to_numpy(dtype=float)
            y_arr = df19["tmax_f"].to_numpy(dtype=float)

            # Vectorized native CRPS & climatology CRPS for W2 cell scorecard
            crps_clim_arr = np.empty(len(df19), dtype=float)
            crps_nat_arr = np.empty(len(df19), dtype=float)
            crps_mm_arr = np.empty(len(df19), dtype=float)
            cov90_arr = np.empty(len(df19), dtype=float)
            bias_pred_minus_obs = mu0_arr - y_arr
            c_nat_p, c_nat_h = [], []
            c0_list: List[int] = []
            hv_list: List[np.ndarray] = []
            rps_nat_arr = np.empty(len(df19), dtype=float)

            for i in range(len(df19)):
                dt = dates_arr[i]
                seas = seas_arr[i]
                mu0 = float(mu0_arr[i])
                s0 = float(s0_arr[i])
                yi = float(y_arr[i])
                fam, sp, ez, stdz = moment_map[(st, seas)]
                mm_mu = mu0 + s0 * ez
                mm_sig = s0 * stdz

                mu_cl, sig_cl = clim_calc.get_climatology(st, "max", dt)
                crps_clim_arr[i] = float(gaussian_crps_exact(np.array([yi]), np.array([mu_cl]), np.array([sig_cl]))[0])
                crps_mm_arr[i] = float(gaussian_crps_exact(np.array([yi]), np.array([mm_mu]), np.array([mm_sig]))[0])
                if fam == "johnsonsu":
                    crps_nat_arr[i] = float(jsu_lookups[(st, seas)].eval_crps(np.array([yi]), np.array([mu0]), np.array([s0]))[0])
                    lq = mu0 + s0 * float(stats.johnsonsu.ppf(0.05, sp["gamma"], sp["delta"], loc=sp["xi"], scale=sp["lambda"]))
                    uq = mu0 + s0 * float(stats.johnsonsu.ppf(0.95, sp["gamma"], sp["delta"], loc=sp["xi"], scale=sp["lambda"]))
                else:
                    crps_nat_arr[i] = float(gaussian_crps_exact(np.array([yi]), np.array([mu0]), np.array([s0]))[0])
                    lq = mu0 - 1.6448536 * s0
                    uq = mu0 + 1.6448536 * s0
                cov90_arr[i] = 1.0 if (lq <= yi <= uq) else 0.0

                c0 = int(round(mu0))
                c0_list.append(c0)
                p_nat, _, _, _ = evaluate_11_bracket_probs_prior(mu0, s0, fam, sp, c0, mm_mu, mm_sig)
                h_idx = bracket_hit_index(yi, c0)
                hv = np.zeros(11, dtype=float)
                hv[h_idx] = 1.0
                hv_list.append(hv)
                c_nat_p.append(p_nat); c_nat_h.append(hv)
                rps_nat_arr[i] = float(np.sum((np.cumsum(p_nat) - np.cumsum(hv)) ** 2))

                bs = bin_sens[(st, seas, per)]
                bs["nat_p"].append(p_nat); bs["nat_h"].append(hv)

            ece_w20_cell = compute_ece_w20(np.concatenate(c_nat_p), np.concatenate(c_nat_h))
            ece_inw_cell = compute_ece_inw(np.concatenate(c_nat_p), np.concatenate(c_nat_h))
            bias_mean = float(np.mean(bias_pred_minus_obs))
            crps_nat_mean = float(np.mean(crps_nat_arr))
            crps_clim_mean = float(np.mean(crps_clim_arr))
            crpss_val = float(1.0 - crps_nat_mean / crps_clim_mean)
            cov90_mean = float(np.mean(cov90_arr))

            d1_w20, d2, d3, d4, ov_w20, scale_w20 = grade_w2_cell(ece_w20_cell, bias_mean, crpss_val, cov90_mean)
            d1_inw, _, _, _, ov_inw, scale_inw = grade_w2_cell(ece_inw_cell, bias_mean, crpss_val, cov90_mean)

            w2_cell_rows.append(
                {
                    "cell": f"{st}_{lead}h",
                    "station": st,
                    "lead_hours": lead,
                    "period": per,
                    "n_days": int(len(df19)),
                    "ece_w20": round(ece_w20_cell, 6),
                    "ece_inw": round(ece_inw_cell, 6),
                    "bias_f": round(bias_mean, 4),
                    "crps_native": round(crps_nat_mean, 4),
                    "crps_clim": round(crps_clim_mean, 4),
                    "crpss": round(crpss_val, 4),
                    "cov90": round(cov90_mean, 4),
                    "tier_ece_w20": d1_w20,
                    "tier_ece_inw": d1_inw,
                    "tier_bias": d2,
                    "tier_crpss": d3,
                    "tier_cov90": d4,
                    "overall_w20": ov_w20,
                    "scale_w20": scale_w20,
                    "overall_inw": ov_inw,
                    "scale_inw": scale_inw,
                }
            )

            # Intraday loop across 29 half-hour slices
            y_settled_all = np.array([float(settle_half_up(float(yy))) for yy in y_arr], dtype=float)
            for hf_np in T_GRID:
                hf = float(hf_np)
                obs_slice = day_summaries[(st, hf)].reindex(dates_arr)
                mt_vec = obs_slice["mt"].to_numpy(dtype=float)
                xt_vec = obs_slice["xt"].to_numpy(dtype=float)
                tfin_vec = obs_slice["tfin_all"].to_numpy(dtype=float)

                # Gather vectorized per-day inputs
                valid_idx = [i for i in range(len(df19)) if not (np.isnan(mt_vec[i]) or np.isnan(xt_vec[i]))]
                n_v = len(valid_idx)
                m_int_v = np.empty(n_v, dtype=float)
                mt_v = np.empty(n_v, dtype=float)
                mu_r_v = np.empty(n_v, dtype=float)
                sr_v = np.empty(n_v, dtype=float)
                y_v = y_arr[valid_idx]
                ys_v = y_settled_all[valid_idx]
                tfin_v = tfin_vec[valid_idx]
                mu0_v = mu0_arr[valid_idx]
                s0_v = s0_arr[valid_idx]
                cnat_v = crps_nat_arr[valid_idx]
                cmm_v = crps_mm_arr[valid_idx]
                rnat_v = rps_nat_arr[valid_idx]

                for j, i in enumerate(valid_idx):
                    mt_f = float(mt_vec[i])
                    xt_f = float(xt_vec[i])
                    seas = seas_arr[i]
                    mu0 = float(mu0_arr[i])
                    s0 = float(s0_arr[i])
                    m_int = float(settle_half_up(mt_f))
                    eta = eta_map[(st, seas, hf)]
                    sr = max(s0 * math.sqrt(max(eta, 0.0)), SIGMA_INST_PHYSICAL_FLOOR)
                    res_mu = hook.compute(
                        t_local=hf,
                        extreme_m=m_int,
                        instant_x_t=xt_f,
                        mu_0=mu0,
                        target_type="max",
                        station_id=st,
                        season=seas,
                    )
                    m_int_v[j] = m_int
                    mt_v[j] = mt_f
                    mu_r_v[j] = res_mu.mu_r
                    sr_v[j] = sr

                cbr_v = bridge_crps_exact(y_v, m_int_v, mu_r_v, sr_v)
                cbr_rawmt_v = bridge_crps_exact(y_v, mt_v, mu_r_v, sr_v)

                sa = slice_acc[hf]
                sa["crps_nat"].append(cnat_v)
                sa["crps_br"].append(cbr_v)
                sa["mu_shift_vs_mu0"].append(m_int_v + mu_r_v - mu0_v)
                sa["sqrt_eta"].append(sr_v / np.maximum(s0_v, 1e-8))
                p_atom_v = special.ndtr(-mu_r_v / sr_v)
                sa["p_atom"].append(p_atom_v)
                sa["emp_atom_raw"].append((tfin_v <= mt_v + 1e-6).astype(float))
                sa["emp_atom_settle"].append((ys_v <= m_int_v + 1e-6).astype(float))

                # Evaluate discrete probabilities per day at slice hf
                for j, i in enumerate(valid_idx):
                    seas = seas_arr[i]
                    m_int = float(m_int_v[j])
                    mt_f = float(mt_v[j])
                    mu_r = float(mu_r_v[j])
                    sr = float(sr_v[j])
                    c0 = c0_list[i]
                    hv = hv_list[i]
                    yi = float(y_arr[i])
                    ysi = float(y_settled_all[i])
                    p_atom = float(p_atom_v[j])

                    lower = c0 - 9
                    edges = [lower + 2 * k for k in range(10)]
                    cdfs = np.array(
                        [0.0 if e <= m_int else float(special.ndtr(((e - m_int) - mu_r) / sr)) for e in edges],
                        dtype=float,
                    )
                    p_cond = np.empty(11, dtype=float)
                    p_cond[0] = cdfs[0]
                    p_cond[1:10] = np.maximum(0.0, cdfs[1:10] - cdfs[0:9])
                    p_cond[10] = max(0.0, 1.0 - cdfs[9])
                    ps = p_cond.sum()
                    if ps > 0:
                        p_cond /= ps

                    rps_br = float(np.sum((np.cumsum(p_cond) - np.cumsum(hv)) ** 2))
                    sc = strata_crps[(st, seas, per)]
                    sc["crps_nat"].append(float(cnat_v[j]))
                    sc["crps_br"].append(float(cbr_v[j]))
                    sc["crps_br_rawmt"].append(float(cbr_rawmt_v[j]))
                    sc["crps_mm"].append(float(cmm_v[j]))
                    sc["rps_nat"].append(float(rnat_v[j]))
                    sc["rps_br"].append(rps_br)

                    k_atom = bracket_hit_index(m_int, c0)
                    grp = np.empty(11, dtype=np.int8)
                    grp[:k_atom] = 0
                    grp[k_atom] = 1
                    if k_atom < 10:
                        grp[k_atom + 1 :] = 2

                    all_br_p.append(p_cond)
                    all_br_h.append(hv)
                    all_br_g.append(grp)
                    all_br_st.append(st)
                    all_br_seas.append(seas)
                    all_br_per.append(per)

                    sa["br_p"].append(p_cond); sa["br_h"].append(hv)
                    if st == "KORD":
                        sa["kord_p"].append(p_cond); sa["kord_h"].append(hv)
                    else:
                        sa["kmia_p"].append(p_cond); sa["kmia_h"].append(hv)
                        if seas == "Summer":
                            sa["kmia_sum_p"].append(p_cond); sa["kmia_sum_h"].append(hv)

                    bs = bin_sens[(st, seas, per)]
                    bs["fixed_p"].append(p_cond); bs["fixed_h"].append(hv)

                    # Variant A: Split-Atom 12-event binning (atom event + continuous tail events strictly disjoint)
                    # Atom event = {settled <= m_int} (also raw tfin <= mt_f)
                    # Continuous remainder inside atom bracket = (p_cond[k_atom] - p_atom) if >0
                    p_rem_in_k = max(0.0, float(p_cond[k_atom]) - p_atom)
                    hit_atom_set = 1.0 if ysi <= m_int + 1e-6 else 0.0
                    hit_atom_raw = 1.0 if tfin_v[j] <= mt_f + 1e-6 else 0.0
                    hit_rem_in_k = max(0.0, float(hv[k_atom]) - hit_atom_set)
                    hit_rem_raw = max(0.0, float(hv[k_atom]) - hit_atom_raw)
                    # Build event probability & hit vector: [atom] + [cont_rem_in_k?] + [k > k_atom]
                    sp_probs = [p_atom]
                    sp_hits_set = [hit_atom_set]
                    sp_hits_raw = [hit_atom_raw]
                    # Only include above/remainder continuous events with positive support (skip structural zero bins k < k_atom)
                    sp_probs.append(p_rem_in_k)
                    sp_hits_set.append(hit_rem_in_k)
                    sp_hits_raw.append(hit_rem_raw)
                    for kk in range(k_atom + 1, 11):
                        sp_probs.append(float(p_cond[kk]))
                        sp_hits_set.append(float(hv[kk]))
                        sp_hits_raw.append(float(hv[kk]))
                    bs["split_set_p"].append(np.array(sp_probs, dtype=float))
                    bs["split_set_h"].append(np.array(sp_hits_set, dtype=float))
                    bs["split_raw_p"].append(np.array(sp_probs, dtype=float))
                    bs["split_raw_h"].append(np.array(sp_hits_raw, dtype=float))

                    # Variant B: Anchor-aligned 2F grid starting cleanly at m_int:
                    # Event 0: exact atom {Y_settled == m_int} -> P = Phi(-mu_R / sigma_rem)
                    # Event 1..6: continuous upper half-open 2F intervals (m_int + 2*(r-1), m_int + 2*r] and open upper tail (m_int+10, inf)
                    anc_edges = [m_int + 2 * r for r in range(1, 6)]  # m+2, m+4, m+6, m+8, m+10
                    anc_cdfs = [float(special.ndtr(((e - m_int) - mu_r) / sr)) for e in anc_edges]
                    ap = np.empty(7, dtype=float)
                    ap[0] = p_atom
                    ap[1] = max(0.0, anc_cdfs[0] - p_atom)
                    for r in range(2, 6):
                        ap[r] = max(0.0, anc_cdfs[r - 1] - anc_cdfs[r - 2])
                    ap[6] = max(0.0, 1.0 - anc_cdfs[4])
                    aps = ap.sum()
                    if aps > 0:
                        ap /= aps
                    ah = np.zeros(7, dtype=float)
                    if ysi <= m_int + 1e-6:
                        ah[0] = 1.0
                    elif ysi > m_int + 10:
                        ah[6] = 1.0
                    else:
                        # (m_int + 2*(r-1), m_int + 2*r], e.g. m+1 or m+2 -> r=1
                        diff_s = ysi - m_int
                        r_idx = int(math.ceil(diff_s / 2.0))
                        r_idx = max(1, min(5, r_idx))
                        ah[r_idx] = 1.0
                    bs["anchor_set_p"].append(ap)
                    bs["anchor_set_h"].append(ah)

    # ---- Summarize Task 2(a): CRPS & RPS ----
    crps_16_rows: List[Dict[str, Any]] = []
    all_c_nat, all_c_br, all_c_br_raw, all_r_nat, all_r_br = [], [], [], [], []
    n_strata_crps_br_ge_nat = 0
    n_strata_rps_br_ge_nat = 0
    for st in AUTHORIZED_STATIONS:
        for seas in SEASONS:
            for per in ("early", "late"):
                sc = strata_crps[(st, seas, per)]
                cn = float(np.mean(sc["crps_nat"]))
                cb = float(np.mean(sc["crps_br"]))
                cbr_raw = float(np.mean(sc["crps_br_rawmt"]))
                cmm = float(np.mean(sc["crps_mm"]))
                rn = float(np.mean(sc["rps_nat"]))
                rb = float(np.mean(sc["rps_br"]))
                if cb >= cn:
                    n_strata_crps_br_ge_nat += 1
                if rb >= rn:
                    n_strata_rps_br_ge_nat += 1
                all_c_nat.extend(sc["crps_nat"])
                all_c_br.extend(sc["crps_br"])
                all_c_br_raw.extend(sc["crps_br_rawmt"])
                all_r_nat.extend(sc["rps_nat"])
                all_r_br.extend(sc["rps_br"])
                crps_16_rows.append(
                    {
                        "station": st,
                        "season": seas,
                        "period": per,
                        "n_evals": len(sc["crps_nat"]),
                        "crps_native": round(cn, 4),
                        "crps_mm_gauss": round(cmm, 4),
                        "crps_bridge": round(cb, 4),
                        "crps_bridge_raw_mt": round(cbr_raw, 4),
                        "diff_crps_br_minus_nat": round(cb - cn, 4),
                        "pct_change_crps": round(100.0 * (cb - cn) / cn, 2),
                        "bridge_better_crps": bool(cb < cn),
                        "rps11_native": round(rn, 5),
                        "rps11_bridge": round(rb, 5),
                        "diff_rps_br_minus_nat": round(rb - rn, 5),
                    }
                )
    pd.DataFrame(crps_16_rows).to_csv(OUT_CRPS_CSV, index=False)

    pooled_crps_nat = float(np.mean(all_c_nat))
    pooled_crps_br = float(np.mean(all_c_br))
    pooled_crps_br_raw = float(np.mean(all_c_br_raw))
    pooled_rps_nat = float(np.mean(all_r_nat))
    pooled_rps_br = float(np.mean(all_r_br))

    # ---- Summarize Task 2(b): 29 half-hour time-slice profile ----
    ts_rows: List[Dict[str, Any]] = []
    for h in T_GRID:
        hf = float(h)
        sa = slice_acc[hf]
        bp = np.concatenate(sa["br_p"]); bh = np.concatenate(sa["br_h"])
        kp = np.concatenate(sa["kord_p"]); kh = np.concatenate(sa["kord_h"])
        mp = np.concatenate(sa["kmia_p"]); mh = np.concatenate(sa["kmia_h"])
        msp = np.concatenate(sa["kmia_sum_p"]); msh = np.concatenate(sa["kmia_sum_h"])
        cn_s = float(np.mean(np.concatenate(sa["crps_nat"])))
        cb_s = float(np.mean(np.concatenate(sa["crps_br"])))
        mu_sh = float(np.mean(np.concatenate(sa["mu_shift_vs_mu0"])))
        sq_eta = float(np.mean(np.concatenate(sa["sqrt_eta"])))
        pat_m = float(np.mean(np.concatenate(sa["p_atom"])))
        emp_r = float(np.mean(np.concatenate(sa["emp_atom_raw"])))
        emp_s = float(np.mean(np.concatenate(sa["emp_atom_settle"])))
        ts_rows.append(
            {
                "t_hour": hf,
                "t_label": format_hour(hf),
                "ece_bridge_inw": round(compute_ece_inw(bp, bh), 6),
                "ece_bridge_w20": round(compute_ece_w20(bp, bh), 6),
                "ece_kord_inw": round(compute_ece_inw(kp, kh), 6),
                "ece_kmia_inw": round(compute_ece_inw(mp, mh), 6),
                "ece_kmia_summer_inw": round(compute_ece_inw(msp, msh), 6),
                "crps_native": round(cn_s, 4),
                "crps_bridge": round(cb_s, 4),
                "crps_diff": round(cb_s - cn_s, 4),
                "mean_implied_anchor_plus_mur_minus_mu0": round(mu_sh, 4),
                "mean_sqrt_eta": round(sq_eta, 4),
                "mean_p_atom": round(pat_m, 4),
                "emp_atom_raw": round(emp_r, 4),
                "emp_atom_settle": round(emp_s, 4),
                "atom_resid_raw": round(emp_r - pat_m, 4),
            }
        )
    ts_df = pd.DataFrame(ts_rows)
    ts_df.to_csv(OUT_TIMESLICE_CSV, index=False)

    # Extra deep inspection of 06:00-07:00 KMIA Summer construction fingerprint
    kmia_sum_06_diag: Dict[str, Any] = {}
    curve_ks = hook._resolve_curve("KMIA", "Summer")
    for hf in (6.0, 6.5, 7.0, 12.0, 14.0):
        eta_ks = eta_map[("KMIA", "Summer", hf)]
        rho_ks, _ = eval_piecewise_linear_and_deriv(hf, np.array(curve_ks["rho_knots"], dtype=float), np.array(curve_ks["rho_values"], dtype=float))
        row_s = ts_df[ts_df["t_hour"] == hf].iloc[0]
        # Compute KMIA Summer specific p_atom vs emp & implied mean bias at 18h
        df_ks18 = build_2019_cell_priors("KMIA", 18, manifest_models, climate_calib, contract_cells)
        df_ks18 = df_ks18[(df_ks18["season"] == "Summer") & (df_ks18["target_date"].isin(set(iem_2019["KMIA"]["local_date"].unique())))].copy()
        agg_ks = day_summaries[("KMIA", hf)].reindex(df_ks18["target_date"].tolist())
        df_ks18["mt"] = agg_ks["mt"].to_numpy(dtype=float)
        df_ks18["xt"] = agg_ks["xt"].to_numpy(dtype=float)
        df_ks18["tfin"] = agg_ks["tfin_all"].to_numpy(dtype=float)
        df_ks18 = df_ks18.dropna(subset=["mt", "xt"])
        m_ints = np.array([float(settle_half_up(float(x))) for x in df_ks18["mt"]])
        mu_rs = np.array([
            hook.compute(hf, float(m_ints[k]), float(df_ks18["xt"].iloc[k]), float(df_ks18["mu_0"].iloc[k]), "max", "KMIA", "Summer").mu_r
            for k in range(len(df_ks18))
        ])
        srs = np.maximum(df_ks18["sigma_0"].to_numpy(dtype=float) * math.sqrt(max(eta_ks, 0.0)), SIGMA_INST_PHYSICAL_FLOOR)
        # Expected truncated Gaussian mean: m_int + mu_r*Phi(mu_r/sr) + sr*phi(mu_r/sr)
        u = mu_rs / srs
        e_bridge = m_ints + mu_rs * special.ndtr(u) + srs * np.exp(-0.5 * u * u) / math.sqrt(2.0 * math.pi)
        # Expected native JSU mean:
        _, sp_ks, ez_ks, _ = moment_map[("KMIA", "Summer")]
        e_native = df_ks18["mu_0"].to_numpy(dtype=float) + df_ks18["sigma_0"].to_numpy(dtype=float) * ez_ks
        # Implied std of rectified normal: Var = E[(W+)^2] - (E[W+])^2
        # E[(W+)^2] = (mu_r^2 + sr^2)*Phi(u) + mu_r*sr*phi(u)
        e_w2 = (mu_rs**2 + srs**2) * special.ndtr(u) + mu_rs * srs * np.exp(-0.5 * u * u) / math.sqrt(2.0 * math.pi)
        e_w1 = mu_rs * special.ndtr(u) + srs * np.exp(-0.5 * u * u) / math.sqrt(2.0 * math.pi)
        std_bridge = np.sqrt(np.maximum(0.0, e_w2 - e_w1**2))
        real_err = df_ks18["tmax_f"].to_numpy(dtype=float) - e_bridge
        kmia_sum_06_diag[format_hour(hf)] = {
            "eta_calibrated": round(eta_ks, 6),
            "sqrt_eta": round(math.sqrt(eta_ks), 6),
            "rho_calibrated": round(rho_ks, 6),
            "ece_kmia_summer_inw": float(row_s["ece_kmia_summer_inw"]),
            "mean_e_bridge_minus_e_native_f": round(float(np.mean(e_bridge - e_native)), 4),
            "mean_bridge_bias_y_minus_ebridge_f": round(float(np.mean(real_err)), 4),
            "mean_std_bridge_over_sigma0": round(float(np.mean(std_bridge / df_ks18["sigma_0"].to_numpy(dtype=float))), 4),
            "empirical_std_resid_over_mean_std_bridge": round(float(np.std(real_err, ddof=1) / max(1e-8, float(np.mean(std_bridge)))), 4),
            "mean_m_int_minus_mu0_f": round(float(np.mean(m_ints - df_ks18["mu_0"].to_numpy(dtype=float))), 4),
            "mean_mu_r_f": round(float(np.mean(mu_rs)), 4),
        }

    # ---- Summarize Task 2(c): Exact Atom vs Continuous Tail Decomposition ----
    p_flat = np.concatenate(all_br_p)
    h_flat = np.concatenate(all_br_h)
    g_flat = np.concatenate(all_br_g)
    decomp_inw = compute_additive_ece_decomp_inw(p_flat, h_flat, g_flat)
    decomp_w20 = compute_additive_ece_decomp_w20(p_flat, h_flat, g_flat)

    # Also decompose early (06:00-13:30) vs afternoon (14:00-20:00) using time slice split
    all_br_early_p, all_br_early_h, all_br_early_g = [], [], []
    all_br_aft_p, all_br_aft_h, all_br_aft_g = [], [], []
    # Re-use slice lengths: all_br_p pushed in outer loop st/lead/hf/j -> let's track cleanly via fast recomputation?
    # Actually we already have all_br_st/seas/per aligned by eval; let's check KMIA Summer group decomp cleanly:
    st_arr = np.repeat(np.array(all_br_st), 11)
    seas_arr_rep = np.repeat(np.array(all_br_seas), 11)
    km_sum_mask = (st_arr == "KMIA") & (seas_arr_rep == "Summer")
    decomp_kmia_sum_inw = compute_additive_ece_decomp_inw(p_flat[km_sum_mask], h_flat[km_sum_mask], g_flat[km_sum_mask])

    # ---- Summarize Task 2(d): Binning Sensitivity ----
    pool_nat_p = np.concatenate([np.concatenate(bin_sens[(st, s, p)]["nat_p"]) for st in AUTHORIZED_STATIONS for s in SEASONS for p in ("early", "late")])
    pool_nat_h = np.concatenate([np.concatenate(bin_sens[(st, s, p)]["nat_h"]) for st in AUTHORIZED_STATIONS for s in SEASONS for p in ("early", "late")])
    pool_fix_p = np.concatenate([np.concatenate(bin_sens[(st, s, p)]["fixed_p"]) for st in AUTHORIZED_STATIONS for s in SEASONS for p in ("early", "late")])
    pool_fix_h = np.concatenate([np.concatenate(bin_sens[(st, s, p)]["fixed_h"]) for st in AUTHORIZED_STATIONS for s in SEASONS for p in ("early", "late")])
    pool_sps_p = np.concatenate([np.concatenate(bin_sens[(st, s, p)]["split_set_p"]) for st in AUTHORIZED_STATIONS for s in SEASONS for p in ("early", "late")])
    pool_sps_h = np.concatenate([np.concatenate(bin_sens[(st, s, p)]["split_set_h"]) for st in AUTHORIZED_STATIONS for s in SEASONS for p in ("early", "late")])
    pool_spr_p = np.concatenate([np.concatenate(bin_sens[(st, s, p)]["split_raw_p"]) for st in AUTHORIZED_STATIONS for s in SEASONS for p in ("early", "late")])
    pool_spr_h = np.concatenate([np.concatenate(bin_sens[(st, s, p)]["split_raw_h"]) for st in AUTHORIZED_STATIONS for s in SEASONS for p in ("early", "late")])
    pool_anc_p = np.concatenate([np.concatenate(bin_sens[(st, s, p)]["anchor_set_p"]) for st in AUTHORIZED_STATIONS for s in SEASONS for p in ("early", "late")])
    pool_anc_h = np.concatenate([np.concatenate(bin_sens[(st, s, p)]["anchor_set_h"]) for st in AUTHORIZED_STATIONS for s in SEASONS for p in ("early", "late")])

    ece_nat_inw_p = compute_ece_inw(pool_nat_p, pool_nat_h)
    ece_fix_inw_p = compute_ece_inw(pool_fix_p, pool_fix_h)
    ece_sps_inw_p = compute_ece_inw(pool_sps_p, pool_sps_h)
    ece_spr_inw_p = compute_ece_inw(pool_spr_p, pool_spr_h)
    ece_anc_inw_p = compute_ece_inw(pool_anc_p, pool_anc_h)

    ece_nat_w20_p = compute_ece_w20(pool_nat_p, pool_nat_h)
    ece_fix_w20_p = compute_ece_w20(pool_fix_p, pool_fix_h)
    ece_sps_w20_p = compute_ece_w20(pool_sps_p, pool_sps_h)
    ece_spr_w20_p = compute_ece_w20(pool_spr_p, pool_spr_h)
    ece_anc_w20_p = compute_ece_w20(pool_anc_p, pool_anc_h)

    d_fix_inw = ece_fix_inw_p - ece_nat_inw_p
    d_sps_inw = ece_sps_inw_p - ece_nat_inw_p
    d_spr_inw = ece_spr_inw_p - ece_nat_inw_p
    d_anc_inw = ece_anc_inw_p - ece_nat_inw_p

    d_fix_w20 = ece_fix_w20_p - ece_nat_w20_p
    d_sps_w20 = ece_sps_w20_p - ece_nat_w20_p
    d_anc_w20 = ece_anc_w20_p - ece_nat_w20_p

    bin_sens_summary = {
        "inw": {
            "ece_native": round(ece_nat_inw_p, 6),
            "ece_bridge_fixed_2f": round(ece_fix_inw_p, 6),
            "delta_fixed_2f": round(d_fix_inw, 6),
            "ece_bridge_split_atom_settled": round(ece_sps_inw_p, 6),
            "delta_split_atom_settled": round(d_sps_inw, 6),
            "pct_delta_explained_by_split_settled": round(100.0 * (d_fix_inw - d_sps_inw) / max(d_fix_inw, 1e-12), 2),
            "ece_bridge_split_atom_raw": round(ece_spr_inw_p, 6),
            "delta_split_atom_raw": round(d_spr_inw, 6),
            "pct_delta_explained_by_split_raw": round(100.0 * (d_fix_inw - d_spr_inw) / max(d_fix_inw, 1e-12), 2),
            "ece_bridge_anchor_aligned_2f": round(ece_anc_inw_p, 6),
            "delta_anchor_aligned_2f": round(d_anc_inw, 6),
            "pct_delta_explained_by_anchor_aligned": round(100.0 * (d_fix_inw - d_anc_inw) / max(d_fix_inw, 1e-12), 2),
        },
        "w20": {
            "ece_native": round(ece_nat_w20_p, 6),
            "ece_bridge_fixed_2f": round(ece_fix_w20_p, 6),
            "delta_fixed_2f": round(d_fix_w20, 6),
            "ece_bridge_split_atom_settled": round(ece_sps_w20_p, 6),
            "delta_split_atom_settled": round(d_sps_w20, 6),
            "pct_delta_explained_by_split_settled": round(100.0 * (d_fix_w20 - d_sps_w20) / max(d_fix_w20, 1e-12), 2),
            "ece_bridge_anchor_aligned_2f": round(ece_anc_w20_p, 6),
            "delta_anchor_aligned_2f": round(d_anc_w20, 6),
            "pct_delta_explained_by_anchor_aligned": round(100.0 * (d_fix_w20 - d_anc_w20) / max(d_fix_w20, 1e-12), 2),
        },
    }

    # ---- Task 3: OOS Degradation Attribution (608-day vs 2019) ----
    # 3.1 Load 608-day calibration residuals & 2019 18h atom CSV for exact bucket comparison
    cal608_res = pd.read_csv(PROJECT_ROOT / "evidence" / "p8_mu_r_rho_released_residuals_full_20261114.csv")
    oos19_res = pd.read_csv(PROJECT_ROOT / "evidence" / "p8_inspection_c_2019_atom_696_20261114.csv")
    comp = pd.merge(
        cal608_res,
        oos19_res,
        on=["station", "season", "t_hour", "t_label", "pos_bucket"],
        suffixes=("_608", "_2019"),
    )
    comp["d_emp"] = comp["emp_no_new_raw_2019"] - comp["emp_no_new_raw_608"]
    comp["d_pred"] = comp["pred_after_2019"] - comp["pred_after_608"]

    attr_bucket_rows: List[Dict[str, Any]] = []
    for half_name, mask_h in [("06:00-13:30", comp["t_hour"] <= 13.5), ("14:00-20:00", comp["t_hour"] >= 14.0)]:
        for pb in POSITION_BUCKETS:
            sub = comp[mask_h & (comp["pos_bucket"] == pb)]
            w19 = sub["n_bucket_2019"].to_numpy(dtype=float)
            w608 = sub["n_bucket_608"].to_numpy(dtype=float)
            emp608 = float(np.average(sub["emp_no_new_raw_608"], weights=w608))
            pred608 = float(np.average(sub["pred_after_608"], weights=w608))
            emp19 = float(np.average(sub["emp_no_new_raw_2019"], weights=w19))
            pred19 = float(np.average(sub["pred_after_2019"], weights=w19))
            attr_bucket_rows.append(
                {
                    "half": half_name,
                    "pos_bucket": pb,
                    "n_obs_608": int(w608.sum()),
                    "n_obs_2019": int(w19.sum()),
                    "emp_608": round(emp608, 4),
                    "pred_608": round(pred608, 4),
                    "resid_608": round(emp608 - pred608, 4),
                    "emp_2019": round(emp19, 4),
                    "pred_2019": round(pred19, 4),
                    "resid_2019": round(emp19 - pred19, 4),
                    "emp_shift_2019_minus_608": round(emp19 - emp608, 4),
                    "pred_shift_2019_minus_608": round(pred19 - pred608, 4),
                    "out95_2019": int(sub["outside_ci_after_2019"].sum()),
                    "frac_neg_resid_2019": round(float(np.mean(sub["resid_after_2019"] < 0)), 4),
                }
            )

    # Check KORD Spring & Autumn afternoon empirical shift vs pred shift
    kord_sa_shift: Dict[str, Any] = {}
    for seas in ("Spring", "Autumn"):
        sub = comp[(comp["station"] == "KORD") & (comp["season"] == seas) & (comp["t_hour"] >= 14.0)]
        w19 = sub["n_bucket_2019"].to_numpy(dtype=float)
        w608 = sub["n_bucket_608"].to_numpy(dtype=float)
        emp608 = float(np.average(sub["emp_no_new_raw_608"], weights=w608))
        pred608 = float(np.average(sub["pred_after_608"], weights=w608))
        emp19 = float(np.average(sub["emp_no_new_raw_2019"], weights=w19))
        pred19 = float(np.average(sub["pred_after_2019"], weights=w19))
        kord_sa_shift[seas] = {
            "emp_608": round(emp608, 4),
            "pred_608": round(pred608, 4),
            "emp_2019": round(emp19, 4),
            "pred_2019": round(pred19, 4),
            "emp_shift": round(emp19 - emp608, 4),
            "pred_shift": round(pred19 - pred608, 4),
            "out95_608": int(sub["outside_ci_after_608"].sum()),
            "out95_2019": int(sub["outside_ci_after_2019"].sum()),
        }

    # 3.2 & 3.3 Direct 5-min climate & cooling intensity audit: 2016, 2017, 2018 (608-day pool) vs 2019
    climate_regime_rows: List[Dict[str, Any]] = []
    kord_spring_yearly_rows: List[Dict[str, Any]] = []

    for st in AUTHORIZED_STATIONS:
        obs_pre, _ = load_clean_pre2019_5min(st)
        obs_19 = iem_2019[st]
        obs_all = pd.concat([obs_pre, obs_19], ignore_index=True)
        obs_all["year"] = pd.to_datetime(obs_all["local_date"]).dt.year
        obs_all["season"] = [get_season(str(d)) for d in obs_all["local_date"]]

        # Load 18h priors (2016..2019) from train_arrays + build_2019_cell_priors
        train_arr = pd.read_parquet(PROJECT_ROOT / "data" / "processed" / "audit_arrays" / "2000_2018_training_arrays.parquet")
        ta_st = train_arr[(train_arr["station"] == st) & (train_arr["year"].isin(PRE2019_YEARS))].copy()
        ta_st["local_date"] = pd.to_datetime(ta_st["date"]).dt.date
        ta_st["mu_0"] = ta_st["mu_forecast"].astype(float)
        df19_18 = build_2019_cell_priors(st, 18, manifest_models, climate_calib, contract_cells)
        df19_18["local_date"] = df19_18["target_date"]
        priors_16_19 = pd.concat([ta_st[["local_date", "mu_0"]], df19_18[["local_date", "mu_0"]]], ignore_index=True).drop_duplicates("local_date").set_index("local_date")

        # Per-day stats
        day_tfin = obs_all.groupby("local_date")["temp_f"].max()
        day_meta = obs_all.groupby("local_date").agg(year=("year", "first"), season=("season", "first"))
        # Peak hour (first occurrence of daily max in daytime 00:00-23:59)
        idx_max = obs_all.groupby("local_date")["temp_f"].idxmax()
        peak_hr = obs_all.loc[idx_max].set_index("local_date")["hour_f"]
        day_meta["tfin"] = day_tfin
        day_meta["peak_hour"] = peak_hr
        day_meta["mu_0"] = priors_16_19["mu_0"]

        # Running max at 13:30, 14:00, and afternoon mean cooling drop 14:00-20:00
        m_at_14 = obs_all[obs_all["hour_f"] <= 14.0].groupby("local_date")["temp_f"].max()
        x_at_14 = obs_all[obs_all["hour_f"] <= 14.0].sort_values("local_dt").groupby("local_date")["temp_f"].last()
        m_at_1330 = obs_all[obs_all["hour_f"] <= 13.5].groupby("local_date")["temp_f"].max()
        x_at_1330 = obs_all[obs_all["hour_f"] <= 13.5].sort_values("local_dt").groupby("local_date")["temp_f"].last()
        day_meta["m_14"] = m_at_14
        day_meta["drop_14"] = np.maximum(0.0, m_at_14 - x_at_14)
        day_meta["post14_rise"] = np.maximum(0.0, day_meta["tfin"] - m_at_14)
        day_meta["post14_new_high"] = (day_meta["tfin"] > m_at_14 + 1e-6).astype(float)
        day_meta["early_drop_ge2"] = ((m_at_1330 - x_at_1330) >= 2.0).astype(float)
        day_meta["below_anchor_14"] = (day_meta["m_14"] < day_meta["mu_0"] - 2.0).astype(float)
        day_meta["deficit_14"] = day_meta["mu_0"] - day_meta["m_14"]

        # Mean afternoon cooling drop averaged across 14:00..20:00 slices
        aft_drops_per_day = []
        for hf in T_GRID:
            if float(hf) < 14.0:
                continue
            sh = obs_all[obs_all["hour_f"] <= float(hf) + 1e-9].sort_values("local_dt")
            gg = sh.groupby("local_date")["temp_f"].agg(mt="max", xt="last")
            aft_drops_per_day.append((gg["mt"] - gg["xt"]).rename(f"h_{hf}"))
        aft_df = pd.concat(aft_drops_per_day, axis=1)
        day_meta["mean_aft_drop"] = aft_df.mean(axis=1)

        # Seasonal climate trend 2016-2018 vs 2019
        for seas in list(SEASONS) + ["ALL"]:
            sub_dm = day_meta if seas == "ALL" else day_meta[day_meta["season"] == seas]
            pre_dm = sub_dm[sub_dm["year"].isin([2016, 2017, 2018])].dropna(subset=["tfin", "mean_aft_drop", "post14_rise"])
            y19_dm = sub_dm[sub_dm["year"] == 2019].dropna(subset=["tfin", "mean_aft_drop", "post14_rise"])
            climate_regime_rows.append(
                {
                    "station": st,
                    "season": seas,
                    "n_2016_18": int(len(pre_dm)),
                    "n_2019": int(len(y19_dm)),
                    "mean_tmax_16_18": round(float(pre_dm["tfin"].mean()), 2),
                    "mean_tmax_2019": round(float(y19_dm["tfin"].mean()), 2),
                    "tmax_diff_19_minus_16_18": round(float(y19_dm["tfin"].mean() - pre_dm["tfin"].mean()), 2),
                    "aft_drop_16_18": round(float(pre_dm["mean_aft_drop"].mean()), 3),
                    "aft_drop_2019": round(float(y19_dm["mean_aft_drop"].mean()), 3),
                    "aft_drop_diff": round(float(y19_dm["mean_aft_drop"].mean() - pre_dm["mean_aft_drop"].mean()), 3),
                    "post14_rise_16_18": round(float(pre_dm["post14_rise"].mean()), 3),
                    "post14_rise_2019": round(float(y19_dm["post14_rise"].mean()), 3),
                    "post14_newhigh_rate_16_18": round(float(pre_dm["post14_new_high"].mean()), 4),
                    "post14_newhigh_rate_2019": round(float(y19_dm["post14_new_high"].mean()), 4),
                    "mean_peak_hr_16_18": round(float(pre_dm["peak_hour"].mean()), 2),
                    "mean_peak_hr_2019": round(float(y19_dm["peak_hour"].mean()), 2),
                }
            )

        # KORD Spring yearly breakdown (2016, 2017, 2018, 2016-2018 vs 2019)
        if st == "KORD":
            sp_dm = day_meta[day_meta["season"] == "Spring"].dropna(subset=["tfin", "mu_0", "m_14", "mean_aft_drop"])
            for label, yr_filter in [("2016 (May)", [2016]), ("2017", [2017]), ("2018", [2018]), ("2016-2018 pooled", [2016, 2017, 2018]), ("2019 OOS", [2019])]:
                sub_y = sp_dm[sp_dm["year"].isin(yr_filter)]
                if len(sub_y) == 0:
                    continue
                b23 = sub_y[(sub_y["m_14"] - sub_y["mu_0"]) >= -2.0]
                kord_spring_yearly_rows.append(
                    {
                        "cohort": label,
                        "n_days": int(len(sub_y)),
                        "mean_tmax_f": round(float(sub_y["tfin"].mean()), 2),
                        "mean_mu0_f": round(float(sub_y["mu_0"].mean()), 2),
                        "below_anchor_14_rate": round(float(sub_y["below_anchor_14"].mean()), 4),
                        "drop_ge2_at_14_rate": round(float((sub_y["drop_14"] >= 2.0).mean()), 4),
                        "mean_aft_drop_f": round(float(sub_y["mean_aft_drop"].mean()), 3),
                        "post14_newhigh_rate_all": round(float(sub_y["post14_new_high"].mean()), 4),
                        "post14_newhigh_rate_B2B3": round(float(b23["post14_new_high"].mean()), 4) if len(b23) else None,
                        "n_B2B3": int(len(b23)),
                        "post14_rise_f": round(float(sub_y["post14_rise"].mean()), 3),
                        "mean_peak_hr": round(float(sub_y["peak_hour"].mean()), 2),
                    }
                )

    # Save W2 22-cell scorecard CSV
    w2_df = pd.DataFrame(w2_cell_rows)
    w2_df.to_csv(OUT_W2_CSV, index=False)

    # ---- Pre-Registered Rules 1 / 2 / 3 Boolean Evaluation (strictly in code) ----
    rule1_pooled_crps_worse = bool(pooled_crps_br >= pooled_crps_nat)
    rule1_strata_ge_12 = bool(n_strata_crps_br_ge_nat >= 12)
    rule1_triggered = bool(rule1_pooled_crps_worse and rule1_strata_ge_12)

    pct_explained_inw = float(bin_sens_summary["inw"]["pct_delta_explained_by_split_settled"])
    pct_explained_anc_inw = float(bin_sens_summary["inw"]["pct_delta_explained_by_anchor_aligned"])
    early_06_ece = float(ts_df[ts_df["t_hour"] == 6.0]["ece_bridge_inw"].iloc[0])
    early_kmia_sum_06_ece = float(ts_df[ts_df["t_hour"] == 6.0]["ece_kmia_summer_inw"].iloc[0])
    rule2_binning_gt_50 = bool(pct_explained_inw > 50.0 or pct_explained_anc_inw > 50.0)
    rule2_early_anomaly = bool(early_kmia_sum_06_ece > 0.05 or early_06_ece > 0.03)
    rule2_triggered = bool(rule2_binning_gt_50 or rule2_early_anomaly)

    aft_2019_out95 = int(oos19_res[oos19_res["t_hour"] >= 14.0]["outside_ci_after"].sum())
    aft_2019_total = int(len(oos19_res[oos19_res["t_hour"] >= 14.0]))
    rule3_atom_out95_gt_25 = bool(aft_2019_out95 > 25)
    rule3_triggered = bool((not rule1_triggered) and rule3_atom_out95_gt_25)

    rules_eval = {
        "rule1_value_check": {
            "pooled_crps_native": round(pooled_crps_nat, 4),
            "pooled_crps_bridge": round(pooled_crps_br, 4),
            "pooled_crps_bridge_raw_mt": round(pooled_crps_br_raw, 4),
            "pooled_crps_bridge_ge_native": rule1_pooled_crps_worse,
            "strata_crps_bridge_ge_native_count": int(n_strata_crps_br_ge_nat),
            "strata_total": 16,
            "pooled_rps11_native": round(pooled_rps_nat, 5),
            "pooled_rps11_bridge": round(pooled_rps_br, 5),
            "strata_rps11_bridge_ge_native_count": int(n_strata_rps_br_ge_nat),
            "rule1_crps_condition_met": rule1_triggered,
        },
        "rule2_construction_check": {
            "ece_0600_pooled_inw": early_06_ece,
            "ece_0600_kmia_summer_inw": early_kmia_sum_06_ece,
            "pct_delta_explained_split_atom_settled_inw": pct_explained_inw,
            "pct_delta_explained_anchor_aligned_inw": pct_explained_anc_inw,
            "rule2_binning_gt_50_pct": rule2_binning_gt_50,
            "rule2_early_anomaly": rule2_early_anomaly,
            "rule2_triggered": rule2_triggered,
        },
        "rule3_real_oos_degradation_check": {
            "aft_2019_out95": aft_2019_out95,
            "aft_2019_total": aft_2019_total,
            "threshold": 25,
            "bridge_has_crps_value": bool(not rule1_triggered),
            "rule3_out95_gt_25": rule3_atom_out95_gt_25,
            "rule3_triggered": rule3_triggered,
        },
    }

    w2_counts_w20 = w2_df["overall_w20"].value_counts().to_dict()
    w2_counts_inw = w2_df["overall_inw"].value_counts().to_dict()

    payload = {
        "schema_version": "p8_inspection_c_diagnostics_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "formula_verification": crps_formula_checks,
        "rules_eval": rules_eval,
        "task2a_crps_pooled": {
            "crps_native": round(pooled_crps_nat, 4),
            "crps_bridge": round(pooled_crps_br, 4),
            "crps_bridge_raw_mt": round(pooled_crps_br_raw, 4),
            "rps11_native": round(pooled_rps_nat, 5),
            "rps11_bridge": round(pooled_rps_br, 5),
        },
        "task2a_crps_16strata": crps_16_rows,
        "task2b_kmia_summer_early_diagnosis": kmia_sum_06_diag,
        "task2c_additive_decomp_inw": decomp_inw,
        "task2c_additive_decomp_w20": decomp_w20,
        "task2c_kmia_summer_decomp_inw": decomp_kmia_sum_inw,
        "task2d_binning_sensitivity": bin_sens_summary,
        "task3_bucket_attribution": attr_bucket_rows,
        "task3_kord_spring_autumn_shift": kord_sa_shift,
        "task3_kord_spring_yearly": kord_spring_yearly_rows,
        "task3_climate_regime": climate_regime_rows,
        "task4_w2_tier_counts_w20": w2_counts_w20,
        "task4_w2_tier_counts_inw": w2_counts_inw,
        "task4_w2_22cells": w2_cell_rows,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # Build clean Markdown diagnostic report
    lines: List[str] = [
        "# P8-ALGO 检验 C 判决诊断报告（规则一/二/三与 W2 22 格体检）",
        "",
        f"- **执行日期**: `2026-11-14` | **CRPS 闭式公式核验误差 vs quad**: `bridge={crps_formula_checks['max_bridge_crps_err_vs_quad']:.2e}`, `JSU={crps_formula_checks['max_jsu_crps_err_vs_quad']:.2e}`",
        "",
        "## 一、 预注册判据规则一/二/三代码计算结果",
        "",
        f"- **规则一（信息价值 CRPS）**: `CRPS_native = {pooled_crps_nat:.4f}°F` vs `CRPS_bridge = {pooled_crps_br:.4f}°F`（raw $M_t$: `{pooled_crps_br_raw:.4f}°F`），`16 层中 bridge 劣于或等于 native 层数 = {n_strata_crps_br_ge_nat}/16`；11 档离散 RPS：`RPS_native = {pooled_rps_nat:.5f}` vs `RPS_bridge = {pooled_rps_br:.5f}`（`{n_strata_rps_br_ge_nat}/16` 层劣）；`rule1_crps_condition_met = {rule1_triggered}`",
        f"- **规则二（构造/分箱缺陷）**: `06:00 ECE_bridge(inw) = {early_06_ece:.6f}`（`KMIA Summer 06:00 = {early_kmia_sum_06_ece:.6f}`）；原子单列（Split-Atom 12-Event）解释 `Δ_bridge(inw)` 比例 = `{pct_explained_inw:.2f}%`，锚点对齐（Anchor-Aligned 2°F）解释比例 = `{pct_explained_anc_inw:.2f}%`；`rule2_binning_gt_50_pct = {rule2_binning_gt_50}`, `rule2_early_anomaly = {rule2_early_anomaly}`, `rule2_triggered = {rule2_triggered}`",
        f"- **规则三（OOS 真实降质）**: `aft_2019_out95 = {aft_2019_out95}/{aft_2019_total}` vs 阈值 `25`，`bridge_has_crps_value = {not rule1_triggered}`，`rule3_triggered = {rule3_triggered}`",
        "",
        "## 二、 任务二 a｜CRPS & 离散 11 档 RPS 对照（全池 + 16 层）",
        "",
        "| 站 | 季 | 段 | n_evals | CRPS_native | CRPS_mm_gauss | CRPS_bridge | `ΔCRPS(br-nat)` | 改善率 | `bridge < native` | RPS11_nat | RPS11_br |",
        "|:---|:---|:---|---:|---:|---:|---:|---:|---:|:---:|---:|---:|",
    ]
    for r in crps_16_rows:
        lines.append(
            f"| {r['station']} | {r['season']} | {r['period']} | {r['n_evals']} | {r['crps_native']:.4f} | {r['crps_mm_gauss']:.4f} | {r['crps_bridge']:.4f} | {r['diff_crps_br_minus_nat']:+.4f} | {r['pct_change_crps']:+.2f}% | `{r['bridge_better_crps']}` | {r['rps11_native']:.5f} | {r['rps11_bridge']:.5f} |"
        )
    lines.extend(
        [
            "",
            "## 三、 任务二 b｜06:00–20:00 逐半时剖面（含 `06:00–07:00` 构造诊断）",
            "",
            "| 时分 | ECE_bridge (inw) | ECE_bridge (w20) | KORD (inw) | KMIA (inw) | KMIA Summer (inw) | CRPS_nat | CRPS_br | `m_int+mu_R-mu0` | `sqrt(η)` | p_atom | emp_atom_raw |",
            "|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for r in ts_rows:
        lines.append(
            f"| {r['t_label']} | {r['ece_bridge_inw']:.6f} | {r['ece_bridge_w20']:.6f} | {r['ece_kord_inw']:.6f} | {r['ece_kmia_inw']:.6f} | {r['ece_kmia_summer_inw']:.6f} | {r['crps_native']:.4f} | {r['crps_bridge']:.4f} | {r['mean_implied_anchor_plus_mur_minus_mu0']:+.4f} | {r['mean_sqrt_eta']:.4f} | {r['mean_p_atom']:.4f} | {r['emp_atom_raw']:.4f} |"
        )
    lines.extend(
        [
            "",
            "### KMIA Summer 重点切片（06:00–07:00 vs 12:00 / 14:00）构造指纹：",
            "",
            "| 时分 | `η_s(t)` | `√η_s(t)` | `ρ_s,se(t)` | `ECE_inw` | `E[Y_br]-E[Y_nat]` | 实测 `y - E[Y_br]` | `std_br / σ_0` | 实测残差std / `std_br` | `m_int - μ₀` | `μ_R` |",
            "|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for lbl, d in kmia_sum_06_diag.items():
        lines.append(
            f"| {lbl} | {d['eta_calibrated']:.4f} | {d['sqrt_eta']:.4f} | {d['rho_calibrated']:+.4f} | {d['ece_kmia_summer_inw']:.6f} | {d['mean_e_bridge_minus_e_native_f']:+.4f} | {d['mean_bridge_bias_y_minus_ebridge_f']:+.4f} | {d['mean_std_bridge_over_sigma0']:.4f} | {d['empirical_std_resid_over_mean_std_bridge']:.4f} | {d['mean_m_int_minus_mu0_f']:+.4f} | {d['mean_mu_r_f']:+.4f} |"
        )
    lines.extend(
        [
            "",
            "## 四、 任务二 c & d｜原子/连续加性分解与分箱敏感性",
            "",
            f"- **全池 `inw` 加性分解 (`ECE_bridge = {decomp_inw['ece_total']:.6f}`)**: 下侧归零档 `{decomp_inw['contrib_below']:+.6f}` (`{decomp_inw['share_below_pct']:.2f}%`, 样本占比 `{decomp_inw['n_below']}`)、**原子所属档 `{decomp_inw['contrib_atom']:+.6f}` (`{decomp_inw['share_atom_pct']:.2f}%`, 样本 `{decomp_inw['n_atom']}`, 独立 ECE `{decomp_inw['standalone_ece_atom']:.6f}`)**、**纯上尾连续档 `{decomp_inw['contrib_above']:+.6f}` (`{decomp_inw['share_above_pct']:.2f}%`, 样本 `{decomp_inw['n_above']}`, 独立 ECE `{decomp_inw['standalone_ece_above']:.6f}`)**",
            f"- **全池 `w20` 加性分解 (`ECE_bridge = {decomp_w20['ece_total']:.6f}`)**: 下侧 `{decomp_w20['contrib_below']:+.6f}` (`{decomp_w20['share_below_pct']:.2f}%`)、原子所属档 `{decomp_w20['contrib_atom']:+.6f}` (`{decomp_w20['share_atom_pct']:.2f}%`)、纯上尾连续档 `{decomp_w20['contrib_above']:+.6f}` (`{decomp_w20['share_above_pct']:.2f}%`)",
            f"- **KMIA Summer `inw` 加性分解 (`ECE_bridge = {decomp_kmia_sum_inw['ece_total']:.6f}`)**: 下侧 `{decomp_kmia_sum_inw['share_below_pct']:.2f}%`、原子所属档 `{decomp_kmia_sum_inw['share_atom_pct']:.2f}%` (`standalone={decomp_kmia_sum_inw['standalone_ece_atom']:.6f}`)、纯上尾连续档 `{decomp_kmia_sum_inw['share_above_pct']:.2f}%` (`standalone={decomp_kmia_sum_inw['standalone_ece_above']:.6f}`)",
            f"- **分箱敏感性 (`inw`)**: 现行 2°F 固定框 `ECE_bridge = {bin_sens_summary['inw']['ece_bridge_fixed_2f']:.6f}` (`Δ={bin_sens_summary['inw']['delta_fixed_2f']:+.6f}`) → 原子单列 12 事件（settled `m_int`）`{bin_sens_summary['inw']['ece_bridge_split_atom_settled']:.6f}` (`Δ={bin_sens_summary['inw']['delta_split_atom_settled']:+.6f}`, 解释 `{bin_sens_summary['inw']['pct_delta_explained_by_split_settled']:.2f}%`) / raw $M_t$ `{bin_sens_summary['inw']['ece_bridge_split_atom_raw']:.6f}` (解释 `{bin_sens_summary['inw']['pct_delta_explained_by_split_raw']:.2f}%`) → 锚点对齐 2°F 框 `{bin_sens_summary['inw']['ece_bridge_anchor_aligned_2f']:.6f}` (`Δ={bin_sens_summary['inw']['delta_anchor_aligned_2f']:+.6f}`, 解释 `{bin_sens_summary['inw']['pct_delta_explained_by_anchor_aligned']:.2f}%`)",
            f"- **分箱敏感性 (`w20`)**: 现行 `Δ={bin_sens_summary['w20']['delta_fixed_2f']:+.6f}` → 原子单列 `Δ={bin_sens_summary['w20']['delta_split_atom_settled']:+.6f}` (解释 `{bin_sens_summary['w20']['pct_delta_explained_by_split_settled']:.2f}%`) → 锚点对齐 `Δ={bin_sens_summary['w20']['delta_anchor_aligned_2f']:+.6f}` (解释 `{bin_sens_summary['w20']['pct_delta_explained_by_anchor_aligned']:.2f}%`)",
            "",
            "## 五、 任务三｜OOS 降质归因（608 天 vs 2019 实测体制对照）",
            "",
            "### 5.1 逐桶实测锁顶率对照（`608` 天 vs `2019`）",
            "",
            "| 时段 | 位置桶 | 608实测 | 608预测 | 608残差 | 2019实测 | 2019预测 | 2019残差 | 实测变化 (`19-608`) | 预测变化 (`19-608`) | 2019 out95 |",
            "|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for r in attr_bucket_rows:
        lines.append(
            f"| {r['half']} | {r['pos_bucket']} | {r['emp_608']:.4f} | {r['pred_608']:.4f} | {r['resid_608']:+.4f} | {r['emp_2019']:.4f} | {r['pred_2019']:.4f} | {r['resid_2019']:+.4f} | {r['emp_shift_2019_minus_608']:+.4f} | {r['pred_shift_2019_minus_608']:+.4f} | {r['out95_2019']} |"
        )
    lines.extend(
        [
            "",
            f"- **KORD 春/秋午后对照**: `Spring` (`608实测 {kord_sa_shift['Spring']['emp_608']:.4f} vs 2019实测 {kord_sa_shift['Spring']['emp_2019']:.4f}`, `Δemp={kord_sa_shift['Spring']['emp_shift']:+.4f}`, `Δpred={kord_sa_shift['Spring']['pred_shift']:+.4f}`, `out95: {kord_sa_shift['Spring']['out95_608']}->{kord_sa_shift['Spring']['out95_2019']}`); `Autumn` (`608实测 {kord_sa_shift['Autumn']['emp_608']:.4f} vs 2019实测 {kord_sa_shift['Autumn']['emp_2019']:.4f}`, `Δemp={kord_sa_shift['Autumn']['emp_shift']:+.4f}`, `Δpred={kord_sa_shift['Autumn']['pred_shift']:+.4f}`, `out95: {kord_sa_shift['Autumn']['out95_608']}->{kord_sa_shift['Autumn']['out95_2019']}`)",
            "",
            "### 5.2 KORD Spring 逐年阴云降温与午后新高对比",
            "",
            "| 样本窗 | 天数 | 均值 T_max | 均值 μ₀ | 14:00低于锚2°F率 | 14:00冷却drop≥2°F率 | 午后均冷却drop | 午后新高率(全) | 午后新高率(B2/B3) | 峰值平均时刻 |",
            "|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for r in kord_spring_yearly_rows:
        b23_str = f"{r['post14_newhigh_rate_B2B3']:.4f} (n={r['n_B2B3']})" if r["post14_newhigh_rate_B2B3"] is not None else "N/A (n=0)"
        lines.append(
            f"| {r['cohort']} | {r['n_days']} | {r['mean_tmax_f']:.2f} | {r['mean_mu0_f']:.2f} | {r['below_anchor_14_rate']:.4f} | {r['drop_ge2_at_14_rate']:.4f} | {r['mean_aft_drop_f']:.3f} | {r['post14_newhigh_rate_all']:.4f} | {b23_str} | {r['mean_peak_hr']:.2f} |"
        )
    lines.extend(
        [
            "",
            "### 5.3 2019 vs 2016–2018 午后冷却强度与季节气候趋势",
            "",
            "| 站 | 季 | T_max(16-18) | T_max(19) | `ΔT_max` | 午后drop(16-18) | 午后drop(19) | `Δdrop` | 14h后升幅(16-18) | 14h后升幅(19) | 14h后新高率(16-18) | 14h后新高率(19) |",
            "|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for r in climate_regime_rows:
        lines.append(
            f"| {r['station']} | {r['season']} | {r['mean_tmax_16_18']:.2f} | {r['mean_tmax_2019']:.2f} | {r['tmax_diff_19_minus_16_18']:+.2f} | {r['aft_drop_16_18']:.3f} | {r['aft_drop_2019']:.3f} | {r['aft_drop_diff']:+.3f} | {r['post14_rise_16_18']:.3f} | {r['post14_rise_2019']:.3f} | {r['post14_newhigh_rate_16_18']:.4f} | {r['post14_newhigh_rate_2019']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## 六、 任务四｜W2 四维在 2019 盲测 22 格全量红黄绿体检表（`native` 口径）",
            "",
            f"- **按法定维度 1 (`w20` 20 桶) 汇总**: `{w2_counts_w20}`；**按主校准参考 (`inw` 8 谱带) 汇总**: `{w2_counts_inw}`",
            "",
            "| Cell | `ECE_w20` | `ECE_inw` | `Bias(°F)` | `CRPS_nat` | `CRPS_clim` | `CRPSS` | `Cov90` | D1(`w20`) | D1(`inw`) | D2(Bias) | D3(CRPSS) | D4(Cov90) | 总评(`w20`) | 总评(`inw`) |",
            "|:---|---:|---:|---:|---:|---:|---:|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
        ]
    )
    for r in w2_cell_rows:
        lines.append(
            f"| {r['cell']} | {r['ece_w20']:.6f} | {r['ece_inw']:.6f} | {r['bias_f']:+.4f} | {r['crps_native']:.4f} | {r['crps_clim']:.4f} | {r['crpss']:.4f} | {r['cov90']:.4f} | {r['tier_ece_w20']} | {r['tier_ece_inw']} | {r['tier_bias']} | {r['tier_crpss']} | {r['tier_cov90']} | **{r['overall_w20']}** ({r['scale_w20']}x) | **{r['overall_inw']}** ({r['scale_inw']}x) |"
        )

    OUT_REPORT_MD.write_text("\n".join(lines), encoding="utf-8")

    print("=== INSPECTION C DIAGNOSTICS SUMMARY ===")
    print("Rules:", json.dumps(rules_eval, ensure_ascii=False))
    print("Decomp INW:", json.dumps(decomp_inw))
    print("Binning Sens INW:", json.dumps(bin_sens_summary["inw"]))
    print("W2 counts (w20):", w2_counts_w20, "| W2 counts (inw):", w2_counts_inw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
