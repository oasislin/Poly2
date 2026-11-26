#!/usr/bin/env python3
"""S3-11 Offline P13 Delayed-Replay Scheduler CLI (no live/paper trading endpoints)."""

from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.audit.p13_reader import load_p13_session_readonly
from src.bankroll.manager import BankrollAccountManager
from src.bankroll.models import BankrollConfig
from src.calibration.policy_ledger import PolicyParameterLedger, issue_policy_bundle
from src.decision.offline_scheduler import (
    OfflineScheduleTarget,
    OfflineSchedulerConfig,
    generate_synthetic_clock_ticks,
    run_s311_offline_schedule,
)
from src.execution.clob_gateway import DEFAULT_GATEWAY_CONFIG_PATH, load_gateway_safety_config
from src.execution.executor import TradingExecutionConfig
from src.prediction.live_p5_producer import load_p5_jsonl_snapshots, parse_polymarket_bin_label
from src.utils.causal_utils import ensure_utc_datetime, parse_utc_timestamp

DEFAULT_RECORDINGS_ROOT = _REPO_ROOT / "data" / "market_recordings"
WATERMARK_FILENAME = ".s311_watermark.json"


def _is_subpath(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def validate_audit_output_root(audit_root: Path, recordings_root: Path) -> Path:
    """Ensure `--audit-output-root` is physically isolated from code/docs/evidence/recordings."""
    resolved = audit_root.resolve()
    forbidden = (
        _REPO_ROOT / "src", _REPO_ROOT / "docs" / "audit",
        _REPO_ROOT / "evidence", recordings_root.resolve(),
    )
    for blocked in forbidden:
        if _is_subpath(resolved, blocked):
            raise ValueError(f"audit_output_root must be isolated from {blocked}: got {resolved}")
    return resolved


def discover_completed_p13_sessions(recordings_root: Path = DEFAULT_RECORDINGS_ROOT) -> Tuple[Path, ...]:
    """Discover completed `PASSIVE_RECORD` session dirs (excluding active pointer)."""
    ptr = recordings_root / "latest_session.json"
    active_sid = json.loads(ptr.read_text(encoding="utf-8")).get("session_id") if ptr.exists() else None
    base = recordings_root / "PASSIVE_RECORD"
    if not base.exists():
        return ()
    found: List[Path] = []
    for day_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        for sess_dir in sorted(p for p in day_dir.iterdir() if p.is_dir()):
            if active_sid and sess_dir.name == active_sid:
                continue
            if any(sess_dir.glob("p13_book_stream_*.jsonl")):
                found.append(sess_dir)
    return tuple(found)


def discover_active_p13_session(recordings_root: Path = DEFAULT_RECORDINGS_ROOT) -> Path:
    """Locate current active `PASSIVE_RECORD` session dir from `latest_session.json`."""
    ptr = recordings_root / "latest_session.json"
    if not ptr.exists():
        raise FileNotFoundError(f"Active session pointer missing: {ptr}")
    sid = json.loads(ptr.read_text(encoding="utf-8")).get("session_id")
    matches = sorted((recordings_root / "PASSIVE_RECORD").rglob(str(sid))) if sid else []
    if not matches:
        raise FileNotFoundError(f"Active session directory not found for session_id={sid!r}")
    return matches[0]


def load_watermark(audit_root: Path) -> Dict[str, str]:
    """Load persisted `{session_id: last_tick_utc_iso}` watermark map."""
    wm_path = audit_root / WATERMARK_FILENAME
    if not wm_path.exists():
        return {}
    raw = json.loads(wm_path.read_text(encoding="utf-8"))
    sessions = raw.get("sessions") if isinstance(raw, dict) else {}
    return {str(k): str(v) for k, v in sessions.items()} if isinstance(sessions, dict) else {}


def save_watermark(audit_root: Path, sessions_map: Dict[str, str]) -> Path:
    """Atomically persist watermark state inside `audit_root`."""
    audit_root.mkdir(parents=True, exist_ok=True)
    wm_path = audit_root / WATERMARK_FILENAME
    tmp_path = audit_root / f".{WATERMARK_FILENAME}.{os.getpid()}.tmp"
    payload = {"schema_version": "s311_watermark.v1", "sessions": dict(sorted(sessions_map.items()))}
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp_path, wm_path)
    return wm_path


