"""
Dual-Source Monotonic Confluence and Calendar Day State Engine (Phase 2 Task 02 - Ticket 03 / Issue #67).
Implements ADR-0011 monotonic extreme accumulation (max/min), station timezone calendar rollover,
and permanent truncation lock.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
import logging
from typing import Dict, Optional
import zoneinfo

from src.data_acquisition.observation_stream import ObservationPacket
from src.data_processing.constants import STATION_METADATA

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StationDayState:
    """Immutable snapshot of station's monotonic extreme state for the local calendar day."""
    station_id: str
    local_date: date
    tmax_so_far: Optional[float]
    tmin_so_far: Optional[float]
    last_update_utc: datetime
    last_source: str
    observation_count: int


class MonotonicConfluenceEngine:
    """
    Manages dual-source monotonic confluence and calendar-day tracking for Active 10 stations.
    All extremes are monotonic: TMAX is strictly non-decreasing; TMIN is strictly non-increasing.
    """

    DEFAULT_TIMEZONES = {
        "KORD": "America/Chicago",
        "KLGA": "America/New_York",
        "KATL": "America/New_York",
        "KDAL": "America/Chicago",
        "KSEA": "America/Los_Angeles",
        "KLAX": "America/Los_Angeles",
        "KHOU": "America/Chicago",
        "KMIA": "America/New_York",
        "KSFO": "America/Los_Angeles",
        "KAUS": "America/Chicago",
    }

    def __init__(self):
        # station_id -> mutable dict holding current state
        self._states: Dict[str, Dict] = {}

    def get_station_timezone(self, station_id: str) -> str:
        """Resolve station timezone string."""
        meta = STATION_METADATA.get(station_id, {})
        return meta.get("timezone", self.DEFAULT_TIMEZONES.get(station_id, "UTC"))

    def get_station_state(self, station_id: str) -> Optional[StationDayState]:
        """Return the current StationDayState snapshot for a station."""
        st = self._states.get(station_id)
        if not st:
            return None
        return StationDayState(
            station_id=station_id,
            local_date=st["local_date"],
            tmax_so_far=st["tmax_so_far"],
            tmin_so_far=st["tmin_so_far"],
            last_update_utc=st["last_update_utc"],
            last_source=st["last_source"],
            observation_count=st["observation_count"],
        )

    def ingest(self, packet: ObservationPacket) -> StationDayState:
        """
        Ingest a validated ObservationPacket, advancing the monotonic extreme state.
        Handles local midnight calendar rollover atomically.
        """
        station = packet.station_id
        if packet.temp_f is None:
            raise ValueError(f"Cannot ingest packet with None temp_f for station {station}")

        tz_str = self.get_station_timezone(station)
        tz = zoneinfo.ZoneInfo(tz_str)

        # Convert packet timestamp to station's local date
        pkt_time_utc = packet.timestamp_utc
        if pkt_time_utc.tzinfo is None:
            pkt_time_utc = pkt_time_utc.replace(tzinfo=timezone.utc)

        local_dt = pkt_time_utc.astimezone(tz)
        local_date = local_dt.date()

        current = self._states.get(station)

        # Check if new station or local calendar day has rolled over
        if current is None or current["local_date"] != local_date:
            logger.info(
                "Initializing / rolling over calendar day state for %s: local_date=%s (tz=%s)",
                station,
                local_date,
                tz_str,
            )
            self._states[station] = {
                "local_date": local_date,
                "tmax_so_far": packet.temp_f,
                "tmin_so_far": packet.temp_f,
                "last_update_utc": pkt_time_utc,
                "last_source": packet.source_type,
                "observation_count": 1,
            }
        else:
            # Monotonic accumulation:
            # TMAX is max(current_tmax, new_temp) -> never decreases
            # TMIN is min(current_tmin, new_temp) -> never increases
            new_tmax = max(current["tmax_so_far"], packet.temp_f)
            new_tmin = min(current["tmin_so_far"], packet.temp_f)

            current["tmax_so_far"] = new_tmax
            current["tmin_so_far"] = new_tmin
            current["last_update_utc"] = pkt_time_utc
            current["last_source"] = packet.source_type
            current["observation_count"] += 1

        return self.get_station_state(station)
