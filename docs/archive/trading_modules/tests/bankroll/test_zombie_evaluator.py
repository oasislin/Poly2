"""
Unit tests for Zombie Position Evaluator and Tiered Liquidity Circuit Breaker (Phase 2 Task 05 - Ticket 02 / Issue #84).
Implements ADR-0012 §D2 and §D4 dual-book valuation and tiered liquidity watchdog.
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest

from src.bankroll.bankroll_manager import BankrollManager
from src.bankroll.zombie_evaluator import (
    LiquidityTier,
    PositionRecord,
    ZombieEvaluator,
    ZombieEvaluatorConfig,
)


class TestZombieEvaluator:
    """Test suite for 12h physical timeout, dual-book valuation, and tiered circuit breaker."""

    @pytest.fixture
    def manager(self):
        return BankrollManager(initial_free_usdc=1000.0)

    @pytest.fixture
    def evaluator(self, manager):
        cfg = ZombieEvaluatorConfig(
            grace_period_hours=12.0,
            zombie_haircut=0.10,
            tier_haircut_threshold=0.15,
            tier_halt_threshold=0.30,
            tier_safe_mode_threshold=0.50,
        )
        return ZombieEvaluator(bankroll_manager=manager, config=cfg)

    def test_zombie_12h_transition_and_transfer(self, evaluator, manager):
        """Verify position un-settled past 12h trigger is transferred to Zombie Margin."""
        manager.lock_funds(200.0)

        # KORD position target date 2026-09-21.
        # Expected settle: 2026-09-22 05:00 UTC (midnight Chicago)
        # 12h Zombie trigger: 2026-09-22 17:00 UTC (noon Chicago)
        t_before = datetime(2026, 9, 22, 16, 30, 0, tzinfo=timezone.utc)
        t_after = datetime(2026, 9, 22, 17, 30, 0, tzinfo=timezone.utc)

        pos = PositionRecord(
            position_id="pos_001",
            station_id="KORD",
            market_date="2026-09-21",
            cost_basis=Decimal("200.000000"),
            shares=Decimal("400.000000"),
            expected_payout=Decimal("300.000000"),
        )
        evaluator.register_position(pos)

        # Before 12h: remains active
        evaluator.evaluate_positions(current_wall_time=t_before)
        assert manager.get_balance().active_locked == Decimal("200.000000")
        assert manager.get_balance().zombie_margin == Decimal("0.000000")

        # After 12h: transferred to zombie
        evaluator.evaluate_positions(current_wall_time=t_after)
        assert manager.get_balance().active_locked == Decimal("0.000000")
        assert manager.get_balance().zombie_margin == Decimal("200.000000")
        assert manager.get_effective_bankroll() == Decimal("800.000000")  # Excludes zombie!

    def test_dual_book_accounting_and_nav_valuation(self, evaluator, manager):
        """
        Verify:
        - Trading Sizing Book excludes Zombie (0.0x weight)
        - Financial NAV Book marks Zombie at 90% (10% liquidity discount)
        """
        manager.lock_funds(200.0)
        pos = PositionRecord(
            position_id="pos_002",
            station_id="KLGA",
            market_date="2026-09-21",
            cost_basis=Decimal("200.000000"),
            shares=Decimal("400.000000"),
            expected_payout=Decimal("300.000000"),  # Expected value E[V] = $300
        )
        evaluator.register_position(pos)

        t_after = datetime(2026, 9, 22, 18, 0, 0, tzinfo=timezone.utc)
        evaluator.evaluate_positions(current_wall_time=t_after)

        # Sizing book
        assert manager.get_effective_bankroll() == Decimal("800.000000")

        # NAV book: Free (800) + Active (0) + Zombie NAV (300 * 0.90 = 270) = 1070
        nav = evaluator.calculate_financial_nav()
        assert nav == Decimal("1070.000000")

    def test_tiered_liquidity_watchdog_thresholds(self, evaluator, manager):
        """
        Verify tiered liquidity thresholds:
        - R_z <= 15%: HEALTHY (1.0x sizing)
        - 15% < R_z <= 30%: WARNING_HAIRCUT (0.5x sizing)
        - 30% < R_z <= 50%: HALT_NEW_POSITIONS (0.0x sizing)
        - R_z > 50%: CRITICAL_SAFE_MODE
        """
        # Case 1: Zombie = 100 on 1000 Total -> R_z = 10% -> HEALTHY
        manager.lock_funds(100.0)
        manager.transfer_to_zombie(100.0)
        status1 = evaluator.evaluate_liquidity_tier()
        assert status1.tier == LiquidityTier.HEALTHY
        assert status1.sizing_multiplier == 1.0

        # Case 2: Zombie = 200 on 1000 Total -> R_z = 20% -> WARNING_HAIRCUT
        manager.lock_funds(100.0)
        manager.transfer_to_zombie(100.0)
        status2 = evaluator.evaluate_liquidity_tier()
        assert status2.tier == LiquidityTier.WARNING_HAIRCUT
        assert status2.sizing_multiplier == 0.5

        # Case 3: Zombie = 350 on 1000 Total -> R_z = 35% -> HALT_NEW_POSITIONS
        manager.lock_funds(150.0)
        manager.transfer_to_zombie(150.0)
        status3 = evaluator.evaluate_liquidity_tier()
        assert status3.tier == LiquidityTier.HALT_NEW_POSITIONS
        assert status3.sizing_multiplier == 0.0

        # Case 4: Zombie = 600 on 1000 Total -> R_z = 60% -> CRITICAL_SAFE_MODE
        manager.lock_funds(250.0)
        manager.transfer_to_zombie(250.0)
        status4 = evaluator.evaluate_liquidity_tier()
        assert status4.tier == LiquidityTier.CRITICAL_SAFE_MODE
        assert status4.sizing_multiplier == 0.0
