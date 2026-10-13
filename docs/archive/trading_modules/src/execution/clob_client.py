"""
Polymarket CLOB Client Interface, Signer Stub, and Mock Engine (Phase 2 Task 06 - Ticket 01 / Issue #89).
Provides order placement, IOC instant partial/full fills, cancel_all quotes, and local orderbook state.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import hashlib
import logging
from typing import Dict, List, Optional

from src.execution.models import (
    CLOBOrder,
    FillEvent,
    MarketOrderForbiddenError,
    OrderPlacementResult,
    OrderSide,
    OrderStatus,
    OrderType,
    PRICE_DECIMAL_PLACES,
    SIZE_DECIMAL_PLACES,
)
from src.pricing.ev_engine import OrderBookLevel, OrderBookSnapshot

logger = logging.getLogger(__name__)


class CLOBSigner:
    """Cryptographic order signer stub for EIP-712 or API key digest generation."""

    def __init__(self, private_key: str = "0x" + "0" * 64):
        self.private_key = private_key

    def sign_order(self, order: CLOBOrder) -> str:
        """Generate deterministic hex signature stub (65 bytes / 132 chars with 0x prefix)."""
        payload = f"{self.private_key}:{order.station_id}:{order.market_id}:{order.bin_index}:{order.side}:{order.price}:{order.size}:{order.client_order_id}"
        h1 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        h2 = hashlib.sha256((payload + ":v2").encode("utf-8")).hexdigest()
        full_hex = "0x" + h1 + h2 + "1b"
        return full_hex


class CLOBClientInterface(ABC):
    """Abstract interface for Polymarket CLOB client implementations."""

    @abstractmethod
    def place_order(self, order: CLOBOrder) -> OrderPlacementResult:
        """Submit limit order to CLOB."""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a specific pending maker order."""
        pass

    @abstractmethod
    def cancel_all_orders(self, station_id: Optional[str] = None) -> List[str]:
        """Cancel all pending open maker quotes (optionally filtered by station)."""
        pass

    @abstractmethod
    def get_order_status(self, order_id: str) -> Optional[CLOBOrder]:
        """Retrieve current order details."""
        pass

    @abstractmethod
    def get_orderbook(self, market_id: str, bin_index: int) -> Optional[OrderBookSnapshot]:
        """Fetch current orderbook snapshot for a bin."""
        pass


