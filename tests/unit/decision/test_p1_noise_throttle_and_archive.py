"""Unit tests for Part A: P1 no-depth throttle, `.jsonl.gz` reader, and safe archival."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import gzip
from pathlib import Path

import pytest

from scripts.archive_audit_logs import archive_historical_logs
from src.audit.audit_logger import AsyncAuditLogger
from src.audit.p10_reader import P10Query, query_p10_session_view, read_verified_jsonl_file
from src.decision.engine import ScanDecisionEvent
from src.decision.offline_scheduler import _P1NoDepthThrottle


def _make_p1_event(
    *,
    decision_id: str,
    scan_ts_utc: datetime,
    outcome: str,
    reason: str | None = None,
    bin_id: str = "bin-60-61F",
) -> ScanDecisionEvent:
    return ScanDecisionEvent(
        schema_version="p1.v3",
        decision_id=decision_id,
        session_id="sess-test",
        execution_mode="PAPER",
        scan_ts_utc=scan_ts_utc,
        scan_clock="PRICE_CLOCK",
        station_id="KMIA",
        target_date="2026-11-27",
        target_type="TMAX",
        market_id="mkt-1",
        bin_id=bin_id,
        token_id="tok-1",
        forecast_id="fc-1",
        book_frame_ref=1,
        tau_hours=10.0,
        model_hash="mh-1",
        config_hash="ch-1",
        policy_version="p6-v1",
        policy_overdue=False,
        scaler_policy_id="IdentityScaler",
        scaler_provisional=True,
        scaler_provenance="TEST",
        light_status="GREEN",
        p16_event_id=None,
        best_ask_price=0.40 if outcome != "BLOCKED_NO_BOOK_DEPTH" else None,
        best_ask_edge=0.10 if outcome != "BLOCKED_NO_BOOK_DEPTH" else None,
        m_threshold=0.04,
        w_tau=0.5,
        s_edge=0.5,
        b_budget_usd=100.0,
        held_usd=0.0,
        g_cap_usd=25.0,
        headroom_d=25.0,
        target_slice_usd=10.0 if outcome == "ORDERED" else 0.0,
        decision_outcome=outcome,
        degradation_reason=reason,
    )


def test_p1_no_depth_throttle_never_drops_actionable_and_respects_heartbeat() -> None:
    t0 = datetime(2026, 11, 27, 10, 0, 0, tzinfo=timezone.utc)
    th = _P1NoDepthThrottle(heartbeat_sec=900.0)

    # First BLOCKED_NO_BOOK_DEPTH is logged; repeated within 900s is suppressed.
    assert th.should_log(_make_p1_event(decision_id="d1", scan_ts_utc=t0, outcome="BLOCKED_NO_BOOK_DEPTH", reason="STALE_OR_MISSING_BOTH_LEGS")) is True
    assert th.should_log(_make_p1_event(decision_id="d2", scan_ts_utc=t0 + timedelta(seconds=60), outcome="BLOCKED_NO_BOOK_DEPTH", reason="STALE_OR_MISSING_BOTH_LEGS")) is False
    # Degradation reason change triggers immediate log.
    assert th.should_log(_make_p1_event(decision_id="d3", scan_ts_utc=t0 + timedelta(seconds=120), outcome="BLOCKED_NO_BOOK_DEPTH", reason="MISSING_BOOK_FRAME")) is True
    # After >=900s heartbeat, logs again.
    assert th.should_log(_make_p1_event(decision_id="d4", scan_ts_utc=t0 + timedelta(seconds=1020), outcome="BLOCKED_NO_BOOK_DEPTH", reason="MISSING_BOOK_FRAME")) is True

    # Non-BLOCKED_NO_BOOK_DEPTH outcomes are NEVER throttled even at identical timestamps.
    for idx, outcome in enumerate(("ORDERED", "SKIP_EDGE_BELOW_M", "BLOCKED_BELOW_MIN_ORDER", "IDLE_BUDGET_EXHAUSTED")):
        assert th.should_log(_make_p1_event(decision_id=f"act-{idx}-a", scan_ts_utc=t0, outcome=outcome)) is True
        assert th.should_log(_make_p1_event(decision_id=f"act-{idx}-b", scan_ts_utc=t0 + timedelta(seconds=1), outcome=outcome)) is True


def test_archive_historical_logs_skips_today_and_p10_reader_reads_gz(tmp_path: Path) -> None:
    audit_root = tmp_path / "audit"
    with AsyncAuditLogger(audit_root, execution_mode="PAPER") as logger:
        logger.log_p1_scan_decision(
            _make_p1_event(
                decision_id="hist-1",
                scan_ts_utc=datetime(2026, 11, 26, 12, 0, 0, tzinfo=timezone.utc),
                outcome="ORDERED",
            )
        )
        logger.log_p1_scan_decision(
            _make_p1_event(
                decision_id="today-1",
                scan_ts_utc=datetime(2026, 11, 27, 12, 0, 0, tzinfo=timezone.utc),
                outcome="ORDERED",
            )
        )
        logger.flush()

    hist_jsonl = audit_root / "PAPER" / "2026-11-26" / "p1_scan_decisions.jsonl"
    today_jsonl = audit_root / "PAPER" / "2026-11-27" / "p1_scan_decisions.jsonl"
    assert hist_jsonl.exists() and today_jsonl.exists()

    # Dry-run leaves everything untouched.
    dry = archive_historical_logs(audit_root=audit_root, execution_mode="PAPER", today_utc=date(2026, 11, 27), dry_run=True)
    assert len(dry) == 1
    assert hist_jsonl.exists()

    # Real archive compresses only < today_utc.
    done = archive_historical_logs(audit_root=audit_root, execution_mode="PAPER", today_utc=date(2026, 11, 27), dry_run=False)
    assert len(done) == 1
    assert not hist_jsonl.exists()
    hist_gz = hist_jsonl.with_name(hist_jsonl.name + ".gz")
    assert hist_gz.exists()
    assert today_jsonl.exists()

    # Direct gz read + corrupt detection + full query_p10_session_view across .gz and .jsonl
    gz_res = read_verified_jsonl_file(hist_gz, verify_sha256=True)
    assert gz_res.valid_lines == 1 and len(gz_res.corrupt_lines) == 0

    view = query_p10_session_view(audit_root, P10Query(execution_mode="PAPER"))
    assert view.render_status == "OK"
    assert sorted(r["decision_id"] for r in view.p1_events) == ["hist-1", "today-1"]

    # Corrupt line inside .gz is quarantined cleanly.
    with gzip.open(hist_gz, "at", encoding="utf-8") as fh:
        fh.write("{bad json\n")
    corrupt_res = read_verified_jsonl_file(hist_gz, verify_sha256=True)
    assert corrupt_res.valid_lines == 1 and len(corrupt_res.corrupt_lines) == 1
