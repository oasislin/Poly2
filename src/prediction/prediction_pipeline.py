#!/usr/bin/env python3
"""
PredictionPipeline: End-to-end orchestration of static, dynamic, physical constraints, and discrete bin probabilities (Ticket 3.5-01 / Issue #30).

Implements (Phase 1C / v5.9.2):
    1. Full 4-Stage Execution Stack:
       Input Ensemble Features
       -> Stage 1: StaticPredictor (Base Gaussian EMOS & Parameter Routing)
       -> Stage 2: DynamicCorrector (Real-time Observation Truncation)
       -> Stage 3: ConstraintEnforcer (Historical Rate Limit Reachability Bounds)
       -> Stage 4: Statutory 2°F adsorbed grid for ACTIVE_10_STATIONS (DiscreteBinEngine),
                   legacy BinConverter bins otherwise (custom_bins overrides both)
    2. SQLite Database Persistence:
       - Upserts complete prediction records (distribution parameters, dynamic observations, discrete bin probabilities JSON)
       - Provides historical queries and replay capabilities.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd

from src.data_processing.constants import ACTIVE_10_STATIONS
from src.data_processing.database import DEFAULT_DB_PATH
from src.modeling.climatology import ClimatologyCalculator
from src.modeling.gaussian_emos import GaussianEMOS
from src.modeling.registry import ModelRegistry
from src.prediction.bin_converter import BinConverter, MarketBin, celsius_to_fahrenheit
from src.prediction.constraint_enforcer import ConstrainedDistribution, ConstraintEnforcer
from src.prediction.discrete_bin_engine import DiscreteBin, DiscreteBinEngine
from src.prediction.dynamic_corrector import (
    DynamicCorrector,
    MuRHook,
    TruncatedDistribution,
)
from src.prediction.monotonic_confluence import StationDayState
from src.prediction.static_predictor import StaticPredictionResult, StaticPredictor

logger = logging.getLogger(__name__)

PREDICTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,
    target_date TEXT NOT NULL,
    target_type TEXT NOT NULL,
    lead_time_hours REAL NOT NULL,
    issue_time TEXT NOT NULL,
    predicted_mu REAL NOT NULL,
    predicted_sigma REAL NOT NULL,
    current_temp REAL,
    observation_time TEXT,
    bin_probabilities TEXT NOT NULL,
    is_interpolated INTEGER DEFAULT 0,
    is_short_lead_decay INTEGER DEFAULT 0,
    is_truncated INTEGER DEFAULT 0,
    is_physically_constrained INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(station_id, target_date, target_type, lead_time_hours, issue_time)
);

CREATE INDEX IF NOT EXISTS idx_mkt_pred_query ON market_predictions(station_id, target_date, target_type);
"""


