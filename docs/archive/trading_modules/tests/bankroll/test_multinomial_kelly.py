"""
Unit tests for Multinomial Kelly SLSQP Optimizer with Sunk-Cost Incremental Sizing (Phase 2 Task 05 - Ticket 03 / Issue #85).
Implements Phase 2 Execution Document v2.0 §4.3.
"""

import numpy as np
import pytest

from src.bankroll.multinomial_kelly import (
    KellyAllocationResult,
    MultinomialKellyOptimizer,
    MultinomialKellyConfig,
)


class TestMultinomialKellyOptimizer:
    """Test suite for incremental multinomial log-wealth maximization."""

    @pytest.fixture
    def optimizer(self):
        return MultinomialKellyOptimizer()

    def test_single_favorable_outcome_sizing(self, optimizer):
        """
        Verify Kelly allocation on a simple 2-outcome market:
        Outcome 1: p=0.60, price q=0.40 (Edge = 50%, EV = +0.20)
        Outcome 2: p=0.40, price q=0.60 (Negative EV)
        With W_free=1000, Kelly should allocate positively to Outcome 1, zero to Outcome 2.
        """
        res: KellyAllocationResult = optimizer.optimize(
            probabilities=[0.60, 0.40],
            prices=[0.40, 0.60],
            w_free=1000.0,
            max_allocable=500.0,
        )

        assert res.success is True
        f = res.optimal_allocations
        assert len(f) == 2
        assert f[0] > 50.0  # Significant positive allocation to +EV outcome
        assert f[1] == pytest.approx(0.0, abs=1e-3)  # Zero to negative EV outcome
        assert sum(f) <= 500.0

    def test_sunk_cost_natural_hedging_on_probability_flip(self, optimizer):
        """
        Verify Test-Scenario A logic:
        Previous position: Bought Outcome 1 heavily ($100 payout if Outcome 1 wins, N_1=100).
        Sudden cold front arrives: Probability flips to Outcome 2 (p_1=0.10, p_2=0.90).
        Prices: q_1=0.10, q_2=0.40.
        Optimizer must naturally allocate to Outcome 2 without forced market dump of Outcome 1!
        """
        res: KellyAllocationResult = optimizer.optimize(
            probabilities=[0.10, 0.90],
            prices=[0.10, 0.40],
            existing_payouts=[100.0, 0.0],  # Sunk-cost old holding: N_1=100, N_2=0
            w_free=1000.0,
            max_allocable=300.0,
        )

        assert res.success is True
        f = res.optimal_allocations
        assert f[0] == pytest.approx(0.0, abs=1e-3)  # No addition to degraded outcome
        assert f[1] > 100.0                          # New money shifts naturally to favored outcome
        assert sum(f) <= 300.0

    def test_all_negative_ev_allocates_zero(self, optimizer):
        """Verify when all market prices are overpriced (negative EV), allocation is all zeros."""
        res = optimizer.optimize(
            probabilities=[0.25, 0.25, 0.25, 0.25],
            prices=[0.30, 0.30, 0.30, 0.30],  # Overpriced: sum(q) = 1.20
            w_free=1000.0,
            max_allocable=200.0,
        )

        assert res.success is True
        assert all(f == pytest.approx(0.0, abs=1e-4) for f in res.optimal_allocations)
        assert res.total_allocation == pytest.approx(0.0, abs=1e-4)

    def test_optimizer_fallback_on_invalid_inputs(self, optimizer):
        """Verify optimizer fails closed with zero vector on dimension mismatch or invalid probs."""
        # Dimension mismatch
        res1 = optimizer.optimize(
            probabilities=[0.60, 0.40],
            prices=[0.50],  # Only 1 price
            w_free=1000.0,
        )
        assert res1.success is False
        assert res1.optimal_allocations == [0.0, 0.0]

        # Non-positive w_free
        res2 = optimizer.optimize(
            probabilities=[0.50, 0.50],
            prices=[0.40, 0.40],
            w_free=-100.0,
        )
        assert res2.success is False
        assert res2.optimal_allocations == [0.0, 0.0]
