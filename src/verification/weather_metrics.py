#!/usr/bin/env python3
"""
weather_metrics.py: Pure physical and statistical verification metrics for weather probability models.
Implements WMO and NOAA standard ensemble verification:
- Continuous Ranked Probability Score (CRPS) & Continuous Ranked Probability Skill Score (CRPSS)
- Reliability Diagram with uniform binning (default 5%) and Wilson 95% Confidence Intervals
- Probability Integral Transform (PIT) histogram and variance dispersion diagnostics
- Top-1 and ±1 Neighborhood Bin Hit Rates for discrete temperature intervals
"""

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import numpy as np
import pandas as pd
from scipy import special, stats


def wilson_score_interval(k: int, n: int, confidence: float = 0.95) -> Tuple[float, float]:
    """Compute the Wilson score interval for a binomial proportion.

    Args:
        k: Number of successes (hits).
        n: Total number of trials (samples in bin).
        confidence: Confidence level (default 0.95).

    Returns:
        (lower_bound, upper_bound) clamped to [0.0, 1.0].
    """
    if n <= 0:
        return 0.0, 0.0
    if k <= 0:
        k = 0
    if k > n:
        k = n

    z = float(stats.norm.ppf(1.0 - (1.0 - confidence) / 2.0))
    p = k / n
    denom = 1.0 + (z ** 2) / n
    center = (p + (z ** 2) / (2.0 * n)) / denom
    spread = (z / denom) * math.sqrt((p * (1.0 - p) / n) + ((z ** 2) / (4.0 * (n ** 2))))

    lower = 0.0 if k == 0 else max(0.0, center - spread)
    upper = 1.0 if k == n else min(1.0, center + spread)
    return lower, upper


def gaussian_crps(
    obs: Union[float, np.ndarray, pd.Series],
    mu: Union[float, np.ndarray, pd.Series],
    sigma: Union[float, np.ndarray, pd.Series],
) -> Union[float, np.ndarray]:
    """Compute closed-form Gaussian Continuous Ranked Probability Score (Gneiting et al. 2005).

    Formula:
        CRPS(y, mu, sigma) = sigma * [ z * (2*Phi(z) - 1) + 2*phi(z) - 1/sqrt(pi) ]
    where z = (y - mu) / sigma.
    """
    y_arr = np.asarray(obs, dtype=np.float64)
    mu_arr = np.asarray(mu, dtype=np.float64)
    sigma_arr = np.asarray(sigma, dtype=np.float64)

    is_scalar = (y_arr.ndim == 0) and (mu_arr.ndim == 0) and (sigma_arr.ndim == 0)
    y_b, mu_b, sigma_b = np.broadcast_arrays(y_arr, mu_arr, sigma_arr)

    safe_sigma = np.maximum(1e-8, sigma_b)
    z = (y_b - mu_b) / safe_sigma

    inv_sqrt_pi = 1.0 / math.sqrt(math.pi)
    sqrt_2_over_pi = math.sqrt(2.0 / math.pi)
    erf_z = special.erf(z / math.sqrt(2.0))
    exp_term = sqrt_2_over_pi * np.exp(-0.5 * np.square(z))

    crps_values = safe_sigma * (z * erf_z + exp_term - inv_sqrt_pi)
    # Zero-sigma limit is exact MAE |y - mu|
    small_mask = sigma_b < 1e-8
    if np.any(small_mask):
        mae = np.abs(y_b - mu_b)
        crps_values = np.where(small_mask, mae, crps_values)

    crps_values = np.maximum(0.0, crps_values)
    if is_scalar:
        return float(crps_values.item())
    return crps_values


def compute_reliability_diagram(
    predicted_probs: Sequence[float],
    actual_hits: Sequence[int],
    bin_step: float = 0.05,
) -> Dict[str, Any]:
    """Compute reliability calibration table with uniform equal-width bins and Wilson 95% CIs.

    Args:
        predicted_probs: Sequence of predicted event probabilities in [0.0, 1.0].
        actual_hits: Sequence of binary outcomes (1 = event occurred, 0 = event did not occur).
        bin_step: Bin width (default 0.05 = 5%).

    Returns:
        Dictionary containing per-bin calibration statistics and overall Expected Calibration Error (ECE).
    """
    p_arr = np.asarray(predicted_probs, dtype=np.float64)
    y_arr = np.asarray(actual_hits, dtype=np.int32)

    if len(p_arr) != len(y_arr):
        raise ValueError(f"Lengths must match: probs={len(p_arr)}, hits={len(y_arr)}")
    if len(p_arr) == 0:
        return {"bins": [], "ece": 0.0, "total_samples": 0}

    # Generate bin edges: e.g. [0.0, 0.05, 0.10, ..., 1.00]
    num_bins = int(round(1.0 / bin_step))
    edges = [round(i * bin_step, 6) for i in range(num_bins + 1)]

    bins_data = []
    total_weighted_abs_error = 0.0
    total_samples = len(p_arr)

    for i in range(num_bins):
        low = edges[i]
        high = edges[i + 1]

        # Right-inclusive on the last bin
        if i == num_bins - 1:
            mask = (p_arr >= low) & (p_arr <= high)
        else:
            mask = (p_arr >= low) & (p_arr < high)

        count = int(np.sum(mask))
        if count > 0:
            bin_p = p_arr[mask]
            bin_y = y_arr[mask]
            mean_pred = float(np.mean(bin_p))
            hit_count = int(np.sum(bin_y))
            hit_rate = float(hit_count / count)
            calib_error = abs(mean_pred - hit_rate)
            ci_low, ci_high = wilson_score_interval(hit_count, count, confidence=0.95)
            total_weighted_abs_error += calib_error * count
        else:
            mean_pred = float((low + high) / 2.0)
            hit_count = 0
            hit_rate = 0.0
            calib_error = 0.0
            ci_low, ci_high = 0.0, 0.0

        bins_data.append({
            "bin_index": i,
            "bin_range": f"[{low:.1%}, {high:.1%})",
            "lower_edge": low,
            "upper_edge": high,
            "sample_count": count,
            "mean_predicted_prob": round(mean_pred, 5),
            "empirical_hit_count": hit_count,
            "empirical_hit_rate": round(hit_rate, 5),
            "calibration_error": round(calib_error, 5),
            "ci_95_lower": round(ci_low, 5),
            "ci_95_upper": round(ci_high, 5),
            "is_low_sample": count < 30,
        })

    ece = float(total_weighted_abs_error / total_samples) if total_samples > 0 else 0.0

    return {
        "bins": bins_data,
        "ece": round(ece, 5),
        "total_samples": total_samples,
    }


