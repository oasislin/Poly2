#!/usr/bin/env python3
"""Read-only S3-16 ECE Pilot CLI outputting Markdown report under `docs/audit/`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Optional, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.calibration.ece_evaluator import (
    EceEvaluationConfig,
    evaluate_ece_from_directories,
    render_ece_pilot_markdown,
)


def summarize_stale_watch_trend(scheduler_log: Path) -> str:
    """Read-only summary of `STALE_OR_MISSING_BOTH_LEGS` rejection ratio across scheduler watch cycles."""
    if not scheduler_log.exists():
        return "No scheduler.log present."
    cycles = [json.loads(line) for line in scheduler_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    active = [c for c in cycles if int(c.get("new_ticks_processed", 0)) > 0]
    if not active:
        return f"Observed {len(cycles)} scheduler poll(s), 0 processed ticks yet."
    rates = []
    prev_tot, prev_stale = 0, 0
    for c in active:
        cum_tot = sum(int(v) for v in c.get("stats", {}).get("outcomes", {}).values())
        cum_stale = int(c.get("stats", {}).get("degradations", {}).get("STALE_OR_MISSING_BOTH_LEGS", 0))
        d_tot, d_stale = max(1, cum_tot - prev_tot), max(0, cum_stale - prev_stale)
        rates.append(d_stale / d_tot)
        prev_tot, prev_stale = cum_tot, cum_stale
    cum_rate = prev_stale / max(1, prev_tot)
    return (
        f"Active cycles={len(active)}/{len(cycles)} | cycle_stale_rate min={min(rates):.2%}, "
        f"first={rates[0]:.2%}, latest={rates[-1]:.2%}, max={max(rates):.2%} | "
        f"cumulative={prev_stale}/{prev_tot} ({cum_rate:.2%})."
    )


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run read-only S3-16 ECE evaluation / pilot report.")
    parser.add_argument("--audit-root", type=Path, default=_REPO_ROOT / "data" / "audit_logs")
    parser.add_argument("--live-p5-dir", type=Path, default=_REPO_ROOT / "data" / "live_p5")
    parser.add_argument("--scheduler-log", type=Path, default=_REPO_ROOT / "data" / "audit_logs" / "scheduler.log")
    parser.add_argument("--num-prob-bins", type=int, default=10)
    parser.add_argument("--min-settled-markets", type=int, default=30)
    parser.add_argument("--non-pilot", action="store_true", default=False)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    cfg = EceEvaluationConfig(
        num_prob_bins=args.num_prob_bins,
        min_settled_markets=args.min_settled_markets,
        is_pilot=not args.non_pilot,
    )
    reports = evaluate_ece_from_directories(
        audit_root=args.audit_root, live_p5_dir=args.live_p5_dir, config=cfg
    )
    trend = summarize_stale_watch_trend(args.scheduler_log)
    md = render_ece_pilot_markdown(reports, stale_trend_summary=trend)
    if args.output is not None:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
