"""S3-17 Real Online M1/M2 P5 Forecast Producer (`GEFS -> EMOS -> P11 -> P5 JSONL`).

Wires together existing M1/M2 production building blocks without touching frozen zones:
- `GEFSFetcher.download_realtime(model="gefs", product="atmos.25")` ensemble mean/spread
- `ModelRegistry` frozen EMOS prior (`data/models/manifest.json`)
- `LiveAwcMetarAdapter` + `SettlementMetarStreamEngine` (`StationDayState` / `P11`)
- `ForecastDistributionEngine.build_snapshot` (`P5 v1.1` / `p17.v3` JSONL with explicit `forecast_origin`)

Data discipline:
- Every serialized record carries explicit `forecast_origin` (default `"REALTIME_LIVE_PULL"`).
- Never writes to `data/audit_logs/` by default; callers must pass an explicit `output_path`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
from typing import Any, Dict, List, Literal, Mapping, Optional, Protocol, Sequence, Tuple
import numpy as np

from src.audit.p10_reader import CorruptLineRecord, read_verified_jsonl_file
from src.audit.p13_reader import load_p13_session_readonly
from src.contract.parameter_contract import AUTHORIZED_LEAD_HOURS
from src.data_acquisition.gefs_fetcher import GEFSFetcher
from src.data_acquisition.settlement_metar_stream import (
    FreshnessPolicy,
    LiveAwcMetarAdapter,
    MissingDispatchPolicy,
    RawMetarSource,
    SettlementMetarStreamEngine,
    StationDayState,
    compute_local_day_window_utc,
    resolve_station_timezone,
)
from src.data_processing.constants import STATION_METADATA
from src.modeling.registry import ModelRegistry
from src.prediction.discrete_bin_engine import (
    BinProbV11,
    IntegerBinSpec,
    build_integer_bin_ladder,
    validate_contiguous_bin_ladder,
)
from src.prediction.forecast_distribution_engine import (
    CalibrationJsonEtaProvider,
    ConstantEtaProvider,
    EtaProvider,
    ExecutionMode,
    ForecastDistributionEngine,
    ForecastDistributionSnapshotV11,
    P5InvariantReport,
    PriorAffineFamilyModel,
    TargetType,
    verify_p17_json_line,
)
from src.utils.causal_utils import compute_record_sha256, ensure_utc_datetime, parse_utc_timestamp

SUPPORTED_LIVE_STATIONS: Tuple[str, ...] = ("KORD", "KMIA", "KLGA", "KATL", "KDAL", "KSEA")
DEFAULT_GEFS_MEMBERS: Tuple[int, ...] = (0, 1, 2, 3, 4)
ForecastOrigin = Literal["REALTIME_LIVE_PULL", "BACKFILL_GEFS_HISTORICAL"]
DEFAULT_FORECAST_ORIGIN: ForecastOrigin = "REALTIME_LIVE_PULL"


class RealtimeGefsSource(Protocol):
    """Minimal protocol satisfied by `GEFSFetcher.download_realtime` and test doubles."""

    def download_realtime(
        self,
        region_bounds: Mapping[str, Tuple[float, float]],
        forecast_time: datetime,
        members: Sequence[int],
        fxx_hours: Optional[Sequence[int]] = None,
    ) -> Any:
        ...


@dataclass(frozen=True)
class LiveGefsEnsembleSummary:
    """Extracted single-station GEFS ensemble statistics in Fahrenheit."""

    station_id: str
    cycle_utc: datetime
    lead_hours: int
    ens_mean_f: float
    ens_std_f: float
    ens_var_f: float
    member_count: int


@dataclass(frozen=True)
class LiveP5ProducerConfig:
    """Configuration for `LiveP5Producer` (never defaults output to `data/audit_logs/`)."""

    stations: Tuple[str, ...] = SUPPORTED_LIVE_STATIONS
    model_dir: Path = Path("data/models")
    climate_floor_path: Path = Path("configs/climate_floor_v2.json")
    eta_calibration_path: Optional[Path] = Path("evidence/p8_inspection_a_eta_s_calibration_20261113.json")
    gefs_members: Tuple[int, ...] = DEFAULT_GEFS_MEMBERS
    default_lead_hours: int = 24
    bin_half_width_f: int = 10
    bin_width_f: int = 2
    region_pad_deg: float = 0.5
    forecast_origin: ForecastOrigin = DEFAULT_FORECAST_ORIGIN


@dataclass(frozen=True)
class LiveP5ProductionRecord:
    """In-memory bundle produced by `LiveP5Producer` for one `(station_id, target_date)`."""

    snapshot: ForecastDistributionSnapshotV11
    invariant_report: P5InvariantReport
    p11_state: StationDayState
    gefs_summary: LiveGefsEnsembleSummary
    forecast_origin: ForecastOrigin


class FallbackEtaProvider:
    """Uses calibrated `eta_s(t)` curves where available, else uniform fallback `eta_s=1.0`."""

    def __init__(
        self,
        primary: Optional[EtaProvider] = None,
        fallback_eta: float = 1.0,
    ) -> None:
        self._primary = primary
        self._fallback = ConstantEtaProvider(eta_s=fallback_eta, provenance="UNIFORM_PRIOR_FALLBACK")
        self.provenance = primary.provenance if primary is not None else self._fallback.provenance

    def get_eta_s(self, *, station_id: str, season: str, t_local_hour: float) -> float:
        if self._primary is not None:
            try:
                return self._primary.get_eta_s(
                    station_id=station_id, season=season, t_local_hour=t_local_hour
                )
            except KeyError:
                pass
        return self._fallback.get_eta_s(station_id=station_id, season=season, t_local_hour=t_local_hour)


def kelvin_to_fahrenheit(val: float) -> float:
    """Convert Kelvin temperature to Fahrenheit when `val > 150.0`, else keep Fahrenheit."""
    num = float(val)
    if not math.isfinite(num):
        raise ValueError(f"Temperature value must be finite, got {val!r}")
    return (num - 273.15) * 9.0 / 5.0 + 32.0 if num > 150.0 else num


def build_station_region_bounds(station_id: str, pad_deg: float = 0.5) -> Dict[str, Tuple[float, float]]:
    """Build small lat/lon crop around station coordinates from `STATION_METADATA`."""
    code = station_id.strip().upper()
    if code not in STATION_METADATA:
        raise KeyError(f"Unknown station_id {code!r} not in STATION_METADATA")
    lat = float(STATION_METADATA[code]["latitude"])
    lon = float(STATION_METADATA[code]["longitude"])
    pad = float(pad_deg)
    return {"lat": (lat - pad, lat + pad), "lon": (lon - pad, lon + pad)}


def resolve_latest_gefs_cycle_utc(issue_ts_utc: datetime, *, lag_hours: int = 6) -> datetime:
    """Return latest published 6-hourly GEFS synoptic cycle (`00/06/12/18Z`) before `issue - lag`."""
    ts = ensure_utc_datetime(issue_ts_utc, field_name="issue_ts_utc")
    ready = ts - timedelta(hours=int(lag_hours))
    cycle_hour = (ready.hour // 6) * 6
    return datetime(ready.year, ready.month, ready.day, cycle_hour, 0, 0, tzinfo=timezone.utc)


def resolve_gefs_lead_hours(
    cycle_utc: datetime, settle_close_utc: datetime, *, default_lead_hours: int = 24
) -> int:
    """Map `(settle_close - cycle)` onto nearest authorized GEFS lead hour (`AUTHORIZED_LEAD_HOURS`)."""
    cyc = ensure_utc_datetime(cycle_utc, field_name="cycle_utc")
    close = ensure_utc_datetime(settle_close_utc, field_name="settle_close_utc")
    raw_hours = (close - cyc).total_seconds() / 3600.0
    if raw_hours <= 0:
        return int(default_lead_hours)
    return int(min(AUTHORIZED_LEAD_HOURS, key=lambda h: abs(float(h) - raw_hours)))


def extract_gefs_station_ensemble(
    ds: Any,
    *,
    station_id: str,
    cycle_utc: datetime,
    lead_hours: int,
    target_type: TargetType = "TMAX",
) -> LiveGefsEnsembleSummary:
    """Extract nearest-grid-point ensemble mean/std/var in °F from a GEFS xarray Dataset."""
    code = station_id.strip().upper()
    var_name = "tmax" if target_type == "TMAX" else "tmin"
    if var_name not in ds.data_vars:
        raise KeyError(f"GEFS dataset missing variable {var_name!r}; available={list(ds.data_vars)}")
    lat = float(STATION_METADATA[code]["latitude"])
    lon = float(STATION_METADATA[code]["longitude"])
    point = ds[var_name].sel(latitude=lat, longitude=lon, method="nearest")
    member_vals: List[float] = []
    if "member" in point.dims:
        for m_idx in range(int(point.sizes["member"])):
            sub = point.isel(member=m_idx)
            arr = np.asarray(sub.values, dtype=float).ravel()
            finite = arr[np.isfinite(arr)]
            if finite.size:
                agg = float(np.max(finite) if target_type == "TMAX" else np.min(finite))
                member_vals.append(kelvin_to_fahrenheit(agg))
    else:
        arr = np.asarray(point.values, dtype=float).ravel()
        finite = arr[np.isfinite(arr)]
        if finite.size:
            agg = float(np.max(finite) if target_type == "TMAX" else np.min(finite))
            member_vals.append(kelvin_to_fahrenheit(agg))
    if not member_vals:
        raise ValueError(f"No finite GEFS {var_name} values extracted for {code}")
    vals = np.asarray(member_vals, dtype=float)
    mean_f = float(np.mean(vals))
    var_f = float(np.var(vals, ddof=1)) if vals.size > 1 else 0.0
    return LiveGefsEnsembleSummary(
        station_id=code,
        cycle_utc=ensure_utc_datetime(cycle_utc, field_name="cycle_utc"),
        lead_hours=int(lead_hours),
        ens_mean_f=mean_f,
        ens_std_f=math.sqrt(max(var_f, 0.0)),
        ens_var_f=max(var_f, 0.0),
        member_count=int(vals.size),
    )


def lookup_climate_variance(
    climate_floor_data: Mapping[str, Any],
    *,
    station_id: str,
    target_date: date,
    target_type: TargetType = "TMAX",
) -> float:
    """Lookup daily climatological variance (°F^2) from `configs/climate_floor_v2.json`."""
    code = station_id.strip().upper()
    var_key = "max" if target_type == "TMAX" else "min"
    doy = min(int(target_date.timetuple().tm_yday), 365)
    station_block = climate_floor_data.get("stations", {}).get(code, {})
    rows = station_block.get(var_key, [])
    for row in rows:
        if int(row.get("day_of_year", -1)) == doy:
            return float(row["variance_clim"])
    if rows:
        return float(rows[0]["variance_clim"])
    raise KeyError(f"No climate_floor_v2 entry for station={code!r}, var={var_key!r}")


def build_default_bin_ladder(
    center_f: float, *, half_width_f: int = 10, bin_width_f: int = 2
) -> Tuple[IntegerBinSpec, ...]:
    """Construct contiguous Polymarket integer ladder centered around `center_f`."""
    center_int = int(math.floor(float(center_f) + 0.5))
    first_start = center_int - int(half_width_f)
    if first_start % bin_width_f != 0:
        first_start -= 1
    num_interior = max(1, (2 * int(half_width_f)) // int(bin_width_f))
    return build_integer_bin_ladder(
        first_interior_start_f=first_start,
        num_interior_bins=num_interior,
        bin_width_f=int(bin_width_f),
    )


def serialize_p5_jsonl_record(
    record: LiveP5ProductionRecord,
    *,
    session_id: str,
    execution_mode: ExecutionMode = "PAPER",
    config_hash: str = "s317-live-p5",
    capture_replay_mode: Literal["NONE", "REPLAY_P13"] = "NONE",
) -> str:
    """Serialize `LiveP5ProductionRecord` into canonical JSONL with explicit `forecast_origin`."""
    payload = record.snapshot.to_p17_dict_without_hash(
        session_id=session_id,
        execution_mode=execution_mode,
        config_hash=config_hash,
        capture_replay_mode=capture_replay_mode,
    )
    payload["forecast_origin"] = record.forecast_origin
    payload["gefs_cycle_utc"] = record.gefs_summary.cycle_utc.isoformat()
    payload["gefs_ens_mean_f"] = record.gefs_summary.ens_mean_f
    payload["gefs_ens_std_f"] = record.gefs_summary.ens_std_f
    payload["gefs_member_count"] = record.gefs_summary.member_count
    payload["record_sha256"] = compute_record_sha256(payload)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def write_p5_jsonl(
    records: Sequence[LiveP5ProductionRecord],
    output_path: Path,
    *,
    session_id: str,
    execution_mode: ExecutionMode = "PAPER",
    config_hash: str = "s317-live-p5",
    capture_replay_mode: Literal["NONE", "REPLAY_P13"] = "NONE",
) -> Path:
    """Write `P5` JSONL records to an explicit caller-provided path."""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        serialize_p5_jsonl_record(
            rec,
            session_id=session_id,
            execution_mode=execution_mode,
            config_hash=config_hash,
            capture_replay_mode=capture_replay_mode,
        )
        for rec in records
    ]
    target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return target


def _load_eta_provider(path: Optional[Path]) -> FallbackEtaProvider:
    if path is not None and Path(path).exists():
        primary = CalibrationJsonEtaProvider.from_json(Path(path))
        return FallbackEtaProvider(primary=primary)
    return FallbackEtaProvider(primary=None)


class LiveP5Producer:
    """End-to-end M1/M2 online producer: GEFS -> EMOS prior -> LiveAwcMetar P11 -> P5 snapshot."""

    def __init__(
        self,
        config: Optional[LiveP5ProducerConfig] = None,
        *,
        gefs_fetcher: Optional[RealtimeGefsSource] = None,
        metar_adapter: Optional[RawMetarSource] = None,
        model_registry: Optional[ModelRegistry] = None,
        distribution_engine: Optional[ForecastDistributionEngine] = None,
        climate_floor_data: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self._config = config or LiveP5ProducerConfig()
        self._gefs = gefs_fetcher or GEFSFetcher(verbose=False)
        self._metar_source = metar_adapter or LiveAwcMetarAdapter()
        self._registry = model_registry or ModelRegistry(base_dir=self._config.model_dir)
        self._climate_floor = (
            dict(climate_floor_data)
            if climate_floor_data is not None
            else json.loads(Path(self._config.climate_floor_path).read_text(encoding="utf-8"))
        )
        self._manifest = self._load_manifest_metadata()
        freshness = FreshnessPolicy(
            physical_age_limit_sec=5400.0,
            provenance="S3-17_LIVE_P5_PRODUCER",
        )
        self._metar_stream = SettlementMetarStreamEngine(
            source=self._metar_source,
            freshness_policy=freshness,
            missing_dispatch_policy=MissingDispatchPolicy(
                mode="REJECT",
                provenance="S3-17_LIVE_P5_PRODUCER",
            ),
        )
        self._engine = distribution_engine or ForecastDistributionEngine(
            freshness_policy=freshness,
            eta_provider=_load_eta_provider(self._config.eta_calibration_path),
        )

    def _load_manifest_metadata(self) -> Dict[str, Any]:
        manifest_path = Path(self._config.model_dir) / "manifest.json"
        if not manifest_path.exists():
            return {"spec_sha256": "unverified-local", "models": {}}
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def _resolve_prior(
        self,
        *,
        station_id: str,
        target_date: date,
        target_type: TargetType,
        lead_hours: int,
        gefs_summary: LiveGefsEnsembleSummary,
    ) -> Tuple[PriorAffineFamilyModel, str]:
        var_name = "max" if target_type == "TMAX" else "min"
        sigma_clim_sq = lookup_climate_variance(
            self._climate_floor, station_id=station_id, target_date=target_date, target_type=target_type
        )
        pred = self._registry.predict(
            station_id=station_id,
            target_date=target_date,
            target_type=var_name,
            lead_hours=lead_hours,
            ensemble_mean=gefs_summary.ens_mean_f,
            ensemble_variance=gefs_summary.ens_var_f,
            sigma_clim_squared=sigma_clim_sq,
        )
        season = self._registry.partitioner.get_season(target_date)
        key = self._registry.format_model_filename(station_id, season, var_name, lead_hours)
        meta = self._manifest.get("models", {}).get(key, {})
        c_train = float(meta.get("c_train", 1.0))
        mu0 = float(np.asarray(pred.mu).ravel()[0])
        sigma0 = max(float(np.asarray(pred.sigma).ravel()[0]) * c_train, 0.9)
        raw_family = str(meta.get("distribution", "gaussian")).lower()
        shape_params = dict(meta.get("shape_params") or {})
        family = raw_family if (raw_family == "gaussian" or shape_params) else "gaussian"
        model_hash = str(meta.get("sha256") or self._manifest.get("spec_sha256") or "emos-frozen")
        return PriorAffineFamilyModel(family=family, mu0=mu0, sigma0=sigma0, shape_params=shape_params), model_hash

    def _pull_gefs_summary(
        self,
        *,
        station_id: str,
        cycle_utc: datetime,
        lead_hours: int,
        target_type: TargetType,
    ) -> LiveGefsEnsembleSummary:
        bounds = build_station_region_bounds(station_id, pad_deg=self._config.region_pad_deg)
        ds = self._gefs.download_realtime(
            region_bounds=bounds,
            forecast_time=cycle_utc.replace(tzinfo=None),
            members=list(self._config.gefs_members),
            fxx_hours=[lead_hours],
        )
        return extract_gefs_station_ensemble(
            ds, station_id=station_id, cycle_utc=cycle_utc, lead_hours=lead_hours, target_type=target_type
        )

    def produce_station_snapshot(
        self,
        *,
        station_id: str,
        target_date: date,
        issue_ts_utc: datetime,
        cycle_utc: Optional[datetime] = None,
        lead_hours: Optional[int] = None,
        target_type: TargetType = "TMAX",
        bins: Optional[Sequence[IntegerBinSpec]] = None,
        session_id: str = "s317-live-p5",
        execution_mode: ExecutionMode = "PAPER",
        config_hash: str = "s317-live-p5",
    ) -> LiveP5ProductionRecord:
        """Pull live GEFS + AWC METAR and emit a verified `P5 v1.1` snapshot for one station."""
        code = station_id.strip().upper()
        issue_ts = ensure_utc_datetime(issue_ts_utc, field_name="issue_ts_utc")
        _, settle_close_utc = compute_local_day_window_utc(target_date, resolve_station_timezone(code))
        cyc = cycle_utc or resolve_latest_gefs_cycle_utc(issue_ts)
        lead = int(lead_hours) if lead_hours is not None else resolve_gefs_lead_hours(
            cyc, settle_close_utc, default_lead_hours=self._config.default_lead_hours
        )
        gefs_summary = self._pull_gefs_summary(
            station_id=code, cycle_utc=cyc, lead_hours=lead, target_type=target_type
        )
        prior, model_hash = self._resolve_prior(
            station_id=code, target_date=target_date, target_type=target_type,
            lead_hours=lead, gefs_summary=gefs_summary,
        )
        eval_out = self._metar_stream.evaluate_as_of(
            station_id=code, target_date=target_date, as_of_ts_utc=issue_ts,
            session_id=session_id, execution_mode=execution_mode, model_hash=model_hash,
            config_hash=config_hash, gfs_init_utc=cyc.isoformat(), gfs_available=True,
            gfs_completeness_ratio=gefs_summary.member_count / max(len(self._config.gefs_members), 1),
        )
        ladder = tuple(bins) if bins is not None else build_default_bin_ladder(
            prior.mu0, half_width_f=self._config.bin_half_width_f, bin_width_f=self._config.bin_width_f
        )
        snap, report = self._engine.build_snapshot(
            station_id=code, target_date=target_date, target_type=target_type,
            issue_ts_utc=issue_ts, settle_close_utc=settle_close_utc, gefs_lead_hours=lead,
            model_hash=model_hash, prior=prior, bins=ladder, p11_state=eval_out.state,
            validate_invariants=True,
        )
        return LiveP5ProductionRecord(
            snapshot=snap, invariant_report=report, p11_state=eval_out.state,
            gefs_summary=gefs_summary, forecast_origin=self._config.forecast_origin,
        )

    def produce_batch(
        self,
        *,
        target_date: date,
        issue_ts_utc: datetime,
        stations: Optional[Sequence[str]] = None,
        cycle_utc: Optional[datetime] = None,
        lead_hours: Optional[int] = None,
        target_type: TargetType = "TMAX",
        session_id: str = "s317-live-p5",
        execution_mode: ExecutionMode = "PAPER",
        config_hash: str = "s317-live-p5",
    ) -> List[LiveP5ProductionRecord]:
        """Produce verified `P5 v1.1` snapshots across all configured stations."""
        selected = tuple(stations) if stations is not None else self._config.stations
        return [
            self.produce_station_snapshot(
                station_id=st,
                target_date=target_date,
                issue_ts_utc=issue_ts_utc,
                cycle_utc=cycle_utc,
                lead_hours=lead_hours,
                target_type=target_type,
                session_id=session_id,
                execution_mode=execution_mode,
                config_hash=config_hash,
            )
            for st in selected
        ]


_RE_BIN_BELOW = re.compile(r"^(?:<=)?\s*(-?\d+)\s*°?F(?:\s+or\s+below)?$", re.IGNORECASE)
_RE_BIN_ABOVE = re.compile(r"^(?:>=)?\s*(-?\d+)\s*°?F(?:\s+or\s+(?:higher|above))?$", re.IGNORECASE)
_RE_BIN_RANGE = re.compile(r"^(-?\d+)\s*-\s*(-?\d+)\s*°?F$", re.IGNORECASE)


def parse_polymarket_bin_label(bin_label: str) -> IntegerBinSpec:
    """Parse Polymarket integer temperature label (e.g. `'33°F or below'`, `'34-35°F'`) into `IntegerBinSpec`."""
    raw = bin_label.strip()
    if raw.startswith("<=") or raw.lower().endswith("or below"):
        m_low = _RE_BIN_BELOW.match(raw)
        if m_low:
            hi = int(m_low.group(1))
            return IntegerBinSpec(f"le_{hi}F", raw, None, hi)
    if raw.startswith(">=") or raw.lower().endswith(("or higher", "or above")):
        m_hi = _RE_BIN_ABOVE.match(raw)
        if m_hi:
            lo = int(m_hi.group(1))
            return IntegerBinSpec(f"ge_{lo}F", raw, lo, None)
    m_rng = _RE_BIN_RANGE.match(raw)
    if m_rng:
        lo, hi = int(m_rng.group(1)), int(m_rng.group(2))
        bid = f"{lo}F" if lo == hi else f"{lo}-{hi}F"
        return IntegerBinSpec(bid, raw, lo, hi)
    m_single = re.match(r"^(-?\d+)\s*°?F$", raw, re.IGNORECASE)
    if m_single:
        val = int(m_single.group(1))
        return IntegerBinSpec(f"{val}F", raw, val, val)
    raise ValueError(f"Unrecognized Polymarket temperature bin_label: {bin_label!r}")


def _resolve_ladder_session_dir(
    recordings_root: Path, session_dir: Optional[Path], active_only: bool
) -> Optional[Path]:
    if session_dir is not None:
        return Path(session_dir)
    if not active_only:
        return None
    ptr = Path(recordings_root) / "latest_session.json"
    if not ptr.exists():
        return None
    sid = json.loads(ptr.read_text(encoding="utf-8")).get("session_id")
    if not sid:
        return None
    matches = list((Path(recordings_root) / "PASSIVE_RECORD").rglob(str(sid)))
    return matches[0] if matches else None


def discover_p13_market_ladders(
    recordings_root: Path = Path("data/market_recordings"),
    *,
    session_dir: Optional[Path] = None,
    active_only: bool = True,
) -> Dict[Tuple[str, str], Tuple[IntegerBinSpec, ...]]:
    """Discover and validate contiguous `IntegerBinSpec` ladders per `(station_id, target_date)`."""
    target_dir = _resolve_ladder_session_dir(recordings_root, session_dir, active_only)
    if target_dir is None or not target_dir.exists():
        return {}
    loaded = load_p13_session_readonly(target_dir)
    grouped: Dict[Tuple[str, str], set[str]] = {}
    for env in loaded.envelopes:
        grouped.setdefault((env.station_id, env.target_date), set()).add(env.bin_label)
    out: Dict[Tuple[str, str], Tuple[IntegerBinSpec, ...]] = {}
    for key, labels in sorted(grouped.items()):
        specs = sorted(
            (parse_polymarket_bin_label(lbl) for lbl in labels),
            key=lambda b: (0, b.upper_int_f or 0) if b.lower_int_f is None else ((2, b.lower_int_f) if b.upper_int_f is None else (1, b.lower_int_f)),
        )
        validate_contiguous_bin_ladder(specs)
        out[key] = tuple(specs)
    return out


def deserialize_p5_jsonl_record(raw_line: str) -> Tuple[ForecastDistributionSnapshotV11, str]:
    """Verify `record_sha256` and deserialize one `p17.v3` JSONL line back to `P5 v1.1` + `forecast_origin`."""
    if not verify_p17_json_line(raw_line):
        raise ValueError("P5/P17 JSONL record failed record_sha256 integrity verification")
    row = json.loads(raw_line)
    bins = tuple(
        BinProbV11(
            bin_id=str(b["bin_id"]), label=str(b["label"]),
            lower_int_f=b["lower_int_f"], upper_int_f=b["upper_int_f"], p_model=float(b["p_model"]),
        )
        for b in row["bin_probs"]
    )
    snap = ForecastDistributionSnapshotV11(
        schema_version=str(row["schema_version"]), forecast_id=str(row["forecast_id"]),
        issue_ts_utc=parse_utc_timestamp(str(row["issue_ts_utc"]), field_name="p5.issue_ts_utc"),
        station_id=str(row["station_id"]), target_date=date.fromisoformat(str(row["target_date"])),
        target_type=row["target_type"], gefs_lead_hours=int(row["gefs_lead_hours"]),
        tau_hours=float(row["tau_hours"]),
        settle_close_utc=parse_utc_timestamp(str(row["settle_close_utc"]), field_name="p5.settle_close_utc"),
        model_hash=str(row["model_hash"]), prior_mu0=float(row["prior_mu0"]),
        prior_sigma0=float(row["prior_sigma0"]), family=row["family"],
        m_now_f=row.get("m_now_f"), m_now_int_f=row.get("m_now_int_f"),
        oracle_compliant=bool(row["oracle_compliant"]), upstream_obs_fresh=bool(row["upstream_obs_fresh"]),
        is_bridge_active=bool(row["is_bridge_active"]),
        p_stay_phys=row.get("p_stay_phys"), p_bin_stay=row.get("p_bin_stay"),
        bin_probs=bins, sigma_delta_sample=float(row["sigma_delta_sample"]),
        obs_temp_f=row.get("obs_temp_f"),
        obs_ts_utc=parse_utc_timestamp(str(row["obs_ts_utc"]), field_name="p5.obs_ts_utc") if row.get("obs_ts_utc") else None,
        obs_source=row.get("obs_source"),
    )
    return snap, str(row.get("forecast_origin") or "UNKNOWN")


def load_p5_jsonl_snapshots(
    p5_path: Path,
    *,
    forecast_origin_filter: Optional[str] = DEFAULT_FORECAST_ORIGIN,
) -> Tuple[ForecastDistributionSnapshotV11, ...]:
    """Load verified `P5` snapshots from a `.jsonl` file or directory, deduplicated by `forecast_id`."""
    target = Path(p5_path)
    files = [target] if target.is_file() else (sorted(target.glob("*.jsonl")) if target.is_dir() else [])
    by_id: Dict[str, ForecastDistributionSnapshotV11] = {}
    for fp in files:
        res = read_verified_jsonl_file(fp, verify_sha256=True)
        for idx, rec in enumerate(res.records, start=1):
            raw = json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            snap, origin = deserialize_p5_jsonl_record(raw)
            if forecast_origin_filter and origin != forecast_origin_filter:
                continue
            by_id[snap.forecast_id] = snap
        if res.corrupt_lines:
            raise ValueError(f"Corrupt P5 records in {fp}: {len(res.corrupt_lines)}")
    return tuple(sorted(by_id.values(), key=lambda s: (s.issue_ts_utc, s.station_id, s.target_date)))
