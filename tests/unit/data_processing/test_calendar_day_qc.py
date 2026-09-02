"""
Unit Tests for Calendar Day Slicing and Observation Quality Control Engine.
"""

from datetime import date, datetime, timezone, timedelta
import zoneinfo
import pytest

from src.data_acquisition.observation_adapter import ObservationRecord
from src.data_processing.calendar_day_qc import (
    CalendarDaySlicer,
    ObservationQualityControl,
    DayQcResult,
    WindowQcSummary,
    DataPipelineOutageError,
    FlatlineAnomalyError,
)

CST = zoneinfo.ZoneInfo("Asia/Shanghai")


def make_record(dt_cst: datetime, temp_c: float = 25.0) -> ObservationRecord:
    """Helper to create an ObservationRecord at specific CST time."""
    if dt_cst.tzinfo is None:
        dt_cst = dt_cst.replace(tzinfo=CST)
    return ObservationRecord(
        timestamp=dt_cst,
        temp_c=temp_c,
        raw_metar=f"METAR ZSPD {dt_cst.strftime('%d%H%M')}Z {int(temp_c)}/20 Q1010",
    )


class TestCalendarDaySlicer:
    """Test calendar day slicing, boundary adherence, and left-closed right-open logic."""

    def test_left_closed_right_open_boundary(self):
        slicer = CalendarDaySlicer()
        target = date(2026, 9, 1)

        rec_start = make_record(datetime(2026, 9, 1, 0, 0, 0, tzinfo=CST))
        rec_mid = make_record(datetime(2026, 9, 1, 12, 30, 0, tzinfo=CST))
        rec_end = make_record(datetime(2026, 9, 1, 23, 59, 59, tzinfo=CST))
        rec_next_start = make_record(datetime(2026, 9, 2, 0, 0, 0, tzinfo=CST))
        rec_prev_end = make_record(datetime(2026, 8, 31, 23, 59, 59, tzinfo=CST))

        all_records = [rec_prev_end, rec_start, rec_mid, rec_end, rec_next_start]
        sliced = slicer.slice_by_calendar_day(all_records, target_date=target, timezone_str="Asia/Shanghai")

        assert len(sliced) == 3
        assert rec_start in sliced
        assert rec_mid in sliced
        assert rec_end in sliced
        assert rec_next_start not in sliced
        assert rec_prev_end not in sliced

    def test_utc_to_cst_boundary_conversion(self):
        slicer = CalendarDaySlicer()
        target = date(2026, 9, 1)

        rec_utc_start = ObservationRecord(
            timestamp=datetime(2026, 8, 31, 16, 0, 0, tzinfo=timezone.utc),
            temp_c=26.0,
        )
        rec_utc_end = ObservationRecord(
            timestamp=datetime(2026, 9, 1, 15, 59, 59, tzinfo=timezone.utc),
            temp_c=27.0,
        )
        rec_utc_next = ObservationRecord(
            timestamp=datetime(2026, 9, 1, 16, 0, 0, tzinfo=timezone.utc),
            temp_c=28.0,
        )

        sliced = slicer.slice_by_calendar_day(
            [rec_utc_start, rec_utc_end, rec_utc_next],
            target_date=target,
            timezone_str="Asia/Shanghai",
        )
        assert len(sliced) == 2
        assert rec_utc_start in sliced
        assert rec_utc_end in sliced
        assert rec_utc_next not in sliced

    def test_group_by_calendar_days(self):
        slicer = CalendarDaySlicer()
        records = [
            make_record(datetime(2026, 9, 1, 10, 0, tzinfo=CST)),
            make_record(datetime(2026, 9, 1, 14, 0, tzinfo=CST)),
            make_record(datetime(2026, 9, 2, 8, 0, tzinfo=CST)),
        ]
        groups = slicer.group_by_calendar_days(records, timezone_str="Asia/Shanghai")
        assert "2026-09-01" in groups
        assert "2026-09-02" in groups
        assert len(groups["2026-09-01"]) == 2
        assert len(groups["2026-09-02"]) == 1


