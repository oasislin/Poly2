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
from src.utils.causal_utils import (
    CausalInputError,
    compute_record_sha256,
    ensure_utc_datetime,
    parse_utc_timestamp,
    verify_record_sha256_line,
)
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

_RMK_SPLIT_RE = re.compile(r"\bRMK\b", re.IGNORECASE)
_TGROUP_RE = re.compile(r"(?:^|\s)T([01])(\d{3})(?:[01]\d{3}|////)(?=\s|=|$)")
_BODY_TEMP_RE = re.compile(r"(?:^|\s)(M?\d{2})/(?:M?\d{2}|//)(?=\s|=|$)")
_FORBIDDEN_WU_CHANNEL_RE = re.compile(
    r"(?:^|[^A-Z0-9])(WU|WUNDERGROUND|WEATHER_UNDERGROUND)(?:[^A-Z0-9]|$)",
    re.IGNORECASE,
)

verify_p12_json_line = verify_record_sha256_line


class ForbiddenIntradaySourceError(ValueError):
    """Raised when a forbidden source (e.g., Weather Underground) enters M1 intraday stream."""


class UnknownStationTimezoneError(KeyError):
    """Raised when a station ICAO code has no registered IANA timezone."""


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
    """Compute `[day_start_utc, settle_close_utc)` for `target_date` in DST-aware station local time."""
    local_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=station_tz)
    next_day = target_date + timedelta(days=1)
    local_end = datetime(next_day.year, next_day.month, next_day.day, tzinfo=station_tz)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


def _et_lock_deadline_utc(target_date: date) -> datetime:
    next_day = target_date + timedelta(days=1)
    return datetime(
        next_day.year, next_day.month, next_day.day, 23, 59, 0, tzinfo=_US_EASTERN_TZ
    ).astimezone(timezone.utc)


def celsius_to_fahrenheit_exact(temp_c: DecimalInput) -> Decimal:
    """Convert Celsius to Fahrenheit in exact guarded `Decimal` arithmetic."""
    d_c = to_guarded_decimal(temp_c, name="temp_c")
    with exact_decimal_context(prec=EXACT_DECIMAL_CONTEXT_PREC, trap_inexact=True):
        return (d_c * Decimal("9")) / Decimal("5") + Decimal("32")


def settle_round_pos_inf(temp_f: DecimalInput) -> int:
    """Round °F to nearest whole integer with `.5` rounded toward +infinity (`floor(x + 0.5)`)."""
    d_f = to_guarded_decimal(temp_f, name="temp_f")
    with exact_decimal_context(prec=EXACT_DECIMAL_CONTEXT_PREC, trap_inexact=True):
        shifted = d_f + Decimal("0.5")
    with exact_decimal_context(prec=EXACT_DECIMAL_CONTEXT_PREC, trap_inexact=False):
        return int(shifted.to_integral_value(rounding=ROUND_FLOOR))


def classify_report_type(raw_text: str, declared_type: Optional[str] = None) -> ReportType:
    """Classify report per Polymarket official wording (ADR-0009 §4 / ADR-0012 §5)."""
    if (raw_text or "").lstrip().upper().startswith("SPECI"):
        return "SPECI"
    if declared_type is not None and declared_type.strip().upper() == "SPECI":
        return "SPECI"
    return "METAR"


