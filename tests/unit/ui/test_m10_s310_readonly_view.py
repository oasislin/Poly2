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


def test_m10_city_date_nested_aggregation_multi_market_split_and_totals(tmp_path: Path) -> None:
    """City->Date two-level aggregation preserves M7 §2.7 market independence & exact totals equality."""
    from src.ui.m10_view import build_m10_dashboard_model, render_m10_dashboard_html

    audit_root = tmp_path / "m7"
    day1_dir = audit_root / "PAPER" / "2026-11-21"
    day2_dir = audit_root / "PAPER" / "2026-11-22"
    day3_dir = audit_root / "PAPER" / "2026-11-23"
    cfg_path = _write_safety_yaml(tmp_path / "gw.yaml", tmp_path / "usage.json", mode="PAPER")

    # KORD 2026-11-21: two independent markets on the same day (TMAX WIN, TMIN LOSS)
    p1_tmax = _sample_p1(decision_id="dec-tmax", market_id="mkt-tmax", bin_id="bin-58-59", target_date="2026-11-21")
    p1_tmin = _sample_p1(decision_id="dec-tmin", market_id="mkt-tmin", bin_id="bin-40-41", target_date="2026-11-21")
    p1_tmin["target_type"] = "TMIN"
    # KORD 2026-11-22: unfilled empty market (decision scanned, 0 fill)
    p1_empty = _sample_p1(decision_id="dec-empty", market_id="mkt-empty", bin_id="bin-60-61", target_date="2026-11-22")
    p1_empty["decision_outcome"] = "REJECT_CIRCUIT_OPEN"
    # KORD 2026-11-23: PENDING_P9 unsettled exposure
    p1_pend = _sample_p1(decision_id="dec-pend", market_id="mkt-pend", bin_id="bin-62-63", target_date="2026-11-23")
    # KLGA 2026-11-23: separate city PENDING_P9
    p1_klga = _sample_p1(decision_id="dec-klga", market_id="mkt-klga", bin_id="bin-54-55", target_date="2026-11-23")
    p1_klga["station_id"] = "KLGA"

    _write_signed_stream(day1_dir / "p1_scan_decisions.jsonl", [p1_tmax, p1_tmin])
    _write_signed_stream(day2_dir / "p1_scan_decisions.jsonl", [p1_empty])
    _write_signed_stream(day3_dir / "p1_scan_decisions.jsonl", [p1_pend, p1_klga])

    att_tmax = _sample_p3_attempt(
        attempt_id="att-tmax",
        decision_id="dec-tmax",
        market_id="mkt-tmax",
        terminal_status="FILLED",
        filled_shares="20.00",
        filled_usd="5.00",
        fee_paid_usd="0.02",
        final_ts_utc="2026-11-21T14:00:01+00:00",
    )
    att_tmin = _sample_p3_attempt(
        attempt_id="att-tmin",
        decision_id="dec-tmin",
        market_id="mkt-tmin",
        terminal_status="FILLED",
        filled_shares="10.00",
        filled_usd="5.00",
        fee_paid_usd="0.02",
        final_ts_utc="2026-11-21T14:05:01+00:00",
    )
    att_tmin["target_type"] = "TMIN"
    att_pend = _sample_p3_attempt(
        attempt_id="att-pend",
        decision_id="dec-pend",
        market_id="mkt-pend",
        terminal_status="FILLED",
        filled_shares="12.00",
        filled_usd="6.00",
        fee_paid_usd="0.03",
        final_ts_utc="2026-11-23T14:00:01+00:00",
    )
    att_klga = _sample_p3_attempt(
        attempt_id="att-klga",
        decision_id="dec-klga",
        market_id="mkt-klga",
        terminal_status="FILLED",
        filled_shares="8.00",
        filled_usd="4.00",
        fee_paid_usd="0.02",
        final_ts_utc="2026-11-23T14:01:01+00:00",
    )
    att_klga["station_id"] = "KLGA"

    _write_signed_stream(day1_dir / "p3_execution_attempts.jsonl", [att_tmax, att_tmin])
    _write_signed_stream(day3_dir / "p3_execution_attempts.jsonl", [att_pend, att_klga])

    _write_signed_stream(
        day2_dir / "p9_settlement_truths.jsonl",
        [
            {
                "schema_version": "p9.v1",
                "settlement_id": "sid-tmax",
                "settled_ts_utc": "2026-11-22T06:00:00+00:00",
                "session_id": "sess-q6",
                "execution_mode": "PAPER",
                "station_id": "KORD",
                "target_date": "2026-11-21",
                "target_type": "TMAX",
                "market_id": "mkt-tmax",
                "winning_bin_id": "bin-58-59",
                "oracle_source": "AWC_ROUTINE_METAR",
                "oracle_source_tier": "AWC_METAR_TGROUP",
                "settled_temp_f_int": 59,
                "fallback_to_lowest_bin": False,
            },
            {
                "schema_version": "p9.v1",
                "settlement_id": "sid-tmin",
                "settled_ts_utc": "2026-11-22T06:05:00+00:00",
                "session_id": "sess-q6",
                "execution_mode": "PAPER",
                "station_id": "KORD",
                "target_date": "2026-11-21",
                "target_type": "TMIN",
                "market_id": "mkt-tmin",
                "winning_bin_id": "bin-42-43",
                "oracle_source": "AWC_ROUTINE_METAR",
                "oracle_source_tier": "AWC_METAR_TGROUP",
                "settled_temp_f_int": 42,
                "fallback_to_lowest_bin": False,
            },
        ],
    )

    model = build_m10_dashboard_model(audit_root=audit_root, execution_mode="PAPER", safety_config_path=cfg_path)
    by_city = {c["station_id"]: c for c in model.city_cards}
    assert set(by_city.keys()) == {"KLGA", "KORD"}

    kord = by_city["KORD"]
    kord_rows = kord["market_rows"]
    assert len(kord_rows) == 4  # 2026-11-21 TMAX, 2026-11-21 TMIN, 2026-11-22 empty, 2026-11-23 pending
    assert kord["total_invested_usd"] == sum((r["invested_usd"] for r in kord_rows), Decimal("0")) == Decimal("16.07")
    assert kord["total_realized_pnl_usd"] == sum(
        (r["realized_pnl_usd"] for r in kord_rows if r["realized_pnl_usd"] is not None),
        Decimal("0"),
    ) == Decimal("9.96")  # (+14.98) + (-5.02)
    assert kord["unsettled_exposure_usd"] == sum((r["unsettled_exposure_usd"] for r in kord_rows), Decimal("0")) == Decimal("6.03")
    assert kord["settled_count"] == 2
    assert kord["win_count"] == 1

    # Verify empty unfilled market row & same-day multi-market split flag
    row_by_mkt = {r["market_id"]: r for r in kord_rows}
    assert row_by_mkt["mkt-tmax"]["multi_market_same_day"] is True
    assert row_by_mkt["mkt-tmin"]["multi_market_same_day"] is True
    assert row_by_mkt["mkt-tmax"]["outcome"] == "WIN"
    assert row_by_mkt["mkt-tmin"]["outcome"] == "LOSS"
    assert row_by_mkt["mkt-empty"]["is_empty_market"] is True
    assert row_by_mkt["mkt-empty"]["invested_usd"] == Decimal("0")
    assert row_by_mkt["mkt-empty"]["unsettled_exposure_usd"] == Decimal("0")
    assert row_by_mkt["mkt-empty"]["outcome"] == "未成交"
    assert row_by_mkt["mkt-pend"]["settlement_status"] == "PENDING_P9"

    klga = by_city["KLGA"]
    assert klga["total_invested_usd"] == Decimal("4.02")
    assert klga["total_realized_pnl_usd"] == Decimal("0")
    assert klga["unsettled_exposure_usd"] == Decimal("4.02")
    assert klga["settled_count"] == 0
    assert klga["win_count"] == 0

    html = render_m10_dashboard_html(model)
    _assert_strictly_readonly_html(html)
    assert '<details class="city-card" open>' in html
    assert '<details class="market-day-card">' in html
    assert "空盘口（有决策未成交）" in html
    assert "同日多盘口独立核算" in html
    assert "未落盘" not in html or "未落盘 (P17.bin_probs 缺失)" in html  # placeholders intact when P17 absent
    # Domain invariant: city-level summaries only sum amounts/counts (never win-rate % or probability blend)
    city_sum_start = html.index('<details class="city-card" open><summary>')
    city_sum_end = html.index("</summary>", city_sum_start)
    assert "%" not in html[city_sum_start:city_sum_end]


