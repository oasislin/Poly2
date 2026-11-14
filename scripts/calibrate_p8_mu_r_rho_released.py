#!/usr/bin/env python3
"""Recalibrate Proposal-1 mu_R(t, m, X_t) with released station x season rho_{s,se}(t).

Reuses scripts/calibrate_p8_mu_r_cooling_drift.py 608-day zero-2019 corpus and piecewise-linear
continuous differentiable basis:
    mu_R(t, m, X_t) = rho_{s,se}(t) * max(0, mu_0 - m)
                      - kappa_{s,se}(t) * max(0, M_t - X_t)
                      - delta_{s,se}(t) * 1_{t > t_peak}

where rho_{s,se}(t) is unconstrained in sign, kappa_{s,se}(t) >= 0, delta_{s,se}(t) >= 0,
and delta_{s,se}(t_peak) = 0 (closed-form derivatives verified for Stage 9.7 dp/dt).

Evaluates mechanical acceptance criteria:
- Criterion 1: 06:00-13:30 B1/B2 pooled wMAE <= Round1 (0.048242) and B1/B2 out95 <= Round1 (26, 26),
  plus check against original Inspection A baseline (0.051684 / 43 / 26).
- Criterion 2': Afternoon (14:00-20:00) pooled out95 <= 25/312 (binomial p=0.05, 99% 1-sided upper bound)
  AND |wResid| <= 0.05 separately for B1, B2, and B3; plus 3-param unconstrained per-slice bound.
- Criterion 3: Early B3 cooling subset & all early B3 |wResid| <= 25% of baseline.
"""

from __future__ import annotations

import json
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

from scripts.calibrate_p8_mu_r_cooling_drift import (
    DELTA_KNOTS,
    KAPPA_KNOTS,
    OUT_JSON as ROUND1_JSON,
    REG_SECOND_DIFF,
    T_PEAK_DEFAULT,
    build_piecewise_linear_basis,
    compute_unconstrained_afternoon_lower_bound as compute_round1_unconstrained_2param_bound,
    eval_piecewise_linear_and_deriv,
    load_608day_snapshot_frame,
    summarize_strata,
)
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

RHO_KNOTS: np.ndarray = KAPPA_KNOTS.copy()

OUT_JSON = PROJECT_ROOT / "evidence" / "p8_mu_r_rho_released_calibration_20261114.json"
OUT_CURVES_CSV = PROJECT_ROOT / "evidence" / "p8_mu_r_rho_released_curves_20261114.csv"
OUT_RESID_312_CSV = PROJECT_ROOT / "evidence" / "p8_mu_r_rho_released_residuals_312_20261114.csv"
OUT_RESID_FULL_CSV = PROJECT_ROOT / "evidence" / "p8_mu_r_rho_released_residuals_full_20261114.csv"
OUT_PLOT_SVG = PROJECT_ROOT / "evidence" / "p8_mu_r_rho_released_out95_dist_20261114.svg"
OUT_REPORT_MD = PROJECT_ROOT / "evidence" / "p8_mu_r_rho_released_report_20261114.md"

ROUND1_EARLY_B12_POOLED_WMAE_GATE: float = 0.048242
ROUND1_EARLY_B1_OUT95_GATE: int = 26
ROUND1_EARLY_B2_OUT95_GATE: int = 26
CRITERION_2_PRIME_OUT95_MAX: int = 25
CRITERION_2_PRIME_ABS_WRESID_MAX: float = 0.05


def verify_rho_derivative(knots_r: np.ndarray, vals_r: np.ndarray) -> float:
    """Compare closed-form interior drho/dt against central finite differences."""
    knot_set = set(float(k) for k in knots_r)
    eps = 1e-6
    max_err = 0.0
    for h in T_GRID:
        t = float(h)
        if any(abs(t - k) < 1e-4 for k in knot_set):
            continue
        _, dr = eval_piecewise_linear_and_deriv(t, knots_r, vals_r)
        rp = eval_piecewise_linear_and_deriv(t + eps, knots_r, vals_r)[0]
        rm = eval_piecewise_linear_and_deriv(t - eps, knots_r, vals_r)[0]
        max_err = max(max_err, abs(dr - (rp - rm) / (2.0 * eps)))
    return float(max_err)


