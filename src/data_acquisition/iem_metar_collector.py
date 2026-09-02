"""
IEM ASOS / METAR Historical Message Collector and Extreme Group Parser.
Fetches raw METAR time-series and decodes WMO/ASOS main body and remark extreme code groups.
"""

import csv
import io
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from src.data_acquisition.observation_adapter import (
    BaseObservationAdapter,
    ObservationRecord,
)

logger = logging.getLogger(__name__)


def _coalesce(*values: Any) -> Any:
    """Return the first non-None value among arguments."""
    for v in values:
        if v is not None:
            return v
    return None


def parse_metar_dry_bulb(metar_text: str) -> Optional[float]:
    """
    Parse main body dry bulb temperature from METAR text (e.g. '28/25', 'M05/M10', '00/M02').
    Returns temperature in Celsius.
    """
    if not metar_text:
        return None
    # Pattern: (M?digits)/(M?digits)
    pattern = r"(?:^|\s)(M?\d{2})\/(M?\d{2})(?=\s|$)"
    match = re.search(pattern, metar_text)
    if not match:
        return None

    raw_t = match.group(1)
    if raw_t.startswith("M"):
        return -float(raw_t[1:])
    return float(raw_t)


def _decode_signed_tenths(sign_char: str, value_digits: str) -> float:
    """Decode WMO signed temperature in tenths of °C (0=positive, 1=negative)."""
    val = float(value_digits) / 10.0
    return -val if sign_char == "1" else val


def parse_metar_extreme_remarks(metar_text: str) -> Dict[str, Optional[float]]:
    """
    Parse extreme code groups and high-res temperatures from METAR RMK section:
    - 1snTxTxTx: 6-hour maximum temperature
    - 2snTnTnTn: 6-hour minimum temperature
    - 4snTxTxTxsnTnTnTn: 24-hour maximum and minimum temperature
    - TsnTTTsnTdTdTd: 0.1°C precision temperature and dewpoint
    """
    results: Dict[str, Optional[float]] = {
        "temp_6h_max": None,
        "temp_6h_min": None,
        "temp_24h_max": None,
        "temp_24h_min": None,
        "temp_high_res": None,
        "dewpoint_high_res": None,
    }
    if not metar_text:
        return results

    # 1. 6h max (1snTxTxTx)
    match_6max = re.search(r"(?:^|\s)1([01])(\d{3})(?=\s|$)", metar_text)
    if match_6max:
        results["temp_6h_max"] = _decode_signed_tenths(match_6max.group(1), match_6max.group(2))

    # 2. 6h min (2snTnTnTn)
    match_6min = re.search(r"(?:^|\s)2([01])(\d{3})(?=\s|$)", metar_text)
    if match_6min:
        results["temp_6h_min"] = _decode_signed_tenths(match_6min.group(1), match_6min.group(2))

    # 3. 24h max and min (4snTxTxTxsnTnTnTn)
    match_24 = re.search(r"(?:^|\s)4([01])(\d{3})([01])(\d{3})(?=\s|$)", metar_text)
    if match_24:
        results["temp_24h_max"] = _decode_signed_tenths(match_24.group(1), match_24.group(2))
        results["temp_24h_min"] = _decode_signed_tenths(match_24.group(3), match_24.group(4))

    # 4. High-resolution temperature (TsnTTTsnTdTdTd)
    match_t = re.search(r"(?:^|\s)T([01])(\d{3})([01])(\d{3})(?=\s|$)", metar_text)
    if match_t:
        results["temp_high_res"] = _decode_signed_tenths(match_t.group(1), match_t.group(2))
        results["dewpoint_high_res"] = _decode_signed_tenths(match_t.group(3), match_t.group(4))

    return results


def _get_extreme_remark_val(record: ObservationRecord, key: str) -> Optional[float]:
    """Safely extract an extreme remark field value from ObservationRecord metadata."""
    return record.metadata.get("extreme_remarks", {}).get(key)


