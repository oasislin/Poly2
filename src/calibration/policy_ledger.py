"""M8 (`S3-08`) Parameter Ledger, `P6` Policy Signing, Monthly Three-Layer Hold & `P16` Broadcaster.

Anchors:
- `P8-T4-M4M5-INTERFACE v1.0 §3.2 & §3.4`: `P8 -> M8` read-only intake, `P6` `config_hash` signing,
  `friction_median is None` fail-closed gate (`B5`), and `is_overdue=True` hold (`B6`).
- `P8-CAPITAL-CONFIG v1.1 §7`: unified nine-entry parameter ledger.
- `P8-D6-POLICY-CLOSURE v1.0 §一–§十`: three-layer anti-forgetfulness, `ECE` anchors, typed `YELLOW` reasons,
  `yellow_multiplier` (`config_hash v2`), and dual-target `P16` (`LightLevelEvent` + `TierStepUpEvent`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple

from src.audit.p8_aggregator import CalibrationAggregateBatch
from src.bankroll.manager import BankrollAccountManager
from src.bankroll.models import TierStepUpEvent
from src.decision.engine import (
    ExecutionPolicyBundle,
    LightLevel,
    LightLevelEvent,
    P16SubscriptionSlot,
    PhiPolicy,
    SigmaDeltaFrozen,
    build_execution_policy_bundle,
)
from src.utils.causal_utils import ensure_utc_datetime, parse_utc_timestamp

DEFAULT_REVIEW_INTERVAL_DAYS = 30
DEFAULT_REVIEW_TRIGGER_HOUR_UTC = 0
DEFAULT_REVIEW_TRIGGER_MINUTE_UTC = 15
ECE_GREEN_ANCHOR = 0.020
ECE_RED_ANCHOR = 0.040
MIN_P3_SLIPPAGE_FILLS = 30
MIN_FORECAST_SAMPLES = 60

ALLOWED_YELLOW_REASONS: frozenset[str] = frozenset(
    {
        "YELLOW_INSUFFICIENT_SAMPLE",
        "YELLOW_MILD_CALIBRATION_DRIFT",
        "YELLOW_INFRA_DEGRADED",
    }
)

LEDGER_PARAMETER_NAMES: Tuple[str, ...] = (
    "k0_threshold_coef",
    "concurrent_days",
    "w0_intent",
    "p",
    "phi_policy",
    "scan_schedule",
    "friction_median",
    "platform_min_order",
    "yellow_multiplier",
)


class PolicySigningBlockedError(ValueError):
    """Raised when `P6` signing is attempted without required real measurements (`friction_median is None`)."""


@dataclass(frozen=True)
class ParameterLedgerEntry:
    """Single audited entry inside `P8-CAPITAL-CONFIG §7` parameter ledger."""

    name: str
    value: Any
    basis: str
    sample_source: str = "P8-CAPITAL-CONFIG §7"
    replace_condition: str = "Monthly manual sign-off"
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "basis": self.basis,
            "sample_source": self.sample_source,
            "replace_condition": self.replace_condition,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ParameterLedgerEntry":
        return cls(
            name=str(payload["name"]),
            value=payload["value"],
            basis=str(payload["basis"]),
            sample_source=str(payload.get("sample_source", "P8-CAPITAL-CONFIG §7")),
            replace_condition=str(payload.get("replace_condition", "Monthly manual sign-off")),
            note=str(payload.get("note", "")),
        )


@dataclass(frozen=True)
class ParameterReplacementRecord:
    """Immutable audit record appended only upon explicit human sign-off (`Layer 2`)."""

    signed_ts_utc: datetime
    operator: str
    policy_version: str
    rationale: str
    updated_fields: Tuple[str, ...]

    def __post_init__(self) -> None:
        ensure_utc_datetime(self.signed_ts_utc, field_name="replacement.signed_ts_utc")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signed_ts_utc": self.signed_ts_utc.isoformat(),
            "operator": self.operator,
            "policy_version": self.policy_version,
            "rationale": self.rationale,
            "updated_fields": list(self.updated_fields),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ParameterReplacementRecord":
        return cls(
            signed_ts_utc=parse_utc_timestamp(str(payload["signed_ts_utc"]), field_name="replacement.signed_ts_utc"),
            operator=str(payload["operator"]),
            policy_version=str(payload["policy_version"]),
            rationale=str(payload["rationale"]),
            updated_fields=tuple(str(x) for x in payload.get("updated_fields", ())),
        )


def _phi_to_dict(phi: PhiPolicy) -> Dict[str, Any]:
    return {
        "rho_0": str(phi.rho_0),
        "k_slope": str(phi.k_slope),
        "rho_min": str(phi.rho_min),
        "rho_max": str(phi.rho_max),
        "order_type": phi.order_type,
        "provenance": phi.provenance,
    }


def _phi_from_dict(raw: Mapping[str, Any]) -> PhiPolicy:
    return PhiPolicy(
        rho_0=Decimal(str(raw["rho_0"])),
        k_slope=Decimal(str(raw["k_slope"])),
        rho_min=Decimal(str(raw["rho_min"])),
        rho_max=Decimal(str(raw["rho_max"])),
        order_type=str(raw.get("order_type", "IOC_FAK")),  # type: ignore[arg-type]
        provenance=str(raw.get("provenance", "T4")),
    )


def _default_entries(
    *,
    k0_threshold_coef: float,
    concurrent_days: int,
    w0_intent: float,
    p: float,
    phi_policy: PhiPolicy,
    friction_median: Optional[float],
    min_order_usd_eff: float,
    min_order_shares: int,
    yellow_multiplier: float,
) -> Dict[str, ParameterLedgerEntry]:
    return {
        "k0_threshold_coef": ParameterLedgerEntry("k0_threshold_coef", float(k0_threshold_coef), "P8-CAPITAL-CONFIG §7"),
        "concurrent_days": ParameterLedgerEntry("concurrent_days", int(concurrent_days), "P8-CAPITAL-CONFIG §7"),
        "w0_intent": ParameterLedgerEntry("w0_intent", float(w0_intent), "P8-CAPITAL-CONFIG §7"),
        "p": ParameterLedgerEntry("p", float(p), "P8-CAPITAL-CONFIG §7"),
        "phi_policy": ParameterLedgerEntry("phi_policy", _phi_to_dict(phi_policy), "P8-CAPITAL-CONFIG §7"),
        "scan_schedule": ParameterLedgerEntry(
            "scan_schedule",
            {"info_clock_hours": [6.0, 3.0, 1.0, 0.5], "price_clock_minutes": 45.0},
            "P8-CAPITAL-CONFIG §7",
        ),
        "friction_median": ParameterLedgerEntry(
            "friction_median",
            friction_median,
            "P8-CAPITAL-CONFIG §7 / D-A1",
            sample_source="P13 -> P3",
            replace_condition="S2-02 0.01-era measured slippage",
        ),
        "platform_min_order": ParameterLedgerEntry(
            "platform_min_order",
            {"min_shares": int(min_order_shares), "min_notional_usd": float(min_order_usd_eff)},
            "FACT-004 / P8-CAPITAL-CONFIG §7",
        ),
        "yellow_multiplier": ParameterLedgerEntry("yellow_multiplier", float(yellow_multiplier), "P8-D6-POLICY-CLOSURE §六"),
    }


@dataclass(frozen=True)
class PolicyParameterLedger:
    """Authoritative offline/persisted M8 parameter ledger feeding `build_execution_policy_bundle`."""

    policy_version: str
    signed_at_utc: datetime
    sigma_delta_frozen: SigmaDeltaFrozen
    entries: Dict[str, ParameterLedgerEntry]
    m_floor: float = 0.02
    tau_max_h: float = 24.0
    station_cap_usd: float = 500.0
    w_provenance: str = "P8-CAPITAL-CONFIG v1.1"
    scaler_policy_id: str = "provisional_identity_v0"
    scaler_provisional: bool = True
    scaler_provenance: str = "PROVISIONAL_UNTIL_D6"
    review_interval_days: int = DEFAULT_REVIEW_INTERVAL_DAYS
    replacement_history: Tuple[ParameterReplacementRecord, ...] = ()
    calibration_archive: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        ensure_utc_datetime(self.signed_at_utc, field_name="ledger.signed_at_utc")
        missing = set(LEDGER_PARAMETER_NAMES) - set(self.entries.keys())
        if missing:
            raise ValueError(f"Parameter ledger missing required §7 entries: {sorted(missing)}")

    @property
    def friction_median(self) -> Optional[float]:
        val = self.entries["friction_median"].value
        return None if val is None else float(val)

    @property
    def yellow_multiplier(self) -> float:
        return float(self.entries["yellow_multiplier"].value)

    @classmethod
    def create_initial_placeholder(
        cls,
        *,
        policy_version: str,
        created_ts_utc: datetime,
        sigma_delta_frozen: SigmaDeltaFrozen,
        phi_policy: PhiPolicy,
        k0_threshold_coef: float = 2.0,
        concurrent_days: int = 2,
        w0_intent: float = 0.10,
        p: float = 1.5,
        friction_median: Optional[float] = None,
        min_order_usd_eff: float = 1.0,
        min_order_shares: int = 5,
        yellow_multiplier: float = 0.5,
        m_floor: float = 0.02,
        tau_max_h: float = 24.0,
        station_cap_usd: float = 500.0,
        extra_metadata: Optional[Mapping[str, ParameterLedgerEntry]] = None,
    ) -> "PolicyParameterLedger":
        entries = _default_entries(
            k0_threshold_coef=k0_threshold_coef,
            concurrent_days=concurrent_days,
            w0_intent=w0_intent,
            p=p,
            phi_policy=phi_policy,
            friction_median=friction_median,
            min_order_usd_eff=min_order_usd_eff,
            min_order_shares=min_order_shares,
            yellow_multiplier=yellow_multiplier,
        )
        if extra_metadata:
            for key, entry in extra_metadata.items():
                if key in entries:
                    entries[key] = entry
        return cls(
            policy_version=policy_version,
            signed_at_utc=ensure_utc_datetime(created_ts_utc, field_name="ledger.created_ts_utc"),
            sigma_delta_frozen=sigma_delta_frozen,
            entries=entries,
            m_floor=m_floor,
            tau_max_h=tau_max_h,
            station_cap_usd=station_cap_usd,
        )

    def with_updated_yellow_multiplier(
        self,
        yellow_multiplier: float,
        *,
        updated_ts_utc: datetime,
        reason: str,
    ) -> "PolicyParameterLedger":
        """Return new ledger instance with updated `yellow_multiplier` and replacement note."""
        new_entries = dict(self.entries)
        new_entries["yellow_multiplier"] = ParameterLedgerEntry(
            "yellow_multiplier", float(yellow_multiplier), "P8-D6-POLICY-CLOSURE §六", note=reason
        )
        return PolicyParameterLedger(
            policy_version=self.policy_version,
            signed_at_utc=ensure_utc_datetime(updated_ts_utc, field_name="ledger.updated_ts_utc"),
            sigma_delta_frozen=self.sigma_delta_frozen,
            entries=new_entries,
            m_floor=self.m_floor,
            tau_max_h=self.tau_max_h,
            station_cap_usd=self.station_cap_usd,
            w_provenance=self.w_provenance,
            scaler_policy_id=self.scaler_policy_id,
            scaler_provisional=self.scaler_provisional,
            scaler_provenance=self.scaler_provenance,
            review_interval_days=self.review_interval_days,
            replacement_history=self.replacement_history,
        )

    def with_calibration_archive(self, archive: Mapping[str, Any]) -> "PolicyParameterLedger":
        """Attach read-only calibration distribution archive (e.g. p25/p50/p75/p90) to ledger."""
        return PolicyParameterLedger(
            policy_version=self.policy_version, signed_at_utc=self.signed_at_utc,
            sigma_delta_frozen=self.sigma_delta_frozen, entries=dict(self.entries),
            m_floor=self.m_floor, tau_max_h=self.tau_max_h, station_cap_usd=self.station_cap_usd,
            w_provenance=self.w_provenance, scaler_policy_id=self.scaler_policy_id,
            scaler_provisional=self.scaler_provisional, scaler_provenance=self.scaler_provenance,
            review_interval_days=self.review_interval_days,
            replacement_history=self.replacement_history, calibration_archive=dict(archive),
        )

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "policy_version": self.policy_version,
            "signed_at_utc": self.signed_at_utc.isoformat(),
            "sigma_delta_frozen": {
                "value": self.sigma_delta_frozen.value,
                "provenance": self.sigma_delta_frozen.provenance,
                "freeze_cycle_id": self.sigma_delta_frozen.freeze_cycle_id,
            },
            "entries": {k: self.entries[k].to_dict() for k in sorted(self.entries)},
            "m_floor": self.m_floor,
            "tau_max_h": self.tau_max_h,
            "station_cap_usd": self.station_cap_usd,
            "w_provenance": self.w_provenance,
            "scaler_policy_id": self.scaler_policy_id,
            "scaler_provisional": self.scaler_provisional,
            "scaler_provenance": self.scaler_provenance,
            "review_interval_days": self.review_interval_days,
            "replacement_history": [r.to_dict() for r in self.replacement_history],
        }
        if self.calibration_archive is not None:
            payload["calibration_archive"] = dict(self.calibration_archive)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PolicyParameterLedger":
        sd_raw = payload["sigma_delta_frozen"]
        arch_raw = payload.get("calibration_archive")
        return cls(
            policy_version=str(payload["policy_version"]),
            signed_at_utc=parse_utc_timestamp(str(payload["signed_at_utc"]), field_name="ledger.signed_at_utc"),
            sigma_delta_frozen=SigmaDeltaFrozen(
                value=float(sd_raw["value"]),
                provenance=str(sd_raw["provenance"]),
                freeze_cycle_id=str(sd_raw["freeze_cycle_id"]),
            ),
            entries={k: ParameterLedgerEntry.from_dict(v) for k, v in dict(payload["entries"]).items()},
            m_floor=float(payload["m_floor"]),
            tau_max_h=float(payload["tau_max_h"]),
            station_cap_usd=float(payload["station_cap_usd"]),
            w_provenance=str(payload["w_provenance"]),
            scaler_policy_id=str(payload["scaler_policy_id"]),
            scaler_provisional=bool(payload["scaler_provisional"]),
            scaler_provenance=str(payload["scaler_provenance"]),
            review_interval_days=int(payload.get("review_interval_days", DEFAULT_REVIEW_INTERVAL_DAYS)),
            replacement_history=tuple(
                ParameterReplacementRecord.from_dict(r) for r in payload.get("replacement_history", ())
            ),
            calibration_archive=dict(arch_raw) if isinstance(arch_raw, Mapping) else None,
        )

    def save(self, path: Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), sort_keys=True, indent=2), encoding="utf-8")
        tmp.replace(target)
        return target

    @classmethod
    def load(cls, path: Path) -> "PolicyParameterLedger":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(raw)


def issue_policy_bundle(
    ledger: PolicyParameterLedger,
    *,
    signed_at_utc: Optional[datetime] = None,
    is_overdue: bool = False,
    allow_provisional_none_friction: bool = False,
) -> ExecutionPolicyBundle:
    """Sign immutable `P6 ExecutionPolicyBundle` from `M8` ledger (`friction_median is None` fail-closed)."""
    if ledger.friction_median is None and not allow_provisional_none_friction:
        raise PolicySigningBlockedError(
            "P6 signing blocked: ledger.friction_median is None until S2-02 D-A1 measurement completes"
        )
    ts = ensure_utc_datetime(signed_at_utc or ledger.signed_at_utc, field_name="issue.signed_at_utc")
    min_order_info = ledger.entries["platform_min_order"].value
    return build_execution_policy_bundle(
        policy_version=ledger.policy_version,
        signed_at_utc=ts,
        is_overdue=is_overdue,
        w0_intent=float(ledger.entries["w0_intent"].value),
        min_order_usd_eff=float(min_order_info["min_notional_usd"]),
        p=float(ledger.entries["p"].value),
        tau_max_h=ledger.tau_max_h,
        station_cap_usd=ledger.station_cap_usd,
        concurrent_days=int(ledger.entries["concurrent_days"].value),
        w_provenance=ledger.w_provenance,
        phi_policy=_phi_from_dict(ledger.entries["phi_policy"].value),
        k0_threshold_coef=float(ledger.entries["k0_threshold_coef"].value),
        sigma_delta_frozen=ledger.sigma_delta_frozen,
        friction_median=ledger.friction_median,
        m_floor=ledger.m_floor,
        yellow_multiplier=ledger.yellow_multiplier,
        allow_provisional_none_friction=allow_provisional_none_friction,
        scaler_policy_id=ledger.scaler_policy_id,
        scaler_provisional=ledger.scaler_provisional,
        scaler_provenance=ledger.scaler_provenance,
    )


@dataclass(frozen=True)
class MonthlyReviewProposal:
    """Layer 1 read-only monthly review & light recommendation generated from `P8` batch."""

    generated_ts_utc: datetime
    eligible_for_human_signoff: bool
    recommended_light_level: LightLevel
    recommended_light_reason: str
    recommended_friction_median: Optional[float]
    recommended_sigma_delta_iqr: Optional[float]
    sample_gaps: Tuple[str, ...]


@dataclass(frozen=True)
class OverdueHoldOutcome:
    """Layer 3 (`B6`) conservative hold result when human sign-off is overdue."""

    bundle: ExecutionPolicyBundle
    reminder_message: str


def _recommend_light(pooled_ece: float, sample_gaps: Sequence[str]) -> Tuple[LightLevel, str]:
    if pooled_ece > ECE_RED_ANCHOR:
        return "RED", "RED_ECE_GT_0_040"
    if pooled_ece > ECE_GREEN_ANCHOR:
        return "YELLOW", "YELLOW_MILD_CALIBRATION_DRIFT"
    if sample_gaps:
        return "YELLOW", "YELLOW_INSUFFICIENT_SAMPLE"
    return "GREEN", "MONTHLY_GREEN"


def build_monthly_review_proposal(
    *,
    ledger: PolicyParameterLedger,
    calibration_batch: CalibrationAggregateBatch,
    generated_ts_utc: datetime,
    pooled_ece: float,
) -> MonthlyReviewProposal:
    """Layer 1: read-only `P8 -> M8` comparison producing human sign-off proposal without mutation."""
    ts = ensure_utc_datetime(generated_ts_utc, field_name="proposal.generated_ts_utc")
    gaps: List[str] = []
    if calibration_batch.n_forecast_samples < MIN_FORECAST_SAMPLES:
        gaps.append(f"n_forecast_samples={calibration_batch.n_forecast_samples}<{MIN_FORECAST_SAMPLES}")
    if (
        calibration_batch.n_slippage_fills < MIN_P3_SLIPPAGE_FILLS
        or calibration_batch.empirical_slippage_vs_best_ask_median is None
    ):
        gaps.append(f"n_slippage_fills={calibration_batch.n_slippage_fills}<{MIN_P3_SLIPPAGE_FILLS}")
    light, reason = _recommend_light(pooled_ece, gaps)
    sigma_iqr = calibration_batch.sigma_delta_quantiles.get("iqr_sigma")
    return MonthlyReviewProposal(
        generated_ts_utc=ts,
        eligible_for_human_signoff=(len(gaps) == 0),
        recommended_light_level=light,
        recommended_light_reason=reason,
        recommended_friction_median=calibration_batch.empirical_slippage_vs_best_ask_median,
        recommended_sigma_delta_iqr=float(sigma_iqr) if sigma_iqr is not None else None,
        sample_gaps=tuple(gaps),
    )


def sign_off_and_issue(
    *,
    ledger: PolicyParameterLedger,
    operator: str,
    rationale: str,
    new_policy_version: str,
    signed_at_utc: datetime,
    friction_median: Optional[float] = None,
    sigma_delta_frozen: Optional[SigmaDeltaFrozen] = None,
    yellow_multiplier: Optional[float] = None,
) -> Tuple[PolicyParameterLedger, ExecutionPolicyBundle]:
    """Layer 2: explicit human sign-off updating ledger entries, recording history, and issuing `P6`."""
    if not operator.strip() or not rationale.strip() or not new_policy_version.strip():
        raise ValueError("Human sign-off requires non-empty operator, rationale, and new_policy_version")
    ts = ensure_utc_datetime(signed_at_utc, field_name="signoff.signed_at_utc")
    new_entries = dict(ledger.entries)
    changed: List[str] = []
    if friction_median is not None:
        new_entries["friction_median"] = ParameterLedgerEntry(
            "friction_median", float(friction_median), "P8-CAPITAL-CONFIG §7 / D-A1", note=rationale
        )
        changed.append("friction_median")
    if yellow_multiplier is not None:
        new_entries["yellow_multiplier"] = ParameterLedgerEntry(
            "yellow_multiplier", float(yellow_multiplier), "P8-D6-POLICY-CLOSURE §六", note=reason_or_default(rationale)
        )
        changed.append("yellow_multiplier")
    new_sd = sigma_delta_frozen or ledger.sigma_delta_frozen
    if sigma_delta_frozen is not None:
        changed.append("sigma_delta_frozen")

    record = ParameterReplacementRecord(ts, operator, new_policy_version, rationale, tuple(changed))
    updated = PolicyParameterLedger(
        policy_version=new_policy_version,
        signed_at_utc=ts,
        sigma_delta_frozen=new_sd,
        entries=new_entries,
        m_floor=ledger.m_floor,
        tau_max_h=ledger.tau_max_h,
        station_cap_usd=ledger.station_cap_usd,
        w_provenance=ledger.w_provenance,
        scaler_policy_id=ledger.scaler_policy_id,
        scaler_provisional=ledger.scaler_provisional,
        scaler_provenance=ledger.scaler_provenance,
        review_interval_days=ledger.review_interval_days,
        replacement_history=(*ledger.replacement_history, record),
    )
    return updated, issue_policy_bundle(updated, signed_at_utc=ts, is_overdue=False)


def reason_or_default(text: str) -> str:
    return text.strip() or "manual_signoff"


def is_review_overdue(ledger: PolicyParameterLedger, *, as_of_utc: datetime) -> bool:
    """Return True if current UTC time exceeds `signed_at_utc + review_interval_days`."""
    now_utc = ensure_utc_datetime(as_of_utc, field_name="overdue.as_of_utc")
    due = ledger.signed_at_utc + timedelta(days=ledger.review_interval_days)
    due_trigger = datetime(
        due.year,
        due.month,
        due.day,
        DEFAULT_REVIEW_TRIGGER_HOUR_UTC,
        DEFAULT_REVIEW_TRIGGER_MINUTE_UTC,
        tzinfo=timezone.utc,
    )
    return now_utc >= max(due, due_trigger)


def build_overdue_hold_bundle(
    *,
    ledger: PolicyParameterLedger,
    current_bundle: ExecutionPolicyBundle,
    as_of_utc: datetime,
) -> OverdueHoldOutcome:
    """Layer 3 (`B6`): preserve exact frozen params & hash with `is_overdue=True` without halt/shrink."""
    now_utc = ensure_utc_datetime(as_of_utc, field_name="hold.as_of_utc")
    held = ExecutionPolicyBundle(
        policy_version=current_bundle.policy_version,
        config_hash=current_bundle.config_hash,
        signed_at_utc=current_bundle.signed_at_utc,
        is_overdue=True,
        w_policy=current_bundle.w_policy,
        phi_policy=current_bundle.phi_policy,
        risk_gate=current_bundle.risk_gate,
        scaler_policy_id=current_bundle.scaler_policy_id,
        scaler_provisional=current_bundle.scaler_provisional,
        scaler_provenance=current_bundle.scaler_provenance,
    )
    msg = (
        f"POLICY_REVIEW_OVERDUE: policy_version={held.policy_version} config_hash={held.config_hash} "
        f"as_of={now_utc.isoformat()}; conservative hold active without parameter change"
    )
    return OverdueHoldOutcome(bundle=held, reminder_message=msg)


class P16Broadcaster:
    """Unidirectional `M8 -> M4 + M6` `P16` broadcaster (`LightLevelEvent` + `TierStepUpEvent`)."""

    def __init__(
        self,
        *,
        m4_slot: P16SubscriptionSlot,
        m6_bankroll: BankrollAccountManager,
        extra_step_up_listeners: Sequence[Callable[[TierStepUpEvent], None]] = (),
    ) -> None:
        self._m4_slot = m4_slot
        self._m6_bankroll = m6_bankroll
        self._step_up_listeners = list(extra_step_up_listeners)

    def broadcast_light_level(
        self,
        *,
        event_id: str,
        level: LightLevel,
        reason: str,
        emitted_ts_utc: datetime,
        station_id: Optional[str] = None,
    ) -> LightLevelEvent:
        if not reason.strip():
            raise ValueError("P16 LightLevelEvent reason must be non-empty")
        if level == "YELLOW" and reason not in ALLOWED_YELLOW_REASONS:
            raise ValueError(
                f"YELLOW P16 event requires typed D-6 §5 reason in {sorted(ALLOWED_YELLOW_REASONS)}, got {reason!r}"
            )
        ev = LightLevelEvent(
            event_id=event_id,
            level=level,
            reason=reason,
            emitted_ts_utc=ensure_utc_datetime(emitted_ts_utc, field_name="p16.emitted_ts_utc"),
            station_id=station_id,
        )
        self._m4_slot.publish(ev)
        self._m6_bankroll.on_p16_event(ev)
        return ev

    def broadcast_tier_step_up(
        self,
        *,
        event_id: str,
        added_usd: Decimal,
        new_tier_pool_usd: Decimal,
        emitted_ts_utc: datetime,
        reason: str,
        is_full_deployment: bool = False,
    ) -> TierStepUpEvent:
        step = TierStepUpEvent(
            event_id=event_id,
            added_usd=added_usd,
            new_tier_pool_usd=new_tier_pool_usd,
            emitted_ts_utc=ensure_utc_datetime(emitted_ts_utc, field_name="p16.step_up_ts_utc"),
            reason=reason,
            is_full_deployment=is_full_deployment,
        )
        self._m6_bankroll.apply_tier_step_up(step)
        for listener in tuple(self._step_up_listeners):
            listener(step)
        return step
