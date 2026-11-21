"""
High-Precision Discrete Bin Probability Engine (Phase 2 Task 04 - Ticket 01 / Issue #77).
Converts continuous Gaussian distributions (mu, sigma) into discrete Polymarket 1°F temperature contract bins
using scipy.special.ndtr with half-degree continuity correction.
"""

from dataclasses import dataclass
import logging
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
import numpy as np
from scipy.special import ndtr

from src.data_processing.constants import ACTIVE_10_STATIONS

logger = logging.getLogger(__name__)


class BinLadderValidationError(ValueError):
    """Raised when an integer bin ladder fails contiguous complete partition preconditions."""


@dataclass(frozen=True)
class IntegerBinSpec:
    """Closed integer settlement bin boundary ('.5°F' boundaries eliminated per P5 v1.1)."""

    bin_id: str
    label: str
    lower_int_f: Optional[int]
    upper_int_f: Optional[int]

    def __post_init__(self) -> None:
        if not self.bin_id or not self.bin_id.strip():
            raise BinLadderValidationError("bin_id must be non-empty")
        for attr in ("lower_int_f", "upper_int_f"):
            val = getattr(self, attr)
            if val is not None and (isinstance(val, bool) or not isinstance(val, int)):
                raise BinLadderValidationError(
                    f"{attr} must be Optional[int] (no floats/half-degrees), got {val!r}"
                )
        if self.lower_int_f is None and self.upper_int_f is None:
            raise BinLadderValidationError("Bin cannot be open on both lower and upper ends")
        if (
            self.lower_int_f is not None
            and self.upper_int_f is not None
            and self.lower_int_f > self.upper_int_f
        ):
            raise BinLadderValidationError(
                f"Inverted integer bin bounds: {self.lower_int_f} > {self.upper_int_f}"
            )

    @property
    def continuous_lower(self) -> float:
        return -float("inf") if self.lower_int_f is None else float(self.lower_int_f) - 0.5

    @property
    def continuous_upper(self) -> float:
        return float("inf") if self.upper_int_f is None else float(self.upper_int_f) + 0.5

    def contains_int(self, k: int) -> bool:
        low_ok = self.lower_int_f is None or k >= self.lower_int_f
        high_ok = self.upper_int_f is None or k <= self.upper_int_f
        return low_ok and high_ok


@dataclass(frozen=True)
class BinProbV11:
    """Single integer-bounded probability bin in `P5 ForecastDistributionSnapshot v1.1`."""

    bin_id: str
    label: str
    lower_int_f: Optional[int]
    upper_int_f: Optional[int]
    p_model: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bin_id": self.bin_id,
            "label": self.label,
            "lower_int_f": self.lower_int_f,
            "upper_int_f": self.upper_int_f,
            "p_model": self.p_model,
        }


def validate_contiguous_bin_ladder(bins: Sequence[IntegerBinSpec]) -> None:
    """Fail-closed guard guaranteeing integer bins form a complete contiguous Z partition."""
    if len(bins) < 2:
        raise BinLadderValidationError(f"Bin ladder requires >= 2 bins, got {len(bins)}")
    if bins[0].lower_int_f is not None or bins[0].upper_int_f is None:
        raise BinLadderValidationError("First bin must be lower-open and upper-bounded")
    if bins[-1].upper_int_f is not None or bins[-1].lower_int_f is None:
        raise BinLadderValidationError("Last bin must be upper-open and lower-bounded")
    seen_ids = set()
    for idx, b in enumerate(bins):
        if b.bin_id in seen_ids:
            raise BinLadderValidationError(f"Duplicate bin_id {b.bin_id!r}")
        seen_ids.add(b.bin_id)
        if 0 < idx < len(bins) - 1 and (b.lower_int_f is None or b.upper_int_f is None):
            raise BinLadderValidationError(f"Interior bin {idx} ({b.bin_id}) must have finite bounds")
    for idx in range(len(bins) - 1):
        cur_u, nxt_l = bins[idx].upper_int_f, bins[idx + 1].lower_int_f
        if cur_u is None or nxt_l is None or cur_u + 1 != nxt_l:
            raise BinLadderValidationError(
                f"Discontiguous or overlapping bin ladder between {bins[idx].bin_id!r} "
                f"(upper={cur_u}) and {bins[idx + 1].bin_id!r} (lower={nxt_l})"
            )


