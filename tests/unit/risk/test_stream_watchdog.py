"""
Unit tests for StreamRiskWatchdog (Phase 2 Task 02 - Ticket 04 / Issue #68).
Tests two-tier tiered risk boundaries (15m arrival heartbeat, 35m physical staleness),
CancelAll protocol, and 3-frame hysteresis recovery.
"""

from datetime import datetime, timezone, timedelta
import pytest

from src.data_acquisition.observation_stream import ObservationPacket
from src.risk.stream_watchdog import (
    RiskLevel,
    RiskStatus,
    StreamRiskWatchdog,
    WatchdogConfig,
)


class TestStreamRiskWatchdog:
    """Test suite for StreamRiskWatchdog two-tier defense and hysteresis recovery."""

    @pytest.fixture
    def watchdog(self):
        cfg = WatchdogConfig(
            arrival_heartbeat_timeout_minutes=15.0,
            physical_staleness_timeout_minutes=35.0,
            recovery_staleness_threshold_minutes=20.0,
            consecutive_healthy_frames_required=3,
        )
        return StreamRiskWatchdog(config=cfg)

    def _make_packet(
        self,
        station_id: str,
        timestamp_utc: datetime,
        temp_f: float = 70.0,
    ) -> ObservationPacket:
        return ObservationPacket(
            station_id=station_id,
            timestamp_utc=timestamp_utc,
            temp_c=(temp_f - 32.0) * 5.0 / 9.0,
            temp_f=temp_f,
            source_type="iem_metar",
            is_speci=False,
        )

    def test_healthy_station_evaluation(self, watchdog):
        """Station receiving regular packets within 5 minutes is HEALTHY."""
        t0 = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)
        pkt = self._make_packet("KORD", timestamp_utc=t0)
        watchdog.record_packet(pkt, arrival_wall_time=t0 + timedelta(seconds=30))

        status = watchdog.evaluate("KORD", current_wall_time=t0 + timedelta(minutes=5))
        assert status.level == RiskLevel.HEALTHY
        assert status.cancel_all_quotes is False
        assert status.safe_mode is False

    def test_tier1_arrival_heartbeat_timeout_at_15m_triggers_cancel_all(self, watchdog):
        """No packet arrival for > 15m triggers WARNING and CancelAll quotes protocol."""
        t0 = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)
        pkt = self._make_packet("KORD", timestamp_utc=t0)
        watchdog.record_packet(pkt, arrival_wall_time=t0)

        # At 14:16 (16 minutes since last arrival), triggers Tier 1 WARNING
        t_eval = t0 + timedelta(minutes=16)
        status = watchdog.evaluate("KORD", current_wall_time=t_eval)

        assert status.level == RiskLevel.WARNING
        assert status.cancel_all_quotes is True
        assert status.safe_mode is False
        assert "arrival heartbeat" in status.reason.lower()

    def test_tier2_physical_staleness_at_35m_triggers_safe_mode(self, watchdog):
        """Observation age > 35m triggers DATA_STALENESS (ERROR) and SAFE_MODE."""
        t0 = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)
        pkt = self._make_packet("KLGA", timestamp_utc=t0)
        watchdog.record_packet(pkt, arrival_wall_time=t0)

        # At 14:36 (36 minutes physical staleness)
        t_eval = t0 + timedelta(minutes=36)
        status = watchdog.evaluate("KLGA", current_wall_time=t_eval)

        assert status.level == RiskLevel.DATA_STALENESS
        assert status.cancel_all_quotes is True
        assert status.safe_mode is True
        assert "physical staleness" in status.reason.lower()

    def test_hysteresis_recovery_requires_3_consecutive_frames(self, watchdog):
        """Recovering from WARNING/SAFE_MODE requires staleness < 20m AND 3 consecutive frames."""
        t0 = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)
        pkt0 = self._make_packet("KATL", timestamp_utc=t0)
        watchdog.record_packet(pkt0, arrival_wall_time=t0)

        # Cause station to enter WARNING at 14:16
        t_warn = t0 + timedelta(minutes=16)
        assert watchdog.evaluate("KATL", current_wall_time=t_warn).level == RiskLevel.WARNING

        # Frame 1 received at 14:17 with fresh timestamp 14:16
        t_pkt1 = t0 + timedelta(minutes=16)
        t_arr1 = t0 + timedelta(minutes=17)
        pkt1 = self._make_packet("KATL", timestamp_utc=t_pkt1)
        watchdog.record_packet(pkt1, arrival_wall_time=t_arr1)

        # Still in WARNING (only 1 consecutive healthy frame, needs 3)
        st1 = watchdog.evaluate("KATL", current_wall_time=t_arr1)
        assert st1.level == RiskLevel.WARNING

        # Frame 2 received at 14:22
        t_pkt2 = t0 + timedelta(minutes=21)
        t_arr2 = t0 + timedelta(minutes=22)
        pkt2 = self._make_packet("KATL", timestamp_utc=t_pkt2)
        watchdog.record_packet(pkt2, arrival_wall_time=t_arr2)

        # Still in WARNING (2 frames)
        st2 = watchdog.evaluate("KATL", current_wall_time=t_arr2)
        assert st2.level == RiskLevel.WARNING

        # Frame 3 received at 14:27
        t_pkt3 = t0 + timedelta(minutes=26)
        t_arr3 = t0 + timedelta(minutes=27)
        pkt3 = self._make_packet("KATL", timestamp_utc=t_pkt3)
        watchdog.record_packet(pkt3, arrival_wall_time=t_arr3)

        # 3 consecutive healthy frames reached -> RECOVERED TO HEALTHY!
        st3 = watchdog.evaluate("KATL", current_wall_time=t_arr3)
        assert st3.level == RiskLevel.HEALTHY
        assert st3.cancel_all_quotes is False
        assert st3.safe_mode is False
