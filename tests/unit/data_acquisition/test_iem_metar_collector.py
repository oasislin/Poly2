"""
Unit and Contract Tests for IEM METAR Collector and Extreme Group Parser.
"""

import os
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from src.data_acquisition.observation_adapter import ObservationRecord
from src.data_acquisition.iem_metar_collector import (
    IemMetarAdapter,
    parse_metar_dry_bulb,
    parse_metar_extreme_remarks,
)


MOCK_IEM_CSV_PAYLOAD = """station,valid,tmpc,tmpf,dwpc,metar
ZSPD,2026-09-01 00:00,28.00,82.40,25.00,ZSPD 010000Z 12003MPS CAVOK 28/25 Q1009 NOSIG
ZSPD,2026-09-01 00:30,28.00,82.40,25.00,ZSPD 010030Z 14004MPS CAVOK 28/25 Q1009 NOSIG
ZSPD,2026-09-01 06:00,30.00,86.00,25.00,ZSPD 010600Z 09006MPS 9999 SCT020 30/25 Q1008 NOSIG
ZSPD,2026-09-01 12:00,28.00,82.40,25.00,METAR KDEN 011200Z 10004MPS 28/25 Q1009 RMK 10305 20180 403151010 T02830250
"""


class TestMetarRegexParsing:
    """Test parsing of main body and RMK extreme code groups."""

    def test_parse_standard_and_negative_main_body(self):
        assert parse_metar_dry_bulb("METAR ZSPD 010000Z 28/25 Q1009") == 28.0
        assert parse_metar_dry_bulb("ZSPD 010000Z M05/M10 Q1009") == -5.0
        assert parse_metar_dry_bulb("METAR KDEN 010000Z 00/M02 Q1009") == 0.0
        assert parse_metar_dry_bulb("COR METAR ZSPD 010000Z 35/20 Q1009") == 35.0
        assert parse_metar_dry_bulb("INVALID MESSAGE WITHOUT TEMP") is None

    def test_parse_6h_extreme_remarks(self):
        # 10283 -> +28.3°C, 20150 -> +15.0°C
        rem1 = parse_metar_extreme_remarks("METAR KDEN 010600Z 25/15 Q1010 RMK 10283 20150")
        assert rem1["temp_6h_max"] == 28.3
        assert rem1["temp_6h_min"] == 15.0

        # 11050 -> -5.0°C (sign bit 1 = negative)
        rem2 = parse_metar_extreme_remarks("METAR KDEN 010600Z 25/15 Q1010 RMK 11050 21120")
        assert rem2["temp_6h_max"] == -5.0
        assert rem2["temp_6h_min"] == -12.0

    def test_parse_24h_extreme_remarks(self):
        # 403151010 -> 24h max +31.5°C, 24h min -1.0°C
        rem = parse_metar_extreme_remarks("METAR KDEN 010600Z 25/15 Q1010 RMK 403151010")
        assert rem["temp_24h_max"] == 31.5
        assert rem["temp_24h_min"] == -1.0

    def test_parse_high_res_t_group(self):
        # T02830250 -> temp +28.3°C, dewpoint +25.0°C
        rem = parse_metar_extreme_remarks("METAR KDEN 010600Z 28/25 Q1010 RMK T02830250")
        assert rem["temp_high_res"] == 28.3
        assert rem["dewpoint_high_res"] == 25.0

        # T10501120 -> temp -5.0°C, dewpoint -12.0°C
        rem_neg = parse_metar_extreme_remarks("METAR KDEN 010600Z M05/M12 Q1010 RMK T10501120")
        assert rem_neg["temp_high_res"] == -5.0
        assert rem_neg["dewpoint_high_res"] == -12.0


