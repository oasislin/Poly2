"""
Test-Scenario D Acceptance Test Suite: Multi-Source Confluence and SPECI Truncation (Phase 2 Task 02 - Ticket 05 / Issue #69).
Implements execution specification §IV.4:
- D1: Lateness METAR raw message discard negative assertion.
- D2: Main body vs RMK temperature conflict correction positive assertion.
- D3: Abnormal temperature jump (20°F) Fail-Closed safety circuit breaker assertion.
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
from src.risk.stream_watchdog import (
    RiskLevel,
    StreamRiskWatchdog,
)
from src.pipeline.stream_confluence_pipeline import (
    StreamConfluencePipeline,
    PipelineProcessResult,
)


class TestScenarioD:
    """Official Phase 2 Test-Scenario D acceptance gate suite."""

    @pytest.fixture
    def pipeline(self):
        adapter = ObservationStreamAdapter()
        sanitizer = TemperatureSanitizer(SanitizerConfig())
        confluence = MonotonicConfluenceEngine()
        watchdog = StreamRiskWatchdog()
        return StreamConfluencePipeline(
            adapter=adapter,
            sanitizer=sanitizer,
            confluence=confluence,
            watchdog=watchdog,
        )

    def test_scenario_d1_late_metar_discard_negative_assertion(self, pipeline):
        """
        D1: Late METAR raw message arrival (>15 min latency) must be discarded.
        Negative assertion: Extrema state is NOT updated, no re-pricing event emitted.
        """
        station = "KORD"
        # Observation at 14:00 UTC
        obs_time = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)
        raw_metar = "METAR KORD 211400Z 04010KT 10SM CLR 20/10 A3000 RMK AO2 T02000100"

        # Packet arrives at 14:25 UTC (25 minutes late > 15m threshold)
        wall_time = obs_time + timedelta(minutes=25)

        result: PipelineProcessResult = pipeline.process_raw_metar(
            station_id=station,
            raw_metar=raw_metar,
            timestamp_utc=obs_time,
            arrival_wall_time=wall_time,
        )

        # Assertions for D1
        assert result.sanitizer_result.is_valid is False
        assert result.sanitizer_result.is_late is True
        assert result.confluence_updated is False
        assert result.confluence_state is None
        # Must not block station (lateness is not physical tear)
        assert result.sanitizer_result.station_blocked is False

    def test_scenario_d2_body_vs_rmk_cross_check_and_rmk_preference(self, pipeline):
        """
        D2: Main body integer vs RMK 0.1°C precision within acceptable tolerance (<=1.8°F).
        Positive assertion: RMK 0.1°C precision is preferred, correctly updating TMAX/TMIN.
        """
        station = "KATL"
        obs_time = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)
        # Body reports 22°C (=71.6°F), RMK reports T0224 (=22.4°C = 72.32°F). Difference = 0.72°F <= 1.8°F.
        raw_metar = "METAR KATL 211500Z 18008KT 10SM SCT030 22/15 A3010 RMK AO2 T02240150"
        wall_time = obs_time + timedelta(minutes=2)

        result: PipelineProcessResult = pipeline.process_raw_metar(
            station_id=station,
            raw_metar=raw_metar,
            timestamp_utc=obs_time,
            arrival_wall_time=wall_time,
        )

        # Assertions for D2
        assert result.sanitizer_result.is_valid is True
        assert result.confluence_updated is True
        assert result.confluence_state is not None
        # Effective temperature preferred RMK 22.4°C
        assert result.packet.temp_c == 22.4
        expected_f = 22.4 * 9.0 / 5.0 + 32.0
        assert result.confluence_state.tmax_so_far == pytest.approx(expected_f, abs=1e-4)
        assert result.confluence_state.tmin_so_far == pytest.approx(expected_f, abs=1e-4)

    def test_scenario_d3_abnormal_20f_jump_triggers_fail_closed_circuit_breaker(self, pipeline):
        """
        D3: Abnormal temperature jump of 20°F (>15.0°F gate) triggers Fail-Closed safety breaker.
        Assertion: PHYSICAL_TEAR reported, station locked to STATION_BLOCKED, CancelAll instruction emitted.
        """
        station = "KDAL"
        # 1. Normal observation at 16:00 UTC: 80°F
        t0 = datetime(2026, 9, 21, 16, 0, tzinfo=timezone.utc)
        raw_t0 = "METAR KDAL 211600Z 18010KT 10SM CLR 27/15 A2995 RMK AO2 T02670150"  # 26.7°C ~ 80.06°F
        res0 = pipeline.process_raw_metar(station, raw_t0, t0, t0 + timedelta(minutes=1))
        assert res0.sanitizer_result.is_valid is True

        # 2. Corrupted jump at 16:05 UTC to 102°F (Delta ~ 22°F > 15°F threshold)
        t1 = t0 + timedelta(minutes=5)
        raw_t1 = "METAR KDAL 211605Z 18010KT 10SM CLR 39/15 A2995 RMK AO2 T03890150"  # 38.9°C ~ 102.02°F
        res1 = pipeline.process_raw_metar(station, raw_t1, t1, t1 + timedelta(minutes=1))

        # Assertions for D3
        assert res1.sanitizer_result.is_valid is False
        assert res1.sanitizer_result.station_blocked is True
        assert res1.sanitizer_result.incident_type == "PHYSICAL_TEAR"
        assert res1.sanitizer_result.action == "CANCEL_ALL_OPEN_ORDERS"
        assert res1.confluence_updated is False

        # 3. Subsequent packet on same day is immediately rejected due to persistent STATION_BLOCKED
        t2 = t0 + timedelta(minutes=10)
        raw_t2 = "METAR KDAL 211610Z 18010KT 10SM CLR 28/15 A2995 RMK AO2 T02780150"
        res2 = pipeline.process_raw_metar(station, raw_t2, t2, t2 + timedelta(minutes=1))
        assert res2.sanitizer_result.is_valid is False
        assert res2.sanitizer_result.station_blocked is True
