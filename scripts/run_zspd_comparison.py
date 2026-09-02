#!/usr/bin/env python
"""
CLI Script for ZSPD NWS WRH vs IEM METAR Daily Temperature Extreme Comparison Pipeline.
Orchestrates dual-source data acquisition, calendar day slicing, QC, algebraic decomposition,
and generation of calibration JSON and Markdown analysis report.
"""

import argparse
import csv
from datetime import date, datetime, time, timedelta, timezone
import io
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple, Union
import zoneinfo

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_acquisition.nws_wrh_collector import NwsWrhAdapter
from src.data_acquisition.iem_metar_collector import IemMetarAdapter
from src.data_acquisition.observation_adapter import ObservationRecord
from src.data_processing.calendar_day_qc import (
    CalendarDaySlicer,
    DayQcResult,
    ObservationQualityControl,
    WindowQcSummary,
    DataPipelineOutageError,
)
from src.data_analysis.deviation_decomposer import (
    DailyDiffRecord,
    DeviationDecomposer,
    calibrate_empirical_rounding_operator,
)
from src.data_analysis.distribution_calibrator import (
    DistributionCalibrator,
    ReportGenerator,
)
from scripts.probe_nws_wrh_availability import NwsAvailabilityProber

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_zspd_comparison")


def _resolve_date_range(
    days: int,
    start_date: Optional[Union[date, str]] = None,
    end_date: Optional[Union[date, str]] = None,
    timezone_str: str = "Asia/Shanghai",
) -> Tuple[date, date]:
    """Resolve start and end dates in local timezone."""
    tz = zoneinfo.ZoneInfo(timezone_str)
    now_local = datetime.now(tz).date()

    if end_date:
        end_d = datetime.strptime(end_date, "%Y-%m-%d").date() if isinstance(end_date, str) else end_date
    else:
        end_d = now_local

    if start_date:
        start_d = datetime.strptime(start_date, "%Y-%m-%d").date() if isinstance(start_date, str) else start_date
    else:
        start_d = end_d - timedelta(days=days - 1)

    return start_d, end_d


def _generate_mock_series(
    start_date: date,
    end_date: date,
    timezone_str: str = "Asia/Shanghai",
) -> Tuple[List[ObservationRecord], List[ObservationRecord]]:
    """Generate realistic synthetic observations with natural daily variance for unit tests."""
    tz = zoneinfo.ZoneInfo(timezone_str)
    curr = start_date
    nws_recs = []
    iem_recs = []
    day_idx = 0

    while curr <= end_date:
        daily_baseline = 24.0 + (day_idx % 5) * 1.5  # 24.0, 25.5, 27.0, 28.5, 30.0
        for half_hour in range(48):
            dt_local = datetime.combine(curr, time(0, 0), tzinfo=tz) + timedelta(minutes=30 * half_hour)
            hour = dt_local.hour + dt_local.minute / 60.0
            temp_c = round(daily_baseline + 5.0 * max(0.0, 1.0 - abs(hour - 14.0) / 6.0))
            nws_recs.append(ObservationRecord(timestamp=dt_local, temp_c=float(temp_c), temp_f=round(temp_c * 1.8 + 32.0)))
            iem_recs.append(ObservationRecord(timestamp=dt_local, temp_c=float(temp_c), raw_metar=f"METAR ZSPD {dt_local.strftime('%d%H%M')}Z {int(temp_c)}/20 Q1010"))
        curr += timedelta(days=1)
        day_idx += 1

    return nws_recs, iem_recs


def _load_series_from_cached_raw(
    station: str = "ZSPD",
) -> Tuple[List[ObservationRecord], List[ObservationRecord]]:
    """Load real observation series from latest cached raw files in data/raw."""
    # Filter for full-window files (excluding short recent files)
    nws_m_files = sorted([f for f in (PROJECT_ROOT / "data/raw/nws_wrh").glob(f"{station}_*_metric_*.json") if "recent" not in f.name], key=lambda x: x.stat().st_size)
    nws_e_files = sorted([f for f in (PROJECT_ROOT / "data/raw/nws_wrh").glob(f"{station}_*_english_*.json") if "recent" not in f.name], key=lambda x: x.stat().st_size)
    if not nws_m_files or not nws_e_files:
        raise FileNotFoundError(f"No cached NWS raw files found for {station}")

    with open(nws_m_files[-1], "r", encoding="utf-8") as f:
        m_payload = json.load(f)["response"]
    with open(nws_e_files[-1], "r", encoding="utf-8") as f:
        e_payload = json.load(f)["response"]

    nws_adapter = NwsWrhAdapter()
    nws_records = nws_adapter._parse_dual_probe_payloads(m_payload, e_payload)

    iem_files = sorted([f for f in (PROJECT_ROOT / "data/raw/iem_metar").glob(f"{station}_*.csv")], key=lambda x: x.stat().st_size)
    if not iem_files:
        raise FileNotFoundError(f"No cached IEM raw files found for {station}")

    iem_adapter = IemMetarAdapter()
    with open(iem_files[-1], "r", encoding="utf-8") as f:
        csv_text = f.read()

    reader = csv.DictReader(io.StringIO(csv_text))
    iem_records = []
    for row in reader:
        rec = iem_adapter._parse_csv_row(row)
        if rec:
            iem_records.append(rec)

    return nws_records, iem_records


