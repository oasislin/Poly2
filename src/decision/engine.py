"""M4 (S3-04) Decision Engine: CausalSnapshotAssembler, OpportunityScaler, and DeterministicDecider.

Anchors:
- `P8-T8-ALGO4-DESIGN v0.3 §3` (`P5` latest `issue_ts`, dual age limits, `provisional_identity_v0`, UUIDv5 replay)
- `P8-T4-M4M5-INTERFACE v1.0 §1.2, §3.1, §3.4` (`WPolicy`, `RiskGatePolicy`, `P6`, `P7`)
- `P8-RECORDER-NO-SIDE-DESIGN v0.1 §2.2 & §3.1` (`P4 v1.1` one-sided guard + optional dual-side pair)

Read-only consumer of `src/pricing/edge_math.py` (`F-2` locked zone remains zero-diff).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
from typing import Any, Callable, Dict, Literal, Mapping, Optional, Protocol, Sequence, Tuple
import uuid

from src.data_acquisition.passive_book_recorder import MarketBookSnapshot
from src.execution.executor import PhiPolicy, SlicePlan, TradingExecutionConfig, plan_slice
from src.execution.orderbook_views import (
    DualSideBookPair,
    MergedYesAskView,
    build_merged_yes_ask_view,
)
from src.prediction.forecast_distribution_engine import ForecastDistributionSnapshotV11
from src.pricing.edge_math import evaluate_book_edges
from src.utils.causal_utils import CausalInputError, compute_record_sha256, ensure_utc_datetime
from src.utils.decimal_guard import to_guarded_decimal

ScanClock = Literal["INFO_CLOCK", "PRICE_CLOCK"]
ExecutionMode = Literal["PAPER", "LIVE"]
LightLevel = Literal["GREEN", "YELLOW", "RED"]
DecisionOutcome = Literal[
    "ORDERED",
    "IDLE_BUDGET_EXHAUSTED",
    "BLOCKED_BELOW_MIN_ORDER",
    "BLOCKED_NO_BOOK_DEPTH",
    "SKIP_EDGE_BELOW_M",
]
_DECISION_UUID_NAMESPACE = uuid.UUID("7f1e88b2-0c3e-4636-8d95-4df4e6372026")


@dataclass(frozen=True)
class LightLevelEvent:
    """`P16` system health & light-level transition signal (`M6 -> M4`)."""

    event_id: str
    level: LightLevel
    reason: str
    emitted_ts_utc: datetime
    station_id: Optional[str] = None


class P16SubscriptionSlot:
    """Registerable `P16` subscription slot forwarding light status into `M4` decisions."""

    def __init__(self) -> None:
        self._latest_event: Optional[LightLevelEvent] = None
        self._listeners: list[Callable[[LightLevelEvent], None]] = []

    def register_listener(self, listener: Callable[[LightLevelEvent], None]) -> None:
        self._listeners.append(listener)

    def publish(self, event: LightLevelEvent) -> None:
        ensure_utc_datetime(event.emitted_ts_utc, field_name="p16.emitted_ts_utc")
        self._latest_event = event
        for listener in tuple(self._listeners):
            listener(event)

    @property
    def latest_event(self) -> Optional[LightLevelEvent]:
        return self._latest_event


class CausalViolationError(CausalInputError):
    """Raised when `P5` or `P4` timestamps strictly exceed decision `scan_ts_utc`."""


@dataclass(frozen=True)
class SigmaDeltaFrozen:
    """Monthly frozen residual dispersion parameter (`P6 RiskGatePolicy` · `N4`)."""

    value: float
    provenance: str
    freeze_cycle_id: str

    def __post_init__(self) -> None:
        if self.value < 0.0:
            raise ValueError(f"sigma_delta_frozen.value must be >= 0, got {self.value}")


@dataclass(frozen=True)
class WPolicy:
    """Time-backbone budget schedule `w(tau)` kept strictly internal to `M4` (`B2`, `B4`)."""

    w0_intent: float
    min_order_usd_eff: float
    p: float
    tau_max_h: float
    station_cap_usd: float
    concurrent_days: int
    b_budget_usd: float
    w0: float
    provenance: str

    def __post_init__(self) -> None:
        if self.tau_max_h <= 0.0 or self.p < 1.0:
            raise ValueError("WPolicy requires tau_max_h > 0 and p >= 1.0")
        if self.concurrent_days < 1 or self.station_cap_usd <= 0.0:
            raise ValueError("WPolicy requires concurrent_days >= 1 and station_cap_usd > 0")
        if not (0.0 < self.w0 <= 1.0):
            raise ValueError(f"WPolicy requires 0 < w0 <= 1.0, got {self.w0}")
        if self.w0 * self.b_budget_usd + 1e-12 < self.min_order_usd_eff:
            raise ValueError("WPolicy requires w0 * b_budget_usd >= min_order_usd_eff (Ruling B4)")


@dataclass(frozen=True)
class RiskGatePolicy:
    """`P6` risk gate threshold parameters (`B5`, `A1`)."""

    k0_threshold_coef: float
    sigma_delta_frozen: SigmaDeltaFrozen
    friction_median: Optional[float]
    m_floor: float
    station_cap_usd: float = 500.0
    concurrent_days: int = 2
    yellow_multiplier: float = 1.0
    yellow_multiplier_note: str = "待 D-6 作用点"
    allow_provisional_none_friction: bool = False

    def __post_init__(self) -> None:
        if self.friction_median is None and not self.allow_provisional_none_friction:
            raise ValueError(
                "RiskGatePolicy.friction_median is None: production signing blocked until D-A1 measurement"
            )
        if self.friction_median is not None and self.friction_median < 0.0:
            raise ValueError(f"friction_median must be >= 0, got {self.friction_median}")
        if self.m_floor < 0.0 or self.k0_threshold_coef < 0.0:
            raise ValueError("m_floor and k0_threshold_coef must be >= 0")

    @property
    def m_threshold(self) -> float:
        """Derived dimensionless relative edge threshold (`B5`)."""
        fric = 0.0 if self.friction_median is None else float(self.friction_median)
        return max(
            float(self.k0_threshold_coef) * float(self.sigma_delta_frozen.value) + fric,
            float(self.m_floor),
        )


@dataclass(frozen=True)
class ExecutionPolicyBundle:
    """`P6 ExecutionPolicyBundle v1.0` (`M8 -> M4 / M5 / M7`)."""

    policy_version: str
    config_hash: str
    signed_at_utc: datetime
    is_overdue: bool
    w_policy: WPolicy
    phi_policy: PhiPolicy
    risk_gate: RiskGatePolicy
    scaler_policy_id: str = "provisional_identity_v0"
    scaler_provisional: bool = True
    scaler_provenance: str = "PROVISIONAL_UNTIL_D6"


def _compute_policy_config_hash(
    policy_version: str,
    w0: float,
    b_budget: float,
    phi_policy: PhiPolicy,
    gate: RiskGatePolicy,
    scaler_policy_id: str,
) -> str:
    raw_hash_input = json.dumps(
        {
            "policy_version": policy_version,
            "w0": w0,
            "b_budget": b_budget,
            "rho_0": str(phi_policy.rho_0),
            "m_threshold": gate.m_threshold,
            "sigma_cycle": gate.sigma_delta_frozen.freeze_cycle_id,
            "scaler_policy_id": scaler_policy_id,
        },
        sort_keys=True,
    )
    return compute_record_sha256({"bundle": raw_hash_input})[:16]


def build_execution_policy_bundle(
    *,
    policy_version: str,
    signed_at_utc: datetime,
    is_overdue: bool,
    w0_intent: float,
    min_order_usd_eff: float,
    p: float,
    tau_max_h: float,
    station_cap_usd: float,
    concurrent_days: int,
    w_provenance: str,
    phi_policy: PhiPolicy,
    k0_threshold_coef: float,
    sigma_delta_frozen: SigmaDeltaFrozen,
    friction_median: Optional[float],
    m_floor: float,
    yellow_multiplier: float = 1.0,
    allow_provisional_none_friction: bool = False,
    scaler_policy_id: str = "provisional_identity_v0",
    scaler_provisional: bool = True,
    scaler_provenance: str = "PROVISIONAL_UNTIL_D6",
) -> ExecutionPolicyBundle:
    """Factory deriving `b_budget_usd` and `w0` at construction time (`interface §3.4` B4)."""
    signed = ensure_utc_datetime(signed_at_utc, field_name="signed_at_utc")
    b_budget = float(station_cap_usd) / float(concurrent_days)
    w0 = max(float(min_order_usd_eff) / b_budget, float(w0_intent))
    w_pol = WPolicy(
        w0_intent=w0_intent, min_order_usd_eff=min_order_usd_eff, p=p, tau_max_h=tau_max_h,
        station_cap_usd=station_cap_usd, concurrent_days=concurrent_days, b_budget_usd=b_budget,
        w0=w0, provenance=w_provenance,
    )
    gate = RiskGatePolicy(
        k0_threshold_coef=k0_threshold_coef, sigma_delta_frozen=sigma_delta_frozen,
        friction_median=friction_median, m_floor=m_floor, station_cap_usd=station_cap_usd,
        concurrent_days=concurrent_days, yellow_multiplier=yellow_multiplier,
        allow_provisional_none_friction=allow_provisional_none_friction,
    )
    cfg_hash = _compute_policy_config_hash(
        policy_version, w0, b_budget, phi_policy, gate, scaler_policy_id
    )
    return ExecutionPolicyBundle(
        policy_version=policy_version, config_hash=cfg_hash, signed_at_utc=signed,
        is_overdue=bool(is_overdue), w_policy=w_pol, phi_policy=phi_policy, risk_gate=gate,
        scaler_policy_id=scaler_policy_id, scaler_provisional=scaler_provisional,
        scaler_provenance=scaler_provenance,
    )


@dataclass(frozen=True)
class QuotaQuery:
    """`P7 QuotaQuery` request sent by `M4` to resolve current `QuotaSnapshot`."""

    station_id: str
    market_id: str
    token_id: str
    policy_version: str


class QuotaProvider(Protocol):
    """`P7` pull port allowing `M4` to request `QuotaSnapshot` per station/market."""

    def query_quota(self, query: QuotaQuery) -> QuotaSnapshot: ...


@dataclass(frozen=True)
class QuotaSnapshot:
    """`P7 QuotaSnapshot v1.0` (`M6 -> M4`)."""

    station_id: str
    market_id: str
    free_usd: float
    station_active_locked_usd: float
    market_held_usd: float
    station_cap_usd: float
    station_realized_loss_usd: float
    station_loss_gate_tripped: bool
    account_drawdown_brake_tripped: bool
    b_eff_headroom_usd: float
    blocked_reason: Optional[str] = None


class OpportunityScaler(Protocol):
    """Ported `s(edge)` scaler protocol awaiting final `D-6` shape rules."""

    policy_id: str
    provisional: bool
    provenance: str

    def scale(self, *, best_ask_edge: float, m_threshold: float) -> float: ...


@dataclass(frozen=True)
class IdentityScaler:
    """Provisional `s(edge)` implementation strictly bound to `v0.3 §3.2` three conditions."""

    policy_id: str = "provisional_identity_v0"
    provisional: bool = True
    provenance: str = "PROVISIONAL_UNTIL_D6"

    def scale(self, *, best_ask_edge: float, m_threshold: float) -> float:
        if best_ask_edge < m_threshold:
            return 0.0
        return 1.0


@dataclass(frozen=True)
class ScanDecisionEvent:
    """`P1 ScanDecisionEvent` (`M4 -> M7`) aligned to `P8-T2-M7-LOGGING §2.1` + `v0.3 §3.2`."""

    schema_version: str
    decision_id: str
    session_id: str
    execution_mode: ExecutionMode
    scan_clock: ScanClock
    scan_ts_utc: datetime
    station_id: str
    target_date: str
    target_type: str
    bin_id: str
    token_id: str
    market_id: str
    model_hash: str
    config_hash: str
    policy_version: str
    policy_overdue: bool
    forecast_id: str
    book_frame_ref: int
    best_ask_price: Optional[float]
    best_ask_edge: Optional[float]
    m_threshold: float
    tau_hours: float
    b_budget_usd: float
    w_tau: float
    s_edge: float
    g_cap_usd: float
    held_usd: float
    headroom_d: float
    decision_outcome: DecisionOutcome
    target_slice_usd: float
    scaler_policy_id: str
    scaler_provisional: bool
    scaler_provenance: str
    light_status: Optional[LightLevel] = None
    p16_event_id: Optional[str] = None
    degradation_reason: Optional[str] = None
    slice_plan: Optional[SlicePlan] = None

    def to_dict_without_hash(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "session_id": self.session_id,
            "execution_mode": self.execution_mode,
            "scan_clock": self.scan_clock,
            "scan_ts_utc": self.scan_ts_utc.isoformat(),
            "station_id": self.station_id,
            "target_date": self.target_date,
            "target_type": self.target_type,
            "bin_id": self.bin_id,
            "token_id": self.token_id,
            "market_id": self.market_id,
            "model_hash": self.model_hash,
            "config_hash": self.config_hash,
            "policy_version": self.policy_version,
            "policy_overdue": self.policy_overdue,
            "forecast_id": self.forecast_id,
            "book_frame_ref": self.book_frame_ref,
            "best_ask_price": self.best_ask_price,
            "best_ask_edge": self.best_ask_edge,
            "m_threshold": self.m_threshold,
            "tau_hours": self.tau_hours,
            "b_budget_usd": self.b_budget_usd,
            "w_tau": self.w_tau,
            "s_edge": self.s_edge,
            "g_cap_usd": self.g_cap_usd,
            "held_usd": self.held_usd,
            "headroom_d": self.headroom_d,
            "decision_outcome": self.decision_outcome,
            "target_slice_usd": self.target_slice_usd,
            "scaler_policy_id": self.scaler_policy_id,
            "scaler_provisional": self.scaler_provisional,
            "scaler_provenance": self.scaler_provenance,
            "light_status": self.light_status,
            "p16_event_id": self.p16_event_id,
            "degradation_reason": self.degradation_reason,
        }

    def to_json_line(self) -> str:
        payload = self.to_dict_without_hash()
        payload["record_sha256"] = compute_record_sha256(payload)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_w_tau(tau_hours: float, policy: WPolicy) -> float:
    """Compute bounded anchor power schedule `w(tau)` in `[policy.w0, 1.0]` (`interface §1.2`)."""
    tau_clamped = min(max(float(tau_hours), 0.0), float(policy.tau_max_h))
    progress = 1.0 - (tau_clamped / float(policy.tau_max_h))
    return float(policy.w0) + (1.0 - float(policy.w0)) * (progress ** float(policy.p))


@dataclass(frozen=True)
class AssembledScanInputs:
    """Result of causal `P5` and `P4` assembly at `scan_ts_utc` (`v0.3 §3.1`)."""

    winning_forecast: Optional[ForecastDistributionSnapshotV11]
    forecast_ok: bool
    forecast_degradation_reason: Optional[str]
    yes_frame: Optional[MarketBookSnapshot]
    no_frame: Optional[MarketBookSnapshot]
    merged_view: MergedYesAskView
    book_ok: bool
    book_degradation_reason: Optional[str]


class CausalSnapshotAssembler:
    """Strict causal snapshot selector (`issue_ts_utc` no-rollback + `M3->M4` book age)."""

    def __init__(self, exec_config: TradingExecutionConfig) -> None:
        self.exec_config = exec_config

    def select_latest_forecast(
        self,
        forecasts: Sequence[ForecastDistributionSnapshotV11],
        *,
        station_id: str,
        target_date_str: str,
        target_type: str,
        scan_ts_utc: datetime,
    ) -> Tuple[Optional[ForecastDistributionSnapshotV11], bool, Optional[str]]:
        t_scan = ensure_utc_datetime(scan_ts_utc, field_name="scan_ts_utc")
        matched: list[ForecastDistributionSnapshotV11] = []
        for fc in forecasts:
            issue_ts = ensure_utc_datetime(fc.issue_ts_utc, field_name="P5.issue_ts_utc")
            if issue_ts > t_scan:
                raise CausalViolationError(
                    f"Causal breach: P5.issue_ts_utc={issue_ts.isoformat()} > scan={t_scan.isoformat()}"
                )
            if (
                fc.station_id == station_id
                and fc.target_date.isoformat() == target_date_str
                and fc.target_type == target_type
            ):
                matched.append(fc)

        if not matched:
            return None, False, "MISSING_FORECAST"

        # Strict latest `issue_ts_utc` wins; NEVER roll back to an older snapshot.
        winner = max(matched, key=lambda fc: ensure_utc_datetime(fc.issue_ts_utc, field_name="P5.issue_ts_utc"))
        if not winner.oracle_compliant:
            return winner, False, "NON_ORACLE_COMPLIANT_FORECAST"
        forecast_age = (t_scan - ensure_utc_datetime(winner.issue_ts_utc, field_name="winner.issue_ts_utc")).total_seconds()
        if forecast_age > self.exec_config.forecast_age_limit_sec:
            return winner, False, f"STALE_FORECAST_DEGRADED:{forecast_age:.1f}s"
        return winner, True, None

    def _check_book_causality_and_age(
        self,
        snap: Optional[MarketBookSnapshot],
        *,
        label: str,
        t_scan: datetime,
        stale_reason_prefix: str,
    ) -> Tuple[Optional[MarketBookSnapshot], Optional[str]]:
        if snap is None:
            return None, None
        recv = ensure_utc_datetime(snap.recv_ts_utc, field_name=f"{label}.recv_ts_utc")
        if recv > t_scan:
            raise CausalViolationError(
                f"Causal breach: {label}.recv_ts_utc={recv.isoformat()} > scan={t_scan.isoformat()}"
            )
        age = (t_scan - recv).total_seconds()
        if age > self.exec_config.max_book_staleness_sec:
            return None, f"{stale_reason_prefix}:{age:.1f}s"
        return snap, None

    def assemble(
        self,
        *,
        forecasts: Sequence[ForecastDistributionSnapshotV11],
        station_id: str,
        target_date_str: str,
        target_type: str,
        scan_ts_utc: datetime,
        yes_frame: Optional[MarketBookSnapshot] = None,
        no_frame: Optional[MarketBookSnapshot] = None,
        dual_pair: Optional[DualSideBookPair] = None,
        include_no_side: bool = False,
    ) -> AssembledScanInputs:
        t_scan = ensure_utc_datetime(scan_ts_utc, field_name="scan_ts_utc")
        fc, fc_ok, fc_reason = self.select_latest_forecast(
            forecasts, station_id=station_id, target_date_str=target_date_str,
            target_type=target_type, scan_ts_utc=t_scan,
        )
        raw_y = dual_pair.yes_frame if dual_pair is not None else yes_frame
        raw_n = dual_pair.no_frame if dual_pair is not None else no_frame
        y_snap, y_reason = self._check_book_causality_and_age(
            raw_y, label="yes_frame", t_scan=t_scan, stale_reason_prefix="STALE_BOOK_DEGRADED"
        )
        n_snap, n_reason = self._check_book_causality_and_age(
            raw_n, label="no_frame", t_scan=t_scan, stale_reason_prefix="STALE_NO_BOOK_DEGRADED"
        )
        merged_view = build_merged_yes_ask_view(y_snap, n_snap, include_no_side=include_no_side)
        book_ok = y_snap is not None or (include_no_side and n_snap is not None)
        book_reason = y_reason or n_reason
        if not book_ok and book_reason is None:
            book_reason = dual_pair.degraded_reason if dual_pair is not None else "MISSING_BOOK_FRAME"
        return AssembledScanInputs(
            winning_forecast=fc, forecast_ok=fc_ok, forecast_degradation_reason=fc_reason,
            yes_frame=y_snap, no_frame=n_snap, merged_view=merged_view,
            book_ok=book_ok, book_degradation_reason=book_reason,
        )


def compute_deterministic_decision_id(
    *,
    orig_session_id: str,
    scan_ts_utc: datetime,
    scan_clock: ScanClock,
    station_id: str,
    target_date: str,
    bin_id: str,
) -> str:
    """Generate deterministic `UUIDv5` reusing original `P1.session_id` (`v0.3 §3.3`)."""
    t_scan = ensure_utc_datetime(scan_ts_utc, field_name="scan_ts_utc")
    key = f"{orig_session_id}|{t_scan.isoformat()}|{scan_clock}|{station_id}|{target_date}|{bin_id}"
    return str(uuid.uuid5(_DECISION_UUID_NAMESPACE, key))


@dataclass(frozen=True)
class _DecisionContext:
    decision_id: str
    orig_session_id: str
    execution_mode: ExecutionMode
    scan_clock: ScanClock
    t_scan: datetime
    station_id: str
    target_date: str
    target_type: str
    bin_id: str
    yes_token_id: str
    market_id: str
    policy_bundle: ExecutionPolicyBundle
    quota: QuotaSnapshot
    forecast_id: str
    model_hash: str
    book_frame_ref: int
    tau_hours: float
    m_threshold: float
    b_budget: float
    w_tau: float
    light_status: Optional[LightLevel]
    p16_event_id: Optional[str]


class DeterministicDecider:
    """`M4` pure deterministic scanner producing `P1` events and `P2` `SlicePlan`s."""

    def __init__(
        self,
        *,
        exec_config: TradingExecutionConfig,
        scaler: Optional[OpportunityScaler] = None,
        p16_slot: Optional[P16SubscriptionSlot] = None,
    ) -> None:
        self.exec_config = exec_config
        self.scaler: OpportunityScaler = scaler if scaler is not None else IdentityScaler()
        self.assembler = CausalSnapshotAssembler(exec_config)
        self.p16_slot = p16_slot if p16_slot is not None else P16SubscriptionSlot()

    @staticmethod
    def _resolve_quota(
        *,
        quota: Optional[QuotaSnapshot],
        quota_provider: Optional[QuotaProvider],
        station_id: str,
        market_id: str,
        yes_token_id: str,
        policy_version: str,
    ) -> QuotaSnapshot:
        if quota is not None:
            return quota
        if quota_provider is None:
            raise ValueError("Either quota or quota_provider must be provided to evaluate_bin")
        return quota_provider.query_quota(
            QuotaQuery(
                station_id=station_id,
                market_id=market_id,
                token_id=yes_token_id,
                policy_version=policy_version,
            )
        )

    def _build_scan_event(
        self,
        ctx: _DecisionContext,
        outcome: DecisionOutcome,
        *,
        reason: Optional[str] = None,
        best_ask_price: Optional[float] = None,
        best_ask_edge: Optional[float] = None,
        s_edge: float = 0.0,
        g_cap: float = 0.0,
        headroom_d: float = 0.0,
        slice_plan: Optional[SlicePlan] = None,
    ) -> ScanDecisionEvent:
        target_usd = float(slice_plan.target_usd) if (slice_plan and slice_plan.should_submit) else 0.0
        return ScanDecisionEvent(
            schema_version="p1.v1", decision_id=ctx.decision_id, session_id=ctx.orig_session_id,
            execution_mode=ctx.execution_mode, scan_clock=ctx.scan_clock, scan_ts_utc=ctx.t_scan,
            station_id=ctx.station_id, target_date=ctx.target_date, target_type=ctx.target_type,
            bin_id=ctx.bin_id, token_id=ctx.yes_token_id, market_id=ctx.market_id,
            model_hash=ctx.model_hash, config_hash=ctx.policy_bundle.config_hash,
            policy_version=ctx.policy_bundle.policy_version, policy_overdue=ctx.policy_bundle.is_overdue,
            forecast_id=ctx.forecast_id, book_frame_ref=ctx.book_frame_ref,
            best_ask_price=best_ask_price, best_ask_edge=best_ask_edge,
            m_threshold=ctx.m_threshold, tau_hours=ctx.tau_hours, b_budget_usd=ctx.b_budget,
            w_tau=ctx.w_tau, s_edge=s_edge, g_cap_usd=g_cap, held_usd=ctx.quota.market_held_usd,
            headroom_d=headroom_d, decision_outcome=outcome, target_slice_usd=target_usd,
            scaler_policy_id=self.scaler.policy_id, scaler_provisional=self.scaler.provisional,
            scaler_provenance=self.scaler.provenance, light_status=ctx.light_status,
            p16_event_id=ctx.p16_event_id, degradation_reason=reason, slice_plan=slice_plan,
        )

    def _build_decision_context(
        self,
        *,
        orig_session_id: str,
        execution_mode: ExecutionMode,
        scan_clock: ScanClock,
        t_scan: datetime,
        station_id: str,
        target_date: str,
        target_type: str,
        bin_id: str,
        market_id: str,
        yes_token_id: str,
        policy_bundle: ExecutionPolicyBundle,
        quota: QuotaSnapshot,
        assembled: AssembledScanInputs,
        light_event: Optional[LightLevelEvent],
    ) -> _DecisionContext:
        fc = assembled.winning_forecast
        tau_h = (
            max(0.0, (ensure_utc_datetime(fc.settle_close_utc, field_name="settle_close") - t_scan).total_seconds() / 3600.0)
            if fc is not None
            else 0.0
        )
        ref_snap = assembled.yes_frame or assembled.no_frame
        b_budget = policy_bundle.w_policy.b_budget_usd
        active_light = light_event if light_event is not None else self.p16_slot.latest_event
        return _DecisionContext(
            decision_id=compute_deterministic_decision_id(
                orig_session_id=orig_session_id, scan_ts_utc=t_scan, scan_clock=scan_clock,
                station_id=station_id, target_date=target_date, bin_id=bin_id,
            ),
            orig_session_id=orig_session_id, execution_mode=execution_mode, scan_clock=scan_clock,
            t_scan=t_scan, station_id=station_id, target_date=target_date, target_type=target_type,
            bin_id=bin_id, yes_token_id=yes_token_id, market_id=market_id,
            policy_bundle=policy_bundle, quota=quota,
            forecast_id=fc.forecast_id if fc is not None else "MISSING_FORECAST",
            model_hash=fc.model_hash if fc is not None else "MISSING_MODEL",
            book_frame_ref=ref_snap.frame_seq if ref_snap is not None else 0,
            tau_hours=tau_h, m_threshold=policy_bundle.risk_gate.m_threshold,
            b_budget=b_budget, w_tau=compute_w_tau(tau_h, policy_bundle.w_policy),
            light_status=active_light.level if active_light is not None else None,
            p16_event_id=active_light.event_id if active_light is not None else None,
        )

    def _check_input_gates(
        self,
        ctx: _DecisionContext,
        assembled: AssembledScanInputs,
    ) -> Optional[ScanDecisionEvent]:
        if not assembled.forecast_ok or assembled.winning_forecast is None:
            return self._build_scan_event(
                ctx, "BLOCKED_NO_BOOK_DEPTH",
                reason=assembled.forecast_degradation_reason or "MISSING_FORECAST",
            )
        view = assembled.merged_view
        if not assembled.book_ok:
            return self._build_scan_event(
                ctx, "BLOCKED_NO_BOOK_DEPTH",
                reason=assembled.book_degradation_reason or "MISSING_BOOK",
            )
        if view.inverted_cross:
            return self._build_scan_event(
                ctx, "BLOCKED_NO_BOOK_DEPTH", reason=view.inversion_reason or "INVERTED_BOOK"
            )
        if view.ask_book is None or not view.legged_levels:
            return self._build_scan_event(ctx, "BLOCKED_NO_BOOK_DEPTH", reason="NO_ASK_DEPTH")
        return None

    def _apply_headroom_and_slice(
        self,
        ctx: _DecisionContext,
        view: MergedYesAskView,
        p_model: float,
        best_ask_price: float,
        best_ask_edge: float,
    ) -> ScanDecisionEvent:
        s_edge = float(self.scaler.scale(best_ask_edge=best_ask_edge, m_threshold=ctx.m_threshold))
        g_cap_usd = ctx.b_budget * ctx.w_tau * s_edge
        q = ctx.quota
        if q.account_drawdown_brake_tripped or q.station_loss_gate_tripped:
            return self._build_scan_event(
                ctx, "IDLE_BUDGET_EXHAUSTED", reason=q.blocked_reason or "RISK_BRAKE_TRIPPED",
                best_ask_price=best_ask_price, best_ask_edge=best_ask_edge, s_edge=s_edge, g_cap=g_cap_usd,
            )
        headroom_d = max(0.0, min(g_cap_usd - float(q.market_held_usd), float(q.b_eff_headroom_usd)))
        if headroom_d <= 0.0:
            return self._build_scan_event(
                ctx, "IDLE_BUDGET_EXHAUSTED", reason=q.blocked_reason,
                best_ask_price=best_ask_price, best_ask_edge=best_ask_edge, s_edge=s_edge, g_cap=g_cap_usd,
            )
        slice_plan = plan_slice(
            d_headroom_usd=to_guarded_decimal(round(headroom_d, 6), name="headroom_d"),
            ask_book_frame=view, p_model=p_model, m_threshold=ctx.m_threshold,
            phi_policy=ctx.policy_bundle.phi_policy,
            min_order_size_shares=self.exec_config.min_order_size_shares,
            min_notional_usd=self.exec_config.min_notional_usd,
        )
        if not slice_plan.should_submit:
            outcome: DecisionOutcome = (
                "BLOCKED_NO_BOOK_DEPTH"
                if slice_plan.abort_reason in ("NO_ASK_DEPTH", "INVERTED_BOOK")
                else "BLOCKED_BELOW_MIN_ORDER"
            )
            return self._build_scan_event(
                ctx, outcome, reason=slice_plan.abort_reason,
                best_ask_price=best_ask_price, best_ask_edge=best_ask_edge,
                s_edge=s_edge, g_cap=g_cap_usd, headroom_d=headroom_d,
            )
        return self._build_scan_event(
            ctx, "ORDERED", best_ask_price=best_ask_price, best_ask_edge=best_ask_edge,
            s_edge=s_edge, g_cap=g_cap_usd, headroom_d=headroom_d, slice_plan=slice_plan,
        )

    def evaluate_bin(
        self,
        *,
        orig_session_id: str,
        execution_mode: ExecutionMode,
        scan_clock: ScanClock,
        scan_ts_utc: datetime,
        station_id: str,
        target_date: str,
        bin_id: str,
        market_id: str,
        yes_token_id: str,
        forecasts: Sequence[ForecastDistributionSnapshotV11],
        policy_bundle: ExecutionPolicyBundle,
        quota: Optional[QuotaSnapshot] = None,
        quota_provider: Optional[QuotaProvider] = None,
        yes_frame: Optional[MarketBookSnapshot] = None,
        no_frame: Optional[MarketBookSnapshot] = None,
        dual_pair: Optional[DualSideBookPair] = None,
        include_no_side: bool = False,
        target_type: str = "TMAX",
        light_event: Optional[LightLevelEvent] = None,
    ) -> ScanDecisionEvent:
        """Evaluate one bin deterministically (never raises on bad book / stale forecast)."""
        t_scan = ensure_utc_datetime(scan_ts_utc, field_name="scan_ts_utc")
        resolved_quota = self._resolve_quota(
            quota=quota, quota_provider=quota_provider, station_id=station_id,
            market_id=market_id, yes_token_id=yes_token_id, policy_version=policy_bundle.policy_version,
        )
        assembled = self.assembler.assemble(
            forecasts=forecasts, station_id=station_id, target_date_str=target_date,
            target_type=target_type, scan_ts_utc=t_scan, yes_frame=yes_frame,
            no_frame=no_frame, dual_pair=dual_pair, include_no_side=include_no_side,
        )
        ctx = self._build_decision_context(
            orig_session_id=orig_session_id, execution_mode=execution_mode, scan_clock=scan_clock,
            t_scan=t_scan, station_id=station_id, target_date=target_date, target_type=target_type,
            bin_id=bin_id, market_id=market_id, yes_token_id=yes_token_id,
            policy_bundle=policy_bundle, quota=resolved_quota, assembled=assembled,
            light_event=light_event,
        )
        gate_block = self._check_input_gates(ctx, assembled)
        if gate_block is not None:
            return gate_block
        assert assembled.winning_forecast is not None
        view = assembled.merged_view
        assert view.ask_book is not None and view.legged_levels

        bin_match = next((bp for bp in assembled.winning_forecast.bin_probs if bp.bin_id == bin_id), None)
        if bin_match is None:
            return self._build_scan_event(ctx, "BLOCKED_NO_BOOK_DEPTH", reason=f"UNKNOWN_BIN_ID:{bin_id}")

        edge_summary = evaluate_book_edges(
            ask_book=view.ask_book, p_model=bin_match.p_model,
            m=ctx.m_threshold, fee_rate=float(view.legged_levels[0].fee_rate),
        )
        best_ask_price = float(view.ask_book.levels[0][0])
        best_ask_edge = float(edge_summary.best_ask_edge)
        if best_ask_edge < ctx.m_threshold or not edge_summary.qualified_levels:
            return self._build_scan_event(
                ctx, "SKIP_EDGE_BELOW_M", best_ask_price=best_ask_price, best_ask_edge=best_ask_edge
            )
        return self._apply_headroom_and_slice(
            ctx, view, bin_match.p_model, best_ask_price, best_ask_edge
        )


__all__ = [
    "AssembledScanInputs",
    "CausalSnapshotAssembler",
    "CausalViolationError",
    "DecisionOutcome",
    "DeterministicDecider",
    "ExecutionMode",
    "ExecutionPolicyBundle",
    "IdentityScaler",
    "LightLevel",
    "LightLevelEvent",
    "OpportunityScaler",
    "P16SubscriptionSlot",
    "QuotaProvider",
    "QuotaQuery",
    "QuotaSnapshot",
    "RiskGatePolicy",
    "ScanClock",
    "ScanDecisionEvent",
    "SigmaDeltaFrozen",
    "WPolicy",
    "build_execution_policy_bundle",
    "compute_deterministic_decision_id",
    "compute_w_tau",
]
