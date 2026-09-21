"""
High-Precision Discrete Bin Probability Engine (Phase 2 Task 04 - Ticket 01 / Issue #77).
Converts continuous Gaussian distributions (mu, sigma) into discrete Polymarket 1°F temperature contract bins
using scipy.special.ndtr with half-degree continuity correction.
"""

from dataclasses import dataclass
import logging
from typing import Any, Dict, List, Optional
import numpy as np
from scipy.special import ndtr

from src.data_processing.constants import ACTIVE_10_STATIONS

logger = logging.getLogger(__name__)


@dataclass
class DiscreteBin:
    """Represents a single discrete temperature bin in a Polymarket contract."""
    bin_index: int
    bin_type: str  # 'lte', 'exact', 'gte'
    label: str
    lower_bound_f: float
    upper_bound_f: float
    nominal_temp_f: Optional[int] = None
    probability: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize DiscreteBin to dictionary."""
        return {
            "bin_index": self.bin_index,
            "bin_type": self.bin_type,
            "label": self.label,
            "lower_bound_f": float(self.lower_bound_f),
            "upper_bound_f": float(self.upper_bound_f),
            "nominal_temp_f": self.nominal_temp_f,
            "probability": float(self.probability),
        }


class DiscreteBinEngine:
    """
    Integrates continuous Gaussian probability distributions into discrete Polymarket 1°F bins.
    Enforces Active 10 station metadata validation, half-degree continuity correction,
    and probability simplex normalization.
    """

    @classmethod
    def generate_standard_bins(
        cls,
        center_temp_f: int,
        num_exact_bins: int = 5,
        station_id: Optional[str] = None,
    ) -> List[DiscreteBin]:
        """
        Generate standard mutually exclusive, collectively exhaustive 1°F market bins.
        E.g., for center=70, num_exact=5:
        <=67°F, 68°F, 69°F, 70°F, 71°F, 72°F, >=73°F.
        """
        if station_id is not None and station_id not in ACTIVE_10_STATIONS:
            raise ValueError(
                f"Invalid station_id: '{station_id}'. Must be one of {sorted(ACTIVE_10_STATIONS)}"
            )

        half_span = num_exact_bins // 2
        start_exact = center_temp_f - half_span
        end_exact = start_exact + num_exact_bins - 1

        bins: List[DiscreteBin] = []
        idx = 0

        # 1. Left tail: <= (start_exact - 1)
        lte_val = start_exact - 1
        bins.append(
            DiscreteBin(
                bin_index=idx,
                bin_type="lte",
                label=f"≤{lte_val}°F",
                lower_bound_f=-np.inf,
                upper_bound_f=float(lte_val) + 0.5,
                nominal_temp_f=lte_val,
            )
        )
        idx += 1

        # 2. Exact integer bins: [start_exact, end_exact]
        for t in range(start_exact, end_exact + 1):
            bins.append(
                DiscreteBin(
                    bin_index=idx,
                    bin_type="exact",
                    label=f"{t}°F",
                    lower_bound_f=float(t) - 0.5,
                    upper_bound_f=float(t) + 0.5,
                    nominal_temp_f=t,
                )
            )
            idx += 1

        # 3. Right tail: >= (end_exact + 1)
        gte_val = end_exact + 1
        bins.append(
            DiscreteBin(
                bin_index=idx,
                bin_type="gte",
                label=f"≥{gte_val}°F",
                lower_bound_f=float(gte_val) - 0.5,
                upper_bound_f=np.inf,
                nominal_temp_f=gte_val,
            )
        )

        return bins

    @classmethod
    def calculate_bin_probabilities(
        cls,
        mu: float,
        sigma: float,
        bins: List[DiscreteBin],
        normalize: bool = True,
    ) -> List[DiscreteBin]:
        """
        Integrate continuous gaussian distribution across discrete bins using scipy.special.ndtr.
        P(i) = ndtr((upper - mu) / sigma) - ndtr((lower - mu) / sigma).
        """
        if sigma <= 0.0:
            raise ValueError(f"sigma must be strictly positive, got {sigma}")

        evaluated_bins: List[DiscreteBin] = []
        raw_probs: List[float] = []

        for b in bins:
            # Handle -inf and +inf bounds
            cdf_high = 1.0 if np.isposinf(b.upper_bound_f) else float(ndtr((b.upper_bound_f - mu) / sigma))
            cdf_low = 0.0 if np.isneginf(b.lower_bound_f) else float(ndtr((b.lower_bound_f - mu) / sigma))

            p = max(0.0, cdf_high - cdf_low)
            raw_probs.append(p)

            evaluated_bins.append(
                DiscreteBin(
                    bin_index=b.bin_index,
                    bin_type=b.bin_type,
                    label=b.label,
                    lower_bound_f=b.lower_bound_f,
                    upper_bound_f=b.upper_bound_f,
                    nominal_temp_f=b.nominal_temp_f,
                    probability=p,
                )
            )

        if normalize and len(evaluated_bins) > 0:
            total_prob = sum(raw_probs)
            if total_prob > 1e-12:
                for b in evaluated_bins:
                    b.probability = float(b.probability / total_prob)

        return evaluated_bins
