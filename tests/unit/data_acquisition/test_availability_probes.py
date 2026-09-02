"""
Unit & Live Smoke Tests for NWS WRH Service Availability Probes (Probe 1 Retention & Probe 2 Precision).
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from scripts.probe_nws_wrh_availability import NwsAvailabilityProber


class TestAvailabilityProbes:
    """Test retention window probing with record count validity and field precision auditing."""

    def test_probe_retention_window_complete(self):
        prober = NwsAvailabilityProber(station="ZSPD")

        # 48 records returned for 1 day -> 100% complete
        mock_response = {
            "SUMMARY": {"RESPONSE_MESSAGE": "OK", "HTTP_STATUS": 200},
            "STATION": [
                {
                    "STID": "ZSPD",
                    "OBSERVATIONS": {
                        "date_time": [f"2026-08-25T{h:02d}:{m:02d}:00Z" for h in range(24) for m in [0, 30]],
                        "air_temp_set_1": [31.0] * 48,
                    },
                }
            ],
        }

        with patch.object(prober.adapter, "_execute_request_with_retry", return_value=mock_response):
            results = prober.probe_retention_window(test_days=[7], units=["metric"])

        assert len(results) == 1
        res = results[0]
        assert res["is_data_available"] is True
        assert res["returned_records_count"] == 48
        assert res["expected_records_count"] == 48
        assert res["coverage_ratio"] == 1.0
        assert res["completeness_status"] == "COMPLETE"

    def test_probe_retention_window_empty_payload(self):
        prober = NwsAvailabilityProber(station="ZSPD")

        mock_empty_response = {
            "SUMMARY": {"RESPONSE_MESSAGE": "OK", "HTTP_STATUS": 200},
            "STATION": [
                {
                    "STID": "ZSPD",
                    "OBSERVATIONS": {
                        "date_time": [],
                        "air_temp_set_1": [],
                    },
                }
            ],
        }

        with patch.object(prober.adapter, "_execute_request_with_retry", return_value=mock_empty_response):
            results = prober.probe_retention_window(test_days=[400], units=["metric"])

        assert len(results) == 1
        res = results[0]
        assert res["is_data_available"] is False
        assert res["returned_records_count"] == 0
        assert res["completeness_status"] == "EMPTY_PAYLOAD"

    def test_probe_retention_window_sparse_data(self):
        prober = NwsAvailabilityProber(station="ZSPD")

        # Only 10 records returned out of 48 expected -> sparse data (< 80% coverage)
        mock_sparse_response = {
            "SUMMARY": {"RESPONSE_MESSAGE": "OK", "HTTP_STATUS": 200},
            "STATION": [
                {
                    "STID": "ZSPD",
                    "OBSERVATIONS": {
                        "date_time": [f"2026-08-25T{h:02d}:00:00Z" for h in range(10)],
                        "air_temp_set_1": [31.0] * 10,
                    },
                }
            ],
        }

        with patch.object(prober.adapter, "_execute_request_with_retry", return_value=mock_sparse_response):
            results = prober.probe_retention_window(test_days=[730], units=["metric"])

        assert len(results) == 1
        res = results[0]
        assert res["is_data_available"] is False
        assert res["returned_records_count"] == 10
        assert res["coverage_ratio"] == pytest.approx(10 / 48, 0.001)
        assert res["completeness_status"] == "SPARSE_DATA"

    def test_probe_station_metadata_origin(self):
        prober = NwsAvailabilityProber(station="ZSPD")
        meta = prober.probe_station_metadata_origin()
        assert meta["station"] == "ZSPD"
        assert meta["synoptic_archive_start"] == "2018-11-01"
        assert "2018-11-01" in meta["origin_clarification"]
        assert "database ingestion inception" in meta["origin_clarification"]

    def test_audit_field_precision(self, tmp_path):
        prober = NwsAvailabilityProber(station="ZSPD", storage_dir=str(tmp_path))

        metric_file = tmp_path / "ZSPD_20260901_metric_20260901T000000Z.json"
        english_file = tmp_path / "ZSPD_20260901_english_20260901T000000Z.json"

        metric_payload = {
            "unit_type": "metric",
            "response": {
                "STATION": [
                    {
                        "OBSERVATIONS": {
                            "air_temp_set_1": [28.0, 29.0, 30.0, 31.0],
                        }
                    }
                ]
            },
        }
        english_payload = {
            "unit_type": "english",
            "response": {
                "STATION": [
                    {
                        "OBSERVATIONS": {
                            "air_temp_set_1": [82.0, 84.0, 86.0, 88.0],
                        }
                    }
                ]
            },
        }

        with open(metric_file, "w", encoding="utf-8") as f:
            json.dump(metric_payload, f)
        with open(english_file, "w", encoding="utf-8") as f:
            json.dump(english_payload, f)

        audit_res = prober.audit_field_precision()
        assert audit_res["total_files_audited"] == 2
        assert audit_res["metric_sample_count"] == 4
        assert audit_res["metric_integer_pct"] == 1.0
        assert audit_res["english_sample_count"] == 4
        assert audit_res["english_pure_integer_pct"] == 1.0

    def test_record_uptime_metrics_mocked(self, tmp_path):
        prober = NwsAvailabilityProber(station="ZSPD")
        mock_response = {
            "SUMMARY": {"RESPONSE_MESSAGE": "OK", "HTTP_STATUS": 200},
            "STATION": [{"STID": "ZSPD", "OBSERVATIONS": {"date_time": ["2026-09-02T12:00:00Z"]}}],
        }
        target_csv = tmp_path / "test_uptime.csv"

        with patch.object(prober.adapter, "fetch_raw_json", return_value=mock_response):
            metrics_dict = prober.record_uptime_metrics(output_csv=str(target_csv), num_requests=3)

        assert metrics_dict["total_requests"] == 3
        assert metrics_dict["successful_requests"] == 3
        assert metrics_dict["success_rate"] == 1.0
        assert target_csv.exists()


@pytest.mark.skipif(
    os.getenv("RUN_NETWORK_TESTS") != "1",
    reason="Network tests disabled by default. Run with RUN_NETWORK_TESTS=1",
)
def test_live_network_retention_probe():
    """Live smoke test executing retention depth probing against real Synoptic MesoWest servers."""
    prober = NwsAvailabilityProber(station="ZSPD")
    results = prober.probe_retention_window(test_days=[7, 365, 730], units=["metric"])
    assert len(results) == 3
    for res in results:
        assert res["http_status"] == 200
        assert res["completeness_status"] == "COMPLETE"
        assert res["is_data_available"] is True
        assert res["returned_records_count"] >= 40
