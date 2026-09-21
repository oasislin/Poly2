"""
Truncated Probability Engine and Simplex Re-normalization (Phase 2 Task 04 - Ticket 02 / Issue #78).
Applies physical observed extreme temperature truncation (TMAX/TMIN) and re-normalizes surviving bins
to maintain a strict probability simplex (sum == 1.000000).
"""

from dataclasses import dataclass, field
import logging
from typing import List, Optional, Set
import numpy as np

from src.prediction.discrete_bin_engine import DiscreteBin

logger = logging.getLogger(__name__)


@dataclass
class TruncationResult:
    """Outcome of physical extreme truncation on discrete market bins."""
    bins: List[DiscreteBin]
    target_type: str
    observed_extreme_f: Optional[float]
    dead_bin_indices: Set[int] = field(default_factory=set)


class TruncatedProbabilityEngine:
    """
    Applies real-time physical extreme constraints to discrete market bins.
    Enforces ADR-0011 monotonic truncation:
    - For TMAX: All bins with upper_bound <= observed_extreme are irreversibly dead (P=0.0).
    - For TMIN: All bins with lower_bound >= observed_extreme are irreversibly dead (P=0.0).
    - Surviving bins are condition-renormalized to sum == 1.0.
    - Dead bin status is permanently locked.
    """

    def __init__(self):
        self._locked_dead_indices: Set[int] = set()

    def reset_locks(self) -> None:
        """Reset locked dead bin history (e.g. at calendar day rollover)."""
        self._locked_dead_indices.clear()

    def apply_truncation(
        self,
        bins: List[DiscreteBin],
        target_type: str,
        observed_extreme_f: Optional[float],
    ) -> TruncationResult:
        """
        Evaluate physical feasibility and re-normalize probabilities.
        """
        t_type = target_type.lower()
        if t_type not in ("max", "min"):
            raise ValueError(f"target_type must be 'max' or 'min', got '{target_type}'")

        # Copy bins
        evaluated_bins = [
            DiscreteBin(
                bin_index=b.bin_index,
                bin_type=b.bin_type,
                label=b.label,
                lower_bound_f=b.lower_bound_f,
                upper_bound_f=b.upper_bound_f,
                nominal_temp_f=b.nominal_temp_f,
                probability=b.probability,
            )
            for b in bins
        ]

        if observed_extreme_f is None:
            return TruncationResult(
                bins=evaluated_bins,
                target_type=t_type,
                observed_extreme_f=None,
                dead_bin_indices=set(self._locked_dead_indices),
            )

        # Identify newly dead bins
        for idx, b in enumerate(evaluated_bins):
            if idx in self._locked_dead_indices:
                continue

            if t_type == "max":
                # For maximum temp, if upper bound is <= observed temp, it cannot win
                if not np.isposinf(b.upper_bound_f) and b.upper_bound_f <= observed_extreme_f:
                    self._locked_dead_indices.add(idx)
            elif t_type == "min":
                # For minimum temp, if lower bound is >= observed temp, it cannot win
                if not np.isneginf(b.lower_bound_f) and b.lower_bound_f >= observed_extreme_f:
                    self._locked_dead_indices.add(idx)

        # Zero out all dead bins
        for idx in self._locked_dead_indices:
            if idx < len(evaluated_bins):
                evaluated_bins[idx].probability = 0.0

        # Calculate sum of surviving bins
        surviving_sum = sum(
            b.probability for idx, b in enumerate(evaluated_bins) if idx not in self._locked_dead_indices
        )

        if surviving_sum > 1e-12:
            # Conditional simplex re-normalization
            for idx, b in enumerate(evaluated_bins):
                if idx not in self._locked_dead_indices:
                    b.probability = float(b.probability / surviving_sum)
        else:
            # Extreme blowout protection: all exact bins dead -> assign 1.0 to tail
            if t_type == "max" and len(evaluated_bins) > 0:
                evaluated_bins[-1].probability = 1.0
                self._locked_dead_indices.discard(len(evaluated_bins) - 1)
            elif t_type == "min" and len(evaluated_bins) > 0:
                evaluated_bins[0].probability = 1.0
                self._locked_dead_indices.discard(0)

        return TruncationResult(
            bins=evaluated_bins,
            target_type=t_type,
            observed_extreme_f=observed_extreme_f,
            dead_bin_indices=set(self._locked_dead_indices),
        )
