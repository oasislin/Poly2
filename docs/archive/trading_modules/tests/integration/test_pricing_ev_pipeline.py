"""
Integration Test Suite: Pricing and EV Pipeline (Phase 2 Task 04 - Ticket 05 / Issue #81).
Validates end-to-end flow:
Continuous EMOS (mu, sigma) -> High-Precision ndtr Bin Integration -> Monotonic Extreme Truncation & Re-normalization ->
NWS Half-Up Rounding & Borderline Sentinel -> OrderBook Depth Penetration -> Positive EV Trade Signal.
"""

import numpy as np
import pytest

from src.prediction.discrete_bin_engine import DiscreteBinEngine
from src.prediction.truncated_probability_engine import TruncatedProbabilityEngine
from src.pricing.ev_engine import (
    DynamicEVEngine,
    EVConfig,
    OrderBookLevel,
    OrderBookSnapshot,
)
from src.settlement.rounding_simulator import (
    BorderlineSentinel,
    replicate_nws_temperature_rounding,
)


class TestPricingEVPipelineIntegration:
    """End-to-end integration test suite for Phase 2 Task 04 pricing & EV pipeline."""

    def test_full_pipeline_from_gaussian_to_positive_ev_signal(self):
        """
        Verify complete workflow:
        1. DiscreteBinEngine generates 1°F bins for KORD and integrates mu=70.0, sigma=2.0
        2. Real-time TMAX hits 69.6°F -> TruncatedProbabilityEngine kills <=67, 68, 69 bins
        3. Surviving bins (70°F, 71°F, 72°F, >=73°F) re-normalize to simplex sum == 1.0
        4. Injected orderbooks:
           - Bin 70°F is underpriced by market (Ask = $0.40, but model re-normalized prob = 0.58) -> +EV Signal
           - Bin 69°F (dead bin) has market Ask = $0.15, but model prob = 0.0 -> Negative EV Rejected
        """
        # Step 1: DiscreteBinEngine
        bins = DiscreteBinEngine.generate_standard_bins(
            center_temp_f=70,
            num_exact_bins=5,
            station_id="KORD",
        )
        evaluated_bins = DiscreteBinEngine.calculate_bin_probabilities(
            mu=70.0,
            sigma=2.0,
            bins=bins,
        )
        assert sum(b.probability for b in evaluated_bins) == pytest.approx(1.0, abs=1e-6)

        # Step 2: TruncatedProbabilityEngine
        trunc_engine = TruncatedProbabilityEngine()
        trunc_res = trunc_engine.apply_truncation(
            bins=evaluated_bins,
            target_type="max",
            observed_extreme_f=69.6,  # 69.6°F kills upper <= 69.6
        )

        assert trunc_res.bins[0].probability == 0.0  # <=67°F
        assert trunc_res.bins[1].probability == 0.0  # 68°F
        assert trunc_res.bins[2].probability == 0.0  # 69°F

        # Step 3: Check surviving bins sum to 1.0
        assert sum(b.probability for b in trunc_res.bins) == pytest.approx(1.0, abs=1e-6)
        prob_70 = trunc_res.bins[3].probability
        assert prob_70 > 0.30  # Re-normalized conditional probability of peak bin (~0.33)

        # Step 4: DynamicEVEngine
        ev_engine = DynamicEVEngine(EVConfig(min_reprice_edge=0.03, fee_rate=0.0))

        # Evaluate 70°F bin (Positive EV: Model Prob ~0.33 vs Market Ask = $0.22)
        book_70 = OrderBookSnapshot(
            station_id="KORD",
            bin_index=3,
            bin_label="70°F",
            asks=[
                OrderBookLevel(price=0.20, size=50.0),
                OrderBookLevel(price=0.24, size=50.0),
            ],
        )
        signal_70 = ev_engine.evaluate_bin(
            snapshot=book_70,
            model_probability=prob_70,
            target_size=100.0,  # VWAP = (50*0.20 + 50*0.24) / 100 = 0.22
        )
        assert signal_70.is_tradable is True
        assert signal_70.effective_price == pytest.approx(0.22, abs=1e-4)
        assert signal_70.net_ev > 0.08
        assert signal_70.edge > 0.30
        assert signal_70.reason == "APPROVED_POSITIVE_EV"

        # Evaluate 69°F dead bin (Must reject even if market price is dirt cheap at $0.05)
        book_69 = OrderBookSnapshot(
            station_id="KORD",
            bin_index=2,
            bin_label="69°F",
            asks=[OrderBookLevel(price=0.05, size=100.0)],
        )
        signal_69 = ev_engine.evaluate_bin(
            snapshot=book_69,
            model_probability=trunc_res.bins[2].probability,  # 0.0
            target_size=50.0,
        )
        assert signal_69.is_tradable is False
        assert signal_69.net_ev == pytest.approx(-0.05, abs=1e-4)
        assert signal_69.reason == "REJECTED_NEGATIVE_EV"

    def test_borderline_sentinel_with_half_up_settlement(self):
        """Verify borderline observation triggers critical warning and half-up resolves correctly."""
        sentinel = BorderlineSentinel(tolerance=0.05)
        # Real-time max reaches 74.50°F
        analysis = sentinel.analyze(74.50)
        assert analysis.is_borderline is True
        assert analysis.status == "BORDERLINE_CRITICAL"

        # Settles to 75°F (whereas Python round(74.5) would erroneously settle to 74)
        official_int = replicate_nws_temperature_rounding(74.50)
        assert official_int == 75
        assert official_int != round(74.50)
