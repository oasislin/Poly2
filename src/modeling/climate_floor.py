#!/usr/bin/env python3
"""
ClimateFloor: Historical baseline and variance floor reconstruction (Phase 1.5 Task 05).

Calculates production-grade daily climatological mean (mu_clim) and smooth variance floor
(sigma_clim, sigma_clim^2) across the 11 active US trading stations.
Strictly Out-Of-Sample (OOS): strictly consumes 2000-2018 data, blocking 2019+ data.
Enforces ADR-0009 full-report extreme retention, 31-day sliding window, circular periodic
Gaussian smoothing (seamless Dec 31 -> Jan 1 boundary), and physical plausibility gates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d

from src.data_processing.constants import ACTIVE_11_STATIONS, STATION_METADATA

logger = logging.getLogger("poly.modeling.climate_floor")

# Domain Named Constants (Zero magic numbers)
TRAIN_START_YEAR: int = 2000
TRAIN_END_YEAR: int = 2018
OOS_FORBIDDEN_START_YEAR: int = 2019
REFERENCE_LEAP_YEAR: int = 2020
DAYS_IN_LEAP_YEAR: int = 366
FEB_29_DOY: int = 60
DEC_31_DOY: int = 366

DEFAULT_WINDOW_DAYS: int = 31
DEFAULT_HALF_WINDOW_DAYS: int = 15
DEFAULT_SMOOTH_SIGMA_DAYS: float = 7.0

FLOOR_ABS_MIN_F: float = 1.5
FLOOR_PHYSICAL_MIN_F: float = 1.5

# ==============================================================================
# 物理上下限门禁 (Physical Feasibility Gates)
# 规范依据: docs/adr/ADR-0010
# 数学推导: FLOOR_PHYSICAL_MAX_F = max(KBKF winter sigma = 13.74°F) + buffer(1.26°F)
# 历史溯源: 对齐 Phase 1 原型 8.0°C (8.0 * 1.8 = 14.4°F)，修复单位漂移
# 变更约束: 严禁随意微调！任何变更必须满足: Value >= max(empirical_sigmas)
# ==============================================================================
FLOOR_PHYSICAL_MAX_F: float = 15.0
MIN_REQUIRED_SAMPLES_PER_WINDOW: int = 50
MIN_DAILY_OBS_FOR_EXTREMES: int = 5

TARGET_TYPE_MAX: str = "max"
TARGET_TYPE_MIN: str = "min"
VALID_TARGET_TYPES: Tuple[str, str] = (TARGET_TYPE_MAX, TARGET_TYPE_MIN)

# Cumulative leap year days for vectorized month/day to DOY 1..366 mapping
CUMULATIVE_DAYS_LEAP: Tuple[int, ...] = (
    0, 31, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335
)


def resolve_day_of_year(target: Union[str, date, datetime, int]) -> int:
    """Resolve string, date, datetime, or int into reference leap-year DOY (1..366)."""
    if isinstance(target, int):
        if 1 <= target <= DAYS_IN_LEAP_YEAR:
            return target
        raise ValueError(f"Day of year integer must be in 1..{DAYS_IN_LEAP_YEAR}, got {target}")

    if isinstance(target, str):
        dt = pd.to_datetime(target)
        month, day = dt.month, dt.day
    elif isinstance(target, (datetime, date)):
        month, day = target.month, target.day
    else:
        raise TypeError(f"Unsupported target date type: {type(target)}")

    return CUMULATIVE_DAYS_LEAP[month - 1] + day


def validate_station_id(station_id: str) -> str:
    """Enforce Active 11 station universe compliance."""
    st_norm = station_id.strip().upper()
    if st_norm not in ACTIVE_11_STATIONS:
        raise ValueError(
            f"Station '{st_norm}' is not in active 11 stations: {ACTIVE_11_STATIONS}. "
            "Decommissioned or non-compliant stations are strictly prohibited."
        )
    return st_norm


def validate_year_range(start_year: int, end_year: int) -> None:
    """Enforce strict Out-Of-Sample (OOS) year boundary discipline."""
    if start_year > end_year:
        raise ValueError(f"start_year ({start_year}) cannot be greater than end_year ({end_year})")
    if start_year < TRAIN_START_YEAR:
        raise ValueError(f"start_year ({start_year}) cannot be prior to {TRAIN_START_YEAR}")
    if end_year > TRAIN_END_YEAR:
        raise ValueError(
            f"end_year ({end_year}) violates OOS boundary! Strict redline requires "
            f"end_year <= {TRAIN_END_YEAR}. 2019+ data must never be consumed."
        )


@dataclass
class ClimateFloorPoint:
    """Daily climatological baseline and variance floor data point."""

    day_of_year: int
    mu_raw: float
    sigma_raw: float
    mu_clim: float
    sigma_clim: float
    variance_clim: float
    sample_count: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert data point to serializable dictionary."""
        return asdict(self)


