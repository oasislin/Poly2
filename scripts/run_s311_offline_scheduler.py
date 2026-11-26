#!/usr/bin/env python3
"""S3-11 Offline P13 Delayed-Replay Scheduler CLI (no live/paper trading endpoints).

Supports:
- `--dry-run-plan` (default): read-only schedule inspection without writing audit logs.
- `--execute`: fail-closed execution entry point (requires `--audit-output-root` isolated
  outside repo code/docs/recordings; blocks when real P5/P6 inputs are absent).
- `--all-completed-sessions`: discovers all completed `PASSIVE_RECORD` sessions under
  `--recordings-root` (excluding active `latest_session.json` session_id).
- `--watch-interval-sec`: periodic watch loop with atomic watermark deduplication
  (`<audit_output_root>/.s311_watermark.json`).
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.audit.p13_reader import load_p13_session_readonly
from src.decision.offline_scheduler import generate_synthetic_clock_ticks
from src.execution.clob_gateway import DEFAULT_GATEWAY_CONFIG_PATH, load_gateway_safety_config
from src.utils.causal_utils import ensure_utc_datetime

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
        _REPO_ROOT / "src",
        _REPO_ROOT / "docs" / "audit",
        _REPO_ROOT / "evidence",
        recordings_root.resolve(),
    )
    for blocked in forbidden:
        if _is_subpath(resolved, blocked):
            raise ValueError(f"audit_output_root must be isolated from {blocked}: got {resolved}")
    return resolved


def discover_completed_p13_sessions(
    recordings_root: Path = DEFAULT_RECORDINGS_ROOT,
) -> Tuple[Path, ...]:
    """Discover completed `PASSIVE_RECORD` session dirs (excluding active pointer)."""
    active_sid: Optional[str] = None
    ptr = recordings_root / "latest_session.json"
    if ptr.exists():
        try:
            active_sid = json.loads(ptr.read_text(encoding="utf-8")).get("session_id")
        except Exception:
            active_sid = None
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


def filter_unprocessed_ticks(
    ticks: Sequence[datetime], last_processed_iso: Optional[str]
) -> Tuple[datetime, ...]:
    """Return strictly newer UTC ticks than `last_processed_iso` for watermark dedup."""
    if not last_processed_iso:
        return tuple(ticks)
    cutoff = ensure_utc_datetime(datetime.fromisoformat(last_processed_iso), field_name="watermark.last_tick")
    return tuple(t for t in ticks if ensure_utc_datetime(t, field_name="tick") > cutoff)


def build_session_plan(
    session_dir: Path, *, safety_config: Path, cadence_sec: float, replay_delay_ms: int
) -> Dict[str, Any]:
    """Build deterministic read-only replay plan dict for one P13 session directory."""
    safety = load_gateway_safety_config(safety_config)
    loaded = load_p13_session_readonly(session_dir)
    if loaded.envelopes:
        ts_list = [ensure_utc_datetime(e.payload.recv_ts_utc, field_name="p13.recv_ts_utc") for e in loaded.envelopes]
        ticks = generate_synthetic_clock_ticks(min(ts_list), max(ts_list), cadence_sec)
    else:
        ticks = ()
    return {
        "mode": "OFFLINE_P13_REPLAY_ONLY",
        "capture_replay_mode": "REPLAY_P13",
        "session_id": session_dir.name,
        "execution_mode": safety.execution_mode,
        "clob_host_wired": safety.clob_host,
        "enable_official_fee_rate_probe_default": False,
        "fee_rate_timeout_sec": 0.5,
        "p13_valid_frames": loaded.summary.valid_frames,
        "p13_corrupt_lines": len(loaded.summary.corrupt_lines),
        "cadence_sec": cadence_sec,
        "replay_delay_ms": replay_delay_ms,
        "planned_ticks": len(ticks),
    }


def _resolve_target_sessions(args: argparse.Namespace) -> Tuple[Path, ...]:
    if args.all_completed_sessions:
        return discover_completed_p13_sessions(args.recordings_root)
    if args.p13_session_dir is not None:
        return (args.p13_session_dir,)
    raise ValueError("Provide either --p13-session-dir or --all-completed-sessions")


def _run_execute_cycle(
    sessions: Sequence[Path],
    *,
    args: argparse.Namespace,
    audit_root: Path,
    session_runner: Callable[[Path, Tuple[datetime, ...], Path], int],
) -> Dict[str, Any]:
    watermark = load_watermark(audit_root)
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
        pending = filter_unprocessed_ticks(all_ticks, watermark.get(sess_dir.name))
        if not pending:
            continue
        new_ticks_total += int(session_runner(sess_dir, pending, audit_root))
        watermark[sess_dir.name] = pending[-1].isoformat()
        processed_sessions += 1
    save_watermark(audit_root, watermark)
    return {
        "status": "OK",
        "processed_sessions": processed_sessions,
        "new_ticks_processed": new_ticks_total,
        "skipped_corrupt_sessions": skipped_corrupt,
        "watermark_sessions": len(watermark),
    }


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect/run S3-11 offline P13 replay schedule (zero live trading).")
    parser.add_argument("--p13-session-dir", type=Path, default=None, help="Single recorded P13 session directory.")
    parser.add_argument("--all-completed-sessions", action="store_true", help="Scan all completed PASSIVE_RECORD sessions.")
    parser.add_argument("--recordings-root", type=Path, default=DEFAULT_RECORDINGS_ROOT)
    parser.add_argument("--safety-config", type=Path, default=DEFAULT_GATEWAY_CONFIG_PATH)
    parser.add_argument("--audit-output-root", type=Path, default=None, help="Isolated output root for p1.v3/p17.v3.")
    parser.add_argument("--cadence-sec", type=float, default=60.0)
    parser.add_argument("--replay-delay-ms", type=int, default=0, help="Causal book lag ms (D1=0: recv_ts <= tick_utc).")
    parser.add_argument("--dry-run-plan", action="store_true", default=False)
    parser.add_argument("--execute", action="store_true", default=False, help="Run fail-closed execution mode.")
    parser.add_argument("--watch-interval-sec", type=float, default=None, help="Periodic watch interval in seconds.")
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
        plans = [
            build_session_plan(
                s, safety_config=args.safety_config, cadence_sec=args.cadence_sec, replay_delay_ms=args.replay_delay_ms
            )
            for s in sessions
        ]
        out: Any = plans[0] if (len(plans) == 1 and not args.all_completed_sessions) else {"sessions": plans}
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    if args.audit_output_root is None:
        raise ValueError("--execute requires --audit-output-root")
    audit_root = validate_audit_output_root(args.audit_output_root, args.recordings_root)
    if session_runner is None:
        blocked = {
            "status": "BLOCKED_MISSING_REAL_INPUTS",
            "reason": "Real M1/M2 P5 forecast stream and S2-02 friction_median P6 bundle are not yet provisioned.",
            "audit_output_root": str(audit_root),
            "sessions_discovered": len(sessions),
            "replay_delay_ms": args.replay_delay_ms,
        }
        print(json.dumps(blocked, indent=2, ensure_ascii=False))
        return 2
    cycles, last_summary = 0, {}
    while True:
        last_summary = _run_execute_cycle(
            _resolve_target_sessions(args), args=args, audit_root=audit_root, session_runner=session_runner
        )
        cycles += 1
        if args.watch_interval_sec is None or (max_watch_cycles is not None and cycles >= max_watch_cycles):
            break
        sleep_fn(float(args.watch_interval_sec))
    print(json.dumps(last_summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