def filter_unprocessed_ticks(ticks: Sequence[datetime], last_processed_iso: Optional[str]) -> Tuple[datetime, ...]:
    """Return strictly newer UTC ticks than `last_processed_iso` for watermark dedup."""
    if not last_processed_iso:
        return tuple(ticks)
    cutoff = ensure_utc_datetime(datetime.fromisoformat(last_processed_iso), field_name="watermark.last_tick")
    return tuple(t for t in ticks if ensure_utc_datetime(t, field_name="tick") > cutoff)


def discover_p13_schedule_targets(session_dir: Path) -> Tuple[OfflineScheduleTarget, ...]:
    """Extract unique YES-anchored `OfflineScheduleTarget` records from a `P13` session."""
    loaded = load_p13_session_readonly(session_dir, verify_sha256=False)
    seen: Dict[Tuple[str, str, str, str], OfflineScheduleTarget] = {}
    for env in loaded.envelopes:
        if env.payload.outcome != "YES":
            continue
        key = (env.station_id, env.target_date, env.bin_label, env.payload.market_id)
        if key in seen:
            continue
        try:
            bid = parse_polymarket_bin_label(env.bin_label).bin_id
        except ValueError:
            bid = env.bin_label
        seen[key] = OfflineScheduleTarget(
            station_id=env.station_id, target_date=env.target_date, bin_id=bid,
            bin_label=env.bin_label, market_id=env.payload.market_id,
            yes_token_id=env.payload.token_id, include_no_side=False,
        )
    return tuple(seen[k] for k in sorted(seen))


def _default_prod_exec_config(replay_delay_ms: int) -> TradingExecutionConfig:
    return TradingExecutionConfig(
        min_order_size_shares=Decimal("5.0"), min_order_size_shares_provenance="FACT-004",
        min_notional_usd=Decimal("1.0"), min_notional_usd_provenance="P8-CAPITAL-CONFIG v1.0",
        forecast_age_limit_sec=21600.0, forecast_age_limit_sec_provenance="P8-T8-ALGO4-DESIGN v0.3 §3.2",
        max_book_staleness_sec=60.0, max_book_staleness_sec_provenance="P8-T8-ALGO4-DESIGN v0.3 §3.2",
        pair_max_skew_sec=5.0, pair_max_skew_sec_provenance="P8-D6-POLICY-CLOSURE v1.0 §9.2",
        latency_ms=int(replay_delay_ms), latency_ms_provenance="EXEC16 D1=0 causal book lag",
        heartbeat_timeout_sec=25.0, heartbeat_timeout_sec_provenance="configs/passive_book_recorder.example.yaml",
        rest_fallback_interval_sec=5.0, rest_fallback_interval_sec_provenance="configs/passive_book_recorder.example.yaml",
        enable_cross_side_split_routing=False, cross_side_split_routing_provenance="EXEC15 S2-02 YES_ONLY",
    )


def _load_existing_p17_ids(audit_root: Path) -> Set[str]:
    seen: Set[str] = set()
    for p17_file in audit_root.rglob("p17_forecast_snapshots.jsonl"):
        for line in p17_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    seen.add(str(json.loads(line)["forecast_id"]))
                except Exception:
                    continue
    return seen


def _build_real_session_runner(
    args: argparse.Namespace, *, audit_root: Path, run_stats: Dict[str, Any]
) -> Optional[Callable[[Path, Tuple[datetime, ...], Path], int]]:
    if args.p5_dir is None or args.policy_ledger_path is None:
        return None
    p5_dir, ledger_path = Path(args.p5_dir), Path(args.policy_ledger_path)
    if not p5_dir.exists() or not ledger_path.is_file():
        return None
    ledger = PolicyParameterLedger.load(ledger_path)
    if ledger.friction_median is None or not load_p5_jsonl_snapshots(p5_dir):
        return None
    policy_bundle = issue_policy_bundle(ledger)
    safety = load_gateway_safety_config(args.safety_config)
    exec_cfg = _default_prod_exec_config(args.replay_delay_ms)
    quota_mgr = BankrollAccountManager(BankrollConfig(
        session_id="s311-exec16", execution_mode=safety.execution_mode,
        policy_version=policy_bundle.policy_version, config_hash=policy_bundle.config_hash,
        is_overdue=policy_bundle.is_overdue,
    ))
    seen_p17 = _load_existing_p17_ids(audit_root)
    return _make_runner_fn(args, p5_dir, policy_bundle, exec_cfg, quota_mgr, seen_p17, run_stats)


