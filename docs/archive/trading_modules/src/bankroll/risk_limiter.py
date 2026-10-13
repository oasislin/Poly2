"""
Global and Single-Market Risk Limiter (Phase 2 Task 05 - Ticket 04 / Issue #86).
Enforces ADR-0012 §D4:
- 10% Single Market Cap on effective bankroll (Bankroll_eff = Free + Active)
- 70% Global Active Utilization Cap on total bankroll (Active / Total <= 70%)
- Tiered Zombie Haircuts (Healthy=1.0x, Warning=0.5x, Halt=0.0x, SafeMode=0.0x)
- Full 6-decimal Decimal truncation (ROUND_DOWN).
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
import logging
from typing import List, Optional

from src.bankroll.bankroll_manager import BankrollManager
from src.bankroll.zombie_evaluator import LiquidityTier

logger = logging.getLogger(__name__)

PRECISION = Decimal("0.000001")


@dataclass(frozen=True)
class RiskLimiterConfig:
    """Configuration for risk limits and haircuts."""
    fractional_multiplier: Decimal = Decimal("0.25")
    single_market_cap_ratio: Decimal = Decimal("0.10")
    global_utilization_cap_ratio: Decimal = Decimal("0.70")
    precision: Decimal = PRECISION


@dataclass(frozen=True)
class RiskLimitResult:
    """Result of risk limit evaluation on candidate allocations."""
    is_approved: bool
    approved_allocations: List[Decimal]
    total_approved: Decimal
    is_throttled: bool
    throttle_reason: Optional[str]
    market_exposure_after: Decimal
    global_utilization_after: Decimal


class RiskLimiter:
    """
    Enforces risk constraints across portfolio, market, and operational dimensions.
    """

    def __init__(self, config: Optional[RiskLimiterConfig] = None):
        self.config = config or RiskLimiterConfig()

    def apply_limits(
        self,
        market_id: str,
        raw_allocations: List[Decimal],
        current_market_exposure: Decimal,
        bankroll_manager: BankrollManager,
        liquidity_tier: LiquidityTier = LiquidityTier.HEALTHY,
    ) -> RiskLimitResult:
        """
        Evaluate and throttle candidate allocations against risk rules.
        """
        zeros = [Decimal("0.000000") for _ in raw_allocations]
        total_bankroll = bankroll_manager.get_total_bankroll()
        effective_bankroll = bankroll_manager.get_effective_bankroll()
        bal = bankroll_manager.get_balance()
        free_usdc = bal.free_usdc
        active_locked = bal.active_locked

        # 1. Operational Zombie Tier Gates
        if liquidity_tier == LiquidityTier.CRITICAL_SAFE_MODE:
            logger.critical("RiskLimiter: Allocation rejected due to SAFE_MODE (R_z > 50%%)")
            return RiskLimitResult(
                is_approved=False,
                approved_allocations=zeros,
                total_approved=Decimal("0.000000"),
                is_throttled=True,
                throttle_reason="ZOMBIE_RATE_SAFE_MODE",
                market_exposure_after=current_market_exposure,
                global_utilization_after=bankroll_manager.get_utilization_ratio(),
            )

        if liquidity_tier == LiquidityTier.HALT_NEW_POSITIONS:
            logger.warning("RiskLimiter: Allocation halted due to HALT tier (R_z > 30%%)")
            return RiskLimitResult(
                is_approved=False,
                approved_allocations=zeros,
                total_approved=Decimal("0.000000"),
                is_throttled=True,
                throttle_reason="ZOMBIE_RATE_HALT",
                market_exposure_after=current_market_exposure,
                global_utilization_after=bankroll_manager.get_utilization_ratio(),
            )

        zombie_haircut = Decimal("0.5") if liquidity_tier == LiquidityTier.WARNING_HAIRCUT else Decimal("1.0")

        # 2. Base scaling: fractional Kelly and zombie haircut
        scaled_allocations = [
            (a * self.config.fractional_multiplier * zombie_haircut).quantize(
                self.config.precision, rounding=ROUND_DOWN
            )
            for a in raw_allocations
        ]
        sum_requested = sum(scaled_allocations, Decimal("0.000000"))

        if sum_requested <= Decimal("0.000000"):
            return RiskLimitResult(
                is_approved=True,
                approved_allocations=zeros,
                total_approved=Decimal("0.000000"),
                is_throttled=False,
                throttle_reason=None,
                market_exposure_after=current_market_exposure,
                global_utilization_after=bankroll_manager.get_utilization_ratio(),
            )

        # 3. Compute capacity headroom
        # Rule A: Single Market Cap (<= 10% of Bankroll_effective)
        max_market_exposure = (effective_bankroll * self.config.single_market_cap_ratio).quantize(
            self.config.precision, rounding=ROUND_DOWN
        )
        single_market_budget = max(Decimal("0.000000"), max_market_exposure - current_market_exposure)

        # Rule B: Global Utilization Cap (Active Locked / Total Bankroll <= 70%)
        max_active_locked = (total_bankroll * self.config.global_utilization_cap_ratio).quantize(
            self.config.precision, rounding=ROUND_DOWN
        )
        global_active_budget = max(Decimal("0.000000"), max_active_locked - active_locked)

        # Rule C: Available Cash
        cash_budget = free_usdc

        # Binding ceiling
        limiting_budget = min(single_market_budget, global_active_budget, cash_budget)

        is_throttled = (liquidity_tier == LiquidityTier.WARNING_HAIRCUT) or (sum_requested > limiting_budget)
        throttle_reasons = []

        if liquidity_tier == LiquidityTier.WARNING_HAIRCUT:
            throttle_reasons.append("ZOMBIE_RATE_WARNING_0.5X")

        if sum_requested > limiting_budget:
            if limiting_budget == single_market_budget:
                throttle_reasons.append("SINGLE_MARKET_CAP_EXCEEDED")
            elif limiting_budget == global_active_budget:
                throttle_reasons.append("GLOBAL_UTILIZATION_CAP_EXCEEDED")
            else:
                throttle_reasons.append("INSUFFICIENT_FREE_USDC")

        # Proportional scale down if exceeds limiting budget
        if sum_requested > limiting_budget:
            if limiting_budget <= Decimal("0.000000"):
                final_allocations = zeros
            else:
                scale = limiting_budget / sum_requested
                final_allocations = [
                    (a * scale).quantize(self.config.precision, rounding=ROUND_DOWN)
                    for a in scaled_allocations
                ]
                # Ensure truncation doesn't overshoot
                while sum(final_allocations, Decimal("0.000000")) > limiting_budget:
                    # Drop by 1 least significant digit on largest
                    max_idx = final_allocations.index(max(final_allocations))
                    final_allocations[max_idx] -= self.config.precision
        else:
            final_allocations = scaled_allocations

        total_approved = sum(final_allocations, Decimal("0.000000"))
        market_exposure_after = current_market_exposure + total_approved
        active_locked_after = active_locked + total_approved
        global_utilization_after = (
            (active_locked_after / total_bankroll).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
            if total_bankroll > Decimal("0.000000")
            else Decimal("0.0000")
        )

        return RiskLimitResult(
            is_approved=True,
            approved_allocations=final_allocations,
            total_approved=total_approved,
            is_throttled=is_throttled,
            throttle_reason="; ".join(throttle_reasons) if throttle_reasons else None,
            market_exposure_after=market_exposure_after,
            global_utilization_after=global_utilization_after,
        )
