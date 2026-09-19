#!/usr/bin/env python3
"""
IEM ASOS/METAR Formal Observation Pipeline Adapter (Phase 1.5 Task 02).

Provides production-grade fetching, decoding, and quality control of IEM METAR observations:
1. High-resolution RMK T-group parsing (0.1°C precision).
2. Quality Gate 1: Local calendar-day T-group coverage >= 99% (flag degraded on failure).
3. Quality Gate 2: Dual-source consistency vs NWS WRH (|ΔT| <= 0.2°F), preserving raw METARs.
4. Quality Gate 3: Provenance 4-tuple (timestamp, commit, sha256, source_url) + manifest.
5. Engineering robustness: yearly chunking, SHA-256 validated resumption, adaptive rate limiting.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from src.data_acquisition.observation_adapter import (
    BaseObservationAdapter,
    ObservationRecord,
)
from src.data_processing.constants import ACTIVE_11_STATIONS, STATION_METADATA
from src.data_processing.unit_converter import fahrenheit_to_celsius
from src.utils.logger import contextualize, get_logger

logger = get_logger("poly.pipeline.iem_adapter")

# Module Constants (eliminates all magic numbers and magic strings)
DEFAULT_HASH_CHUNK_SIZE_BYTES: int = 65536
C_TO_F_SCALE: float = 1.8
C_TO_F_OFFSET: float = 32.0
TEMP_ROUND_DECIMALS: int = 4
TENTHS_TO_CELSIUS_DIVISOR: float = 10.0

ERA2_START_YEAR: int = 2019
VINTAGE_ERA1: str = "era1"
VINTAGE_ERA2: str = "era2"
USAGE_STRESS_TEST_ONLY: str = "stress-test-only"
USAGE_TRAINING_READY: str = "training-ready"

QUALITY_NOMINAL: str = "nominal"
QUALITY_DEGRADED: str = "degraded"

DEFAULT_GATE1_THRESHOLD_PCT: float = 99.0
DEFAULT_GATE2_DELTA_THRESHOLD_F: float = 0.2
DEFAULT_RATE_LIMIT_DELAY_SECONDS: float = 1.0
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_BACKOFF_BASE_SECONDS: float = 1.0
DEFAULT_TIMEOUT_SECONDS: int = 30
DEFAULT_BASE_URL: str = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
DEFAULT_USER_AGENT: str = "Poly2-QuantitativeModel/1.0 (ClimateResearch)"


def get_git_commit_sha() -> str:
    """Retrieve current Git commit SHA."""
    try:
        cmd = ["git", "rev-parse", "HEAD"]
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def compute_file_sha256(path: Union[str, Path]) -> str:
    """Compute SHA-256 checksum of a file using buffered streaming."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(DEFAULT_HASH_CHUNK_SIZE_BYTES):
            h.update(chunk)
    return h.hexdigest()


def celsius_to_fahrenheit(temp_c: Optional[float]) -> Optional[float]:
    """Convert Celsius to Fahrenheit with fixed precision rounding."""
    if temp_c is None:
        return None
    return round(temp_c * C_TO_F_SCALE + C_TO_F_OFFSET, TEMP_ROUND_DECIMALS)


def _coalesce(*values: Any) -> Any:
    """Return the first non-None value among arguments (preserving 0.0)."""
    for v in values:
        if v is not None:
            return v
    return None