class TestIemMetarAdapter:
    """Test IemMetarAdapter fetching, parsing, coverage metrics, and fallback."""

    @patch("src.data_acquisition.iem_metar_collector.requests.Session.get")
    def test_fetch_and_parse_iem_csv(self, mock_get, tmp_path):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = MOCK_IEM_CSV_PAYLOAD
        mock_get.return_value = resp

        adapter = IemMetarAdapter(storage_dir=str(tmp_path))
        records = adapter.fetch_raw_series(
            station="ZSPD",
            start_date=datetime(2026, 9, 1, 0, 0),
            end_date=datetime(2026, 9, 1, 23, 59),
        )

        assert len(records) == 4
        assert records[0].temp_c == 28.0
        assert records[2].temp_c == 30.0
        # 4th record has high-res temperature from RMK T-group
        assert records[3].temp_c == 28.3
        assert records[3].metadata["extreme_remarks"]["temp_24h_max"] == 31.5

        # Check raw CSV and metadata persistence
        saved_files = os.listdir(str(tmp_path))
        assert any(f.endswith(".csv") for f in saved_files)
        assert any(f.endswith(".meta.json") for f in saved_files)

    def test_zero_celsius_preservation(self):
        """Verify that 0.0°C is strictly preserved and not treated as falsy."""
        # Row with 0.0°C high-res temperature in RMK
        row = {
            "valid": "2026-01-01 00:00",
            "tmpc": "5.0",
            "metar": "METAR KDEN 010000Z 05/00 Q1015 RMK T00000000",
        }
        rec = IemMetarAdapter._parse_csv_row(row)
        assert rec is not None
        assert rec.temp_c == 0.0  # Must be 0.0, not fall back to 5.0
        assert rec.dewpoint_c == 0.0

    def test_calculate_extreme_group_coverage(self):
        adapter = IemMetarAdapter()
        # 3 international METARs without RMK + 1 US METAR with RMK
        records = [
            ObservationRecord(
                timestamp=datetime(2026, 9, 1, 0, 0),
                temp_c=28.0,
                raw_metar="ZSPD 010000Z 28/25 Q1009 NOSIG",
                metadata={"extreme_remarks": {}},
            ),
            ObservationRecord(
                timestamp=datetime(2026, 9, 1, 6, 0),
                temp_c=30.0,
                raw_metar="ZSPD 010600Z 30/25 Q1008 NOSIG",
                metadata={"extreme_remarks": {}},
            ),
            ObservationRecord(
                timestamp=datetime(2026, 9, 1, 12, 0),
                temp_c=28.3,
                raw_metar="KDEN 011200Z 28/25 Q1009 RMK 10305 403151010",
                metadata={"extreme_remarks": {"temp_6h_max": 30.5, "temp_24h_max": 31.5}},
            ),
        ]
        cov = adapter.calculate_extreme_group_coverage(records)
        assert cov["total_records"] == 3
        assert pytest.approx(cov["coverage_6h_max"], 0.01) == 1 / 3
        assert pytest.approx(cov["coverage_24h_max"], 0.01) == 1 / 3

    def test_extract_calendar_day_max_strategies(self):
        adapter = IemMetarAdapter()
        # Sample with 24h extreme group: Strategy B should pick 31.5°C over max(28, 30) = 30°C
        records_with_rmk = [
            ObservationRecord(
                timestamp=datetime(2026, 9, 1, 0, 0),
                temp_c=28.0,
                metadata={"extreme_remarks": {}},
            ),
            ObservationRecord(
                timestamp=datetime(2026, 9, 1, 6, 0),
                temp_c=30.0,
                metadata={"extreme_remarks": {"temp_24h_max": 31.5}},
            ),
        ]
        max_b = adapter.extract_calendar_day_max(records_with_rmk, strategy="B")
        assert max_b == 31.5

        max_a = adapter.extract_calendar_day_max(records_with_rmk, strategy="A")
        assert max_a == 30.0

        # Sample without RMK (ZSPD international): Strategy B gracefully falls back to Strategy A
        records_without_rmk = [
            ObservationRecord(
                timestamp=datetime(2026, 9, 1, 0, 0),
                temp_c=28.0,
                metadata={"extreme_remarks": {}},
            ),
            ObservationRecord(
                timestamp=datetime(2026, 9, 1, 6, 0),
                temp_c=30.0,
                metadata={"extreme_remarks": {}},
            ),
        ]
        assert adapter.extract_calendar_day_max(records_without_rmk, strategy="B") == 30.0
        assert adapter.extract_calendar_day_max(records_without_rmk, strategy="A") == 30.0

    @patch("src.data_acquisition.iem_metar_collector.requests.Session.get")
    def test_retry_on_iem_failure(self, mock_get, tmp_path):
        resp_fail = MagicMock()
        resp_fail.status_code = 502
        resp_fail.raise_for_status.side_effect = Exception("Bad Gateway")

        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.text = MOCK_IEM_CSV_PAYLOAD

        mock_get.side_effect = [resp_fail, resp_ok]

        adapter = IemMetarAdapter(storage_dir=str(tmp_path), max_retries=3, backoff_base=0.01)
        records = adapter.fetch_raw_series(
            station="ZSPD",
            start_date=datetime(2026, 9, 1, 0, 0),
            end_date=datetime(2026, 9, 1, 23, 59),
        )
        assert len(records) == 4
        assert mock_get.call_count == 2


@pytest.mark.skipif(
    os.getenv("RUN_NETWORK_TESTS") != "1",
    reason="Requires RUN_NETWORK_TESTS=1 to run live IEM ASOS API smoke test",
)
def test_live_network_iem():
    """Live network smoke test against real IEM ASOS API for ZSPD."""
    adapter = IemMetarAdapter()
    records = adapter.fetch_raw_series(
        station="ZSPD",
        start_date=datetime(2026, 9, 1, 0, 0),
        end_date=datetime(2026, 9, 1, 23, 59),
    )
    assert len(records) > 0
    # ZSPD METARs should be physically valid temperatures
    for r in records:
        assert r.temp_c is not None
        assert 15.0 <= r.temp_c <= 45.0
        assert r.raw_metar is not None
        assert "ZSPD" in r.raw_metar
