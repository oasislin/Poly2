#!/usr/bin/env python3
"""S3-11 Offline P13 Delayed-Replay Scheduler CLI (no live/paper trading endpoints)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Optional, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.audit.p13_reader import load_p13_session_readonly
from src.decision.offline_scheduler import OfflineSchedulerConfig, generate_synthetic_clock_ticks
from src.execution.clob_gateway import DEFAULT_GATEWAY_CONFIG_PATH, load_gateway_safety_config
from src.utils.causal_utils import ensure_utc_datetime


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect/plan S3-11 offline P13 replay schedule (zero live trading).")
    parser.add_argument("--p13-session-dir", type=Path, required=True, help="Recorded P13 session directory.")
    parser.add_argument("--safety-config", type=Path, default=DEFAULT_GATEWAY_CONFIG_PATH)
    parser.add_argument("--cadence-sec", type=float, default=60.0)
    parser.add_argument("--replay-delay-ms", type=int, default=0)
    parser.add_argument("--dry-run-plan", action="store_true", default=True)
    args = parser.parse_args(argv)

    safety = load_gateway_safety_config(args.safety_config)
    loaded = load_p13_session_readonly(args.p13_session_dir)
    if loaded.envelopes:
        ts_list = [ensure_utc_datetime(e.payload.recv_ts_utc, field_name="p13.recv_ts_utc") for e in loaded.envelopes]
        ticks = generate_synthetic_clock_ticks(min(ts_list), max(ts_list), args.cadence_sec)
    else:
        ticks = ()
    plan = {
        "mode": "OFFLINE_P13_REPLAY_ONLY",
        "capture_replay_mode": "REPLAY_P13",
        "execution_mode": safety.execution_mode,
        "clob_host_wired": safety.clob_host,
        "enable_official_fee_rate_probe_default": False,
        "fee_rate_timeout_sec": 0.5,
        "p13_valid_frames": loaded.summary.valid_frames,
        "p13_corrupt_lines": len(loaded.summary.corrupt_lines),
        "cadence_sec": args.cadence_sec,
        "replay_delay_ms": args.replay_delay_ms,
        "planned_ticks": len(ticks),
    }
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
