"""Typed `P14`, `P15`, `TierStepUp`, and configuration models for `src/bankroll/` (`M6`).

Anchors:
- `P8-T4-M4M5-INTERFACE v1.1 §3.1 & §3.5` (`P7 QuotaSnapshot`, `P14 Freeze/Loopback`)
- `P8-CAPITAL-CONFIG v1.0 §4 & §6.4` (tier pool, exempt <= $2,000 rule, no auto-close)
- `P8-D6-POLICY-CLOSURE v1.0 §1.3 & §6` (`P16 -> M6 -> P19 LIGHT_LEVEL_APPLIED`)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional, Tuple

from src.audit.p19_events import ExecutionMode
from src.utils.causal_utils import ensure_utc_datetime
from src.utils.decimal_guard import to_guarded_decimal

P14TerminalStatus = Literal[
    "FILLED",
    "PARTIAL",
    "CANCELLED_UNFILLED",
    "REJECTED",
    "PAPER_MATCH_ABORTED_GAP",
]
BlockedReason = Literal[
    "ACCOUNT_DRAWDOWN_BRAKE_TRIPPED",
    "STATION_LOSS_GATE_TRIPPED",
    "P16_RED_LIGHT_BLOCKED",
    "INSUFFICIENT_FREE_USD",
    "STATION_CAP_EXCEEDED",
]


def to_bankroll_decimal(value: Decimal | float | int | str, *, name: str) -> Decimal:
    """Convert numeric inputs safely to `Decimal` without binary float contamination."""
    digits = 18 if isinstance(value, float) else 12
    return to_guarded_decimal(value, name=name, max_sig_digits=digits)


@dataclass(frozen=True)
class FreezeRequest:
    """`P14 FreezeRequest v1.0` (`M5 -> M6`): pre-freeze cash before order submit."""

    decision_id: str
    idempotency_key: str
    station_id: str
    market_id: str
    token_id: str
    target_freeze_usd: Decimal
    requested_ts_utc: datetime

    def __post_init__(self) -> None:
        if not self.decision_id or not self.idempotency_key:
            raise ValueError("FreezeRequest decision_id and idempotency_key must be non-empty")
        amt = to_bankroll_decimal(self.target_freeze_usd, name="FreezeRequest.target_freeze_usd")
        if amt <= Decimal("0"):
            raise ValueError(f"target_freeze_usd must be > 0, got {amt}")
        object.__setattr__(self, "target_freeze_usd", amt)
        ensure_utc_datetime(self.requested_ts_utc, field_name="FreezeRequest.requested_ts_utc")


@dataclass(frozen=True)
class FreezeReceipt:
    """`P14 FreezeReceipt v1.0` (`M6 -> M5`): Fail-Closed freeze acknowledgement."""

    accepted: bool
    decision_id: str
    idempotency_key: str
    frozen_usd: Decimal
    blocked_reason: Optional[str]
    recorded_ts_utc: datetime
    deduplicated: bool = False


@dataclass(frozen=True)
class FillSettleLoopback:
    """`P14 FillSettleLoopback v1.0` (`M5 -> M6`): post-IOC fill conversion or unfreeze."""

    decision_id: str
    attempt_id: str
    station_id: str
    market_id: str
    filled_usd: Decimal
    terminal_status: P14TerminalStatus
    settled_ts_utc: datetime
    reject_or_abort_reason: Optional[str] = None
    fee_paid_usd: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.decision_id or not self.attempt_id:
            raise ValueError("FillSettleLoopback decision_id and attempt_id must be non-empty")
        amt = to_bankroll_decimal(self.filled_usd, name="FillSettleLoopback.filled_usd")
        if amt < Decimal("0"):
            raise ValueError(f"filled_usd must be >= 0, got {amt}")
        fee = to_bankroll_decimal(self.fee_paid_usd, name="FillSettleLoopback.fee_paid_usd")
        if fee < Decimal("0"):
            raise ValueError(f"fee_paid_usd must be >= 0, got {fee}")
        object.__setattr__(self, "filled_usd", amt)
        object.__setattr__(self, "fee_paid_usd", fee)
        ensure_utc_datetime(self.settled_ts_utc, field_name="FillSettleLoopback.settled_ts_utc")


@dataclass(frozen=True)
class TierStepUpEvent:
    """Manual/governance capital tier step-up (`+$1,000` or full deployment)."""

    event_id: str
    added_usd: Decimal
    new_tier_pool_usd: Decimal
    emitted_ts_utc: datetime
    reason: str
    is_full_deployment: bool = False

    def __post_init__(self) -> None:
        added = to_bankroll_decimal(self.added_usd, name="TierStepUpEvent.added_usd")
        pool = to_bankroll_decimal(self.new_tier_pool_usd, name="TierStepUpEvent.new_tier_pool_usd")
        if added <= Decimal("0") or pool <= Decimal("0"):
            raise ValueError("TierStepUpEvent added_usd and new_tier_pool_usd must be > 0")
        object.__setattr__(self, "added_usd", added)
        object.__setattr__(self, "new_tier_pool_usd", pool)
        ensure_utc_datetime(self.emitted_ts_utc, field_name="TierStepUpEvent.emitted_ts_utc")


@dataclass(frozen=True)
class P15SettlementEvent:
    """`P15 SettlementEvent` port (`M9 -> M6`, reserved for `S3-09`)."""

    settlement_id: str
    station_id: str
    market_id: str
    payout_usd: Decimal
    settled_ts_utc: datetime
    cost_basis_usd: Optional[Decimal] = None

    def __post_init__(self) -> None:
        if not self.settlement_id:
            raise ValueError("P15SettlementEvent.settlement_id must be non-empty")
        payout = to_bankroll_decimal(self.payout_usd, name="P15SettlementEvent.payout_usd")
        if payout < Decimal("0"):
            raise ValueError(f"payout_usd must be >= 0, got {payout}")
        object.__setattr__(self, "payout_usd", payout)
        if self.cost_basis_usd is not None:
            basis = to_bankroll_decimal(self.cost_basis_usd, name="P15SettlementEvent.cost_basis_usd")
            if basis < Decimal("0"):
                raise ValueError(f"cost_basis_usd must be >= 0, got {basis}")
            object.__setattr__(self, "cost_basis_usd", basis)
        ensure_utc_datetime(self.settled_ts_utc, field_name="P15SettlementEvent.settled_ts_utc")


@dataclass(frozen=True)
class BankrollConfig:
    """Configuration parameters for `BankrollAccountManager` (`CAPITAL-CONFIG v1.0`)."""

    session_id: str
    execution_mode: ExecutionMode
    policy_version: str
    config_hash: str
    is_overdue: bool = False
    initial_pool_usd: Decimal = Decimal("2000")
    station_cap_usd: Decimal = Decimal("500")
    station_loss_gate_usd: Decimal = Decimal("500")
    drawdown_brake_ratio: Decimal = Decimal("0.25")
    drawdown_activation_threshold_usd: Decimal = Decimal("2000")
    full_deployment: bool = False

    def __post_init__(self) -> None:
        pool = to_bankroll_decimal(self.initial_pool_usd, name="BankrollConfig.initial_pool_usd")
        cap = to_bankroll_decimal(self.station_cap_usd, name="BankrollConfig.station_cap_usd")
        gate = to_bankroll_decimal(self.station_loss_gate_usd, name="BankrollConfig.station_loss_gate_usd")
        ratio = to_bankroll_decimal(self.drawdown_brake_ratio, name="BankrollConfig.drawdown_brake_ratio")
        thresh = to_bankroll_decimal(
            self.drawdown_activation_threshold_usd,
            name="BankrollConfig.drawdown_activation_threshold_usd",
        )
        if pool <= Decimal("0") or cap <= Decimal("0") or gate <= Decimal("0"):
            raise ValueError("Pool, station_cap_usd, and station_loss_gate_usd must be > 0")
        if not (Decimal("0") < ratio <= Decimal("1")):
            raise ValueError(f"drawdown_brake_ratio must be in (0, 1], got {ratio}")
        object.__setattr__(self, "initial_pool_usd", pool)
        object.__setattr__(self, "station_cap_usd", cap)
        object.__setattr__(self, "station_loss_gate_usd", gate)
        object.__setattr__(self, "drawdown_brake_ratio", ratio)
        object.__setattr__(self, "drawdown_activation_threshold_usd", thresh)


@dataclass(frozen=True)
class BankrollStateSnapshot:
    """Immutable exact-`Decimal` diagnostic snapshot including conservation residual."""

    tier_pool_usd: Decimal
    free_usd: Decimal
    active_locked_usd: Decimal
    held_total_usd: Decimal
    peak_equity_usd: Decimal
    drawdown_usd: Decimal
    drawdown_ratio: Decimal
    drawdown_brake_enabled: bool
    drawdown_brake_tripped: bool
    tripped_station_gates: Tuple[str, ...]
    light_status: Optional[str]
    consecutive_green_months: int
    realized_pnl_total_usd: Decimal
    conservation_residual_usd: Decimal
    fee_paid_total_usd: Decimal = Decimal("0")
