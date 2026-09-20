#!/usr/bin/env python3
"""
DatasetPartitioner: Lead time bucketing, nominal local time conversion, and seasonal matrix partitioner (Ticket 2.2-03 / Issue #16).

Implements:
    - 4-season grouping: Spring (3-5), Summer (6-8), Autumn (9-11), Winter (12-2)
    - Nominal occurrence hours: Max 15:00 Local Time, Min 06:00 Local Time
    - Station UTC offsets: ZSPD (+8 UTC), KDEN (-7 UTC / Mountain Time)
    - round_to_nearest_6h lead time bucketing
    - Discrete matrix training nodes: Max {54h, 30h, 6h}, Min {48h, 24h}
    - 40 standard training partition buckets (2 stations x 4 seasons x 5 nodes)
"""

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

from src.data_processing.constants import (
    ACTIVE_11_STATIONS,
    STATION_METADATA,
    STATION_TIMEZONES,
)

# Standard station offsets and nominal extrema hours
STATION_UTC_OFFSETS: Dict[str, int] = {
    "ZSPD": 8,   # Shanghai Pudong (UTC+8)
    "KDEN": -7,  # Denver International (UTC-7 Mountain Standard)
}

NOMINAL_LOCAL_HOURS: Dict[str, int] = {
    "max": 15,  # 15:00 Local Time (diurnal peak temperature)
    "min": 6,   # 06:00 Local Time (diurnal minimum temperature / near sunrise)
}

LEAD_TIME_NODES: Dict[str, List[int]] = {
    "max": [54, 30, 6],
    "min": [48, 24],
}

SEASONS: List[str] = ["Spring", "Summer", "Autumn", "Winter"]

TRAIN_START_YEAR: int = 2000
TRAIN_END_YEAR: int = 2018
VAL_YEAR: int = 2019

FORBIDDEN_PATH_SUBSTRINGS: Tuple[str, ...] = (
    "legacy-v1-suspect",
    "wunderground",
)


def validate_safe_dataset_path(path: Union[str, Path]) -> Path:
    """Enforce strict isolation blocking deprecated/polluted legacy data paths."""
    p_str = str(path).lower()
    for forbidden in FORBIDDEN_PATH_SUBSTRINGS:
        if forbidden in p_str:
            raise ValueError(
                f"Access to deprecated/polluted legacy path is strictly blocked: '{path}'. "
                f"Matched forbidden token: '{forbidden}'."
            )
    return Path(path)


def validate_time_wall(start_year: int, end_year: int, split_type: str = "train") -> None:
    """Enforce strict out-of-sample (OOS) time-wall discipline.

    - Train split: strictly bounded within [2000, 2018].
    - Validation split: strictly locked to 2019.
    """
    if start_year > end_year:
        raise ValueError(f"start_year ({start_year}) cannot be greater than end_year ({end_year})")

    s_type = split_type.lower()
    if s_type == "train":
        if start_year < TRAIN_START_YEAR:
            raise ValueError(f"start_year ({start_year}) cannot be prior to {TRAIN_START_YEAR}")
        if end_year > TRAIN_END_YEAR:
            raise ValueError(
                f"Training set violates OOS boundary! Strict redline requires end_year <= {TRAIN_END_YEAR}, "
                f"got {end_year}. 2019+ data must never be consumed in training."
            )
    elif s_type == "validation":
        if start_year != VAL_YEAR or end_year != VAL_YEAR:
            raise ValueError(
                f"Validation set strictly locked to {VAL_YEAR}, got [{start_year}, {end_year}]. "
                "Out-of-sample verification requires exactly year 2019."
            )
    else:
        raise ValueError(f"Unknown split_type: '{split_type}', expected 'train' or 'validation'")


def validate_station_id(station_id: str) -> str:
    """Validate station identifier against Active 11 station universe or legacy test stations."""
    st_norm = station_id.strip().upper()
    if st_norm in ACTIVE_11_STATIONS or st_norm in STATION_UTC_OFFSETS:
        return st_norm
    raise ValueError(
        f"Unknown or non-compliant station_id: '{station_id}'. Allowed stations: "
        f"{ACTIVE_11_STATIONS} (or legacy {list(STATION_UTC_OFFSETS.keys())})"
    )


