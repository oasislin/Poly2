"""
Unit Tests for Latency and Hourly Outage Distribution Analyzer (Probe 4).
"""

from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import pytest

from src.data_acquisition.observation_adapter import ObservationRecord
from src.data_analysis.latency_outage_analyzer import (
    HourlyOutageDistribution,
    LatencyOutageAnalyzer,
    UpdateLatencySummary,
)


class TestLatencyOutageAnalyzer:
    """Test update latency calculation and 24-hour observation frequency histogram."""

    def test_compute_update_latency_from_raw_files(self, tmp_path):
        analyzer = LatencyOutageAnalyzer()

        # Create two sample raw JSON files with known latency
        # File 1: obs at 12:00:00Z, fetched at 12:15:00Z -> lag = 15.0 min
        f1_payload = {
            "unit_type": "metric",
            "fetched_at_utc": "2026-09-02T12:15:00Z",
            "response": {
                "STATION": [
                    {
                        "OBSERVATIONS": {
                            "date_time": ["2026-09-02T11:30:00Z", "2026-09-02T12:00:00Z"],
                        }
                    }
                ]
            },
        }
        # File 2: obs at 13:00:00Z, fetched at 13:25:00Z -> lag = 25.0 min
        f2_payload = {
            "unit_type": "metric",
            "fetched_at_utc": "2026-09-02T13:25:00Z",
            "response": {
                "STATION": [
                    {
                        "OBSERVATIONS": {
                            "date_time": ["2026-09-02T12:30:00Z", "2026-09-02T13:00:00Z"],
                        }
                    }
                ]
            },
        }

        with open(tmp_path / "ZSPD_20260902_1.json", "w", encoding="utf-8") as f:
            json.dump(f1_payload, f)
        with open(tmp_path / "ZSPD_20260902_2.json", "w", encoding="utf-8") as f:
            json.dump(f2_payload, f)

        summary = analyzer.compute_update_latency_from_raw_files(tmp_path, station="ZSPD")
        assert summary.sample_count == 2
        assert summary.median_latency_min == 20.0
        assert summary.p95_latency_min == 24.5
        assert summary.max_latency_min == 25.0
        assert summary.min_latency_min == 15.0

    def test_compute_hourly_outage_distribution_uniform(self):
        analyzer = LatencyOutageAnalyzer()

        # Build 48 records across 24 hours (2 per hour) in Asia/Shanghai for 14 days
        records = []
        base = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
        for day in range(14):
            for h in range(24):
                records.append(ObservationRecord(timestamp=base + timedelta(days=day, hours=h, minutes=0), temp_c=25.0))
                records.append(ObservationRecord(timestamp=base + timedelta(days=day, hours=h, minutes=30), temp_c=25.0))

        dist = analyzer.compute_hourly_outage_distribution(records, days_count=14, timezone_str="Asia/Shanghai")
        assert dist.total_observations == 14 * 48
        assert dist.cumulative_hourly_counts[0] == 28
        assert dist.mean_obs_per_day_per_hour[0] == 2.0
        assert dist.hourly_coverage_pct[0] == 100.0
        assert dist.mean_cumulative_count_in_window == 28.0
        assert dist.mean_daily_obs_per_hour == 2.0
        assert len(dist.low_coverage_hours) == 0
        assert dist.outage_clustering_detected is False

        d = dist.to_dict()
        assert d["days_evaluated"] == 14
        assert d["mean_daily_obs_per_hour"] == 2.0
        assert d["expected_daily_obs_per_hour"] == 2.0

    def test_compute_hourly_outage_distribution_with_gap(self):
        analyzer = LatencyOutageAnalyzer()

        # Build records with complete outage during 02:00-04:00 CST (18:00-20:00 UTC)
        records = []
        base = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
        for h in range(24):
            # Skip 18:00 and 19:00 UTC (which is 02:00 and 03:00 CST)
            if h in [18, 19]:
                continue
            records.append(ObservationRecord(timestamp=base + timedelta(hours=h, minutes=0), temp_c=25.0))
            records.append(ObservationRecord(timestamp=base + timedelta(hours=h, minutes=30), temp_c=25.0))

        dist = analyzer.compute_hourly_outage_distribution(records, days_count=1, timezone_str="Asia/Shanghai")
        assert dist.total_observations == 44
        assert 2 in dist.low_coverage_hours
        assert 3 in dist.low_coverage_hours
        assert dist.outage_clustering_detected is True
