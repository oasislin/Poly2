#!/usr/bin/env python3
"""
scripts/fit_r6_kmia_correction.py: R-6 KMIA Asymmetric Convective Cold Bias Correction.

STRICT RED-LINE RULES:
1. All parameters fitted EXCLUSIVELY on 2000-2018 training window (6,940 station-days).
2. NO LOOKAHEAD: 2019 data is strictly untouched.
3. INVARIANCE REQUIREMENT: mu forecast and overall MAE must NOT be degraded.
4. VARIANCE RATIO CONSTRAINT: Variance ratio must NOT be worsened (must not shift upward from 1.1776).
5. PRIMARY OBJECTIVE: Elevate randomized PIT Kolmogorov-Smirnov p-value >= 0.05.

Outputs:
- evidence/r6_kmia_parameters.json
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
EVIDENCE_DIR = PROJECT_ROOT / "evidence"


def compute_sha256(file_path: Path) -> str:
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest()


def main():
    print("================================================================================")
    print("   R-6 KMIA ASYMMETRIC CONVECTIVE COLD BIAS FITTING (2000-2018 TRAIN ONLY)      ")
    print("================================================================================")

    if not TRAIN_PARQUET.exists():
        raise FileNotFoundError(f"Training arrays {TRAIN_PARQUET} not found.")

    df_train = pd.read_parquet(TRAIN_PARQUET)
    kmia_train = df_train[df_train["station"] == "KMIA"].copy()
    n_samples = len(kmia_train)
    print(f"Loaded KMIA 2000-2018 training data: N={n_samples} days.")

    r_cal = kmia_train["resid_calibrated"].to_numpy()
    sig_f = kmia_train["sigma_forecast"].to_numpy()
    z_raw = r_cal / sig_f

    # 1. Baseline Gaussian Evaluation on Train
    pit_gauss = stats.norm.cdf(z_raw)
    ks_gauss = stats.kstest(pit_gauss, "uniform")
    print(f"Train Baseline Gaussian: KS stat={ks_gauss.statistic:.4f}, p-val={ks_gauss.pvalue:.4e}")
    print(f"Train Residual Skewness: {stats.skew(r_cal):.4f}, Kurtosis: {stats.kurtosis(r_cal):.4f}")

    # 2. Fit Johnson SU (Standard 4-parameter flexible transformation for skewed/kurtotic residuals)
    # Johnson SU maps X to standard normal Z = gamma + delta * asinh((X - xi)/lambda)
    # CDF: F(x) = Phi(gamma + delta * asinh((x - xi)/lambda))
    # where gamma is skewness parameter, delta is kurtosis/tail parameter, xi is loc, lambda is scale.
    params_jsu = stats.johnsonsu.fit(z_raw)
    gamma, delta, xi, lam = params_jsu
    print(f"Fitted Johnson SU on Train: gamma={gamma:.4f}, delta={delta:.4f}, xi={xi:.4f}, lambda={lam:.4f}")

    pit_jsu = stats.johnsonsu.cdf(z_raw, *params_jsu)
    ks_jsu = stats.kstest(pit_jsu, "uniform")
    print(f"Train Johnson SU: KS stat={ks_jsu.statistic:.4f}, p-val={ks_jsu.pvalue:.4f}")

    # 3. Fit Two-Piece Asymmetric Normal (Split-Normal / Fechner distribution)
    # In meteorology, split-normal is physically motivated by differing sea-breeze convection dynamics
    # PDF: f(z) = sqrt(2/pi)/(sigma_L + sigma_R) * exp(-0.5 * (z/sigma_i)^2)
    def split_normal_nll(sig_pair: Tuple[float, float], z: np.ndarray) -> float:
        s_l, s_r = sig_pair
        if s_l <= 0.1 or s_r <= 0.1:
            return 1e9
        left = z < 0
        right = ~left
        const = np.log(s_l + s_r) + 0.5 * np.log(np.pi / 2.0)
        nll = np.sum(const + 0.5 * (z[left] / s_l) ** 2) + np.sum(const + 0.5 * (z[right] / s_r) ** 2)
        return float(nll)

    res_sn = optimize.minimize(split_normal_nll, x0=[1.2, 0.8], args=(z_raw,), bounds=[(0.2, 3.0), (0.2, 3.0)])
    s_l_fit, s_r_fit = res_sn.x
    print(f"Fitted Split-Normal on Train: sigma_L={s_l_fit:.4f} (cold excess), sigma_R={s_r_fit:.4f} (warm excess)")

    def split_normal_cdf(z: np.ndarray, s_l: float, s_r: float) -> np.ndarray:
        p = np.zeros_like(z)
        left = z < 0
        right = ~left
        denom = s_l + s_r
        # Left tail
        p[left] = (2.0 * s_l / denom) * stats.norm.cdf(z[left] / s_l)
        # Right tail
        p[right] = (s_l - s_r) / denom + (2.0 * s_r / denom) * stats.norm.cdf(z[right] / s_r)
        return p

    pit_sn = split_normal_cdf(z_raw, s_l_fit, s_r_fit)
    ks_sn = stats.kstest(pit_sn, "uniform")
    print(f"Train Split-Normal: KS stat={ks_sn.statistic:.4f}, p-val={ks_sn.pvalue:.4f}")

    # 4. Fit Skew-Normal
    a_sn, loc_sn, scale_sn = stats.skewnorm.fit(z_raw)
    pit_skewnorm = stats.skewnorm.cdf(z_raw, a_sn, loc=loc_sn, scale=scale_sn)
    ks_skewnorm = stats.kstest(pit_skewnorm, "uniform")
    print(f"Train Skew-Normal: KS stat={ks_skewnorm.statistic:.4f}, p-val={ks_skewnorm.pvalue:.4e}")

    # Export fitted R-6 parameters
    r6_output = {
        "station": "KMIA",
        "training_window": "2000-2018",
        "sample_count": n_samples,
        "raw_residual_moments": {
            "mean": float(np.mean(r_cal)),
            "std": float(np.std(r_cal)),
            "skewness": float(stats.skew(r_cal)),
            "kurtosis": float(stats.kurtosis(r_cal)),
        },
        "selected_distribution": "johnsonsu",
        "johnsonsu_parameters": {
            "gamma": float(gamma),
            "delta": float(delta),
            "xi": float(xi),
            "lambda": float(lam),
            "train_ks_stat": float(ks_jsu.statistic),
            "train_ks_p_value": float(ks_jsu.pvalue),
        },
        "split_normal_parameters": {
            "sigma_L": float(s_l_fit),
            "sigma_R": float(s_r_fit),
            "train_ks_stat": float(ks_sn.statistic),
            "train_ks_p_value": float(ks_sn.pvalue),
        },
        "skew_normal_parameters": {
            "a": float(a_sn),
            "loc": float(loc_sn),
            "scale": float(scale_sn),
            "train_ks_stat": float(ks_skewnorm.statistic),
            "train_ks_p_value": float(ks_skewnorm.pvalue),
        },
        "training_data_sha256": compute_sha256(TRAIN_PARQUET),
    }

    out_file = EVIDENCE_DIR / "r6_kmia_parameters.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(r6_output, f, indent=2)

    print(f"\nSaved R-6 KMIA parameters to {out_file}")


if __name__ == "__main__":
    main()
