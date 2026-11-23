"""TDD tests and automated S3-14 acceptance gates (Preflight, E2E PAPER, Faults, UTC Rollover, P3/P14)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from src.audit.audit_logger import AsyncAuditLogger
from src.audit.p10_reader import P10Query, query_p10_session_view, read_verified_jsonl_file
from src.bankroll.manager import BankrollAccountManager
from src.bankroll.models import BankrollConfig
from src.decision.engine import (
    DeterministicDecider,
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


def _write_trial_safety_yaml(path: Path, ledger_path: Path, *, max_single: str = "25", max_daily: str = "250") -> Path:
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
                "backoff_base_sec: 0.001",
                "backoff_max_sec: 0.005",
                "backoff_jitter_ratio: 0.1",
                "circuit_breaker_failure_threshold: 5",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _make_trial_bankroll(logger: AsyncAuditLogger, *, pool: str = "2000.00") -> BankrollAccountManager:
    cfg = BankrollConfig(
        session_id="sess-s314-test",
        execution_mode="PAPER",
        policy_version="p6.v2",
        config_hash="s314-test-hash",
        initial_pool_usd=Decimal(pool),
        full_deployment=False,
    )
    return BankrollAccountManager(cfg, audit_logger=logger)


def _make_trial_policy_bundle(as_of: datetime):
    return build_execution_policy_bundle(
        policy_version="p6.v2",
        signed_at_utc=as_of - timedelta(hours=1),
        is_overdue=False,
        w0_intent=0.10,
        min_order_usd_eff=2.0,
        p=1.5,
        tau_max_h=24.0,
        station_cap_usd=60.0,
        concurrent_days=2,
        w_provenance="TEST_S314",
        phi_policy=PhiPolicy(
            rho_0=Decimal("0.40"),
            k_slope=Decimal("0.0"),
            rho_min=Decimal("0.20"),
            rho_max=Decimal("0.60"),
        ),
        k0_threshold_coef=1.0,
        sigma_delta_frozen=SigmaDeltaFrozen(0.01, "TEST", "cyc-s314"),
        friction_median=0.005,
        m_floor=0.01,
        yellow_multiplier=0.5,
    )


def test_preflight_checks_locked_sdk_paper_fail_closed_and_readonly_allowance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Preflight verifies SDK 0.34.6, fail-closed PAPER mode, YAML ledger path, logger, and read-only allowance RPC."""
    from src.execution.trial_runner import run_preflight_checks

    monkeypatch.delenv("POLY_CLOB_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("POLY_CLOB_API_KEY", raising=False)

    ledger_path = tmp_path / "daily_usage.json"
    cfg_path = _write_trial_safety_yaml(tmp_path / "clob_gateway.yaml", ledger_path)

    rpc_methods: list[dict[str, object]] = []

    def rpc_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        rpc_methods.append(body)
        # Expect eth_call to ERC20 allowance(address,address) selector 0xdd62ed3e (zero Approve tx)
        if body.get("method") == "eth_call":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": hex(125_000_000)})
        return httpx.Response(400, json={"error": "unexpected_rpc_method"})

    def gamma_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json=[{"id": "gamma-mkt-1", "enableOrderBook": True, "orderPriceMinTickSize": 0.01}])

    with AsyncAuditLogger(tmp_path / "m7", execution_mode="PAPER") as audit_logger:
        report = run_preflight_checks(
            safety_config_path=cfg_path,
            audit_logger=audit_logger,
            rpc_url="https://polygon-rpc.example",
            owner_address="0x000000000000000000000000000000000000dEaD",
            spender_address="0x4bFb4155B35707903C39A5A4D8dA6b8B8982E54d",
            token_contract="0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
            rpc_transport=httpx.MockTransport(rpc_handler),
            gamma_url="https://gamma-api.polymarket.com/markets?limit=1",
            gamma_transport=httpx.MockTransport(gamma_handler),
        )

    assert report.ok is True
    assert report.sdk_version == "0.34.6"
    assert report.execution_mode == "PAPER"
    assert report.credentials_fail_closed is True
    assert report.yaml_complete is True
    assert report.audit_logger_online is True
    assert report.allowance_probe.status == "OK_READONLY"
    assert report.allowance_probe.raw_allowance_units == 125_000_000
    assert report.gamma_probe.status == "OK_READONLY"
    assert report.gamma_probe.markets_sampled == 1
    assert len(rpc_methods) == 1
    assert rpc_methods[0]["method"] == "eth_call"
    call_data = rpc_methods[0]["params"][0]["data"]  # type: ignore[index]
    assert str(call_data).startswith("0xdd62ed3e")
    # Static guardrail: zero Approve tx selector (0x095ea7b3) or eth_sendRawTransaction in src/execution/
    exec_src = "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted((Path(__file__).resolve().parents[3] / "src/execution").glob("*.py"))
    )
    assert "0x095ea7b3" not in exec_src
    assert "eth_sendRawTransaction" not in exec_src


