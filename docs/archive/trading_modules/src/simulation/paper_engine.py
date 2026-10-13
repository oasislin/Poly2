"""
Paper Trading Simulator and End-to-End Orchestrator (Phase 2 Task 07 - Ticket 02 / Issue #96).
Integrates CentralExceptionArbiter, TwoDimensionalRiskController, MultinomialKellyOptimizer,
CLOBExecutionEngine, SettlementSimulator, and Four-Bucket BankrollManager into an event-driven loop.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import logging
from typing import Any, Dict, List, Optional, Tuple

from src.bankroll.bankroll_manager import BankrollManager
from src.bankroll.multinomial_kelly import MultinomialKellyOptimizer
from src.bankroll.risk_limiter import RiskLimiter, RiskLimiterConfig
from src.execution.clob_client import CLOBClientInterface
from src.execution.execution_engine import CLOBExecutionEngine, EngineExecutionResult
from src.execution.models import SIZE_DECIMAL_PLACES
from src.risk.central_arbiter import CentralExceptionArbiter
from src.risk.two_dimensional_risk import TwoDimensionalRiskController
from src.simulation.clock import SimulationClock
from src.simulation.models import (
    PaperPosition,
    PaperTradeRecord,
    SimulationEvent,
    SimulationEventType,
)
from src.simulation.settlement_sim import SettlementRecord, SettlementSimulator

logger = logging.getLogger(__name__)


@dataclass
class PaperSimulationConfig:
    """Configuration parameters for paper trading simulation."""
    fractional_multiplier: Decimal = Decimal("0.5")  # Half-Kelly
    single_market_cap_ratio: Decimal = Decimal("0.10")  # 10% Bankroll max per market
    global_utilization_cap_ratio: Decimal = Decimal("0.70")  # 70% Max total bankroll deployment
    min_edge: float = 0.02  # 2% minimum edge required to issue orders
    auto_rehedge: bool = True


class PaperTradingSimulator:
    """
    Production-grade Paper Trading Simulator executing full Phase 2 pipeline.
    """

    def __init__(
        self,
        clock: SimulationClock,
        bankroll_manager: BankrollManager,
        clob_client: CLOBClientInterface,
        arbiter: Optional[CentralExceptionArbiter] = None,
        risk_controller: Optional[TwoDimensionalRiskController] = None,
        config: Optional[PaperSimulationConfig] = None,
    ):
        self.clock = clock
        self.bankroll_manager = bankroll_manager
        self.clob_client = clob_client
        self.arbiter = arbiter or CentralExceptionArbiter()
        self.risk_controller = risk_controller or TwoDimensionalRiskController()
        self.config = config or PaperSimulationConfig()

        self.limiter = RiskLimiter(
            RiskLimiterConfig(
                fractional_multiplier=self.config.fractional_multiplier,
                single_market_cap_ratio=self.config.single_market_cap_ratio,
                global_utilization_cap_ratio=self.config.global_utilization_cap_ratio,
            )
        )
        self.kelly_optimizer = MultinomialKellyOptimizer()

        self.execution_engine = CLOBExecutionEngine(
            clob_client=self.clob_client,
            bankroll_manager=self.bankroll_manager,
            arbiter=self.arbiter,
            risk_controller=self.risk_controller,
            min_edge=self.config.min_edge,
        )

        self.settlement_sim = SettlementSimulator(bankroll_manager=self.bankroll_manager)

        # Storage
        self.positions: Dict[Tuple[str, str, int], PaperPosition] = {}  # (station, market, bin) -> pos
        self.trade_history: List[PaperTradeRecord] = []
        self.events: List[SimulationEvent] = []
        self.non_physical_orders_count: int = 0

    def on_weather_observation(
        self,
        station_id: str,
        current_temp_f: float,
        obs_time: datetime,
    ) -> None:
        """Process incoming station weather observation and update Arbiter status."""
        if self.arbiter:
            self.arbiter.check_calendar_rollover(station_id=station_id, current_wall_time=obs_time)
            self.arbiter.record_healthy_frame(station_id=station_id, current_wall_time=obs_time)

        self.events.append(
            SimulationEvent(
                timestamp=obs_time,
                event_type=SimulationEventType.OBSERVATION_UPDATE,
                station_id=station_id,
                details={"current_temp_f": current_temp_f},
            )
        )

    def evaluate_and_execute(
        self,
        station_id: str,
        market_id: str,
        model_probs: Dict[int, float],
        bin_labels: Dict[int, str],
        bin_centers: Dict[int, float],
        t_remain_hours: float,
        current_temp_f: float,
    ) -> EngineExecutionResult:
        """
        Evaluate full quantitative cycle and route paper orders.
        Strictly enforces Zero Non-physical Orders Theorem.
        """
        now = self.clock.now()

        # Step 1: Pre-check Arbiter
        if self.arbiter and not self.arbiter.is_station_tradable(station_id):
            logger.warning(f"Paper trading blocked for {station_id} by CentralExceptionArbiter.")
            return EngineExecutionResult(
                executed=False,
                station_id=station_id,
                market_id=market_id,
                risk_regime=self.risk_controller.evaluate_regime(t_remain_hours, 0.0).regime,
                blocked_reason="Arbiter blocked station",
            )

        # Step 2: Fetch current market book prices for available bins
        num_bins = len(bin_labels)
        prices: List[float] = []
        probs: List[float] = []
        bin_indices = sorted(bin_labels.keys())

        for b in bin_indices:
            probs.append(model_probs.get(b, 0.0))
            snap = self.clob_client.get_orderbook(market_id, b)
            if snap and snap.asks:
                best_ask = min(lvl.price for lvl in snap.asks)
            else:
                best_ask = 1.0  # Prohibitive price if no liquidity
            prices.append(best_ask)

        # Step 3: Extract existing payout vector for current holdings
        existing_payouts: List[float] = []
        market_current_cost = Decimal("0.000000")
        for b in bin_indices:
            key = (station_id, market_id, b)
            pos = self.positions.get(key)
            if pos:
                existing_payouts.append(float(pos.shares))
                market_current_cost += pos.total_cost
            else:
                existing_payouts.append(0.0)

        # Step 4: Multinomial Kelly Optimization
        bal = self.bankroll_manager.get_balance()
        free_usdc = float(bal.free_usdc)

        kelly_res = self.kelly_optimizer.optimize(
            probabilities=probs,
            prices=prices,
            existing_payouts=existing_payouts,
            w_free=free_usdc,
        )

        raw_allocations: Dict[int, Decimal] = {}
        for idx, b in enumerate(bin_indices):
            alloc_val = Decimal(f"{kelly_res.optimal_allocations[idx]:.6f}")
            # Strict Zero Non-physical Orders Guardrail:
            if probs[idx] <= 0.0 or prices[idx] >= 1.0:
                alloc_val = Decimal("0.000000")
            raw_allocations[b] = alloc_val

        # Step 5: Risk Limiter (Fractional Kelly, 10% market cap, 70% global cap)
        raw_allocations_list = [raw_allocations[b] for b in bin_indices]
        limiter_res = self.limiter.apply_limits(
            market_id=market_id,
            raw_allocations=raw_allocations_list,
            current_market_exposure=market_current_cost,
            bankroll_manager=self.bankroll_manager,
        )

        effective_allocations: Dict[int, Decimal] = {
            b: limiter_res.approved_allocations[i] for i, b in enumerate(bin_indices)
        }

        # Step 6: CLOB Execution Engine (IOC Protection, Two-Dimensional Risk Haircut, Residual Healing)
        exec_res = self.execution_engine.execute_strategy(
            station_id=station_id,
            market_id=market_id,
            allocations=effective_allocations,
            model_probs=model_probs,
            bin_labels=bin_labels,
            t_remain_hours=t_remain_hours,
            current_temp_f=current_temp_f,
            bin_centers=bin_centers,
        )

        # Step 7: Record Positions & Trade Audit
        if exec_res.executed:
            final_fills = self.execution_engine.residual_sm.current_fills
            for order in exec_res.orders:
                if order.filled_size > Decimal("0.000000"):
                    if model_probs.get(order.bin_index, 0.0) <= 0.0:
                        self.non_physical_orders_count += 1
                        logger.critical(f"FATAL: Non-physical order placed on bin {order.bin_index}!")

                    b_idx = order.bin_index
                    key = (station_id, market_id, b_idx)
                    if key not in self.positions:
                        self.positions[key] = PaperPosition(
                            station_id=station_id,
                            market_id=market_id,
                            bin_index=b_idx,
                            bin_label=bin_labels.get(b_idx, f"Bin {b_idx}"),
                        )
                    fill_cost = (order.avg_fill_price * order.filled_size).quantize(
                        SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN
                    )
                    self.positions[key].add_fill(shares=order.filled_size, cost=fill_cost)

                    trade_rec = PaperTradeRecord(
                        timestamp=now,
                        station_id=station_id,
                        market_id=market_id,
                        bin_index=b_idx,
                        action="BUY",
                        shares=order.filled_size,
                        price=order.avg_fill_price,
                        total_cost=fill_cost,
                    )
                    self.trade_history.append(trade_rec)
                    self.events.append(
                        SimulationEvent(
                            timestamp=now,
                            event_type=SimulationEventType.ORDER_FILLED,
                            station_id=station_id,
                            details=trade_rec.to_dict(),
                        )
                    )

            # Check if Residual Risk State Machine added extra rehedge fills
            for b_idx, total_fill_size in final_fills.items():
                key = (station_id, market_id, b_idx)
                existing_pos = self.positions.get(key)
                existing_shares = existing_pos.shares if existing_pos else Decimal("0.000000")
                diff_shares = total_fill_size - existing_shares
                if diff_shares > Decimal("0.000000"):
                    # Additional rehedge fill
                    snap = self.clob_client.get_orderbook(market_id, b_idx)
                    rehedge_price = Decimal(str(snap.asks[0].price)) if (snap and snap.asks) else Decimal("0.5000")
                    rehedge_cost = (diff_shares * rehedge_price).quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)

                    if key not in self.positions:
                        self.positions[key] = PaperPosition(
                            station_id=station_id,
                            market_id=market_id,
                            bin_index=b_idx,
                            bin_label=bin_labels.get(b_idx, f"Bin {b_idx}"),
                        )
                    self.positions[key].add_fill(shares=diff_shares, cost=rehedge_cost)

                    rehedge_rec = PaperTradeRecord(
                        timestamp=now,
                        station_id=station_id,
                        market_id=market_id,
                        bin_index=b_idx,
                        action="REHEDGE",
                        shares=diff_shares,
                        price=rehedge_price,
                        total_cost=rehedge_cost,
                    )
                    self.trade_history.append(rehedge_rec)
                    self.events.append(
                        SimulationEvent(
                            timestamp=now,
                            event_type=SimulationEventType.ORDER_FILLED,
                            station_id=station_id,
                            details=rehedge_rec.to_dict(),
                        )
                    )

        return exec_res

    def settle_market(
        self,
        market_id: str,
        winning_bin_index: int,
    ) -> SettlementRecord:
        """Settle a market upon official resolution."""
        now = self.clock.now()
        market_positions = [
            pos for (s, m, b), pos in list(self.positions.items()) if m == market_id
        ]

        record = self.settlement_sim.settle_market(
            market_id=market_id,
            winning_bin_index=winning_bin_index,
            positions=market_positions,
        )

        # Remove settled positions
        for (s, m, b) in list(self.positions.keys()):
            if m == market_id:
                del self.positions[(s, m, b)]

        self.events.append(
            SimulationEvent(
                timestamp=now,
                event_type=SimulationEventType.SETTLEMENT,
                station_id=market_id.split("-")[0] if "-" in market_id else "UNKNOWN",
                details=record.to_dict(),
            )
        )

        return record
