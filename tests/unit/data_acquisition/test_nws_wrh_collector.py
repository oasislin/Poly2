"""
Unit and Contract Tests for NWS WRH Collector and BaseObservationAdapter.
"""

import json
import os
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from src.data_acquisition.observation_adapter import (
    BaseObservationAdapter,
    ObservationRecord,
    WundergroundAdapter,
)
from src.data_acquisition.nws_wrh_collector import NwsWrhAdapter


# Static Mock Fixtures representing real Synoptic MesoWest API payloads
MOCK_SYNOPTIC_METRIC_PAYLOAD = {
    "STATION": [
        {
            "STID": "ZSPD",
            "NAME": "Shanghai Pudong International Airport",
            "TIMEZONE": "Asia/Shanghai",
            "OBSERVATIONS": {
                "date_time": [
                    "2026-09-02T12:30:00+0800",
                    "2026-09-02T13:00:00+0800",
                    "2026-09-02T13:30:00+0800",
                ],
                "air_temp_set_1": [27.0, 26.0, 25.0],
                "dew_point_temperature_set_1d": [25.0, 26.0, 25.0],
                "metar_set_1": [
                    "METAR ZSPD 020430Z 10008MPS 9999 27/25 Q1009 NOSIG",
                    "METAR ZSPD 020500Z 10009MPS 9999 26/26 Q1009 NOSIG",
                    "METAR ZSPD 020530Z 10008MPS 9999 25/25 Q1009 NOSIG",
                ],
            },
        }
    ],
    "SUMMARY": {
        "RESPONSE_CODE": 1,
        "RESPONSE_MESSAGE": "OK",
    },
    "UNITS": {
        "air_temp": "Celsius",
    },
}

MOCK_SYNOPTIC_ENGLISH_PAYLOAD = {
    "STATION": [
        {
            "STID": "ZSPD",
            "NAME": "Shanghai Pudong International Airport",
            "TIMEZONE": "Asia/Shanghai",
            "OBSERVATIONS": {
                "date_time": [
                    "2026-09-02T12:30:00+0800",
                    "2026-09-02T13:00:00+0800",
                    "2026-09-02T13:30:00+0800",
                ],
                "air_temp_set_1": [80.6, 78.8, 77.0],
                "dew_point_temperature_set_1": [77.0, 78.8, 77.0],
                "metar_set_1": [
                    "METAR ZSPD 020430Z 10008MPS 9999 27/25 Q1009 NOSIG",
                    "METAR ZSPD 020500Z 10009MPS 9999 26/26 Q1009 NOSIG",
                    "METAR ZSPD 020530Z 10008MPS 9999 25/25 Q1009 NOSIG",
                ],
            },
        }
    ],
    "SUMMARY": {
        "RESPONSE_CODE": 1,
        "RESPONSE_MESSAGE": "OK",
    },
    "UNITS": {
        "air_temp": "Fahrenheit",
    },
}


class TestObservationAdapterContract:
    """Test BaseObservationAdapter contract and Wunderground placeholder."""

    def test_wunderground_adapter_raises_not_implemented(self):
        adapter = WundergroundAdapter()
        with pytest.raises(NotImplementedError) as excinfo:
            adapter.fetch_raw_series(
                station="ZSPD",
                start_date=datetime(2026, 9, 1),
                end_date=datetime(2026, 9, 2),
            )
        assert "WundergroundAdapter is reserved" in str(excinfo.value)

    def test_precision_metadata_contract(self):
        adapter = NwsWrhAdapter()
        meta = adapter.get_source_precision_metadata()
        assert isinstance(meta, dict)
        assert "primary_unit" in meta
        assert "supports_dual_probe" in meta
        assert meta["supports_dual_probe"] is True