def test_s314_gate1_e2e_paper_pipeline_four_statuses_and_ten_orders(tmp_path: Path) -> None:
    """Gate ①: M4->M5(PAPER)->M6->M7 produces >=10 orders covering FILLED, PARTIAL, REJECTED, TIMEOUT."""
    from src.execution.trial_runner import PaperMockClobExchange, PaperOrderScenario, TrialRunner

    t0 = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)
    ledger_path = tmp_path / "daily_usage.json"
    cfg_path = _write_trial_safety_yaml(tmp_path / "clob_gateway.yaml", ledger_path)
    audit_root = tmp_path / "m7"

    statuses = [
        "FILLED",
        "PARTIAL",
        "REJECTED",
        "TIMEOUT",
        "FILLED",
        "PARTIAL",
        "FILLED",
        "REJECTED",
        "TIMEOUT",
        "FILLED",
        "PARTIAL",
        "FILLED",
    ]
    exchange = PaperMockClobExchange(fee_rate_bps=100)  # 1.00% simulated fee
    with AsyncAuditLogger(audit_root, execution_mode="PAPER") as logger:
        bankroll = _make_trial_bankroll(logger)
        gateway = ClobOrderGateway(
            safety_config_path=cfg_path,
            audit_logger=logger,
            credentials_path=tmp_path / "missing_creds.yaml",
        )
        assert gateway.effective_mode == "PAPER"
        assert gateway.live_transport_enabled is False

        runner = TrialRunner(
            session_id="sess-gate1",
            decider=DeterministicDecider(exec_config=default_stub_trading_config()),
            gateway=gateway,
            bankroll=bankroll,
            audit_logger=logger,
            exchange=exchange,
            policy_bundle=_make_trial_policy_bundle(t0),
        )
        fc = build_stub_forecast_v11(
            target_date_str="2026-11-23",
            issue_ts_utc=t0 - timedelta(minutes=10),
            settle_close_utc=t0 + timedelta(hours=10),
        )
        results = []
        for idx, outcome_kind in enumerate(statuses):
            ts = t0 + timedelta(seconds=idx * 5)
            yes_frame = build_p4_v11_stub_envelope(
                session_id="sess-gate1",
                seq_id=idx + 1,
                frame_seq=idx + 1,
                token_id="tok-y-1",
                market_id=f"mkt-{idx}",
                condition_id="cond-1",
                station_id="KORD",
                target_date="2026-11-23",
                bin_label="58-59°F",
                outcome="YES",
                regime="two_sided",
                recv_ts_utc=ts - timedelta(seconds=1),
                asks=((0.25, 200.0), (0.28, 200.0)),
                bids=((0.24, 200.0),),
            )[0].payload
            exchange.queue_scenario(PaperOrderScenario(mode=outcome_kind))  # type: ignore[arg-type]
            res = runner.step_bin(
                scan_ts_utc=ts,
                station_id="KORD",
                target_date="2026-11-23",
                bin_id="bin-58-59",
                market_id=f"mkt-{idx}",
                yes_token_id="tok-y-1",
                forecasts=[fc],
                yes_frame=yes_frame,
                tick_size=Decimal("0.01"),
                neg_risk=True,
                exec_config=default_stub_trading_config(),
            )
            results.append(res)
        logger.flush()

    assert len(results) == 12 >= 10
    seen_statuses = {r.attempt_log.terminal_status for r in results}
    assert seen_statuses == {"FILLED", "PARTIAL", "REJECTED", "CANCELLED_UNFILLED"}
    # Both REJECTED and TIMEOUT (terminal CANCELLED_UNFILLED with TIMEOUT reason) were exercised
    timeout_logs = [r for r in results if "TIMEOUT" in (r.attempt_log.reject_or_abort_reason or "")]
    assert len(timeout_logs) == 2

    snap = bankroll.snapshot_state()
    assert snap.fee_paid_total_usd > Decimal("0")
    assert snap.conservation_residual_usd == Decimal("0")
    assert snap.active_locked_usd == Decimal("0")


