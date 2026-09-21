"""
Unified Incident Protocol and Bus Dispatcher (Phase 2 Task 03 - Ticket 01 / Issue #71).
Implements ADR-0014 §3 standard incident contract and controlled enums for system-wide exceptions.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import logging
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Optional, Set
import uuid

from src.data_processing.constants import ACTIVE_10_STATIONS

logger = logging.getLogger(__name__)

# Allowed entities: Active 10 trading stations or GLOBAL
ALLOWED_STATION_SCOPES: Set[str] = set(ACTIVE_10_STATIONS) | {"GLOBAL"}


class IncidentSubsystem(str, Enum):
    """Subsystems originating incidents (ADR-0014 §3)."""
    INGESTION = "INGESTION"
    TRUNCATION = "TRUNCATION"
    PRICING = "PRICING"
    EXECUTION = "EXECUTION"
    SETTLEMENT = "SETTLEMENT"


class IncidentSeverity(str, Enum):
    """Severity levels for incidents (ADR-0014 §3)."""
    DEGRADED = "DEGRADED"      # e.g., network retry exhaustion, heartbeat timeout
    CORRUPTED = "CORRUPTED"    # e.g., physical sanity breach, COR conflict
    PANIC = "PANIC"            # e.g., global exchange down, emergency stop triggered


class IncidentReasonCode(str, Enum):
    """Controlled incident reason codes (ADR-0014 §3)."""
    SANITY_BREACH = "SANITY_BREACH"
    DATA_STALENESS = "DATA_STALENESS"
    COR_CONFLICT = "COR_CONFLICT"
    EXCHANGE_DOWN = "EXCHANGE_DOWN"
    MANUAL_EMERGENCY_STOP = "MANUAL_EMERGENCY_STOP"
    RETRY_BUDGET_EXHAUSTED = "RETRY_BUDGET_EXHAUSTED"


@dataclass(frozen=True)
class IncidentReport:
    """
    Standard Immutable Incident Contract (ADR-0014 §3).
    Encapsulates all 7 constitutional fields with zero mutable leakage.
    """
    incident_id: str
    timestamp_utc: datetime
    station_id: str
    subsystem: IncidentSubsystem
    severity: IncidentSeverity
    reason_code: IncidentReasonCode
    evidence_snapshot: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))
    retry_count: int = 0
    retry_elapsed_seconds: float = 0.0

    def __post_init__(self):
        # Validate station_id
        if self.station_id not in ALLOWED_STATION_SCOPES:
            raise ValueError(
                f"Invalid station_id: '{self.station_id}'. Must be one of {sorted(ALLOWED_STATION_SCOPES)}"
            )

        # Enforce UTC timezone on timestamp
        if self.timestamp_utc.tzinfo is None:
            object.__setattr__(
                self, "timestamp_utc", self.timestamp_utc.replace(tzinfo=timezone.utc)
            )

        # Ensure evidence_snapshot is read-only
        if not isinstance(self.evidence_snapshot, MappingProxyType):
            object.__setattr__(
                self, "evidence_snapshot", MappingProxyType(dict(self.evidence_snapshot))
            )

    @classmethod
    def create(
        cls,
        station_id: str,
        subsystem: IncidentSubsystem,
        severity: IncidentSeverity,
        reason_code: IncidentReasonCode,
        evidence_snapshot: Optional[Dict[str, Any]] = None,
        incident_id: Optional[str] = None,
        timestamp_utc: Optional[datetime] = None,
        retry_count: int = 0,
        retry_elapsed_seconds: float = 0.0,
    ) -> "IncidentReport":
        """Factory method to create a valid IncidentReport with automatic ID & UTC timestamp."""
        i_id = incident_id or str(uuid.uuid4())
        ts = timestamp_utc or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        read_only_snapshot = MappingProxyType(dict(evidence_snapshot or {}))
        return cls(
            incident_id=i_id,
            timestamp_utc=ts,
            station_id=station_id,
            subsystem=subsystem,
            severity=severity,
            reason_code=reason_code,
            evidence_snapshot=read_only_snapshot,
            retry_count=retry_count,
            retry_elapsed_seconds=retry_elapsed_seconds,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize IncidentReport into a standard JSON-compatible dictionary."""
        return {
            "incident_id": self.incident_id,
            "timestamp_utc": self.timestamp_utc.isoformat(),
            "station_id": self.station_id,
            "subsystem": self.subsystem.value,
            "severity": self.severity.value,
            "reason_code": self.reason_code.value,
            "evidence_snapshot": dict(self.evidence_snapshot),
            "retry_count": self.retry_count,
            "retry_elapsed_seconds": self.retry_elapsed_seconds,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IncidentReport":
        """Deserialize an IncidentReport from a dictionary representation."""
        ts = datetime.fromisoformat(data["timestamp_utc"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        return cls.create(
            incident_id=data["incident_id"],
            timestamp_utc=ts,
            station_id=data["station_id"],
            subsystem=IncidentSubsystem(data["subsystem"]),
            severity=IncidentSeverity(data["severity"]),
            reason_code=IncidentReasonCode(data["reason_code"]),
            evidence_snapshot=data.get("evidence_snapshot", {}),
            retry_count=data.get("retry_count", 0),
            retry_elapsed_seconds=data.get("retry_elapsed_seconds", 0.0),
        )


class IncidentBus:
    """
    Synchronous In-Memory Incident Bus (ADR-0014).
    Dispatches published incident reports to registered subscribers with filtering support.
    """

    def __init__(self):
        self._subscribers: List[Dict[str, Any]] = []
        self._history: List[IncidentReport] = []

    def subscribe(
        self,
        callback: Callable[[IncidentReport], None],
        subsystems: Optional[Set[IncidentSubsystem]] = None,
        severities: Optional[Set[IncidentSeverity]] = None,
        station_ids: Optional[Set[str]] = None,
    ) -> None:
        """Register a subscriber callback with optional filtering predicates."""
        self._subscribers.append({
            "callback": callback,
            "subsystems": subsystems,
            "severities": severities,
            "station_ids": station_ids,
        })

    def publish(self, incident: IncidentReport) -> None:
        """Publish an incident report to all matching subscribers synchronously."""
        self._history.append(incident)
        logger.warning(
            f"Incident published: [{incident.severity.value}] {incident.station_id} "
            f"{incident.subsystem.value}:{incident.reason_code.value} (ID: {incident.incident_id})"
        )

        for sub in self._subscribers:
            # Check filter predicates
            if sub["subsystems"] and incident.subsystem not in sub["subsystems"]:
                continue
            if sub["severities"] and incident.severity not in sub["severities"]:
                continue
            if sub["station_ids"] and incident.station_id not in sub["station_ids"]:
                continue

            try:
                sub["callback"](incident)
            except Exception as e:
                logger.error(f"Error in incident subscriber callback: {e}", exc_info=True)

    def get_history(self) -> List[IncidentReport]:
        """Return a copy of all recorded incident reports."""
        return list(self._history)

    def clear_history(self) -> None:
        """Clear recorded incidents in memory."""
        self._history.clear()
