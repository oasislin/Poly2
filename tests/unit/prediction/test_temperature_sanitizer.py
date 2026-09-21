"""
Unit tests for TemperatureSanitizer (Phase 2 Task 02 - Ticket 02 / Issue #66).
Tests three pure-temperature sanity gates, missed window lateness discard, and Fail-Closed security circuit breaker.
"""

from datetime import datetime, timezone, timedelta
import pytest

from src.data_acquisition.observation_stream import ObservationPacket
from src.prediction.temperature_sanitizer import (
    SanitizerConfig,
    SanitizerResult,
    TemperatureSanitizer,
)


class TestTemperatureSanitizer:
    """Test suite for pure-temperature sanity gates and fail-closed circuit breaker."""

    @pytest.fixture
    def sanitizer(self):
        config = SanitizerConfig(
            climatological_min_f=-40.0,
            climatological_max_f=135.0,
            max_body_rmk_delta_f=1.8,
            max_temperature_jump_step_f=15.0,
            stale_packet_threshold_minutes=15.0,
        )
        return TemperatureSanitizer(config=config)

    def _make_packet(
        self,
        temp_f: float,
        timestamp_utc: datetime,
        body_temp_f: float = None,
        rmk_temp_f: float = None,
        station_id: str = "KORD",
        is_speci: bool = False,
    ) -> ObservationPacket:
        temp_c = (temp_f - 32.0) * 5.0 / 9.0
        body_c = (body_temp_f - 32.0) * 5.0 / 9.0 if body_temp_f is not None else temp_c
        rmk_c = (rmk_temp_f - 32.0) * 5.0 / 9.0 if rmk_temp_f is not None else temp_c
        return ObservationPacket(
            station_id=station_id,
            timestamp_utc=timestamp_utc,
            temp_c=temp_c,
            temp_f=temp_f,
            source_type="iem_speci" if is_speci else "iem_metar",
            is_speci=is_speci,
            body_temp_c=body_c,
            rmk_temp_c=rmk_c,
        )

    def test_healthy_packet_passes_all_gates(self, sanitizer):
        """Normal, physically reasonable packet passes validation cleanly."""
        t0 = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)
        pkt = self._make_packet(temp_f=72.5, timestamp_utc=t0)
        verdict = sanitizer.validate(pkt, current_wall_time=t0 + timedelta(minutes=2))

        assert verdict.is_valid is True
        assert verdict.is_late is False
        assert verdict.station_blocked is False
        assert verdict.incident_type is None

    def test_gate1_out_of_climatological_bounds_triggers_tear(self, sanitizer):
        """Gate 1: Temperature out of [-40°F, 135°F] triggers physical tear and block."""
        t0 = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)
        pkt_hot = self._make_packet(temp_f=142.0, timestamp_utc=t0)
        verdict_hot = sanitizer.validate(pkt_hot, current_wall_time=t0)

        assert verdict_hot.is_valid is False
        assert verdict_hot.station_blocked is True
        assert verdict_hot.incident_type == "PHYSICAL_TEAR"
        assert "Gate 1" in verdict_hot.error_reason

        pkt_cold = self._make_packet(temp_f=-55.0, timestamp_utc=t0)
        verdict_cold = sanitizer.validate(pkt_cold, current_wall_time=t0)
        assert verdict_cold.is_valid is False
        assert verdict_cold.station_blocked is True
        assert verdict_cold.incident_type == "PHYSICAL_TEAR"

    def test_gate2_body_vs_rmk_divergence_triggers_tear(self, sanitizer):
        """Gate 2: Divergence between body and RMK > 1.8°F triggers tear."""
        t0 = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)
        # Body = 60°F (15.56°C), RMK = 65°F (18.33°C) -> delta = 5.0°F > 1.8°F
        pkt = self._make_packet(temp_f=65.0, timestamp_utc=t0, body_temp_f=60.0, rmk_temp_f=65.0)
        verdict = sanitizer.validate(pkt, current_wall_time=t0)

        assert verdict.is_valid is False
        assert verdict.station_blocked is True
        assert verdict.incident_type == "PHYSICAL_TEAR"
        assert "Gate 2" in verdict.error_reason

    def test_gate3_single_step_jump_greater_than_15f_triggers_tear(self, sanitizer):
        """Gate 3: Jump > 15.0°F between consecutive observations triggers tear."""
        t0 = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)
        pkt1 = self._make_packet(temp_f=70.0, timestamp_utc=t0)
        v1 = sanitizer.validate(pkt1, current_wall_time=t0)
        assert v1.is_valid is True

        # Next observation 5 mins later jumps from 70°F to 88°F (Delta = +18°F > 15.0°F)
        t1 = t0 + timedelta(minutes=5)
        pkt2 = self._make_packet(temp_f=88.0, timestamp_utc=t1)
        v2 = sanitizer.validate(pkt2, current_wall_time=t1)

        assert v2.is_valid is False
        assert v2.station_blocked is True
        assert v2.incident_type == "PHYSICAL_TEAR"
        assert "Gate 3" in v2.error_reason

    def test_missed_window_arrival_delay_discards_without_tear(self, sanitizer):
        """Packet arriving with wall-clock latency > 15 mins is marked late and discarded without tear."""
        t0 = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)
        pkt = self._make_packet(temp_f=75.0, timestamp_utc=t0)
        # Arrives at 14:20 (20 minutes late)
        verdict = sanitizer.validate(pkt, current_wall_time=t0 + timedelta(minutes=20))

        assert verdict.is_valid is False
        assert verdict.is_late is True
        assert verdict.station_blocked is False
        assert verdict.incident_type is None
        assert "late" in verdict.error_reason.lower()

    def test_out_of_order_timestamp_is_discarded_as_late(self, sanitizer):
        """Packet with timestamp earlier than already-processed latest timestamp is discarded."""
        t0 = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)
        pkt1 = self._make_packet(temp_f=75.0, timestamp_utc=t0)
        assert sanitizer.validate(pkt1, current_wall_time=t0).is_valid is True

        # Out-of-order packet timestamped 13:55 arrives later
        t_early = t0 - timedelta(minutes=5)
        pkt_early = self._make_packet(temp_f=74.5, timestamp_utc=t_early)
        verdict = sanitizer.validate(pkt_early, current_wall_time=t0 + timedelta(minutes=1))

        assert verdict.is_valid is False
        assert verdict.is_late is True
        assert verdict.station_blocked is False

    def test_auto_reset_station_block_on_local_midnight_rollover(self, sanitizer):
        """Station blocked on day 1 automatically resets when advancing to day 2 (ADR-0013)."""
        # Block station on Day 1 (2026-09-21 15:00 UTC) with jump > 15°F
        t0 = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)
        sanitizer.validate(self._make_packet(temp_f=70.0, timestamp_utc=t0))
        t0_jump = t0 + timedelta(minutes=5)
        v_blocked = sanitizer.validate(self._make_packet(temp_f=90.0, timestamp_utc=t0_jump))
        assert v_blocked.station_blocked is True
        assert sanitizer.is_station_blocked("KORD") is True

        # Next day packet arrives (2026-09-22 12:00 UTC)
        t_next_day = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
        v_next = sanitizer.validate(self._make_packet(temp_f=68.0, timestamp_utc=t_next_day), current_wall_time=t_next_day)

        assert v_next.is_valid is True
        assert v_next.station_blocked is False
        assert sanitizer.is_station_blocked("KORD") is False
