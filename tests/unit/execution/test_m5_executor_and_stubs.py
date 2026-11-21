"""Unit tests for M5 executor (P2 Decimal SlicePlan, P18 ReplayMatcher, DualSideBookPair, P4 v1.1 stubs)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest

from src.decision import (
    DeterministicDecider,
    QuotaSnapshot,
    SigmaDeltaFrozen,
    build_execution_policy_bundle,
)
from src.execution import (
    OrderExecutionContext,
    PhiPolicy,
    ReplayMatcher,
    align_price_down_to_tick,
    build_merged_yes_ask_view,
    compute_merge_sell_yes_proceeds,
    compute_taker_fee_usd_raw,
    equivalent_complementary_price,
    pair_dual_side_books,
    parse_p4_snapshot_from_p13_dict,
    plan_slice,
    quantize_polymarket_fee_usd,
)
from src.execution.stub_generator import (
    build_p4_v11_stub_envelope,
    build_stub_forecast_v11,
    default_stub_trading_config,
    generate_regression_stub_bundle,
)
from src.utils.causal_utils import CausalInputError, verify_record_sha256_line


def test_p4_v11_stub_generator_covers_three_regimes_and_sha256_roundtrips() -> None:
    bundle = generate_regression_stub_bundle()
    raw_dicts = bundle["raw_dicts"]
    parsed = [parse_p4_snapshot_from_p13_dict(d) for d in raw_dicts]

    regimes_seen = {
        "two_sided": any(e.payload.single_side is None for e in parsed),
        "bid_only": any(e.payload.single_side == "bid_only" and e.payload.ask_book is None for e in parsed),
        "ask_only": any(e.payload.single_side == "ask_only" and e.payload.bid_book is None for e in parsed),
    }
    assert regimes_seen == {"two_sided": True, "bid_only": True, "ask_only": True}

    for env, raw in zip(parsed, raw_dicts):
        line = env.to_json_line()
        assert verify_record_sha256_line(line)
        assert raw["payload"]["outcome"] in ("YES", "NO")


def test_dual_side_pair_enforces_causality_and_skew_fallback() -> None:
    t0 = datetime(2026, 11, 21, 14, 0, 0, tzinfo=timezone.utc)
    bundle = generate_regression_stub_bundle(base_ts=t0)
    parsed = [parse_p4_snapshot_from_p13_dict(d) for d in bundle["raw_dicts"]]

    # Future frame causal check
    with pytest.raises(CausalInputError):
        pair_dual_side_books(
            parsed,
            as_of_ts_utc=t0 + timedelta(milliseconds=500),
            max_book_staleness_sec=60.0,
            pair_max_skew_sec=5.0,
        )

    scan_ts = t0 + timedelta(seconds=1)
    scan_stream = [e for e in parsed if e.payload.recv_ts_utc <= scan_ts]
    pairs = pair_dual_side_books(
        scan_stream,
        as_of_ts_utc=scan_ts,
        max_book_staleness_sec=60.0,
        pair_max_skew_sec=5.0,
    )
    # 58-59°F pair: |t_yes - t_no| = 1.0s <= 5.0s -> both legs kept
    aligned = pairs[("KORD", "2026-11-21", "58-59°F", "mkt-5859")]
    assert aligned.yes_frame is not None and aligned.no_frame is not None
    assert aligned.skew_fallback is False
    assert aligned.skew_sec == pytest.approx(1.0)

    # 57below pair: NO lags YES by 12.0s > 5.0s -> skew_fallback keeps fresher YES leg only
    skewed = pairs[("KORD", "2026-11-21", "57°F or below", "mkt-57b")]
    assert skewed.skew_fallback is True
    assert skewed.skew_sec == pytest.approx(12.0)
    assert skewed.yes_frame is not None
    assert skewed.no_frame is None


def test_cross_view_split_merge_equivalence_and_inversion_guard() -> None:
    t0 = datetime(2026, 11, 21, 14, 0, 0, tzinfo=timezone.utc)
    # bid_only YES (asks=[], bids=[0.20]) + two_sided NO (bids=[0.68 -> imp ask YES = 0.32])
    yes_env, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=1, frame_seq=1,
        token_id="ty", market_id="m1", condition_id="c1",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="YES", regime="bid_only", recv_ts_utc=t0,
        asks=(), bids=((0.20, 40.0),),
    )
    no_env, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=2, frame_seq=2,
        token_id="tn", market_id="m1", condition_id="c1",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="NO", regime="two_sided", recv_ts_utc=t0,
        asks=((0.72, 20.0),), bids=((0.68, 100.0),),
    )
    merged = build_merged_yes_ask_view(yes_env.payload, no_env.payload, include_no_side=True)
    assert merged.inverted_cross is False
    assert merged.ask_book is not None
    assert merged.ask_book.levels == ((0.32, 100.0),)
    assert merged.legged_levels[0].leg_source == "NO_BID_SPLIT_SELL"
    assert merged.legged_levels[0].raw_source_price == Decimal("0.68")

    # Fee symmetry check: fee(buy YES @ 0.32) == fee(split + sell NO @ 0.68)
    fee_yes = compute_taker_fee_usd_raw(Decimal("25"), Decimal("0.32"), Decimal("0.01"))
    fee_no = compute_taker_fee_usd_raw(Decimal("25"), Decimal("0.68"), Decimal("0.01"))
    assert fee_yes == fee_no

    # Reverse merge equivalence: sell YES @ (1 - 0.64) = 0.36 <-> buy NO @ 0.64
    assert equivalent_complementary_price("0.64") == Decimal("0.36")
    proceeds, fee_q = compute_merge_sell_yes_proceeds(
        shares=Decimal("100"), no_ask_price=Decimal("0.64"), fee_rate=Decimal("0.01")
    )
    assert fee_q == Decimal("0.23040")
    assert proceeds == Decimal("35.76960")

    # Cross-view equality boundary: Ask(YES)=0.40 & Ask(NO)=0.60 (sum == 1.0) is NOT inverted
    eq_yes, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=30, frame_seq=30,
        token_id="ty-eq", market_id="m-eq", condition_id="c-eq",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="YES", regime="two_sided", recv_ts_utc=t0,
        asks=((0.40, 20.0),), bids=((0.39, 20.0),),
    )
    eq_no, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=31, frame_seq=31,
        token_id="tn-eq", market_id="m-eq", condition_id="c-eq",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="NO", regime="two_sided", recv_ts_utc=t0,
        asks=((0.60, 20.0),), bids=((0.59, 20.0),),
    )
    eq_view = build_merged_yes_ask_view(eq_yes.payload, eq_no.payload, include_no_side=True)
    assert eq_view.inverted_cross is False

    # Cross-view inverted book check: Ask(YES)=0.35 while Bid(YES)=0.40
    inv_yes, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=3, frame_seq=3,
        token_id="ty2", market_id="m2", condition_id="c2",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="YES", regime="two_sided", recv_ts_utc=t0,
        asks=((0.35, 20.0),), bids=((0.40, 20.0),),
    )
    inv_view = build_merged_yes_ask_view(inv_yes.payload, include_no_side=False)
    assert inv_view.inverted_cross is True

    # Cross-view arb violation exceeding epsilon: Ask(YES)=0.39 < 1 - Ask(NO)=0.40
    arb_yes, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=32, frame_seq=32,
        token_id="ty-eq", market_id="m-eq", condition_id="c-eq",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="YES", regime="two_sided", recv_ts_utc=t0,
        asks=((0.39, 20.0),), bids=((0.38, 20.0),),
    )
    arb_view = build_merged_yes_ask_view(arb_yes.payload, eq_no.payload, include_no_side=True)
    assert arb_view.inverted_cross is True
    assert arb_view.inversion_reason == "CROSS_VIEW_INVERTED_SPREAD"


def test_pov_slicer_decimal_tick_alignment_and_one_sided_guard() -> None:
    t0 = datetime(2026, 11, 21, 14, 0, 0, tzinfo=timezone.utc)
    phi = PhiPolicy(rho_0=Decimal("0.30"), k_slope=Decimal("0"), rho_min=Decimal("0.1"), rho_max=Decimal("0.5"))

    # bid_only single-side frame must short-circuit to NO_ASK_DEPTH without touching edge_math
    bid_only_env, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=1, frame_seq=1,
        token_id="t-bo", market_id="m1", condition_id="c1",
        station_id="KORD", target_date="2026-11-21", bin_label="60°F or above",
        outcome="YES", regime="bid_only", recv_ts_utc=t0,
        asks=(), bids=((0.02, 50.0),), tick_size=0.001,
    )
    blocked = plan_slice(Decimal("50"), bid_only_env.payload, p_model=0.55, m_threshold=0.02, phi_policy=phi)
    assert blocked.should_submit is False
    assert blocked.abort_reason == "NO_ASK_DEPTH"

    # ask_only frame with 0.001 tick executes cleanly in Decimal domain
    ask_only_env, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=2, frame_seq=2,
        token_id="t-ao", market_id="m2", condition_id="c2",
        station_id="KORD", target_date="2026-11-21", bin_label="57°F or below",
        outcome="YES", regime="ask_only", recv_ts_utc=t0,
        asks=((0.308, 100.0),), bids=(), tick_size=0.001,
    )
    plan = plan_slice(
        Decimal("20"),
        ask_only_env.payload,
        p_model=0.60,
        m_threshold=0.02,
        phi_policy=phi,
        min_order_size_shares=Decimal("5.0"),
        min_notional_usd=Decimal("1.0"),
    )
    assert plan.should_submit is True
    assert plan.limit_price == Decimal("0.308")
    assert plan.target_shares * plan.limit_price <= Decimal("20")
    assert align_price_down_to_tick(Decimal("0.3089"), Decimal("0.001")) == Decimal("0.308")
    assert quantize_polymarket_fee_usd(Decimal("0.000004")) == Decimal("0.00000")


def test_p18_replay_matcher_gap_guards_and_one_sided_non_abort() -> None:
    t0 = datetime(2026, 11, 21, 14, 0, 0, tzinfo=timezone.utc)
    cfg = default_stub_trading_config()
    matcher = ReplayMatcher(cfg)
    phi = PhiPolicy(rho_0=Decimal("0.5"), k_slope=Decimal("0"), rho_min=Decimal("0.1"), rho_max=Decimal("0.5"))

    # Plan from two_sided snapshot @ 0.40
    dec_env, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=1, frame_seq=1,
        token_id="ty", market_id="m1", condition_id="c1",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="YES", regime="two_sided", recv_ts_utc=t0,
        asks=((0.40, 50.0),), bids=((0.35, 30.0),),
    )
    plan = plan_slice(Decimal("10"), dec_env.payload, p_model=0.65, m_threshold=0.02, phi_policy=phi)
    assert plan.should_submit is True

    # Float 15-17 significant digits tolerance (e.g. 0.1 + 0.2) must not crash plan_slice
    float_plan = plan_slice(
        15.0 + 0.1 + 0.2,
        dec_env.payload,
        p_model=0.65,
        m_threshold=0.01 + 0.02,
        phi_policy=phi,
        min_order_size_shares=1.0 / 3.0 * 3.0,
        min_notional_usd=0.1 + 0.2,
    )
    assert float_plan.should_submit is True

    # R1: no frame at or after t_arrive -> PAPER_MATCH_ABORTED_GAP
    r1 = matcher.match_order(
        context=OrderExecutionContext(
            decision_id="d1", session_id="s1", station_id="KORD", market_id="m1",
            yes_token_id="ty", model_hash="mh", config_hash="ch",
            decision_ts_utc=t0, decision_best_ask=Decimal("0.40"),
            submit_ts_utc=t0, decision_seq_id=1,
        ),
        plan=plan,
        recorded_envelopes=[dec_env],
    )
    assert r1.terminal_status == "PAPER_MATCH_ABORTED_GAP"
    assert "R1_NO_FRAME_AFTER_ARRIVE" in (r1.reject_or_abort_reason or "")

    # R2: intervening gap_detected=True before arrival frame -> PAPER_MATCH_ABORTED_GAP
    gap_env, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=2, frame_seq=2,
        token_id="ty", market_id="m1", condition_id="c1",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="YES", regime="two_sided", recv_ts_utc=t0 + timedelta(milliseconds=100),
        asks=((0.40, 50.0),), bids=((0.35, 30.0),),
        gap_detected=True, gap_reason="WS_RECONNECT",
    )
    clean_after, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=3, frame_seq=3,
        token_id="ty", market_id="m1", condition_id="c1",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="YES", regime="two_sided", recv_ts_utc=t0 + timedelta(seconds=1),
        asks=((0.40, 50.0),), bids=((0.35, 30.0),),
    )
    r2 = matcher.match_order(
        context=OrderExecutionContext(
            decision_id="d2", session_id="s1", station_id="KORD", market_id="m1",
            yes_token_id="ty", model_hash="mh", config_hash="ch",
            decision_ts_utc=t0, decision_best_ask=Decimal("0.40"),
            submit_ts_utc=t0, decision_seq_id=1,
        ),
        plan=plan,
        recorded_envelopes=[dec_env, gap_env, clean_after],
    )
    assert r2.terminal_status == "PAPER_MATCH_ABORTED_GAP"
    assert "R2_GAP_IN_WINDOW" in (r2.reject_or_abort_reason or "")

    # R3: even with prior_clean=None, > max_silent_gap_sec from submit_ts triggers R3_SILENT_GAP
    delayed_clean, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=3, frame_seq=3,
        token_id="ty", market_id="m1", condition_id="c1",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="YES", regime="two_sided", recv_ts_utc=t0 + timedelta(seconds=35),
        asks=((0.40, 50.0),), bids=((0.35, 30.0),),
    )
    r3 = matcher.match_order(
        context=OrderExecutionContext(
            decision_id="d3-r3", session_id="s1", station_id="KORD", market_id="m1",
            yes_token_id="ty", model_hash="mh", config_hash="ch",
            decision_ts_utc=t0, decision_best_ask=Decimal("0.40"),
            submit_ts_utc=t0, decision_seq_id=1,
        ),
        plan=plan,
        recorded_envelopes=[delayed_clean],
    )
    assert r3.terminal_status == "PAPER_MATCH_ABORTED_GAP"
    assert "R3_SILENT_GAP" in (r3.reject_or_abort_reason or "")

    # Pure YES_ASK plan must NOT abort if unused NO leg has no arrival frame (include_no_side=True)
    pure_yes_ok = matcher.match_order(
        context=OrderExecutionContext(
            decision_id="d-yes-ok", session_id="s1", station_id="KORD", market_id="m1",
            yes_token_id="ty", no_token_id="tn-missing", model_hash="mh", config_hash="ch",
            decision_ts_utc=t0, decision_best_ask=Decimal("0.40"),
            submit_ts_utc=t0, decision_seq_id=1, include_no_side=True,
        ),
        plan=plan,
        recorded_envelopes=[dec_env, clean_after],
    )
    assert pure_yes_ok.terminal_status == "FILLED"
    assert pure_yes_ok.replay_source_seq_id == clean_after.seq_id

    # One-sided guard: arrival YES bid_only & NO ask_only -> CANCELLED_UNFILLED (NO_ASK_DEPTH), NEVER P18 gap abort
    bid_only_arrive, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=4, frame_seq=4,
        token_id="ty", market_id="m1", condition_id="c1",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="YES", regime="bid_only", recv_ts_utc=t0 + timedelta(seconds=1),
        asks=(), bids=((0.35, 30.0),),
    )
    no_ask_only_arrive, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=5, frame_seq=5,
        token_id="tn", market_id="m1", condition_id="c1",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="NO", regime="ask_only", recv_ts_utc=t0 + timedelta(seconds=1),
        asks=((0.65, 30.0),), bids=(),
    )
    no_ask_res = matcher.match_order(
        context=OrderExecutionContext(
            decision_id="d3", session_id="s1", station_id="KORD", market_id="m1",
            yes_token_id="ty", no_token_id="tn", model_hash="mh", config_hash="ch",
            decision_ts_utc=t0, decision_best_ask=Decimal("0.40"),
            submit_ts_utc=t0, decision_seq_id=1, no_decision_seq_id=1, include_no_side=True,
        ),
        plan=plan,
        recorded_envelopes=[dec_env, bid_only_arrive, no_ask_only_arrive],
    )
    assert no_ask_res.terminal_status == "CANCELLED_UNFILLED"
    assert no_ask_res.reject_or_abort_reason == "NO_ASK_DEPTH"
    assert verify_record_sha256_line(no_ask_res.to_json_line())


def _run_stub_regression_suite_helper():
    bundle = generate_regression_stub_bundle()
    t0: datetime = bundle["base_ts"]
    cfg = default_stub_trading_config()
    parsed = [parse_p4_snapshot_from_p13_dict(d) for d in bundle["raw_dicts"]]
    scan_ts = t0 + timedelta(seconds=1)
    pairs = pair_dual_side_books(
        [e for e in parsed if e.payload.recv_ts_utc <= scan_ts],
        as_of_ts_utc=scan_ts, max_book_staleness_sec=cfg.max_book_staleness_sec, pair_max_skew_sec=cfg.pair_max_skew_sec,
    )
    fc = build_stub_forecast_v11(issue_ts_utc=t0 - timedelta(minutes=10), settle_close_utc=t0 + timedelta(hours=10))
    policy = build_execution_policy_bundle(
        policy_version="p6.stub.v1", signed_at_utc=t0 - timedelta(hours=1), is_overdue=False,
        w0_intent=0.10, min_order_usd_eff=5.0, p=1.5, tau_max_h=24.0, station_cap_usd=500.0,
        concurrent_days=2, w_provenance="P8-CAPITAL-CONFIG v1.0",
        phi_policy=PhiPolicy(rho_0=Decimal("0.30"), k_slope=Decimal("0.0"), rho_min=Decimal("0.10"), rho_max=Decimal("0.50")),
        k0_threshold_coef=2.0, sigma_delta_frozen=SigmaDeltaFrozen(0.02, "stub", "cycle-0"),
        friction_median=0.01, m_floor=0.02,
    )
    decider = DeterministicDecider(exec_config=cfg)
    matcher = ReplayMatcher(cfg)
    quota = QuotaSnapshot(
        station_id="KORD", market_id="mkt-5859", free_usd=500.0, station_active_locked_usd=0.0,
        market_held_usd=0.0, station_cap_usd=500.0, station_realized_loss_usd=0.0,
        station_loss_gate_tripped=False, account_drawdown_brake_tripped=False, b_eff_headroom_usd=250.0,
    )
    ev_cross = decider.evaluate_bin(
        orig_session_id=bundle["session_id"], execution_mode="PAPER", scan_clock="PRICE_CLOCK",
        scan_ts_utc=scan_ts, station_id="KORD", target_date="2026-11-21", bin_id="bin-58-59",
        market_id="mkt-5859", yes_token_id="tok-kord-5859-yes", forecasts=[fc], policy_bundle=policy,
        quota=quota, dual_pair=pairs[("KORD", "2026-11-21", "58-59°F", "mkt-5859")], include_no_side=True,
    )
    assert ev_cross.slice_plan is not None
    p3_cross = matcher.match_order(
        context=OrderExecutionContext(
            decision_id=ev_cross.decision_id, session_id=bundle["session_id"], station_id="KORD",
            market_id="mkt-5859", yes_token_id="tok-kord-5859-yes", no_token_id="tok-kord-5859-no",
            model_hash=fc.model_hash, config_hash=policy.config_hash, decision_ts_utc=ev_cross.scan_ts_utc,
            decision_best_ask=Decimal(str(ev_cross.best_ask_price)), submit_ts_utc=scan_ts,
            decision_seq_id=1, no_decision_seq_id=2, include_no_side=True,
        ),
        plan=ev_cross.slice_plan,
        recorded_envelopes=parsed,
    )
    # LIVE mode with enable_cross_side_split_routing=False rejects NO_BID_SPLIT_SELL leg cleanly
    cfg_no_live_split = type(cfg)(**{**cfg.__dict__, "enable_cross_side_split_routing": False})
    p3_live_gate = ReplayMatcher(cfg_no_live_split).match_order(
        context=OrderExecutionContext(
            decision_id=ev_cross.decision_id, session_id=bundle["session_id"], station_id="KORD",
            market_id="mkt-5859", yes_token_id="tok-kord-5859-yes", no_token_id="tok-kord-5859-no",
            model_hash=fc.model_hash, config_hash=policy.config_hash, decision_ts_utc=ev_cross.scan_ts_utc,
            decision_best_ask=Decimal(str(ev_cross.best_ask_price)), submit_ts_utc=scan_ts,
            decision_seq_id=1, no_decision_seq_id=2, include_no_side=True, execution_mode="LIVE",
        ),
        plan=ev_cross.slice_plan,
        recorded_envelopes=parsed,
    )
    ev_bid_only = decider.evaluate_bin(
        orig_session_id=bundle["session_id"], execution_mode="PAPER", scan_clock="PRICE_CLOCK",
        scan_ts_utc=scan_ts, station_id="KORD", target_date="2026-11-21", bin_id="bin-60plus",
        market_id="mkt-60p", yes_token_id="tok-kord-60p-yes", forecasts=[fc], policy_bundle=policy,
        quota=quota, dual_pair=pairs[("KORD", "2026-11-21", "60°F or above", "mkt-60p")], include_no_side=True,
    )
    ev_ask_only = decider.evaluate_bin(
        orig_session_id=bundle["session_id"], execution_mode="PAPER", scan_clock="PRICE_CLOCK",
        scan_ts_utc=scan_ts, station_id="KORD", target_date="2026-11-21", bin_id="bin-57below",
        market_id="mkt-57b", yes_token_id="tok-kord-57b-yes", forecasts=[fc], policy_bundle=policy,
        quota=quota, dual_pair=pairs[("KORD", "2026-11-21", "57°F or below", "mkt-57b")], include_no_side=True,
    )
    pair_57b = pairs[("KORD", "2026-11-21", "57°F or below", "mkt-57b")]
    return parsed, pair_57b, ev_cross, p3_cross, p3_live_gate, ev_bid_only, ev_ask_only


def test_cross_arb_eps_boundary_vs_single_side_strict_inequality() -> None:
    """Prove `cross_arb_eps=0.0001` avoids `ask_YES+ask_NO==1.0` false positive while single-side keeps `<=`."""
    t0 = datetime(2026, 11, 21, 14, 0, 0, tzinfo=timezone.utc)
    no_env, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=101, frame_seq=101,
        token_id="tn-eps", market_id="m-eps", condition_id="c-eps",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="NO", regime="two_sided", recv_ts_utc=t0,
        asks=((0.60, 20.0),), bids=((0.59, 20.0),),
    )
    # ask_YES=0.40, 1-ask_NO=0.40: strict <= cross check would false-positive; eps=0.0001 allows equality.
    yes_eq, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=102, frame_seq=102,
        token_id="ty-eps", market_id="m-eps", condition_id="c-eps",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="YES", regime="two_sided", recv_ts_utc=t0,
        asks=((0.40, 20.0),), bids=((0.39, 20.0),),
    )
    v_eq = build_merged_yes_ask_view(yes_eq.payload, no_env.payload, include_no_side=True)
    assert v_eq.best_bid_effective == Decimal("0.40")
    assert v_eq.legged_levels[0].implied_yes_price <= v_eq.best_bid_effective  # pre-fix <= check tripped here
    assert v_eq.inverted_cross is False

    # Boundary at eps=0.0001: 0.3999 (diff == 0.0001) passes strict <; 0.3998 trips CROSS_VIEW_INVERTED_SPREAD.
    yes_edge, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=103, frame_seq=103,
        token_id="ty-eps", market_id="m-eps", condition_id="c-eps",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="YES", regime="two_sided", recv_ts_utc=t0,
        asks=((0.3999, 20.0),), bids=((0.38, 20.0),), tick_size=0.0001,
    )
    assert build_merged_yes_ask_view(yes_edge.payload, no_env.payload).inverted_cross is False

    yes_cross, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=104, frame_seq=104,
        token_id="ty-eps", market_id="m-eps", condition_id="c-eps",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="YES", regime="two_sided", recv_ts_utc=t0,
        asks=((0.3998, 20.0),), bids=((0.38, 20.0),), tick_size=0.0001,
    )
    v_cross = build_merged_yes_ask_view(yes_cross.payload, no_env.payload)
    assert v_cross.inverted_cross is True and v_cross.inversion_reason == "CROSS_VIEW_INVERTED_SPREAD"

    # Single-side intra-book equality (ask_YES == bid_YES == 0.40) stays strictly <= rejected.
    yes_intra, _ = build_p4_v11_stub_envelope(
        session_id="s1", seq_id=105, frame_seq=105,
        token_id="ty-intra", market_id="m-intra", condition_id="c-intra",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="YES", regime="two_sided", recv_ts_utc=t0,
        asks=((0.40, 20.0),), bids=((0.40, 20.0),),
    )
    v_intra = build_merged_yes_ask_view(yes_intra.payload, include_no_side=False)
    assert v_intra.inverted_cross is True and v_intra.inversion_reason == "YES_INTRA_BOOK_INVERTED"


def test_to_exec_decimal_float_tolerance_and_downstream_12_digit_guard() -> None:
    """Prove float str conversion handles `0.1+0.2` while preserving 12-digit downstream guard."""
    from src.execution.executor import _to_exec_decimal
    from src.utils.decimal_guard import DecimalOperandBoundsError, to_guarded_decimal

    artifact = 0.1 + 0.2  # 0.30000000000000004 (17 significant digits)
    assert _to_exec_decimal(artifact, name="float_artifact") == Decimal("0.30000000000000004")

    with pytest.raises(DecimalOperandBoundsError):
        _to_exec_decimal(Decimal("0.1234567890123"), name="explicit_dec_13")
    with pytest.raises(DecimalOperandBoundsError):
        _to_exec_decimal("0.1234567890123", name="explicit_str_13")
    with pytest.raises(DecimalOperandBoundsError):
        to_guarded_decimal("0.1234567890123", name="downstream_13")
    with pytest.raises(DecimalOperandBoundsError):
        compute_taker_fee_usd_raw(Decimal("10"), Decimal("0.1234567890123"), Decimal("0.01"))
    with pytest.raises(DecimalOperandBoundsError):
        align_price_down_to_tick(Decimal("0.1234567890123"), Decimal("0.01"))


def test_stub_regression_suite_deterministic_end_to_end() -> None:
    parsed, pair_57b, ev_cross, p3_cross, p3_live_gate, ev_bid_only, ev_ask_only = _run_stub_regression_suite_helper()
    merge_proceeds, merge_fee = compute_merge_sell_yes_proceeds(
        shares=Decimal("20"), no_ask_price=Decimal("0.64"), fee_rate=Decimal("0.01"),
    )
    assert len(parsed) == 10
    assert {e.payload.single_side for e in parsed} == {None, "bid_only", "ask_only"}
    assert pair_57b.skew_fallback is True
    assert ev_cross.decision_outcome == "ORDERED"
    assert ev_cross.best_ask_price == pytest.approx(0.36)
    assert ev_cross.scaler_policy_id == "provisional_identity_v0"
    assert p3_cross.terminal_status == "FILLED"
    assert p3_cross.replay_source_seq_id == 4  # consumed NO leg seq_id
    assert [leg.leg_source for leg in p3_cross.execution_legs] == ["NO_BID_SPLIT_SELL"]
    assert p3_live_gate.terminal_status == "REJECTED"
    assert p3_live_gate.reject_or_abort_reason == "LIVE_CROSS_SIDE_SPLIT_DISABLED"
    assert ev_bid_only.decision_outcome == "BLOCKED_NO_BOOK_DEPTH"
    assert ev_bid_only.degradation_reason == "NO_ASK_DEPTH"
    assert ev_ask_only.decision_outcome == "ORDERED"
    summary = {
        "parsed_envelopes": len(parsed),
        "regimes_covered": sorted({e.payload.single_side or "two_sided" for e in parsed}),
        "pair_57b_skew_fallback": pair_57b.skew_fallback,
        "pair_57b_skew_sec": pair_57b.skew_sec,
        "cross_view_m4_outcome": ev_cross.decision_outcome,
        "cross_view_best_ask_yes": ev_cross.best_ask_price,
        "cross_view_scaler_policy_id": ev_cross.scaler_policy_id,
        "cross_view_p3_status": p3_cross.terminal_status,
        "cross_view_p3_replay_source_seq_id": p3_cross.replay_source_seq_id,
        "cross_view_p3_filled_shares": str(p3_cross.filled_shares),
        "cross_view_p3_avg_price": str(p3_cross.actual_avg_fill_price),
        "cross_view_p3_fee_usd": str(p3_cross.fee_paid_usd),
        "cross_view_legs": [leg.leg_source for leg in p3_cross.execution_legs],
        "live_split_gate_status": p3_live_gate.terminal_status,
        "live_split_gate_reason": p3_live_gate.reject_or_abort_reason,
        "bid_only_m4_outcome": ev_bid_only.decision_outcome,
        "bid_only_m4_reason": ev_bid_only.degradation_reason,
        "ask_only_m4_outcome": ev_ask_only.decision_outcome,
        "merge_proceeds_20sh_at_064no": str(merge_proceeds),
        "merge_fee_20sh_at_064no": str(merge_fee),
    }
    print("\nSTUB_REGRESSION_OUTPUT=" + json.dumps(summary, indent=2, ensure_ascii=False))
