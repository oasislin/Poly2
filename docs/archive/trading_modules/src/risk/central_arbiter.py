"""
Central Exception Arbiter and Station Lifecycle State Machine (Phase 2 Task 03 - Ticket 02 / Issue #72).
Implements ADR-0014 §2 core arbitration principles, dual-categorization (INVALIDATED vs SUSPENDED),
and retry budget exhaustion escalation.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, date
from enum import Enum
import logging
from typing import Any, Dict, Optional, Set
import zoneinfo

from src.data_processing.constants import ACTIVE_10_STATIONS, STATION_METADATA
from src.risk.incident_protocol import (
    IncidentBus,
    IncidentReasonCode,
    IncidentReport,
    IncidentSeverity,
    IncidentSubsystem,
)

logger = logging.getLogger(__name__)


class StationLifeCycleState(str, Enum):
    """Controlled lifecycle states for trading stations (ADR-0014 §2)."""
    ACTIVE = "ACTIVE"              # Fully operational and tradable
    SUSPENDED = "SUSPENDED"        # Temporarily suspended, in cooldown / hysteresis observation
    INVALIDATED = "INVALIDATED"    # Corrupted / physical tear, invalidated to EoD
    EMERGENCY_HALT = "EMERGENCY_HALT"  # Hardware-level emergency stop (sentinel / manual)


@dataclass(frozen=True)
class ArbiterConfig:
    """Configurable thresholds for arbitration and lifecycle management."""
    cooldown_seconds: float = 60.0
    consecutive_healthy_frames_required: int = 3
    max_daily_suspensions: int = 3
    retry_budget_seconds: float = 30.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArbiterConfig":
        """Build ArbiterConfig from dictionary (e.g. from default.yaml)."""
        cfg = data.get("arbiter", data)
        return cls(
            cooldown_seconds=float(cfg.get("cooldown_seconds", 60.0)),
            consecutive_healthy_frames_required=int(cfg.get("consecutive_healthy_frames_required", 3)),
            max_daily_suspensions=int(cfg.get("max_daily_suspensions", 3)),
            retry_budget_seconds=float(cfg.get("retry_budget_seconds", 30.0)),
        )


@dataclass
class _StationStateRecord:
    state: StationLifeCycleState = StationLifeCycleState.ACTIVE
    suspension_count: int = 0
    last_suspension_time: Optional[datetime] = None
    consecutive_healthy_frames: int = 0
    current_calendar_day: Optional[date] = None
    last_reason: Optional[str] = None


class CentralExceptionArbiter:
    """
    Central control plane exception arbiter (ADR-0014).
    Governs Active 10 station lifecycle states, performs dual-categorization,
    enforces hysteresis recovery, and monitors retry budgets.
    """

    def __init__(self, bus: Optional[IncidentBus] = None, config: Optional[ArbiterConfig] = None):
        self.bus = bus or IncidentBus()
        self.config = config or ArbiterConfig()
        self._states: Dict[str, _StationStateRecord] = {}

        # Auto-subscribe arbiter to incident bus
        self.bus.subscribe(self.handle_incident)

        # Initialize all Active 10 stations
        for st in ACTIVE_10_STATIONS:
            self._states[st] = _StationStateRecord()

    def _get_station_tz(self, station_id: str) -> zoneinfo.ZoneInfo:
        tz_name = STATION_METADATA.get(station_id, {}).get("timezone", "UTC")
        try:
            return zoneinfo.ZoneInfo(tz_name)
        except Exception:
            return zoneinfo.ZoneInfo("UTC")

    def _get_local_date(self, station_id: str, dt_utc: datetime) -> date:
        tz = self._get_station_tz(station_id)
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        return dt_utc.astimezone(tz).date()

    def check_calendar_rollover(
        self, station_id: str, current_wall_time: Optional[datetime] = None
    ) -> None:
        """Atomically reset suspension counters and INVALIDATED states at local midnight."""
        if station_id not in self._states:
            return

        now = current_wall_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        current_local_date = self._get_local_date(station_id, now)
        record = self._states[station_id]

        if record.current_calendar_day is None:
            record.current_calendar_day = current_local_date
            return

        if current_local_date > record.current_calendar_day:
            logger.info(
                f"Station {station_id} midnight rollover detected: {record.current_calendar_day} -> {current_local_date}. Resetting state."
            )
            record.current_calendar_day = current_local_date
            record.suspension_count = 0
            record.consecutive_healthy_frames = 0
            # Reset INVALIDATED or SUSPENDED back to ACTIVE (EMERGENCY_HALT requires manual reset)
            if record.state in (StationLifeCycleState.INVALIDATED, StationLifeCycleState.SUSPENDED):
                record.state = StationLifeCycleState.ACTIVE
                record.last_reason = "MIDNIGHT_ROLLOVER_RESET"

    def get_station_state(self, station_id: str) -> StationLifeCycleState:
        """Return the current lifecycle state of a station."""
        record = self._states.get(station_id)
        if not record:
            return StationLifeCycleState.INVALIDATED
        return record.state

    def is_station_tradable(self, station_id: str) -> bool:
        """Check if station is fully qualified for active quoting and trading."""
        return self.get_station_state(station_id) == StationLifeCycleState.ACTIVE

    def handle_incident(self, incident: IncidentReport) -> None:
        """
        Arbitrate an incoming IncidentReport (ADR-0014 §2).
        Enforces dual-categorization: physical corruption -> INVALIDATED, degraded communication -> SUSPENDED.
        """
        targets = ACTIVE_10_STATIONS if incident.station_id == "GLOBAL" else (incident.station_id,)

        now = incident.timestamp_utc
        for st in targets:
            if st not in self._states:
                continue

            self.check_calendar_rollover(st, current_wall_time=now)
            rec = self._states[st]

            # 1. Emergency stop or PANIC severity -> EMERGENCY_HALT
            if (
                incident.reason_code == IncidentReasonCode.MANUAL_EMERGENCY_STOP
                or incident.severity == IncidentSeverity.PANIC
            ):
                rec.state = StationLifeCycleState.EMERGENCY_HALT
                rec.last_reason = incident.reason_code.value
                logger.critical(f"Station {st} placed in EMERGENCY_HALT by incident {incident.incident_id}")
                continue

            # If already in EMERGENCY_HALT, do not overwrite unless explicit reset
            if rec.state == StationLifeCycleState.EMERGENCY_HALT:
                continue

            # 2. Physical Untrustworthiness (CORRUPTED / SANITY_BREACH / COR_CONFLICT) -> INVALIDATED to EoD
            if (
                incident.severity == IncidentSeverity.CORRUPTED
                or incident.reason_code in (IncidentReasonCode.SANITY_BREACH, IncidentReasonCode.COR_CONFLICT)
            ):
                rec.state = StationLifeCycleState.INVALIDATED
                rec.last_reason = incident.reason_code.value
                logger.warning(
                    f"Station {st} INVALIDATED to EoD due to physical corruption: {incident.reason_code.value}"
                )
                continue

            # If already INVALIDATED, cannot recover or suspend
            if rec.state == StationLifeCycleState.INVALIDATED:
                continue

            # 3. Communication Degraded (DEGRADED / DATA_STALENESS / EXCHANGE_DOWN / RETRY_BUDGET_EXHAUSTED) -> SUSPENDED
            if (
                incident.severity == IncidentSeverity.DEGRADED
                or incident.reason_code in (
                    IncidentReasonCode.DATA_STALENESS,
                    IncidentReasonCode.EXCHANGE_DOWN,
                    IncidentReasonCode.RETRY_BUDGET_EXHAUSTED,
                )
            ):
                if rec.state != StationLifeCycleState.SUSPENDED:
                    rec.suspension_count += 1

                # Check decay rule: > max_daily_suspensions (default 3) -> decays to INVALIDATED
                if rec.suspension_count > self.config.max_daily_suspensions:
                    rec.state = StationLifeCycleState.INVALIDATED
                    rec.last_reason = "MAX_DAILY_SUSPENSIONS_EXCEEDED"
                    logger.warning(
                        f"Station {st} decayed to INVALIDATED: {rec.suspension_count} suspensions exceeded limit {self.config.max_daily_suspensions}"
                    )
                else:
                    rec.state = StationLifeCycleState.SUSPENDED
                    rec.last_suspension_time = now
                    rec.consecutive_healthy_frames = 0
                    rec.last_reason = incident.reason_code.value
                    logger.warning(
                        f"Station {st} SUSPENDED ({rec.suspension_count}/{self.config.max_daily_suspensions}) due to: {incident.reason_code.value}"
                    )

    def record_healthy_frame(
        self, station_id: str, current_wall_time: Optional[datetime] = None
    ) -> None:
        """
        Record a verified healthy packet for hysteresis recovery lock evaluation.
        Requires cooldown elapsed + consecutive healthy frames to recover from SUSPENDED.
        """
        if station_id not in self._states:
            return

        now = current_wall_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        self.check_calendar_rollover(station_id, current_wall_time=now)
        rec = self._states[station_id]

        if rec.state != StationLifeCycleState.SUSPENDED:
            # If ACTIVE, INVALIDATED, or EMERGENCY_HALT, no recovery evaluation needed
            return

        # Check cooldown period
        if rec.last_suspension_time:
            elapsed_cooldown = (now - rec.last_suspension_time).total_seconds()
            if elapsed_cooldown < self.config.cooldown_seconds:
                # Still in quiet cooldown window, ignore health frames
                return

        rec.consecutive_healthy_frames += 1
        if rec.consecutive_healthy_frames >= self.config.consecutive_healthy_frames_required:
            rec.state = StationLifeCycleState.ACTIVE
            rec.consecutive_healthy_frames = 0
            rec.last_reason = "HYSTERESIS_RECOVERY_CLEARED"
            logger.info(
                f"Station {station_id} successfully cleared hysteresis lock and recovered to ACTIVE."
            )

    def report_retry_failure(
        self,
        station_id: str,
        subsystem: IncidentSubsystem,
        retry_count: int,
        elapsed_seconds: float,
        evidence: Optional[Dict[str, Any]] = None,
        wall_time: Optional[datetime] = None,
    ) -> None:
        """
        Evaluate technical transient retry budget (ADR-0014 §2 Principle 1).
        If elapsed time >= retry_budget_seconds (30s), escalate to IncidentReport and publish.
        """
        if elapsed_seconds >= self.config.retry_budget_seconds:
            logger.error(
                f"Subsystem {subsystem.value} on station {station_id} exhausted retry budget "
                f"({elapsed_seconds:.1f}s >= {self.config.retry_budget_seconds}s, count={retry_count}). Escalating to Incident."
            )
            snapshot = dict(evidence or {})
            snapshot["retry_count"] = retry_count
            snapshot["elapsed_seconds"] = elapsed_seconds

            rep = IncidentReport.create(
                station_id=station_id,
                subsystem=subsystem,
                severity=IncidentSeverity.DEGRADED,
                reason_code=IncidentReasonCode.RETRY_BUDGET_EXHAUSTED,
                evidence_snapshot=snapshot,
                timestamp_utc=wall_time or datetime.now(timezone.utc),
                retry_count=retry_count,
                retry_elapsed_seconds=elapsed_seconds,
            )
            self.bus.publish(rep)

    def set_emergency_halt(self, station_id: str, reason: str = "MANUAL_STOP") -> None:
        """Explicitly place station (or GLOBAL) into EMERGENCY_HALT state."""
        rep = IncidentReport.create(
            station_id=station_id,
            subsystem=IncidentSubsystem.EXECUTION,
            severity=IncidentSeverity.PANIC,
            reason_code=IncidentReasonCode.MANUAL_EMERGENCY_STOP,
            evidence_snapshot={"reason": reason},
        )
        self.bus.publish(rep)

    def reset_emergency_halt(self, station_id: str) -> None:
        """Explicitly clear EMERGENCY_HALT state and return station to ACTIVE."""
        targets = ACTIVE_10_STATIONS if station_id == "GLOBAL" else (station_id,)
        for st in targets:
            if st in self._states:
                self._states[st].state = StationLifeCycleState.ACTIVE
                self._states[st].last_reason = "EMERGENCY_HALT_CLEARED"
                logger.info(f"Station {st} cleared EMERGENCY_HALT and restored to ACTIVE.")
