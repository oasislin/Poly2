"""
Scraping Stability & Uptime Metrics Tracker for NWS WRH and External Meteorological APIs.
Quantifies request latency percentiles, error categorizations, and JSON schema drift.
"""

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class UptimeMetricsRecord:
    """Strongly-typed container for service stability and latency metrics."""
    timestamp_utc: str
    station: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    success_rate: float
    latency_p50_sec: float
    latency_p95_sec: float
    failure_breakdown: str
    schema_drift_detected: bool

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for export."""
        return {
            "timestamp_utc": self.timestamp_utc,
            "station": self.station,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": self.success_rate,
            "latency_p50_sec": self.latency_p50_sec,
            "latency_p95_sec": self.latency_p95_sec,
            "failure_breakdown": self.failure_breakdown,
            "schema_drift_detected": self.schema_drift_detected,
        }


class ScrapingStabilityTracker:
    """
    Tracks API execution attempts, calculates latency percentiles,
    categorizes errors, and detects schema key drift.
    """

    CSV_HEADERS = [
        "timestamp_utc",
        "station",
        "total_requests",
        "successful_requests",
        "failed_requests",
        "success_rate",
        "latency_p50_sec",
        "latency_p95_sec",
        "failure_breakdown",
        "schema_drift_detected",
    ]

    def __init__(self, baseline_keys: Optional[Set[str]] = None):
        self.latencies: List[float] = []
        self.successes: int = 0
        self.failures: int = 0
        self.failure_counts: Dict[str, int] = {}
        self.baseline_keys: Optional[Set[str]] = baseline_keys
        self.drift_detected: bool = False
        self.drift_diffs: List[str] = []

    @staticmethod
    def categorize_error(error: Exception) -> str:
        """Classify exceptions (including wrapped exceptions) into standardized failure buckets."""
        # Unpack wrapped cause if present
        all_err_text = f"{error} {getattr(error, '__cause__', '')} {type(error).__name__}".lower()

        if "timeout" in all_err_text or "timed out" in all_err_text:
            return "Timeout"
        if "401" in all_err_text or "unauthorized" in all_err_text:
            return "HTTP_401_Unauthorized"
        if "403" in all_err_text or "forbidden" in all_err_text:
            return "HTTP_403_Forbidden"
        if "empty" in all_err_text or "no data" in all_err_text:
            return "EmptyResponse"
        if "json" in all_err_text or "parse" in all_err_text:
            return "ParseError"
        return type(error).__name__

    def record_attempt(
        self,
        latency_sec: float,
        success: bool,
        error: Optional[Exception] = None,
        observed_keys: Optional[Set[str]] = None,
    ) -> None:
        """Record single request attempt and update trackers."""
        self.latencies.append(latency_sec)
        if success:
            self.successes += 1
            if observed_keys is not None:
                self._check_schema_drift(observed_keys)
        else:
            self.failures += 1
            category = self.categorize_error(error) if error else "UnknownError"
            self.failure_counts[category] = self.failure_counts.get(category, 0) + 1

    def _check_schema_drift(self, observed_keys: Set[str]) -> None:
        """Diff observed schema keys against established baseline."""
        if self.baseline_keys is None:
            self.baseline_keys = set(observed_keys)
        else:
            diff = self.baseline_keys ^ observed_keys
            if diff:
                self.drift_detected = True
                diff_msg = f"Key diff: {diff}"
                self.drift_diffs.append(diff_msg)
                logger.warning(f"Schema drift detected: {diff_msg}")

    def compute_metrics(self, station: str) -> UptimeMetricsRecord:
        """Compute aggregated metrics snapshot."""
        total = self.successes + self.failures
        rate = round(self.successes / total, 4) if total > 0 else 0.0

        if self.latencies:
            p50 = float(np.percentile(self.latencies, 50))
            p95 = float(np.percentile(self.latencies, 95))
        else:
            p50, p95 = 0.0, 0.0

        return UptimeMetricsRecord(
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            station=station,
            total_requests=total,
            successful_requests=self.successes,
            failed_requests=self.failures,
            success_rate=rate,
            latency_p50_sec=round(p50, 3),
            latency_p95_sec=round(p95, 3),
            failure_breakdown=json.dumps(self.failure_counts),
            schema_drift_detected=self.drift_detected,
        )

    def append_to_csv(
        self,
        record: UptimeMetricsRecord,
        output_path: Union[str, Path] = "data/processed/nws_wrh_uptime_metrics.csv",
    ) -> Path:
        """Append UptimeMetricsRecord to CSV file with automatic header generation."""
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        file_exists = target.exists()

        with open(target, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.CSV_HEADERS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(record.to_dict())

        return target
