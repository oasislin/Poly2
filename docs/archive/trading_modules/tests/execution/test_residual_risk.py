"""
Unit tests for Non-Atomic Residual Risk Evaluation and Healing State Machine (Phase 2 Task 06 - Ticket 03 / Issue #91).
"""

from decimal import Decimal
import time
import pytest

from src.bankroll.bankroll_manager import BankrollManager
from src.execution.clob_client import MockCLOBClient
from src.execution.models import (
    CLOBOrder,
    OrderPlacementResult,
    OrderSide,
    OrderStatus,
    OrderType,
)
from src.execution.residual_risk import (
    ResidualRiskConfig,
    ResidualRiskEvaluator,
    ResidualRiskStateMachine,
    ResidualState,
)
from src.pricing.ev_engine import OrderBookLevel, OrderBookSnapshot


class TestResidualRiskEvaluator:
    """Tests for residual exposure and EV recalculation."""

    def test_evaluate_balanced_fill(self):
        """When fills match probabilities with positive EV, no residual risk is flagged."""
        evaluator = ResidualRiskEvaluator()
        # Holding 50 shares in bin 1 (p=0.40) and 50 shares in bin 2 (p=0.50), cost = $25
        fills = {1: Decimal("50.000000"), 2: Decimal("50.000000")}
        model_probs = {1: 0.40, 2: 0.50}
        total_cost = Decimal("25.000000")

        risk = evaluator.evaluate(
            station_id="KORD",
            market_id="mkt-kord",
            fills=fills,
            model_probs=model_probs,
            total_cost=total_cost,
        )
        assert risk.is_exposed is False
        assert risk.expected_pnl == Decimal("20.000000")  # (50*0.4 + 50*0.5) - 25 = 45 - 25 = +20

    def test_evaluate_single_leg_exposed_fill(self):
        """When only one leg fills and other high-prob leg is 0, exposure is flagged."""
        evaluator = ResidualRiskEvaluator()
        # Only bin 1 filled (10 shares, cost = $8), bin 2 (prob 0.60) filled 0
        fills = {1: Decimal("10.000000"), 2: Decimal("0.000000")}
        model_probs = {1: 0.20, 2: 0.60}
        total_cost = Decimal("8.000000")

        risk = evaluator.evaluate(
            station_id="KORD",
            market_id="mkt-kord",
            fills=fills,
            model_probs=model_probs,
            total_cost=total_cost,
        )
        # Expected value: 10 * 0.20 = 2.0 - 8.0 = -6.0 expected PnL!
        assert risk.is_exposed is True
        assert risk.expected_pnl == Decimal("-6.000000")
        assert risk.max_loss == Decimal("8.000000")


class TestResidualRiskStateMachine:
    """Tests for three-stage healing state machine (Execution v2.0 §5.2)."""

    @pytest.fixture
    def setup_sm(self):
        client = MockCLOBClient()
        bm = BankrollManager(initial_free_usdc=Decimal("1000.000000"))
        config = ResidualRiskConfig(rehedge_timeout_seconds=0.1)  # fast for testing
        sm = ResidualRiskStateMachine(clob_client=client, bankroll_manager=bm, config=config)
        return sm, client, bm

    def test_state_machine_clean_when_no_exposure(self, setup_sm):
        sm, client, bm = setup_sm
        fills = {1: Decimal("50.000000"), 2: Decimal("50.000000")}
        model_probs = {1: 0.50, 2: 0.50}
        state = sm.handle_execution_result(
            station_id="KORD",
            market_id="mkt-kord",
            fills=fills,
            model_probs=model_probs,
            total_cost=Decimal("20.000000"),
        )
        assert state == ResidualState.CLEAN

    def test_state_machine_rehedges_successfully_when_depth_exists(self, setup_sm):
        sm, client, bm = setup_sm
        # Set orderbook for bin 2 where rehedge can happen (ask @ 0.30, size 50)
        ob = OrderBookSnapshot(
            station_id="KORD",
            bin_index=2,
            bin_label="[70, 72)",
            asks=[OrderBookLevel(price=0.30, size=50.0)],
        )
        client.set_orderbook("mkt-kord", 2, ob)

        # Single leg fill on bin 1, bin 2 completely missed
        fills = {1: Decimal("20.000000"), 2: Decimal("0.000000")}
        model_probs = {1: 0.30, 2: 0.60}  # Bin 2 is high probability!
        total_cost = Decimal("6.000000")

        state = sm.handle_execution_result(
            station_id="KORD",
            market_id="mkt-kord",
            fills=fills,
            model_probs=model_probs,
            total_cost=total_cost,
        )
        assert state == ResidualState.RESOLVED_BALANCED
        # Check that bin 2 was rehedged
        assert sm.current_fills[2] > Decimal("0.000000")

    def test_state_machine_triggers_hard_stop_loss_on_timeout(self, setup_sm):
        sm, client, bm = setup_sm
        # No asks available for bin 2, and bids exist to liquidate bin 1
        ob_bin1 = OrderBookSnapshot(
            station_id="KORD",
            bin_index=1,
            bin_label="[68, 70)",
            bids=[OrderBookLevel(price=0.25, size=50.0)],
            asks=[],
        )
        client.set_orderbook("mkt-kord", 1, ob_bin1)

        fills = {1: Decimal("20.000000"), 2: Decimal("0.000000")}
        model_probs = {1: 0.10, 2: 0.80}  # Severe single-leg downside
        total_cost = Decimal("10.000000")

        state = sm.handle_execution_result(
            station_id="KORD",
            market_id="mkt-kord",
            fills=fills,
            model_probs=model_probs,
            total_cost=total_cost,
        )
        # Should attempt rehedge, fail due to no asks in bin 2, and trigger stop loss
        assert state == ResidualState.LIQUIDATED
        assert sm.current_fills[1] == Decimal("0.000000")  # Liquidated
