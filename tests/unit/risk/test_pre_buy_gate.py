"""
Unit tests for PreBuyGateKeeper, LocalHardValve, and Position Insulation (Phase 2 Task 03 - Ticket 03 / Issue #73).
Implements ADR-0014 §2 Principles 1, 2, and 4.
"""

from datetime import datetime, timezone, timedelta
import pytest

from src.risk.central_arbiter import ArbiterConfig, CentralExceptionArbiter, StationLifeCycleState
from src.risk.incident_protocol import (
    IncidentBus,
    IncidentReasonCode,
    IncidentReport,
    IncidentSeverity,
    IncidentSubsystem,
)
from src.risk.pre_buy_gate import (
    HardValveClosedError,
    LocalHardValve,
    OrderIntent,
    PositionInsulationPolicy,
    PreBuyDecision,
    PreBuyGateConfig,
    PreBuyGateKeeper,
)


class TestPreBuyGateKeeper:
    """Test suite for pre-buy gate freshness and connectivity checks."""

    @pytest.fixture
    def arbiter(self):
        bus = IncidentBus()
        return CentralExceptionArbiter(bus=bus)

    @pytest.fixture
    def gate(self, arbiter):
        config = PreBuyGateConfig(max_observation_age_minutes=7.0)
        valve = LocalHardValve(arbiter=arbiter)
        return PreBuyGateKeeper(arbiter=arbiter, valve=valve, config=config)

    def test_pre_buy_allowed_when_fresh_and_active(self, gate):
        """Verify buy order is permitted when data is fresh (<7.0m) and station is ACTIVE."""
        now = datetime(2026, 9, 21, 14, 0, 0, tzinfo=timezone.utc)
        obs_time = now - timedelta(minutes=3.0)  # 3 minutes old <= 7.0m

        intent = OrderIntent(station_id="KORD", price=0.45, size=100)
        decision = gate.verify_pre_buy(
            intent=intent,
            latest_observation_time=obs_time,
            data_stream_connected=True,
            gateway_connected=True,
            current_wall_time=now,
        )

        assert decision.allowed is True
        assert decision.reason == "APPROVED"

    def test_pre_buy_rejected_on_stale_observation_age(self, gate):
        """Verify buy order is rejected locally when observation age exceeds 7.0m."""
        now = datetime(2026, 9, 21, 14, 0, 0, tzinfo=timezone.utc)
        obs_time = now - timedelta(minutes=7.5)  # 7.5 minutes old > 7.0m

        intent = OrderIntent(station_id="KORD", price=0.45, size=100)
        decision = gate.verify_pre_buy(
            intent=intent,
            latest_observation_time=obs_time,
            data_stream_connected=True,
            gateway_connected=True,
            current_wall_time=now,
        )

        assert decision.allowed is False
        assert decision.reason == "REJECTED_STALE_DATA"
        assert decision.age_seconds == pytest.approx(450.0)

    def test_pre_buy_rejected_on_network_disconnected(self, gate):
        """Verify buy order is rejected if data stream or gateway is not confirmed connected."""
        now = datetime(2026, 9, 21, 14, 0, 0, tzinfo=timezone.utc)
        obs_time = now - timedelta(minutes=2.0)

        intent = OrderIntent(station_id="KLGA", price=0.50, size=50)

        # Data stream disconnected
        d1 = gate.verify_pre_buy(
            intent=intent,
            latest_observation_time=obs_time,
            data_stream_connected=False,
            gateway_connected=True,
            current_wall_time=now,
        )
        assert d1.allowed is False
        assert d1.reason == "REJECTED_NETWORK_DISCONNECTED"

        # Gateway disconnected
        d2 = gate.verify_pre_buy(
            intent=intent,
            latest_observation_time=obs_time,
            data_stream_connected=True,
            gateway_connected=False,
            current_wall_time=now,
        )
        assert d2.allowed is False
        assert d2.reason == "REJECTED_NETWORK_DISCONNECTED"

    def test_pre_buy_rejected_when_station_suspended_or_invalidated(self, gate, arbiter):
        """Verify buy order is rejected if station is SUSPENDED or INVALIDATED in arbiter."""
        now = datetime(2026, 9, 21, 14, 0, 0, tzinfo=timezone.utc)
        obs_time = now - timedelta(minutes=1.0)
        intent = OrderIntent(station_id="KATL", price=0.50, size=50)

        # Trigger suspension in arbiter
        rep = IncidentReport.create(
            station_id="KATL",
            subsystem=IncidentSubsystem.INGESTION,
            severity=IncidentSeverity.DEGRADED,
            reason_code=IncidentReasonCode.DATA_STALENESS,
            timestamp_utc=now,
        )
        arbiter.handle_incident(rep)
        assert arbiter.get_station_state("KATL") == StationLifeCycleState.SUSPENDED

        decision = gate.verify_pre_buy(
            intent=intent,
            latest_observation_time=obs_time,
            data_stream_connected=True,
            gateway_connected=True,
            current_wall_time=now,
        )
        assert decision.allowed is False
        assert decision.reason == "REJECTED_STATION_NOT_ACTIVE"


