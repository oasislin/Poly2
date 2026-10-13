"""
Unit tests for Simulation Metrics Calculator (Phase 2 Task 07 - Ticket 03 / Issue #97).
Verifies:
- Sharpe Ratio computation with zero-volatility smoothing and non-zero protection
- Maximum Drawdown (MDD) calculation
- Four-bucket capital conservation theorem
- Non-physical orders audit detection
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest

from src.bankroll.bankroll_manager import FourBucketBalance
from src.simulation.metrics import (
    SimulationMetricsCalculator,
    SimulationMetricsConfig,
    SimulationMetricsSnapshot,
)


class TestSimulationMetricsCalculator:
    def test_metrics_snapshot_and_mdd(self):
        calc = SimulationMetricsCalculator(initial_capital=Decimal("10000.000000"))
        t0 = datetime(2026, 10, 15, 0, 0, 0, tzinfo=timezone.utc)

        # Snapshot 0: 10000
        calc.record_snapshot(
            timestamp=t0,
            balance=FourBucketBalance(
                free_usdc=Decimal("10000.000000"),
                active_locked=Decimal("0"),
                zombie_margin=Decimal("0"),
                disputed_margin=Decimal("0"),
            ),
        )

        # Snapshot 1: Peak 12000
        calc.record_snapshot(
            timestamp=t0 + timedelta(hours=12),
            balance=FourBucketBalance(
                free_usdc=Decimal("12000.000000"),
                active_locked=Decimal("0"),
                zombie_margin=Decimal("0"),
                disputed_margin=Decimal("0"),
            ),
        )

        # Snapshot 2: Trough 9600 (Drawdown from 12000 to 9600 = 2400 / 12000 = 20%)
        calc.record_snapshot(
            timestamp=t0 + timedelta(hours=24),
            balance=FourBucketBalance(
                free_usdc=Decimal("9600.000000"),
                active_locked=Decimal("0"),
                zombie_margin=Decimal("0"),
                disputed_margin=Decimal("0"),
            ),
        )

        # Snapshot 3: Recovery 11000
        calc.record_snapshot(
            timestamp=t0 + timedelta(hours=36),
            balance=FourBucketBalance(
                free_usdc=Decimal("11000.000000"),
                active_locked=Decimal("0"),
                zombie_margin=Decimal("0"),
                disputed_margin=Decimal("0"),
            ),
        )

        report = calc.generate_report()
        assert report.initial_capital == Decimal("10000.000000")
        assert report.final_nav == Decimal("11000.000000")
        assert pytest.approx(report.total_return_pct, abs=1e-3) == 10.0
        assert pytest.approx(report.max_drawdown_pct, abs=1e-3) == 20.0

    def test_sharpe_ratio_zero_volatility_protection(self):
        calc = SimulationMetricsCalculator(initial_capital=Decimal("10000.000000"))
        t0 = datetime(2026, 10, 15, 0, 0, 0, tzinfo=timezone.utc)

        # Flat line: NAV never changes
        for i in range(10):
            calc.record_snapshot(
                timestamp=t0 + timedelta(hours=i),
                balance=FourBucketBalance(
                    free_usdc=Decimal("10000.000000"),
                    active_locked=Decimal("0"),
                    zombie_margin=Decimal("0"),
                    disputed_margin=Decimal("0"),
                ),
            )

        report = calc.generate_report()
        # When volatility is zero and return is zero, Sharpe must be 0.0 (no crash/no div by zero)
        assert report.sharpe_ratio == 0.0

    def test_sharpe_ratio_steady_positive_returns(self):
        calc = SimulationMetricsCalculator(initial_capital=Decimal("10000.000000"))
        t0 = datetime(2026, 10, 15, 0, 0, 0, tzinfo=timezone.utc)

        # Constant steady positive gains
        val = 10000.0
        for i in range(24):
            val += 20.0
            calc.record_snapshot(
                timestamp=t0 + timedelta(hours=i),
                balance=FourBucketBalance(
                    free_usdc=Decimal(f"{val:.6f}"),
                    active_locked=Decimal("0"),
                    zombie_margin=Decimal("0"),
                    disputed_margin=Decimal("0"),
                ),
            )

        report = calc.generate_report()
        # Positive returns with near-zero volatility should have a high Sharpe ratio (> 2.0)
        assert report.sharpe_ratio > 2.0

    def test_capital_conservation_and_non_physical_audit(self):
        calc = SimulationMetricsCalculator(initial_capital=Decimal("10000.000000"))
        t0 = datetime(2026, 10, 15, 0, 0, 0, tzinfo=timezone.utc)

        calc.record_snapshot(
            timestamp=t0,
            balance=FourBucketBalance(
                free_usdc=Decimal("8000.000000"),
                active_locked=Decimal("2000.000000"),
                zombie_margin=Decimal("0"),
                disputed_margin=Decimal("0"),
            ),
        )

        # Total bankroll is 10000, initial is 10000 -> perfectly conserved
        report = calc.generate_report(non_physical_violations=0)
        assert report.capital_conservation_passed is True
        assert report.zero_non_physical_orders_violated == 0
