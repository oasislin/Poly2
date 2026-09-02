"""
NWS WRH / Synoptic API Rate Limit & Concurrency Stress Tester.
Evaluates API throttling thresholds, 429 rate limit behaviors, and recovery latencies at high QPS.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import requests

from src.data_acquisition.nws_wrh_collector import NwsWrhAdapter

logger = logging.getLogger(__name__)


@dataclass
class RateLimitStressResult:
    """Strongly-typed outcome of a rate-limit stress test run."""
    station: str
    target_qps: float
    test_duration_sec: float
    total_requests_sent: int
    http_200_count: int
    http_429_count: int
    timeout_count: int
    error_count: int
    success_rate: float
    effective_qps: float
    latency_p50_sec: float
    latency_p95_sec: float
    first_429_trigger_index: Optional[int] = None
    recovery_time_sec: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for serialization and reporting."""
        return {
            "station": self.station,
            "target_qps": self.target_qps,
            "test_duration_sec": round(self.test_duration_sec, 2),
            "total_requests_sent": self.total_requests_sent,
            "http_200_count": self.http_200_count,
            "http_429_count": self.http_429_count,
            "timeout_count": self.timeout_count,
            "error_count": self.error_count,
            "success_rate": round(self.success_rate, 4),
            "effective_qps": round(self.effective_qps, 2),
            "latency_p50_sec": round(self.latency_p50_sec, 3),
            "latency_p95_sec": round(self.latency_p95_sec, 3),
            "first_429_trigger_index": self.first_429_trigger_index,
            "recovery_time_sec": (
                round(self.recovery_time_sec, 3) if self.recovery_time_sec is not None else None
            ),
        }


class RateLimitStressTester:
    """Sends controlled concurrent bursts of API requests to evaluate rate limits."""

    def __init__(self, adapter: Optional[NwsWrhAdapter] = None, max_workers: int = 10):
        self.adapter = adapter or NwsWrhAdapter()
        self.max_workers = max_workers

    def _execute_single_probe(
        self, params: Dict[str, Any], req_index: int
    ) -> Tuple[int, int, float, Optional[str]]:
        """Send a single probe request and return (req_index, status_code, latency, error)."""
        t0 = time.perf_counter()
        code = 500
        err_msg = None
        try:
            resp = self.adapter.session.get(
                self.adapter.BASE_URL,
                params=params,
                timeout=5.0,
            )
            code = resp.status_code
        except requests.exceptions.Timeout as e:
            code = 504
            err_msg = str(e)
        except requests.exceptions.RequestException as e:
            code = getattr(e.response, "status_code", 500) if getattr(e, "response", None) else 500
            err_msg = str(e)
        except Exception as e:
            code = 500
            err_msg = str(e)
        finally:
            latency = time.perf_counter() - t0

        return req_index, code, latency, err_msg

    @staticmethod
    def _aggregate_results(
        probe_records: List[Tuple[int, int, float, Optional[str]]],
        station: str,
        target_qps: float,
        total_elapsed: float,
    ) -> RateLimitStressResult:
        """Aggregate probe outcomes into a strongly-typed RateLimitStressResult."""
        sorted_records = sorted(probe_records, key=lambda x: x[0])
        latencies = [r[2] for r in sorted_records]
        count_200 = sum(1 for r in sorted_records if r[1] == 200)
        count_429 = sum(1 for r in sorted_records if r[1] == 429)
        count_timeout = sum(1 for r in sorted_records if r[1] == 504)
        count_error = len(sorted_records) - count_200 - count_429 - count_timeout

        first_429_idx: Optional[int] = None
        recovery_time: Optional[float] = None
        seen_429 = False

        for req_idx, code, lat, _ in sorted_records:
            if code == 429 and not seen_429:
                first_429_idx = req_idx
                seen_429 = True
            elif seen_429 and code == 200 and recovery_time is None:
                recovery_time = lat

        p50 = float(np.percentile(latencies, 50)) if latencies else 0.0
        p95 = float(np.percentile(latencies, 95)) if latencies else 0.0

        return RateLimitStressResult(
            station=station,
            target_qps=target_qps,
            test_duration_sec=total_elapsed,
            total_requests_sent=len(sorted_records),
            http_200_count=count_200,
            http_429_count=count_429,
            timeout_count=count_timeout,
            error_count=count_error,
            success_rate=count_200 / len(sorted_records) if sorted_records else 0.0,
            effective_qps=len(sorted_records) / max(0.001, total_elapsed),
            latency_p50_sec=p50,
            latency_p95_sec=p95,
            first_429_trigger_index=first_429_idx,
            recovery_time_sec=recovery_time,
        )

    def run_stress_test(
        self,
        target_qps: float = 5.0,
        duration_sec: float = 60.0,
        station: str = "ZSPD",
    ) -> RateLimitStressResult:
        """Run threaded request burst at target QPS and measure concurrency / 429 behavior."""
        params = {"stid": station, "token": self.adapter.token, "recent": 60, "units": "metric"}
        interval = 1.0 / max(0.1, target_qps)
        total_target_requests = max(1, int(target_qps * duration_sec))

        probe_records: List[Tuple[int, int, float, Optional[str]]] = []
        t_start = time.perf_counter()

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            for idx in range(1, total_target_requests + 1):
                futures.append(executor.submit(self._execute_single_probe, params, idx))
                time.sleep(interval)

            for fut in as_completed(futures):
                probe_records.append(fut.result())

        total_elapsed = max(0.001, time.perf_counter() - t_start)
        return self._aggregate_results(probe_records, station, target_qps, total_elapsed)
