"""
Three-Component Deviation Decomposer & Direct Precision Reconciler.
R2 Verdict: Direct integer passthrough without phantom C->F->C quantization noise.
Delta_quant = 0.0, Delta_res = T_nws_cal_max - T_iem_raw_max.
"""

import csv
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.data_acquisition.observation_adapter import ObservationRecord

logger = logging.getLogger(__name__)


@dataclass
class EmpiricalRoundingCalibrationResult:
    """Strongly-typed container for empirical rounding operator calibration."""
    is_pure_integer_fahrenheit: bool
    sample_count: int
    quantization_variance: float
    lookup_table: Dict[float, float]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON persistence."""
        return {
            "is_pure_integer_fahrenheit": self.is_pure_integer_fahrenheit,
            "sample_count": self.sample_count,
            "quantization_variance": self.quantization_variance,
            "lookup_table": self.lookup_table,
            "deprecated": "phantom_model",
        }


def calibrate_empirical_rounding_operator(
    probe_records: List[ObservationRecord],
) -> EmpiricalRoundingCalibrationResult:
    """
    Validate integer Fahrenheit storage hypothesis from dual-probe records (temp_c & temp_f).
    Under R2 verdict, metric feed is direct integer passthrough with zero quantization variance.
    """
    valid_pairs = [
        (r.temp_c, r.temp_f)
        for r in probe_records
        if r.temp_c is not None and r.temp_f is not None
    ]
    if not valid_pairs:
        return EmpiricalRoundingCalibrationResult(
            is_pure_integer_fahrenheit=True,
            sample_count=0,
            quantization_variance=0.0,
            lookup_table={},
        )

    is_pure_int_f = all(abs(f - round(f)) < 1e-4 for _, f in valid_pairs)

    return EmpiricalRoundingCalibrationResult(
        is_pure_integer_fahrenheit=is_pure_int_f,
        sample_count=len(valid_pairs),
        quantization_variance=0.0,
        lookup_table={},
    )


@dataclass
class DailyDiffRecord:
    """Standard record for a single day's deviation decomposition with raw precision tracking."""
    date: str
    temp_nws_summary: Optional[float]
    temp_nws_cal_max: Optional[float]
    temp_iem_raw_max: Optional[float]
    temp_iem_quant_sim: Optional[float]
    delta_align: Optional[float]
    delta_quant: Optional[float]
    delta_res: Optional[float]
    status: str  # "VALID" or "INCOMPLETE_DATA"
    temp_nws_cal_max_raw_precision: Optional[str] = None


class DeviationDecomposer:
    """
    Decomposes daily temperature discrepancies between NWS WRH and IEM METAR:
    Delta_Total = T_nws_cal_max - T_iem_raw_max = Delta_quant (0.0) + Delta_res
    Delta_align = T_nws_summary - T_nws_cal_max
    """

    CSV_HEADERS = [
        "date",
        "temp_nws_summary",
        "temp_nws_cal_max",
        "temp_nws_cal_max_raw_precision",
        "temp_iem_raw_max",
        "temp_iem_quant_sim",
        "delta_align",
        "delta_quant",
        "delta_res",
        "status",
    ]

    def decompose_daily_diff(
        self,
        date_str: str,
        temp_nws_cal_max: Optional[float],
        temp_iem_raw_max: Optional[float],
        temp_nws_summary: Optional[float] = None,
        status: str = "VALID",
        temp_nws_cal_max_raw_precision: Optional[str] = None,
    ) -> DailyDiffRecord:
        """Calculate direct algebraic decomposition without phantom quantization noise."""
        temp_iem_quant_sim = temp_iem_raw_max
        delta_quant = 0.0 if temp_iem_raw_max is not None else None
        delta_res = None
        delta_align = None

        if temp_nws_cal_max is not None:
            if temp_iem_raw_max is not None:
                delta_res = round(temp_nws_cal_max - temp_iem_raw_max, 4)
            if temp_nws_summary is not None:
                delta_align = round(temp_nws_summary - temp_nws_cal_max, 4)

        return DailyDiffRecord(
            date=date_str,
            temp_nws_summary=temp_nws_summary,
            temp_nws_cal_max=temp_nws_cal_max,
            temp_nws_cal_max_raw_precision=temp_nws_cal_max_raw_precision,
            temp_iem_raw_max=temp_iem_raw_max,
            temp_iem_quant_sim=temp_iem_quant_sim,
            delta_align=delta_align,
            delta_quant=delta_quant,
            delta_res=delta_res,
            status=status,
        )

    @staticmethod
    def _fmt(val: Optional[float], prec: int = 4) -> str:
        """Helper to format nullable float with precision."""
        if val is None:
            return ""
        return f"{val:.{prec}f}"

    def export_to_csv(
        self,
        records: List[DailyDiffRecord],
        output_path: Union[str, Path],
    ) -> Path:
        """Export list of DailyDiffRecords to standardized CSV file."""
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        with open(target, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.CSV_HEADERS)
            writer.writeheader()
            for r in records:
                row = {
                    "date": r.date,
                    "temp_nws_summary": self._fmt(r.temp_nws_summary, 1),
                    "temp_nws_cal_max": self._fmt(r.temp_nws_cal_max, 1),
                    "temp_nws_cal_max_raw_precision": r.temp_nws_cal_max_raw_precision or "",
                    "temp_iem_raw_max": self._fmt(r.temp_iem_raw_max, 1),
                    "temp_iem_quant_sim": self._fmt(r.temp_iem_quant_sim, 4),
                    "delta_align": self._fmt(r.delta_align, 4),
                    "delta_quant": self._fmt(r.delta_quant, 4),
                    "delta_res": self._fmt(r.delta_res, 4),
                    "status": r.status,
                }
                writer.writerow(row)

        return target
