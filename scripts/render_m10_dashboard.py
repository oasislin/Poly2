#!/usr/bin/env python3
"""Render standalone read-only `M10 v1` monitoring HTML purely from `M7` audit logs."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.execution.clob_gateway import DEFAULT_GATEWAY_CONFIG_PATH, ExecutionMode
from src.ui.m10_view import build_m10_dashboard_model, render_m10_dashboard_html


def _parse_date(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    return date.fromisoformat(raw)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Render strictly read-only M10 v1 HTML dashboard.")
    parser.add_argument("--audit-root", type=Path, required=True, help="Root directory of M7 JSONL audit logs.")
    parser.add_argument(
        "--execution-mode",
        choices=("PAPER", "LIVE"),
        default="PAPER",
        help="Execution mode stream to query (default: PAPER).",
    )
    parser.add_argument(
        "--safety-config",
        type=Path,
        default=DEFAULT_GATEWAY_CONFIG_PATH,
        help="Path to gateway safety YAML config.",
    )
    parser.add_argument("--utc-date", type=str, default=None, help="Optional UTC filter date YYYY-MM-DD.")
    parser.add_argument("--session-id", type=str, default=None, help="Optional session_id filter.")
    parser.add_argument("--station-id", type=str, default=None, help="Optional station_id filter.")
    parser.add_argument("--p13-root", type=Path, default=None, help="Optional P13 recordings root.")
    parser.add_argument("--model-hash", type=str, default=None, help="Optional explicit model hash.")
    parser.add_argument(
        "--model-unfrozen",
        action="store_true",
        help="Mark model freeze badge as UNFROZEN instead of default FROZEN.",
    )
    parser.add_argument(
        "--alerts-status",
        type=Path,
        default=None,
        help="Optional read-only path to watchdog_status.json for top watchdog summary badges.",
    )
    parser.add_argument("--output", type=Path, required=True, help="Output standalone HTML path (must be outside audit-root).")
    args = parser.parse_args(argv)

    audit_resolved = args.audit_root.resolve()
    out_resolved = args.output.resolve()
    if out_resolved == audit_resolved or audit_resolved in out_resolved.parents:
        raise ValueError(f"--output ({out_resolved}) must not reside inside --audit-root ({audit_resolved})")

    mode: ExecutionMode = args.execution_mode
    model = build_m10_dashboard_model(
        audit_root=args.audit_root,
        execution_mode=mode,
        safety_config_path=args.safety_config,
        utc_date=_parse_date(args.utc_date),
        session_id=args.session_id,
        station_id=args.station_id,
        p13_root=args.p13_root,
        model_hash=args.model_hash,
        model_frozen=not args.model_unfrozen,
        alerts_status_path=args.alerts_status,
    )
    html_text = render_m10_dashboard_html(model)
    out_resolved.parent.mkdir(parents=True, exist_ok=True)
    out_resolved.write_text(html_text, encoding="utf-8")
    print(
        f"Rendered M10 v1 HTML -> {out_resolved} "
        f"(mode={model.execution_mode}, render_status={model.render_status}, "
        f"settlement_status={model.settlement_status}, chains={len(model.decision_rows)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
