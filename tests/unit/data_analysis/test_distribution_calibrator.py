"""
Unit Tests for Distribution Calibrator, Safety Loader Guard, and Availability & Arbitration Report Generation (v1.0-final).
"""

import json
import os
import pytest
import numpy as np

from src.data_analysis.deviation_decomposer import DailyDiffRecord
from src.data_processing.calendar_day_qc import WindowQcSummary
from src.data_analysis.distribution_calibrator import (
    DistributionCalibrator,
    ReportGenerator,
    load_noise_calibration_config,
)


class TestDistributionCalibrator:
    """Test statistical moments fitting, frozen guard, and JSON export."""

    def test_fit_gaussian_and_quantiles_frozen(self):
        calibrator = DistributionCalibrator()
        np.random.seed(42)
        simulated_res = np.random.normal(loc=0.05, scale=0.20, size=14)

        records = [
            DailyDiffRecord(
                date=f"2026-08-{18+i:02d}" if 18 + i <= 31 else f"2026-09-{i-13:02d}",
                temp_nws_summary=28.0,
                temp_nws_cal_max=27.5 + round(float(simulated_res[i]), 2),
                temp_iem_raw_max=27.5,
                temp_iem_quant_sim=27.5,
                delta_align=0.5,
                delta_quant=0.0,
                delta_res=round(float(simulated_res[i]), 4),
                status="VALID",
            )
            for i in range(14)
        ]

        fit = calibrator.fit_residual_distribution(records)
        assert fit["status"] == "NOT_FOR_PRODUCTION"
        assert fit["frozen"] is True
        assert fit["calibration_window"]["valid_days"] == 14
        assert "raw_provisional_sample_stats_not_for_inference" in fit
        # Extrapolation keys must NOT be present
        assert "empirical_quantiles" not in fit

        raw_stats = fit["raw_provisional_sample_stats_not_for_inference"]
        assert pytest.approx(raw_stats["mu_res"], 0.001) == float(np.mean(simulated_res))
        assert pytest.approx(raw_stats["sigma_res"], 0.001) == float(np.std(simulated_res, ddof=1))

    def test_load_noise_calibration_config_guard(self, tmp_path):
        frozen_file = tmp_path / "frozen_calibration.json"
        data = {
            "status": "NOT_FOR_PRODUCTION",
            "frozen": True,
            "station_id": "ZSPD",
        }
        with open(frozen_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        # Must raise RuntimeError with exact message when trying to load frozen configuration
        with pytest.raises(RuntimeError) as excinfo:
            load_noise_calibration_config(frozen_file)
        assert "Calibration file is frozen and NOT_FOR_PRODUCTION" in str(excinfo.value)

        # Valid non-frozen config loads successfully
        approved_file = tmp_path / "approved_calibration.json"
        approved_data = {"status": "APPROVED_FOR_PRODUCTION", "frozen": False, "station_id": "ZSPD"}
        with open(approved_file, "w", encoding="utf-8") as f:
            json.dump(approved_data, f)

        loaded = load_noise_calibration_config(approved_file)
        assert loaded["station_id"] == "ZSPD"


class TestReportGenerator:
    """Test generating v1.0-final availability & precision arbitration report."""

    def test_generate_markdown_report_v10(self, tmp_path):
        generator = ReportGenerator()
        window_summary = WindowQcSummary(
            total_days=14, valid_days=12, incomplete_days=2, incomplete_ratio=0.1429, is_pipeline_healthy=True
        )
        coverage_meta = {
            "total_records": 639,
            "coverage_6h_max": 0.0,
            "coverage_24h_max": 0.0,
            "coverage_high_res_temp": 0.0,
        }
        rounding_meta = {"is_pure_integer_fahrenheit": True, "quantization_variance": 0.0}
        calibration_data = {
            "calibration_window": {"start": "2026-08-20", "end": "2026-09-02"},
            "raw_provisional_sample_stats_not_for_inference": {"mu_res": 0.0, "sigma_res": 0.0},
        }
        diff_records = [
            DailyDiffRecord(
                date="2026-09-01",
                temp_nws_summary=None,
                temp_nws_cal_max=30.0,
                temp_nws_cal_max_raw_precision="30",
                temp_iem_raw_max=30.0,
                temp_iem_quant_sim=30.0,
                delta_align=None,
                delta_quant=0.0,
                delta_res=0.0,
                status="VALID",
            ),
        ]

        uptime_meta = {"success_rate": 1.0, "latency_p50_sec": 0.294, "latency_p95_sec": 0.303, "schema_drift_detected": False}
        latency_meta = {"sample_count": 20, "median_latency_min": 28.08, "p95_latency_min": 37.05}
        outage_distributions = {"14_days": {"mean_daily_obs_per_hour": 2.05, "mean_cumulative_count_in_window": 28.71, "low_coverage_hours": []}}

        target_report = tmp_path / "zspd-data-availability-report-v1.0.md"
        saved = generator.generate_markdown_report(
            station_id="ZSPD",
            window_summary=window_summary,
            coverage_meta=coverage_meta,
            rounding_meta=rounding_meta,
            calibration_data=calibration_data,
            diff_records=diff_records,
            output_path=target_report,
            uptime_meta=uptime_meta,
            latency_meta=latency_meta,
            outage_distributions=outage_distributions,
        )

        assert os.path.exists(saved)
        content = open(saved, "r", encoding="utf-8").read()
        assert "# 📊 ZSPD NWS WRH 数据可用性与精度裁决报告（v1.2）" in content
        assert "v1.2" in content
        assert "§1 执行摘要与准入裁决" in content
        assert "§2 数据字段精度终审与“幻影量化”废案 (R2 裁决)" in content
        assert "§3 历史留存窗口与边界探顶实测 (R1 裁决)" in content
        assert "§4 抓取稳定性与限流压力测试 (R3 裁决)" in content
        assert "§5 更新时延" in content
        assert "§6 上游架构依赖与双活容灾审计 (R5 裁决)" in content
        assert "§7 每日对账与代数分解实测明细表" in content
