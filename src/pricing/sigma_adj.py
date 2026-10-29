"""
Adaptive Variance Inflation sigma_adj Computation Engine (Phase 2 Task 08 - Ticket 07).
Implements ADR-0019 §4 variance inflation based on out-of-sample skill score s_oos.
Production parameters remain locked under F-2 pending calibration in #156.
"""

from dataclasses import dataclass
from enum import Enum
import math
from typing import Protocol

ADR_SIGMA_ADJ_REFERENCE: str = "ADR-0019 §4 第一道防线：σ_adj = √(max(1.0, s_oos)) · σ_eff"


class SigmaAdjError(Exception):
    """Base exception for sigma_adj calculation and policy errors."""


class F2LockNotReleasedError(SigmaAdjError):
    """Raised when calculation or policy access is attempted while F-2 lock is active."""


class InvalidSigmaAdjPolicyError(SigmaAdjError):
    """Raised when sigma_adj policy attributes or types are invalid."""


class InvalidSigmaAdjInputError(SigmaAdjError):
    """Raised when input parameters (s_oos or sigma_eff) are invalid."""


class SigmaAdjLockState(str, Enum):
    """Allowed release states for SigmaAdjPolicy."""

    LOCKED = "F-2 LOCKED"
    RELEASED = "F2_RELEASED"


class CellRecordProtocol(Protocol):
    """Structural protocol for calibrated cell records."""

    s_oos: float


class ParameterContractProtocol(Protocol):
    """Structural protocol for contract accessing cell calibration parameters."""

    def get_cell(self, station: str, lead_hours: int) -> CellRecordProtocol: ...


@dataclass(frozen=True)
class SigmaAdjPolicy:
    """Policy holding variance inflation parameters and release state."""

    exponent: float
    floor: float
    provenance: str
    lock_state: str  # Only "F-2 LOCKED" or "F2_RELEASED"

    def __post_init__(self) -> None:
        if self.lock_state not in (SigmaAdjLockState.LOCKED, SigmaAdjLockState.RELEASED):
            raise InvalidSigmaAdjPolicyError(
                f"lock_state must be 'F-2 LOCKED' or 'F2_RELEASED', got '{self.lock_state}'"
            )
        if isinstance(self.exponent, bool) or not math.isfinite(self.exponent) or self.exponent <= 0:
            raise InvalidSigmaAdjPolicyError(
                f"exponent must be finite and positive, got {self.exponent}"
            )
        if isinstance(self.floor, bool) or not math.isfinite(self.floor) or self.floor < 1:
            raise InvalidSigmaAdjPolicyError(
                f"floor must be finite and >= 1, got {self.floor}"
            )
        if not isinstance(self.provenance, str) or not self.provenance:
            raise InvalidSigmaAdjPolicyError(
                f"provenance must be a non-empty string, got {self.provenance!r}"
            )


def load_sigma_adj_policy() -> SigmaAdjPolicy:
    """F-2 parameter entry point. Production calibration pending release in #156."""
    raise F2LockNotReleasedError(
        "F-2 lock is active: SigmaAdjPolicy parameters are LOCKED pending calibration release in #156."
    )


def compute_sigma_adj(s_oos: float, sigma_eff: float, policy: SigmaAdjPolicy) -> float:
    """Pure function computing sigma_adj = (max(floor, s_oos)) ** exponent * sigma_eff."""
    if not isinstance(policy, SigmaAdjPolicy):
        raise InvalidSigmaAdjPolicyError(
            f"policy must be an instance of SigmaAdjPolicy, got {type(policy).__name__}"
        )
    if policy.lock_state == SigmaAdjLockState.LOCKED:
        raise F2LockNotReleasedError(
            "F-2 lock is active: policy cannot be evaluated until released (#156)."
        )

    if isinstance(sigma_eff, bool) or not math.isfinite(sigma_eff) or sigma_eff <= 0:
        raise InvalidSigmaAdjInputError(
            f"sigma_eff must be finite and positive, got {sigma_eff}"
        )
    if isinstance(s_oos, bool) or not math.isfinite(s_oos) or s_oos < 0:
        raise InvalidSigmaAdjInputError(
            f"s_oos must be finite and non-negative, got {s_oos}"
        )

    base = max(policy.floor, s_oos)
    return float((base ** policy.exponent) * sigma_eff)


def sigma_adj_for_cell(
    contract: ParameterContractProtocol,
    station: str,
    lead_hours: int,
    sigma_eff: float,
    policy: SigmaAdjPolicy,
) -> float:
    """Retrieve s_oos for exact cell from contract and compute sigma_adj without aggregation."""
    cell = contract.get_cell(station, lead_hours)
    return compute_sigma_adj(s_oos=cell.s_oos, sigma_eff=sigma_eff, policy=policy)
