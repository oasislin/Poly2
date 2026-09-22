"""
Unit tests for SyntheticMarketMaker (Phase 2 Task 07 - Fix Ticket 01 / Issue #101).
"""

import pytest
import numpy as np

from src.prediction.discrete_bin_engine import DiscreteBin, DiscreteBinEngine
from src.simulation.market_maker import MarketMakerConfig, SyntheticMarketMaker


@pytest.fixture
def standard_bins():
    """Generate 7 standard temperature bins centered at 70°F."""
    return DiscreteBinEngine.generate_standard_bins(center_temp_f=70, num_exact_bins=5, station_id="KORD")


@pytest.fixture
def market_maker():
    """Instantiate SyntheticMarketMaker with default configuration."""
    return SyntheticMarketMaker()


def test_naive_probabilities_simplex(market_maker, standard_bins):
    """Test that naive probabilities form a strict valid probability simplex (sum == 1.0)."""
    naive_probs = market_maker.compute_naive_probabilities(
        bins=standard_bins,
        ensemble_mean=70.0,
        ensemble_variance=4.0,
    )
    assert len(naive_probs) == len(standard_bins)
    total_p = sum(naive_probs.values())
    assert pytest.approx(total_p, abs=1e-6) == 1.0
    for p in naive_probs.values():
        assert 0.0 <= p <= 1.0


def test_order_book_spread_and_depth(market_maker, standard_bins):
    """Test that generated order books maintain empirical spreads and tiered depth."""
    order_books = market_maker.generate_market_order_books(
        station_id="KORD",
        market_id="KORD-20190101-MAX",
        bins=standard_bins,
        ensemble_mean=70.0,
        ensemble_variance=4.0,
    )

    assert len(order_books) == len(standard_bins)

    for bin_idx, ob in order_books.items():
        assert len(ob.asks) == 3
        assert len(ob.bids) == 3

        # Best ask >= best bid + 0.01
        assert ob.best_ask is not None and ob.best_bid is not None
        from decimal import Decimal
        assert ob.best_ask >= ob.best_bid + Decimal("0.01")

        # Depth price widening: Ask level 1 < level 2 < level 3
        assert ob.asks[0].price <= ob.asks[1].price <= ob.asks[2].price
        # Bid level 1 > level 2 > level 3
        assert ob.bids[0].price >= ob.bids[1].price >= ob.bids[2].price

        # Liquidity depth sizes are non-zero and tiered
        assert ob.asks[0].size == 150.0
        assert ob.asks[1].size == 250.0
        assert ob.asks[2].size == 400.0


def test_no_free_money_arbitrage(market_maker, standard_bins):
    """
    Ensure the market maker does not give away free arbitrage:
    Ask price for an event with probability p is always >= p (never selling 0.65 probability at 0.40).
    """
    naive_probs = market_maker.compute_naive_probabilities(
        bins=standard_bins,
        ensemble_mean=70.0,
        ensemble_variance=4.0,
    )

    order_books = market_maker.generate_market_order_books(
        station_id="KORD",
        market_id="KORD-20190101-MAX",
        bins=standard_bins,
        ensemble_mean=70.0,
        ensemble_variance=4.0,
    )

    for b in standard_bins:
        p_naive = naive_probs[b.bin_index]
        ob = order_books[b.bin_index]
        # Best ask should be >= p_naive (or bounded at 0.99)
        assert float(ob.best_ask) >= p_naive or float(ob.best_ask) == 0.99
        # Best bid should be <= p_naive (or bounded at 0.01)
        assert float(ob.best_bid) <= p_naive or float(ob.best_bid) == 0.01


def test_intraday_nudge(market_maker, standard_bins):
    """Test that intraday temperature observation naively shifts probabilities."""
    probs_no_obs = market_maker.compute_naive_probabilities(
        bins=standard_bins,
        ensemble_mean=70.0,
        ensemble_variance=4.0,
    )

    # If observed temp is high (75°F), upper bins should increase in naive probability
    probs_with_hot_obs = market_maker.compute_naive_probabilities(
        bins=standard_bins,
        ensemble_mean=70.0,
        ensemble_variance=4.0,
        observed_temp_f=75.0,
    )

    last_bin_idx = standard_bins[-1].bin_index
    assert probs_with_hot_obs[last_bin_idx] > probs_no_obs[last_bin_idx]
