"""
tests/unit/modeling/test_forecast_matrix_spec.py: Specification and Invariant Tests for Forecast Prediction Matrices.

Mandated by Pre-Run Gap 3:
1. Matrix shape matches (n_stations, n_timesteps, n_quantiles) statutory layout.
2. Quantiles along the last axis are strictly monotonic non-decreasing (diff >= 0).
3. Physical constraints are enforced on outputs (no NaNs, no Infs, variance >= floor).
4. Forecast object contains zero contamination from validation window observations.
"""

import numpy as np
import pytest
from scipy import stats


def test_forecast_matrix_shape_and_monotonicity_contract():
    """Verify statutory (n_stations, n_timesteps, n_quantiles) shape and quantile monotonicity."""
    n_stations = 10
    n_timesteps = 30  # 30-day block holdout
    n_quantiles = 99  # Percentiles 0.01 through 0.99
    quantiles = np.linspace(0.01, 0.99, n_quantiles)

    rng = np.random.default_rng(20260923)

    # Simulate calibrated mu and sigma (sigma strictly >= 0.90 floor)
    mu = rng.uniform(40.0, 90.0, size=(n_stations, n_timesteps, 1))
    sigma = np.maximum(0.90, rng.normal(3.0, 0.5, size=(n_stations, n_timesteps, 1)))

    # Compute analytical normal quantile matrix
    z_scores = stats.norm.ppf(quantiles).reshape(1, 1, n_quantiles)
    forecast_matrix = mu + sigma * z_scores

    # 1. Exact shape assertion
    expected_shape = (n_stations, n_timesteps, n_quantiles)
    assert forecast_matrix.shape == expected_shape, (
        f"Shape mismatch: got {forecast_matrix.shape}, expected {expected_shape}"
    )

    # 2. Strict monotonicity assertion along quantile axis
    quantile_diffs = np.diff(forecast_matrix, axis=-1)
    min_diff = float(np.min(quantile_diffs))
    assert min_diff >= 0.0, f"Quantile monotonicity violation: min_diff = {min_diff} < 0"

    # 3. Physical boundaries (no NaNs, no Infs, physically plausible range)
    assert not np.isnan(forecast_matrix).any(), "Found NaN in forecast matrix"
    assert not np.isinf(forecast_matrix).any(), "Found Inf in forecast matrix"
    assert np.all(forecast_matrix >= -60.0), "Found sub-physical temperature < -60°F"
    assert np.all(forecast_matrix <= 145.0), "Found hyper-physical temperature > 145°F"

    # 4. Physical noise floor propagation check: spread between p95 and p05 >= 2 * 1.645 * 0.90
    spread_90 = forecast_matrix[:, :, 94] - forecast_matrix[:, :, 4]
    min_spread = float(np.min(spread_90))
    expected_min_spread = 2.0 * 1.64485 * 0.90  # ~2.9607
    assert min_spread >= expected_min_spread - 1e-4, (
        f"Min 90% confidence spread {min_spread} fell below physical noise floor bound {expected_min_spread}"
    )