class MockCLOBClient(CLOBClientInterface):
    """
    In-memory simulation of Polymarket CLOB matching engine.
    Faithfully simulates IOC matching against asks, partial fills, cancellations, and orderbook depletion.
    """

    def __init__(self, signer: Optional[CLOBSigner] = None):
        self.signer = signer or CLOBSigner()
        # Storage: (market_id, bin_index) -> OrderBookSnapshot
        self._orderbooks: Dict[tuple[str, int], OrderBookSnapshot] = {}
        # Storage: order_id -> CLOBOrder
        self._orders: Dict[str, CLOBOrder] = {}
        # Storage: order_id -> List[FillEvent]
        self._fills: Dict[str, List[FillEvent]] = {}

    def set_orderbook(self, market_id: str, bin_index: int, snapshot: OrderBookSnapshot) -> None:
        """Seed or update orderbook snapshot for testing."""
        self._orderbooks[(market_id, bin_index)] = snapshot

    def get_orderbook(self, market_id: str, bin_index: int) -> Optional[OrderBookSnapshot]:
        """Retrieve current orderbook snapshot for bin."""
        return self._orderbooks.get((market_id, bin_index))

    def get_order_status(self, order_id: str) -> Optional[CLOBOrder]:
        """Get order status from internal store."""
        return self._orders.get(order_id)

    def place_order(self, order: CLOBOrder) -> OrderPlacementResult:
        """
        Execute order against mock orderbook.
        Strictly enforces Zero-Market-Order and simulates IOC cancellation of untaken residual.
        """
        if order.order_type == OrderType.MARKET:
            raise MarketOrderForbiddenError("Market orders are forbidden.")

        # Sign order if unsigned
        if not order.signature:
            order.signature = self.signer.sign_order(order)

        self._orders[order.order_id] = order
        key = (order.market_id, order.bin_index)
        snapshot = self._orderbooks.get(key)

        if snapshot is None or not snapshot.asks:
            # Empty orderbook
            if order.order_type == OrderType.IOC:
                order.status = OrderStatus.CANCELLED
                return OrderPlacementResult(
                    order_id=order.order_id,
                    client_order_id=order.client_order_id,
                    success=True,
                    status=OrderStatus.CANCELLED,
                    filled_size=Decimal("0.000000"),
                    remaining_size=order.size,
                    avg_fill_price=None,
                    rejection_reason="No ask depth available for IOC order",
                )
            else:
                order.status = OrderStatus.PENDING
                return OrderPlacementResult(
                    order_id=order.order_id,
                    client_order_id=order.client_order_id,
                    success=True,
                    status=OrderStatus.PENDING,
                    filled_size=Decimal("0.000000"),
                    remaining_size=order.size,
                )

        # Match against asks (sorted ascending)
        remaining_needed = order.size
        filled_total = Decimal("0.000000")
        total_cost = Decimal("0.000000")
        fills: List[FillEvent] = []
        new_asks: List[OrderBookLevel] = []

        if order.side == OrderSide.BUY:
            tiers = sorted(snapshot.asks, key=lambda lvl: lvl.price)
        else:
            tiers = sorted(snapshot.bids, key=lambda lvl: lvl.price, reverse=True)

        for lvl in tiers:
            lvl_price_dec = Decimal(str(lvl.price)).quantize(PRICE_DECIMAL_PLACES, rounding=ROUND_DOWN)
            lvl_size_dec = Decimal(str(lvl.size)).quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)

            if order.side == OrderSide.BUY:
                if lvl_price_dec > order.price:
                    new_asks.append(lvl)
                    continue
            else:
                if lvl_price_dec < order.price:
                    # Sell limit price is higher than available bid
                    continue

            if remaining_needed <= Decimal("0.000000"):
                if order.side == OrderSide.BUY:
                    new_asks.append(lvl)
                continue

            take_size = min(lvl_size_dec, remaining_needed)
            fill_cost = (take_size * lvl_price_dec).quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)

            filled_total += take_size
            total_cost += fill_cost
            remaining_needed -= take_size

            fill_event = FillEvent(
                order_id=order.order_id,
                fill_price=lvl_price_dec,
                fill_size=take_size,
                fee=Decimal("0.000000"),
            )
            fills.append(fill_event)

            rem_lvl_size = lvl_size_dec - take_size
            if rem_lvl_size > Decimal("0.000001"):
                if order.side == OrderSide.BUY:
                    new_asks.append(OrderBookLevel(price=lvl.price, size=float(rem_lvl_size)))

        # Update remaining depth in snapshot
        if order.side == OrderSide.BUY:
            self._orderbooks[key] = OrderBookSnapshot(
                station_id=snapshot.station_id,
                bin_index=snapshot.bin_index,
                bin_label=snapshot.bin_label,
                bids=snapshot.bids,
                asks=new_asks,
            )
        else:
            # Cleared bids
            self._orderbooks[key] = OrderBookSnapshot(
                station_id=snapshot.station_id,
                bin_index=snapshot.bin_index,
                bin_label=snapshot.bin_label,
                bids=[],
                asks=snapshot.asks,
            )

        self._fills[order.order_id] = fills
        order.filled_size = filled_total

        if filled_total > Decimal("0.000000"):
            avg_price = (total_cost / filled_total).quantize(PRICE_DECIMAL_PLACES, rounding=ROUND_DOWN)
            order.avg_fill_price = avg_price
        else:
            order.avg_fill_price = None

        if order.order_type == OrderType.IOC:
            if filled_total >= order.size:
                order.status = OrderStatus.FILLED
            elif filled_total > Decimal("0.000000"):
                order.status = OrderStatus.PARTIALLY_FILLED
            else:
                order.status = OrderStatus.CANCELLED
        else:
            # GTC
            if filled_total >= order.size:
                order.status = OrderStatus.FILLED
            else:
                order.status = OrderStatus.PENDING

        return OrderPlacementResult(
            order_id=order.order_id,
            client_order_id=order.client_order_id,
            success=True,
            status=order.status,
            filled_size=filled_total,
            remaining_size=order.remaining_size,
            avg_fill_price=order.avg_fill_price,
            fills=fills,
        )

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""
        if order_id in self._orders:
            order = self._orders[order_id]
            if order.status in (OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED):
                order.status = OrderStatus.CANCELLED
                return True
        return False

    def cancel_all_orders(self, station_id: Optional[str] = None) -> List[str]:
        """
        Cancel all open/pending orders for a specific station (or globally).
        Returns list of cancelled order IDs.
        """
        cancelled_ids = []
        for oid, order in self._orders.items():
            if order.status == OrderStatus.PENDING:
                if station_id is None or order.station_id == station_id:
                    order.status = OrderStatus.CANCELLED
                    cancelled_ids.append(oid)
        logger.info(f"MockCLOB: Cancelled {len(cancelled_ids)} pending orders for station '{station_id}'.")
        return cancelled_ids
