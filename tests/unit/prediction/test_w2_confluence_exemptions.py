"""
tests/unit/prediction/test_w2_confluence_exemptions.py:
Unit test suite for Phase 2 W2 Rev.1.1 Dual-Source Confluence Contracts:
- R-W2-1: NWS WRH late-arrival extreme exemption (Option a) and WRH_LATE_ABSORB audit tagging.
- R-W2-2: Cross-source divergence monitoring (|Delta T| > 2.0°F within 5m window) and CROSS_SOURCE_DIVERGENCE tagging.
"""

from datetime import datetime, timezone, timedelta
import pytest

from src.data_acquisition.observation_stream import (
    ObservationPacket,
    ObservationStreamAdapter,
)
from src.prediction.monotonic_confluence import MonotonicConfluenceEngine
from src.prediction.temperature_sanitizer import (
    SanitizerConfig,
    TemperatureSanitizer,
)
from src.pipeline.stream_confluence_pipeline import (
    StreamConfluencePipeline,
    PipelineProcessResult,
)
from src.risk.stream_watchdog import StreamRiskWatchdog


@pytest.fixture
def pipeline():
    return StreamConfluencePipeline(
        adapter=ObservationStreamAdapter(),
        sanitizer=TemperatureSanitizer(SanitizerConfig()),
        confluence=MonotonicConfluenceEngine(),
        watchdog=StreamRiskWatchdog(),
    )


