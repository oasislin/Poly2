"""
Unit and Integration Tests for Paper Trading Evaluation Engine (Phase 2 Wave 3 / W3-B).
Governed by docs/w3_polymarket_ingestion_preregistration.md Rev.1.0 & Work Order P7-W3-TASK2-AUTH-001.

Validates:
1. 过门槛信号: Edge >= 5% & Depth >= 10 -> POSITIVE_EV_SIGNAL, is_signal=True (B-3, B-5)
2. 未过门槛照记: Edge < 5% -> Recorded in ledger, is_signal=False (B-4)
3. NO_QUOTE 跳过: Missing book side -> Recorded with NO_QUOTE tag, is_signal=False (B-2)
4. 深度不足: Edge >= 5% but Depth < 10 -> POSITIVE_EV_SIGNAL + INSUFFICIENT_DEPTH, is_signal=False (B-5)
5. 分歧打标: |Model Prob - Mid Price| > 15pp -> MODEL_MARKET_DIVERGENCE, non-blocking (B-6)
6. PROB_STATIC: Unchanged model probability across snapshots -> PROB_STATIC tag (A-4)
7. Full Ledger Persistence with DATA_PROVENANCE == 'POLYMARKET_LIVE_CLOB' (B-4, E-2)
8. Bracket Bounds Parser & Simplex Conservation
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import numpy as np
import pytest

from src.data_acquisition.polymarket_clob_collector import (
    DATA_PROVENANCE_LIVE,
    CLOBQuote,
    MarketTokenBracket,
    PolymarketTemperatureMarket,
    SnapshotRecord,
)
from src.pricing.paper_evaluation_engine import (
    MIN_ORDERBOOK_DEPTH,
    MIN_POSITIVE_EV_EDGE,
    BracketEvaluationRecord,
    MarketEvaluationSnapshot,
    PaperEvaluationEngine,
    compute_bracket_probabilities,
    parse_bracket_bounds,
)


class TestBracketBoundsAndProbabilityIntegration:
    """Tests bracket text parsing and Gaussian simplex probability computation."""

    def test_parse_bracket_bounds_various_patterns(self):
        # Range
        assert parse_bracket_bounds("56-57°F") == (55.5, 57.5)
        assert parse_bracket_bounds("60 - 61 F") == (59.5, 61.5)
        # Left tail
        assert parse_bracket_bounds("55°F or below") == (-np.inf, 55.5)
        assert parse_bracket_bounds("≤50°F") == (-np.inf, 50.5)
        assert parse_bracket_bounds("48 or less") == (-np.inf, 48.5)
        # Right tail
        assert parse_bracket_bounds("76°F or above") == (75.5, np.inf)
        assert parse_bracket_bounds("≥72°F") == (71.5, np.inf)
        assert parse_bracket_bounds("80 or more") == (79.5, np.inf)
        # Single exact
        assert parse_bracket_bounds("65°F") == (64.5, 65.5)

    def test_compute_bracket_probabilities_simplex_conservation(self):
        brackets = [
            MarketTokenBracket("tok_1", "55°F or below", "Yes", "c1"),
            MarketTokenBracket("tok_2", "56-57°F", "Yes", "c2"),
            MarketTokenBracket("tok_3", "58-59°F", "Yes", "c3"),
            MarketTokenBracket("tok_4", "60°F or above", "Yes", "c4"),
        ]
        probs = compute_bracket_probabilities(brackets=brackets, mu=57.0, sigma=2.0)

        assert len(probs) == 4
        # Simplex sum == 1.0
        assert sum(probs.values()) == pytest.approx(1.0, abs=1e-6)
        # Peak probability should be at 56-57°F containing mu=57.0
        assert probs["tok_2"] > probs["tok_1"]
        assert probs["tok_2"] > probs["tok_4"]


class TestPaperEvaluationEngineScenarios:
    """Validates the 6 required scenarios in P7-W3-TASK2-AUTH-001."""

    @pytest.fixture
    def test_market_and_snapshot(self):
        """Construct a test market with 6 brackets to evaluate all scenarios."""
        brackets = [
            MarketTokenBracket("tok_win", "60-61°F", "Yes", "c1"),      # 1. 过门槛信号
            MarketTokenBracket("tok_low_ev", "62-63°F", "Yes", "c2"),   # 2. 未过门槛照记
            MarketTokenBracket("tok_no_q", "64-65°F", "Yes", "c3"),     # 3. NO_QUOTE 跳过
            MarketTokenBracket("tok_thin", "66-67°F", "Yes", "c4"),     # 4. 深度不足
            MarketTokenBracket("tok_div", "68-69°F", "Yes", "c5"),      # 5. 分歧打标
            MarketTokenBracket("tok_static", "70-71°F", "Yes", "c6"),   # 6. PROB_STATIC
        ]

        market = PolymarketTemperatureMarket(
            event_id="evt_paper_01",
            slug="highest-temp-test-oct-12",
            title="Highest temperature in Test City on October 12?",
            city="TestCity",
            station_id="KORD",
            target_date_str="2026-10-12",
            official_settlement_time=datetime(2026, 10, 12, 18, 0, 0, tzinfo=timezone.utc),
            brackets=brackets,
        )

        quotes = {
            # 1. tok_win: ask=0.30 (size=50 >= 10), bid=0.28, prob=0.40 -> edge = +0.10 >= 0.05
            "tok_win": CLOBQuote(
                token_id="tok_win",
                best_ask=0.30,
                best_bid=0.28,
                mid_price=0.29,
                best_ask_size=50.0,
                best_bid_size=50.0,
                quote_status="NORMAL",
            ),
            # 2. tok_low_ev: ask=0.20 (size=20), bid=0.18, prob=0.22 -> edge = +0.02 < 0.05
            "tok_low_ev": CLOBQuote(
                token_id="tok_low_ev",
                best_ask=0.20,
                best_bid=0.18,
                mid_price=0.19,
                best_ask_size=20.0,
                best_bid_size=20.0,
                quote_status="NORMAL",
            ),
            # 3. tok_no_q: missing bid side -> NO_QUOTE
            "tok_no_q": CLOBQuote(
                token_id="tok_no_q",
                best_ask=0.15,
                best_bid=None,
                mid_price=None,
                best_ask_size=15.0,
                best_bid_size=0.0,
                quote_status="NO_QUOTE",
            ),
            # 4. tok_thin: ask=0.10 (size=5.0 < 10), bid=0.08, prob=0.25 -> edge = +0.15 >= 0.05, but thin depth!
            "tok_thin": CLOBQuote(
                token_id="tok_thin",
                best_ask=0.10,
                best_bid=0.08,
                mid_price=0.09,
                best_ask_size=5.0,  # Below 10.0 threshold
                best_bid_size=20.0,
                quote_status="NORMAL",
            ),
            # 5. tok_div: ask=0.42, bid=0.38, mid=0.40, prob=0.10 -> divergence = |0.10 - 0.40| = 0.30 > 0.15
            "tok_div": CLOBQuote(
                token_id="tok_div",
                best_ask=0.42,
                best_bid=0.38,
                mid_price=0.40,
                best_ask_size=25.0,
                best_bid_size=25.0,
                quote_status="NORMAL",
            ),
            # 6. tok_static: ask=0.05, bid=0.03, mid=0.04, prob=0.03 -> normal quote
            "tok_static": CLOBQuote(
                token_id="tok_static",
                best_ask=0.05,
                best_bid=0.03,
                mid_price=0.04,
                best_ask_size=30.0,
                best_bid_size=30.0,
                quote_status="NORMAL",
            ),
        }

        snapshot = SnapshotRecord(
            snapshot_id="test_snapshot_01",
            timestamp_iso="2026-10-12T10:00:00Z",
            snapshot_layer="SETTLEMENT_PROBE_15M",
            data_provenance=DATA_PROVENANCE_LIVE,
            market_slug=market.slug,
            station_id=market.station_id,
            settlement_time_iso=market.official_settlement_time.isoformat(),
            hours_to_settlement=8.0,
            quotes=quotes,
        )

        model_probs = {
            "tok_win": 0.40,
            "tok_low_ev": 0.22,
            "tok_no_q": 0.05,
            "tok_thin": 0.20,
            "tok_div": 0.10,
            "tok_static": 0.03,
        }

        return market, snapshot, model_probs

    def test_six_paper_evaluation_scenarios(self, test_market_and_snapshot):
        market, snapshot, model_probs = test_market_and_snapshot
        engine = PaperEvaluationEngine()

        # Prime the static probability cache with prior value for tok_static
        engine._prev_model_probs["tok_static"] = 0.03  # identical -> PROB_STATIC

        eval_res = engine.evaluate_market_snapshot(
            market=market,
            snapshot=snapshot,
            model_probs=model_probs,
        )

        assert eval_res.data_provenance == DATA_PROVENANCE_LIVE
        assert len(eval_res.records) == 6

        rec_by_tid = {r.token_id: r for r in eval_res.records}

        # Scenario 1: 过门槛信号 (Edge >= 5% and Depth >= 10)
        r1 = rec_by_tid["tok_win"]
        assert r1.is_signal is True
        assert r1.eval_status == "APPROVED_POSITIVE_EV"
        assert "POSITIVE_EV_SIGNAL" in r1.tags
        assert r1.edge == pytest.approx(0.10)
        assert r1.best_ask_size >= MIN_ORDERBOOK_DEPTH

        # Scenario 2: 未过门槛照记 (Edge < 5%)
        r2 = rec_by_tid["tok_low_ev"]
        assert r2.is_signal is False
        assert r2.eval_status == "BELOW_EDGE_THRESHOLD"
        assert "POSITIVE_EV_SIGNAL" not in r2.tags
        assert r2.edge == pytest.approx(0.02)  # Persisted in ledger (B-4)

        # Scenario 3: NO_QUOTE 跳过 (Missing book side)
        r3 = rec_by_tid["tok_no_q"]
        assert r3.is_signal is False
        assert r3.eval_status == "NO_QUOTE"
        assert "NO_QUOTE" in r3.tags
        assert r3.edge is None

        # Scenario 4: 深度不足 (Edge >= 5%, but Depth < 10)
        r4 = rec_by_tid["tok_thin"]
        assert r4.is_signal is False
        assert r4.eval_status == "INSUFFICIENT_DEPTH"
        assert "POSITIVE_EV_SIGNAL" in r4.tags
        assert "INSUFFICIENT_DEPTH" in r4.tags
        assert r4.best_ask_size < MIN_ORDERBOOK_DEPTH

        # Scenario 5: 分歧打标 (|model_prob - mid_price| > 0.15)
        r5 = rec_by_tid["tok_div"]
        assert "MODEL_MARKET_DIVERGENCE" in r5.tags
        # Divergence is non-blocking
        assert r5.edge == pytest.approx(0.10 - 0.42)

        # Scenario 6: PROB_STATIC (identical probability across snapshots)
        r6 = rec_by_tid["tok_static"]
        assert "PROB_STATIC" in r6.tags
        assert r6.model_probability == pytest.approx(0.03)

    def test_full_ledger_persistence_and_provenance(self, test_market_and_snapshot):
        """B-4 & E-2: Full ledger persistence with data_provenance == POLYMARKET_LIVE_CLOB."""
        market, snapshot, model_probs = test_market_and_snapshot

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = PaperEvaluationEngine(storage_base_dir=Path(tmpdir))
            eval_res = engine.evaluate_market_snapshot(
                market=market,
                snapshot=snapshot,
                model_probs=model_probs,
            )

            saved_path = engine.save_evaluation_snapshot(eval_res)
            assert saved_path.exists()

            with open(saved_path, "r", encoding="utf-8") as f:
                payload = json.load(f)

            assert payload["data_provenance"] == "POLYMARKET_LIVE_CLOB"
            assert payload["market_slug"] == market.slug
            assert len(payload["records"]) == 6
            assert payload["summary"]["positive_ev_signals"] == 1
            assert payload["summary"]["divergence_count"] == 1
            assert payload["summary"]["no_quote_count"] == 1


class TestInputSuspectAndPipelineProvenance:
    """Validates the INPUT_SUSPECT isolation gate and PROB_SOURCE provenance stamping."""

    def test_input_suspect_triggers_quarantine_on_large_deviation(self):
        """When |M_model - M_market| > 8.0°F, signals are quarantined and is_signal=False."""
        brackets = [
            MarketTokenBracket("tok_low", "73°F or below", "Yes", "c1"),
            MarketTokenBracket("tok_mid", "84-85°F", "Yes", "c2"),
            MarketTokenBracket("tok_high", "86°F or above", "Yes", "c3"),
        ]
        market = PolymarketTemperatureMarket(
            event_id="evt_suspect_01",
            slug="highest-temp-chicago-oct-12",
            title="Chicago High Temp Oct 12",
            city="chicago",
            station_id="KORD",
            target_date_str="2026-10-12",
            official_settlement_time=datetime(2026, 10, 12, 18, 0, 0, tzinfo=timezone.utc),
            brackets=brackets,
        )
        quotes = {
            "tok_low": CLOBQuote("tok_low", best_ask=0.01, best_bid=0.005, mid_price=0.0075, best_ask_size=50.0, best_bid_size=50.0, quote_status="NORMAL"),
            "tok_mid": CLOBQuote("tok_mid", best_ask=0.70, best_bid=0.68, mid_price=0.69, best_ask_size=50.0, best_bid_size=50.0, quote_status="NORMAL"),
            "tok_high": CLOBQuote("tok_high", best_ask=0.30, best_bid=0.28, mid_price=0.29, best_ask_size=50.0, best_bid_size=50.0, quote_status="NORMAL"),
        }
        snapshot = SnapshotRecord(
            snapshot_id="snap_suspect_01",
            timestamp_iso="2026-10-11T12:00:00Z",
            snapshot_layer="BASELINE_60M",
            data_provenance=DATA_PROVENANCE_LIVE,
            market_slug=market.slug,
            station_id=market.station_id,
            settlement_time_iso=market.official_settlement_time.isoformat(),
            hours_to_settlement=24.0,
            quotes=quotes,
        )
        engine = PaperEvaluationEngine()

        # Case A: Erroneous model mu = 62.0°F (Market median ~ 85.0°F -> dev ~ 23°F > 8.0°F)
        eval_res = engine.evaluate_market_snapshot(
            market=market,
            snapshot=snapshot,
            mu=62.0,
            sigma=3.5,
            prob_source="CLIMATOLOGY_PLACEHOLDER",
        )
        assert eval_res.summary["is_input_suspect"] is True
        assert eval_res.summary["median_deviation"] > 8.0
        assert eval_res.summary["quarantined_signals"] > 0
        assert eval_res.summary["positive_ev_signals"] == 0

        rec_low = [r for r in eval_res.records if r.token_id == "tok_low"][0]
        assert rec_low.edge > 0.05
        assert rec_low.is_signal is False  # QUARANTINED!
        assert rec_low.eval_status == "QUARANTINED_INPUT_SUSPECT"
        assert "INPUT_SUSPECT" in rec_low.tags
        assert "QUARANTINED" in rec_low.tags
        assert rec_low.prob_source == "CLIMATOLOGY_PLACEHOLDER"

        # Case B: Clean model mu = 85.0°F (dev ~ 0.0°F <= 8.0°F)
        eval_clean = engine.evaluate_market_snapshot(
            market=market,
            snapshot=snapshot,
            mu=85.0,
            sigma=2.0,
            prob_source="EMOS_PIPELINE",
        )
        assert eval_clean.summary["is_input_suspect"] is False
        assert eval_clean.summary["median_deviation"] <= 8.0
        for r in eval_clean.records:
            assert "INPUT_SUSPECT" not in r.tags
            assert "QUARANTINED" not in r.tags
            assert r.prob_source == "EMOS_PIPELINE"

    def test_e4_rule_enforces_explicit_distribution_parameters(self):
        """Rule E-4: Calling compute_bracket_probabilities without explicit params must raise ValueError."""
        brackets = [MarketTokenBracket("b1", "60-61°F", "Yes", "c1")]
        with pytest.raises(ValueError, match="Rule E-4"):
            compute_bracket_probabilities(brackets=brackets)

    def test_real_emos_pipeline_execution_and_stamping(self):
        """Verify RealEMOSPipeline calculates valid parameters and stamps PROB_SOURCE_EMOS."""
        from src.prediction.real_emos_pipeline import RealEMOSPipeline, PROB_SOURCE_EMOS

        pipe = RealEMOSPipeline()
        members = {"c00": 88.0, "p01": 88.5, "p02": 89.0, "p03": 87.5, "p04": 89.2}
        result = pipe.predict(
            station_id="KMIA",
            target_date="2026-10-12",
            lead_hours=24,
            injected_members=members,
        )
        assert result.prob_source == PROB_SOURCE_EMOS
        assert result.station_id == "KMIA"
        assert result.season == "Autumn"
        assert result.mu > 85.0
        assert result.sigma > 0.0
        assert result.climatological_variance > 0.0
        assert "a" in result.emos_params