class TestNwsWrhAdapterParsingAndProbing:
    """Test NwsWrhAdapter parsing, dual probe matching, and retry mechanics."""

    @patch("src.data_acquisition.nws_wrh_collector.requests.Session.get")
    def test_fetch_dual_probe_aligned(self, mock_get, tmp_path):
        # Configure mock responses for SI and English requests
        resp_metric = MagicMock()
        resp_metric.status_code = 200
        resp_metric.json.return_value = MOCK_SYNOPTIC_METRIC_PAYLOAD

        resp_english = MagicMock()
        resp_english.status_code = 200
        resp_english.json.return_value = MOCK_SYNOPTIC_ENGLISH_PAYLOAD

        mock_get.side_effect = [resp_metric, resp_english]

        adapter = NwsWrhAdapter(storage_dir=str(tmp_path))
        records = adapter.fetch_raw_series(
            station="ZSPD",
            start_date=datetime(2026, 9, 2, 0, 0),
            end_date=datetime(2026, 9, 2, 23, 59),
        )

        assert len(records) == 3
        r0 = records[0]
        assert isinstance(r0, ObservationRecord)
        assert r0.temp_c == 27.0
        assert r0.temp_f == 80.6
        assert r0.dewpoint_c == 25.0
        assert "METAR ZSPD 020430Z" in r0.raw_metar

        # Check calendar day max
        max_temp = adapter.extract_calendar_day_max(records, timezone_str="Asia/Shanghai")
        assert max_temp == 27.0

        # Verify raw persistence files created in storage_dir
        saved_files = os.listdir(str(tmp_path))
        assert any("metric" in f for f in saved_files)
        assert any("english" in f for f in saved_files)

    @patch("src.data_acquisition.nws_wrh_collector.requests.Session.get")
    def test_retry_on_network_failure(self, mock_get, tmp_path):
        # Fail twice with 500 then succeed
        resp_fail = MagicMock()
        resp_fail.status_code = 500
        resp_fail.raise_for_status.side_effect = Exception("Server Error")

        resp_ok_m = MagicMock()
        resp_ok_m.status_code = 200
        resp_ok_m.json.return_value = MOCK_SYNOPTIC_METRIC_PAYLOAD

        resp_ok_e = MagicMock()
        resp_ok_e.status_code = 200
        resp_ok_e.json.return_value = MOCK_SYNOPTIC_ENGLISH_PAYLOAD

        mock_get.side_effect = [resp_fail, resp_fail, resp_ok_m, resp_ok_e]

        adapter = NwsWrhAdapter(storage_dir=str(tmp_path), max_retries=3, backoff_base=0.01)
        records = adapter.fetch_raw_series(
            station="ZSPD",
            start_date=datetime(2026, 9, 2, 0, 0),
            end_date=datetime(2026, 9, 2, 23, 59),
        )
        assert len(records) == 3
        assert mock_get.call_count == 4

    @patch("src.data_acquisition.nws_wrh_collector.requests.Session.get")
    def test_exceed_max_retries_raises(self, mock_get, tmp_path):
        resp_fail = MagicMock()
        resp_fail.status_code = 503
        resp_fail.raise_for_status.side_effect = Exception("Unavailable")

        mock_get.return_value = resp_fail

        adapter = NwsWrhAdapter(storage_dir=str(tmp_path), max_retries=2, backoff_base=0.01)
        with pytest.raises(RuntimeError) as excinfo:
            adapter.fetch_raw_series(
                station="ZSPD",
                start_date=datetime(2026, 9, 2, 0, 0),
                end_date=datetime(2026, 9, 2, 23, 59),
            )
        assert "Failed to fetch NWS WRH data after 2 retries" in str(excinfo.value)
        assert excinfo.value.__cause__ is not None

    @patch("src.data_acquisition.nws_wrh_collector.requests.Session.get")
    def test_nws_wrh_adapter_with_tracker(self, mock_get, tmp_path):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "SUMMARY": {"RESPONSE_MESSAGE": "OK", "HTTP_STATUS": 200},
            "STATION": [{"STID": "ZSPD", "OBSERVATIONS": {"date_time": [], "air_temp_set_1": []}}],
        }
        mock_get.return_value = mock_resp

        mock_tracker = MagicMock()
        adapter = NwsWrhAdapter(storage_dir=str(tmp_path), tracker=mock_tracker)
        adapter.fetch_raw_json({"stid": "ZSPD"})

        assert mock_tracker.record_attempt.called
        assert mock_tracker.record_attempt.call_args[1]["success"] is True

    def test_high_resolution_t_group_parsing_eliminates_integer_artifact(self):
        """Verify that raw METAR T-group remarks (e.g. T0261) override coarse integer-Celsius."""
        m_obs = {
            "air_temp_set_1": [27.0],  # Coarse integer Celsius -> 80.60°F artifact
            "metar_set_1": ["KORD 121851Z 21022G33KT 10SM 26/13 A2987 RMK AO2 T02610133"],  # +26.1°C -> 78.98°F
        }
        e_match = {"temp_f": 80.6}
        rec = NwsWrhAdapter._create_observation_record(
            idx=0,
            dt_str="2026-04-12T13:51:00",
            m_obs=m_obs,
            e_match=e_match,
        )
        assert rec.temp_c == 26.1
        assert rec.temp_f == 78.98
        assert rec.temp_f != 80.60  # Artifact successfully eliminated!


@pytest.mark.skipif(
    os.getenv("RUN_NETWORK_TESTS") != "1",
    reason="Requires RUN_NETWORK_TESTS=1 to run live NWS WRH Synoptic API smoke test",
)
def test_live_network_probe():
    """Live network smoke test against real Synoptic API for ZSPD."""
    adapter = NwsWrhAdapter()
    records = adapter.fetch_recent(station="ZSPD", recent_minutes=120)
    assert len(records) > 0
    latest = records[-1]
    assert latest.temp_c is not None
    assert latest.temp_f is not None
    # Check that temp_c and temp_f are physically plausible temperatures for Shanghai (0°C to 45°C)
    assert 0.0 <= latest.temp_c <= 45.0
    assert 32.0 <= latest.temp_f <= 113.0
