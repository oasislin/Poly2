"""
tests/unit/prediction/test_w2_gate_c3_sampling.py:
Unit test suite for Phase 2 W2 Rev.1.1 Gate C3:
- Full-grid mu sampling injected into DiscreteBinEngine across Gaussian, Johnson SU, and EVT distributions.
- Assert sum(p_k) - 1.0 <= 1e-6 and outer tail bins match analytic CDF.
"""

import numpy as np
import pytest
from scipy import stats

from src.prediction.discrete_bin_engine import (
    DiscreteBin,
    DiscreteBinEngine,
)


class TestW2GateC3Sampling:
    """Test suite for Gate C3 probability simplex conservation and tail consistency."""

    @pytest.mark.parametrize("mu", [25.0, 32.5, 50.0, 68.7, 72.0, 85.3, 100.0])
    @pytest.mark.parametrize("sigma", [1.5, 3.0, 5.5])
    def test_c3_gaussian_simplex_and_outer_tails(self, mu, sigma):
        """Gaussian distribution across sampled mu grid."""
        bins = DiscreteBinEngine.generate_2deg_adsorbed_bins(mu=mu)
        assert len(bins) == 11

        def cdf_fn(x: float) -> float:
            return float(stats.norm.cdf(x, loc=mu, scale=sigma))

        probs = DiscreteBinEngine.calculate_2deg_bin_probabilities(bins, cdf_fn=cdf_fn)

        # 1. Simplex conservation: sum(p_k) - 1.0 <= 1e-6
        assert abs(sum(probs) - 1.0) <= 1e-6

        # 2. Outer tail bins match analytic CDF
        left_tail_prob = cdf_fn(bins[0].upper_bound_f)
        right_tail_prob = 1.0 - cdf_fn(bins[-1].lower_bound_f)
        assert probs[0] == pytest.approx(left_tail_prob, abs=1e-6)
        assert probs[-1] == pytest.approx(right_tail_prob, abs=1e-6)

    @pytest.mark.parametrize("mu", [40.0, 65.0, 75.0, 88.0])
    def test_c3_johnson_su_simplex_and_outer_tails(self, mu):
        """Johnson SU distribution (representing KMIA skewed regime) across sampled mu."""
        # KMIA representative JSU parameters
        a_skew = -0.5
        b_tail = 1.2
        loc = mu
        scale = 3.0

        bins = DiscreteBinEngine.generate_2deg_adsorbed_bins(mu=mu)

        def cdf_fn(x: float) -> float:
            return float(stats.johnsonsu.cdf(x, a_skew, b_tail, loc=loc, scale=scale))

        probs = DiscreteBinEngine.calculate_2deg_bin_probabilities(bins, cdf_fn=cdf_fn)

        assert abs(sum(probs) - 1.0) <= 1e-6
        assert probs[0] == pytest.approx(cdf_fn(bins[0].upper_bound_f), abs=1e-6)
        assert probs[-1] == pytest.approx(1.0 - cdf_fn(bins[-1].lower_bound_f), abs=1e-6)

    @pytest.mark.parametrize("mu", [30.0, 55.0, 70.0, 92.0])
    def test_c3_evt_hybrid_simplex_and_outer_tails(self, mu):
        """EVT-Hybrid Scheme B (conditional Gaussian core + GPD tail) across sampled mu."""
        # Hybrid CDF approximation fixture
        def cdf_fn(x: float) -> float:
            # Simple piecewise heavy-tail surrogate
            z = (x - mu) / 3.5
            if z < -2.0:
                return float(0.025 / (1.0 + 0.3 * abs(z + 2.0)) ** 4.0)
            elif z > 2.0:
                return float(1.0 - 0.025 / (1.0 + 0.3 * (z - 2.0)) ** 4.0)
            else:
                return float(stats.norm.cdf(z, loc=0, scale=1))

        bins = DiscreteBinEngine.generate_2deg_adsorbed_bins(mu=mu)
        probs = DiscreteBinEngine.calculate_2deg_bin_probabilities(bins, cdf_fn=cdf_fn)

        assert abs(sum(probs) - 1.0) <= 1e-6
        assert probs[0] == pytest.approx(cdf_fn(bins[0].upper_bound_f), abs=1e-6)
        assert probs[-1] == pytest.approx(1.0 - cdf_fn(bins[-1].lower_bound_f), abs=1e-6)
