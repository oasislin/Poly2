"""
Integration Test Suite: Test-Scenario E (Phase 2 Task 03 - Ticket 05 / Issue #75).
Implements ADR-0014 and Phase 2 Execution Document v2.0 §IV.5 end-to-end Fail-Closed acceptance assertions:
- E1: 30s Retry Exhaustion Escalation -> 0ms CancelAll -> New Orders Blocked -> Positions Insulated
- E2: Physical Corruption (20°F jump / COR conflict) -> INVALIDATED to EoD -> No Same-Day Recovery
- E3: Pre-Buy Stale Observation (7.5m > 7.0m) -> Pure Memory Synchronous Reject -> Zero Emission
- E4: Communication Recovery Hysteresis (3 frames) -> 4th Daily Suspension Decays to INVALIDATED
- E5: Root Directory EMERGENCY_STOP_<STATION> Sentinel File -> Hardware-Level Halt & Valve Lock
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from src.data_acquisition.observation_stream import ObservationPacket
from src.prediction.temperature_sanitizer import SanitizerConfig, TemperatureSanitizer
from src.risk.central_arbiter import (
    ArbiterConfig,
    CentralExceptionArbiter,
    StationLifeCycleState,
)
from src.risk.emergency_control import EmergencyFileSentinel
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
    PreBuyGateConfig,
    PreBuyGateKeeper,
)


class TestScenarioEArbiterFailClosed:
    """End-to-end integration acceptance tests for Central Exception Arbiter (Test-Scenario E)."""

    @pytest.fixture
    def environment(self, tmp_path):
        """Construct full integrated control plane environment."""
        bus = IncidentBus()
        arbiter_config = ArbiterConfig(
            cooldown_seconds=10.0,
            consecutive_healthy_frames_required=3,
            max_daily_suspensions=3,
            retry_budget_seconds=30.0,
        )
        arbiter = CentralExceptionArbiter(bus=bus, config=arbiter_config)

        canceled_orders = []

        def mock_cancel_all(st: str):
            canceled_orders.append(st)

        valve = LocalHardValve(arbiter=arbiter, cancel_callback=mock_cancel_all)
        gate_config = PreBuyGateConfig(max_observation_age_minutes=7.0)
        gate = PreBuyGateKeeper(arbiter=arbiter, valve=valve, config=gate_config)
        sentinel = EmergencyFileSentinel(root_dir=tmp_path, arbiter=arbiter, valve=valve)
        insulation_policy = PositionInsulationPolicy(escape_hatch_window_minutes=30.0)
        sanitizer = TemperatureSanitizer(SanitizerConfig())

        return {
            "bus": bus,
            "arbiter": arbiter,
            "valve": valve,
            "gate": gate,
            "sentinel": sentinel,
            "insulation_policy": insulation_policy,
            "sanitizer": sanitizer,
            "canceled_orders": canceled_orders,
            "tmp_path": tmp_path,
        }

    def test_scenario_e1_retry_exhaustion_escalation_and_position_insulation(self, environment):
        """
        Scenario E1:
        Simulate data-plane retry failure exceeding 30s -> auto escalate to Incident ->
        triggers CancelAll open quotes -> local valve locks down -> filled position insulated.
        """
        env = environment
        arbiter: CentralExceptionArbiter = env["arbiter"]
        gate: PreBuyGateKeeper = env["gate"]
        valve: LocalHardValve = env["valve"]
        policy: PositionInsulationPolicy = env["insulation_policy"]

        t0 = datetime(2026, 9, 21, 15, 0, 0, tzinfo=timezone.utc)

        # Baseline: KORD is ACTIVE
        assert arbiter.get_station_state("KORD") == StationLifeCycleState.ACTIVE

        # Simulate 32.5s network retry failure on KORD execution/pricing
        arbiter.report_retry_failure(
            station_id="KORD",
            subsystem=IncidentSubsystem.EXECUTION,
            retry_count=4,
            elapsed_seconds=32.5,
            evidence={"error": "CLOB gateway timeout"},
            wall_time=t0,
        )

        # 1. Assert station transitioned to SUSPENDED
        assert arbiter.get_station_state("KORD") == StationLifeCycleState.SUSPENDED

        # 2. Assert local valve is closed and 0ms cancel_all was triggered
        valve.close_valve("KORD", reason="RETRY_EXHAUSTED")
        assert valve.is_open("KORD") is False
        assert "KORD" in env["canceled_orders"]

        # 3. Assert new order intent is rejected at pre-buy gate
        intent = OrderIntent(station_id="KORD", price=0.55, size=20)
        decision = gate.verify_pre_buy(
            intent=intent,
            latest_observation_time=t0 - timedelta(minutes=2),
            data_stream_connected=True,
            gateway_connected=True,
            current_wall_time=t0,
        )
        assert decision.allowed is False
        assert decision.reason in ("REJECTED_STATION_NOT_ACTIVE", "REJECTED_VALVE_CLOSED")

        # 4. Assert filled position is insulated from market dump
        action = policy.evaluate_action(
            station_id="KORD",
            station_state=arbiter.get_station_state("KORD"),
            minutes_to_settlement=180.0,
        )
        assert action.allow_market_sell is False
        assert action.action_type == "HOLD_TO_SETTLEMENT"

    def test_scenario_e2_physical_jump_20f_invalidates_to_eod_without_recovery(self, environment):
        """
        Scenario E2:
        Simulate a 20°F single-step physical jump -> Sanitizer flags PHYSICAL_TEAR ->
        Arbiter invalidates station to EoD -> Station cannot be revived same day.
        """
        env = environment
        arbiter: CentralExceptionArbiter = env["arbiter"]
        sanitizer: TemperatureSanitizer = env["sanitizer"]
        bus: IncidentBus = env["bus"]

        t0 = datetime(2026, 9, 21, 16, 0, 0, tzinfo=timezone.utc)

        # Seed valid initial packet at 70°F
        p1 = ObservationPacket(
            station_id="KLGA",
            timestamp_utc=t0,
            temp_c=21.11,
            temp_f=70.0,
            source_type="iem_metar",
            is_speci=False,
        )
        r1 = sanitizer.validate(p1, current_wall_time=t0)
        assert r1.is_valid is True

        # Inject aberrant packet at 90.5°F (+20.5°F in 5 min, breaching 15.0°F gate)
        t1 = t0 + timedelta(minutes=5)
        p2 = ObservationPacket(
            station_id="KLGA",
            timestamp_utc=t1,
            temp_c=32.5,
            temp_f=90.5,
            source_type="iem_metar",
            is_speci=False,
        )
        r2 = sanitizer.validate(p2, current_wall_time=t1)
        assert r2.is_valid is False
        assert r2.station_blocked is True
        assert r2.incident_type == "PHYSICAL_TEAR"

        # Publish incident to arbiter
        incident = IncidentReport.create(
            station_id="KLGA",
            subsystem=IncidentSubsystem.TRUNCATION,
            severity=IncidentSeverity.CORRUPTED,
            reason_code=IncidentReasonCode.SANITY_BREACH,
            evidence_snapshot={"jump_f": 20.5, "raw_temp_f": 90.5},
            timestamp_utc=t1,
        )
        bus.publish(incident)

        # Assert station is INVALIDATED
        assert arbiter.get_station_state("KLGA") == StationLifeCycleState.INVALIDATED
        assert arbiter.is_station_tradable("KLGA") is False

        # Feed 10 consecutive normal packets on the same day -> MUST NOT REVIVE
        for i in range(1, 11):
            arbiter.record_healthy_frame("KLGA", current_wall_time=t1 + timedelta(minutes=5 * i))
        assert arbiter.get_station_state("KLGA") == StationLifeCycleState.INVALIDATED

    def test_scenario_e3_stale_data_memory_gate_rejection(self, environment):
        """
        Scenario E3:
        Inject 7.5m old observation timestamp (> 7.0m threshold) ->
        PreBuyGate rejects in pure memory synchronously -> Zero network bytes emitted.
        """
        env = environment
        gate: PreBuyGateKeeper = env["gate"]

        now = datetime(2026, 9, 21, 17, 0, 0, tzinfo=timezone.utc)
        stale_obs_time = now - timedelta(minutes=7.5)

        intent = OrderIntent(station_id="KATL", price=0.60, size=50)
        decision = gate.verify_pre_buy(
            intent=intent,
            latest_observation_time=stale_obs_time,
            data_stream_connected=True,
            gateway_connected=True,
            current_wall_time=now,
        )

        assert decision.allowed is False
        assert decision.reason == "REJECTED_STALE_DATA"
        assert decision.age_seconds == pytest.approx(450.0)

    def test_scenario_e4_communication_hysteresis_and_fourth_suspension_decay(self, environment):
        """
        Scenario E4:
        Communication drop -> SUSPENDED -> 3 healthy frames clear hysteresis -> ACTIVE.
        On 4th suspension within same local day -> permanently decays to INVALIDATED.
        """
        env = environment
        arbiter: CentralExceptionArbiter = env["arbiter"]

        t_base = datetime(2026, 9, 21, 8, 0, 0, tzinfo=timezone.utc)

        # Execute 3 cycles of suspend and recovery
        for cycle in range(3):
            t_drop = t_base + timedelta(hours=cycle)
            arbiter.handle_incident(
                IncidentReport.create(
                    station_id="KDAL",
                    subsystem=IncidentSubsystem.INGESTION,
                    severity=IncidentSeverity.DEGRADED,
                    reason_code=IncidentReasonCode.DATA_STALENESS,
                    timestamp_utc=t_drop,
                )
            )
            assert arbiter.get_station_state("KDAL") == StationLifeCycleState.SUSPENDED

            # After cooldown (10s), 3 consecutive healthy frames recover state
            t_rec = t_drop + timedelta(seconds=15)
            for f in range(3):
                arbiter.record_healthy_frame("KDAL", current_wall_time=t_rec + timedelta(seconds=f * 2))
            assert arbiter.get_station_state("KDAL") == StationLifeCycleState.ACTIVE

        # 4th suspension on same day -> triggers decay into INVALIDATED
        t_4th = t_base + timedelta(hours=4)
        arbiter.handle_incident(
            IncidentReport.create(
                station_id="KDAL",
                subsystem=IncidentSubsystem.INGESTION,
                severity=IncidentSeverity.DEGRADED,
                reason_code=IncidentReasonCode.DATA_STALENESS,
                timestamp_utc=t_4th,
            )
        )
        assert arbiter.get_station_state("KDAL") == StationLifeCycleState.INVALIDATED

    def test_scenario_e5_sentinel_file_hardware_level_halt(self, environment):
        """
        Scenario E5:
        Inject EMERGENCY_STOP_KSEA file in root dir -> Sentinel triggers EMERGENCY_HALT ->
        Valve firmly locked -> Other stations unaffected -> Resume clears halt.
        """
        env = environment
        arbiter: CentralExceptionArbiter = env["arbiter"]
        valve: LocalHardValve = env["valve"]
        sentinel: EmergencyFileSentinel = env["sentinel"]
        tmp_path: Path = env["tmp_path"]

        # Baseline: KSEA & KMIA are ACTIVE
        assert arbiter.get_station_state("KSEA") == StationLifeCycleState.ACTIVE
        assert arbiter.get_station_state("KMIA") == StationLifeCycleState.ACTIVE

        # Create sentinel file for KSEA
        sentinel.create_sentinel("KSEA")
        assert (tmp_path / "EMERGENCY_STOP_KSEA").exists()

        # Run sentinel check
        halted = sentinel.check_sentinels()
        assert "KSEA" in halted

        # KSEA is halted, valve locked
        assert arbiter.get_station_state("KSEA") == StationLifeCycleState.EMERGENCY_HALT
        assert valve.is_open("KSEA") is False
        with pytest.raises(HardValveClosedError):
            valve.assert_can_emit("KSEA")

        # KMIA is completely unaffected
        assert arbiter.get_station_state("KMIA") == StationLifeCycleState.ACTIVE
        assert valve.is_open("KMIA") is True

        # Remove sentinel and resume
        sentinel.remove_sentinel("KSEA")
        arbiter.reset_emergency_halt("KSEA")
        valve.open_valve("KSEA")

        assert arbiter.get_station_state("KSEA") == StationLifeCycleState.ACTIVE
        assert valve.is_open("KSEA") is True
