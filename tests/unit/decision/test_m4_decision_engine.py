"""Unit tests for M4 Decision Engine (no-rollback P5, dual ages, IdentityScaler, P4 v1.1, UUIDv5 replay)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest

from src.decision import (
    CausalViolationError,
    DeterministicDecider,
    IdentityScaler,
    LightLevelEvent,
    P16SubscriptionSlot,
    QuotaQuery,
    QuotaSnapshot,
    SigmaDeltaFrozen,
    build_execution_policy_bundle,
)
from src.execution import PhiPolicy
from src.execution.orderbook_views import pair_dual_side_books
from src.execution.stub_generator import (
    build_p4_v11_stub_envelope,
    build_stub_forecast_v11,
    default_stub_trading_config,
)
from src.utils.causal_utils import verify_record_sha256_line


def _sample_policy_bundle(t0: datetime, *, is_overdue: bool = False, friction_median: float | None = 0.01):
    return build_execution_policy_bundle(
        policy_version="p6.test.v1",
        signed_at_utc=t0 - timedelta(hours=2),
        is_overdue=is_overdue,
        w0_intent=0.10,
        min_order_usd_eff=5.0,
        p=1.5,
        tau_max_h=24.0,
        station_cap_usd=500.0,
        concurrent_days=2,
        w_provenance="P8-CAPITAL-CONFIG v1.0",
        phi_policy=PhiPolicy(
            rho_0=Decimal("0.30"),
            k_slope=Decimal("0.0"),
            rho_min=Decimal("0.10"),
            rho_max=Decimal("0.50"),
        ),
        k0_threshold_coef=2.0,
        sigma_delta_frozen=SigmaDeltaFrozen(0.02, "test", "cyc-1"),
        friction_median=friction_median,
        m_floor=0.02,
        allow_provisional_none_friction=False,
    )


def _sample_quota(*, market_held_usd: float = 0.0, b_eff_headroom_usd: float = 250.0) -> QuotaSnapshot:
    return QuotaSnapshot(
        station_id="KORD",
        market_id="mkt-1",
        free_usd=500.0,
        station_active_locked_usd=market_held_usd,
        market_held_usd=market_held_usd,
        station_cap_usd=500.0,
        station_realized_loss_usd=0.0,
        station_loss_gate_tripped=False,
        account_drawdown_brake_tripped=False,
        b_eff_headroom_usd=b_eff_headroom_usd,
    )


def test_identity_scaler_forces_provisional_metadata_and_p6_blocks_none_friction() -> None:
    t0 = datetime(2026, 11, 21, 14, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="friction_median is None"):
        _sample_policy_bundle(t0, friction_median=None)

    scaler = IdentityScaler()
    assert scaler.policy_id == "provisional_identity_v0"
    assert scaler.provisional is True
    assert scaler.provenance == "PROVISIONAL_UNTIL_D6"
    assert scaler.scale(best_ask_edge=0.04, m_threshold=0.05) == 0.0
    assert scaler.scale(best_ask_edge=0.05, m_threshold=0.05) == 1.0


def test_latest_issue_ts_wins_no_rollback_when_stale_and_overdue_continues() -> None:
    t0 = datetime(2026, 11, 21, 14, 0, 0, tzinfo=timezone.utc)
    cfg = default_stub_trading_config()
    decider = DeterministicDecider(exec_config=cfg)
    bundle_overdue = _sample_policy_bundle(t0, is_overdue=True)

    yes_env, _ = build_p4_v11_stub_envelope(
        session_id="sess-m4", seq_id=1, frame_seq=1,
        token_id="tok-y", market_id="mkt-1", condition_id="0xc1",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="YES", regime="two_sided", recv_ts_utc=t0 - timedelta(seconds=5),
        asks=((0.30, 100.0),), bids=((0.28, 40.0),),
    )

    # Older forecast inside age limit (t0 - 1h), newer forecast NON_ORACLE_COMPLIANT (t0 - 5m)
    fc_older_fresh = build_stub_forecast_v11(
        issue_ts_utc=t0 - timedelta(hours=1),
        settle_close_utc=t0 + timedelta(hours=10),
    )
    fc_newer_non_oracle = build_stub_forecast_v11(
        issue_ts_utc=t0 - timedelta(minutes=5),
        settle_close_utc=t0 + timedelta(hours=10),
    )
    fc_newer_non_oracle = type(fc_newer_non_oracle)(
        **{**fc_newer_non_oracle.__dict__, "oracle_compliant": False}
    )

    # Must pick latest `fc_newer_non_oracle` and NOT roll back to `fc_older_fresh`!
    ev_no_rollback = decider.evaluate_bin(
        orig_session_id="sess-m4",
        execution_mode="PAPER",
        scan_clock="PRICE_CLOCK",
        scan_ts_utc=t0,
        station_id="KORD",
        target_date="2026-11-21",
        bin_id="bin-58-59",
        market_id="mkt-1",
        yes_token_id="tok-y",
        forecasts=[fc_older_fresh, fc_newer_non_oracle],
        policy_bundle=bundle_overdue,
        quota=_sample_quota(),
        yes_frame=yes_env.payload,
    )
    assert ev_no_rollback.decision_outcome == "BLOCKED_NO_BOOK_DEPTH"
    assert ev_no_rollback.degradation_reason == "NON_ORACLE_COMPLIANT_FORECAST"
    assert ev_no_rollback.policy_overdue is True
    assert ev_no_rollback.scaler_policy_id == "provisional_identity_v0"

    # Future forecast violates strict causality
    fc_future = build_stub_forecast_v11(
        issue_ts_utc=t0 + timedelta(seconds=1),
        settle_close_utc=t0 + timedelta(hours=10),
    )
    with pytest.raises(CausalViolationError):
        decider.evaluate_bin(
            orig_session_id="sess-m4",
            execution_mode="PAPER",
            scan_clock="PRICE_CLOCK",
            scan_ts_utc=t0,
            station_id="KORD",
            target_date="2026-11-21",
            bin_id="bin-58-59",
            market_id="mkt-1",
            yes_token_id="tok-y",
            forecasts=[fc_future],
            policy_bundle=bundle_overdue,
            quota=_sample_quota(),
            yes_frame=yes_env.payload,
        )


def test_p4_v11_one_sided_paths_and_deterministic_replay_bitwise_equal() -> None:
    t0 = datetime(2026, 11, 21, 14, 0, 0, tzinfo=timezone.utc)
    cfg = default_stub_trading_config()
    decider = DeterministicDecider(exec_config=cfg)
    bundle = _sample_policy_bundle(t0, is_overdue=True)
    fc = build_stub_forecast_v11(
        issue_ts_utc=t0 - timedelta(minutes=15),
        settle_close_utc=t0 + timedelta(hours=10),
    )

    bid_only_yes, _ = build_p4_v11_stub_envelope(
        session_id="orig-sess-99", seq_id=1, frame_seq=10,
        token_id="ty", market_id="mkt-1", condition_id="c1",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="YES", regime="bid_only", recv_ts_utc=t0 - timedelta(seconds=2),
        asks=(), bids=((0.20, 50.0),),
    )
    ask_only_yes, _ = build_p4_v11_stub_envelope(
        session_id="orig-sess-99", seq_id=2, frame_seq=11,
        token_id="ty", market_id="mkt-1", condition_id="c1",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="YES", regime="ask_only", recv_ts_utc=t0 - timedelta(seconds=1),
        asks=((0.25, 100.0),), bids=(),
    )
    no_with_bid, _ = build_p4_v11_stub_envelope(
        session_id="orig-sess-99", seq_id=3, frame_seq=12,
        token_id="tn", market_id="mkt-1", condition_id="c1",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="NO", regime="two_sided", recv_ts_utc=t0 - timedelta(seconds=1),
        asks=((0.75, 40.0),), bids=((0.70, 80.0),),
    )

    # 1. Single-side bid_only YES -> BLOCKED_NO_BOOK_DEPTH cleanly
    ev_bo = decider.evaluate_bin(
        orig_session_id="orig-sess-99", execution_mode="PAPER", scan_clock="INFO_CLOCK",
        scan_ts_utc=t0, station_id="KORD", target_date="2026-11-21",
        bin_id="bin-58-59", market_id="mkt-1", yes_token_id="ty",
        forecasts=[fc], policy_bundle=bundle, quota=_sample_quota(),
        yes_frame=bid_only_yes.payload, include_no_side=False,
    )
    assert ev_bo.decision_outcome == "BLOCKED_NO_BOOK_DEPTH"
    assert ev_bo.best_ask_price is None

    # 2. Single-side bid_only YES + paired NO Bid(0.70 -> imp ask 0.30) -> ORDERED
    pairs = pair_dual_side_books(
        [bid_only_yes, no_with_bid],
        as_of_ts_utc=t0, max_book_staleness_sec=60.0, pair_max_skew_sec=5.0,
    )
    ev_rescued = decider.evaluate_bin(
        orig_session_id="orig-sess-99", execution_mode="PAPER", scan_clock="INFO_CLOCK",
        scan_ts_utc=t0, station_id="KORD", target_date="2026-11-21",
        bin_id="bin-58-59", market_id="mkt-1", yes_token_id="ty",
        forecasts=[fc], policy_bundle=bundle, quota=_sample_quota(b_eff_headroom_usd=30.0),
        dual_pair=pairs[("KORD", "2026-11-21", "58-59°F", "mkt-1")], include_no_side=True,
    )
    assert ev_rescued.decision_outcome == "ORDERED"
    assert ev_rescued.best_ask_price == pytest.approx(0.30)
    assert ev_rescued.headroom_d <= 30.0  # N8 B_eff cap honored
    assert ev_rescued.policy_overdue is True  # B6 honored

    # 3. Single-side ask_only YES -> ORDERED & bit-for-bit replay with same orig_session_id
    ev_run1 = decider.evaluate_bin(
        orig_session_id="orig-sess-99", execution_mode="PAPER", scan_clock="PRICE_CLOCK",
        scan_ts_utc=t0, station_id="KORD", target_date="2026-11-21",
        bin_id="bin-58-59", market_id="mkt-1", yes_token_id="ty",
        forecasts=[fc], policy_bundle=bundle, quota=_sample_quota(),
        yes_frame=ask_only_yes.payload, include_no_side=False,
    )
    ev_run2 = decider.evaluate_bin(
        orig_session_id="orig-sess-99", execution_mode="PAPER", scan_clock="PRICE_CLOCK",
        scan_ts_utc=t0, station_id="KORD", target_date="2026-11-21",
        bin_id="bin-58-59", market_id="mkt-1", yes_token_id="ty",
        forecasts=[fc], policy_bundle=bundle, quota=_sample_quota(),
        yes_frame=ask_only_yes.payload, include_no_side=False,
    )
    assert ev_run1.decision_outcome == "ORDERED"
    line1 = ev_run1.to_json_line()
    line2 = ev_run2.to_json_line()
    assert line1 == line2
    assert ev_run1.decision_id == ev_run2.decision_id
    assert verify_record_sha256_line(line1)
    parsed_p1 = json.loads(line1)
    assert parsed_p1["scaler_policy_id"] == "provisional_identity_v0"
    assert parsed_p1["scaler_provisional"] is True
    assert parsed_p1["scaler_provenance"] == "PROVISIONAL_UNTIL_D6"


def test_p6_scaler_mirror_p7_quota_provider_and_p16_slot() -> None:
    t0 = datetime(2026, 11, 21, 14, 0, 0, tzinfo=timezone.utc)
    bundle = _sample_policy_bundle(t0)
    assert bundle.scaler_policy_id == "provisional_identity_v0"
    assert bundle.scaler_provisional is True
    assert bundle.scaler_provenance == "PROVISIONAL_UNTIL_D6"

    seen_queries: list[QuotaQuery] = []

    class _StubQuotaProvider:
        def query_quota(self, query: QuotaQuery) -> QuotaSnapshot:
            seen_queries.append(query)
            return _sample_quota()

    seen_events: list[LightLevelEvent] = []
    slot = P16SubscriptionSlot()
    slot.register_listener(seen_events.append)
    p16_ev = LightLevelEvent(
        event_id="p16-ev-01", level="YELLOW", reason="TEST_LIGHT", emitted_ts_utc=t0
    )
    slot.publish(p16_ev)
    assert seen_events == [p16_ev]

    cfg = default_stub_trading_config()
    decider = DeterministicDecider(exec_config=cfg, p16_slot=slot)
    fc = build_stub_forecast_v11(issue_ts_utc=t0 - timedelta(minutes=15), settle_close_utc=t0 + timedelta(hours=10))
    ask_yes, _ = build_p4_v11_stub_envelope(
        session_id="sess-q", seq_id=1, frame_seq=1,
        token_id="ty", market_id="mkt-1", condition_id="c1",
        station_id="KORD", target_date="2026-11-21", bin_label="58-59°F",
        outcome="YES", regime="ask_only", recv_ts_utc=t0 - timedelta(seconds=1),
        asks=((0.25, 100.0),), bids=(),
    )
    ev = decider.evaluate_bin(
        orig_session_id="sess-q", execution_mode="PAPER", scan_clock="PRICE_CLOCK",
        scan_ts_utc=t0, station_id="KORD", target_date="2026-11-21",
        bin_id="bin-58-59", market_id="mkt-1", yes_token_id="ty",
        forecasts=[fc], policy_bundle=bundle, quota_provider=_StubQuotaProvider(),
        yes_frame=ask_yes.payload, include_no_side=False,
    )
    assert len(seen_queries) == 1
    assert seen_queries[0].policy_version == bundle.policy_version
    assert ev.light_status == "YELLOW"
    assert ev.p16_event_id == "p16-ev-01"
    parsed_p1 = json.loads(ev.to_json_line())
    assert parsed_p1["light_status"] == "YELLOW"
    assert parsed_p1["p16_event_id"] == "p16-ev-01"
