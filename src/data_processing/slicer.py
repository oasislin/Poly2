#!/usr/bin/env python3
"""
ObservationSlicer: High-resolution ASOS/METAR Feature Slicing Engine (Phase 1.5 Task 06).

Transforms raw continuous/non-periodic observation records into structured daily
feature tables for EMOS training and GEFS factor alignment:
1. ADR-0009 D3 dual-track separation:
   - Settlement target: tmax/tmin_daily_all_reports (all reports, METAR + SPECI).
   - Noise-resilient feature: tmax/tmin_daily_hourly_only (nominal routine hourly METARs).
   - Dual-unit retention: °C primary and °F (_f suffix).
   - Discrepancy indicator: has_speci_divergence.
2. Calendar axis projection: Mandatory resolve_day_of_year (2020 leap year base, 1..366).
3. DST 23h/25h adaptive local calendar day slicing [00:00, 24:00 LT).
4. Station-aware hourly window: Default :50-:55 with KSFO (:56) and KBKF (:58) adaptation.
5. Vintage and usage tiering: era1 / stress-test-only (2000-2018), era2 / training-ready (2019-2026).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, Union
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from src.data_acquisition.observation_adapter import ObservationRecord
from src.data_processing.calendar_day_qc import CalendarDaySlicer, normalize_target_date
from src.data_processing.constants import ACTIVE_11_STATIONS, STATION_METADATA
from src.modeling.climate_floor import resolve_day_of_year

logger = logging.getLogger("poly.data_processing.slicer")

# Domain Named Constants
ERA2_START_YEAR: int = 2019
VintageType = Literal["era1", "era2"]
UsageType = Literal["stress-test-only", "training-ready"]
QualityFlagType = Literal["nominal", "degraded"]

VINTAGE_ERA1: VintageType = "era1"
VINTAGE_ERA2: VintageType = "era2"
USAGE_STRESS_TEST_ONLY: UsageType = "stress-test-only"
USAGE_TRAINING_READY: UsageType = "training-ready"

QUALITY_NOMINAL: QualityFlagType = "nominal"
QUALITY_DEGRADED: QualityFlagType = "degraded"

DEFAULT_HOURLY_WINDOW: Tuple[int, int] = (50, 55)

# Station-specific nominal hourly window offsets
# 9 stations broadcast routine METAR in :51-:53. Exceptions: KSFO at :56, KBKF at :58.
STATION_HOURLY_WINDOWS: Dict[str, Tuple[int, int]] = {
    "KSFO": (50, 56),
    "KBKF": (50, 58),
}

C_TO_F_SCALE: float = 1.8
C_TO_F_OFFSET: float = 32.0
ROUND_DECIMALS_F: int = 4
ROUND_DECIMALS_C: int = 4
MIN_DAILY_OBS_NOMINAL: int = 4
SPECI_REGEX = re.compile(r"(?:^\s*SPECI\b|\bSPECI\b)", re.IGNORECASE)


def celsius_to_fahrenheit(temp_c: Optional[float]) -> Optional[float]:
    """Convert Celsius to Fahrenheit with fixed precision rounding."""
    if temp_c is None or pd.isna(temp_c):
        return None
    return round(float(temp_c) * C_TO_F_SCALE + C_TO_F_OFFSET, ROUND_DECIMALS_F)


def fahrenheit_to_celsius(temp_f: Optional[float]) -> Optional[float]:
    """Convert Fahrenheit to Celsius with fixed precision rounding."""
    if temp_f is None or pd.isna(temp_f):
        return None
    return round((float(temp_f) - C_TO_F_OFFSET) / C_TO_F_SCALE, ROUND_DECIMALS_C)


def validate_active_station(station: str) -> str:
    """Enforce Active 11 station universe compliance."""
    st_norm = station.strip().upper()
    if st_norm not in ACTIVE_11_STATIONS:
        raise ValueError(
            f"Station '{st_norm}' is not in active 11 stations: {ACTIVE_11_STATIONS}. "
            "Decommissioned stations (e.g. KDCA, ZSPD, KDEN) are strictly prohibited."
        )
    return st_norm


def check_speci_divergence(
    tmax_all: Optional[float],
    tmax_hr: Optional[float],
    tmin_all: Optional[float],
    tmin_hr: Optional[float],
    tol: float = 1e-4,
) -> bool:
    """Check if all_reports extrema diverge from hourly_only extrema without null-defaulting bugs."""
    if (tmax_all is not None and tmax_hr is None) or (tmin_all is not None and tmin_hr is None):
        return True
    if tmax_all is not None and tmax_hr is not None and abs(tmax_all - tmax_hr) > tol:
        return True
    if tmin_all is not None and tmin_hr is not None and abs(tmin_all - tmin_hr) > tol:
        return True
    return False


@dataclass
class DailyFeatureRecord:
    """Standardized daily sliced feature and target record."""

    station: str
    target_date: str
    local_date: str
    day_of_year: int
    tmax_daily_all_reports: Optional[float]
    tmin_daily_all_reports: Optional[float]
    tmax_daily_hourly_only: Optional[float]
    tmin_daily_hourly_only: Optional[float]
    tmax_daily_all_reports_f: Optional[float]
    tmin_daily_all_reports_f: Optional[float]
    tmax_daily_hourly_only_f: Optional[float]
    tmin_daily_hourly_only_f: Optional[float]
    total_obs_count: int
    hourly_obs_count: int
    has_speci_divergence: bool
    vintage: VintageType
    usage: UsageType
    quality_flag: QualityFlagType

    def to_dict(self) -> Dict[str, Any]:
        """Convert dataclass to dictionary."""
        return asdict(self)


class ObservationSlicer:
    """
    Production-grade slicer for IEM ASOS observations.
    Implements DST-adaptive calendar day slicing, ADR-0009 dual-track
    aggregation, unified 2020 leap-year DOY projection, and vintage tagging.
    """

    def __init__(
        self,
        hourly_windows: Optional[Dict[str, Tuple[int, int]]] = None,
        calendar_slicer: Optional[CalendarDaySlicer] = None,
    ):
        self.hourly_windows = hourly_windows or dict(STATION_HOURLY_WINDOWS)
        self.calendar_slicer = calendar_slicer or CalendarDaySlicer()

    def get_hourly_window(self, station: str) -> Tuple[int, int]:
        """Resolve station-specific nominal hourly METAR minute window."""
        st_norm = validate_active_station(station)
        return self.hourly_windows.get(st_norm, DEFAULT_HOURLY_WINDOW)

    def _determine_vintage_usage(self, year: int) -> Tuple[VintageType, UsageType]:
        """Determine vintage and usage tiers based on calendar year."""
        if year >= ERA2_START_YEAR:
            return VINTAGE_ERA2, USAGE_TRAINING_READY
        return VINTAGE_ERA1, USAGE_STRESS_TEST_ONLY

    def _prepare_local_series(
        self, df_obs: pd.DataFrame, station: str, hourly_window: Optional[Tuple[int, int]] = None
    ) -> pd.DataFrame:
        """Project observation timestamps to local timezone, filter out SPECIs from hourly window."""
        st_norm = validate_active_station(station)
        tz = ZoneInfo(STATION_METADATA.get(st_norm, {}).get("timezone", "UTC"))

        df = df_obs.copy()
        if not pd.api.types.is_datetime64_any_dtype(df["valid_utc"]):
            df["valid_utc"] = pd.to_datetime(df["valid_utc"])
        if df["valid_utc"].dt.tz is None:
            df["valid_utc"] = df["valid_utc"].dt.tz_localize(timezone.utc)
        else:
            df["valid_utc"] = df["valid_utc"].dt.tz_convert(timezone.utc)

        df["local_dt"] = df["valid_utc"].dt.tz_convert(tz)
        df["local_date"] = df["local_dt"].dt.strftime("%Y-%m-%d")

        win_min, win_max = hourly_window or self.get_hourly_window(st_norm)
        mins = df["local_dt"].dt.minute
        in_window = (mins >= win_min) & (mins <= win_max)

        # Exclude explicit SPECI reports from nominal hourly window
        metar_series = df["raw_metar"].astype(str) if "raw_metar" in df.columns else pd.Series("", index=df.index)
        is_speci = metar_series.str.contains(SPECI_REGEX)
        df["is_hourly_window"] = in_window & (~is_speci)

        if "temp_c" not in df.columns and "temp_f" in df.columns:
            df["temp_c"] = [fahrenheit_to_celsius(v) for v in df["temp_f"]]
        elif "temp_f" not in df.columns and "temp_c" in df.columns:
            df["temp_f"] = [celsius_to_fahrenheit(v) for v in df["temp_c"]]

        return df

    def _compute_extremes_and_counts(
        self, group: pd.DataFrame
    ) -> Tuple[int, int, Optional[float], Optional[float], Optional[float], Optional[float]]:
        """Extract observation counts and extreme Celsius temperatures for all and hourly subsets."""
        total_obs = len(group)
        hourly_sub = group[group["is_hourly_window"]]
        hourly_obs = len(hourly_sub)

        valid_c_all = group["temp_c"].dropna()
        tmax_all_c = float(valid_c_all.max()) if not valid_c_all.empty else None
        tmin_all_c = float(valid_c_all.min()) if not valid_c_all.empty else None

        valid_c_hr = hourly_sub["temp_c"].dropna()
        tmax_hr_c = float(valid_c_hr.max()) if not valid_c_hr.empty else None
        tmin_hr_c = float(valid_c_hr.min()) if not valid_c_hr.empty else None

        return total_obs, hourly_obs, tmax_all_c, tmin_all_c, tmax_hr_c, tmin_hr_c

    def _aggregate_single_day(
        self,
        group: pd.DataFrame,
        station: str,
        date_str: str,
    ) -> DailyFeatureRecord:
        """Aggregate one local calendar day's observations into a DailyFeatureRecord (strictly <= 50 lines)."""
        total_obs, hourly_obs, tmax_all_c, tmin_all_c, tmax_hr_c, tmin_hr_c = self._compute_extremes_and_counts(group)
        has_div = check_speci_divergence(tmax_all_c, tmax_hr_c, tmin_all_c, tmin_hr_c)

        doy = resolve_day_of_year(date_str)
        day_year = int(date_str.split("-")[0])
        vintage, usage = self._determine_vintage_usage(day_year)

        quality = QUALITY_NOMINAL if (total_obs >= MIN_DAILY_OBS_NOMINAL and tmax_all_c is not None) else QUALITY_DEGRADED

        return DailyFeatureRecord(
            station=station,
            target_date=date_str,
            local_date=date_str,
            day_of_year=doy,
            tmax_daily_all_reports=tmax_all_c,
            tmin_daily_all_reports=tmin_all_c,
            tmax_daily_hourly_only=tmax_hr_c,
            tmin_daily_hourly_only=tmin_hr_c,
            tmax_daily_all_reports_f=celsius_to_fahrenheit(tmax_all_c),
            tmin_daily_all_reports_f=celsius_to_fahrenheit(tmin_all_c),
            tmax_daily_hourly_only_f=celsius_to_fahrenheit(tmax_hr_c),
            tmin_daily_hourly_only_f=celsius_to_fahrenheit(tmin_hr_c),
            total_obs_count=total_obs,
            hourly_obs_count=hourly_obs,
            has_speci_divergence=has_div,
            vintage=vintage,
            usage=usage,
            quality_flag=quality,
        )

    def slice_dataframe(
        self,
        df_obs: pd.DataFrame,
        station: str,
        target_year: Optional[int] = None,
        hourly_window: Optional[Tuple[int, int]] = None,
    ) -> pd.DataFrame:
        """Slice raw observation DataFrame into structured daily feature DataFrame."""
        fields = [f.name for f in DailyFeatureRecord.__dataclass_fields__.values()]
        if df_obs.empty:
            return pd.DataFrame(columns=fields)

        st_norm = validate_active_station(station)
        prepared_df = self._prepare_local_series(df_obs, st_norm, hourly_window=hourly_window)

        records: List[Dict[str, Any]] = []
        for date_str, group in prepared_df.groupby("local_date", sort=True):
            if target_year is not None:
                day_year = int(str(date_str).split("-")[0])
                if day_year != target_year:
                    continue
            rec = self._aggregate_single_day(group, st_norm, str(date_str))
            records.append(rec.to_dict())

        df_out = pd.DataFrame(records)
        if df_out.empty:
            return pd.DataFrame(columns=fields)
        return df_out.sort_values("local_date").reset_index(drop=True)
