#!/usr/bin/env python3
"""Recalibrate Proposal-1 mu_R(t, m, X_t) on LST 608-day pre-2019 corpus with identifiability & regularization fixes.

Addresses Inspection C diagnostic findings strictly on pre-2019 608-day LST snapshots (zero 2019 data):
1. Adds continuous bridge CRPS + morning physical rho(t<=9)~=1.0 anchor + per-slice Tower-expectation
   |E[Y_bridge] - mu_0| constraint to eliminate early-morning BCE non-identifiability (KMIA Summer 06:00 rho=2.37 -> ~1.0).
2. Applies moderate kappa/delta regularization: reduced knot count (kappa: 7->5, delta: 6->4) + 2nd-diff & L2 penalties.
3. Enforces mechanical acceptance criteria:
   - Criterion 1: Early (06:00-13:30) B1/B2 pooled wMAE & out95 non-degradation vs both Inspection-A & Round-1 fixed-rho baselines recomputed on LST 608-day corpus.
   - Criterion 2': Afternoon (14:00-20:00) pooled out95 <= 25/312 AND |wResid| <= 0.05 separately for B1, B2, B3.
   - Criterion 3: Early B3 cooling subset & all early B3 |wResid| <= 25% of Inspection-A LST baseline.
   - Pre-registered Gate G2a_608: ALL 232 (station, season, t_hour) slices satisfy |mean(E[Y_bridge] - mu_0)| <= 2.0 degF.
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
from scipy import special
from scipy.optimize import minimize
from scipy.stats import norm

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.calibrate_p8_mu_r_cooling_drift import (
    T_PEAK_DEFAULT,
    build_piecewise_linear_basis,
    eval_piecewise_linear_and_deriv,
    summarize_strata,
    verify_analytical_derivatives,
)
from scripts.calibrate_p8_mu_r_rho_released import (
    CRITERION_2_PRIME_ABS_WRESID_MAX,
    CRITERION_2_PRIME_OUT95_MAX,
    compute_unconstrained_3param_afternoon_bound,
    make_out95_distribution_plot,
    verify_rho_derivative,
)
from scripts.diagnose_p8_inspection_c_2019 import bridge_crps_exact
from scripts.run_p8_inspection_a_eta_calibration import (
    POSITION_BUCKETS,
    SEASONS,
    SIGMA_INST_PHYSICAL_FLOOR,
    STATIONS,
    T_GRID,
    format_hour,
    rho_weight,
    wilson_ci,
)

SNAP_LST_PATH = PROJECT_ROOT / "evidence" / "p8_608d_snapshots_lst.parquet"
OUT_JSON = PROJECT_ROOT / "evidence" / "p8_mu_r_lst_identifiable_calibration_20261114.json"
OUT_CURVES_CSV = PROJECT_ROOT / "evidence" / "p8_mu_r_lst_identifiable_curves_20261114.csv"
OUT_RESID_312_CSV = PROJECT_ROOT / "evidence" / "p8_mu_r_lst_identifiable_residuals_312_20261114.csv"
OUT_RESID_FULL_CSV = PROJECT_ROOT / "evidence" / "p8_mu_r_lst_identifiable_residuals_full_20261114.csv"
OUT_SLICE_232_CSV = PROJECT_ROOT / "evidence" / "p8_mu_r_lst_identifiable_slices_232_20261114.csv"
OUT_PLOT_SVG = PROJECT_ROOT / "evidence" / "p8_mu_r_lst_identifiable_out95_dist_20261114.svg"
OUT_REPORT_MD = PROJECT_ROOT / "evidence" / "p8_mu_r_lst_identifiable_report_20261114.md"

# Regularized knots: rho keeps early/afternoon resolution; kappa & delta reduced (7->5, 6->4)
RHO_KNOTS_LST: np.ndarray = np.array([6.0, 9.0, 12.0, 13.5, 15.0, 17.0, 20.0], dtype=float)
KAPPA_KNOTS_LST: np.ndarray = np.array([6.0, 10.0, 13.5, 16.5, 20.0], dtype=float)
DELTA_KNOTS_LST: np.ndarray = np.array([13.5, 15.0, 17.5, 20.0], dtype=float)

# Regularization & identifiability hyperparameters (zero 2019 involvement)
W_CRPS: float = 0.25
W_EARLY_RHO_ANCHOR: float = 0.08
W_SLICE_TOWER_L2: float = 0.025
W_SLICE_TOWER_HINGE: float = 0.30
SLICE_TOWER_SOFT_MARGIN: float = 1.35
REG_2DIFF_RHO: float = 0.004
REG_2DIFF_KD: float = 0.008
REG_L2_KD: float = 0.0005

G2A_MAX_ABS_MEAN_DIFF: float = 2.0


def bridge_expectation(m_int: np.ndarray, mu_r: np.ndarray, sigma_rem: np.ndarray) -> np.ndarray:
    """Exact conditional expectation E[Y_bridge] = m_int + mu_R*Phi(mu_R/s) + s*phi(mu_R/s)."""
    s = np.maximum(sigma_rem, 1e-8)
    z = mu_r / s
    phi_z = np.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    cdf_z = special.ndtr(z)
    return m_int + mu_r * cdf_z + s * phi_z


def calibrate_round1_fixed_rho_lst(
    sub_df: pd.DataFrame,
    knots_k: np.ndarray = KAPPA_KNOTS_LST,
    knots_d: np.ndarray = DELTA_KNOTS_LST,
    t_peak: float = T_PEAK_DEFAULT,
    reg_2diff: float = REG_2DIFF_KD,
    reg_l2: float = REG_L2_KD,
) -> Tuple[np.ndarray, np.ndarray]:
    """Recompute Round-1 fixed-rho (kappa, delta) baseline strictly on LST 608-day corpus."""
    h = sub_df["t_hour"].to_numpy(dtype=float)
    sr = sub_df["sigma_rem"].to_numpy(dtype=float)
    heat = sub_df["heat_term"].to_numpy(dtype=float)
    drop = sub_df["cooling_drop"].to_numpy(dtype=float)
    y = sub_df["y_raw"].to_numpy(dtype=float)

    basis_k = build_piecewise_linear_basis(h, knots_k)
    basis_d = build_piecewise_linear_basis(np.maximum(h, t_peak), knots_d)[:, 1:]
    after_mask = (h > t_peak).astype(float)

    n_k = len(knots_k)
    n_d_free = len(knots_d) - 1

    def obj(theta: np.ndarray) -> float:
        vk = theta[:n_k]
        vd_free = theta[n_k:]
        vd_full = np.concatenate([[0.0], vd_free])
        kap = basis_k @ vk
        delt = after_mask * (basis_d @ vd_free)
        mu_r = heat - kap * drop - delt
        p = np.clip(special.ndtr(-mu_r / sr), 1e-6, 1.0 - 1e-6)
        bce = float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))
        reg = reg_2diff * float(np.sum(np.diff(vk, 2) ** 2) + np.sum(np.diff(vd_full, 2) ** 2))
        reg += reg_l2 * float(np.sum(vk**2) + np.sum(vd_free**2))
        return bce + reg

    x0 = np.concatenate([np.full(n_k, 0.3), np.full(n_d_free, 1.2)])
    bounds = [(0.0, 5.0)] * n_k + [(0.0, 12.0)] * n_d_free
    res = minimize(obj, x0, method="L-BFGS-B", bounds=bounds, options={"maxiter": 800})
    return np.maximum(0.0, res.x[:n_k]), np.concatenate([[0.0], np.maximum(0.0, res.x[n_k:])])


def calibrate_station_season_identifiable(
    sub_df: pd.DataFrame,
    r1_vk: np.ndarray,
    r1_vd: np.ndarray,
    knots_r: np.ndarray = RHO_KNOTS_LST,
    knots_k: np.ndarray = KAPPA_KNOTS_LST,
    knots_d: np.ndarray = DELTA_KNOTS_LST,
    t_peak: float = T_PEAK_DEFAULT,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Jointly optimize (rho, kappa, delta) with continuous CRPS + morning rho + slice Tower anchors."""
    h = sub_df["t_hour"].to_numpy(dtype=float)
    sr = sub_df["sigma_rem"].to_numpy(dtype=float)
    deficit = sub_df["heating_deficit"].to_numpy(dtype=float)
    drop = sub_df["cooling_drop"].to_numpy(dtype=float)
    y_lock = sub_df["y_raw"].to_numpy(dtype=float)
    m_int = sub_df["m_int"].to_numpy(dtype=float)
    mu_0 = sub_df["mu_0"].to_numpy(dtype=float)
    y_ghcn = sub_df["ghcn_tmax_f"].to_numpy(dtype=float)

    # Precompute hour-slice index lists for vectorized per-slice mean expectation check
    unique_hours = np.sort(sub_df["t_hour"].unique())
    slice_indices = [np.where(h == hf)[0] for hf in unique_hours]

    basis_r = build_piecewise_linear_basis(h, knots_r)
    basis_k = build_piecewise_linear_basis(h, knots_k)
    basis_d = build_piecewise_linear_basis(np.maximum(h, t_peak), knots_d)[:, 1:]
    after_mask = (h > t_peak).astype(float)

    n_r = len(knots_r)
    n_k = len(knots_k)
    n_d_free = len(knots_d) - 1
    early_rho_mask = knots_r <= 9.0

    def objective(theta: np.ndarray) -> float:
        vr = theta[:n_r]
        vk = theta[n_r : n_r + n_k]
        vd_free = theta[n_r + n_k :]
        vd_full = np.concatenate([[0.0], vd_free])

        rho_v = basis_r @ vr
        kap_v = basis_k @ vk
        delt_v = after_mask * (basis_d @ vd_free)
        mu_r = rho_v * deficit - kap_v * drop - delt_v

        # 1. Binary lock-top probability calibration
        p = np.clip(special.ndtr(-mu_r / sr), 1e-6, 1.0 - 1e-6)
        bce = float(-np.mean(y_lock * np.log(p) + (1.0 - y_lock) * np.log(1.0 - p)))

        # 2. Continuous Bridge CRPS against GHCN(LST) prior target
        crps_val = float(np.mean(bridge_crps_exact(y_ghcn, m_int, mu_r, sr)))

        # 3. Morning physical rho(t<=9) ~= 1.0 boundary anchor
        early_anchor = float(np.mean((vr[early_rho_mask] - 1.0) ** 2))

        # 4. Per-slice Tower-expectation consistency |E[Y_bridge] - E[Y_native]| <= 2.0 degF
        ey_br = bridge_expectation(m_int, mu_r, sr)
        diff_vec = ey_br - mu_0
        slice_means = np.array([float(np.mean(diff_vec[idx_s])) for idx_s in slice_indices], dtype=float)
        slice_l2 = float(np.mean(slice_means**2))
        excess = np.maximum(0.0, np.abs(slice_means) - SLICE_TOWER_SOFT_MARGIN)
        slice_hinge = float(np.sum(excess**2))

        # 5. Smoothness & shrinkage regularization
        reg_r = REG_2DIFF_RHO * float(np.sum(np.diff(vr, 2) ** 2))
        reg_kd = REG_2DIFF_KD * float(np.sum(np.diff(vk, 2) ** 2) + np.sum(np.diff(vd_full, 2) ** 2))
        reg_l2 = REG_L2_KD * float(np.sum(vk**2) + np.sum(vd_free**2))

        return (
            bce
            + W_CRPS * crps_val
            + W_EARLY_RHO_ANCHOR * early_anchor
            + W_SLICE_TOWER_L2 * slice_l2
            + W_SLICE_TOWER_HINGE * slice_hinge
            + reg_r
            + reg_kd
            + reg_l2
        )

    vr_ramp = np.array([rho_weight(float(k)) for k in knots_r], dtype=float)
    vr_signed = np.where(knots_r >= 13.5, -0.3, vr_ramp)
    inits = [
        np.concatenate([vr_ramp, r1_vk, r1_vd[1:]]),
        np.concatenate([vr_signed, r1_vk, r1_vd[1:]]),
        np.concatenate([vr_ramp, np.full(n_k, 0.3), np.full(n_d_free, 1.0)]),
    ]
    # Keep morning knots bounded smoothly near physical range; allow afternoon sign release
    bounds = (
        [(0.3, 1.6) if k <= 9.0 else (-4.0, 2.5) for k in knots_r]
        + [(0.0, 4.0)] * n_k
        + [(0.0, 10.0)] * n_d_free
    )

    best_res = None
    for x0 in inits:
        x0_c = np.clip(x0, [b[0] for b in bounds], [b[1] for b in bounds])
        res = minimize(objective, x0_c, method="L-BFGS-B", bounds=bounds, options={"maxiter": 1200})
        if best_res is None or res.fun < best_res.fun:
            best_res = res

    assert best_res is not None
    vr_opt = best_res.x[:n_r]
    vk_opt = np.maximum(0.0, best_res.x[n_r : n_r + n_k])
    vd_opt = np.concatenate([[0.0], np.maximum(0.0, best_res.x[n_r + n_k :])])
    return vr_opt, vk_opt, vd_opt


