"""
Unit tests for Simulation Models and Simulation Clock (Phase 2 Task 07 - Ticket 01 / Issue #95).
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest

from src.simulation.clock import SimulationClock, SimulationClockMode
from src.simulation.models import (
    PaperPosition,
    SimulatedOrderBook,
    SimulationEvent,
    SimulationEventType,
    PaperTradeRecord,
)
from src.pricing.ev_engine import OrderBookLevel


class TestSimulationClock:
    def test_clock_replay_mode_advancement(self):
        start_time = datetime(2026, 10, 15, 0, 0, 0, tzinfo=timezone.utc)
        clock = SimulationClock(mode=SimulationClockMode.REPLAY, initial_time=start_time)

        assert clock.now() == start_time
        assert clock.mode == SimulationClockMode.REPLAY

        # Advance by 15 minutes
        clock.advance(timedelta(minutes=15))
        assert clock.now() == start_time + timedelta(minutes=15)

        # Set specific time
        new_time = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)
        clock.set_time(new_time)
        assert clock.now() == new_time

    def test_clock_replay_mode_cannot_go_backward(self):
        start_time = datetime(2026, 10, 15, 0, 0, 0, tzinfo=timezone.utc)
        clock = SimulationClock(mode=SimulationClockMode.REPLAY, initial_time=start_time)

        with pytest.raises(ValueError, match="cannot advance backward"):
            clock.advance(timedelta(minutes=-10))

    def test_clock_realtime_mode(self):
        clock = SimulationClock(mode=SimulationClockMode.REALTIME)
        t1 = clock.now()
        assert t1.tzinfo is not None
        assert clock.mode == SimulationClockMode.REALTIME

        # In realtime mode, advance should raise error or be ignored
        with pytest.raises(RuntimeError, match="Cannot manually advance time in REALTIME mode"):
            clock.advance(timedelta(hours=1))


class TestSimulationModels:
    def test_paper_position_lifecycle(self):
        pos = PaperPosition(
            station_id="KORD",
            market_id="KORD-2026-10-15-TMAX",
            bin_index=2,
            bin_label="71-75°F",
        )
        assert pos.shares == Decimal("0")
        assert pos.total_cost == Decimal("0")
        assert pos.average_price == Decimal("0")

        # Accumulate fills
        pos.add_fill(shares=Decimal("100.000000"), cost=Decimal("40.000000"))
        assert pos.shares == Decimal("100.000000")
        assert pos.total_cost == Decimal("40.000000")
        assert pos.average_price == Decimal("0.400000")

        # Second fill
        pos.add_fill(shares=Decimal("100.000000"), cost=Decimal("60.000000"))
        assert pos.shares == Decimal("200.000000")
        assert pos.total_cost == Decimal("100.000000")
        assert pos.average_price == Decimal("0.500000")

    def test_simulated_order_book_fill_matching(self):
        book = SimulatedOrderBook(
            market_id="KORD-2026-10-15-TMAX",
            bin_index=1,
            bids=[OrderBookLevel(price=0.4500, size=50.0)],
            asks=[
                OrderBookLevel(price=0.4800, size=50.0),
                OrderBookLevel(price=0.5000, size=100.0),
            ],
        )

        assert book.best_ask == Decimal("0.4800")
        assert book.best_bid == Decimal("0.4500")

        # Match buy order with limit 0.4900 (should only take first level)
        filled_shares, total_cost = book.simulate_buy_ioc(
            max_price=Decimal("0.4900"),
            target_amount_usdc=Decimal("48.000000"),
        )
        # 48 USDC at 0.48 can buy 100 shares, but first level only has 50 shares
        # So 50 shares * 0.48 = 24.000000 USDC
        assert filled_shares == Decimal("50.000000")
        assert total_cost == Decimal("24.000000")
        # Depth at 0.48 should now be 0, best ask becomes 0.5000
        assert book.best_ask == Decimal("0.5000")

    def test_simulation_event_logging(self):
        now = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
        record = PaperTradeRecord(
            timestamp=now,
            station_id="KORD",
            market_id="KORD-2026-10-15-TMAX",
            bin_index=2,
            action="BUY",
            shares=Decimal("100.000000"),
            price=Decimal("0.4500"),
            total_cost=Decimal("45.000000"),
        )
        data = record.to_dict()
        assert data["station_id"] == "KORD"
        assert data["price"] == 0.45
        assert data["shares"] == 100.0
