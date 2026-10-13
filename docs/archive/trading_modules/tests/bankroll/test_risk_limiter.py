"""
Unit tests for Global and Single-Market RiskLimiter (Phase 2 Task 05 - Ticket 04 / Issue #86).
Verifies 10% single-market cap, 70% global active utilization cap, and tiered zombie haircut.
"""

from decimal import Decimal
import pytest

from src.bankroll.bankroll_manager import BankrollManager
from src.bankroll.zombie_evaluator import LiquidityTier
from src.bankroll.risk_limiter import RiskLimiter, RiskLimiterConfig, RiskLimitResult


class TestRiskLimiter:
    @pytest.fixture
    def manager(self):
        # Total = 100,000, Free = 80,000, Active = 20,000
        # Effective = Free + Active = 100,000
        mgr = BankrollManager(initial_free_usdc=Decimal("100000.000000"))
        mgr.lock_funds(Decimal("20000.000000"))
        return mgr

    @pytest.fixture
    def limiter(self):
        return RiskLimiter(
            RiskLimiterConfig(
                fractional_multiplier=Decimal("1.0"),  # Full kelly for direct testing
                single_market_cap_ratio=Decimal("0.10"),
                global_utilization_cap_ratio=Decimal("0.70"),
            )
        )

    def test_normal_allocation_within_limits(self, manager, limiter):
        # Raw allocation: [2000.0, 3000.0], total = 5000 (5% of 100k effective)
        raw_allocations = [Decimal("2000.000000"), Decimal("3000.000000")]
        result = limiter.apply_limits(
            market_id="ORD-2026-09-30-TMAX",
            raw_allocations=raw_allocations,
            current_market_exposure=Decimal("0.000000"),
            bankroll_manager=manager,
            liquidity_tier=LiquidityTier.HEALTHY,
        )

        assert result.is_approved
        assert result.total_approved == Decimal("5000.000000")
        assert result.approved_allocations == [Decimal("2000.000000"), Decimal("3000.000000")]
        assert result.is_throttled is False

    def test_single_market_10_percent_cap_truncation(self, manager, limiter):
        # Effective bankroll = 100,000, max single market = 10,000
        # Existing exposure = 4,000, max remaining budget = 6,000
        # Raw requested = 12,000 ([4000, 8000])
        # Should be scaled proportionally to 6,000 total ([2000, 4000])
        raw_allocations = [Decimal("4000.000000"), Decimal("8000.000000")]
        result = limiter.apply_limits(
            market_id="ORD-2026-09-30-TMAX",
            raw_allocations=raw_allocations,
            current_market_exposure=Decimal("4000.000000"),
            bankroll_manager=manager,
            liquidity_tier=LiquidityTier.HEALTHY,
        )

        assert result.is_approved
        assert result.is_throttled is True
        assert "SINGLE_MARKET_CAP" in (result.throttle_reason or "")
        assert result.total_approved == Decimal("6000.000000")
        assert result.approved_allocations == [Decimal("2000.000000"), Decimal("4000.000000")]

    def test_global_utilization_70_percent_cap(self, limiter):
        # Total bankroll = 100,000. Max active locked = 70,000.
        # Currently active locked = 68,000. Free = 32,000.
        # Available capacity = 70,000 - 68,000 = 2,000.
        # Raw requested = 5,000 -> must be capped at 2,000.
        mgr = BankrollManager(initial_free_usdc=Decimal("100000.000000"))
        mgr.lock_funds(Decimal("68000.000000"))

        raw_allocations = [Decimal("5000.000000")]
        result = limiter.apply_limits(
            market_id="MKT-NEW",
            raw_allocations=raw_allocations,
            current_market_exposure=Decimal("0.000000"),
            bankroll_manager=mgr,
            liquidity_tier=LiquidityTier.HEALTHY,
        )

        assert result.is_approved
        assert result.is_throttled is True
        assert "GLOBAL_UTILIZATION_CAP" in (result.throttle_reason or "")
        assert result.total_approved == Decimal("2000.000000")
        assert result.approved_allocations == [Decimal("2000.000000")]

    def test_zombie_tier_haircuts(self, manager, limiter):
        raw_allocations = [Decimal("4000.000000")]

        # 1. Warning tier: 0.5x haircut
        res_warning = limiter.apply_limits(
            market_id="MKT-1",
            raw_allocations=raw_allocations,
            current_market_exposure=Decimal("0.000000"),
            bankroll_manager=manager,
            liquidity_tier=LiquidityTier.WARNING_HAIRCUT,
        )
        assert res_warning.is_approved
        assert res_warning.total_approved == Decimal("2000.000000")
        assert res_warning.approved_allocations == [Decimal("2000.000000")]
        assert res_warning.is_throttled is True

        # 2. Halt tier: 0.0x (halted)
        res_halt = limiter.apply_limits(
            market_id="MKT-1",
            raw_allocations=raw_allocations,
            current_market_exposure=Decimal("0.000000"),
            bankroll_manager=manager,
            liquidity_tier=LiquidityTier.HALT_NEW_POSITIONS,
        )
        assert not res_halt.is_approved
        assert res_halt.total_approved == Decimal("0.000000")
        assert res_halt.approved_allocations == [Decimal("0.000000")]
        assert "HALT" in (res_halt.throttle_reason or "")

        # 3. Safe Mode tier: 0.0x (frozen)
        res_safe = limiter.apply_limits(
            market_id="MKT-1",
            raw_allocations=raw_allocations,
            current_market_exposure=Decimal("0.000000"),
            bankroll_manager=manager,
            liquidity_tier=LiquidityTier.CRITICAL_SAFE_MODE,
        )
        assert not res_safe.is_approved
        assert res_safe.total_approved == Decimal("0.000000")
        assert "SAFE_MODE" in (res_safe.throttle_reason or "")

    def test_insufficient_free_cash(self, limiter):
        # Total = 100,000, Active = 20,000, Zombie = 79,500, Free = 500
        # Effective = 20,500. Market cap room = 2,050.
        # Global utilization = 20,000 / 100,000 = 20% < 70% (room = 50,000).
        # Free cash is strictly 500.
        # Raw requested = 1000 -> must be capped at 500 due to INSUFFICIENT_FREE_USDC.
        mgr = BankrollManager(initial_free_usdc=Decimal("100000.000000"))
        mgr.lock_funds(Decimal("99500.000000"))
        mgr.transfer_to_zombie(Decimal("79500.000000"))
        # Now free is 500, active is 20000, zombie is 79500
        raw_allocations = [Decimal("1000.000000")]
        result = limiter.apply_limits(
            market_id="MKT-B",
            raw_allocations=raw_allocations,
            current_market_exposure=Decimal("0.000000"),
            bankroll_manager=mgr,
            liquidity_tier=LiquidityTier.HEALTHY,
        )
        assert result.is_approved
        assert result.total_approved == Decimal("500.000000")
        assert "INSUFFICIENT_FREE_USDC" in (result.throttle_reason or "")

    def test_fractional_multiplier_and_decimal_truncation(self, manager):
        # Config with fractional Kelly = 0.25
        limiter = RiskLimiter(
            RiskLimiterConfig(
                fractional_multiplier=Decimal("0.25"),
                single_market_cap_ratio=Decimal("0.10"),
                global_utilization_cap_ratio=Decimal("0.70"),
            )
        )
        # raw = 100.3333333 -> * 0.25 = 25.083333325 -> truncated down to 25.083333
        raw_allocations = [Decimal("100.333333")]
        result = limiter.apply_limits(
            market_id="MKT-FRAC",
            raw_allocations=raw_allocations,
            current_market_exposure=Decimal("0.000000"),
            bankroll_manager=manager,
            liquidity_tier=LiquidityTier.HEALTHY,
        )
        assert result.total_approved == Decimal("25.083333")
        assert result.approved_allocations[0] == Decimal("25.083333")
