#!/usr/bin/env python3
"""
Unit tests for src/verification/weather_metrics.py.
Verifies CRPS, Reliability Diagram, Wilson intervals, PIT diagnostics, and Discrete Bins.
"""

import math
import numpy as np
import pytest
from scipy import stats

from src.verification.weather_metrics import (
    calculate_bin_probabilities,
    compute_pit_diagnostics,
    compute_reliability_diagram,
    gaussian_crps,
    generate_discrete_temperature_bins,
    wilson_score_interval,
)


class TestWilsonScoreInterval:
    def test_boundary_conditions(self):
        # 0 hits in 100 trials: upper bound should be positive but small (~3.7%)
        low, high = wilson_score_interval(0, 100, confidence=0.95)
        assert low == 0.0
        assert 0.03 < high < 0.05

        # 100 hits in 100 trials: lower bound should be near 96.3%, upper is 1.0
        low, high = wilson_score_interval(100, 100, confidence=0.95)
        assert 0.95 < low < 0.97
        assert high == 1.0

        # Empty trials
        low, high = wilson_score_interval(0, 0)
        assert low == 0.0 and high == 0.0

    def test_standard_binomial_interval(self):
        # 50 hits in 100 trials: symmetric around 0.50
        low, high = wilson_score_interval(50, 100, confidence=0.95)
        assert abs((low + high) / 2.0 - 0.50) < 1e-4
        assert 0.40 < low < 0.41
        assert 0.59 < high < 0.61


class TestGaussianCRPS:
    def test_zero_error_perfect_prediction(self):
        # If observation equals mean and sigma is tiny, CRPS approaches 0
        score = gaussian_crps(obs=70.0, mu=70.0, sigma=1e-6)
        assert score < 1e-4

    def test_scaling_property(self):
        # When y == mu, z = 0, CRPS(mu, mu, sigma) = sigma * (sqrt(2) - 1) / sqrt(pi)
        sigma = 4.0
        expected = sigma * (math.sqrt(2.0) - 1.0) / math.sqrt(math.pi)
        actual = gaussian_crps(obs=50.0, mu=50.0, sigma=sigma)
        assert abs(actual - expected) < 1e-5


class TestReliabilityDiagram:
    def test_perfect_calibration_synthetic(self):
        # Generate 10000 predictions drawn from a calibrated Bernoulli process
        np.random.seed(42)
        n = 10000
        probs = np.random.uniform(0.0, 1.0, n)
        hits = (np.random.uniform(0.0, 1.0, n) < probs).astype(int)

        result = compute_reliability_diagram(probs, hits, bin_step=0.05)
        assert result["total_samples"] == n
        assert len(result["bins"]) == 20
        # ECE should be very small for a truly calibrated synthetic generator
        assert result["ece"] < 0.02

        # Sum of counts across bins equals total_samples
        total_count = sum(b["sample_count"] for b in result["bins"])
        assert total_count == n

    def test_empty_input(self):
        result = compute_reliability_diagram([], [])
        assert result["total_samples"] == 0
        assert result["ece"] == 0.0


class TestPITDiagnostics:
    def test_uniform_distribution_ideal(self):
        np.random.seed(42)
        n = 5000
        # Perfect normal draws
        mu = np.full(n, 70.0)
        sigma = np.full(n, 3.0)
        obs = np.random.normal(loc=mu, scale=sigma)

        diag = compute_pit_diagnostics(obs, mu, sigma, num_bins=10)
        assert abs(diag["pit_mean"] - 0.50) < 0.02
        assert abs(diag["pit_std"] - 0.2887) < 0.02
        assert "WELL_CALIBRATED" in diag["diagnosis"]

    def test_overdispersed_variance_flags_dome(self):
        np.random.seed(42)
        n = 2000
        # Model predicts sigma=10.0, but true errors only have std=3.0
        mu = np.full(n, 70.0)
        sigma = np.full(n, 10.0)
        obs = np.random.normal(loc=70.0, scale=3.0, size=n)

        diag = compute_pit_diagnostics(obs, mu, sigma, num_bins=10)
        # Standard deviation will collapse towards middle
        assert diag["pit_std"] < 0.22
        assert "OVERDISPERSED_DOME" in diag["diagnosis"]


class TestDiscreteBins:
    def test_bin_probabilities_sum_to_one(self):
        bins = generate_discrete_temperature_bins(center_f=72.0, bin_width=2.0, half_bins_each_side=3)
        # Left tail + 6 inner bins + right tail = 8 bins total
        assert len(bins) == 8

        probs = calculate_bin_probabilities(mu=72.0, sigma=3.5, bins=bins)
        total_p = sum(p["prob"] for p in probs)
        assert abs(total_p - 1.0) < 1e-5