def test_m10_svg_daily_cumulative_pnl_curve_omits_gap_days(tmp_path: Path) -> None:
    """SVG daily cumulative PnL curve aggregates by settlement day and omits gap days without synthesis."""
    from src.ui.m10_view import build_m10_dashboard_model, render_m10_dashboard_html

    audit_root = tmp_path / "m7"
    p1_dir = audit_root / "PAPER" / "2026-11-20"
    p9_dir_1 = audit_root / "PAPER" / "2026-11-21"
    p9_dir_2 = audit_root / "PAPER" / "2026-11-22"
    p9_dir_3 = audit_root / "PAPER" / "2026-11-24"
    cfg_path = _write_safety_yaml(tmp_path / "gw.yaml", tmp_path / "usage.json", mode="PAPER")

    p1s = [
        _sample_p1(decision_id="d1", market_id="m1", bin_id="b-win", target_date="2026-11-20"),
        _sample_p1(decision_id="d2", market_id="m2", bin_id="b-lose", target_date="2026-11-21"),
        _sample_p1(decision_id="d3", market_id="m3", bin_id="b-win3", target_date="2026-11-23"),
    ]
    _write_signed_stream(p1_dir / "p1_scan_decisions.jsonl", p1s)

    atts = [
        _sample_p3_attempt(
            attempt_id="a1",
            decision_id="d1",
            market_id="m1",
            terminal_status="FILLED",
            filled_shares="20.00",
            filled_usd="5.00",
            fee_paid_usd="0.02",
            final_ts_utc="2026-11-20T14:00:01+00:00",
        ),
        _sample_p3_attempt(
            attempt_id="a2",
            decision_id="d2",
            market_id="m2",
            terminal_status="FILLED",
            filled_shares="10.00",
            filled_usd="5.00",
            fee_paid_usd="0.02",
            final_ts_utc="2026-11-21T14:00:01+00:00",
        ),
        _sample_p3_attempt(
            attempt_id="a3",
            decision_id="d3",
            market_id="m3",
            terminal_status="FILLED",
            filled_shares="15.00",
            filled_usd="4.95",
            fee_paid_usd="0.05",
            final_ts_utc="2026-11-23T14:00:01+00:00",
        ),
    ]
    _write_signed_stream(p1_dir / "p3_execution_attempts.jsonl", atts)

    # Settlements on 2026-11-20, 2026-11-22 (gap 11-21), 2026-11-24 (gap 11-23)
    _write_signed_stream(
        p9_dir_1 / "p9_settlement_truths.jsonl",
        [
            {
                "schema_version": "p9.v1",
                "settlement_id": "sid-svg-1",
                "settled_ts_utc": "2026-11-20T22:00:00+00:00",
                "session_id": "sess-q6",
                "execution_mode": "PAPER",
                "station_id": "KORD",
                "target_date": "2026-11-20",
                "target_type": "TMAX",
                "market_id": "m1",
                "winning_bin_id": "b-win",
                "oracle_source": "AWC_ROUTINE_METAR",
                "oracle_source_tier": "AWC_METAR_TGROUP",
                "settled_temp_f_int": 59,
                "fallback_to_lowest_bin": False,
            }
        ],
    )
    _write_signed_stream(
        p9_dir_2 / "p9_settlement_truths.jsonl",
        [
            {
                "schema_version": "p9.v1",
                "settlement_id": "sid-svg-2",
                "settled_ts_utc": "2026-11-22T06:00:00+00:00",
                "session_id": "sess-q6",
                "execution_mode": "PAPER",
                "station_id": "KORD",
                "target_date": "2026-11-21",
                "target_type": "TMAX",
                "market_id": "m2",
                "winning_bin_id": "b-other",
                "oracle_source": "AWC_ROUTINE_METAR",
                "oracle_source_tier": "AWC_METAR_TGROUP",
                "settled_temp_f_int": 60,
                "fallback_to_lowest_bin": False,
            }
        ],
    )
    _write_signed_stream(
        p9_dir_3 / "p9_settlement_truths.jsonl",
        [
            {
                "schema_version": "p9.v1",
                "settlement_id": "sid-svg-3",
                "settled_ts_utc": "2026-11-24T06:00:00+00:00",
                "session_id": "sess-q6",
                "execution_mode": "PAPER",
                "station_id": "KORD",
                "target_date": "2026-11-23",
                "target_type": "TMAX",
                "market_id": "m3",
                "winning_bin_id": "b-win3",
                "oracle_source": "AWC_ROUTINE_METAR",
                "oracle_source_tier": "AWC_METAR_TGROUP",
                "settled_temp_f_int": 61,
                "fallback_to_lowest_bin": False,
            }
        ],
    )

    model = build_m10_dashboard_model(audit_root=audit_root, execution_mode="PAPER", safety_config_path=cfg_path)
    assert [(p["settlement_date"], p["cumulative_realized_pnl_usd"]) for p in model.daily_pnl_series] == [
        ("2026-11-20", Decimal("14.98")),
        ("2026-11-22", Decimal("9.96")),
        ("2026-11-24", Decimal("19.96")),
    ]

    html = render_m10_dashboard_html(model)
    _assert_strictly_readonly_html(html)
    svg_start = html.index('<svg class="pnl-svg"')
    svg_end = html.index("</svg>", svg_start) + len("</svg>")
    svg_block = html[svg_start:svg_end]
    assert "<polyline" in svg_block
    assert svg_block.count("<circle ") == 3
    assert 'data-settlement-date="2026-11-20"' in svg_block
    assert 'data-settlement-date="2026-11-22"' in svg_block
    assert 'data-settlement-date="2026-11-24"' in svg_block
    assert "2026-11-21" not in svg_block
    assert "2026-11-23" not in svg_block


