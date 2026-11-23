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