def calibrate_station_season_rho_kappa_delta(
    sub_df: pd.DataFrame,
    round1_vk: np.ndarray,
    round1_vd: np.ndarray,
    knots_r: np.ndarray = RHO_KNOTS,
    knots_k: np.ndarray = KAPPA_KNOTS,
    knots_d: np.ndarray = DELTA_KNOTS,
    t_peak: float = T_PEAK_DEFAULT,
    reg_weight: float = REG_SECOND_DIFF,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Jointly fit unconstrained-sign rho and non-negative (kappa, delta) via Bernoulli log-loss."""
    h = sub_df["t_hour"].to_numpy(dtype=float)
    sr = sub_df["sigma_rem"].to_numpy(dtype=float)
    deficit = sub_df["heating_deficit"].to_numpy(dtype=float)
    drop = sub_df["cooling_drop"].to_numpy(dtype=float)
    y = sub_df["y_raw"].to_numpy(dtype=float)

    basis_r = build_piecewise_linear_basis(h, knots_r)
    basis_k = build_piecewise_linear_basis(h, knots_k)
    basis_d = build_piecewise_linear_basis(np.maximum(h, t_peak), knots_d)[:, 1:]
    after_mask = (h > t_peak).astype(float)

    n_r = len(knots_r)
    n_k = len(knots_k)
    n_d_free = len(knots_d) - 1

    def objective(theta: np.ndarray) -> float:
        vr = theta[:n_r]
        vk = theta[n_r : n_r + n_k]
        vd_free = theta[n_r + n_k :]
        vd_full = np.concatenate([[0.0], vd_free])
        rho_v = basis_r @ vr
        kap_v = basis_k @ vk
        delt_v = after_mask * (basis_d @ vd_free)
        mu_r = rho_v * deficit - kap_v * drop - delt_v
        p = np.clip(norm.cdf(-mu_r / sr), 1e-6, 1.0 - 1e-6)
        bce = float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))
        reg = reg_weight * float(
            np.sum(np.diff(vr, 2) ** 2)
            + np.sum(np.diff(vk, 2) ** 2)
            + np.sum(np.diff(vd_full, 2) ** 2)
        )
        return bce + reg

    vr_ramp = np.array([rho_weight(float(k)) for k in knots_r], dtype=float)
    vr_signed = np.where(knots_r >= 13.5, -0.3, vr_ramp)
    inits = [
        np.concatenate([vr_ramp, round1_vk, round1_vd[1:]]),
        np.concatenate([np.zeros(n_r), np.full(n_k, 0.5), np.full(n_d_free, 1.5)]),
        np.concatenate([vr_signed, round1_vk, round1_vd[1:]]),
    ]
    bounds = [(-10.0, 10.0)] * n_r + [(0.0, 5.0)] * n_k + [(0.0, 12.0)] * n_d_free

    best_res = None
    for x0 in inits:
        res = minimize(objective, x0, method="L-BFGS-B", bounds=bounds, options={"maxiter": 1000})
        if best_res is None or res.fun < best_res.fun:
            best_res = res

    assert best_res is not None
    vr_opt = best_res.x[:n_r]
    vk_opt = np.maximum(0.0, best_res.x[n_r : n_r + n_k])
    vd_opt = np.concatenate([[0.0], np.maximum(0.0, best_res.x[n_r + n_k :])])
    return vr_opt, vk_opt, vd_opt


def compute_unconstrained_3param_afternoon_bound(all_df: pd.DataFrame) -> Dict[str, Any]:
    """Per-(station, season, t_hour >= 14.0) unconstrained 3-param (rho in R, kappa>=0, delta>=0) CI bound."""
    aft = all_df[all_df["t_hour"] >= 14.0]
    min_out = 0
    conflict_details: List[Dict[str, Any]] = []
    slice_params: List[Dict[str, Any]] = []

    for (st, seas, hf), g in aft.groupby(["station", "season", "t_hour"]):
        sr = g["sigma_rem"].to_numpy(dtype=float)
        deficit = g["heating_deficit"].to_numpy(dtype=float)
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

        def obj(p3: np.ndarray) -> float:
            r_val, k_val, d_val = p3
            p = norm.cdf(-(r_val * deficit - k_val * drop - d_val) / sr)
            viol = 0.0
            for _, m, _, _, _, lo, hi in bucket_meta:
                pm = float(p[m].mean())
                if pm < lo:
                    viol += (lo - pm) ** 2
                elif pm > hi:
                    viol += (pm - hi) ** 2
            return viol

        inits = [
            [0.0, 0.5, 1.5],
            [-0.5, 0.5, 1.5],
            [-1.0, 1.0, 2.0],
            [rho_weight(float(hf)), 0.3, 1.5],
            [-2.0, 0.2, 1.0],
        ]
        bounds = [(-20.0, 20.0), (0.0, 20.0), (0.0, 25.0)]
        best_res = None
        for init in inits:
            r = minimize(obj, init, method="L-BFGS-B", bounds=bounds)
            if best_res is None or r.fun < best_res.fun:
                best_res = r

        assert best_res is not None
        r_val, k_val, d_val = [float(x) for x in best_res.x]
        p_opt = norm.cdf(-(r_val * deficit - k_val * drop - d_val) / sr)
        slice_params.append(
            {
                "station": st,
                "season": seas,
                "t_hour": float(hf),
                "rho_free": round(r_val, 6),
                "kappa_free": round(k_val, 6),
                "delta_free": round(d_val, 6),
            }
        )
        for b, m, nb, _, emp, lo, hi in bucket_meta:
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
        "unconstrained_3param_min_out95": int(min_out),
        "conflict_details": conflict_details,
        "negative_rho_slice_count": int(sum(1 for x in slice_params if x["rho_free"] < 0)),
        "total_afternoon_slices": int(len(slice_params)),
        "slice_params": slice_params,
    }


def _resid_to_hex(val: float, vmax: float = 0.18) -> str:
    """Diverging blue-white-red color mapping for signed residuals."""
    x = max(-1.0, min(1.0, val / vmax))
    if x >= 0.0:
        r = 255
        g = int(round(255 * (1.0 - 0.72 * x)))
        b = int(round(255 * (1.0 - 0.78 * x)))
    else:
        t = -x
        r = int(round(255 * (1.0 - 0.78 * t)))
        g = int(round(255 * (1.0 - 0.58 * t)))
        b = 255
    return f"#{r:02x}{g:02x}{b:02x}"


def make_out95_distribution_plot(resid_312_df: pd.DataFrame, out_path: Path) -> None:
    """Render dependency-free vector SVG heatmap of afternoon out95 cells: Round 1 vs Round 2."""
    hours = sorted(resid_312_df["t_hour"].unique())
    hour_labels = [format_hour(float(h)) for h in hours]
    col_keys: List[Tuple[str, str]] = [(s, b) for s in SEASONS for b in POSITION_BUCKETS]
    col_labels = [f"{s[:2]}/{b[:2]}" for s, b in col_keys]

    cell_w, cell_h = 38, 22
    panel_w = len(col_keys) * cell_w
    panel_h = len(hours) * cell_h
    pad_l, pad_t, gap_x, gap_y = 64, 58, 76, 70
    svg_w = pad_l * 2 + panel_w * 2 + gap_x + 40
    svg_h = pad_t + panel_h * 2 + gap_y + 90

    panels = [
        (0, 0, "KORD", "resid_round1", "outside_ci_round1", "KORD Round 1 (Fixed rho)"),
        (1, 0, "KORD", "resid_after", "outside_ci_after", "KORD Round 2 (Released rho_s,se)"),
        (0, 1, "KMIA", "resid_round1", "outside_ci_round1", "KMIA Round 1 (Fixed rho)"),
        (1, 1, "KMIA", "resid_after", "outside_ci_after", "KMIA Round 2 (Released rho_s,se)"),
    ]

    svg: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w}" height="{svg_h}" viewBox="0 0 {svg_w} {svg_h}" style="background:#ffffff;font-family:monospace">',
        f'<text x="{svg_w / 2:.1f}" y="26" text-anchor="middle" font-size="15" font-weight="bold" fill="#111">Afternoon (14:00-20:00) Residual Heatmap &amp; Wilson 95% CI Out-of-Bounds (X) Distribution</text>',
    ]

    for px, py, st, res_col, out_col, title in panels:
        x0 = pad_l + px * (panel_w + gap_x)
        y0 = pad_t + py * (panel_h + gap_y)
        sub = resid_312_df[resid_312_df["station"] == st]
        n_out = int(sub[out_col].sum())
        svg.append(
            f'<text x="{x0 + panel_w / 2:.1f}" y="{y0 - 10}" text-anchor="middle" font-size="12" font-weight="bold" fill="#222">{title} [out95={n_out}/156]</text>'
        )

        for i, hf in enumerate(hours):
            cy = y0 + i * cell_h
            svg.append(
                f'<text x="{x0 - 6}" y="{cy + cell_h * 0.68:.1f}" text-anchor="end" font-size="10" fill="#333">{hour_labels[i]}</text>'
            )
            for j, (seas, bkt) in enumerate(col_keys):
                cx = x0 + j * cell_w
                row = sub[(sub["season"] == seas) & (sub["t_hour"] == hf) & (sub["pos_bucket"] == bkt)]
                if row.empty:
                    continue
                val = float(row[res_col].iloc[0])
                is_out = bool(row[out_col].iloc[0])
                fill = _resid_to_hex(val)
                stroke = "#111111" if is_out else "#e0e0e0"
                sw = "1.8" if is_out else "0.6"
                svg.append(
                    f'<rect x="{cx}" y="{cy}" width="{cell_w}" height="{cell_h}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
                )
                svg.append(
                    f'<text x="{cx + cell_w / 2:.1f}" y="{cy + cell_h * 0.64:.1f}" text-anchor="middle" font-size="8.5" fill="#111">{val:+.2f}</text>'
                )
                if is_out:
                    svg.append(
                        f'<line x1="{cx + 2}" y1="{cy + 2}" x2="{cx + cell_w - 2}" y2="{cy + cell_h - 2}" stroke="#111" stroke-width="1.3" opacity="0.65"/>'
                        f'<line x1="{cx + cell_w - 2}" y1="{cy + 2}" x2="{cx + 2}" y2="{cy + cell_h - 2}" stroke="#111" stroke-width="1.3" opacity="0.65"/>'
                    )

        for sep in (3, 6, 9):
            sx = x0 + sep * cell_w
            svg.append(f'<line x1="{sx}" y1="{y0}" x2="{sx}" y2="{y0 + panel_h}" stroke="#000" stroke-width="1.5"/>')
        for j, lbl in enumerate(col_labels):
            cx = x0 + j * cell_w + cell_w / 2
            svg.append(
                f'<text x="{cx:.1f}" y="{y0 + panel_h + 14}" text-anchor="middle" font-size="9" fill="#333">{lbl}</text>'
            )

    svg.append(
        f'<text x="{pad_l}" y="{svg_h - 14}" font-size="11" fill="#444">Color scale: red (+emp&gt;pred), blue (-emp&lt;pred), clipped at +/-0.18; Black X box = outside Wilson 95% CI.</text>'
    )
    svg.append("</svg>")
    out_path.write_text("\n".join(svg), encoding="utf-8")


def main() -> int:
    round1_payload = json.loads(ROUND1_JSON.read_text(encoding="utf-8"))
    round1_curves = round1_payload["curves"]

    all_df, station_meta = load_608day_snapshot_frame()
    all_df["heating_deficit"] = np.maximum(0.0, all_df["mu_0"] - all_df["m_int"])

    # Reconstruct exact Round-1 predictions for side-by-side comparison.
    pred_round1 = np.zeros(len(all_df), dtype=float)
    mu_r_round1 = np.zeros(len(all_df), dtype=float)
    for (station, season), g in all_df.groupby(["station", "season"]):
        idx = g.index.to_numpy()
        c = round1_curves[station][season]
        vk_r1 = np.array(c["kappa_values"], dtype=float)
        vd_r1 = np.array(c["delta_values"], dtype=float)
        h_arr = g["t_hour"].to_numpy(dtype=float)
        kap_r1 = np.array([eval_piecewise_linear_and_deriv(float(h), KAPPA_KNOTS, vk_r1)[0] for h in h_arr])
        delt_r1 = np.array(
            [eval_piecewise_linear_and_deriv(float(h), DELTA_KNOTS, vd_r1)[0] if h > T_PEAK_DEFAULT else 0.0 for h in h_arr]
        )
        mr1 = g["heat_term"].to_numpy(dtype=float) - kap_r1 * g["cooling_drop"].to_numpy(dtype=float) - delt_r1
        mu_r_round1[idx] = mr1
        pred_round1[idx] = norm.cdf(-mr1 / g["sigma_rem"].to_numpy(dtype=float))
    all_df["mu_r_round1"] = mu_r_round1
    all_df["p_round1"] = pred_round1

    curves_payload: Dict[str, Dict[str, Any]] = {"KORD": {}, "KMIA": {}}
    curve_csv_rows: List[Dict[str, Any]] = []
    pred_after = np.zeros(len(all_df), dtype=float)
    mu_r_after = np.zeros(len(all_df), dtype=float)

    max_deriv_err = 0.0
    for (station, season), g in all_df.groupby(["station", "season"]):
        idx = g.index.to_numpy()
        c1 = round1_curves[station][season]
        vk_r1 = np.array(c1["kappa_values"], dtype=float)
        vd_r1 = np.array(c1["delta_values"], dtype=float)

        vr, vk, vd = calibrate_station_season_rho_kappa_delta(g, vk_r1, vd_r1)
        from scripts.calibrate_p8_mu_r_cooling_drift import verify_analytical_derivatives

        deriv_err_kd = verify_analytical_derivatives(KAPPA_KNOTS, vk, DELTA_KNOTS, vd, T_PEAK_DEFAULT)
        deriv_err_r = verify_rho_derivative(RHO_KNOTS, vr)
        deriv_err = max(deriv_err_kd, deriv_err_r)
        max_deriv_err = max(max_deriv_err, deriv_err)

        h_arr = g["t_hour"].to_numpy(dtype=float)
        rho_arr = np.array([eval_piecewise_linear_and_deriv(float(h), RHO_KNOTS, vr)[0] for h in h_arr])
        kap_arr = np.array([eval_piecewise_linear_and_deriv(float(h), KAPPA_KNOTS, vk)[0] for h in h_arr])
        delt_arr = np.array(
            [eval_piecewise_linear_and_deriv(float(h), DELTA_KNOTS, vd)[0] if h > T_PEAK_DEFAULT else 0.0 for h in h_arr]
        )
        mu_r_vec = (
            rho_arr * g["heating_deficit"].to_numpy(dtype=float)
            - kap_arr * g["cooling_drop"].to_numpy(dtype=float)
            - delt_arr
        )
        p_vec = norm.cdf(-mu_r_vec / g["sigma_rem"].to_numpy(dtype=float))
        mu_r_after[idx] = mu_r_vec
        pred_after[idx] = p_vec

        curves_payload[station][season] = {
            "t_peak": T_PEAK_DEFAULT,
            "rho_knots": [float(x) for x in RHO_KNOTS],
            "rho_values": [round(float(x), 6) for x in vr],
            "kappa_knots": [float(x) for x in KAPPA_KNOTS],
            "kappa_values": [round(float(x), 6) for x in vk],
            "delta_knots": [float(x) for x in DELTA_KNOTS],
            "delta_values": [round(float(x), 6) for x in vd],
            "stage97_deriv_max_fd_error": round(deriv_err, 9),
        }

        for h in T_GRID:
            hf = float(h)
            rv, drv = eval_piecewise_linear_and_deriv(hf, RHO_KNOTS, vr)
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

    # Early B3 cooling subset (m >= mu0 and X_t < M_t)
    early_b3_cool = all_df[
        (all_df["t_hour"] <= 13.5)
        & (all_df["pos_bucket"] == "B3_at_or_above")
        & (all_df["cooling_drop"] > 0.05)
    ]
    eb3_emp = float(early_b3_cool["y_raw"].mean())
    eb3_pbase = float(early_b3_cool["p_base"].mean())
    eb3_round1 = float(early_b3_cool["p_round1"].mean())
    eb3_after = float(early_b3_cool["p_after"].mean())

    # KMIA afternoon reachability check (t >= 15.0 where floor 0.9 degF is active)
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
        "reachable": bool(kmia_aft["mu_r_after"].min() <= -1.4804),
    }

    bound_2p = compute_round1_unconstrained_2param_bound(all_df)
    bound_3p = compute_unconstrained_3param_afternoon_bound(all_df)

    # Mechanical boolean gates
    pass_c1_vs_round1 = bool(
        (after_stats["early_B12_pooled"]["wMAE"] <= ROUND1_EARLY_B12_POOLED_WMAE_GATE)
        and (after_stats["early_B1"]["out95"] <= ROUND1_EARLY_B1_OUT95_GATE)
        and (after_stats["early_B2"]["out95"] <= ROUND1_EARLY_B2_OUT95_GATE)
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
    overall_pass = bool(pass_c1_vs_round1 and pass_c1_vs_insp_a and pass_c2_prime and pass_c3)

    # Stratified afternoon out95 table (station x season x bucket)
    out95_breakdown: List[Dict[str, Any]] = []
    for st in STATIONS:
        for seas in SEASONS:
            row_entry: Dict[str, Any] = {"station": st, "season": seas}
            for b in POSITION_BUCKETS:
                sub = resid_312_df[
                    (resid_312_df["station"] == st)
                    & (resid_312_df["season"] == seas)
                    & (resid_312_df["pos_bucket"] == b)
                ]
                row_entry[f"{b}_round1_out"] = int(sub["outside_ci_round1"].sum())
                row_entry[f"{b}_after_out"] = int(sub["outside_ci_after"].sum())
                w = sub["n_bucket"].to_numpy(dtype=float)
                row_entry[f"{b}_after_wResid"] = round(float(np.average(sub["resid_after"], weights=w)), 6)
            row_entry["total_round1_out"] = sum(row_entry[f"{b}_round1_out"] for b in POSITION_BUCKETS)
            row_entry["total_after_out"] = sum(row_entry[f"{b}_after_out"] for b in POSITION_BUCKETS)
            out95_breakdown.append(row_entry)

    remaining_out_cells = resid_312_df[resid_312_df["outside_ci_after"] == True].to_dict(orient="records")

    payload = {
        "schema_version": "p8_mu_r_rho_released_calibration_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_boundary": "2016-04-30 .. 2018-12-30 (608 valid days per station, zero 2019)",
        "station_metadata": station_meta,
        "parameterization": {
            "form": "piecewise_linear_c0_analytic_derivative_released_rho",
            "t_peak": T_PEAK_DEFAULT,
            "rho_knots": [float(x) for x in RHO_KNOTS],
            "rho_sign": "unconstrained",
            "kappa_knots": [float(x) for x in KAPPA_KNOTS],
            "delta_knots": [float(x) for x in DELTA_KNOTS],
            "reg_second_diff": REG_SECOND_DIFF,
            "stage97_deriv_max_fd_error": round(max_deriv_err, 9),
        },
        "curves": curves_payload,
        "reachability_kmia_1500_2000": reachability,
        "insp_a_baseline_stats": pbase_stats,
        "round1_fixed_rho_stats": round1_stats,
        "calibrated_released_rho_stats": after_stats,
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
        "unconstrained_reachability_bounds": {
            "round1_2param_fixed_rho_out95": int(bound_2p["unconstrained_min_out95"]),
            "round2_3param_released_rho_out95": int(bound_3p["unconstrained_3param_min_out95"]),
            "round2_3param_negative_rho_slices": f"{bound_3p['negative_rho_slice_count']}/{bound_3p['total_afternoon_slices']}",
            "round2_3param_conflicts": bound_3p["conflict_details"],
            "round2_3param_slice_params": bound_3p["slice_params"],
        },
        "afternoon_out95_breakdown": out95_breakdown,
        "remaining_afternoon_out95_cells": remaining_out_cells,
        "acceptance_gates": {
            "criterion_1_early_b12_non_degradation": {
                "round1_gate_b12_wmae": ROUND1_EARLY_B12_POOLED_WMAE_GATE,
                "after_b12_wmae": after_stats["early_B12_pooled"]["wMAE"],
                "round1_gate_b1_out95": ROUND1_EARLY_B1_OUT95_GATE,
                "after_b1_out95": after_stats["early_B1"]["out95"],
                "round1_gate_b2_out95": ROUND1_EARLY_B2_OUT95_GATE,
                "after_b2_out95": after_stats["early_B2"]["out95"],
                "insp_a_b12_wmae": pbase_stats["early_B12_pooled"]["wMAE"],
                "insp_a_b1_out95": pbase_stats["early_B1"]["out95"],
                "insp_a_b2_out95": pbase_stats["early_B2"]["out95"],
                "after_b1_wmae": after_stats["early_B1"]["wMAE"],
                "after_b2_wmae": after_stats["early_B2"]["wMAE"],
                "pass_vs_round1_gate": pass_c1_vs_round1,
                "pass_vs_insp_a_base": pass_c1_vs_insp_a,
                "pass": bool(pass_c1_vs_round1 and pass_c1_vs_insp_a),
            },
            "criterion_2_prime_afternoon_binomial_and_family_mean": {
                "round1_out95": round1_stats["aft_total_out95"],
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
                "subset_resid_round1": round(eb3_emp - eb3_round1, 6),
                "subset_resid_after": round(eb3_emp - eb3_after, 6),
                "subset_threshold_25pct_insp_a": round(0.25 * abs(eb3_emp - eb3_pbase), 6),
                "all_early_b3_wResid_insp_a_base": pbase_stats["early_B3"]["wResid"],
                "all_early_b3_wResid_round1": round1_stats["early_B3"]["wResid"],
                "all_early_b3_wResid_after": after_stats["early_B3"]["wResid"],
                "all_threshold_25pct_insp_a": round(0.25 * abs(pbase_stats["early_B3"]["wResid"]), 6),
                "pass": pass_c3,
            },
            "overall_pass": overall_pass,
        },
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # Build human-readable report
    lines = [
        "# P8-ALGO 方案一 ρ_s,se(t) 释放重标定报告（608 天零 2019 数据）",
        "",
        f"- **执行日期**: 2026-11-14 | **脚本**: [`scripts/calibrate_p8_mu_r_rho_released.py`](../scripts/calibrate_p8_mu_r_rho_released.py)",
        "- **数据边界**: KORD/KMIA `2016-04-30 ~ 2018-12-30` 各 608 有效日（严禁 2019 参与）；复用 `v2_2000_2018_oof_cv` `s_oos` 与 [`p8_inspection_a_eta_s_calibration_20261113.csv`](p8_inspection_a_eta_s_calibration_20261113.csv)",
        f"- **曲线形式**: `(ρ_s,se(t), κ_s,se(t), δ_s,se(t))` 分段线性连续可微样条（`ρ` 符号不限，`κ, δ ≥ 0`，`δ(t_peak=13.5)=0`），Stage 9.7 数值差分自检最大误差 = `{max_deriv_err:.2e}`",
        "",
        "## 一、 硬性验收判据（两步机械判定）",
        "",
        f"- **判据 ①（06:00–13:30 B1/B2 不劣化）**: 原始观测值 = `pooled wMAE {after_stats['early_B12_pooled']['wMAE']:.6f}` (`B1 out95 {after_stats['early_B1']['out95']}/128`, `B2 out95 {after_stats['early_B2']['out95']}/109`); 判定阈值 = Round-1 现基线 (`≤ {ROUND1_EARLY_B12_POOLED_WMAE_GATE:.6f}` / `≤ {ROUND1_EARLY_B1_OUT95_GATE}/128` / `≤ {ROUND1_EARLY_B2_OUT95_GATE}/109`) 且 Inspection A 原基线 (`≤ {pbase_stats['early_B12_pooled']['wMAE']:.6f}` / `≤ {pbase_stats['early_B1']['out95']}/128` / `≤ {pbase_stats['early_B2']['out95']}/109`); 结论 = `{'通过' if (pass_c1_vs_round1 and pass_c1_vs_insp_a) else '不通过'}` (`pass_vs_round1={pass_c1_vs_round1}`, `pass_vs_insp_a={pass_c1_vs_insp_a}`)",
        f"- **判据 ②′（午后 14:00–20:00 二项界 + 分族均值）**: 原始观测值 = `out95 {after_stats['aft_total_out95']}/312` (`KORD {after_stats['aft_kord_out95']}/156`, `KMIA {after_stats['aft_kmia_out95']}/156`), `B1 wResid {after_stats['aft_B1']['wResid']:+.6f}`, `B2 wResid {after_stats['aft_B2']['wResid']:+.6f}`, `B3 wResid {after_stats['aft_B3']['wResid']:+.6f}`; 判定阈值 = `out95 ≤ 25/312` 且各族 `|wResid| ≤ 0.05`; 结论 = `{'通过' if pass_c2_prime else '不通过'}` (`pass={pass_c2_prime}`: out95={pass_c2p_out95}, B1={pass_c2p_b1}, B2={pass_c2p_b2}, B3={pass_c2p_b3})",
        f"- **判据 ③（早段 B3 冷却子集收敛 ≤ 基线 25%）**: 原始观测值 = 冷却子集 `(n={len(early_b3_cool)})` 残差 `{eb3_emp - eb3_after:+.6f}` (原基线 `{eb3_emp - eb3_pbase:+.6f}`, Round-1 `{eb3_emp - eb3_round1:+.6f}`), 早段全量 B3 `wResid {after_stats['early_B3']['wResid']:+.6f}` (原基线 `{pbase_stats['early_B3']['wResid']:+.6f}`, Round-1 `{round1_stats['early_B3']['wResid']:+.6f}`); 判定阈值 = `≤ 原基线 25%` (`≤ {0.25 * abs(eb3_emp - eb3_pbase):.6f}` / `≤ {0.25 * abs(pbase_stats['early_B3']['wResid']):.6f}`); 结论 = `{'通过' if pass_c3 else '不通过'}` (`pass={pass_c3}`)",
        f"- **总门禁**: `overall_pass = {overall_pass}`",
        "",
        "## 二、 Unconstrained per-slice 可达性界对照",
        "",
        "| 优化配置 | 约束结构 | 午后出界数 (/312) | 说明 |",
        "|:---|:---|---:|:---|",
        f"| Inspection A 原基线 | 固定 `ρ(t)`, `κ=δ=0` | `{pbase_stats['aft_total_out95']}/312` | 无符号漂移与过峰衰减 |",
        f"| Round 1 样条（`ρ` 固定） | 固定 `ρ(t)=(20-t)/14`, 样条 `(κ,δ)` | `{round1_stats['aft_total_out95']}/312` | 受固定 `ρ>0` 强行正向平漂制约 |",
        f"| Round 1 无约束 2 参极限 | 每切片独立最优 `(κ,δ)`, `ρ` 固定 | `{bound_2p['unconstrained_min_out95']}/312` | 证明固定 `ρ(t)` 存在理论不可消解地板 |",
        f"| **Round 2 样条（释放 `ρ_s,se(t)`）** | **站×季平滑样条 `(ρ,κ,δ)`** | **`{after_stats['aft_total_out95']}/312`** | **`ρ` 释放为有符号站×季样条** |",
        f"| **Round 2 无约束 3 参极限** | **每切片独立最优 `(ρ,κ,δ)`** | **`{bound_3p['unconstrained_3param_min_out95']}/312`** | **`{bound_3p['negative_rho_slice_count']}/{bound_3p['total_afternoon_slices']}` 个午后切片最优 `ρ_free < 0`** |",
        "",
        "## 三、 分时段与分桶前后残差汇总对照表",
        "",
        "| 时段 | 位置桶 | 格数 | 观测条数 | Round-1 wMAE | 本轮 wMAE | Round-1 wResid | 本轮 wResid | 原基线出界 | Round-1 出界 | 本轮出界 |",
        "|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for label, key in [
        ("06:00–13:30", "early_B12_pooled"),
        ("06:00–13:30", "early_B1"),
        ("06:00–13:30", "early_B2"),
        ("06:00–13:30", "early_B3"),
        ("14:00–20:00", "aft_B1"),
        ("14:00–20:00", "aft_B2"),
        ("14:00–20:00", "aft_B3"),
    ]:
        pb = pbase_stats[key]
        r1 = round1_stats[key]
        af = after_stats[key]
        lines.append(
            f"| {label} | {key} | {af['cells']} | {af['n_obs']} | {r1['wMAE']:.6f} | {af['wMAE']:.6f} | {r1['wResid']:+.6f} | {af['wResid']:+.6f} | {pb['out95']} | {r1['out95']} | {af['out95']} |"
        )

    lines.extend(
        [
            "",
            "## 四、 午后出界（312 格）站×季×桶分布表",
            "",
            "出界分布图：[`p8_mu_r_rho_released_out95_dist_20261114.svg`](p8_mu_r_rho_released_out95_dist_20261114.svg)",
            "",
            "| 站 | 季 | B1 出界 (R1→R2) | B1 wResid | B2 出界 (R1→R2) | B2 wResid | B3 出界 (R1→R2) | B3 wResid | 合计出界 (R1→R2) |",
            "|:---|:---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in out95_breakdown:
        lines.append(
            f"| {row['station']} | {row['season']} | {row['B1_below_anchor_round1_out']}→{row['B1_below_anchor_after_out']} | {row['B1_below_anchor_after_wResid']:+.4f} | "
            f"{row['B2_near_anchor_round1_out']}→{row['B2_near_anchor_after_out']} | {row['B2_near_anchor_after_wResid']:+.4f} | "
            f"{row['B3_at_or_above_round1_out']}→{row['B3_at_or_above_after_out']} | {row['B3_at_or_above_after_wResid']:+.4f} | "
            f"{row['total_round1_out']}→{row['total_after_out']} |"
        )

    lines.extend(["", "## 五、 本轮残留出界格子明细（after out95）", ""])
    if not remaining_out_cells:
        lines.append("- 无残留出界格（0/312）。")
    else:
        lines.append("| 站 | 季 | 时分 | 桶 | n | 实测 emp | Round-1 pred | 本轮 pred | Wilson 95% CI | 本轮残差 |")
        lines.append("|:---|:---|:---|:---|---:|---:|---:|---:|:---|---:|")
        for r in remaining_out_cells:
            lines.append(
                f"| {r['station']} | {r['season']} | {r['t_label']} | {r['pos_bucket']} | {r['n_bucket']} | {r['emp_no_new_raw']:.4f} | {r['pred_round1']:.4f} | {r['pred_after']:.4f} | [{r['wilson95_lo']:.4f}, {r['wilson95_hi']:.4f}] | {r['resid_after']:+.4f} |"
            )

    lines.extend(
        [
            "",
            "## 六、 KMIA 午后（15:00–20:00）负漂移可达性核验",
            "",
            f"- `15:00–20:00` KMIA 样本量 = `{reachability['n_obs']}`，实测 `mu_R` 分位数 `[10%, 25%, 50%, 75%, 90%]` = `{reachability['mu_r_quantiles_10_25_50_75_90']}`°F，全量极差 `[{reachability['min_mu_r']}, {reachability['max_mu_r']}]`°F。",
            f"- 触底 `0.9°F` 产生 `Φ(-mu_R/0.9) ≥ 0.95`（`mu_R ≤ -1.4804°F`）：`actual_p ≥ 0.95` 占比 `{reachability['frac_phi_actual_ge_095']:.4f}`，`reachable = {reachability['reachable']}`。",
            "",
            "## 七、 8 组站×季标定节点值（ρ_s,se, κ_s,se, δ_s,se）",
            "",
            "| 站 | 季 | ρ knots `[6, 9, 12, 13.5, 15, 17, 20]` | κ knots `[6, 9, 12, 13.5, 15, 17, 20]` | δ knots `[13.5, 14, 15, 16.5, 18, 20]` |",
            "|:---|:---|:---|:---|:---|",
        ]
    )
    for st in STATIONS:
        for seas in SEASONS:
            c = curves_payload[st][seas]
            lines.append(f"| {st} | {seas} | `{c['rho_values']}` | `{c['kappa_values']}` | `{c['delta_values']}` |")

    lines.extend(
        [
            "",
            "## 八、 产物清单",
            "",
            f"- 标定汇总与判定 JSON: [`{OUT_JSON.name}`]({OUT_JSON.name})",
            f"- 样条曲线逐半小时节点与斜率 CSV: [`{OUT_CURVES_CSV.name}`]({OUT_CURVES_CSV.name})",
            f"- 312 午后桶标定前后残差表 CSV: [`{OUT_RESID_312_CSV.name}`]({OUT_RESID_312_CSV.name})",
            f"- 全量 696 桶标定前后残差表 CSV: [`{OUT_RESID_FULL_CSV.name}`]({OUT_RESID_FULL_CSV.name})",
            f"- 午后出界分布图 SVG: [`{OUT_PLOT_SVG.name}`]({OUT_PLOT_SVG.name})",
        ]
    )

    OUT_REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=== P8-ALGO RHO_S,SE(T) RELEASED CALIBRATION SUMMARY ===")
    print(json.dumps(payload["acceptance_gates"], indent=2, ensure_ascii=False))
    print("Unconstrained bounds:", json.dumps({k: v for k, v in payload["unconstrained_reachability_bounds"].items() if k not in ("round2_3param_conflicts", "round2_3param_slice_params")}, ensure_ascii=False))
    print("KMIA reachability:", json.dumps(reachability, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
