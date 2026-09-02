"""
Unit & Live Smoke Tests for Rate Limit Stress Tester.
"""

import os
from unittest.mock import patch
import pytest

from src.data_acquisition.rate_limit_stress_tester import RateLimitStressTester, RateLimitStressResult


class TestRateLimitStressTester:
    """Test burst request generation, status code aggregation, and 429 recovery calculations."""

    def test_run_stress_test_all_200(self):
        tester = RateLimitStressTester()

        # Mock 10 successful requests
        def mock_probe(params, req_index):
            return req_index, 200, 0.05, None

        with patch.object(tester, "_execute_single_probe", side_effect=mock_probe):
            res = tester.run_stress_test(target_qps=5.0, duration_sec=2.0)

        assert res.total_requests_sent == 10
        assert res.http_200_count == 10
        assert res.http_429_count == 0
        assert res.success_rate == 1.0
        assert res.first_429_trigger_index is None
        assert res.recovery_time_sec is None
        assert res.latency_p50_sec == pytest.approx(0.05, 0.01)

    def test_run_stress_test_with_429_and_recovery(self):
        tester = RateLimitStressTester()

        # Mock sequence: 3x 200, 2x 429, 5x 200
        responses = [
            (200, 0.05, None),
            (200, 0.05, None),
            (200, 0.05, None),
            (429, 0.02, "Too Many Requests"),
            (429, 0.02, "Too Many Requests"),
            (200, 0.05, None),
            (200, 0.05, None),
            (200, 0.05, None),
            (200, 0.05, None),
            (200, 0.05, None),
        ]

        def mock_probe(params, req_index):
            code, lat, err = responses[req_index - 1]
            return req_index, code, lat, err

        with patch.object(tester, "_execute_single_probe", side_effect=mock_probe):
            res = tester.run_stress_test(target_qps=5.0, duration_sec=2.0)

        assert res.total_requests_sent == 10
        assert res.http_200_count == 8
        assert res.http_429_count == 2
        assert res.success_rate == 0.8
        assert res.first_429_trigger_index == 4
        assert res.recovery_time_sec is not None
        assert res.recovery_time_sec > 0.0

    def test_to_dict_formatting(self):
        res = RateLimitStressResult(
            station="ZSPD",
            target_qps=5.0,
            test_duration_sec=10.0,
            total_requests_sent=50,
            http_200_count=48,
            http_429_count=2,
            timeout_count=0,
            error_count=0,
            success_rate=0.96,
            effective_qps=4.95,
            latency_p50_sec=0.25,
            latency_p95_sec=0.40,
            first_429_trigger_index=25,
            recovery_time_sec=0.85,
        )
        d = res.to_dict()
        assert d["station"] == "ZSPD"
        assert d["total_requests_sent"] == 50
        assert d["success_rate"] == 0.96
        assert d["first_429_trigger_index"] == 25
        assert d["recovery_time_sec"] == 0.85


@pytest.mark.skipif(
    os.getenv("RUN_NETWORK_TESTS") != "1",
    reason="Network tests disabled by default. Run with RUN_NETWORK_TESTS=1",
)
def test_live_network_rate_limit_stress_test():
    """Live smoke test executing 5 req/s burst against Synoptic servers."""
    tester = RateLimitStressTester()
    res = tester.run_stress_test(target_qps=5.0, duration_sec=2.0, station="ZSPD")
    assert res.total_requests_sent == 10
    assert res.http_200_count >= 8
    assert res.http_429_count == 0
