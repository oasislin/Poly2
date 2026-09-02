"""
Update Latency & 24-Hour Outage / Gap Distribution Analyzer for NWS WRH Observations.
Evaluates empirical update latency and diagnoses hourly observation density patterns.
Strictly frozen from pricing judgments and Go/No-Go downstream recommendations.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import zoneinfo

import numpy as np

from src.data_acquisition.observation_adapter import ObservationRecord

logger = logging.getLogger(__name__)

# Maximum lag threshold (in hours) to distinguish real-time update lag from historical archive lookbacks:
MAX_REALTIME_LAG_HOURS: float = 6.0


@dataclass
class UpdateLatencySummary:
    """Strongly-typed summary of empirical data update lag between observation and availability."""
    sample_count: int
    median_latency_min: float
    p95_latency_min: float
    max_latency_min: float
    min_latency_min: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert latency summary to dictionary."""
        return {
            "sample_count": self.sample_count,
            "median_latency_min": self.median_latency_min,
            "p95_latency_min": self.p95_latency_min,
            "max_latency_min": self.max_latency_min,
            "min_latency_min": self.min_latency_min,
        }


@dataclass
class HourlyOutageDistribution:
    """
    Hourly observation frequency histogram and outage clustering analysis.
    Clarifies window cumulative counts vs daily hourly frequencies to avoid unit confusion.
    """
    days_evaluated: int
    total_observations: int
    cumulative_hourly_counts: Dict[int, int]
    mean_obs_per_day_per_hour: Dict[int, float]
    hourly_coverage_pct: Dict[int, float]
    mean_cumulative_count_in_window: float
    mean_daily_obs_per_hour: float
    expected_cumulative_count: float
    expected_daily_obs_per_hour: float
    low_coverage_hours: List[int]
    outage_clustering_detected: bool

    # Backwards compatibility property
    @property
    def hourly_counts(self) -> Dict[int, int]:
        return self.cumulative_hourly_counts

    @property
    def average_per_hour(self) -> float:
        return self.mean_cumulative_count_in_window

    @property
    def expected_per_hour(self) -> float:
        return self.expected_cumulative_count

    @property
    def low_coverage_hours_list(self) -> List[int]:
        return self.low_coverage_hours

    def to_dict(self) -> Dict[str, Any]:
        """Convert hourly distribution to dictionary with explicit unit clarity."""
        return {
            "days_evaluated": self.days_evaluated,
            "total_observations": self.total_observations,
            "cumulative_hourly_counts": self.cumulative_hourly_counts,
            "mean_obs_per_day_per_hour": self.mean_obs_per_day_per_hour,
            "hourly_coverage_pct": self.hourly_coverage_pct,
            "mean_cumulative_count_in_window": self.mean_cumulative_count_in_window,
            "mean_daily_obs_per_hour": self.mean_daily_obs_per_hour,
            "expected_cumulative_count": self.expected_cumulative_count,
            "expected_daily_obs_per_hour": self.expected_daily_obs_per_hour,
            "low_coverage_hours": self.low_coverage_hours,
            "outage_clustering_detected": self.outage_clustering_detected,
            "hourly_counts": self.cumulative_hourly_counts,
            "average_per_hour": self.mean_cumulative_count_in_window,
            "expected_per_hour": self.expected_cumulative_count,
        }


