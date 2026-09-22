"""
Settlement Simulator for Paper Trading (Phase 2 Task 07 - Ticket 02 / Issue #96).
Coordinates terminal settlement against ground-truth station observations,
payout credit to Free USDC, position liquidation, and zombie margin transfer.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import logging
from typing import Dict, List, Optional

from src.bankroll.bankroll_manager import BankrollManager, to_usdc_decimal
from src.execution.models import SIZE_DECIMAL_PLACES
from src.simulation.models import PaperPosition

logger = logging.getLogger(__name__)

PAYOUT_PER_SHARE = Decimal("1.000000")  # Polymarket pays 1 USDC per winning share


@dataclass
class SettlementRecord:
    """Audit summary of market settlement."""
    market_id: str
    winning_bin_index: int
    total_shares_held: Decimal
    total_cost: Decimal
    total_payout: Decimal
    net_pnl: Decimal
    settled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, float]:
        return {
            "total_shares_held": float(self.total_shares_held),
            "total_cost": float(self.total_cost),
            "total_payout": float(self.total_payout),
            "net_pnl": float(self.net_pnl),
        }


class SettlementSimulator:
    """
    Simulates official market resolution and ledger accounting.
    """

    def __init__(self, bankroll_manager: BankrollManager):
        self.bankroll_manager = bankroll_manager

    def settle_market(
        self,
        market_id: str,
        winning_bin_index: int,
        positions: List[PaperPosition],
    ) -> SettlementRecord:
        """
        Settle all positions for a specific market against winning_bin_index.
        Releases locked capital from active_locked and credits winning payout to free_usdc.
        """
        total_shares = Decimal("0.000000")
        total_cost = Decimal("0.000000")
        total_payout = Decimal("0.000000")

        for pos in positions:
            if pos.market_id != market_id:
                continue
            total_shares += pos.shares
            total_cost += pos.total_cost

            if pos.bin_index == winning_bin_index:
                # Winning position: 1 USDC per share
                win_payout = (pos.shares * PAYOUT_PER_SHARE).quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)
                total_payout += win_payout

        # Settle through bankroll manager
        self.bankroll_manager.settle_position(
            original_locked=total_cost,
            payout=total_payout,
        )

        net_pnl = total_payout - total_cost
        logger.info(
            f"Market {market_id} settled. Winning bin: {winning_bin_index}, "
            f"Total Cost: {total_cost}, Total Payout: {total_payout}, Net PnL: {net_pnl}"
        )

        return SettlementRecord(
            market_id=market_id,
            winning_bin_index=winning_bin_index,
            total_shares_held=total_shares,
            total_cost=total_cost,
            total_payout=total_payout,
            net_pnl=net_pnl,
        )

    def handle_overdue_market(
        self,
        market_id: str,
        positions: List[PaperPosition],
        overdue_hours: float,
    ) -> Decimal:
        """
        If market has been un-settled for > 12 hours past expected resolution,
        move active locked funds into Zombie Margin according to ADR-0012 §D4.
        """
        if overdue_hours < 12.0:
            return Decimal("0.000000")

        overdue_cost = Decimal("0.000000")
        for pos in positions:
            if pos.market_id == market_id:
                overdue_cost += pos.total_cost

        if overdue_cost > Decimal("0.000000"):
            self.bankroll_manager.transfer_to_zombie(overdue_cost)
            logger.warning(
                f"Market {market_id} is overdue ({overdue_hours:.1f}h > 12.0h). "
                f"Transferred {overdue_cost} USDC to Zombie Margin."
            )

        return overdue_cost
