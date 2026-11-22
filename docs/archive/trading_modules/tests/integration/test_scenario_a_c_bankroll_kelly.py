"""
Acceptance Integration Tests for Test-Scenario A and Test-Scenario C (Phase 2 Task 05 - Ticket 05 / Issue #87).
Verifies:
- Scenario A: 4-outcome market probability flip, sunk-cost natural forward hedging without forced dump, single market 10% cap.
- Scenario C: 12h un-cleared position zombie isolation, dual-track accounting (0.0x Sizing vs 0.90x NAV), tiered liquidity watchdogs, and 6-decimal zero-drift conservation.
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest

from src.bankroll.bankroll_manager import BankrollManager, FourBucketBalance
from src.bankroll.zombie_evaluator import (
    ZombieEvaluator,
    PositionRecord,
    LiquidityTier,
)
from src.bankroll.multinomial_kelly import MultinomialKellyOptimizer
from src.bankroll.risk_limiter import RiskLimiter, RiskLimiterConfig


class TestScenarioABankrollKellyHedging:
    """
    Test-Scenario A: 4-outcome temperature market probability flip & natural forward hedging.
    """

    def test_scenario_a_cold_front_probability_flip(self):
        # 1. Initialize bankroll with 50,000 USDC
        manager = BankrollManager(initial_free_usdc=Decimal("50000.000000"))
        limiter = RiskLimiter(
            RiskLimiterConfig(
                fractional_multiplier=Decimal("0.5"),  # Half-Kelly
                single_market_cap_ratio=Decimal("0.10"),  # 10% max market cap
                global_utilization_cap_ratio=Decimal("0.70"),
            )
        )
        optimizer = MultinomialKellyOptimizer()

        market_id = "KORD-2026-10-15-TMAX"
        # 4 Outcomes: [<=65°F, 66-70°F, 71-75°F, >=76°F]
        # Market prices (implied odds): [0.20, 0.25, 0.35, 0.20]
        prices = [0.20, 0.25, 0.35, 0.20]

        # Initial trade yesterday: Prior forecast favored warm weather (Outcome 2 & 3).
        # We hold 2000 shares in Outcome 2 (cost 500 USDC), 4000 shares in Outcome 3 (cost 1400 USDC).
        # Total locked = 1900 USDC.
        initial_locked = Decimal("1900.000000")
        manager.lock_funds(initial_locked)

        # Existing payouts vector if each state wins (1 USDC per share):
        # Outcome 0: 0, Outcome 1: 2000, Outcome 2: 4000, Outcome 3: 0
        existing_payouts = [0.0, 2000.0, 4000.0, 0.0]

        # 2. Sudden Cold Front Update:
        # Probabilities flip dramatically towards colder outcomes:
        # New model probabilities: [0.55, 0.35, 0.08, 0.02]
        probabilities = [0.55, 0.35, 0.08, 0.02]

        free_usdc_float = float(manager.get_balance().free_usdc)

        # 3. Run Multinomial Kelly SLSQP Optimizer with sunk-cost N_i injected
        opt_res = optimizer.optimize(
            probabilities=probabilities,
            prices=prices,
            existing_payouts=existing_payouts,
            w_free=free_usdc_float,
        )

        assert opt_res.success is True
        # Cold front favor: Outcome 0 (prob 0.55 vs price 0.20) has massive edge
        assert opt_res.optimal_allocations[0] > 0.0
        # Warm outcome 2 (prob 0.08 vs price 0.35) and outcome 3 (prob 0.02 vs price 0.20) should have ZERO new allocation
        assert opt_res.optimal_allocations[2] == 0.0
        assert opt_res.optimal_allocations[3] == 0.0

        # 4. Pass candidate allocations through RiskLimiter
        raw_allocations = [Decimal(f"{x:.6f}") for x in opt_res.optimal_allocations]
        risk_res = limiter.apply_limits(
            market_id=market_id,
            raw_allocations=raw_allocations,
            current_market_exposure=initial_locked,
            bankroll_manager=manager,
            liquidity_tier=LiquidityTier.HEALTHY,
        )

        assert risk_res.is_approved is True
        # Total market exposure after cannot exceed 10% of effective bankroll (50,000 * 0.10 = 5,000)
        assert risk_res.market_exposure_after <= Decimal("5000.000000")
        # Ensure approved allocations are strictly non-negative
        assert all(a >= Decimal("0.000000") for a in risk_res.approved_allocations)
        # Outcome 2 and 3 remain 0
        assert risk_res.approved_allocations[2] == Decimal("0.000000")
        assert risk_res.approved_allocations[3] == Decimal("0.000000")

        # 5. Execute approved order lock
        manager.lock_funds(risk_res.total_approved)
        bal = manager.get_balance()
        assert bal.active_locked == initial_locked + risk_res.total_approved
        assert bal.free_usdc + bal.active_locked == Decimal("50000.000000")


class TestScenarioCBankrollZombieDualTrack:
    """
    Test-Scenario C: 12h un-cleared position zombie isolation, dual-track accounting & zero-drift precision.
    """

    def test_scenario_c_zombie_timeout_and_circuit_breakers(self):
        # 1. Setup Bankroll Manager with 100,000 USDC
        manager = BankrollManager(initial_free_usdc=Decimal("100000.000000"))
        evaluator = ZombieEvaluator(bankroll_manager=manager)
        limiter = RiskLimiter(
            RiskLimiterConfig(
                fractional_multiplier=Decimal("1.0"),
                single_market_cap_ratio=Decimal("0.10"),
                global_utilization_cap_ratio=Decimal("0.70"),
            )
        )

        # 2. Place trades on KORD and KMIA
        # KORD: 20,000 USDC on 2026-08-31
        # KMIA: 5,000 USDC on 2026-09-01
        pos_kord = PositionRecord(
            position_id="POS-KORD-01",
            station_id="KORD",
            market_date="2026-08-31",
            cost_basis=Decimal("20000.000000"),
            shares=Decimal("30000.000000"),
            expected_payout=Decimal("28000.000000"),
        )
        pos_kmia = PositionRecord(
            position_id="POS-KMIA-01",
            station_id="KMIA",
            market_date="2026-09-01",
            cost_basis=Decimal("5000.000000"),
            shares=Decimal("7000.000000"),
            expected_payout=Decimal("6000.000000"),
        )

        manager.lock_funds(pos_kord.cost_basis + pos_kmia.cost_basis)
        evaluator.register_position(pos_kord)
        evaluator.register_position(pos_kmia)

        assert manager.get_effective_bankroll() == Decimal("100000.000000")
        assert manager.get_balance().active_locked == Decimal("25000.000000")
        assert manager.get_balance().free_usdc == Decimal("75000.000000")

        # 3. Time advances to 2026-09-01 13:00 UTC
        # KORD is America/Chicago (UTC-5 in summer).
        # Midnight end of 2026-08-31 for KORD is 2026-09-01 05:00 UTC.
        # +12h deadline is 2026-09-01 17:00 UTC.
        # At 13:00 UTC, KORD is NOT yet zombie.
        zombie_t1 = evaluator.evaluate_positions(
            current_wall_time=datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc)
        )
        assert len(zombie_t1) == 0
        liq_t1 = evaluator.evaluate_liquidity_tier()
        assert liq_t1.tier == LiquidityTier.HEALTHY
        assert manager.get_effective_bankroll() == Decimal("100000.000000")

        # 4. Time advances to 2026-09-01 18:00 UTC (13h post-midnight)
        # KORD deadline (17:00 UTC) has passed! KMIA market_date is 2026-09-01, not expired.
        zombie_t2 = evaluator.evaluate_positions(
            current_wall_time=datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
        )

        assert len(zombie_t2) == 1
        assert zombie_t2[0] == "POS-KORD-01"

        # Check Bankroll State Machine updates
        bal_after = manager.get_balance()
        assert bal_after.active_locked == Decimal("5000.000000")  # KMIA only
        assert bal_after.zombie_margin == Decimal("20000.000000") # KORD transferred
        assert bal_after.free_usdc == Decimal("75000.000000")

        # DUAL-TRACK ASSERTIONS (ADR-0012 §D4):
        # Sizing Track: Effective bankroll strictly EXCLUDES Zombie (0.0x weight)
        # Effective = Free (75,000) + Active (5,000) = 80,000 USDC.
        assert manager.get_effective_bankroll() == Decimal("80000.000000")

        # Financial NAV Track: Zombie discounted by 10% on expected payout (0.90 * 28,000 = 25,200)
        # NAV = Free (75,000) + Active Cost (5,000) + Zombie Valued (25,200) = 105,200 USDC
        nav = evaluator.calculate_financial_nav()
        assert nav == Decimal("105200.000000")

        # Nominal Zombie Ratio R_z:
        # R_z = (20,000 Zombie + 0 Disputed) / 100,000 Total = 20.00%
        # 15% < R_z <= 30% -> Triggers WARNING_HAIRCUT (0.5x sizing haircut)!
        liq_t2 = evaluator.evaluate_liquidity_tier()
        assert abs(liq_t2.nominal_zombie_ratio - 0.20) < 1e-6
        assert liq_t2.tier == LiquidityTier.WARNING_HAIRCUT

        # 5. Risk Limiter under WARNING_HAIRCUT:
        # A new trade requesting 4,000 USDC should be cut in half (2,000 USDC)
        risk_res = limiter.apply_limits(
            market_id="KLAX-2026-09-02-TMAX",
            raw_allocations=[Decimal("4000.000000")],
            current_market_exposure=Decimal("0.000000"),
            bankroll_manager=manager,
            liquidity_tier=liq_t2.tier,
        )
        assert risk_res.is_approved is True
        assert risk_res.is_throttled is True
        assert "ZOMBIE_RATE_WARNING_0.5X" in risk_res.throttle_reason
        assert risk_res.total_approved == Decimal("2000.000000")

        # 6. Perfect Conservation and Zero Precision Drift Assertion
        # Total bankroll across 4 buckets must always exactly equal initial deposits
        assert (
            bal_after.free_usdc
            + bal_after.active_locked
            + bal_after.zombie_margin
            + bal_after.disputed_margin
            == Decimal("100000.000000")
        )
        # All decimal string representations have exactly 6 decimal places
        for bucket_val in [
            bal_after.free_usdc,
            bal_after.active_locked,
            bal_after.zombie_margin,
            bal_after.disputed_margin,
            manager.get_effective_bankroll(),
            nav,
        ]:
            _, _, exponent = bucket_val.as_tuple()
            assert exponent == -6
