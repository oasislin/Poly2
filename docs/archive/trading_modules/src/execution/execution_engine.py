"""
Unified CLOB Execution Engine (Phase 2 Task 06 - Ticket 04 / Issue #92).
Orchestrates pre-buy gatekeeping, two-dimensional risk haircuts, IOC protection routing,
bankroll ledger synchronization, and residual risk state machine healing.
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN
import logging
from typing import Dict, List, Optional

from src.bankroll.bankroll_manager import BankrollManager
from src.execution.clob_client import CLOBClientInterface
from src.execution.models import (
    CLOBOrder,
    OrderStatus,
    SIZE_DECIMAL_PLACES,
)
from src.execution.order_router import OrderRouter, RouterExecutionReport
from src.execution.residual_risk import (
    ResidualRiskConfig,
    ResidualRiskStateMachine,
    ResidualState,
)
from src.risk.central_arbiter import CentralExceptionArbiter
from src.risk.pre_buy_gate import LocalHardValve
from src.risk.two_dimensional_risk import (
    RiskRegime,
    TwoDimensionalRiskController,
)

logger = logging.getLogger(__name__)


@dataclass
class EngineExecutionResult:
    """Consolidated outcome of the execution engine trade orchestration."""
    executed: bool
    station_id: str
    market_id: str
    risk_regime: RiskRegime
    orders: List[CLOBOrder] = field(default_factory=list)
    committed_cost: Decimal = Decimal("0.000000")
    residual_state: ResidualState = ResidualState.CLEAN
    blocked_reason: Optional[str] = None


class CLOBExecutionEngine:
    """
    Production-grade execution orchestrator for Polymarket CLOB trading.
    """

    def __init__(
        self,
        clob_client: CLOBClientInterface,
        bankroll_manager: BankrollManager,
        arbiter: Optional[CentralExceptionArbiter] = None,
        hard_valve: Optional[LocalHardValve] = None,
        risk_controller: Optional[TwoDimensionalRiskController] = None,
        residual_config: Optional[ResidualRiskConfig] = None,
        min_edge: float = 0.0,
    ):
        self.clob_client = clob_client
        self.bankroll_manager = bankroll_manager
        self.arbiter = arbiter
        self.hard_valve = hard_valve
        self.risk_controller = risk_controller or TwoDimensionalRiskController()
        self.order_router = OrderRouter(
            clob_client=self.clob_client,
            bankroll_manager=self.bankroll_manager,
            min_edge=min_edge,
        )
        self.residual_sm = ResidualRiskStateMachine(
            clob_client=self.clob_client,
            bankroll_manager=self.bankroll_manager,
            config=residual_config,
        )

    def execute_strategy(
        self,
        station_id: str,
        market_id: str,
        allocations: Dict[int, Decimal],
        model_probs: Dict[int, float],
        bin_labels: Dict[int, str],
        t_remain_hours: float,
        current_temp_f: float,
        bin_centers: Optional[Dict[int, float]] = None,
    ) -> EngineExecutionResult:
        """
        Execute full trade pipeline:
        1. Pre-buy safety checks (Arbiter + HardValve)
        2. Two-dimensional risk evaluation (Haircut / Directional lock)
        3. Protected IOC Limit Order Routing
        4. Residual Risk evaluation & healing
        """
        # Step 1: Pre-buy safety gate checks
        if self.arbiter is not None and not self.arbiter.is_station_tradable(station_id):
            state = self.arbiter.get_station_state(station_id).value
            logger.critical(f"Trade blocked: Station '{station_id}' state is {state} (SUSPENDED/INVALIDATED)")
            return EngineExecutionResult(
                executed=False,
                station_id=station_id,
                market_id=market_id,
                risk_regime=RiskRegime.NORMAL,
                blocked_reason=f"Station '{station_id}' state is {state} in CentralExceptionArbiter",
            )

        if self.hard_valve is not None and not self.hard_valve.is_open(station_id):
            logger.critical(f"Trade blocked: Local hard valve closed for '{station_id}'")
            return EngineExecutionResult(
                executed=False,
                station_id=station_id,
                market_id=market_id,
                risk_regime=RiskRegime.NORMAL,
                blocked_reason=f"Local hard valve is closed for station '{station_id}'",
            )

        # Step 2: Two-dimensional ladder risk assessment
        # Compute delta_T: distance between current temp and primary probability mass
        delta_temp_f = 0.0
        if bin_centers and model_probs:
            best_bin = max(model_probs, key=lambda b: model_probs[b])
            target_temp = bin_centers.get(best_bin, current_temp_f)
            delta_temp_f = abs(target_temp - current_temp_f)

        risk_decision = self.risk_controller.evaluate_regime(t_remain_hours, delta_temp_f)
        logger.info(f"Two-dimensional risk verdict for {station_id}: {risk_decision.regime.value} ({risk_decision.reason})")

        # Adjust allocations based on regime
        effective_allocations: Dict[int, Decimal] = {}
        for b, alloc in allocations.items():
            if alloc <= Decimal("0.000000"):
                continue

            # In Certain Regime, forbid opposite speculative orders (distant bins)
            if risk_decision.forbid_opposite_speculation and bin_centers:
                bin_temp = bin_centers.get(b, current_temp_f)
                if abs(bin_temp - current_temp_f) > 1.5:
                    logger.info(f"Skipping opposite speculative bin {b} ({bin_temp}°F vs {current_temp_f}°F) in CERTAIN regime.")
                    continue

            # Scale by sizing multiplier (e.g. 0.20 in Critical regime)
            scaled_alloc = (alloc * risk_decision.sizing_multiplier).quantize(SIZE_DECIMAL_PLACES, rounding=ROUND_DOWN)
            if scaled_alloc > Decimal("0.000000"):
                effective_allocations[b] = scaled_alloc

        if not effective_allocations:
            return EngineExecutionResult(
                executed=True,
                station_id=station_id,
                market_id=market_id,
                risk_regime=risk_decision.regime,
                committed_cost=Decimal("0.000000"),
                residual_state=ResidualState.CLEAN,
                blocked_reason="No effective allocations after risk regime scaling",
            )

        # Step 3: Route protected IOC limit orders
        router_report = self.order_router.route_allocations(
            station_id=station_id,
            market_id=market_id,
            allocations=effective_allocations,
            model_probs=model_probs,
            bin_labels=bin_labels,
        )

        # Step 4: Extract initial fill quantities
        fills: Dict[int, Decimal] = {}
        for order in router_report.orders:
            fills[order.bin_index] = order.filled_size

        # Step 5: Process through residual risk healing state machine
        res_state = self.residual_sm.handle_execution_result(
            station_id=station_id,
            market_id=market_id,
            fills=fills,
            model_probs=model_probs,
            total_cost=router_report.total_committed_cost,
        )

        return EngineExecutionResult(
            executed=True,
            station_id=station_id,
            market_id=market_id,
            risk_regime=risk_decision.regime,
            orders=router_report.orders,
            committed_cost=router_report.total_committed_cost,
            residual_state=res_state,
        )

    def emergency_cancel_all(self, station_id: Optional[str] = None) -> List[str]:
        """
        Emergency 0ms cancel all outstanding open orders without disrupting filled positions.
        """
        return self.clob_client.cancel_all_orders(station_id=station_id)
