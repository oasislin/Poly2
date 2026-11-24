"""TDD unit & architectural guardrail tests for `S3-10` (`M10 v1` Read-Only View & Risk Panel)."""

from __future__ import annotations

import ast
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.audit.audit_logger import AsyncAuditLogger
from src.bankroll import (
    BankrollAccountManager,
    BankrollConfig,
    FillSettleLoopback,
    FreezeRequest,
)
from src.decision.engine import (
    DeterministicDecider,
    LightLevelEvent,
    P16SubscriptionSlot,
    PhiPolicy,
    SigmaDeltaFrozen,
    build_execution_policy_bundle,
)
from src.execution.clob_gateway import ClobOrderGateway
from src.execution.stub_generator import (
    build_p4_v11_stub_envelope,
    build_stub_forecast_v11,
    default_stub_trading_config,
)
from src.execution.trial_runner import PaperMockClobExchange, PaperOrderScenario, TrialRunner
from src.settlement.m9_settler import M9SettlementEngine, MarketPositionClaim, SettlementBinSpec
from src.data_acquisition.settlement_metar_stream import RawMetarReport


def _write_safety_yaml(path: Path, ledger_path: Path, *, mode: str = "PAPER", max_single: str = "25", max_daily: str = "250") -> Path:
    path.write_text(
        "\n".join(
            [
                f"execution_mode: {mode}",
                "live_confirmation_env_var: POLY_LIVE_CONFIRM",
                "live_confirmation_expected_value: CONFIRM_LIVE",
                "clob_host: https://clob.polymarket.com",
                "chain_id: 137",
                "signature_type: 2",
                "tick_size_ttl_sec: 300.0",
                "use_system_proxy: false",
                f'max_single_order_usd: "{max_single}"',
                f'max_daily_cumulative_usd: "{max_daily}"',
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


def _assert_strictly_readonly_html(html_text: str) -> None:
    low = html_text.lower()
    for forbidden in ("<form", "<button", "<input", "<select", "<textarea", "<script", "fetch(", "xmlhttprequest", "cdn."):
        assert forbidden not in low, f"Forbidden write/external element found in M10 HTML: {forbidden!r}"
    assert "风险参数面板" in html_text


def test_m10_full_chain_settlement_reconcile_and_paper_risk_panel(tmp_path: Path) -> None:
    """E2E M4->M5(PAPER)->M6->M9(P9+P15)->M7->M10 renders trace, dual hashes, PnL & PAPER gray panel."""
    from src.ui.m10_view import build_m10_dashboard_model, render_m10_dashboard_html

    t0 = datetime(2026, 11, 23, 14, 0, 0, tzinfo=timezone.utc)
    d = date(2026, 11, 23)
    audit_root = tmp_path / "m7"
    ledger_path = tmp_path / "daily_usage.json"
    cfg_path = _write_safety_yaml(tmp_path / "clob_gateway.yaml", ledger_path, mode="PAPER", max_single="25", max_daily="250")

    policy = build_execution_policy_bundle(
        policy_version="p6.v3",
        signed_at_utc=t0 - timedelta(hours=1),
        is_overdue=False,
        w0_intent=0.10,
        min_order_usd_eff=2.0,
        p=1.5,
        tau_max_h=24.0,
        station_cap_usd=60.0,
        concurrent_days=2,
        w_provenance="TEST_M10",
        phi_policy=PhiPolicy(rho_0=Decimal("0.40"), k_slope=Decimal("0"), rho_min=Decimal("0.20"), rho_max=Decimal("0.60")),
        k0_threshold_coef=1.0,
        sigma_delta_frozen=SigmaDeltaFrozen(0.01, "TEST", "cyc-m10"),
        friction_median=0.005,
        m_floor=0.01,
        yellow_multiplier=0.5,
    )
    exchange = PaperMockClobExchange(fee_rate_bps=50)
    exchange.queue_scenario(PaperOrderScenario(mode="FILLED"))
    slot = P16SubscriptionSlot()

    with AsyncAuditLogger(audit_root, execution_mode="PAPER") as logger:
        mgr = BankrollAccountManager(
            BankrollConfig(
                session_id="sess-m10",
                execution_mode="PAPER",
                policy_version=policy.policy_version,
                config_hash=policy.config_hash,
                initial_pool_usd=Decimal("2000.00"),
            ),
            audit_logger=logger,
        )
        light_ev = LightLevelEvent("p16-y-1", "YELLOW", "YELLOW_MILD_CALIBRATION_DRIFT", t0 - timedelta(minutes=5))
        slot.publish(light_ev)
        mgr.on_p16_event(light_ev)

        gw = ClobOrderGateway(safety_config_path=cfg_path, audit_logger=logger)
        runner = TrialRunner(
            session_id="sess-m10",
            decider=DeterministicDecider(exec_config=default_stub_trading_config(), p16_slot=slot),
            gateway=gw,
            bankroll=mgr,
            audit_logger=logger,
            exchange=exchange,
            policy_bundle=policy,
        )
        fc = build_stub_forecast_v11(
            target_date_str="2026-11-23",
            issue_ts_utc=t0 - timedelta(minutes=10),
            settle_close_utc=t0 + timedelta(hours=10),
        )
        yf = build_p4_v11_stub_envelope(
            session_id="sess-m10",
            seq_id=1,
            frame_seq=1,
            token_id="tok-m10",
            market_id="mkt-m10",
            condition_id="cond-m10",
            station_id="KORD",
            target_date="2026-11-23",
            bin_label="58-59°F",
            outcome="YES",
            regime="two_sided",
            recv_ts_utc=t0 - timedelta(seconds=1),
            asks=((0.25, 200.0),),
            bids=((0.24, 200.0),),
        )[0].payload
        step_res = runner.step_bin(
            scan_ts_utc=t0,
            station_id="KORD",
            target_date="2026-11-23",
            bin_id="bin-58-59",
            market_id="mkt-m10",
            yes_token_id="tok-m10",
            forecasts=[fc],
            yes_frame=yf,
            tick_size=Decimal("0.01"),
            neg_risk=True,
            exec_config=default_stub_trading_config(),
        )
        assert step_res.attempt_log is not None and step_res.attempt_log.terminal_status == "FILLED"

        # M9 settles winning bin 58-59°F (15.0°C = 59°F)
        settler = M9SettlementEngine(audit_logger=logger)
        reports = [
            RawMetarReport("KORD", datetime(2026, 11, 23, 18, 0, tzinfo=timezone.utc), datetime(2026, 11, 23, 18, 2, tzinfo=timezone.utc), "METAR", False, "METAR KORD 231800Z 00000KT 15/05 RMK T01500050", "AWC"),
            RawMetarReport("KORD", datetime(2026, 11, 24, 6, 5, tzinfo=timezone.utc), datetime(2026, 11, 24, 6, 7, tzinfo=timezone.utc), "METAR", False, "METAR KORD 240605Z 00000KT 10/04 RMK T01000040", "AWC"),
        ]
        bins = (
            SettlementBinSpec("bin-57below", None, 57),
            SettlementBinSpec("bin-58-59", 58, 59),
            SettlementBinSpec("bin-60plus", 60, None),
        )
        settler.settle_and_release_p15(
            session_id="sess-m10",
            execution_mode="PAPER",
            station_id="KORD",
            target_date=d,
            target_type="TMAX",
            claim=MarketPositionClaim(market_id="mkt-m10", bin_id="bin-58-59", held_shares=step_res.attempt_log.filled_shares),
            reports=reports,
            bins=bins,
            bankroll=mgr,
            as_of_ts_utc=datetime(2026, 11, 24, 6, 10, tzinfo=timezone.utc),
        )
        logger.flush()

    model = build_m10_dashboard_model(
        audit_root=audit_root,
        execution_mode="PAPER",
        safety_config_path=cfg_path,
        utc_date=d,
        model_hash="stub-model-hash-v1",
        model_frozen=True,
    )
    assert model.render_status == "OK"
    assert model.settlement_status == "READY"
    assert model.risk_panel.execution_mode == "PAPER"
    assert model.risk_panel.max_single_order_usd == Decimal("25")
    assert model.risk_panel.max_daily_cumulative_usd == Decimal("250")
    assert model.risk_panel.daily_used_usd == step_res.attempt_log.filled_usd
    assert model.risk_panel.daily_remaining_usd == Decimal("250") - step_res.attempt_log.filled_usd
    assert model.risk_panel.circuit_open is False
    assert model.risk_panel.light_status == "YELLOW"
    assert model.risk_panel.model_hash == "stub-model-hash-v1"
    assert model.risk_panel.model_frozen is True
    assert len(model.decision_rows) == 1
    assert len(model.settlement_rows) == 1
    assert model.settlement_rows[0]["winning_bin_id"] == "bin-58-59"
    assert model.settlement_rows[0]["reconciled"] is True
    assert model.total_filled_usd == step_res.attempt_log.filled_usd
    assert model.total_realized_pnl_usd == (
        step_res.attempt_log.filled_shares - step_res.attempt_log.filled_usd - step_res.attempt_log.fee_paid_usd
    )

    html = render_m10_dashboard_html(model)
    _assert_strictly_readonly_html(html)
    assert "mode-banner-paper" in html
    assert "mode-banner-live" not in html
    assert "stub-model-hash-v1" in html
    assert policy.config_hash in html
    assert "YELLOW" in html
    assert "bin-58-59" in html
    assert "CLOSED" in html


def test_m10_live_mode_red_banner_circuit_open_and_empty_degraded_safety(tmp_path: Path) -> None:
    """LIVE red banner, OPEN circuit breaker detection from P3 trace, and empty PENDING_P9 safety."""
    from src.execution.clob_gateway import GatewayRiskPanelSnapshot
    from src.ui.m10_view import build_m10_dashboard_model, render_m10_dashboard_html

    cfg_path = _write_safety_yaml(tmp_path / "live_gw.yaml", tmp_path / "daily_live.json", mode="LIVE", max_single="25", max_daily="250")
    snapshot = GatewayRiskPanelSnapshot(
        execution_mode="LIVE",
        max_single_order_usd=Decimal("25"),
        max_daily_cumulative_usd=Decimal("250"),
        daily_used_usd=Decimal("50"),
        daily_remaining_usd=Decimal("200"),
        circuit_open=True,
        consecutive_failures=5,
        light_status="RED",
        model_hash="frozen-model-hash-v2",
        model_frozen=True,
        safety_config_sha256="abc123def456",
    )
    model = build_m10_dashboard_model(
        audit_root=tmp_path / "empty_m7",
        execution_mode="LIVE",
        safety_config_path=cfg_path,
        risk_panel_override=snapshot,
    )
    assert model.render_status == "NO_AUDIT_RECORDS"
    assert model.settlement_status == "PENDING_P9"

    html = render_m10_dashboard_html(model)
    _assert_strictly_readonly_html(html)
    assert "mode-banner-live" in html
    assert "LIVE" in html
    assert "OPEN" in html
    assert "RED" in html
    assert "NO_AUDIT_RECORDS" in html
    assert "PENDING_P9" in html
    assert "frozen-model-hash-v2" in html


def test_m10_ast_zero_database_zero_write_and_cli_render(tmp_path: Path) -> None:
    """Static AST verifies zero DB / writeback in `src/ui/` and CLI renders standalone HTML."""
    repo_root = Path(__file__).resolve().parents[3]
    ui_dir = repo_root / "src/ui"
    assert ui_dir.exists()
    for py_file in sorted(ui_dir.glob("*.py")):
        src_text = py_file.read_text(encoding="utf-8")
        tree = ast.parse(src_text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name not in ("sqlite3", "sqlalchemy", "psycopg", "py_clob_client")
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(("sqlite3", "sqlalchemy", "psycopg", "py_clob_client"))
        for bad_call in (".write(", ".unlink(", ".mkdir(", "open(..., \"w\")", "open(..., \"a\")"):
            assert bad_call not in src_text

    cfg_path = _write_safety_yaml(tmp_path / "gw.yaml", tmp_path / "usage.json", mode="PAPER")
    out_html = tmp_path / "m10_board.html"
    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/render_m10_dashboard.py"),
            "--audit-root",
            str(tmp_path / "missing_m7"),
            "--execution-mode",
            "PAPER",
            "--safety-config",
            str(cfg_path),
            "--output",
            str(out_html),
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    rendered = out_html.read_text(encoding="utf-8")
    _assert_strictly_readonly_html(rendered)
    assert "mode-banner-paper" in rendered


def _write_signed_stream(path: Path, records: list[dict]) -> None:
    from src.utils.causal_utils import compute_record_sha256

    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for rec in records:
        payload = dict(rec)
        payload["record_sha256"] = compute_record_sha256(payload)
        lines.append(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sample_p1(
    *,
    decision_id: str,
    session_id: str = "sess-q6",
    station_id: str = "KORD",
    target_date: str = "2026-11-23",
    target_type: str = "TMAX",
    market_id: str = "mkt-a",
    bin_id: str = "bin-58-59",
    forecast_id: str = "fc-ok-1",
) -> dict:
    return {
        "schema_version": "p1.v1",
        "decision_id": decision_id,
        "session_id": session_id,
        "execution_mode": "PAPER",
        "scan_clock": "PRICE_CLOCK",
        "scan_ts_utc": "2026-11-23T14:00:00+00:00",
        "station_id": station_id,
        "target_date": target_date,
        "target_type": target_type,
        "bin_id": bin_id,
        "token_id": f"tok-{market_id}",
        "market_id": market_id,
        "model_hash": "mh-q6",
        "config_hash": "ch-q6",
        "policy_version": "p6.v3",
        "policy_overdue": False,
        "forecast_id": forecast_id,
        "book_frame_ref": 1,
        "decision_outcome": "ORDERED",
    }


def _sample_p3_attempt(
    *,
    attempt_id: str,
    decision_id: str,
    session_id: str = "sess-q6",
    station_id: str = "KORD",
    market_id: str = "mkt-a",
    terminal_status: str,
    filled_shares: str,
    filled_usd: str,
    fee_paid_usd: str,
    final_ts_utc: str,
) -> dict:
    return {
        "schema_version": "p3.v1",
        "attempt_id": attempt_id,
        "decision_id": decision_id,
        "idempotency_key": f"idem-{attempt_id}",
        "session_id": session_id,
        "execution_mode": "PAPER",
        "station_id": station_id,
        "market_id": market_id,
        "token_id": f"tok-{market_id}",
        "model_hash": "mh-q6",
        "config_hash": "ch-q6",
        "submit_ts_utc": final_ts_utc,
        "final_ts_utc": final_ts_utc,
        "terminal_status": terminal_status,
        "filled_shares": filled_shares,
        "filled_usd": filled_usd,
        "fee_paid_usd": fee_paid_usd,
    }


def test_m10_single_decision_multiple_partial_p3_attempts_aggregated(tmp_path: Path) -> None:
    """1:N `P1 -> P3` multi-attempt re-slicing sums fills/fees without overwriting earlier attempts."""
    from src.ui.m10_view import build_m10_dashboard_model

    audit_root = tmp_path / "m7"
    day_dir = audit_root / "PAPER" / "2026-11-23"
    cfg_path = _write_safety_yaml(tmp_path / "gw.yaml", tmp_path / "usage.json", mode="PAPER")

    _write_signed_stream(
        day_dir / "p17_forecast_snapshots.jsonl",
        [{"schema_version": "p17.v1", "execution_mode": "PAPER", "session_id": "sess-q6", "station_id": "KORD", "forecast_id": "fc-ok-1", "model_hash": "mh-q6", "config_hash": "ch-q6"}],
    )
    _write_signed_stream(
        day_dir / "p1_scan_decisions.jsonl",
        [
            _sample_p1(decision_id="dec-reslice-filled", market_id="mkt-a", bin_id="bin-58-59"),
            _sample_p1(decision_id="dec-partial-cancel", market_id="mkt-b", bin_id="bin-60plus"),
        ],
    )
    _write_signed_stream(
        day_dir / "p3_execution_attempts.jsonl",
        [
            _sample_p3_attempt(
                attempt_id="att-1a",
                decision_id="dec-reslice-filled",
                market_id="mkt-a",
                terminal_status="PARTIAL",
                filled_shares="10.00",
                filled_usd="2.50",
                fee_paid_usd="0.01",
                final_ts_utc="2026-11-23T14:00:01+00:00",
            ),
            _sample_p3_attempt(
                attempt_id="att-1b",
                decision_id="dec-reslice-filled",
                market_id="mkt-a",
                terminal_status="FILLED",
                filled_shares="15.00",
                filled_usd="3.75",
                fee_paid_usd="0.02",
                final_ts_utc="2026-11-23T14:00:02+00:00",
            ),
            _sample_p3_attempt(
                attempt_id="att-2a",
                decision_id="dec-partial-cancel",
                market_id="mkt-b",
                terminal_status="PARTIAL",
                filled_shares="8.00",
                filled_usd="2.00",
                fee_paid_usd="0.01",
                final_ts_utc="2026-11-23T14:01:01+00:00",
            ),
            _sample_p3_attempt(
                attempt_id="att-2b",
                decision_id="dec-partial-cancel",
                market_id="mkt-b",
                terminal_status="CANCELLED_UNFILLED",
                filled_shares="0",
                filled_usd="0",
                fee_paid_usd="0",
                final_ts_utc="2026-11-23T14:01:02+00:00",
            ),
        ],
    )

    model = build_m10_dashboard_model(audit_root=audit_root, execution_mode="PAPER", safety_config_path=cfg_path)
    by_dec = {row["decision_id"]: row for row in model.decision_rows}
    assert by_dec["dec-reslice-filled"]["attempt_count"] == 2
    assert by_dec["dec-reslice-filled"]["filled_shares"] == Decimal("25.00")
    assert by_dec["dec-reslice-filled"]["filled_usd"] == Decimal("6.25")
    assert by_dec["dec-reslice-filled"]["fee_paid_usd"] == Decimal("0.03")
    assert by_dec["dec-reslice-filled"]["terminal_status"] == "FILLED"

    assert by_dec["dec-partial-cancel"]["attempt_count"] == 2
    assert by_dec["dec-partial-cancel"]["filled_shares"] == Decimal("8.00")
    assert by_dec["dec-partial-cancel"]["filled_usd"] == Decimal("2.00")
    assert by_dec["dec-partial-cancel"]["fee_paid_usd"] == Decimal("0.01")
    assert by_dec["dec-partial-cancel"]["terminal_status"] == "PARTIAL"

    assert model.total_filled_usd == Decimal("8.25")
    assert model.total_fee_paid_usd == Decimal("0.04")


def test_m10_multiple_p9_same_station_date_bound_by_market_session_type_no_double_count(tmp_path: Path) -> None:
    """Multiple `P9` rows on same `(station, target_date)` bind strictly by `settlement_id` scope without double counting."""
    from src.ui.m10_view import build_m10_dashboard_model

    audit_root = tmp_path / "m7"
    day_dir = audit_root / "PAPER" / "2026-11-23"
    settle_dir = audit_root / "PAPER" / "2026-11-24"
    cfg_path = _write_safety_yaml(tmp_path / "gw.yaml", tmp_path / "usage.json", mode="PAPER")

    _write_signed_stream(
        day_dir / "p17_forecast_snapshots.jsonl",
        [{"schema_version": "p17.v1", "execution_mode": "PAPER", "session_id": "sess-q6", "station_id": "KORD", "forecast_id": "fc-ok-1", "model_hash": "mh-q6", "config_hash": "ch-q6"}],
    )
    _write_signed_stream(
        day_dir / "p1_scan_decisions.jsonl",
        [
            _sample_p1(decision_id="dec-mkt-a", session_id="sess-q6", station_id="KORD", target_date="2026-11-23", target_type="TMAX", market_id="mkt-a", bin_id="bin-58-59"),
            _sample_p1(decision_id="dec-mkt-b", session_id="sess-q6", station_id="KORD", target_date="2026-11-23", target_type="TMIN", market_id="mkt-b", bin_id="bin-40-41"),
        ],
    )
    _write_signed_stream(
        day_dir / "p3_execution_attempts.jsonl",
        [
            _sample_p3_attempt(
                attempt_id="att-a",
                decision_id="dec-mkt-a",
                session_id="sess-q6",
                market_id="mkt-a",
                terminal_status="FILLED",
                filled_shares="20.00",
                filled_usd="5.00",
                fee_paid_usd="0.02",
                final_ts_utc="2026-11-23T14:00:01+00:00",
            ),
            _sample_p3_attempt(
                attempt_id="att-b",
                decision_id="dec-mkt-b",
                session_id="sess-q6",
                market_id="mkt-b",
                terminal_status="FILLED",
                filled_shares="10.00",
                filled_usd="4.00",
                fee_paid_usd="0.01",
                final_ts_utc="2026-11-23T14:00:02+00:00",
            ),
        ],
    )
    _write_signed_stream(
        settle_dir / "p9_settlement_truths.jsonl",
        [
            {
                "schema_version": "p9.v1",
                "settlement_id": "sid-tmax-mkt-a",
                "settled_ts_utc": "2026-11-24T06:10:00+00:00",
                "session_id": "sess-q6",
                "execution_mode": "PAPER",
                "station_id": "KORD",
                "target_date": "2026-11-23",
                "target_type": "TMAX",
                "market_id": "mkt-a",
                "winning_bin_id": "bin-58-59",
                "oracle_source": "AWC_ROUTINE_METAR",
                "oracle_source_tier": "AWC_METAR_TGROUP",
                "settled_temp_f_int": 59,
                "fallback_to_lowest_bin": False,
            },
            # Duplicate identical settlement_id row must be deduplicated cleanly
            {
                "schema_version": "p9.v1",
                "settlement_id": "sid-tmax-mkt-a",
                "settled_ts_utc": "2026-11-24T06:10:00+00:00",
                "session_id": "sess-q6",
                "execution_mode": "PAPER",
                "station_id": "KORD",
                "target_date": "2026-11-23",
                "target_type": "TMAX",
                "market_id": "mkt-a",
                "winning_bin_id": "bin-58-59",
                "oracle_source": "AWC_ROUTINE_METAR",
                "oracle_source_tier": "AWC_METAR_TGROUP",
                "settled_temp_f_int": 59,
                "fallback_to_lowest_bin": False,
            },
            {
                "schema_version": "p9.v1",
                "settlement_id": "sid-tmin-mkt-b",
                "settled_ts_utc": "2026-11-24T06:10:00+00:00",
                "session_id": "sess-q6",
                "execution_mode": "PAPER",
                "station_id": "KORD",
                "target_date": "2026-11-23",
                "target_type": "TMIN",
                "market_id": "mkt-b",
                "winning_bin_id": "bin-42-43",  # losing bin -> payout 0
                "oracle_source": "AWC_ROUTINE_METAR",
                "oracle_source_tier": "AWC_METAR_TGROUP",
                "settled_temp_f_int": 42,
                "fallback_to_lowest_bin": False,
            },
        ],
    )

    model = build_m10_dashboard_model(audit_root=audit_root, execution_mode="PAPER", safety_config_path=cfg_path)
    assert len(model.settlement_rows) == 2
    by_sid = {row["settlement_id"]: row for row in model.settlement_rows}
    # mkt-a: payout 20.00 - (5.00 + 0.02) = 14.98
    assert by_sid["sid-tmax-mkt-a"]["realized_pnl_usd"] == Decimal("14.98")
    # mkt-b: payout 0 - (4.00 + 0.01) = -4.01
    assert by_sid["sid-tmin-mkt-b"]["realized_pnl_usd"] == Decimal("-4.01")
    # Total = 14.98 + (-4.01) = 10.97 (zero cross-P9 double-counting)
    assert model.total_realized_pnl_usd == Decimal("10.97")


def test_m10_missing_forecast_fk_count_positive(tmp_path: Path) -> None:
    """Broken non-MISSING `forecast_id` increments `missing_forecast_fk_count`, while `MISSING*` sentinel is exempted."""
    from src.ui.m10_view import build_m10_dashboard_model, render_m10_dashboard_html

    audit_root = tmp_path / "m7"
    day_dir = audit_root / "PAPER" / "2026-11-23"
    cfg_path = _write_safety_yaml(tmp_path / "gw.yaml", tmp_path / "usage.json", mode="PAPER")

    _write_signed_stream(
        day_dir / "p1_scan_decisions.jsonl",
        [
            _sample_p1(decision_id="dec-fk-broken", forecast_id="fc-missing-p17"),
            _sample_p1(decision_id="dec-fk-sentinel", forecast_id="MISSING_FORECAST"),
        ],
    )

    model = build_m10_dashboard_model(audit_root=audit_root, execution_mode="PAPER", safety_config_path=cfg_path)
    assert model.render_status == "OK"
    assert model.missing_forecast_fk_count == 1
    html = render_m10_dashboard_html(model)
    _assert_strictly_readonly_html(html)
    assert "<div class=\"k\">missing_forecast_fk</div><div class=\"v\">1</div>" in html


def test_m10_decision_chain_cross_stream_join_distribution_and_p13_snapshot(tmp_path: Path) -> None:
    """Cross-stream join `P1 -> P17.bin_probs` + `P13` populates 6-stage card with selected bin highlight & LIVE slot."""
    from src.ui.m10_view import build_m10_dashboard_model, render_m10_dashboard_html

    audit_root = tmp_path / "m7"
    p13_root = tmp_path / "p13"
    day_dir = audit_root / "PAPER" / "2026-11-23"
    cfg_path = _write_safety_yaml(tmp_path / "gw.yaml", tmp_path / "usage.json", mode="PAPER")

    _write_signed_stream(
        day_dir / "p17_forecast_snapshots.jsonl",
        [
            {
                "schema_version": "p17.v1",
                "execution_mode": "PAPER",
                "session_id": "sess-q6",
                "station_id": "KORD",
                "forecast_id": "fc-ok-1",
                "issue_ts_utc": "2026-11-23T13:50:00+00:00",
                "gefs_lead_hours": 24,
                "tau_hours": 16.0,
                "model_hash": "mh-q6",
                "config_hash": "ch-q6",
                "prior_mu0": 58.4,
                "prior_sigma0": 1.8,
                "family": "normal",
                "m_now_f": 56.3,
                "m_now_int_f": 56,
                "oracle_compliant": True,
                "upstream_obs_fresh": True,
                "is_bridge_active": True,
                "bin_probs": [
                    {"bin_id": "bin-57below", "label": "<=57°F", "p_model": 0.12, "is_dead_bin": True, "is_boundary_bin": False},
                    {"bin_id": "bin-58-59", "label": "58-59°F", "p_model": 0.54, "is_dead_bin": False, "is_boundary_bin": True},
                    {"bin_id": "bin-60plus", "label": ">=60°F", "p_model": 0.34, "is_dead_bin": False, "is_boundary_bin": False},
                ],
            }
        ],
    )
    _write_signed_stream(
        day_dir / "p1_scan_decisions.jsonl",
        [_sample_p1(decision_id="dec-chain-1", market_id="mkt-a", bin_id="bin-58-59", forecast_id="fc-ok-1")],
    )
    _write_signed_stream(
        p13_root / "PASSIVE_RECORD" / "2026-11-23" / "sess-q6" / "p13_book_stream_KORD.jsonl",
        [
            {
                "schema_version": "p13.v1",
                "session_id": "sess-q6",
                "payload": {
                    "token_id": "tok-mkt-a",
                    "frame_seq": 1,
                    "data_source": "CLOB_WS",
                    "single_side": None,
                    "best_bid": 0.24,
                    "fee_rate": 0.01,
                    "min_order_size_shares": 5.0,
                    "asks": [[0.25, 120.0], [0.26, 80.0]],
                    "bids": [[0.24, 90.0]],
                },
            }
        ],
    )

    model = build_m10_dashboard_model(
        audit_root=audit_root, execution_mode="PAPER", safety_config_path=cfg_path, p13_root=p13_root
    )
    row = model.decision_rows[0]
    assert row["forecast_fk_present"] is True
    assert row["p13_ref_present"] is True
    assert len(row["distribution_bins"]) == 3
    selected = [b for b in row["distribution_bins"] if b["is_selected"]]
    assert len(selected) == 1 and selected[0]["bin_id"] == "bin-58-59"
    assert row["prob_edge_stage"]["selected_bin_p_model"] == 0.54
    assert row["p13_book_stage"]["asks_top3"] == ([0.25, 120.0], [0.26, 80.0])

    html = render_m10_dashboard_html(model)
    _assert_strictly_readonly_html(html)
    assert '<details class="chain-card" open>' in html
    assert "bin-row bin-picked" in html
    assert "58-59°F [★选中 · BOUNDARY]" in html
    assert "54.00%" in html
    assert "0.25×120.0" in html
    assert "reserved-live-slot" in html
    assert "待 S3-15 LIVE 轨启用" in html


def test_m10_unpersisted_fields_render_fail_honest_placeholder_and_autofill_when_present(tmp_path: Path) -> None:
    """Unpersisted Batch-1 fields render `未落盘` fail-honestly, and auto-populate without branching when persisted."""
    from src.ui.m10_view import build_m10_dashboard_model, render_m10_dashboard_html

    cfg_path = _write_safety_yaml(tmp_path / "gw.yaml", tmp_path / "usage.json", mode="PAPER")

    # (a) v1 records missing Batch-1 fields -> fail-honest "未落盘"
    audit_v1 = tmp_path / "m7_v1"
    day_v1 = audit_v1 / "PAPER" / "2026-11-23"
    _write_signed_stream(
        day_v1 / "p17_forecast_snapshots.jsonl",
        [{"schema_version": "p17.v1", "execution_mode": "PAPER", "session_id": "sess-q6", "station_id": "KORD", "forecast_id": "fc-ok-1", "model_hash": "mh-q6", "config_hash": "ch-q6"}],
    )
    _write_signed_stream(day_v1 / "p1_scan_decisions.jsonl", [_sample_p1(decision_id="dec-v1")])

    html_v1 = render_m10_dashboard_html(
        build_m10_dashboard_model(audit_root=audit_v1, execution_mode="PAPER", safety_config_path=cfg_path)
    )
    _assert_strictly_readonly_html(html_v1)
    assert "瞬时观测温: 未落盘" in html_v1
    assert "I值 (net_ev / i_value)=未落盘" in html_v1
    assert "λ(L)=未落盘" in html_v1
    assert "b_eff_headroom=$未落盘" in html_v1
    assert "pov_cap=$未落盘" in html_v1
    assert "reject_reason=未落盘" in html_v1

    # (b) v2 records WITH Batch-1 fields persisted -> same renderer populates values cleanly
    audit_v2 = tmp_path / "m7_v2"
    day_v2 = audit_v2 / "PAPER" / "2026-11-23"
    _write_signed_stream(
        day_v2 / "p17_forecast_snapshots.jsonl",
        [
            {
                "schema_version": "p17.v2",
                "execution_mode": "PAPER",
                "session_id": "sess-q6",
                "station_id": "KORD",
                "forecast_id": "fc-ok-1",
                "model_hash": "mh-q6",
                "config_hash": "ch-q6",
                "latest_obs_temp_f": 57.2,
                "latest_obs_ts_utc": "2026-11-23T13:55:00+00:00",
                "obs_source_mode": "AWC_ROUTINE_METAR",
            }
        ],
    )
    p1_v2 = _sample_p1(decision_id="dec-v2")
    p1_v2.update(
        {
            "schema_version": "p1.v2",
            "selected_bin_p_model": 0.35,
            "best_ask_price": 0.25,
            "applied_fee_rate": 0.01,
            "best_ask_q_eff": 0.251875,
            "best_ask_net_ev": 0.098125,
            "best_ask_edge": 0.389578,
            "m_threshold": 0.01,
            "lambda_l": 0.5,
            "b_eff_headroom_usd": "20.0",
            "pov_cap_usd": "18.5",
            "gateway_reject_reason": "NONE",
        }
    )
    _write_signed_stream(day_v2 / "p1_scan_decisions.jsonl", [p1_v2])

    html_v2 = render_m10_dashboard_html(
        build_m10_dashboard_model(audit_root=audit_v2, execution_mode="PAPER", safety_config_path=cfg_path)
    )
    _assert_strictly_readonly_html(html_v2)
    assert "瞬时观测温: 57.2 °F" in html_v2
    assert "I值 (net_ev / i_value)=0.098125" in html_v2
    assert "q_eff=0.251875" in html_v2
    assert "λ(L)=0.5" in html_v2
    assert "b_eff_headroom=$20.0" in html_v2
    assert "pov_cap=$18.5" in html_v2


def test_m10_three_stage_sizing_deltas_exact_decimal_with_1n_reslice(tmp_path: Path) -> None:
    """Three-stage deltas (`G->D`, `D->target_slice`, `target_slice->sum(filled)`) prevent 1:N `target_usd` doubling."""
    from src.ui.m10_view import build_m10_dashboard_model, render_m10_dashboard_html

    audit_root = tmp_path / "m7"
    day_dir = audit_root / "PAPER" / "2026-11-23"
    cfg_path = _write_safety_yaml(tmp_path / "gw.yaml", tmp_path / "usage.json", mode="PAPER")

    p1_sized = _sample_p1(decision_id="dec-3stage")
    p1_sized.update(
        {
            "b_budget_usd": 50.0,
            "w_tau": 0.8,
            "s_edge": 1.0,
            "g_cap_usd": 40.0,
            "held_usd": 15.0,
            "headroom_d": 25.0,
            "target_slice_usd": 10.0,
        }
    )
    _write_signed_stream(day_dir / "p1_scan_decisions.jsonl", [p1_sized])
    att_1 = _sample_p3_attempt(
        attempt_id="att-s1",
        decision_id="dec-3stage",
        terminal_status="PARTIAL",
        filled_shares="16.00",
        filled_usd="4.00",
        fee_paid_usd="0.02",
        final_ts_utc="2026-11-23T14:00:01+00:00",
    )
    att_1["target_usd"] = "10.0"
    att_2 = _sample_p3_attempt(
        attempt_id="att-s2",
        decision_id="dec-3stage",
        terminal_status="FILLED",
        filled_shares="22.00",
        filled_usd="5.50",
        fee_paid_usd="0.03",
        final_ts_utc="2026-11-23T14:00:02+00:00",
    )
    att_2["target_usd"] = "6.0"  # sum(target_usd)=16.0 must NOT replace P1.target_slice_usd=10.0
    _write_signed_stream(day_dir / "p3_execution_attempts.jsonl", [att_1, att_2])

    model = build_m10_dashboard_model(audit_root=audit_root, execution_mode="PAPER", safety_config_path=cfg_path)
    sz = model.decision_rows[0]["sizing_stage"]
    assert sz["delta_g_to_d"] == Decimal("15.0")
    assert sz["delta_d_to_slice"] == Decimal("15.0")
    assert sz["delta_slice_to_fill"] == Decimal("0.50")
    assert sz["filled_usd"] == Decimal("9.50")

    html = render_m10_dashboard_html(model)
    _assert_strictly_readonly_html(html)
    assert "Δ_G→D=$15.0" in html
    assert "Δ_D→slice=$15.0" in html
    assert "Δ_slice→fill=$0.50" in html


def test_m10_full_distribution_render_missing_p17_fallback_and_p9_card_link(tmp_path: Path) -> None:
    """Cards render P9 reconciliation link when settled and clean `未落盘` distribution fallback when P17 is absent."""
    from src.ui.m10_view import build_m10_dashboard_model, render_m10_dashboard_html

    audit_root = tmp_path / "m7"
    day_dir = audit_root / "PAPER" / "2026-11-23"
    settle_dir = audit_root / "PAPER" / "2026-11-24"
    cfg_path = _write_safety_yaml(tmp_path / "gw.yaml", tmp_path / "usage.json", mode="PAPER")

    _write_signed_stream(
        day_dir / "p1_scan_decisions.jsonl",
        [_sample_p1(decision_id="dec-no-p17", market_id="mkt-a", bin_id="bin-58-59", forecast_id="fc-lost")],
    )
    _write_signed_stream(
        day_dir / "p3_execution_attempts.jsonl",
        [
            _sample_p3_attempt(
                attempt_id="att-p9",
                decision_id="dec-no-p17",
                market_id="mkt-a",
                terminal_status="FILLED",
                filled_shares="20.00",
                filled_usd="5.00",
                fee_paid_usd="0.02",
                final_ts_utc="2026-11-23T14:00:01+00:00",
            )
        ],
    )
    _write_signed_stream(
        settle_dir / "p9_settlement_truths.jsonl",
        [
            {
                "schema_version": "p9.v1",
                "settlement_id": "sid-card-p9",
                "settled_ts_utc": "2026-11-24T06:10:00+00:00",
                "session_id": "sess-q6",
                "execution_mode": "PAPER",
                "station_id": "KORD",
                "target_date": "2026-11-23",
                "target_type": "TMAX",
                "market_id": "mkt-a",
                "winning_bin_id": "bin-58-59",
                "oracle_source": "AWC_ROUTINE_METAR",
                "oracle_source_tier": "AWC_METAR_TGROUP",
                "settled_temp_f_int": 59,
                "fallback_to_lowest_bin": False,
            }
        ],
    )

    model = build_m10_dashboard_model(audit_root=audit_root, execution_mode="PAPER", safety_config_path=cfg_path)
    assert model.missing_forecast_fk_count == 1
    assert model.decision_rows[0]["distribution_bins"] == ()
    html = render_m10_dashboard_html(model)
    _assert_strictly_readonly_html(html)
    assert "未落盘 (P17.bin_probs 缺失)" in html
    assert "sid-card-p9" in html
    assert "realized_pnl=$14.98" in html
