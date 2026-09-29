"""
Unit tests for Settlement Hit Probability under Discretization Jitter (R3).
Verifies single source of truth against analytical expectations and boundary conditions.
"""

import math
import pytest
from src.verification.settlement import compute_settlement_hit_probability


def test_hit_probability_fully_inside():
    # Observation 70.0 is well inside [65.0, 75.0]
    p = compute_settlement_hit_probability(70.0, 65.0, 75.0, jitter_half_width=0.05)
    assert p == 1.0


def test_hit_probability_fully_outside():
    # Observation 60.0 is well outside [65.0, 75.0]
    p = compute_settlement_hit_probability(60.0, 65.0, 75.0, jitter_half_width=0.05)
    assert p == 0.0


def test_hit_probability_exact_lower_boundary():
    # Exactly on lower boundary lb=65.0
    # Jitter range is [64.95, 65.05]. Overlap with [65.0, 75.0] is [65.0, 65.05] -> length 0.05
    # Total width = 0.10 -> probability = 0.50
    p = compute_settlement_hit_probability(65.0, 65.0, 75.0, jitter_half_width=0.05)
    assert math.isclose(p, 0.5, abs_tol=1e-7)


def test_hit_probability_exact_upper_boundary():
    # Exactly on upper boundary ub=75.0
    # Jitter range is [74.95, 75.05]. Overlap with [65.0, 75.0] is [74.95, 75.0] -> length 0.05
    # Probability = 0.50
    p = compute_settlement_hit_probability(75.0, 65.0, 75.0, jitter_half_width=0.05)
    assert math.isclose(p, 0.5, abs_tol=1e-7)


def test_hit_probability_infinite_bounds():
    # Semi-infinite lower bracket: [-inf, 50.0]
    # Obs = 49.97 -> jitter [49.92, 50.02]. Overlap with [-inf, 50.0] is [49.92, 50.00] -> length 0.08 / 0.10 = 0.8
    p = compute_settlement_hit_probability(49.97, -float("inf"), 50.0, jitter_half_width=0.05)
    assert math.isclose(p, 0.8, abs_tol=1e-7)

    # Semi-infinite upper bracket: [80.0, inf]
    # Obs = 80.02 -> jitter [79.97, 80.07]. Overlap is [80.00, 80.07] -> length 0.07 / 0.10 = 0.7
    p2 = compute_settlement_hit_probability(80.02, 80.0, float("inf"), jitter_half_width=0.05)
    assert math.isclose(p2, 0.7, abs_tol=1e-7)


def test_hit_probability_partition_unity():
    # Across consecutive adjacent brackets, total hit probability for any value must sum to 1.0
    obs = 65.02  # Near boundary 65.0
    p_left = compute_settlement_hit_probability(obs, 55.0, 65.0, jitter_half_width=0.05)
    p_right = compute_settlement_hit_probability(obs, 65.0, 75.0, jitter_half_width=0.05)
    assert math.isclose(p_left + p_right, 1.0, abs_tol=1e-7)
