#!/usr/bin/env python3
"""Read-only M3/M7/M10 4-class monitoring & alerting CLI (`S3-13`).

Strictly read-only over recordings/audit/M10 outputs; writes alerts strictly
under `--alerts-dir` (default `data/alerts/`). Exit code: 0=OK, 1=WARN, 2=CRITICAL.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Optional, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.audit.readonly_watchdog import (
    DEFAULT_ALERTS_DIR,
    DEFAULT_AUDIT_ROOT,
    DEFAULT_LEDGER_PATH,
    DEFAULT_RECORDINGS_ROOT,
    WatchdogConfig,
    run_watchdog_once,
)

_EXIT_CODES = {"OK": 0, "WARN": 1, "CRITICAL": 2}


def _format_human_summary(snapshot: dict) -> str:
    lines = [
        f"=== S3-13 Read-Only Watchdog ({snapshot['checked_ts_utc']}) ===",
        f"Overall Severity : {snapshot['overall_severity']} (planned_windows={snapshot['planned_windows_active']})",
    ]
    for name in ("gap_rate", "corrupt_lines", "token_coverage", "disk_watchdog"):
        chk = snapshot["checks"][name]
        lines.append(f"  - {name:14s}: {chk['status']} | scopes={len(chk['triggered_scopes'])}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run S3-13 read-only 4-class watchdog check.")
    parser.add_argument("--recordings-root", type=Path, default=DEFAULT_RECORDINGS_ROOT)
    parser.add_argument("--audit-root", type=Path, default=DEFAULT_AUDIT_ROOT)
    parser.add_argument("--alerts-dir", type=Path, default=DEFAULT_ALERTS_DIR)
    parser.add_argument("--ledger-path", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--m10-html", type=Path, default=None, help="Optional rendered M10 HTML CLI output to inspect.")
    parser.add_argument("--no-sha256", action="store_true", help="Skip SHA256 verification (default: verify).")
    parser.add_argument("--no-expect-recorder", action="store_true", help="Do not fail if recorder PID is offline.")
    parser.add_argument("--once", action="store_true", default=True, help="Execute single read-only pass (default).")
    parser.add_argument("--json", action="store_true", help="Print full watchdog_status.json payload.")
    args = parser.parse_args(argv)

    cfg = WatchdogConfig(
        recordings_root=args.recordings_root,
        audit_root=args.audit_root,
        alerts_dir=args.alerts_dir,
        ledger_path=args.ledger_path,
        m10_html_path=args.m10_html,
        verify_sha256=not args.no_sha256,
        expect_recorder_running=not args.no_expect_recorder,
    )
    snapshot = run_watchdog_once(cfg)
    if args.json:
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    else:
        print(_format_human_summary(snapshot))
    return _EXIT_CODES.get(str(snapshot["overall_severity"]), 2)


if __name__ == "__main__":
    raise SystemExit(main())
