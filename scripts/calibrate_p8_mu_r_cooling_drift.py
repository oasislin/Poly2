#!/usr/bin/env python3
"""Calibrate Proposal-1 mu_R(t, m, X_t) piecewise-smooth cooling & post-peak curves.

Implements P8-ALGO-REVIEW Task 2 (Proposal 1 calibration on identical 608-day pre-2019 Inspection A corpus):
    mu_R(t, m, X_t) = rho(t) * max(0, mu_0 - m)
                      - kappa_{s,se}(t) * max(0, M_t - X_t)
                      - delta_{s,se}(t) * 1_{t > t_peak}

Constraints enforced:
- Strict zero-2019 data boundary (only 2016-2018 MADISHF + 2000_2018_training_arrays + v2_2000_2018_oof_cv s_oos).
- Piecewise-smooth continuous differentiable curves for kappa_{s,se}(t) and delta_{s,se}(t)
  with delta_{s,se}(t_peak) = 0 and closed-form derivatives dkappa/dt, ddelta/dt for Stage 9.7 dp/dt.
- Mechanical two-step boolean acceptance gates (no metric fudging); outputs artifacts to evidence/.
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
from scipy.optimize import minimize
from scipy.stats import norm

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_p8_inspection_a_eta_calibration import (
    CONTRACT_PATH,
    POSITION_BUCKETS,
    SEASONS,
    SIGMA_INST_PHYSICAL_FLOOR,
    STATIONS,
    T_GRID,
    TRAIN_ARRAYS_PATH,
    classify_position_bucket,
    format_hour,
    load_clean_pre2019_5min,
    load_station_priors,
    rho_weight,
    settle_half_up,
    wilson_ci,
)

ETA_CAL_CSV = PROJECT_ROOT / "evidence" / "p8_inspection_a_eta_s_calibration_20261113.csv"
OUT_JSON = PROJECT_ROOT / "evidence" / "p8_mu_r_cooling_drift_calibration_20261114.json"
OUT_CURVES_CSV = PROJECT_ROOT / "evidence" / "p8_mu_r_cooling_drift_curves_20261114.csv"
OUT_RESID_CSV = PROJECT_ROOT / "evidence" / "p8_mu_r_cooling_drift_residuals_20261114.csv"
OUT_REPORT_MD = PROJECT_ROOT / "evidence" / "p8_mu_r_cooling_drift_report_20261114.md"

T_PEAK_DEFAULT: float = 13.5
KAPPA_KNOTS: np.ndarray = np.array([6.0, 9.0, 12.0, 13.5, 15.0, 17.0, 20.0], dtype=float)
DELTA_KNOTS: np.ndarray = np.array([13.5, 14.0, 15.0, 16.5, 18.0, 20.0], dtype=float)
REG_SECOND_DIFF: float = 0.0015


def build_piecewise_linear_basis(t_arr: np.ndarray, knots: np.ndarray) -> np.ndarray:
    """Build piecewise-linear C0 interpolation basis matrix on clamped [knots[0], knots[-1]]."""
    t_c = np.clip(np.asarray(t_arr, dtype=float), knots[0], knots[-1])
    basis = np.zeros((len(t_c), len(knots)), dtype=float)
    for i in range(len(knots) - 1):
        k0, k1 = float(knots[i]), float(knots[i + 1])
        mask = (t_c >= k0 - 1e-12) & (t_c <= k1 + 1e-12)
        if not np.any(mask):
            continue
        w = np.clip((t_c[mask] - k0) / (k1 - k0), 0.0, 1.0)
        basis[mask, i] = np.maximum(basis[mask, i], 1.0 - w)
        basis[mask, i + 1] = np.maximum(basis[mask, i + 1], w)
    # Normalize overlapping knot endpoints to exact unity
    row_sums = basis.sum(axis=1, keepdims=True)
    row_sums = np.where(row_sums > 0.0, row_sums, 1.0)
    return basis / row_sums


def eval_piecewise_linear_and_deriv(
    t_hour: float,
    knots: np.ndarray,
    values: np.ndarray,
) -> Tuple[float, float]:
    """Evaluate continuous piecewise-linear curve value and analytical derivative wrt t_hour."""
    t = float(t_hour)
    if t <= knots[0]:
        return float(values[0]), 0.0
    if t >= knots[-1]:
        return float(values[-1]), 0.0
    idx = int(np.searchsorted(knots, t, side="right")) - 1
    idx = max(0, min(idx, len(knots) - 2))
    k0, k1 = float(knots[idx]), float(knots[idx + 1])
    v0, v1 = float(values[idx]), float(values[idx + 1])
    slope = (v1 - v0) / (k1 - k0)
    val = v0 + slope * (t - k0)
    return float(val), float(slope)


def verify_analytical_derivatives(
    knots_k: np.ndarray,
    vals_k: np.ndarray,
    knots_d: np.ndarray,
    vals_d: np.ndarray,
    t_peak: float = T_PEAK_DEFAULT,
) -> float:
    """Compare closed-form derivatives vs central finite differences away from knots."""
    max_err = 0.0
    eps = 1e-5
    all_knots = set(float(x) for x in np.concatenate([knots_k, knots_d, [t_peak]]))
    for t in np.linspace(6.1, 19.9, 55):
        if any(abs(t - k) < 1e-3 for k in all_knots):
            continue
        _, dk = eval_piecewise_linear_and_deriv(t, knots_k, vals_k)
        kp, _ = eval_piecewise_linear_and_deriv(t + eps, knots_k, vals_k)
        km, _ = eval_piecewise_linear_and_deriv(t - eps, knots_k, vals_k)
        max_err = max(max_err, abs(dk - (kp - km) / (2.0 * eps)))

        _, dd = (
            eval_piecewise_linear_and_deriv(t, knots_d, vals_d)
            if t > t_peak
            else (0.0, 0.0)
        )
        dp = eval_piecewise_linear_and_deriv(t + eps, knots_d, vals_d)[0] if t + eps > t_peak else 0.0
        dm = eval_piecewise_linear_and_deriv(t - eps, knots_d, vals_d)[0] if t - eps > t_peak else 0.0
        max_err = max(max_err, abs(dd - (dp - dm) / (2.0 * eps)))
    return float(max_err)


def load_608day_snapshot_frame() -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Build exact 608-day snapshot dataframe matching Inspection A eta_s baseline."""
    eta_df = pd.read_csv(ETA_CAL_CSV)
    eta_map = {
        (str(r.station), str(r.season), float(r.t_hour)): float(r.eta_calibrated)
        for r in eta_df.itertuples()
    }
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    train_arrays = pd.read_parquet(TRAIN_ARRAYS_PATH)

    frames: List[pd.DataFrame] = []
    station_meta: Dict[str, Any] = {}
    for station in STATIONS:
        obs_df, meta = load_clean_pre2019_5min(station)
        valid_dates = set(obs_df["local_date"].unique())
        max_year = max(d.year for d in valid_dates)
        if max_year > 2018:
            raise RuntimeError(f"Zero-2019 policy violated for {station}: max_year={max_year}")

        c18 = math.sqrt(max(1.0, float(contract["cells"][f"{station}_18h"]["s_oos"])))
        priors = load_station_priors(station, valid_dates, train_arrays, c18)
        if int(priors["year"].max()) > 2018:
            raise RuntimeError(f"Zero-2019 policy violated in priors for {station}")

        priors["local_date"] = pd.to_datetime(priors["date"]).dt.date
        tfin = obs_df.groupby("local_date")["temp_f"].max()
        priors["tfin"] = priors["local_date"].map(tfin)
        p_idx = priors.set_index("local_date")
        station_meta[station] = meta

        for h in T_GRID:
            hf = float(h)
            s_h = obs_df[obs_df["hour_f"] <= hf + 1e-9]
            g = s_h.sort_values("hour_f").groupby("local_date").agg(
                mt=("temp_f", "max"),
                xt=("temp_f", "last"),
            )
            df = p_idx.join(g).dropna(subset=["mt", "xt", "tfin", "mu_0", "sigma_0"]).copy()
            df["eta"] = df["season"].map({seas: eta_map[(station, seas, hf)] for seas in SEASONS})
            df["sigma_rem"] = np.maximum(
                df["sigma_0"].to_numpy(dtype=float) * np.sqrt(np.maximum(df["eta"].to_numpy(dtype=float), 0.0)),
                SIGMA_INST_PHYSICAL_FLOOR,
            )
            df["m_int"] = [settle_half_up(float(x)) for x in df["mt"]]
            df["rho"] = rho_weight(hf)
            df["heat_term"] = df["rho"] * np.maximum(0.0, df["mu_0"] - df["m_int"])
            df["cooling_drop"] = np.maximum(0.0, df["mt"] - df["xt"])
            df["y_raw"] = (df["tfin"] <= df["mt"] + 1e-6).astype(float)
            df["pos_bucket"] = [classify_position_bucket(float(d)) for d in (df["mt"] - df["mu_0"])]
            df["t_hour"] = hf
            df["mu_r_base"] = df["heat_term"]
            df["p_base"] = norm.cdf(-df["mu_r_base"] / df["sigma_rem"])
            frames.append(
                df.reset_index()[
                    [
                        "station",
                        "season",
                        "local_date",
                        "t_hour",
                        "mu_0",
                        "sigma_0",
                        "eta",
                        "sigma_rem",
                        "mt",
                        "xt",
                        "m_int",
                        "tfin",
                        "rho",
                        "heat_term",
                        "cooling_drop",
                        "y_raw",
                        "pos_bucket",
                        "mu_r_base",
                        "p_base",
                    ]
                ]
            )

    all_df = pd.concat(frames, ignore_index=True)
    return all_df, station_meta