def test_s314_gate2_fault_injection_recovers_zero_duplicates(tmp_path: Path) -> None:
    """Gate ②: disconnect, timeout, and delayed_callback faults auto-recover with zero duplicate orders."""
    from src.execution.trial_runner import PaperMockClobExchange, PaperOrderScenario, TrialRunner

    t0 = datetime(2026, 11, 23, 13, 0, 0, tzinfo=timezone.utc)
    cfg_path = _write_trial_safety_yaml(tmp_path / "clob_gateway.yaml", tmp_path / "daily_usage.json")
    exchange = PaperMockClobExchange(fee_rate_bps=50)

    with AsyncAuditLogger(tmp_path / "m7", execution_mode="PAPER") as logger:
        bankroll = _make_trial_bankroll(logger)
        gateway = ClobOrderGateway(
            safety_config_path=cfg_path,
            audit_logger=logger,
            credentials_path=tmp_path / "missing_creds.yaml",
            sleep_fn=lambda _sec: None,
        )
        runner = TrialRunner(
            session_id="sess-gate2",
            decider=DeterministicDecider(exec_config=default_stub_trading_config()),
            gateway=gateway,
            bankroll=bankroll,
            audit_logger=logger,
            exchange=exchange,
            policy_bundle=_make_trial_policy_bundle(t0),
        )
        fc = build_stub_forecast_v11(
            target_date_str="2026-11-23",
            issue_ts_utc=t0 - timedelta(minutes=10),
            settle_close_utc=t0 + timedelta(hours=10),
        )
        yes_frame = build_p4_v11_stub_envelope(
            session_id="sess-gate2",
            seq_id=1,
            frame_seq=1,
            token_id="tok-y-2",
            market_id="mkt-f",
            condition_id="cond-f",
            station_id="KORD",
            target_date="2026-11-23",
            bin_label="58-59°F",
            outcome="YES",
            regime="two_sided",
            recv_ts_utc=t0 - timedelta(seconds=1),
            asks=((0.25, 200.0),),
            bids=((0.24, 200.0),),
        )[0].payload

        faults = ["DISCONNECT", "TIMEOUT_RECOVER", "DELAYED_CALLBACK"]
        results = []
        for idx, fault_kind in enumerate(faults):
            exchange.queue_scenario(PaperOrderScenario(mode=fault_kind))  # type: ignore[arg-type]
            results.append(
                runner.step_bin(
                    scan_ts_utc=t0 + timedelta(seconds=idx),
                    station_id="KORD",
                    target_date="2026-11-23",
                    bin_id="bin-58-59",
                    market_id=f"mkt-f-{idx}",
                    yes_token_id="tok-y-2",
                    forecasts=[fc],
                    yes_frame=yes_frame,
                    tick_size=Decimal("0.01"),
                    neg_risk=True,
                    exec_config=default_stub_trading_config(),
                )
            )
        logger.flush()

    assert [r.attempt_log.terminal_status for r in results] == ["FILLED", "FILLED", "FILLED"]
    assert len(exchange.committed_orders) == 3
    assert len({o.client_order_id for o in exchange.committed_orders.values()}) == 3
    assert bankroll.snapshot_state().conservation_residual_usd == Decimal("0")