class TestW2ConfluenceExemptions:
    """Test suite for R-W2-1 and R-W2-2 specification requirements."""

    def test_wrh_late_arrival_exemption_and_audit_tag(self, pipeline):
        """
        R-W2-1 (Option a):
        NWS WRH late-arriving packet (>15m arrival latency) MUST be exempt from discard,
        MUST update monotonic extreme state, and MUST carry WRH_LATE_ABSORB audit tag.
        """
        station = "KORD"
        obs_time = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)
        # WRH packet arrives 25 minutes late (>15m threshold) with 75.0°F
        wall_time = obs_time + timedelta(minutes=25)

        packet = ObservationPacket(
            station_id=station,
            timestamp_utc=obs_time,
            temp_c=23.8889,
            temp_f=75.0,
            source_type="nws_wrh",
            is_speci=False,
        )

        res: PipelineProcessResult = pipeline.process_packet(packet, arrival_wall_time=wall_time)

        # Assertions
        assert res.sanitizer_result.is_valid is True
        assert res.sanitizer_result.is_late is True
        assert res.sanitizer_result.is_wrh_late_exempt is True
        assert res.confluence_updated is True
        assert res.confluence_state is not None
        assert res.confluence_state.tmax_so_far == pytest.approx(75.0, abs=1e-4)
        assert "WRH_LATE_ABSORB" in res.audit_tags

    def test_wrh_out_of_order_timestamp_exemption(self, pipeline):
        """
        R-W2-1 (Option a):
        NWS WRH packet with timestamp earlier than latest recorded timestamp (out-of-order)
        MUST be exempt from discard and successfully advance the extreme.
        """
        station = "KMIA"
        t0 = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)
        t_earlier = datetime(2026, 9, 21, 13, 30, tzinfo=timezone.utc)

        # 1. First inject IEM METAR at 14:00 UTC with 82.0°F
        pkt1 = ObservationPacket(
            station_id=station,
            timestamp_utc=t0,
            temp_c=27.7778,
            temp_f=82.0,
            source_type="iem_metar",
            is_speci=False,
        )
        res1 = pipeline.process_packet(pkt1, arrival_wall_time=t0 + timedelta(minutes=1))
        assert res1.confluence_updated is True
        assert res1.confluence_state.tmax_so_far == pytest.approx(82.0, abs=1e-4)

        # 2. Later inject delayed NWS WRH record timestamped at 13:30 UTC with 84.5°F (higher extreme!)
        pkt_wrh = ObservationPacket(
            station_id=station,
            timestamp_utc=t_earlier,
            temp_c=29.1667,
            temp_f=84.5,
            source_type="nws_wrh",
            is_speci=False,
        )
        res_wrh = pipeline.process_packet(pkt_wrh, arrival_wall_time=t0 + timedelta(minutes=5))

        # Assertions: WRH is out-of-order, but exempt from discard and monotonic max updated to 84.5°F
        assert res_wrh.sanitizer_result.is_valid is True
        assert res_wrh.sanitizer_result.is_wrh_late_exempt is True
        assert res_wrh.confluence_updated is True
        assert res_wrh.confluence_state.tmax_so_far == pytest.approx(84.5, abs=1e-4)
        assert "WRH_LATE_ABSORB" in res_wrh.audit_tags

    def test_regular_iem_metar_late_is_not_exempt(self, pipeline):
        """
        Confirm that regular IEM METAR late-arriving packets are NOT exempt and ARE discarded.
        """
        station = "KORD"
        obs_time = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)
        wall_time = obs_time + timedelta(minutes=25)

        pkt_iem = ObservationPacket(
            station_id=station,
            timestamp_utc=obs_time,
            temp_c=20.0,
            temp_f=68.0,
            source_type="iem_metar",
            is_speci=False,
        )

        res = pipeline.process_packet(pkt_iem, arrival_wall_time=wall_time)
        assert res.sanitizer_result.is_valid is False
        assert res.sanitizer_result.is_late is True
        assert res.sanitizer_result.is_wrh_late_exempt is False
        assert res.confluence_updated is False
        assert "WRH_LATE_ABSORB" not in res.audit_tags

    def test_cross_source_divergence_above_2f_triggers_tag(self, pipeline):
        """
        R-W2-2:
        When IEM and WRH observations within 5 minutes diverge by > 2.0°F,
        CROSS_SOURCE_DIVERGENCE tag MUST be present, and trading MUST NOT be blocked.
        """
        station = "KORD"
        t0 = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)

        # 1. Ingest IEM METAR reporting 70.0°F at 15:00 UTC
        pkt_iem = ObservationPacket(
            station_id=station,
            timestamp_utc=t0,
            temp_c=21.1111,
            temp_f=70.0,
            source_type="iem_metar",
            is_speci=False,
        )
        res_iem = pipeline.process_packet(pkt_iem, arrival_wall_time=t0 + timedelta(minutes=1))
        assert "CROSS_SOURCE_DIVERGENCE" not in res_iem.audit_tags

        # 2. Ingest NWS WRH reporting 72.5°F at 15:02 UTC (Delta = 2.5°F > 2.0°F)
        t_wrh = t0 + timedelta(minutes=2)
        pkt_wrh = ObservationPacket(
            station_id=station,
            timestamp_utc=t_wrh,
            temp_c=22.5,
            temp_f=72.5,
            source_type="nws_wrh",
            is_speci=False,
        )
        res_wrh = pipeline.process_packet(pkt_wrh, arrival_wall_time=t_wrh + timedelta(minutes=1))

        # Assertions
        assert "CROSS_SOURCE_DIVERGENCE" in res_wrh.audit_tags
        # Must NOT block trading
        assert res_wrh.sanitizer_result.station_blocked is False
        assert res_wrh.confluence_updated is True
        assert res_wrh.confluence_state.tmax_so_far == pytest.approx(72.5, abs=1e-4)

    def test_cross_source_normal_divergence_within_2f_no_tag(self, pipeline):
        """
        R-W2-2:
        When IEM and WRH observations within 5 minutes diverge by <= 2.0°F (e.g. 0.4°F rounding diff),
        CROSS_SOURCE_DIVERGENCE tag MUST NOT be emitted.
        """
        station = "KMIA"
        t0 = datetime(2026, 9, 21, 16, 0, tzinfo=timezone.utc)

        pkt_iem = ObservationPacket(
            station_id=station,
            timestamp_utc=t0,
            temp_c=26.6667,
            temp_f=80.0,
            source_type="iem_metar",
            is_speci=False,
        )
        pipeline.process_packet(pkt_iem, arrival_wall_time=t0 + timedelta(minutes=1))

        # WRH reports 80.4°F (delta = 0.4°F <= 2.0°F)
        pkt_wrh = ObservationPacket(
            station_id=station,
            timestamp_utc=t0 + timedelta(minutes=1),
            temp_c=26.8889,
            temp_f=80.4,
            source_type="nws_wrh",
            is_speci=False,
        )
        res_wrh = pipeline.process_packet(pkt_wrh, arrival_wall_time=t0 + timedelta(minutes=2))

        assert "CROSS_SOURCE_DIVERGENCE" not in res_wrh.audit_tags
        assert res_wrh.confluence_updated is True
