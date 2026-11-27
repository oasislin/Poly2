"""Unit tests for per-station per-market-day PaperSafetyGate ($25/$250) and 6-city $6,000 pool."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from src.audit.audit_logger import AsyncAuditLogger
from src.audit.p10_reader import P10Query, query_p10_session_view
from src.audit.p13_reader import P18ReplayFrameRetriever
from src.bankroll import BankrollAccountManager, BankrollConfig
from src.decision.offline_scheduler import (
    OfflineSchedulerConfig,
    _match_and_bookkeep_ordered,
)
from src.execution.executor import ReplayMatcher, SlicePlan
from src.execution.paper_safety_gate import PaperSafetyGate
from src.execution.stub_generator import build_p4_v11_stub_envelope, default_stub_trading_config


def _make_p1_ordered_event(
    *,
    decision_id: str,
    ts: datetime,
    target_shares: str,
    limit_price: str,
    station_id: str = "KORD",
    target_date: str = "2026-11-28",
    token_id: str = "tok-yes-1",
) -> SimpleNamespace:
    sh = Decimal(target_shares)
    lp = Decimal(limit_price)
    usd = sh * lp
    plan = SlicePlan(
        should_submit=True,
        target_usd=usd,
        target_shares=sh,
        limit_price=lp,
        est_vwap=lp,
        qual_depth_shares=sh,
        order_type="IOC_FAK",
    )
    return SimpleNamespace(
        decision_outcome="ORDERED",
        decision_id=decision_id,
        station_id=station_id,
        target_date=target_date,
        target_type="TMAX",
        market_id=f"mkt-{station_id.lower()}-{target_date}",
        token_id=token_id,
        model_hash="mh-1",
        config_hash="ch-1",
        scan_ts_utc=ts,
        best_ask_price=float(lp),
        fee_rate_applied=0.01,
        slice_plan=plan,
        bin_id="40-41F",
    )


def _make_p13_retriever(ts: datetime, *, token_id: str = "tok-yes-1", price: float = 0.50, size: float = 1000.0) -> P18ReplayFrameRetriever:
    env, _ = build_p4_v11_stub_envelope(
        session_id="sess-1",
        seq_id=1,
        frame_seq=1,
        token_id=token_id,
        market_id="mkt-kord-2026-11-28",
        condition_id="cond-1",
        station_id="KORD",
        target_date="2026-11-28",
        bin_label="40-41F",
        outcome="YES",
        regime="ask_only",
        recv_ts_utc=ts,
        asks=((price, size),),
        bids=(),
    )
    return P18ReplayFrameRetriever([env])


def test_paper_safety_gate_per_station_per_market_day_isolation(tmp_path: Path) -> None:
    ledger = tmp_path / "gateway" / "paper_daily_usage.json"
    live_ledger = tmp_path / "gateway" / "daily_usage.json"
    gate = PaperSafetyGate(
        max_single_order_usd=Decimal("25"),
        max_daily_cumulative_usd=Decimal("250"),
        ledger_path=ledger,
    )

    # 1) Single order > $25 blocked immediately
    assert gate.check_order(Decimal("25.01"), station_id="KORD", target_date="2026-11-28") == "SAFETY_GATE_SINGLE_ORDER_EXCEEDED"
    assert gate.check_order(Decimal("25.00"), station_id="KORD", target_date="2026-11-28") is None

    # 2) KORD|2026-11-28 consumes $240 -> allows $10, blocks $10.01
    for _ in range(9):
        gate.record_fill(Decimal("25.00"), station_id="KORD", target_date="2026-11-28")
    gate.record_fill(Decimal("15.00"), station_id="KORD", target_date="2026-11-28")
    assert gate.used_usd("KORD", "2026-11-28") == Decimal("240.00")
    assert gate.check_order(Decimal("10.00"), station_id="KORD", target_date="2026-11-28") is None
    assert gate.check_order(Decimal("10.01"), station_id="KORD", target_date="2026-11-28") == "SAFETY_GATE_DAILY_LIMIT_EXCEEDED"

    # 3) Independent quotas for another city (KMIA same market day) and same city next market day (KORD|2026-11-29)
    assert gate.check_order(Decimal("25.00"), station_id="KMIA", target_date="2026-11-28") is None
    assert gate.check_order(Decimal("25.00"), station_id="KORD", target_date="2026-11-29") is None

    # 4) Persists across restart cleanly without touching live daily_usage.json
    gate_reloaded = PaperSafetyGate(
        max_single_order_usd=Decimal("25"),
        max_daily_cumulative_usd=Decimal("250"),
        ledger_path=ledger,
    )
    assert gate_reloaded.used_usd("KORD", "2026-11-28") == Decimal("240.00")
    assert json.loads(ledger.read_text(encoding="utf-8")) == {"KORD|2026-11-28": "240.00"}
    assert not live_ledger.exists()


def test_scheduler_paper_safety_gate_6_city_pool_and_conservation(tmp_path: Path) -> None:
    audit_root = tmp_path / "audit"
    ledger_path = tmp_path / "gateway" / "paper_daily_usage.json"
    gate = PaperSafetyGate(
        max_single_order_usd=Decimal("25"),
        max_daily_cumulative_usd=Decimal("30"),
        ledger_path=ledger_path,
    )
    t0 = datetime(2026, 11, 28, 16, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 11, 28, 16, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 11, 28, 16, 2, tzinfo=timezone.utc)

    retriever = _make_p13_retriever(t0, price=0.50, size=1000.0)
    matcher = ReplayMatcher(default_stub_trading_config(), allow_resting_book_fallback=True)
    cfg = OfflineSchedulerConfig(
        p13_session_dir=tmp_path / "p13",
        audit_output_root=audit_root,
        orig_session_id="sess-1",
        enable_p18_matching=True,
        enable_paper_safety_gate=True,
        paper_daily_ledger_path=ledger_path,
    )
    claims: dict = {}
    with AsyncAuditLogger(audit_root, execution_mode="PAPER") as logger:
        mgr = BankrollAccountManager(
            BankrollConfig(
                session_id="sess-1",
                execution_mode="PAPER",
                policy_version="p6-test",
                config_hash="ch-1",
                initial_pool_usd=Decimal("6000"),
                drawdown_activation_threshold_usd=Decimal("6000"),
            ),
            p19_sink=logger.log_p19_capital_event,
        )
        # 1) Single order $26 > $25 -> REJECTED before freeze
        att1 = _match_and_bookkeep_ordered(
            ev=_make_p1_ordered_event(decision_id="d-1", ts=t0, target_shares="52.00", limit_price="0.50", station_id="KORD", target_date="2026-11-28"),
            cfg=cfg, retriever=retriever, matcher=matcher, quota_provider=mgr,
            logger=logger, open_claims=claims, paper_safety_gate=gate,
        )
        assert att1 is not None and att1.terminal_status == "REJECTED"
        assert att1.reject_or_abort_reason == "SAFETY_GATE_SINGLE_ORDER_EXCEEDED"
        assert mgr.snapshot_state().free_usd == Decimal("6000")

        # 2) Valid $20 order for KORD|2026-11-28 -> FILLED
        att2 = _match_and_bookkeep_ordered(
            ev=_make_p1_ordered_event(decision_id="d-2", ts=t1, target_shares="40.00", limit_price="0.50", station_id="KORD", target_date="2026-11-28"),
            cfg=cfg, retriever=retriever, matcher=matcher, quota_provider=mgr,
            logger=logger, open_claims=claims, paper_safety_gate=gate,
        )
        assert att2 is not None and att2.terminal_status == "FILLED"
        assert att2.filled_usd == Decimal("20.00")
        assert gate.used_usd("KORD", "2026-11-28") == Decimal("20.00")

        # 3) Next $15 order for KORD|2026-11-28 ($20 + $15 = $35 > $30 cap) -> REJECTED before freeze
        att3 = _match_and_bookkeep_ordered(
            ev=_make_p1_ordered_event(decision_id="d-3", ts=t2, target_shares="30.00", limit_price="0.50", station_id="KORD", target_date="2026-11-28"),
            cfg=cfg, retriever=retriever, matcher=matcher, quota_provider=mgr,
            logger=logger, open_claims=claims, paper_safety_gate=gate,
        )
        assert att3 is not None and att3.terminal_status == "REJECTED"
        assert att3.reject_or_abort_reason == "SAFETY_GATE_DAILY_LIMIT_EXCEEDED"
        assert mgr.conservation_residual_usd == Decimal("0")
        logger.flush()

    view = query_p10_session_view(audit_root, P10Query(execution_mode="PAPER"))
    reasons = [r["reject_or_abort_reason"] for r in view.p3_events]
    assert reasons == [
        "SAFETY_GATE_SINGLE_ORDER_EXCEEDED",
        None,
        "SAFETY_GATE_DAILY_LIMIT_EXCEEDED",
    ]
