"""Unit & contract tests for `src/bankroll/` (`M6`), `P7/P14/P15/P16/P19`, and `config_hash v2`."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest

from src.audit.audit_logger import AsyncAuditLogger
from src.audit.p10_reader import P10Query, query_p10_session_view
from src.audit.p19_events import CapitalEventLog
from src.audit.p8_aggregator import aggregate_p8_calibration_batch
from src.bankroll import (
    BankrollAccountManager,
    BankrollConfig,
    FillSettleLoopback,
    FreezeRequest,
    P15SettlementEvent,
    TierStepUpEvent,
)
from src.decision.engine import (
    DeterministicDecider,
    LightLevelEvent,
    P16SubscriptionSlot,
    PhiPolicy,
    QuotaQuery,
    SigmaDeltaFrozen,
    build_execution_policy_bundle,
)
from src.execution.stub_generator import (
    build_p4_v11_stub_envelope,
    build_stub_forecast_v11,
    default_stub_trading_config,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _make_manager(
    *,
    initial_pool_usd: Decimal = Decimal("2000"),
    full_deployment: bool = False,
    audit_logger: AsyncAuditLogger | None = None,
) -> tuple[BankrollAccountManager, list[CapitalEventLog]]:
    events: list[CapitalEventLog] = []
    cfg = BankrollConfig(
        session_id="sess-m6",
        execution_mode="PAPER",
        policy_version="p6.v2",
        config_hash="8173bc6e03015b22",
        initial_pool_usd=initial_pool_usd,
        full_deployment=full_deployment,
    )
    mgr = BankrollAccountManager(cfg, audit_logger=audit_logger, p19_sink=events.append)
    return mgr, events


def test_p14_freeze_partial_fill_unfreeze_p15_conservation_and_idempotency() -> None:
    t0 = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
    mgr, events = _make_manager(initial_pool_usd=Decimal("2000"))

    req1 = FreezeRequest("dec-1", "idem-1", "KORD", "mkt-1", "tok-1", Decimal("120.25"), t0)
    rec1 = mgr.freeze_for_order(req1)
    assert rec1.accepted and rec1.frozen_usd == Decimal("120.25") and not rec1.deduplicated
    # Duplicate idempotency_key returns cached receipt with zero duplicate P19 log
    rec1_dup = mgr.freeze_for_order(req1)
    assert rec1_dup.deduplicated and rec1_dup.frozen_usd == Decimal("120.25")
    assert len([e for e in events if e.event_type == "FREEZE"]) == 1

    # Partial fill converts filled cost basis into held bucket and refunds remainder
    filled = mgr.settle_order_fill(
        FillSettleLoopback("dec-1", "att-1", "KORD", "mkt-1", Decimal("80.10"), "PARTIAL", t0 + timedelta(seconds=1))
    )
    assert filled == Decimal("80.10")
    # Idempotent attempt retry
    assert mgr.settle_order_fill(
        FillSettleLoopback("dec-1", "att-1", "KORD", "mkt-1", Decimal("80.10"), "PARTIAL", t0 + timedelta(seconds=1))
    ) == Decimal("80.10")
    snap_after_fill = mgr.snapshot_state()
    assert snap_after_fill.active_locked_usd == Decimal("0")
    assert snap_after_fill.held_total_usd == Decimal("80.10")
    assert snap_after_fill.free_usd == Decimal("1919.90")
    assert snap_after_fill.conservation_residual_usd == Decimal("0")

    # Second freeze -> PAPER_MATCH_ABORTED_GAP unfreezes cleanly
    req2 = FreezeRequest("dec-2", "idem-2", "KORD", "mkt-2", "tok-2", Decimal("50.00"), t0 + timedelta(seconds=2))
    assert mgr.freeze_for_order(req2).accepted
    refunded = mgr.settle_order_fill(
        FillSettleLoopback(
            "dec-2", "att-2", "KORD", "mkt-2", Decimal("0"),
            "PAPER_MATCH_ABORTED_GAP", t0 + timedelta(seconds=3), "PAPER_MATCH_ABORTED_GAP",
        )
    )
    assert refunded == Decimal("50.00")

    # Fail-Closed when single freeze exceeds remaining station cap ($500)
    req_over_cap = FreezeRequest("dec-3", "idem-3", "KORD", "mkt-3", "tok-3", Decimal("420.00"), t0 + timedelta(seconds=4))
    rec_over = mgr.freeze_for_order(req_over_cap)
    assert not rec_over.accepted and rec_over.frozen_usd == Decimal("0")
    assert rec_over.blocked_reason == "STATION_CAP_EXCEEDED"

    # P15 settlement settles mkt-1 winning payout ($110.10 -> +$30.00 PnL)
    pnl = mgr.apply_p15_settlement(
        P15SettlementEvent("settle-1", "KORD", "mkt-1", Decimal("110.10"), t0 + timedelta(hours=6))
    )
    assert pnl == Decimal("30.00")
    assert mgr.apply_p15_settlement(
        P15SettlementEvent("settle-1", "KORD", "mkt-1", Decimal("110.10"), t0 + timedelta(hours=6))
    ) == Decimal("30.00")
    final_snap = mgr.snapshot_state()
    assert final_snap.held_total_usd == Decimal("0")
    assert final_snap.free_usd == Decimal("2030.00")
    assert final_snap.realized_pnl_total_usd == Decimal("30.00")
    assert final_snap.conservation_residual_usd == Decimal("0")


def test_station_loss_gate_trips_in_exempt_phase_without_p16_or_autoclose() -> None:
    t0 = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
    mgr, events = _make_manager(initial_pool_usd=Decimal("2000"))

    # Two positions at KMIA: lose $500 on mkt-a, still hold mkt-b ($100)
    assert mgr.freeze_for_order(FreezeRequest("d-a", "i-a", "KMIA", "mkt-a", "ta", Decimal("500"), t0)).accepted
    mgr.settle_order_fill(FillSettleLoopback("d-a", "a-a", "KMIA", "mkt-a", Decimal("500"), "FILLED", t0 + timedelta(seconds=1)))
    pnl_a = mgr.apply_p15_settlement(P15SettlementEvent("s-a", "KMIA", "mkt-a", Decimal("0"), t0 + timedelta(hours=1)))
    assert pnl_a == Decimal("-500")

    # Re-open would be blocked, check prior position stays untouched if filled before loss gate
    q_kmia = mgr.query_quota(QuotaQuery("KMIA", "mkt-new", "tn", "p6.v2"))
    assert q_kmia.station_loss_gate_tripped is True
    assert not q_kmia.account_drawdown_brake_tripped  # $500 == 25% of $2000, exempt phase!
    assert q_kmia.b_eff_headroom_usd == 0.0
    assert q_kmia.blocked_reason == "STATION_LOSS_GATE_TRIPPED"

    # Neighboring healthy station remains open; light_status never altered by local gate
    q_kord = mgr.query_quota(QuotaQuery("KORD", "mkt-ok", "to", "p6.v2"))
    assert not q_kord.station_loss_gate_tripped and q_kord.b_eff_headroom_usd == 500.0
    assert mgr.snapshot_state().light_status is None
    assert [e.event_type for e in events if e.event_type == "STATION_LOSS_GATE_TRIP"] == ["STATION_LOSS_GATE_TRIP"]


def test_drawdown_brake_dual_activation_paths_and_existing_held_preserved() -> None:
    t0 = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
    # Path 1: <= $2,000 exempt phase -> $600 loss (30% > 25%) does NOT trip account brake
    mgr, events = _make_manager(initial_pool_usd=Decimal("2000"))
    for idx, sid in enumerate(("KORD", "KJFK")):
        amt = Decimal("300")
        assert mgr.freeze_for_order(FreezeRequest(f"d-{idx}", f"i-{idx}", sid, f"m-{idx}", "t", amt, t0)).accepted
        mgr.settle_order_fill(FillSettleLoopback(f"d-{idx}", f"a-{idx}", sid, f"m-{idx}", amt, "FILLED", t0 + timedelta(seconds=1)))
        mgr.apply_p15_settlement(P15SettlementEvent(f"s-{idx}", sid, f"m-{idx}", Decimal("0"), t0 + timedelta(hours=2)))
    # Open a held position at KMIA before step-up to confirm super-gate never auto-closes held positions
    assert mgr.freeze_for_order(FreezeRequest("d-hold", "i-hold", "KMIA", "m-hold", "th", Decimal("150"), t0 + timedelta(hours=3))).accepted
    mgr.settle_order_fill(FillSettleLoopback("d-hold", "a-hold", "KMIA", "m-hold", Decimal("150"), "FILLED", t0 + timedelta(hours=3, seconds=1)))

    snap_exempt = mgr.snapshot_state()
    assert snap_exempt.drawdown_usd == Decimal("600")
    assert snap_exempt.drawdown_ratio == Decimal("0.3")
    assert not snap_exempt.drawdown_brake_enabled and not snap_exempt.drawdown_brake_tripped

    # First +$1,000 TIER_STEP_UP ($2,000 -> $3,000) activates 25% drawdown brake ($750)
    mgr.apply_tier_step_up(TierStepUpEvent("step-1", Decimal("1000"), Decimal("3000"), t0 + timedelta(hours=4), "MONTH2_GREEN_STEP"))
    assert mgr.snapshot_state().drawdown_brake_enabled is True
    # Peak equity is now 2400 ($3000 - $600? wait: initial peak was $2000, added $1000 -> equity $2400 -> new peak $2400)
    # Lose $400 at KATL + $400 at KDEN = $800 drop >= 25% * $3000 ($750)
    for idx, sid in enumerate(("KATL", "KDEN")):
        assert mgr.freeze_for_order(FreezeRequest(f"df-{idx}", f"if-{idx}", sid, f"mf-{idx}", "t", Decimal("400"), t0 + timedelta(hours=5))).accepted
        mgr.settle_order_fill(FillSettleLoopback(f"df-{idx}", f"af-{idx}", sid, f"mf-{idx}", Decimal("400"), "FILLED", t0 + timedelta(hours=5, seconds=1)))
        mgr.apply_p15_settlement(P15SettlementEvent(f"sf-{idx}", sid, f"mf-{idx}", Decimal("0"), t0 + timedelta(hours=6)))

    q_any = mgr.query_quota(QuotaQuery("KMIA", "m-hold", "th", "p6.v2"))
    assert q_any.account_drawdown_brake_tripped is True
    assert q_any.blocked_reason == "ACCOUNT_DRAWDOWN_BRAKE_TRIPPED"
    assert q_any.b_eff_headroom_usd == 0.0
    # Existing KMIA held $150 remains untouched (超门不自动平仓)
    assert q_any.market_held_usd == 150.0
    assert [e.event_type for e in events if e.event_type == "ACCOUNT_DRAWDOWN_BRAKE_TRIP"] == ["ACCOUNT_DRAWDOWN_BRAKE_TRIP"]

    # Path 2: Full deployment ($10,000) immediately activates 25% brake ($2,500)
    mgr_full, _ = _make_manager(initial_pool_usd=Decimal("10000"), full_deployment=True)
    assert mgr_full.snapshot_state().drawdown_brake_enabled is True


def test_p16_red_blocks_freeze_and_yellow_resets_green_months_plus_n8_headroom(tmp_path: Path) -> None:
    t0 = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
    logger = AsyncAuditLogger(tmp_path / "m7", execution_mode="PAPER")
    try:
        mgr, _ = _make_manager(audit_logger=logger)
        slot = P16SubscriptionSlot()
        slot.register_listener(mgr.on_p16_event)

        slot.publish(LightLevelEvent("ev-g1", "GREEN", "NORMAL", t0))
        assert mgr.increment_green_month(2) == 2

        # N8 multi-day headroom across two markets at same station (150 + 200 = 350 -> 150 left)
        assert mgr.freeze_for_order(FreezeRequest("d1", "k1", "KORD", "m1", "t1", Decimal("150"), t0)).accepted
        mgr.settle_order_fill(FillSettleLoopback("d1", "a1", "KORD", "m1", Decimal("150"), "FILLED", t0 + timedelta(seconds=1)))
        assert mgr.freeze_for_order(FreezeRequest("d2", "k2", "KORD", "m2", "t2", Decimal("200"), t0 + timedelta(seconds=2))).accepted
        q_n8 = mgr.query_quota(QuotaQuery("KORD", "m3", "t3", "p6.v2"))
        assert q_n8.station_active_locked_usd == 200.0
        assert q_n8.b_eff_headroom_usd == 150.0

        slot.publish(LightLevelEvent("ev-y1", "YELLOW", "DRIFT", t0 + timedelta(minutes=5)))
        assert mgr.snapshot_state().consecutive_green_months == 0

        slot.publish(LightLevelEvent("ev-r1", "RED", "EMERGENCY", t0 + timedelta(minutes=10)))
        q_red = mgr.query_quota(QuotaQuery("KORD", "m1", "t1", "p6.v2"))
        assert q_red.blocked_reason == "P16_RED_LIGHT_BLOCKED" and q_red.b_eff_headroom_usd == 0.0
        assert q_red.market_held_usd == 150.0  # Existing held untouched
        blocked_freeze = mgr.freeze_for_order(
            FreezeRequest("d-red", "k-red", "KORD", "m3", "t3", Decimal("50"), t0 + timedelta(minutes=11))
        )
        assert not blocked_freeze.accepted and blocked_freeze.blocked_reason == "P16_RED_LIGHT_BLOCKED"
    finally:
        logger.close()

    view = query_p10_session_view(tmp_path / "m7", P10Query(execution_mode="PAPER", date_range=(t0.date(), t0.date())))
    assert [r["event_type"] for r in view.p19_events] == [
        "LIGHT_LEVEL_APPLIED",
        "FREEZE",
        "FILL_SETTLE_CONVERSION",
        "FREEZE",
        "LIGHT_LEVEL_APPLIED",
        "LIGHT_LEVEL_APPLIED",
    ]


def test_config_hash_v2_includes_yellow_multiplier_and_p8_aggregator_filter(tmp_path: Path) -> None:
    t0 = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
    common = dict(
        policy_version="p6.v2", signed_at_utc=t0 - timedelta(hours=1), is_overdue=False,
        w0_intent=0.10, min_order_usd_eff=5.0, p=1.5, tau_max_h=24.0, station_cap_usd=500.0,
        concurrent_days=2, w_provenance="P8-CAPITAL-CONFIG v1.0",
        phi_policy=PhiPolicy(rho_0=Decimal("0.30"), k_slope=Decimal("0.0"), rho_min=Decimal("0.10"), rho_max=Decimal("0.50")),
        k0_threshold_coef=2.0, sigma_delta_frozen=SigmaDeltaFrozen(0.02, "test", "cyc-1"),
        friction_median=0.01, m_floor=0.02,
    )
    b_05 = build_execution_policy_bundle(yellow_multiplier=0.5, **common)
    b_025 = build_execution_policy_bundle(yellow_multiplier=0.25, **common)
    assert b_05.config_hash != b_025.config_hash

    mgr, _ = _make_manager()
    slot = P16SubscriptionSlot()
    decider = DeterministicDecider(exec_config=default_stub_trading_config(), p16_slot=slot)
    fc = build_stub_forecast_v11(issue_ts_utc=t0 - timedelta(minutes=15), settle_close_utc=t0 + timedelta(hours=10))
    ask_yes, _ = build_p4_v11_stub_envelope(
        session_id="sess-m6", seq_id=1, frame_seq=1, token_id="tok-y", market_id="mkt-1",
        condition_id="c1", station_id="KORD", target_date="2026-11-22", bin_label="58-59°F",
        outcome="YES", regime="ask_only", recv_ts_utc=t0 - timedelta(seconds=1),
        asks=((0.25, 100.0), (0.28, 200.0)), bids=(),
    )
    ev_05 = decider.evaluate_bin(
        orig_session_id="sess-m6", execution_mode="PAPER", scan_clock="PRICE_CLOCK",
        scan_ts_utc=t0, station_id="KORD", target_date="2026-11-22", bin_id="bin-58-59",
        market_id="mkt-1", yes_token_id="tok-y", forecasts=[fc], policy_bundle=b_05,
        quota_provider=mgr, yes_frame=ask_yes.payload, include_no_side=False,
    )
    # Publish RED so b_025 event logs IDLE_BUDGET_EXHAUSTED, proving p8_aggregator isolates b_05 cleanly
    slot.publish(LightLevelEvent("ev-red", "RED", "TEST_FILTER", t0))
    ev_025_idle = decider.evaluate_bin(
        orig_session_id="sess-m6-b", execution_mode="PAPER", scan_clock="PRICE_CLOCK",
        scan_ts_utc=t0, station_id="KORD", target_date="2026-11-22", bin_id="bin-58-59",
        market_id="mkt-1", yes_token_id="tok-y", forecasts=[fc], policy_bundle=b_025,
        quota_provider=mgr, yes_frame=ask_yes.payload, include_no_side=False,
    )
    logger = AsyncAuditLogger(tmp_path / "agg", execution_mode="PAPER")
    try:
        logger.log_p1_scan_decision(ev_05)
        logger.log_p1_scan_decision(ev_025_idle)
    finally:
        logger.close()
    batch = aggregate_p8_calibration_batch(
        tmp_path / "agg",
        execution_mode="PAPER",
        window_start_utc=t0 - timedelta(minutes=5),
        window_end_utc=t0 + timedelta(minutes=5),
        config_hash=b_05.config_hash,
    )
    assert batch.config_hash == b_05.config_hash
    assert batch.idle_rate_by_tau == {"tau_ge_24h": 0.0, "tau_6h_24h": 0.0, "tau_lt_6h": 0.0}


def test_p14_fee_paid_conservation_and_cost_basis() -> None:
    """`P14` fee_paid_usd stays conserved in `free + locked + held + fee == tier_pool + realized_pnl`."""
    t0 = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)
    mgr, _ = _make_manager(initial_pool_usd=Decimal("2000.00"))
    req = FreezeRequest("dec-fee-1", "idem-fee-1", "KORD", "mkt-fee", "tok-fee", Decimal("25.00"), t0)
    assert mgr.freeze_for_order(req).accepted

    total_spent = mgr.settle_order_fill(
        FillSettleLoopback(
            decision_id="dec-fee-1",
            attempt_id="att-fee-1",
            station_id="KORD",
            market_id="mkt-fee",
            filled_usd=Decimal("20.00"),
            fee_paid_usd=Decimal("0.40"),
            terminal_status="PARTIAL",
            settled_ts_utc=t0 + timedelta(seconds=1),
        )
    )
    assert total_spent == Decimal("20.40")
    snap = mgr.snapshot_state()
    assert snap.active_locked_usd == Decimal("0")
    assert snap.free_usd == Decimal("1979.60")
    assert snap.held_total_usd == Decimal("20.00")
    assert snap.fee_paid_total_usd == Decimal("0.40")
    assert snap.conservation_residual_usd == Decimal("0")
    assert mgr.position_cost_basis_incl_fee("KORD", "mkt-fee") == Decimal("20.40")

    # P15 settlement preserves cumulative fee_paid_usd conservation (`residual == 0`)
    pnl = mgr.apply_p15_settlement(
        P15SettlementEvent("settle-fee-1", "KORD", "mkt-fee", Decimal("30.00"), t0 + timedelta(hours=4))
    )
    assert pnl == Decimal("10.00")
    post_snap = mgr.snapshot_state()
    assert post_snap.held_total_usd == Decimal("0")
    assert post_snap.free_usd == Decimal("2009.60")
    assert post_snap.fee_paid_total_usd == Decimal("0.40")
    assert post_snap.conservation_residual_usd == Decimal("0")
    assert mgr.position_cost_basis_incl_fee("KORD", "mkt-fee") == Decimal("0")

    # Non-fill terminal status forbids non-zero fee_paid_usd
    req2 = FreezeRequest("dec-fee-2", "idem-fee-2", "KORD", "mkt-fee-2", "tok-fee-2", Decimal("10.00"), t0)
    assert mgr.freeze_for_order(req2).accepted
    with pytest.raises(ValueError, match="fee_paid_usd"):
        mgr.settle_order_fill(
            FillSettleLoopback(
                decision_id="dec-fee-2",
                attempt_id="att-fee-2",
                station_id="KORD",
                market_id="mkt-fee-2",
                filled_usd=Decimal("0"),
                fee_paid_usd=Decimal("0.10"),
                terminal_status="REJECTED",
                settled_ts_utc=t0 + timedelta(seconds=2),
            )
        )


def test_bankroll_and_decision_ast_function_length_under_50_lines() -> None:
    ge_50: list[tuple[str, str, int]] = []
    targets = list((REPO_ROOT / "src/bankroll").glob("*.py")) + [
        REPO_ROOT / "src/decision/engine.py",
        REPO_ROOT / "src/decision/offline_scheduler.py",
        REPO_ROOT / "src/prediction/forecast_distribution_engine.py",
        REPO_ROOT / "src/prediction/live_p5_producer.py",
    ]
    for path in targets:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                span = (node.end_lineno or node.lineno) - node.lineno + 1
                if span >= 50:
                    ge_50.append((str(path.relative_to(REPO_ROOT)), node.name, span))
    assert ge_50 == []
