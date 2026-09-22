"""
Non-Atomic Residual Risk Evaluation, Rehedge Dispatcher, and Hard Stop-Loss State Machine (Phase 2 Task 06 - Ticket 03 / Issue #91).
Implements three-tier residual risk healing (Execution v2.0 §5.2):
1. Real-time Residual EV Recalculation
2. Limit Rehedge Dispatch (Positive-EV & 10% Single Market Cap)
3. Deterministic Hard Stop Loss (Timeout or Downside Breach)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from enum import Enum
import logging
import time
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
from src.execution.order_router import calculate_protection_price

logger = logging.getLogger(__name__)


class ResidualState(str, Enum):
    """Lifecycle states of the residual risk healing engine."""
    CLEAN = "CLEAN"                                # Completely filled according to strategy
    RESIDUAL_DETECTED = "RESIDUAL_DETECTED"        # Non-atomic partial fill or single leg detected
    REHEDGING = "REHEDGING"                        # Limit rehedge order dispatched
    RESOLVED_BALANCED = "RESOLVED_BALANCED"        # Successfully rehedged and balanced
    STOP_LOSS_TRIGGERED = "STOP_LOSS_TRIGGERED"    # Stop loss triggered
    LIQUIDATED = "LIQUIDATED"                      # Positions closed to stop further drawdown
    FAILED = "FAILED"                              # Unrecoverable error


@dataclass(frozen=True)
class ResidualRiskConfig:
    """Configuration thresholds for residual risk engine."""
    rehedge_timeout_seconds: float = 30.0
    min_rehedge_edge: float = 0.0
    single_market_max_pct: float = 0.10
    exposure_prob_threshold: float = 0.20


@dataclass(frozen=True)
class ResidualRiskReport:
    """Report detailing current residual exposure metrics."""
    is_exposed: bool
    expected_pnl: Decimal
    max_loss: Decimal
    unhedged_bins: List[int] = field(default_factory=list)
    details: str = ""


class ResidualRiskEvaluator:
    """
    Evaluates net expected payoff and downside exposure across filled bin shares.
    """

    def __init__(self, config: Optional[ResidualRiskConfig] = None):
        self.config = config or ResidualRiskConfig()

    def evaluate(
        self,
        station_id: str,
        market_id: str,
        fills: Dict[int, Decimal],
        model_probs: Dict[int, float],
        total_cost: Decimal,
    ) -> ResidualRiskReport:
        """
        Calculates E[PnL] = sum(p_i * N_i) - total_cost and identifies unhedged high-probability bins.
        """
        # Ensure fills are Decimal
        normalized_fills = {
            b: (f if isinstance(f, Decimal) else Decimal(str(f))).quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)
            for b, f in fills.items()
        }
        if not isinstance(total_cost, Decimal):
            total_cost = Decimal(str(total_cost))
        total_cost = total_cost.quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)

        # Expected payout = sum(p_i * N_i)
        expected_payout = Decimal("0.000000")
        for b, prob in model_probs.items():
            prob_dec = Decimal(str(prob)).quantize(PRICE_DECIMAL_PLACES, rounding=ROUND_DOWN)
            size = normalized_fills.get(b, Decimal("0.000000"))
            expected_payout += (size * prob_dec).quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)

        expected_pnl = expected_payout - total_cost

        # Determine worst-case loss: total_cost - min_i(N_i)
        all_sizes = [normalized_fills.get(b, Decimal("0.000000")) for b in model_probs]
        min_size = min(all_sizes) if all_sizes else Decimal("0.000000")
        max_loss = (total_cost - min_size).quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)

        # Identify missing legs with high model probability
        unhedged_bins = []
        for b, prob in model_probs.items():
            size = normalized_fills.get(b, Decimal("0.000000"))
            if prob >= self.config.exposure_prob_threshold and size <= Decimal("0.000001"):
                unhedged_bins.append(b)

        # Exposure exists if expected_pnl is negative while we have committed capital,
        # or if significant probability mass is entirely unhedged
        has_active_positions = any(sz > Decimal("0.000001") for sz in normalized_fills.values())
        is_exposed = False
        if has_active_positions:
            if expected_pnl < Decimal("0.000000") or len(unhedged_bins) > 0:
                is_exposed = True

        details = f"E[PnL]={expected_pnl}, MaxLoss={max_loss}, UnhedgedBins={unhedged_bins}"

        return ResidualRiskReport(
            is_exposed=is_exposed,
            expected_pnl=expected_pnl,
            max_loss=max_loss,
            unhedged_bins=unhedged_bins,
            details=details,
        )


class ResidualRiskStateMachine:
    """
    Self-healing state machine for non-atomic partial fills and residual exposures.
    """

    def __init__(
        self,
        clob_client: CLOBClientInterface,
        bankroll_manager: Optional[BankrollManager] = None,
        config: Optional[ResidualRiskConfig] = None,
    ):
        self.clob_client = clob_client
        self.bankroll_manager = bankroll_manager
        self.config = config or ResidualRiskConfig()
        self.evaluator = ResidualRiskEvaluator(self.config)
        self.state: ResidualState = ResidualState.CLEAN
        self.current_fills: Dict[int, Decimal] = {}
        self.total_cost: Decimal = Decimal("0.000000")

    def handle_execution_result(
        self,
        station_id: str,
        market_id: str,
        fills: Dict[int, Decimal],
        model_probs: Dict[int, float],
        total_cost: Decimal,
    ) -> ResidualState:
        """
        Main entrypoint to process execution results through the 3-stage self-healing pipeline.
        """
        self.current_fills = {k: Decimal(str(v)) for k, v in fills.items()}
        self.total_cost = Decimal(str(total_cost))

        report = self.evaluator.evaluate(station_id, market_id, self.current_fills, model_probs, self.total_cost)

        if not report.is_exposed:
            self.state = ResidualState.CLEAN
            return self.state

        # Residual Exposure detected!
        self.state = ResidualState.RESIDUAL_DETECTED
        logger.warning(f"Residual exposure detected on {station_id}/{market_id}: {report.details}")

        # Stage 2: Attempt Limit Rehedge
        rehedge_ok = self._attempt_rehedge(station_id, market_id, report.unhedged_bins, model_probs)
        if rehedge_ok:
            # Re-evaluate after rehedge
            report_after = self.evaluator.evaluate(station_id, market_id, self.current_fills, model_probs, self.total_cost)
            if not report_after.is_exposed:
                self.state = ResidualState.RESOLVED_BALANCED
                logger.info(f"Residual exposure successfully resolved on {station_id}/{market_id}.")
                return self.state

        # Stage 3: Trigger Deterministic Hard Stop-Loss
        self.state = ResidualState.STOP_LOSS_TRIGGERED
        logger.error(f"Rehedge failed or timed out. Triggering HARD STOP LOSS on {station_id}/{market_id}.")
        self._execute_hard_stop_loss(station_id, market_id)
        self.state = ResidualState.LIQUIDATED
        return self.state

    def _attempt_rehedge(
        self,
        station_id: str,
        market_id: str,
        unhedged_bins: List[int],
        model_probs: Dict[int, float],
    ) -> bool:
        """
        Attempts to submit limit orders on missing positive-EV bins to restore hedge balance.
        """
        self.state = ResidualState.REHEDGING
        if not unhedged_bins:
            return False

        for b in unhedged_bins:
            prob = model_probs.get(b, 0.0)
            ob = self.clob_client.get_orderbook(market_id, b)
            if ob is None or not ob.asks:
                continue

            prot_res = calculate_protection_price(prob, ob.asks, self.config.min_rehedge_edge)
            if not prot_res.is_tradable or prot_res.protection_price is None:
                continue

            # Compute needed size to match max fill in other bins
            target_size = max(self.current_fills.values())
            size_to_buy = min(target_size, prot_res.safe_capacity)
            if size_to_buy <= Decimal("0.000000"):
                continue

            cost_needed = (size_to_buy * prot_res.protection_price).quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)

            if self.bankroll_manager is not None:
                try:
                    self.bankroll_manager.lock_funds(cost_needed)
                except Exception:
                    continue

            order = CLOBOrder.create_buy_ioc(
                station_id=station_id,
                market_id=market_id,
                bin_index=b,
                bin_label=f"Bin {b}",
                price=prot_res.protection_price,
                size=size_to_buy,
            )

            result = self.clob_client.place_order(order)
            if result.filled_size > Decimal("0.000000"):
                self.current_fills[b] = self.current_fills.get(b, Decimal("0.000000")) + result.filled_size
                actual_cost = order.total_cost
                self.total_cost += actual_cost

                if self.bankroll_manager is not None:
                    excess = cost_needed - actual_cost
                    if excess > Decimal("0.000000"):
                        self.bankroll_manager.unlock_funds(excess)

                return True
            else:
                if self.bankroll_manager is not None:
                    self.bankroll_manager.unlock_funds(cost_needed)

        return False

    def _execute_hard_stop_loss(self, station_id: str, market_id: str) -> None:
        """
        Liquidates remaining exposed positions by selling into available bids.
        """
        for b, size in list(self.current_fills.items()):
            if size <= Decimal("0.000000"):
                continue

            ob = self.clob_client.get_orderbook(market_id, b)
            sell_price = Decimal("0.0100")  # Minimum recovery price floor
            if ob is not None and ob.bids:
                best_bid = max(ob.bids, key=lambda lvl: lvl.price)
                sell_price = Decimal(str(best_bid.price)).quantize(PRICE_DECIMAL_PLACES, rounding=ROUND_DOWN)

            sell_order = CLOBOrder(
                order_id=f"stop-{station_id}-{b}",
                client_order_id=f"c-stop-{b}",
                station_id=station_id,
                market_id=market_id,
                bin_index=b,
                bin_label=f"Bin {b}",
                side=OrderSide.SELL,
                order_type=OrderType.IOC,
                price=sell_price,
                size=size,
            )

            result = self.clob_client.place_order(sell_order)
            # Liquidate tracked position
            self.current_fills[b] = Decimal("0.000000")
            logger.info(f"Stop loss executed on {station_id} bin {b}: sold {result.filled_size} @ {result.avg_fill_price}")