def _evaluate_single_day_diff(
    target_date: date,
    iem_records: List[ObservationRecord],
    nws_records: List[ObservationRecord],
    qc: ObservationQualityControl,
    decomposer: DeviationDecomposer,
    timezone_str: str,
) -> Tuple[DayQcResult, DailyDiffRecord]:
    """Evaluate single day QC and calculate deviation decomposition."""
    date_str = target_date.strftime("%Y-%m-%d")
    iem_day_qc = qc.evaluate_day(iem_records, target_date, timezone_str)
    nws_day_qc = qc.evaluate_day(nws_records, target_date, timezone_str)

    is_day_valid = iem_day_qc.is_valid and nws_day_qc.is_valid
    status = "VALID" if is_day_valid else "INCOMPLETE_DATA"

    temp_iem_max = None
    temp_nws_cal_max = None
    temp_nws_cal_max_raw_precision = None

    if len(iem_day_qc.filtered_records) > 0:
        valid_iem = [r.temp_c for r in iem_day_qc.filtered_records if r.temp_c is not None]
        temp_iem_max = max(valid_iem) if valid_iem else None

    if len(nws_day_qc.filtered_records) > 0:
        valid_nws = [r.temp_c for r in nws_day_qc.filtered_records if r.temp_c is not None]
        temp_nws_cal_max = max(valid_nws) if valid_nws else None
        if temp_nws_cal_max is not None:
            temp_nws_cal_max_raw_precision = f"{temp_nws_cal_max:g}"

    diff_rec = decomposer.decompose_daily_diff(
        date_str=date_str,
        temp_nws_cal_max=temp_nws_cal_max,
        temp_iem_raw_max=temp_iem_max,
        temp_nws_summary=None,
        status=status,
        temp_nws_cal_max_raw_precision=temp_nws_cal_max_raw_precision,
    )
    return iem_day_qc, diff_rec


def _process_daily_comparisons(
    start_date: date,
    end_date: date,
    nws_records: List[ObservationRecord],
    iem_records: List[ObservationRecord],
    slicer: CalendarDaySlicer,
    qc: ObservationQualityControl,
    decomposer: DeviationDecomposer,
    timezone_str: str,
) -> Tuple[List[DayQcResult], List[DailyDiffRecord]]:
    """Iterate through date range, perform QC and calculate daily differences."""
    curr = start_date
    daily_qc_results: List[DayQcResult] = []
    daily_diff_records: List[DailyDiffRecord] = []

    while curr <= end_date:
        iem_day_qc, diff_rec = _evaluate_single_day_diff(
            curr, iem_records, nws_records, qc, decomposer, timezone_str
        )
        daily_qc_results.append(iem_day_qc)
        daily_diff_records.append(diff_rec)
        curr += timedelta(days=1)

    return daily_qc_results, daily_diff_records


