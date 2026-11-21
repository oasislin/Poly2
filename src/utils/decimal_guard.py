"""Explicit Decimal precision context and operand digit-bound guard.

Structural guarantee required across M1 / M2 / M4 / M5 arithmetic:
- Never relies on mutable thread-global `decimal.getcontext().prec` (default 28).
- Enforces an explicit `localcontext` with high working precision (`EXACT_DECIMAL_CONTEXT_PREC = 64`).
- Validates operand significant-digit counts (`<= DEFAULT_MAX_OPERAND_SIG_DIGITS = 12`) and
  magnitude bounds so multi-factor products (e.g. 4-factor fee expressions or Celsius-to-Fahrenheit
  conversions) cannot suffer silent intermediate rounding that breaks evaluation-order equivalence.
- Supports `trap_inexact=True` for algebraically exact base-10 steps so any unintended rounding
  raises `decimal.Inexact` / `decimal.Rounded` immediately at runtime.
"""

from __future__ import annotations

from contextlib import contextmanager
from decimal import (
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    localcontext,
)
from typing import Iterator, Union

DecimalInput = Union[Decimal, int, str, float]

# 64 working digits strictly exceeds 5 * 12 = 60 digits (covering up to 5-factor products of
# 12-digit operands plus wide-span decimal additions without any intermediate rounding).
EXACT_DECIMAL_CONTEXT_PREC: int = 64
DEFAULT_MAX_OPERAND_SIG_DIGITS: int = 12
DEFAULT_MAX_ABS_EXPONENT: int = 12


class DecimalOperandBoundsError(ValueError):
    """Raised when a Decimal operand violates finiteness, digit-count, or magnitude bounds."""


@contextmanager
def exact_decimal_context(
    *,
    prec: int = EXACT_DECIMAL_CONTEXT_PREC,
    trap_inexact: bool = False,
) -> Iterator[None]:
    """Enter an isolated `decimal.localcontext` with explicit precision and safety traps."""
    if isinstance(prec, bool) or prec < 34:
        raise ValueError(f"Decimal context precision must be an integer >= 34, got {prec!r}")
    with localcontext() as ctx:
        ctx.prec = prec
        ctx.traps[InvalidOperation] = True
        ctx.traps[DivisionByZero] = True
        ctx.traps[Overflow] = True
        ctx.traps[Inexact] = bool(trap_inexact)
        ctx.traps[Rounded] = bool(trap_inexact)
        yield


def _coerce_to_decimal(value: DecimalInput, *, name: str) -> Decimal:
    """Convert raw numeric input into Decimal while rejecting bool, None, and non-finite literals."""
    if isinstance(value, bool) or value is None:
        raise DecimalOperandBoundsError(f"{name}: bool/None is not a valid Decimal operand")
    try:
        if isinstance(value, Decimal):
            dec = value
        elif isinstance(value, int):
            dec = Decimal(value)
        elif isinstance(value, str):
            dec = Decimal(value.strip())
        elif isinstance(value, float):
            dec = Decimal(str(value))
        else:
            raise DecimalOperandBoundsError(
                f"{name}: unsupported operand type {type(value).__name__}"
            )
    except InvalidOperation as exc:
        raise DecimalOperandBoundsError(f"{name}: invalid Decimal literal {value!r}") from exc
    if not dec.is_finite():
        raise DecimalOperandBoundsError(f"{name}: operand must be finite, got {dec!r}")
    return dec


def _validate_decimal_bounds(
    dec: Decimal,
    *,
    name: str,
    max_sig_digits: int,
    max_abs_exponent: int,
) -> None:
    """Enforce raw coefficient digit count and exponent bounds on finite Decimal."""
    if isinstance(max_sig_digits, bool) or max_sig_digits < 1:
        raise ValueError(f"max_sig_digits must be >= 1, got {max_sig_digits!r}")
    raw_digit_count = len(dec.as_tuple().digits)
    if raw_digit_count > max_sig_digits:
        raise DecimalOperandBoundsError(
            f"{name}: operand {dec!r} has {raw_digit_count} digits, "
            f"exceeding structural bound max_sig_digits={max_sig_digits}"
        )
    if dec != 0 and abs(dec.adjusted()) > max_abs_exponent:
        raise DecimalOperandBoundsError(
            f"{name}: operand {dec!r} has adjusted exponent {dec.adjusted()}, "
            f"exceeding structural bound max_abs_exponent={max_abs_exponent}"
        )


def to_guarded_decimal(
    value: DecimalInput,
    *,
    name: str,
    max_sig_digits: int = DEFAULT_MAX_OPERAND_SIG_DIGITS,
    max_abs_exponent: int = DEFAULT_MAX_ABS_EXPONENT,
) -> Decimal:
    """Convert `value` to `Decimal` and enforce finiteness, digit-count, and scale bounds."""
    dec = _coerce_to_decimal(value, name=name)
    _validate_decimal_bounds(
        dec,
        name=name,
        max_sig_digits=max_sig_digits,
        max_abs_exponent=max_abs_exponent,
    )
    return dec


__all__ = [
    "DEFAULT_MAX_ABS_EXPONENT",
    "DEFAULT_MAX_OPERAND_SIG_DIGITS",
    "DecimalInput",
    "DecimalOperandBoundsError",
    "EXACT_DECIMAL_CONTEXT_PREC",
    "exact_decimal_context",
    "to_guarded_decimal",
]
