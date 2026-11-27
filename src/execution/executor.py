"""M5 (S3-05) Executor: Decimal `P2 v1.1` PovSlicer & `P18` Conservative ReplayMatcher.

Anchors:
- `P8-T8-ALGO4-DESIGN v0.3 §4` (`ρ(edge)` via P2, Decimal domain, P18 R1/R2/R3, §0 fee)
- `P8-T4-M4M5-INTERFACE v1.0 §2.2–§2.4` (`SlicePlan` v1.1 Decimal alignment, `S1-06` fee rule)
- `P8-RECORDER-NO-SIDE-DESIGN v0.1 §2.2 & §3.2` (one-sided guards & split/merge cross-view)

Read-only consumer of `src/pricing/edge_math.py` (`F-2` locked zone remains zero-diff).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
import json
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple
import uuid

from src.data_acquisition.passive_book_recorder import (
    MarketBookRecordEnvelope,
    MarketBookSnapshot,
)
from src.execution.orderbook_views import (
    DualSideBookPair,
    LegSource,
    LeggedAskLevel,
    MergedYesAskView,
    build_merged_yes_ask_view,
    equivalent_complementary_price,
)
from src.pricing.edge_math import evaluate_book_edges
from src.utils.causal_utils import compute_record_sha256, ensure_utc_datetime
from src.utils.decimal_guard import (
    EXACT_DECIMAL_CONTEXT_PREC,
    exact_decimal_context,
    to_guarded_decimal,
)

ExecutionMode = Literal["PAPER", "LIVE"]
CaptureReplayMode = Literal["NONE", "REPLAY_P13"]
TerminalStatus = Literal[
    "FILLED",
    "PARTIAL",
    "CANCELLED_UNFILLED",
    "REJECTED",
    "PAPER_MATCH_ABORTED_GAP",
]
_FEE_QUANTUM = Decimal("0.00001")
_SHARES_QUANTUM = Decimal("0.01")


def _to_exec_decimal(
    value: Decimal | float | int | str,
    *,
    name: str,
) -> Decimal:
    """Convert floats (up to 18 sig digits) or Decimal/str into exact guarded Decimal."""
    digits = 18 if isinstance(value, float) else 12
    return to_guarded_decimal(value, name=name, max_sig_digits=digits)


@dataclass(frozen=True)
class TradingExecutionConfig:
    """Explicitly sourced execution & freshness parameters with zero bare literals (`v0.3 §3.2`)."""

    min_order_size_shares: Decimal
    min_order_size_shares_provenance: str
    min_notional_usd: Optional[Decimal]
    min_notional_usd_provenance: str
    forecast_age_limit_sec: float
    forecast_age_limit_sec_provenance: str
    max_book_staleness_sec: float
    max_book_staleness_sec_provenance: str
    pair_max_skew_sec: float
    pair_max_skew_sec_provenance: str
    latency_ms: int
    latency_ms_provenance: str
    heartbeat_timeout_sec: float
    heartbeat_timeout_sec_provenance: str
    rest_fallback_interval_sec: float
    rest_fallback_interval_sec_provenance: str
    enable_cross_side_split_routing: bool = False
    cross_side_split_routing_provenance: str = "P8-RECORDER-NO-SIDE-DESIGN v0.1 §3.2"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "min_order_size_shares",
            _to_exec_decimal(self.min_order_size_shares, name="min_order_size_shares"),
        )
        if self.min_order_size_shares <= Decimal("0"):
            raise ValueError("min_order_size_shares must be > 0")
        if self.min_notional_usd is not None:
            mn = _to_exec_decimal(self.min_notional_usd, name="min_notional_usd")
            if mn < Decimal("0"):
                raise ValueError("min_notional_usd must be >= 0")
            object.__setattr__(self, "min_notional_usd", mn)
        if self.forecast_age_limit_sec < 0.0 or self.max_book_staleness_sec < 0.0:
            raise ValueError("Age limits must be >= 0")
        if self.pair_max_skew_sec < 0.0 or self.latency_ms < 0:
            raise ValueError("pair_max_skew_sec and latency_ms must be >= 0")
        if self.heartbeat_timeout_sec <= 0.0 or self.rest_fallback_interval_sec < 0.0:
            raise ValueError("Invalid heartbeat_timeout_sec / rest_fallback_interval_sec")

    @property
    def max_silent_gap_sec(self) -> float:
        """Derived R3 window per `ALGO4 v0.3 §4.2`: heartbeat_timeout + rest_fallback_interval."""
        return float(self.heartbeat_timeout_sec) + float(self.rest_fallback_interval_sec)


@dataclass(frozen=True)
class PhiPolicy:
    """`M5` slice participation parameters matching `interface §3.4` (`w` excluded)."""

    rho_0: Decimal
    k_slope: Decimal
    rho_min: Decimal
    rho_max: Decimal
    order_type: Literal["IOC_FAK"] = "IOC_FAK"
    provenance: str = "P8-CAPITAL-CONFIG v1.0 §7"

    def __post_init__(self) -> None:
        r0 = to_guarded_decimal(self.rho_0, name="phi.rho_0")
        ks = to_guarded_decimal(self.k_slope, name="phi.k_slope")
        rmin = to_guarded_decimal(self.rho_min, name="phi.rho_min")
        rmax = to_guarded_decimal(self.rho_max, name="phi.rho_max")
        if not (Decimal("0") < rmin <= r0 <= rmax <= Decimal("1")):
            raise ValueError("PhiPolicy requires 0 < rho_min <= rho_0 <= rho_max <= 1")
        if ks < Decimal("0"):
            raise ValueError("PhiPolicy requires k_slope >= 0")
        object.__setattr__(self, "rho_0", r0)
        object.__setattr__(self, "k_slope", ks)
        object.__setattr__(self, "rho_min", rmin)
        object.__setattr__(self, "rho_max", rmax)


@dataclass(frozen=True)
class PlannedLegSlice:
    """Planned order allocation split by execution leg (`YES_ASK` vs `NO_BID_SPLIT_SELL`)."""

    leg_source: LegSource
    source_token_id: str
    implied_yes_price: Decimal
    raw_source_price: Decimal
    allocated_shares: Decimal
    allocated_usd: Decimal


@dataclass(frozen=True)
class SlicePlan:
    """`P2 plan_slice` output (`v1.1` aligned to exact `Decimal` domain per `v0.3 §4.1`)."""

    should_submit: bool
    target_usd: Decimal
    target_shares: Decimal
    limit_price: Decimal
    est_vwap: Decimal
    qual_depth_shares: Decimal
    order_type: Literal["IOC_FAK"]
    abort_reason: Optional[str] = None
    leg_allocations: Tuple[PlannedLegSlice, ...] = ()


@dataclass(frozen=True)
class FillLegRecord:
    """Single fill slice executed during conservative `P18` replay matching."""

    leg_source: LegSource
    source_token_id: str
    implied_yes_price: Decimal
    raw_source_price: Decimal
    filled_shares: Decimal
    fee_usd_raw: Decimal


@dataclass(frozen=True)
class ExecutionAttemptLog:
    """`P3 ExecutionAttemptLog` (`M5 -> M7`) aligned to `P8-T2-M7-LOGGING §2.2`."""

    schema_version: str
    attempt_id: str
    decision_id: str
    idempotency_key: str
    session_id: str
    execution_mode: ExecutionMode
    capture_replay_mode: CaptureReplayMode
    replay_source_seq_id: Optional[int]
    latency_injected_ms: Optional[int]
    station_id: str
    market_id: str
    token_id: str
    model_hash: str
    config_hash: str
    decision_ts_utc: datetime
    decision_best_ask: Decimal
    decision_est_vwap: Decimal
    decision_qual_depth_shares: Decimal
    order_type: Literal["IOC_FAK"]
    limit_price: Decimal
    target_shares: Decimal
    target_usd: Decimal
    submit_ts_utc: datetime
    final_ts_utc: datetime
    terminal_status: TerminalStatus
    reject_or_abort_reason: Optional[str]
    filled_shares: Decimal
    filled_usd: Decimal
    actual_avg_fill_price: Optional[Decimal]
    fee_paid_usd: Decimal
    fill_rate: Decimal
    slippage_vs_best_ask: Optional[Decimal]
    slippage_vs_est_vwap: Optional[Decimal]
    execution_legs: Tuple[FillLegRecord, ...] = ()

    def to_dict_without_hash(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "attempt_id": self.attempt_id,
            "decision_id": self.decision_id,
            "idempotency_key": self.idempotency_key,
            "session_id": self.session_id,
            "execution_mode": self.execution_mode,
            "capture_replay_mode": self.capture_replay_mode,
            "replay_source_seq_id": self.replay_source_seq_id,
            "latency_injected_ms": self.latency_injected_ms,
            "station_id": self.station_id,
            "market_id": self.market_id,
            "token_id": self.token_id,
            "model_hash": self.model_hash,
            "config_hash": self.config_hash,
            "decision_ts_utc": self.decision_ts_utc.isoformat(),
            "decision_best_ask": str(self.decision_best_ask),
            "decision_est_vwap": str(self.decision_est_vwap),
            "decision_qual_depth_shares": str(self.decision_qual_depth_shares),
            "order_type": self.order_type,
            "limit_price": str(self.limit_price),
            "target_shares": str(self.target_shares),
            "target_usd": str(self.target_usd),
            "submit_ts_utc": self.submit_ts_utc.isoformat(),
            "final_ts_utc": self.final_ts_utc.isoformat(),
            "terminal_status": self.terminal_status,
            "reject_or_abort_reason": self.reject_or_abort_reason,
            "filled_shares": str(self.filled_shares),
            "filled_usd": str(self.filled_usd),
            "actual_avg_fill_price": (
                str(self.actual_avg_fill_price) if self.actual_avg_fill_price is not None else None
            ),
            "fee_paid_usd": str(self.fee_paid_usd),
            "fill_rate": str(self.fill_rate),
            "slippage_vs_best_ask": (
                str(self.slippage_vs_best_ask) if self.slippage_vs_best_ask is not None else None
            ),
            "slippage_vs_est_vwap": (
                str(self.slippage_vs_est_vwap) if self.slippage_vs_est_vwap is not None else None
            ),
            "execution_legs": [
                {
                    "leg_source": leg.leg_source,
                    "source_token_id": leg.source_token_id,
                    "implied_yes_price": str(leg.implied_yes_price),
                    "raw_source_price": str(leg.raw_source_price),
                    "filled_shares": str(leg.filled_shares),
                }
                for leg in self.execution_legs
            ],
        }

    def to_json_line(self) -> str:
        payload = self.to_dict_without_hash()
        payload["record_sha256"] = compute_record_sha256(payload)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_taker_fee_usd_raw(
    shares: Decimal,
    trade_price: Decimal,
    fee_rate: Decimal,
) -> Decimal:
    """Polymarket official taker fee `shares * fee_rate * p * (1 - p)` in exact Decimal."""
    with exact_decimal_context(trap_inexact=True):
        s_d = to_guarded_decimal(shares, name="fee.shares")
        p_d = to_guarded_decimal(trade_price, name="fee.price")
        r_d = to_guarded_decimal(fee_rate, name="fee.rate")
        return s_d * r_d * p_d * (Decimal("1") - p_d)


def quantize_polymarket_fee_usd(raw_fee_total: Decimal) -> Decimal:
    """Round total USDC fee to 5 decimals (`0.00001` floor; smaller rounds to `0`)."""
    with exact_decimal_context():
        rounded = raw_fee_total.quantize(_FEE_QUANTUM, rounding=ROUND_HALF_UP)
        return Decimal("0.00000") if rounded < _FEE_QUANTUM else rounded


def align_price_down_to_tick(raw_price: Decimal, tick_size: Decimal) -> Decimal:
    """Align protection limit price downward to an exact multiple of `tick_size`."""
    with exact_decimal_context(trap_inexact=True):
        p_d = to_guarded_decimal(raw_price, name="limit.raw_price")
        t_d = to_guarded_decimal(tick_size, name="limit.tick_size")
        if t_d <= Decimal("0"):
            raise ValueError(f"tick_size must be > 0, got {t_d}")
        steps = (p_d / t_d).to_integral_value(rounding=ROUND_FLOOR)
        aligned = steps * t_d
        if aligned <= Decimal("0"):
            aligned = t_d
        return aligned


def compute_rho(edge: Decimal, m_threshold: Decimal, phi_policy: PhiPolicy) -> Decimal:
    """Compute edge-aware depth participation rate ρ(edge) per `P2 §2.2`."""
    with exact_decimal_context(trap_inexact=True):
        e_d = to_guarded_decimal(edge, name="rho.edge", max_sig_digits=18)
        m_d = to_guarded_decimal(m_threshold, name="rho.m_threshold", max_sig_digits=18)
        raw = phi_policy.rho_0 + phi_policy.k_slope * (e_d - m_d)
        return min(phi_policy.rho_max, max(phi_policy.rho_min, raw))


def _aborted_slice_plan(
    abort_reason: str,
    order_type: Literal["IOC_FAK"],
) -> SlicePlan:
    zero = Decimal("0")
    return SlicePlan(
        should_submit=False,
        target_usd=zero,
        target_shares=zero,
        limit_price=zero,
        est_vwap=zero,
        qual_depth_shares=zero,
        order_type=order_type,
        abort_reason=abort_reason,
    )


def _resolve_min_order_thresholds(
    ask_book_frame: MarketBookSnapshot | MergedYesAskView,
    min_order_size_shares: Optional[Decimal | float],
    min_notional_usd: Optional[Decimal | float],
) -> Tuple[Decimal, Optional[Decimal]]:
    if min_order_size_shares is not None:
        min_shares = _to_exec_decimal(min_order_size_shares, name="min_order_size_shares")
    else:
        raw_shares = ask_book_frame.min_order_size_shares if isinstance(ask_book_frame, MarketBookSnapshot) else 5.0
        min_shares = _to_exec_decimal(raw_shares, name="fallback_min_shares")

    if min_notional_usd is not None:
        min_notional: Optional[Decimal] = _to_exec_decimal(min_notional_usd, name="min_notional_usd")
    elif isinstance(ask_book_frame, MarketBookSnapshot) and ask_book_frame.min_notional_usd is not None:
        min_notional = _to_exec_decimal(ask_book_frame.min_notional_usd, name="frame_min_notional")
    else:
        min_notional = None
    return min_shares, min_notional


def _allocate_pov_legs(
    d_usd_dec: Decimal,
    qual_legs: Sequence[LeggedAskLevel],
    edge_by_price: Mapping[Decimal, Decimal],
    m_dec: Decimal,
    phi_policy: PhiPolicy,
) -> Tuple[List[PlannedLegSlice], Decimal, Decimal, Decimal, Decimal, Decimal]:
    qual_depth_shares = Decimal("0")
    leg_caps: List[Tuple[LeggedAskLevel, Decimal]] = []
    for leg in qual_legs:
        rho_j = compute_rho(edge_by_price[leg.implied_yes_price], m_dec, phi_policy)
        cap_shares = leg.size_shares * rho_j
        qual_depth_shares += leg.size_shares
        leg_caps.append((leg, cap_shares))

    allocated_legs: List[PlannedLegSlice] = []
    worst_hit_price = qual_legs[0].implied_yes_price
    tick_for_limit = qual_legs[0].tick_size
    total_shares, total_usd = Decimal("0"), Decimal("0")
    for leg, cap_shares in leg_caps:
        p = leg.implied_yes_price
        escrow_room_shares = (d_usd_dec / p) - total_shares
        if escrow_room_shares <= Decimal("0"):
            break
        take_shares = min(cap_shares, escrow_room_shares)
        if take_shares <= Decimal("0"):
            continue
        take_usd = take_shares * p
        allocated_legs.append(
            PlannedLegSlice(
                leg_source=leg.leg_source, source_token_id=leg.source_token_id,
                implied_yes_price=p, raw_source_price=leg.raw_source_price,
                allocated_shares=take_shares, allocated_usd=take_usd,
            )
        )
        total_shares += take_shares
        total_usd += take_usd
        worst_hit_price = max(worst_hit_price, p)
        tick_for_limit = min(tick_for_limit, leg.tick_size)
        if take_shares < cap_shares:
            break
    return allocated_legs, total_shares, total_usd, worst_hit_price, tick_for_limit, qual_depth_shares


def plan_slice(
    d_headroom_usd: Decimal | float,
    ask_book_frame: MarketBookSnapshot | MergedYesAskView,
    p_model: float,
    m_threshold: float,
    phi_policy: PhiPolicy,
    *,
    min_order_size_shares: Optional[Decimal | float] = None,
    min_notional_usd: Optional[Decimal | float] = None,
) -> SlicePlan:
    """`P2 plan_slice` (`M4 -> M5`, `v1.1` Decimal domain + `P4 v1.1` one-sided guard)."""
    view = (
        ask_book_frame
        if isinstance(ask_book_frame, MergedYesAskView)
        else build_merged_yes_ask_view(ask_book_frame, include_no_side=False)
    )
    if view.inverted_cross:
        return _aborted_slice_plan("INVERTED_BOOK", phi_policy.order_type)
    if view.ask_book is None or not view.legged_levels:
        return _aborted_slice_plan("NO_ASK_DEPTH", phi_policy.order_type)

    d_usd_dec = _to_exec_decimal(d_headroom_usd, name="d_headroom_usd")
    if d_usd_dec <= Decimal("0"):
        return _aborted_slice_plan("ZERO_HEADROOM", phi_policy.order_type)

    book_summary = evaluate_book_edges(
        ask_book=view.ask_book,
        p_model=float(p_model),
        m=float(m_threshold),
        fee_rate=float(view.legged_levels[0].fee_rate),
    )
    if not book_summary.qualified_levels:
        return _aborted_slice_plan("NO_QUALIFIED_LEVELS", phi_policy.order_type)

    max_qual = _to_exec_decimal(book_summary.qualified_levels[-1].price, name="max_qual_price")
    edge_by_price = {
        _to_exec_decimal(ql.price, name="ql.price"): _to_exec_decimal(ql.edge, name="ql.edge")
        for ql in book_summary.qualified_levels
    }
    m_dec = _to_exec_decimal(m_threshold, name="m_threshold")
    qual_legs = [lvl for lvl in view.legged_levels if lvl.implied_yes_price <= max_qual]

    with exact_decimal_context():
        legs, tot_sh, tot_usd, worst_p, tick_min, q_depth = _allocate_pov_legs(
            d_usd_dec, qual_legs, edge_by_price, m_dec, phi_policy
        )
        limit_dec = align_price_down_to_tick(worst_p, tick_min)
        target_sh = min(tot_sh, d_usd_dec / limit_dec).quantize(_SHARES_QUANTUM, rounding=ROUND_FLOOR)
        eff_usd = target_sh * limit_dec
        est_vwap = (tot_usd / tot_sh) if tot_sh > Decimal("0") else limit_dec
        est_expected_usd = target_sh * est_vwap

    min_sh, min_not = _resolve_min_order_thresholds(ask_book_frame, min_order_size_shares, min_notional_usd)
    below_min = target_sh < min_sh or (min_not is not None and (eff_usd < min_not or est_expected_usd < min_not))
    return SlicePlan(
        should_submit=not below_min,
        target_usd=eff_usd,
        target_shares=target_sh,
        limit_price=limit_dec,
        est_vwap=est_vwap,
        qual_depth_shares=q_depth,
        order_type=phi_policy.order_type,
        abort_reason="BELOW_MIN_ORDER" if below_min else None,
        leg_allocations=tuple(legs),
    )


@dataclass(frozen=True)
class OrderExecutionContext:
    """Bundled causal identity & replay context passed into `ReplayMatcher.match_order`."""

    decision_id: str
    session_id: str
    station_id: str
    market_id: str
    yes_token_id: str
    model_hash: str
    config_hash: str
    decision_ts_utc: datetime
    decision_best_ask: Decimal
    submit_ts_utc: datetime
    decision_seq_id: int
    include_no_side: bool = False
    no_token_id: Optional[str] = None
    no_decision_seq_id: Optional[int] = None
    execution_mode: ExecutionMode = "PAPER"
    attempt_id: Optional[str] = None
    idempotency_key: Optional[str] = None

    def resolved_attempt_id(self, sub_ts: datetime) -> str:
        return self.attempt_id or str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"{self.decision_id}|{sub_ts.isoformat()}|{self.yes_token_id}")
        )

    def resolved_idempotency_key(self, sub_ts: datetime) -> str:
        return self.idempotency_key or f"{self.decision_id}:{self.yes_token_id}:{sub_ts.isoformat()}"


def validate_cross_side_routing(
    plan: SlicePlan,
    *,
    execution_mode: ExecutionMode,
    config: TradingExecutionConfig,
) -> Optional[str]:
    """Enforce `enable_cross_side_split_routing` guard on `LIVE` split-sell legs (`§3.2`)."""
    if execution_mode == "LIVE" and not config.enable_cross_side_split_routing:
        if any(leg.leg_source == "NO_BID_SPLIT_SELL" for leg in plan.leg_allocations):
            return "LIVE_CROSS_SIDE_SPLIT_DISABLED"
    return None


class ReplayMatcher:
    """`P18` conservative delayed paper-replay matcher supporting dual YES/NO split/merge legs."""

    def __init__(
        self,
        config: TradingExecutionConfig,
        *,
        allow_resting_book_fallback: bool = False,
    ) -> None:
        self.config = config
        self.allow_resting_book_fallback = bool(allow_resting_book_fallback)
        self._consumed_shares: Dict[Tuple[str, int, Decimal], Decimal] = {}

    @staticmethod
    def _check_stream_r1_r2_r3(
        stream: Sequence[MarketBookRecordEnvelope],
        *,
        t_arrive: datetime,
        submit_ts_utc: datetime,
        decision_seq_id: int,
        max_silent_gap_sec: float,
        allow_resting_book_fallback: bool = False,
    ) -> Tuple[Optional[MarketBookRecordEnvelope], Optional[str]]:
        ordered = sorted(stream, key=lambda e: (e.payload.recv_ts_utc, e.seq_id))
        prior_clean: Optional[MarketBookRecordEnvelope] = None
        hit: Optional[MarketBookRecordEnvelope] = None

        for env in ordered:
            ts = ensure_utc_datetime(env.payload.recv_ts_utc, field_name="replay.recv_ts_utc")
            if env.seq_id <= decision_seq_id or ts < t_arrive:
                if env.seq_id > decision_seq_id and env.gap_detected:
                    return None, f"PAPER_MATCH_ABORTED_GAP:R2_GAP_IN_WINDOW:{env.gap_reason}"
                if not env.gap_detected:
                    prior_clean = env
                continue
            if env.gap_detected:
                return None, f"PAPER_MATCH_ABORTED_GAP:R2_HIT_GAP:{env.gap_reason}"
            hit = env
            break

        if hit is None:
            if allow_resting_book_fallback and prior_clean is not None:
                return prior_clean, None
            return None, "PAPER_MATCH_ABORTED_GAP:R1_NO_FRAME_AFTER_ARRIVE"

        # Verify no gap anywhere inside `(decision_seq_id, F*.seq_id]` even out of timestamp order
        for env in stream:
            if decision_seq_id < env.seq_id <= hit.seq_id and env.gap_detected:
                return None, f"PAPER_MATCH_ABORTED_GAP:R2_GAP_IN_WINDOW:{env.gap_reason}"

        baseline_ts = (
            ensure_utc_datetime(prior_clean.payload.recv_ts_utc, field_name="prior.recv_ts_utc")
            if prior_clean is not None
            else ensure_utc_datetime(submit_ts_utc, field_name="submit_ts_utc")
        )
        silent_sec = (
            ensure_utc_datetime(hit.payload.recv_ts_utc, field_name="hit.recv_ts_utc") - baseline_ts
        ).total_seconds()
        if silent_sec > max_silent_gap_sec:
            if allow_resting_book_fallback and prior_clean is not None:
                return prior_clean, None
            return None, f"PAPER_MATCH_ABORTED_GAP:R3_SILENT_GAP:{silent_sec:.3f}s"
        return hit, None

    def _resolve_replay_frames(
        self,
        ctx: OrderExecutionContext,
        plan: SlicePlan,
        recorded_envelopes: Sequence[MarketBookRecordEnvelope],
        t_arrive: datetime,
        sub_ts: datetime,
    ) -> Tuple[Optional[MarketBookRecordEnvelope], Optional[MarketBookRecordEnvelope], bool, Optional[str]]:
        yes_stream = [e for e in recorded_envelopes if e.payload.token_id == ctx.yes_token_id]
        hit_yes, yes_err = self._check_stream_r1_r2_r3(
            yes_stream, t_arrive=t_arrive, submit_ts_utc=sub_ts,
            decision_seq_id=ctx.decision_seq_id, max_silent_gap_sec=self.config.max_silent_gap_sec,
            allow_resting_book_fallback=self.allow_resting_book_fallback,
        )
        hit_no: Optional[MarketBookRecordEnvelope] = None
        no_err: Optional[str] = None
        if ctx.include_no_side and ctx.no_token_id is not None:
            no_stream = [e for e in recorded_envelopes if e.payload.token_id == ctx.no_token_id]
            no_seq = ctx.no_decision_seq_id if ctx.no_decision_seq_id is not None else ctx.decision_seq_id
            hit_no, no_err = self._check_stream_r1_r2_r3(
                no_stream, t_arrive=t_arrive, submit_ts_utc=sub_ts,
                decision_seq_id=no_seq, max_silent_gap_sec=self.config.max_silent_gap_sec,
                allow_resting_book_fallback=self.allow_resting_book_fallback,
            )

        uses_yes = any(leg.leg_source == "YES_ASK" for leg in plan.leg_allocations)
        uses_no = any(leg.leg_source == "NO_BID_SPLIT_SELL" for leg in plan.leg_allocations)
        if yes_err is not None:
            if ctx.include_no_side and no_err is None and hit_no is not None and uses_no and not uses_yes:
                return None, hit_no, True, None
            return hit_yes, hit_no, False, yes_err

        assert hit_yes is not None
        if no_err is not None:
            if not uses_no and hit_yes.payload.ask_book is not None:
                return hit_yes, None, False, None
            return hit_yes, hit_no, False, no_err
        return hit_yes, hit_no, ctx.include_no_side, None

    def _walk_merged_levels(
        self,
        merged_view: MergedYesAskView,
        plan: SlicePlan,
        *,
        yes_frame_seq: Optional[int] = None,
        no_frame_seq: Optional[int] = None,
    ) -> Tuple[List[FillLegRecord], Decimal, Decimal, Decimal, bool]:
        with exact_decimal_context():
            rem_shares = _to_exec_decimal(plan.target_shares, name="match.target_shares")
            limit_dec = _to_exec_decimal(plan.limit_price, name="match.limit_price")
            filled_total, cost_total, raw_fee_total = Decimal("0"), Decimal("0"), Decimal("0")
            fill_legs: List[FillLegRecord] = []
            had_prior_consumed = False
            for leg in merged_view.legged_levels:
                if rem_shares <= Decimal("0") or leg.implied_yes_price > limit_dec:
                    break
                fseq = no_frame_seq if leg.leg_source == "NO_BID_SPLIT_SELL" else yes_frame_seq
                avail = leg.size_shares
                if self.allow_resting_book_fallback and fseq is not None:
                    used = self._consumed_shares.get((leg.source_token_id, fseq, leg.raw_source_price), Decimal("0"))
                    if used > Decimal("0"):
                        had_prior_consumed = True
                    avail = max(Decimal("0"), avail - used)
                take_i = min(rem_shares, avail)
                if take_i <= Decimal("0"):
                    continue
                fee_i_raw = compute_taker_fee_usd_raw(take_i, leg.raw_source_price, leg.fee_rate)
                filled_total += take_i
                cost_total += take_i * leg.implied_yes_price
                raw_fee_total += fee_i_raw
                rem_shares -= take_i
                if self.allow_resting_book_fallback and fseq is not None:
                    ckey = (leg.source_token_id, fseq, leg.raw_source_price)
                    self._consumed_shares[ckey] = self._consumed_shares.get(ckey, Decimal("0")) + take_i
                fill_legs.append(
                    FillLegRecord(
                        leg_source=leg.leg_source, source_token_id=leg.source_token_id,
                        implied_yes_price=leg.implied_yes_price, raw_source_price=leg.raw_source_price,
                        filled_shares=take_i, fee_usd_raw=fee_i_raw,
                    )
                )
        return fill_legs, filled_total, cost_total, raw_fee_total, had_prior_consumed

    def _build_filled_log(
        self,
        ctx: OrderExecutionContext,
        plan: SlicePlan,
        *,
        replay_seq_id: int,
        final_ts: datetime,
        fill_legs: List[FillLegRecord],
        filled_total: Decimal,
        cost_total: Decimal,
        raw_fee_total: Decimal,
    ) -> ExecutionAttemptLog:
        sub_ts = ensure_utc_datetime(ctx.submit_ts_utc, field_name="submit_ts_utc")
        dec_ts = ensure_utc_datetime(ctx.decision_ts_utc, field_name="decision_ts_utc")
        with exact_decimal_context():
            fee_paid = quantize_polymarket_fee_usd(raw_fee_total)
            avg_fill = cost_total / filled_total
            fill_rate = filled_total / plan.target_shares
            best_ask_dec = _to_exec_decimal(ctx.decision_best_ask, name="match.decision_best_ask")
            est_vwap_dec = to_guarded_decimal(
                plan.est_vwap, name="match.decision_est_vwap", max_sig_digits=EXACT_DECIMAL_CONTEXT_PREC
            )
            slip_best = (avg_fill - best_ask_dec) / best_ask_dec
            slip_vwap = (avg_fill - est_vwap_dec) / est_vwap_dec
        term_status: TerminalStatus = "FILLED" if filled_total >= plan.target_shares else "PARTIAL"
        return ExecutionAttemptLog(
            schema_version="p3.v1", attempt_id=ctx.resolved_attempt_id(sub_ts),
            decision_id=ctx.decision_id, idempotency_key=ctx.resolved_idempotency_key(sub_ts),
            session_id=ctx.session_id, execution_mode=ctx.execution_mode, capture_replay_mode="REPLAY_P13",
            replay_source_seq_id=replay_seq_id, latency_injected_ms=self.config.latency_ms,
            station_id=ctx.station_id, market_id=ctx.market_id, token_id=ctx.yes_token_id,
            model_hash=ctx.model_hash, config_hash=ctx.config_hash, decision_ts_utc=dec_ts,
            decision_best_ask=best_ask_dec, decision_est_vwap=est_vwap_dec,
            decision_qual_depth_shares=plan.qual_depth_shares, order_type=plan.order_type,
            limit_price=plan.limit_price, target_shares=plan.target_shares, target_usd=plan.target_usd,
            submit_ts_utc=sub_ts, final_ts_utc=final_ts, terminal_status=term_status,
            reject_or_abort_reason=None, filled_shares=filled_total, filled_usd=cost_total,
            actual_avg_fill_price=avg_fill, fee_paid_usd=fee_paid, fill_rate=fill_rate,
            slippage_vs_best_ask=slip_best, slippage_vs_est_vwap=slip_vwap, execution_legs=tuple(fill_legs),
        )

    def _build_unfilled_log(
        self,
        ctx: OrderExecutionContext,
        plan: SlicePlan,
        *,
        replay_source_seq_id: Optional[int],
        final_ts_utc: datetime,
        terminal_status: TerminalStatus,
        reason: Optional[str],
    ) -> ExecutionAttemptLog:
        sub_ts = ensure_utc_datetime(ctx.submit_ts_utc, field_name="submit_ts_utc")
        dec_ts = ensure_utc_datetime(ctx.decision_ts_utc, field_name="decision_ts_utc")
        return ExecutionAttemptLog(
            schema_version="p3.v1", attempt_id=ctx.resolved_attempt_id(sub_ts),
            decision_id=ctx.decision_id, idempotency_key=ctx.resolved_idempotency_key(sub_ts),
            session_id=ctx.session_id, execution_mode=ctx.execution_mode, capture_replay_mode="REPLAY_P13",
            replay_source_seq_id=replay_source_seq_id, latency_injected_ms=self.config.latency_ms,
            station_id=ctx.station_id, market_id=ctx.market_id, token_id=ctx.yes_token_id,
            model_hash=ctx.model_hash, config_hash=ctx.config_hash, decision_ts_utc=dec_ts,
            decision_best_ask=_to_exec_decimal(ctx.decision_best_ask, name="unfilled.best_ask"),
            decision_est_vwap=plan.est_vwap, decision_qual_depth_shares=plan.qual_depth_shares,
            order_type=plan.order_type, limit_price=plan.limit_price, target_shares=plan.target_shares,
            target_usd=plan.target_usd, submit_ts_utc=sub_ts, final_ts_utc=final_ts_utc,
            terminal_status=terminal_status, reject_or_abort_reason=reason, filled_shares=Decimal("0"),
            filled_usd=Decimal("0"), actual_avg_fill_price=None, fee_paid_usd=Decimal("0.00000"),
            fill_rate=Decimal("0"), slippage_vs_best_ask=None, slippage_vs_est_vwap=None, execution_legs=(),
        )

    def match_order(
        self,
        *,
        context: OrderExecutionContext,
        plan: SlicePlan,
        recorded_envelopes: Sequence[MarketBookRecordEnvelope],
    ) -> ExecutionAttemptLog:
        """Conservatively match `SlicePlan` at `t_arrive = submit_ts_utc + latency_ms` (`P18`)."""
        sub_ts = ensure_utc_datetime(context.submit_ts_utc, field_name="submit_ts_utc")
        t_arrive = sub_ts + timedelta(milliseconds=self.config.latency_ms)

        routing_err = validate_cross_side_routing(
            plan, execution_mode=context.execution_mode, config=self.config
        )
        if routing_err is not None:
            return self._build_unfilled_log(
                context, plan, replay_source_seq_id=None, final_ts_utc=sub_ts,
                terminal_status="REJECTED", reason=routing_err,
            )

        hit_yes, hit_no, use_no_view, abort_err = self._resolve_replay_frames(
            context, plan, recorded_envelopes, t_arrive, sub_ts
        )
        if abort_err is not None:
            replay_seq = hit_yes.seq_id if hit_yes is not None else (hit_no.seq_id if hit_no is not None else None)
            return self._build_unfilled_log(
                context, plan, replay_source_seq_id=replay_seq, final_ts_utc=t_arrive,
                terminal_status="PAPER_MATCH_ABORTED_GAP", reason=abort_err,
            )

        ref_hit = hit_yes if hit_yes is not None else hit_no
        assert ref_hit is not None
        yes_snap = hit_yes.payload if hit_yes is not None else None
        no_snap = hit_no.payload if hit_no is not None else None
        merged_view = build_merged_yes_ask_view(yes_snap, no_snap, include_no_side=use_no_view)

        if merged_view.inverted_cross:
            return self._build_unfilled_log(
                context, plan, replay_source_seq_id=ref_hit.seq_id, final_ts_utc=ref_hit.payload.recv_ts_utc,
                terminal_status="CANCELLED_UNFILLED", reason=merged_view.inversion_reason or "INVERTED_BOOK",
            )
        if merged_view.ask_book is None or not merged_view.legged_levels:
            return self._build_unfilled_log(
                context, plan, replay_source_seq_id=ref_hit.seq_id, final_ts_utc=ref_hit.payload.recv_ts_utc,
                terminal_status="CANCELLED_UNFILLED", reason="NO_ASK_DEPTH",
            )

        fill_legs, filled_total, cost_total, raw_fee_total, had_prior_consumed = self._walk_merged_levels(
            merged_view,
            plan,
            yes_frame_seq=yes_snap.frame_seq if yes_snap is not None else None,
            no_frame_seq=no_snap.frame_seq if no_snap is not None else None,
        )
        if filled_total <= Decimal("0"):
            reason = "RESTING_BOOK_DEPTH_EXHAUSTED" if had_prior_consumed else "LIMIT_PRICE_EXCEEDED_FAK"
            return self._build_unfilled_log(
                context, plan, replay_source_seq_id=ref_hit.seq_id,
                final_ts_utc=max(t_arrive, ref_hit.payload.recv_ts_utc),
                terminal_status="CANCELLED_UNFILLED", reason=reason,
            )

        only_no = all(leg.leg_source == "NO_BID_SPLIT_SELL" for leg in fill_legs)
        replay_seq = hit_no.seq_id if (only_no and hit_no is not None) else ref_hit.seq_id
        if yes_snap is not None and no_snap is not None and any(l.leg_source == "NO_BID_SPLIT_SELL" for l in fill_legs):
            raw_final_ts = max(yes_snap.recv_ts_utc, no_snap.recv_ts_utc)
        elif only_no and no_snap is not None:
            raw_final_ts = no_snap.recv_ts_utc
        else:
            raw_final_ts = ref_hit.payload.recv_ts_utc
        final_ts = max(t_arrive, raw_final_ts)
        return self._build_filled_log(
            context, plan, replay_seq_id=replay_seq, final_ts=final_ts,
            fill_legs=fill_legs, filled_total=filled_total, cost_total=cost_total, raw_fee_total=raw_fee_total,
        )


def compute_merge_sell_yes_proceeds(
    *,
    shares: Decimal,
    no_ask_price: Decimal,
    fee_rate: Decimal,
) -> Tuple[Decimal, Decimal]:
    """CTF `merge` symmetry check: `sell Yes @ (1 - no_ask_price) ↔ buy No @ no_ask_price`.

    Returns `(net_usdc_proceeds_after_fee, quantized_fee_usd)` per `P8-RECORDER-NO-SIDE-DESIGN §3.2`.
    """
    with exact_decimal_context():
        s_d = _to_exec_decimal(shares, name="merge.shares")
        p_no_ask = _to_exec_decimal(no_ask_price, name="merge.no_ask_price")
        p_imp_yes_sell = equivalent_complementary_price(p_no_ask)
        raw_fee = compute_taker_fee_usd_raw(s_d, p_no_ask, _to_exec_decimal(fee_rate, name="merge.fee_rate"))
        fee_q = quantize_polymarket_fee_usd(raw_fee)
        proceeds = (s_d * p_imp_yes_sell) - fee_q
        return proceeds, fee_q


__all__ = [
    "CaptureReplayMode",
    "ExecutionAttemptLog",
    "ExecutionMode",
    "FillLegRecord",
    "OrderExecutionContext",
    "PhiPolicy",
    "PlannedLegSlice",
    "ReplayMatcher",
    "SlicePlan",
    "TerminalStatus",
    "TradingExecutionConfig",
    "align_price_down_to_tick",
    "compute_merge_sell_yes_proceeds",
    "compute_rho",
    "compute_taker_fee_usd_raw",
    "plan_slice",
    "quantize_polymarket_fee_usd",
    "validate_cross_side_routing",
]