def test_s314_gate3_utc_rollover_and_restart_persists_daily_cap(tmp_path: Path) -> None:
    """Gate ③: restart preserves UTC same-day cumulative spend; midnight UTC rollover resets quota."""
    from src.execution.trial_runner import PaperMockClobExchange, PaperOrderScenario, TrialRunner

    day1 = datetime(2026, 11, 23, 23, 50, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 11, 24, 0, 5, 0, tzinfo=timezone.utc)
    ledger_path = tmp_path / "daily_usage.json"
    cfg_path = _write_trial_safety_yaml(tmp_path / "clob_gateway.yaml", ledger_path, max_single="20", max_daily="20")
    exchange = PaperMockClobExchange(fee_rate_bps=0)

    fc = build_stub_forecast_v11(
        target_date_str="2026-11-23",
        issue_ts_utc=day1 - timedelta(minutes=10),
        settle_close_utc=day1 + timedelta(hours=10),
    )
    yes_frame_day1 = build_p4_v11_stub_envelope(
        session_id="sess-gate3",
        seq_id=1,
        frame_seq=1,
        token_id="tok-y-3",
        market_id="mkt-r",
        condition_id="cond-r",
        station_id="KORD",
        target_date="2026-11-23",
        bin_label="58-59°F",
        outcome="YES",
        regime="two_sided",
        recv_ts_utc=day1 - timedelta(seconds=1),
        asks=((0.25, 200.0),),
        bids=((0.24, 200.0),),
    )[0].payload

    # Instance 1 fills ~$10 on day1 before simulated process restart
    with AsyncAuditLogger(tmp_path / "m7", execution_mode="PAPER") as logger1:
        b1 = _make_trial_bankroll(logger1)
        g1 = ClobOrderGateway(safety_config_path=cfg_path, audit_logger=logger1)
        r1 = TrialRunner(
            session_id="sess-g3-a",
            decider=DeterministicDecider(exec_config=default_stub_trading_config()),
            gateway=g1,
            bankroll=b1,
            audit_logger=logger1,
            exchange=exchange,
            policy_bundle=_make_trial_policy_bundle(day1),
        )
        exchange.queue_scenario(PaperOrderScenario(mode="FILLED"))
        out1 = r1.step_bin(
            scan_ts_utc=day1,
            station_id="KORD",
            target_date="2026-11-23",
            bin_id="bin-58-59",
            market_id="mkt-r1",
            yes_token_id="tok-y-3",
            forecasts=[fc],
            yes_frame=yes_frame_day1,
            tick_size=Decimal("0.01"),
            neg_risk=True,
            exec_config=default_stub_trading_config(),
        )
        logger1.flush()
    assert out1.attempt_log.terminal_status == "FILLED"
    used_day1 = g1.get_daily_used_usd(day1.date())
    assert used_day1 > Decimal("5")

    # Instance 2 (after process restart): loads ledger from YAML path, rejects another ~$10 > $15 cap on day1,
    # then allows full order after UTC midnight rollover on day2.
    fc_day2 = build_stub_forecast_v11(
        target_date_str="2026-11-24",
        issue_ts_utc=day2 - timedelta(minutes=10),
        settle_close_utc=day2 + timedelta(hours=10),
    )
    yes_frame_day2 = build_p4_v11_stub_envelope(
        session_id="sess-gate3",
        seq_id=2,
        frame_seq=2,
        token_id="tok-y-3",
        market_id="mkt-r",
        condition_id="cond-r",
        station_id="KORD",
        target_date="2026-11-24",
        bin_label="58-59°F",
        outcome="YES",
        regime="two_sided",
        recv_ts_utc=day2 - timedelta(seconds=1),
        asks=((0.25, 200.0),),
        bids=((0.24, 200.0),),
    )[0].payload

    with AsyncAuditLogger(tmp_path / "m7", execution_mode="PAPER") as logger2:
        b2 = _make_trial_bankroll(logger2)
        g2 = ClobOrderGateway(safety_config_path=cfg_path, audit_logger=logger2)
        assert g2.get_daily_used_usd(day1.date()) == used_day1
        r2 = TrialRunner(
            session_id="sess-g3-b",
            decider=DeterministicDecider(exec_config=default_stub_trading_config()),
            gateway=g2,
            bankroll=b2,
            audit_logger=logger2,
            exchange=exchange,
            policy_bundle=_make_trial_policy_bundle(day2),
        )
        out_day1_blocked = r2.step_bin(
            scan_ts_utc=day1 + timedelta(seconds=3),
            station_id="KORD",
            target_date="2026-11-23",
            bin_id="bin-58-59",
            market_id="mkt-r2",
            yes_token_id="tok-y-3",
            forecasts=[fc],
            yes_frame=yes_frame_day1,
            tick_size=Decimal("0.01"),
            neg_risk=True,
            exec_config=default_stub_trading_config(),
        )
        assert out_day1_blocked.attempt_log.terminal_status == "REJECTED"
        assert out_day1_blocked.attempt_log.reject_or_abort_reason == "SAFETY_GATE_DAILY_LIMIT_EXCEEDED"

        exchange.queue_scenario(PaperOrderScenario(mode="FILLED"))
        out_day2_ok = r2.step_bin(
            scan_ts_utc=day2,
            station_id="KORD",
            target_date="2026-11-24",
            bin_id="bin-58-59",
            market_id="mkt-r3",
            yes_token_id="tok-y-3",
            forecasts=[fc_day2],
            yes_frame=yes_frame_day2,
            tick_size=Decimal("0.01"),
            neg_risk=True,
            exec_config=default_stub_trading_config(),
        )
        logger2.flush()
    assert out_day2_ok.attempt_log.terminal_status == "FILLED"


