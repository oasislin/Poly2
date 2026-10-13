"""
Unit tests for TwoDimensionalRiskController and CLOBExecutionEngine (Phase 2 Task 06 - Ticket 04 / Issue #92).
"""

from decimal import Decimal
import pytest

from src.bankroll.bankroll_manager import BankrollManager
from src.execution.clob_client import MockCLOBClient
from src.execution.execution_engine import (
    CLOBExecutionEngine,
    EngineExecutionResult,
)
from src.execution.models import OrderStatus
from src.pricing.ev_engine import OrderBookLevel, OrderBookSnapshot
from src.risk.central_arbiter import CentralExceptionArbiter, StationLifeCycleState
from src.risk.pre_buy_gate import LocalHardValve
from src.risk.two_dimensional_risk import (
    RiskRegime,
    TwoDimensionalRiskConfig,
    TwoDimensionalRiskController,
)


class TestTwoDimensionalRiskController:
    """Tests for two-dimensional ladder risk thresholds (Execution v2.0 §5.3)."""

    def test_critical_regime_applies_0_2_haircut(self):
        """T_remain < 1.0h and delta_T > 3.0F triggers CRITICAL regime with 0.2 sizing."""
        controller = TwoDimensionalRiskController()
        decision = controller.evaluate_regime(
            t_remain_hours=0.8,
            delta_temp_f=4.5,
        )
        assert decision.regime == RiskRegime.CRITICAL
        assert decision.sizing_multiplier == Decimal("0.20")
        assert decision.forbid_opposite_speculation is False

    def test_certain_regime_forbids_opposite_speculation(self):
        """delta_T <= 0.5F and T_remain < 0.5h triggers CERTAIN regime."""
        controller = TwoDimensionalRiskController()
        decision = controller.evaluate_regime(
            t_remain_hours=0.4,
            delta_temp_f=0.3,
        )
        assert decision.regime == RiskRegime.CERTAIN
        assert decision.sizing_multiplier == Decimal("1.00")
        assert decision.forbid_opposite_speculation is True

    def test_normal_regime(self):
        """Far from closing with moderate delta_T operates in NORMAL regime."""
        controller = TwoDimensionalRiskController()
        decision = controller.evaluate_regime(
            t_remain_hours=4.0,
            delta_temp_f=2.0,
        )
        assert decision.regime == RiskRegime.NORMAL
        assert decision.sizing_multiplier == Decimal("1.00")
        assert decision.forbid_opposite_speculation is False


class TestCLOBExecutionEngine:
    """Tests for unified CLOB execution engine orchestration."""

    @pytest.fixture
    def setup_engine(self):
        client = MockCLOBClient()
        bm = BankrollManager(initial_free_usdc=Decimal("1000.000000"))
        arbiter = CentralExceptionArbiter()
        valve = LocalHardValve(arbiter=arbiter)
        risk_ctrl = TwoDimensionalRiskController()
        engine = CLOBExecutionEngine(
            clob_client=client,
            bankroll_manager=bm,
            arbiter=arbiter,
            hard_valve=valve,
            risk_controller=risk_ctrl,
        )
        return engine, client, bm, arbiter, valve

    def test_execution_blocked_when_station_suspended(self, setup_engine):
        engine, client, bm, arbiter, valve = setup_engine

        # Suspend KORD in arbiter
        arbiter._states["KORD"].state = StationLifeCycleState.SUSPENDED
        arbiter._states["KORD"].last_reason = "Heartbeat lost"

        allocations = {1: Decimal("50.000000")}
        model_probs = {1: 0.60}
        bin_labels = {1: "[70, 72)"}

        result = engine.execute_strategy(
            station_id="KORD",
            market_id="mkt-kord",
            allocations=allocations,
            model_probs=model_probs,
            bin_labels=bin_labels,
            t_remain_hours=2.0,
            current_temp_f=71.0,
            bin_centers={1: 71.0},
        )
        assert result.executed is False
        assert "SUSPENDED" in result.blocked_reason

    def test_execution_haircut_in_critical_regime(self, setup_engine):
        engine, client, bm, arbiter, valve = setup_engine

        # Seed orderbook for KORD bin 1
        ob = OrderBookSnapshot(
            station_id="KORD",
            bin_index=1,
            bin_label="[70, 72)",
            asks=[OrderBookLevel(price=0.20, size=500.0)],
        )
        client.set_orderbook("mkt-kord", 1, ob)

        allocations = {1: Decimal("100.000000")}  # 100 USDC nominal
        model_probs = {1: 0.70}
        bin_labels = {1: "[70, 72)"}

        # T_remain = 0.5h, current_temp = 65.0, bin_center = 71.0 -> delta_T = 6.0F (CRITICAL!)
        result = engine.execute_strategy(
            station_id="KORD",
            market_id="mkt-kord",
            allocations=allocations,
            model_probs=model_probs,
            bin_labels=bin_labels,
            t_remain_hours=0.5,
            current_temp_f=65.0,
            bin_centers={1: 71.0},
        )
        assert result.executed is True
        assert result.risk_regime == RiskRegime.CRITICAL
        # Effective allocation was 100 * 0.2 = 20 USDC
        # With price 0.20, shares = 20 / 0.20 = 100 shares, cost = 20 USDC
        assert result.committed_cost == Decimal("20.000000")
        assert len(result.orders) == 1
        assert result.orders[0].size == Decimal("100.000000")
