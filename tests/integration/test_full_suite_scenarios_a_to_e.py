"""
Unified End-to-End Acceptance Test Suite: Test-Scenario A ~ E (Phase 2 Task 07 - Ticket 04 / Issue #98).
Covers:
- Test-Scenario A: Cold front probability flip, sunk-cost exogenous isolation, incremental multinomial Kelly.
- Test-Scenario B: CLOB thin-depth defense, IOC protection price cut-off, positive EV fill guarantee (EV_bar > 0).
- Test-Scenario C: 12h un-cleared zombie position isolation, dual-track accounting (0.0x sizing vs 0.90x NAV), 6-decimal zero drift.
- Test-Scenario D: Monotonic observation merge, late-arriving drop, RMK temperature reconciliation, 20°F jump block.
- Test-Scenario E: Central exception arbiter heartbeat timeout (>30s), 0ms order cancellation, position insulation.
- Test-Scenario E2E-Full: Cross-scenario unified execution pipeline spanning observation, arbitration, pricing, execution, and settlement.
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest

from src.bankroll.bankroll_manager import BankrollManager, FourBucketBalance
from src.bankroll.multinomial_kelly import MultinomialKellyOptimizer
from src.bankroll.risk_limiter import RiskLimiter, RiskLimiterConfig
from src.bankroll.zombie_evaluator import ZombieEvaluator, PositionRecord, LiquidityTier
from src.data_acquisition.observation_stream import ObservationStreamAdapter
from src.data_processing.constants import ACTIVE_10_STATIONS
from src.execution.clob_client import MockCLOBClient
from src.execution.execution_engine import CLOBExecutionEngine
from src.execution.models import CLOBOrder, OrderSide, OrderStatus, OrderType
from src.execution.order_router import OrderRouter
from src.execution.residual_risk import ResidualRiskStateMachine, ResidualState
from src.pipeline.stream_confluence_pipeline import StreamConfluencePipeline
from src.prediction.monotonic_confluence import MonotonicConfluenceEngine
from src.prediction.temperature_sanitizer import SanitizerConfig, TemperatureSanitizer
from src.pricing.ev_engine import DynamicEVEngine, OrderBookLevel, OrderBookSnapshot
from src.risk.central_arbiter import ArbiterConfig, CentralExceptionArbiter, StationLifeCycleState
from src.risk.incident_protocol import IncidentBus, IncidentReasonCode, IncidentReport, IncidentSeverity, IncidentSubsystem
from src.risk.stream_watchdog import StreamRiskWatchdog
from src.risk.two_dimensional_risk import RiskRegime, TwoDimensionalRiskController
from src.simulation.clock import SimulationClock, SimulationClockMode
from src.simulation.metrics import SimulationMetricsCalculator
from src.simulation.paper_engine import PaperSimulationConfig, PaperTradingSimulator


class TestFullSuiteScenariosAToE:
    """Unified Acceptance Test Suite for Polymarket Prediction System Phase 2."""

    def test_scenario_a_incremental_kelly_cold_front_hedging(self):
        """
        Scenario A: 4-outcome temperature market probability flip & natural forward hedging.
        Asserts sunk-cost isolation, incremental Kelly allocation, and single market 10% cap.
        """
        manager = BankrollManager(initial_free_usdc=Decimal("50000.000000"))
        limiter = RiskLimiter(
            RiskLimiterConfig(
                fractional_multiplier=Decimal("0.5"),
                single_market_cap_ratio=Decimal("0.10"),
                global_utilization_cap_ratio=Decimal("0.70"),
            )
        )
        optimizer = MultinomialKellyOptimizer()

        market_id = "KORD-2026-10-15-TMAX"
        prices = [0.20, 0.25, 0.35, 0.20]

        # Prior positions: 2000 shares in Outcome 1, 4000 shares in Outcome 2. Total cost = 1900.
        initial_locked = Decimal("1900.000000")
        manager.lock_funds(initial_locked)
        existing_payouts = [0.0, 2000.0, 4000.0, 0.0]

        # Cold front flip: cold bins (0 & 1) now dominate
        probabilities = [0.55, 0.35, 0.08, 0.02]

        free_usdc_float = float(manager.get_balance().free_usdc)
        res = optimizer.optimize(
            probabilities=probabilities,
            prices=prices,
            existing_payouts=existing_payouts,
            w_free=free_usdc_float,
        )

        assert res.success is True
        # Natural forward hedging: must deploy capital into Cold bins (0 & 1), zero to warm bins (2 & 3)
        assert res.optimal_allocations[0] > 0.0
        assert res.optimal_allocations[2] == 0.0
        assert res.optimal_allocations[3] == 0.0

        raw_allocations = [Decimal(f"{x:.6f}") for x in res.optimal_allocations]
        limit_res = limiter.apply_limits(
            market_id=market_id,
            raw_allocations=raw_allocations,
            current_market_exposure=initial_locked,
            bankroll_manager=manager,
        )
        assert limit_res.is_approved is True
        # Total market exposure must not exceed 10% of total bankroll (50,000 * 0.10 = 5000 USDC)
        assert limit_res.market_exposure_after <= Decimal("5000.000000")

    def test_scenario_b_clob_thin_liquidity_ioc_protection(self):
        """
        Scenario B: CLOB thin liquidity defense & IOC protection price cut-off.
        Asserts no market orders, IOC limits at last positive EV level, and average EV > 0.
        """
        client = MockCLOBClient()
        bankroll = BankrollManager(initial_free_usdc=Decimal("10000.000000"))
        router = OrderRouter(clob_client=client, bankroll_manager=bankroll, min_edge=0.0)

        market_id = "KORD-2026-10-15-TMAX"
        # Model fair probability: 0.50. Bids/Asks thin depth:
        # Ask 0.40 (EV +25%), Ask 0.45 (EV +11.1%), Ask 0.55 (EV -9.1%), Ask 0.80 (EV -37.5%)
        client.set_orderbook(
            market_id=market_id,
            bin_index=2,
            snapshot=OrderBookSnapshot(
                station_id="KORD",
                bin_index=2,
                bin_label="71-75°F",
                asks=[
                    OrderBookLevel(price=0.40, size=50.0),
                    OrderBookLevel(price=0.45, size=50.0),
                    OrderBookLevel(price=0.55, size=50.0),
                    OrderBookLevel(price=0.80, size=100.0),
                ],
            ),
        )

        # Allocate 200 USDC
        report = router.route_allocations(
            station_id="KORD",
            market_id=market_id,
            allocations={2: Decimal("200.000000")},
            model_probs={2: 0.50},
            bin_labels={2: "71-75°F"},
        )

        order = report.orders[0]
        # Protection price MUST be capped at 0.4500 (last positive EV ask)
        assert order.price == Decimal("0.4500")
        assert order.order_type == OrderType.IOC
        # Only levels <= 0.45 filled: 50@0.40 + 50@0.45 = 100 shares for 42.5 USDC
        assert order.filled_size == Decimal("100.000000")
        assert order.avg_fill_price == Decimal("0.4250")
        # Average EV: (0.50 - 0.4250) / 0.4250 = +17.65% > 0
        avg_ev = (0.50 - float(order.avg_fill_price)) / float(order.avg_fill_price)
        assert avg_ev > 0.0

    def test_scenario_c_zombie_12h_timeout_dual_track_and_precision(self):
        """
        Scenario C: 12h un-cleared position zombie isolation, dual-track valuation, and decimal precision.
        """
        bankroll = BankrollManager(initial_free_usdc=Decimal("100000.000000"))
        evaluator = ZombieEvaluator(bankroll_manager=bankroll)

        pos_cost = Decimal("20000.000000")
        bankroll.lock_funds(pos_cost)

        pos_kord = PositionRecord(
            position_id="POS-KORD-01",
            station_id="KORD",
            market_date="2026-08-31",
            cost_basis=pos_cost,
            shares=Decimal("30000.000000"),
            expected_payout=Decimal("28000.000000"),
        )
        evaluator.register_position(pos_kord)

        # 13 hours post-midnight (18:00 UTC next day for KORD)
        zombie_t2 = evaluator.evaluate_positions(
            current_wall_time=datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
        )
        assert len(zombie_t2) == 1
        assert zombie_t2[0] == "POS-KORD-01"

        bal = bankroll.get_balance()
        assert bal.active_locked == Decimal("0.000000")
        assert bal.zombie_margin == Decimal("20000.000000")

        # Effective Bankroll (Sizing Book) excludes zombie margin completely (0.0x weight)
        assert bankroll.get_effective_bankroll() == Decimal("80000.000000")
        # Financial NAV evaluates zombie with 10% haircut on expected payout: 80,000 + 28,000 * 0.90 = 105,200 USDC
        nav = evaluator.calculate_financial_nav()
        assert nav == Decimal("105200.000000")

    def test_scenario_d_monotonic_weather_gatekeeping(self):
        """
        Scenario D: METAR late-arrival drop, RMK correction, and 20°F jump block.
        """
        pipeline = StreamConfluencePipeline(
            adapter=ObservationStreamAdapter(),
            sanitizer=TemperatureSanitizer(SanitizerConfig()),
            confluence=MonotonicConfluenceEngine(),
            watchdog=StreamRiskWatchdog(),
        )

        station = "KORD"
        base_time = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)

        # D1: Late METAR raw message (>15m latency) MUST be discarded
        raw_late = "METAR KORD 211400Z 04010KT 10SM CLR 20/10 A3000 RMK AO2 T02000100"
        late_wall = base_time + timedelta(minutes=25)
        res_late = pipeline.process_raw_metar(
            station_id=station,
            raw_metar=raw_late,
            timestamp_utc=base_time,
            arrival_wall_time=late_wall,
        )
        assert res_late.sanitizer_result.is_valid is False
        assert res_late.sanitizer_result.is_late is True
        assert res_late.confluence_updated is False

        # D2: RMK 0.1°C precision preferred
        raw_rmk = "METAR KORD 211400Z 04010KT 10SM CLR 22/10 A3000 RMK AO2 T02240100"
        on_time_wall = base_time + timedelta(minutes=2)
        res_rmk = pipeline.process_raw_metar(
            station_id=station,
            raw_metar=raw_rmk,
            timestamp_utc=base_time,
            arrival_wall_time=on_time_wall,
        )
        assert res_rmk.sanitizer_result.is_valid is True
        assert res_rmk.confluence_updated is True
        assert res_rmk.packet.temp_c == 22.4
        expected_f = 22.4 * 9.0 / 5.0 + 32.0
        assert res_rmk.confluence_state.tmax_so_far == pytest.approx(expected_f, abs=1e-4)

        # D3: Abnormal 20°F jump: MUST BE BLOCKED
        obs_time_next = base_time + timedelta(minutes=15)
        raw_jump = "METAR KORD 211415Z 04010KT 10SM CLR 36/10 A3000 RMK AO2 T03600100"
        res_jump = pipeline.process_raw_metar(
            station_id=station,
            raw_metar=raw_jump,
            timestamp_utc=obs_time_next,
            arrival_wall_time=obs_time_next + timedelta(minutes=1),
        )
        assert res_jump.sanitizer_result.is_valid is False
        assert res_jump.sanitizer_result.station_blocked is True
        assert res_jump.confluence_updated is False

    def test_scenario_e_central_arbiter_fail_closed_and_order_cancel(self):
        """
        Scenario E: Central exception arbiter heartbeat timeout (>30s), 0ms order cancellation,
        and position insulation.
        """
        bus = IncidentBus()
        arbiter = CentralExceptionArbiter(bus=bus)
        clob = MockCLOBClient()
        bankroll = BankrollManager(initial_free_usdc=Decimal("10000.000000"))
        engine = CLOBExecutionEngine(clob_client=clob, bankroll_manager=bankroll, arbiter=arbiter)

        station_id = "KORD"
        # Seed an open order into mock CLOB
        clob.place_order(
            CLOBOrder(
                order_id="ORD-OPEN-1",
                client_order_id="CLIENT-ORD-OPEN-1",
                station_id=station_id,
                market_id="KORD-TMAX",
                bin_index=1,
                bin_label="66-70°F",
                side=OrderSide.BUY,
                order_type=OrderType.GTC,
                price=Decimal("0.4000"),
                size=Decimal("100.000000"),
            )
        )
        # Note: GTC order remains open in clob
        open_orders_before = [
            o for o in clob._orders.values() if o.station_id == station_id and o.status == OrderStatus.PENDING
        ]
        assert len(open_orders_before) == 1

        # Simulate heartbeat timeout (>30s staleness)
        incident = IncidentReport(
            incident_id="INC-STALENESS-001",
            timestamp_utc=datetime.now(timezone.utc),
            station_id=station_id,
            subsystem=IncidentSubsystem.INGESTION,
            severity=IncidentSeverity.DEGRADED,
            reason_code=IncidentReasonCode.DATA_STALENESS,
        )
        bus.publish(incident)

        # Arbiter state must be SUSPENDED
        assert arbiter.get_station_state(station_id) == StationLifeCycleState.SUSPENDED
        assert arbiter.is_station_tradable(station_id) is False

        # Fail-closed action: 0ms emergency cancel all open orders
        cancelled_ids = engine.emergency_cancel_all(station_id=station_id)
        assert "ORD-OPEN-1" in cancelled_ids

        # Attempting new trade while SUSPENDED must be blocked immediately
        res = engine.execute_strategy(
            station_id=station_id,
            market_id="KORD-TMAX",
            allocations={1: Decimal("100.000000")},
            model_probs={1: 0.5},
            bin_labels={1: "Bin 1"},
            t_remain_hours=2.0,
            current_temp_f=70.0,
        )
        assert res.executed is False
        assert "SUSPENDED" in (res.blocked_reason or "")

    def test_scenario_e2e_full_lifecycle_cross_scenario(self):
        """
        Comprehensive Cross-Scenario End-to-End Pipeline:
        Observes weather -> Evaluates Arbiter -> Computes Kelly & Two-Dimensional Risk ->
        Executes IOC Limit Orders on CLOB -> Settles Market -> Verifies Metrics & Capital Conservation.
        """
        start_time = datetime(2026, 10, 15, 8, 0, 0, tzinfo=timezone.utc)
        clock = SimulationClock(mode=SimulationClockMode.REPLAY, initial_time=start_time)
        bankroll = BankrollManager(initial_free_usdc=Decimal("20000.000000"))
        clob = MockCLOBClient()
        arbiter = CentralExceptionArbiter()
        risk_controller = TwoDimensionalRiskController()
        metrics = SimulationMetricsCalculator(initial_capital=Decimal("20000.000000"))

        simulator = PaperTradingSimulator(
            clock=clock,
            bankroll_manager=bankroll,
            clob_client=clob,
            arbiter=arbiter,
            risk_controller=risk_controller,
            config=PaperSimulationConfig(fractional_multiplier=Decimal("0.5"), min_edge=0.02),
        )

        station_id = "KDAL"
        market_id = "KDAL-2026-10-15-TMAX"
        bin_labels = {0: "<=70°F", 1: "71-75°F", 2: "76-80°F", 3: ">=81°F"}
        bin_centers = {0: 68.0, 1: 73.0, 2: 78.0, 3: 83.0}

        # Step 1: Initialize CLOB Orderbooks with healthy depth
        for b_idx, (ask_p, ask_sz) in enumerate([(0.15, 500), (0.25, 1000), (0.40, 1000), (0.20, 500)]):
            clob.set_orderbook(
                market_id=market_id,
                bin_index=b_idx,
                snapshot=OrderBookSnapshot(
                    station_id=station_id,
                    bin_index=b_idx,
                    bin_label=bin_labels[b_idx],
                    asks=[OrderBookLevel(price=ask_p, size=ask_sz)],
                ),
            )

        metrics.record_snapshot(clock.now(), bankroll.get_balance())

        # Step 2: Weather observation at 10:00 UTC (Current temp 75°F)
        clock.advance(timedelta(hours=2))
        simulator.on_weather_observation(station_id, current_temp_f=75.0, obs_time=clock.now())

        # Step 3: Morning forecast favors Bin 2 (76-80°F, prob 0.65) and Bin 1 (prob 0.25)
        model_probs = {0: 0.02, 1: 0.25, 2: 0.65, 3: 0.08}
        exec_1 = simulator.evaluate_and_execute(
            station_id=station_id,
            market_id=market_id,
            model_probs=model_probs,
            bin_labels=bin_labels,
            bin_centers=bin_centers,
            t_remain_hours=6.0,
            current_temp_f=75.0,
        )
        assert exec_1.executed is True
        assert exec_1.committed_cost > Decimal("0.000000")
        assert simulator.non_physical_orders_count == 0

        metrics.record_snapshot(clock.now(), bankroll.get_balance())

        # Step 4: Advance to afternoon 14:00 UTC (T_remain = 2.0h, temp 77.5°F, near Bin 2)
        clock.advance(timedelta(hours=4))
        simulator.on_weather_observation(station_id, current_temp_f=77.5, obs_time=clock.now())
        metrics.record_snapshot(clock.now(), bankroll.get_balance())

        # Step 5: Evening resolution at 20:00 UTC. Actual high was 78.2°F -> Bin 2 wins!
        clock.advance(timedelta(hours=6))
        settle_rec = simulator.settle_market(market_id=market_id, winning_bin_index=2)
        assert settle_rec.total_payout > settle_rec.total_cost
        assert settle_rec.net_pnl > Decimal("0.000000")

        metrics.record_snapshot(clock.now(), bankroll.get_balance())

        # Final assertions on metrics report
        report = metrics.generate_report(
            non_physical_violations=simulator.non_physical_orders_count,
            total_trades=len(simulator.trade_history),
        )
        assert report.capital_conservation_passed is True
        assert report.zero_non_physical_orders_violated == 0
        assert report.total_return_pct > 0.0
        assert report.max_drawdown_pct < 15.0
        assert report.sharpe_ratio > 2.0
        assert bankroll.get_balance().active_locked == Decimal("0.000000")
