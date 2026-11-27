"""Unit tests for Part B & C: M10 loopback live server, incremental cache, and consistency verification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import threading
import urllib.error
import urllib.request

import pytest

from scripts.serve_m10_live import create_m10_live_server, validate_loopback_host
from src.audit.audit_logger import AsyncAuditLogger
from src.audit.p10_reader import CorruptLineRecord, DecisionJoinChain, P10Query, P10SessionView
from src.decision.engine import ScanDecisionEvent
from src.ui.m10_consistency import evaluate_m10_consistency
from src.ui.m10_live_cache import IncrementalAuditCache


def _write_safety_yaml(path: Path, ledger_path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                "execution_mode: PAPER",
                "live_confirmation_env_var: POLY_LIVE_CONFIRM",
                "live_confirmation_expected_value: CONFIRM_LIVE",
                "clob_host: https://clob.polymarket.com",
                "chain_id: 137",
                "signature_type: 2",
                "tick_size_ttl_sec: 300.0",
                "use_system_proxy: false",
                'max_single_order_usd: "25"',
                'max_daily_cumulative_usd: "250"',
                f"daily_ledger_path: {ledger_path}",
                'min_order_size_shares: "5"',
                'max_limit_price: "0.99"',
                "allowed_tick_sizes:",
                '  - "0.01"',
                '  - "0.001"',
                "require_neg_risk: true",
                "request_timeout_sec: 5.0",
                "max_reconnect_attempts: 3",
                "backoff_base_sec: 0.01",
                "backoff_max_sec: 0.05",
                "backoff_jitter_ratio: 0.2",
                "circuit_breaker_failure_threshold: 5",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _assert_strictly_readonly_html(html_text: str, *, allow_live_poll_script: bool = False) -> None:
    low = html_text.lower()
    always_forbidden = ("<form", "<button", "<input", "<select", "<textarea", "xmlhttprequest", "cdn.", "<script src=")
    for forbidden in always_forbidden:
        assert forbidden not in low, f"Forbidden write/external element found in M10 HTML: {forbidden!r}"
    if allow_live_poll_script:
        assert low.count("<script") <= 1
        if "<script" in low:
            assert 'data-m10-live-poll="1"' in low
            assert "fetch(window.location.href" in low
            assert "method:" not in low
    else:
        for forbidden in ("<script", "fetch("):
            assert forbidden not in low, f"Forbidden script element found in offline M10 HTML: {forbidden!r}"
    assert "风险参数面板" in html_text


def _make_p1_ordered(decision_id: str, forecast_id: str, ts: datetime) -> ScanDecisionEvent:
    return ScanDecisionEvent(
        schema_version="p1.v3",
        decision_id=decision_id,
        session_id="sess-live",
        execution_mode="PAPER",
        scan_ts_utc=ts,
        scan_clock="PRICE_CLOCK",
        station_id="KMIA",
        target_date="2026-11-27",
        target_type="TMAX",
        market_id="mkt-live",
        bin_id="76-77F",
        token_id="tok-yes",
        forecast_id=forecast_id,
        book_frame_ref=1,
        tau_hours=8.0,
        model_hash="mh-live",
        config_hash="ch-live",
        policy_version="p6-v1",
        policy_overdue=False,
        scaler_policy_id="IdentityScaler",
        scaler_provisional=True,
        scaler_provenance="TEST",
        light_status="GREEN",
        p16_event_id=None,
        best_ask_price=0.40,
        best_ask_edge=0.08,
        m_threshold=0.04,
        w_tau=0.5,
        s_edge=0.5,
        b_budget_usd=100.0,
        held_usd=0.0,
        g_cap_usd=25.0,
        headroom_d=25.0,
        target_slice_usd=10.0,
        decision_outcome="ORDERED",
        degradation_reason=None,
    )


def test_loopback_validation_and_live_http_server_incremental_refresh(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        validate_loopback_host("0.0.0.0")
    assert validate_loopback_host("127.0.0.1") == "127.0.0.1"

    audit_root = tmp_path / "audit"
    cfg_path = _write_safety_yaml(tmp_path / "clob_gateway.yaml", tmp_path / "daily.json")
    t0 = datetime(2026, 11, 27, 10, 0, 0, tzinfo=timezone.utc)
    with AsyncAuditLogger(audit_root, execution_mode="PAPER") as logger:
        logger.log_p1_scan_decision(_make_p1_ordered("dec-1", "MISSING_FORECAST", t0))
        logger.flush()

    server = create_m10_live_server(
        host="127.0.0.1",
        port=0,
        audit_root=audit_root,
        execution_mode="PAPER",
        safety_config=cfg_path,
        refresh_sec=15,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    base_url = f"http://127.0.0.1:{port}/"
    try:
        with urllib.request.urlopen(base_url, timeout=5) as resp:
            assert resp.status == 200
            html1 = resp.read().decode("utf-8")
        _assert_strictly_readonly_html(html1, allow_live_poll_script=True)
        assert 'data-m10-live-poll="1"' in html1 and "15000" in html1
        assert 'id="m10-live-root"' in html1
        assert "dec-1" in html1

        # Paused refresh (refresh=0) emits zero <script> tags.
        with urllib.request.urlopen(base_url + "?refresh=0", timeout=5) as resp_paused:
            assert resp_paused.status == 200
            _assert_strictly_readonly_html(resp_paused.read().decode("utf-8"), allow_live_poll_script=False)

        # Append a new P1 line and verify second GET picks it up incrementally.
        with AsyncAuditLogger(audit_root, execution_mode="PAPER") as logger:
            logger.log_p1_scan_decision(_make_p1_ordered("dec-2", "MISSING_FORECAST", t0 + timedelta(minutes=1)))
            logger.flush()

        with urllib.request.urlopen(base_url, timeout=5) as resp2:
            assert resp2.status == 200
            html2 = resp2.read().decode("utf-8")
        _assert_strictly_readonly_html(html2, allow_live_poll_script=True)
        assert "dec-2" in html2
        assert "缓存跳过" in html2

        # Write methods must return 405 Method Not Allowed.
        for method in ("POST", "PUT", "DELETE"):
            req = urllib.request.Request(base_url, method=method, data=b"x")
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(req, timeout=5)
            assert exc_info.value.code == 405
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_incremental_cache_skips_prior_bytes(tmp_path: Path) -> None:
    audit_root = tmp_path / "audit"
    t0 = datetime(2026, 11, 27, 10, 0, 0, tzinfo=timezone.utc)
    with AsyncAuditLogger(audit_root, execution_mode="PAPER") as logger:
        logger.log_p1_scan_decision(_make_p1_ordered("d-a", "MISSING_FORECAST", t0))
        logger.flush()

    cache = IncrementalAuditCache(audit_root=audit_root, execution_mode="PAPER")
    _, meta1 = cache.build_live_view(P10Query(execution_mode="PAPER"))
    assert meta1["bytes_read"] > 0 and meta1["bytes_skipped"] == 0

    _, meta2 = cache.build_live_view(P10Query(execution_mode="PAPER"))
    assert meta2["bytes_read"] == 0 and meta2["bytes_skipped"] == meta1["bytes_read"]


def test_consistency_verifier_detects_pass_and_failures() -> None:
    t0 = datetime(2026, 11, 27, 10, 0, 0, tzinfo=timezone.utc)
    p17 = {
        "forecast_id": "fc-1",
        "issue_ts_utc": t0.isoformat(),
        "model_hash": "mh-1",
        "config_hash": "ch-1",
    }
    p1 = {
        "decision_id": "dec-ok",
        "forecast_id": "fc-1",
        "scan_ts_utc": (t0 + timedelta(seconds=10)).isoformat(),
        "station_id": "KMIA",
        "target_date": "2026-11-27",
        "target_type": "TMAX",
        "market_id": "mkt-1",
        "bin_id": "76-77F",
        "model_hash": "mh-1",
        "config_hash": "ch-1",
        "decision_outcome": "ORDERED",
        "target_slice_usd": "10",
    }
    p3 = {
        "attempt_id": "att-1",
        "decision_id": "dec-ok",
        "submit_ts_utc": (t0 + timedelta(seconds=11)).isoformat(),
        "final_ts_utc": (t0 + timedelta(seconds=12)).isoformat(),
        "station_id": "KMIA",
        "market_id": "mkt-1",
        "filled_usd": "5.0",
        "terminal_status": "FILLED",
        "schema_version": "p3.v1",
    }
    p19_ok = {
        "event_id": "ev-1",
        "related_ref_id": "dec-ok",
        "event_ts_utc": (t0 + timedelta(seconds=12)).isoformat(),
        "event_type": "FILL_SETTLE_CONVERSION",
        "free_cash_usd": "1994.95",
        "active_locked_usd": "0",
        "held_position_cost_usd": "5.00",
        "cumulative_fee_paid_usd": "0.05",
        "tier_pool_usd": "2000",
        "realized_pnl_usd": "0",
    }
    ok_view = P10SessionView(
        execution_mode="PAPER", render_status="OK", tail_status="NONE", settlement_status="PENDING_P9",
        p1_events=(p1,), p3_events=(p3,), p12_ledgers=(), p17_snapshots=(p17,), p19_events=(p19_ok,),
        joined_chains=(DecisionJoinChain("dec-ok", p1, p17, None, (p3,), (p19_ok,)),),
        valid_lines=4, corrupt_lines=(), partial_tail_skipped_lines=0, missing_forecast_fk_count=0, p9_events=(),
    )
    ok_report = evaluate_m10_consistency(ok_view, (), ())
    assert ok_report.overall_status == "PASS"
    assert ok_report.chain_verifications["dec-ok"].status == "PASS"

    # Inject out-of-order P3 (< P1), orphan P3, and non-zero P19 conservation residual.
    bad_p3 = {**p3, "submit_ts_utc": (t0 + timedelta(seconds=5)).isoformat(), "final_ts_utc": (t0 + timedelta(seconds=5)).isoformat()}
    orphan_p3 = {**p3, "attempt_id": "att-orphan", "decision_id": "dec-ghost"}
    bad_p19 = {**p19_ok, "free_cash_usd": "1900.00"}
    bad_view = P10SessionView(
        execution_mode="PAPER", render_status="OK", tail_status="NONE", settlement_status="PENDING_P9",
        p1_events=(p1,), p3_events=(bad_p3, orphan_p3), p12_ledgers=(), p17_snapshots=(p17,), p19_events=(bad_p19,),
        joined_chains=(DecisionJoinChain("dec-ok", p1, p17, None, (bad_p3,), (bad_p19,)),),
        valid_lines=5, corrupt_lines=(), partial_tail_skipped_lines=0, missing_forecast_fk_count=0, p9_events=(),
    )
    bad_report = evaluate_m10_consistency(bad_view, (), ())
    assert bad_report.overall_status == "FAIL"
    by_name = {c.name[:2]: c.status for c in bad_report.checks}
    assert by_name["1."] == "FAIL"
    assert by_name["3."] == "FAIL"
    assert by_name["4."] == "FAIL"


def test_live_server_filters_lazy_period_and_filled_priority(tmp_path: Path) -> None:
    from src.execution.executor import ExecutionAttemptLog
    from src.audit.p19_events import CapitalEventLog

    audit_root = tmp_path / "audit"
    cfg_path = _write_safety_yaml(tmp_path / "clob_gateway.yaml", tmp_path / "daily.json")
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.date().isoformat()
    old_ts = now_utc - timedelta(days=20)
    fill_ts = now_utc - timedelta(minutes=20)

    with AsyncAuditLogger(audit_root, execution_mode="PAPER") as logger:
        old_p1 = _make_p1_ordered("dec-old", "MISSING_FORECAST", old_ts)
        old_p1 = ScanDecisionEvent(**{**old_p1.__dict__, "target_date": old_ts.date().isoformat()})
        logger.log_p1_scan_decision(old_p1)

        fill_p1 = _make_p1_ordered("dec-filled", "MISSING_FORECAST", fill_ts)
        fill_p1 = ScanDecisionEvent(**{**fill_p1.__dict__, "station_id": "KORD", "target_date": today_str, "target_type": "TMIN"})
        logger.log_p1_scan_decision(fill_p1)
        logger.log_p3_execution_attempt(
            ExecutionAttemptLog(
                schema_version="p3.v1", attempt_id="att-fill", idempotency_key="k1",
                decision_id="dec-filled", session_id="sess-live", execution_mode="PAPER",
                capture_replay_mode="NONE", replay_source_seq_id=None, latency_injected_ms=0,
                station_id="KORD", market_id="mkt-live", token_id="tok-yes",
                model_hash="mh-live", config_hash="ch-live",
                decision_ts_utc=fill_ts, decision_best_ask=Decimal("0.40"),
                decision_est_vwap=Decimal("0.40"), decision_qual_depth_shares=Decimal("50"),
                order_type="IOC_FAK", limit_price=Decimal("0.41"), target_shares=Decimal("10"),
                target_usd=Decimal("4.00"), submit_ts_utc=fill_ts + timedelta(seconds=1),
                final_ts_utc=fill_ts + timedelta(seconds=2), terminal_status="FILLED",
                reject_or_abort_reason=None, filled_shares=Decimal("10"), filled_usd=Decimal("4.00"),
                actual_avg_fill_price=Decimal("0.40"), fee_paid_usd=Decimal("0.04"),
                fill_rate=Decimal("1"), slippage_vs_best_ask=Decimal("0"),
                slippage_vs_est_vwap=Decimal("0"), execution_legs=(),
            )
        )
        logger.log_p19_capital_event(
            CapitalEventLog(
                schema_version="p19.v1", event_id="ev-fill", event_ts_utc=fill_ts + timedelta(seconds=2),
                session_id="sess-live", execution_mode="PAPER", station_id="KORD",
                event_type="FILL_SETTLE_CONVERSION", light_status="GREEN",
                tier_pool_usd=2000.0, free_usd_after=1995.96, active_locked_usd_after=0.0,
                station_realized_pnl_usd=0.0, policy_version="p6-v1", config_hash="ch-live",
                is_overdue=False, related_ref_id="dec-filled", reason="FILL",
            )
        )
        # Add 60 newer SKIP_EDGE_BELOW_M scans on KMIA/TMAX that would bury dec-filled without P3 priority.
        for idx in range(60):
            sk = _make_p1_ordered(f"dec-skip-{idx}", "MISSING_FORECAST", now_utc - timedelta(seconds=60 - idx))
            sk = ScanDecisionEvent(**{**sk.__dict__, "target_date": today_str, "decision_outcome": "SKIP_EDGE_BELOW_M"})
            logger.log_p1_scan_decision(sk)
        logger.flush()

    server = create_m10_live_server(
        host="127.0.0.1", port=0, audit_root=audit_root, execution_mode="PAPER", safety_config=cfg_path,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}/"
    try:
        # 1. Default view (period=today, action=p3) lazily skips old_ts dir and prioritizes dec-filled.
        with urllib.request.urlopen(base_url, timeout=5) as resp:
            html_today = resp.read().decode("utf-8")
        _assert_strictly_readonly_html(html_today, allow_live_poll_script=True)
        assert "dec-filled" in html_today and 'id="city-KORD"' in html_today and 'id="drawer-p9"' in html_today
        assert "dec-old" not in html_today
        assert "1 笔成交" in html_today and "$4.00" in html_today
        assert "$1995.96" in html_today
        assert "/decision?" in html_today and "id=dec-filled" in html_today and 'target="_blank"' in html_today
        assert "最近成交与委托订单一览" in html_today
        assert html_today.index("最近成交与委托订单一览") < html_today.index("分城市持仓与独立盘口") < html_today.index("累计已实现盈亏走势")

        # 1a. Verify popup /decision?id=dec-filled detail page is zero-script and shows full 6-step card.
        with urllib.request.urlopen(base_url + "decision?id=dec-filled", timeout=5) as resp_det:
            detail_html = resp_det.read().decode("utf-8")
        _assert_strictly_readonly_html(detail_html, allow_live_poll_script=False)
        assert 'id="dec-dec-filled"' in detail_html and "← 返回监控主页" in detail_html

        # 1b. Simulate upstream scheduler restart writing free_usd_after=2000.0 after prior fill: KPI Card 1 shows both accounts & warning.
        with AsyncAuditLogger(audit_root, execution_mode="PAPER") as logger:
            logger.log_p19_capital_event(
                CapitalEventLog(
                    schema_version="p19.v1", event_id="ev-reset", event_ts_utc=now_utc + timedelta(seconds=1),
                    session_id="sess-live", execution_mode="PAPER", station_id="KORD",
                    event_type="UNFREEZE", light_status="GREEN", tier_pool_usd=None,
                    free_usd_after=2000.0, active_locked_usd_after=0.0,
                    station_realized_pnl_usd=None, policy_version="p6-v1", config_hash="ch-live",
                    is_overdue=False, related_ref_id="dec-skip-0", reason="RESTART_UNFREEZE",
                )
            )
            logger.flush()
        with urllib.request.urlopen(base_url, timeout=5) as resp_mismatch:
            html_mismatch = resp_mismatch.read().decode("utf-8")
        assert "$1995.96" in html_mismatch and "P19 最新落盘=$2000.0" in html_mismatch and "上游重启未继承持仓" in html_mismatch

        # 2. Target type & station filtering + station timezone display.
        with urllib.request.urlopen(base_url + "?period=today&station=KORD&target_type=TMIN&tz=station", timeout=5) as resp2:
            html_kord = resp2.read().decode("utf-8")
        assert "dec-filled" in html_kord
        assert "最低温 TMIN" in html_kord
        assert ("CST" in html_kord or "CDT" in html_kord)

        # 3. Period=all loads the older directory on demand.
        with urllib.request.urlopen(base_url + "?period=all&action=p3", timeout=5) as resp3:
            html_all = resp3.read().decode("utf-8")
        assert "dec-old" in html_all
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_live_server_p13_on_demand_incremental_lookup(tmp_path: Path) -> None:
    from src.utils.causal_utils import compute_record_sha256

    audit_root = tmp_path / "audit"
    p13_root = tmp_path / "recordings"
    cfg_path = _write_safety_yaml(tmp_path / "clob_gateway.yaml", tmp_path / "daily.json")
    t0 = datetime.now(timezone.utc) - timedelta(minutes=5)
    with AsyncAuditLogger(audit_root, execution_mode="PAPER") as logger:
        logger.log_p1_scan_decision(_make_p1_ordered("dec-p13-live", "MISSING_FORECAST", t0))
        logger.flush()

    p13_file = p13_root / "PASSIVE_RECORD" / t0.date().isoformat() / "sess-live" / "p13_book_stream_KMIA.jsonl"
    p13_file.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "schema_version": "p13.v1",
        "session_id": "sess-live",
        "payload": {
            "token_id": "tok-yes",
            "frame_seq": 1,
            "recv_ts_utc": (t0 - timedelta(seconds=5)).isoformat(),
            "data_source": "CLOB_WS",
            "single_side": None,
            "best_bid": 0.38,
            "fee_rate": 0.01,
            "min_order_size_shares": 5.0,
            "asks": [[0.40, 25.0], [0.41, 60.0]],
            "bids": [[0.38, 40.0]],
        },
    }
    rec["record_sha256"] = compute_record_sha256(rec)
    p13_file.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    server = create_m10_live_server(
        host="127.0.0.1", port=0, audit_root=audit_root, execution_mode="PAPER",
        safety_config=cfg_path, p13_root=p13_root,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/decision?id=dec-p13-live", timeout=5) as resp:
            html_out = resp.read().decode("utf-8")
        _assert_strictly_readonly_html(html_out, allow_live_poll_script=False)
        assert "0.4×25.0" in html_out or "0.40×25.0" in html_out
        assert "0.38×40.0" in html_out
        assert "CLOB_WS" in html_out
        assert "暂无对应快照" not in html_out
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_live_server_pagination_across_many_filled_orders(tmp_path: Path) -> None:
    from src.execution.executor import ExecutionAttemptLog

    audit_root = tmp_path / "audit"
    cfg_path = _write_safety_yaml(tmp_path / "clob_gateway.yaml", tmp_path / "daily.json")
    now_utc = datetime.now(timezone.utc)
    with AsyncAuditLogger(audit_root, execution_mode="PAPER") as logger:
        for i in range(55):
            ts = now_utc - timedelta(minutes=60 - i)
            did = f"dec-page-{i:03d}"
            p1 = ScanDecisionEvent(**{**_make_p1_ordered(did, "MISSING_FORECAST", ts).__dict__, "target_date": now_utc.date().isoformat()})
            logger.log_p1_scan_decision(p1)
            logger.log_p3_execution_attempt(
                ExecutionAttemptLog(
                    schema_version="p3.v1", attempt_id=f"att-{i:03d}", idempotency_key=f"k-{i}",
                    decision_id=did, session_id="sess-live", execution_mode="PAPER",
                    capture_replay_mode="NONE", replay_source_seq_id=None, latency_injected_ms=0,
                    station_id="KMIA", market_id="mkt-live", token_id="tok-yes",
                    model_hash="mh-live", config_hash="ch-live", decision_ts_utc=ts,
                    decision_best_ask=Decimal("0.40"), decision_est_vwap=Decimal("0.40"),
                    decision_qual_depth_shares=Decimal("50"), order_type="IOC_FAK",
                    limit_price=Decimal("0.41"), target_shares=Decimal("5"), target_usd=Decimal("2.00"),
                    submit_ts_utc=ts + timedelta(seconds=1), final_ts_utc=ts + timedelta(seconds=2),
                    terminal_status="FILLED", reject_or_abort_reason=None, filled_shares=Decimal("5"),
                    filled_usd=Decimal("2.00"), actual_avg_fill_price=Decimal("0.40"),
                    fee_paid_usd=Decimal("0.02"), fill_rate=Decimal("1"),
                    slippage_vs_best_ask=Decimal("0"), slippage_vs_est_vwap=Decimal("0"), execution_legs=(),
                )
            )
        logger.flush()

    server = create_m10_live_server(
        host="127.0.0.1", port=0, audit_root=audit_root, execution_mode="PAPER",
        safety_config=cfg_path, default_limit=20,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}/"
    try:
        with urllib.request.urlopen(base, timeout=5) as r1:
            h1 = r1.read().decode("utf-8")
        assert "已成交 55 笔" in h1
        assert "id=dec-page-054" in h1 and "id=dec-page-000" not in h1
        assert "第 1/3 页" in h1

        with urllib.request.urlopen(base + "?page=3", timeout=5) as r3:
            h3 = r3.read().decode("utf-8")
        assert "id=dec-page-000" in h3 and "id=dec-page-014" in h3 and "id=dec-page-054" not in h3
        assert "第 3/3 页" in h3
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