def run_comparison_pipeline(
    station: str = "ZSPD",
    days: int = 14,
    start_date: Optional[Union[date, str]] = None,
    end_date: Optional[Union[date, str]] = None,
    output_csv: Union[str, Path] = "data/processed/zspd_daily_diff.csv",
    output_json: Union[str, Path] = "config/zspd_metar_noise_calibration.json",
    output_report: Union[str, Path] = "docs/reports/zspd-data-availability-report-v1.2.md",
    timezone_str: str = "Asia/Shanghai",
    mock_mode: bool = False,
    from_cache: bool = True,
) -> int:
    """Execute the end-to-end ZSPD temperature extreme comparison pipeline."""
    start_d, end_d = _resolve_date_range(days, start_date, end_date, timezone_str)
    logger.info(f"Starting comparison pipeline for {station} across [{start_d} ~ {end_d}] ({timezone_str})")

    if mock_mode:
        # Write-protection guard: Divert default production outputs to .scratch sandbox to prevent pollution
        if str(output_csv).endswith("data/processed/zspd_daily_diff.csv"):
            output_csv = PROJECT_ROOT / ".scratch/mock_output/zspd_daily_diff.csv"
        if str(output_json).endswith("config/zspd_metar_noise_calibration.json"):
            output_json = PROJECT_ROOT / ".scratch/mock_output/zspd_metar_noise_calibration.json"
        if "docs/reports" in str(output_report):
            output_report = PROJECT_ROOT / ".scratch/mock_output/zspd-data-availability-report-mock.md"
        logger.info(f"Mock mode write-protection active: Diverting default outputs to sandbox under .scratch/mock_output/")
        nws_records, iem_records = _generate_mock_series(start_d, end_d, timezone_str)
    elif from_cache:
        try:
            nws_records, iem_records = _load_series_from_cached_raw(station)
            logger.info(f"Loaded {len(nws_records)} NWS records and {len(iem_records)} IEM records from local cached raw files.")
        except Exception as e:
            logger.warning(f"Failed to load cached raw files: {e}, falling back to live network fetch.")
            nws_adapter = NwsWrhAdapter()
            iem_adapter = IemMetarAdapter()
            dt_start = datetime.combine(start_d, time(0, 0), tzinfo=timezone.utc)
            dt_end = datetime.combine(end_d, time(23, 59), tzinfo=timezone.utc)
            nws_records = nws_adapter.fetch_raw_series(station, dt_start, dt_end)
            iem_records = iem_adapter.fetch_raw_series(station, dt_start, dt_end)
    else:
        nws_adapter = NwsWrhAdapter()
        iem_adapter = IemMetarAdapter()
        dt_start = datetime.combine(start_d, time(0, 0), tzinfo=timezone.utc)
        dt_end = datetime.combine(end_d, time(23, 59), tzinfo=timezone.utc)
        nws_records = nws_adapter.fetch_raw_series(station, dt_start, dt_end)
        iem_records = iem_adapter.fetch_raw_series(station, dt_start, dt_end)

    coverage_meta = IemMetarAdapter.calculate_extreme_group_coverage(iem_records)
    rounding_result = calibrate_empirical_rounding_operator(nws_records)
    rounding_meta = rounding_result.to_dict()

    slicer = CalendarDaySlicer()
    qc = ObservationQualityControl(slicer)
    decomposer = DeviationDecomposer()
    daily_qc_results, daily_diff_records = _process_daily_comparisons(
        start_d, end_d, nws_records, iem_records, slicer, qc, decomposer, timezone_str
    )

    window_summary = qc.evaluate_window(daily_qc_results)
    calibrator = DistributionCalibrator()
    calibration_data = calibrator.fit_residual_distribution(
        daily_diff_records,
        station_id=station,
        start_date=start_d.strftime("%Y-%m-%d"),
        end_date=end_d.strftime("%Y-%m-%d"),
        window_summary=window_summary,
    )
    calibration_data["empirical_rounding_operator"] = rounding_meta

    prober = NwsAvailabilityProber(station=station)
    precision_meta = prober.audit_field_precision()
    outage_res = prober.analyze_outage_and_latency(days_list=[days])
    latency_meta = outage_res.get("update_latency", {})
    outage_distributions = outage_res.get("hourly_outage_distributions", {})
    uptime_meta = prober.record_uptime_metrics(num_requests=3)

    # Export artifacts
    decomposer.export_to_csv(daily_diff_records, output_csv)
    calibrator.export_calibration_json(calibration_data, output_json)
    reporter = ReportGenerator()
    reporter.generate_markdown_report(
        station_id=station,
        window_summary=window_summary,
        coverage_meta=coverage_meta,
        rounding_meta=rounding_meta,
        calibration_data=calibration_data,
        diff_records=daily_diff_records,
        output_path=output_report,
        uptime_meta=uptime_meta,
        latency_meta=latency_meta,
        precision_meta=precision_meta,
        outage_distributions=outage_distributions,
    )

    logger.info(f"Pipeline complete. Outputs saved to:\n  - CSV: {output_csv}\n  - JSON: {output_json}\n  - Report: {output_report}")
    return 0


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="ZSPD NWS WRH vs IEM METAR Comparison CLI")
    parser.add_argument("--station", default="ZSPD", help="Target station ICAO code (default: ZSPD)")
    parser.add_argument("--days", type=int, default=14, help="Number of lookback days (default: 14)")
    parser.add_argument("--start-date", help="Start date YYYY-MM-DD")
    parser.add_argument("--end-date", help="End date YYYY-MM-DD")
    parser.add_argument("--output-csv", default="data/processed/zspd_daily_diff.csv", help="Target CSV file path")
    parser.add_argument("--output-json", default="config/zspd_metar_noise_calibration.json", help="Target JSON file path")
    parser.add_argument("--output-report", default="docs/reports/zspd-data-availability-report-v1.2.md", help="Target Report file path")
    parser.add_argument("--timezone", default="Asia/Shanghai", help="Local timezone string")
    parser.add_argument("--mock", action="store_true", help="Run with mock data generator")
    parser.add_argument("--no-cache", dest="from_cache", action="store_false", help="Force live network fetch rather than local cache")
    parser.set_defaults(from_cache=True)
    return parser.parse_args()


def main() -> None:
    """CLI execution entrypoint."""
    args = parse_args()
    code = run_comparison_pipeline(
        station=args.station,
        days=args.days,
        start_date=args.start_date,
        end_date=args.end_date,
        output_csv=args.output_csv,
        output_json=args.output_json,
        output_report=args.output_report,
        timezone_str=args.timezone,
        mock_mode=args.mock,
        from_cache=args.from_cache,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
