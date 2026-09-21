"""
Unit tests for MonotonicConfluenceEngine and Calendar Day State Machine (Phase 2 Task 02 - Ticket 03 / Issue #67).
Tests dual-source monotonic accumulation, local timezone calendar-day rollover, and permanent truncation lock.
"""

from datetime import datetime, timezone, timedelta
import pytest

from src.data_acquisition.observation_stream import ObservationPacket
from src.prediction.monotonic_confluence import (
    MonotonicConfluenceEngine,
    StationDayState,
)


class TestMonotonicConfluenceEngine:
    """Test suite for MonotonicConfluenceEngine and calendar-day state tracking."""

    @pytest.fixture
    def engine(self):
        return MonotonicConfluenceEngine()

    def _make_packet(
        self,
        station_id: str,
        temp_f: float,
        timestamp_utc: datetime,
        source_type: str = "iem_metar",
    ) -> ObservationPacket:
        temp_c = (temp_f - 32.0) * 5.0 / 9.0
        return ObservationPacket(
            station_id=station_id,
            timestamp_utc=timestamp_utc,
            temp_c=temp_c,
            temp_f=temp_f,
            source_type=source_type,
            is_speci=False,
        )

    def test_dual_source_monotonic_accumulation(self, engine):
        """TMAX monotonically non-decreasing, TMIN monotonically non-increasing across IEM and NWS."""
        # KORD in America/Chicago. 2026-09-21 14:00 UTC = 09:00 local time
        t0 = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)
        pkt1 = self._make_packet("KORD", temp_f=65.0, timestamp_utc=t0, source_type="iem_metar")
        s1 = engine.ingest(pkt1)
        assert s1.tmax_so_far == 65.0
        assert s1.tmin_so_far == 65.0

        # Step 2: NWS reports 68.0°F -> TMAX climbs to 68.0, TMIN stays 65.0
        t1 = t0 + timedelta(minutes=15)
        pkt2 = self._make_packet("KORD", temp_f=68.0, timestamp_utc=t1, source_type="nws_wrh")
        s2 = engine.ingest(pkt2)
        assert s2.tmax_so_far == 68.0
        assert s2.tmin_so_far == 65.0

        # Step 3: IEM reports 66.0°F (temp dipped slightly in afternoon shade)
        # TMAX must remain at peak 68.0°F (never decreases), TMIN remains 65.0
        t2 = t1 + timedelta(minutes=15)
        pkt3 = self._make_packet("KORD", temp_f=66.0, timestamp_utc=t2, source_type="iem_metar")
        s3 = engine.ingest(pkt3)
        assert s3.tmax_so_far == 68.0
        assert s3.tmin_so_far == 65.0

        # Step 4: Early morning/evening cool down to 60.0°F -> TMIN drops to 60.0, TMAX stays 68.0
        t3 = t2 + timedelta(minutes=15)
        pkt4 = self._make_packet("KORD", temp_f=60.0, timestamp_utc=t3, source_type="iem_metar")
        s4 = engine.ingest(pkt4)
        assert s4.tmax_so_far == 68.0
        assert s4.tmin_so_far == 60.0

    def test_local_calendar_day_rollover(self, engine):
        """State resets cleanly when advancing past local midnight in station's timezone."""
        # KLAX is America/Los_Angeles (UTC-7 in daylight saving)
        # 2026-09-21 23:30 PDT = 2026-09-22 06:30 UTC
        t_night = datetime(2026, 9, 22, 6, 30, tzinfo=timezone.utc)
        pkt1 = self._make_packet("KLAX", temp_f=75.0, timestamp_utc=t_night)
        s1 = engine.ingest(pkt1)
        assert s1.local_date.isoformat() == "2026-09-21"
        assert s1.tmax_so_far == 75.0

        # 2026-09-22 00:30 PDT = 2026-09-22 07:30 UTC (Rollover to 2026-09-22!)
        t_next_day = datetime(2026, 9, 22, 7, 30, tzinfo=timezone.utc)
        pkt2 = self._make_packet("KLAX", temp_f=62.0, timestamp_utc=t_next_day)
        s2 = engine.ingest(pkt2)
        assert s2.local_date.isoformat() == "2026-09-22"
        # Reset to new day's initial observation
        assert s2.tmax_so_far == 62.0
        assert s2.tmin_so_far == 62.0

    def test_permanent_truncation_lock_during_feed_gap(self, engine):
        """TMAX and TMIN remain locked during feed gap without resetting."""
        t0 = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)
        pkt = self._make_packet("KATL", temp_f=82.0, timestamp_utc=t0)
        engine.ingest(pkt)

        # Query state 2 hours later without new packets
        state = engine.get_station_state("KATL")
        assert state is not None
        assert state.tmax_so_far == 82.0
        assert state.tmin_so_far == 82.0