class TestObservationQualityControl:
    """Test valid day criteria (N>=36, peak N>=8), flatline anomaly detector, and pipeline health."""

    def test_valid_day_evaluation(self):
        qc = ObservationQualityControl()
        target = date(2026, 9, 1)

        records = []
        for i in range(48):
            dt = datetime(2026, 9, 1, 0, 0, tzinfo=CST) + timedelta(minutes=30 * i)
            records.append(make_record(dt, temp_c=25.0 + (i % 5)))

        result = qc.evaluate_day(records, target_date=target, timezone_str="Asia/Shanghai")
        assert isinstance(result, DayQcResult)
        assert result.is_valid is True
        assert result.status == "VALID"
        assert result.total_obs == 48
        assert result.peak_obs == 12
        assert result.failure_reason is None

    def test_incomplete_day_low_obs_count(self):
        qc = ObservationQualityControl()
        target = date(2026, 9, 1)

        records = [
            make_record(datetime(2026, 9, 1, 0, 0, tzinfo=CST) + timedelta(minutes=30 * i))
            for i in range(20)
        ]
        result = qc.evaluate_day(records, target_date=target, timezone_str="Asia/Shanghai")
        assert result.is_valid is False
        assert result.status == "INCOMPLETE_DATA"
        assert result.total_obs == 20
        assert "low_obs_count" in result.failure_reason

    def test_incomplete_day_insufficient_peak_obs(self):
        qc = ObservationQualityControl()
        target = date(2026, 9, 1)

        records = []
        for i in range(22):
            records.append(make_record(datetime(2026, 9, 1, 0, 0, tzinfo=CST) + timedelta(minutes=30 * i)))
        for i in range(4):
            records.append(make_record(datetime(2026, 9, 1, 11, 0, tzinfo=CST) + timedelta(minutes=30 * i)))
        for i in range(14):
            records.append(make_record(datetime(2026, 9, 1, 17, 0, tzinfo=CST) + timedelta(minutes=30 * i)))

        assert len(records) == 40
        result = qc.evaluate_day(records, target_date=target, timezone_str="Asia/Shanghai")
        assert result.is_valid is False
        assert result.status == "INCOMPLETE_DATA"
        assert result.peak_obs == 4
        assert "insufficient_peak_obs" in result.failure_reason

    def test_window_evaluation_healthy(self):
        qc = ObservationQualityControl()
        # 10 days total, natural variation in max temps
        results = []
        for i in range(9):
            recs = [make_record(datetime(2026, 9, i+1, 14, 0, tzinfo=CST), temp_c=28.0 + (i % 4))]
            results.append(
                DayQcResult(date=f"2026-09-{i+1:02d}", total_obs=48, peak_obs=10, is_valid=True, status="VALID", failure_reason=None, filtered_records=recs)
            )
        results.append(
            DayQcResult(date="2026-09-10", total_obs=20, peak_obs=3, is_valid=False, status="INCOMPLETE_DATA", failure_reason="low_obs_count", filtered_records=[])
        )

        summary = qc.evaluate_window(results)
        assert isinstance(summary, WindowQcSummary)
        assert summary.total_days == 10
        assert summary.valid_days == 9
        assert summary.incomplete_days == 1
        assert pytest.approx(summary.incomplete_ratio, 0.01) == 0.10
        assert summary.is_pipeline_healthy is True
        assert summary.flatline_anomaly_detected is False
        qc.check_pipeline_health_or_raise(summary)

    def test_window_evaluation_flatline_anomaly_raises(self):
        qc = ObservationQualityControl()
        # 7 valid days all with identical flat 28.0 max and dead flat diurnal curves
        results = []
        for i in range(7):
            day_records = [
                make_record(datetime(2026, 9, i+1, h, 0, tzinfo=CST), temp_c=28.0)
                for h in range(24)
            ]
            results.append(
                DayQcResult(
                    date=f"2026-09-{i+1:02d}",
                    total_obs=48,
                    peak_obs=10,
                    is_valid=True,
                    status="VALID",
                    failure_reason=None,
                    filtered_records=day_records,
                )
            )

        summary = qc.evaluate_window(results)
        assert summary.flatline_anomaly_detected is True
        assert summary.is_pipeline_healthy is False
        assert "FLATLINE ANOMALY ALERT" in summary.alert_message

        with pytest.raises(FlatlineAnomalyError) as excinfo:
            qc.check_pipeline_health_or_raise(summary)
        assert "FLATLINE ANOMALY ALERT" in str(excinfo.value)

    def test_window_evaluation_persistent_heatwave_passes(self):
        qc = ObservationQualityControl()
        # 7 valid days in summer: daily max is identically 31.0°C, but nighttime temp and diurnal curves vary naturally
        results = []
        for i in range(7):
            min_temp = 25.0 + (i % 3) * 0.5  # 25.0, 25.5, 26.0 (natural night variation)
            day_records = [
                make_record(datetime(2026, 9, i+1, 4, 0, tzinfo=CST), temp_c=min_temp),
                make_record(datetime(2026, 9, i+1, 14, 0, tzinfo=CST), temp_c=31.0),
            ]
            results.append(
                DayQcResult(
                    date=f"2026-09-{i+1:02d}",
                    total_obs=48,
                    peak_obs=10,
                    is_valid=True,
                    status="VALID",
                    failure_reason=None,
                    filtered_records=day_records,
                )
            )

        summary = qc.evaluate_window(results)
        assert summary.flatline_anomaly_detected is False
        assert summary.is_pipeline_healthy is True
        qc.check_pipeline_health_or_raise(summary)
