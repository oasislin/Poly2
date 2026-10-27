"""
Q7 Coverage Dual-Track Separation Module (Phase 2 Task 08 - Ticket 06).
Decouples exact analytical coverage (offline audit) from gaussian proxy interval (online pricing).
Enforces strict context separation and three non-mixing rules.
"""

from dataclasses import dataclass
from enum import Enum
import math
from typing import Any, Dict, Optional, Sequence, Tuple

Z_90_HALF_WIDTH: float = 1.6448536269514722  # Standard normal 95th percentile Φ⁻¹(0.95)
NOMINAL_INTERVAL_LEVEL: float = round(0.95 - 0.05, 12)  # = 0.9,消除二进制浮点残差


class CoverageTrackError(Exception):
    """Base exception for coverage track operations."""


class UnsupportedDistributionFamilyError(CoverageTrackError):
    """Raised when distribution family is unrecognized (fallback to gaussian forbidden)."""


class CoverageTrackMisuseError(CoverageTrackError):
    """Raised when execution context violates allowed track context."""


class InvalidCoverageInputError(CoverageTrackError):
    """Raised when calculation inputs (e.g. non-finite or non-positive sigma_eff) are invalid."""


class TrackContext(str, Enum):
    """Execution context distinguishing offline audit from online pricing."""

    OFFLINE_AUDIT = "OFFLINE_AUDIT"
    ONLINE_PRICING = "ONLINE_PRICING"


@dataclass(frozen=True)
class CoverageInterval:
    """Online pricing track output: bounded confidence interval with no coverage rate field."""

    lower: float
    upper: float
    interval_level: float


@dataclass(frozen=True)
class CoverageRate:
    """Offline audit track output: empirical coverage metrics with no interval bounds fields."""

    hits: int
    total: int
    coverage_rate: float
    interval_level: float


class ExactCoverageTrack:
    """Track A: Exact analytical bounds and empirical coverage rates for offline audit."""

    allowed_context: TrackContext = TrackContext.OFFLINE_AUDIT

    def __init__(self, context: Optional[TrackContext] = None) -> None:
        if context is not None and (
            not isinstance(context, TrackContext) or context != self.allowed_context
        ):
            raise CoverageTrackMisuseError(
                f"ExactCoverageTrack cannot run under context {context}. "
                f"Allowed context is {self.allowed_context}."
            )

    def bounds(
        self,
        mu: float,
        sigma_eff: float,
        family: str,
        shape_params: Dict[str, Any],
        context: TrackContext,
    ) -> Tuple[float, float]:
        """Compute exact 5% and 95% quantile bounds matching calibrated family."""
        if not isinstance(context, TrackContext) or context != self.allowed_context:
            raise CoverageTrackMisuseError(
                f"ExactCoverageTrack requires explicit context {self.allowed_context}, "
                f"got {context}."
            )
        if not math.isfinite(sigma_eff) or sigma_eff <= 0.0:
            raise InvalidCoverageInputError(
                f"sigma_eff must be finite and positive, got {sigma_eff}"
            )

        if family == "johnsonsu":
            g = float(shape_params["gamma"])
            d = float(shape_params["delta"])
            xi = float(shape_params["xi"])
            lam = float(shape_params["lambda"])
            z_low = xi + lam * math.sinh((-Z_90_HALF_WIDTH - g) / d)
            z_high = xi + lam * math.sinh((Z_90_HALF_WIDTH - g) / d)
        elif family == "evt_hybrid":
            z_low = float(shape_params["u_left"])
            z_high = float(shape_params["u_right"])
        elif family == "gaussian":
            z_low = -Z_90_HALF_WIDTH
            z_high = Z_90_HALF_WIDTH
        else:
            raise UnsupportedDistributionFamilyError(
                f"Unsupported distribution family '{family}'. "
                f"Supported families: 'johnsonsu', 'evt_hybrid', 'gaussian'."
            )

        return mu + sigma_eff * z_low, mu + sigma_eff * z_high

    def coverage(
        self,
        mu: float,
        sigma_eff: float,
        family: str,
        shape_params: Dict[str, Any],
        observations: Sequence[float],
        context: TrackContext,
    ) -> CoverageRate:
        """Calculate empirical hit count and coverage rate over observations."""
        if not isinstance(context, TrackContext) or context != self.allowed_context:
            raise CoverageTrackMisuseError(
                f"ExactCoverageTrack requires explicit context {self.allowed_context}, "
                f"got {context}."
            )
        if not observations:
            raise InvalidCoverageInputError("observations sequence cannot be empty")

        lower, upper = self.bounds(
            mu, sigma_eff, family, shape_params, context=context
        )
        hits = sum(1 for obs in observations if lower <= obs <= upper)
        total = len(observations)
        rate = hits / total
        return CoverageRate(
            hits=hits,
            total=total,
            coverage_rate=rate,
            interval_level=NOMINAL_INTERVAL_LEVEL,
        )


class GaussianProxyCoverageTrack:
    """Track B: Fast symmetric analytical interval for real-time online pricing."""

    allowed_context: TrackContext = TrackContext.ONLINE_PRICING

    def __init__(self, context: Optional[TrackContext] = None) -> None:
        if context is not None and (
            not isinstance(context, TrackContext) or context != self.allowed_context
        ):
            raise CoverageTrackMisuseError(
                f"GaussianProxyCoverageTrack cannot run under context {context}. "
                f"Allowed context is {self.allowed_context}."
            )

    def interval(
        self,
        mu: float,
        sigma_eff: float,
        context: TrackContext,
    ) -> CoverageInterval:
        """Compute fast symmetric proxy interval bounds mu +/- Z_90 * sigma_eff."""
        if not isinstance(context, TrackContext) or context != self.allowed_context:
            raise CoverageTrackMisuseError(
                f"GaussianProxyCoverageTrack requires explicit context {self.allowed_context}, "
                f"got {context}."
            )
        if not math.isfinite(sigma_eff) or sigma_eff <= 0.0:
            raise InvalidCoverageInputError(
                f"sigma_eff must be finite and positive, got {sigma_eff}"
            )

        half_width = Z_90_HALF_WIDTH * sigma_eff
        lower = mu - half_width
        upper = mu + half_width
        return CoverageInterval(
            lower=lower,
            upper=upper,
            interval_level=NOMINAL_INTERVAL_LEVEL,
        )
