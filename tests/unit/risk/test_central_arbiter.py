"""
Unit tests for CentralExceptionArbiter and station lifecycle state machine (Phase 2 Task 03 - Ticket 02 / Issue #72).
Implements ADR-0014 §2 core arbitration principles and dual-categorization.
"""

from datetime import datetime, timezone, timedelta
import pytest

from src.data_processing.constants import ACTIVE_10_STATIONS
from src.risk.central_arbiter import (
    ArbiterConfig,
    CentralExceptionArbiter,
    StationLifeCycleState,
)
from src.risk.incident_protocol import (
    IncidentBus,
    IncidentReasonCode,
    IncidentReport,
    IncidentSeverity,
    IncidentSubsystem,
)


class TestCentralExceptionArbiter:
    """Test suite for CentralExceptionArbiter state machine and dual-categorization arbitration."""

    @pytest.fixture
    def bus(self):
        return IncidentBus()

    @pytest.fixture
    def arbiter(self, bus):
        config = ArbiterConfig(
            cooldown_seconds=10.0,
            consecutive_healthy_frames_required=3,
            max_daily_suspensions=3,
            retry_budget_seconds=30.0,
        )
        return CentralExceptionArbiter(bus=bus, config=config)

    def test_initial_states_all_active(self, arbiter):
        """Verify all Active 10 stations initialize in ACTIVE state."""
        for st in ACTIVE_10_STATIONS:
            assert arbiter.get_station_state(st) == StationLifeCycleState.ACTIVE
            assert arbiter.is_station_tradable(st) is True

    def test_physical_corruption_invalidates_to_eod(self, arbiter):
        """Verify corrupted data immediately transitions station to INVALIDATED."""
        report = IncidentReport.create(
            station_id="KORD",
            subsystem=IncidentSubsystem.TRUNCATION,
            severity=IncidentSeverity.CORRUPTED,
            reason_code=IncidentReasonCode.SANITY_BREACH,
            evidence_snapshot={"jump_f": 20.0},
        )
        arbiter.handle_incident(report)

        assert arbiter.get_station_state("KORD") == StationLifeCycleState.INVALIDATED
        assert arbiter.is_station_tradable("KORD") is False

        # Attempting healthy frame recording must NOT recover INVALIDATED station
        for _ in range(5):
            arbiter.record_healthy_frame("KORD")
        assert arbiter.get_station_state("KORD") == StationLifeCycleState.INVALIDATED

    def test_cor_conflict_invalidates_station(self, arbiter):
        """Verify COR modification conflict invalidates station to EoD."""
        report = IncidentReport.create(
            station_id="KLGA",
            subsystem=IncidentSubsystem.TRUNCATION,
            severity=IncidentSeverity.CORRUPTED,
            reason_code=IncidentReasonCode.COR_CONFLICT,
            evidence_snapshot={"old": 80.0, "cor": 75.0},
        )
        arbiter.handle_incident(report)
        assert arbiter.get_station_state("KLGA") == StationLifeCycleState.INVALIDATED

    def test_communication_degraded_suspends_with_hysteresis_recovery(self, arbiter):
        """Verify DEGRADED communication suspends station and recovers after cooldown + 3 healthy frames."""
        t0 = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)
        report = IncidentReport.create(
            station_id="KATL",
            subsystem=IncidentSubsystem.INGESTION,
            severity=IncidentSeverity.DEGRADED,
            reason_code=IncidentReasonCode.DATA_STALENESS,
            evidence_snapshot={"staleness_minutes": 16.0},
            timestamp_utc=t0,
        )
        arbiter.handle_incident(report)

        assert arbiter.get_station_state("KATL") == StationLifeCycleState.SUSPENDED
        assert arbiter.is_station_tradable("KATL") is False

        # Healthy frame during cooldown (t0 + 5s < cooldown 10s) -> remains SUSPENDED
        t_during_cooldown = t0 + timedelta(seconds=5)
        arbiter.record_healthy_frame("KATL", current_wall_time=t_during_cooldown)
        assert arbiter.get_station_state("KATL") == StationLifeCycleState.SUSPENDED

        # Healthy frame after cooldown (t0 + 12s)
        t1 = t0 + timedelta(seconds=12)
        arbiter.record_healthy_frame("KATL", current_wall_time=t1)
        assert arbiter.get_station_state("KATL") == StationLifeCycleState.SUSPENDED  # Frame 1

        t2 = t0 + timedelta(seconds=15)
        arbiter.record_healthy_frame("KATL", current_wall_time=t2)
        assert arbiter.get_station_state("KATL") == StationLifeCycleState.SUSPENDED  # Frame 2

        t3 = t0 + timedelta(seconds=18)
        arbiter.record_healthy_frame("KATL", current_wall_time=t3)
        assert arbiter.get_station_state("KATL") == StationLifeCycleState.ACTIVE     # Frame 3 -> RECOVERED
        assert arbiter.is_station_tradable("KATL") is True

    def test_daily_suspension_decay_to_invalidated(self, arbiter):
        """Verify 4th suspension within same local day decays to INVALIDATED."""
        t_base = datetime(2026, 9, 21, 10, 0, 0, tzinfo=timezone.utc)

        for cycle in range(3):
            # Trigger suspension
            rep = IncidentReport.create(
                station_id="KDAL",
                subsystem=IncidentSubsystem.INGESTION,
                severity=IncidentSeverity.DEGRADED,
                reason_code=IncidentReasonCode.DATA_STALENESS,
                evidence_snapshot={"cycle": cycle},
                timestamp_utc=t_base + timedelta(minutes=cycle * 30),
            )
            arbiter.handle_incident(rep)
            assert arbiter.get_station_state("KDAL") == StationLifeCycleState.SUSPENDED

            # Fast forward after cooldown and record 3 healthy frames to recover
            t_rec = t_base + timedelta(minutes=cycle * 30, seconds=15)
            for f in range(3):
                arbiter.record_healthy_frame("KDAL", current_wall_time=t_rec + timedelta(seconds=f * 2))
            assert arbiter.get_station_state("KDAL") == StationLifeCycleState.ACTIVE

        # 4th suspension on same day -> triggers decay into INVALIDATED
        rep4 = IncidentReport.create(
            station_id="KDAL",
            subsystem=IncidentSubsystem.INGESTION,
            severity=IncidentSeverity.DEGRADED,
            reason_code=IncidentReasonCode.DATA_STALENESS,
            evidence_snapshot={"cycle": 3},
            timestamp_utc=t_base + timedelta(minutes=120),
        )
        arbiter.handle_incident(rep4)
        assert arbiter.get_station_state("KDAL") == StationLifeCycleState.INVALIDATED

    def test_retry_budget_exhaustion_helper(self, arbiter):
        """Verify retry failure >= 30s automatically escalates to Incident and suspends station."""
        t_now = datetime(2026, 9, 21, 14, 0, 0, tzinfo=timezone.utc)
        arbiter.report_retry_failure(
            station_id="KSEA",
            subsystem=IncidentSubsystem.PRICING,
            retry_count=5,
            elapsed_seconds=32.5,
            evidence={"error": "timeout"},
            wall_time=t_now,
        )

        assert arbiter.get_station_state("KSEA") == StationLifeCycleState.SUSPENDED
        history = arbiter.bus.get_history()
        assert len(history) == 1
        assert history[0].reason_code == IncidentReasonCode.RETRY_BUDGET_EXHAUSTED
        assert history[0].station_id == "KSEA"

    def test_global_scope_suspends_all_active_stations(self, arbiter):
        """Verify GLOBAL incident affects all Active 10 stations."""
        report = IncidentReport.create(
            station_id="GLOBAL",
            subsystem=IncidentSubsystem.EXECUTION,
            severity=IncidentSeverity.DEGRADED,
            reason_code=IncidentReasonCode.EXCHANGE_DOWN,
            evidence_snapshot={"http_code": 502},
        )
        arbiter.handle_incident(report)

        for st in ACTIVE_10_STATIONS:
            assert arbiter.get_station_state(st) == StationLifeCycleState.SUSPENDED

    def test_local_midnight_rollover_resets_invalidated_state(self, arbiter):
        """Verify local midnight rollover safely resets INVALIDATED state to ACTIVE."""
        # Invalidate KORD (America/Chicago) at 23:00 on Day 1
        t_day1 = datetime(2026, 9, 21, 23, 0, 0, tzinfo=timezone.utc)
        rep = IncidentReport.create(
            station_id="KORD",
            subsystem=IncidentSubsystem.TRUNCATION,
            severity=IncidentSeverity.CORRUPTED,
            reason_code=IncidentReasonCode.SANITY_BREACH,
            timestamp_utc=t_day1,
        )
        arbiter.handle_incident(rep)
        assert arbiter.get_station_state("KORD") == StationLifeCycleState.INVALIDATED

        # Advance to next day at noon
        t_day2 = datetime(2026, 9, 22, 18, 0, 0, tzinfo=timezone.utc)
        arbiter.check_calendar_rollover("KORD", current_wall_time=t_day2)
        assert arbiter.get_station_state("KORD") == StationLifeCycleState.ACTIVE
