"""S3-11 Offline P13 Delayed-Replay Scheduler, EXEC4 Fee Probe Wiring, and p1.v3/p17.v3 Contract Tests."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from src.audit.p10_reader import P10Query, query_p10_session_view
from src.decision.engine import (
    PhiPolicy,
    QuotaQuery,
    QuotaSnapshot,
    SigmaDeltaFrozen,
    build_execution_policy_bundle,
)
from src.utils.causal_utils import verify_record_sha256_line
from src.decision.offline_scheduler import (
    OfflineScheduleTarget,
    OfflineSchedulerConfig,
    build_wired_decider,
    generate_synthetic_clock_ticks,
    run_s311_offline_schedule,
)
from src.execution.clob_gateway import DEFAULT_GATEWAY_CONFIG_PATH
from src.execution.stub_generator import (
    build_p4_v11_stub_envelope,
    build_stub_forecast_v11,
    default_stub_trading_config,
)
from src.prediction.forecast_distribution_engine import verify_p17_json_line
from src.ui.m10_view import build_m10_dashboard_model, render_m10_dashboard_html


def _sign_jsonl_record(payload: Dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "record_sha256"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    body["record_sha256"] = hashlib.sha256(canonical).hexdigest()
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sample_policy(t0: datetime):
    return build_execution_policy_bundle(
        policy_version="p6.s311.v1",
        signed_at_utc=t0 - timedelta(hours=1),
        is_overdue=False,
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
        sigma_delta_frozen=SigmaDeltaFrozen(0.02, "test", "cyc-s311"),
        friction_median=0.01,
        m_floor=0.02,
        yellow_multiplier=0.5,
    )


class _StaticQuotaProvider:
    def query_quota(self, query: QuotaQuery) -> QuotaSnapshot:
        return QuotaSnapshot(
            station_id=query.station_id,
            market_id=query.market_id,
            free_usd=1000.0,
            station_active_locked_usd=0.0,
            market_held_usd=0.0,
            station_cap_usd=500.0,
            station_realized_loss_usd=0.0,
            station_loss_gate_tripped=False,
            account_drawdown_brake_tripped=False,
            b_eff_headroom_usd=250.0,
            blocked_reason=None,
        )


def _sample_quota() -> _StaticQuotaProvider:
    return _StaticQuotaProvider()


def _write_p13_session(session_dir: Path, t0: datetime) -> None:
    """Write out-of-order P13 frames (seq 2 written before seq 1) to verify causal sorting."""
    session_dir.mkdir(parents=True, exist_ok=True)
    # Earlier frame at t0 (expensive ask -> SKIP), later frame at t0 + 60s (cheap ask -> ORDERED)
    env_early, _ = build_p4_v11_stub_envelope(
        session_id="rec-s311-test",
        seq_id=1,
        frame_seq=10,
        token_id="tok-y",
        market_id="mkt-1",
        condition_id="cond-1",
        station_id="KORD",
        target_date="2026-11-25",
        bin_label="58-59°F",
        outcome="YES",
        regime="ask_only",
        recv_ts_utc=t0,
        asks=((0.85, 100.0),),
        bids=(),
    )
    env_late, _ = build_p4_v11_stub_envelope(
        session_id="rec-s311-test",
        seq_id=2,
        frame_seq=20,
        token_id="tok-y",
        market_id="mkt-1",
        condition_id="cond-1",
        station_id="KORD",
        target_date="2026-11-25",
        bin_label="58-59°F",
        outcome="YES",
        regime="ask_only",
        recv_ts_utc=t0 + timedelta(seconds=60),
        asks=((0.25, 100.0), (0.28, 200.0)),
        bids=(),
    )
    p13_file = session_dir / "p13_book_stream_20261125.jsonl"
    p13_file.write_text(
        env_late.to_json_line() + "\n" + env_early.to_json_line() + "\n",
        encoding="utf-8",
    )


def test_s311_synthetic_clock_ticks_cadence_and_validation() -> None:
    t0 = datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)
    ticks = generate_synthetic_clock_ticks(t0, t0 + timedelta(seconds=150), cadence_sec=60.0)
    assert ticks == (
        t0,
        t0 + timedelta(seconds=60),
        t0 + timedelta(seconds=120),
    )
    with pytest.raises(ValueError, match="cadence_sec"):
        generate_synthetic_clock_ticks(t0, t0 + timedelta(seconds=60), cadence_sec=0.0)
    with pytest.raises(ValueError, match="end_utc"):
        generate_synthetic_clock_ticks(t0 + timedelta(seconds=10), t0, cadence_sec=10.0)


def test_s311_p13_delayed_replay_causal_ordering_and_v3_serialization(tmp_path: Path) -> None:
    t0 = datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)
    p13_dir = tmp_path / "p13_sess"
    audit_dir = tmp_path / "audit_out"
    _write_p13_session(p13_dir, t0)

    fc = build_stub_forecast_v11(
        target_date_str="2026-11-25",
        issue_ts_utc=t0 - timedelta(minutes=10),
        settle_close_utc=t0 + timedelta(hours=10),
    )
    target = OfflineScheduleTarget(
        station_id="KORD",
        target_date="2026-11-25",
        bin_id="bin-58-59",
        bin_label="58-59°F",
        market_id="mkt-1",
        yes_token_id="tok-y",
    )
    # With replay_delay_ms=15_000 (and default max_book_staleness_sec=30s):
    # - tick t0 + 10s => book_as_of = t0 - 5s  => no frame visible yet (book_frame_ref == 0)
    # - tick t0 + 30s => book_as_of = t0 + 15s => only seq=1 visible & fresh (frame_seq=10, ask=0.85 -> SKIP)
    # - tick t0 + 80s => book_as_of = t0 + 65s => seq=2 visible & fresh (frame_seq=20, ask=0.25 -> ORDERED)
    ticks = (
        t0 + timedelta(seconds=10),
        t0 + timedelta(seconds=30),
        t0 + timedelta(seconds=80),
    )
    cfg = OfflineSchedulerConfig(
        p13_session_dir=p13_dir,
        audit_output_root=audit_dir,
        orig_session_id="s311-replay-01",
        safety_config_path=DEFAULT_GATEWAY_CONFIG_PATH,
        replay_delay_ms=15_000,
    )
    summary = run_s311_offline_schedule(
        cfg,
        exec_config=default_stub_trading_config(),
        policy_bundle=_sample_policy(t0),
        forecasts=[fc],
        targets=[target],
        quota_provider=_sample_quota(),
        clock_ticks=ticks,
    )
    assert summary.ticks_executed == 3
    assert summary.decisions_logged == 3
    assert summary.p17_logged == 1
    assert summary.ordered_count == 1
    assert summary.p13_valid_frames == 2
    assert summary.p13_corrupt_lines == 0
    assert summary.probe_enabled is False
    assert summary.clob_host_wired == "https://clob.polymarket.com"
    assert summary.consumed_frame_seqs == (0, 10, 20)

    p1_files = sorted(audit_dir.rglob("p1_scan_decisions.jsonl"))
    p17_files = sorted(audit_dir.rglob("p17_forecast_snapshots.jsonl"))
    assert len(p1_files) == 1 and len(p17_files) == 1

    p1_lines = [ln for ln in p1_files[0].read_text(encoding="utf-8").splitlines() if ln.strip()]
    p17_lines = [ln for ln in p17_files[0].read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(p1_lines) == 3 and len(p17_lines) == 1
    for ln in p1_lines:
        assert verify_record_sha256_line(ln) is True
        obj = json.loads(ln)
        assert obj["schema_version"] == "p1.v3"
        assert obj["capture_replay_mode"] == "REPLAY_P13"
        assert obj["fee_rate_official_raw"] is None
    assert verify_p17_json_line(p17_lines[0]) is True
    p17_obj = json.loads(p17_lines[0])
    assert p17_obj["schema_version"] == "p17.v3"
    assert p17_obj["capture_replay_mode"] == "REPLAY_P13"


def test_s311_fee_probe_wiring_default_false_zero_http_and_true_mock_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    t0 = datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)
    p13_dir = tmp_path / "p13_sess"
    _write_p13_session(p13_dir, t0)
    fc = build_stub_forecast_v11(
        target_date_str="2026-11-25",
        issue_ts_utc=t0 - timedelta(minutes=10),
        settle_close_utc=t0 + timedelta(hours=10),
    )
    target = OfflineScheduleTarget(
        station_id="KORD",
        target_date="2026-11-25",
        bin_id="bin-58-59",
        bin_label="58-59°F",
        market_id="mkt-1",
        yes_token_id="tok-y",
    )

    calls: List[Tuple[str, float]] = []

    class _FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return b'{"base_fee": 1000}'

    class _FakeOpener:
        def open(self, req, timeout=0.5):
            calls.append((req.full_url, float(timeout)))
            return _FakeResp()

    monkeypatch.setattr("urllib.request.build_opener", lambda *_args, **_kwargs: _FakeOpener())

    # 1) Offline default enable_official_fee_rate_probe=False => zero HTTP calls, raw=None
    cfg_off = OfflineSchedulerConfig(
        p13_session_dir=p13_dir,
        audit_output_root=tmp_path / "audit_off",
        orig_session_id="s311-probe-off",
        safety_config_path=DEFAULT_GATEWAY_CONFIG_PATH,
    )
    run_s311_offline_schedule(
        cfg_off,
        exec_config=default_stub_trading_config(),
        policy_bundle=_sample_policy(t0),
        forecasts=[fc],
        targets=[target],
        quota_provider=_sample_quota(),
        clock_ticks=(t0 + timedelta(seconds=65),),
    )
    assert calls == []

    # 2) Explicit enable_official_fee_rate_probe=True => forwards safety.clob_host + 0.5s timeout
    decider_on, wired_host = build_wired_decider(
        exec_config=default_stub_trading_config(),
        safety_config_path=DEFAULT_GATEWAY_CONFIG_PATH,
        enable_official_fee_rate_probe=True,
        fee_rate_timeout_sec=0.5,
    )
    assert wired_host == "https://clob.polymarket.com"
    env_yes, _ = build_p4_v11_stub_envelope(
        session_id="live-sim",
        seq_id=1,
        frame_seq=1,
        token_id="tok-y",
        market_id="mkt-1",
        condition_id="cond-1",
        station_id="KORD",
        target_date="2026-11-25",
        bin_label="58-59°F",
        outcome="YES",
        regime="ask_only",
        recv_ts_utc=t0,
        asks=((0.25, 100.0),),
        bids=(),
    )
    ev_live = decider_on.evaluate_bin(
        orig_session_id="live-sim",
        execution_mode="PAPER",
        scan_clock="PRICE_CLOCK",
        scan_ts_utc=t0 + timedelta(seconds=1),
        station_id="KORD",
        target_date="2026-11-25",
        bin_id="bin-58-59",
        market_id="mkt-1",
        yes_token_id="tok-y",
        forecasts=[fc],
        policy_bundle=_sample_policy(t0),
        quota_provider=_sample_quota(),
        yes_frame=env_yes.payload,
        include_no_side=False,
    )
    assert ev_live.schema_version == "p1.v3"
    assert ev_live.capture_replay_mode == "NONE"
    assert ev_live.fee_rate_official_raw == {"base_fee": 1000}
    assert calls == [("https://clob.polymarket.com/fee-rate?token_id=tok-y", 0.5)]


def test_s311_p10_reader_backward_compat_v2_and_v3_round_trip(tmp_path: Path) -> None:
    t0 = datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)
    p13_dir = tmp_path / "p13_sess"
    audit_dir = tmp_path / "audit_mix"
    _write_p13_session(p13_dir, t0)
    fc = build_stub_forecast_v11(
        target_date_str="2026-11-25",
        issue_ts_utc=t0 - timedelta(minutes=10),
        settle_close_utc=t0 + timedelta(hours=10),
    )
    target = OfflineScheduleTarget(
        station_id="KORD",
        target_date="2026-11-25",
        bin_id="bin-58-59",
        bin_label="58-59°F",
        market_id="mkt-1",
        yes_token_id="tok-y",
    )
    cfg = OfflineSchedulerConfig(
        p13_session_dir=p13_dir,
        audit_output_root=audit_dir,
        orig_session_id="s311-mix",
    )
    run_s311_offline_schedule(
        cfg,
        exec_config=default_stub_trading_config(),
        policy_bundle=_sample_policy(t0),
        forecasts=[fc],
        targets=[target],
        quota_provider=_sample_quota(),
        clock_ticks=(t0 + timedelta(seconds=65),),
    )

    # Append one legacy p1.v2 line (without capture_replay_mode) and one legacy p17.v2 line
    p1_file = next(audit_dir.rglob("p1_scan_decisions.jsonl"))
    p17_file = next(audit_dir.rglob("p17_forecast_snapshots.jsonl"))
    v3_p1 = json.loads(p1_file.read_text(encoding="utf-8").splitlines()[0])
    v2_p1 = {k: v for k, v in v3_p1.items() if k != "capture_replay_mode"}
    v2_p1["schema_version"] = "p1.v2"
    v2_p1["decision_id"] = "legacy-v2-decision-001"
    with p1_file.open("a", encoding="utf-8") as fh:
        fh.write(_sign_jsonl_record(v2_p1) + "\n")

    v3_p17 = json.loads(p17_file.read_text(encoding="utf-8").splitlines()[0])
    v2_p17 = {k: v for k, v in v3_p17.items() if k != "capture_replay_mode"}
    v2_p17["schema_version"] = "p17.v2"
    v2_p17["forecast_id"] = "fc-legacy-v2"
    with p17_file.open("a", encoding="utf-8") as fh:
        fh.write(_sign_jsonl_record(v2_p17) + "\n")

    # p10_reader loads both v3 and legacy v2 cleanly without corrupt lines
    view = query_p10_session_view(audit_dir, P10Query(execution_mode="PAPER"))
    assert view.render_status == "OK"
    assert view.corrupt_lines == ()
    assert len(view.p1_events) == 2
    assert len(view.p17_snapshots) == 2

    by_id = {r["decision_id"]: r for r in view.p1_events}
    assert by_id["legacy-v2-decision-001"].get("capture_replay_mode") is None
    v3_recs = [r for r in view.p1_events if r["schema_version"] == "p1.v3"]
    assert len(v3_recs) == 1
    assert v3_recs[0]["capture_replay_mode"] == "REPLAY_P13"

    # M10 renders mixed v2 + v3 cleanly without crashing and surfaces REPLAY_P13 mode tag
    model = build_m10_dashboard_model(
        audit_root=audit_dir,
        execution_mode="PAPER",
        safety_config_path=DEFAULT_GATEWAY_CONFIG_PATH,
    )
    assert model.render_status == "OK"
    assert len(model.decision_rows) == 2
    modes = {r["decision_id"]: r["capture_replay_mode"] for r in model.decision_rows}
    assert modes["legacy-v2-decision-001"] is None
    assert "REPLAY_P13" in modes.values()
    html_out = render_m10_dashboard_html(model)
    assert "mode=REPLAY_P13" in html_out


def test_s311_cli_dry_run_plan_and_zero_trading_endpoints_ast_check(tmp_path: Path) -> None:
    t0 = datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)
    p13_dir = tmp_path / "p13_cli"
    _write_p13_session(p13_dir, t0)

    proc = subprocess.run(
        [
            sys.executable,
            "scripts/run_s311_offline_scheduler.py",
            "--p13-session-dir",
            str(p13_dir),
            "--cadence-sec",
            "30",
            "--replay-delay-ms",
            "500",
            "--dry-run-plan",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    plan = json.loads(proc.stdout)
    assert plan["mode"] == "OFFLINE_P13_REPLAY_ONLY"
    assert plan["capture_replay_mode"] == "REPLAY_P13"
    assert plan["enable_official_fee_rate_probe_default"] is False
    assert plan["clob_host_wired"] == "https://clob.polymarket.com"
    assert plan["p13_valid_frames"] == 2
    assert plan["planned_ticks"] == 3

    # AST static guard: offline_scheduler.py must never import/call order submission gateways
    src_path = Path("src/decision/offline_scheduler.py")
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    forbidden_names = {"ClobGateway", "PaperGateway", "LiveGateway", "submit_order", "place_order", "cancel_order"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in forbidden_names, f"Forbidden trading symbol {node.id} in offline_scheduler.py"
        elif isinstance(node, ast.Attribute):
            assert node.attr not in forbidden_names, f"Forbidden trading attr {node.attr} in offline_scheduler.py"
        elif isinstance(node, ast.alias):
            assert node.name not in forbidden_names, f"Forbidden trading import {node.name} in offline_scheduler.py"
