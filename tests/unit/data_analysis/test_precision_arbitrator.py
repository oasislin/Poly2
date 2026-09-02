"""
Unit Tests for Precision Arbitrator (R2 Precision Conflict Resolution).
"""

from pathlib import Path
import json
import pytest

from src.data_analysis.precision_arbitrator import (
    PrecisionArbitrator,
    TimestampComparisonRow,
)


class TestPrecisionArbitrator:
    """Test byte-level auditing of metric vs english payloads and report generation."""

    def test_audit_raw_payloads_mocked(self, tmp_path):
        arbitrator = PrecisionArbitrator()

        # Create paired metric and english files
        # Metric file: temp = 31.0
        metric_payload = {
            "unit_type": "metric",
            "response": {
                "STATION": [
                    {
                        "OBSERVATIONS": {
                            "date_time": ["2026-09-02T06:00:00Z", "2026-09-02T06:30:00Z"],
                            "air_temp_set_1": [31.0, 32.0],
                        }
                    }
                ]
            },
        }
        # English file: temp = 88.0 (88F -> 31.11C), 90.0 (90F -> 32.22C)
        english_payload = {
            "unit_type": "english",
            "response": {
                "STATION": [
                    {
                        "OBSERVATIONS": {
                            "date_time": ["2026-09-02T06:00:00Z", "2026-09-02T06:30:00Z"],
                            "air_temp_set_1": [88.0, 90.0],
                        }
                    }
                ]
            },
        }

        with open(tmp_path / "ZSPD_20260902_metric_01.json", "w", encoding="utf-8") as f:
            json.dump(metric_payload, f)
        with open(tmp_path / "ZSPD_20260902_english_01.json", "w", encoding="utf-8") as f:
            json.dump(english_payload, f)

        rows = arbitrator.audit_raw_payloads(tmp_path, station="ZSPD")
        assert len(rows) == 2
        r1 = rows[0]
        assert r1.timestamp_utc == "2026-09-02T06:00:00Z"
        assert r1.metric_raw_literal == 31.0
        assert r1.english_raw_literal == 88.0
        assert pytest.approx(r1.reconverted_c_from_f, 0.001) == 31.1111
        assert r1.is_metric_integer is True
        assert "Metric Direct Passthrough" in r1.verdict

    def test_generate_verdict_report(self, tmp_path):
        arbitrator = PrecisionArbitrator()
        rows = [
            TimestampComparisonRow(
                timestamp_utc="2026-09-02T06:00:00Z",
                metric_raw_literal=31.0,
                english_raw_literal=88.0,
                reconverted_c_from_f=31.1111,
                is_metric_integer=True,
                is_english_integer=True,
                verdict="Metric Direct Passthrough",
            )
        ]

        out_report = tmp_path / "nws_wrh_precision_audit_verdict.md"
        saved = arbitrator.generate_verdict_report(rows, output_path=out_report)
        assert saved.exists()
        content = open(saved, "r", encoding="utf-8").read()
        assert "# ⚖️ NWS WRH 公制探针精度与“幻影量化”终审记录" in content
        assert "最高优先级技术裁决" in content
        assert "31.1111 °C" in content
        assert "deprecated: phantom_model" in content
