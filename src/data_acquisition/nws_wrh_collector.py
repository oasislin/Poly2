"""
NWS WRH / Synoptic MesoWest Timeseries Collector & Adapter.
Implements concurrent dual-probe fetching (Metric / English), exponential backoff retry, and raw JSON persistence.
"""

import concurrent.futures
import json
import logging
import os
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


class NwsWrhAdapter(BaseObservationAdapter):
    """
    Adapter for NWS WRH Timeseries viewer powered by Synoptic MesoWest API.
    """

    BASE_URL = "https://api.synopticdata.com/v2/stations/timeseries"
    DEFAULT_TOKEN = os.getenv("SYNOPTIC_TOKEN", "7c76618b66c74aee913bdbae4b448bdd")

    def __init__(
        self,
        token: Optional[str] = None,
        storage_dir: Optional[str] = None,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        timeout_seconds: int = 30,
        tracker: Optional[Any] = None,
    ):
        self.token = token if token else self.DEFAULT_TOKEN
        self.storage_dir = Path(storage_dir) if storage_dir else Path("data/raw/nws_wrh")
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Origin": "https://www.weather.gov",
                "Referer": "https://www.weather.gov/",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            }
        )
        self.tracker = tracker
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def get_source_precision_metadata(self) -> Dict[str, Any]:
        return {
            "source_name": "NWS_WRH_Synoptic",
            "primary_unit": "Fahrenheit",
            "reported_unit": "Celsius",
            "supports_dual_probe": True,
            "api_endpoint": self.BASE_URL,
        }

    def fetch_raw_json(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Public interface for fetching raw Synoptic API JSON payload."""
        req_params = dict(params)
        if "token" not in req_params:
            req_params["token"] = self.token
        return self._execute_request_with_retry(req_params)

    def _execute_request_with_retry(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute HTTP GET with exponential backoff retry."""
        last_error = None
        t0 = time.perf_counter()
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(
                    self.BASE_URL, params=params, timeout=self.timeout_seconds
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("SUMMARY", {}).get("RESPONSE_MESSAGE") == "OK":
                        if self.tracker:
                            top_k = set(data.keys())
                            st_k = set(data["STATION"][0].keys()) if data.get("STATION") else set()
                            obs_k = set(data["STATION"][0].get("OBSERVATIONS", {}).keys()) if data.get("STATION") else set()
                            self.tracker.record_attempt(time.perf_counter() - t0, success=True, observed_keys=(top_k | st_k | obs_k))
                        return data
                    msg = data.get("SUMMARY", {}).get("RESPONSE_MESSAGE", "API Error")
                    raise ValueError(f"Synoptic API returned error: {msg}")
                resp.raise_for_status()
            except Exception as e:
                last_error = e
                logger.warning(
                    f"NWS WRH fetch attempt {attempt}/{self.max_retries} failed: {e}"
                )
                if attempt < self.max_retries:
                    time.sleep(self.backoff_base * (2 ** (attempt - 1)))

        err = RuntimeError(
            f"Failed to fetch NWS WRH data after {self.max_retries} retries. Error: {last_error}"
        )
        if self.tracker:
            self.tracker.record_attempt(time.perf_counter() - t0, success=False, error=err)
        raise err from last_error

    def _persist_raw_payload(
        self,
        station: str,
        tag: str,
        unit_type: str,
        payload: Dict[str, Any],
    ) -> Path:
        """Persist raw response payload with request metadata and status code."""
        now_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = f"{station}_{tag}_{unit_type}_{now_ts}.json"
        target_path = self.storage_dir / filename
        meta_payload = {
            "fetched_at": now_ts,
            "station": station,
            "unit_type": unit_type,
            "http_status_code": 200,
            "response": payload,
        }
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(meta_payload, f, indent=2, ensure_ascii=False)
        return target_path

    @staticmethod
    def _build_english_index(e_obs: Dict[str, Any]) -> Dict[str, Dict[str, Optional[float]]]:
        """Index English temperatures and dewpoints by timestamp string."""
        e_times = e_obs.get("date_time", [])
        e_temps = e_obs.get("air_temp_set_1", [])
        e_dew = e_obs.get("dew_point_temperature_set_1", e_obs.get("dew_point_temperature_set_1d", []))

        english_by_time: Dict[str, Dict[str, Optional[float]]] = {}
        for idx, dt_str in enumerate(e_times):
            english_by_time[dt_str] = {
                "temp_f": e_temps[idx] if idx < len(e_temps) else None,
                "dewpoint_f": e_dew[idx] if idx < len(e_dew) else None,
            }
        return english_by_time

    @staticmethod
    def _create_observation_record(
        idx: int,
        dt_str: str,
        m_obs: Dict[str, Any],
        e_match: Dict[str, Optional[float]],
    ) -> ObservationRecord:
        """Create a single ObservationRecord from parallel arrays at index."""
        dt = datetime.fromisoformat(dt_str)
        m_temps = m_obs.get("air_temp_set_1", [])
        m_dew = m_obs.get("dew_point_temperature_set_1d", m_obs.get("dew_point_temperature_set_1", []))
        m_metar = m_obs.get("metar_set_1", [])
        m_humidity = m_obs.get("relative_humidity_set_1", [])
        m_wind_speed = m_obs.get("wind_speed_set_1", [])
        m_wind_dir = m_obs.get("wind_direction_set_1", [])
        m_press = m_obs.get("pressure_set_1d", m_obs.get("pressure_set_1", []))

        temp_c = m_temps[idx] if idx < len(m_temps) else None
        dew_c = m_dew[idx] if idx < len(m_dew) else None
        metar_str = m_metar[idx] if idx < len(m_metar) else None
        hum = m_humidity[idx] if idx < len(m_humidity) else None
        ws = m_wind_speed[idx] if idx < len(m_wind_speed) else None
        wd = m_wind_dir[idx] if idx < len(m_wind_dir) else None
        pr = m_press[idx] if idx < len(m_press) else None

        return ObservationRecord(
            timestamp=dt,
            temp_c=float(temp_c) if temp_c is not None else None,
            temp_f=float(e_match["temp_f"]) if e_match.get("temp_f") is not None else None,
            dewpoint_c=float(dew_c) if dew_c is not None else None,
            dewpoint_f=float(e_match["dewpoint_f"]) if e_match.get("dewpoint_f") is not None else None,
            humidity_pct=float(hum) if hum is not None else None,
            wind_speed_mps=float(ws) if ws is not None else None,
            wind_direction_deg=float(wd) if wd is not None else None,
            pressure_hpa=float(pr) if pr is not None else None,
            raw_metar=metar_str,
            metadata={"raw_time_str": dt_str},
        )

    def _parse_dual_probe_payloads(
        self,
        metric_data: Dict[str, Any],
        english_data: Dict[str, Any],
    ) -> List[ObservationRecord]:
        """Align observations from Metric and English payloads by timestamp."""
        try:
            m_obs = metric_data["STATION"][0].get("OBSERVATIONS", {})
            e_obs = english_data["STATION"][0].get("OBSERVATIONS", {})
        except (KeyError, IndexError) as err:
            logger.error(f"Invalid Synoptic response structure: {err}")
            return []

        m_times = m_obs.get("date_time", [])
        english_by_time = self._build_english_index(e_obs)

        records: List[ObservationRecord] = []
        for idx, dt_str in enumerate(m_times):
            e_match = english_by_time.get(dt_str, {})
            records.append(
                self._create_observation_record(idx, dt_str, m_obs, e_match)
            )
        return records

    def _fetch_probe_pair(
        self, station: str, tag: str, base_params: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Fetch metric and english probe data concurrently with ThreadPoolExecutor."""
        m_params = {**base_params, "STID": station, "token": self.token}
        e_params = {
            **base_params,
            "STID": station,
            "token": self.token,
            "units": "temp|F,speed|mph,english",
        }

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_metric = executor.submit(self._execute_request_with_retry, m_params)
            future_english = executor.submit(self._execute_request_with_retry, e_params)
            metric_payload = future_metric.result()
            english_payload = future_english.result()

        self._persist_raw_payload(station, tag, "metric", metric_payload)
        self._persist_raw_payload(station, tag, "english", english_payload)
        return metric_payload, english_payload

    def fetch_raw_series(
        self, station: str, start_date: datetime, end_date: datetime
    ) -> List[ObservationRecord]:
        """Fetch historical time-series observations using start/end range."""
        start_str = start_date.strftime("%Y%m%d%H%M")
        end_str = end_date.strftime("%Y%m%d%H%M")
        tag = f"{start_str}_{end_str}"
        base_params = {
            "showemptystations": 1,
            "start": start_str,
            "end": end_str,
            "complete": 1,
            "obtimezone": "local",
        }
        metric_payload, english_payload = self._fetch_probe_pair(
            station, tag, base_params
        )
        return self._parse_dual_probe_payloads(metric_payload, english_payload)

    def fetch_recent(
        self, station: str, recent_minutes: int = 1440
    ) -> List[ObservationRecord]:
        """Fetch rolling recent observations within recent_minutes."""
        tag = f"recent_{recent_minutes}m"
        base_params = {
            "showemptystations": 1,
            "recent": recent_minutes,
            "complete": 1,
            "obtimezone": "local",
        }
        metric_payload, english_payload = self._fetch_probe_pair(
            station, tag, base_params
        )
        return self._parse_dual_probe_payloads(metric_payload, english_payload)

    def extract_calendar_day_max(
        self, records: List[ObservationRecord], timezone_str: str = "Asia/Shanghai"
    ) -> Optional[float]:
        """Extract max Celsius temperature among all valid records."""
        valid_temps = [r.temp_c for r in records if r.temp_c is not None]
        if not valid_temps:
            return None
        return max(valid_temps)
