"""
Real Production EMOS Pipeline Integration (Phase 2 Wave 3 / W3-B Redo).
Governed by P7-W3-REPRIMAND-001 & P7-W3-TASK2-REDO-001.

Implements:
1. Station coordinates & metadata resolution from constants.
2. 5-member GEFS live forecast extraction (c00, gep01..gep04) via Herbie / AWS S3 with local cache.
3. Climatological variance floor lookup from data/processed/climate_floor/.
4. GaussianEMOS link function parameter evaluation from data/models/.
5. Strict PROB_SOURCE stamping ("EMOS_PIPELINE" vs "CLIMATOLOGY_PLACEHOLDER").
6. Complete diagnostic traceability.
"""

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import pickle
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from src.data_processing.constants import STATION_METADATA

logger = logging.getLogger(__name__)

# Statutory Provenance Constants
PROB_SOURCE_EMOS = "EMOS_PIPELINE"
PROB_SOURCE_PLACEHOLDER = "CLIMATOLOGY_PLACEHOLDER"

GEFS_MEMBERS = ("c00", "p01", "p02", "p03", "p04")


def get_meteorological_season(dt: Union[date, datetime]) -> str:
    """Return meteorological season for a given date."""
    m = dt.month
    if m in (3, 4, 5):
        return "Spring"
    elif m in (6, 7, 8):
        return "Summer"
    elif m in (9, 10, 11):
        return "Autumn"
    else:
        return "Winter"