def _make_runner_fn(
    args: argparse.Namespace, p5_dir: Path, policy_bundle: Any,
    exec_cfg: TradingExecutionConfig, quota_mgr: BankrollAccountManager,
    seen_p17: Set[str], run_stats: Dict[str, Any],
) -> Callable[[Path, Tuple[datetime, ...], Path], int]:
    def _runner(sess_dir: Path, pending_ticks: Tuple[datetime, ...], out_root: Path) -> int:
        targets = discover_p13_schedule_targets(sess_dir)
        all_fc = load_p5_jsonl_snapshots(p5_dir)
        causal_fc = [fc for fc in all_fc if fc.issue_ts_utc <= pending_ticks[-1]]
        cfg = OfflineSchedulerConfig(
            p13_session_dir=sess_dir, audit_output_root=out_root, orig_session_id=sess_dir.name,
            safety_config_path=args.safety_config, cadence_sec=args.cadence_sec,
            replay_delay_ms=args.replay_delay_ms, enable_official_fee_rate_probe=False,
        )
        summary = run_s311_offline_schedule(
            cfg, exec_config=exec_cfg, policy_bundle=policy_bundle, forecasts=causal_fc,
            targets=targets, quota_provider=quota_mgr, clock_ticks=pending_ticks,
            p17_forecast_ids_to_skip=seen_p17,
        )
        seen_p17.update(fc.forecast_id for fc in causal_fc)
        for key, cnt in summary.outcome_counts:
            oc = run_stats.setdefault("outcomes", {})
            oc[key] = oc.get(key, 0) + cnt
        for key, cnt in summary.degradation_counts:
            dc = run_stats.setdefault("degradations", {})
            dc[key] = dc.get(key, 0) + cnt
        return summary.decisions_logged
    return _runner


def build_session_plan(
    session_dir: Path, *, safety_config: Path, cadence_sec: float, replay_delay_ms: int
) -> Dict[str, Any]:
    """Build deterministic read-only replay plan dict for one P13 session directory."""
    safety = load_gateway_safety_config(safety_config)
    loaded = load_p13_session_readonly(session_dir)
    ts_list = [ensure_utc_datetime(e.payload.recv_ts_utc, field_name="p13.recv_ts_utc") for e in loaded.envelopes]
    ticks = generate_synthetic_clock_ticks(min(ts_list), max(ts_list), cadence_sec) if ts_list else ()
    return {
        "mode": "OFFLINE_P13_REPLAY_ONLY", "capture_replay_mode": "REPLAY_P13",
        "session_id": session_dir.name, "execution_mode": safety.execution_mode,
        "clob_host_wired": safety.clob_host, "enable_official_fee_rate_probe_default": False,
        "fee_rate_timeout_sec": 0.5, "p13_valid_frames": loaded.summary.valid_frames,
        "p13_corrupt_lines": len(loaded.summary.corrupt_lines), "cadence_sec": cadence_sec,
        "replay_delay_ms": replay_delay_ms, "planned_ticks": len(ticks),
    }


def _resolve_target_sessions(args: argparse.Namespace) -> Tuple[Path, ...]:
    if getattr(args, "active_session", False):
        return (discover_active_p13_session(args.recordings_root),)
    if args.all_completed_sessions:
        return discover_completed_p13_sessions(args.recordings_root)
    if args.p13_session_dir is not None:
        return (args.p13_session_dir,)
    raise ValueError("Provide --p13-session-dir, --all-completed-sessions, or --active-session")