@dataclass
class ClimateFloorTable:
    """Lookup table holding 1..366 daily climatological distributions for a station/target."""

    station: str
    target_type: str
    points: List[ClimateFloorPoint] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.points and len(self.points) != DAYS_IN_LEAP_YEAR:
            raise ValueError(
                f"ClimateFloorTable must contain exactly {DAYS_IN_LEAP_YEAR} points, got {len(self.points)}"
            )

    def get_point(self, doy: int) -> ClimateFloorPoint:
        """Retrieve the ClimateFloorPoint for a specific DOY (1..366)."""
        if not (1 <= doy <= DAYS_IN_LEAP_YEAR):
            raise ValueError(f"DOY must be between 1 and {DAYS_IN_LEAP_YEAR}, got {doy}")
        return self.points[doy - 1]

    def to_dataframe(self) -> pd.DataFrame:
        """Convert all points to a structured pandas DataFrame."""
        records = [p.to_dict() for p in self.points]
        df = pd.DataFrame(records)
        df["station"] = self.station
        df["target_type"] = self.target_type
        return df

    @classmethod
    def from_dataframe(cls, df: pd.DataFrame, station: str, target_type: str) -> ClimateFloorTable:
        """Construct a ClimateFloorTable from a pandas DataFrame."""
        points: List[ClimateFloorPoint] = []
        sorted_df = df.sort_values("day_of_year")
        for _, row in sorted_df.iterrows():
            points.append(
                ClimateFloorPoint(
                    day_of_year=int(row["day_of_year"]),
                    mu_raw=float(row["mu_raw"]),
                    sigma_raw=float(row["sigma_raw"]),
                    mu_clim=float(row["mu_clim"]),
                    sigma_clim=float(row["sigma_clim"]),
                    variance_clim=float(row["variance_clim"]),
                    sample_count=int(row["sample_count"]),
                )
            )
        return cls(station=station, target_type=target_type, points=points)


@dataclass
class ClimateFloorConfig:
    """Configurable hyperparameters for climate floor calculation."""

    train_start_year: int = TRAIN_START_YEAR
    train_end_year: int = TRAIN_END_YEAR
    window_days: int = DEFAULT_WINDOW_DAYS
    smooth_sigma_days: float = DEFAULT_SMOOTH_SIGMA_DAYS
    floor_abs_min_f: float = FLOOR_ABS_MIN_F
    floor_physical_min_f: float = FLOOR_PHYSICAL_MIN_F
    floor_physical_max_f: float = FLOOR_PHYSICAL_MAX_F

    def __post_init__(self) -> None:
        validate_year_range(self.train_start_year, self.train_end_year)
        if self.window_days % 2 == 0 or self.window_days < 3:
            raise ValueError(f"window_days must be an odd positive integer >= 3, got {self.window_days}")


def load_station_raw_observations(
    station: str,
    raw_dir: Union[str, Path] = Path("data/raw/iem"),
    start_year: int = TRAIN_START_YEAR,
    end_year: int = TRAIN_END_YEAR,
) -> pd.DataFrame:
    """Load and concatenate raw IEM ASOS parquet files strictly bounded to [start_year, end_year]."""
    validate_station_id(station)
    validate_year_range(start_year, end_year)

    raw_path = Path(raw_dir) / station
    if not raw_path.exists():
        raise FileNotFoundError(f"Observation directory for station {station} not found: {raw_path}")

    dfs: List[pd.DataFrame] = []
    for y in range(start_year, end_year + 1):
        fpath = raw_path / f"{y}.parquet"
        if not fpath.exists():
            logger.warning(f"Missing parquet file for {station} year {y}: {fpath}")
            continue
        sub_df = pd.read_parquet(fpath, columns=["station", "valid_utc", "temp_f"])
        dfs.append(sub_df)

    if not dfs:
        raise ValueError(f"No parquet files found for {station} in range {start_year}-{end_year}")

    concatenated = pd.concat(dfs, ignore_index=True)
    logger.info(f"Loaded {len(concatenated)} observations for {station} ({start_year}-{end_year})")
    return concatenated


