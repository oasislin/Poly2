"""
Four-Bucket Bankroll State Machine and Decimal Precision Controller (Phase 2 Task 05 - Ticket 01 / Issue #83).
Implements ADR-0012 §D4:
- Four-Bucket balance equation: Total = Free USDC + Active Locked + Zombie Margin + Disputed Margin
- 6-decimal fixed-point Decimal arithmetic (ROUND_DOWN) preventing fractional leakage
- Zero-leakage transaction transitions (lock, unlock, settle, zombie transfer)
- Effective Bankroll (excluding Zombie and Disputed by 0.0x for Kelly sizing)
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
import logging
import threading
from typing import Any, Dict, Union

logger = logging.getLogger(__name__)

USDC_PRECISION = Decimal("0.000001")  # 6 decimal places (micro-USDC, ERC-20 standard)


class InsufficientFundsError(Exception):
    """Raised when an operation requires more free USDC than currently available."""
    pass


def to_usdc_decimal(val: Union[Decimal, float, int, str]) -> Decimal:
    """
    Convert numerical input into a 6-decimal USDC Decimal with ROUND_DOWN truncation.
    Guarantees no upward creep or fractional dust creation.
    """
    if isinstance(val, Decimal):
        d = val
    elif isinstance(val, (int, str)):
        d = Decimal(str(val))
    else:
        # Float: clean formatting to avoid binary floating point representation artifacts
        d = Decimal(f"{float(val):.8f}")

    return d.quantize(USDC_PRECISION, rounding=ROUND_DOWN)


@dataclass(frozen=True)
class FourBucketBalance:
    """Snapshot of four-bucket bankroll distribution."""
    free_usdc: Decimal
    active_locked: Decimal
    zombie_margin: Decimal
    disputed_margin: Decimal

    @property
    def total_bankroll(self) -> Decimal:
        """Total accounting assets across all four buckets."""
        return self.free_usdc + self.active_locked + self.zombie_margin + self.disputed_margin

    def to_dict(self) -> Dict[str, Any]:
        """Serialize balance snapshot to dictionary."""
        return {
            "free_usdc": float(self.free_usdc),
            "active_locked": float(self.active_locked),
            "zombie_margin": float(self.zombie_margin),
            "disputed_margin": float(self.disputed_margin),
            "total_bankroll": float(self.total_bankroll),
        }


class BankrollManager:
    """
    Governs the four-bucket bankroll state machine with thread-safe atomic transactions.
    """

    def __init__(self, initial_free_usdc: Union[Decimal, float, str] = 0.0):
        self._lock = threading.Lock()
        init_dec = to_usdc_decimal(initial_free_usdc)
        self._free_usdc: Decimal = init_dec
        self._active_locked: Decimal = Decimal("0.000000")
        self._zombie_margin: Decimal = Decimal("0.000000")
        self._disputed_margin: Decimal = Decimal("0.000000")

    def get_balance(self) -> FourBucketBalance:
        """Return an immutable snapshot of the current four buckets."""
        with self._lock:
            return FourBucketBalance(
                free_usdc=self._free_usdc,
                active_locked=self._active_locked,
                zombie_margin=self._zombie_margin,
                disputed_margin=self._disputed_margin,
            )

    def get_effective_bankroll(self) -> Decimal:
        """
        Effective bankroll for trading and Kelly sizing (ADR-0012 §D4 Rule 1).
        Strictly excludes Zombie Margin and Disputed Margin (0.0x weight).
        Effective = Free USDC + Active Locked.
        """
        with self._lock:
            return self._free_usdc + self._active_locked

    def can_lock(self, amount: Union[Decimal, float, str]) -> bool:
        """Check if sufficient free USDC is available to lock amount."""
        amt = to_usdc_decimal(amount)
        with self._lock:
            return self._free_usdc >= amt

    @property
    def total_balance(self) -> Decimal:
        """Convenience property returning total balance across all four buckets."""
        return self.get_balance().total_bankroll

    @property
    def effective_bankroll(self) -> Decimal:
        """Convenience property returning effective bankroll."""
        return self.get_effective_bankroll()

    def deposit(self, amount: Union[Decimal, float, str]) -> Decimal:
        """Deposit funds into Free USDC."""
        amt = to_usdc_decimal(amount)
        if amt <= Decimal("0"):
            return self.get_balance().total_bankroll

        with self._lock:
            self._free_usdc += amt
            logger.info(f"Deposited {amt} USDC. New Free: {self._free_usdc}")
            return self._free_usdc + self._active_locked + self._zombie_margin + self._disputed_margin

    def withdraw(self, amount: Union[Decimal, float, str]) -> Decimal:
        """Withdraw funds from Free USDC."""
        amt = to_usdc_decimal(amount)
        if amt <= Decimal("0"):
            return self.get_balance().total_bankroll

        with self._lock:
            if amt > self._free_usdc:
                raise InsufficientFundsError(
                    f"Insufficient free USDC for withdrawal. Requested: {amt}, Available: {self._free_usdc}"
                )
            self._free_usdc -= amt
            logger.info(f"Withdrew {amt} USDC. New Free: {self._free_usdc}")
            return self._free_usdc + self._active_locked + self._zombie_margin + self._disputed_margin

    def lock_funds(self, amount: Union[Decimal, float, str]) -> None:
        """Lock free USDC for an active order or position."""
        amt = to_usdc_decimal(amount)
        if amt <= Decimal("0"):
            return

        with self._lock:
            if amt > self._free_usdc:
                raise InsufficientFundsError(
                    f"Insufficient free USDC to lock funds. Requested: {amt}, Available: {self._free_usdc}"
                )
            self._free_usdc -= amt
            self._active_locked += amt
            logger.debug(f"Locked {amt} USDC. Free: {self._free_usdc}, Active: {self._active_locked}")

    def unlock_funds(self, amount: Union[Decimal, float, str]) -> None:
        """Unlock previously locked funds back to Free USDC (e.g. order cancel)."""
        amt = to_usdc_decimal(amount)
        if amt <= Decimal("0"):
            return

        with self._lock:
            release = min(amt, self._active_locked)
            self._active_locked -= release
            self._free_usdc += release
            logger.debug(f"Unlocked {release} USDC. Free: {self._free_usdc}, Active: {self._active_locked}")

    def settle_position(
        self,
        original_locked: Union[Decimal, float, str],
        payout: Union[Decimal, float, str],
    ) -> None:
        """
        Settle an active position: releases original_locked from active_locked and credits payout to free_usdc.
        """
        orig = to_usdc_decimal(original_locked)
        pay = to_usdc_decimal(payout)

        with self._lock:
            release = min(orig, self._active_locked)
            self._active_locked -= release
            self._free_usdc += pay
            logger.info(
                f"Settled position. Released locked: {release}, Payout: {pay}, Net PnL: {pay - release}"
            )

    def transfer_to_zombie(self, amount: Union[Decimal, float, str]) -> None:
        """Move un-cleared funds from Active Locked to Zombie Margin upon 12h timeout."""
        amt = to_usdc_decimal(amount)
        if amt <= Decimal("0"):
            return

        with self._lock:
            transfer_amt = min(amt, self._active_locked)
            self._active_locked -= transfer_amt
            self._zombie_margin += transfer_amt
            logger.warning(
                f"Transferred {transfer_amt} USDC from Active to Zombie Margin (12h timeout). "
                f"Zombie: {self._zombie_margin}, Active: {self._active_locked}"
            )

    def settle_zombie(
        self,
        amount: Union[Decimal, float, str],
        payout: Union[Decimal, float, str],
    ) -> None:
        """Settle a position that was previously moved to Zombie Margin."""
        amt = to_usdc_decimal(amount)
        pay = to_usdc_decimal(payout)

        with self._lock:
            release = min(amt, self._zombie_margin)
            self._zombie_margin -= release
            self._free_usdc += pay
            logger.info(
                f"Settled zombie position. Released zombie: {release}, Payout: {pay} to Free USDC."
            )

    def transfer_to_disputed(
        self,
        amount: Union[Decimal, float, str],
        source: str = "active",
    ) -> None:
        """Move funds to Disputed Margin from active or zombie."""
        amt = to_usdc_decimal(amount)
        if amt <= Decimal("0"):
            return

        with self._lock:
            if source == "active":
                transfer_amt = min(amt, self._active_locked)
                self._active_locked -= transfer_amt
            else:
                transfer_amt = min(amt, self._zombie_margin)
                self._zombie_margin -= transfer_amt

            self._disputed_margin += transfer_amt
            logger.critical(
                f"Transferred {transfer_amt} USDC from {source} to Disputed Margin. Total Disputed: {self._disputed_margin}"
            )

    def get_total_bankroll(self) -> Decimal:
        """Total accounting assets across all four buckets."""
        return self.get_balance().total_bankroll

    def get_utilization_ratio(self) -> Decimal:
        """
        Global liquidity utilization ratio (Active Locked / Total Bankroll).
        Zombie and Disputed are strictly excluded from numerator (ADR-0012 §D4 Rule 3).
        """
        bal = self.get_balance()
        if bal.total_bankroll <= Decimal("0"):
            return Decimal("0.000000")
        return (bal.active_locked / bal.total_bankroll).quantize(USDC_PRECISION, rounding=ROUND_DOWN)

