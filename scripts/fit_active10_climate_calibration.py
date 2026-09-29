#!/usr/bin/env python3
"""
scripts/fit_active10_climate_calibration.py: Local Climate Skewness (R-6) & EVT Thick-Tail (R-7) Parameterization for Active 10 Stations.

Strictly adheres to D-3, D-6, R-6, R-7, and ADR-0015/0017 specifications:
1. Purely derived from 2000-2018 training window (6,940 station-days per station).
2. Zero lookahead into 2019 out-of-sample data.
3. Fits:
   - Residual moments (mean, std, skewness, kurtosis) on training residuals.
   - 4-parameter Johnson SU transformation (gamma, delta, xi, lambda) for convective/skewed distributions.
   - 5% and 95% threshold Generalized Pareto Distribution (GPD) tails for extreme event tails.
   - Theoretical EVT hybrid variance factor Var_EVT and expansion scale factor kappa_evt = sqrt(Var_EVT).
4. Outputs:
   - evidence/active10_climate_calibration.json
"""

import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Dict

import numpy as np
import pandas as pd
from scipy import integrate, stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.fit_training_variance_factors import (
    GHCN_DIR,
    SIGMA_INST_PHYSICAL_FLOOR,
    STATIONS,
    load_station_training_data,
)

EVIDENCE_DIR = PROJECT_ROOT / "evidence"
TRAIN_FACTORS_JSON = EVIDENCE_DIR / "active10_training_variance_factors.json"
OUT_CALIBRATION_JSON = EVIDENCE_DIR / "active10_climate_calibration.json"


def compute_sha256(file_path: Path) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()


def compute_evt_variance(u_l: float, u_r: float, xi_l: float, beta_l: float, xi_r: float, beta_r: float) -> float:
    """Compute theoretical variance of hybrid core + EVT GPD tail model."""
    # 1. Left tail (<= 5%)
    def f_left(x: float) -> float:
        return (u_l - x) ** 2 * 0.05 * (1.0 / beta_l) * (1.0 + xi_l * x / beta_l) ** (-1.0 / xi_l - 1.0)

    x_max_l = -beta_l / xi_l if xi_l < 0 else 50.0
    m2_l, _ = integrate.quad(f_left, 0, x_max_l * 0.9999)

    # 2. Right tail (>= 95%)
    def f_right(x: float) -> float:
        return (u_r + x) ** 2 * 0.05 * (1.0 / beta_r) * (1.0 + xi_r * x / beta_r) ** (-1.0 / xi_r - 1.0)

    x_max_r = -beta_r / xi_r if xi_r < 0 else 50.0
    m2_r, _ = integrate.quad(f_right, 0, x_max_r * 0.9999)

    # 3. Core (Gaussian baseline between u_l and u_r)
    def f_core(z: float) -> float:
        return z ** 2 * stats.norm.pdf(z)

    m2_core, _ = integrate.quad(f_core, u_l, u_r)

    var_evt = float(m2_l + m2_core + m2_r)
    return var_evt


