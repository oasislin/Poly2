"""
Integration and Live Network Smoke Tests for ZSPD METAR vs NWS WRH Comparison Pipeline.
"""

from datetime import datetime, date, timezone, timedelta
import os
import pytest
from pathlib import Path
import json

from src.data_acquisition.observation_adapter import ObservationRecord
from src.data_processing.calendar_day_qc import CalendarDaySlicer, ObservationQualityControl
from src.data_analysis.deviation_decomposer import DeviationDecomposer, calibrate_empirical_rounding_operator
from src.data_analysis.distribution_calibrator import DistributionCalibrator, ReportGenerator
from scripts.run_zspd_comparison import run_comparison_pipeline


class TestZspdComparisonPipelineIntegration:
    """Test end-to-end comparison pipeline with mock data."""

    def test_pipeline_execution_mocked(self, tmp_path):
        out_csv = tmp_path / "zspd_daily_diff.csv"
        out_json = tmp_path / "zspd_metar_noise_calibration.json"
        out_report = tmp_path / "zspd_temperature_comparison_report.md"

        # Run pipeline with a mock data injector or test arguments
        exit_code = run_comparison_pipeline(
            station="ZSPD",
            days=3,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 3),
            output_csv=str(out_csv),
            output_json=str(out_json),
            output_report=str(out_report),
            mock_mode=True,
        )

        assert exit_code == 0
        assert os.path.exists(out_csv)
        assert os.path.exists(out_json)
        assert os.path.exists(out_report)

        with open(out_json, "r", encoding="utf-8") as f:
            cal_data = json.load(f)
            assert cal_data["station_id"] == "ZSPD"
            assert cal_data["status"] == "NOT_FOR_PRODUCTION"
            assert cal_data["frozen"] is True
            assert "raw_provisional_sample_stats_not_for_inference" in cal_data

        with open(out_report, "r", encoding="utf-8") as f:
            report_text = f.read()
            assert "NWS WRH 数据可用性与精度裁决报告（v1.2）" in report_text


@pytest.mark.skipif(
    os.getenv("RUN_NETWORK_TESTS") != "1",
    reason="Network tests disabled by default. Run with RUN_NETWORK_TESTS=1",
)
def test_live_network_pipeline(tmp_path):
    """Live smoke test executing end-to-end pipeline against real IEM and NWS WRH servers."""
    out_csv = tmp_path / "live_zspd_daily_diff.csv"
    out_json = tmp_path / "live_zspd_metar_noise_calibration.json"
    out_report = tmp_path / "live_zspd_report.md"

    # Test recent 3 days on real networks
    end_d = datetime.now(timezone.utc).date()
    start_d = end_d - timedelta(days=2)

    exit_code = run_comparison_pipeline(
        station="ZSPD",
        days=3,
        start_date=start_d,
        end_date=end_d,
        output_csv=str(out_csv),
        output_json=str(out_json),
        output_report=str(out_report),
        mock_mode=False,
    )

    assert exit_code == 0
    assert os.path.exists(out_csv)
    assert os.path.exists(out_json)
    assert os.path.exists(out_report)
