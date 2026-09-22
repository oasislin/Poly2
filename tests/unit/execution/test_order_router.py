"""
Unit tests for IOC Protection Price Calculation and Order Router (Phase 2 Task 06 - Ticket 02 / Issue #90).
"""

from decimal import Decimal
import pytest

from src.bankroll.bankroll_manager import BankrollManager
from src.execution.clob_client import MockCLOBClient
from src.execution.models import OrderStatus, OrderType
from src.execution.order_router import (
    OrderRouter,
    ProtectionPriceResult,
    calculate_protection_price,
)
from src.pricing.ev_engine import OrderBookLevel, OrderBookSnapshot


class TestProtectionPriceCalculation:
    """Tests for protection price determination contract (Execution v2.0 §5.1)."""

    def test_protection_price_stops_before_negative_ev_tier(self):
        """
        Model probability = 0.40. Min edge = 0.0 (EV > 0 required).
        Asks:
          Tier 0: price = 0.20 (EV = (0.40 - 0.20)/0.20 = 1.0 > 0)
          Tier 1: price = 0.35 (EV = (0.40 - 0.35)/0.35 = 0.14 > 0)
          Tier 2: price = 0.45 (EV = (0.40 - 0.45)/0.45 = -0.11 < 0) -> NEGATIVE!
          Tier 3: price = 0.80
        Assert protection price locks onto Tier 1 price (0.3500) and safe capacity = Tier 0 + Tier 1 size.
        """
        asks = [
            OrderBookLevel(price=0.20, size=50.0),
            OrderBookLevel(price=0.35, size=40.0),
            OrderBookLevel(price=0.45, size=100.0),
            OrderBookLevel(price=0.80, size=200.0),
        ]
        res = calculate_protection_price(model_prob=0.40, asks=asks, min_edge=0.0)
        assert res.is_tradable is True
        assert res.protection_price == Decimal("0.3500")
        assert res.safe_capacity == Decimal("90.000000")

    def test_protection_price_rejects_when_first_tier_is_negative_ev(self):
        """When the best ask already has negative EV, no order should be generated."""
        asks = [
            OrderBookLevel(price=0.50, size=100.0),
            OrderBookLevel(price=0.60, size=100.0),
        ]
        res = calculate_protection_price(model_prob=0.30, asks=asks, min_edge=0.0)
        assert res.is_tradable is False
        assert res.protection_price is None
        assert res.safe_capacity == Decimal("0.000000")

    def test_protection_price_all_tiers_positive_ev(self):
        """When all tiers have positive EV, lock onto the last positive tier."""
        asks = [
            OrderBookLevel(price=0.10, size=30.0),
            OrderBookLevel(price=0.15, size=70.0),
        ]
        res = calculate_protection_price(model_prob=0.50, asks=asks, min_edge=0.03)
        assert res.is_tradable is True
        assert res.protection_price == Decimal("0.1500")
        assert res.safe_capacity == Decimal("100.000000")


class TestOrderRouter:
    """Tests for OrderRouter dispatch and bankroll locking integration."""

    @pytest.fixture
    def setup_router(self):
        client = MockCLOBClient()
        bm = BankrollManager(initial_free_usdc=Decimal("1000.000000"))
        router = OrderRouter(clob_client=client, bankroll_manager=bm)

        # Seed orderbooks for KORD
        # Bin 1: positive EV at 0.25 (model prob = 0.50)
        ob_bin1 = OrderBookSnapshot(
            station_id="KORD",
            bin_index=1,
            bin_label="[68, 70)",
            asks=[
                OrderBookLevel(price=0.20, size=100.0),
                OrderBookLevel(price=0.25, size=100.0),
                OrderBookLevel(price=0.55, size=200.0),  # Negative EV
            ],
        )
        client.set_orderbook("mkt-kord", 1, ob_bin1)

        # Bin 2: Negative EV at first tier (ask 0.60 vs model prob 0.10)
        ob_bin2 = OrderBookSnapshot(
            station_id="KORD",
            bin_index=2,
            bin_label="[70, 72)",
            asks=[
                OrderBookLevel(price=0.60, size=50.0),
            ],
        )
        client.set_orderbook("mkt-kord", 2, ob_bin2)

        return router, client, bm

    def test_route_allocations_generates_ioc_with_protection_price(self, setup_router):
        router, client, bm = setup_router

        allocations = {
            1: Decimal("40.000000"),  # 40 USDC to Bin 1
            2: Decimal("20.000000"),  # 20 USDC to Bin 2 (should be skipped due to negative EV)
        }
        model_probs = {1: 0.50, 2: 0.10}
        bin_labels = {1: "[68, 70)", 2: "[70, 72)"}

        report = router.route_allocations(
            station_id="KORD",
            market_id="mkt-kord",
            allocations=allocations,
            model_probs=model_probs,
            bin_labels=bin_labels,
        )

        assert len(report.orders) == 1
        order_bin1 = report.orders[0]
        assert order_bin1.bin_index == 1
        assert order_bin1.order_type == OrderType.IOC
        assert order_bin1.price == Decimal("0.2500")  # Locked protection price!
        assert order_bin1.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)
        assert order_bin1.avg_fill_price is not None
        assert order_bin1.avg_fill_price <= Decimal("0.2500")

        # Verify bankroll was updated: Active Locked should reflect actual filled cost
        # and unexecuted capital unlocked back to Free USDC
        total_balance = bm.get_balance()
        assert total_balance.total_bankroll == Decimal("1000.000000")
        assert total_balance.active_locked == order_bin1.total_cost
        assert total_balance.free_usdc == Decimal("1000.000000") - order_bin1.total_cost