def compute_pit_diagnostics(
    obs: Sequence[float],
    mu: Sequence[float],
    sigma: Sequence[float],
    num_bins: int = 10,
) -> Dict[str, Any]:
    """Compute Probability Integral Transform (PIT) statistics and physical dispersion diagnosis.

    In a statistically well-calibrated distribution, PIT values u = Phi((y - mu) / sigma)
    follow a standard uniform distribution U(0, 1), with mean = 0.5 and std = 1 / sqrt(12) ≈ 0.2887.
    """
    obs_arr = np.asarray(obs, dtype=np.float64)
    mu_arr = np.asarray(mu, dtype=np.float64)
    sigma_arr = np.maximum(1e-8, np.asarray(sigma, dtype=np.float64))

    z = (obs_arr - mu_arr) / sigma_arr
    u = stats.norm.cdf(z)

    pit_mean = float(np.mean(u))
    pit_std = float(np.std(u, ddof=1)) if len(u) > 1 else 0.0

    # Histogram of PIT values across equal bins in [0, 1]
    hist_counts, bin_edges = np.histogram(u, bins=num_bins, range=(0.0, 1.0))
    hist_data = [
        {
            "bin": f"[{bin_edges[i]:.1f}, {bin_edges[i+1]:.1f})",
            "count": int(hist_counts[i]),
            "pct": round(float(hist_counts[i] / len(u)), 4),
        }
        for i in range(num_bins)
    ]

    # Diagnostic classification
    # Theoretical ideal: mean in [0.46, 0.54], std in [0.25, 0.32]
    diagnosis = []
    if pit_mean < 0.46:
        diagnosis.append("COLD_BIAS (Model systematically overpredicts temperatures, observations fall on low percentiles)")
    elif pit_mean > 0.54:
        diagnosis.append("WARM_BIAS (Model systematically underpredicts temperatures, observations fall on high percentiles)")

    if pit_std < 0.24:
        diagnosis.append("OVERDISPERSED_DOME (Model variance too large / overly conservative, distribution too wide)")
    elif pit_std > 0.33:
        diagnosis.append("UNDERDISPERSED_U_SHAPED (Model variance too narrow / overly confident, too many tail misses)")
    else:
        diagnosis.append("WELL_CALIBRATED_DISPERSION (Spread matches true observational uncertainty)")

    return {
        "sample_count": len(u),
        "pit_mean": round(pit_mean, 4),
        "pit_std": round(pit_std, 4),
        "ideal_mean": 0.5000,
        "ideal_std": 0.2887,
        "histogram": hist_data,
        "diagnosis": " | ".join(diagnosis),
    }


def generate_discrete_temperature_bins(
    center_f: float,
    bin_width: float = 2.0,
    half_bins_each_side: int = 4,
) -> List[Tuple[float, float, str]]:
    """Generate fixed-width temperature bins around an anchor center.

    Example for center_f=70.0, bin_width=2.0, half_bins=2:
    - (-inf, 66.0, "<= 65°F")
    - [66.0, 68.0, "66-67°F")
    - [68.0, 70.0, "68-69°F")
    - [70.0, 72.0, "70-71°F")
    - [72.0, 74.0, "72-73°F")
    - [74.0, +inf, ">= 74°F")

    Returns:
        List of (lower_bound, upper_bound, label).
    """
    c = float(round(center_f / bin_width) * bin_width)
    bins = []

    # Left tail
    lowest_inner = c - half_bins_each_side * bin_width
    highest_inner = c + half_bins_each_side * bin_width

    bins.append((-float("inf"), lowest_inner, f"< {lowest_inner:.0f}°F"))

    curr = lowest_inner
    while curr < highest_inner - 1e-6:
        nxt = curr + bin_width
        label = f"{curr:.0f} to {nxt:.0f}°F"
        bins.append((curr, nxt, label))
        curr = nxt

    # Right tail
    bins.append((highest_inner, float("inf"), f">= {highest_inner:.0f}°F"))
    return bins


def calculate_bin_probabilities(
    mu: float,
    sigma: float,
    bins: Sequence[Tuple[float, float, str]],
) -> List[Dict[str, Any]]:
    """Integrate Gaussian distribution over discrete bins."""
    loc = float(mu)
    scale = max(1e-8, float(sigma))
    results = []

    for low, high, label in bins:
        if math.isinf(low) and low < 0:
            prob = float(stats.norm.cdf(high, loc=loc, scale=scale))
        elif math.isinf(high) and high > 0:
            prob = float(1.0 - stats.norm.cdf(low, loc=loc, scale=scale))
        else:
            prob = float(stats.norm.cdf(high, loc=loc, scale=scale) - stats.norm.cdf(low, loc=loc, scale=scale))
        prob = max(0.0, min(1.0, prob))
        results.append({
            "label": label,
            "lower": low,
            "upper": high,
            "prob": prob,
        })
    return results