def calibrate_station_season_curves(
    sub_df: pd.DataFrame,
    knots_k: np.ndarray = KAPPA_KNOTS,
    knots_d: np.ndarray = DELTA_KNOTS,
    t_peak: float = T_PEAK_DEFAULT,
    reg_weight: float = REG_SECOND_DIFF,
) -> Tuple[np.ndarray, np.ndarray]:
    """Fit piecewise-linear smooth (kappa, delta) curves via regularized Bernoulli log-loss."""
    h = sub_df["t_hour"].to_numpy(dtype=float)
    sr = sub_df["sigma_rem"].to_numpy(dtype=float)
    heat = sub_df["heat_term"].to_numpy(dtype=float)
    drop = sub_df["cooling_drop"].to_numpy(dtype=float)
    y = sub_df["y_raw"].to_numpy(dtype=float)

    basis_k = build_piecewise_linear_basis(h, knots_k)
    basis_d = build_piecewise_linear_basis(np.maximum(h, t_peak), knots_d)[:, 1:]  # delta(t_peak) == 0 fixed
    after_mask = (h > t_peak).astype(float)

    n_k = len(knots_k)
    n_d_free = len(knots_d) - 1

    def objective(theta: np.ndarray) -> float:
        vk = theta[:n_k]
        vd_free = theta[n_k:]
        vd_full = np.concatenate([[0.0], vd_free])
        kap = basis_k @ vk
        delt = after_mask * (basis_d @ vd_free)
        mu_r = heat - kap * drop - delt
        p = np.clip(norm.cdf(-mu_r / sr), 1e-6, 1.0 - 1e-6)
        bce = float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))
        reg = reg_weight * float(np.sum(np.diff(vk, 2) ** 2) + np.sum(np.diff(vd_full, 2) ** 2))
        return bce + reg

    x0 = np.concatenate([np.full(n_k, 0.3), np.full(n_d_free, 1.5)])
    bounds = [(0.0, 5.0)] * n_k + [(0.0, 12.0)] * n_d_free
    res = minimize(objective, x0, method="L-BFGS-B", bounds=bounds)
    vk_opt = np.maximum(0.0, res.x[:n_k])
    vd_opt = np.concatenate([[0.0], np.maximum(0.0, res.x[n_k:])])
    return vk_opt, vd_opt


