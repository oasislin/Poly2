"""CLI launcher for M3 read-only passive orderbook recorder (`S1-05`).

Usage (only execute after explicit user sign-off to start passive recording):
    python scripts/run_passive_book_recorder.py --config configs/passive_book_recorder.example.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
import signal
import sys
from typing import Optional, Sequence

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.data_acquisition.passive_book_recorder import PassiveBookRecorder, RecorderConfig

logger = logging.getLogger(__name__)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run M3 read-only passive orderbook recorder")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/passive_book_recorder.example.yaml"),
        help="Path to passive recorder YAML config",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        default=None,
        help="Optional explicit session_id for recording directory partitioning",
    )
    parser.add_argument(
        "--dry-run-discover",
        action="store_true",
        help="Discover markets from Gamma REST once and exit without starting recording loop",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)
    with open(args.config, "r", encoding="utf-8") as fh:
        raw_cfg = yaml.safe_load(fh)
    config = RecorderConfig.from_yaml_dict(raw_cfg)
    recorder = PassiveBookRecorder(config=config, session_id=args.session_id)

    metas = recorder.discover_active_temperature_markets()
    logger.info("Discovered %d active market outcome tokens", len(metas))
    if args.dry_run_discover:
        recorder.flush_and_close()
        return 0

    stop_event = asyncio.Event()
    loop = asyncio.new_event_loop()
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass
        loop.run_until_complete(recorder.run_ws_loop(stop_event=stop_event))
    finally:
        recorder.flush_and_close()
        loop.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
