"""
Calendar Day Slicing & Quality Control Module for Observation Records.
Provides day window partitioning [00:00:00, 24:00:00) in target timezone,
minimum daily count / peak hour coverage gating, flatline anomaly detection,
and window health evaluation.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
import logging
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import zoneinfo

from src.data_acquisition.observation_adapter import ObservationRecord

logger = logging.getLogger(__name__)


class DataPipelineOutageError(RuntimeError):
    """Raised when incomplete data day ratio exceeds the tolerable threshold (20%)."""
    pass


class FlatlineAnomalyError(RuntimeError):
    """Raised when consecutive identical temperatures indicate synthetic or frozen data."""
    pass


class QcStatus(str, Enum):
    """Enumeration of quality control statuses."""
    VALID = "VALID"
    INCOMPLETE_DATA = "INCOMPLETE_DATA"


@dataclass
class DayQcResult:
    """Quality control evaluation result for a single local calendar day."""
    date: str
    total_obs: int
    peak_obs: int
    is_valid: bool
    status: str  # "VALID" or "INCOMPLETE_DATA"
    failure_reason: Optional[str] = None
    filtered_records: List[ObservationRecord] = field(default_factory=list)


@dataclass
class WindowQcSummary:
    """Summary of QC health across an evaluation window."""
    total_days: int
    valid_days: int
    incomplete_days: int
    incomplete_ratio: float
    is_pipeline_healthy: bool
    alert_message: Optional[str] = None
    flatline_anomaly_detected: bool = False


def normalize_target_date(target_date: Union[date, str]) -> date:
    """Ensure target_date is a standard datetime.date instance."""
    if isinstance(target_date, str):
        return datetime.strptime(target_date, "%Y-%m-%d").date()
    return target_date


def _to_local_tz(dt: datetime, tz: zoneinfo.ZoneInfo) -> datetime:
    """Convert datetime to target timezone, assuming UTC if tz-naive."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).astimezone(tz)
    return dt.astimezone(tz)


class CalendarDaySlicer:
    """Slices and groups observation records by local calendar days [00:00:00, 24:00:00)."""

    def slice_by_calendar_day(
        self,
        records: List[ObservationRecord],
        target_date: Union[date, str],
        timezone_str: str = "Asia/Shanghai",
    ) -> List[ObservationRecord]:
        """
        Filter records belonging to [target_date 00:00:00, target_date+1 00:00:00) in local timezone.
        """
        target_d = normalize_target_date(target_date)
        tz = zoneinfo.ZoneInfo(timezone_str)

        dt_start_local = datetime.combine(target_d, time(0, 0), tzinfo=tz)
        dt_end_local = dt_start_local + timedelta(days=1)

        dt_start_utc = dt_start_local.astimezone(timezone.utc)
        dt_end_utc = dt_end_local.astimezone(timezone.utc)

        day_records = []
        for r in records:
            r_ts_utc = r.timestamp if r.timestamp.tzinfo else r.timestamp.replace(tzinfo=timezone.utc)
            if dt_start_utc <= r_ts_utc < dt_end_utc:
                day_records.append(r)

        return sorted(day_records, key=lambda x: x.timestamp)

    def group_by_calendar_days(
        self,
        records: List[ObservationRecord],
        timezone_str: str = "Asia/Shanghai",
    ) -> Dict[str, List[ObservationRecord]]:
        """Group a continuous stream of observation records by local calendar day string (YYYY-MM-DD)."""
        tz = zoneinfo.ZoneInfo(timezone_str)
        groups: Dict[str, List[ObservationRecord]] = {}

        for r in records:
            r_ts_local = _to_local_tz(r.timestamp, tz)
            date_key = r_ts_local.strftime("%Y-%m-%d")
            groups.setdefault(date_key, []).append(r)

        for date_key in groups:
            groups[date_key].sort(key=lambda x: x.timestamp)

        return groups