def _make_interior_integer_bins(
    first_interior_start_f: int,
    num_interior_bins: int,
    bin_width_f: int,
) -> Tuple[List[IntegerBinSpec], int]:
    interior: List[IntegerBinSpec] = []
    cursor = first_interior_start_f
    for _ in range(num_interior_bins):
        upper = cursor + bin_width_f - 1
        bid = f"{cursor}F" if cursor == upper else f"{cursor}-{upper}F"
        lbl = f"{cursor}°F" if cursor == upper else f"{cursor}-{upper}°F"
        interior.append(IntegerBinSpec(bin_id=bid, label=lbl, lower_int_f=cursor, upper_int_f=upper))
        cursor = upper + 1
    return interior, cursor


def build_integer_bin_ladder(
    *,
    first_interior_start_f: int,
    num_interior_bins: int,
    bin_width_f: int = 2,
) -> Tuple[IntegerBinSpec, ...]:
    """Build standard Polymarket integer contract ladder (`<= k0`, contiguous interior, `>= k1`)."""
    if isinstance(bin_width_f, bool) or not isinstance(bin_width_f, int) or bin_width_f < 1:
        raise ValueError(f"bin_width_f must be integer >= 1, got {bin_width_f!r}")
    if isinstance(num_interior_bins, bool) or not isinstance(num_interior_bins, int) or num_interior_bins < 1:
        raise ValueError(f"num_interior_bins must be >= 1, got {num_interior_bins!r}")
    lower_tail_max = first_interior_start_f - 1
    head = IntegerBinSpec(f"le_{lower_tail_max}F", f"<={lower_tail_max}°F", None, lower_tail_max)
    interior, next_start = _make_interior_integer_bins(
        first_interior_start_f, num_interior_bins, bin_width_f
    )
    tail = IntegerBinSpec(f"ge_{next_start}F", f">={next_start}°F", next_start, None)
    ladder = (head, *interior, tail)
    validate_contiguous_bin_ladder(ladder)
    return ladder


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
    step_size: float = 1.0
    is_tradeable_window: bool = True

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
            "step_size": float(self.step_size),
            "is_tradeable_window": bool(self.is_tradeable_window),
        }


