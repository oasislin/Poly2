"""Pure `Decimal` risk-gate, drawdown-brake, and `P7` quota evaluation helpers (`M6`).

Anchors:
- `P8-CAPITAL-CONFIG v1.0 §4 & §6.4`: `-$500/station` local loss gate, `25%` drawdown
  brake exempt while `<= $2,000` until first step-up or full deployment, never auto-closes positions.
- `P8-T4-M4M5-INTERFACE v1.1 §3.1` (`N8`): concurrent-day headroom floor cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from src.decision.engine import QuotaSnapshot


@dataclass(frozen=True)
class DrawdownEvaluation:
    """Result of evaluating 25% account drawdown against tier pool."""

    new_peak_equity_usd: Decimal
    drawdown_usd: Decimal
    drawdown_ratio: Decimal
    newly_tripped: bool
    is_tripped: bool


def evaluate_drawdown_status(
    *,
    tier_pool_usd: Decimal,
    peak_equity_usd: Decimal,
    current_equity_usd: Decimal,
    brake_enabled: bool,
    brake_already_tripped: bool,
    drawdown_brake_ratio: Decimal,
) -> DrawdownEvaluation:
    """Compute drawdown metrics and trigger state (`<= $2,000` phase is read-only)."""
    new_peak = max(peak_equity_usd, current_equity_usd)
    drawdown = max(Decimal("0"), new_peak - current_equity_usd)
    ratio = drawdown / tier_pool_usd if tier_pool_usd > Decimal("0") else Decimal("0")
    threshold = tier_pool_usd * drawdown_brake_ratio
    breached = brake_enabled and drawdown >= threshold
    is_tripped = brake_already_tripped or breached
    newly_tripped = (not brake_already_tripped) and breached
    return DrawdownEvaluation(
        new_peak_equity_usd=new_peak,
        drawdown_usd=drawdown,
        drawdown_ratio=ratio,
        newly_tripped=newly_tripped,
        is_tripped=is_tripped,
    )


def resolve_hard_block_reason(
    *,
    drawdown_brake_tripped: bool,
    station_loss_gate_tripped: bool,
    light_status: Optional[str],
) -> Optional[str]:
    """Resolve highest-priority Fail-Closed block reason (`drawdown > loss_gate > RED`)."""
    if drawdown_brake_tripped:
        return "ACCOUNT_DRAWDOWN_BRAKE_TRIPPED"
    if station_loss_gate_tripped:
        return "STATION_LOSS_GATE_TRIPPED"
    if light_status == "RED":
        return "P16_RED_LIGHT_BLOCKED"
    return None


def compute_station_quota(
    *,
    station_id: str,
    market_id: str,
    free_usd: Decimal,
    station_active_locked_usd: Decimal,
    station_held_total_usd: Decimal,
    market_held_usd: Decimal,
    station_cap_usd: Decimal,
    station_realized_pnl_usd: Decimal,
    station_loss_gate_tripped: bool,
    drawdown_brake_tripped: bool,
    light_status: Optional[str],
) -> QuotaSnapshot:
    """Build `P7 QuotaSnapshot` enforcing hard brakes and `N8` station headroom cap."""
    blocked_reason = resolve_hard_block_reason(
        drawdown_brake_tripped=drawdown_brake_tripped,
        station_loss_gate_tripped=station_loss_gate_tripped,
        light_status=light_status,
    )
    if blocked_reason is not None:
        headroom = Decimal("0")
    else:
        committed = station_active_locked_usd + station_held_total_usd
        station_remaining = max(Decimal("0"), station_cap_usd - committed)
        headroom = max(Decimal("0"), min(free_usd, station_remaining))
    realized_loss = max(Decimal("0"), -station_realized_pnl_usd)
    return QuotaSnapshot(
        station_id=station_id,
        market_id=market_id,
        free_usd=float(free_usd),
        station_active_locked_usd=float(station_active_locked_usd),
        market_held_usd=float(market_held_usd),
        station_cap_usd=float(station_cap_usd),
        station_realized_loss_usd=float(realized_loss),
        station_loss_gate_tripped=station_loss_gate_tripped,
        account_drawdown_brake_tripped=drawdown_brake_tripped,
        b_eff_headroom_usd=float(headroom),
        blocked_reason=blocked_reason,
    )