class IemMetarAdapter(BaseObservationAdapter):
    """
    Adapter for Iowa Environmental Mesonet (IEM) ASOS METAR data service.
    """

    BASE_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"

    def __init__(
        self,
        storage_dir: Optional[str] = None,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        timeout_seconds: int = 30,
    ):
        self.storage_dir = Path(storage_dir) if storage_dir else Path("data/raw/iem_metar")
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "Poly2-QuantitativeModel/1.0 (ClimateResearch)"}
        )
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def get_source_precision_metadata(self) -> Dict[str, Any]:
        return {
            "source_name": "IEM_Mesonet_METAR",
            "primary_unit": "Celsius",
            "supports_extreme_groups": True,
            "api_endpoint": self.BASE_URL,
        }

    def _execute_download_with_retry(self, params: Dict[str, Any]) -> str:
        """Download CSV response with exponential backoff retry."""
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(
                    self.BASE_URL, params=params, timeout=self.timeout_seconds
                )
                if resp.status_code == 200:
                    return resp.text
                resp.raise_for_status()
            except Exception as e:
                last_error = e
                logger.warning(
                    f"IEM METAR fetch attempt {attempt}/{self.max_retries} failed: {e}"
                )
                if attempt < self.max_retries:
                    time.sleep(self.backoff_base * (2 ** (attempt - 1)))

        raise RuntimeError(
            f"Failed to fetch IEM METAR data after {self.max_retries} retries. Error: {last_error}"
        )

    def _persist_raw_csv(self, station: str, tag: str, csv_content: str) -> Path:
        """Save raw CSV response and metadata to local storage."""
        now_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        csv_filename = f"{station}_{tag}_{now_ts}.csv"
        meta_filename = f"{station}_{tag}_{now_ts}.meta.json"
        target_path = self.storage_dir / csv_filename
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(csv_content)

        meta_path = self.storage_dir / meta_filename
        meta_payload = {
            "fetched_at": now_ts,
            "station": station,
            "http_status_code": 200,
            "raw_csv_file": csv_filename,
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta_payload, f, indent=2)

        return target_path

    @staticmethod
    def _parse_csv_row(row: Dict[str, str]) -> Optional[ObservationRecord]:
        """Convert a single CSV dict row into an ObservationRecord."""
        valid_str = row.get("valid", "").strip()
        if not valid_str:
            return None

        dt = datetime.strptime(valid_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        metar_text = row.get("metar", "").strip()
        remarks = parse_metar_extreme_remarks(metar_text)

        tmpc_raw = row.get("tmpc")
        csv_temp_c = float(tmpc_raw) if tmpc_raw and tmpc_raw != "null" else None
        body_temp_c = parse_metar_dry_bulb(metar_text)

        # Hierarchy with strict non-None check (immune to 0.0°C falsy bug)
        final_temp_c = _coalesce(remarks.get("temp_high_res"), body_temp_c, csv_temp_c)
        dwpc_raw = row.get("dwpc")
        csv_dew_c = float(dwpc_raw) if dwpc_raw and dwpc_raw != "null" else None
        final_dew_c = _coalesce(remarks.get("dewpoint_high_res"), csv_dew_c)

        tmpf_raw = row.get("tmpf")
        temp_f = float(tmpf_raw) if tmpf_raw and tmpf_raw != "null" else None

        return ObservationRecord(
            timestamp=dt,
            temp_c=final_temp_c,
            temp_f=temp_f,
            dewpoint_c=final_dew_c,
            raw_metar=metar_text,
            metadata={"extreme_remarks": remarks, "raw_valid_utc": valid_str},
        )

    def fetch_raw_series(
        self, station: str, start_date: datetime, end_date: datetime
    ) -> List[ObservationRecord]:
        """Fetch historical METAR observations from IEM within date range."""
        params = {
            "station": station,
            "data": ["tmpc", "tmpf", "dwpc", "metar"],
            "year1": start_date.year,
            "month1": start_date.month,
            "day1": start_date.day,
            "year2": end_date.year,
            "month2": end_date.month,
            "day2": end_date.day,
            "tz": "Etc/UTC",
            "format": "onlycomma",
            "latlon": "no",
            "missing": "null",
            "report_type": ["1", "2"],
        }
        tag = f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
        csv_text = self._execute_download_with_retry(params)
        self._persist_raw_csv(station, tag, csv_text)

        reader = csv.DictReader(io.StringIO(csv_text))
        records: List[ObservationRecord] = []
        for row in reader:
            rec = self._parse_csv_row(row)
            if rec:
                records.append(rec)
        return records

    @staticmethod
    def calculate_extreme_group_coverage(
        records: List[ObservationRecord],
    ) -> Dict[str, float]:
        """Calculate frequency of extreme groups (6h, 24h, high-res) across records."""
        total = len(records)
        if total == 0:
            return {
                "total_records": 0,
                "coverage_6h_max": 0.0,
                "coverage_24h_max": 0.0,
                "coverage_high_res_temp": 0.0,
            }

        c_6h = sum(1 for r in records if _get_extreme_remark_val(r, "temp_6h_max") is not None)
        c_24h = sum(1 for r in records if _get_extreme_remark_val(r, "temp_24h_max") is not None)
        c_hires = sum(1 for r in records if _get_extreme_remark_val(r, "temp_high_res") is not None)

        return {
            "total_records": total,
            "coverage_6h_max": c_6h / total,
            "coverage_24h_max": c_24h / total,
            "coverage_high_res_temp": c_hires / total,
        }

    def extract_calendar_day_max(
        self,
        records: List[ObservationRecord],
        timezone_str: str = "Asia/Shanghai",
        strategy: str = "B",
    ) -> Optional[float]:
        """
        Extract daily maximum temperature using Strategy A (instantaneous max)
        or Strategy B (priority extreme remark groups -> fallback to Strategy A).
        """
        if not records:
            return None

        if strategy == "B":
            # 1. Check for 24h extreme group
            ext_24 = [_get_extreme_remark_val(r, "temp_24h_max") for r in records]
            valid_24 = [v for v in ext_24 if v is not None]
            if valid_24:
                return max(valid_24)

            # 2. Check for 6h extreme group
            ext_6 = [_get_extreme_remark_val(r, "temp_6h_max") for r in records]
            valid_6 = [v for v in ext_6 if v is not None]
            if valid_6:
                return max(valid_6)

        # Strategy A (or fallback)
        valid_temps = [r.temp_c for r in records if r.temp_c is not None]
        return max(valid_temps) if valid_temps else None
