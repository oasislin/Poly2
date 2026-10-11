"""
Unit Tests for W3 Offline Replay and Performance Analysis Engine (D-1, D-2, D-3).
Governed by docs/w3_polymarket_ingestion_preregistration.md Rev.1.1 (Work Order P7-W3-TASK3-AUTH-001).
"""

from datetime import datetime, timedelta, timezone
import json
import pytest

from src.pricing.w3_offline_replay_analyzer import (
    D1_SWEEP_THRESHOLDS,
    D2_JUMP_THRESHOLD,
    W3OfflineReplayAnalyzer,
)


class TestD1ThresholdSweepFramework:
    """Validates D-1 Threshold Sweep (2% to 15% Edge Replay)."""

    @pytest.fixture
    def mock_b4_snapshots(self):
        """Construct mock B-4 ledger snapshots with various edges and depths."""
        records = [
            {"token_id": "tok_01", "best_ask": 0.10, "best_ask_size": 20.0, "edge": 0.12, "tags": ["POSITIVE_EV_SIGNAL"]},
            {"token_id": "tok_02", "best_ask": 0.20, "best_ask_size": 15.0, "edge": 0.08, "tags": ["POSITIVE_EV_SIGNAL"]},
            {"token_id": "tok_03", "best_ask": 0.30, "best_ask_size": 50.0, "edge": 0.04, "tags": []},
            {"token_id": "tok_04", "best_ask": 0.40, "best_ask_size": 12.0, "edge": 0.025, "tags": []},
            {"token_id": "tok_thin", "best_ask": 0.50, "best_ask_size": 5.0, "edge": 0.10, "tags": ["INSUFFICIENT_DEPTH"]},  # depth < 10
            {"token_id": "tok_quar", "best_ask": 0.05, "best_ask_size": 50.0, "edge": 0.90, "tags": ["QUARANTINED", "INPUT_SUSPECT"]},  # quarantined
        ]
        return [
            {
                "snapshot_id": "snap_01",
                "timestamp_iso": "2026-10-12T10:00:00Z",
                "market_slug": "highest-temp-city-oct-12",
                "summary": {"is_input_suspect": False},
                "records": records,
            }
        ]

    def test_d1_sweep_monotonically_non_increasing(self, mock_b4_snapshots):
        analyzer = W3OfflineReplayAnalyzer()
        curve = analyzer.sweep_thresholds_d1(mock_b4_snapshots)

        assert len(curve) == len(D1_SWEEP_THRESHOLDS)
        assert curve[0].threshold == 0.02
        assert curve[-1].threshold == 0.15

        # Signal counts must be monotonically non-increasing as threshold increases
        counts = [p.signal_count for p in curve]
        for i in range(1, len(counts)):
            assert counts[i] <= counts[i - 1]

        # At 2% threshold: tok_01 (0.12), tok_02 (0.08), tok_03 (0.04), tok_04 (0.025) pass -> 4 signals
        assert curve[0].signal_count == 4
        # tok_thin (depth 5 < 10) and tok_quar (quarantined) must be excluded
        assert curve[0].signal_frequency_rate == 1.0  # 4 out of 4 eligible

        # At 5% threshold: tok_01 (0.12) and tok_02 (0.08) pass -> 2 signals
        p_5pct = [p for p in curve if abs(p.threshold - 0.05) < 1e-4][0]
        assert p_5pct.signal_count == 2
        assert p_5pct.mean_edge == pytest.approx(0.10)

        # At 15% threshold: none pass -> 0 signals
        assert curve[-1].signal_count == 0
        assert curve[-1].mean_edge == 0.0


class TestD2MetricALeadLagFollowing:
    """Validates D-2 Metric A (Lead-Lag Following)."""

    def test_d2_significant_market_following(self):
        """Case A: Model jump > 3pp followed by market midpoint within 1..3 snapshots."""
        t0 = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
        snapshots = [
            # t0: base state, prob = 0.20, mid = 0.20
            {
                "timestamp_iso": (t0).isoformat(),
                "market_slug": "market_test",
                "records": [{"token_id": "tok_win", "bracket_label": "88-89°F", "model_probability": 0.20, "mid_price": 0.20}],
            },
            # t1: model jumps +0.06 (> 0.03 jump), prob = 0.26, mid = 0.20
            {
                "timestamp_iso": (t0 + timedelta(minutes=15)).isoformat(),
                "market_slug": "market_test",
                "records": [{"token_id": "tok_win", "bracket_label": "88-89°F", "model_probability": 0.26, "mid_price": 0.20}],
            },
            # t2 (lag=1): market midpoint follows, mid moves up to 0.25 (delta = +0.05)
            {
                "timestamp_iso": (t0 + timedelta(minutes=30)).isoformat(),
                "market_slug": "market_test",
                "records": [{"token_id": "tok_win", "bracket_label": "88-89°F", "model_probability": 0.26, "mid_price": 0.25}],
            },
        ]

        analyzer = W3OfflineReplayAnalyzer()
        res = analyzer.evaluate_metric_a_lead_lag_d2(snapshots)

        assert res.total_jump_events == 1
        assert res.followed_events == 1
        assert res.follow_rate == 1.0
        assert res.average_lag == 1.0
        assert res.verdict == "RETAIN_PROBE_LAYER"

    def test_d2_market_not_following_leads_to_cut_verdict(self):
        """Case B: Model jump > 3pp, but market does not follow or moves opposite."""
        t0 = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
        snapshots = [
            {
                "timestamp_iso": (t0).isoformat(),
                "market_slug": "market_test",
                "records": [{"token_id": "tok_win", "bracket_label": "88-89°F", "model_probability": 0.20, "mid_price": 0.25}],
            },
            # Model jumps up +0.05
            {
                "timestamp_iso": (t0 + timedelta(minutes=15)).isoformat(),
                "market_slug": "market_test",
                "records": [{"token_id": "tok_win", "bracket_label": "88-89°F", "model_probability": 0.25, "mid_price": 0.25}],
            },
            # Market moves down (opposite) in next 2 snapshots
            {
                "timestamp_iso": (t0 + timedelta(minutes=30)).isoformat(),
                "market_slug": "market_test",
                "records": [{"token_id": "tok_win", "bracket_label": "88-89°F", "model_probability": 0.25, "mid_price": 0.23}],
            },
            {
                "timestamp_iso": (t0 + timedelta(minutes=45)).isoformat(),
                "market_slug": "market_test",
                "records": [{"token_id": "tok_win", "bracket_label": "88-89°F", "model_probability": 0.25, "mid_price": 0.22}],
            },
        ]

        analyzer = W3OfflineReplayAnalyzer()
        res = analyzer.evaluate_metric_a_lead_lag_d2(snapshots)

        assert res.total_jump_events == 1
        assert res.followed_events == 0
        assert res.follow_rate == 0.0
        assert res.verdict == "CUT_PROBE_LAYER"


