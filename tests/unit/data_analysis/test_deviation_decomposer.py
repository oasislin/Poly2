"""
Unit Tests for Deviation Decomposer and CSV Export (R2 Precision Verdict: Direct Reconciler).
"""

import csv
import os
import pytest
from datetime import datetime

from src.data_acquisition.observation_adapter import ObservationRecord
from src.data_analysis.deviation_decomposer import (
    DailyDiffRecord,
    DeviationDecomposer,
    calibrate_empirical_rounding_operator,
)


class TestEmpiricalRoundingCalibration:
    """Test empirical operator calibration and deprecated model tag."""

    def test_calibrate_empirical_operator_from_records(self):
        # Records matching pure integer F
        probe_records = [
            ObservationRecord(timestamp=datetime(2026, 9, 1, 12, 0), temp_c=27.0, temp_f=81.0),
            ObservationRecord(timestamp=datetime(2026, 9, 1, 13, 0), temp_c=26.0, temp_f=79.0),
            ObservationRecord(timestamp=datetime(2026, 9, 1, 14, 0), temp_c=25.0, temp_f=77.0),
        ]
        cal = calibrate_empirical_rounding_operator(probe_records)
        assert cal.is_pure_integer_fahrenheit is True
        assert cal.sample_count == 3
        assert cal.quantization_variance == 0.0
        assert cal.to_dict()["deprecated"] == "phantom_model"


class TestDeviationDecomposerAlgebra:
    """Test exact direct decomposition: Delta_Total == Delta_quant (0.0) + Delta_res."""

    def test_algebraic_identity_valid_day(self):
        decomposer = DeviationDecomposer()
        # Direct reconciliation:
        # T_iem_raw = 26.0, T_nws_cal_max = 26.5
        # Delta_quant = 0.0, Delta_res = 26.5 - 26.0 = 0.50
        record = decomposer.decompose_daily_diff(
            date_str="2026-09-01",
            temp_nws_cal_max=26.5,
            temp_iem_raw_max=26.0,
            temp_nws_summary=27.0,
            status="VALID",
        )

        assert record.date == "2026-09-01"
        assert record.temp_nws_summary == 27.0
        assert record.temp_nws_cal_max == 26.5
        assert record.temp_iem_raw_max == 26.0
        assert record.temp_iem_quant_sim == 26.0

        # Check deltas
        assert pytest.approx(record.delta_align, 0.001) == 0.5  # 27.0 - 26.5
        assert record.delta_quant == 0.0
        assert pytest.approx(record.delta_res, 0.001) == 0.50
        # Verify algebraic identity
        delta_total = record.temp_nws_cal_max - record.temp_iem_raw_max
        assert pytest.approx(record.delta_quant + record.delta_res, 0.0001) == delta_total

    def test_incomplete_day_handling(self):
        decomposer = DeviationDecomposer()
        record = decomposer.decompose_daily_diff(
            date_str="2026-09-02",
            temp_nws_cal_max=None,
            temp_iem_raw_max=28.0,
            temp_nws_summary=None,
            status="INCOMPLETE_DATA",
        )
        assert record.status == "INCOMPLETE_DATA"
        assert record.temp_nws_cal_max is None
        assert record.delta_res is None
        assert record.delta_quant == 0.0


class TestDailyDiffCsvExport:
    """Test exporting daily diff records to formatted CSV."""

    def test_export_to_csv(self, tmp_path):
        decomposer = DeviationDecomposer()
        records = [
            DailyDiffRecord(
                date="2026-09-01",
                temp_nws_summary=28.0,
                temp_nws_cal_max=27.8,
                temp_iem_raw_max=27.0,
                temp_iem_quant_sim=27.0,
                delta_align=0.2,
                delta_quant=0.0,
                delta_res=0.8,
                status="VALID",
                temp_nws_cal_max_raw_precision="27.8",
            ),
            DailyDiffRecord(
                date="2026-09-02",
                temp_nws_summary=None,
                temp_nws_cal_max=None,
                temp_iem_raw_max=25.0,
                temp_iem_quant_sim=25.0,
                delta_align=None,
                delta_quant=0.0,
                delta_res=None,
                status="INCOMPLETE_DATA",
                temp_nws_cal_max_raw_precision=None,
            ),
        ]

        target_file = tmp_path / "zspd_daily_diff.csv"
        saved_path = decomposer.export_to_csv(records, target_file)
        assert os.path.exists(saved_path)

        with open(saved_path, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            assert len(reader) == 2
            row0 = reader[0]
            assert row0["date"] == "2026-09-01"
            assert row0["temp_nws_summary"] == "28.0"
            assert row0["temp_nws_cal_max"] == "27.8"
            assert row0["temp_nws_cal_max_raw_precision"] == "27.8"
            assert row0["temp_iem_raw_max"] == "27.0"
            assert row0["temp_iem_quant_sim"] == "27.0000"
            assert row0["delta_align"] == "0.2000"
            assert row0["delta_quant"] == "0.0000"
            assert row0["delta_res"] == "0.8000"
            assert row0["status"] == "VALID"

            row1 = reader[1]
            assert row1["date"] == "2026-09-02"
            assert row1["temp_nws_cal_max"] == ""
            assert row1["temp_nws_cal_max_raw_precision"] == ""
            assert row1["status"] == "INCOMPLETE_DATA"
