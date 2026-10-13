"""
tests/unit/pricing/test_w2_asset_governance.py:
Unit test suite for Phase 2 W2 Rev.1.1 Asset Governance and Pricing Contracts:
- R-W2-3: router fallback to FAILSAFE asset forced read-only downgrade (READ_ONLY_OBSERVE).
- R-W2-3: KMIA_12h flagged asset governance (COMPLETED_ECE_FLAGGED) and 50% position haircut.
- C4: Dead bin (prob = 0.0) negative EV rejection.
"""

import pytest

from src.pricing.ev_engine import (
    DynamicEVEngine,
    EVConfig,
    OrderBookLevel,
    OrderBookSnapshot,
    EVTradeSignal,
)


@pytest.fixture
def ev_engine():
    return DynamicEVEngine(EVConfig(min_reprice_edge=0.03, fee_rate=0.0))


@pytest.fixture
def standard_snapshot():
    return OrderBookSnapshot(
        station_id="KMIA",
        bin_index=4,
        bin_label="78-80°F",
        bids=[OrderBookLevel(price=0.35, size=50.0)],
        asks=[OrderBookLevel(price=0.40, size=100.0), OrderBookLevel(price=0.45, size=100.0)],
    )


class TestW2AssetGovernance:
    """Test suite for R-W2-3 asset governance in pricing and EV engine."""

    def test_failsafe_fallback_asset_forces_readonly_downgrade(self, ev_engine, standard_snapshot):
        """
        R-W2-3:
        When is_failsafe=True, pricing signal MUST be downgraded to read-only observation.
        is_tradable MUST be False, target_size MUST be 0.0, reason MUST be FAILSAFE_DEGRADED_READONLY.
        """
        model_prob = 0.60  # Significant positive EV (60% model prob vs 40c Ask)
        target_size = 50.0

        signal: EVTradeSignal = ev_engine.evaluate_bin(
            snapshot=standard_snapshot,
            model_probability=model_prob,
            target_size=target_size,
            is_failsafe=True,
        )

        # Assertions
        assert signal.is_tradable is False
        assert signal.target_size == 0.0
        assert signal.reason == "FAILSAFE_DEGRADED_READONLY"
        assert "FAILSAFE_DEGRADED_READONLY" in signal.governance_flags
        # Theoretical metrics are preserved for read-only observation
        assert signal.effective_price == pytest.approx(0.40)
        assert signal.net_ev == pytest.approx(0.20)
        assert signal.edge == pytest.approx(0.50)

    def test_kmia_12h_flagged_asset_applies_50_pct_haircut(self, ev_engine, standard_snapshot):
        """
        R-W2-3:
        When is_flagged=True, target_size MUST be halved (50% position discount),
        and governance_flags MUST include COMPLETED_ECE_FLAGGED.
        """
        model_prob = 0.55
        target_size = 80.0  # Nominally 80 units

        signal: EVTradeSignal = ev_engine.evaluate_bin(
            snapshot=standard_snapshot,
            model_probability=model_prob,
            target_size=target_size,
            is_failsafe=False,
            is_flagged=True,
            flag_label="KMIA_12h_ECE_0.018318",
        )

        assert signal.is_tradable is True
        # Target size halved: 80 -> 40
        assert signal.target_size == pytest.approx(40.0)
        assert signal.reason == "APPROVED_POSITIVE_EV"
        assert "KMIA_12h_ECE_0.018318" in signal.governance_flags

    def test_dead_bin_zero_prob_is_rejected_negative_ev(self, ev_engine, standard_snapshot):
        """
        C4 Gate:
        A dead bin with model_probability = 0.0 MUST always produce negative EV and be rejected.
        """
        signal: EVTradeSignal = ev_engine.evaluate_bin(
            snapshot=standard_snapshot,
            model_probability=0.0,
            target_size=50.0,
        )

        assert signal.is_tradable is False
        assert signal.net_ev == pytest.approx(-0.40)
        assert signal.reason == "REJECTED_NEGATIVE_EV"