def main() -> int:
    if not SNAP_LST_PATH.exists():
        raise FileNotFoundError(f"Missing LST 608-day snapshots at {SNAP_LST_PATH}")

    all_df = pd.read_parquet(SNAP_LST_PATH).copy()
    all_df["heating_deficit"] = np.maximum(0.0, all_df["mu_0"] - all_df["m_int"])
    all_df["mu_r_base"] = all_df["rho"] * all_df["heating_deficit"]
    all_df["p_base"] = special.ndtr(-all_df["mu_r_base"].to_numpy(dtype=float) / all_df["sigma_rem"].to_numpy(dtype=float))

    # Strict zero-2019 check
    years_present = sorted(pd.to_datetime(all_df["local_date"]).dt.year.unique().tolist())
    assert max(years_present) <= 2018, f"2019 leakage detected in calibration snapshots: {years_present}"

    # 1. Recompute Round-1 fixed-rho baseline strictly on LST 608d snapshots
    pred_round1 = np.zeros(len(all_df), dtype=float)
    mu_r_round1 = np.zeros(len(all_df), dtype=float)
    r1_curves: Dict[Tuple[str, str], Tuple[np.ndarray, np.ndarray]] = {}
    for (station, season), g in all_df.groupby(["station", "season"]):
        idx = g.index.to_numpy()
        vk_r1, vd_r1 = calibrate_round1_fixed_rho_lst(g)
        r1_curves[(station, season)] = (vk_r1, vd_r1)
        h_arr = g["t_hour"].to_numpy(dtype=float)
        kap_r1 = np.array([eval_piecewise_linear_and_deriv(float(h), KAPPA_KNOTS_LST, vk_r1)[0] for h in h_arr])
        delt_r1 = np.array(
            [eval_piecewise_linear_and_deriv(float(h), DELTA_KNOTS_LST, vd_r1)[0] if h > T_PEAK_DEFAULT else 0.0 for h in h_arr]
        )
        mr1 = g["heat_term"].to_numpy(dtype=float) - kap_r1 * g["cooling_drop"].to_numpy(dtype=float) - delt_r1
        mu_r_round1[idx] = mr1
        pred_round1[idx] = special.ndtr(-mr1 / g["sigma_rem"].to_numpy(dtype=float))
    all_df["mu_r_round1"] = mu_r_round1
    all_df["p_round1"] = pred_round1

    # 2. Fit identifiable + regularized (rho, kappa, delta) curves per station x season
    curves_payload: Dict[str, Dict[str, Any]] = {"KORD": {}, "KMIA": {}}
    curve_csv_rows: List[Dict[str, Any]] = []
    pred_after = np.zeros(len(all_df), dtype=float)
    mu_r_after = np.zeros(len(all_df), dtype=float)
    max_deriv_err = 0.0

    for (station, season), g in all_df.groupby(["station", "season"]):
        idx = g.index.to_numpy()
        vk_r1, vd_r1 = r1_curves[(station, season)]
        vr, vk, vd = calibrate_station_season_identifiable(g, vk_r1, vd_r1)

        deriv_err_kd = verify_analytical_derivatives(KAPPA_KNOTS_LST, vk, DELTA_KNOTS_LST, vd, T_PEAK_DEFAULT)
        deriv_err_r = verify_rho_derivative(RHO_KNOTS_LST, vr)
        deriv_err = max(deriv_err_kd, deriv_err_r)
        max_deriv_err = max(max_deriv_err, deriv_err)

        h_arr = g["t_hour"].to_numpy(dtype=float)
        rho_arr = np.array([eval_piecewise_linear_and_deriv(float(h), RHO_KNOTS_LST, vr)[0] for h in h_arr])
        kap_arr = np.array([eval_piecewise_linear_and_deriv(float(h), KAPPA_KNOTS_LST, vk)[0] for h in h_arr])
        delt_arr = np.array(
            [eval_piecewise_linear_and_deriv(float(h), DELTA_KNOTS_LST, vd)[0] if h > T_PEAK_DEFAULT else 0.0 for h in h_arr]
        )
        mu_r_vec = (
            rho_arr * g["heating_deficit"].to_numpy(dtype=float)
            - kap_arr * g["cooling_drop"].to_numpy(dtype=float)
            - delt_arr
        )
        p_vec = special.ndtr(-mu_r_vec / g["sigma_rem"].to_numpy(dtype=float))
        mu_r_after[idx] = mu_r_vec
        pred_after[idx] = p_vec

        curves_payload[station][season] = {
            "t_peak": T_PEAK_DEFAULT,
            "rho_knots": [float(x) for x in RHO_KNOTS_LST],
            "rho_values": [round(float(x), 6) for x in vr],
            "kappa_knots": [float(x) for x in KAPPA_KNOTS_LST],
            "kappa_values": [round(float(x), 6) for x in vk],
            "delta_knots": [float(x) for x in DELTA_KNOTS_LST],
            "delta_values": [round(float(x), 6) for x in vd],
            "stage97_deriv_max_fd_error": round(deriv_err, 9),
        }

        for h in T_GRID:
            hf = float(h)
            rv, drv = eval_piecewise_linear_and_deriv(hf, RHO_KNOTS_LST, vr)
            kv, dkv = eval_piecewise_linear_and_deriv(hf, KAPPA_KNOTS_LST, vk)
            if hf > T_PEAK_DEFAULT:
                dv, ddv = eval_piecewise_linear_and_deriv(hf, DELTA_KNOTS_LST, vd)
            else:
                dv, ddv = 0.0, 0.0
            curve_csv_rows.append(
                {
                    "station": station,
                    "season": season,
                    "t_hour": hf,
                    "t_label": format_hour(hf),
                    "t_peak": T_PEAK_DEFAULT,
                    "rho_fixed": round(rho_weight(hf), 6),
                    "rho": round(rv, 6),
                    "drho_dt": round(drv, 6),
                    "kappa": round(kv, 6),
                    "dkappa_dt": round(dkv, 6),
                    "delta": round(dv, 6),
                    "ddelta_dt": round(ddv, 6),
                }
            )

    all_df["mu_r_after"] = mu_r_after
    all_df["p_after"] = pred_after

    # 3. Evaluate G2a across all 232 (station, season, t_hour) slices on 608-day LST corpus
    all_df["ey_bridge_after"] = bridge_expectation(
        all_df["m_int"].to_numpy(dtype=float),
        mu_r_after,
        all_df["sigma_rem"].to_numpy(dtype=float),
    )
    all_df["ey_diff_after"] = all_df["ey_bridge_after"] - all_df["mu_0"]
    all_df["crps_bridge_after"] = bridge_crps_exact(
        all_df["ghcn_tmax_f"].to_numpy(dtype=float),
        all_df["m_int"].to_numpy(dtype=float),
        mu_r_after,
        all_df["sigma_rem"].to_numpy(dtype=float),
    )

    slice_232_rows: List[Dict[str, Any]] = []
    for st in STATIONS:
        for seas in SEASONS:
            for h in T_GRID:
                hf = float(h)
                sub = all_df[(all_df["station"] == st) & (all_df["season"] == seas) & (all_df["t_hour"] == hf)]
                mean_ey = float(sub["ey_bridge_after"].mean())
                mean_mu0 = float(sub["mu_0"].mean())
                mean_diff = float(sub["ey_diff_after"].mean())
                slice_232_rows.append(
                    {
                        "station": st,
                        "season": seas,
                        "t_hour": hf,
                        "t_label": format_hour(hf),
                        "n_days": int(len(sub)),
                        "mean_ey_bridge": round(mean_ey, 6),
                        "mean_mu0": round(mean_mu0, 6),
                        "mean_ey_minus_mu0": round(mean_diff, 6),
                        "abs_mean_ey_minus_mu0": round(abs(mean_diff), 6),
                        "pass_g2a_le_2_0": bool(abs(mean_diff) <= G2A_MAX_ABS_MEAN_DIFF),
                        "mean_crps_bridge_ghcn": round(float(sub["crps_bridge_after"].mean()), 6),
                    }
                )
    slice_232_df = pd.DataFrame(slice_232_rows)
    slice_232_df.to_csv(OUT_SLICE_232_CSV, index=False)

    max_abs_slice_diff = float(slice_232_df["abs_mean_ey_minus_mu0"].max())
    n_g2a_violations = int((~slice_232_df["pass_g2a_le_2_0"]).sum())
    pass_g2a_608 = bool(n_g2a_violations == 0)

    # 4. Evaluate bucket residuals & 3 acceptance criteria (① / ②' / ③)
    resid_rows: List[Dict[str, Any]] = []
    for station in STATIONS:
        for season in SEASONS:
            for h in T_GRID:
                hf = float(h)
                s_slice = all_df[(all_df["station"] == station) & (all_df["season"] == season) & (all_df["t_hour"] == hf)]
                for b in POSITION_BUCKETS:
                    sb = s_slice[s_slice["pos_bucket"] == b]
                    nb = int(len(sb))
                    if nb == 0:
                        continue
                    kb = int(sb["y_raw"].sum())
                    emp = kb / nb
                    pb = float(sb["p_base"].mean())
                    pr1 = float(sb["p_round1"].mean())
                    pa = float(sb["p_after"].mean())
                    lo, hi = wilson_ci(kb, nb)
                    resid_rows.append(
                        {
                            "station": station,
                            "season": season,
                            "t_hour": hf,
                            "t_label": format_hour(hf),
                            "pos_bucket": b,
                            "n_bucket": nb,
                            "emp_no_new_raw": round(emp, 6),
                            "pred_insp_a_base": round(pb, 6),
                            "resid_insp_a_base": round(emp - pb, 6),
                            "pred_round1": round(pr1, 6),
                            "resid_round1": round(emp - pr1, 6),
                            "pred_after": round(pa, 6),
                            "resid_after": round(emp - pa, 6),
                            "wilson95_lo": round(lo, 6),
                            "wilson95_hi": round(hi, 6),
                            "outside_ci_insp_a_base": bool(pb < lo or pb > hi),
                            "outside_ci_round1": bool(pr1 < lo or pr1 > hi),
                            "outside_ci_after": bool(pa < lo or pa > hi),
                        }
                    )

    resid_full_df = pd.DataFrame(resid_rows)
    resid_312_df = resid_full_df[resid_full_df["t_hour"] >= 14.0].copy()
    assert len(resid_312_df) == 312, f"Expected 312 afternoon cells, got {len(resid_312_df)}"

    pd.DataFrame(curve_csv_rows).to_csv(OUT_CURVES_CSV, index=False)
    resid_full_df.to_csv(OUT_RESID_FULL_CSV, index=False)
    resid_312_df.to_csv(OUT_RESID_312_CSV, index=False)
    make_out95_distribution_plot(resid_312_df, OUT_PLOT_SVG)

    pbase_stats = summarize_strata(all_df, "p_base")
    round1_stats = summarize_strata(all_df, "p_round1")
    after_stats = summarize_strata(all_df, "p_after")

    early_b3_cool = all_df[
        (all_df["t_hour"] <= 13.5)
        & (all_df["pos_bucket"] == "B3_at_or_above")
        & (all_df["cooling_drop"] > 0.05)
    ]
    eb3_emp = float(early_b3_cool["y_raw"].mean())
    eb3_pbase = float(early_b3_cool["p_base"].mean())
    eb3_round1 = float(early_b3_cool["p_round1"].mean())
    eb3_after = float(early_b3_cool["p_after"].mean())

    kmia_aft = all_df[(all_df["station"] == "KMIA") & (all_df["t_hour"] >= 15.0)]
    kmia_mu_q = np.quantile(kmia_aft["mu_r_after"], [0.10, 0.25, 0.50, 0.75, 0.90])
    kmia_phi_at_09 = special.ndtr(-kmia_aft["mu_r_after"].to_numpy() / SIGMA_INST_PHYSICAL_FLOOR)
    reachability = {
        "n_obs": int(len(kmia_aft)),
        "mu_r_quantiles_10_25_50_75_90": [round(float(x), 4) for x in kmia_mu_q],
        "frac_phi_at_09_ge_095": round(float(np.mean(kmia_phi_at_09 >= 0.95)), 6),
        "frac_phi_actual_ge_095": round(float(np.mean(kmia_aft["p_after"].to_numpy() >= 0.95)), 6),
        "min_mu_r": round(float(kmia_aft["mu_r_after"].min()), 4),
        "max_mu_r": round(float(kmia_aft["mu_r_after"].max()), 4),
        "reachable": bool(kmia_aft["mu_r_after"].min() <= -1.4804),
    }

    # Criterion 1 vs LST baselines (Inspection A base & Round-1 fixed rho)
    pass_c1_vs_round1 = bool(
        (after_stats["early_B12_pooled"]["wMAE"] <= round1_stats["early_B12_pooled"]["wMAE"])
        and (after_stats["early_B1"]["out95"] <= round1_stats["early_B1"]["out95"])
        and (after_stats["early_B2"]["out95"] <= round1_stats["early_B2"]["out95"])
    )
    pass_c1_vs_insp_a = bool(
        (after_stats["early_B12_pooled"]["wMAE"] <= pbase_stats["early_B12_pooled"]["wMAE"])
        and (after_stats["early_B1"]["wMAE"] <= pbase_stats["early_B1"]["wMAE"])
        and (after_stats["early_B2"]["wMAE"] <= pbase_stats["early_B2"]["wMAE"])
        and (after_stats["early_B1"]["out95"] <= pbase_stats["early_B1"]["out95"])
        and (after_stats["early_B2"]["out95"] <= pbase_stats["early_B2"]["out95"])
    )
    pass_c2p_out95 = bool(after_stats["aft_total_out95"] <= CRITERION_2_PRIME_OUT95_MAX)
    pass_c2p_b1 = bool(abs(after_stats["aft_B1"]["wResid"]) <= CRITERION_2_PRIME_ABS_WRESID_MAX)
    pass_c2p_b2 = bool(abs(after_stats["aft_B2"]["wResid"]) <= CRITERION_2_PRIME_ABS_WRESID_MAX)
    pass_c2p_b3 = bool(abs(after_stats["aft_B3"]["wResid"]) <= CRITERION_2_PRIME_ABS_WRESID_MAX)
    pass_c2_prime = bool(pass_c2p_out95 and pass_c2p_b1 and pass_c2p_b2 and pass_c2p_b3)
    pass_c3 = bool(
        (abs(eb3_emp - eb3_after) <= 0.25 * abs(eb3_emp - eb3_pbase))
        and (abs(after_stats["early_B3"]["wResid"]) <= 0.25 * abs(pbase_stats["early_B3"]["wResid"]))
    )
    overall_pass = bool(pass_c1_vs_round1 and pass_c1_vs_insp_a and pass_c2_prime and pass_c3 and pass_g2a_608)

    payload = {
        "schema_version": "p8_mu_r_lst_identifiable_calibration_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_boundary": "2016-04-30 .. 2018-12-30 LST day-boundary (608 valid days/station, zero 2019)",
        "years_verified": years_present,
        "parameterization": {
            "form": "piecewise_linear_c0_analytic_derivative_identifiable_lst",
            "t_peak": T_PEAK_DEFAULT,
            "rho_knots": [float(x) for x in RHO_KNOTS_LST],
            "kappa_knots": [float(x) for x in KAPPA_KNOTS_LST],
            "delta_knots": [float(x) for x in DELTA_KNOTS_LST],
            "w_crps": W_CRPS,
            "w_early_rho_anchor": W_EARLY_RHO_ANCHOR,
            "w_slice_tower_l2": W_SLICE_TOWER_L2,
            "w_slice_tower_hinge": W_SLICE_TOWER_HINGE,
            "reg_2diff_rho": REG_2DIFF_RHO,
            "reg_2diff_kd": REG_2DIFF_KD,
            "reg_l2_kd": REG_L2_KD,
            "stage97_deriv_max_fd_error": round(max_deriv_err, 9),
        },
        "curves": curves_payload,
        "reachability_kmia_1500_2000": reachability,
        "lst_insp_a_baseline_stats": pbase_stats,
        "lst_round1_fixed_rho_stats": round1_stats,
        "calibrated_lst_identifiable_stats": after_stats,
        "g2a_608_summary": {
            "total_slices": int(len(slice_232_df)),
            "max_abs_mean_ey_minus_mu0": round(max_abs_slice_diff, 6),
            "threshold": G2A_MAX_ABS_MEAN_DIFF,
            "n_violations": n_g2a_violations,
            "pass": pass_g2a_608,
            "top5_slices": slice_232_df.sort_values("abs_mean_ey_minus_mu0", ascending=False).head(5).to_dict(orient="records"),
        },
        "early_b3_cooling_subset": {
            "n_obs": int(len(early_b3_cool)),
            "emp_no_new_raw": round(eb3_emp, 6),
            "pred_insp_a_base": round(eb3_pbase, 6),
            "resid_insp_a_base": round(eb3_emp - eb3_pbase, 6),
            "pred_round1": round(eb3_round1, 6),
            "resid_round1": round(eb3_emp - eb3_round1, 6),
            "pred_after": round(eb3_after, 6),
            "resid_after": round(eb3_emp - eb3_after, 6),
        },
        "acceptance_gates": {
            "criterion_1_early_b12_non_degradation": {
                "lst_round1_b12_wmae": round1_stats["early_B12_pooled"]["wMAE"],
                "after_b12_wmae": after_stats["early_B12_pooled"]["wMAE"],
                "lst_round1_b1_out95": round1_stats["early_B1"]["out95"],
                "after_b1_out95": after_stats["early_B1"]["out95"],
                "lst_round1_b2_out95": round1_stats["early_B2"]["out95"],
                "after_b2_out95": after_stats["early_B2"]["out95"],
                "lst_insp_a_b12_wmae": pbase_stats["early_B12_pooled"]["wMAE"],
                "lst_insp_a_b1_out95": pbase_stats["early_B1"]["out95"],
                "lst_insp_a_b2_out95": pbase_stats["early_B2"]["out95"],
                "pass_vs_round1_lst": pass_c1_vs_round1,
                "pass_vs_insp_a_lst": pass_c1_vs_insp_a,
                "pass": bool(pass_c1_vs_round1 and pass_c1_vs_insp_a),
            },
            "criterion_2_prime_afternoon_binomial_and_family_mean": {
                "lst_round1_out95": round1_stats["aft_total_out95"],
                "after_out95": after_stats["aft_total_out95"],
                "threshold_out95_max": CRITERION_2_PRIME_OUT95_MAX,
                "pass_out95": pass_c2p_out95,
                "after_B1_wResid": after_stats["aft_B1"]["wResid"],
                "after_B2_wResid": after_stats["aft_B2"]["wResid"],
                "after_B3_wResid": after_stats["aft_B3"]["wResid"],
                "threshold_abs_wResid_max": CRITERION_2_PRIME_ABS_WRESID_MAX,
                "pass_B1_wResid": pass_c2p_b1,
                "pass_B2_wResid": pass_c2p_b2,
                "pass_B3_wResid": pass_c2p_b3,
                "pass": pass_c2_prime,
            },
            "criterion_3_early_b3_cooling_convergence": {
                "subset_resid_insp_a_base": round(eb3_emp - eb3_pbase, 6),
                "subset_resid_after": round(eb3_emp - eb3_after, 6),
                "subset_threshold_25pct_insp_a": round(0.25 * abs(eb3_emp - eb3_pbase), 6),
                "all_early_b3_wResid_insp_a_base": pbase_stats["early_B3"]["wResid"],
                "all_early_b3_wResid_after": after_stats["early_B3"]["wResid"],
                "pass": pass_c3,
            },
            "g2a_608_tower_expectation_232_slices": {
                "max_abs_mean_ey_minus_mu0": round(max_abs_slice_diff, 6),
                "threshold": G2A_MAX_ABS_MEAN_DIFF,
                "n_violations": n_g2a_violations,
                "pass": pass_g2a_608,
            },
            "overall_pass": overall_pass,
        },
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# P8-ALGO LST 可识别性修复与正则重标定报告（608 天零 2019）",
        "",
        f"- **执行日期**: 2026-11-14 | **脚本**: [`scripts/calibrate_p8_mu_r_lst_identifiable.py`](../scripts/calibrate_p8_mu_r_lst_identifiable.py)",
        "- **数据边界**: `evidence/p8_608d_snapshots_lst.parquet`（2016–2018 各 608 日，严格零 2019）",
        f"- **正则配置**: `kappa` 节点 `7->5` `{KAPPA_KNOTS_LST.tolist()}`, `delta` 节点 `6->4` `{DELTA_KNOTS_LST.tolist()}`, `w_crps={W_CRPS}`, `w_early_rho={W_EARLY_RHO_ANCHOR}`, `w_slice_l2={W_SLICE_TOWER_L2}`, `w_slice_hinge={W_SLICE_TOWER_HINGE}`, `reg_2diff_r={REG_2DIFF_RHO}`, `reg_2diff_kd={REG_2DIFF_KD}`, Stage 9.7 数值差分最大误差 = `{max_deriv_err:.2e}`",
        "",
        "## 一、 硬性验收判据（LST 基线重算 + G2a_608）",
        "",
        f"- **判据 ①（06:00–13:30 B1/B2 不劣化）**: 原始观测值 = `pooled wMAE {after_stats['early_B12_pooled']['wMAE']:.6f}` (`B1 out95 {after_stats['early_B1']['out95']}/128`, `B2 out95 {after_stats['early_B2']['out95']}/109`); 判定阈值 = LST Round-1 (`≤ {round1_stats['early_B12_pooled']['wMAE']:.6f}` / `≤ {round1_stats['early_B1']['out95']}` / `≤ {round1_stats['early_B2']['out95']}`) & LST Insp-A (`≤ {pbase_stats['early_B12_pooled']['wMAE']:.6f}` / `≤ {pbase_stats['early_B1']['out95']}` / `≤ {pbase_stats['early_B2']['out95']}`); 结论 = `{'通过' if (pass_c1_vs_round1 and pass_c1_vs_insp_a) else '不通过'}` (`vs_round1={pass_c1_vs_round1}`, `vs_insp_a={pass_c1_vs_insp_a}`)",
        f"- **判据 ②′（午后 14:00–20:00 二项界 + 分族均值）**: 原始观测值 = `out95 {after_stats['aft_total_out95']}/312`, `B1 wResid {after_stats['aft_B1']['wResid']:+.6f}`, `B2 wResid {after_stats['aft_B2']['wResid']:+.6f}`, `B3 wResid {after_stats['aft_B3']['wResid']:+.6f}`; 判定阈值 = `out95 ≤ 25/312` 且各族 `|wResid| ≤ 0.05`; 结论 = `{'通过' if pass_c2_prime else '不通过'}`",
        f"- **判据 ③（早段 B3 冷却收敛 ≤ 基线 25%）**: 原始观测值 = 冷却子集 `(n={len(early_b3_cool)})` `{eb3_emp - eb3_after:+.6f}` (基线 `{eb3_emp - eb3_pbase:+.6f}`), 全量早段 B3 `wResid {after_stats['early_B3']['wResid']:+.6f}` (基线 `{pbase_stats['early_B3']['wResid']:+.6f}`); 结论 = `{'通过' if pass_c3 else '不通过'}`",
        f"- **预注册 G2a_608（232 切片塔性质偏差 ≤ 2.0°F）**: 原始观测值 = `max |E[Y_bridge]-mu_0| = {max_abs_slice_diff:.4f}°F` (`violations = {n_g2a_violations}/232`); 判定阈值 = `≤ 2.0°F`; 结论 = `{'通过' if pass_g2a_608 else '不通过'}`",
        f"- **总门禁**: `overall_pass = {overall_pass}`",
    ]
    OUT_REPORT_MD.write_text("\n".join(lines), encoding="utf-8")

    print("=== TASK 2: LST IDENTIFIABLE RECALIBRATION (608d ZERO 2019) ===")
    print("acceptance_gates:", json.dumps(payload["acceptance_gates"], indent=2))
    print("rho_KMIA_Summer:", curves_payload["KMIA"]["Summer"]["rho_values"])
    print("rho_KORD_Spring:", curves_payload["KORD"]["Spring"]["rho_values"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
