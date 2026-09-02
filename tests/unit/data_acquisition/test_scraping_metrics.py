"""
Unit Tests for Scraping Stability Tracker, Error Categorization, and Schema Drift Detection.
"""

import csv
import json
import pytest
from pathlib import Path

from src.data_acquisition.scraping_metrics import (
    ScrapingStabilityTracker,
    UptimeMetricsRecord,
)


class TestScrapingStabilityTracker:
    """Test metrics tracking, latency percentiles, error classification, and schema drift."""

    def test_record_successful_attempts_and_percentiles(self):
        tracker = ScrapingStabilityTracker()
        latencies = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00]
        for lat in latencies:
            tracker.record_attempt(latency_sec=lat, success=True, observed_keys={"STATION", "SUMMARY"})

        metrics = tracker.compute_metrics(station="ZSPD")
        assert metrics.station == "ZSPD"
        assert metrics.total_requests == 10
        assert metrics.successful_requests == 10
        assert metrics.failed_requests == 0
        assert metrics.success_rate == 1.0
        assert pytest.approx(metrics.latency_p50_sec, 0.05) == 0.55
        assert pytest.approx(metrics.latency_p95_sec, 0.05) == 0.955
        assert metrics.schema_drift_detected is False

    def test_error_categorization(self):
        tracker = ScrapingStabilityTracker()
        tracker.record_attempt(0.5, success=False, error=TimeoutError("HTTPSConnectionPool: Read timed out."))
        tracker.record_attempt(0.2, success=False, error=RuntimeError("401 Client Error: Unauthorized"))
        tracker.record_attempt(0.2, success=False, error=PermissionError("403 Forbidden Access"))
        tracker.record_attempt(0.1, success=False, error=ValueError("Empty response payload"))
        tracker.record_attempt(0.1, success=False, error=json.JSONDecodeError("Parse error", "", 0))

        metrics = tracker.compute_metrics(station="ZSPD")
        assert metrics.total_requests == 5
        assert metrics.successful_requests == 0
        assert metrics.failed_requests == 5
        assert metrics.success_rate == 0.0

        breakdown = json.loads(metrics.failure_breakdown)
        assert breakdown["Timeout"] == 1
        assert breakdown["HTTP_401_Unauthorized"] == 1
        assert breakdown["HTTP_403_Forbidden"] == 1
        assert breakdown["EmptyResponse"] == 1
        assert breakdown["ParseError"] == 1

    def test_schema_drift_detection(self):
        baseline = {"STATION", "SUMMARY", "UNITS"}
        tracker = ScrapingStabilityTracker(baseline_keys=baseline)

        # 1. Matching keys -> no drift
        tracker.record_attempt(0.2, success=True, observed_keys={"STATION", "SUMMARY", "UNITS"})
        assert tracker.drift_detected is False

        # 2. Missing key or new key -> drift detected
        tracker.record_attempt(0.2, success=True, observed_keys={"STATION", "SUMMARY", "NEW_KEY"})
        assert tracker.drift_detected is True

        metrics = tracker.compute_metrics(station="ZSPD")
        assert metrics.schema_drift_detected is True

    def test_append_metrics_to_csv(self, tmp_path):
        tracker = ScrapingStabilityTracker()
        tracker.record_attempt(0.25, success=True, observed_keys={"STATION", "SUMMARY"})
        metrics = tracker.compute_metrics(station="ZSPD")

        target_csv = tmp_path / "nws_wrh_uptime_metrics.csv"
        saved = tracker.append_to_csv(metrics, target_csv)
        assert saved.exists()

        with open(saved, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            assert len(rows) == 1
            assert rows[0]["station"] == "ZSPD"
            assert rows[0]["total_requests"] == "1"
            assert rows[0]["success_rate"] == "1.0"
            assert rows[0]["latency_p50_sec"] == "0.25"
            assert rows[0]["schema_drift_detected"] == "False"
