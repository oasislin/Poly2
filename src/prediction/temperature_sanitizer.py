"""
Pure-Temperature Sanity Gates, Missed Window Discarder, and Fail-Closed Circuit Breaker (Phase 2 Task 02 - Ticket 02 / Issue #66).
Implements ADR-0013 and ADR-0011 core gate contracts for Active 10 observation streams.
"""

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import logging
from typing import Any, Dict, Optional

from src.data_acquisition.observation_stream import ObservationPacket

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SanitizerConfig:
    """Configuration constants for temperature sanity gates (ADR-0013)."""
    climatological_min_f: float = -40.0
    climatological_max_f: float = 135.0
    max_body_rmk_delta_f: float = 1.8
    max_temperature_jump_step_f: float = 15.0
    stale_packet_threshold_minutes: float = 15.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SanitizerConfig":
        """Build SanitizerConfig from config dictionary (e.g. from default.yaml)."""
        rules = data.get("truncation_rules", data)
        return cls(
            climatological_min_f=float(rules.get("climatological_min_f", -40.0)),
            climatological_max_f=float(rules.get("climatological_max_f", 135.0)),
            max_body_rmk_delta_f=float(rules.get("max_body_rmk_delta_f", 1.8)),
            max_temperature_jump_step_f=float(rules.get("max_temperature_jump_step_f", 15.0)),
            stale_packet_threshold_minutes=float(rules.get("stale_packet_threshold_minutes", 15.0)),
        )


@dataclass(frozen=True)
class SanitizerResult:
    """Result verdict of observation sanitization."""
    is_valid: bool
    is_late: bool = False
    station_blocked: bool = False
    error_reason: Optional[str] = None
    incident_type: Optional[str] = None  # e.g., "PHYSICAL_TEAR"
    action: Optional[str] = None  # e.g., "CANCEL_ALL_OPEN_ORDERS"


