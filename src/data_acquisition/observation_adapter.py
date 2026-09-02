"""
Observation Adapter Core Interface and Data Structures.
Defines unified contracts for weather observation sources (NWS WRH, Wunderground, IEM, etc.)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import zoneinfo


@dataclass
class ObservationRecord:
    """
    Standardized single observation record from weather stations.
    """
    timestamp: datetime
    temp_c: Optional[float] = None
    temp_f: Optional[float] = None
    dewpoint_c: Optional[float] = None
    dewpoint_f: Optional[float] = None
    humidity_pct: Optional[float] = None
    wind_speed_mps: Optional[float] = None
    wind_direction_deg: Optional[float] = None
    pressure_hpa: Optional[float] = None
    raw_metar: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseObservationAdapter(ABC):
    """
    Abstract Base Class defining the strategy contract for weather observation data sources.
    """

    @abstractmethod
    def fetch_raw_series(
        self, station: str, start_date: datetime, end_date: datetime
    ) -> List[ObservationRecord]:
        """
        Fetch time-series observation records for a station within [start_date, end_date].
        """
        pass

    @abstractmethod
    def extract_calendar_day_max(
        self, records: List[ObservationRecord], timezone_str: str = "Asia/Shanghai"
    ) -> Optional[float]:
        """
        Extract the maximum Celsius temperature for records belonging to a local calendar day.
        """
        pass

    @abstractmethod
    def get_source_precision_metadata(self) -> Dict[str, Any]:
        """
        Return metadata describing the native precision and units of this data source.
        """
        pass


class WundergroundAdapter(BaseObservationAdapter):
    """
    Wunderground Observation Adapter.
    Reserved placeholder for Phase 2 dual-track extension.
    """

    def fetch_raw_series(
        self, station: str, start_date: datetime, end_date: datetime
    ) -> List[ObservationRecord]:
        raise NotImplementedError(
            "WundergroundAdapter is reserved for Phase 2 dual-track extension."
        )

    def extract_calendar_day_max(
        self, records: List[ObservationRecord], timezone_str: str = "Asia/Shanghai"
    ) -> Optional[float]:
        raise NotImplementedError(
            "WundergroundAdapter is reserved for Phase 2 dual-track extension."
        )

    def get_source_precision_metadata(self) -> Dict[str, Any]:
        return {
            "source_name": "Wunderground",
            "primary_unit": "Celsius",
            "supports_dual_probe": False,
        }
