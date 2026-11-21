#!/usr/bin/env python3
"""Daily 00:05Z graceful rotation supervisor CLI for M3 passive orderbook recorder (`S2-01`).

Rotates `scripts/run_passive_book_recorder.py` once per UTC day at `--rotate-utc` (default `00:05`):
1. Sends SIGTERM to the active child recorder, triggering `stop_event.set()` in
   `scripts/run_passive_book_recorder.py` so `run_ws_loop` exits immediately without spurious gap
   polling and executes `recorder.flush_and_close()`.
2. Waits for clean exit and starts a new child process with a fresh UTC-stamped `session_id`
   so `AsyncJsonlSink` rotates cleanly under `<output_root>/<capture_mode>/<YYYY-MM-DD>/<session_id>/`
   and re-runs Gamma market discovery for newly listed daily markets.

Safety: NEVER executes automatically on import; run explicitly after user launch approval.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple
import uuid

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
RECORDER_SCRIPT = REPO_ROOT / "scripts" / "run_passive_book_recorder.py"

logger = logging.getLogger(__name__)


def parse_utc_hhmm(raw: str) -> Tuple[int, int]:
    """Parse `HH:MM` UTC cutover specification strictly."""
    parts = raw.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Expected HH:MM UTC cutover format, got {raw!r}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"UTC hour/minute out of bounds: {raw!r}")
    return hour, minute


def compute_next_cutover_utc(
    now_utc: datetime,
    cutover_hour: int = 0,
    cutover_minute: int = 5,
) -> datetime:
    """Return the next strict-future UTC cutover timestamp at `HH:MM:00Z`."""
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)
    candidate = now_utc.replace(
        hour=cutover_hour,
        minute=cutover_minute,
        second=0,
        microsecond=0,
    )
    if now_utc >= candidate:
        candidate += timedelta(days=1)
    return candidate


def generate_session_id(
    now_utc: Optional[datetime] = None,
    prefix: str = "rec",
) -> str:
    """Generate a unique UTC-timestamped session_id for day-partitioned P13 recording."""
    ts = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return f"{prefix}-{ts.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"


def stop_child_gracefully(
    proc: subprocess.Popen[Any],
    graceful_timeout_sec: float = 20.0,
) -> int:
    """Send SIGTERM (triggering stop_event + flush_and_close) and escalate only on timeout."""
    if proc.poll() is None:
        proc.terminate()
        try:
            return proc.wait(timeout=graceful_timeout_sec)
        except subprocess.TimeoutExpired:
            logger.warning(
                "Child PID %s did not exit within %.1fs after SIGTERM; forcing SIGKILL",
                proc.pid,
                graceful_timeout_sec,
            )
            proc.kill()
            return proc.wait(timeout=5.0)
    return proc.returncode if proc.returncode is not None else 0


def build_child_command(
    config_path: Path,
    session_id: str,
    python_executable: str = sys.executable,
    recorder_script: Path = RECORDER_SCRIPT,
) -> list[str]:
    """Build exact subprocess CLI command for a single passive recorder session."""
    return [
        python_executable,
        str(recorder_script),
        "--config",
        str(config_path),
        "--session-id",
        session_id,
    ]


def resolve_output_root_from_config(config_path: Path) -> Path:
    """Resolve `recording.output_root` from recorder YAML config without modifying files."""
    if not config_path.exists():
        return REPO_ROOT / "data" / "market_recordings"
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    rec = raw.get("recording") or {}
    raw_root = Path(str(rec.get("output_root", "data/market_recordings")))
    return raw_root if raw_root.is_absolute() else (REPO_ROOT / raw_root)


def write_latest_session_pointer(
    output_root: Path,
    session_id: str,
    started_at_utc: datetime,
    next_cutover_utc: datetime,
    config_path: Path,
    child_pid: Optional[int],
    supervisor_pid: Optional[int] = None,
) -> Path:
    """Atomically write `<output_root>/latest_session.json` on each session start/rotation."""
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / "latest_session.json"
    tmp_path = output_root / f".latest_session.{os.getpid()}.tmp"
    payload = {
        "schema_version": "latest_session.v1",
        "session_id": session_id,
        "started_at_utc": started_at_utc.astimezone(timezone.utc).isoformat(),
        "next_cutover_utc": next_cutover_utc.astimezone(timezone.utc).isoformat(),
        "config_path": str(config_path),
        "supervisor_pid": supervisor_pid if supervisor_pid is not None else os.getpid(),
        "child_pid": child_pid,
    }
    tmp_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp_path, target)
    return target


def _wait_active_cycle(
    active_proc: subprocess.Popen[Any],
    session_id: str,
    next_cutover: datetime,
    *,
    stop_flag: Callable[[], bool],
    graceful_timeout_sec: float,
    crash_backoff_sec: float,
    poll_interval_sec: float,
    now_fn: Callable[[], datetime],
    sleep_fn: Callable[[float], None],
) -> None:
    while not stop_flag():
        rc = active_proc.poll()
        if rc is not None:
            logger.warning(
                "Child session_id=%s exited early with rc=%s; restarting after %.1fs",
                session_id,
                rc,
                crash_backoff_sec,
            )
            sleep_fn(crash_backoff_sec)
            return
        cur_utc = now_fn()
        if cur_utc >= next_cutover:
            logger.info(
                "Reached daily cutover %s; sending SIGTERM to session_id=%s (flush_and_close)",
                next_cutover.isoformat(),
                session_id,
            )
            rc_stop = stop_child_gracefully(active_proc, graceful_timeout_sec=graceful_timeout_sec)
            logger.info("Session %s stopped cleanly (rc=%s)", session_id, rc_stop)
            return
        sleep_dur = min(poll_interval_sec, max(0.05, (next_cutover - cur_utc).total_seconds()))
        sleep_fn(sleep_dur)


def run_daily_supervisor(
    config_path: Path,
    cutover_hhmm: str = "00:05",
    graceful_timeout_sec: float = 20.0,
    crash_backoff_sec: float = 5.0,
    poll_interval_sec: float = 1.0,
    max_cycles: Optional[int] = None,
    output_root: Optional[Path] = None,
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    popen_fn: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> int:
    """Supervise `run_passive_book_recorder.py` with daily UTC cutover and graceful rotation."""
    cut_hour, cut_min = parse_utc_hhmm(cutover_hhmm)
    resolved_output_root = (
        output_root if output_root is not None else resolve_output_root_from_config(config_path)
    )
    stop_requested = False
    active_proc: Optional[subprocess.Popen[Any]] = None

    def _on_signal(signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        logger.info("Supervisor received signal %s; stopping active session gracefully", signum)
        stop_requested = True
        if active_proc is not None and active_proc.poll() is None:
            active_proc.terminate()

    prev_sigint, prev_sigterm = signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    cycles = 0
    try:
        while not stop_requested and (max_cycles is None or cycles < max_cycles):
            now_utc = now_fn()
            next_cutover = compute_next_cutover_utc(now_utc, cut_hour, cut_min)
            session_id = generate_session_id(now_utc)
            cmd = build_child_command(config_path=config_path, session_id=session_id)
            logger.info("Starting cycle=%d session_id=%s next_cutover_utc=%s", cycles + 1, session_id, next_cutover.isoformat())
            active_proc = popen_fn(cmd, cwd=str(REPO_ROOT))
            write_latest_session_pointer(
                output_root=resolved_output_root, session_id=session_id, started_at_utc=now_utc,
                next_cutover_utc=next_cutover, config_path=config_path, child_pid=getattr(active_proc, "pid", None),
            )
            cycles += 1
            _wait_active_cycle(
                active_proc, session_id, next_cutover, stop_flag=lambda: stop_requested,
                graceful_timeout_sec=graceful_timeout_sec, crash_backoff_sec=crash_backoff_sec,
                poll_interval_sec=poll_interval_sec, now_fn=now_fn, sleep_fn=sleep_fn,
            )
            if stop_requested and active_proc is not None and active_proc.poll() is None:
                stop_child_gracefully(active_proc, graceful_timeout_sec=graceful_timeout_sec)
            active_proc = None
    finally:
        if active_proc is not None and active_proc.poll() is None:
            stop_child_gracefully(active_proc, graceful_timeout_sec=graceful_timeout_sec)
        signal.signal(signal.SIGINT, prev_sigint)
        signal.signal(signal.SIGTERM, prev_sigterm)
    return 0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run M3 passive book recorder with daily 00:05Z graceful stop & session rotation"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/passive_book_recorder.example.yaml"),
        help="Path to passive recorder YAML config",
    )
    parser.add_argument(
        "--rotate-utc",
        type=str,
        default="00:05",
        help="Daily UTC rotation time HH:MM (default: 00:05)",
    )
    parser.add_argument(
        "--graceful-timeout-sec",
        type=float,
        default=20.0,
        help="Seconds to wait for child flush_and_close after SIGTERM before SIGKILL",
    )
    parser.add_argument(
        "--crash-backoff-sec",
        type=float,
        default=5.0,
        help="Delay before respawning if child exits unexpectedly",
    )
    parser.add_argument(
        "--dry-run-plan",
        action="store_true",
        help="Print computed next cutover UTC and sample session_id, then exit cleanly",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)
    cut_hour, cut_min = parse_utc_hhmm(args.rotate_utc)
    if args.dry_run_plan:
        now_utc = datetime.now(timezone.utc)
        next_cut = compute_next_cutover_utc(now_utc, cut_hour, cut_min)
        sample_sid = generate_session_id(now_utc)
        print(
            f"config={args.config} rotate_utc={args.rotate_utc}Z "
            f"next_cutover_utc={next_cut.isoformat()} sample_session_id={sample_sid}"
        )
        return 0
    return run_daily_supervisor(
        config_path=args.config,
        cutover_hhmm=args.rotate_utc,
        graceful_timeout_sec=args.graceful_timeout_sec,
        crash_backoff_sec=args.crash_backoff_sec,
    )


if __name__ == "__main__":
    raise SystemExit(main())
