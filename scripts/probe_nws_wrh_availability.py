"""
NWS WRH Availability Prober Suite (Probes 1, 2, 3, 4).
Runs empirical investigations into retention limits, precision, stability SLA, and latency.
Strictly frozen from statistical pricing parameters and downstream recommendation models.
"""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import json
import logging
from pathlib import Path
import time as time_lib
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from src.data_acquisition.nws_wrh_collector import NwsWrhAdapter
from src.data_acquisition.scraping_metrics import ScrapingStabilityTracker, UptimeMetricsRecord
from src.data_analysis.latency_outage_analyzer import LatencyOutageAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class RetentionWindowResult:
    """Strongly-typed container for retention depth probing results."""
    lookback_days: int
    unit_type: str
    success: bool
    status_code: int
    returned_records_count: int
    expected_records_count: int
    coverage_ratio: float
    completeness_status: str
    earliest_returned_timestamp: Optional[str] = None
    latest_returned_timestamp: Optional[str] = None
    request_latency_sec: float = 0.0
    error_message: Optional[str] = None


class NwsAvailabilityProber:
    """Executes empirical availability probing against NWS WRH API."""

    def __init__(self, station: str = "ZSPD", storage_dir: Optional[str] = None):
        self.station = station
        self.storage_dir = Path(storage_dir) if storage_dir else Path("data/raw/nws_wrh")
        self.adapter = NwsWrhAdapter(storage_dir=str(self.storage_dir))

    @staticmethod
    def _evaluate_payload_completeness(
        ret_count: int, expected_count: int
    ) -> Tuple[float, str, bool]:
        """Evaluate coverage ratio, completeness category, and availability gate."""
        coverage = round(ret_count / expected_count, 4) if expected_count > 0 else 0.0
        if ret_count == 0:
            return 0.0, "EMPTY_PAYLOAD", False
        if coverage >= 0.8:
            return coverage, "COMPLETE", True
        return coverage, "SPARSE_DATA", False

    @staticmethod
    def _extract_date_times_from_payload(raw_json: Dict[str, Any]) -> List[str]:
        """Safely extract date_time array from raw response."""
        stations = raw_json.get("STATION", [])
        if not stations:
            return []
        return stations[0].get("OBSERVATIONS", {}).get("date_time", [])

    def _probe_single_depth_unit(
        self, days_back: int, unit_type: str, now_utc: datetime
    ) -> Dict[str, Any]:
        """Probe a single depth and unit type against Synoptic MesoWest API."""
        start_dt = now_utc - timedelta(days=days_back)
        end_dt = start_dt + timedelta(days=1)
        start_str = start_dt.strftime("%Y%m%d%H%M")
        end_str = end_dt.strftime("%Y%m%d%H%M")

        params = {"stid": self.station, "start": start_str, "end": end_str, "units": unit_type}
        t0 = time_lib.perf_counter()
        base_res = {
            "requested_days_back": days_back,
            "unit_type": unit_type,
            "requested_start": start_str,
            "requested_end": end_str,
        }
        expected_count = max(1, int((end_dt - start_dt).total_seconds() / 1800))

        try:
            raw_json = self.adapter.fetch_raw_json(params)
            latency = time_lib.perf_counter() - t0
            date_times = self._extract_date_times_from_payload(raw_json)
            ret_count = len(date_times)
            coverage, completeness, avail = self._evaluate_payload_completeness(ret_count, expected_count)

            return {
                **base_res,
                "http_status": 200,
                "returned_records_count": ret_count,
                "expected_records_count": expected_count,
                "coverage_ratio": coverage,
                "completeness_status": completeness,
                "earliest_returned_timestamp": date_times[0] if date_times else None,
                "latest_returned_timestamp": date_times[-1] if date_times else None,
                "request_latency_sec": round(latency, 3),
                "is_data_available": avail,
            }
        except Exception as e:
            return {
                **base_res,
                "http_status": "ERROR",
                "error_message": str(e),
                "returned_records_count": 0,
                "expected_records_count": expected_count,
                "coverage_ratio": 0.0,
                "completeness_status": "HTTP_ERROR",
                "earliest_returned_timestamp": None,
                "latest_returned_timestamp": None,
                "request_latency_sec": round(time_lib.perf_counter() - t0, 3),
                "is_data_available": False,
            }

    def probe_retention_window(
        self,
        test_days: Optional[List[int]] = None,
        units: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Probe 1: Test NWS WRH retention window with strict record count validation across
        multiple lookback depths including free-tier boundaries (365d, 400d, 730d).
        """
        if test_days is None:
            test_days = [7, 14, 30, 60, 90, 365, 400, 730]
        if units is None:
            units = ["metric", "english"]

        results = []
        now_utc = datetime.now(timezone.utc)

        for unit in units:
            for days_back in test_days:
                res = self._probe_single_depth_unit(days_back, unit, now_utc)
                results.append(res)
                logger.info(
                    f"Retention Probe [{unit} {days_back}d]: status={res['completeness_status']}, "
                    f"count={res['returned_records_count']}/{res['expected_records_count']} ({res['coverage_ratio']:.1%})"
                )

        return results

    def probe_station_metadata_origin(self) -> Dict[str, Any]:
        """Clarify station archive origin vs physical airport commissioning history."""
        return {
            "station": self.station,
            "synoptic_archive_start": "2018-11-01",
            "physical_airport_opening": "1999-10-01",
            "origin_clarification": (
                "Synoptic MesoWest began archiving ZSPD observations on 2018-11-01. "
                "This represents database ingestion inception, distinct from 1999 physical airport commissioning."
            ),
        }

    @staticmethod
    def _collect_temps_from_file(
        f_path: Path,
    ) -> Tuple[List[float], List[float]]:
        """Read a single JSON file and extract metric or english temperature lists."""
        m_temps: List[float] = []
        e_temps: List[float] = []
        try:
            with open(f_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            unit_type = data.get("unit_type")
            stations = data.get("response", {}).get("STATION", [])
            if stations:
                temps = stations[0].get("OBSERVATIONS", {}).get("air_temp_set_1", [])
                valid_temps = [t for t in temps if t is not None]
                if unit_type == "metric":
                    m_temps.extend(valid_temps)
                elif unit_type == "english":
                    e_temps.extend(valid_temps)
        except Exception as e:
            logger.warning(f"Error reading {f_path}: {e}")
        return m_temps, e_temps

    @staticmethod
    def _calculate_precision_breakdown(
        metric_temps: List[float], english_temps: List[float], total_files: int
    ) -> Dict[str, Any]:
        """Compute integer, one-decimal, and high-decimal percentages."""
        m_total = len(metric_temps)
        e_total = len(english_temps)

        int_m = sum(1 for t in metric_temps if abs(t - round(t)) < 1e-4)
        one_dec_m = sum(
            1 for t in metric_temps if abs(t * 10 - round(t * 10)) < 1e-4 and abs(t - round(t)) >= 1e-4
        )
        high_dec_m = m_total - int_m - one_dec_m

        int_e = sum(1 for t in english_temps if abs(t - round(t)) < 1e-4)

        return {
            "total_files_audited": total_files,
            "metric_sample_count": m_total,
            "metric_integer_count": int_m,
            "metric_integer_pct": round(int_m / m_total, 4) if m_total > 0 else 0.0,
            "metric_one_decimal_count": one_dec_m,
            "metric_one_decimal_pct": round(one_dec_m / m_total, 4) if m_total > 0 else 0.0,
            "metric_high_decimal_count": high_dec_m,
            "english_sample_count": e_total,
            "english_pure_integer_count": int_e,
            "english_pure_integer_pct": round(int_e / e_total, 4) if e_total > 0 else 0.0,
        }

    def audit_field_precision(self) -> Dict[str, Any]:
        """Probe 2: Audit raw JSON files in storage_dir for metric and english decimal precision."""
        raw_files = list(self.storage_dir.glob(f"{self.station}_*.json"))
        if not raw_files:
            return {
                "total_files_audited": 0,
                "metric_sample_count": 0,
                "metric_integer_pct": 0.0,
                "english_sample_count": 0,
                "english_pure_integer_pct": 0.0,
            }

        all_metric_temps: List[float] = []
        all_english_temps: List[float] = []

        for f_path in raw_files:
            m, e = self._collect_temps_from_file(f_path)
            all_metric_temps.extend(m)
            all_english_temps.extend(e)

        return self._calculate_precision_breakdown(
            all_metric_temps, all_english_temps, len(raw_files)
        )

    def record_uptime_metrics(
        self,
        output_csv: str = "data/processed/nws_wrh_uptime_metrics.csv",
        num_requests: int = 5,
    ) -> Dict[str, Any]:
        """
        Probe 3: Quantify scraping stability, API latency distribution, schema drift.
        Appends metrics to CSV.
        """
        tracker = ScrapingStabilityTracker()
        params = {"stid": self.station, "recent": 120, "units": "metric"}

        for _ in range(num_requests):
            t0 = time_lib.perf_counter()
            try:
                data = self.adapter.fetch_raw_json(params)
                latency = time_lib.perf_counter() - t0
                top_keys = set(data.keys())
                st_keys = set(data["STATION"][0].keys()) if data.get("STATION") else set()
                obs_keys = set(data["STATION"][0].get("OBSERVATIONS", {}).keys()) if data.get("STATION") else set()
                tracker.record_attempt(latency, success=True, observed_keys=(top_keys | st_keys | obs_keys))
            except Exception as e:
                latency = time_lib.perf_counter() - t0
                tracker.record_attempt(latency, success=False, error=e)

        metrics = tracker.compute_metrics(station=self.station)
        tracker.append_to_csv(metrics, output_csv)
        return metrics.to_dict()

    def analyze_outage_and_latency(
        self, days_list: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """
        Probe 4: Analyze data update latency and multi-window 24-hour observation gap patterns.
        """
        if days_list is None:
            days_list = [14, 30]

        analyzer = LatencyOutageAnalyzer()
        latency_summary = analyzer.compute_update_latency_from_raw_files(
            self.storage_dir, station=self.station
        )

        dt_end = datetime.now(timezone.utc)
        hourly_distributions: Dict[str, Any] = {}

        for d in days_list:
            dt_start = dt_end - timedelta(days=d)
            records = self.adapter.fetch_raw_series(self.station, dt_start, dt_end)
            dist = analyzer.compute_hourly_outage_distribution(
                records, days_count=d, timezone_str="Asia/Shanghai"
            )
            hourly_distributions[f"{d}_days"] = dist.to_dict()

        return {
            "update_latency": latency_summary.to_dict(),
            "hourly_outage_distributions": hourly_distributions,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="NWS WRH Availability Prober")
    parser.add_argument("--station", default="ZSPD", help="Station ICAO (default: ZSPD)")
    parser.add_argument("--output-metrics", default="data/processed/nws_wrh_uptime_metrics.csv")
    args = parser.parse_args()

    prober = NwsAvailabilityProber(station=args.station)

    print("\n=======================================================")
    print(f"  🔍 NWS WRH Service Availability Probing Suite: {args.station}")
    print("=======================================================\n")

    print("--- [探针 1: WRH 留存窗口与边界探顶实测 (Metric & English)] ---")
    retention_res = prober.probe_retention_window([7, 14, 30, 60, 90, 365, 400, 730], ["metric", "english"])
    print(json.dumps(retention_res, indent=2))

    print("\n--- [站点元数据起点与通航历史澄清] ---")
    meta_origin = prober.probe_station_metadata_origin()
    print(json.dumps(meta_origin, indent=2))

    print("\n--- [探针 2: 字段精度审计] ---")
    precision_res = prober.audit_field_precision()
    print(json.dumps(precision_res, indent=2))

    print("\n--- [探针 3: 抓取稳定性量化] ---")
    uptime_res = prober.record_uptime_metrics(output_csv=args.output_metrics, num_requests=5)
    print(json.dumps(uptime_res, indent=2))

    print("\n--- [探针 4: 更新时延与 24 小时断流时段分析] ---")
    outage_res = prober.analyze_outage_and_latency(days_list=[14, 30])
    print(json.dumps(outage_res, indent=2))


if __name__ == "__main__":
    main()
