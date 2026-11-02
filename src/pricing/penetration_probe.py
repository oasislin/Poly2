"""
Market Penetration Probe and Trade EV Engine (Phase 2 Task 08 - Ticket 08).
Implements M1 Pricing safe capacity S_target and probe calculation (DR-2026-1014-01).
P7-ALGO-2_规格书 L60-63:
1. S_target = sum_{j: edge_j >= min_edge} s_j
2. p_bar = depth-weighted average ask price across qualified levels
3. q_eff = p_bar * (1 + fee_base * (1 - p_bar))
4. net_ev = p_hat - q_eff, edge = net_ev / q_eff
Production min_edge is [待标定] and remains LOCKED under F-2 pending calibration in #156.
"""

from dataclasses import dataclass
import math
from typing import Tuple

from src.pricing.sigma_adj import (
    F2LockNotReleasedError as SigmaAdjF2LockNotReleasedError,
    SigmaAdjLockState,
)

# Fee base ratio定案依据: P7-ALGO-2_规格书 L61 / 市场特性契约 v1.0
FEE_BASE_RATIO: float = 0.05
FEE_BASE_PROVENANCE: str = "P7-ALGO-2_规格书 L61 / 市场特性契约 v1.0"


class PenetrationError(Exception):
    """Base exception for orderbook penetration probe calculations."""


class F2LockNotReleasedError(PenetrationError, SigmaAdjF2LockNotReleasedError):
    """Raised when probe calculation or policy loading is attempted while F-2 lock is active."""


class InvalidPenetrationPolicyError(PenetrationError):
    """Raised when PenetrationPolicy attributes or types are invalid."""


class InvalidOrderBookError(PenetrationError):
    """Raised when AskBook structure, prices, or sizes are invalid."""


class InvalidProbabilityError(PenetrationError):
    """Raised when p_hat is not a finite probability in (0, 1)."""


class NoQualifiedLevelsError(PenetrationError):
    """Raised when no orderbook ask levels meet min_edge threshold."""


@dataclass(frozen=True)
class AskBook:
    """Ask order book containing (price, size) levels from top (best price) downwards."""

    levels: Tuple[Tuple[float, float], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.levels, (tuple, list)):
            raise InvalidOrderBookError(
                f"levels must be a sequence of (price, size) pairs, got {type(self.levels).__name__}"
            )
        if len(self.levels) == 0:
            raise InvalidOrderBookError("AskBook levels cannot be empty")

        normalized = []
        for idx, lvl in enumerate(self.levels):
            if not isinstance(lvl, (tuple, list)) or len(lvl) != 2:
                raise InvalidOrderBookError(
                    f"Level {idx} must be a 2-element tuple of (price, size), got {lvl!r}"
                )
            price, size = lvl
            if isinstance(price, bool) or not math.isfinite(price) or not (0 < price < 1):
                raise InvalidOrderBookError(
                    f"Level {idx} price must be finite in (0, 1), got {price}"
                )
            if isinstance(size, bool) or not math.isfinite(size) or size <= 0:
                raise InvalidOrderBookError(
                    f"Level {idx} size must be finite and positive, got {size}"
                )
            normalized.append((float(price), float(size)))

        for i in range(len(normalized) - 1):
            if normalized[i][0] >= normalized[i + 1][0]:
                raise InvalidOrderBookError(
                    f"AskBook levels must be strictly increasing in price (best to worst), got {normalized[i][0]} >= {normalized[i + 1][0]}"
                )

        object.__setattr__(self, "levels", tuple(normalized))


@dataclass(frozen=True)
class PenetrationPolicy:
    """Policy holding penetration probe threshold and release state."""

    min_edge: float
    provenance: str
    lock_state: SigmaAdjLockState

    def __post_init__(self) -> None:
        if isinstance(self.lock_state, str):
            try:
                normalized_lock = SigmaAdjLockState(self.lock_state)
                object.__setattr__(self, "lock_state", normalized_lock)
            except ValueError:
                raise InvalidPenetrationPolicyError(
                    f"lock_state must be 'F-2 LOCKED' or 'F2_RELEASED', got '{self.lock_state}'"
                )
        elif self.lock_state not in (SigmaAdjLockState.LOCKED, SigmaAdjLockState.RELEASED):
            raise InvalidPenetrationPolicyError(
                f"lock_state must be 'F-2 LOCKED' or 'F2_RELEASED', got '{self.lock_state}'"
            )
        if isinstance(self.min_edge, bool) or not math.isfinite(self.min_edge) or self.min_edge < 0:
            raise InvalidPenetrationPolicyError(
                f"min_edge must be finite and non-negative, got {self.min_edge}"
            )
        if not isinstance(self.provenance, str) or not self.provenance:
            raise InvalidPenetrationPolicyError(
                f"provenance must be a non-empty string, got {self.provenance!r}"
            )