def test_m10_svg_empty_settlements_renders_blank_placeholder(tmp_path: Path) -> None:
    """When zero settlements exist, cumulative PnL SVG renders no fake line."""
    from src.ui.m10_view import build_m10_dashboard_model, render_m10_dashboard_html

    audit_root = tmp_path / "m7"
    cfg_path = _write_safety_yaml(tmp_path / "gw.yaml", tmp_path / "usage.json", mode="PAPER")
    model = build_m10_dashboard_model(audit_root=audit_root, execution_mode="PAPER", safety_config_path=cfg_path)
    assert model.daily_pnl_series == ()
    assert model.city_cards == ()
    html = render_m10_dashboard_html(model)
    _assert_strictly_readonly_html(html)
    assert '<svg class="pnl-svg"' not in html
    assert "暂无已结算数据，按结算日累计盈亏 SVG 曲线如实留空" in html


def test_m10_svg_same_settlement_day_summation_and_negative_cumulative_pnl(tmp_path: Path) -> None:
    """Multiple P9 settlements on the same settlement day aggregate into one SVG dot & handle negative PnL."""
    from src.ui.m10_view import build_m10_dashboard_model, render_m10_dashboard_html

    audit_root = tmp_path / "m7"
    p1_dir = audit_root / "PAPER" / "2026-11-22"
    cfg_path = _write_safety_yaml(tmp_path / "gw.yaml", tmp_path / "usage.json", mode="PAPER")

    _write_signed_stream(
        p1_dir / "p1_scan_decisions.jsonl",
        [
            _sample_p1(decision_id="d-s1", market_id="m-s1", bin_id="b-lose", target_date="2026-11-21"),
            _sample_p1(decision_id="d-s2", market_id="m-s2", bin_id="b-lose", target_date="2026-11-21"),
        ],
    )
    _write_signed_stream(
        p1_dir / "p3_execution_attempts.jsonl",
        [
            _sample_p3_attempt(
                attempt_id="a-s1",
                decision_id="d-s1",
                market_id="m-s1",
                terminal_status="FILLED",
                filled_shares="10.00",
                filled_usd="5.00",
                fee_paid_usd="0.02",
                final_ts_utc="2026-11-21T14:00:01+00:00",
            ),
            _sample_p3_attempt(
                attempt_id="a-s2",
                decision_id="d-s2",
                market_id="m-s2",
                terminal_status="FILLED",
                filled_shares="8.00",
                filled_usd="4.00",
                fee_paid_usd="0.02",
                final_ts_utc="2026-11-21T14:05:01+00:00",
            ),
        ],
    )
    _write_signed_stream(
        p1_dir / "p9_settlement_truths.jsonl",
        [
            {
                "schema_version": "p9.v1",
                "settlement_id": "sid-same-1",
                "settled_ts_utc": "2026-11-22T06:00:00+00:00",
                "session_id": "sess-q6",
                "execution_mode": "PAPER",
                "station_id": "KORD",
                "target_date": "2026-11-21",
                "target_type": "TMAX",
                "market_id": "m-s1",
                "winning_bin_id": "b-other",
                "oracle_source": "AWC_ROUTINE_METAR",
                "oracle_source_tier": "AWC_METAR_TGROUP",
                "settled_temp_f_int": 60,
                "fallback_to_lowest_bin": False,
            },
            {
                "schema_version": "p9.v1",
                "settlement_id": "sid-same-2",
                "settled_ts_utc": "2026-11-22T06:05:00+00:00",
                "session_id": "sess-q6",
                "execution_mode": "PAPER",
                "station_id": "KORD",
                "target_date": "2026-11-21",
                "target_type": "TMAX",
                "market_id": "m-s2",
                "winning_bin_id": "b-other",
                "oracle_source": "AWC_ROUTINE_METAR",
                "oracle_source_tier": "AWC_METAR_TGROUP",
                "settled_temp_f_int": 60,
                "fallback_to_lowest_bin": False,
            },
        ],
    )

    model = build_m10_dashboard_model(audit_root=audit_root, execution_mode="PAPER", safety_config_path=cfg_path)
    assert len(model.daily_pnl_series) == 1
    assert model.daily_pnl_series[0]["settlement_date"] == "2026-11-22"
    assert model.daily_pnl_series[0]["daily_realized_pnl_usd"] == Decimal("-9.04")
    assert model.daily_pnl_series[0]["cumulative_realized_pnl_usd"] == Decimal("-9.04")
    html = render_m10_dashboard_html(model)
    _assert_strictly_readonly_html(html)
    assert 'data-settlement-date="2026-11-22"' in html
    assert 'data-cumulative-pnl="-9.04"' in html


