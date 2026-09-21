"""
Unit tests for NWS WRH settlement rounding and borderline sentinel (Phase 2 Task 04 - Ticket 03 / Issue #79).
Implements ADR-0012 §D3 Half-Up rounding and PENDING-01 closure.
"""

from decimal import Decimal
import pytest

from src.settlement.rounding_simulator import (
    BorderlineAnalysis,
    BorderlineSentinel,
    replicate_nws_temperature_rounding,
)


class TestSettlementRoundingSimulator:
    """Test suite for ADR-0012 arithmetic half-up rounding and borderline scenarios."""

    def test_arithmetic_half_up_vs_bankers_rounding(self):
        """
        Verify Decimal ROUND_HALF_UP strictly differs from Python's banker's rounding on even .50.
        E.g.:
        74.50°F:
          - Python round(74.5) -> 74 (Banker's round-to-even)
          - NWS Half-Up -> 75 (Arithmetic half-up)
        75.50°F:
          - Python round(75.5) -> 76
          - NWS Half-Up -> 76
        """
        # 74.5: Even base, banker's rounding fails, half-up succeeds
        assert round(74.5) == 74  # Banker's rounding
        assert replicate_nws_temperature_rounding(74.5) == 75  # NWS Standard

        # 75.5: Odd base, both round up to 76
        assert replicate_nws_temperature_rounding(75.5) == 76

        # Standard non-ambiguous fractions
        assert replicate_nws_temperature_rounding(74.49) == 74
        assert replicate_nws_temperature_rounding(74.51) == 75
        assert replicate_nws_temperature_rounding(74.0) == 74
        assert replicate_nws_temperature_rounding(74.99) == 75

    def test_negative_temperature_half_up(self):
        """Verify negative temperatures round away from zero or half-up per standard decimal."""
        # -4.5 -> -5 (ROUND_HALF_UP in Decimal quantizes half away from zero)
        assert replicate_nws_temperature_rounding(-4.5) == -5
        assert replicate_nws_temperature_rounding(-4.49) == -4
        assert replicate_nws_temperature_rounding(-4.51) == -5

    def test_borderline_sentinel_critical_detection(self):
        """Verify sentinel flags observations within [X.45, X.55] as BORDERLINE_CRITICAL."""
        sentinel = BorderlineSentinel(tolerance=0.05)

        # 74.48 -> within [74.45, 74.55] -> Critical
        res1: BorderlineAnalysis = sentinel.analyze(74.48)
        assert res1.is_borderline is True
        assert res1.status == "BORDERLINE_CRITICAL"
        assert res1.down_int == 74
        assert res1.up_int == 75
        assert res1.expected_official_int == 74

        # 74.50 -> Critical
        res2: BorderlineAnalysis = sentinel.analyze(74.50)
        assert res2.is_borderline is True
        assert res2.status == "BORDERLINE_CRITICAL"
        assert res2.expected_official_int == 75

        # 74.53 -> Critical
        res3: BorderlineAnalysis = sentinel.analyze(74.53)
        assert res3.is_borderline is True
        assert res3.status == "BORDERLINE_CRITICAL"
        assert res3.expected_official_int == 75

        # 74.20 -> Safe
        res4: BorderlineAnalysis = sentinel.analyze(74.20)
        assert res4.is_borderline is False
        assert res4.status == "SAFE_NON_CRITICAL"
        assert res4.expected_official_int == 74

        # 74.80 -> Safe
        res5: BorderlineAnalysis = sentinel.analyze(74.80)
        assert res5.is_borderline is False
        assert res5.status == "SAFE_NON_CRITICAL"
        assert res5.expected_official_int == 75