def settle_half_up(val: float) -> int:
    """
    Statutory NWS WRH half-up rounding (round half away from negative infinity / round half up).
    Guarantees that .5 always rounds up (e.g. 68.5 -> 69, 2.5 -> 3, -0.5 -> 0).
    Explicitly prevents Python's native round() banker's rounding bug.
    """
    import math
    return int(math.floor(val + 0.5))


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

    @classmethod
    def generate_2deg_adsorbed_bins(
        cls,
        mu: float,
        station_id: Optional[str] = None,
    ) -> List[DiscreteBin]:
        """
        P4-AUDIT-RELIABILITY v1.1 Statutory 2°F Grid Specification:
        - Step size: 2°F
        - Grid lines: strictly even integers
        - Center bin: even 2°F bin containing mu, i.e. [2k* - 0.5, 2k* + 1.5) where 2k* = 2 * floor((mu + 0.5) / 2)
        - Window: 9-bin tradeable window centered such that center bin is strictly at slot 5 (0-indexed 4)
        - Tails: 2 exterior tail bins covering (-inf, window_low) and [window_high, +inf)
        - Total: Strictly 11 mutually exclusive and collectively exhaustive bins.
        """
        import math
        if station_id is not None and station_id not in ACTIVE_10_STATIONS:
            raise ValueError(
                f"Invalid station_id: '{station_id}'. Must be one of {sorted(ACTIVE_10_STATIONS)}"
            )

        # 1. Identify center even integer 2k*
        # Interval [2k* - 0.5, 2k* + 1.5) contains mu
        center_even = 2 * int(math.floor((mu + 0.5) / 2.0))

        # 2. Window has 9 bins, center bin is slot 4 (5th slot)
        # Leftmost window bin starts at center_even - 4 * 2 = center_even - 8
        e_start = center_even - 8
        e_end = center_even + 8

        bins: List[DiscreteBin] = []
        idx = 0

        # Left tail: < e_start
        bins.append(
            DiscreteBin(
                bin_index=idx,
                bin_type="lte",
                label=f"<{e_start}°F",
                lower_bound_f=-np.inf,
                upper_bound_f=float(e_start) - 0.5,
                nominal_temp_f=None,
                probability=0.0,
                step_size=np.inf,
                is_tradeable_window=False,
            )
        )
        idx += 1

        # 9 Window bins
        for j in range(9):
            e_k = e_start + 2 * j
            bins.append(
                DiscreteBin(
                    bin_index=idx,
                    bin_type="exact",
                    label=f"{e_k}-{e_k + 2}°F",
                    lower_bound_f=float(e_k) - 0.5,
                    upper_bound_f=float(e_k + 2) - 0.5,
                    nominal_temp_f=e_k,
                    probability=0.0,
                    step_size=2.0,
                    is_tradeable_window=True,
                )
            )
            idx += 1

        # Right tail: >= (e_end + 2)
        gte_edge = e_end + 2
        bins.append(
            DiscreteBin(
                bin_index=idx,
                bin_type="gte",
                label=f"≥{gte_edge}°F",
                lower_bound_f=float(gte_edge) - 0.5,
                upper_bound_f=np.inf,
                nominal_temp_f=None,
                probability=0.0,
                step_size=np.inf,
                is_tradeable_window=False,
            )
        )

        return bins

    @classmethod
    def calculate_2deg_bin_probabilities(
        cls,
        bins: List[DiscreteBin],
        cdf_fn: Any,
    ) -> List[float]:
        """
        Pure CDF differencing against continuous distribution F (no approximation):
        p_k = F(upper_bound_f) - F(lower_bound_f).
        Guarantees simplex conservation sum == 1.0.
        """
        probs: List[float] = []
        for b in bins:
            cdf_high = 1.0 if np.isposinf(b.upper_bound_f) else float(cdf_fn(b.upper_bound_f))
            cdf_low = 0.0 if np.isneginf(b.lower_bound_f) else float(cdf_fn(b.lower_bound_f))
            p = max(0.0, cdf_high - cdf_low)
            probs.append(p)

        total_p = sum(probs)
        if total_p > 1e-12:
            probs = [p / total_p for p in probs]

        return probs

    @classmethod
    def generate_integer_bins(
        cls,
        *,
        first_interior_start_f: int,
        num_interior_bins: int,
        bin_width_f: int = 2,
        station_id: Optional[str] = None,
    ) -> Tuple[IntegerBinSpec, ...]:
        """Generate `P5 v1.1` integer closed-interval market bins with contiguous ladder check."""
        if station_id is not None and station_id not in ACTIVE_10_STATIONS:
            raise ValueError(
                f"Invalid station_id: '{station_id}'. Must be one of {sorted(ACTIVE_10_STATIONS)}"
            )
        return build_integer_bin_ladder(
            first_interior_start_f=first_interior_start_f,
            num_interior_bins=num_interior_bins,
            bin_width_f=bin_width_f,
        )

    @staticmethod
    def validate_contiguous_integer_ladder(bins: Sequence[IntegerBinSpec]) -> None:
        """Enforce contiguous complete Z-partition preconditions prior to telescoping integration."""
        validate_contiguous_bin_ladder(bins)

    @staticmethod
    def calculate_integer_bin_probabilities(
        bins: Sequence[IntegerBinSpec],
        left_limit_cdf: Callable[[float], float],
        *,
        m_now_int_f: Optional[int] = None,
        is_bridge_active: bool = False,
    ) -> Tuple[Tuple[BinProbV11, ...], Optional[float]]:
        """Discretize left-limit CDF across contiguous integer bins by telescoping differences."""
        validate_contiguous_bin_ladder(bins)
        out: List[BinProbV11] = []
        p_bin_stay: Optional[float] = None
        for b in bins:
            p_bin = min(
                1.0,
                max(0.0, float(left_limit_cdf(b.continuous_upper)) - float(left_limit_cdf(b.continuous_lower))),
            )
            out.append(BinProbV11(b.bin_id, b.label, b.lower_int_f, b.upper_int_f, p_bin))
            if is_bridge_active and m_now_int_f is not None and b.contains_int(m_now_int_f):
                p_bin_stay = p_bin
        return tuple(out), p_bin_stay