def detect_cor_flag(raw_text: str, declared_is_cor: bool = False) -> bool:
    """Detect whether a METAR/SPECI bulletin is a `COR` (corrected) report."""
    if declared_is_cor:
        return True
    body = _RMK_SPLIT_RE.split(raw_text or "", maxsplit=1)[0]
    return "COR" in body.strip().upper().split()[:6]


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
            self, "obs_ts_utc", ensure_utc_datetime(self.obs_ts_utc, field_name="obs_ts_utc")
        )
        if self.dispatch_ts_utc is not None:
            object.__setattr__(
                self,
                "dispatch_ts_utc",
                ensure_utc_datetime(self.dispatch_ts_utc, field_name="dispatch_ts_utc"),
            )
        object.__setattr__(self, "report_type", classify_report_type(self.raw_text, self.report_type))
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
    """Explicit causal policy when METAR records lack `dispatch_ts_utc` (`v0.3 §5 #1`)."""

    mode: MissingDispatchMode
    provenance: str
    conservative_lag_bound_sec: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.provenance or not self.provenance.strip():
            raise ValueError("MissingDispatchPolicy.provenance must be non-empty")
        if self.mode == "REJECT":
            if self.conservative_lag_bound_sec is not None:
                raise ValueError("conservative_lag_bound_sec must be None when mode='REJECT'")
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
    """Configuration-injected M1->M2 observation age limits with mandatory provenance."""

    physical_age_limit_sec: float
    provenance: str
    dispatch_age_limit_sec: Optional[float] = None
    require_dispatch_age: bool = False

    def __post_init__(self) -> None:
        if not self.provenance or not self.provenance.strip():
            raise ValueError("FreshnessPolicy.provenance must be non-empty")
        if isinstance(self.physical_age_limit_sec, bool) or self.physical_age_limit_sec <= 0.0:
            raise ValueError("physical_age_limit_sec must be > 0")
        if self.dispatch_age_limit_sec is not None and (
            isinstance(self.dispatch_age_limit_sec, bool) or self.dispatch_age_limit_sec <= 0.0
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
        """Float projection of exact Decimal `m_now_exact_f` for downstream consumers."""
        return float(self.m_now_exact_f) if self.m_now_exact_f is not None else None


@dataclass(frozen=True)
class CoverageLedgerEntry:
    """P12 Weather CoverageLedgerLog (`M1 -> M7`) aligned to `P8-T2-M7-LOGGING §2.5` + `v0.3 §1.2`."""

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


@dataclass(frozen=True)
class DualStreamEvaluation:
    """Output of one causal M1 evaluation: isolated P11 bridge state + archival stream + P12."""

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
        """Return raw METAR/SPECI reports for `station_id` with `start_utc <= obs_ts_utc < end_utc`."""
        ...


class SettlementIsomorphicParser:
    """Pure parser implementing ADR-0009 §4 & ADR-0012 §5 METAR extraction in exact Decimal domain."""

    @staticmethod
    def parse_temperature_c(raw_text: str) -> Tuple[Optional[Decimal], OracleSourceTier]:
        """Extract exact Celsius (`T`-group 0.1°C first, then body `TT/TD` 1°C fallback)."""
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
            mag_int = int(token[1:]) if token.startswith("M") else int(token)
            temp_c = Decimal(0) if mag_int == 0 else (Decimal(-mag_int) if token.startswith("M") else Decimal(mag_int))
            return temp_c, "AWC_METAR_BODY"
        return None, "MISSING"

    @classmethod
    def parse_report(
        cls,
        report: RawMetarReport,
        *,
        effective_causal_ts_utc: Optional[datetime] = None,
    ) -> ParsedMetarObservation:
        """Parse a `RawMetarReport` into exact `Decimal` Celsius, Fahrenheit, and settled int °F."""
        temp_c_dec, tier = cls.parse_temperature_c(report.raw_text)
        temp_f_dec = celsius_to_fahrenheit_exact(temp_c_dec) if temp_c_dec is not None else None
        temp_f_int = settle_round_pos_inf(temp_f_dec) if temp_f_dec is not None else None
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
    """Compute Polymarket revision lock point (earlier of next-day routine METAR or 11:59 PM ET)."""
    _, settle_close_utc = compute_local_day_window_utc(target_date, station_tz)
    et_deadline_utc = _et_lock_deadline_utc(target_date)

    if causal_lock_candidates_utc is not None:
        candidates = [
            ensure_utc_datetime(ts, field_name="causal_lock_candidates_utc")
            for ts in causal_lock_candidates_utc
        ]
    else:
        candidates = [
            (rep.dispatch_ts_utc if rep.dispatch_ts_utc is not None else rep.obs_ts_utc)
            for rep in reports
            if rep.report_type == "METAR" and rep.obs_ts_utc >= settle_close_utc
        ]
    return min(candidates + [et_deadline_utc])


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

    @staticmethod
    def _build_query_params(
        code: str, start: datetime, end: datetime, now_utc: datetime
    ) -> Dict[str, Any]:
        if end <= now_utc:
            window_hours = max(1, int(((end - start).total_seconds() + 3599) // 3600) + 1)
            return {
                "ids": code,
                "format": "json",
                "date": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "hours": window_hours,
            }
        hours_back = max(1, int(((now_utc - start).total_seconds() + 3599) // 3600) + 1)
        return {"ids": code, "format": "json", "hours": hours_back}

    @staticmethod
    def _parse_awc_item(
        code: str, idx: int, item: Any, start: datetime, end: datetime
    ) -> Optional[RawMetarReport]:
        if not isinstance(item, Mapping):
            return None
        if str(item.get("icaoId") or code).strip().upper() != code:
            return None
        raw_ob = str(item.get("rawOb") or "").strip()
        obs_raw = item.get("obsTime") if item.get("obsTime") is not None else item.get("reportTime")
        if not raw_ob or obs_raw is None:
            return None
        obs_ts = parse_utc_timestamp(obs_raw, field_name="obsTime", assume_naive_utc=True)
        if not (start <= obs_ts < end):
            return None

        # Never fabricate a synthetic 0s lag or now_utc if receiptTime is missing (v0.3 §5 #1).
        receipt_raw = item.get("receiptTime")
        dispatch_ts = (
            parse_utc_timestamp(receipt_raw, field_name="receiptTime", assume_naive_utc=True)
            if receipt_raw is not None
            else None
        )
        metar_type = item.get("metarType")
        return RawMetarReport(
            station_id=code,
            obs_ts_utc=obs_ts,
            dispatch_ts_utc=dispatch_ts,
            report_type=classify_report_type(raw_ob, str(metar_type) if metar_type is not None else None),
            is_cor=detect_cor_flag(raw_ob),
            raw_text=raw_ob,
            source_channel="AWC_LIVE",
            sequence_hint=idx,
        )

    def fetch_window(
        self, station_id: str, start_utc: datetime, end_utc: datetime
    ) -> Tuple[RawMetarReport, ...]:
        start = ensure_utc_datetime(start_utc, field_name="start_utc")
        end = ensure_utc_datetime(end_utc, field_name="end_utc")
        if end <= start:
            raise ValueError("end_utc must be strictly greater than start_utc")
        code = station_id.strip().upper()
        now_utc = ensure_utc_datetime(self._clock_utc(), field_name="clock_utc")
        payload = self._http_get(
            self.BASE_URL, self._build_query_params(code, start, end, now_utc), self._timeout_sec
        )
        if not payload:
            return ()
        reports = [
            rep
            for idx, item in enumerate(payload)
            if (rep := self._parse_awc_item(code, idx, item, start, end)) is not None
        ]
        return tuple(reports)


class _BufferedMetarAdapter:
    """Shared read-only window slicer and mapping parser for replay & shadow adapters."""

    source_mode: str = "BUFFERED"

    def __init__(self, reports: Iterable[RawMetarReport]) -> None:
        validated: List[RawMetarReport] = []
        for rep in reports:
            _assert_not_forbidden_intraday_channel(rep.source_channel)
            validated.append(rep)
        self._reports: Tuple[RawMetarReport, ...] = tuple(validated)

    @staticmethod
    def _report_from_mapping(
        row: Mapping[str, Any], *, idx: int, default_channel: str
    ) -> RawMetarReport:
        channel = str(row.get("source_channel", default_channel))
        _assert_not_forbidden_intraday_channel(channel)
        dispatch_val = row.get("dispatch_ts_utc")
        raw_text = str(row["raw_text"])
        return RawMetarReport(
            station_id=str(row["station_id"]),
            obs_ts_utc=parse_utc_timestamp(row["obs_ts_utc"], field_name="obs_ts_utc"),
            dispatch_ts_utc=(
                parse_utc_timestamp(dispatch_val, field_name="dispatch_ts_utc")
                if dispatch_val is not None
                else None
            ),
            report_type=classify_report_type(raw_text, row.get("report_type")),
            is_cor=bool(row.get("is_cor", False)),
            raw_text=raw_text,
            source_channel=channel,
            sequence_hint=int(row.get("sequence_hint", idx)),
        )

    def fetch_window(
        self, station_id: str, start_utc: datetime, end_utc: datetime
    ) -> Tuple[RawMetarReport, ...]:
        start = ensure_utc_datetime(start_utc, field_name="start_utc")
        end = ensure_utc_datetime(end_utc, field_name="end_utc")
        if end <= start:
            raise ValueError("end_utc must be strictly greater than start_utc")
        code = station_id.strip().upper()
        return tuple(
            r for r in self._reports if r.station_id == code and start <= r.obs_ts_utc < end
        )


class PaperReplayMetarAdapter(_BufferedMetarAdapter):
    """Read-only adapter over recorded in-memory or JSONL METAR/SPECI frames for paper replay."""

    source_mode: str = "PAPER_REPLAY"

    @classmethod
    def from_jsonl(cls, path: Path) -> "PaperReplayMetarAdapter":
        loaded: List[RawMetarReport] = []
        with Path(path).open("r", encoding="utf-8") as fh:
            for idx, line in enumerate(fh):
                if stripped := line.strip():
                    loaded.append(
                        cls._report_from_mapping(
                            json.loads(stripped), idx=idx, default_channel="PAPER_REPLAY"
                        )
                    )
        return cls(loaded)


class HistoricalShadowMetarAdapter(_BufferedMetarAdapter):
    """Read-only adapter for historical shadow verification preserving missing `dispatch_ts_utc`."""

    source_mode: str = "HISTORICAL_SHADOW"

    def __init__(self, rows: Iterable[Mapping[str, Any]]) -> None:
        super().__init__(
            self._report_from_mapping(row, idx=idx, default_channel="HISTORICAL_SHADOW")
            for idx, row in enumerate(rows)
        )


@dataclass(frozen=True)
class _ComputedExtremaMetrics:
    m_now_exact_f: Optional[Decimal]
    m_now_int_f: Optional[int]
    m_now_min_exact_f: Optional[Decimal]
    m_now_min_int_f: Optional[int]
    oracle_source_tier: OracleSourceTier
    latest_obs_utc: Optional[datetime]
    latest_dispatch_ts_utc: Optional[datetime]
    latest_instant_temp_f: Optional[Decimal]
    physical_age_sec: Optional[float]
    dispatch_age_sec: Optional[float]
    dispatch_age_available: bool
    freshness_ok: bool


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
        self, *, station_id: str, target_date: date, as_of_ts_utc: datetime,
        session_id: str, execution_mode: ExecutionMode, model_hash: str, config_hash: str,
        gfs_init_utc: Optional[str] = None, gfs_available: bool = False,
        gfs_completeness_ratio: float = 0.0, apply_post_close_settlement_lock: bool = True,
    ) -> DualStreamEvaluation:
        """Evaluate causal prefix up to `as_of_ts_utc` for `(station_id, target_date)`."""
        as_of = ensure_utc_datetime(as_of_ts_utc, field_name="as_of_ts_utc")
        code = station_id.strip().upper()
        station_tz = resolve_station_timezone(code, self._station_timezones)
        day_start_utc, settle_close_utc = compute_local_day_window_utc(target_date, station_tz)
        day_reps, next_reps = self._fetch_and_partition_windows(
            code, target_date, as_of, day_start_utc, settle_close_utc, apply_post_close_settlement_lock
        )
        lock_ts = self._resolve_post_close_lock(
            target_date, station_tz, as_of, settle_close_utc, next_reps, apply_post_close_settlement_lock
        )
        gap_flags: List[str] = []
        archival, by_obs, specis = self._collect_causal_observations(day_reps, as_of, lock_ts, gap_flags)
        accepted, cor_cnt = self._deduplicate_routine_reports(by_obs, gap_flags)
        valid = [o for o in accepted if o.temp_f_dec is not None and o.temp_f_int is not None]
        metrics = self._compute_extrema_and_ages(valid, as_of, gap_flags)
        flags = tuple(dict.fromkeys(gap_flags))
        state = self._assemble_station_day_state(
            code, target_date, station_tz, day_start_utc, settle_close_utc,
            as_of, metrics, len(valid), cor_cnt, specis, flags,
        )
        ledger = self._assemble_coverage_ledger(
            code, target_date, as_of, session_id, execution_mode, model_hash, config_hash,
            gfs_init_utc, gfs_available, gfs_completeness_ratio, metrics, len(valid), specis, flags,
        )
        arch_sorted = tuple(sorted(
            archival, key=lambda o: (o.obs_ts_utc, o.effective_causal_ts_utc or o.obs_ts_utc, o.sequence_hint)
        ))
        return DualStreamEvaluation(state, tuple(accepted), arch_sorted, ledger)

    def _fetch_and_partition_windows(
        self,
        code: str,
        target_date: date,
        as_of: datetime,
        day_start_utc: datetime,
        settle_close_utc: datetime,
        apply_post_close_settlement_lock: bool,
    ) -> Tuple[List[RawMetarReport], List[RawMetarReport]]:
        et_deadline_utc = _et_lock_deadline_utc(target_date)
        fetch_end_utc = (
            max(settle_close_utc, min(as_of + timedelta(seconds=1), et_deadline_utc + timedelta(seconds=1)))
            if apply_post_close_settlement_lock and as_of >= settle_close_utc
            else settle_close_utc
        )
        day_reports: List[RawMetarReport] = []
        next_day_reports: List[RawMetarReport] = []
        for rep in self._source.fetch_window(code, day_start_utc, fetch_end_utc):
            _assert_not_forbidden_intraday_channel(rep.source_channel)
            if rep.station_id != code:
                continue
            if day_start_utc <= rep.obs_ts_utc < settle_close_utc:
                day_reports.append(rep)
            elif rep.obs_ts_utc >= settle_close_utc:
                next_day_reports.append(rep)
        return day_reports, next_day_reports

    def _resolve_post_close_lock(
        self,
        target_date: date,
        station_tz: ZoneInfo,
        as_of: datetime,
        settle_close_utc: datetime,
        next_day_reports: Sequence[RawMetarReport],
        apply_post_close_settlement_lock: bool,
    ) -> Optional[datetime]:
        if not apply_post_close_settlement_lock or as_of < settle_close_utc:
            return None
        causal_next: List[RawMetarReport] = []
        causal_lock_ts: List[datetime] = []
        for rep in next_day_reports:
            eff_ts = self._resolve_causal_ts(rep, as_of, gap_flags_out=None)
            if eff_ts is not None:
                causal_next.append(rep)
                if rep.report_type == "METAR":
                    causal_lock_ts.append(eff_ts)
        return compute_settlement_lock_ts_utc(
            target_date, station_tz, causal_next, causal_lock_candidates_utc=causal_lock_ts
        )

    def _collect_causal_observations(
        self,
        day_reports: Sequence[RawMetarReport],
        as_of: datetime,
        lock_ts_utc: Optional[datetime],
        gap_flags: List[str],
    ) -> Tuple[List[ParsedMetarObservation], Dict[datetime, List[ParsedMetarObservation]], int]:
        archival_obs: List[ParsedMetarObservation] = []
        routine_by_obs_ts: Dict[datetime, List[ParsedMetarObservation]] = {}
        specis_seen = 0
        for rep in day_reports:
            eff_ts = self._resolve_causal_ts(rep, as_of, gap_flags_out=gap_flags)
            if eff_ts is None:
                continue
            parsed = SettlementIsomorphicParser.parse_report(rep, effective_causal_ts_utc=eff_ts)
            archival_obs.append(parsed)
            if parsed.report_type == "SPECI":
                specis_seen += 1
                continue
            if lock_ts_utc is not None and parsed.is_cor and eff_ts > lock_ts_utc:
                if "POST_LOCK_COR_IGNORED" not in gap_flags:
                    gap_flags.append("POST_LOCK_COR_IGNORED")
                continue
            routine_by_obs_ts.setdefault(parsed.obs_ts_utc, []).append(parsed)
        return archival_obs, routine_by_obs_ts, specis_seen

    @staticmethod
    def _deduplicate_routine_reports(
        routine_by_obs_ts: Mapping[datetime, Sequence[ParsedMetarObservation]],
        gap_flags: List[str],
    ) -> Tuple[List[ParsedMetarObservation], int]:
        accepted: List[ParsedMetarObservation] = []
        cor_overwrites = 0
        for obs_ts in sorted(routine_by_obs_ts.keys()):
            ordered = sorted(
                routine_by_obs_ts[obs_ts],
                key=lambda o: (1 if o.is_cor else 0, o.effective_causal_ts_utc or o.obs_ts_utc, o.sequence_hint),
            )
            winner = ordered[-1]
            if winner.is_cor and len(ordered) > 1:
                cor_overwrites += 1
            if winner.temp_f_dec is None:
                flag = "COR_UNPARSEABLE_TEMP" if winner.is_cor else "UNPARSEABLE_ROUTINE_TEMP"
                if flag not in gap_flags:
                    gap_flags.append(flag)
            accepted.append(winner)
        return accepted, cor_overwrites

    def _compute_extrema_and_ages(
        self,
        valid_routine: Sequence[ParsedMetarObservation],
        as_of: datetime,
        gap_flags: List[str],
    ) -> _ComputedExtremaMetrics:
        if not valid_routine:
            gap_flags.append("NO_ROUTINE_METAR_IN_DAY_WINDOW")
            return _ComputedExtremaMetrics(
                None, None, None, None, "MISSING", None, None, None, None, None, False, False
            )

        winning_max = max(
            valid_routine,
            key=lambda o: (o.temp_f_dec, 1 if o.oracle_source_tier == "AWC_METAR_TGROUP" else 0, -o.obs_ts_utc.timestamp()),  # type: ignore[arg-type]
        )
        winning_min = min(
            valid_routine,
            key=lambda o: (o.temp_f_dec, o.obs_ts_utc.timestamp()),  # type: ignore[arg-type]
        )
        m_max_dec, m_min_dec = winning_max.temp_f_dec, winning_min.temp_f_dec
        assert m_max_dec is not None and m_min_dec is not None
        m_max_int = settle_round_pos_inf(m_max_dec)
        m_min_int = settle_round_pos_inf(m_min_dec)
        if m_max_int != max(o.temp_f_int for o in valid_routine if o.temp_f_int is not None):
            raise AssertionError("max/floor commutation violated")
        if m_min_int != min(o.temp_f_int for o in valid_routine if o.temp_f_int is not None):
            raise AssertionError("min/floor commutation violated")

        latest = max(valid_routine, key=lambda o: (o.obs_ts_utc, o.effective_causal_ts_utc or o.obs_ts_utc))
        phys_age, disp_age, disp_avail, fresh_ok = self._evaluate_observation_ages(
            latest.obs_ts_utc, latest.dispatch_ts_utc, as_of, gap_flags
        )
        return _ComputedExtremaMetrics(
            m_max_dec, m_max_int, m_min_dec, m_min_int, winning_max.oracle_source_tier,
            latest.obs_ts_utc, latest.dispatch_ts_utc, latest.temp_f_dec,
            phys_age, disp_age, disp_avail, fresh_ok,
        )

    def _evaluate_observation_ages(
        self,
        latest_obs_utc: datetime,
        latest_dispatch_utc: Optional[datetime],
        as_of: datetime,
        gap_flags: List[str],
    ) -> Tuple[float, Optional[float], bool, bool]:
        physical_age = (as_of - latest_obs_utc).total_seconds()
        phys_ok = 0.0 <= physical_age <= self._freshness_policy.physical_age_limit_sec
        if not phys_ok:
            gap_flags.append("PHYSICAL_AGE_EXCEEDED")

        if latest_dispatch_utc is None:
            disp_ok = not self._freshness_policy.require_dispatch_age
            if not disp_ok:
                gap_flags.append("DISPATCH_AGE_UNAVAILABLE")
            return physical_age, None, False, bool(phys_ok and disp_ok)

        dispatch_age = (as_of - latest_dispatch_utc).total_seconds()
        limit = self._freshness_policy.dispatch_age_limit_sec
        disp_ok = dispatch_age >= 0.0 if limit is None else (0.0 <= dispatch_age <= limit)
        if not disp_ok:
            gap_flags.append("DISPATCH_AGE_EXCEEDED")
        return physical_age, dispatch_age, True, bool(phys_ok and disp_ok)

    def _assemble_station_day_state(
        self, code: str, target_date: date, station_tz: ZoneInfo, day_start_utc: datetime,
        settle_close_utc: datetime, as_of: datetime, metrics: _ComputedExtremaMetrics,
        routine_count: int, cor_overwrites: int, specis_seen: int, dedup_flags: Tuple[str, ...],
    ) -> StationDayState:
        state_key = "|".join([
            code, target_date.isoformat(), as_of.isoformat(),
            metrics.latest_obs_utc.isoformat() if metrics.latest_obs_utc is not None else "NONE",
            str(metrics.m_now_exact_f) if metrics.m_now_exact_f is not None else "NONE",
            "ORACLE_COMPLIANT",
        ])
        return StationDayState(
            schema_version="p11.v1",
            state_id=str(uuid.uuid5(_STATE_ID_NAMESPACE, state_key)),
            as_of_ts_utc=as_of,
            station_id=code,
            station_timezone=str(station_tz.key),
            target_date=target_date,
            day_start_utc=day_start_utc,
            settle_close_utc=settle_close_utc,
            m_now_exact_f=metrics.m_now_exact_f,
            m_now_int_f=metrics.m_now_int_f,
            m_now_min_exact_f=metrics.m_now_min_exact_f,
            m_now_min_int_f=metrics.m_now_min_int_f,
            oracle_compliant=True,
            oracle_source_tier=metrics.oracle_source_tier,
            latest_obs_utc=metrics.latest_obs_utc,
            latest_dispatch_ts_utc=metrics.latest_dispatch_ts_utc,
            latest_instant_temp_f=metrics.latest_instant_temp_f,
            physical_age_sec=metrics.physical_age_sec,
            dispatch_age_sec=metrics.dispatch_age_sec,
            dispatch_age_available=metrics.dispatch_age_available,
            freshness_ok=metrics.freshness_ok,
            freshness_policy_provenance=self._freshness_policy.provenance,
            routine_obs_count=routine_count,
            cor_overwrites_count=cor_overwrites,
            specis_seen_count=specis_seen,
            gap_flags=dedup_flags,
        )

    def _assemble_coverage_ledger(
        self,
        code: str,
        target_date: date,
        as_of: datetime,
        session_id: str,
        execution_mode: ExecutionMode,
        model_hash: str,
        config_hash: str,
        gfs_init_utc: Optional[str],
        gfs_available: bool,
        gfs_completeness_ratio: float,
        metrics: _ComputedExtremaMetrics,
        routine_count: int,
        specis_seen: int,
        dedup_flags: Tuple[str, ...],
    ) -> CoverageLedgerEntry:
        return CoverageLedgerEntry(
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
            metar_obs_count_window=routine_count,
            specis_seen_count=specis_seen,
            latest_obs_utc=metrics.latest_obs_utc.isoformat() if metrics.latest_obs_utc is not None else None,
            physical_age_sec=metrics.physical_age_sec,
            dispatch_age_sec=metrics.dispatch_age_sec,
            dispatch_age_available=metrics.dispatch_age_available,
            freshness_ok=metrics.freshness_ok,
            gap_flags=dedup_flags,
            model_hash=model_hash,
            config_hash=config_hash,
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
            return report.dispatch_ts_utc if report.dispatch_ts_utc <= as_of_ts_utc else None
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


def _is_visible_oracle_routine(
    rep: RawMetarReport, code: str, as_of: Optional[datetime]
) -> bool:
    if rep.station_id != code or rep.report_type == "SPECI":
        return False
    if rep.raw_text.lstrip().upper().startswith("SPECI"):
        return False
    if as_of is None:
        return True
    return (
        rep.obs_ts_utc <= as_of
        and rep.dispatch_ts_utc is not None
        and rep.dispatch_ts_utc <= as_of
    )


def extract_settlement_reference_int(
    *,
    station_id: str,
    target_date: date,
    reports: Sequence[RawMetarReport],
    as_of_ts_utc: Optional[datetime] = None,
    station_timezones: Optional[Mapping[str, str]] = None,
) -> Optional[int]:
    """Independent reference settlement extractor implementing Polymarket contract wording directly."""
    code = station_id.strip().upper()
    tz = resolve_station_timezone(code, station_timezones)
    day_start_utc, settle_close_utc = compute_local_day_window_utc(target_date, tz)
    as_of = ensure_utc_datetime(as_of_ts_utc, field_name="as_of_ts_utc") if as_of_ts_utc is not None else None

    next_day_visible = [
        r for r in reports
        if r.obs_ts_utc >= settle_close_utc and _is_visible_oracle_routine(r, code, as_of)
    ]
    lock_ts = (
        compute_settlement_lock_ts_utc(target_date, tz, next_day_visible)
        if as_of is None or as_of >= settle_close_utc
        else None
    )

    by_obs_ts: Dict[datetime, List[RawMetarReport]] = {}
    for rep in reports:
        if not (day_start_utc <= rep.obs_ts_utc < settle_close_utc):
            continue
        if not _is_visible_oracle_routine(rep, code, as_of):
            continue
        eff_ts = rep.dispatch_ts_utc if rep.dispatch_ts_utc is not None else rep.obs_ts_utc
        if lock_ts is not None and rep.is_cor and eff_ts > lock_ts:
            continue
        by_obs_ts.setdefault(rep.obs_ts_utc, []).append(rep)

    rounded_temps: List[int] = []
    for group in by_obs_ts.values():
        winner = sorted(
            group,
            key=lambda r: (1 if r.is_cor else 0, r.dispatch_ts_utc or r.obs_ts_utc, r.sequence_hint),
        )[-1]
        temp_c, _ = SettlementIsomorphicParser.parse_temperature_c(winner.raw_text)
        if temp_c is not None:
            rounded_temps.append(settle_round_pos_inf(celsius_to_fahrenheit_exact(temp_c)))
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
