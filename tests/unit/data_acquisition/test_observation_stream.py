"""
Unit tests for ObservationStreamAdapter and ObservationPacket (Phase 2 Task 02 - Ticket 01 / Issue #65).
Tests IEM METAR/SPECI and NWS WRH raw message ingestion, high-precision decoding, and UTC normalization.
"""

from datetime import datetime, timezone
import pytest

from src.data_acquisition.observation_stream import (
    ObservationPacket,
    ObservationStreamAdapter,
)


class TestObservationStreamAdapter:
    """Test suite for ObservationStreamAdapter ingestion contract."""

    @pytest.fixture
    def adapter(self):
        return ObservationStreamAdapter()

    def test_parse_routine_metar_with_high_res_rmk(self, adapter):
        """Standard METAR with 0.1°C precision T-group in remarks."""
        raw = "METAR KORD 211851Z 04010KT 10SM BKN045 22/14 A3005 RMK AO2 SLP176 T02170139 51008"
        ts = datetime(2026, 9, 21, 18, 51, tzinfo=timezone.utc)
        packet = adapter.parse_iem_metar(station_id="KORD", raw_metar=raw, timestamp_utc=ts)

        assert isinstance(packet, ObservationPacket)
        assert packet.station_id == "KORD"
        assert packet.timestamp_utc == ts
        assert packet.source_type == "iem_metar"
        assert packet.is_speci is False
        assert packet.body_temp_c == 22.0
        assert packet.rmk_temp_c == 21.7
        # Effective temperature prefers RMK 0.1°C precision
        assert packet.temp_c == 21.7
        assert packet.temp_f == pytest.approx(21.7 * 9.0 / 5.0 + 32.0, abs=1e-4)

    def test_parse_speci_metar_with_subzero_temp(self, adapter):
        """SPECI report with sub-zero temperature (M prefix and T1 code)."""
        raw = "SPECI KORD 211915Z 36015G25KT 3SM -SN BKN015 M05/M09 A2990 RMK AO2 PK WND 36025/1912 T10521089"
        ts = datetime(2026, 1, 15, 19, 15, tzinfo=timezone.utc)
        packet = adapter.parse_iem_metar(station_id="KORD", raw_metar=raw, timestamp_utc=ts)

        assert packet.is_speci is True
        assert packet.source_type == "iem_speci"
        assert packet.body_temp_c == -5.0
        assert packet.rmk_temp_c == -5.2
        assert packet.temp_c == -5.2
        assert packet.temp_f == pytest.approx(-5.2 * 9.0 / 5.0 + 32.0, abs=1e-4)

    def test_parse_metar_without_rmk_t_group_falls_back_to_body(self, adapter):
        """METAR without RMK T-group falls back cleanly to main body integer temperature."""
        raw = "METAR KLGA 211200Z 18008KT 10SM CLR 18/10 A3012 RMK AO2 SLP195"
        ts = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        packet = adapter.parse_iem_metar(station_id="KLGA", raw_metar=raw, timestamp_utc=ts)

        assert packet.is_speci is False
        assert packet.body_temp_c == 18.0
        assert packet.rmk_temp_c is None
        assert packet.temp_c == 18.0
        assert packet.temp_f == pytest.approx(18.0 * 9.0 / 5.0 + 32.0, abs=1e-4)

    def test_parse_nws_wrh_record(self, adapter):
        """Parse NWS WRH observation dict into standardized ObservationPacket."""
        record = {
            "station_id": "KATL",
            "date_time": "2026-09-21T14:30:00Z",
            "air_temp_set_1": 77.0,  # Fahrenheit in English probe
        }
        packet = adapter.parse_nws_wrh_dict(station_id="KATL", record=record)

        assert packet.station_id == "KATL"
        assert packet.source_type == "nws_wrh"
        assert packet.is_speci is False
        assert packet.temp_f == 77.0
        assert packet.temp_c == pytest.approx((77.0 - 32.0) * 5.0 / 9.0, abs=1e-4)
        assert packet.timestamp_utc == datetime(2026, 9, 21, 14, 30, tzinfo=timezone.utc)

    def test_empty_or_malformed_metar_returns_none_temps(self, adapter):
        """Malformed or unparseable METAR produces packet with None temps."""
        raw = "GARBAGE DATA NO TEMPERATURE RECORDED"
        ts = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        packet = adapter.parse_iem_metar(station_id="KMIA", raw_metar=raw, timestamp_utc=ts)

        assert packet.station_id == "KMIA"
        assert packet.temp_c is None
        assert packet.temp_f is None
        assert packet.body_temp_c is None
        assert packet.rmk_temp_c is None

    def test_parse_observation_record(self, adapter):
        """Parse ObservationRecord instance directly into ObservationPacket."""
        from src.data_acquisition.observation_adapter import ObservationRecord

        rec = ObservationRecord(
            timestamp=datetime(2026, 9, 21, 13, 30, tzinfo=timezone.utc),
            temp_c=25.0,
            raw_metar="METAR KSEA 211330Z 18005KT 10SM CLR 25/12 A3015 RMK AO2 T02500120",
            metadata={"extreme_remarks": {"temp_high_res": 25.0}},
        )
        packet = adapter.parse_observation_record(station_id="KSEA", record=rec)

        assert packet.station_id == "KSEA"
        assert packet.temp_c == 25.0
        assert packet.temp_f == 77.0
        assert packet.source_type == "nws_wrh"
        assert packet.is_speci is False
