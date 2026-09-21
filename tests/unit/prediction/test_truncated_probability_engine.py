"""
Unit tests for TruncatedProbabilityEngine (Phase 2 Task 04 - Ticket 02 / Issue #78).
Implements ADR-0011 and Phase 2 Execution Document v2.0 §1 dynamic truncation and simplex re-normalization.
"""

import numpy as np
import pytest

from src.prediction.discrete_bin_engine import DiscreteBinEngine
from src.prediction.truncated_probability_engine import (
    TruncatedProbabilityEngine,
    TruncationResult,
)


class TestTruncatedProbabilityEngine:
    """Test suite for physical extreme truncation and condition simplex re-normalization."""

    @pytest.fixture
    def standard_bins(self):
        # Center=70, 5 exact bins -> <=67°F, 68°F, 69°F, 70°F, 71°F, 72°F, >=73°F
        bins = DiscreteBinEngine.generate_standard_bins(center_temp_f=70, num_exact_bins=5)
        # Prior: mu=70.0, sigma=2.0
        return DiscreteBinEngine.calculate_bin_probabilities(mu=70.0, sigma=2.0, bins=bins)

    def test_tmax_truncation_dead_bins_zeroed_and_simplex_preserved(self, standard_bins):
        """
        Verify for TMAX: when T_obs = 69.6°F:
        - <=67°F (upper=67.5 <= 69.6) -> P = 0.0
        - 68°F (upper=68.5 <= 69.6) -> P = 0.0
        - 69°F (upper=69.5 <= 69.6) -> P = 0.0
        - 70°F and above survive and re-normalize to sum == 1.0.
        """
        engine = TruncatedProbabilityEngine()
        result: TruncationResult = engine.apply_truncation(
            bins=standard_bins,
            target_type="max",
            observed_extreme_f=69.6,
        )

        evaluated = result.bins
        # Check dead bins
        assert evaluated[0].probability == 0.0  # <=67°F
        assert evaluated[1].probability == 0.0  # 68°F
        assert evaluated[2].probability == 0.0  # 69°F

        # Check surviving bins have positive probability and sum to 1.0
        alive_probs = [b.probability for b in evaluated[3:]]
        assert all(p > 0.0 for p in alive_probs)
        assert sum(b.probability for b in evaluated) == pytest.approx(1.0, abs=1e-6)

        assert 0 in result.dead_bin_indices
        assert 1 in result.dead_bin_indices
        assert 2 in result.dead_bin_indices

    def test_tmin_truncation_dead_bins_zeroed_and_simplex_preserved(self, standard_bins):
        """
        Verify for TMIN: when T_obs = 70.4°F:
        - >=73°F (lower=72.5 >= 70.4) -> P = 0.0
        - 72°F (lower=71.5 >= 70.4) -> P = 0.0
        - 71°F (lower=70.5 >= 70.4) -> P = 0.0
        - 70°F and below survive and re-normalize to sum == 1.0.
        """
        engine = TruncatedProbabilityEngine()
        result: TruncationResult = engine.apply_truncation(
            bins=standard_bins,
            target_type="min",
            observed_extreme_f=70.4,
        )

        evaluated = result.bins
        # Check dead bins
        assert evaluated[4].probability == 0.0  # 71°F (lower=70.5 >= 70.4)
        assert evaluated[5].probability == 0.0  # 72°F (lower=71.5 >= 70.4)
        assert evaluated[6].probability == 0.0  # >=73°F (lower=72.5 >= 70.4)

        # Check surviving bins sum to 1.0
        assert sum(b.probability for b in evaluated) == pytest.approx(1.0, abs=1e-6)
        assert 4 in result.dead_bin_indices
        assert 5 in result.dead_bin_indices
        assert 6 in result.dead_bin_indices

    def test_monotonic_dead_bin_locking_across_multiple_ticks(self, standard_bins):
        """Verify dead bins are permanently locked even if a lower observation is later reported."""
        engine = TruncatedProbabilityEngine()

        # Step 1: TMAX reached 68.6°F -> <=67°F and 68°F die
        res1 = engine.apply_truncation(standard_bins, target_type="max", observed_extreme_f=68.6)
        assert 0 in res1.dead_bin_indices
        assert 1 in res1.dead_bin_indices

        # Step 2: Aberrant lower observation reported (e.g. 65.0°F) -> dead bins MUST REMAIN DEAD
        res2 = engine.apply_truncation(res1.bins, target_type="max", observed_extreme_f=65.0)
        assert res2.bins[0].probability == 0.0
        assert res2.bins[1].probability == 0.0
        assert 0 in res2.dead_bin_indices
        assert 1 in res2.dead_bin_indices

    def test_extreme_blowout_overflow_all_probability_to_tail(self, standard_bins):
        """Verify if observation blows out all exact bins, tail bin absorbs 1.0."""
        engine = TruncatedProbabilityEngine()
        # TMAX reaches 95.0°F (far above highest bin >=73°F)
        res = engine.apply_truncation(standard_bins, target_type="max", observed_extreme_f=95.0)

        # All bins except the highest tail should be dead
        for b in res.bins[:-1]:
            assert b.probability == 0.0
        assert res.bins[-1].probability == pytest.approx(1.0, abs=1e-6)
