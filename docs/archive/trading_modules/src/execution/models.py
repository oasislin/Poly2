"""
CLOB Order Data Models and Financial Domain Representations (Phase 2 Task 06 - Ticket 01 / Issue #89).
Enforces zero-market-order theorem, 6-decimal down-clamped precision, and Active 10 station confinement.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from enum import Enum
import hashlib
from typing import Any, Dict, List, Optional
import uuid

from src.data_processing.constants import ACTIVE_10_STATIONS

PRICE_DECIMAL_PLACES = Decimal("0.0001")
SIZE_DECIMAL_PLACES = Decimal("0.000001")


class MarketOrderForbiddenError(Exception):
    """Raised when any code attempts to construct, submit, or route a MARKET order."""
    pass


class OrderType(str, Enum):
    """Supported CLOB order execution types."""
    IOC = "IOC"  # Immediate-Or-Cancel (Primary execution mode for price protection)
    GTC = "GTC"  # Good-Til-Cancelled (Maker quote / rehedge limit orders)
    MARKET = "MARKET"  # Strictly forbidden by architecture protocol


class OrderSide(str, Enum):
    """Order trade side."""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    """CLOB order lifecycle states."""
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


@dataclass
class FillEvent:
    """Represents a single execution trade match event on CLOB."""
    order_id: str
    fill_price: Decimal
    fill_size: Decimal
    fee: Decimal = Decimal("0.000000")
    timestamp_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if not isinstance(self.fill_price, Decimal):
            self.fill_price = Decimal(str(self.fill_price))
        if not isinstance(self.fill_size, Decimal):
            self.fill_size = Decimal(str(self.fill_size))
        if not isinstance(self.fee, Decimal):
            self.fee = Decimal(str(self.fee))
        self.fill_price = self.fill_price.quantize(PRICE_DECIMAL_PLACES, rounding=ROUND_DOWN)
        self.fill_size = self.fill_size.quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)
        self.fee = self.fee.quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)


@dataclass
class OrderPlacementResult:
    """Result returned by CLOB client upon order submission."""
    order_id: str
    client_order_id: str
    success: bool
    status: OrderStatus
    filled_size: Decimal
    remaining_size: Decimal
    avg_fill_price: Optional[Decimal] = None
    fills: List[FillEvent] = field(default_factory=list)
    rejection_reason: Optional[str] = None


@dataclass
class CLOBOrder:
    """
    Standardized Polymarket CLOB limit order entity.
    All monetary and volumetric amounts are strictly Decimal.
    """
    order_id: str
    client_order_id: str
    station_id: str
    market_id: str
    bin_index: int
    bin_label: str
    side: OrderSide
    order_type: OrderType
    price: Decimal
    size: Decimal
    filled_size: Decimal = Decimal("0.000000")
    avg_fill_price: Optional[Decimal] = None
    status: OrderStatus = OrderStatus.PENDING
    timestamp_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    signature: Optional[str] = None

    def __post_init__(self):
        # 1. Zero-Market-Order Theorem Check
        if self.order_type == OrderType.MARKET or str(self.order_type).upper() == "MARKET":
            raise MarketOrderForbiddenError(
                "Market orders are strictly forbidden by architectural decree (ADR-0011/Execution v2.0 §5). "
                "Only IOC or GTC limit orders are allowed."
            )

        # 2. Station validation
        if self.station_id not in ACTIVE_10_STATIONS:
            raise ValueError(f"Station '{self.station_id}' not in Active 10 station pool.")

        # 3. Decimal quantizing with ROUND_DOWN
        if not isinstance(self.price, Decimal):
            self.price = Decimal(str(self.price))
        if not isinstance(self.size, Decimal):
            self.size = Decimal(str(self.size))
        if not isinstance(self.filled_size, Decimal):
            self.filled_size = Decimal(str(self.filled_size))

        self.price = self.price.quantize(PRICE_DECIMAL_PLACES, rounding=ROUND_DOWN)
        self.size = self.size.quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)
        self.filled_size = self.filled_size.quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)

        if self.avg_fill_price is not None:
            if not isinstance(self.avg_fill_price, Decimal):
                self.avg_fill_price = Decimal(str(self.avg_fill_price))
            self.avg_fill_price = self.avg_fill_price.quantize(PRICE_DECIMAL_PLACES, rounding=ROUND_DOWN)

    @classmethod
    def create_buy_ioc(
        cls,
        station_id: str,
        market_id: str,
        bin_index: int,
        bin_label: str,
        price: Decimal | float | str,
        size: Decimal | float | str,
        client_order_id: Optional[str] = None,
    ) -> "CLOBOrder":
        """Factory constructor for standard Buy IOC protection order."""
        cid = client_order_id or f"ioc-{station_id}-{bin_index}-{uuid.uuid4().hex[:8]}"
        oid = f"ord-{uuid.uuid4().hex[:12]}"
        return cls(
            order_id=oid,
            client_order_id=cid,
            station_id=station_id,
            market_id=market_id,
            bin_index=bin_index,
            bin_label=bin_label,
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal(str(price)),
            size=Decimal(str(size)),
        )

    @property
    def remaining_size(self) -> Decimal:
        """Calculate unexecuted size."""
        rem = self.size - self.filled_size
        return max(Decimal("0.000000"), rem.quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN))

    @property
    def total_cost(self) -> Decimal:
        """Committed capital value for filled portion."""
        if self.avg_fill_price is None or self.filled_size == Decimal("0.000000"):
            return Decimal("0.000000")
        return (self.filled_size * self.avg_fill_price).quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)
