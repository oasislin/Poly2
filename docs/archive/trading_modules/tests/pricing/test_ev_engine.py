"""
Unit tests for DynamicEVEngine and OrderBook Depth Penetration (Phase 2 Task 04 - Ticket 04 / Issue #80).
Implements Phase 2 Execution Document v2.0 §2 microstructural EV calculations.
"""

import pytest

from src.pricing.ev_engine import (
    DynamicEVEngine,
    EVConfig,
    EVTradeSignal,
    OrderBookLevel,
    OrderBookSnapshot,
)


class TestDynamicEVEngine:
    """Test suite for orderbook depth penetration and dynamic EV calculations."""

    @pytest.fixture
    def engine(self):
        config = EVConfig(min_reprice_edge=0.03, fee_rate=0.0)
        return DynamicEVEngine(config=config)

    def test_effective_price_calculation_with_depth_penetration(self, engine):
        """Verify VWAP cost calculation across multiple orderbook ask levels."""
        asks = [
            OrderBookLevel(price=0.40, size=50.0),   # 50 shares @ $0.40 = $20.00
            OrderBookLevel(price=0.42, size=50.0),   # 50 shares @ $0.42 = $21.00
            OrderBookLevel(price=0.50, size=100.0),  # 100 shares @ $0.50
        ]
        # Target 100 shares -> 50@0.40 + 50@0.42 = 41.00 / 100 = $0.4100
        p_eff = engine.calculate_effective_price(asks=asks, target_size=100.0)
        assert p_eff == pytest.approx(0.41, abs=1e-4)

    def test_insufficient_depth_rejection(self, engine):
        """Verify None is returned when available ask depth is less than target size."""
        asks = [OrderBookLevel(price=0.40, size=30.0)]
        p_eff = engine.calculate_effective_price(asks=asks, target_size=100.0)
        assert p_eff is None

    def test_positive_ev_trade_signal_generation(self, engine):
        """
        Verify positive EV signal generation when model_prob > effective_price + margin.
        Model Prob = 0.55
        Effective Ask = 0.40 (Edge = (0.55 - 0.40) / 0.40 = 0.375 >= 0.03) -> Tradable.
        """
        book = OrderBookSnapshot(
            station_id="KORD",
            bin_index=3,
            bin_label="70°F",
            bids=[OrderBookLevel(price=0.38, size=100.0)],
            asks=[OrderBookLevel(price=0.40, size=100.0)],
        )

        signal: EVTradeSignal = engine.evaluate_bin(
            snapshot=book,
            model_probability=0.55,
            target_size=50.0,
        )

        assert signal.is_tradable is True
        assert signal.effective_price == pytest.approx(0.40, abs=1e-4)
        assert signal.net_ev == pytest.approx(0.15, abs=1e-4)  # 0.55 - 0.40 = 0.15
        assert signal.edge == pytest.approx(0.375, abs=1e-4)   # 0.15 / 0.40 = 0.375
        assert signal.reason == "APPROVED_POSITIVE_EV"

    def test_negative_ev_rejection(self, engine):
        """
        Verify rejection when model_prob < effective_price.
        Model Prob = 0.30, Ask = 0.40 -> EV = -0.10 -> Negative EV Rejected.
        """
        book = OrderBookSnapshot(
            station_id="KLGA",
            bin_index=2,
            bin_label="69°F",
            bids=[OrderBookLevel(price=0.35, size=100.0)],
            asks=[OrderBookLevel(price=0.40, size=100.0)],
        )

        signal: EVTradeSignal = engine.evaluate_bin(
            snapshot=book,
            model_probability=0.30,
            target_size=50.0,
        )

        assert signal.is_tradable is False
        assert signal.net_ev < 0.0
        assert signal.reason == "REJECTED_NEGATIVE_EV"

    def test_insufficient_edge_rejection(self, engine):
        """
        Verify rejection when EV > 0 but Edge < min_reprice_edge (3%).
        Model Prob = 0.405, Ask = 0.40 -> EV = 0.005, Edge = 0.005 / 0.40 = 0.0125 < 0.03.
        """
        book = OrderBookSnapshot(
            station_id="KATL",
            bin_index=1,
            bin_label="68°F",
            bids=[OrderBookLevel(price=0.38, size=100.0)],
            asks=[OrderBookLevel(price=0.40, size=100.0)],
        )

        signal: EVTradeSignal = engine.evaluate_bin(
            snapshot=book,
            model_probability=0.405,
            target_size=50.0,
        )

        assert signal.is_tradable is False
        assert signal.reason == "REJECTED_EDGE_BELOW_THRESHOLD"

    def test_fee_rate_deduction(self):
        """Verify non-zero fee rate reduces payout and EV accordingly."""
        config_with_fee = EVConfig(min_reprice_edge=0.03, fee_rate=0.02)  # 2% fee
        engine = DynamicEVEngine(config=config_with_fee)

        book = OrderBookSnapshot(
            station_id="KDAL",
            bin_index=0,
            bin_label="≤67°F",
            bids=[],
            asks=[OrderBookLevel(price=0.50, size=100.0)],
        )

        # Prob = 0.60 -> Net Payout = 0.60 * (1 - 0.02) = 0.588
        # Net EV = 0.588 - 0.50 = 0.088
        signal = engine.evaluate_bin(snapshot=book, model_probability=0.60, target_size=50.0)
        assert signal.net_ev == pytest.approx(0.088, abs=1e-4)
        assert signal.edge == pytest.approx(0.088 / 0.50, abs=1e-4)
