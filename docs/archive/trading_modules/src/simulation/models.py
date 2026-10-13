"""
Simulation Data Models and Simulated Order Book (Phase 2 Task 07 - Ticket 01 / Issue #95).
Provides strict Decimal fixed-point tracking for paper positions, simulated order books,
and structured trade logging, fully interoperable with OrderBookSnapshot and CLOBClient.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from enum import Enum
import logging
from typing import Any, Dict, List, Optional, Tuple

from src.execution.models import PRICE_DECIMAL_PLACES, SIZE_DECIMAL_PLACES
from src.pricing.ev_engine import OrderBookLevel, OrderBookSnapshot

logger = logging.getLogger(__name__)


class SimulationEventType(str, Enum):
    OBSERVATION_UPDATE = "OBSERVATION_UPDATE"
    PREDICTION_UPDATE = "PREDICTION_UPDATE"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_FILLED = "ORDER_FILLED"
    SETTLEMENT = "SETTLEMENT"
    ZOMBIE_TRANSFERRED = "ZOMBIE_TRANSFERRED"
    SAFETY_ALERT = "SAFETY_ALERT"


@dataclass
class SimulationEvent:
    """Generic simulation timeline event."""
    timestamp: datetime
    event_type: SimulationEventType
    station_id: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.value,
            "station_id": self.station_id,
            "details": self.details,
        }


@dataclass
class PaperTradeRecord:
    """Audit record of a filled paper trade."""
    timestamp: datetime
    station_id: str
    market_id: str
    bin_index: int
    action: str  # e.g., 'BUY', 'SELL', 'REHEDGE'
    shares: Decimal
    price: Decimal
    total_cost: Decimal

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "station_id": self.station_id,
            "market_id": self.market_id,
            "bin_index": self.bin_index,
            "action": self.action,
            "shares": float(self.shares),
            "price": float(self.price),
            "total_cost": float(self.total_cost),
        }


@dataclass
class PaperPosition:
    """
    Tracks paper position in a specific market bin.
    Uses 6-decimal fixed-point Decimal arithmetic.
    """
    station_id: str
    market_id: str
    bin_index: int
    bin_label: str
    shares: Decimal = Decimal("0.000000")
    total_cost: Decimal = Decimal("0.000000")

    @property
    def average_price(self) -> Decimal:
        """Weighted average fill price."""
        if self.shares <= Decimal("0.000000"):
            return Decimal("0.000000")
        return (self.total_cost / self.shares).quantize(PRICE_DECIMAL_PLACES, rounding=ROUND_DOWN)

    def add_fill(self, shares: Decimal, cost: Decimal) -> None:
        """Accumulate new executed fill."""
        if shares <= Decimal("0.000000") or cost <= Decimal("0.000000"):
            return
        self.shares += shares.quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)
        self.total_cost += cost.quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "station_id": self.station_id,
            "market_id": self.market_id,
            "bin_index": self.bin_index,
            "bin_label": self.bin_label,
            "shares": float(self.shares),
            "total_cost": float(self.total_cost),
            "average_price": float(self.average_price),
        }


class SimulatedOrderBook:
    """
    Simulates a discrete order book for a single bin in Polymarket CLOB.
    Supports IOC order execution matching against available ask liquidity.
    """

    def __init__(
        self,
        market_id: str,
        bin_index: int,
        station_id: str = "KORD",
        bin_label: str = "",
        bids: Optional[List[OrderBookLevel]] = None,
        asks: Optional[List[OrderBookLevel]] = None,
    ):
        self.market_id = market_id
        self.bin_index = bin_index
        self.station_id = station_id
        self.bin_label = bin_label
        # bids sorted descending by price
        self.bids: List[OrderBookLevel] = sorted(bids or [], key=lambda l: l.price, reverse=True)
        # asks sorted ascending by price
        self.asks: List[OrderBookLevel] = sorted(asks or [], key=lambda l: l.price)

    @property
    def best_bid(self) -> Optional[Decimal]:
        return Decimal(str(self.bids[0].price)) if self.bids else None

    @property
    def best_ask(self) -> Optional[Decimal]:
        return Decimal(str(self.asks[0].price)) if self.asks else None

    def to_snapshot(self) -> OrderBookSnapshot:
        """Export as standard OrderBookSnapshot for CLOBClient/OrderRouter."""
        return OrderBookSnapshot(
            station_id=self.station_id,
            bin_index=self.bin_index,
            bin_label=self.bin_label,
            bids=list(self.bids),
            asks=list(self.asks),
        )

    def update_depth(self, bids: List[OrderBookLevel], asks: List[OrderBookLevel]) -> None:
        """Refresh order book depth."""
        self.bids = sorted(bids, key=lambda l: l.price, reverse=True)
        self.asks = sorted(asks, key=lambda l: l.price)

    def simulate_buy_ioc(
        self,
        max_price: Decimal,
        target_amount_usdc: Decimal,
    ) -> Tuple[Decimal, Decimal]:
        """
        Simulate an IOC buy order up to max_price for target_amount_usdc.
        Returns (filled_shares, total_cost_usdc).
        Consumes matching ask depth from the book.
        """
        if target_amount_usdc <= Decimal("0.000000") or max_price <= Decimal("0.0000"):
            return Decimal("0.000000"), Decimal("0.000000")

        remaining_budget = target_amount_usdc
        total_shares = Decimal("0.000000")
        total_cost = Decimal("0.000000")

        remaining_asks: List[OrderBookLevel] = []

        for level in self.asks:
            level_price = Decimal(str(level.price))
            level_size = Decimal(str(level.size))

            if remaining_budget <= Decimal("0.000000"):
                remaining_asks.append(level)
                continue

            if level_price > max_price:
                # Exceeds limit price, IOC cuts off immediately
                remaining_asks.append(level)
                continue

            cost_for_full_level = (level_price * level_size).quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)

            if remaining_budget >= cost_for_full_level:
                # Fully consume this level
                total_shares += level_size
                total_cost += cost_for_full_level
                remaining_budget -= cost_for_full_level
            else:
                # Partially consume this level
                shares_bought = (remaining_budget / level_price).quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)
                if shares_bought > Decimal("0.000000"):
                    actual_cost = (shares_bought * level_price).quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)
                    total_shares += shares_bought
                    total_cost += actual_cost
                    remaining_budget -= actual_cost

                    remaining_size = level_size - shares_bought
                    if remaining_size > Decimal("0.000000"):
                        remaining_asks.append(OrderBookLevel(price=float(level_price), size=float(remaining_size)))
                else:
                    remaining_asks.append(level)
                remaining_budget = Decimal("0.000000")

        self.asks = remaining_asks
        return total_shares, total_cost