class TestLocalHardValve:
    """Test suite for LocalHardValve zero-emission and Best-Effort Cancel."""

    def test_valve_instant_closure_and_zero_emission(self):
        """Verify closing valve prevents any byte emission and raises HardValveClosedError."""
        arbiter = CentralExceptionArbiter()
        canceled_stations = []

        valve = LocalHardValve(
            arbiter=arbiter,
            cancel_callback=lambda st: canceled_stations.append(st),
        )

        assert valve.is_open("KORD") is True

        # Close valve for KORD
        valve.close_valve("KORD", reason="PHYSICAL_TEAR")
        assert valve.is_open("KORD") is False
        assert "KORD" in canceled_stations

        # Trying to emit an order through closed valve raises HardValveClosedError
        with pytest.raises(HardValveClosedError, match="Local hard valve is closed"):
            valve.assert_can_emit("KORD")

    def test_best_effort_cancel_resilience_to_callback_failure(self):
        """Verify valve closes cleanly even if external cancel_all callback raises exception."""
        arbiter = CentralExceptionArbiter()

        def failing_cancel(st):
            raise ConnectionResetError("Polymarket CLOB API connection reset")

        valve = LocalHardValve(arbiter=arbiter, cancel_callback=failing_cancel)
        # Closing valve must not propagate the network error to caller
        valve.close_valve("KLGA", reason="NETWORK_TIMEOUT")
        assert valve.is_open("KLGA") is False


class TestPositionInsulationPolicy:
    """Test suite for position insulation and 30-minute settlement escape hatch."""

    def test_filled_position_insulated_from_market_dump(self):
        """Verify filled positions are never dumped into market orderbook during halts."""
        policy = PositionInsulationPolicy()
        action = policy.evaluate_action(
            station_id="KDAL",
            station_state=StationLifeCycleState.SUSPENDED,
            minutes_to_settlement=120.0,  # 2 hours to settlement
        )
        assert action.allow_market_sell is False
        assert action.action_type == "HOLD_TO_SETTLEMENT"

    def test_settlement_escape_hatch_triggered_within_30min(self):
        """Verify within 30 minutes of settlement, position transfers to manual/risk escape hatch."""
        policy = PositionInsulationPolicy(escape_hatch_window_minutes=30.0)
        action = policy.evaluate_action(
            station_id="KDAL",
            station_state=StationLifeCycleState.INVALIDATED,
            minutes_to_settlement=15.0,  # 15 minutes to settlement
        )
        assert action.allow_market_sell is False
        assert action.action_type == "TRANSFER_TO_SETTLEMENT_ESCAPE_HATCH"
        assert action.requires_manual_intervention is True
