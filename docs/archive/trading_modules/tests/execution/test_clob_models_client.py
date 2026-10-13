"""
Unit tests for CLOB Order Data Models, Signer Stub, and Client Interface (Phase 2 Task 06 - Ticket 01 / Issue #89).
"""

from decimal import Decimal
import pytest

from src.data_processing.constants import ACTIVE_10_STATIONS
from src.pricing.ev_engine import OrderBookLevel, OrderBookSnapshot
from src.execution.models import (
    CLOBOrder,
    OrderType,
    OrderSide,
    OrderStatus,
    FillEvent,
    OrderPlacementResult,
    MarketOrderForbiddenError,
)
from src.execution.clob_client import (
    CLOBSigner,
    CLOBClientInterface,
    MockCLOBClient,
)


class TestCLOBModels:
    """Tests for CLOB order models and validation contracts."""

    def test_market_order_strictly_forbidden(self):
        """Zero-Market-Order Theorem: Any attempt to instantiate or flag MARKET order raises error."""
        with pytest.raises(MarketOrderForbiddenError, match="Market orders are strictly forbidden"):
            CLOBOrder(
                order_id="ord-001",
                client_order_id="client-001",
                station_id="KORD",
                market_id="mkt-kord-tmax",
                bin_index=2,
                bin_label="[70, 72)",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,  # Forbidden!
                price=Decimal("0.5000"),
                size=Decimal("100.000000"),
            )

    def test_order_decimal_precision_clamping(self):
        """Verify order amounts and prices enforce Decimal precision with down-clamping."""
        order = CLOBOrder.create_buy_ioc(
            station_id="KLGA",
            market_id="mkt-klga-tmax",
            bin_index=1,
            bin_label="[68, 70)",
            price=Decimal("0.25006"),  # Should clamp to 4 decimal places ROUND_DOWN -> 0.2500
            size=Decimal("10.1234567"),  # Should clamp to 6 decimal places ROUND_DOWN -> 10.123456
        )
        assert order.order_type == OrderType.IOC
        assert order.side == OrderSide.BUY
        assert order.price == Decimal("0.2500")
        assert order.size == Decimal("10.123456")
        assert order.filled_size == Decimal("0.000000")
        assert order.status == OrderStatus.PENDING

    def test_order_station_validation(self):
        """Enforces order station belongs to ACTIVE_10_STATIONS."""
        with pytest.raises(ValueError, match="Station 'INVALID' not in Active 10"):
            CLOBOrder.create_buy_ioc(
                station_id="INVALID",
                market_id="mkt-inv",
                bin_index=0,
                bin_label="<50",
                price=Decimal("0.10"),
                size=Decimal("1.0"),
            )


class TestCLOBSigner:
    """Tests for CLOB Signer Stub."""

    def test_signer_generates_deterministic_signature(self):
        signer = CLOBSigner(private_key="0x" + "a" * 64)
        order = CLOBOrder.create_buy_ioc(
            station_id="KATL",
            market_id="mkt-katl-tmax",
            bin_index=3,
            bin_label="[75, 77)",
            price=Decimal("0.3000"),
            size=Decimal("50.000000"),
        )
        sig1 = signer.sign_order(order)
        sig2 = signer.sign_order(order)
        assert sig1.startswith("0x")
        assert len(sig1) == 132  # Standard 65-byte hex signature stub
        assert sig1 == sig2


class TestMockCLOBClient:
    """Tests for MockCLOBClient matching engine simulations."""

    @pytest.fixture
    def client(self):
        client = MockCLOBClient()
        # Seed orderbook snapshot for KORD bin 2
        ob = OrderBookSnapshot(
            station_id="KORD",
            bin_index=2,
            bin_label="[70, 72)",
            bids=[],
            asks=[
                OrderBookLevel(price=0.20, size=50.0),
                OrderBookLevel(price=0.22, size=30.0),
                OrderBookLevel(price=0.25, size=20.0),
                OrderBookLevel(price=0.30, size=100.0),
            ],
        )
        client.set_orderbook("mkt-kord-tmax", 2, ob)
        return client

    def test_ioc_full_fill_across_tiers(self, client):
        """IOC order fills completely when limit price covers depth."""
        order = CLOBOrder.create_buy_ioc(
            station_id="KORD",
            market_id="mkt-kord-tmax",
            bin_index=2,
            bin_label="[70, 72)",
            price=Decimal("0.2500"),
            size=Decimal("80.000000"),  # Needs 50 @ 0.20 + 30 @ 0.22 = 80 total
        )
        result = client.place_order(order)
        assert result.success is True
        assert result.status == OrderStatus.FILLED
        assert result.filled_size == Decimal("80.000000")
        # VWAP = (50*0.20 + 30*0.22) / 80 = (10 + 6.6) / 80 = 16.6 / 80 = 0.2075
        assert result.avg_fill_price == Decimal("0.2075")
        assert result.remaining_size == Decimal("0.000000")

    def test_ioc_partial_fill_and_cancel_residual(self, client):
        """IOC order partially fills up to limit price and cancels remaining size."""
        order = CLOBOrder.create_buy_ioc(
            station_id="KORD",
            market_id="mkt-kord-tmax",
            bin_index=2,
            bin_label="[70, 72)",
            price=Decimal("0.2200"),
            size=Decimal("100.000000"),  # Asks <= 0.22 only have 50 + 30 = 80
        )
        result = client.place_order(order)
        assert result.success is True
        assert result.status == OrderStatus.PARTIALLY_FILLED
        assert result.filled_size == Decimal("80.000000")
        assert result.remaining_size == Decimal("20.000000")
        assert result.avg_fill_price == Decimal("0.2075")
        # Assert orderbook asks were consumed
        ob = client.get_orderbook("mkt-kord-tmax", 2)
        assert len(ob.asks) == 2
        assert ob.asks[0].price == 0.25

    def test_cancel_all_orders_for_station(self, client):
        """Verify cancel_all_orders removes maker quotes for a given station."""
        order_gtc1 = CLOBOrder(
            order_id="ord-gtc-1",
            client_order_id="c-1",
            station_id="KORD",
            market_id="mkt-kord-tmax",
            bin_index=2,
            bin_label="[70, 72)",
            side=OrderSide.BUY,
            order_type=OrderType.GTC,
            price=Decimal("0.1500"),
            size=Decimal("50.000000"),
        )
        order_gtc2 = CLOBOrder(
            order_id="ord-gtc-2",
            client_order_id="c-2",
            station_id="KLGA",
            market_id="mkt-klga-tmax",
            bin_index=1,
            bin_label="[68, 70)",
            side=OrderSide.BUY,
            order_type=OrderType.GTC,
            price=Decimal("0.1800"),
            size=Decimal("50.000000"),
        )
        client.place_order(order_gtc1)
        client.place_order(order_gtc2)

        # Cancel KORD only
        cancelled = client.cancel_all_orders(station_id="KORD")
        assert cancelled == ["ord-gtc-1"]
        assert client.get_order_status("ord-gtc-1").status == OrderStatus.CANCELLED
        assert client.get_order_status("ord-gtc-2").status == OrderStatus.PENDING