class LatencyOutageAnalyzer:
    """Analyzes observation update latency and 24-hour diurnal gap distributions."""

    @staticmethod
    def _parse_iso_utc(ts_str: str) -> Optional[datetime]:
        """Parse ISO or compact formatted timestamp string into UTC datetime."""
        try:
            cleaned = ts_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            return dt.astimezone(timezone.utc)
        except (ValueError, TypeError):
            try:
                dt = datetime.strptime(ts_str, "%Y%m%dT%H%M%SZ")
                return dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                return None

    @staticmethod
    def _extract_file_metadata(payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], List[str]]:
        """Safely extract unit type, fetched timestamp, and observation timestamps from raw payload."""
        unit_type = payload.get("unit_type", "metric")
        fetched_at = payload.get("fetched_at_utc") or payload.get("fetched_at")
        stations = payload.get("response", {}).get("STATION", [])
        obs_dates = stations[0].get("OBSERVATIONS", {}).get("date_time", []) if stations else []
        return unit_type, fetched_at, obs_dates

    def compute_update_latency_from_raw_files(
        self, storage_dir: Union[str, Path], station: str = "ZSPD"
    ) -> UpdateLatencySummary:
        """
        Analyze update lag (fetched_at timestamp - latest observation timestamp)
        across raw JSON files in storage_dir. Excludes historical lookbacks and English probe duplicates.
        """
        target_dir = Path(storage_dir)
        raw_files = sorted(list(target_dir.glob(f"{station}_*.json")))
        lag_minutes: List[float] = []

        for f_path in raw_files:
            try:
                with open(f_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)

                unit_type, fetched_at_str, obs_dates = self._extract_file_metadata(payload)
                if unit_type != "metric" or not fetched_at_str or not obs_dates:
                    continue

                dt_fetched = self._parse_iso_utc(fetched_at_str)
                dt_obs_latest = self._parse_iso_utc(obs_dates[-1])

                if dt_fetched and dt_obs_latest:
                    diff_sec = (dt_fetched - dt_obs_latest).total_seconds()
                    if 0 <= diff_sec <= (MAX_REALTIME_LAG_HOURS * 3600):
                        lag_minutes.append(diff_sec / 60.0)
            except (IOError, json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Error parsing latency from {f_path}: {e}")

        return self._summarize_latency_distribution(lag_minutes)

    @staticmethod
    def _summarize_latency_distribution(lags: List[float]) -> UpdateLatencySummary:
        """Calculate empirical percentiles from lag list."""
        if not lags:
            return UpdateLatencySummary(
                sample_count=0,
                median_latency_min=0.0,
                p95_latency_min=0.0,
                max_latency_min=0.0,
                min_latency_min=0.0,
            )

        med = float(np.percentile(lags, 50))
        p95 = float(np.percentile(lags, 95))
        max_l = float(np.max(lags))
        min_l = float(np.min(lags))

        return UpdateLatencySummary(
            sample_count=len(lags),
            median_latency_min=round(med, 2),
            p95_latency_min=round(p95, 2),
            max_latency_min=round(max_l, 2),
            min_latency_min=round(min_l, 2),
        )

    @staticmethod
    def _build_hourly_distribution(
        cumulative_counts: Dict[int, int],
        total_obs: int,
        days_count: int,
    ) -> HourlyOutageDistribution:
        """Factory helper: calculate derived hourly frequencies and construct distribution dataclass."""
        expected_cumulative_per_hour = days_count * 2.0
        expected_daily_obs_per_hour = 2.0

        mean_obs_daily = {h: round(count / max(1, days_count), 2) for h, count in cumulative_counts.items()}
        coverage_pct = {
            h: round((count / max(0.001, expected_cumulative_per_hour)) * 100.0, 1)
            for h, count in cumulative_counts.items()
        }
        low_coverage = [h for h, count in cumulative_counts.items() if count < (expected_cumulative_per_hour * 0.5)]

        mean_cum = round(total_obs / 24.0, 2) if total_obs > 0 else 0.0
        mean_daily = round(mean_cum / max(1, days_count), 2)

        return HourlyOutageDistribution(
            days_evaluated=days_count,
            total_observations=total_obs,
            cumulative_hourly_counts=cumulative_counts,
            mean_obs_per_day_per_hour=mean_obs_daily,
            hourly_coverage_pct=coverage_pct,
            mean_cumulative_count_in_window=mean_cum,
            mean_daily_obs_per_hour=mean_daily,
            expected_cumulative_count=round(expected_cumulative_per_hour, 2),
            expected_daily_obs_per_hour=expected_daily_obs_per_hour,
            low_coverage_hours=low_coverage,
            outage_clustering_detected=len(low_coverage) > 0,
        )

    def compute_hourly_outage_distribution(
        self,
        records: List[ObservationRecord],
        days_count: int,
        timezone_str: str = "Asia/Shanghai",
    ) -> HourlyOutageDistribution:
        """Build 24-hour observation frequency histogram in target timezone."""
        tz = zoneinfo.ZoneInfo(timezone_str)
        cumulative_counts: Dict[int, int] = {h: 0 for h in range(24)}

        for r in records:
            dt_local = (
                r.timestamp.astimezone(tz)
                if r.timestamp.tzinfo
                else r.timestamp.replace(tzinfo=timezone.utc).astimezone(tz)
            )
            cumulative_counts[dt_local.hour] += 1

        return self._build_hourly_distribution(cumulative_counts, len(records), days_count)
