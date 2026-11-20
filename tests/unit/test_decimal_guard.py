"""Tests for explicit Decimal context precision and operand digit-bound guard."""

from __future__ import annotations

from decimal import Decimal, Inexact, localcontext
import pytest

from src.utils.decimal_guard import (
    DEFAULT_MAX_OPERAND_SIG_DIGITS,
    EXACT_DECIMAL_CONTEXT_PREC,
    DecimalOperandBoundsError,
    exact_decimal_context,
    to_guarded_decimal,
)


def test_17_digit_operands_break_associativity_at_default_28_and_are_rejected_by_guard() -> None:
    """Reproduce the 17-digit / 28-prec intermediate rounding hazard and assert structural rejection."""
    a = Decimal("1.2345678901234502")   # 17 significant digits
    b = Decimal("0.71828182845904523")  # 17 significant digits (p)
    c = Decimal("0.28171817154095477")  # 17 significant digits (1 - p)

    with localcontext() as default_ctx:
        default_ctx.prec = 28
        lhs = (a * b) * c
        rhs = a * (b * c)
        assert lhs != rhs  # confirms the exact hazard under default 28-digit precision

    # Guard structurally rejects 17-digit operands before arithmetic begins
    with pytest.raises(DecimalOperandBoundsError, match="exceeding structural bound"):
        to_guarded_decimal(a, name="a")

    # Even padded trailing zeros that would consume product digits are caught
    padded = Decimal("1.0000000000000000")  # 17 digits in coefficient tuple
    with pytest.raises(DecimalOperandBoundsError, match="exceeding structural bound"):
        to_guarded_decimal(padded, name="padded")


def test_guarded_12_digit_operands_preserve_exact_associativity_under_explicit_context() -> None:
    """Up to 5-factor products of 12-digit operands suffer zero rounding in prec=64 context."""
    a = to_guarded_decimal("12345.6789012", name="a")
    b = to_guarded_decimal("0.876543210987", name="b")
    c = to_guarded_decimal("0.010000000001", name="c")
    d = to_guarded_decimal("0.123456789013", name="d")

    assert len(a.as_tuple().digits) == DEFAULT_MAX_OPERAND_SIG_DIGITS
    assert EXACT_DECIMAL_CONTEXT_PREC == 64

    with exact_decimal_context(trap_inexact=True):
        order_1 = ((a * b) * c) * d
        order_2 = a * (b * (c * d))
        order_3 = (a * c) * (b * d)
        assert order_1 == order_2 == order_3


def test_trap_inexact_catches_non_terminating_division() -> None:
    """Exact context with trap_inexact=True raises immediately on any inexact arithmetic."""
    with exact_decimal_context(trap_inexact=True):
        with pytest.raises(Inexact):
            _ = Decimal("1") / Decimal("3")


def test_guard_rejects_non_finite_bool_none_and_extreme_exponents() -> None:
    for bad in (True, False, None, float("nan"), float("inf"), float("-inf"), "NaN", "Infinity"):
        with pytest.raises(DecimalOperandBoundsError):
            to_guarded_decimal(bad, name="bad")  # type: ignore[arg-type]

    with pytest.raises(DecimalOperandBoundsError, match="adjusted exponent"):
        to_guarded_decimal(Decimal("1E+20"), name="huge")

    with pytest.raises(DecimalOperandBoundsError, match="adjusted exponent"):
        to_guarded_decimal(Decimal("1E-20"), name="tiny")
