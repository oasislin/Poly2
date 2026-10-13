"""
Unit tests for unified Incident protocol and IncidentBus (Phase 2 Task 03 - Ticket 01 / Issue #71).
Implements ADR-0014 §3 standard incident contract validation.
"""

from datetime import datetime, timezone
import pytest

from src.data_processing.constants import ACTIVE_10_STATIONS
from src.risk.incident_protocol import (
    IncidentBus,
    IncidentReasonCode,
    IncidentReport,
    IncidentSeverity,
    IncidentSubsystem,
)


class TestIncidentProtocol:
    """Test suite for ADR-0014 §3 standard Incident contract."""

    def test_valid_incident_report_creation(self):
        """Verify standard 7-field IncidentReport creation with defaults."""
        now = datetime.now(timezone.utc)
        report = IncidentReport.create(
            station_id="KORD",
            subsystem=IncidentSubsystem.TRUNCATION,
            severity=IncidentSeverity.CORRUPTED,
            reason_code=IncidentReasonCode.SANITY_BREACH,
            evidence_snapshot={"raw_temp": 150.0, "reason": "Gate 1 breach"},
            timestamp_utc=now,
        )

        assert report.incident_id is not None
        assert len(report.incident_id) > 0
        assert report.station_id == "KORD"
        assert report.subsystem == IncidentSubsystem.TRUNCATION
        assert report.severity == IncidentSeverity.CORRUPTED
        assert report.reason_code == IncidentReasonCode.SANITY_BREACH
        assert report.timestamp_utc == now
        assert report.evidence_snapshot["raw_temp"] == 150.0

    def test_global_station_scope_allowed(self):
        """Verify 'GLOBAL' station_id is accepted for system-wide incidents."""
        report = IncidentReport.create(
            station_id="GLOBAL",
            subsystem=IncidentSubsystem.EXECUTION,
            severity=IncidentSeverity.PANIC,
            reason_code=IncidentReasonCode.EXCHANGE_DOWN,
            evidence_snapshot={"status_code": 503},
        )
        assert report.station_id == "GLOBAL"

    def test_invalid_station_rejected(self):
        """Verify non-active station (e.g. KDCA or invalid code) is strictly rejected."""
        with pytest.raises(ValueError, match="Invalid station_id"):
            IncidentReport.create(
                station_id="KDCA",  # Retired station
                subsystem=IncidentSubsystem.INGESTION,
                severity=IncidentSeverity.DEGRADED,
                reason_code=IncidentReasonCode.DATA_STALENESS,
                evidence_snapshot={},
            )

        with pytest.raises(ValueError, match="Invalid station_id"):
            IncidentReport.create(
                station_id="UNKNOWN_STATION",
                subsystem=IncidentSubsystem.INGESTION,
                severity=IncidentSeverity.DEGRADED,
                reason_code=IncidentReasonCode.DATA_STALENESS,
                evidence_snapshot={},
            )

    def test_immutability_of_report_and_evidence(self):
        """Verify IncidentReport is frozen and evidence snapshot cannot be mutated in place."""
        report = IncidentReport.create(
            station_id="KLGA",
            subsystem=IncidentSubsystem.INGESTION,
            severity=IncidentSeverity.DEGRADED,
            reason_code=IncidentReasonCode.DATA_STALENESS,
            evidence_snapshot={"lag_minutes": 16.0},
        )

        with pytest.raises((TypeError, AttributeError)):
            report.station_id = "KATL"  # Frozen dataclass check

        with pytest.raises((TypeError, AttributeError)):
            report.evidence_snapshot["lag_minutes"] = 99.0  # MappingProxyType or read-only dict

    def test_naive_datetime_converted_to_utc(self):
        """Verify timezone-naive timestamps are automatically normalized to UTC."""
        naive_dt = datetime(2026, 9, 21, 12, 0, 0)
        report = IncidentReport.create(
            station_id="KDAL",
            subsystem=IncidentSubsystem.PRICING,
            severity=IncidentSeverity.DEGRADED,
            reason_code=IncidentReasonCode.RETRY_BUDGET_EXHAUSTED,
            evidence_snapshot={"retry_s": 31.0},
            timestamp_utc=naive_dt,
        )
        assert report.timestamp_utc.tzinfo is not None
        assert report.timestamp_utc == naive_dt.replace(tzinfo=timezone.utc)

    def test_serialization_roundtrip(self):
        """Verify IncidentReport to_dict and from_dict roundtrip fidelity."""
        original = IncidentReport.create(
            station_id="KSEA",
            subsystem=IncidentSubsystem.TRUNCATION,
            severity=IncidentSeverity.CORRUPTED,
            reason_code=IncidentReasonCode.COR_CONFLICT,
            evidence_snapshot={"old_tmax": 75.0, "cor_tmax": 70.0},
        )
        d = original.to_dict()
        reconstructed = IncidentReport.from_dict(d)

        assert reconstructed.incident_id == original.incident_id
        assert reconstructed.station_id == original.station_id
        assert reconstructed.subsystem == original.subsystem
        assert reconstructed.severity == original.severity
        assert reconstructed.reason_code == original.reason_code
        assert reconstructed.timestamp_utc == original.timestamp_utc
        assert dict(reconstructed.evidence_snapshot) == dict(original.evidence_snapshot)


class TestIncidentBus:
    """Test suite for IncidentBus pub/sub dispatching."""

    def test_publish_and_subscribe_all(self):
        """Verify bus delivers published incident to registered subscriber."""
        bus = IncidentBus()
        received = []

        bus.subscribe(lambda inc: received.append(inc))

        report = IncidentReport.create(
            station_id="KLAX",
            subsystem=IncidentSubsystem.INGESTION,
            severity=IncidentSeverity.DEGRADED,
            reason_code=IncidentReasonCode.DATA_STALENESS,
            evidence_snapshot={},
        )
        bus.publish(report)

        assert len(received) == 1
        assert received[0].incident_id == report.incident_id
        assert len(bus.get_history()) == 1

    def test_subscriber_filtering(self):
        """Verify subscriber filter by severity and station_id."""
        bus = IncidentBus()
        corrupted_kord_events = []

        bus.subscribe(
            lambda inc: corrupted_kord_events.append(inc),
            severities={IncidentSeverity.CORRUPTED},
            station_ids={"KORD"},
        )

        r1 = IncidentReport.create(
            station_id="KORD",
            subsystem=IncidentSubsystem.TRUNCATION,
            severity=IncidentSeverity.DEGRADED,
            reason_code=IncidentReasonCode.DATA_STALENESS,
            evidence_snapshot={},
        )
        r2 = IncidentReport.create(
            station_id="KLGA",
            subsystem=IncidentSubsystem.TRUNCATION,
            severity=IncidentSeverity.CORRUPTED,
            reason_code=IncidentReasonCode.SANITY_BREACH,
            evidence_snapshot={},
        )
        r3 = IncidentReport.create(
            station_id="KORD",
            subsystem=IncidentSubsystem.TRUNCATION,
            severity=IncidentSeverity.CORRUPTED,
            reason_code=IncidentReasonCode.SANITY_BREACH,
            evidence_snapshot={},
        )

        bus.publish(r1)
        bus.publish(r2)
        bus.publish(r3)

        assert len(corrupted_kord_events) == 1
        assert corrupted_kord_events[0].incident_id == r3.incident_id
        assert len(bus.get_history()) == 3