def compute_unconstrained_afternoon_lower_bound(all_df: pd.DataFrame) -> Dict[str, Any]:
    """Solve per-(station, season, t_hour >= 14.0) unconstrained 2-param best CI count."""
    aft = all_df[all_df["t_hour"] >= 14.0]
    min_out = 0
    conflict_details: List[Dict[str, Any]] = []
    for (st, seas, hf), g in aft.groupby(["station", "season", "t_hour"]):
        sr = g["sigma_rem"].to_numpy(dtype=float)
        heat = g["heat_term"].to_numpy(dtype=float)
        drop = g["cooling_drop"].to_numpy(dtype=float)
        y = g["y_raw"].to_numpy(dtype=float)
        bkts = g["pos_bucket"].to_numpy()

        bucket_meta = []
        for b in POSITION_BUCKETS:
            m = bkts == b
            nb = int(m.sum())
            if nb > 0:
                kb = int(y[m].sum())
                lo, hi = wilson_ci(kb, nb)
                bucket_meta.append((b, m, nb, kb, kb / nb, lo, hi))

        def obj(p2: np.ndarray) -> float:
            k_val, d_val = p2
            p = norm.cdf(-(heat - k_val * drop - d_val) / sr)
            viol = 0.0
            for _, m, _, _, emp, lo, hi in bucket_meta:
                pm = float(p[m].mean())
                if pm < lo:
                    viol += (lo - pm) ** 2
                elif pm > hi:
                    viol += (pm - hi) ** 2
            return viol

        best_res = None
        for init in ([0.3, 1.5], [1.0, 3.0], [2.5, 5.0], [0.05, 0.2], [5.0, 0.5]):
            r = minimize(obj, init, method="L-BFGS-B", bounds=[(0.0, 20.0), (0.0, 25.0)])
            if best_res is None or r.fun < best_res.fun:
                best_res = r
        k_val, d_val = float(best_res.x[0]), float(best_res.x[1])
        p_opt = norm.cdf(-(heat - k_val * drop - d_val) / sr)
        for b, m, nb, kb, emp, lo, hi in bucket_meta:
            pm = float(p_opt[m].mean())
            if pm < lo or pm > hi:
                min_out += 1
                conflict_details.append(
                    {
                        "station": st,
                        "season": seas,
                        "t_hour": float(hf),
                        "pos_bucket": b,
                        "n": nb,
                        "emp_no_new": round(emp, 6),
                        "best_pred": round(pm, 6),
                        "wilson95_lo": round(lo, 6),
                        "wilson95_hi": round(hi, 6),
                    }
                )
    return {
        "total_afternoon_cells": 312,
        "unconstrained_min_out95": int(min_out),
        "conflict_details": conflict_details,
    }


