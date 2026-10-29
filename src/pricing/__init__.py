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
from src.pricing.sigma_adj import (
    ADR_SIGMA_ADJ_REFERENCE,
    CellRecordProtocol,
    F2LockNotReleasedError,
    InvalidSigmaAdjInputError,
    InvalidSigmaAdjPolicyError,
    ParameterContractProtocol,
    SigmaAdjError,
    SigmaAdjLockState,
    SigmaAdjPolicy,
    compute_sigma_adj,
    load_sigma_adj_policy,
    sigma_adj_for_cell,
)

__all__ = [
    "ADR_SIGMA_ADJ_REFERENCE",
    "CellRecordProtocol",
    "CoverageInterval",
    "CoverageRate",
    "CoverageTrackError",
    "CoverageTrackMisuseError",
    "ExactCoverageTrack",
    "F2LockNotReleasedError",
    "GaussianProxyCoverageTrack",
    "InvalidCoverageInputError",
    "InvalidSigmaAdjInputError",
    "InvalidSigmaAdjPolicyError",
    "NOMINAL_INTERVAL_LEVEL",
    "ParameterContractProtocol",
    "SigmaAdjError",
    "SigmaAdjLockState",
    "SigmaAdjPolicy",
    "TrackContext",
    "UnsupportedDistributionFamilyError",
    "Z_90_HALF_WIDTH",
    "compute_sigma_adj",
    "load_sigma_adj_policy",
    "sigma_adj_for_cell",
]
