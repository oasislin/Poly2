#!/usr/bin/env python3
"""S3-17 Persistent Online M1/M2 P5 Forecast Producer Daemon (6 stations x 5 GEFS members).

Zero order-execution imports or endpoints. Writes verified `p17.v3` JSONL records with
explicit `forecast_origin="REALTIME_LIVE_PULL"` to `--output-dir` (default `data/live_p5`).
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Callable, Dict, List, Optional, Sequence, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.data_acquisition.gefs_fetcher import VALID_MEMBERS
from src.data_acquisition.settlement_metar_stream import compute_local_day_window_utc, resolve_station_timezone
from src.prediction.forecast_distribution_engine import ExecutionMode
from src.prediction.live_p5_producer import (
    DEFAULT_GEFS_MEMBERS,
    LiveP5ProductionRecord,
    LiveP5Producer,
    LiveP5ProducerConfig,
    SUPPORTED_LIVE_STATIONS,
    discover_p13_market_ladders,
    resolve_latest_gefs_cycle_utc,
    serialize_p5_jsonl_record,
)

DEFAULT_RECORDINGS_ROOT = _REPO_ROOT / "data" / "market_recordings"
DEFAULT_LIVE_P5_DIR = _REPO_ROOT / "data" / "live_p5"


def _write_pid_file(pid_file: Optional[Path]) -> None:
    if pid_file is None:
        return
    target = Path(pid_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{os.getpid()}\n", encoding="utf-8")


def _append_p5_records(
    records: Sequence[LiveP5ProductionRecord], output_dir: Path, *, cycle_utc: datetime, execution_mode: ExecutionMode
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / f"p5_live_{cycle_utc.strftime('%Y%m%d')}.jsonl"
    sess_id = f"s317-live-{cycle_utc.strftime('%Y%m%dT%H%MZ')}"
    lines = [
        serialize_p5_jsonl_record(
            rec, session_id=sess_id, execution_mode=execution_mode,
            config_hash="s317-live-p5", capture_replay_mode="NONE",
        )
        for rec in records
    ]
    if lines:
        with out_file.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
            fh.flush()
    return out_file


def _resolve_station_targets(
    station_id: str, issue_ts: datetime, ladders: Dict[Tuple[str, str], Tuple]
) -> List[Tuple[date, Optional[Tuple]]]:
    matched = [
        (date.fromisoformat(d_str), bins)
        for (st, d_str), bins in sorted(ladders.items())
        if st == station_id
    ]
    active: List[Tuple[date, Optional[Tuple]]] = []
    tz = resolve_station_timezone(station_id)
    for t_date, bins in matched:
        _, close_utc = compute_local_day_window_utc(t_date, tz)
        if close_utc > issue_ts:
            active.append((t_date, bins))
    return active if active else [(issue_ts.date(), None)]


def run_live_p5_cycle(
    producer: LiveP5Producer,
    *,
    recordings_root: Path,
    output_dir: Path,
    stations: Sequence[str],
    execution_mode: ExecutionMode = "PAPER",
    now_utc: Optional[datetime] = None,
) -> Dict[str, object]:
    """Produce one live 6-station 5-member `P5` batch aligned to active P13 ladders."""
    issue_ts = now_utc or datetime.now(timezone.utc)
    cycle_utc = resolve_latest_gefs_cycle_utc(issue_ts)
    try:
        ladders = discover_p13_market_ladders(recordings_root, active_only=True)
    except Exception:
        ladders = {}
    records: List[LiveP5ProductionRecord] = []
    errors: List[str] = []
    for station_id in stations:
        for t_date, bins in _resolve_station_targets(station_id, issue_ts, ladders):
            try:
                rec = producer.produce_station_snapshot(
                    station_id=station_id, target_date=t_date, issue_ts_utc=issue_ts,
                    cycle_utc=cycle_utc, bins=bins, execution_mode=execution_mode,
                    session_id=f"s317-live-{cycle_utc.strftime('%Y%m%dT%H%MZ')}",
                )
                records.append(rec)
            except Exception as exc:
                errors.append(f"{station_id}/{t_date.isoformat()}:{type(exc).__name__}:{exc}")
    out_file = _append_p5_records(records, output_dir, cycle_utc=cycle_utc, execution_mode=execution_mode)
    return {
        "status": "OK" if records else "ERROR",
        "issue_ts_utc": issue_ts.isoformat(),
        "cycle_utc": cycle_utc.isoformat(),
        "produced_count": len(records),
        "error_count": len(errors),
        "errors": errors,
        "output_file": str(out_file),
    }


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="S3-17 persistent online M1/M2 P5 producer.")
    parser.add_argument("--recordings-root", type=Path, default=DEFAULT_RECORDINGS_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_LIVE_P5_DIR)
    parser.add_argument("--stations", nargs="+", default=list(SUPPORTED_LIVE_STATIONS))
    parser.add_argument("--members", nargs="+", type=int, default=list(DEFAULT_GEFS_MEMBERS))
    parser.add_argument("--interval-sec", type=float, default=1800.0)
    parser.add_argument("--execution-mode", choices=("PAPER", "LIVE"), default="PAPER")
    parser.add_argument("--pid-file", type=Path, default=DEFAULT_LIVE_P5_DIR / "live_p5_producer.pid")
    parser.add_argument("--once", action="store_true", default=False)
    return parser.parse_args(argv)


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    producer: Optional[LiveP5Producer] = None,
    max_cycles: Optional[int] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> int:
    args = _parse_args(argv)
    members = tuple(int(m) for m in args.members)
    if any(m not in VALID_MEMBERS for m in members):
        raise ValueError(f"Unsupported GEFS member(s) in {members}; authorized={VALID_MEMBERS}")
    _write_pid_file(args.pid_file)
    stations = tuple(str(s).strip().upper() for s in args.stations)
    active_producer = producer or LiveP5Producer(
        config=LiveP5ProducerConfig(stations=stations, gefs_members=members)
    )
    cycles = 0
    while True:
        summary = run_live_p5_cycle(
            active_producer, recordings_root=args.recordings_root, output_dir=args.output_dir,
            stations=stations, execution_mode=args.execution_mode,
        )
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        cycles += 1
        if args.once or (max_cycles is not None and cycles >= max_cycles):
            return 0 if int(summary["produced_count"]) > 0 else 2
        sleep_fn(float(args.interval_sec))


if __name__ == "__main__":
    raise SystemExit(main())