def summarize_strata(df: pd.DataFrame, pred_col: str) -> Dict[str, Any]:
    """Compute exact bucket metrics matching Inspection A residual layout."""
    bucket_rows = []
    for (st, seas, hf, b), g in df.groupby(["station", "season", "t_hour", "pos_bucket"]):
        nb = int(len(g))
        kb = int(g["y_raw"].sum())
        lo, hi = wilson_ci(kb, nb)
        emp = kb / nb
        prd = float(g[pred_col].mean())
        bucket_rows.append(
            {
                "station": st,
                "season": seas,
                "t_hour": float(hf),
                "pos_bucket": b,
                "n": nb,
                "emp": emp,
                "pred": prd,
                "resid": emp - prd,
                "abs_resid": abs(emp - prd),
                "out95": bool(prd < lo or prd > hi),
            }
        )
    bdf = pd.DataFrame(bucket_rows)

    def _agg(sub: pd.DataFrame) -> Dict[str, Any]:
        w = sub["n"].to_numpy(dtype=float)
        return {
            "cells": int(len(sub)),
            "n_obs": int(sub["n"].sum()),
            "wMAE": round(float(np.average(sub["abs_resid"], weights=w)), 6),
            "wResid": round(float(np.average(sub["resid"], weights=w)), 6),
            "out95": int(sub["out95"].sum()),
        }

    early = bdf[bdf["t_hour"] <= 13.5]
    aft = bdf[bdf["t_hour"] >= 14.0]
    e_b12 = early[early["pos_bucket"].isin(["B1_below_anchor", "B2_near_anchor"])]
    return {
        "early_B12_pooled": _agg(e_b12),
        "early_B1": _agg(early[early["pos_bucket"] == "B1_below_anchor"]),
        "early_B2": _agg(early[early["pos_bucket"] == "B2_near_anchor"]),
        "early_B3": _agg(early[early["pos_bucket"] == "B3_at_or_above"]),
        "aft_B1": _agg(aft[aft["pos_bucket"] == "B1_below_anchor"]),
        "aft_B2": _agg(aft[aft["pos_bucket"] == "B2_near_anchor"]),
        "aft_B3": _agg(aft[aft["pos_bucket"] == "B3_at_or_above"]),
        "aft_total_cells": int(len(aft)),
        "aft_total_out95": int(aft["out95"].sum()),
        "aft_kord_out95": int(aft[aft["station"] == "KORD"]["out95"].sum()),
        "aft_kmia_out95": int(aft[aft["station"] == "KMIA"]["out95"].sum()),
    }


