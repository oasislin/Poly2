"""
Integration Test Suite: Test-Scenario B (CLOB Depth Penetration Defense & IOC Limit Order Routing).
Complies with Phase 2 Execution Document v2.0 §4 (Test-Scenario B) & §5, and ADR-0011 ~ ADR-0014.
Verifies thin orderbook penetration defense, positive EV trade assertion, residual risk state machine healing,
two-dimensional ladder risk haircuts, and Decimal bankroll ledger conservation.
"""

from decimal import Decimal
import pytest

from src.bankroll.bankroll_manager import BankrollManager
from src.execution.clob_client import MockCLOBClient
from src.execution.execution_engine import CLOBExecutionEngine
from src.execution.models import OrderStatus, OrderType
from src.execution.order_router import calculate_protection_price
from src.execution.residual_risk import ResidualRiskConfig, ResidualState
from src.pricing.ev_engine import OrderBookLevel, OrderBookSnapshot
from src.risk.central_arbiter import CentralExceptionArbiter, StationLifeCycleState
from src.risk.pre_buy_gate import LocalHardValve
from src.risk.two_dimensional_risk import RiskRegime, TwoDimensionalRiskController


class TestScenarioBDepthPenetrationAndExecution:
    """
    Test-Scenario B formal test gate:
    Guarantees zero liquidity blow-through, strict positive EV on filled volume,
    non-atomic partial fill healing, and arbiter circuit breaker protection.
    """

    @pytest.fixture
    def environment(self):
        client = MockCLOBClient()
        bankroll = BankrollManager(initial_free_usdc=Decimal("1000.000000"))
        arbiter = CentralExceptionArbiter()
        valve = LocalHardValve(arbiter=arbiter)
        risk_ctrl = TwoDimensionalRiskController()
        residual_cfg = ResidualRiskConfig(rehedge_timeout_seconds=0.1)

        engine = CLOBExecutionEngine(
            clob_client=client,
            bankroll_manager=bankroll,
            arbiter=arbiter,
            hard_valve=valve,
            risk_controller=risk_ctrl,
            residual_config=residual_cfg,
            min_edge=0.0,
        )
        return {
            "client": client,
            "bankroll": bankroll,
            "arbiter": arbiter,
            "valve": valve,
            "risk_ctrl": risk_ctrl,
            "engine": engine,
        }

    def test_scenario_b1_ioc_depth_penetration_defense_and_positive_ev(self, environment):
        """
        B1 & B2 & B3 & B4: Thin Orderbook Liquidity Trap.
        Construct an orderbook where:
          - Model probability = 0.40
          - Ask Tier 0: 0.20, size = 20.0  (EV = +1.00 > 0)
          - Ask Tier 1: 0.35, size = 30.0  (EV = +0.1429 > 0)
          - Ask Tier 2: 0.75, size = 500.0 (EV = -0.4667 < 0 -> TRAP TIER!)
        Target: Buy 100 shares ($40 USDC allocation).
        Assert:
          1. Protection price is strictly clamped to Tier 1 price (0.3500);
          2. Order size is limited to safe capacity (50.0 shares);
          3. Only 50 shares are filled, and trap tier (0.75) is NEVER penetrated;
          4. Average filled price = 0.2900, Net EV = (0.40 - 0.29)/0.29 = +37.93% > 0;
          5. Bankroll correctly locks $14.50 and returns $985.50 to Free USDC with 0 precision error.
        """
        client: MockCLOBClient = environment["client"]
        engine: CLOBExecutionEngine = environment["engine"]
        bankroll: BankrollManager = environment["bankroll"]

        # Setup thin orderbook with liquidity trap on KORD bin 2
        thin_ob = OrderBookSnapshot(
            station_id="KORD",
            bin_index=2,
            bin_label="[70, 72)",
            bids=[],
            asks=[
                OrderBookLevel(price=0.20, size=20.0),
                OrderBookLevel(price=0.35, size=30.0),
                OrderBookLevel(price=0.75, size=500.0),  # Liquidity trap!
            ],
        )
        client.set_orderbook("mkt-kord-tmax", 2, thin_ob)

        # Execute strategy targeting 100 shares ($35.00 nominal allocation)
        allocations = {2: Decimal("35.000000")}
        model_probs = {2: 0.40}
        bin_labels = {2: "[70, 72)"}

        result = engine.execute_strategy(
            station_id="KORD",
            market_id="mkt-kord-tmax",
            allocations=allocations,
            model_probs=model_probs,
            bin_labels=bin_labels,
            t_remain_hours=5.0,  # Normal regime
            current_temp_f=70.5,
            bin_centers={2: 71.0},
        )

        assert result.executed is True
        assert len(result.orders) == 1
        order = result.orders[0]

        # 1. Zero Market Order & IOC check
        assert order.order_type == OrderType.IOC
        assert order.price == Decimal("0.3500")  # Locked at 0.3500, never allowed 0.75

        # 2. Assert depth penetration was blocked
        assert order.filled_size == Decimal("50.000000")  # Only took the safe 50 shares
        assert order.avg_fill_price == Decimal("0.2900")  # (20*0.20 + 30*0.35) / 50 = 14.5 / 50 = 0.2900

        # 3. Positive EV Assertion (Execution v2.0 §4 Test-Scenario B)
        avg_price_float = float(order.avg_fill_price)
        net_ev = (0.40 - avg_price_float) / avg_price_float
        assert net_ev > 0.0, f"Expected positive EV, got {net_ev:.4f}"
        assert abs(net_ev - 0.3793) < 0.001

        # 4. Bankroll Conservation Assertion
        balance = bankroll.get_balance()
        assert balance.total_bankroll == Decimal("1000.000000")
        assert balance.active_locked == Decimal("14.500000")
        assert balance.free_usdc == Decimal("985.500000")

        # 5. Trap depth in orderbook remained untouched
        ob_after = client.get_orderbook("mkt-kord-tmax", 2)
        assert len(ob_after.asks) == 1
        assert ob_after.asks[0].price == 0.75
        assert ob_after.asks[0].size == 500.0

    def test_scenario_b2_non_atomic_partial_fill_residual_healing(self, environment):
        """
        B5: Non-Atomic Partial Fill & Rehedge Self-Healing.
        Target: Buy bin 1 and bin 2.
        Order on bin 1 fills completely, bin 2 partially fills or misses.
        ResidualRiskStateMachine detects single-leg exposure and executes rehedge order.
        """
        client: MockCLOBClient = environment["client"]
        engine: CLOBExecutionEngine = environment["engine"]

        # Bin 1 has immediate depth
        ob_bin1 = OrderBookSnapshot(
            station_id="KORD",
            bin_index=1,
            bin_label="[68, 70)",
            asks=[OrderBookLevel(price=0.25, size=40.0)],
        )
        client.set_orderbook("mkt-kord-tmax", 1, ob_bin1)

        # Bin 2 has depth available for rehedge
        ob_bin2 = OrderBookSnapshot(
            station_id="KORD",
            bin_index=2,
            bin_label="[70, 72)",
            asks=[OrderBookLevel(price=0.30, size=50.0)],
        )
        client.set_orderbook("mkt-kord-tmax", 2, ob_bin2)

        # Allocate to bin 1 and bin 2
        allocations = {
            1: Decimal("10.000000"),  # 40 shares @ 0.25
            2: Decimal("0.000000"),   # Intentionally empty initial allocation to simulate single leg
        }
        model_probs = {1: 0.30, 2: 0.60}  # Bin 2 has major probability mass
        bin_labels = {1: "[68, 70)", 2: "[70, 72)"}

        result = engine.execute_strategy(
            station_id="KORD",
            market_id="mkt-kord-tmax",
            allocations=allocations,
            model_probs=model_probs,
            bin_labels=bin_labels,
            t_remain_hours=3.0,
            current_temp_f=70.0,
            bin_centers={1: 69.0, 2: 71.0},
        )

        assert result.executed is True
        # State machine should have recognized single leg exposure on bin 1 and rehedged bin 2
        assert result.residual_state == ResidualState.RESOLVED_BALANCED
        assert engine.residual_sm.current_fills[2] > Decimal("0.000000")

    def test_scenario_b3_two_dimensional_risk_ladder_interception(self, environment):
        """
        B6: Two-Dimensional Risk Ladder Interception.
        Case 1: T_remain = 0.5h, delta_T = 5.0°F -> CRITICAL regime -> 0.2x sizing haircut.
        Case 2: T_remain = 0.3h, delta_T = 0.2°F -> CERTAIN regime -> Forbids distant speculative bins.
        """
        client: MockCLOBClient = environment["client"]
        engine: CLOBExecutionEngine = environment["engine"]

        # Seed depths
        client.set_orderbook(
            "mkt-kord-tmax", 1,
            OrderBookSnapshot(station_id="KORD", bin_index=1, bin_label="[68, 70)", asks=[OrderBookLevel(price=0.20, size=100.0)])
        )
        client.set_orderbook(
            "mkt-kord-tmax", 4,
            OrderBookSnapshot(station_id="KORD", bin_index=4, bin_label="[74, 76)", asks=[OrderBookLevel(price=0.10, size=100.0)])
        )

        # Case 1: Critical regime
        res_crit = engine.execute_strategy(
            station_id="KORD",
            market_id="mkt-kord-tmax",
            allocations={1: Decimal("50.000000")},
            model_probs={1: 0.60},
            bin_labels={1: "[68, 70)"},
            t_remain_hours=0.6,
            current_temp_f=64.0,  # delta_T = 69.0 - 64.0 = 5.0°F
            bin_centers={1: 69.0},
        )
        assert res_crit.risk_regime == RiskRegime.CRITICAL
        # 50 USDC scaled to 10 USDC -> 50 shares @ 0.20 = 10 USDC committed
        assert res_crit.committed_cost == Decimal("10.000000")

        # Case 2: Certain regime (Current temp 69.1, Bin 1 center 69.0 -> delta_T = 0.1°F, T_remain = 0.3h)
        # Allocate to winning bin 1 and distant bin 4
        res_certain = engine.execute_strategy(
            station_id="KORD",
            market_id="mkt-kord-tmax",
            allocations={1: Decimal("20.000000"), 4: Decimal("20.000000")},
            model_probs={1: 0.90, 4: 0.05},
            bin_labels={1: "[68, 70)", 4: "[74, 76)"},
            t_remain_hours=0.3,
            current_temp_f=69.1,
            bin_centers={1: 69.0, 4: 75.0},
        )
        assert res_certain.risk_regime == RiskRegime.CERTAIN
        # Bin 4 is distant (|75.0 - 69.1| = 5.9 > 1.5) -> skipped in Certain regime!
        assert len(res_certain.orders) == 1
        assert res_certain.orders[0].bin_index == 1

    def test_scenario_b4_central_arbiter_circuit_breaker_and_zero_emission(self, environment):
        """
        B7: CentralExceptionArbiter Suspension 0ms Interception.
        When station is marked SUSPENDED, engine immediately blocks trade emission,
        and emergency_cancel_all successfully purges open quotes.
        """
        engine: CLOBExecutionEngine = environment["engine"]
        arbiter: CentralExceptionArbiter = environment["arbiter"]

        # Mark KORD as SUSPENDED
        arbiter._states["KORD"].state = StationLifeCycleState.SUSPENDED
        arbiter._states["KORD"].last_reason = "METAR Stream Outage > 15m"

        res = engine.execute_strategy(
            station_id="KORD",
            market_id="mkt-kord-tmax",
            allocations={1: Decimal("30.000000")},
            model_probs={1: 0.50},
            bin_labels={1: "[68, 70)"},
            t_remain_hours=2.0,
            current_temp_f=69.0,
            bin_centers={1: 69.0},
        )
        assert res.executed is False
        assert "SUSPENDED" in res.blocked_reason
        assert res.committed_cost == Decimal("0.000000")

        # Assert emergency cancel all executes cleanly
        cancelled = engine.emergency_cancel_all(station_id="KORD")
        assert isinstance(cancelled, list)