def test_m10_p1_v2_p17_v2_autofill_and_v1_backward_compat(tmp_path: Path) -> None:
    """Mixed v1+v2 M7 streams parse cleanly; real M2 p17.v2 & M4 p1.v2 outputs auto-fill M10 placeholders."""
    from src.data_acquisition.settlement_metar_stream import FreshnessPolicy, StationDayState
    from src.decision.engine import QuotaSnapshot
    from src.prediction.dynamic_corrector import SpecV2BaselineMuRHook
    from src.prediction.forecast_distribution_engine import (
        ConstantEtaProvider,
        ForecastDistributionEngine,
        PriorAffineFamilyModel,
        build_integer_bin_ladder,
    )
    from src.ui.m10_view import build_m10_dashboard_model, render_m10_dashboard_html

    audit_root = tmp_path / "m7"
    day_v1 = audit_root / "PAPER" / "2026-11-22"
    day_v2 = audit_root / "PAPER" / "2026-11-23"
    cfg_path = _write_safety_yaml(tmp_path / "gw.yaml", tmp_path / "usage.json", mode="PAPER")

    # 1) Legacy v1 streams
    _write_signed_stream(
        day_v1 / "p17_forecast_snapshots.jsonl",
        [{"schema_version": "p17.v1", "execution_mode": "PAPER", "session_id": "sess-q6", "station_id": "KORD", "forecast_id": "fc-legacy", "model_hash": "mh-1", "config_hash": "ch-1"}],
    )
    p1_v1 = _sample_p1(decision_id="dec-legacy-v1", target_date="2026-11-22", forecast_id="fc-legacy")
    _write_signed_stream(day_v1 / "p1_scan_decisions.jsonl", [p1_v1])

    # 2) Real M2 (p17.v2) + Real M4 (p1.v2) producer outputs
    t0 = datetime(2026, 11, 23, 14, 0, 0, tzinfo=timezone.utc)
    obs_ts = t0 - timedelta(minutes=8)
    fc_engine = ForecastDistributionEngine(
        freshness_policy=FreshnessPolicy(
            physical_age_limit_sec=3600.0,
            dispatch_age_limit_sec=3600.0,
            provenance="TEST_EXEC3",
        ),
        eta_provider=ConstantEtaProvider(eta_s=0.35, provenance="TEST_EXEC3"),
        mu_r_hook=SpecV2BaselineMuRHook(),
    )
    ladder = build_integer_bin_ladder(first_interior_start_f=56, num_interior_bins=4, bin_width_f=2)
    p11_state = StationDayState(
        schema_version="p11.v1",
        state_id="st-exec3",
        as_of_ts_utc=t0 - timedelta(minutes=5),
        station_id="KORD",
        station_timezone="America/Chicago",
        target_date=date(2026, 11, 23),
        day_start_utc=datetime(2026, 11, 23, 6, 0, tzinfo=timezone.utc),
        settle_close_utc=t0 + timedelta(hours=10),
        m_now_exact_f=Decimal("58.4"),
        m_now_int_f=58,
        m_now_min_exact_f=Decimal("44.0"),
        m_now_min_int_f=44,
        oracle_compliant=True,
        oracle_source_tier="AWC_METAR_TGROUP",
        latest_obs_utc=obs_ts,
        latest_dispatch_ts_utc=obs_ts + timedelta(minutes=1),
        latest_instant_temp_f=Decimal("55.6"),
        physical_age_sec=480.0,
        dispatch_age_sec=420.0,
        dispatch_age_available=True,
        freshness_ok=True,
        freshness_policy_provenance="TEST_POLICY",
        routine_obs_count=10,
        cor_overwrites_count=0,
        specis_seen_count=0,
        gap_flags=(),
    )
    snap, _ = fc_engine.build_snapshot(
        station_id="KORD",
        target_date=date(2026, 11, 23),
        target_type="TMAX",
        issue_ts_utc=t0 - timedelta(minutes=5),
        settle_close_utc=t0 + timedelta(hours=10),
        gefs_lead_hours=18,
        model_hash="mh-v2",
        prior=PriorAffineFamilyModel(family="gaussian", mu0=60.0, sigma0=3.0),
        bins=ladder,
        p11_state=p11_state,
    )
    p17_obj = json.loads(snap.to_p17_json_line(session_id="sess-v2", execution_mode="PAPER", config_hash="ch-v2"))
    day_v2.mkdir(parents=True, exist_ok=True)
    with (day_v2 / "p17_forecast_snapshots.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(snap.to_p17_json_line(session_id="sess-v2", execution_mode="PAPER", config_hash="ch-v2") + "\n")

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
        w_provenance="TEST_EXEC3",
        phi_policy=PhiPolicy(rho_0=Decimal("0.40"), k_slope=Decimal("0"), rho_min=Decimal("0.20"), rho_max=Decimal("0.60")),
        k0_threshold_coef=1.0,
        sigma_delta_frozen=SigmaDeltaFrozen(0.01, "TEST", "cyc-exec3"),
        friction_median=0.005,
        m_floor=0.01,
        yellow_multiplier=0.5,
    )
    ask_yes, _ = build_p4_v11_stub_envelope(
        session_id="sess-v2",
        seq_id=1,
        frame_seq=1,
        token_id="tok-exec3",
        market_id="mkt-exec3",
        condition_id="c-exec3",
        station_id="KORD",
        target_date="2026-11-23",
        bin_label="58-59°F",
        outcome="YES",
        regime="ask_only",
        recv_ts_utc=t0 - timedelta(seconds=1),
        asks=((0.20, 100.0),),
        bids=(),
    )
    slot = P16SubscriptionSlot()
    slot.publish(LightLevelEvent("p16-y-exec3", "YELLOW", "YELLOW_DRIFT", t0 - timedelta(minutes=2), "KORD"))
    decider = DeterministicDecider(
        exec_config=default_stub_trading_config(),
        p16_slot=slot,
        fee_rate_fetcher=lambda _tok: {"base_fee": 1000},
    )
    target_bin_id = next(bp["bin_id"] for bp in p17_obj["bin_probs"] if bp["lower_int_f"] == 58)
    ev_v2 = decider.evaluate_bin(
        orig_session_id="sess-v2",
        execution_mode="PAPER",
        scan_clock="PRICE_CLOCK",
        scan_ts_utc=t0,
        station_id="KORD",
        target_date="2026-11-23",
        bin_id=target_bin_id,
        market_id="mkt-exec3",
        yes_token_id="tok-exec3",
        forecasts=[snap],
        policy_bundle=policy,
        quota=QuotaSnapshot(
            station_id="KORD",
            market_id="mkt-exec3",
            free_usd=1000.0,
            station_active_locked_usd=0.0,
            market_held_usd=0.0,
            station_cap_usd=60.0,
            station_realized_loss_usd=0.0,
            station_loss_gate_tripped=False,
            account_drawdown_brake_tripped=False,
            b_eff_headroom_usd=22.0,
        ),
        yes_frame=ask_yes.payload,
    )
    with (day_v2 / "p1_scan_decisions.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(ev_v2.to_json_line() + "\n")

    model = build_m10_dashboard_model(audit_root=audit_root, execution_mode="PAPER", safety_config_path=cfg_path)
    assert model.render_status == "OK"
    assert model.corrupt_count == 0
    assert len(model.decision_rows) == 2

    rows_by_id = {r["decision_id"]: r for r in model.decision_rows}
    r_v2 = rows_by_id[ev_v2.decision_id]
    assert r_v2["weather_stage"]["latest_obs_temp_f"] == pytest.approx(55.6)
    assert r_v2["weather_stage"]["obs_source_mode"] == "AWC_METAR_TGROUP"
    assert r_v2["prob_edge_stage"]["best_ask_net_ev"] == pytest.approx(ev_v2.net_ev)
    assert r_v2["prob_edge_stage"]["best_ask_q_eff"] == pytest.approx(ev_v2.q_eff)
    assert r_v2["prob_edge_stage"]["applied_fee_rate"] == pytest.approx(ev_v2.fee_rate_applied)
    assert r_v2["sizing_stage"]["lambda_l"] == pytest.approx(0.5)
    assert r_v2["sizing_stage"]["b_eff_headroom_usd"] == pytest.approx(22.0)
    assert r_v2["sizing_stage"]["pov_cap_usd"] == pytest.approx(ev_v2.pov_cap_usd)
    assert r_v2["sizing_stage"]["reject_reason"] == "NONE"

    html = render_m10_dashboard_html(model)
    _assert_strictly_readonly_html(html)
    assert "瞬时观测温: 55.6 °F" in html
    assert "源=AWC_METAR_TGROUP" in html
    assert "λ(L)=0.5" in html
    assert "b_eff_headroom=$22.0" in html
    assert f"pov_cap=${ev_v2.pov_cap_usd}" in html
    assert "瞬时观测温: 未落盘" in html  # legacy v1 row stays fail-honest alongside v2 row


def test_m10_readonly_watchdog_alerts_status_badge_integration(tmp_path: Path) -> None:
    cfg_path = _write_safety_yaml(tmp_path / "gw.yaml", tmp_path / "usage.json", mode="PAPER")
    alerts_json = tmp_path / "watchdog_status.json"
    alerts_json.write_text(
        json.dumps(
            {
                "schema_version": "watchdog.v1",
                "checked_ts_utc": "2026-11-25T00:10:00+00:00",
                "overall_severity": "WARN",
                "checks": {
                    "gap_rate": {"status": "OK"},
                    "corrupt_lines": {"status": "OK"},
                    "token_coverage": {"status": "WARN"},
                    "disk_watchdog": {"status": "OK"},
                },
            }
        ),
        encoding="utf-8",
    )
    out_html = tmp_path / "m10_with_alerts.html"
    repo_root = Path(__file__).resolve().parents[3]
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
            "--alerts-status",
            str(alerts_json),
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
    assert "watchdog_summary (read-only)" in rendered
    assert "token_coverage: WARN" in rendered
    assert "gap_rate: OK" in rendered