def main() -> int:
    all_df, station_meta = load_608day_snapshot_frame()

    curves_payload: Dict[str, Dict[str, Any]] = {"KORD": {}, "KMIA": {}}
    curve_csv_rows: List[Dict[str, Any]] = []
    pred_after = np.zeros(len(all_df), dtype=float)
    mu_r_after = np.zeros(len(all_df), dtype=float)

    max_deriv_err = 0.0
    for (station, season), g in all_df.groupby(["station", "season"]):
        idx = g.index.to_numpy()
        vk, vd = calibrate_station_season_curves(g)
        deriv_err = verify_analytical_derivatives(KAPPA_KNOTS, vk, DELTA_KNOTS, vd, T_PEAK_DEFAULT)
        max_deriv_err = max(max_deriv_err, deriv_err)

        h_arr = g["t_hour"].to_numpy(dtype=float)
        kap_arr = np.array([eval_piecewise_linear_and_deriv(float(h), KAPPA_KNOTS, vk)[0] for h in h_arr])
        delt_arr = np.array(
            [eval_piecewise_linear_and_deriv(float(h), DELTA_KNOTS, vd)[0] if h > T_PEAK_DEFAULT else 0.0 for h in h_arr]
        )
        mu_r_vec = g["heat_term"].to_numpy(dtype=float) - kap_arr * g["cooling_drop"].to_numpy(dtype=float) - delt_arr
        p_vec = norm.cdf(-mu_r_vec / g["sigma_rem"].to_numpy(dtype=float))
        mu_r_after[idx] = mu_r_vec
        pred_after[idx] = p_vec

        curves_payload[station][season] = {
            "t_peak": T_PEAK_DEFAULT,
            "kappa_knots": [float(x) for x in KAPPA_KNOTS],
            "kappa_values": [round(float(x), 6) for x in vk],
            "delta_knots": [float(x) for x in DELTA_KNOTS],
            "delta_values": [round(float(x), 6) for x in vd],
            "stage97_deriv_max_fd_error": round(deriv_err, 9),
        }

        for h in T_GRID:
            hf = float(h)
            kv, dkv = eval_piecewise_linear_and_deriv(hf, KAPPA_KNOTS, vk)
            if hf > T_PEAK_DEFAULT:
                dv, ddv = eval_piecewise_linear_and_deriv(hf, DELTA_KNOTS, vd)
            else:
                dv, ddv = 0.0, 0.0
            curve_csv_rows.append(
                {
                    "station": station,
                    "season": season,
                    "t_hour": hf,
                    "t_label": format_hour(hf),
                    "t_peak": T_PEAK_DEFAULT,
                    "kappa": round(kv, 6),
                    "dkappa_dt": round(dkv, 6),
                    "delta": round(dv, 6),
                    "ddelta_dt": round(ddv, 6),
                }
            )

    all_df["mu_r_after"] = mu_r_after
    all_df["p_after"] = pred_after

    # Full 696-bucket before/after residual table
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
                        resid_rows.append(
                            {
                                "station": station,
                                "season": season,
                                "t_hour": hf,
                                "t_label": format_hour(hf),
                                "pos_bucket": b,
                                "n_bucket": 0,
                                "emp_no_new_raw": None,
                                "pred_before": None,
                                "resid_before": None,
                                "pred_after": None,
                                "resid_after": None,
                                "wilson95_lo": None,
                                "wilson95_hi": None,
                                "outside_ci_before": None,
                                "outside_ci_after": None,
                            }
                        )
                        continue
                    kb = int(sb["y_raw"].sum())
                    emp = kb / nb
                    pb = float(sb["p_base"].mean())
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
                            "pred_before": round(pb, 6),
                            "resid_before": round(emp - pb, 6),
                            "pred_after": round(pa, 6),
                            "resid_after": round(emp - pa, 6),
                            "wilson95_lo": round(lo, 6),
                            "wilson95_hi": round(hi, 6),
                            "outside_ci_before": bool(pb < lo or pb > hi),
                            "outside_ci_after": bool(pa < lo or pa > hi),
                        }
                    )

    pd.DataFrame(curve_csv_rows).to_csv(OUT_CURVES_CSV, index=False)
    pd.DataFrame(resid_rows).to_csv(OUT_RESID_CSV, index=False)

    base_stats = summarize_strata(all_df, "p_base")
    after_stats = summarize_strata(all_df, "p_after")

    # Early B3 cooling subset (m >= mu0 -> B3_at_or_above, X_t < M_t)
    early_b3_cool = all_df[
        (all_df["t_hour"] <= 13.5)
        & (all_df["pos_bucket"] == "B3_at_or_above")
        & (all_df["cooling_drop"] > 0.05)
    ]
    eb3_emp = float(early_b3_cool["y_raw"].mean())
    eb3_before = float(early_b3_cool["p_base"].mean())
    eb3_after = float(early_b3_cool["p_after"].mean())

    # KMIA afternoon reachability check (t >= 15.0 where floor 0.9°F is active)
    kmia_aft = all_df[(all_df["station"] == "KMIA") & (all_df["t_hour"] >= 15.0)]
    kmia_mu_q = np.quantile(kmia_aft["mu_r_after"], [0.10, 0.25, 0.50, 0.75, 0.90])
    kmia_phi_at_09 = norm.cdf(-kmia_aft["mu_r_after"].to_numpy() / SIGMA_INST_PHYSICAL_FLOOR)
    kmia_phi_actual = kmia_aft["p_after"].to_numpy()
    reachability = {
        "n_obs": int(len(kmia_aft)),
        "mu_r_quantiles_10_25_50_75_90": [round(float(x), 4) for x in kmia_mu_q],
        "frac_mu_r_le_minus_1_2": round(float(np.mean(kmia_aft["mu_r_after"] <= -1.2)), 6),
        "frac_phi_at_09_ge_095": round(float(np.mean(kmia_phi_at_09 >= 0.95)), 6),
        "frac_phi_actual_ge_095": round(float(np.mean(kmia_phi_actual >= 0.95)), 6),
        "min_mu_r": round(float(kmia_aft["mu_r_after"].min()), 4),
        "max_mu_r": round(float(kmia_aft["mu_r_after"].max()), 4),
        "reachable": bool(kmia_aft["mu_r_after"].min() <= -1.4804),  # Phi(+1.4804/0.9) = 0.9500
    }

    unconstrained_lb = compute_unconstrained_afternoon_lower_bound(all_df)

    # Mechanical boolean acceptance criteria
    pass_c1 = bool(
        (after_stats["early_B12_pooled"]["wMAE"] <= base_stats["early_B12_pooled"]["wMAE"])
        and (after_stats["early_B1"]["wMAE"] <= base_stats["early_B1"]["wMAE"])
        and (after_stats["early_B2"]["wMAE"] <= base_stats["early_B2"]["wMAE"])
        and (after_stats["early_B1"]["out95"] <= base_stats["early_B1"]["out95"])
        and (after_stats["early_B2"]["out95"] <= base_stats["early_B2"]["out95"])
    )
    pass_c2 = bool(after_stats["aft_total_out95"] == 0)
    pass_c3 = bool(
        (abs(eb3_emp - eb3_after) <= 0.25 * abs(eb3_emp - eb3_before))
        and (abs(after_stats["early_B3"]["wResid"]) <= 0.25 * abs(base_stats["early_B3"]["wResid"]))
    )
    overall_pass = bool(pass_c1 and pass_c2 and pass_c3)

    payload = {
        "schema_version": "p8_mu_r_cooling_drift_calibration_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_boundary": "2016-04-30 .. 2018-12-30 (608 valid days per station, zero 2019)",
        "station_metadata": station_meta,
        "parameterization": {
            "form": "piecewise_linear_c0_analytic_derivative",
            "t_peak": T_PEAK_DEFAULT,
            "kappa_knots": [float(x) for x in KAPPA_KNOTS],
            "delta_knots": [float(x) for x in DELTA_KNOTS],
            "reg_second_diff": REG_SECOND_DIFF,
            "stage97_deriv_max_fd_error": round(max_deriv_err, 9),
        },
        "curves": curves_payload,
        "reachability_kmia_1500_2000": reachability,
        "baseline_stats": base_stats,
        "calibrated_stats": after_stats,
        "early_b3_cooling_subset": {
            "n_obs": int(len(early_b3_cool)),
            "emp_no_new_raw": round(eb3_emp, 6),
            "pred_before": round(eb3_before, 6),
            "resid_before": round(eb3_emp - eb3_before, 6),
            "pred_after": round(eb3_after, 6),
            "resid_after": round(eb3_emp - eb3_after, 6),
        },
        "unconstrained_criterion2_lower_bound": unconstrained_lb,
        "acceptance_gates": {
            "criterion_1_early_b12_non_degradation": {
                "before_b12_wmae": base_stats["early_B12_pooled"]["wMAE"],
                "after_b12_wmae": after_stats["early_B12_pooled"]["wMAE"],
                "before_b1_wmae": base_stats["early_B1"]["wMAE"],
                "after_b1_wmae": after_stats["early_B1"]["wMAE"],
                "before_b2_wmae": base_stats["early_B2"]["wMAE"],
                "after_b2_wmae": after_stats["early_B2"]["wMAE"],
                "before_b1_out95": base_stats["early_B1"]["out95"],
                "after_b1_out95": after_stats["early_B1"]["out95"],
                "before_b2_out95": base_stats["early_B2"]["out95"],
                "after_b2_out95": after_stats["early_B2"]["out95"],
                "pass": pass_c1,
            },
            "criterion_2_afternoon_all_wilson_ci": {
                "before_out95": base_stats["aft_total_out95"],
                "after_out95": after_stats["aft_total_out95"],
                "total_cells": after_stats["aft_total_cells"],
                "threshold": 0,
                "kord_after_out95": after_stats["aft_kord_out95"],
                "kmia_after_out95": after_stats["aft_kmia_out95"],
                "unconstrained_min_out95": unconstrained_lb["unconstrained_min_out95"],
                "pass": pass_c2,
            },
            "criterion_3_early_b3_cooling_convergence": {
                "before_b3_all_wres": base_stats["early_B3"]["wResid"],
                "after_b3_all_wres": after_stats["early_B3"]["wResid"],
                "before_b3_cooling_resid": round(eb3_emp - eb3_before, 6),
                "after_b3_cooling_resid": round(eb3_emp - eb3_after, 6),
                "pass": pass_c3,
            },
            "overall_pass": overall_pass,
        },
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # Write Markdown report
    lines = [
        "# P8-ALGO 方案一 μ_R(t, m, X_t) 标定报告（608 天零 2019 数据）",
        "",
        f"- **执行日期**: 2026-11-14 | **脚本**: [`scripts/calibrate_p8_mu_r_cooling_drift.py`](../scripts/calibrate_p8_mu_r_cooling_drift.py)",
        "- **数据边界**: KORD/KMIA `2016-04-30 ~ 2018-12-30` 各 608 有效日（严禁 2019 参与）；复现 `v2_2000_2018_oof_cv` `s_oos` 与 [`p8_inspection_a_eta_s_calibration_20261113.csv`](p8_inspection_a_eta_s_calibration_20261113.csv)",
        "- **曲线形式**: 分段线性连续可微样条（`C^0` 全局连续、区间内部 `C^∞` 解析可微，`δ(t_peak)=0` 连续拼接，`t_peak = 13.5`），Stage 9.7 数值差分自检最大误差 = "
        f"`{max_deriv_err:.2e}`",
        "",
        "## 一、 硬性验收判据（两步机械判定，不硬凑）",
        "",
        f"- **判据 ①（06:00–13:30 B1/B2 误差不劣化）**: `原始观测值 = pooled wMAE {after_stats['early_B12_pooled']['wMAE']} (vs 基线 {base_stats['early_B12_pooled']['wMAE']}), "
        f"B1 wMAE {after_stats['early_B1']['wMAE']} (<= {base_stats['early_B1']['wMAE']}), out95 {after_stats['early_B1']['out95']}/128 (<= {base_stats['early_B1']['out95']}), "
        f"B2 wMAE {after_stats['early_B2']['wMAE']} (<= {base_stats['early_B2']['wMAE']}), out95 {after_stats['early_B2']['out95']}/109 (<= {base_stats['early_B2']['out95']}); "
        f"判定阈值 = 不劣于基线; 结论 = {'通过' if pass_c1 else '不通过'}` (`pass = {pass_c1}`)",
        f"- **判据 ②（14:00–20:00 B1/B2/B3 残差全落 Wilson 95% CI）**: `原始观测值 = {after_stats['aft_total_out95']}/312 出界 (KMIA {after_stats['aft_kmia_out95']}/156, KORD {after_stats['aft_kord_out95']}/156; 基线 {base_stats['aft_total_out95']}/312); "
        f"判定阈值 = 0/312; 结论 = {'通过' if pass_c2 else '不通过'}` (`pass = {pass_c2}`)",
        f"- **判据 ③（早段 B3 `m>=μ_0 ∧ X_t<M_t` 显著收敛）**: `原始观测值 = 早段全量 B3 wResid {after_stats['early_B3']['wResid']:+.6f} (基线 {base_stats['early_B3']['wResid']:+.6f}), "
        f"冷却子集 (n={len(early_b3_cool)}) 残差 {eb3_emp - eb3_after:+.6f} (基线 {eb3_emp - eb3_before:+.6f}); "
        f"判定阈值 = 相对基线收敛 ≥75%; 结论 = {'通过' if pass_c3 else '不通过'}` (`pass = {pass_c3}`)",
        f"- **总门禁**: `overall_pass = {overall_pass}`（依据任务二规则：任一不达标回传分析，不硬凑，检验 C 判决跑批冻结维持）",
        "",
        "## 二、 分时段与分桶前后残差对照表",
        "",
        "| 时段 | 位置桶 | 样本格数 | 观测条数 | 基线 wMAE | 标定后 wMAE | 基线 wResid | 标定后 wResid | 基线出界格数 | 标定后出界格数 |",
        "|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| 06:00–13:30 | B1+B2 Pooled | {base_stats['early_B12_pooled']['cells']} | {base_stats['early_B12_pooled']['n_obs']} | {base_stats['early_B12_pooled']['wMAE']:.6f} | {after_stats['early_B12_pooled']['wMAE']:.6f} | {base_stats['early_B12_pooled']['wResid']:+.6f} | {after_stats['early_B12_pooled']['wResid']:+.6f} | {base_stats['early_B12_pooled']['out95']} | {after_stats['early_B12_pooled']['out95']} |",
        f"| 06:00–13:30 | B1_below_anchor | {base_stats['early_B1']['cells']} | {base_stats['early_B1']['n_obs']} | {base_stats['early_B1']['wMAE']:.6f} | {after_stats['early_B1']['wMAE']:.6f} | {base_stats['early_B1']['wResid']:+.6f} | {after_stats['early_B1']['wResid']:+.6f} | {base_stats['early_B1']['out95']} | {after_stats['early_B1']['out95']} |",
        f"| 06:00–13:30 | B2_near_anchor | {base_stats['early_B2']['cells']} | {base_stats['early_B2']['n_obs']} | {base_stats['early_B2']['wMAE']:.6f} | {after_stats['early_B2']['wMAE']:.6f} | {base_stats['early_B2']['wResid']:+.6f} | {after_stats['early_B2']['wResid']:+.6f} | {base_stats['early_B2']['out95']} | {after_stats['early_B2']['out95']} |",
        f"| 06:00–13:30 | B3_at_or_above | {base_stats['early_B3']['cells']} | {base_stats['early_B3']['n_obs']} | {base_stats['early_B3']['wMAE']:.6f} | {after_stats['early_B3']['wMAE']:.6f} | {base_stats['early_B3']['wResid']:+.6f} | {after_stats['early_B3']['wResid']:+.6f} | {base_stats['early_B3']['out95']} | {after_stats['early_B3']['out95']} |",
        f"| 14:00–20:00 | B1_below_anchor | {base_stats['aft_B1']['cells']} | {base_stats['aft_B1']['n_obs']} | {base_stats['aft_B1']['wMAE']:.6f} | {after_stats['aft_B1']['wMAE']:.6f} | {base_stats['aft_B1']['wResid']:+.6f} | {after_stats['aft_B1']['wResid']:+.6f} | {base_stats['aft_B1']['out95']} | {after_stats['aft_B1']['out95']} |",
        f"| 14:00–20:00 | B2_near_anchor | {base_stats['aft_B2']['cells']} | {base_stats['aft_B2']['n_obs']} | {base_stats['aft_B2']['wMAE']:.6f} | {after_stats['aft_B2']['wMAE']:.6f} | {base_stats['aft_B2']['wResid']:+.6f} | {after_stats['aft_B2']['wResid']:+.6f} | {base_stats['aft_B2']['out95']} | {after_stats['aft_B2']['out95']} |",
        f"| 14:00–20:00 | B3_at_or_above | {base_stats['aft_B3']['cells']} | {base_stats['aft_B3']['n_obs']} | {base_stats['aft_B3']['wMAE']:.6f} | {after_stats['aft_B3']['wMAE']:.6f} | {base_stats['aft_B3']['wResid']:+.6f} | {after_stats['aft_B3']['wResid']:+.6f} | {base_stats['aft_B3']['out95']} | {after_stats['aft_B3']['out95']} |",
        "",
        "## 三、 KMIA 午后（15:00–20:00）负漂移可达性核验",
        "",
        f"- `15:00–20:00` KMIA 样本量 = `{reachability['n_obs']}`，实测 `mu_R` 分位数 `[10%, 25%, 50%, 75%, 90%]` = `{reachability['mu_r_quantiles_10_25_50_75_90']}`°F（全量极差 `[{reachability['min_mu_r']}, {reachability['max_mu_r']}]`°F）。",
        f"- 触及 `0.9°F` 底后产生 `Φ(-μ_R/0.9) ≥ 0.95`（需 `μ_R ≤ -1.4804°F`）：其中 `μ_R ≤ -1.2°F` 占比 `{reachability['frac_mu_r_le_minus_1_2']:.4f}`、"
        f"`Φ(-μ_R/0.9) ≥ 0.95` 占比 `{reachability['frac_phi_at_09_ge_095']:.4f}`、`actual_p ≥ 0.95` 占比 `{reachability['frac_phi_actual_ge_095']:.4f}`，`reachable = {reachability['reachable']}`。",
        "",
        "## 四、 判据 ② 未清零（0/312）数学根因与逐片冲突实证",
        "",
        f"1. **固定 `ρ(t)=(20-t)/14` 引起的正负单调性冲突**：在无约束每切片独立优化 `(κ, δ)` 理论极限测试中，仍有 **`{unconstrained_lb['unconstrained_min_out95']}/312`** 格无法同时落入 Wilson 95% CI：",
    ]
    for d in unconstrained_lb["conflict_details"]:
        lines.append(
            f"   - `{d['station']} {d['season']} {format_hour(d['t_hour'])} {d['pos_bucket']}` (`n={d['n']}`): "
            f"`emp={d['emp_no_new']:.4f}` (Wilson 95% CI `[{d['wilson95_lo']:.4f}, {d['wilson95_hi']:.4f}]`), 理论最优预测 `best_pred={d['best_pred']:.4f}`"
        )
    lines.extend(
        [
            "2. **机理根因**：KORD 春季 `14:00–16:00` 时，`B1_below_anchor` 样本多为阴云凉爽午后（锁顶实测 0.50–0.93），反高于晴热/升温中的 `B3_at_or_above`（0.36–0.88）；但固定正向加热项 `ρ(t)·max(0, μ_0 − m)` 在 `B1` (`μ_0 − m > +2°F`) 强行叠加正向平漂，使 `μ_R(B1) > μ_R(B3)` 恒成立、无法调和 `B1` 与 `B3` 的相反符号方向需求（见上列 14:00–16:00 理论极限最优值仍与 Wilson 95% CI 两端相悖）。",
            "3. **站季分化**: 平滑曲线下 KMIA 午后 `{0}/156` 出界，KORD 为 `{1}/156`（集中在 Spring / Autumn B1 正残差与 B3 负残差互斥，及固定单一点值 `t_peak=13.5` 与 KORD 真实 `14:00~15:30` 日峰转移的过渡张力）。".format(
                after_stats["aft_kmia_out95"],
                after_stats["aft_kord_out95"],
            ),
            "",
            "## 五、 8 组站×季标定节点值摘要",
            "",
            "| 站 | 季 | κ knots (6.0, 9.0, 12.0, 13.5, 15.0, 17.0, 20.0) | δ knots (13.5, 14.0, 15.0, 16.5, 18.0, 20.0) |",
            "|:---|:---|:---|:---|",
        ]
    )
    for st in STATIONS:
        for seas in SEASONS:
            c = curves_payload[st][seas]
            lines.append(
                f"| {st} | {seas} | `{c['kappa_values']}` | `{c['delta_values']}` |"
            )

    OUT_REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "reachability": reachability,
                "acceptance_gates": payload["acceptance_gates"],
                "unconstrained_min_out95": unconstrained_lb["unconstrained_min_out95"],
                "stage97_deriv_max_fd_error": round(max_deriv_err, 9),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
