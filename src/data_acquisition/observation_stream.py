"""
Observation Stream Ingestion Adapter and Standardized Data Contract (Phase 2 Task 02 - Ticket 01 / Issue #65).
Parses real-time IEM METAR/SPECI raw messages and NWS WRH observation streams into ObservationPacket.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional
import zoneinfo

from src.data_acquisition.iem_metar_collector import (
    parse_metar_dry_bulb,
    parse_metar_extreme_remarks,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ObservationPacket:
    """
    Immutable standardized single observation packet ingested from stream or polling.
    """
    station_id: str
    timestamp_utc: datetime
    temp_c: Optional[float]
    temp_f: Optional[float]
    source_type: str  # "iem_metar", "iem_speci", "nws_wrh"
    is_speci: bool
    raw_text: Optional[str] = None
    body_temp_c: Optional[float] = None
    rmk_temp_c: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ObservationStreamAdapter:
    """
    Standardized adapter for parsing and normalizing real-time observation feeds.
    """

    @staticmethod
    def _c_to_f(temp_c: Optional[float]) -> Optional[float]:
        if temp_c is None:
            return None
        return float(temp_c * 9.0 / 5.0 + 32.0)

    @staticmethod
    def _f_to_c(temp_f: Optional[float]) -> Optional[float]:
        if temp_f is None:
            return None
        return float((temp_f - 32.0) * 5.0 / 9.0)

    def parse_iem_metar(
        self,
        station_id: str,
        raw_metar: str,
        timestamp_utc: datetime,
        report_type: Optional[str] = None,
    ) -> ObservationPacket:
        """
        Parse raw IEM METAR/SPECI string into an ObservationPacket.
        Prioritizes 0.1°C precision RMK T-group over main body integer Celsius.
        """
        if timestamp_utc.tzinfo is None:
            timestamp_utc = timestamp_utc.replace(tzinfo=timezone.utc)
        else:
            timestamp_utc = timestamp_utc.astimezone(timezone.utc)

        is_speci = False
        raw_stripped = raw_metar.strip() if raw_metar else ""
        if raw_stripped.startswith("SPECI") or report_type in ("2", "SPECI"):
            is_speci = True

        source_type = "iem_speci" if is_speci else "iem_metar"

        body_temp = parse_metar_dry_bulb(raw_stripped)
        rmk_dict = parse_metar_extreme_remarks(raw_stripped)
        rmk_temp = rmk_dict.get("temp_high_res")

        # Prioritize 0.1°C RMK T group, fallback to body integer
        effective_temp_c = rmk_temp if rmk_temp is not None else body_temp
        effective_temp_f = self._c_to_f(effective_temp_c)

        return ObservationPacket(
            station_id=station_id,
            timestamp_utc=timestamp_utc,
            temp_c=effective_temp_c,
            temp_f=effective_temp_f,
            source_type=source_type,
            is_speci=is_speci,
            raw_text=raw_metar,
            body_temp_c=body_temp,
            rmk_temp_c=rmk_temp,
            metadata={"extreme_remarks": rmk_dict},
        )

    def parse_nws_wrh_dict(
        self,
        station_id: str,
        record: Dict[str, Any],
    ) -> ObservationPacket:
        """
        Parse NWS WRH timeseries observation record dictionary into ObservationPacket.
        """
        raw_ts = record.get("date_time")
        if isinstance(raw_ts, str):
            # Parse ISO string e.g. "2026-09-21T14:30:00Z"
            ts_str = raw_ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts_str)
        elif isinstance(raw_ts, datetime):
            dt = raw_ts
        else:
            raise ValueError(f"Invalid date_time in record: {raw_ts}")

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        # Temp could be in air_temp_set_1 (Fahrenheit) or air_temp (Celsius/Fahrenheit)
        temp_f = record.get("air_temp_set_1")
        if temp_f is None:
            temp_f = record.get("temp_f")

        temp_c = record.get("temp_c")
        if temp_f is not None:
            temp_f = float(temp_f)
            temp_c = self._f_to_c(temp_f)
        elif temp_c is not None:
            temp_c = float(temp_c)
            temp_f = self._c_to_f(temp_c)

        return ObservationPacket(
            station_id=station_id,
            timestamp_utc=dt,
            temp_c=temp_c,
            temp_f=temp_f,
            source_type="nws_wrh",
            is_speci=False,
            raw_text=str(record),
            body_temp_c=temp_c,
            rmk_temp_c=None,
            metadata=record,
        )

    def parse_observation_record(
        self,
        station_id: str,
        record: Any,
        source_type: str = "nws_wrh",
    ) -> ObservationPacket:
        """Convert an ObservationRecord object into an ObservationPacket."""
        dt = record.timestamp
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        temp_c = record.temp_c
        temp_f = record.temp_f
        if temp_f is None and temp_c is not None:
            temp_f = self._c_to_f(temp_c)
        elif temp_c is None and temp_f is not None:
            temp_c = self._f_to_c(temp_f)

        raw_metar = getattr(record, "raw_metar", None)
        is_speci = bool(raw_metar and raw_metar.strip().startswith("SPECI"))

        return ObservationPacket(
            station_id=station_id,
            timestamp_utc=dt,
            temp_c=temp_c,
            temp_f=temp_f,
            source_type=source_type,
            is_speci=is_speci,
            raw_text=raw_metar or str(record),
            body_temp_c=temp_c,
            rmk_temp_c=getattr(record, "metadata", {}).get("extreme_remarks", {}).get("temp_high_res"),
            metadata=getattr(record, "metadata", {}),
        )
