"""
NWS WRH Official Settlement Rounding Simulator and Borderline Sentinel (Phase 2 Task 04 - Ticket 03 / Issue #79).
Implements ADR-0012 §D3 Decimal Half-Up rounding and PENDING-01 resolution.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import math
from typing import Dict, Any, Optional


def replicate_nws_temperature_rounding(temp_f: float) -> int:
    """
    Replicate official NWS arithmetic half-up rounding (ADR-0012 §D3).
    Strictly avoids Python's default banker's rounding (round-to-even).
    E.g.: 74.50°F -> 75 (Python's round(74.5) returns 74).
    """
    # Round float slightly to remove IEEE-754 representation noise before Decimal conversion
    cleaned_str = f"{temp_f:.4f}".rstrip("0").rstrip(".")
    d = Decimal(cleaned_str)
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class BorderlineAnalysis:
    """Detailed evaluation of an observation near a .50°F rounding boundary."""
    temp_f: float
    is_borderline: bool
    status: str  # "BORDERLINE_CRITICAL" or "SAFE_NON_CRITICAL"
    expected_official_int: int
    down_int: int
    up_int: int
    distance_to_half: float

    def to_dict(self) -> Dict[str, Any]:
        """Serialize analysis to dictionary."""
        return {
            "temp_f": self.temp_f,
            "is_borderline": self.is_borderline,
            "status": self.status,
            "expected_official_int": self.expected_official_int,
            "down_int": self.down_int,
            "up_int": self.up_int,
            "distance_to_half": self.distance_to_half,
        }


class BorderlineSentinel:
    """
    Monitors observations falling in [X.45, X.55] critical rounding ambiguity windows.
    Flags BORDERLINE_CRITICAL and provides dual-scenario projections.
    """

    def __init__(self, tolerance: float = 0.05):
        self.tolerance = tolerance

    def analyze(self, temp_f: float) -> BorderlineAnalysis:
        """
        Analyze whether temp_f is within tolerance of any integer + 0.5 boundary.
        """
        floor_val = math.floor(temp_f)
        half_boundary = floor_val + 0.5
        distance = abs(temp_f - half_boundary)

        is_critical = (distance <= self.tolerance + 1e-9)
        official_int = replicate_nws_temperature_rounding(temp_f)

        return BorderlineAnalysis(
            temp_f=float(temp_f),
            is_borderline=is_critical,
            status="BORDERLINE_CRITICAL" if is_critical else "SAFE_NON_CRITICAL",
            expected_official_int=official_int,
            down_int=floor_val,
            up_int=floor_val + 1,
            distance_to_half=round(float(distance), 4),
        )