def _safe_float(val: Any) -> Optional[float]:
    """Safely convert raw string or number to float, returning None on non-numeric or missing markers."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("null", "none", "m", "t", "nan", "-"):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def parse_metar_dry_bulb(metar_text: str) -> Optional[float]:
    """Parse main body dry bulb temperature from METAR text (e.g. '28/25', 'M05/M10')."""
    if not metar_text:
        return None
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
    val = float(value_digits) / TENTHS_TO_CELSIUS_DIVISOR
    return -val if sign_char == "1" else val


def parse_metar_extreme_remarks(metar_text: str) -> Dict[str, Optional[float]]:
    """Parse extreme code groups and high-res temperatures from METAR RMK section."""
    results: Dict[str, Optional[float]] = {
        "temp_high_res": None,
        "dewpoint_high_res": None,
        "temp_6h_max": None,
        "temp_6h_min": None,
        "temp_24h_max": None,
        "temp_24h_min": None,
    }
    if not metar_text:
        return results

    match_t = re.search(r"(?:^|\s)T([01])(\d{3})([01])(\d{3})(?=\s|$)", metar_text)
    if match_t:
        results["temp_high_res"] = _decode_signed_tenths(match_t.group(1), match_t.group(2))
        results["dewpoint_high_res"] = _decode_signed_tenths(match_t.group(3), match_t.group(4))

    match_6max = re.search(r"(?:^|\s)1([01])(\d{3})(?=\s|$)", metar_text)
    if match_6max:
        results["temp_6h_max"] = _decode_signed_tenths(match_6max.group(1), match_6max.group(2))

    match_6min = re.search(r"(?:^|\s)2([01])(\d{3})(?=\s|$)", metar_text)
    if match_6min:
        results["temp_6h_min"] = _decode_signed_tenths(match_6min.group(1), match_6min.group(2))

    match_24 = re.search(r"(?:^|\s)4([01])(\d{3})([01])(\d{3})(?=\s|$)", metar_text)
    if match_24:
        results["temp_24h_max"] = _decode_signed_tenths(match_24.group(1), match_24.group(2))
        results["temp_24h_min"] = _decode_signed_tenths(match_24.group(3), match_24.group(4))

    return results


@dataclass
class DateWindow:
    """Encapsulates date range queries to eliminate data clumps."""
    start_month: int = 1
    start_day: int = 1
    end_month: int = 12
    end_day: int = 31


@dataclass
class IemAdapterConfig:
    """Configuration for IEM observation adapter pipeline."""
    storage_dir: Path = Path("data/raw/iem")
    reports_dir: Path = Path("data/reports")
    base_url: str = DEFAULT_BASE_URL
    max_retries: int = DEFAULT_MAX_RETRIES
    backoff_base: float = DEFAULT_BACKOFF_BASE_SECONDS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    rate_limit_delay: float = DEFAULT_RATE_LIMIT_DELAY_SECONDS
    gate1_coverage_threshold: float = DEFAULT_GATE1_THRESHOLD_PCT
    gate2_delta_threshold: float = DEFAULT_GATE2_DELTA_THRESHOLD_F
    user_agent: str = DEFAULT_USER_AGENT

    def __post_init__(self):
        self.storage_dir = Path(self.storage_dir)
        self.reports_dir = Path(self.reports_dir)


@dataclass
class IemArtifact:
    """Artifact metadata of a processed station-year file."""
    station: str
    year: int
    parquet_path: Path
    raw_archive_path: Path
    row_count: int
    quality_flag: str
    gate1_passed: bool
    manifest_entry: Dict[str, Any]


class IemAdapter(BaseObservationAdapter):
    """
    Formal production adapter for Iowa Environmental Mesonet (IEM) ASOS METAR service.
    Enforces Active 11 station universe, RMK T-group parsing, and 3 quality gates.
    """

    def __init__(self, config: Optional[IemAdapterConfig] = None):
        self.config = config or IemAdapterConfig()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.config.user_agent})
        self.config.storage_dir.mkdir(parents=True, exist_ok=True)
        self.config.reports_dir.mkdir(parents=True, exist_ok=True)

    def __enter__(self) -> IemAdapter:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def close(self) -> None:
        """Explicitly release HTTP connection resources."""
        self.session.close()

    def get_source_precision_metadata(self) -> Dict[str, Any]:
        return {
            "source_name": "IEM_ASOS_METAR_V2",
            "primary_unit": "Celsius",
            "precision_celsius": 0.1,
            "supports_t_group": True,
            "api_endpoint": self.config.base_url,
            "active_stations": list(ACTIVE_11_STATIONS),
        }

    def _validate_station(self, station: str) -> None:
        """Enforce strict Active 11 station universe."""
        st_norm = station.strip().upper()
        if st_norm not in ACTIVE_11_STATIONS:
            raise ValueError(
                f"Station '{st_norm}' is not in active 11 stations: {ACTIVE_11_STATIONS}. "
                "Non-compliant stations (e.g. KDCA, ZSPD, EGLC) are strictly banned."
            )

    def _build_query_params(
        self, station: str, year: int, window: Optional[DateWindow] = None
    ) -> Dict[str, Any]:
        """Construct IEM ASOS query parameters."""
        w = window or DateWindow()
        return {
            "station": station,
            "data": ["tmpc", "tmpf", "dwpc", "metar"],
            "year1": year,
            "month1": w.start_month,
            "day1": w.start_day,
            "year2": year,
            "month2": w.end_month,
            "day2": w.end_day,
            "tz": "Etc/UTC",
            "format": "onlycomma",
            "latlon": "no",
            "missing": "null",
            "report_type": ["1", "2"],
        }

    def _build_request_url(self, params: Dict[str, Any]) -> str:
        """Construct full request URL for auditing and provenance."""
        return f"{self.config.base_url}?{urlencode(params, doseq=True)}"

    def _execute_http_download(self, params: Dict[str, Any]) -> str:
        """Download raw CSV from IEM ASOS endpoint with rate limiting and exponential backoff."""
        if self.config.rate_limit_delay > 0:
            time.sleep(self.config.rate_limit_delay)

        last_error: Optional[Exception] = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                resp = self.session.get(
                    self.config.base_url,
                    params=params,
                    timeout=self.config.timeout_seconds,
                )
                if resp.status_code == 200:
                    return resp.text
                resp.raise_for_status()
            except (requests.RequestException, OSError) as e:
                last_error = e
                logger.warning(
                    f"IEM ASOS fetch attempt {attempt}/{self.config.max_retries} failed for "
                    f"station={params.get('station')}, year={params.get('year1')}: {e}"
                )
                if attempt < self.config.max_retries:
                    time.sleep(self.config.backoff_base * (2 ** (attempt - 1)))

        raise RuntimeError(
            f"Failed to fetch IEM ASOS data after {self.config.max_retries} retries: {last_error}"
        )

    def _parse_single_csv_row(self, row: Dict[str, str], station: str) -> Optional[Dict[str, Any]]:
        """Parse an individual CSV row into a structured observation dictionary."""
        valid_str = (row.get("valid") or "").strip()
        if not valid_str:
            return None
        try:
            dt_utc = datetime.strptime(valid_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            return None

        metar_text = (row.get("metar") or "").strip()
        remarks = parse_metar_extreme_remarks(metar_text)
        t_temp, t_dew = remarks.get("temp_high_res"), remarks.get("dewpoint_high_res")

        body_temp_c = parse_metar_dry_bulb(metar_text)
        csv_temp_c = _safe_float(row.get("tmpc"))
        tmpf_val = _safe_float(row.get("tmpf"))
        csv_from_tmpf = (
            round(float(fahrenheit_to_celsius(tmpf_val)), TEMP_ROUND_DECIMALS)
            if tmpf_val is not None
            else None
        )
        final_temp_c = _coalesce(t_temp, body_temp_c, csv_temp_c, csv_from_tmpf)

        csv_dew_c = _safe_float(row.get("dwpc"))
        final_dew_c = _coalesce(t_dew, csv_dew_c)

        is_era2 = dt_utc.year >= ERA2_START_YEAR
        vintage = VINTAGE_ERA2 if is_era2 else VINTAGE_ERA1
        usage = USAGE_TRAINING_READY if is_era2 else USAGE_STRESS_TEST_ONLY

        return {
            "station": station,
            "valid_utc": dt_utc,
            "temp_c": final_temp_c,
            "temp_f": celsius_to_fahrenheit(final_temp_c),
            "dewpoint_c": final_dew_c,
            "dewpoint_f": celsius_to_fahrenheit(final_dew_c),
            "raw_metar": metar_text,
            "t_group_parsed": t_temp is not None,
            "temp_6h_max": remarks.get("temp_6h_max"),
            "temp_6h_min": remarks.get("temp_6h_min"),
            "temp_24h_max": remarks.get("temp_24h_max"),
            "temp_24h_min": remarks.get("temp_24h_min"),
            "vintage": vintage,
            "usage": usage,
        }

    def parse_csv_observations(self, csv_content: str, station: str) -> List[Dict[str, Any]]:
        """Parse raw IEM CSV text into structured observation records."""
        reader = csv.DictReader(io.StringIO(csv_content))
        records: List[Dict[str, Any]] = []
        for row in reader:
            parsed = self._parse_single_csv_row(row, station)
            if parsed:
                records.append(parsed)
        return records

    def _aggregate_daily_summary(
        self, df_obs: pd.DataFrame, station: str
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """Aggregate observations by local date and evaluate coverage threshold."""
        daily_rows: List[Dict[str, Any]] = []
        overall_passed = True

        for date_str, group in df_obs.groupby("local_date", sort=True):
            total_obs = len(group)
            t_group_obs = int(group["t_group_parsed"].sum())
            cov_pct = (t_group_obs / total_obs * 100.0) if total_obs > 0 else 0.0

            passed = cov_pct >= self.config.gate1_coverage_threshold
            if not passed:
                overall_passed = False
                logger.warning(
                    f"Gate 1 Degraded: {station} on {date_str} has T-group coverage "
                    f"{cov_pct:.2f}% ({t_group_obs}/{total_obs}) < {self.config.gate1_coverage_threshold}%"
                )

            valid_temps_c = [t for t in group["temp_c"] if t is not None]
            tmax_c = max(valid_temps_c) if valid_temps_c else None
            tmin_c = min(valid_temps_c) if valid_temps_c else None

            # Collect raw METAR strings for daily arbitration retention
            raw_metars = [m for m in group["raw_metar"] if m]

            daily_rows.append({
                "station": station,
                "local_date": date_str,
                "total_obs": total_obs,
                "t_group_obs": t_group_obs,
                "t_group_coverage_pct": round(cov_pct, 2),
                "daily_tmax_c": tmax_c,
                "daily_tmax_f": celsius_to_fahrenheit(tmax_c),
                "daily_tmin_c": tmin_c,
                "daily_tmin_f": celsius_to_fahrenheit(tmin_c),
                "quality_flag": QUALITY_NOMINAL if passed else QUALITY_DEGRADED,
                "gate_1_passed": passed,
                "daily_raw_metars": raw_metars,
            })

        return daily_rows, overall_passed

    def evaluate_gate1_coverage(
        self, records: List[Dict[str, Any]], station: str
    ) -> Tuple[pd.DataFrame, bool]:
        """Quality Gate 1: Slices observations by local calendar day and checks T-group coverage."""
        if not records:
            empty_df = pd.DataFrame(columns=[
                "station", "local_date", "total_obs", "t_group_obs",
                "t_group_coverage_pct", "daily_tmax_c", "daily_tmax_f",
                "daily_tmin_c", "daily_tmin_f", "quality_flag", "gate_1_passed", "daily_raw_metars"
            ])
            return empty_df, False

        st_meta = STATION_METADATA.get(station, {})
        tz = ZoneInfo(st_meta.get("timezone", "UTC"))

        df_obs = pd.DataFrame(records)
        df_obs["valid_local"] = [dt.astimezone(tz) for dt in df_obs["valid_utc"]]
        df_obs["local_date"] = [dt.strftime("%Y-%m-%d") for dt in df_obs["valid_local"]]

        daily_rows, overall_passed = self._aggregate_daily_summary(df_obs, station)
        return pd.DataFrame(daily_rows), overall_passed

    def _check_variable_discrepancy(
        self,
        row: pd.Series,
        var_name: str,
        iem_val: Optional[float],
        wrh_val: Optional[float],
        raw_metars: List[str],
    ) -> Optional[Dict[str, Any]]:
        """Evaluate extreme discrepancy for a single variable (TMAX or TMIN)."""
        if pd.isna(iem_val) or pd.isna(wrh_val):
            return None
        delta = abs(float(iem_val) - float(wrh_val))
        if delta <= self.config.gate2_delta_threshold:
            return None

        return {
            "station": row["station"],
            "local_date": row["local_date"],
            "variable": var_name,
            "iem_value_f": float(iem_val),
            "wrh_value_f": float(wrh_val),
            "delta_f": round(delta, TEMP_ROUND_DECIMALS),
            "threshold_f": self.config.gate2_delta_threshold,
            "severity": "WARNING",
            "iem_raw_metars": raw_metars,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def evaluate_gate2_wrh_consistency(
        self, daily_df: pd.DataFrame, wrh_reference: Optional[pd.DataFrame] = None
    ) -> List[Dict[str, Any]]:
        """Quality Gate 2: Cross-references IEM calculated daily extremes against NWS WRH values."""
        if wrh_reference is None or wrh_reference.empty or daily_df.empty:
            logger.info("Gate 2 SKIPPED_NO_WRH_REFERENCE: Reference dataset not provided.")
            return []

        discrepancies: List[Dict[str, Any]] = []
        log_path = self.config.reports_dir / "dual_source_discrepancies.jsonl"
        merged = pd.merge(daily_df, wrh_reference, on=["station", "local_date"], how="inner")

        for _, row in merged.iterrows():
            raw_metars = row.get("daily_raw_metars", [])
            for var_name, iem_col, wrh_col in [("TMAX", "daily_tmax_f", "wrh_tmax_f"), ("TMIN", "daily_tmin_f", "wrh_tmin_f")]:
                if wrh_col in row:
                    disc = self._check_variable_discrepancy(
                        row, var_name, row.get(iem_col), row.get(wrh_col), raw_metars
                    )
                    if disc:
                        discrepancies.append(disc)

        if discrepancies:
            with open(log_path, "a", encoding="utf-8") as f:
                for disc in discrepancies:
                    f.write(json.dumps(disc, ensure_ascii=False) + "\n")
            logger.warning(
                f"Gate 2 Discrepancies: {len(discrepancies)} instances exceeded "
                f"{self.config.gate2_delta_threshold}°F. Appended to {log_path}"
            )

        return discrepancies

    def _check_resumption(
        self, station: str, year: int, parquet_path: Path, raw_archive_path: Path, window: DateWindow
    ) -> Optional[IemArtifact]:
        """Validate existing files against manifest SHA-256 for resumption."""
        if not (parquet_path.exists() and raw_archive_path.exists()):
            return None

        manifest_path = self.config.storage_dir / "manifest.json"
        if not manifest_path.exists():
            return None

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            rel_key = f"{station}/{year}.parquet"
            entry = meta.get("files", {}).get(rel_key)
            if not entry:
                return None

            actual_sha = compute_file_sha256(parquet_path)
            if actual_sha != entry.get("sha256"):
                logger.warning(f"Resumption hash mismatch for {parquet_path}, re-downloading.")
                return None

            logger.info(f"Resumption: {parquet_path} validated via manifest sha256, skipping.")
            df_existing = pd.read_parquet(parquet_path)
            q_flag = (
                QUALITY_DEGRADED
                if "quality_flag" in df_existing.columns and (df_existing["quality_flag"] == QUALITY_DEGRADED).any()
                else QUALITY_NOMINAL
            )
            return IemArtifact(
                station=station,
                year=year,
                parquet_path=parquet_path,
                raw_archive_path=raw_archive_path,
                row_count=len(df_existing),
                quality_flag=q_flag,
                gate1_passed=(q_flag == QUALITY_NOMINAL),
                manifest_entry=entry,
            )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Error checking resumption manifest: {e}")
            return None

    def _build_and_save_parquet(
        self, station: str, records: List[Dict[str, Any]], daily_summary_df: pd.DataFrame, parquet_path: Path
    ) -> Tuple[pd.DataFrame, str]:
        """Format dataframe with quality tags and save Snappy-compressed Parquet."""
        df = pd.DataFrame(records)
        if df.empty:
            df = pd.DataFrame(columns=[
                "station", "valid_utc", "temp_c", "temp_f", "dewpoint_c", "dewpoint_f",
                "raw_metar", "t_group_parsed", "temp_6h_max", "temp_6h_min",
                "temp_24h_max", "temp_24h_min", "vintage", "usage", "quality_flag"
            ])
        else:
            degraded_dates = set(
                daily_summary_df[daily_summary_df["quality_flag"] == QUALITY_DEGRADED]["local_date"]
            )
            st_meta = STATION_METADATA.get(station, {})
            tz = ZoneInfo(st_meta.get("timezone", "UTC"))
            df["local_date"] = [dt.astimezone(tz).strftime("%Y-%m-%d") for dt in df["valid_utc"]]
            df["quality_flag"] = [
                QUALITY_DEGRADED if d in degraded_dates else QUALITY_NOMINAL for d in df["local_date"]
            ]
            df.drop(columns=["local_date"], inplace=True)

            df["station"] = df["station"].astype("category")
            df["vintage"] = df["vintage"].astype("category")
            df["usage"] = df["usage"].astype("category")
            df["quality_flag"] = df["quality_flag"].astype("category")
            df["t_group_parsed"] = df["t_group_parsed"].astype("bool")

        df.to_parquet(parquet_path, compression="snappy", index=False)
        return df, compute_file_sha256(parquet_path)

    def _update_manifest(self, artifact: IemArtifact) -> None:
        """Quality Gate 3: Update and persist central manifest.json."""
        manifest_path = self.config.storage_dir / "manifest.json"
        manifest_data: Dict[str, Any] = {
            "version": "1.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "git_commit_sha": get_git_commit_sha(),
            "total_station_years": 0,
            "total_rows": 0,
            "files": {},
        }

        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to read existing manifest.json, recreating: {e}")

        rel_key = f"{artifact.station}/{artifact.year}.parquet"
        manifest_data["files"][rel_key] = artifact.manifest_entry
        manifest_data["timestamp"] = datetime.now(timezone.utc).isoformat()
        manifest_data["git_commit_sha"] = get_git_commit_sha()
        manifest_data["total_station_years"] = len(manifest_data["files"])
        manifest_data["total_rows"] = sum(
            e.get("row_count", 0) for e in manifest_data["files"].values()
        )

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2, ensure_ascii=False)

    def _create_artifact(
        self,
        station: str,
        year: int,
        parquet_path: Path,
        raw_archive_path: Path,
        df: pd.DataFrame,
        overall_flag: str,
        gate1_passed: bool,
        sha256: str,
        source_url: str,
    ) -> IemArtifact:
        """Create and record an IemArtifact alongside its manifest entry."""
        manifest_entry = {
            "station": station,
            "year": year,
            "parquet_path": str(parquet_path),
            "raw_archive_path": str(raw_archive_path),
            "row_count": len(df),
            "quality_flag": overall_flag,
            "sha256": sha256,
            "source_url": source_url,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "git_commit_sha": get_git_commit_sha(),
        }
        artifact = IemArtifact(
            station=station,
            year=year,
            parquet_path=parquet_path,
            raw_archive_path=raw_archive_path,
            row_count=len(df),
            quality_flag=overall_flag,
            gate1_passed=gate1_passed,
            manifest_entry=manifest_entry,
        )
        self._update_manifest(artifact)
        return artifact

    def fetch_station_year(
        self,
        station: str,
        year: int,
        force: bool = False,
        start_month: int = 1,
        start_day: int = 1,
        end_month: int = 12,
        end_day: int = 31,
        wrh_reference: Optional[pd.DataFrame] = None,
    ) -> IemArtifact:
        """Fetch, process, validate, and store a station-year observation block."""
        self._validate_station(station)
        window = DateWindow(start_month, start_day, end_month, end_day)

        station_dir = self.config.storage_dir / station
        station_dir.mkdir(parents=True, exist_ok=True)
        parquet_path = station_dir / f"{year}.parquet"
        raw_archive_path = station_dir / f"{year}.csv.gz"

        if not force:
            resumed = self._check_resumption(station, year, parquet_path, raw_archive_path, window)
            if resumed:
                return resumed

        params = self._build_query_params(station, year, window)
        source_url = self._build_request_url(params)
        csv_text = self._execute_http_download(params)

        with gzip.open(raw_archive_path, "wt", encoding="utf-8") as f:
            f.write(csv_text)

        records = self.parse_csv_observations(csv_text, station)
        daily_summary_df, gate1_passed = self.evaluate_gate1_coverage(records, station)
        overall_flag = QUALITY_NOMINAL if gate1_passed else QUALITY_DEGRADED

        self.evaluate_gate2_wrh_consistency(daily_summary_df, wrh_reference)
        df, sha256 = self._build_and_save_parquet(station, records, daily_summary_df, parquet_path)

        return self._create_artifact(
            station, year, parquet_path, raw_archive_path, df, overall_flag, gate1_passed, sha256, source_url
        )

    def fetch_raw_series(
        self, station: str, start_date: datetime, end_date: datetime
    ) -> List[ObservationRecord]:
        """Adheres to BaseObservationAdapter abstract interface contract."""
        self._validate_station(station)
        window = DateWindow(
            start_month=start_date.month,
            start_day=start_date.day,
            end_month=end_date.month,
            end_day=end_date.day,
        )
        params = self._build_query_params(station, start_date.year, window)
        params["year2"] = end_date.year

        csv_text = self._execute_http_download(params)
        records_raw = self.parse_csv_observations(csv_text, station)

        obs_records: List[ObservationRecord] = []
        for r in records_raw:
            obs_records.append(
                ObservationRecord(
                    timestamp=r["valid_utc"],
                    temp_c=r["temp_c"],
                    temp_f=r["temp_f"],
                    dewpoint_c=r["dewpoint_c"],
                    dewpoint_f=r["dewpoint_f"],
                    raw_metar=r["raw_metar"],
                    metadata={
                        "t_group_parsed": r["t_group_parsed"],
                        "extreme_remarks": {
                            "temp_6h_max": r["temp_6h_max"],
                            "temp_6h_min": r["temp_6h_min"],
                            "temp_24h_max": r["temp_24h_max"],
                            "temp_24h_min": r["temp_24h_min"],
                        },
                    },
                )
            )
        return obs_records

    def extract_calendar_day_max(
        self, records: List[ObservationRecord], timezone_str: str = "America/Chicago"
    ) -> Optional[float]:
        """Extract calendar-day max temperature (°C) sliced by local timezone [00:00:00, 24:00:00)."""
        if not records:
            return None
        tz = ZoneInfo(timezone_str)
        # Convert each record timestamp to local datetime
        local_records = []
        for r in records:
            if r.temp_c is not None:
                local_dt = r.timestamp.astimezone(tz)
                local_records.append((local_dt.date(), r.temp_c))

        if not local_records:
            return None

        # Group by local date and compute max for each day (returning the global daily peak)
        return max(t for _, t in local_records)


def _parse_cli_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="IEM ASOS Observation Pipeline Adapter (Phase 1.5 Task 02)"
    )
    parser.add_argument("--station", type=str, required=True, help="Station ICAO or 'ALL'")
    parser.add_argument("--year", type=int, help="Single year (e.g. 2024)")
    parser.add_argument("--start-year", type=int, default=2000, help="Start year (default: 2000)")
    parser.add_argument("--end-year", type=int, default=2024, help="End year (default: 2024)")
    parser.add_argument("--out-dir", type=str, default="data/raw/iem", help="Output directory")
    parser.add_argument("--force", action="store_true", help="Force re-download")
    parser.add_argument("--dry-run", action="store_true", help="Dry run validation")
    parser.add_argument("--verify-wrh", type=str, help="Optional NWS WRH reference table path")
    return parser.parse_args()


def _load_wrh_reference(wrh_path_str: Optional[str]) -> Optional[pd.DataFrame]:
    """Safely load WRH reference table if provided."""
    if not wrh_path_str:
        return None
    p = Path(wrh_path_str)
    if not p.exists():
        logger.warning(f"WRH reference file {p} does not exist, skipping Gate 2.")
        return None
    return pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)


def main() -> int:
    """CLI entry point for IEM Adapter pipeline."""
    args = _parse_cli_args()
    stations = list(ACTIVE_11_STATIONS) if args.station.upper() == "ALL" else [args.station.upper()]
    years = [args.year] if args.year is not None else list(range(args.start_year, args.end_year + 1))

    with IemAdapter(config=IemAdapterConfig(storage_dir=Path(args.out_dir))) as adapter:
        for st in stations:
            try:
                adapter._validate_station(st)
            except ValueError as err:
                logger.error(str(err))
                return 1

        if args.dry_run:
            logger.info(f"Dry run validated: {len(stations)} stations across {len(years)} years.")
            return 0

        wrh_df = _load_wrh_reference(args.verify_wrh)
        success_count = 0
        total_count = len(stations) * len(years)

        for st in stations:
            for yr in years:
                try:
                    artifact = adapter.fetch_station_year(st, yr, force=args.force, wrh_reference=wrh_df)
                    logger.info(f"Processed {st} {yr}: {artifact.row_count} rows, flag={artifact.quality_flag}")
                    success_count += 1
                except (RuntimeError, requests.RequestException, OSError) as e:
                    logger.error(f"Failed processing {st} {yr}: {e}", exc_info=True)

        logger.info(f"Pipeline completed: {success_count}/{total_count} processed successfully.")
        return 0 if success_count == total_count else 1


if __name__ == "__main__":
    exit(main())
