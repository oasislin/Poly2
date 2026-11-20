"""M1 (S3-01) Settlement-Isomorphic METAR Stream, Causal Replay Adapters, and P11/P12 Pipeline.

Design & protocol anchors:
- `P8-T8-ALGO4-DESIGN v0.3 §1 & §5 (#1, #2)`
- `P8-KERNEL-CONSENSUS v1.1 §七` (G-15 settlement isomorphism, max/floor monotonicity, T8 M1 inputs)
- `ADR-0009 §4` (SPECI excluded from settlement & bridge M_now; preserved in archival stream)
- `ADR-0012 §5` (AWC routine METAR T-group -> TT/TD fallback, ZoneInfo DST day, floor(x + 0.5))
- `P8-T2-M7-LOGGING v1.0 §1.4 & §2.5` (P12 CoverageLedgerLog schema & canonical record_sha256)

Strict architectural boundaries:
- Weather Underground (WU) is strictly barred from intraday M1 bridge feeding (`m_now`);
  WU fallback belongs exclusively to post-close M9 settlement after next-day 11:59 PM ET.
- Never modifies any file inside the F-2 locked `src/pricing/` directory.
- All temperature conversions and half-degree rounding execute in an explicit `Decimal`
  `localcontext` with operand digit-bound validation via `src.utils.decimal_guard`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
from pathlib import Path
import re
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Literal,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
)
import uuid
from zoneinfo import ZoneInfo

import requests

from src.data_processing.constants import STATION_TIMEZONES
from src.utils.decimal_guard import (
    EXACT_DECIMAL_CONTEXT_PREC,
    DecimalInput,
    exact_decimal_context,
    to_guarded_decimal,
)

ReportType = Literal["METAR", "SPECI"]
OracleSourceTier = Literal["AWC_METAR_TGROUP", "AWC_METAR_BODY", "MISSING"]
ExecutionMode = Literal["PAPER", "LIVE"]
MissingDispatchMode = Literal["REJECT", "CONSERVATIVE_LAG_BOUND"]

_STATE_ID_NAMESPACE = uuid.UUID("a3f7b1d4-6e29-4c91-9b8e-202611200001")
_US_EASTERN_TZ = ZoneInfo("America/New_York")

# Precompiled WMO/ASOS METAR patterns:
# - T-group in RMK: 8-digit TsnTTTsnTdTdTd (also supports missing dewpoint TsnTTT////)
# - Main body dry bulb/dewpoint before RMK: TT/TD or TT/// (e.g. 28/25, M05/M10, 00/M02, 21///)
_RMK_SPLIT_RE = re.compile(r"\bRMK\b", re.IGNORECASE)
_TGROUP_RE = re.compile(r"(?:^|\s)T([01])(\d{3})(?:[01]\d{3}|////)(?=\s|=|$)")
_BODY_TEMP_RE = re.compile(r"(?:^|\s)(M?\d{2})/(?:M?\d{2}|//)(?=\s|=|$)")
_FORBIDDEN_WU_CHANNEL_RE = re.compile(
    r"(?:^|[^A-Z0-9])(WU|WUNDERGROUND|WEATHER_UNDERGROUND)(?:[^A-Z0-9]|$)",
    re.IGNORECASE,
)


class ForbiddenIntradaySourceError(ValueError):
    """Raised when a forbidden source (e.g., Weather Underground) attempts to enter M1 intraday stream."""


class UnknownStationTimezoneError(KeyError):
    """Raised when a station ICAO code has no registered IANA timezone."""


class CausalInputError(ValueError):
    """Raised when timestamps are naive or violate basic temporal contract."""


def _ensure_utc(dt: datetime, *, field_name: str) -> datetime:
    if not isinstance(dt, datetime):
        raise CausalInputError(f"{field_name} must be a datetime, got {type(dt).__name__}")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise CausalInputError(f"{field_name} must be timezone-aware UTC, got naive {dt!r}")
    return dt.astimezone(timezone.utc)


def _parse_iso_or_epoch_utc(value: Any, *, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return _ensure_utc(value, field_name=field_name)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise CausalInputError(f"{field_name} cannot be an empty string")
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return _ensure_utc(datetime.fromisoformat(raw), field_name=field_name)
    raise CausalInputError(f"{field_name}: unsupported timestamp value {value!r}")


def _assert_not_forbidden_intraday_channel(source_channel: str) -> None:
    if _FORBIDDEN_WU_CHANNEL_RE.search(source_channel or ""):
        raise ForbiddenIntradaySourceError(
            f"Source channel {source_channel!r} is barred from intraday M1 bridge stream "
            "(WU fallback is restricted exclusively to post-close M9 settlement per ADR-0012 §5)."
        )


def resolve_station_timezone(
    station_id: str,
    station_timezones: Optional[Mapping[str, str]] = None,
) -> ZoneInfo:
    """Resolve IANA `ZoneInfo` for `station_id` (fail-closed if unknown)."""
    code = station_id.strip().upper()
    mapping = station_timezones if station_timezones is not None else STATION_TIMEZONES
    tz_name = mapping.get(code)
    if not tz_name:
        raise UnknownStationTimezoneError(f"No IANA timezone registered for station {code!r}")
    return ZoneInfo(tz_name)


def compute_local_day_window_utc(
    target_date: date,
    station_tz: ZoneInfo,
) -> Tuple[datetime, datetime]:
    """Compute `[day_start_utc, settle_close_utc)` for `target_date` in DST-aware station local time.

    On US DST spring-forward days this window spans 23h; on fall-back days it spans 25h.
    `settle_close_utc` equals `(target_date + 1 day) 00:00:00 Local -> UTC` per ADR-0012 §5.
    """
    local_start = datetime(
        target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=station_tz
    )
    next_day = target_date + timedelta(days=1)
    local_end = datetime(
        next_day.year, next_day.month, next_day.day, 0, 0, 0, tzinfo=station_tz
    )
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


def celsius_to_fahrenheit_exact(temp_c: DecimalInput) -> Decimal:
    """Convert Celsius to Fahrenheit in exact guarded `Decimal` arithmetic (`d_F = d_C * 9 / 5 + 32`).

    Because 5 divides 10, this conversion is algebraically exact in base 10; `trap_inexact=True`
    structurally guarantees zero intermediate rounding.
    """
    d_c = to_guarded_decimal(temp_c, name="temp_c")
    with exact_decimal_context(prec=EXACT_DECIMAL_CONTEXT_PREC, trap_inexact=True):
        return (d_c * Decimal("9")) / Decimal("5") + Decimal("32")


def settle_round_pos_inf(temp_f: DecimalInput) -> int:
    """Round °F to nearest whole integer with exact `.5` rounded toward +infinity (`floor(x + 0.5)`).

    Matches Polymarket official settlement wording (ADR-0012 §5):
    - `-22.5°C = -8.5°F -> -8°F`
    - `-0.5°F -> 0°F`
    - `68.5°F -> 69°F`
    """
    d_f = to_guarded_decimal(temp_f, name="temp_f")
    with exact_decimal_context(prec=EXACT_DECIMAL_CONTEXT_PREC, trap_inexact=True):
        shifted = d_f + Decimal("0.5")
    with exact_decimal_context(prec=EXACT_DECIMAL_CONTEXT_PREC, trap_inexact=False):
        return int(shifted.to_integral_value(rounding=ROUND_FLOOR))


def classify_report_type(
    raw_text: str,
    declared_type: Optional[str] = None,
) -> ReportType:
    """Classify report per Polymarket official wording (ADR-0009 §4 / ADR-0012 §5).

    "A report whose line begins with SPECI is a special observation and does not count.
    Every other report is routine, including one issued off the nominal hour and one that
    carries no METAR or SPECI label."
    """
    stripped = (raw_text or "").lstrip().upper()
    if stripped.startswith("SPECI"):
        return "SPECI"
    if declared_type is not None and declared_type.strip().upper() == "SPECI":
        return "SPECI"
    return "METAR"


def detect_cor_flag(raw_text: str, declared_is_cor: bool = False) -> bool:
    """Detect whether a METAR/SPECI bulletin is a `COR` (corrected) report."""
    if declared_is_cor:
        return True
    body = _RMK_SPLIT_RE.split(raw_text or "", maxsplit=1)[0]
    header_tokens = body.strip().upper().split()[:6]
    return "COR" in header_tokens


@dataclass(frozen=True)
class RawMetarReport:
    """Immutable raw METAR/SPECI report returned by any `RawMetarSource` adapter."""

    station_id: str
    obs_ts_utc: datetime
    dispatch_ts_utc: Optional[datetime]
    report_type: ReportType
    is_cor: bool
    raw_text: str
    source_channel: str
    sequence_hint: int = 0

    def __post_init__(self) -> None:
        code = self.station_id.strip().upper()
        if not code:
            raise ValueError("station_id cannot be empty")
        object.__setattr__(self, "station_id", code)
        object.__setattr__(
            self, "obs_ts_utc", _ensure_utc(self.obs_ts_utc, field_name="obs_ts_utc")
        )
        if self.dispatch_ts_utc is not None:
            object.__setattr__(
                self,
                "dispatch_ts_utc",
                _ensure_utc(self.dispatch_ts_utc, field_name="dispatch_ts_utc"),
            )
        normalized_type = classify_report_type(self.raw_text, self.report_type)
        object.__setattr__(self, "report_type", normalized_type)
        object.__setattr__(self, "is_cor", detect_cor_flag(self.raw_text, self.is_cor))
        if not self.source_channel or not self.source_channel.strip():
            raise ValueError("source_channel must be a non-empty string")


@dataclass(frozen=True)
class ParsedMetarObservation:
    """Single METAR/SPECI bulletin parsed into settlement-isomorphic exact Decimal fields."""

    station_id: str
    obs_ts_utc: datetime
    dispatch_ts_utc: Optional[datetime]
    effective_causal_ts_utc: Optional[datetime]
    report_type: ReportType
    is_cor: bool
    oracle_source_tier: OracleSourceTier
    temp_c_dec: Optional[Decimal]
    temp_f_dec: Optional[Decimal]
    temp_f_int: Optional[int]
    raw_text: str
    source_channel: str
    sequence_hint: int = 0


@dataclass(frozen=True)
class MissingDispatchPolicy:
    """Explicit causal policy when historical/replay METAR records lack `dispatch_ts_utc` (§5 #1).

    Never permits a silent `0s` lag assumption:
    - `mode == "REJECT"`: fail-closed, excludes reports missing `dispatch_ts_utc`.
    - `mode == "CONSERVATIVE_LAG_BOUND"`: requires explicit `conservative_lag_bound_sec > 0.0`
      backed by `provenance`, and preserves `dispatch_age_available = False`.
    """

    mode: MissingDispatchMode
    provenance: str
    conservative_lag_bound_sec: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.provenance or not self.provenance.strip():
            raise ValueError("MissingDispatchPolicy.provenance must be non-empty")
        if self.mode == "REJECT":
            if self.conservative_lag_bound_sec is not None:
                raise ValueError(
                    "conservative_lag_bound_sec must be None when MissingDispatchPolicy.mode='REJECT'"
                )
        elif self.mode == "CONSERVATIVE_LAG_BOUND":
            lag = self.conservative_lag_bound_sec
            if lag is None or isinstance(lag, bool) or lag <= 0.0:
                raise ValueError(
                    "conservative_lag_bound_sec must be strictly > 0.0 for CONSERVATIVE_LAG_BOUND "
                    "(0s lag assumption is strictly forbidden per v0.3 §5 #1)"
                )
        else:
            raise ValueError(f"Unsupported MissingDispatchPolicy.mode: {self.mode!r}")


@dataclass(frozen=True)
class FreshnessPolicy:
    """Configuration-injected M1->M2 observation age limits with mandatory provenance (§1.2, §5 #2)."""

    physical_age_limit_sec: float
    provenance: str
    dispatch_age_limit_sec: Optional[float] = None
    require_dispatch_age: bool = False

    def __post_init__(self) -> None:
        if not self.provenance or not self.provenance.strip():
            raise ValueError("FreshnessPolicy.provenance must be non-empty")
        if isinstance(self.physical_age_limit_sec, bool) or self.physical_age_limit_sec <= 0.0:
            raise ValueError("physical_age_limit_sec must be > 0")
        if self.dispatch_age_limit_sec is not None:
            if (
                isinstance(self.dispatch_age_limit_sec, bool)
                or self.dispatch_age_limit_sec <= 0.0
            ):
                raise ValueError("dispatch_age_limit_sec must be > 0 when provided")


@dataclass(frozen=True)
class StationDayState:
    """P11 StationDayState output from M1 -> M2 (oracle-compliant routine METAR bridge stream)."""

    schema_version: str
    state_id: str
    as_of_ts_utc: datetime
    station_id: str
    station_timezone: str
    target_date: date
    day_start_utc: datetime
    settle_close_utc: datetime
    m_now_exact_f: Optional[Decimal]
    m_now_int_f: Optional[int]
    m_now_min_exact_f: Optional[Decimal]
    m_now_min_int_f: Optional[int]
    oracle_compliant: bool
    oracle_source_tier: OracleSourceTier
    latest_obs_utc: Optional[datetime]
    latest_dispatch_ts_utc: Optional[datetime]
    latest_instant_temp_f: Optional[Decimal]
    physical_age_sec: Optional[float]
    dispatch_age_sec: Optional[float]
    dispatch_age_available: bool
    freshness_ok: bool
    freshness_policy_provenance: str
    routine_obs_count: int
    cor_overwrites_count: int
    specis_seen_count: int
    gap_flags: Tuple[str, ...]

    @property
    def m_now_f(self) -> Optional[float]:
        """Float projection of exact Decimal `m_now_exact_f` for downstream numerical consumers."""
        return float(self.m_now_exact_f) if self.m_now_exact_f is not None else None


def compute_record_sha256(record_without_hash: Mapping[str, Any]) -> str:
    """Compute canonical 64-hex SHA256 matching `P8-T2-M7-LOGGING v1.0 §1.4`."""
    canonical = json.dumps(
        record_without_hash,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class CoverageLedgerEntry:
    """P12 Weather CoverageLedgerLog entry (`M1 -> M7`) conforming to `P8-T2-M7-LOGGING §2.5`."""

    schema_version: str
    run_ts_utc: datetime
    session_id: str
    execution_mode: ExecutionMode
    station_id: str
    target_date: str
    gfs_init_utc: Optional[str]
    gfs_available: bool
    gfs_completeness_ratio: float
    metar_source_mode: str
    metar_obs_count_window: int
    specis_seen_count: int
    total_reports_archived_count: int
    oracle_compliant: bool
    latest_obs_utc: Optional[str]
    physical_age_sec: Optional[float]
    dispatch_age_sec: Optional[float]
    dispatch_age_available: bool
    freshness_ok: bool
    gap_flags: Tuple[str, ...]
    model_hash: str
    config_hash: str

    def to_dict_without_hash(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_ts_utc": self.run_ts_utc.isoformat(),
            "session_id": self.session_id,
            "execution_mode": self.execution_mode,
            "station_id": self.station_id,
            "target_date": self.target_date,
            "gfs_init_utc": self.gfs_init_utc,
            "gfs_available": self.gfs_available,
            "gfs_completeness_ratio": self.gfs_completeness_ratio,
            "metar_source_mode": self.metar_source_mode,
            "metar_obs_count_window": self.metar_obs_count_window,
            "specis_seen_count": self.specis_seen_count,
            "total_reports_archived_count": self.total_reports_archived_count,
            "oracle_compliant": self.oracle_compliant,
            "latest_obs_utc": self.latest_obs_utc,
            "physical_age_sec": self.physical_age_sec,
            "dispatch_age_sec": self.dispatch_age_sec,
            "dispatch_age_available": self.dispatch_age_available,
            "freshness_ok": self.freshness_ok,
            "gap_flags": list(self.gap_flags),
            "model_hash": self.model_hash,
            "config_hash": self.config_hash,
        }

    def to_json_line(self) -> str:
        payload = self.to_dict_without_hash()
        payload["record_sha256"] = compute_record_sha256(payload)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def verify_p12_json_line(line: str) -> bool:
    """Verify canonical `record_sha256` integrity of a serialized P12 JSONL line."""
    data = json.loads(line)
    expected = data.pop("record_sha256", None)
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    return compute_record_sha256(data) == expected


@dataclass(frozen=True)
class DualStreamEvaluation:
    """Output of one causal M1 evaluation: isolated P11 bridge state + full archival stream + P12."""

    state: StationDayState
    accepted_routine_observations: Tuple[ParsedMetarObservation, ...]
    archival_observations: Tuple[ParsedMetarObservation, ...]
    coverage_ledger: CoverageLedgerEntry


class RawMetarSource(Protocol):
    """Read-only port abstracting live AWC, paper replay, and historical shadow METAR feeds."""

    source_mode: str

    def fetch_window(
        self,
        station_id: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> Tuple[RawMetarReport, ...]:
        """Return all raw METAR/SPECI reports for `station_id` with `start_utc <= obs_ts_utc < end_utc`."""
        ...


class SettlementIsomorphicParser:
    """Pure parser implementing ADR-0009 §4 & ADR-0012 §5 METAR extraction in exact Decimal domain."""

    @staticmethod
    def parse_temperature_c(raw_text: str) -> Tuple[Optional[Decimal], OracleSourceTier]:
        """Extract exact Celsius temperature (`T`-group 0.1°C first, then body `TT/TD` 1°C fallback)."""
        if not raw_text:
            return None, "MISSING"

        parts = _RMK_SPLIT_RE.split(raw_text, maxsplit=1)
        body_part = parts[0]
        rmk_part = parts[1] if len(parts) > 1 else raw_text

        t_match = _TGROUP_RE.search(rmk_part)
        if t_match:
            sign_char, digits = t_match.group(1), t_match.group(2)
            with exact_decimal_context(prec=EXACT_DECIMAL_CONTEXT_PREC, trap_inexact=True):
                mag = Decimal(digits) / Decimal("10")
                temp_c = -mag if sign_char == "1" and mag != 0 else mag
                if temp_c == 0:
                    temp_c = Decimal("0.0")
            return temp_c, "AWC_METAR_TGROUP"

        body_match = _BODY_TEMP_RE.search(body_part)
        if body_match:
            token = body_match.group(1)
            if token.startswith("M"):
                mag_int = int(token[1:])
                temp_c = Decimal(-mag_int) if mag_int != 0 else Decimal("0")
            else:
                temp_c = Decimal(int(token))
            return temp_c, "AWC_METAR_BODY"

        return None, "MISSING"

    @classmethod
    def parse_report(
        cls,
        report: RawMetarReport,
        *,
        effective_causal_ts_utc: Optional[datetime] = None,
    ) -> ParsedMetarObservation:
        """Parse a `RawMetarReport` into exact `Decimal` Celsius, Fahrenheit, and settlement integer °F."""
        temp_c_dec, tier = cls.parse_temperature_c(report.raw_text)
        if temp_c_dec is not None:
            temp_f_dec: Optional[Decimal] = celsius_to_fahrenheit_exact(temp_c_dec)
            temp_f_int: Optional[int] = settle_round_pos_inf(temp_f_dec)
        else:
            temp_f_dec = None
            temp_f_int = None

        return ParsedMetarObservation(
            station_id=report.station_id,
            obs_ts_utc=report.obs_ts_utc,
            dispatch_ts_utc=report.dispatch_ts_utc,
            effective_causal_ts_utc=effective_causal_ts_utc,
            report_type=report.report_type,
            is_cor=report.is_cor,
            oracle_source_tier=tier,
            temp_c_dec=temp_c_dec,
            temp_f_dec=temp_f_dec,
            temp_f_int=temp_f_int,
            raw_text=report.raw_text,
            source_channel=report.source_channel,
            sequence_hint=report.sequence_hint,
        )


def compute_settlement_lock_ts_utc(
    target_date: date,
    station_tz: ZoneInfo,
    reports: Sequence[RawMetarReport],
    *,
    causal_lock_candidates_utc: Optional[Sequence[datetime]] = None,
) -> datetime:
    """Compute Polymarket revision lock point per ADR-0012 §5.

    Locks at the earlier of:
    1. First routine METAR causal availability timestamp on `target_date + 1`+,
    2. `11:59 PM America/New_York` on `target_date + 1`.

    When `causal_lock_candidates_utc` is supplied (resolved via `_resolve_causal_ts`), lock
    timing uses the exact same causal availability timestamps (`eff_ts`) as visibility filtering,
    preventing retroactive COR revocation under `CONSERVATIVE_LAG_BOUND`.
    """
    _, settle_close_utc = compute_local_day_window_utc(target_date, station_tz)
    next_day = target_date + timedelta(days=1)
    et_deadline_utc = datetime(
        next_day.year, next_day.month, next_day.day, 23, 59, 0, tzinfo=_US_EASTERN_TZ
    ).astimezone(timezone.utc)

    next_day_candidates: List[datetime] = []
    if causal_lock_candidates_utc is not None:
        for ts in causal_lock_candidates_utc:
            next_day_candidates.append(_ensure_utc(ts, field_name="causal_lock_candidates_utc"))
    else:
        for rep in reports:
            if rep.report_type != "METAR":
                continue
            if rep.obs_ts_utc >= settle_close_utc:
                ts = rep.dispatch_ts_utc if rep.dispatch_ts_utc is not None else rep.obs_ts_utc
                next_day_candidates.append(ts)

    if not next_day_candidates:
        return et_deadline_utc
    return min(min(next_day_candidates), et_deadline_utc)


def _parse_awc_utc_timestamp(value: Any, *, field_name: str) -> datetime:
    """Parse AWC JSON timestamp where string values without tz suffix (e.g. `receiptTime`) denote UTC."""
    if isinstance(value, datetime):
        return _ensure_utc(value, field_name=field_name)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise CausalInputError(f"{field_name} cannot be an empty string")
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None or dt.utcoffset() is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    raise CausalInputError(f"{field_name}: unsupported timestamp value {value!r}")


class LiveAwcMetarAdapter:
    """Read-only adapter for `aviationweather.gov/api/data/metar` JSON feed."""

    BASE_URL = "https://aviationweather.gov/api/data/metar"
    source_mode: str = "AWC_LIVE"

    def __init__(
        self,
        *,
        http_get: Optional[Callable[[str, Mapping[str, Any], float], Any]] = None,
        clock_utc: Optional[Callable[[], datetime]] = None,
        timeout_sec: float = 10.0,
    ) -> None:
        self._http_get = http_get or self._default_http_get
        self._clock_utc = clock_utc or (lambda: datetime.now(timezone.utc))
        self._timeout_sec = float(timeout_sec)

    @staticmethod
    def _default_http_get(url: str, params: Mapping[str, Any], timeout: float) -> Any:
        resp = requests.get(url, params=dict(params), timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def fetch_window(
        self,
        station_id: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> Tuple[RawMetarReport, ...]:
        start = _ensure_utc(start_utc, field_name="start_utc")
        end = _ensure_utc(end_utc, field_name="end_utc")
        if end <= start:
            raise ValueError("end_utc must be strictly greater than start_utc")

        code = station_id.strip().upper()
        now_utc = _ensure_utc(self._clock_utc(), field_name="clock_utc")
        if end <= now_utc:
            window_hours = max(1, int(((end - start).total_seconds() + 3599) // 3600) + 1)
            params: Dict[str, Any] = {
                "ids": code,
                "format": "json",
                "date": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "hours": window_hours,
            }
        else:
            hours_back = max(1, int(((now_utc - start).total_seconds() + 3599) // 3600) + 1)
            params = {
                "ids": code,
                "format": "json",
                "hours": hours_back,
            }
        payload = self._http_get(self.BASE_URL, params, self._timeout_sec)
        if not payload:
            return ()

        reports: List[RawMetarReport] = []
        for idx, item in enumerate(payload):
            if not isinstance(item, Mapping):
                continue
            item_station = str(item.get("icaoId") or code).strip().upper()
            if item_station != code:
                continue
            raw_ob = str(item.get("rawOb") or "").strip()
            if not raw_ob:
                continue

            obs_raw = item.get("obsTime")
            if obs_raw is None:
                obs_raw = item.get("reportTime")
            if obs_raw is None:
                continue
            obs_ts = _parse_awc_utc_timestamp(obs_raw, field_name="obsTime")
            if not (start <= obs_ts < end):
                continue

            receipt_raw = item.get("receiptTime")
            dispatch_ts = (
                _parse_awc_utc_timestamp(receipt_raw, field_name="receiptTime")
                if receipt_raw is not None
                else now_utc
            )
            metar_type = item.get("metarType")
            reports.append(
                RawMetarReport(
                    station_id=code,
                    obs_ts_utc=obs_ts,
                    dispatch_ts_utc=dispatch_ts,
                    report_type=classify_report_type(
                        raw_ob, str(metar_type) if metar_type is not None else None
                    ),
                    is_cor=detect_cor_flag(raw_ob),
                    raw_text=raw_ob,
                    source_channel="AWC_LIVE",
                    sequence_hint=idx,
                )
            )
        return tuple(reports)


class PaperReplayMetarAdapter:
    """Read-only adapter over recorded in-memory or JSONL METAR/SPECI frames for paper replay."""

    source_mode: str = "PAPER_REPLAY"

    def __init__(self, reports: Iterable[RawMetarReport]) -> None:
        validated: List[RawMetarReport] = []
        for rep in reports:
            _assert_not_forbidden_intraday_channel(rep.source_channel)
            validated.append(rep)
        self._reports: Tuple[RawMetarReport, ...] = tuple(validated)

    @classmethod
    def from_jsonl(cls, path: Path) -> "PaperReplayMetarAdapter":
        loaded: List[RawMetarReport] = []
        with Path(path).open("r", encoding="utf-8") as fh:
            for idx, line in enumerate(fh):
                stripped = line.strip()
                if not stripped:
                    continue
                row = json.loads(stripped)
                dispatch_val = row.get("dispatch_ts_utc")
                loaded.append(
                    RawMetarReport(
                        station_id=str(row["station_id"]),
                        obs_ts_utc=_parse_iso_or_epoch_utc(
                            row["obs_ts_utc"], field_name="obs_ts_utc"
                        ),
                        dispatch_ts_utc=(
                            _parse_iso_or_epoch_utc(dispatch_val, field_name="dispatch_ts_utc")
                            if dispatch_val is not None
                            else None
                        ),
                        report_type=classify_report_type(
                            str(row["raw_text"]), row.get("report_type")
                        ),
                        is_cor=bool(row.get("is_cor", False)),
                        raw_text=str(row["raw_text"]),
                        source_channel=str(row.get("source_channel", "PAPER_REPLAY")),
                        sequence_hint=int(row.get("sequence_hint", idx)),
                    )
                )
        return cls(loaded)

    def fetch_window(
        self,
        station_id: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> Tuple[RawMetarReport, ...]:
        start = _ensure_utc(start_utc, field_name="start_utc")
        end = _ensure_utc(end_utc, field_name="end_utc")
        if end <= start:
            raise ValueError("end_utc must be strictly greater than start_utc")
        code = station_id.strip().upper()
        return tuple(
            r for r in self._reports if r.station_id == code and start <= r.obs_ts_utc < end
        )


class HistoricalShadowMetarAdapter:
    """Read-only adapter for historical shadow verification (e.g. 2019 T8 morphology check).

    Preserves `dispatch_ts_utc=None` when archive rows lack dispatch timestamps rather than
    fabricating zero transmission lag.
    """

    source_mode: str = "HISTORICAL_SHADOW"

    def __init__(self, rows: Iterable[Mapping[str, Any]]) -> None:
        parsed: List[RawMetarReport] = []
        for idx, row in enumerate(rows):
            channel = str(row.get("source_channel", "HISTORICAL_SHADOW"))
            _assert_not_forbidden_intraday_channel(channel)
            dispatch_val = row.get("dispatch_ts_utc")
            raw_text = str(row["raw_text"])
            parsed.append(
                RawMetarReport(
                    station_id=str(row["station_id"]),
                    obs_ts_utc=_parse_iso_or_epoch_utc(
                        row["obs_ts_utc"], field_name="obs_ts_utc"
                    ),
                    dispatch_ts_utc=(
                        _parse_iso_or_epoch_utc(dispatch_val, field_name="dispatch_ts_utc")
                        if dispatch_val is not None
                        else None
                    ),
                    report_type=classify_report_type(raw_text, row.get("report_type")),
                    is_cor=bool(row.get("is_cor", False)),
                    raw_text=raw_text,
                    source_channel=channel,
                    sequence_hint=int(row.get("sequence_hint", idx)),
                )
            )
        self._reports: Tuple[RawMetarReport, ...] = tuple(parsed)

    def fetch_window(
        self,
        station_id: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> Tuple[RawMetarReport, ...]:
        start = _ensure_utc(start_utc, field_name="start_utc")
        end = _ensure_utc(end_utc, field_name="end_utc")
        if end <= start:
            raise ValueError("end_utc must be strictly greater than start_utc")
        code = station_id.strip().upper()
        return tuple(
            r for r in self._reports if r.station_id == code and start <= r.obs_ts_utc < end
        )


class SettlementMetarStreamEngine:
    """M1 dual-stream causal engine producing oracle-compliant P11 state and P12 ledger entries."""

    def __init__(
        self,
        *,
        source: RawMetarSource,
        freshness_policy: FreshnessPolicy,
        missing_dispatch_policy: MissingDispatchPolicy,
        station_timezones: Optional[Mapping[str, str]] = None,
    ) -> None:
        self._source = source
        self._freshness_policy = freshness_policy
        self._missing_dispatch_policy = missing_dispatch_policy
        self._station_timezones = station_timezones

    def evaluate_as_of(
        self,
        *,
        station_id: str,
        target_date: date,
        as_of_ts_utc: datetime,
        session_id: str,
        execution_mode: ExecutionMode,
        model_hash: str,
        config_hash: str,
        gfs_init_utc: Optional[str] = None,
        gfs_available: bool = False,
        gfs_completeness_ratio: float = 0.0,
        apply_post_close_settlement_lock: bool = True,
    ) -> DualStreamEvaluation:
        """Evaluate causal prefix up to `as_of_ts_utc` for `(station_id, target_date)`."""
        as_of = _ensure_utc(as_of_ts_utc, field_name="as_of_ts_utc")
        code = station_id.strip().upper()
        station_tz = resolve_station_timezone(code, self._station_timezones)
        day_start_utc, settle_close_utc = compute_local_day_window_utc(target_date, station_tz)

        # Fetch target local day reports; if evaluating post-close with lock enforcement, also fetch
        # next day window up to next-day 11:59 PM ET so first next-day routine METAR can lock CORs.
        next_day = target_date + timedelta(days=1)
        et_deadline_utc = datetime(
            next_day.year, next_day.month, next_day.day, 23, 59, 0, tzinfo=_US_EASTERN_TZ
        ).astimezone(timezone.utc)
        fetch_end_utc = (
            max(settle_close_utc, min(as_of + timedelta(seconds=1), et_deadline_utc + timedelta(seconds=1)))
            if apply_post_close_settlement_lock and as_of >= settle_close_utc
            else settle_close_utc
        )
        raw_reports = self._source.fetch_window(code, day_start_utc, fetch_end_utc)

        gap_flags: List[str] = []
        day_reports: List[RawMetarReport] = []
        next_day_reports: List[RawMetarReport] = []

        for rep in raw_reports:
            _assert_not_forbidden_intraday_channel(rep.source_channel)
            if rep.station_id != code:
                continue
            if day_start_utc <= rep.obs_ts_utc < settle_close_utc:
                day_reports.append(rep)
            elif rep.obs_ts_utc >= settle_close_utc:
                next_day_reports.append(rep)

        # Causally filter next-day reports before computing post-close lock point
        causal_next_day: List[RawMetarReport] = []
        causal_next_day_lock_ts: List[datetime] = []
        for rep in next_day_reports:
            eff_ts = self._resolve_causal_ts(rep, as_of, gap_flags_out=None)
            if eff_ts is not None:
                causal_next_day.append(rep)
                if rep.report_type == "METAR":
                    causal_next_day_lock_ts.append(eff_ts)

        lock_ts_utc: Optional[datetime] = None
        if apply_post_close_settlement_lock and as_of >= settle_close_utc:
            lock_ts_utc = compute_settlement_lock_ts_utc(
                target_date,
                station_tz,
                causal_next_day,
                causal_lock_candidates_utc=causal_next_day_lock_ts,
            )

        archival_obs: List[ParsedMetarObservation] = []
        routine_by_obs_ts: Dict[datetime, List[ParsedMetarObservation]] = {}
        specis_seen_count = 0

        for rep in day_reports:
            eff_ts = self._resolve_causal_ts(rep, as_of, gap_flags_out=gap_flags)
            if eff_ts is None:
                continue

            parsed = SettlementIsomorphicParser.parse_report(
                rep, effective_causal_ts_utc=eff_ts
            )
            archival_obs.append(parsed)

            if parsed.report_type == "SPECI":
                specis_seen_count += 1
                continue

            if lock_ts_utc is not None and parsed.is_cor and eff_ts > lock_ts_utc:
                if "POST_LOCK_COR_IGNORED" not in gap_flags:
                    gap_flags.append("POST_LOCK_COR_IGNORED")
                continue

            routine_by_obs_ts.setdefault(parsed.obs_ts_utc, []).append(parsed)

        # Deduplicate per obs_ts_utc with COR overwrite semantics
        accepted_routine: List[ParsedMetarObservation] = []
        cor_overwrites_count = 0
        for obs_ts in sorted(routine_by_obs_ts.keys()):
            candidates = routine_by_obs_ts[obs_ts]
            ordered = sorted(
                candidates,
                key=lambda o: (
                    1 if o.is_cor else 0,
                    o.effective_causal_ts_utc or o.obs_ts_utc,
                    o.sequence_hint,
                ),
            )
            winner = ordered[-1]
            if winner.is_cor and len(ordered) > 1:
                cor_overwrites_count += 1
            if winner.temp_f_dec is None:
                flag = "COR_UNPARSEABLE_TEMP" if winner.is_cor else "UNPARSEABLE_ROUTINE_TEMP"
                if flag not in gap_flags:
                    gap_flags.append(flag)
            accepted_routine.append(winner)

        valid_routine = [o for o in accepted_routine if o.temp_f_dec is not None and o.temp_f_int is not None]

        m_now_exact_f: Optional[Decimal] = None
        m_now_int_f: Optional[int] = None
        m_now_min_exact_f: Optional[Decimal] = None
        m_now_min_int_f: Optional[int] = None
        oracle_source_tier: OracleSourceTier = "MISSING"
        latest_obs_utc: Optional[datetime] = None
        latest_dispatch_ts_utc: Optional[datetime] = None
        latest_instant_temp_f: Optional[Decimal] = None
        physical_age_sec: Optional[float] = None
        dispatch_age_sec: Optional[float] = None
        dispatch_age_available = False
        freshness_ok = False

        if not valid_routine:
            gap_flags.append("NO_ROUTINE_METAR_IN_DAY_WINDOW")
        else:
            # Exact Decimal max/min and runtime commutation check against per-observation rounded ints
            winning_max = max(
                valid_routine,
                key=lambda o: (
                    o.temp_f_dec,  # type: ignore[arg-type]
                    1 if o.oracle_source_tier == "AWC_METAR_TGROUP" else 0,
                    -o.obs_ts_utc.timestamp(),
                ),
            )
            winning_min = min(
                valid_routine,
                key=lambda o: (
                    o.temp_f_dec,  # type: ignore[arg-type]
                    o.obs_ts_utc.timestamp(),
                ),
            )
            m_now_exact_f = winning_max.temp_f_dec
            assert m_now_exact_f is not None
            m_now_int_f = settle_round_pos_inf(m_now_exact_f)
            max_of_rounded = max(o.temp_f_int for o in valid_routine if o.temp_f_int is not None)
            if m_now_int_f != max_of_rounded:
                raise AssertionError(
                    f"max/floor commutation violated: floor(max)={m_now_int_f} != max(floor)={max_of_rounded}"
                )

            m_now_min_exact_f = winning_min.temp_f_dec
            assert m_now_min_exact_f is not None
            m_now_min_int_f = settle_round_pos_inf(m_now_min_exact_f)
            min_of_rounded = min(o.temp_f_int for o in valid_routine if o.temp_f_int is not None)
            if m_now_min_int_f != min_of_rounded:
                raise AssertionError(
                    f"min/floor commutation violated: floor(min)={m_now_min_int_f} != min(floor)={min_of_rounded}"
                )

            oracle_source_tier = winning_max.oracle_source_tier

            latest_obs = max(
                valid_routine,
                key=lambda o: (o.obs_ts_utc, o.effective_causal_ts_utc or o.obs_ts_utc),
            )
            latest_obs_utc = latest_obs.obs_ts_utc
            latest_dispatch_ts_utc = latest_obs.dispatch_ts_utc
            latest_instant_temp_f = latest_obs.temp_f_dec

            physical_age_sec = (as_of - latest_obs_utc).total_seconds()
            physical_ok = 0.0 <= physical_age_sec <= self._freshness_policy.physical_age_limit_sec
            if not physical_ok:
                gap_flags.append("PHYSICAL_AGE_EXCEEDED")

            if latest_dispatch_ts_utc is not None:
                dispatch_age_available = True
                dispatch_age_sec = (as_of - latest_dispatch_ts_utc).total_seconds()
                if self._freshness_policy.dispatch_age_limit_sec is None:
                    dispatch_ok = dispatch_age_sec >= 0.0
                else:
                    dispatch_ok = (
                        0.0 <= dispatch_age_sec <= self._freshness_policy.dispatch_age_limit_sec
                    )
                if not dispatch_ok:
                    gap_flags.append("DISPATCH_AGE_EXCEEDED")
            else:
                dispatch_age_available = False
                dispatch_age_sec = None
                dispatch_ok = not self._freshness_policy.require_dispatch_age
                if not dispatch_ok:
                    gap_flags.append("DISPATCH_AGE_UNAVAILABLE")

            freshness_ok = bool(physical_ok and dispatch_ok)

        dedup_flags = tuple(dict.fromkeys(gap_flags))
        state_key = "|".join(
            [
                code,
                target_date.isoformat(),
                as_of.isoformat(),
                latest_obs_utc.isoformat() if latest_obs_utc is not None else "NONE",
                str(m_now_exact_f) if m_now_exact_f is not None else "NONE",
                "ORACLE_COMPLIANT",
            ]
        )
        state_id = str(uuid.uuid5(_STATE_ID_NAMESPACE, state_key))

        state = StationDayState(
            schema_version="p11.v1",
            state_id=state_id,
            as_of_ts_utc=as_of,
            station_id=code,
            station_timezone=str(station_tz.key),
            target_date=target_date,
            day_start_utc=day_start_utc,
            settle_close_utc=settle_close_utc,
            m_now_exact_f=m_now_exact_f,
            m_now_int_f=m_now_int_f,
            m_now_min_exact_f=m_now_min_exact_f,
            m_now_min_int_f=m_now_min_int_f,
            oracle_compliant=True,
            oracle_source_tier=oracle_source_tier,
            latest_obs_utc=latest_obs_utc,
            latest_dispatch_ts_utc=latest_dispatch_ts_utc,
            latest_instant_temp_f=latest_instant_temp_f,
            physical_age_sec=physical_age_sec,
            dispatch_age_sec=dispatch_age_sec,
            dispatch_age_available=dispatch_age_available,
            freshness_ok=freshness_ok,
            freshness_policy_provenance=self._freshness_policy.provenance,
            routine_obs_count=len(valid_routine),
            cor_overwrites_count=cor_overwrites_count,
            specis_seen_count=specis_seen_count,
            gap_flags=dedup_flags,
        )

        ledger = CoverageLedgerEntry(
            schema_version="p12.v1",
            run_ts_utc=as_of,
            session_id=session_id,
            execution_mode=execution_mode,
            station_id=code,
            target_date=target_date.isoformat(),
            gfs_init_utc=gfs_init_utc,
            gfs_available=bool(gfs_available),
            gfs_completeness_ratio=float(gfs_completeness_ratio),
            metar_source_mode=self._source.source_mode,
            metar_obs_count_window=len(valid_routine),
            specis_seen_count=specis_seen_count,
            total_reports_archived_count=len(archival_obs),
            oracle_compliant=True,
            latest_obs_utc=latest_obs_utc.isoformat() if latest_obs_utc is not None else None,
            physical_age_sec=physical_age_sec,
            dispatch_age_sec=dispatch_age_sec,
            dispatch_age_available=dispatch_age_available,
            freshness_ok=freshness_ok,
            gap_flags=dedup_flags,
            model_hash=model_hash,
            config_hash=config_hash,
        )

        archival_sorted = tuple(
            sorted(
                archival_obs,
                key=lambda o: (o.obs_ts_utc, o.effective_causal_ts_utc or o.obs_ts_utc, o.sequence_hint),
            )
        )
        return DualStreamEvaluation(
            state=state,
            accepted_routine_observations=tuple(accepted_routine),
            archival_observations=archival_sorted,
            coverage_ledger=ledger,
        )

    def _resolve_causal_ts(
        self,
        report: RawMetarReport,
        as_of_ts_utc: datetime,
        *,
        gap_flags_out: Optional[List[str]],
    ) -> Optional[datetime]:
        """Return effective causal availability timestamp if visible at `as_of_ts_utc`, else `None`."""
        if report.obs_ts_utc > as_of_ts_utc:
            return None

        if report.dispatch_ts_utc is not None:
            if report.dispatch_ts_utc > as_of_ts_utc:
                return None
            return report.dispatch_ts_utc

        # Missing dispatch_ts_utc: never assume 0s lag (v0.3 §5 #1)
        if self._missing_dispatch_policy.mode == "REJECT":
            if gap_flags_out is not None and "MISSING_DISPATCH_TS_REJECTED" not in gap_flags_out:
                gap_flags_out.append("MISSING_DISPATCH_TS_REJECTED")
            return None

        assert self._missing_dispatch_policy.conservative_lag_bound_sec is not None
        bounded_ts = report.obs_ts_utc + timedelta(
            seconds=self._missing_dispatch_policy.conservative_lag_bound_sec
        )
        if bounded_ts > as_of_ts_utc:
            return None
        if gap_flags_out is not None and "MISSING_DISPATCH_TS_BOUNDED" not in gap_flags_out:
            gap_flags_out.append("MISSING_DISPATCH_TS_BOUNDED")
        return bounded_ts


def extract_settlement_reference_int(
    *,
    station_id: str,
    target_date: date,
    reports: Sequence[RawMetarReport],
    as_of_ts_utc: Optional[datetime] = None,
    station_timezones: Optional[Mapping[str, str]] = None,
) -> Optional[int]:
    """Independent reference settlement extractor implementing Polymarket contract wording directly.

    Used by M1 frame-by-frame acceptance tests to verify `P11(t_i).m_now_int_f == settlement_prefix(t_i)`
    and `P11(t_i).m_now_int_f <= T_settle(D)` without sharing state with `SettlementMetarStreamEngine`.
    """
    code = station_id.strip().upper()
    tz = resolve_station_timezone(code, station_timezones)
    day_start_utc, settle_close_utc = compute_local_day_window_utc(target_date, tz)
    as_of = _ensure_utc(as_of_ts_utc, field_name="as_of_ts_utc") if as_of_ts_utc is not None else None

    next_day_visible = [
        r
        for r in reports
        if r.station_id == code
        and r.obs_ts_utc >= settle_close_utc
        and not r.raw_text.lstrip().upper().startswith("SPECI")
        and r.report_type != "SPECI"
        and (
            as_of is None
            or (
                r.obs_ts_utc <= as_of
                and r.dispatch_ts_utc is not None
                and r.dispatch_ts_utc <= as_of
            )
        )
    ]
    lock_ts = (
        compute_settlement_lock_ts_utc(target_date, tz, next_day_visible)
        if as_of is None or as_of >= settle_close_utc
        else None
    )

    by_obs_ts: Dict[datetime, List[RawMetarReport]] = {}
    for rep in reports:
        if rep.station_id != code:
            continue
        if rep.raw_text.lstrip().upper().startswith("SPECI") or rep.report_type == "SPECI":
            continue
        if not (day_start_utc <= rep.obs_ts_utc < settle_close_utc):
            continue
        if as_of is not None:
            if rep.obs_ts_utc > as_of:
                continue
            if rep.dispatch_ts_utc is None or rep.dispatch_ts_utc > as_of:
                continue
        eff_ts = rep.dispatch_ts_utc if rep.dispatch_ts_utc is not None else rep.obs_ts_utc
        if lock_ts is not None and rep.is_cor and eff_ts > lock_ts:
            continue
        by_obs_ts.setdefault(rep.obs_ts_utc, []).append(rep)

    rounded_temps: List[int] = []
    for obs_ts, group in by_obs_ts.items():
        winner = sorted(
            group,
            key=lambda r: (
                1 if r.is_cor else 0,
                r.dispatch_ts_utc if r.dispatch_ts_utc is not None else r.obs_ts_utc,
                r.sequence_hint,
            ),
        )[-1]
        temp_c, _ = SettlementIsomorphicParser.parse_temperature_c(winner.raw_text)
        if temp_c is None:
            continue
        temp_f = celsius_to_fahrenheit_exact(temp_c)
        rounded_temps.append(settle_round_pos_inf(temp_f))

    return max(rounded_temps) if rounded_temps else None


__all__ = [
    "CausalInputError",
    "CoverageLedgerEntry",
    "DualStreamEvaluation",
    "ExecutionMode",
    "ForbiddenIntradaySourceError",
    "FreshnessPolicy",
    "HistoricalShadowMetarAdapter",
    "LiveAwcMetarAdapter",
    "MissingDispatchMode",
    "MissingDispatchPolicy",
    "OracleSourceTier",
    "PaperReplayMetarAdapter",
    "ParsedMetarObservation",
    "RawMetarReport",
    "RawMetarSource",
    "ReportType",
    "SettlementIsomorphicParser",
    "SettlementMetarStreamEngine",
    "StationDayState",
    "UnknownStationTimezoneError",
    "celsius_to_fahrenheit_exact",
    "classify_report_type",
    "compute_local_day_window_utc",
    "compute_record_sha256",
    "compute_settlement_lock_ts_utc",
    "detect_cor_flag",
    "extract_settlement_reference_int",
    "resolve_station_timezone",
    "settle_round_pos_inf",
    "verify_p12_json_line",
]
