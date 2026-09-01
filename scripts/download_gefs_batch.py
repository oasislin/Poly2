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


def parse_args():
    parser = argparse.ArgumentParser(
        description="GEFS Reforecast Batch Downloader with CSV State Machine"
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=2000,
        help="Start year to download (inclusive, default: 2000)",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=2019,
        help="End year to download (inclusive, default: 2019)",
    )
    parser.add_argument(
        "--state-file",
        type=str,
        default="data/gefs_download_state.csv",
        help="Path to CSV state machine tracking file",
    )
    parser.add_argument(
        "--raw-cache-dir",
        type=str,
        default="data/raw/gefs",
        help="Directory to store raw GEFS files before moving",
    )
    parser.add_argument(
        "--processed-dir",
        type=str,
        default="data/processed/gefs",
        help="Directory to store cropped regional datasets",
    )
    parser.add_argument(
        "--stations",
        type=str,
        default="shanghai,denver",
        help="Comma-separated station names (default: shanghai,denver)",
    )
    parser.add_argument(
        "--auto-continue",
        action="store_true",
        help="Auto-confirm raw file move without interactive pause",
    )
    parser.add_argument(
        "--check-interval",
        type=float,
        default=2.0,
        help="State file polling interval in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Path to write log output in addition to console (e.g. logs/download_2000s.log)",
    )
    parser.add_argument(
        "--use-proxy",
        action="store_true",
        default=None,
        help="Force using system/local proxy for downloads",
    )
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        default=None,
        help="Force direct AWS S3 connection bypassing any proxy (recommended)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug-level logging",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Dynamic proxy flag override via CLI
    if args.no_proxy:
        os.environ["GEFS_USE_PROXY"] = "false"
    elif args.use_proxy:
        os.environ["GEFS_USE_PROXY"] = "true"

    handlers = [logging.StreamHandler(sys.stdout)]
    if args.log_file:
        log_path = Path(args.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Write metadata header for dashboard auto-discovery
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
    for h in handlers:
        if h not in logging.root.handlers:
            logging.root.addHandler(h)

    station_list = [s.strip() for s in args.stations.split(",") if s.strip()]

    downloader = GEFSBatchDownloader(
        state_file=args.state_file,
        raw_cache_dir=args.raw_cache_dir,
        processed_dir=args.processed_dir,
        stations=station_list,
        auto_continue=args.auto_continue,
        check_interval=args.check_interval,
        verbose=args.verbose,
    )

    downloader.run(start_year=args.start_year, end_year=args.end_year)


if __name__ == "__main__":
    main()
