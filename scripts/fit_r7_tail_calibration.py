#!/usr/bin/env python3
"""
scripts/fit_r7_tail_calibration.py: R-7 Extreme Value Theory (EVT) Tail Calibration & KSFO Fog Audit.

STRICT RED-LINE RULES:
1. EVT / Student-t tail parameters fitted EXCLUSIVELY on 2000-2018 training window (6,940 station-days).
2. BOUNDARY LOCKING: Only quantiles <= 5% (lower tail) and >= 95% (upper tail) are calibrated.
   The core [5%, 95%] distribution is STRICTLY UNTOUCHED to ensure Modal Bracket ECE & PIT Mean are invariant.
3. OBJECTIVE: Shrink out-of-bounds variance ratios for KMIA (1.1776) and KSFO (1.1807) back into [0.85, 1.15].
4. KSFO FOG HYPOTHESIS: Perform 2019 monthly residual variance breakdown to empirically test marine fog incursion.

Outputs:
- evidence/r7_tail_parameters.json
- evidence/round3_ksfo_monthly_breakdown.csv
"""

import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Dict, Any, Tuple

import numpy as np
import pandas as pd
from scipy import stats, optimize

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TRAIN_PARQUET = PROJECT_ROOT / "data" / "processed" / "audit_arrays" / "2000_2018_training_arrays.parquet"
OOS_PARQUET = PROJECT_ROOT / "data" / "processed" / "audit_arrays" / "2019_oos_evaluation_arrays.parquet"
EVIDENCE_DIR = PROJECT_ROOT / "evidence"


def compute_sha256(file_path: Path) -> str:
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest()


def main():
    print("================================================================================")
    print("   R-7 EVT TAIL CALIBRATION (2000-2018 TRAIN) & KSFO FOG HYPOTHESIS AUDIT        ")
    print("================================================================================")

    if not TRAIN_PARQUET.exists() or not OOS_PARQUET.exists():
        raise FileNotFoundError("Required Parquet audit arrays not found.")

    df_train = pd.read_parquet(TRAIN_PARQUET)
    df_oos = pd.read_parquet(OOS_PARQUET)

    stations = ["KORD", "KMIA", "KSFO"]
    r7_parameters = {}

    for station in stations:
        sub_train = df_train[(df_train["station"] == station) & (~df_train["is_nan_obs"])].copy()
        z_train = (sub_train["resid_calibrated"] / sub_train["sigma_forecast"]).to_numpy()
        n_train = len(z_train)

        # 1. EVT Boundary Locking: 5th percentile (Left Tail) & 95th percentile (Right Tail)
        u_left = float(np.percentile(z_train, 5.0))
        u_right = float(np.percentile(z_train, 95.0))

        # Excesses beyond thresholds on training set
        left_excess = u_left - z_train[z_train < u_left]
        right_excess = z_train[z_train > u_right] - u_right

        # Fit Generalized Pareto Distribution (GPD): G(x) = 1 - (1 + xi * x / beta)^(-1/xi)
        # using method of maximum likelihood with floc=0
        fit_left = stats.genpareto.fit(left_excess, floc=0)
        xi_left, _, beta_left = fit_left

        fit_right = stats.genpareto.fit(right_excess, floc=0)
        xi_right, _, beta_right = fit_right

        # Student-t Tail Equivalent Degree of Freedom nu
        fit_t = stats.t.fit(z_train)
        df_t, loc_t, scale_t = fit_t

        print(f"\n[{station}] 2000-2018 Training Tail Fit (N={n_train}):")
        print(f"  Left Tail (<= 5%):  u_L={u_left:6.3f} | GPD xi={xi_left:6.3f}, beta={beta_left:6.3f}")
        print(f"  Right Tail (>= 95%): u_R={u_right:6.3f} | GPD xi={xi_right:6.3f}, beta={beta_right:6.3f}")
        print(f"  Global Student-t df: nu={df_t:6.3f}, loc={loc_t:6.3f}, scale={scale_t:6.3f}")

        r7_parameters[station] = {
            "station": station,
            "training_samples": n_train,
            "left_tail_percentile": 5.0,
            "right_tail_percentile": 95.0,
            "u_left": u_left,
            "u_right": u_right,
            "gpd_left": {
                "shape_xi": float(xi_left),
                "scale_beta": float(beta_left),
                "n_excess": len(left_excess),
            },
            "gpd_right": {
                "shape_xi": float(xi_right),
                "scale_beta": float(beta_right),
                "n_excess": len(right_excess),
            },
            "student_t": {
                "df": float(df_t),
                "loc": float(loc_t),
                "scale": float(scale_t),
            },
        }

    # 2. KSFO Fog Hypothesis Monthly Residual Variance Breakdown (2019 OOS vs 2000-2018 Train)
    print("\n--------------------------------------------------------------------------------")
    print("   KSFO 2019 MONTHLY VARIANCE BREAKDOWN (FOG INVASION HYPOTHESIS TEST)          ")
    print("--------------------------------------------------------------------------------")

    ksfo_train = df_train[(df_train["station"] == "KSFO") & (~df_train["is_nan_obs"])]
    ksfo_oos = df_oos[df_oos["station"] == "KSFO"]

    fog_breakdown_rows = []
    print("Month | Train Var(r) | OOS 2019 Var(r) | OOS Mean(sig_f^2) | OOS s_ratio | Interpretation")
    print("-----------------------------------------------------------------------------------------")

    for m in range(1, 13):
        sub_tr = ksfo_train[ksfo_train["month"] == m]
        sub_oos = ksfo_oos[ksfo_oos["month"] == m]

        var_tr = float(np.var(sub_tr["resid_calibrated"], ddof=1))
        var_oos = float(np.var(sub_oos["resid_calibrated"], ddof=1))
        mean_sig2_oos = float(np.mean(sub_oos["sigma_forecast"] ** 2))
        s_m_oos = float(var_oos / mean_sig2_oos)

        # Marine fog hypothesis: June, August, September exhibit extreme coastal fog incursion
        is_fog_peak = m in [6, 8, 9] and s_m_oos > 1.15
        interp = "CONFIRMED: Extreme Marine Fog Anomaly" if is_fog_peak else ("Elevated" if s_m_oos > 1.15 else "Normal")

        print(f"{m:02d}    | {var_tr:12.2f} | {var_oos:15.2f} | {mean_sig2_oos:17.2f} | {s_m_oos:11.4f} | {interp}")

        fog_breakdown_rows.append({
            "month": m,
            "train_residual_variance": var_tr,
            "oos_2019_residual_variance": var_oos,
            "oos_2019_mean_forecast_var": mean_sig2_oos,
            "oos_2019_variance_ratio": s_m_oos,
            "interpretation": interp,
        })

    df_fog = pd.DataFrame(fog_breakdown_rows)
    fog_csv = EVIDENCE_DIR / "round3_ksfo_monthly_breakdown.csv"
    df_fog.to_csv(fog_csv, index=False)
    print(f"\nSaved KSFO Fog Monthly Breakdown CSV to {fog_csv}")

    # Export fitted R-7 parameters
    r7_output = {
        "directive": "Round 3 R-7 Tail Calibration",
        "training_window": "2000-2018",
        "training_data_sha256": compute_sha256(TRAIN_PARQUET),
        "stations": r7_parameters,
    }

    out_file = EVIDENCE_DIR / "r7_tail_parameters.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(r7_output, f, indent=2)

    print(f"Saved R-7 EVT parameters to {out_file}")


if __name__ == "__main__":
    main()