def main():
    print("================================================================================")
    print("   ACTIVE 10 STATIONS: R-6 CLIMATE SKEWNESS & R-7 EVT TAIL PARAMETERIZATION     ")
    print("================================================================================")

    if not TRAIN_FACTORS_JSON.exists():
        raise FileNotFoundError(f"Training variance factors file {TRAIN_FACTORS_JSON} not found!")

    with open(TRAIN_FACTORS_JSON, "r", encoding="utf-8") as f:
        v_factors = json.load(f)

    calibration_results: Dict[str, Any] = {
        "metadata": {
            "title": "Active 10 Stations Local Climate Skewness (R-6) and EVT Tail (R-7) Parameterization",
            "training_window": "2000-2018",
            "training_variance_factors_sha256": compute_sha256(TRAIN_FACTORS_JSON),
            "tail_percentiles": {"left": 5.0, "right": 95.0},
        },
        "stations": {},
    }

    for station in STATIONS:
        print(f"\nProcessing Climate Calibration for {station} (2000-2018 Training Window)...")
        st_meta = v_factors[station]
        p_seasons = st_meta["seasonal_parameters"]
        c_train = st_meta["frozen_c_train"]

        df_train = load_station_training_data(station, range(2000, 2019))
        n_samples = len(df_train)

        # 1. Compute mu_raw, sigma_raw and trailing bias on training set
        mu_raw_list = []
        sig_raw_list = []
        for _, row in df_train.iterrows():
            p = p_seasons[row["season"]]
            m = p["a"] + p["b"] * row["ens_mean"]
            v = (p["c"] ** 2) + (p["d"] ** 2) * row["ens_var"]
            s = math.sqrt(max(SIGMA_INST_PHYSICAL_FLOOR ** 2, v))
            mu_raw_list.append(m)
            sig_raw_list.append(s)

        df_train["mu_raw"] = mu_raw_list
        df_train["sigma_raw"] = sig_raw_list
        df_train["resid_raw"] = df_train["obs_tmax_f"] - df_train["mu_raw"]
        df_train["trailing_bias"] = df_train["resid_raw"].shift(1).rolling(window=30, min_periods=10).mean().fillna(0.0)
        df_train["mu_forecast"] = df_train["mu_raw"] + df_train["trailing_bias"]
        df_train["resid_calibrated"] = df_train["obs_tmax_f"] - df_train["mu_forecast"]
        df_train["sigma_forecast"] = df_train["sigma_raw"] * c_train

        # Standardized residuals on training set
        z_train = (df_train["resid_calibrated"] / df_train["sigma_forecast"]).to_numpy(dtype=np.float64)

        # 2. Moments & Baseline Gaussian KS
        mean_z = float(np.mean(z_train))
        std_z = float(np.std(z_train, ddof=1))
        skew_z = float(stats.skew(z_train))
        kurt_z = float(stats.kurtosis(z_train))
        ks_gauss = stats.kstest(stats.norm.cdf(z_train), "uniform")

        print(f"  Training Residuals Moments: Mean={mean_z:+.4f}, Std={std_z:.4f}, Skew={skew_z:+.4f}, Kurt={kurt_z:+.4f}")
        print(f"  Baseline Gaussian KS stat={ks_gauss.statistic:.4f}, p={ks_gauss.pvalue:.4e}")

        # 3. R-6: Fit Johnson SU
        jsu_params = stats.johnsonsu.fit(z_train)
        gamma, delta, xi, lam = [float(x) for x in jsu_params]
        pit_jsu = stats.johnsonsu.cdf(z_train, *jsu_params)
        ks_jsu = stats.kstest(pit_jsu, "uniform")
        print(f"  R-6 Johnson SU Fit: gamma={gamma:.4f}, delta={delta:.4f}, xi={xi:.4f}, lambda={lam:.4f}")
        print(f"  Train Johnson SU KS stat={ks_jsu.statistic:.4f}, p={ks_jsu.pvalue:.4f}")

        # 4. R-7: Fit EVT Generalized Pareto Distribution (GPD) at 5% and 95% quantiles
        u_left = float(np.percentile(z_train, 5.0))
        u_right = float(np.percentile(z_train, 95.0))

        left_excess = u_left - z_train[z_train < u_left]
        right_excess = z_train[z_train > u_right] - u_right

        fit_l = stats.genpareto.fit(left_excess, floc=0)
        xi_left, _, beta_left = [float(x) for x in fit_l]

        fit_r = stats.genpareto.fit(right_excess, floc=0)
        xi_right, _, beta_right = [float(x) for x in fit_r]

        # Student-t for reference
        fit_t = stats.t.fit(z_train)
        df_t, loc_t, scale_t = [float(x) for x in fit_t]

        # Theoretical EVT variance factor
        var_evt = compute_evt_variance(u_left, u_right, xi_left, beta_left, xi_right, beta_right)
        kappa_evt = float(math.sqrt(var_evt))

        print(f"  R-7 EVT Left Tail  (<= 5%):  u_L={u_left:6.3f} | GPD xi={xi_left:6.3f}, beta={beta_left:6.3f} (N={len(left_excess)})")
        print(f"  R-7 EVT Right Tail (>= 95%): u_R={u_right:6.3f} | GPD xi={xi_right:6.3f}, beta={beta_right:6.3f} (N={len(right_excess)})")
        print(f"  R-7 Theoretical Var_EVT = {var_evt:.4f} -> Dynamic Scale Factor kappa_evt = {kappa_evt:.4f}")

        ghcn_file = GHCN_DIR / f"{station}.parquet"
        calibration_results["stations"][station] = {
            "station": station,
            "training_samples": n_samples,
            "training_window": "2000-2018",
            "ghcn_truth_sha256": compute_sha256(ghcn_file),
            "residual_moments": {
                "mean": mean_z,
                "std": std_z,
                "skewness": skew_z,
                "kurtosis": kurt_z,
                "gaussian_ks_p_value": float(ks_gauss.pvalue),
            },
            "johnsonsu_parameters": {
                "gamma": gamma,
                "delta": delta,
                "xi": xi,
                "lambda": lam,
                "train_ks_statistic": float(ks_jsu.statistic),
                "train_ks_p_value": float(ks_jsu.pvalue),
            },
            "evt_tail_parameters": {
                "u_left": u_left,
                "u_right": u_right,
                "gpd_left": {
                    "shape_xi": xi_left,
                    "scale_beta": beta_left,
                    "n_excess": len(left_excess),
                },
                "gpd_right": {
                    "shape_xi": xi_right,
                    "scale_beta": beta_right,
                    "n_excess": len(right_excess),
                },
                "student_t": {
                    "df": df_t,
                    "loc": loc_t,
                    "scale": scale_t,
                },
                "theoretical_var_evt": var_evt,
                "kappa_evt": kappa_evt,
            },
        }

    with open(OUT_CALIBRATION_JSON, "w", encoding="utf-8") as f:
        json.dump(calibration_results, f, indent=2)

    print(f"\nSaved Active 10 climate calibration parameters to {OUT_CALIBRATION_JSON}")


if __name__ == "__main__":
    main()
