"""
Stream Confluence Pipeline: End-to-End Ingestion, Sanitization, Monotonic Tracking, and Risk Evaluation (Phase 2 Task 02 - Ticket 05 / Issue #69).
Coordinates ObservationStreamAdapter, TemperatureSanitizer, MonotonicConfluenceEngine, and StreamRiskWatchdog.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional

from src.data_acquisition.observation_stream import (
    ObservationPacket,
    ObservationStreamAdapter,
)
from src.prediction.monotonic_confluence import (
    MonotonicConfluenceEngine,
    StationDayState,
)
from src.prediction.temperature_sanitizer import (
    SanitizerResult,
    TemperatureSanitizer,
)
from src.risk.stream_watchdog import (
    RiskStatus,
    StreamRiskWatchdog,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineProcessResult:
    """Comprehensive result of processing a single raw observation feed entry."""
    packet: ObservationPacket
    sanitizer_result: SanitizerResult
    confluence_state: Optional[StationDayState]
    confluence_updated: bool
    risk_status: RiskStatus


class StreamConfluencePipeline:
    """
    Unified pipeline processor for real-time observation feeds.
    """

    def __init__(
        self,
        adapter: Optional[ObservationStreamAdapter] = None,
        sanitizer: Optional[TemperatureSanitizer] = None,
        confluence: Optional[MonotonicConfluenceEngine] = None,
        watchdog: Optional[StreamRiskWatchdog] = None,
    ):
        self.adapter = adapter or ObservationStreamAdapter()
        self.sanitizer = sanitizer or TemperatureSanitizer()
        self.confluence = confluence or MonotonicConfluenceEngine()
        self.watchdog = watchdog or StreamRiskWatchdog()

    def process_packet(
        self,
        packet: ObservationPacket,
        arrival_wall_time: Optional[datetime] = None,
    ) -> PipelineProcessResult:
        """
        Process an already parsed ObservationPacket through validation, confluence, and watchdog.
        """
        wall_now = arrival_wall_time or datetime.now(timezone.utc)
        station = packet.station_id

        # 1. Record packet arrival in watchdog
        self.watchdog.record_packet(packet, arrival_wall_time=wall_now)

        # 2. Run pure-temperature sanity gates and timeliness checks
        sanitizer_res = self.sanitizer.validate(packet, current_wall_time=wall_now)

        confluence_state = None
        confluence_updated = False

        # 3. If valid, update monotonic confluence state
        if sanitizer_res.is_valid and packet.temp_f is not None:
            confluence_state = self.confluence.ingest(packet)
            confluence_updated = True
        else:
            # Query existing state without updating
            confluence_state = self.confluence.get_station_state(station)

        # 4. Evaluate stream risk status
        risk_status = self.watchdog.evaluate(station, current_wall_time=wall_now)

        return PipelineProcessResult(
            packet=packet,
            sanitizer_result=sanitizer_res,
            confluence_state=confluence_state,
            confluence_updated=confluence_updated,
            risk_status=risk_status,
        )

    def process_raw_metar(
        self,
        station_id: str,
        raw_metar: str,
        timestamp_utc: datetime,
        arrival_wall_time: Optional[datetime] = None,
        report_type: Optional[str] = None,
    ) -> PipelineProcessResult:
        """Parse raw METAR/SPECI string and process through full pipeline."""
        packet = self.adapter.parse_iem_metar(
            station_id=station_id,
            raw_metar=raw_metar,
            timestamp_utc=timestamp_utc,
            report_type=report_type,
        )
        return self.process_packet(packet, arrival_wall_time=arrival_wall_time)

    def process_raw_nws_dict(
        self,
        station_id: str,
        record: Dict[str, Any],
        arrival_wall_time: Optional[datetime] = None,
    ) -> PipelineProcessResult:
        """Parse NWS WRH record dictionary and process through full pipeline."""
        packet = self.adapter.parse_nws_wrh_dict(station_id=station_id, record=record)
        return self.process_packet(packet, arrival_wall_time=arrival_wall_time)