class DatasetPartitioner:
    """Manages seasonal dataset splitting and lead-time discretization into standard training matrices."""

    @staticmethod
    def validate_safe_dataset_path(path: Union[str, Path]) -> Path:
        """Enforce strict isolation blocking deprecated/polluted legacy data paths."""
        return validate_safe_dataset_path(path)

    @staticmethod
    def validate_time_wall(start_year: int, end_year: int, split_type: str = "train") -> None:
        """Enforce strict out-of-sample (OOS) time-wall boundaries."""
        return validate_time_wall(start_year, end_year, split_type=split_type)

    @staticmethod
    def round_to_nearest_6h(lead_hours: Union[float, np.ndarray, pd.Series]) -> Union[int, np.ndarray]:
        """Round continuous forecast lead hours to the nearest 6-hour discrete multiple."""
        arr = np.asarray(lead_hours, dtype=np.float64)
        rounded = np.round(arr / 6.0) * 6.0
        if np.ndim(rounded) == 0:
            return int(rounded.item())
        return rounded.astype(int)

    @staticmethod
    def get_season(date_or_month: Union[int, date, datetime, str]) -> str:
        """Map a month number, date, or date string to its meteorological season."""
        if isinstance(date_or_month, int):
            month = date_or_month
        elif isinstance(date_or_month, (date, datetime)):
            month = date_or_month.month
        elif isinstance(date_or_month, str):
            dt = pd.to_datetime(date_or_month)
            month = dt.month
        else:
            raise TypeError(f"Unsupported type for season mapping: {type(date_or_month)}")

        if month in (3, 4, 5):
            return "Spring"
        elif month in (6, 7, 8):
            return "Summer"
        elif month in (9, 10, 11):
            return "Autumn"
        elif month in (12, 1, 2):
            return "Winter"
        else:
            raise ValueError(f"Invalid month integer: {month}")

    @staticmethod
    def compute_nominal_lead_hours(
        station_id: str,
        target_type: str,
        init_datetime: Union[datetime, str, pd.Timestamp],
        target_date: Union[date, str, pd.Timestamp],
    ) -> float:
        """Compute continuous lead hours from forecast init UTC to the nominal diurnal extreme time in UTC.

        Supports both Active 10/11 trading stations (via IANA timezone resolution) and legacy stations.
        """
        station = validate_station_id(station_id)

        target_t = target_type.lower()
        if target_t not in NOMINAL_LOCAL_HOURS:
            raise ValueError(f"Unknown target_type: {target_type}, expected 'max' or 'min'")

        init_dt = pd.to_datetime(init_datetime)
        t_date = pd.to_datetime(target_date).date()
        nominal_local_hour = NOMINAL_LOCAL_HOURS[target_t]

        if station in STATION_TIMEZONES:
            tz = ZoneInfo(STATION_TIMEZONES[station])
            local_dt = datetime(t_date.year, t_date.month, t_date.day, nominal_local_hour, 0, 0, tzinfo=tz)
            nominal_utc_dt = local_dt.astimezone(timezone.utc)
            if init_dt.tzinfo is None:
                init_utc_dt = init_dt.tz_localize("UTC")
            else:
                init_utc_dt = init_dt.tz_convert("UTC")
            lead_delta = (nominal_utc_dt - init_utc_dt.to_pydatetime()).total_seconds() / 3600.0
            return float(lead_delta)
        else:
            # Fallback for legacy stations with fixed UTC offsets
            utc_offset = STATION_UTC_OFFSETS[station]
            local_dt = datetime(t_date.year, t_date.month, t_date.day, nominal_local_hour, 0, 0)
            nominal_utc_dt = local_dt - timedelta(hours=utc_offset)
            init_naive = init_dt.to_pydatetime()
            if init_naive.tzinfo is not None:
                init_naive = init_naive.replace(tzinfo=None)
            lead_delta = (nominal_utc_dt - init_naive).total_seconds() / 3600.0
            return float(lead_delta)

    @staticmethod
    def get_contained_lead_windows(
        station_id: str,
        target_date: Union[date, str, pd.Timestamp],
        init_time_utc: Optional[Union[datetime, str, pd.Timestamp]] = None,
        max_lead_hours: int = 120,
    ) -> List[int]:
        """Dynamically compute 6h forecast lead windows completely contained within station local calendar day.

        Enforces ADR-0008 timezone and daylight saving time adaptive scheduling.
        """
        from src.data_processing.time_aligner import select_contained_6h_windows
        st_norm = validate_station_id(station_id)
        t_d = pd.to_datetime(target_date).date()
        if init_time_utc is None:
            init_dt = datetime.combine(t_d - timedelta(days=1), time(0, 0), tzinfo=timezone.utc)
        else:
            init_dt = pd.to_datetime(init_time_utc)
            if init_dt.tzinfo is None:
                init_dt = init_dt.replace(tzinfo=timezone.utc)
            else:
                init_dt = init_dt.astimezone(timezone.utc)
        return select_contained_6h_windows(
            init_time_utc=init_dt,
            target_date=t_d,
            tz_or_station=st_norm,
            max_lead_hours=max_lead_hours,
        )

    @classmethod
    def get_lead_time_nodes(cls, target_type: str) -> List[int]:
        """Return the list of standard discrete lead time training nodes for target type."""
        t_type = target_type.lower()
        if t_type not in LEAD_TIME_NODES:
            raise ValueError(f"Unknown target_type: {target_type}, expected 'max' or 'min'")
        return list(LEAD_TIME_NODES[t_type])

    @classmethod
    def split_by_season(
        cls,
        df: pd.DataFrame,
        date_col: str = "target_date",
    ) -> Dict[str, pd.DataFrame]:
        """Split a DataFrame into 4 seasonal sub-DataFrames based on the date column."""
        if date_col not in df.columns:
            raise KeyError(f"Date column '{date_col}' not found in DataFrame columns: {df.columns.tolist()}")

        dt_series = pd.to_datetime(df[date_col])
        seasons_series = dt_series.dt.month.map(lambda m: cls.get_season(m))

        return {
            season: df[seasons_series == season].copy()
            for season in SEASONS
        }

    @classmethod
    def get_all_matrix_keys(cls) -> List[Tuple[str, str, str, int]]:
        """Return the exhaustive list of 40 training matrix keys: (station_id, season, target_type, lead_bucket)."""
        keys = []
        for station in sorted(STATION_UTC_OFFSETS.keys()):
            for season in SEASONS:
                for target_type in ["max", "min"]:
                    for lead in LEAD_TIME_NODES[target_type]:
                        keys.append((station, season, target_type, lead))
        return keys

    @classmethod
    def load_aligned_dataset(
        cls,
        station: str,
        years: Sequence[int],
        base_dir: Union[str, Path] = Path("data/processed/calib-dataset-v2.0"),
        target_type: Optional[str] = None,
        lead_bucket: Optional[int] = None,
    ) -> pd.DataFrame:
        """Load and align observation features and GEFS ensemble factors from calib-dataset-v2.0.

        Merges:
        - Observation truth from `features/{station}/{year}.parquet` (ADR-0009 full-report extreme retention)
        - 5-member ensemble forecast from `gefs_factors/{station}/{year}.parquet` (converted from Kelvin to Fahrenheit)

        Computes:
        - `ensemble_mean` = mean(temp_f)
        - `ensemble_variance` = var(temp_f, ddof=1)
        - `observed_temp` = tmax_daily_all_reports_f or tmin_daily_all_reports_f

        Returns:
            pd.DataFrame with columns:
                ['station', 'target_date', 'season', 'target_type', 'lead_hours',
                 'ensemble_mean', 'ensemble_variance', 'observed_temp']
        """
        base_path = validate_safe_dataset_path(base_dir)
        st_norm = validate_station_id(station)

        feat_dir = base_path / "features" / st_norm
        gefs_dir = base_path / "gefs_factors" / st_norm

        feat_dfs: List[pd.DataFrame] = []
        gefs_dfs: List[pd.DataFrame] = []

        for y in sorted(years):
            feat_file = feat_dir / f"{y}.parquet"
            gefs_file = gefs_dir / f"{y}.parquet"

            if not feat_file.exists():
                raise FileNotFoundError(f"Feature parquet missing for station {st_norm} year {y}: {feat_file}")
            if not gefs_file.exists():
                raise FileNotFoundError(f"GEFS factor parquet missing for station {st_norm} year {y}: {gefs_file}")

            feat_dfs.append(pd.read_parquet(feat_file))
            gefs_dfs.append(pd.read_parquet(gefs_file))

        if not feat_dfs:
            return pd.DataFrame()

        full_feat = pd.concat(feat_dfs, ignore_index=True)
        full_gefs = pd.concat(gefs_dfs, ignore_index=True)

        # Convert Kelvin to Fahrenheit
        full_gefs["temp_f"] = (full_gefs["value_K"] - 273.15) * 1.8 + 32.0

        # Group by (station, target_date, variable, lead_hours) to aggregate ensemble statistics
        agg_gefs = (
            full_gefs.groupby(["station", "target_date", "variable", "lead_hours"], observed=True)["temp_f"]
            .agg(
                ensemble_mean="mean",
                ensemble_variance=lambda s: float(np.var(s, ddof=1)) if len(s) > 1 else 0.0,
            )
            .reset_index()
        )

        # Prepare observation subset
        feat_sub = full_feat[[
            "station", "target_date", "tmax_daily_all_reports_f", "tmin_daily_all_reports_f"
        ]].copy()

        # Inner join features with GEFS factors
        merged = pd.merge(agg_gefs, feat_sub, on=["station", "target_date"])

        # Map variable to target_type ('max' / 'min') and assign true observed_temp
        merged["target_type"] = merged["variable"].map({"tmax": "max", "tmin": "min"})
        merged["observed_temp"] = np.where(
            merged["target_type"] == "max",
            merged["tmax_daily_all_reports_f"],
            merged["tmin_daily_all_reports_f"],
        )

        # Map season
        merged["season"] = [cls.get_season(d) for d in merged["target_date"]]

        # Optional filters
        if target_type is not None:
            t_norm = target_type.strip().lower()
            if t_norm in ("tmax", "max"):
                merged = merged[merged["target_type"] == "max"]
            elif t_norm in ("tmin", "min"):
                merged = merged[merged["target_type"] == "min"]

        if lead_bucket is not None:
            merged = merged[merged["lead_hours"] == lead_bucket]

        output_cols = [
            "station",
            "target_date",
            "season",
            "target_type",
            "lead_hours",
            "ensemble_mean",
            "ensemble_variance",
            "observed_temp",
        ]
        return merged[output_cols].sort_values(["target_date", "target_type", "lead_hours"]).reset_index(drop=True)

    @classmethod
    def load_training_dataset(
        cls,
        station: str,
        start_year: int = TRAIN_START_YEAR,
        end_year: int = TRAIN_END_YEAR,
        target_type: Optional[str] = None,
        lead_bucket: Optional[int] = None,
        base_dir: Union[str, Path] = Path("data/processed/calib-dataset-v2.0"),
    ) -> pd.DataFrame:
        """Load training dataset strictly locked to [2000, 2018] time-wall."""
        validate_time_wall(start_year, end_year, split_type="train")
        years = list(range(start_year, end_year + 1))
        return cls.load_aligned_dataset(
            station=station,
            years=years,
            base_dir=base_dir,
            target_type=target_type,
            lead_bucket=lead_bucket,
        )

    @classmethod
    def load_validation_dataset(
        cls,
        station: str,
        year: int = VAL_YEAR,
        target_type: Optional[str] = None,
        lead_bucket: Optional[int] = None,
        base_dir: Union[str, Path] = Path("data/processed/calib-dataset-v2.0"),
    ) -> pd.DataFrame:
        """Load validation dataset strictly locked to 2019 time-wall."""
        validate_time_wall(year, year, split_type="validation")
        return cls.load_aligned_dataset(
            station=station,
            years=[year],
            base_dir=base_dir,
            target_type=target_type,
            lead_bucket=lead_bucket,
        )

