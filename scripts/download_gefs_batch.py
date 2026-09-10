#!/usr/bin/env python3
"""
CLI Batch Downloader for GEFS Reforecast Data (2000-2019).

Usage:
  python scripts/download_gefs_batch.py --start-year 2000 --end-year 2019
  python scripts/download_gefs_batch.py --start-year 2019 --end-year 2019 --auto-continue
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data_acquisition.gefs_batch_downloader import GEFSBatchDownloader

logger = logging.getLogger("gefs_batch_downloader")


def _add_core_args(parser: argparse.ArgumentParser) -> None:
    """Register core batch download arguments."""
    parser.add_argument("--start-year", type=int, default=2000, help="Start year (inclusive)")
    parser.add_argument("--end-year", type=int, default=2019, help="End year (inclusive)")
    parser.add_argument("--state-file", type=str, default="data/gefs_download_state.csv", help="State file")
    parser.add_argument("--raw-cache-dir", type=str, default="data/raw/gefs", help="Raw GEFS directory")
    parser.add_argument("--processed-dir", type=str, default="data/processed/gefs", help="Cropped directory")
    parser.add_argument("--stations", type=str, default="shanghai,denver", help="Comma-separated stations")
    parser.add_argument("--target-offsets", type=str, default="0,1,2", help="Target day offsets (0,1,2)")
    parser.add_argument("--fxx", type=str, default="", help="Optional comma-separated fxx filter")
    parser.add_argument("--gap-dates", type=str, default="", help="Optional gap dates for B1 repair")


def _add_advanced_args(parser: argparse.ArgumentParser) -> None:
    """Register advanced control and network arguments."""
    parser.add_argument("--auto-continue", action="store_true", help="Auto-confirm raw file move")
    parser.add_argument("--check-interval", type=float, default=2.0, help="Polling interval in seconds")
    parser.add_argument("--log-file", type=str, default=None, help="Path to write log output")
    parser.add_argument("--use-proxy", action="store_true", default=None, help="Force using proxy")
    parser.add_argument("--no-proxy", action="store_true", default=None, help="Force direct S3 connection")
    parser.add_argument("--verbose", action="store_true", help="Enable debug-level logging")


def parse_args():
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="GEFS Reforecast Batch Downloader with CSV State Machine")
    _add_core_args(parser)
    _add_advanced_args(parser)
    return parser.parse_args()


def _setup_logging(args):
    """Configure console and file loggers."""
    if args.no_proxy:
        os.environ["GEFS_USE_PROXY"] = "false"
    elif args.use_proxy:
        os.environ["GEFS_USE_PROXY"] = "true"

    handlers = [logging.StreamHandler(sys.stdout)]
    if args.log_file:
        log_path = Path(args.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(
                f"# METADATA: pid={os.getpid()} start_year={args.start_year} end_year={args.end_year} "
                f"stations={args.stations} started_at={datetime.now().isoformat()}\n"
            )
        handlers.append(logging.FileHandler(log_path, mode="a", encoding="utf-8"))

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def main():
    args = parse_args()
    _setup_logging(args)

    station_list = [s.strip() for s in args.stations.split(",") if s.strip()]
    offsets = [int(x.strip()) for x in args.target_offsets.split(",") if x.strip()]
    fxx_list = [int(x.strip()) for x in args.fxx.split(",") if x.strip()] if args.fxx else None

    downloader = GEFSBatchDownloader(
        state_file=args.state_file,
        raw_cache_dir=args.raw_cache_dir,
        processed_dir=args.processed_dir,
        stations=station_list,
        target_offsets=offsets,
        fxx_filter=fxx_list,
        auto_continue=args.auto_continue,
        check_interval=args.check_interval,
        verbose=args.verbose,
    )

    if args.gap_dates:
        gap_list = [d.strip() for d in args.gap_dates.split(",") if d.strip()]
        logger.info(f"Running in B1 gap filling mode for {len(gap_list)} dates...")
        downloader.download_gap_days(gap_list)
    else:
        downloader.run(start_year=args.start_year, end_year=args.end_year)


if __name__ == "__main__":
    main()
