"""
IOC Protection Limit Order Calculation and Order Router (Phase 2 Task 06 - Ticket 02 / Issue #90).
Calculates safe protection price P_protect to eliminate depth penetration risk (Execution v2.0 §5.1),
assembles Immediate-Or-Cancel limit orders, and synchronizes capital allocation with BankrollManager.
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN
import logging
from typing import Dict, List, Optional

from src.bankroll.bankroll_manager import BankrollManager
from src.execution.clob_client import CLOBClientInterface
from src.execution.models import (
    CLOBOrder,
    OrderPlacementResult,
    OrderSide,
    OrderStatus,
    OrderType,
    PRICE_DECIMAL_PLACES,
    SIZE_DECIMAL_PLACES,
)
from src.pricing.ev_engine import OrderBookLevel, OrderBookSnapshot

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProtectionPriceResult:
    """Result of protection price and capacity calculation."""
    is_tradable: bool
    protection_price: Optional[Decimal]
    safe_capacity: Decimal
    reason: str


def calculate_protection_price(
    model_prob: float,
    asks: List[OrderBookLevel],
    min_edge: float = 0.0,
) -> ProtectionPriceResult:
    """
    Determine safe protection price P_protect across orderbook ask tiers.
    Traverses asks from lowest price upward until EV(P_k) < min_edge,
    then locks onto the immediately preceding safe tier's price (Execution v2.0 §5.1).
    """
    if not asks:
        return ProtectionPriceResult(
            is_tradable=False,
            protection_price=None,
            safe_capacity=Decimal("0.000000"),
            reason="Orderbook ask depth is empty",
        )

    if model_prob <= 0.0:
        return ProtectionPriceResult(
            is_tradable=False,
            protection_price=None,
            safe_capacity=Decimal("0.000000"),
            reason=f"Model probability non-positive ({model_prob:.4f})",
        )

    # Sort asks ascending by price
    sorted_asks = sorted(asks, key=lambda lvl: lvl.price)

    safe_price: Optional[Decimal] = None
    safe_capacity = Decimal("0.000000")

    for i, ask in enumerate(sorted_asks):
        ask_price = ask.price
        if ask_price <= 0.0 or ask_price >= 1.0:
            continue

        # Single-share EV = (p_model - P) / P
        ev = (model_prob - ask_price) / ask_price
        ask_price_dec = Decimal(str(ask_price)).quantize(PRICE_DECIMAL_PLACES, rounding=ROUND_DOWN)
        ask_size_dec = Decimal(str(ask.size)).quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)

        if ev < min_edge:
            # First tier that breaches minimum edge
            if i == 0:
                # Even best ask is unacceptable
                return ProtectionPriceResult(
                    is_tradable=False,
                    protection_price=None,
                    safe_capacity=Decimal("0.000000"),
                    reason=f"Best ask price {ask_price:.4f} has insufficient edge {ev:.4f} < {min_edge:.4f}",
                )
            # Stop right before this tier
            break

        # Tier is safe
        safe_price = ask_price_dec
        safe_capacity += ask_size_dec

    if safe_price is None or safe_capacity <= Decimal("0.000000"):
        return ProtectionPriceResult(
            is_tradable=False,
            protection_price=None,
            safe_capacity=Decimal("0.000000"),
            reason="No executable positive-EV depth discovered",
        )

    return ProtectionPriceResult(
        is_tradable=True,
        protection_price=safe_price,
        safe_capacity=safe_capacity,
        reason="Safe protection tier established",
    )


@dataclass
class RouterExecutionReport:
    """Consolidated dispatch report for a market execution cycle."""
    station_id: str
    market_id: str
    orders: List[CLOBOrder] = field(default_factory=list)
    results: List[OrderPlacementResult] = field(default_factory=list)
    total_committed_cost: Decimal = Decimal("0.000000")
    skipped_bins: Dict[int, str] = field(default_factory=dict)


class OrderRouter:
    """
    Assembles and routes IOC limit orders with strict price protection.
    Prevents depth penetration and locks/unlocks funds via BankrollManager.
    """

    def __init__(
        self,
        clob_client: CLOBClientInterface,
        bankroll_manager: Optional[BankrollManager] = None,
        min_edge: float = 0.0,
    ):
        self.clob_client = clob_client
        self.bankroll_manager = bankroll_manager
        self.min_edge = min_edge

    def route_allocations(
        self,
        station_id: str,
        market_id: str,
        allocations: Dict[int, Decimal],
        model_probs: Dict[int, float],
        bin_labels: Dict[int, str],
    ) -> RouterExecutionReport:
        """
        Convert multinomial Kelly allocations (USDC per bin) into protected IOC orders,
        execute against CLOB, and update bankroll ledger.
        """
        report = RouterExecutionReport(station_id=station_id, market_id=market_id)

        for bin_index, alloc_usdc in allocations.items():
            if not isinstance(alloc_usdc, Decimal):
                alloc_usdc = Decimal(str(alloc_usdc))
            alloc_usdc = alloc_usdc.quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)

            if alloc_usdc <= Decimal("0.000000"):
                continue

            prob = model_probs.get(bin_index, 0.0)
            label = bin_labels.get(bin_index, f"Bin {bin_index}")

            # Fetch orderbook snapshot
            ob = self.clob_client.get_orderbook(market_id, bin_index)
            if ob is None or not ob.asks:
                report.skipped_bins[bin_index] = "No orderbook depth available"
                continue

            # Calculate safe protection price
            prot_res = calculate_protection_price(prob, ob.asks, self.min_edge)
            if not prot_res.is_tradable or prot_res.protection_price is None:
                report.skipped_bins[bin_index] = prot_res.reason
                continue

            p_protect = prot_res.protection_price
            if p_protect <= Decimal("0.0000"):
                report.skipped_bins[bin_index] = "Protection price non-positive"
                continue

            # Target share size = alloc_usdc / P_protect (quantized ROUND_DOWN)
            target_shares = (alloc_usdc / p_protect).quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)
            executable_shares = min(target_shares, prot_res.safe_capacity)

            if executable_shares <= Decimal("0.000000"):
                report.skipped_bins[bin_index] = "Executable shares zero"
                continue

            # Max capital lock needed
            max_lock_amount = (executable_shares * p_protect).quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)

            # Lock funds if bankroll manager attached
            if self.bankroll_manager is not None:
                try:
                    self.bankroll_manager.lock_funds(max_lock_amount)
                except Exception as e:
                    logger.error(f"Failed to lock funds for bin {bin_index}: {e}")
                    report.skipped_bins[bin_index] = f"Bankroll lock failed: {e}"
                    continue

            # Assemble IOC limit order
            order = CLOBOrder.create_buy_ioc(
                station_id=station_id,
                market_id=market_id,
                bin_index=bin_index,
                bin_label=label,
                price=p_protect,
                size=executable_shares,
            )

            # Submit to CLOB
            result = self.clob_client.place_order(order)
            report.orders.append(order)
            report.results.append(result)

            # Settle locked funds based on actual filled cost
            actual_cost = order.total_cost
            report.total_committed_cost += actual_cost

            if self.bankroll_manager is not None:
                excess_locked = max_lock_amount - actual_cost
                if excess_locked > Decimal("0.000000"):
                    self.bankroll_manager.unlock_funds(excess_locked)

        return report
