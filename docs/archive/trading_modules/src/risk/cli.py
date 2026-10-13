"""
Command-Line Interface for Emergency Control and Station Operations (Phase 2 Task 03 - Ticket 04 / Issue #74).
Provides commands to stop, resume, and inspect emergency kill-switch status.
Usage:
    python -m src.risk.cli stop <STATION | ALL> [--root-dir <PATH>]
    python -m src.risk.cli resume <STATION | ALL> [--root-dir <PATH>]
    python -m src.risk.cli status [--root-dir <PATH>]
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from src.data_processing.constants import ACTIVE_10_STATIONS
from src.risk.emergency_control import EmergencyFileSentinel

VALID_TARGETS = set(ACTIVE_10_STATIONS) | {"ALL", "GLOBAL"}


def run_cli(args: Optional[List[str]] = None) -> int:
    """Entrypoint for risk CLI commands. Returns process exit code (0 = success, 1 = failure)."""
    # Parent parser for shared options
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument(
        "--root-dir",
        type=str,
        default=None,
        help="Root directory where emergency sentinel files reside (default: cwd)",
    )

    parser = argparse.ArgumentParser(
        prog="risk-cli",
        description="Risk Management and Emergency Kill-Switch CLI",
        parents=[parent_parser],
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # stop command
    stop_parser = subparsers.add_parser(
        "stop", help="Trigger emergency stop for station or ALL", parents=[parent_parser]
    )
    stop_parser.add_argument("target", type=str, help="Station ID (e.g. KORD) or ALL")

    # resume command
    resume_parser = subparsers.add_parser(
        "resume", help="Resume emergency stop for station or ALL", parents=[parent_parser]
    )
    resume_parser.add_argument("target", type=str, help="Station ID (e.g. KORD) or ALL")

    # status command
    subparsers.add_parser(
        "status", help="Show current active emergency sentinels", parents=[parent_parser]
    )

    try:
        parsed = parser.parse_args(args)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1

    if not parsed.command:
        parser.print_help()
        return 1

    root_path = Path(parsed.root_dir) if parsed.root_dir else Path.cwd()
    sentinel = EmergencyFileSentinel(root_dir=root_path)

    if parsed.command == "stop":
        target = parsed.target.upper()
        if target not in VALID_TARGETS:
            print(f"Error: Invalid target '{target}'. Must be one of {sorted(VALID_TARGETS)}", file=sys.stderr)
            return 1

        sentinel.create_sentinel(target)
        print(f"EMERGENCY STOP initiated for station '{target}'! Sentinel file created.")
        return 0

    elif parsed.command == "resume":
        target = parsed.target.upper()
        if target not in VALID_TARGETS:
            print(f"Error: Invalid target '{target}'. Must be one of {sorted(VALID_TARGETS)}", file=sys.stderr)
            return 1

        removed = sentinel.remove_sentinel(target)
        if removed:
            print(f"Resumed station '{target}'. Sentinel file removed.")
        else:
            print(f"No active sentinel file found for station '{target}'.")
        return 0

    elif parsed.command == "status":
        active = sentinel.list_active_sentinels()
        print("=== Active Emergency Sentinel Markers ===")
        if not active:
            print("  No active emergency sentinels. All clear.")
        else:
            for s in active:
                print(f"  [HALTED] {s}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv[1:]))