class TemperatureSanitizer:
    """
    Validates observation packets against pure-temperature sanity gates and timeliness rules.
    Maintains per-station latest observation state and blocks stations on physical tear.
    """

    def __init__(self, config: Optional[SanitizerConfig] = None):
        self.config = config or SanitizerConfig()
        # Per-station history: station_id -> {"last_temp_f": float, "last_timestamp_utc": datetime, "is_blocked": bool}
        self._station_states: Dict[str, Dict] = {}

    def is_station_blocked(self, station_id: str) -> bool:
        """Check if station is currently under Fail-Closed safety block."""
        return self._station_states.get(station_id, {}).get("is_blocked", False)

    def reset_station_block(self, station_id: str) -> None:
        """Reset blocked station state (e.g. at local midnight rollover)."""
        if station_id in self._station_states:
            self._station_states[station_id]["is_blocked"] = False

    def validate(
        self,
        packet: ObservationPacket,
        current_wall_time: Optional[datetime] = None,
    ) -> SanitizerResult:
        """
        Validate an incoming ObservationPacket.
        Enforces Missed Window Lateness, Gate 1, Gate 2, and Gate 3.
        """
        station = packet.station_id
        if station not in self._station_states:
            self._station_states[station] = {
                "last_temp_f": None,
                "last_timestamp_utc": None,
                "is_blocked": False,
            }

        state = self._station_states[station]

        pkt_time = packet.timestamp_utc
        if pkt_time.tzinfo is None:
            pkt_time = pkt_time.replace(tzinfo=timezone.utc)

        # Check if local calendar day advanced, auto-resetting block per ADR-0013
        from src.data_processing.constants import STATION_METADATA
        tz_name = STATION_METADATA.get(station, {}).get("timezone", "UTC")
        try:
            import zoneinfo
            tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc

        if state["last_timestamp_utc"] is not None:
            last_local_date = state["last_timestamp_utc"].astimezone(tz).date()
            pkt_local_date = pkt_time.astimezone(tz).date()
            if pkt_local_date > last_local_date:
                logger.info(
                    "Local calendar rollover for %s (%s -> %s): auto-resetting station block per ADR-0013",
                    station,
                    last_local_date,
                    pkt_local_date,
                )
                state["is_blocked"] = False
                state["last_temp_f"] = None

        # 0. If station is already blocked, reject immediately
        if state["is_blocked"]:
            return SanitizerResult(
                is_valid=False,
                is_late=False,
                station_blocked=True,
                error_reason=f"Station {station} is in STATION_BLOCKED state for today.",
                incident_type="PHYSICAL_TEAR",
                action="CANCEL_ALL_OPEN_ORDERS",
            )

        # 1. Timeliness / Lateness Check (ADR-0013 D2: Missed Window Principle)

        # Check out-of-order timestamp against station's latest recorded timestamp
        if state["last_timestamp_utc"] is not None and pkt_time < state["last_timestamp_utc"]:
            logger.info(
                "Discarding out-of-order packet for %s: pkt_time=%s < last_time=%s",
                station,
                pkt_time,
                state["last_timestamp_utc"],
            )
            return SanitizerResult(
                is_valid=False,
                is_late=True,
                station_blocked=False,
                error_reason=f"Out-of-order observation timestamp {pkt_time} < {state['last_timestamp_utc']}",
            )

        # Check arrival latency against current wall clock time
        if current_wall_time is not None:
            if current_wall_time.tzinfo is None:
                current_wall_time = current_wall_time.replace(tzinfo=timezone.utc)
            latency_sec = (current_wall_time - pkt_time).total_seconds()
            threshold_sec = self.config.stale_packet_threshold_minutes * 60.0
            if latency_sec > threshold_sec:
                logger.info(
                    "Discarding late packet for %s: latency=%.1fs > threshold=%.1fs",
                    station,
                    latency_sec,
                    threshold_sec,
                )
                return SanitizerResult(
                    is_valid=False,
                    is_late=True,
                    station_blocked=False,
                    error_reason=f"Packet arrival late by {latency_sec / 60.0:.1f} minutes > {self.config.stale_packet_threshold_minutes}m",
                )

        # If temperature is None / missing, cannot proceed with extreme updating
        if packet.temp_f is None:
            return SanitizerResult(
                is_valid=False,
                is_late=False,
                station_blocked=False,
                error_reason="Observation packet contains None for temperature.",
            )

        temp_f = packet.temp_f

        # 2. Gate 1: Climatological Absolute Bounds Check (ADR-0013 D1.2)
        if temp_f < self.config.climatological_min_f or temp_f > self.config.climatological_max_f:
            state["is_blocked"] = True
            logger.error(
                "Gate 1 VIOLATION for %s: temp_f=%.2f out of bounds [%.1f, %.1f]",
                station,
                temp_f,
                self.config.climatological_min_f,
                self.config.climatological_max_f,
            )
            return SanitizerResult(
                is_valid=False,
                is_late=False,
                station_blocked=True,
                error_reason=(
                    f"Gate 1 Failed: Temperature {temp_f:.2f}°F outside climatological bounds "
                    f"[{self.config.climatological_min_f}°F, {self.config.climatological_max_f}°F]"
                ),
                incident_type="PHYSICAL_TEAR",
                action="CANCEL_ALL_OPEN_ORDERS",
            )

        # 3. Gate 2: Body vs RMK T-Group Cross-Check (ADR-0013 D1.2)
        if packet.body_temp_c is not None and packet.rmk_temp_c is not None:
            body_f = packet.body_temp_c * 9.0 / 5.0 + 32.0
            rmk_f = packet.rmk_temp_c * 9.0 / 5.0 + 32.0
            delta_body_rmk = abs(body_f - rmk_f)
            if delta_body_rmk > self.config.max_body_rmk_delta_f:
                state["is_blocked"] = True
                logger.error(
                    "Gate 2 VIOLATION for %s: |body_f - rmk_f|=%.2f > %.2f",
                    station,
                    delta_body_rmk,
                    self.config.max_body_rmk_delta_f,
                )
                return SanitizerResult(
                    is_valid=False,
                    is_late=False,
                    station_blocked=True,
                    error_reason=(
                        f"Gate 2 Failed: Body vs RMK divergence |{body_f:.2f} - {rmk_f:.2f}| = "
                        f"{delta_body_rmk:.2f}°F > {self.config.max_body_rmk_delta_f}°F"
                    ),
                    incident_type="PHYSICAL_TEAR",
                    action="CANCEL_ALL_OPEN_ORDERS",
                )

        # 4. Gate 3: Single-Step Jump Check (ADR-0013 D1.2)
        if state["last_temp_f"] is not None:
            delta_step = abs(temp_f - state["last_temp_f"])
            if delta_step > self.config.max_temperature_jump_step_f:
                state["is_blocked"] = True
                logger.error(
                    "Gate 3 VIOLATION for %s: step jump |%.2f - %.2f|=%.2f > %.2f",
                    station,
                    temp_f,
                    state["last_temp_f"],
                    delta_step,
                    self.config.max_temperature_jump_step_f,
                )
                return SanitizerResult(
                    is_valid=False,
                    is_late=False,
                    station_blocked=True,
                    error_reason=(
                        f"Gate 3 Failed: Single-step temperature jump |{temp_f:.2f} - {state['last_temp_f']:.2f}| = "
                        f"{delta_step:.2f}°F > {self.config.max_temperature_jump_step_f}°F"
                    ),
                    incident_type="PHYSICAL_TEAR",
                    action="CANCEL_ALL_OPEN_ORDERS",
                )

        # All gates passed! Update station state
        state["last_temp_f"] = temp_f
        state["last_timestamp_utc"] = pkt_time

        return SanitizerResult(
            is_valid=True,
            is_late=False,
            station_blocked=False,
            error_reason=None,
            incident_type=None,
            action=None,
        )