def _run_execute_cycle(
    sessions: Sequence[Path], *, args: argparse.Namespace, audit_root: Path,
    session_runner: Callable[[Path, Tuple[datetime, ...], Path], int],
    run_stats: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    watermark = load_watermark(audit_root)
    start_cutoff = parse_utc_timestamp(args.start_from_utc, field_name="start_from_utc") if getattr(args, "start_from_utc", None) else None
    processed_sessions, new_ticks_total, skipped_corrupt = 0, 0, 0
    for sess_dir in sessions:
        loaded = load_p13_session_readonly(sess_dir)
        if loaded.summary.corrupt_lines:
            skipped_corrupt += 1
            continue
        if not loaded.envelopes:
            continue
        ts_list = [ensure_utc_datetime(e.payload.recv_ts_utc, field_name="p13.recv_ts_utc") for e in loaded.envelopes]
        all_ticks = generate_synthetic_clock_ticks(min(ts_list), max(ts_list), args.cadence_sec)
        last_iso = watermark.get(sess_dir.name)
        pending = filter_unprocessed_ticks(all_ticks, last_iso) if last_iso or start_cutoff is None else tuple(t for t in all_ticks if t >= start_cutoff)
        if not pending:
            continue
        new_ticks_total += int(session_runner(sess_dir, pending, audit_root))
        watermark[sess_dir.name] = pending[-1].isoformat()
        processed_sessions += 1
    save_watermark(audit_root, watermark)
    return {
        "status": "OK", "processed_sessions": processed_sessions,
        "new_ticks_processed": new_ticks_total, "skipped_corrupt_sessions": skipped_corrupt,
        "watermark_sessions": len(watermark), "stats": run_stats or {},
    }


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect/run S3-11 offline P13 replay schedule (zero live trading).")
    parser.add_argument("--p13-session-dir", type=Path, default=None)
    parser.add_argument("--all-completed-sessions", action="store_true")
    parser.add_argument("--active-session", action="store_true")
    parser.add_argument("--recordings-root", type=Path, default=DEFAULT_RECORDINGS_ROOT)
    parser.add_argument("--safety-config", type=Path, default=DEFAULT_GATEWAY_CONFIG_PATH)
    parser.add_argument("--audit-output-root", type=Path, default=None)
    parser.add_argument("--p5-dir", type=Path, default=None)
    parser.add_argument("--policy-ledger-path", type=Path, default=None)
    parser.add_argument("--start-from-utc", type=str, default=None)
    parser.add_argument("--cadence-sec", type=float, default=60.0)
    parser.add_argument("--replay-delay-ms", type=int, default=0)
    parser.add_argument("--dry-run-plan", action="store_true", default=False)
    parser.add_argument("--execute", action="store_true", default=False)
    parser.add_argument("--watch-interval-sec", type=float, default=None)
    return parser.parse_args(argv)


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    session_runner: Optional[Callable[[Path, Tuple[datetime, ...], Path], int]] = None,
    max_watch_cycles: Optional[int] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> int:
    args = _parse_args(argv)
    sessions = _resolve_target_sessions(args)
    if not args.execute:
        plans = [build_session_plan(s, safety_config=args.safety_config, cadence_sec=args.cadence_sec, replay_delay_ms=args.replay_delay_ms) for s in sessions]
        print(json.dumps(plans[0] if (len(plans) == 1 and not args.all_completed_sessions) else {"sessions": plans}, indent=2, ensure_ascii=False))
        return 0
    if args.audit_output_root is None:
        raise ValueError("--execute requires --audit-output-root")
    audit_root = validate_audit_output_root(args.audit_output_root, args.recordings_root)
    run_stats: Dict[str, Any] = {}
    active_runner = session_runner or _build_real_session_runner(args, audit_root=audit_root, run_stats=run_stats)
    if active_runner is None:
        print(json.dumps({"status": "BLOCKED_MISSING_REAL_INPUTS", "reason": "Real M1/M2 P5 forecast stream and S2-02 friction_median P6 bundle are not yet provisioned.", "audit_output_root": str(audit_root), "sessions_discovered": len(sessions), "replay_delay_ms": args.replay_delay_ms}, indent=2, ensure_ascii=False))
        return 2
    cycles, last_summary = 0, {}
    while True:
        last_summary = _run_execute_cycle(_resolve_target_sessions(args), args=args, audit_root=audit_root, session_runner=active_runner, run_stats=run_stats)
        print(json.dumps(last_summary, ensure_ascii=False), flush=True)
        cycles += 1
        if args.watch_interval_sec is None or (max_watch_cycles is not None and cycles >= max_watch_cycles):
            break
        sleep_fn(float(args.watch_interval_sec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
