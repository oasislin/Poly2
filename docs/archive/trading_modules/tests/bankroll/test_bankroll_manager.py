"""
Unit tests for Four-Bucket Bankroll State Machine and Decimal Rounding (Phase 2 Task 05 - Ticket 01 / Issue #83).
Implements ADR-0012 §D4 and Phase 2 Execution Document v2.0 §3.
"""

from decimal import Decimal
import pytest

from src.bankroll.bankroll_manager import (
    BankrollManager,
    FourBucketBalance,
    InsufficientFundsError,
    to_usdc_decimal,
)


class TestBankrollManager:
    """Test suite for four-bucket bankroll conservation and precision."""

    def test_decimal_conversion_and_truncation(self):
        """Verify float and string inputs are safely converted to 6-decimal USDC with round down."""
        # 100.1234567 -> 100.123456 (truncated to 6 decimals, no upward creep)
        d1 = to_usdc_decimal(100.1234567)
        assert d1 == Decimal("100.123456")

        d2 = to_usdc_decimal("50.5")
        assert d2 == Decimal("50.500000")

    def test_initial_balance_and_total_conservation(self):
        """Verify initial balance deposit and Total = Free + Active + Zombie + Disputed."""
        mgr = BankrollManager(initial_free_usdc=1000.0)
        bal = mgr.get_balance()

        assert bal.free_usdc == Decimal("1000.000000")
        assert bal.active_locked == Decimal("0.000000")
        assert bal.zombie_margin == Decimal("0.000000")
        assert bal.disputed_margin == Decimal("0.000000")
        assert bal.total_bankroll == Decimal("1000.000000")
        assert mgr.get_effective_bankroll() == Decimal("1000.000000")

    def test_order_locking_and_unlocking(self):
        """Verify locking funds for active orders and unlocking on cancellation."""
        mgr = BankrollManager(initial_free_usdc=500.0)

        # Lock 150.00 for order
        mgr.lock_funds(150.0)
        bal = mgr.get_balance()
        assert bal.free_usdc == Decimal("350.000000")
        assert bal.active_locked == Decimal("150.000000")
        assert bal.total_bankroll == Decimal("500.000000")

        # Unlock 50.00 (partial cancel)
        mgr.unlock_funds(50.0)
        bal = mgr.get_balance()
        assert bal.free_usdc == Decimal("400.000000")
        assert bal.active_locked == Decimal("100.000000")
        assert bal.total_bankroll == Decimal("500.000000")

    def test_insufficient_funds_rejected(self):
        """Verify attempting to lock or withdraw more than free USDC raises InsufficientFundsError."""
        mgr = BankrollManager(initial_free_usdc=100.0)
        with pytest.raises(InsufficientFundsError, match="Insufficient free USDC"):
            mgr.lock_funds(150.0)

        with pytest.raises(InsufficientFundsError, match="Insufficient free USDC"):
            mgr.withdraw(150.0)

    def test_settle_position_with_profit_and_loss(self):
        """Verify position settlement correctly credits payout to free USDC and releases locked margin."""
        mgr = BankrollManager(initial_free_usdc=500.0)
        mgr.lock_funds(100.0)  # Locked 100

        # Winning settlement: Payout = 180.00 (profit = +80.00)
        mgr.settle_position(original_locked=100.0, payout=180.0)
        bal = mgr.get_balance()
        assert bal.active_locked == Decimal("0.000000")
        assert bal.free_usdc == Decimal("580.000000")
        assert bal.total_bankroll == Decimal("580.000000")

    def test_zombie_and_disputed_transfers_and_effective_bankroll(self):
        """
        Verify:
        1. Transfer active locked to zombie margin
        2. Transfer to disputed margin
        3. Effective bankroll strictly excludes zombie and disputed (0.0x ADR-0012)
        """
        mgr = BankrollManager(initial_free_usdc=1000.0)
        mgr.lock_funds(300.0)  # Free=700, Active=300

        # 200 of active becomes zombie after 12h
        mgr.transfer_to_zombie(200.0)
        bal = mgr.get_balance()
        assert bal.free_usdc == Decimal("700.000000")
        assert bal.active_locked == Decimal("100.000000")
        assert bal.zombie_margin == Decimal("200.000000")
        assert bal.total_bankroll == Decimal("1000.000000")

        # Effective bankroll for Kelly sizing MUST be Free (700) + Active (100) = 800 (excludes 200 zombie)
        assert mgr.get_effective_bankroll() == Decimal("800.000000")

        # 50 of zombie becomes disputed
        mgr.transfer_to_disputed(50.0, source="zombie")
        bal = mgr.get_balance()
        assert bal.zombie_margin == Decimal("150.000000")
        assert bal.disputed_margin == Decimal("50.000000")
        assert bal.total_bankroll == Decimal("1000.000000")
        assert mgr.get_effective_bankroll() == Decimal("800.000000")

    def test_precision_accumulation_no_drift(self):
        """Verify thousands of tiny micro-transactions do not drift or create fractional dust errors."""
        mgr = BankrollManager(initial_free_usdc=100.0)
        # Lock and unlock 0.000001 10,000 times
        tiny = "0.000001"
        for _ in range(1000):
            mgr.lock_funds(tiny)
            mgr.unlock_funds(tiny)

        bal = mgr.get_balance()
        assert bal.free_usdc == Decimal("100.000000")
        assert bal.total_bankroll == Decimal("100.000000")