@dataclass
class PredictionRecord:
    """Comprehensive container holding all intermediate layers and final discrete market probabilities."""

    station_id: str
    target_date: str
    target_type: str
    lead_time_hours: float
    issue_time: str
    predicted_mu: float
    predicted_sigma: float
    current_temp: Optional[float]
    observation_time: Optional[str]
    static_distribution: StaticPredictionResult
    dynamic_distribution: TruncatedDistribution
    constrained_distribution: ConstrainedDistribution
    market_bins: List[Union[MarketBin, DiscreteBin]]
    is_interpolated: bool = False
    is_short_lead_decay: bool = False
    is_truncated: bool = False
    is_physically_constrained: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def get_bin_probabilities_dict(self) -> Dict[str, float]:
        """Map bin labels to their normalized probabilities."""
        return {b.label: float(b.probability) for b in self.market_bins}

    def get_winning_bin(
        self, observed_temp: float, unit: str = "C"
    ) -> Tuple[int, Union[MarketBin, DiscreteBin]]:
        """Determine which market bin settles as YES (1) for ground truth observed_temp."""
        if self.market_bins and isinstance(self.market_bins[0], DiscreteBin):
            obs_f = float(observed_temp) if unit.upper().startswith("F") else float(
                celsius_to_fahrenheit(float(observed_temp))
            )
            for idx, b in enumerate(self.market_bins):
                if np.isposinf(b.upper_bound_f):
                    hit = obs_f >= b.lower_bound_f
                elif np.isneginf(b.lower_bound_f):
                    hit = obs_f < b.upper_bound_f
                else:
                    hit = b.lower_bound_f <= obs_f < b.upper_bound_f
                if hit:
                    return idx, b
            raise ValueError(
                f"No statutory discrete bin contains observed temperature {observed_temp}°{unit}"
            )
        return BinConverter.determine_winning_bin(self.market_bins, observed_temp=observed_temp, unit=unit)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize complete prediction record to dictionary."""
        return {
            "station_id": self.station_id,
            "target_date": self.target_date,
            "target_type": self.target_type,
            "lead_time_hours": self.lead_time_hours,
            "issue_time": self.issue_time,
            "predicted_mu": float(self.predicted_mu),
            "predicted_sigma": float(self.predicted_sigma),
            "current_temp": self.current_temp,
            "observation_time": self.observation_time,
            "bin_probabilities": self.get_bin_probabilities_dict(),
            "is_interpolated": int(self.is_interpolated),
            "is_short_lead_decay": int(self.is_short_lead_decay),
            "is_truncated": int(self.is_truncated),
            "is_physically_constrained": int(self.is_physically_constrained),
            "created_at": self.created_at,
        }


class PredictionPipeline:
    """End-to-end probabilistic prediction pipeline and SQLite persistence orchestrator."""

    def __init__(
        self,
        model_registry: Optional[Union[ModelRegistry, Any]] = None,
        climatology_calculator: Optional[Union[ClimatologyCalculator, Any]] = None,
        constraint_enforcer: Optional[ConstraintEnforcer] = None,
        bin_converter: Optional[BinConverter] = None,
        dynamic_corrector: Optional[DynamicCorrector] = None,
        mu_r_hook: Optional[MuRHook] = None,
        db_path: Union[str, Path] = DEFAULT_DB_PATH,
    ):
        self.static_predictor = StaticPredictor(
            model_registry=model_registry,
            climatology_calculator=climatology_calculator,
        )
        self.dynamic_corrector = (
            dynamic_corrector
            if dynamic_corrector is not None
            else DynamicCorrector(mu_r_hook=mu_r_hook)
        )
        self.constraint_enforcer = constraint_enforcer or ConstraintEnforcer()
        self.bin_converter = bin_converter or BinConverter()
        self.db_path = Path(db_path)
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Ensure market_predictions SQLite table exists."""
        with self._get_connection() as conn:
            conn.executescript(PREDICTIONS_SCHEMA)
            conn.commit()

    def _execute_prediction_stack(
        self,
        station: str,
        date_str: str,
        t_type: str,
        lead: float,
        ens_mean: float,
        ens_var: float,
        sigma_clim_squared: Optional[float],
        current_temp: Optional[float],
        observation_time: Optional[Union[str, datetime]],
        delta_hours: Optional[float],
        custom_bins: Optional[List[MarketBin]],
        extreme_m: Optional[float] = None,
        instant_x_t: Optional[float] = None,
        t_local: Optional[Union[float, str, datetime]] = None,
        station_state: Optional[StationDayState] = None,
    ) -> Tuple[
        StaticPredictionResult,
        TruncatedDistribution,
        ConstrainedDistribution,
        List[Union[MarketBin, DiscreteBin]],
    ]:
        """Run through the 4 prediction stages."""
        static_res = self.static_predictor.predict_single(
            station_id=station,
            target_date=date_str,
            target_type=t_type,
            lead_time_hours=lead,
            ensemble_mean=ens_mean,
            ensemble_variance=ens_var,
            sigma_clim_squared=sigma_clim_squared,
        )

        effective_t_local = t_local if t_local is not None else observation_time
        if station_state is not None:
            truncated_dist = self.dynamic_corrector.correct_with_station_state(
                base_distribution=static_res,
                station_state=station_state,
                target_type=t_type,
                t_local=effective_t_local,
                station_id=station,
                season=static_res.season,
            )
        else:
            m_val = extreme_m if extreme_m is not None else current_temp
            x_val = instant_x_t if instant_x_t is not None else current_temp
            truncated_dist = self.dynamic_corrector.correct(
                base_distribution=static_res,
                target_type=t_type,
                extreme_m=m_val,
                instant_x_t=x_val,
                t_local=effective_t_local,
                station_id=station,
                season=static_res.season,
            )

        constrained_dist = self.constraint_enforcer.enforce(
            distribution=truncated_dist,
            station_id=station,
            season=static_res.season,
            target_type=t_type,
            current_temp=truncated_dist.extreme_m,
            observation_time=observation_time,
            delta_hours=delta_hours,
        )

        if custom_bins is not None and len(custom_bins) > 0:
            evaluated_bins: List[Union[MarketBin, DiscreteBin]] = self.bin_converter.calculate_bin_probabilities(
                distribution=constrained_dist,
                bins=custom_bins,
                normalize=True,
            )
        elif station in ACTIVE_10_STATIONS:
            # ACTIVE_10 models and settlement bins are both natively in °F;
            # map directly onto the P4-AUDIT v1.1 2°F adsorbed grid without °C<->°F conversion.
            evaluated_bins = self._generate_statutory_2deg_bins(
                distribution=constrained_dist,
                mu_fahrenheit=static_res.mu,
                station=station,
            )
        else:
            legacy_bins = self.bin_converter.generate_bins(
                station_id=station,
                center_temp=static_res.mu,
                spread=static_res.sigma,
            )
            evaluated_bins = self.bin_converter.calculate_bin_probabilities(
                distribution=constrained_dist,
                bins=legacy_bins,
                normalize=True,
            )

        return static_res, truncated_dist, constrained_dist, evaluated_bins

    def _generate_statutory_2deg_bins(
        self,
        distribution: ConstrainedDistribution,
        mu_fahrenheit: float,
        station: str,
    ) -> List[DiscreteBin]:
        """Build the P4-AUDIT v1.1 statutory 2°F adsorbed grid and integrate the constrained CDF onto it.

        ACTIVE_10 models and statutory 2°F bins share the native °F unit; the constrained CDF
        is evaluated directly on the °F edges without double °C<->°F conversion.
        """
        bins = DiscreteBinEngine.generate_2deg_adsorbed_bins(
            mu=float(mu_fahrenheit),
            station_id=station,
        )
        probabilities = DiscreteBinEngine.calculate_2deg_bin_probabilities(
            bins,
            cdf_fn=lambda bound_f: float(distribution.cdf(float(bound_f))),
        )
        for discrete_bin, probability in zip(bins, probabilities):
            discrete_bin.probability = float(probability)
        return bins

    def predict_single(
        self,
        station_id: str,
        target_date: Union[str, datetime, pd.Timestamp],
        target_type: str,
        lead_time_hours: Union[int, float],
        ensemble_mean: float,
        ensemble_variance: float,
        sigma_clim_squared: Optional[float] = None,
        current_temp: Optional[float] = None,
        observation_time: Optional[Union[str, datetime]] = None,
        delta_hours: Optional[float] = None,
        custom_bins: Optional[List[MarketBin]] = None,
        issue_time: Optional[str] = None,
        save_to_db: bool = True,
        extreme_m: Optional[float] = None,
        instant_x_t: Optional[float] = None,
        t_local: Optional[Union[float, str, datetime]] = None,
        station_state: Optional[StationDayState] = None,
    ) -> PredictionRecord:
        """Run the full 4-stage prediction pipeline for a single target."""
        station = station_id.upper()
        date_str = pd.to_datetime(target_date).strftime("%Y-%m-%d")
        t_type = target_type.lower()
        lead = float(lead_time_hours)
        now_iso = issue_time or datetime.now(timezone.utc).isoformat()
        time_src = t_local if t_local is not None else observation_time
        obs_time_str = time_src.strftime("%H:%M") if isinstance(time_src, datetime) else (str(time_src) if time_src is not None else None)

        static_res, truncated_dist, constrained_dist, evaluated_bins = self._execute_prediction_stack(
            station=station,
            date_str=date_str,
            t_type=t_type,
            lead=lead,
            ens_mean=ensemble_mean,
            ens_var=ensemble_variance,
            sigma_clim_squared=sigma_clim_squared,
            current_temp=current_temp,
            observation_time=observation_time,
            delta_hours=delta_hours,
            custom_bins=custom_bins,
            extreme_m=extreme_m,
            instant_x_t=instant_x_t,
            t_local=t_local,
            station_state=station_state,
        )

        record = PredictionRecord(
            station_id=station,
            target_date=date_str,
            target_type=t_type,
            lead_time_hours=lead,
            issue_time=now_iso,
            predicted_mu=static_res.mu,
            predicted_sigma=static_res.sigma,
            current_temp=truncated_dist.extreme_m,
            observation_time=obs_time_str,
            static_distribution=static_res,
            dynamic_distribution=truncated_dist,
            constrained_distribution=constrained_dist,
            market_bins=evaluated_bins,
            is_interpolated=static_res.is_interpolated,
            is_short_lead_decay=static_res.is_short_lead_decay,
            is_truncated=truncated_dist.is_truncated,
            is_physically_constrained=constrained_dist.is_constrained,
            created_at=now_iso,
        )

        if save_to_db:
            self.save_record(record)

        return record

    def save_record(self, record: PredictionRecord) -> None:
        """Persist a PredictionRecord to SQLite database."""
        sql = """
        INSERT INTO market_predictions (
            station_id, target_date, target_type, lead_time_hours, issue_time,
            predicted_mu, predicted_sigma, current_temp, observation_time,
            bin_probabilities, is_interpolated, is_short_lead_decay,
            is_truncated, is_physically_constrained, created_at
        ) VALUES (
            :station_id, :target_date, :target_type, :lead_time_hours, :issue_time,
            :predicted_mu, :predicted_sigma, :current_temp, :observation_time,
            :bin_probabilities, :is_interpolated, :is_short_lead_decay,
            :is_truncated, :is_physically_constrained, :created_at
        ) ON CONFLICT(station_id, target_date, target_type, lead_time_hours, issue_time) DO UPDATE SET
            predicted_mu=excluded.predicted_mu,
            predicted_sigma=excluded.predicted_sigma,
            current_temp=excluded.current_temp,
            observation_time=excluded.observation_time,
            bin_probabilities=excluded.bin_probabilities,
            is_interpolated=excluded.is_interpolated,
            is_short_lead_decay=excluded.is_short_lead_decay,
            is_truncated=excluded.is_truncated,
            is_physically_constrained=excluded.is_physically_constrained,
            created_at=excluded.created_at;
        """
        payload = {
            "station_id": record.station_id,
            "target_date": record.target_date,
            "target_type": record.target_type,
            "lead_time_hours": record.lead_time_hours,
            "issue_time": record.issue_time,
            "predicted_mu": float(record.predicted_mu),
            "predicted_sigma": float(record.predicted_sigma),
            "current_temp": float(record.current_temp) if record.current_temp is not None else None,
            "observation_time": record.observation_time,
            "bin_probabilities": json.dumps(record.get_bin_probabilities_dict()),
            "is_interpolated": int(record.is_interpolated),
            "is_short_lead_decay": int(record.is_short_lead_decay),
            "is_truncated": int(record.is_truncated),
            "is_physically_constrained": int(record.is_physically_constrained),
            "created_at": record.created_at,
        }

        with self._get_connection() as conn:
            conn.execute(sql, payload)
            conn.commit()

    def predict_batch(
        self,
        df: pd.DataFrame,
        save_to_db: bool = True,
    ) -> pd.DataFrame:
        """Run batch predictions over a DataFrame of ensemble features."""
        records = []
        for _, row in df.iterrows():
            rec = self.predict_single(
                station_id=str(row["station_id"]),
                target_date=row["target_date"],
                target_type=str(row["target_type"]),
                lead_time_hours=float(row.get("lead_time_hours", 30)),
                ensemble_mean=float(row["ensemble_mean"]),
                ensemble_variance=float(row["ensemble_variance"]),
                sigma_clim_squared=float(row["sigma_clim_squared"]) if "sigma_clim_squared" in row and pd.notna(row["sigma_clim_squared"]) else None,
                current_temp=float(row["current_temp"]) if "current_temp" in row and pd.notna(row["current_temp"]) else None,
                observation_time=row.get("observation_time"),
                extreme_m=float(row["extreme_m"]) if "extreme_m" in row and pd.notna(row["extreme_m"]) else None,
                instant_x_t=float(row["instant_x_t"]) if "instant_x_t" in row and pd.notna(row["instant_x_t"]) else None,
                t_local=row.get("t_local"),
                save_to_db=save_to_db,
            )
            rec_dict = rec.to_dict()
            rec_dict["bin_probabilities"] = json.dumps(rec_dict["bin_probabilities"])
            records.append(rec_dict)

        return pd.DataFrame(records)

    def get_history(
        self,
        station_id: str,
        target_date: Optional[str] = None,
        target_type: Optional[str] = None,
    ) -> pd.DataFrame:
        """Query persisted prediction records from database."""
        query = "SELECT * FROM market_predictions WHERE station_id = ?"
        params: List[Any] = [station_id.upper()]

        if target_date is not None:
            query += " AND target_date = ?"
            params.append(target_date)
        if target_type is not None:
            query += " AND target_type = ?"
            params.append(target_type.lower())

        query += " ORDER BY target_date ASC, lead_time_hours ASC"

        with self._get_connection() as conn:
            return pd.read_sql_query(query, conn, params=params)
