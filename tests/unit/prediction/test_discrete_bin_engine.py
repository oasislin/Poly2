"""
Unit tests for DiscreteBinEngine and ndtr integration (Phase 2 Task 04 - Ticket 01 / Issue #77).
Implements Phase 2 Execution Document v2.0 §1 discrete probability mapping.
"""

import numpy as np
import pytest
from scipy.special import ndtr

from src.data_processing.constants import ACTIVE_10_STATIONS
from src.prediction.discrete_bin_engine import (
    DiscreteBin,
    DiscreteBinEngine,
)


class TestDiscreteBinEngine:
    """Test suite for high-precision ndtr discrete interval integration."""

    def test_standard_bins_generation(self):
        """Verify layout and boundaries of standard 1°F Polymarket bins."""
        bins = DiscreteBinEngine.generate_standard_bins(
            center_temp_f=70,
            num_exact_bins=5,
            station_id="KORD",
        )

        # 1 lte bin + 5 exact bins (68, 69, 70, 71, 72) + 1 gte bin = 7 bins
        assert len(bins) == 7
        assert bins[0].bin_type == "lte"
        assert bins[0].label == "≤67°F"
        assert bins[0].lower_bound_f == -np.inf
        assert bins[0].upper_bound_f == 67.5

        assert bins[1].bin_type == "exact"
        assert bins[1].label == "68°F"
        assert bins[1].lower_bound_f == 67.5
        assert bins[1].upper_bound_f == 68.5

        assert bins[3].label == "70°F"
        assert bins[3].lower_bound_f == 69.5
        assert bins[3].upper_bound_f == 70.5

        assert bins[-1].bin_type == "gte"
        assert bins[-1].label == "≥73°F"
        assert bins[-1].lower_bound_f == 72.5
        assert bins[-1].upper_bound_f == np.inf

    def test_invalid_station_rejected(self):
        """Verify non-active station is rejected during bin generation."""
        with pytest.raises(ValueError, match="Invalid station_id"):
            DiscreteBinEngine.generate_standard_bins(
                center_temp_f=70,
                station_id="KDCA",  # Retired station
            )

    def test_ndtr_probability_integration_and_simplex_sum(self):
        """Verify continuous gaussian (mu=70.0, sigma=3.0) integrates to simplex sum == 1.0."""
        bins = DiscreteBinEngine.generate_standard_bins(center_temp_f=70, num_exact_bins=7)
        evaluated = DiscreteBinEngine.calculate_bin_probabilities(
            mu=70.0,
            sigma=3.0,
            bins=bins,
        )

        total_prob = sum(b.probability for b in evaluated)
        assert total_prob == pytest.approx(1.0, abs=1e-6)

        # Peak probability should be at center bin 70°F
        bin_70 = next(b for b in evaluated if b.label == "70°F")
        expected_70 = ndtr((70.5 - 70.0) / 3.0) - ndtr((69.5 - 70.0) / 3.0)
        assert bin_70.probability == pytest.approx(expected_70, rel=1e-4)

        # Symmetry: 69°F and 71°F probabilities must match
        bin_69 = next(b for b in evaluated if b.label == "69°F")
        bin_71 = next(b for b in evaluated if b.label == "71°F")
        assert bin_69.probability == pytest.approx(bin_71.probability, rel=1e-5)

    def test_extreme_distribution_offset_stability(self):
        """Verify extreme distribution offset does not produce negative or NaN probabilities."""
        bins = DiscreteBinEngine.generate_standard_bins(center_temp_f=70, num_exact_bins=5)
        # Mu far to the left (mu=40.0, sigma=2.0) -> <=67°F will absorb almost 1.0
        evaluated_left = DiscreteBinEngine.calculate_bin_probabilities(
            mu=40.0,
            sigma=2.0,
            bins=bins,
        )
        assert evaluated_left[0].probability == pytest.approx(1.0, abs=1e-4)
        for b in evaluated_left[1:]:
            assert b.probability >= 0.0
            assert not np.isnan(b.probability)

        # Mu far to the right (mu=100.0, sigma=2.0) -> >=73°F will absorb almost 1.0
        evaluated_right = DiscreteBinEngine.calculate_bin_probabilities(
            mu=100.0,
            sigma=2.0,
            bins=bins,
        )
        assert evaluated_right[-1].probability == pytest.approx(1.0, abs=1e-4)
        for b in evaluated_right[:-1]:
            assert b.probability >= 0.0
            assert not np.isnan(b.probability)

    def test_sigma_positive_constraint(self):
        """Verify non-positive sigma raises ValueError."""
        bins = DiscreteBinEngine.generate_standard_bins(center_temp_f=70)
        with pytest.raises(ValueError, match="sigma must be strictly positive"):
            DiscreteBinEngine.calculate_bin_probabilities(mu=70.0, sigma=0.0, bins=bins)
        with pytest.raises(ValueError, match="sigma must be strictly positive"):
            DiscreteBinEngine.calculate_bin_probabilities(mu=70.0, sigma=-1.5, bins=bins)