def aggregate_daily_extremes(
    obs_df: pd.DataFrame, station: str, min_daily_obs: int = MIN_DAILY_OBS_FOR_EXTREMES
) -> pd.DataFrame:
    """Aggregate raw observations into local calendar-day TMAX and TMIN in Fahrenheit."""
    st_meta = STATION_METADATA.get(station, {})
    tz_name = st_meta.get("timezone", "UTC")
    tz = ZoneInfo(tz_name)

    df = obs_df.dropna(subset=["temp_f"]).copy()
    if df.empty:
        raise ValueError(f"No valid temp_f records found for station {station}")

    # Project valid_utc to station local time
    valid_utc = pd.to_datetime(df["valid_utc"])
    if valid_utc.dt.tz is None:
        valid_utc = valid_utc.dt.tz_localize("UTC")
    df["local_dt"] = valid_utc.dt.tz_convert(tz)
    df["local_date"] = df["local_dt"].dt.strftime("%Y-%m-%d")

    # Aggregate daily extremes keeping ADR-0009 full-report settlement truth
    grouped = df.groupby("local_date")["temp_f"].agg(
        tmax="max",
        tmin="min",
        obs_count="count",
    ).reset_index()

    grouped["station"] = station
    grouped["local_dt"] = pd.to_datetime(grouped["local_date"])

    # Filter out boundary partial days prior to start year and ensure minimum observation count
    grouped = grouped[
        (grouped["local_dt"].dt.year >= TRAIN_START_YEAR)
        & (grouped["obs_count"] >= min_daily_obs)
    ].copy()

    # Reuse resolve_day_of_year to eliminate duplicate mapping logic
    grouped["doy"] = [resolve_day_of_year(d) for d in grouped["local_date"]]

    logger.info(f"Aggregated {len(grouped)} local calendar days for {station}")
    return grouped


def _compute_doy_raw_metrics(
    daily_df: pd.DataFrame,
    target_col: str,
    target_doy: int,
    half_window: int,
    min_samples: int = MIN_REQUIRED_SAMPLES_PER_WINDOW,
) -> Tuple[float, float, int]:
    """Calculate raw sample mean and standard deviation for a target DOY with circular wrap."""
    df_doy = daily_df["doy"].values
    temps = daily_df[target_col].values.astype(np.float64)

    # Circular distance on 366-day cycle
    abs_diff = np.abs(df_doy - target_doy)
    circ_dist = np.minimum(abs_diff, DAYS_IN_LEAP_YEAR - abs_diff)
    in_window = circ_dist <= half_window
    window_samples = temps[in_window]

    n_samples = len(window_samples)
    if n_samples < min_samples:
        raise ValueError(
            f"Insufficient samples ({n_samples}) for DOY {target_doy}. Minimum required is {min_samples}."
        )

    mu_raw = float(np.mean(window_samples))
    sigma_raw = float(np.std(window_samples, ddof=1))
    return mu_raw, sigma_raw, n_samples