@dataclass(frozen=True)
class ProbeResult:
    """Result of market penetration probe computation."""

    p_bar: float  # Qualified depth-weighted average price (pure book price)
    q_eff: float  # p_bar * (1 + fee_base * (1 - p_bar))
    net_ev: float  # p_hat - q_eff
    edge: float  # net_ev / q_eff
    s_target: float  # Sum of qualified levels size
    qualified_levels: Tuple[int, ...]  # Tuple of 0-based qualified level indices


def load_penetration_policy() -> PenetrationPolicy:
    """F-2 parameter entry point. Production calibration pending release in #156."""
    raise F2LockNotReleasedError(
        "F-2 lock is active: PenetrationPolicy parameters are LOCKED pending calibration release in #156."
    )


def _validate_probe_inputs(book: AskBook, p_hat: float, policy: PenetrationPolicy) -> None:
    if not isinstance(policy, PenetrationPolicy):
        raise InvalidPenetrationPolicyError(
            f"policy must be an instance of PenetrationPolicy, got {type(policy).__name__}"
        )
    if policy.lock_state != SigmaAdjLockState.RELEASED:
        raise F2LockNotReleasedError(
            "F-2 lock is active: policy cannot be evaluated until released (#156)."
        )
    if not isinstance(book, AskBook):
        raise InvalidOrderBookError(
            f"book must be an instance of AskBook, got {type(book).__name__}"
        )
    if isinstance(p_hat, bool) or not math.isfinite(p_hat) or not (0 < p_hat < 1):
        raise InvalidProbabilityError(
            f"p_hat must be finite probability in (0, 1), got {p_hat}"
        )


def compute_probe(book: AskBook, p_hat: float, policy: PenetrationPolicy) -> ProbeResult:
    """Compute market penetration probe metrics under given ask book, p_hat, and policy."""
    _validate_probe_inputs(book, p_hat, policy)

    qualified_indices = []
    qualified_sizes = []
    qualified_prices = []

    for idx, (price, size) in enumerate(book.levels):
        q_eff_j = price * (1 + FEE_BASE_RATIO * (1 - price))
        if (p_hat - q_eff_j) / q_eff_j >= policy.min_edge:
            qualified_indices.append(idx)
            qualified_sizes.append(size)
            qualified_prices.append(price)

    if not qualified_indices:
        raise NoQualifiedLevelsError(
            f"No ask levels meet min_edge threshold {policy.min_edge} with p_hat={p_hat}"
        )

    s_target = sum(qualified_sizes)
    p_bar = sum(p * s for p, s in zip(qualified_prices, qualified_sizes)) / s_target

    q_eff = p_bar * (1 + FEE_BASE_RATIO * (1 - p_bar))
    if q_eff <= 0:
        raise PenetrationError(f"Calculated q_eff must be positive, got {q_eff}")

    net_ev = p_hat - q_eff
    edge = net_ev / q_eff

    return ProbeResult(
        p_bar=p_bar,
        q_eff=q_eff,
        net_ev=net_ev,
        edge=edge,
        s_target=s_target,
        qualified_levels=tuple(qualified_indices),
    )


__all__ = [
    "FEE_BASE_PROVENANCE",
    "FEE_BASE_RATIO",
    "AskBook",
    "F2LockNotReleasedError",
    "InvalidOrderBookError",
    "InvalidPenetrationPolicyError",
    "InvalidProbabilityError",
    "NoQualifiedLevelsError",
    "PenetrationError",
    "PenetrationPolicy",
    "ProbeResult",
    "compute_probe",
    "load_penetration_policy",
]
