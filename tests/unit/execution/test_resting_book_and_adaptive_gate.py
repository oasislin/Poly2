"""Unit tests for resting-book paper matching (with virtual depth deduction) and τ-tiered adaptive gate."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.decision.engine import PhiPolicy
from src.decision.offline_scheduler import _AdaptiveTargetGate
from src.execution.executor import OrderExecutionContext, ReplayMatcher, plan_slice
from src.execution.stub_generator import build_p4_v11_stub_envelope, default_stub_trading_config


def test_resting_book_fallback_fills_once_and_deducts_virtual_depth() -> None:
    t0 = datetime(2026, 11, 27, 14, 0, 0, tzinfo=timezone.utc)
    cfg = default_stub_trading_config()
    phi = PhiPolicy(rho_0=Decimal("0.5"), k_slope=Decimal("0"), rho_min=Decimal("0.1"), rho_max=Decimal("0.5"))

    # $10 ask liquidity (20 shares @ $0.50), static book (no subsequent frame after t_arrive)
    frame1, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=1, frame_seq=101,
        token_id="ty", market_id="m1", condition_id="c1",
        station_id="KDAL", target_date="2026-11-27", bin_label="58-59°F",
        outcome="YES", regime="two_sided", recv_ts_utc=t0,
        asks=((0.50, 20.0),), bids=((0.45, 20.0),),
    )
    plan = plan_slice(Decimal("10"), frame1.payload, p_model=0.80, m_threshold=0.02, phi_policy=phi)
    assert plan.should_submit is True
    assert plan.target_shares == Decimal("10.00")

    # Strict default matcher aborts on static book
    strict_matcher = ReplayMatcher(cfg, allow_resting_book_fallback=False)
    r_strict = strict_matcher.match_order(
        context=OrderExecutionContext(
            decision_id="d0", session_id="s1", station_id="KDAL", market_id="m1",
            yes_token_id="ty", model_hash="mh", config_hash="ch",
            decision_ts_utc=t0, decision_best_ask=Decimal("0.50"), submit_ts_utc=t0, decision_seq_id=1,
        ),
        plan=plan, recorded_envelopes=[frame1],
    )
    assert r_strict.terminal_status == "PAPER_MATCH_ABORTED_GAP"

    # Resting-book matcher fills 10 shares on 1st, 10 shares on 2nd (all 20 consumed), then rejects 3rd on SAME frame_seq
    matcher = ReplayMatcher(cfg, allow_resting_book_fallback=True)
    r1 = matcher.match_order(
        context=OrderExecutionContext(
            decision_id="d1", session_id="s1", station_id="KDAL", market_id="m1",
            yes_token_id="ty", model_hash="mh", config_hash="ch",
            decision_ts_utc=t0 + timedelta(seconds=1), decision_best_ask=Decimal("0.50"),
            submit_ts_utc=t0 + timedelta(seconds=1), decision_seq_id=1,
        ),
        plan=plan, recorded_envelopes=[frame1],
    )
    assert r1.terminal_status == "FILLED"
    assert r1.filled_shares == Decimal("10.00")
    assert r1.final_ts_utc >= t0 + timedelta(seconds=1, milliseconds=cfg.latency_ms)

    r1b = matcher.match_order(
        context=OrderExecutionContext(
            decision_id="d1b", session_id="s1", station_id="KDAL", market_id="m1",
            yes_token_id="ty", model_hash="mh", config_hash="ch",
            decision_ts_utc=t0 + timedelta(seconds=30), decision_best_ask=Decimal("0.50"),
            submit_ts_utc=t0 + timedelta(seconds=30), decision_seq_id=1,
        ),
        plan=plan, recorded_envelopes=[frame1],
    )
    assert r1b.terminal_status == "FILLED"
    assert r1b.filled_shares == Decimal("10.00")

    r2 = matcher.match_order(
        context=OrderExecutionContext(
            decision_id="d2", session_id="s1", station_id="KDAL", market_id="m1",
            yes_token_id="ty", model_hash="mh", config_hash="ch",
            decision_ts_utc=t0 + timedelta(minutes=1), decision_best_ask=Decimal("0.50"),
            submit_ts_utc=t0 + timedelta(minutes=1), decision_seq_id=1,
        ),
        plan=plan, recorded_envelopes=[frame1],
    )
    assert r2.terminal_status == "CANCELLED_UNFILLED"
    assert r2.filled_shares == Decimal("0")
    assert r2.reject_or_abort_reason == "RESTING_BOOK_DEPTH_EXHAUSTED"

    # Once a brand new frame_seq arrives, fresh liquidity fills cleanly
    frame2, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=2, frame_seq=102,
        token_id="ty", market_id="m1", condition_id="c1",
        station_id="KDAL", target_date="2026-11-27", bin_label="58-59°F",
        outcome="YES", regime="two_sided", recv_ts_utc=t0 + timedelta(minutes=2),
        asks=((0.50, 20.0),), bids=((0.45, 20.0),),
    )
    r3 = matcher.match_order(
        context=OrderExecutionContext(
            decision_id="d3", session_id="s1", station_id="KDAL", market_id="m1",
            yes_token_id="ty", model_hash="mh", config_hash="ch",
            decision_ts_utc=t0 + timedelta(minutes=2, seconds=1), decision_best_ask=Decimal("0.50"),
            submit_ts_utc=t0 + timedelta(minutes=2, seconds=1), decision_seq_id=2,
        ),
        plan=plan, recorded_envelopes=[frame1, frame2],
    )
    assert r3.terminal_status == "FILLED"
    assert r3.filled_shares == Decimal("10.00")

    # True gap_detected=True still aborts even when resting fallback is enabled
    gap_frame, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=3, frame_seq=103,
        token_id="ty", market_id="m1", condition_id="c1",
        station_id="KDAL", target_date="2026-11-27", bin_label="58-59°F",
        outcome="YES", regime="two_sided", recv_ts_utc=t0 + timedelta(minutes=2, seconds=2),
        asks=((0.50, 20.0),), bids=((0.45, 20.0),), gap_detected=True, gap_reason="WS_DROPPED",
    )
    r_gap = matcher.match_order(
        context=OrderExecutionContext(
            decision_id="d4", session_id="s1", station_id="KDAL", market_id="m1",
            yes_token_id="ty", model_hash="mh", config_hash="ch",
            decision_ts_utc=t0 + timedelta(minutes=2, seconds=1), decision_best_ask=Decimal("0.50"),
            submit_ts_utc=t0 + timedelta(minutes=2, seconds=1), decision_seq_id=2,
        ),
        plan=plan, recorded_envelopes=[frame1, frame2, gap_frame],
    )
    assert r_gap.terminal_status == "PAPER_MATCH_ABORTED_GAP"
    assert "R2_HIT_GAP" in (r_gap.reject_or_abort_reason or "")


def test_adaptive_target_gate_tau_tiers_and_event_triggers() -> None:
    gate = _AdaptiveTargetGate()
    t0 = datetime(2026, 11, 27, 14, 0, 0, tzinfo=timezone.utc)
    k_far = ("KDAL", "2026-11-28", "TMAX", "mkt-1", "58-59F")

    # Initial tick always evaluates
    assert gate.should_evaluate(key=k_far, tick_utc=t0, book_frame_ref=10, forecast_id="fc-1", tau_hours=30.0) is True
    # At +60s and +600s with unchanged frame/forecast, >24h tier (900s) stays asleep
    assert gate.should_evaluate(key=k_far, tick_utc=t0 + timedelta(seconds=60), book_frame_ref=10, forecast_id="fc-1", tau_hours=30.0) is False
    assert gate.should_evaluate(key=k_far, tick_utc=t0 + timedelta(seconds=600), book_frame_ref=10, forecast_id="fc-1", tau_hours=30.0) is False
    # Book frame change wakes immediately
    assert gate.should_evaluate(key=k_far, tick_utc=t0 + timedelta(seconds=660), book_frame_ref=11, forecast_id="fc-1", tau_hours=30.0) is True
    # Forecast change wakes immediately
    assert gate.should_evaluate(key=k_far, tick_utc=t0 + timedelta(seconds=720), book_frame_ref=11, forecast_id="fc-2", tau_hours=30.0) is True
    # 900s (15m) heartbeat wakes even when unchanged
    assert gate.should_evaluate(key=k_far, tick_utc=t0 + timedelta(seconds=720 + 900), book_frame_ref=11, forecast_id="fc-2", tau_hours=30.0) is True

    # 3-24h tier uses 300s (5m)
    k_mid = ("KORD", "2026-11-27", "TMAX", "mkt-2", "44-45F")
    assert gate.should_evaluate(key=k_mid, tick_utc=t0, book_frame_ref=20, forecast_id="fc-3", tau_hours=10.0) is True
    assert gate.should_evaluate(key=k_mid, tick_utc=t0 + timedelta(seconds=240), book_frame_ref=20, forecast_id="fc-3", tau_hours=10.0) is False
    assert gate.should_evaluate(key=k_mid, tick_utc=t0 + timedelta(seconds=300), book_frame_ref=20, forecast_id="fc-3", tau_hours=10.0) is True

    # <=3h tier uses 60s (1m)
    k_near = ("KMIA", "2026-11-27", "TMAX", "mkt-3", "76-77F")
    assert gate.should_evaluate(key=k_near, tick_utc=t0, book_frame_ref=30, forecast_id="fc-4", tau_hours=2.0) is True
    assert gate.should_evaluate(key=k_near, tick_utc=t0 + timedelta(seconds=60), book_frame_ref=30, forecast_id="fc-4", tau_hours=2.0) is True


def test_plan_slice_steep_tail_book_escrow_aware_no_share_collapse() -> None:
    t0 = datetime(2026, 11, 27, 15, 32, 0, tzinfo=timezone.utc)
    phi = PhiPolicy(rho_0=Decimal("0.30"), k_slope=Decimal("0"), rho_min=Decimal("0.10"), rho_max=Decimal("0.50"))
    frame, _ = build_p4_v11_stub_envelope(
        session_id="s-kdal", seq_id=2230, frame_seq=2230,
        token_id="tok-kdal", market_id="7338470", condition_id="c-kdal",
        station_id="KDAL", target_date="2026-11-27", bin_label="58-59°F",
        outcome="YES", regime="ask_only", recv_ts_utc=t0,
        asks=((0.001, 1303.2), (0.002, 530.93), (0.004, 150.0), (0.005, 353.17), (0.008, 20.0), (0.20, 500.0)),
        bids=(),
    )
    plan = plan_slice(
        Decimal("6.312"), frame.payload, p_model=0.35, m_threshold=0.05,
        phi_policy=phi, min_order_size_shares=Decimal("5"), min_notional_usd=Decimal("1.0"),
    )
    assert plan.should_submit is True
    assert plan.limit_price <= Decimal("0.01")
    assert plan.target_shares >= Decimal("500")
    assert plan.target_shares * plan.limit_price <= Decimal("6.312")
    assert plan.target_shares * plan.est_vwap >= Decimal("1.0")


def test_plan_slice_blocks_dust_expected_spend_below_min_notional() -> None:
    t0 = datetime(2026, 11, 27, 15, 32, 0, tzinfo=timezone.utc)
    phi = PhiPolicy(rho_0=Decimal("0.30"), k_slope=Decimal("0"), rho_min=Decimal("0.10"), rho_max=Decimal("0.50"))
    frame, _ = build_p4_v11_stub_envelope(
        session_id="s-dust", seq_id=1, frame_seq=1,
        token_id="tok-dust", market_id="m-dust", condition_id="c-dust",
        station_id="KDAL", target_date="2026-11-27", bin_label="58-59°F",
        outcome="YES", regime="ask_only", recv_ts_utc=t0,
        asks=((0.001, 100.0), (0.20, 50.0)),
        bids=(),
    )
    plan = plan_slice(
        Decimal("6.312"), frame.payload, p_model=0.35, m_threshold=0.05,
        phi_policy=phi, min_order_size_shares=Decimal("5"), min_notional_usd=Decimal("1.0"),
    )
    assert plan.should_submit is False
    assert plan.abort_reason == "BELOW_MIN_ORDER"
