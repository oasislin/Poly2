"""CLI entrypoint for `S3-14` PAPER Trial Runner (`start`, `stop`, `status`, `preflight`, `reconcile`, `self-test`)."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import sys
import time
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.audit.audit_logger import AsyncAuditLogger
from src.audit.p10_reader import read_verified_jsonl_file
from src.execution.clob_gateway import DEFAULT_GATEWAY_CONFIG_PATH
from src.execution.trial_runner import (
    read_runner_state,
    run_cli_self_test,
    run_preflight_checks,
    write_runner_state,
)


def _pid_alive(pid: Optional[int]) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _cmd_preflight(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir)
    with AsyncAuditLogger(state_dir / "m7", execution_mode="PAPER") as logger:
        report = run_preflight_checks(
            safety_config_path=Path(args.safety_config),
            audit_logger=logger,
            rpc_url=args.rpc_url,
            owner_address=args.owner_address,
        )
    print(json.dumps(report.to_dict(), sort_keys=True))
    return 0 if report.ok else 1


def _cmd_self_test(args: argparse.Namespace) -> int:
    res = run_cli_self_test(safety_config_path=Path(args.safety_config), state_dir=Path(args.state_dir))
    print(json.dumps(res, sort_keys=True))
    return 0 if res.get("ok") else 1


def _cmd_start(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir)
    safety_cfg = Path(args.safety_config)
    now = datetime.now(timezone.utc).isoformat()
    if args.once:
        res = run_cli_self_test(safety_config_path=safety_cfg, state_dir=state_dir)
        state = {
            "status": "COMPLETED_ONCE" if res.get("ok") else "FAILED",
            "pid": os.getpid(),
            "execution_mode": "PAPER",
            "started_ts_utc": now,
            "updated_ts_utc": datetime.now(timezone.utc).isoformat(),
            "ok": bool(res.get("ok")),
        }
        write_runner_state(state_dir, state)
        print(json.dumps({"state": state, "result": res}, sort_keys=True))
        return 0 if res.get("ok") else 1

    running = {"stop": False}

    def _handle_sig(_signum: int, _frame: object) -> None:
        running["stop"] = True

    signal.signal(signal.SIGTERM, _handle_sig)
    signal.signal(signal.SIGINT, _handle_sig)
    res = run_cli_self_test(safety_config_path=safety_cfg, state_dir=state_dir)
    state: Dict[str, Any] = {
        "status": "RUNNING" if res.get("ok") else "FAILED",
        "pid": os.getpid(),
        "execution_mode": "PAPER",
        "started_ts_utc": now,
        "updated_ts_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_runner_state(state_dir, state)
    print(json.dumps(state, sort_keys=True), flush=True)
    if not res.get("ok"):
        return 1
    while not running["stop"]:
        time.sleep(0.5)
    state["status"] = "STOPPED"
    state["stopped_ts_utc"] = datetime.now(timezone.utc).isoformat()
    write_runner_state(state_dir, state)
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    state = read_runner_state(Path(args.state_dir))
    if state.get("status") == "RUNNING" and not _pid_alive(state.get("pid")):
        state["status"] = "STALE_NOT_RUNNING"
    print(json.dumps(state, sort_keys=True))
    return 0


def _cmd_stop(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir)
    state = read_runner_state(state_dir)
    pid = state.get("pid")
    if state.get("status") == "RUNNING" and _pid_alive(pid) and pid != os.getpid():
        os.kill(int(pid), signal.SIGTERM)
    state["status"] = "STOPPED"
    state["stopped_ts_utc"] = datetime.now(timezone.utc).isoformat()
    write_runner_state(state_dir, state)
    print(json.dumps(state, sort_keys=True))
    return 0


def _cmd_reconcile(args: argparse.Namespace) -> int:
    audit_root = Path(args.audit_root)
    p3_files = sorted((audit_root / "PAPER").glob("*/p3_execution_attempts.jsonl"))
    corrupt_total = 0
    attempt_total = 0
    for path in p3_files:
        stream = read_verified_jsonl_file(path, verify_sha256=True)
        corrupt_total += len(stream.corrupt_lines)
        attempt_total += sum(1 for r in stream.records if r.get("schema_version") == "p3.v1")
    out = {
        "ok": corrupt_total == 0,
        "p3_files_checked": len(p3_files),
        "p3_attempt_count": attempt_total,
        "corrupt_p3_lines": corrupt_total,
    }
    print(json.dumps(out, sort_keys=True))
    return 0 if corrupt_total == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Polymarket Weather S3-14 PAPER Trial Runner")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("preflight", "self-test", "start", "status", "stop", "reconcile"):
        p = sub.add_parser(name)
        p.add_argument("--safety-config", default=str(DEFAULT_GATEWAY_CONFIG_PATH))
        p.add_argument("--state-dir", default="data/trial_runner")
        if name == "preflight":
            p.add_argument("--rpc-url", default=None)
            p.add_argument("--owner-address", default=None)
        elif name == "start":
            p.add_argument("--once", action="store_true")
        elif name == "reconcile":
            p.add_argument("--audit-root", default="data/trial_runner/m7")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    dispatch = {
        "preflight": _cmd_preflight,
        "self-test": _cmd_self_test,
        "start": _cmd_start,
        "status": _cmd_status,
        "stop": _cmd_stop,
        "reconcile": _cmd_reconcile,
    }
    return dispatch[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
