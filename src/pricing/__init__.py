"""
Pricing package root (Phase 2 Task 08 - Ticket 06).
Exports dual-track coverage classes, data structures, and exceptions.
"""

from src.pricing.coverage_dual_track import (
    CoverageInterval,
    CoverageRate,
    CoverageTrackError,
    CoverageTrackMisuseError,
    ExactCoverageTrack,
    GaussianProxyCoverageTrack,
    InvalidCoverageInputError,
    NOMINAL_INTERVAL_LEVEL,
    TrackContext,
    UnsupportedDistributionFamilyError,
    Z_90_HALF_WIDTH,
)

__all__ = [
    "CoverageInterval",
    "CoverageRate",
    "CoverageTrackError",
    "CoverageTrackMisuseError",
    "ExactCoverageTrack",
    "GaussianProxyCoverageTrack",
    "InvalidCoverageInputError",
    "NOMINAL_INTERVAL_LEVEL",
    "TrackContext",
    "UnsupportedDistributionFamilyError",
    "Z_90_HALF_WIDTH",
]
