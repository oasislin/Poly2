"""Unit tests for S3-13 strictly read-only 4-class watchdog (`src/audit/readonly_watchdog.py`)."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.run_readonly_watchdog import main as watchdog_cli_main
from src.audit.readonly_watchdog import WatchdogConfig, run_watchdog_once
from src.utils.causal_utils import compute_record_sha256


def _signed_p13_line(
    *,
    session_id: str,
    seq_id: int,
    station_id: str,
    token_id: str,
    outcome: str,
    ts_utc: datetime,
    gap_detected: bool = False,
    gap_reason: str | None = None,
    single_side: str | None = None,
) -> str:
    payload = {
        "token_id": token_id,
        "market_id": f"mkt-{station_id}",
        "condition_id": f"cond-{station_id}",
        "outcome": outcome,
        "snapshot_ts_utc": ts_utc.isoformat(),
        "recv_ts_utc": ts_utc.isoformat(),
        "frame_seq": seq_id,
        "data_source": "WS",
        "single_side": single_side,
        "tick_size": 0.01,
        "min_order_size_shares": 5.0,
        "min_notional_usd": 1.0,
        "fee_rate": 0.01,
        "fee_rate_provenance": "API_RUNTIME",
        "neg_risk": True,
        "best_bid": 0.40,
        "asks": [] if single_side == "bid_only" else [[0.45, 10.0]],
        "bids": [] if single_side == "ask_only" else [[0.40, 10.0]],
        "bid_top10": [] if single_side == "ask_only" else [[0.40, 10.0]],
    }
    env = {
        "schema_version": "p13.v1",
        "seq_id": seq_id,
        "session_id": session_id,
        "capture_mode": "PASSIVE_RECORD",
        "gap_detected": gap_detected,
        "gap_reason": gap_reason,
        "recorded_ts_utc": ts_utc.isoformat(),
        "station_id": station_id,
        "payload": payload,
    }
    env["record_sha256"] = compute_record_sha256(env)
    return json.dumps(env, sort_keys=True, separators=(",", ":")) + "\n"


def _write_p13_session(
    rec_root: Path,
    session_id: str,
    station_lines: dict[str, list[str]],
    *,
    day_str: str = "2026-11-24",
    write_pointer: bool = True,
) -> None:
    sess_dir = rec_root / "PASSIVE_RECORD" / day_str / session_id
    sess_dir.mkdir(parents=True, exist_ok=True)
    for st_id, lines in station_lines.items():
        (sess_dir / f"p13_book_stream_{st_id}.jsonl").write_text("".join(lines), encoding="utf-8")
    if write_pointer:
        (rec_root / "latest_session.json").write_text(
            json.dumps({"session_id": session_id, "supervisor_pid": 99991, "child_pid": 99992}),
            encoding="utf-8",
        )


def _snapshot_tree(roots: list[Path]) -> dict[str, tuple[int, str]]:
    snap: dict[str, tuple[int, str]] = {}
    for root in roots:
        if not root.exists():
            continue
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for fp in files:
            st = fp.stat()
            digest = hashlib.sha256(fp.read_bytes()).hexdigest()
            snap[str(fp)] = (st.st_mtime_ns, digest)
    return snap


def _healthy_disk(_path: Path) -> SimpleNamespace:
    return SimpleNamespace(total=100 * 1024**3, used=40 * 1024**3, free=60 * 1024**3)


def test_s313_gap_rate_rollover_grace_and_three_poll_recovery(tmp_path: Path) -> None:
    rec_root, audit_root, alerts_dir = tmp_path / "rec", tmp_path / "audit", tmp_path / "alerts"
    t0 = datetime(2026, 11, 24, 10, 0, 0, tzinfo=timezone.utc)
    lines = [
        _signed_p13_line(
            session_id="s-gap", seq_id=i + 1, station_id="KORD", token_id=f"tok-{i % 2}",
            outcome="YES" if i % 2 == 0 else "NO", ts_utc=t0 + timedelta(seconds=i),
            gap_detected=(i < 5), gap_reason="WS_HEARTBEAT_TIMEOUT" if i < 5 else None,
        )
        for i in range(70)
    ]
    _write_p13_session(rec_root, "s-gap", {"KORD": lines})
    cfg = WatchdogConfig(
        recordings_root=rec_root, audit_root=audit_root, alerts_dir=alerts_dir,
        ledger_path=None, expected_stations=("KORD",),
    )

    # gap_rate = 5/70 = 0.0714 > 0.05 -> CRITICAL
    res1 = run_watchdog_once(cfg, now_utc=t0 + timedelta(seconds=80), disk_usage_fn=_healthy_disk, pid_alive_fn=lambda _: True)
    assert res1["checks"]["gap_rate"]["status"] == "CRITICAL"

    # Replace active window with 70 healthy frames across advancing timestamps -> requires 3 consecutive healthy polls
    t_rec = t0 + timedelta(minutes=20)
    healthy = [
        _signed_p13_line(
            session_id="s-gap", seq_id=100 + i, station_id="KORD", token_id=f"tok-{i % 2}",
            outcome="YES" if i % 2 == 0 else "NO", ts_utc=t_rec + timedelta(seconds=i),
        )
        for i in range(70)
    ]
    _write_p13_session(rec_root, "s-gap", {"KORD": healthy})
    r_p1 = run_watchdog_once(cfg, now_utc=t_rec + timedelta(seconds=75), disk_usage_fn=_healthy_disk, pid_alive_fn=lambda _: True)
    r_p2 = run_watchdog_once(cfg, now_utc=t_rec + timedelta(seconds=80), disk_usage_fn=_healthy_disk, pid_alive_fn=lambda _: True)
    r_p3 = run_watchdog_once(cfg, now_utc=t_rec + timedelta(seconds=85), disk_usage_fn=_healthy_disk, pid_alive_fn=lambda _: True)
    assert r_p1["checks"]["gap_rate"]["status"] == "CRITICAL"
    assert r_p1["checks"]["gap_rate"]["metrics"]["recover_streak"] == 1
    assert r_p2["checks"]["gap_rate"]["status"] == "CRITICAL"
    assert r_p2["checks"]["gap_rate"]["metrics"]["recover_streak"] == 2
    assert r_p3["checks"]["gap_rate"]["status"] == "OK"

    # Daily 00:05Z rollover grace window (silence <= 150s stays OK)
    rollover_ts = datetime(2026, 11, 25, 0, 5, 30, tzinfo=timezone.utc)
    r_lines = [
        _signed_p13_line(
            session_id="s-roll", seq_id=1, station_id="KORD", token_id="t1", outcome="YES",
            ts_utc=datetime(2026, 11, 25, 0, 3, 20, tzinfo=timezone.utc),
        ),
        _signed_p13_line(
            session_id="s-roll", seq_id=2, station_id="KORD", token_id="t2", outcome="NO",
            ts_utc=datetime(2026, 11, 25, 0, 3, 21, tzinfo=timezone.utc),
        ),
    ]
    _write_p13_session(rec_root, "s-roll", {"KORD": r_lines}, day_str="2026-11-25")
    r_roll = run_watchdog_once(cfg, now_utc=rollover_ts, disk_usage_fn=_healthy_disk, pid_alive_fn=lambda _: False)
    assert r_roll["checks"]["gap_rate"]["status"] == "OK"
    assert r_roll["planned_windows_active"] is True


def test_s313_corrupt_lines_and_eof_tail_exemption(tmp_path: Path) -> None:
    rec_root, audit_root, alerts_dir = tmp_path / "rec", tmp_path / "audit", tmp_path / "alerts"
    t0 = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)
    valid_line = _signed_p13_line(session_id="s1", seq_id=1, station_id="KMIA", token_id="ty", outcome="YES", ts_utc=t0)
    valid_no = _signed_p13_line(session_id="s1", seq_id=2, station_id="KMIA", token_id="tn", outcome="NO", ts_utc=t0)
    partial_tail = '{"schema_version":"p13.v1","partial":true'  # no trailing newline
    _write_p13_session(rec_root, "s1", {"KMIA": [valid_line, valid_no, partial_tail]})
    cfg = WatchdogConfig(
        recordings_root=rec_root, audit_root=audit_root, alerts_dir=alerts_dir,
        ledger_path=None, expected_stations=("KMIA",),
    )

    # First two polls under 90s: unterminated tail is NOT corrupt and stays OK
    r1 = run_watchdog_once(cfg, now_utc=t0 + timedelta(seconds=10), disk_usage_fn=_healthy_disk, pid_alive_fn=lambda _: True)
    assert r1["checks"]["corrupt_lines"]["status"] == "OK"
    assert r1["checks"]["corrupt_lines"]["metrics"]["corrupt_lines"] == 0
    assert r1["checks"]["corrupt_lines"]["metrics"]["incomplete_trailing_lines"] == 1

    r2 = run_watchdog_once(cfg, now_utc=t0 + timedelta(seconds=50), disk_usage_fn=_healthy_disk, pid_alive_fn=lambda _: True)
    assert r2["checks"]["corrupt_lines"]["status"] == "OK"

    # 3rd poll > 90s with unchanged byte offset -> WARN TAIL_WRITE_STALLED (still 0 corrupt_lines)
    r3 = run_watchdog_once(cfg, now_utc=t0 + timedelta(seconds=110), disk_usage_fn=_healthy_disk, pid_alive_fn=lambda _: True)
    assert r3["checks"]["corrupt_lines"]["status"] == "WARN"
    assert r3["checks"]["corrupt_lines"]["metrics"]["corrupt_lines"] == 0

    # Terminated corrupt line -> immediate CRITICAL
    _write_p13_session(rec_root, "s1", {"KMIA": [valid_line, valid_no, "{bad json}\n"]})
    r4 = run_watchdog_once(cfg, now_utc=t0 + timedelta(seconds=120), disk_usage_fn=_healthy_disk, pid_alive_fn=lambda _: True)
    assert r4["checks"]["corrupt_lines"]["status"] == "CRITICAL"
    assert r4["checks"]["corrupt_lines"]["metrics"]["corrupt_lines"] == 1


def test_s313_token_coverage_drop_side_missing_and_recovery(tmp_path: Path) -> None:
    rec_root, audit_root, alerts_dir = tmp_path / "rec", tmp_path / "audit", tmp_path / "alerts"
    t_hist = datetime(2026, 11, 24, 10, 0, 0, tzinfo=timezone.utc)
    # Prior 24h healthy complete session (duration >= 180s, >= 10 frames, both YES & NO): 10 tokens (5 YES, 5 NO)
    hist_lines = [
        _signed_p13_line(
            session_id="s-hist", seq_id=i + 1, station_id="KATL",
            token_id=f"tok-{i % 10}", outcome="YES" if (i % 10) < 5 else "NO",
            ts_utc=t_hist + timedelta(seconds=i * 25), single_side="bid_only" if i == 9 else None,
        )
        for i in range(12)
    ]
    _write_p13_session(rec_root, "s-hist", {"KATL": hist_lines}, write_pointer=False)

    # New active session post-180s warmup only discovers 4/10 tokens -> ratio = 0.40 <= 0.50 -> CRITICAL
    t0 = datetime(2026, 11, 24, 14, 0, 0, tzinfo=timezone.utc)
    drop_lines = [
        _signed_p13_line(
            session_id="s-tok", seq_id=i + 1, station_id="KATL",
            token_id=f"tok-{i % 4}", outcome="YES" if (i % 4) < 2 else "NO",
            ts_utc=t0 + timedelta(seconds=i * 30),
        )
        for i in range(8)
    ]
    _write_p13_session(rec_root, "s-tok", {"KATL": drop_lines})
    cfg = WatchdogConfig(
        recordings_root=rec_root, audit_root=audit_root, alerts_dir=alerts_dir,
        ledger_path=None, expected_stations=("KATL",),
    )
    r_crit = run_watchdog_once(cfg, now_utc=t0 + timedelta(seconds=240), disk_usage_fn=_healthy_disk, pid_alive_fn=lambda _: True)
    assert r_crit["checks"]["token_coverage"]["status"] == "CRITICAL"

    # Recover to 9/10 tokens (ratio = 0.90 > 0.85, both YES & NO) across 2 polls -> OK
    recovered = [
        _signed_p13_line(
            session_id="s-tok", seq_id=20 + i, station_id="KATL",
            token_id=f"tok-{i}", outcome="YES" if i < 5 else "NO",
            ts_utc=t0 + timedelta(seconds=250 + i),
        )
        for i in range(9)
    ]
    _write_p13_session(rec_root, "s-tok", {"KATL": drop_lines + recovered})
    r1 = run_watchdog_once(cfg, now_utc=t0 + timedelta(seconds=270), disk_usage_fn=_healthy_disk, pid_alive_fn=lambda _: True)
    r2 = run_watchdog_once(cfg, now_utc=t0 + timedelta(seconds=280), disk_usage_fn=_healthy_disk, pid_alive_fn=lambda _: True)
    assert r1["checks"]["token_coverage"]["status"] == "CRITICAL"
    assert r2["checks"]["token_coverage"]["status"] == "OK"

    # Whole NO side missing in active session -> CRITICAL TOKEN_SIDE_MISSING
    t_side = t0 + timedelta(minutes=20)
    only_yes = [
        _signed_p13_line(
            session_id="s-side", seq_id=i + 1, station_id="KATL",
            token_id=f"tok-{i}", outcome="YES", ts_utc=t_side + timedelta(seconds=i * 45),
        )
        for i in range(5)
    ]
    _write_p13_session(rec_root, "s-side", {"KATL": only_yes})
    r_side = run_watchdog_once(cfg, now_utc=t_side + timedelta(seconds=200), disk_usage_fn=_healthy_disk, pid_alive_fn=lambda _: True)
    assert r_side["checks"]["token_coverage"]["status"] == "CRITICAL"
    assert any(s["reason"] == "TOKEN_SIDE_MISSING" for s in r_side["checks"]["token_coverage"]["triggered_scopes"])


def test_s313_disk_watchdog_watermarks_eta_and_3x_growth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rec_root, audit_root, alerts_dir = tmp_path / "rec", tmp_path / "audit", tmp_path / "alerts"
    t0 = datetime.now(timezone.utc) - timedelta(seconds=5)
    lines = [_signed_p13_line(session_id="s-d", seq_id=1, station_id="KORD", token_id="t1", outcome="YES", ts_utc=t0)]
    _write_p13_session(rec_root, "s-d", {"KORD": lines})
    cfg = WatchdogConfig(
        recordings_root=rec_root, audit_root=audit_root, alerts_dir=alerts_dir,
        ledger_path=None, expected_stations=("KORD",), expect_recorder_running=False,
    )

    r_warn = run_watchdog_once(
        cfg, now_utc=t0,
        disk_usage_fn=lambda _: SimpleNamespace(total=100 * 1024**3, used=85 * 1024**3, free=15 * 1024**3),
    )
    assert r_warn["checks"]["disk_watchdog"]["status"] == "WARN"
    assert any(s["reason"] == "DISK_LOW_FREE_SPACE" for s in r_warn["checks"]["disk_watchdog"]["triggered_scopes"])

    r_crit = run_watchdog_once(
        cfg, now_utc=t0 + timedelta(minutes=1),
        disk_usage_fn=lambda _: SimpleNamespace(total=100 * 1024**3, used=97 * 1024**3, free=3 * 1024**3),
    )
    assert r_crit["checks"]["disk_watchdog"]["status"] == "CRITICAL"
    assert any(s["reason"] == "DISK_CRITICAL_EXHAUSTION" for s in r_crit["checks"]["disk_watchdog"]["triggered_scopes"])

    # 3x growth anomaly + ETA < 24h: baseline ~10 MiB/h over trailing 24h, recent 30m jump = 600 MiB (1200 MiB/h)
    alerts_dir.mkdir(parents=True, exist_ok=True)
    seed_samples = [
        {"ts_utc": (t0 - timedelta(hours=24)).isoformat(), "total_bytes": 100 * 1024**2},
        {"ts_utc": (t0 - timedelta(hours=2)).isoformat(), "total_bytes": 320 * 1024**2},
        {"ts_utc": (t0 - timedelta(minutes=30)).isoformat(), "total_bytes": 320 * 1024**2},
    ]
    (alerts_dir / "watchdog_state.json").write_text(json.dumps({"disk_samples": seed_samples}), encoding="utf-8")
    monkeypatch.setattr(
        "src.audit.readonly_watchdog._scan_audit_and_m10_readonly",
        lambda _cfg: {"valid_lines": 0, "corrupt_items": [], "trailing_tails": [], "disk_bytes": 920 * 1024**2, "render_statuses": {}, "m10_html": {}},
    )
    r_spike = run_watchdog_once(
        cfg, now_utc=t0,
        disk_usage_fn=lambda _: SimpleNamespace(total=200 * 1024**3, used=140 * 1024**3, free=60 * 1024**3),
    )
    assert r_spike["checks"]["disk_watchdog"]["status"] == "WARN"
    assert any(s["reason"] == "DISK_GROWTH_ANOMALY" for s in r_spike["checks"]["disk_watchdog"]["triggered_scopes"])

    # Same growth spike with 20 GiB free -> ETA = 20 GiB / 1.17 GiB/h ~ 17h < 24h -> CRITICAL
    (alerts_dir / "watchdog_state.json").write_text(json.dumps({"disk_samples": seed_samples}), encoding="utf-8")
    r_eta = run_watchdog_once(
        cfg, now_utc=t0,
        disk_usage_fn=lambda _: SimpleNamespace(total=200 * 1024**3, used=180 * 1024**3, free=20 * 1024**3),
    )
    assert r_eta["checks"]["disk_watchdog"]["status"] == "CRITICAL"
    assert any(s["reason"] == "DISK_ETA_UNDER_24H" for s in r_eta["checks"]["disk_watchdog"]["triggered_scopes"])


def test_s313_planned_maintenance_exemption_via_ledger_and_json(tmp_path: Path) -> None:
    rec_root, audit_root, alerts_dir = tmp_path / "rec", tmp_path / "audit", tmp_path / "alerts"
    t0 = datetime(2026, 11, 24, 10, 30, 0, tzinfo=timezone.utc)
    lines = [
        _signed_p13_line(session_id="s-m", seq_id=1, station_id="KORD", token_id="t1", outcome="YES", ts_utc=t0),
        _signed_p13_line(session_id="s-m", seq_id=2, station_id="KORD", token_id="t2", outcome="NO", ts_utc=t0),
    ]
    _write_p13_session(rec_root, "s-m", {"KORD": lines})
    ledger = tmp_path / "ledger.md"
    # 18:30-22:30 +08:00 == 10:30-14:30 UTC
    ledger.write_text(
        "| **`M3`** | 盘口数据 | `已就绪` | `S2-01` | 产线暂停（注：`2026-11-24 18:30–22:30` (`240m`) 系业主主动指令启停，SIGTERM 优雅退出） | x |\n",
        encoding="utf-8",
    )
    cfg = WatchdogConfig(
        recordings_root=rec_root, audit_root=audit_root, alerts_dir=alerts_dir,
        ledger_path=ledger, expected_stations=("KORD",),
    )
    res_exempt = run_watchdog_once(
        cfg, now_utc=datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc),
        disk_usage_fn=_healthy_disk, pid_alive_fn=lambda _: False,
    )
    assert res_exempt["checks"]["gap_rate"]["status"] == "OK"
    assert res_exempt["planned_windows_active"] is True

    # Outside declared maintenance window -> offline PID triggers CRITICAL RECORDER_PROCESS_DOWN
    res_down = run_watchdog_once(
        cfg, now_utc=datetime(2026, 11, 24, 16, 0, 0, tzinfo=timezone.utc),
        disk_usage_fn=_healthy_disk, pid_alive_fn=lambda _: False,
    )
    assert res_down["checks"]["gap_rate"]["status"] == "CRITICAL"
    assert any(s["reason"] == "RECORDER_PROCESS_DOWN" for s in res_down["checks"]["gap_rate"]["triggered_scopes"])


def test_s313_readonly_mtime_content_unchanged_isolation_and_ast(tmp_path: Path) -> None:
    rec_root, audit_root, alerts_dir = tmp_path / "rec", tmp_path / "audit", tmp_path / "alerts"
    m10_html = tmp_path / "m10_board.html"
    m10_html.write_text("<html><body>M10 OK</body></html>", encoding="utf-8")
    t0 = datetime.now(timezone.utc) - timedelta(seconds=5)
    lines = [
        _signed_p13_line(session_id="s-ro", seq_id=1, station_id="KSEA", token_id="t1", outcome="YES", ts_utc=t0),
        _signed_p13_line(session_id="s-ro", seq_id=2, station_id="KSEA", token_id="t2", outcome="NO", ts_utc=t0),
    ]
    _write_p13_session(rec_root, "s-ro", {"KSEA": lines})
    audit_day = audit_root / "PAPER" / "2026-11-24"
    audit_day.mkdir(parents=True, exist_ok=True)
    p1_rec = {"schema_version": "p1.v2", "decision_id": "d1", "station_id": "KSEA"}
    p1_rec["record_sha256"] = compute_record_sha256(p1_rec)
    (audit_day / "p1_scan_decisions.jsonl").write_text(json.dumps(p1_rec) + "\n", encoding="utf-8")

    # Isolation guard rejects alerts_dir inside audit_root or recordings_root
    with pytest.raises(ValueError, match="isolated"):
        run_watchdog_once(WatchdogConfig(recordings_root=rec_root, audit_root=audit_root, alerts_dir=audit_root / "bad", ledger_path=None))

    before = _snapshot_tree([rec_root, audit_root, m10_html])
    rc = watchdog_cli_main([
        "--recordings-root", str(rec_root),
        "--audit-root", str(audit_root),
        "--alerts-dir", str(alerts_dir),
        "--m10-html", str(m10_html),
        "--no-expect-recorder",
        "--once",
    ])
    after = _snapshot_tree([rec_root, audit_root, m10_html])
    assert before == after  # mtime_ns + sha256 + file set strictly untouched
    assert rc == 0
    assert (alerts_dir / "watchdog_status.json").exists()

    # AST static guard on S3-13 module & CLI
    repo_root = Path(__file__).resolve().parents[3]
    for rel_path in ("src/audit/readonly_watchdog.py", "scripts/run_readonly_watchdog.py"):
        src_text = (repo_root / rel_path).read_text(encoding="utf-8")
        assert ".unlink(" not in src_text
        assert ".rmdir(" not in src_text
        assert "rmtree(" not in src_text
        assert "SIGTERM" not in src_text
        tree = ast.parse(src_text)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert (node.end_lineno - node.lineno + 1) <= 50, f"{rel_path}:{node.name} > 50 lines"