def compute_raw_sliding_climatology(
    daily_df: pd.DataFrame,
    target_type: str,
    window_days: int = DEFAULT_WINDOW_DAYS,
    min_samples: int = MIN_REQUIRED_SAMPLES_PER_WINDOW,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute raw sliding window mu, sigma, and sample counts for all 1..366 DOYs."""
    target_col = "tmax" if target_type.lower() == TARGET_TYPE_MAX else "tmin"
    half_window = window_days // 2

    mu_raw = np.zeros(DAYS_IN_LEAP_YEAR, dtype=np.float64)
    sigma_raw = np.zeros(DAYS_IN_LEAP_YEAR, dtype=np.float64)
    sample_counts = np.zeros(DAYS_IN_LEAP_YEAR, dtype=np.int32)

    for doy_idx in range(DAYS_IN_LEAP_YEAR):
        doy = doy_idx + 1
        m, s, cnt = _compute_doy_raw_metrics(daily_df, target_col, doy, half_window, min_samples=min_samples)
        mu_raw[doy_idx] = m
        sigma_raw[doy_idx] = s
        sample_counts[doy_idx] = cnt

    return mu_raw, sigma_raw, sample_counts


def apply_circular_smoothing(
    raw_curve: np.ndarray, sigma_days: float = DEFAULT_SMOOTH_SIGMA_DAYS
) -> np.ndarray:
    """Apply periodic circular Gaussian filter ensuring seamless Dec 31 -> Jan 1 transition."""
    if len(raw_curve) != DAYS_IN_LEAP_YEAR:
        raise ValueError(f"Input curve must have length {DAYS_IN_LEAP_YEAR}, got {len(raw_curve)}")
    # mode='wrap' guarantees exact periodic boundary condition
    smoothed = gaussian_filter1d(raw_curve, sigma=sigma_days, mode="wrap")
    return smoothed


def enforce_variance_floor_and_gates(
    smoothed_sigma: np.ndarray,
    station: str,
    target_type: str,
    floor_abs_min: float = FLOOR_ABS_MIN_F,
    phys_min: float = FLOOR_PHYSICAL_MIN_F,
    phys_max: float = FLOOR_PHYSICAL_MAX_F,
) -> np.ndarray:
    """Enforce absolute variance floor and validate physical feasibility gates."""
    floored_sigma = np.maximum(smoothed_sigma, floor_abs_min)

    min_val = float(np.min(floored_sigma))
    max_val = float(np.max(floored_sigma))

    if min_val < phys_min or max_val > phys_max:
        raise ValueError(
            f"Physical plausibility gate violated for {station} {target_type}: "
            f"sigma range [{min_val:.3f}, {max_val:.3f}] exceeds allowed [{phys_min}, {phys_max}] °F"
        )
    return floored_sigma


class ClimateFloorBuilder:
    """Engine orchestrating raw IEM ingestion, extreme aggregation, and smooth floor construction."""

    def __init__(self, config: Optional[ClimateFloorConfig] = None):
        self.config = config or ClimateFloorConfig()

    def build_station_target_floor(
        self,
        daily_extremes_df: pd.DataFrame,
        station: str,
        target_type: str,
    ) -> ClimateFloorTable:
        """Construct full 366-day smooth ClimateFloorTable for a station and target type."""
        validate_station_id(station)
        if target_type.lower() not in VALID_TARGET_TYPES:
            raise ValueError(f"Invalid target_type '{target_type}', must be one of {VALID_TARGET_TYPES}")

        mu_raw, sigma_raw, counts = compute_raw_sliding_climatology(
            daily_extremes_df, target_type, self.config.window_days
        )
        mu_clim = apply_circular_smoothing(mu_raw, self.config.smooth_sigma_days)
        sigma_smoothed = apply_circular_smoothing(sigma_raw, self.config.smooth_sigma_days)

        sigma_clim = enforce_variance_floor_and_gates(
            sigma_smoothed,
            station=station,
            target_type=target_type,
            floor_abs_min=self.config.floor_abs_min_f,
            phys_min=self.config.floor_physical_min_f,
            phys_max=self.config.floor_physical_max_f,
        )
        variance_clim = np.square(sigma_clim)

        points: List[ClimateFloorPoint] = []
        for i in range(DAYS_IN_LEAP_YEAR):
            s_val = round(float(sigma_clim[i]), 4)
            points.append(
                ClimateFloorPoint(
                    day_of_year=i + 1,
                    mu_raw=round(float(mu_raw[i]), 4),
                    sigma_raw=round(float(sigma_raw[i]), 4),
                    mu_clim=round(float(mu_clim[i]), 4),
                    sigma_clim=s_val,
                    variance_clim=round(s_val ** 2, 4),
                    sample_count=int(counts[i]),
                )
            )

        return ClimateFloorTable(station=station, target_type=target_type, points=points)

    def build_station(
        self,
        station: str,
        raw_dir: Union[str, Path] = Path("data/raw/iem"),
    ) -> Dict[str, ClimateFloorTable]:
        """Load raw observations and build both TMAX and TMIN floor tables for a station."""
        obs_df = load_station_raw_observations(
            station=station,
            raw_dir=raw_dir,
            start_year=self.config.train_start_year,
            end_year=self.config.train_end_year,
        )
        daily_df = aggregate_daily_extremes(obs_df, station=station)

        tables: Dict[str, ClimateFloorTable] = {}
        for t_type in VALID_TARGET_TYPES:
            tables[t_type] = self.build_station_target_floor(daily_df, station, t_type)
        return tables


class ClimateFloorRegistry:
    """In-memory registry and query interface for all active stations' climate floors."""

    def __init__(self) -> None:
        # Key: (station_id, target_type) -> ClimateFloorTable
        self._tables: Dict[Tuple[str, str], ClimateFloorTable] = {}

    @property
    def tables(self) -> Dict[Tuple[str, str], ClimateFloorTable]:
        """Expose a shallow copy of registered tables dictionary."""
        return dict(self._tables)

    def items(self) -> Any:
        """Iterate over ((station, target_type), ClimateFloorTable) pairs."""
        return self._tables.items()

    def register_table(self, table: ClimateFloorTable) -> None:
        """Register a precomputed ClimateFloorTable."""
        key = (table.station.upper(), table.target_type.lower())
        self._tables[key] = table

    def get_climatology(
        self,
        station: str,
        target_type: str,
        target: Union[str, date, datetime, int],
    ) -> Tuple[float, float]:
        """Query (mu_clim, sigma_clim) in Fahrenheit for a target station, type, and date/DOY."""
        key = (station.upper(), target_type.lower())
        if key not in self._tables:
            raise KeyError(f"Climatology table not registered for {key}")

        doy = resolve_day_of_year(target)
        point = self._tables[key].get_point(doy)
        return point.mu_clim, point.sigma_clim

    def get_variance_floor(
        self,
        station: str,
        target_type: str,
        target: Union[str, date, datetime, int],
    ) -> float:
        """Query variance floor sigma_clim^2 in Fahrenheit^2 for static prediction."""
        _, sigma = self.get_climatology(station, target_type, target)
        return sigma ** 2

    def to_json_dict(self) -> Dict[str, Any]:
        """Export all registered tables into a compact nested dictionary."""
        out: Dict[str, Any] = {
            "version": "2.0",
            "source": "IEM_ASOS_METAR_V2",
            "train_period": f"{TRAIN_START_YEAR}-{TRAIN_END_YEAR}",
            "stations": {},
        }
        for (st, t_type), table in self._tables.items():
            if st not in out["stations"]:
                out["stations"][st] = {}
            out["stations"][st][t_type] = [p.to_dict() for p in table.points]
        return out

    def save_to_json(self, json_path: Union[str, Path]) -> None:
        """Persist registry configuration to a JSON file."""
        p = Path(json_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_json_dict(), f, indent=2)
        logger.info(f"Saved climate floor JSON configuration to {p}")

    @classmethod
    def load_from_json(cls, json_path: Union[str, Path]) -> ClimateFloorRegistry:
        """Instantiate registry from a precomputed JSON configuration file."""
        p = Path(json_path)
        if not p.exists():
            raise FileNotFoundError(f"JSON config not found at: {p}")

        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)

        reg = cls()
        stations_data = data.get("stations", {})
        for st, types_dict in stations_data.items():
            for t_type, points_list in types_dict.items():
                points = [
                    ClimateFloorPoint(
                        day_of_year=p_dict["day_of_year"],
                        mu_raw=p_dict["mu_raw"],
                        sigma_raw=p_dict["sigma_raw"],
                        mu_clim=p_dict["mu_clim"],
                        sigma_clim=p_dict["sigma_clim"],
                        variance_clim=p_dict["variance_clim"],
                        sample_count=p_dict["sample_count"],
                    )
                    for p_dict in points_list
                ]
                reg.register_table(ClimateFloorTable(station=st, target_type=t_type, points=points))
        return reg

    def save_to_parquet_dir(self, output_dir: Union[str, Path]) -> List[Path]:
        """Save individual station-target tables as parquet files in output directory."""
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        saved_paths: List[Path] = []

        # Group by station to produce unified station parquet
        station_groups: Dict[str, List[pd.DataFrame]] = {}
        for (st, _), table in self._tables.items():
            station_groups.setdefault(st, []).append(table.to_dataframe())

        for st, dfs in station_groups.items():
            combined_df = pd.concat(dfs, ignore_index=True)
            target_fpath = out_path / f"{st}_climate_floor.parquet"
            combined_df.to_parquet(target_fpath, compression="snappy", index=False)
            saved_paths.append(target_fpath)
            logger.info(f"Saved {st} climate floor to {target_fpath}")

        return saved_paths

    @classmethod
    def load_from_parquet_dir(cls, parquet_dir: Union[str, Path]) -> ClimateFloorRegistry:
        """Instantiate registry from directory of station parquet files."""
        p_dir = Path(parquet_dir)
        if not p_dir.exists():
            raise FileNotFoundError(f"Directory not found: {p_dir}")

        reg = cls()
        for pq_path in sorted(p_dir.glob("*_climate_floor.parquet")):
            df = pd.read_parquet(pq_path)
            for (st, t_type), group in df.groupby(["station", "target_type"]):
                table = ClimateFloorTable.from_dataframe(group, station=str(st), target_type=str(t_type))
                reg.register_table(table)
        return reg
