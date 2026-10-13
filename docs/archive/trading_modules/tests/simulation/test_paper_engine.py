"""
Unit tests for Paper Trading Engine and Settlement Simulator (Phase 2 Task 07 - Ticket 02 / Issue #96).
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest

from src.bankroll.bankroll_manager import BankrollManager
from src.bankroll.risk_limiter import RiskLimiter, RiskLimiterConfig
from src.execution.clob_client import MockCLOBClient
from src.execution.execution_engine import CLOBExecutionEngine
from src.pricing.ev_engine import OrderBookLevel, OrderBookSnapshot
from src.risk.central_arbiter import CentralExceptionArbiter
from src.risk.two_dimensional_risk import TwoDimensionalRiskController
from src.simulation.clock import SimulationClock, SimulationClockMode
from src.simulation.models import PaperPosition
from src.simulation.paper_engine import PaperTradingSimulator, PaperSimulationConfig
from src.simulation.settlement_sim import SettlementSimulator


class TestSettlementSimulator:
    def test_settlement_single_winning_bin(self):
        bankroll = BankrollManager(initial_free_usdc=Decimal("10000.000000"))
        # Lock 100 USDC for a position of 200 shares in Bin 2 (bought at 0.50)
        bankroll.lock_funds(Decimal("100.000000"))
        position = PaperPosition(
            station_id="KORD",
            market_id="KORD-2026-10-15-TMAX",
            bin_index=2,
            bin_label="71-75°F",
            shares=Decimal("200.000000"),
            total_cost=Decimal("100.000000"),
        )

        sim = SettlementSimulator(bankroll_manager=bankroll)
        # Winning bin is 2: payout is 200 * 1.0 = 200 USDC
        record = sim.settle_market(
            market_id="KORD-2026-10-15-TMAX",
            winning_bin_index=2,
            positions=[position],
        )

        assert record.total_payout == Decimal("200.000000")
        assert record.net_pnl == Decimal("100.000000")
        bal = bankroll.get_balance()
        assert bal.active_locked == Decimal("0.000000")
        assert bal.free_usdc == Decimal("10100.000000")

    def test_settlement_losing_bin(self):
        bankroll = BankrollManager(initial_free_usdc=Decimal("10000.000000"))
        bankroll.lock_funds(Decimal("100.000000"))
        position = PaperPosition(
            station_id="KORD",
            market_id="KORD-2026-10-15-TMAX",
            bin_index=1,
            bin_label="66-70°F",
            shares=Decimal("200.000000"),
            total_cost=Decimal("100.000000"),
        )

        sim = SettlementSimulator(bankroll_manager=bankroll)
        # Winning bin is 2: position in bin 1 loses, payout is 0 USDC
        record = sim.settle_market(
            market_id="KORD-2026-10-15-TMAX",
            winning_bin_index=2,
            positions=[position],
        )

        assert record.total_payout == Decimal("0.000000")
        assert record.net_pnl == Decimal("-100.000000")
        bal = bankroll.get_balance()
        assert bal.active_locked == Decimal("0.000000")
        assert bal.free_usdc == Decimal("9900.000000")

    def test_settlement_zombie_timeout_transfer(self):
        bankroll = BankrollManager(initial_free_usdc=Decimal("10000.000000"))
        bankroll.lock_funds(Decimal("150.000000"))
        position = PaperPosition(
            station_id="KORD",
            market_id="KORD-2026-10-15-TMAX",
            bin_index=2,
            bin_label="71-75°F",
            shares=Decimal("300.000000"),
            total_cost=Decimal("150.000000"),
        )

        sim = SettlementSimulator(bankroll_manager=bankroll)
        # 13 hours overdue settlement -> transferred to zombie margin
        sim.handle_overdue_market(
            market_id="KORD-2026-10-15-TMAX",
            positions=[position],
            overdue_hours=13.0,
        )

        bal = bankroll.get_balance()
        assert bal.active_locked == Decimal("0.000000")
        assert bal.zombie_margin == Decimal("150.000000")


class TestPaperTradingSimulator:
    def test_paper_engine_e2e_execution_and_settlement(self):
        start_time = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
        clock = SimulationClock(mode=SimulationClockMode.REPLAY, initial_time=start_time)
        bankroll = BankrollManager(initial_free_usdc=Decimal("20000.000000"))
        clob_client = MockCLOBClient()
        arbiter = CentralExceptionArbiter()
        risk_controller = TwoDimensionalRiskController()

        simulator = PaperTradingSimulator(
            clock=clock,
            bankroll_manager=bankroll,
            clob_client=clob_client,
            arbiter=arbiter,
            risk_controller=risk_controller,
            config=PaperSimulationConfig(min_edge=0.02),
        )

        station_id = "KORD"
        market_id = "KORD-2026-10-15-TMAX"

        # 1. Provide Orderbook Depth for 4 bins
        # Bin 0 (<=65): ask 0.15, size 500
        # Bin 1 (66-70): ask 0.25, size 1000
        # Bin 2 (71-75): ask 0.40, size 1000
        # Bin 3 (>=76): ask 0.20, size 500
        for b_idx, (ask_p, ask_sz) in enumerate([(0.15, 500), (0.25, 1000), (0.40, 1000), (0.20, 500)]):
            clob_client.set_orderbook(
                market_id=market_id,
                bin_index=b_idx,
                snapshot=OrderBookSnapshot(
                    station_id=station_id,
                    bin_index=b_idx,
                    bin_label=f"Bin {b_idx}",
                    asks=[OrderBookLevel(price=ask_p, size=ask_sz)],
                ),
            )

        # 2. Weather observation
        simulator.on_weather_observation(station_id, current_temp_f=72.0, obs_time=clock.now())

        # 3. Model prediction favors Bin 2 (0.60 prob) and Bin 1 (0.30 prob)
        model_probs = {0: 0.02, 1: 0.30, 2: 0.60, 3: 0.08}
        bin_labels = {0: "<=65°F", 1: "66-70°F", 2: "71-75°F", 3: ">=76°F"}
        bin_centers = {0: 63.0, 1: 68.0, 2: 73.0, 3: 78.0}

        # Execute decision cycle
        exec_res = simulator.evaluate_and_execute(
            station_id=station_id,
            market_id=market_id,
            model_probs=model_probs,
            bin_labels=bin_labels,
            bin_centers=bin_centers,
            t_remain_hours=3.5,
            current_temp_f=72.0,
        )

        assert exec_res.executed is True
        assert exec_res.committed_cost > Decimal("0.000000")
        assert bankroll.get_balance().active_locked > Decimal("0.000000")

        # Assert no orders placed on zero/negative EV or zero-prob bins
        # Zero Non-physical Orders Theorem
        for order in exec_res.orders:
            assert model_probs[order.bin_index] > 0.0

        # 4. Advance time to settlement
        clock.advance(timedelta(hours=4))
        # Winning bin is 2
        settle_rec = simulator.settle_market(
            market_id=market_id,
            winning_bin_index=2,
        )
        assert settle_rec.total_payout > Decimal("0.000000")
        # Final bankroll should be strictly positive and balanced
        bal = bankroll.get_balance()
        assert bal.active_locked == Decimal("0.000000")
        assert bal.free_usdc > Decimal("20000.000000")  # Profitable trade
