"""
tests/unit/prediction/test_discrete_bin_engine_2deg.py:
P4-AUDIT-PRE: Contract Verification Suite for DiscreteBinEngine 2°F Adsorbed Bins.

Specifications:
- Step size strictly 2°F; Grid lines strictly even integers.
- Daily anchored 9-bin tradeable window with center bin occupying 5th slot.
- Strictly 11 mutually exclusive and collectively exhaustive bins (1 left tail + 9 window + 1 right tail).
- X.5 continuity correction boundaries: [2k - 0.5, 2k + 1.5).
- Settlement rounding strictly half-up (math.floor(x + 0.5)), preventing Python banker's rounding bug.
- Pure CDF differencing against continuous distribution F (no approximation).
"""

import math
import numpy as np
import pytest
from scipy import stats

from src.prediction.discrete_bin_engine import (
    DiscreteBin,
    DiscreteBinEngine,
    settle_half_up,
)


def test_2deg_grid_lines_strictly_even_integers():
    """Verify that all 9 tradeable bins have nominal grid boundaries that are strictly even integers."""
    mu = 71.2
    bins = DiscreteBinEngine.generate_2deg_adsorbed_bins(mu=mu)
    assert len(bins) == 11, f"Expected 11 bins, got {len(bins)}"

    # Window bins are index 1 to 9
    window_bins = [b for b in bins if b.is_tradeable_window]
    assert len(window_bins) == 9

    for b in window_bins:
        assert b.nominal_temp_f is not None
        assert b.nominal_temp_f % 2 == 0, f"Bin {b.label} nominal {b.nominal_temp_f} is not an even integer"
        # Nominal temp is 2k, range covers 2k and 2k+1, upper nominal edge is 2k+2
        assert b.step_size == 2.0


def test_2deg_x5_continuity_boundary_invariants():
    """Verify continuity boundaries strictly end in .5 with zero overlap and zero gaps."""
    for mu in [32.0, 55.4, 70.0, 71.5, 98.9]:
        bins = DiscreteBinEngine.generate_2deg_adsorbed_bins(mu=mu)

        # Left tail lower bound is -inf
        assert math.isinf(bins[0].lower_bound_f) and bins[0].lower_bound_f < 0
        # Right tail upper bound is +inf
        assert math.isinf(bins[-1].upper_bound_f) and bins[-1].upper_bound_f > 0

        # Boundary chaining check: upper[i] == lower[i+1]
        for i in range(len(bins) - 1):
            assert bins[i].upper_bound_f == bins[i + 1].lower_bound_f, (
                f"Gap or overlap at boundary {i}: {bins[i].upper_bound_f} != {bins[i+1].lower_bound_f}"
            )
            # Intermediate boundaries must end in .5
            val = bins[i].upper_bound_f
            assert abs(val - math.floor(val) - 0.5) < 1e-9, f"Boundary {val} does not end in .5"


def test_center_bin_occupies_5th_slot_in_9_window():
    """Verify that the bin containing mu is strictly the 5th bin (index 4) within the 9-bin tradeable window."""
    test_mus = [45.1, 60.0, 70.9, 71.5, 82.3]
    for mu in test_mus:
        bins = DiscreteBinEngine.generate_2deg_adsorbed_bins(mu=mu)
        window_bins = [b for b in bins if b.is_tradeable_window]
        assert len(window_bins) == 9

        center_bin = window_bins[4]  # 5th slot (0-indexed 4)
        assert center_bin.lower_bound_f <= mu < center_bin.upper_bound_f, (
            f"For mu={mu}, 5th window bin [{center_bin.lower_bound_f}, {center_bin.upper_bound_f}) does not contain mu!"
        )


def test_11_bins_simplex_conservation():
    """Verify probability simplex sum == 1.0 via pure CDF differencing on arbitrary continuous distributions."""
    mu = 68.4
    sigma = 3.2
    bins = DiscreteBinEngine.generate_2deg_adsorbed_bins(mu=mu)

    # CDF function of continuous distribution
    def cdf_fn(x: float) -> float:
        return float(stats.norm.cdf(x, loc=mu, scale=sigma))

    probs = DiscreteBinEngine.calculate_2deg_bin_probabilities(bins, cdf_fn=cdf_fn)
    assert len(probs) == 11
    assert abs(sum(probs) - 1.0) < 1e-12, f"Probabilities do not sum to 1.0: {sum(probs)}"
    for p in probs:
        assert p >= 0.0


def test_tradeable_window_flagging():
    """Verify 9 tradeable bins are True and 2 tail bins are False."""
    bins = DiscreteBinEngine.generate_2deg_adsorbed_bins(mu=50.0)
    assert bins[0].is_tradeable_window is False  # Left tail
    assert bins[-1].is_tradeable_window is False  # Right tail
    for b in bins[1:10]:
        assert b.is_tradeable_window is True  # Exactly 9 window bins


def test_settlement_uses_half_up_not_bankers():
    """
    CRITICAL SETTLEMENT INVARIANT:
    Prevent Python's built-in round() banker's rounding bug (round-to-even).
    Under statutory NWS WRH half-up settlement, 68.5 must round to 69, NOT 68.
    Similarly, 70.5 must round to 71, NOT 70; 2.5 must round to 3, NOT 2.
    """
    # Demonstration of banker's rounding failure in native Python:
    assert round(68.5) == 68, "Sanity check: Python round(68.5) is indeed 68 (banker's rounding)"
    assert round(2.5) == 2, "Sanity check: Python round(2.5) is indeed 2 (banker's rounding)"

    # Statutory half-up requirement:
    assert settle_half_up(68.5) == 69, "settle_half_up(68.5) must be 69"
    assert settle_half_up(70.5) == 71, "settle_half_up(70.5) must be 71"
    assert settle_half_up(2.5) == 3, "settle_half_up(2.5) must be 3"
    assert settle_half_up(68.49) == 68, "settle_half_up(68.49) must be 68"
    assert settle_half_up(68.51) == 69, "settle_half_up(68.51) must be 69"
    assert settle_half_up(-0.5) == 0, "settle_half_up(-0.5) must be 0"
    assert settle_half_up(-1.5) == -1, "settle_half_up(-1.5) must be -1"