@dataclass(frozen=True)
class EMOSForecastResult:
    """Production EMOS pipeline output container with full provenance."""
    station_id: str
    target_date: str
    season: str
    lead_hours: int
    mu: float
    sigma: float
    prob_source: str
    ensemble_mean: float
    ensemble_variance: float
    climatological_variance: float
    emos_params: Dict[str, float]
    member_temperatures_f: Dict[str, float]
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RealEMOSPipeline:
    """
    Production-grade EMOS probability pipeline.
    Combines live NOAA GEFS ensemble forecasts with offline-trained EMOS link functions
    and climatological variance floors.
    """

    def __init__(
        self,
        models_dir: Optional[Path] = None,
        climate_floor_dir: Optional[Path] = None,
        cache_dir: Optional[Path] = None,
    ):
        self.models_dir = Path(models_dir or "data/models")
        self.climate_floor_dir = Path(climate_floor_dir or "data/processed/climate_floor")
        self.cache_dir = Path(cache_dir or "data/cache/gefs")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_station_coords(self, station_id: str) -> Tuple[float, float]:
        """Resolve station latitude and longitude (in 0..360 range for GRIB2)."""
        meta = STATION_METADATA.get(station_id)
        if not meta:
            # Fallbacks for primary airports
            primary = {
                "KORD": (41.97, -87.90),
                "KMIA": (25.79, -80.29),
                "KLGA": (40.78, -73.87),
                "KATL": (33.64, -84.43),
                "KDFW": (32.90, -97.04),
                "KLAX": (33.94, -118.41),
                "KSEA": (47.45, -122.31),
                "KSFO": (37.62, -122.37),
                "KIAH": (29.98, -95.34),
                "KBKF": (39.70, -104.75),
                "KAUS": (30.19, -97.67),
            }
            if station_id in primary:
                lat, lon = primary[station_id]
            else:
                raise ValueError(f"Unknown station_id: {station_id}")
        else:
            lat = float(meta["latitude"])
            lon = float(meta["longitude"])

        lon_360 = (lon % 360.0)
        return lat, lon_360

    def load_climatological_variance(
        self,
        station_id: str,
        target_date: Union[date, datetime],
        target_type: str = "max",
    ) -> float:
        """Load climatological variance floor for station and day of year."""
        parquet_path = self.climate_floor_dir / f"{station_id}_climate_floor.parquet"
        if not parquet_path.exists():
            raise FileNotFoundError(f"Climate floor file missing: {parquet_path}")

        df = pd.read_parquet(parquet_path)
        doy = target_date.timetuple().tm_yday
        subset = df[(df["day_of_year"] == doy) & (df["target_type"].str.lower() == target_type.lower())]
        if subset.empty:
            # Fallback to mean of variance_clim
            logger.warning(f"No exact day_of_year {doy} match in {parquet_path}, using annual average")
            return float(df["variance_clim"].mean())
        return float(subset["variance_clim"].iloc[0])

    def load_emos_model(
        self,
        station_id: str,
        season: str,
        target_type: str = "Max",
        lead_hours: int = 24,
    ) -> Tuple[Any, Dict[str, float]]:
        """Load trained GaussianEMOS model object and parameters from pickle."""
        model_file = self.models_dir / f"{station_id}_{season}_{target_type}_lead{lead_hours}h.pkl"
        if not model_file.exists():
            raise FileNotFoundError(f"EMOS model file missing: {model_file}")

        with open(model_file, "rb") as f:
            data = pickle.load(f)

        model = data["model"]
        params = data.get("metadata", {}).get("params", {
            "a": model.a,
            "b": model.b,
            "c": model.c,
            "d": model.d,
        })
        return model, params

    def fetch_gefs_ensemble_members(
        self,
        station_id: str,
        target_date: Union[date, datetime],
        forecast_cycle: Optional[datetime] = None,
        lead_hours: int = 24,
        allow_cache: bool = True,
    ) -> Dict[str, float]:
        """
        Fetch GEFS 5-member ensemble temperatures (°F) for target station.
        Queries NOAA AWS S3 via Herbie or reads from local disk cache.
        """
        date_str = target_date.strftime("%Y-%m-%d") if isinstance(target_date, (date, datetime)) else str(target_date)
        cache_file = self.cache_dir / f"gefs_{station_id}_{date_str}_lead{lead_hours}h.json"

        if allow_cache and cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                logger.info(f"Loaded GEFS ensemble for {station_id} from cache: {cache_file}")
                return cached_data["member_temperatures_f"]
            except Exception as e:
                logger.warning(f"Failed to read cache {cache_file}: {e}, refetching")

        # Resolve forecast cycle (e.g., target_date - 1 day at 00:00 UTC for 24h lead)
        if forecast_cycle is None:
            if isinstance(target_date, str):
                target_dt = datetime.strptime(target_date, "%Y-%m-%d")
            elif isinstance(target_date, datetime):
                target_dt = target_date
            else:
                target_dt = datetime.combine(target_date, datetime.min.time())
            cycle_dt = target_dt - timedelta(hours=lead_hours)
            cycle_str = cycle_dt.strftime("%Y-%m-%d 00:00")
        else:
            cycle_str = forecast_cycle.strftime("%Y-%m-%d %H:%M")

        lat, lon_360 = self.get_station_coords(station_id)

        try:
            from herbie import Herbie
        except ImportError as e:
            raise ImportError("herbie-data is required to fetch real GEFS forecasts") from e

        member_temps: Dict[str, float] = {}

        for member in GEFS_MEMBERS:
            try:
                H = Herbie(
                    cycle_str,
                    model="gefs",
                    product="atmos.25",
                    member=member,
                    fxx=lead_hours,
                )
                ds = H.xarray(":TMAX:2 m above ground:")
                # Variable name is usually 'tmax'
                var_name = [v for v in ds.data_vars if "tmax" in v.lower()][0]
                pt = ds[var_name].sel(latitude=lat, longitude=lon_360, method="nearest")
                val_k = float(pt.values)
                val_f = (val_k - 273.15) * 9.0 / 5.0 + 32.0
                member_temps[member] = round(val_f, 4)
            except Exception as exc:
                logger.error(f"Failed to fetch GEFS member {member} for {station_id}: {exc}")
                raise RuntimeError(
                    f"Real GEFS fetch failed for {station_id} member {member} cycle {cycle_str}: {exc}"
                ) from exc

        # Save to cache
        cache_payload = {
            "station_id": station_id,
            "target_date": date_str,
            "forecast_cycle": cycle_str,
            "lead_hours": lead_hours,
            "member_temperatures_f": member_temps,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache_payload, f, indent=2)

        return member_temps

    def predict(
        self,
        station_id: str,
        target_date: Union[date, datetime, str],
        lead_hours: int = 24,
        injected_members: Optional[Dict[str, float]] = None,
    ) -> EMOSForecastResult:
        """
        Execute full end-to-end EMOS probability pipeline.
        Calculates μ and σ from live ensemble NWP, climate floor, and trained EMOS parameters.
        PROB_SOURCE is stamped strictly as 'EMOS_PIPELINE'.
        """
        if isinstance(target_date, str):
            dt_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
            date_str = target_date
        elif isinstance(target_date, datetime):
            dt_obj = target_date.date()
            date_str = dt_obj.strftime("%Y-%m-%d")
        else:
            dt_obj = target_date
            date_str = dt_obj.strftime("%Y-%m-%d")

        season = get_meteorological_season(dt_obj)

        # 1. Load EMOS model and params
        model, params = self.load_emos_model(
            station_id=station_id,
            season=season,
            target_type="Max",
            lead_hours=lead_hours,
        )

        # 2. Load Climatological Variance Floor
        clim_var = self.load_climatological_variance(
            station_id=station_id,
            target_date=dt_obj,
            target_type="max",
        )

        # 3. Fetch GEFS Ensemble Members
        if injected_members is not None:
            member_temps = injected_members
        else:
            member_temps = self.fetch_gefs_ensemble_members(
                station_id=station_id,
                target_date=dt_obj,
                lead_hours=lead_hours,
            )

        # 4. Compute Ensemble Statistics
        temps = list(member_temps.values())
        ens_mean = float(np.mean(temps))
        ens_var = float(np.var(temps, ddof=1)) if len(temps) > 1 else 0.0

        # 5. Execute EMOS Link Functions
        mu, sigma = model.compute_params(
            ensemble_mean=ens_mean,
            ensemble_variance=ens_var,
            sigma_clim_squared=clim_var,
        )

        return EMOSForecastResult(
            station_id=station_id,
            target_date=date_str,
            season=season,
            lead_hours=lead_hours,
            mu=float(mu),
            sigma=float(sigma),
            prob_source=PROB_SOURCE_EMOS,
            ensemble_mean=ens_mean,
            ensemble_variance=ens_var,
            climatological_variance=clim_var,
            emos_params=params,
            member_temperatures_f=member_temps,
            diagnostics={
                "n_members": len(temps),
                "a": params.get("a", model.a),
                "b": params.get("b", model.b),
                "c": params.get("c", model.c),
                "d": params.get("d", model.d),
            },
        )