class ObservationQualityControl:
    """Quality control validator enforcing observation frequency and diurnal coverage."""

    MIN_DAILY_OBS: int = 36  # >= 75% of expected 48 observations
    PEAK_START_HOUR: int = 11  # 11:00 local time
    PEAK_END_HOUR: int = 17    # 17:00 local time (11:00 to 16:59:59)
    MIN_PEAK_OBS: int = 8      # >= 8 observations during 6-hour peak window
    MAX_INCOMPLETE_RATIO: float = 0.20  # Max allowable incomplete days ratio in window

    def __init__(self, slicer: Optional[CalendarDaySlicer] = None):
        self.slicer = slicer or CalendarDaySlicer()

    def evaluate_day(
        self,
        records: List[ObservationRecord],
        target_date: Union[date, str],
        timezone_str: str = "Asia/Shanghai",
    ) -> DayQcResult:
        """Evaluate quality control criteria for a single calendar day."""
        target_d = normalize_target_date(target_date)
        date_str = target_d.strftime("%Y-%m-%d")
        tz = zoneinfo.ZoneInfo(timezone_str)

        day_records = self.slicer.slice_by_calendar_day(records, target_d, timezone_str)
        total_obs = len(day_records)

        # Count peak observations during daytime heating window
        peak_obs = sum(
            1 for r in day_records
            if self.PEAK_START_HOUR <= _to_local_tz(r.timestamp, tz).hour < self.PEAK_END_HOUR
        )

        # Check QC criteria
        failures = []
        if total_obs < self.MIN_DAILY_OBS:
            failures.append(f"low_obs_count ({total_obs} < {self.MIN_DAILY_OBS})")
        if peak_obs < self.MIN_PEAK_OBS:
            failures.append(f"insufficient_peak_obs ({peak_obs} < {self.MIN_PEAK_OBS})")

        is_valid = len(failures) == 0
        status = QcStatus.VALID.value if is_valid else QcStatus.INCOMPLETE_DATA.value
        failure_reason = "; ".join(failures) if failures else None

        return DayQcResult(
            date=date_str,
            total_obs=total_obs,
            peak_obs=peak_obs,
            is_valid=is_valid,
            status=status,
            failure_reason=failure_reason,
            filtered_records=day_records,
        )

    def _check_flatline_anomaly(self, daily_results: List[DayQcResult]) -> bool:
        """
        Detect synthetic or frozen flatline temperature anomalies.
        Distinguishes natural persistent summer heatwaves (constant daily max but natural diurnal swings)
        from synthetic / deadlocked pipelines (flat daily max AND dead flat diurnal curves / 100% clone series).
        """
        valid_days = [r for r in daily_results if r.is_valid and r.filtered_records]
        if len(valid_days) < 5:
            return False

        max_temps = []
        min_temps = []
        diurnal_ranges = []
        hourly_series_list = []

        for r in valid_days:
            temps = [rec.temp_c for rec in r.filtered_records if rec.temp_c is not None]
            if temps:
                t_max = max(temps)
                t_min = min(temps)
                max_temps.append(round(t_max, 2))
                min_temps.append(round(t_min, 2))
                diurnal_ranges.append(round(t_max - t_min, 2))
                hourly_series_list.append(temps)

        if len(max_temps) < 5:
            return False

        # Condition: Daily max is 100% identical across all valid days (>= 5 days)
        if len(set(max_temps)) == 1:
            # Check A: Dead flat diurnal range (no daily heating curve, <= 0.5°C swing)
            mean_diurnal_range = sum(diurnal_ranges) / len(diurnal_ranges)
            if mean_diurnal_range <= 0.5:
                return True

            # Check B: Min temperatures and diurnal ranges are also identical across all days
            if len(set(min_temps)) == 1 and len(set(diurnal_ranges)) == 1:
                lengths = [len(s) for s in hourly_series_list]
                if len(set(lengths)) == 1:
                    base_series = hourly_series_list[0]
                    if all(s == base_series for s in hourly_series_list[1:]):
                        return True

        return False

    def evaluate_window(self, daily_results: List[DayQcResult]) -> WindowQcSummary:
        """Summarize QC health across an evaluation window, checking outage ratio and flatline anomalies."""
        total_days = len(daily_results)
        if total_days == 0:
            return WindowQcSummary(0, 0, 0, 0.0, True, None, False)

        valid_days = sum(1 for r in daily_results if r.is_valid)
        incomplete_days = total_days - valid_days
        incomplete_ratio = incomplete_days / total_days

        is_healthy = incomplete_ratio <= self.MAX_INCOMPLETE_RATIO
        alert_msg = None
        if not is_healthy:
            alert_msg = (
                f"🚨 CRITICAL QC ALERT: Incomplete data day ratio {incomplete_ratio:.1%} "
                f"exceeds {self.MAX_INCOMPLETE_RATIO:.1%} threshold "
                f"({incomplete_days}/{total_days} days). System outage suspected."
            )

        flatline_detected = self._check_flatline_anomaly(daily_results)
        if flatline_detected:
            is_healthy = False
            flatline_msg = (
                "🚨 FLATLINE ANOMALY ALERT: All valid days have identical daily maximum temperature "
                "(zero variance). Synthetic, mock, or frozen data lock suspected."
            )
            alert_msg = f"{alert_msg}; {flatline_msg}" if alert_msg else flatline_msg

        return WindowQcSummary(
            total_days=total_days,
            valid_days=valid_days,
            incomplete_days=incomplete_days,
            incomplete_ratio=incomplete_ratio,
            is_pipeline_healthy=is_healthy,
            alert_message=alert_msg,
            flatline_anomaly_detected=flatline_detected,
        )

    def check_pipeline_health_or_raise(self, summary: WindowQcSummary) -> None:
        """Enforce pipeline health, raising DataPipelineOutageError or FlatlineAnomalyError."""
        if not summary.is_pipeline_healthy:
            logger.critical(summary.alert_message)
            if summary.flatline_anomaly_detected:
                raise FlatlineAnomalyError(summary.alert_message)
            raise DataPipelineOutageError(summary.alert_message)