def test_s314_gate4_p3_reconcile_zero_corrupt_and_cli_lifecycle(tmp_path: Path) -> None:
    """Gate ④ + 1.a/1.e: P3 zero corrupt lines, CLOB<->P3 1:1 reconcile, P14 drift==0, CLI start/status/stop."""
    from src.execution.trial_runner import PaperMockClobExchange, PaperOrderScenario, TrialRunner, reconcile_clob_and_p3

    t0 = datetime(2026, 11, 23, 14, 0, 0, tzinfo=timezone.utc)
    ledger_path = tmp_path / "daily_usage.json"
    cfg_path = _write_trial_safety_yaml(tmp_path / "clob_gateway.yaml", ledger_path)
    audit_root = tmp_path / "m7"
    exchange = PaperMockClobExchange(fee_rate_bps=75)

    with AsyncAuditLogger(audit_root, execution_mode="PAPER") as logger:
        bankroll = _make_trial_bankroll(logger)
        gateway = ClobOrderGateway(safety_config_path=cfg_path, audit_logger=logger)
        runner = TrialRunner(
            session_id="sess-gate4",
            decider=DeterministicDecider(exec_config=default_stub_trading_config()),
            gateway=gateway,
            bankroll=bankroll,
            audit_logger=logger,
            exchange=exchange,
            policy_bundle=_make_trial_policy_bundle(t0),
        )
        fc = build_stub_forecast_v11(
            target_date_str="2026-11-23",
            issue_ts_utc=t0 - timedelta(minutes=10),
            settle_close_utc=t0 + timedelta(hours=10),
        )
        yes_frame = build_p4_v11_stub_envelope(
            session_id="sess-gate4",
            seq_id=1,
            frame_seq=1,
            token_id="tok-y-4",
            market_id="mkt-rec",
            condition_id="cond-rec",
            station_id="KORD",
            target_date="2026-11-23",
            bin_label="58-59°F",
            outcome="YES",
            regime="two_sided",
            recv_ts_utc=t0 - timedelta(seconds=1),
            asks=((0.25, 200.0),),
            bids=((0.24, 200.0),),
        )[0].payload
        for idx, mode in enumerate(["FILLED", "PARTIAL", "REJECTED"]):
            exchange.queue_scenario(PaperOrderScenario(mode=mode))  # type: ignore[arg-type]
            runner.step_bin(
                scan_ts_utc=t0 + timedelta(seconds=idx),
                station_id="KORD",
                target_date="2026-11-23",
                bin_id="bin-58-59",
                market_id=f"mkt-rec-{idx}",
                yes_token_id="tok-y-4",
                forecasts=[fc],
                yes_frame=yes_frame,
                tick_size=Decimal("0.01"),
                neg_risk=True,
                exec_config=default_stub_trading_config(),
            )
        logger.flush()

    rec = reconcile_clob_and_p3(
        audit_root=audit_root,
        execution_mode="PAPER",
        utc_date=t0.date(),
        exchange=exchange,
        bankroll_snapshot=bankroll.snapshot_state(),
    )
    assert rec.ok is True
    assert rec.corrupt_p3_lines == 0
    assert rec.p3_attempt_count == 3
    assert rec.clob_order_count == 3
    assert rec.mismatched_attempts == ()
    assert rec.conservation_residual_usd == Decimal("0")

    view = query_p10_session_view(audit_root, P10Query(execution_mode="PAPER", date_range=(t0.date(), t0.date())))
    assert len(view.corrupt_lines) == 0
    assert len(view.p1_events) == 3

    # CLI lifecycle test: self-test, start, status, stop
    repo_root = Path(__file__).resolve().parents[3]
    state_dir = tmp_path / "runner_state"
    for cmd in (
        ["self-test", "--safety-config", str(cfg_path), "--state-dir", str(state_dir)],
        ["start", "--safety-config", str(cfg_path), "--state-dir", str(state_dir), "--once"],
        ["status", "--state-dir", str(state_dir)],
        ["stop", "--state-dir", str(state_dir)],
    ):
        proc = subprocess.run(
            [sys.executable, str(repo_root / "scripts/run_trial_runner.py"), *cmd],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"cmd={cmd} failed: {proc.stderr or proc.stdout}"
        payload = json.loads(proc.stdout)
        assert isinstance(payload, dict)
