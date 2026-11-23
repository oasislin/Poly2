"""M9 (`S3-09`) Official Polymarket Settlement Oracle (`P9`), WU Fallback & `P15` Release.

Anchors:
- `ADR-0012 §5` (`~2026-10-23` active contract rule):
  1. Primary: AWC routine `METAR` (`T`-group `0.1°C` -> `TT/TD` body `1°C`);
  2. Strict `SPECI` exclusion (`report_type == "SPECI"` or `SPECI` prefix ignored);
  3. Station local `ZoneInfo` calendar day `[00:00, 24:00)` preserving 23h/25h DST windows;
  4. Half-degree `.5` rounded toward `+infinity` (`floor(x + 0.5)`);
  5. Revisions allowed only until earlier of next-day routine METAR or next-day `11:59 PM ET`;
  6. Post-close Weather Underground Daily Observations fallback allowed ONLY after `11:59 PM ET`
     next day when 0 qualifying routine METARs exist; if both missing -> lowest bin fallback.
- `ADR-0012 D5`: zero dependency on `src/legacy/wunderground/`.
- `项目方案 v3.0 §8.2 P9` & `P8-T2-M7-LOGGING §2.7`: formal `P9SettlementTruthRecord` (`p9.v1`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from typing import Any, Dict, List, Literal, Mapping, Optional, Protocol, Sequence, Tuple
import uuid
from zoneinfo import ZoneInfo

from src.audit.audit_logger import AsyncAuditLogger
from src.audit.p19_events import ExecutionMode
from src.bankroll.manager import BankrollAccountManager
from src.bankroll.models import P15SettlementEvent
from src.data_acquisition.settlement_metar_stream import (
    RawMetarReport,
    SettlementIsomorphicParser,
    celsius_to_fahrenheit_exact,
    compute_local_day_window_utc,
    compute_settlement_lock_ts_utc,
    resolve_station_timezone,
    settle_round_pos_inf,
)
from src.utils.causal_utils import compute_record_sha256, ensure_utc_datetime
from src.utils.decimal_guard import to_guarded_decimal

TargetType = Literal["TMAX", "TMIN"]
P9OracleSource = Literal["AWC_ROUTINE_METAR", "WU_FALLBACK_DAILY", "LOWEST_BIN_FALLBACK"]
P9OracleSourceTier = Literal[
    "AWC_METAR_TGROUP",
    "AWC_METAR_BODY",
    "WU_DAILY_OBSERVATIONS",
    "LOWEST_BIN_FALLBACK",
]

_P9_NAMESPACE = uuid.UUID("c4b1e8a2-9f40-4d8e-b711-202611230309")
_US_EASTERN_TZ = ZoneInfo("America/New_York")


class SettlementPendingError(RuntimeError):
    """Raised when market day has 0 routine METARs and next-day `11:59 PM ET` has not elapsed."""


@dataclass(frozen=True)
class SettlementBinSpec:
    """Integer closed-endpoint discrete temperature bin (`lower_int_f .. upper_int_f`)."""

    bin_id: str
    lower_int_f: Optional[int]
    upper_int_f: Optional[int]

    def matches(self, temp_int_f: int) -> bool:
        lo_ok = self.lower_int_f is None or temp_int_f >= self.lower_int_f
        hi_ok = self.upper_int_f is None or temp_int_f <= self.upper_int_f
        return lo_ok and hi_ok


@dataclass(frozen=True)
class WuDailySummary:
    """Weather Underground Daily Observations fallback summary (consumed only post 11:59 PM ET)."""

    station_id: str
    target_date: date
    temp_max_f: Optional[Decimal]
    temp_min_f: Optional[Decimal]
    source_url: str


class WeatherUndergroundFallbackPort(Protocol):
    """Read-only post-deadline WU Daily Observations port (isolated from `src/legacy/wunderground/`)."""

    def fetch_daily(self, station_id: str, target_date: date) -> Optional[WuDailySummary]:
        """Return daily summary for `(station_id, target_date)` or `None` if unavailable."""
        ...


@dataclass(frozen=True)
class MarketPositionClaim:
    """Settled open position claim handed to `M9` for binary payout calculation & `P15` release."""

    market_id: str
    bin_id: str
    held_shares: Decimal
    cost_basis_usd: Optional[Decimal] = None


@dataclass(frozen=True)
class P9SettlementTruthRecord:
    """Canonical `P9 SettlementTruthRecord v1.0` (`M9 -> M7 / M8`, `schema_version='p9.v1'`)."""

    schema_version: str
    settlement_id: str
    settled_ts_utc: datetime
    session_id: str
    execution_mode: ExecutionMode
    station_id: str
    station_timezone: str
    target_date: str
    target_type: TargetType
    market_id: str
    winning_bin_id: Optional[str]
    oracle_source: P9OracleSource
    oracle_source_tier: P9OracleSourceTier
    day_start_utc: datetime
    settle_close_utc: datetime
    revision_lock_ts_utc: datetime
    qualifying_obs_count: int
    speci_excluded_count: int
    cor_included_count: int
    post_lock_cor_ignored_count: int
    settled_temp_f_exact: Optional[Decimal]
    settled_temp_f_int: Optional[int]
    fallback_to_lowest_bin: bool
    wu_fallback_reason: Optional[str] = None

    def to_dict_without_hash(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "settlement_id": self.settlement_id,
            "settled_ts_utc": ensure_utc_datetime(
                self.settled_ts_utc, field_name="p9.settled_ts_utc"
            ).isoformat(),
            "session_id": self.session_id,
            "execution_mode": self.execution_mode,
            "station_id": self.station_id,
            "station_timezone": self.station_timezone,
            "target_date": self.target_date,
            "target_type": self.target_type,
            "market_id": self.market_id,
            "winning_bin_id": self.winning_bin_id,
            "oracle_source": self.oracle_source,
            "oracle_source_tier": self.oracle_source_tier,
            "day_start_utc": ensure_utc_datetime(
                self.day_start_utc, field_name="p9.day_start_utc"
            ).isoformat(),
            "settle_close_utc": ensure_utc_datetime(
                self.settle_close_utc, field_name="p9.settle_close_utc"
            ).isoformat(),
            "revision_lock_ts_utc": ensure_utc_datetime(
                self.revision_lock_ts_utc, field_name="p9.revision_lock_ts_utc"
            ).isoformat(),
            "qualifying_obs_count": int(self.qualifying_obs_count),
            "speci_excluded_count": int(self.speci_excluded_count),
            "cor_included_count": int(self.cor_included_count),
            "post_lock_cor_ignored_count": int(self.post_lock_cor_ignored_count),
            "settled_temp_f_exact": (
                str(self.settled_temp_f_exact) if self.settled_temp_f_exact is not None else None
            ),
            "settled_temp_f_int": self.settled_temp_f_int,
            "fallback_to_lowest_bin": bool(self.fallback_to_lowest_bin),
            "wu_fallback_reason": self.wu_fallback_reason,
        }

    def to_json_line(self) -> str:
        payload = self.to_dict_without_hash()
        payload["record_sha256"] = compute_record_sha256(payload)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class P15ReleaseOutcome:
    """Combined `P9` truth + `P15` bankroll release receipt."""

    p9_record: P9SettlementTruthRecord
    p15_event: P15SettlementEvent
    realized_pnl_usd: Decimal


def next_day_et_deadline_utc(target_date: date) -> datetime:
    """Return `(target_date + 1d) 23:59:00 America/New_York -> UTC` per `ADR-0012 §5`."""
    next_d = date.fromordinal(target_date.toordinal() + 1)
    return datetime(next_d.year, next_d.month, next_d.day, 23, 59, 0, tzinfo=_US_EASTERN_TZ).astimezone(
        timezone.utc
    )


def resolve_winning_bin(
    *,
    settled_temp_f_int: Optional[int],
    bins: Sequence[SettlementBinSpec],
    fallback_to_lowest_bin: bool,
) -> Optional[str]:
    """Match winning bin by integer closed endpoints or return lowest bin on fallback."""
    if not bins:
        return None
    if fallback_to_lowest_bin or settled_temp_f_int is None:
        ordered = sorted(bins, key=lambda b: float("-inf") if b.lower_int_f is None else float(b.lower_int_f))
        return ordered[0].bin_id
    for b in bins:
        if b.matches(settled_temp_f_int):
            return b.bin_id
    return None


@dataclass(frozen=True)
class _MetarDayScan:
    winners: Tuple[RawMetarReport, ...]
    speci_excluded: int
    cor_included: int
    post_lock_cor_ignored: int
    lock_ts_utc: datetime


def _scan_routine_metars_for_day(
    *,
    station_id: str,
    target_date: date,
    tz: ZoneInfo,
    day_start_utc: datetime,
    settle_close_utc: datetime,
    reports: Sequence[RawMetarReport],
) -> _MetarDayScan:
    code = station_id.strip().upper()
    station_reports = [r for r in reports if r.station_id == code]
    next_day_routine = [
        r
        for r in station_reports
        if r.obs_ts_utc >= settle_close_utc
        and r.report_type != "SPECI"
        and not r.raw_text.lstrip().upper().startswith("SPECI")
    ]
    lock_ts = compute_settlement_lock_ts_utc(target_date, tz, next_day_routine)

    speci_excluded = 0
    post_lock_cor_ignored = 0
    by_obs_ts: Dict[datetime, List[RawMetarReport]] = {}
    for rep in station_reports:
        if not (day_start_utc <= rep.obs_ts_utc < settle_close_utc):
            continue
        if rep.report_type == "SPECI" or rep.raw_text.lstrip().upper().startswith("SPECI"):
            speci_excluded += 1
            continue
        eff_ts = rep.dispatch_ts_utc if rep.dispatch_ts_utc is not None else rep.obs_ts_utc
        if rep.is_cor and eff_ts > lock_ts:
            post_lock_cor_ignored += 1
            continue
        by_obs_ts.setdefault(rep.obs_ts_utc, []).append(rep)

    winners: List[RawMetarReport] = []
    cor_included = 0
    for group in by_obs_ts.values():
        chosen = sorted(
            group,
            key=lambda r: (1 if r.is_cor else 0, r.dispatch_ts_utc or r.obs_ts_utc, r.sequence_hint),
        )[-1]
        if chosen.is_cor:
            cor_included += 1
        winners.append(chosen)
    return _MetarDayScan(
        winners=tuple(winners),
        speci_excluded=speci_excluded,
        cor_included=cor_included,
        post_lock_cor_ignored=post_lock_cor_ignored,
        lock_ts_utc=lock_ts,
    )


def _pick_extreme_observation(
    winners: Sequence[RawMetarReport],
    target_type: TargetType,
) -> Optional[Tuple[Decimal, int, P9OracleSourceTier]]:
    parsed: List[Tuple[Decimal, int, P9OracleSourceTier]] = []
    for rep in winners:
        temp_c, tier = SettlementIsomorphicParser.parse_temperature_c(rep.raw_text)
        if temp_c is None or tier == "MISSING":
            continue
        f_exact = celsius_to_fahrenheit_exact(temp_c)
        f_int = settle_round_pos_inf(f_exact)
        parsed.append((f_exact, f_int, tier))  # type: ignore[arg-type]
    if not parsed:
        return None
    chooser = max if target_type == "TMAX" else min
    return chooser(parsed, key=lambda item: item[0])


class M9SettlementEngine:
    """`M9` Official Settlement Engine emitting `P9` records and `P15` releases."""

    def __init__(
        self,
        *,
        wu_source: Optional[WeatherUndergroundFallbackPort] = None,
        audit_logger: Optional[AsyncAuditLogger] = None,
        station_timezones: Optional[Mapping[str, str]] = None,
    ) -> None:
        self._wu_source = wu_source
        self._audit_logger = audit_logger
        self._station_timezones = station_timezones

    def evaluate_settlement(
        self,
        *,
        session_id: str,
        execution_mode: ExecutionMode,
        station_id: str,
        target_date: date,
        target_type: TargetType,
        market_id: str,
        reports: Sequence[RawMetarReport],
        bins: Sequence[SettlementBinSpec],
        as_of_ts_utc: datetime,
    ) -> P9SettlementTruthRecord:
        code = station_id.strip().upper()
        as_of = ensure_utc_datetime(as_of_ts_utc, field_name="m9.as_of_ts_utc")
        tz = resolve_station_timezone(code, self._station_timezones)
        day_start_utc, settle_close_utc = compute_local_day_window_utc(target_date, tz)
        scan = _scan_routine_metars_for_day(
            station_id=code,
            target_date=target_date,
            tz=tz,
            day_start_utc=day_start_utc,
            settle_close_utc=settle_close_utc,
            reports=reports,
        )
        extreme = _pick_extreme_observation(scan.winners, target_type)
        sid = str(
            uuid.uuid5(_P9_NAMESPACE, f"{session_id}|{code}|{target_date.isoformat()}|{target_type}|{market_id}")
        )
        if extreme is not None:
            f_exact, f_int, tier = extreme
            win_bin = resolve_winning_bin(settled_temp_f_int=f_int, bins=bins, fallback_to_lowest_bin=False)
            return P9SettlementTruthRecord(
                schema_version="p9.v1",
                settlement_id=sid,
                settled_ts_utc=as_of,
                session_id=session_id,
                execution_mode=execution_mode,
                station_id=code,
                station_timezone=str(tz),
                target_date=target_date.isoformat(),
                target_type=target_type,
                market_id=market_id,
                winning_bin_id=win_bin,
                oracle_source="AWC_ROUTINE_METAR",
                oracle_source_tier=tier,
                day_start_utc=day_start_utc,
                settle_close_utc=settle_close_utc,
                revision_lock_ts_utc=scan.lock_ts_utc,
                qualifying_obs_count=len(scan.winners),
                speci_excluded_count=scan.speci_excluded,
                cor_included_count=scan.cor_included,
                post_lock_cor_ignored_count=scan.post_lock_cor_ignored,
                settled_temp_f_exact=f_exact,
                settled_temp_f_int=f_int,
                fallback_to_lowest_bin=False,
            )

        et_deadline = next_day_et_deadline_utc(target_date)
        if as_of < et_deadline:
            raise SettlementPendingError(
                f"No qualifying routine METAR for {code} {target_date}; WU fallback barred until 11:59 PM ET ({et_deadline.isoformat()})"
            )
        return self._evaluate_post_deadline_fallback(
            sid=sid,
            as_of=as_of,
            session_id=session_id,
            execution_mode=execution_mode,
            code=code,
            tz=tz,
            target_date=target_date,
            target_type=target_type,
            market_id=market_id,
            day_start_utc=day_start_utc,
            settle_close_utc=settle_close_utc,
            scan=scan,
            bins=bins,
        )

    def _evaluate_post_deadline_fallback(
        self,
        *,
        sid: str,
        as_of: datetime,
        session_id: str,
        execution_mode: ExecutionMode,
        code: str,
        tz: ZoneInfo,
        target_date: date,
        target_type: TargetType,
        market_id: str,
        day_start_utc: datetime,
        settle_close_utc: datetime,
        scan: _MetarDayScan,
        bins: Sequence[SettlementBinSpec],
    ) -> P9SettlementTruthRecord:
        wu_summary = self._wu_source.fetch_daily(code, target_date) if self._wu_source is not None else None
        wu_temp = (
            (wu_summary.temp_max_f if target_type == "TMAX" else wu_summary.temp_min_f)
            if wu_summary is not None
            else None
        )
        if wu_summary is not None and wu_temp is not None:
            f_exact = to_guarded_decimal(wu_temp, name="wu.temp_f")
            f_int = settle_round_pos_inf(f_exact)
            win_bin = resolve_winning_bin(settled_temp_f_int=f_int, bins=bins, fallback_to_lowest_bin=False)
            return P9SettlementTruthRecord(
                schema_version="p9.v1",
                settlement_id=sid,
                settled_ts_utc=as_of,
                session_id=session_id,
                execution_mode=execution_mode,
                station_id=code,
                station_timezone=str(tz),
                target_date=target_date.isoformat(),
                target_type=target_type,
                market_id=market_id,
                winning_bin_id=win_bin,
                oracle_source="WU_FALLBACK_DAILY",
                oracle_source_tier="WU_DAILY_OBSERVATIONS",
                day_start_utc=day_start_utc,
                settle_close_utc=settle_close_utc,
                revision_lock_ts_utc=scan.lock_ts_utc,
                qualifying_obs_count=0,
                speci_excluded_count=scan.speci_excluded,
                cor_included_count=0,
                post_lock_cor_ignored_count=scan.post_lock_cor_ignored,
                settled_temp_f_exact=f_exact,
                settled_temp_f_int=f_int,
                fallback_to_lowest_bin=False,
                wu_fallback_reason=f"ZERO_AWC_METAR_AFTER_ET_LOCK:{wu_summary.source_url}",
            )

        low_bin = resolve_winning_bin(settled_temp_f_int=None, bins=bins, fallback_to_lowest_bin=True)
        return P9SettlementTruthRecord(
            schema_version="p9.v1",
            settlement_id=sid,
            settled_ts_utc=as_of,
            session_id=session_id,
            execution_mode=execution_mode,
            station_id=code,
            station_timezone=str(tz),
            target_date=target_date.isoformat(),
            target_type=target_type,
            market_id=market_id,
            winning_bin_id=low_bin,
            oracle_source="LOWEST_BIN_FALLBACK",
            oracle_source_tier="LOWEST_BIN_FALLBACK",
            day_start_utc=day_start_utc,
            settle_close_utc=settle_close_utc,
            revision_lock_ts_utc=scan.lock_ts_utc,
            qualifying_obs_count=0,
            speci_excluded_count=scan.speci_excluded,
            cor_included_count=0,
            post_lock_cor_ignored_count=scan.post_lock_cor_ignored,
            settled_temp_f_exact=None,
            settled_temp_f_int=None,
            fallback_to_lowest_bin=True,
            wu_fallback_reason="ZERO_AWC_AND_ZERO_WU_AFTER_ET_LOCK",
        )

    def settle_and_release_p15(
        self,
        *,
        session_id: str,
        execution_mode: ExecutionMode,
        station_id: str,
        target_date: date,
        target_type: TargetType,
        claim: MarketPositionClaim,
        reports: Sequence[RawMetarReport],
        bins: Sequence[SettlementBinSpec],
        bankroll: BankrollAccountManager,
        as_of_ts_utc: datetime,
    ) -> P15ReleaseOutcome:
        """Evaluate official `P9` truth, log to `M7`, and release `P15` payout into `M6`."""
        p9 = self.evaluate_settlement(
            session_id=session_id,
            execution_mode=execution_mode,
            station_id=station_id,
            target_date=target_date,
            target_type=target_type,
            market_id=claim.market_id,
            reports=reports,
            bins=bins,
            as_of_ts_utc=as_of_ts_utc,
        )
        if self._audit_logger is not None:
            self._audit_logger.log_p9_settlement_truth(p9)
        payout = claim.held_shares * Decimal("1") if claim.bin_id == p9.winning_bin_id else Decimal("0")
        p15 = P15SettlementEvent(
            settlement_id=p9.settlement_id,
            station_id=p9.station_id,
            market_id=claim.market_id,
            payout_usd=payout,
            settled_ts_utc=p9.settled_ts_utc,
            cost_basis_usd=claim.cost_basis_usd,
        )
        pnl = bankroll.apply_p15_settlement(p15)
        return P15ReleaseOutcome(p9_record=p9, p15_event=p15, realized_pnl_usd=pnl)
