"""
Dynamic Microstructural EV Engine and OrderBook Depth Penetration (Phase 2 Task 04 - Ticket 04 / Issue #80).
Evaluates Polymarket orderbook liquidity depth to calculate effective volume-weighted average price (VWAP),
applies fee structures, and generates actionable positive-EV trade signals.
"""

from dataclasses import dataclass, field
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrderBookLevel:
    """Single price-quantity tier in a CLOB orderbook."""
    price: float
    size: float


@dataclass(frozen=True)
class OrderBookSnapshot:
    """Snapshot of bids and asks for a specific market bin."""
    station_id: str
    bin_index: int
    bin_label: str
    bids: List[OrderBookLevel] = field(default_factory=list)
    asks: List[OrderBookLevel] = field(default_factory=list)


@dataclass(frozen=True)
class EVConfig:
    """Configurable thresholds for dynamic EV evaluations."""
    min_reprice_edge: float = 0.03  # Minimum required edge (3%) to trade
    fee_rate: float = 0.0           # Taker fee rate (Polymarket standard is 0%)


@dataclass(frozen=True)
class EVTradeSignal:
    """Trading signal verdict containing net EV and edge metrics."""
    station_id: str
    bin_index: int
    bin_label: str
    model_probability: float
    effective_price: Optional[float]
    net_ev: float
    edge: float
    is_tradable: bool
    target_size: float
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        """Serialize trade signal to dictionary."""
        return {
            "station_id": self.station_id,
            "bin_index": self.bin_index,
            "bin_label": self.bin_label,
            "model_probability": self.model_probability,
            "effective_price": self.effective_price,
            "net_ev": self.net_ev,
            "edge": self.edge,
            "is_tradable": self.is_tradable,
            "target_size": self.target_size,
            "reason": self.reason,
        }


class DynamicEVEngine:
    """
    Evaluates orderbook microstructure and calculates expected value (EV) for trading decisions.
    """

    def __init__(self, config: Optional[EVConfig] = None):
        self.config = config or EVConfig()

    def calculate_effective_price(
        self,
        asks: List[OrderBookLevel],
        target_size: float,
    ) -> Optional[float]:
        """
        Calculate volume-weighted average price (VWAP) across ask tiers to fill target_size.
        Returns None if total available size across all ask tiers is less than target_size.
        """
        if target_size <= 0.0:
            return 0.0

        accumulated_size = 0.0
        total_cost = 0.0

        # Ensure asks are sorted ascending by price
        sorted_asks = sorted(asks, key=lambda lvl: lvl.price)

        for lvl in sorted_asks:
            needed = target_size - accumulated_size
            take = min(lvl.size, needed)
            total_cost += take * lvl.price
            accumulated_size += take

            if accumulated_size >= target_size - 1e-9:
                return total_cost / target_size

        # Insufficient depth to satisfy target_size
        return None

    def evaluate_bin(
        self,
        snapshot: OrderBookSnapshot,
        model_probability: float,
        target_size: float,
    ) -> EVTradeSignal:
        """
        Evaluate net EV and edge for buying shares in a discrete market bin.
        Net EV = model_prob * (1 - fee) - P_eff
        Edge = Net EV / P_eff
        """
        p_eff = self.calculate_effective_price(asks=snapshot.asks, target_size=target_size)

        if p_eff is None:
            return EVTradeSignal(
                station_id=snapshot.station_id,
                bin_index=snapshot.bin_index,
                bin_label=snapshot.bin_label,
                model_probability=model_probability,
                effective_price=None,
                net_ev=0.0,
                edge=0.0,
                is_tradable=False,
                target_size=target_size,
                reason="REJECTED_INSUFFICIENT_DEPTH",
            )

        # Calculate Net Payout & Net EV
        net_payout = model_probability * (1.0 - self.config.fee_rate)
        net_ev = net_payout - p_eff

        if p_eff > 1e-9:
            edge = net_ev / p_eff
        else:
            edge = 0.0

        if net_ev <= 0.0:
            return EVTradeSignal(
                station_id=snapshot.station_id,
                bin_index=snapshot.bin_index,
                bin_label=snapshot.bin_label,
                model_probability=model_probability,
                effective_price=p_eff,
                net_ev=net_ev,
                edge=edge,
                is_tradable=False,
                target_size=target_size,
                reason="REJECTED_NEGATIVE_EV",
            )

        if edge < self.config.min_reprice_edge:
            return EVTradeSignal(
                station_id=snapshot.station_id,
                bin_index=snapshot.bin_index,
                bin_label=snapshot.bin_label,
                model_probability=model_probability,
                effective_price=p_eff,
                net_ev=net_ev,
                edge=edge,
                is_tradable=False,
                target_size=target_size,
                reason="REJECTED_EDGE_BELOW_THRESHOLD",
            )

        return EVTradeSignal(
            station_id=snapshot.station_id,
            bin_index=snapshot.bin_index,
            bin_label=snapshot.bin_label,
            model_probability=model_probability,
            effective_price=p_eff,
            net_ev=net_ev,
            edge=edge,
            is_tradable=True,
            target_size=target_size,
            reason="APPROVED_POSITIVE_EV",
        )