class TestD3MetricBCalibrationRealization:
    """Validates D-3 Metric B (Calibration Realization & Brier Score Comparison)."""

    def test_d3_model_advantage_yields_true_ev(self):
        """Model Brier score is lower than market -> TRUE_EV_ADVANTAGE."""
        snapshots = [
            {
                "market_slug": "mkt_01",
                "records": [
                    # Winning bracket: model predicted 0.70, market predicted 0.30 -> model much closer to 1
                    {"token_id": "tok_win", "model_probability": 0.70, "mid_price": 0.30, "edge": 0.40, "tags": ["POSITIVE_EV_SIGNAL"]},
                    # Losing bracket: model predicted 0.05, market predicted 0.25 -> model much closer to 0
                    {"token_id": "tok_lose", "model_probability": 0.05, "mid_price": 0.25, "edge": -0.20, "tags": []},
                ],
            }
        ]
        settlements = {"mkt_01": "tok_win"}

        analyzer = W3OfflineReplayAnalyzer()
        res = analyzer.evaluate_metric_b_calibration_d3(snapshots, settlements)

        assert res is not None
        assert res.sample_count == 1  # Only tok_win had edge >= 0.05
        # tok_win: y=1. BS_model = (0.70 - 1)^2 = 0.09. BS_mkt = (0.30/0.55 - 1)^2 or approx
        assert res.model_brier_score < res.market_brier_score
        assert res.brier_skill_score > 0.0
        assert res.verdict == "TRUE_EV_ADVANTAGE"
        # Check mandatory disclosure clause
        assert "Annex A Clause 1" in res.limitation_disclosure

    def test_d3_model_disadvantage_yields_raise_threshold(self):
        """Model Brier score worse than market -> RAISE_THRESHOLD_OR_CUT_PROBE."""
        snapshots = [
            {
                "market_slug": "mkt_02",
                "records": [
                    # tok_wrong had edge >= 0.05 but lost: model predicted 0.80, market predicted 0.10, outcome y=0
                    {"token_id": "tok_wrong", "model_probability": 0.80, "mid_price": 0.10, "edge": 0.70, "tags": ["POSITIVE_EV_SIGNAL"]},
                    # tok_winner had model 0.20, market mid 0.90
                    {"token_id": "tok_winner", "model_probability": 0.20, "mid_price": 0.90, "edge": -0.70, "tags": []},
                ],
            }
        ]
        settlements = {"mkt_02": "tok_winner"}

        analyzer = W3OfflineReplayAnalyzer()
        res = analyzer.evaluate_metric_b_calibration_d3(snapshots, settlements)

        assert res is not None
        assert res.model_brier_score > res.market_brier_score
        assert res.brier_skill_score <= 0.0
        assert res.verdict == "RAISE_THRESHOLD_OR_CUT_PROBE"


class TestFullOfflineReplayRunner:
    """Validates complete offline runner and summary structure."""

    def test_run_full_offline_analysis_smoke(self):
        snapshots = [
            {
                "snapshot_id": "s1",
                "timestamp_iso": "2026-10-12T10:00:00Z",
                "market_slug": "m1",
                "summary": {"is_input_suspect": False, "divergence_count": 1, "quarantined_signals": 0},
                "records": [
                    {"token_id": "t1", "bracket_label": "80-81°F", "model_probability": 0.30, "best_ask": 0.20, "best_ask_size": 25.0, "mid_price": 0.18, "edge": 0.10, "tags": ["POSITIVE_EV_SIGNAL"]}
                ],
            }
        ]
        analyzer = W3OfflineReplayAnalyzer()
        summary = analyzer.run_full_offline_analysis(snapshots, official_settlements={"m1": "t1"})

        assert summary.total_snapshots_analyzed == 1
        assert summary.total_brackets_analyzed == 1
        assert len(summary.d1_threshold_curve) == len(D1_SWEEP_THRESHOLDS)
        assert summary.d2_metric_a is not None
        assert summary.d3_metric_b is not None
        assert summary.divergence_count == 1
        assert summary.input_suspect_count == 0

        # Dict serialization test
        d = summary.to_dict()
        assert "analysis_id" in d
        assert "d1_threshold_curve" in d
        assert "d2_metric_a" in d
        assert "d3_metric_b" in d
