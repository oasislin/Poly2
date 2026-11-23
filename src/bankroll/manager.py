"""`BankrollAccountManager` (`M6`): Decimal-exact ledger, `P7/P14/P15/P16` ports, & `P19` audit sink.

Anchors:
- `P8-T4-M4M5-INTERFACE v1.1 §3.1 & §3.5` (`P7 QuotaProvider`, `P14 Freeze/Loopback`)
- `P8-CAPITAL-CONFIG v1.0 §4 & §6.4` (`-$500/station`, `25%` drawdown exempt `<= $2,000`
  until first `+$1,000` step-up or full deployment, never auto-closes held positions)
- `P8-D6-POLICY-CLOSURE v1.0 §1.3 & §6` (`P16 -> M6 -> P19 LIGHT_LEVEL_APPLIED`)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable, Dict, Optional, Set, Tuple

from src.audit.audit_logger import AsyncAuditLogger
from src.audit.p19_events import CapitalEventLog, CapitalEventType, build_capital_event_log
from src.bankroll.models import (
    BankrollConfig,
    BankrollStateSnapshot,
    FillSettleLoopback,
    FreezeReceipt,
    FreezeRequest,
    P15SettlementEvent,
    TierStepUpEvent,
    to_bankroll_decimal,
)
from src.bankroll.risk_controller import (
    compute_station_quota,
    evaluate_drawdown_status,
    resolve_hard_block_reason,
)
from src.decision.engine import LightLevelEvent, QuotaQuery, QuotaSnapshot


@dataclass(frozen=True)
class _FrozenLot:
    decision_id: str
    idempotency_key: str
    station_id: str
    market_id: str
    amount_usd: Decimal


class BankrollAccountManager:
    """`M6` production capital manager implementing `QuotaProvider`, `P14`, `P15`, and `P16`."""

    def __init__(
        self,
        config: BankrollConfig,
        *,
        audit_logger: Optional[AsyncAuditLogger] = None,
        p19_sink: Optional[Callable[[CapitalEventLog], None]] = None,
    ) -> None:
        self._config = config
        self._audit_logger = audit_logger
        self._p19_sink = p19_sink
        self._policy_version = config.policy_version
        self._config_hash = config.config_hash
        self._is_overdue = config.is_overdue
        self._tier_pool_usd = config.initial_pool_usd
        self._free_usd = config.initial_pool_usd
        self._peak_equity_usd = config.initial_pool_usd
        self._drawdown_brake_enabled = bool(
            config.full_deployment
            or config.initial_pool_usd > config.drawdown_activation_threshold_usd
        )
        self._drawdown_brake_tripped = False
        self._frozen_by_decision: Dict[str, _FrozenLot] = {}
        self._freeze_receipts: Dict[str, FreezeReceipt] = {}
        self._held_by_market: Dict[Tuple[str, str], Decimal] = {}
        self._fee_by_market: Dict[Tuple[str, str], Decimal] = {}
        self._fee_paid_total_usd: Decimal = Decimal("0")
        self._realized_pnl_by_station: Dict[str, Decimal] = {}
        self._tripped_stations: Set[str] = set()
        self._settled_attempts: Dict[str, Decimal] = {}
        self._settled_p15_ids: Dict[str, Decimal] = {}
        self._light_status: Optional[str] = None
        self._consecutive_green_months = 0

    @property
    def active_locked_usd(self) -> Decimal:
        """Total pending `P14` frozen cash awaiting order settlement."""
        return sum(
            (lot.amount_usd for lot in self._frozen_by_decision.values()),
            Decimal("0"),
        )

    @property
    def held_total_usd(self) -> Decimal:
        """Total open held cost basis across all `(station_id, market_id)` positions."""
        return sum(self._held_by_market.values(), Decimal("0"))

    @property
    def realized_pnl_total_usd(self) -> Decimal:
        """Total cumulative realized PnL across all stations."""
        return sum(self._realized_pnl_by_station.values(), Decimal("0"))

    @property
    def equity_usd(self) -> Decimal:
        """Total equity (`free + active_locked + sum(held)`)."""
        return self._free_usd + self.active_locked_usd + self.held_total_usd

    @property
    def fee_paid_total_usd(self) -> Decimal:
        """Total cumulative execution fees recorded through `P14` fill settlements."""
        return self._fee_paid_total_usd

    def position_cost_basis_incl_fee(self, station_id: str, market_id: str) -> Decimal:
        """Return fee-inclusive cost basis (`held + fee`) for open `(station_id, market_id)`."""
        key = (station_id, market_id)
        return self._held_by_market.get(key, Decimal("0")) + self._fee_by_market.get(key, Decimal("0"))

    @property
    def conservation_residual_usd(self) -> Decimal:
        """Must remain `Decimal('0')` (`free + active_locked + held + fee - (tier_pool + realized_pnl)`)."""
        expected = self._tier_pool_usd + self.realized_pnl_total_usd
        return (self.equity_usd + self._fee_paid_total_usd) - expected

    def _station_active_locked(self, station_id: str) -> Decimal:
        return sum(
            (lot.amount_usd for lot in self._frozen_by_decision.values() if lot.station_id == station_id),
            Decimal("0"),
        )

    def _station_held_total(self, station_id: str) -> Decimal:
        return sum(
            (amt for (sid, _), amt in self._held_by_market.items() if sid == station_id),
            Decimal("0"),
        )

    def _emit_p19(
        self,
        *,
        ts_utc: datetime,
        event_type: CapitalEventType,
        station_id: Optional[str],
        related_ref_id: Optional[str],
        reason: str,
        tier_pool_override: Optional[float] = None,
        station_pnl_override: Optional[float] = None,
    ) -> CapitalEventLog:
        ev = build_capital_event_log(
            event_ts_utc=ts_utc,
            session_id=self._config.session_id,
            execution_mode=self._config.execution_mode,
            station_id=station_id,
            event_type=event_type,
            light_status=self._light_status,
            tier_pool_usd=tier_pool_override,
            free_usd_after=float(self._free_usd),
            active_locked_usd_after=float(self.active_locked_usd),
            station_realized_pnl_usd=station_pnl_override,
            policy_version=self._policy_version,
            config_hash=self._config_hash,
            is_overdue=self._is_overdue,
            related_ref_id=related_ref_id,
            reason=reason,
        )
        if self._audit_logger is not None:
            self._audit_logger.log_p19_capital_event(ev)
        if self._p19_sink is not None:
            self._p19_sink(ev)
        return ev

    def sync_policy_context(
        self,
        *,
        policy_version: str,
        config_hash: str,
        is_overdue: bool,
    ) -> None:
        """Update active `P6` metadata attached to emitted `P19` capital logs."""
        self._policy_version = policy_version
        self._config_hash = config_hash
        self._is_overdue = bool(is_overdue)

    def increment_green_month(self, months: int = 1) -> int:
        """Advance consecutive `GREEN` month counter (only when currently `GREEN`)."""
        if months < 0:
            raise ValueError(f"months must be >= 0, got {months}")
        if self._light_status == "GREEN":
            self._consecutive_green_months += months
        return self._consecutive_green_months

    def snapshot_state(self) -> BankrollStateSnapshot:
        """Return exact-`Decimal` diagnostic snapshot of all buckets and drawdown state."""
        dd = evaluate_drawdown_status(
            tier_pool_usd=self._tier_pool_usd,
            peak_equity_usd=self._peak_equity_usd,
            current_equity_usd=self.equity_usd,
            brake_enabled=self._drawdown_brake_enabled,
            brake_already_tripped=self._drawdown_brake_tripped,
            drawdown_brake_ratio=self._config.drawdown_brake_ratio,
        )
        return BankrollStateSnapshot(
            tier_pool_usd=self._tier_pool_usd,
            free_usd=self._free_usd,
            active_locked_usd=self.active_locked_usd,
            held_total_usd=self.held_total_usd,
            peak_equity_usd=dd.new_peak_equity_usd,
            drawdown_usd=dd.drawdown_usd,
            drawdown_ratio=dd.drawdown_ratio,
            drawdown_brake_enabled=self._drawdown_brake_enabled,
            drawdown_brake_tripped=self._drawdown_brake_tripped,
            tripped_station_gates=tuple(sorted(self._tripped_stations)),
            light_status=self._light_status,
            consecutive_green_months=self._consecutive_green_months,
            realized_pnl_total_usd=self.realized_pnl_total_usd,
            conservation_residual_usd=self.conservation_residual_usd,
            fee_paid_total_usd=self._fee_paid_total_usd,
        )

    def query_quota(self, query: QuotaQuery) -> QuotaSnapshot:
        """`P7 QuotaProvider` port returning `QuotaSnapshot` for `(station_id, market_id)`."""
        sid, mid = query.station_id, query.market_id
        return compute_station_quota(
            station_id=sid,
            market_id=mid,
            free_usd=self._free_usd,
            station_active_locked_usd=self._station_active_locked(sid),
            station_held_total_usd=self._station_held_total(sid),
            market_held_usd=self._held_by_market.get((sid, mid), Decimal("0")),
            station_cap_usd=self._config.station_cap_usd,
            station_realized_pnl_usd=self._realized_pnl_by_station.get(sid, Decimal("0")),
            station_loss_gate_tripped=(sid in self._tripped_stations),
            drawdown_brake_tripped=self._drawdown_brake_tripped,
            light_status=self._light_status,
        )

    def on_p16_event(
        self,
        event: LightLevelEvent,
        *,
        tier_step_up: Optional[TierStepUpEvent] = None,
    ) -> None:
        """Handle `P16 LightLevelEvent`: reset green streak on `YELLOW` & emit `P19`."""
        self._light_status = event.level
        if event.level == "YELLOW":
            self._consecutive_green_months = 0
        self._emit_p19(
            ts_utc=event.emitted_ts_utc,
            event_type="LIGHT_LEVEL_APPLIED",
            station_id=event.station_id,
            related_ref_id=event.event_id,
            reason=event.reason,
            tier_pool_override=float(self._tier_pool_usd),
        )
        if tier_step_up is not None:
            self.apply_tier_step_up(tier_step_up)

    def apply_tier_step_up(self, step_up: TierStepUpEvent) -> None:
        """Apply principal step-up, enable 25% drawdown brake per `§4 L40-45`, emit `P19`."""
        expected_pool = self._tier_pool_usd + step_up.added_usd
        if expected_pool != step_up.new_tier_pool_usd:
            raise ValueError(
                f"Step-up pool mismatch: {expected_pool} != {step_up.new_tier_pool_usd}"
            )
        self._tier_pool_usd = step_up.new_tier_pool_usd
        self._free_usd += step_up.added_usd
        self._peak_equity_usd = max(self._peak_equity_usd, self.equity_usd)
        if (
            step_up.is_full_deployment
            or step_up.added_usd > Decimal("0")
            or self._tier_pool_usd > self._config.drawdown_activation_threshold_usd
        ):
            self._drawdown_brake_enabled = True
        self._emit_p19(
            ts_utc=step_up.emitted_ts_utc,
            event_type="TIER_STEP_UP",
            station_id=None,
            related_ref_id=step_up.event_id,
            reason=step_up.reason,
            tier_pool_override=float(self._tier_pool_usd),
        )

    def _validate_freeze_request(self, req: FreezeRequest) -> Optional[str]:
        if req.decision_id in self._frozen_by_decision:
            raise ValueError(f"Duplicate active freeze for decision_id={req.decision_id!r}")
        hard_block = resolve_hard_block_reason(
            drawdown_brake_tripped=self._drawdown_brake_tripped,
            station_loss_gate_tripped=(req.station_id in self._tripped_stations),
            light_status=self._light_status,
        )
        if hard_block is not None:
            return hard_block
        if req.target_freeze_usd > self._free_usd:
            return "INSUFFICIENT_FREE_USD"
        committed = (
            self._station_active_locked(req.station_id)
            + self._station_held_total(req.station_id)
        )
        if committed + req.target_freeze_usd > self._config.station_cap_usd:
            return "STATION_CAP_EXCEEDED"
        return None

    def freeze_for_order(self, req: FreezeRequest) -> FreezeReceipt:
        """`P14 FREEZE` entry: idempotent key dedup & Fail-Closed on gates/cap/cash."""
        cached = self._freeze_receipts.get(req.idempotency_key)
        if cached is not None:
            return FreezeReceipt(
                accepted=cached.accepted, decision_id=cached.decision_id,
                idempotency_key=cached.idempotency_key, frozen_usd=cached.frozen_usd,
                blocked_reason=cached.blocked_reason, recorded_ts_utc=cached.recorded_ts_utc,
                deduplicated=True,
            )
        block_reason = self._validate_freeze_request(req)
        if block_reason is not None:
            receipt = FreezeReceipt(
                accepted=False, decision_id=req.decision_id,
                idempotency_key=req.idempotency_key, frozen_usd=Decimal("0"),
                blocked_reason=block_reason, recorded_ts_utc=req.requested_ts_utc,
            )
            self._freeze_receipts[req.idempotency_key] = receipt
            return receipt
        self._free_usd -= req.target_freeze_usd
        self._frozen_by_decision[req.decision_id] = _FrozenLot(
            decision_id=req.decision_id, idempotency_key=req.idempotency_key,
            station_id=req.station_id, market_id=req.market_id, amount_usd=req.target_freeze_usd,
        )
        self._emit_p19(
            ts_utc=req.requested_ts_utc, event_type="FREEZE", station_id=req.station_id,
            related_ref_id=req.decision_id, reason=f"P14_FREEZE:{req.idempotency_key}",
        )
        receipt = FreezeReceipt(
            accepted=True, decision_id=req.decision_id,
            idempotency_key=req.idempotency_key, frozen_usd=req.target_freeze_usd,
            blocked_reason=None, recorded_ts_utc=req.requested_ts_utc,
        )
        self._freeze_receipts[req.idempotency_key] = receipt
        return receipt

    def settle_order_fill(self, loopback: FillSettleLoopback) -> Decimal:
        """`P14` IOC loopback: convert filled USD to `held`, account fee, refund remainder."""
        if loopback.attempt_id in self._settled_attempts:
            return self._settled_attempts[loopback.attempt_id]
        if loopback.terminal_status in ("CANCELLED_UNFILLED", "REJECTED", "PAPER_MATCH_ABORTED_GAP"):
            if loopback.filled_usd > Decimal("0") or loopback.fee_paid_usd > Decimal("0"):
                raise ValueError(
                    f"Non-fill status {loopback.terminal_status} has filled_usd={loopback.filled_usd}, fee_paid_usd={loopback.fee_paid_usd}"
                )
            reason = loopback.reject_or_abort_reason or loopback.terminal_status
            return self.release_unfill(
                decision_id=loopback.decision_id, attempt_id=loopback.attempt_id,
                ts_utc=loopback.settled_ts_utc, reason=reason,
            )
        lot = self._frozen_by_decision.pop(loopback.decision_id)
        total_cash_spent = loopback.filled_usd + loopback.fee_paid_usd
        if total_cash_spent > lot.amount_usd:
            self._frozen_by_decision[loopback.decision_id] = lot
            raise ValueError(f"filled+fee {total_cash_spent} exceeds frozen {lot.amount_usd}")
        self._free_usd += lot.amount_usd - total_cash_spent
        key = (lot.station_id, lot.market_id)
        self._held_by_market[key] = self._held_by_market.get(key, Decimal("0")) + loopback.filled_usd
        if loopback.fee_paid_usd > Decimal("0"):
            self._fee_by_market[key] = self._fee_by_market.get(key, Decimal("0")) + loopback.fee_paid_usd
            self._fee_paid_total_usd += loopback.fee_paid_usd
        self._settled_attempts[loopback.attempt_id] = total_cash_spent
        self._emit_p19(
            ts_utc=loopback.settled_ts_utc, event_type="FILL_SETTLE_CONVERSION",
            station_id=lot.station_id, related_ref_id=loopback.attempt_id,
            reason=f"P14_{loopback.terminal_status}:{loopback.decision_id}",
        )
        return total_cash_spent

    def release_unfill(
        self,
        *,
        decision_id: str,
        attempt_id: str,
        ts_utc: datetime,
        reason: str,
    ) -> Decimal:
        """`P14 UNFREEZE`: return full frozen cash to `free_usd` & emit `P19 UNFREEZE`."""
        if attempt_id in self._settled_attempts:
            return self._settled_attempts[attempt_id]
        lot = self._frozen_by_decision.pop(decision_id)
        self._free_usd += lot.amount_usd
        self._settled_attempts[attempt_id] = lot.amount_usd
        self._emit_p19(
            ts_utc=ts_utc,
            event_type="UNFREEZE",
            station_id=lot.station_id,
            related_ref_id=attempt_id,
            reason=f"P14_UNFREEZE:{reason}",
        )
        return lot.amount_usd

    def _reconcile_gates_after_pnl(
        self,
        *,
        station_id: str,
        ts_utc: datetime,
        ref_id: str,
    ) -> None:
        station_pnl = self._realized_pnl_by_station.get(station_id, Decimal("0"))
        if station_id not in self._tripped_stations and station_pnl <= -self._config.station_loss_gate_usd:
            self._tripped_stations.add(station_id)
            self._emit_p19(
                ts_utc=ts_utc,
                event_type="STATION_LOSS_GATE_TRIP",
                station_id=station_id,
                related_ref_id=ref_id,
                reason=f"STATION_REALIZED_LOSS_GE_{self._config.station_loss_gate_usd}",
                station_pnl_override=float(station_pnl),
            )
        dd = evaluate_drawdown_status(
            tier_pool_usd=self._tier_pool_usd,
            peak_equity_usd=self._peak_equity_usd,
            current_equity_usd=self.equity_usd,
            brake_enabled=self._drawdown_brake_enabled,
            brake_already_tripped=self._drawdown_brake_tripped,
            drawdown_brake_ratio=self._config.drawdown_brake_ratio,
        )
        self._peak_equity_usd = dd.new_peak_equity_usd
        if dd.newly_tripped:
            self._drawdown_brake_tripped = True
            self._emit_p19(
                ts_utc=ts_utc,
                event_type="ACCOUNT_DRAWDOWN_BRAKE_TRIP",
                station_id=None,
                related_ref_id=ref_id,
                reason=f"DRAWDOWN_GE_{self._config.drawdown_brake_ratio}",
                tier_pool_override=float(self._tier_pool_usd),
            )

    def apply_p15_settlement(self, event: P15SettlementEvent) -> Decimal:
        """Idempotent `P15` settlement entry: release `held`, update realized PnL, check gates."""
        if event.settlement_id in self._settled_p15_ids:
            return self._settled_p15_ids[event.settlement_id]
        key = (event.station_id, event.market_id)
        held_amt = self._held_by_market.get(key, Decimal("0"))
        cost_basis = held_amt if event.cost_basis_usd is None else to_bankroll_decimal(
            event.cost_basis_usd, name="p15.cost_basis_usd"
        )
        if cost_basis > held_amt:
            raise ValueError(f"Settlement cost_basis {cost_basis} exceeds held {held_amt} for {key}")
        remaining = held_amt - cost_basis
        if remaining == Decimal("0"):
            self._held_by_market.pop(key, None)
            self._fee_by_market.pop(key, None)
        else:
            self._held_by_market[key] = remaining
        self._free_usd += event.payout_usd
        pnl = event.payout_usd - cost_basis
        self._realized_pnl_by_station[event.station_id] = (
            self._realized_pnl_by_station.get(event.station_id, Decimal("0")) + pnl
        )
        self._settled_p15_ids[event.settlement_id] = pnl
        self._reconcile_gates_after_pnl(
            station_id=event.station_id,
            ts_utc=event.settled_ts_utc,
            ref_id=event.settlement_id,
        )
        return pnl
