#!/usr/bin/env python3
"""GEFS Reforecast B1 Gap Repair Downloader (External Storage).

Downloads missing and truncated GRIB2 subset files for identified gap dates
(2019-12-31, 2001-12-31, 2004-03-28, 2011-12-31, 2014-10-18, 2003-01-21, 2012-10-31)
directly into external storage, ensuring 100% idempotency and zero accidental file deletion.
"""

import argparse
import concurrent.futures
from dataclasses import dataclass
from datetime import datetime
import logging
import os
from pathlib import Path
import sys
import time
from typing import List, Sequence, Tuple

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from herbie import Herbie
from scripts.download_gefs_b2 import is_valid_grib2_slice
from src.data_acquisition.gefs_fetcher import GEFSFetcher

logger = logging.getLogger("gefs_b1_gaps")


@dataclass
class SliceGapTask:
    dt: datetime
    var: str
    member: int
    window: List[int]
    raw_dir: str
    max_retries: int
    fetcher: GEFSFetcher


B1_DEFAULT_GAP_DATES = [
    "20191231",
    "20011231",
    "20040328",
    "20111231",
    "20141018",
    "20030121",
    "20121031",
]

B1_WINDOWS = [
    [24, 30, 36],
    [42, 48, 54],
]
B1_VARIABLES = ["tmax_2m", "tmin_2m"]
B1_MEMBERS = [0, 1, 2, 3, 4]


def parse_args():
    """Parse CLI arguments for B1 gap downloader."""
    parser = argparse.ArgumentParser(description="GEFS B1 Gap Repair Downloader")
    parser.add_argument(
        "--raw-dir",
        type=str,
        default="/Volumes/EricSSD/Poly RawData",
        help="Root path containing gefs_reforecast directory",
    )
    parser.add_argument(
        "--dates",
        type=str,
        default=",".join(B1_DEFAULT_GAP_DATES),
        help="Comma-separated gap dates in YYYYMMDD format",
    )
    parser.add_argument("--threads", type=int, default=4, help="Parallel download threads")
    parser.add_argument("--max-retries", type=int, default=3, help="Retries per slice")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def setup_logging(verbose: bool = False) -> None:
    """Configure console logging."""
    lvl = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=lvl,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )


def download_single_slice(h: Herbie, search: str, local_path: Path, max_retries: int = 3) -> bool:
    """Download single Herbie slice with retry, skipping valid existing files."""
    if is_valid_grib2_slice(local_path, expected_messages=3):
        logger.debug(f"Skip existing valid file: {local_path.name}")
        return False

    logger.info(f"Downloading gap slice: {local_path.name} (target: {local_path.parent.name})")
    for attempt in range(1, max_retries + 1):
        try:
            local_path.unlink(missing_ok=True)
            h.download(search=search, overwrite=True)
            if is_valid_grib2_slice(local_path, expected_messages=3):
                logger.info(f"✅ Success: {local_path.name} ({local_path.stat().st_size:,} bytes)")
                return True
            logger.warning(f"File downloaded but invalid WMO structure, retry {attempt}/{max_retries}")
        except Exception as exc:
            logger.warning(f"Download attempt {attempt}/{max_retries} failed for {local_path.name}: {exc}")
            if attempt < max_retries:
                time.sleep(2.0 * attempt)
    raise RuntimeError(f"Failed to download valid slice after {max_retries} attempts: {local_path.name}")


def _fetch_slice_worker(task: SliceGapTask) -> bool:
    """Worker function for downloading a single slice in a thread."""
    h = Herbie(
        task.dt,
        model="gefs_reforecast",
        product="GEFSv12/reforecast",
        member=task.member,
        fxx=0,
        variable_level=task.var,
        save_dir=task.raw_dir,
        verbose=False,
    )
    search = task.fetcher.build_search(task.var, task.window)
    local = h.get_localFilePath(search)
    return download_single_slice(h, search, local, task.max_retries)


def download_day_gaps(
    fetcher: GEFSFetcher,
    dt: datetime,
    raw_dir: str,
    max_retries: int = 3,
    threads: int = 4,
) -> int:
    """Download missing or corrupted slices for a single date in parallel."""
    tasks = [
        SliceGapTask(
            dt=dt,
            var=var,
            member=mem,
            window=window,
            raw_dir=raw_dir,
            max_retries=max_retries,
            fetcher=fetcher,
        )
        for var in B1_VARIABLES
        for mem in B1_MEMBERS
        for window in B1_WINDOWS
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
        results = list(executor.map(_fetch_slice_worker, tasks))
    return sum(1 for r in results if r)


def verify_gap_dates_completion(raw_dir: Path, dates: Sequence[str]) -> bool:
    """Verify all gap dates satisfy the V1 20-file criterion with zero truncated files."""
    gefs_root = raw_dir / "gefs_reforecast"
    all_passed = True
    print("\n" + "=" * 70)
    print(" B1 GAP REPAIR POST-CHECK VERIFICATION")
    print("=" * 70)
    print(f"{'Date':<12} | {'Files':<6} | {'Truncated (<1MB)':<18} | {'Status':<8}")
    print("-" * 70)

    for d_str in dates:
        day_p = gefs_root / d_str
        if not day_p.exists():
            print(f"{d_str:<12} | {0:<6} | {'-':<18} | ❌ MISSING")
            all_passed = False
            continue
        gribs = [f for f in day_p.iterdir() if f.is_file() and not f.name.startswith(".") and f.name.endswith(".grib2")]
        trunc = [f for f in gribs if not is_valid_grib2_slice(f, expected_messages=3)]
        if len(gribs) == 20 and len(trunc) == 0:
            status = "✅ PASS (Exact 20)"
        elif len(gribs) > 20 and len(trunc) == 0:
            status = f"✅ PASS (Redundant {len(gribs)})"
        else:
            status = "❌ FAIL (Incomplete)"
            all_passed = False
        print(f"{d_str:<12} | {len(gribs):<6} | {len(trunc):<18} | {status}")

    print("=" * 70)
    return all_passed


def main():
    args = parse_args()
    setup_logging(args.verbose)
    raw_path = Path(args.raw_dir)
    dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    fetcher = GEFSFetcher(cache_dir=str(raw_path), verbose=args.verbose)

    logger.info(f"Starting B1 gap repair for {len(dates)} dates on {raw_path} with {args.threads} threads...")
    t0 = time.time()
    total_downloaded = 0

    for idx, d_str in enumerate(dates, 1):
        dt = datetime.strptime(d_str, "%Y%m%d")
        logger.info(f"[{idx}/{len(dates)}] Processing date {d_str}...")
        downloaded = download_day_gaps(fetcher, dt, str(raw_path), args.max_retries, args.threads)
        total_downloaded += downloaded
        logger.info(f"[{idx}/{len(dates)}] Finished {d_str}: downloaded {downloaded} new/repaired slices")

    elapsed = time.time() - t0
    logger.info(f"All {len(dates)} dates processed in {elapsed:.1f}s. Total slices downloaded: {total_downloaded}")

    passed = verify_gap_dates_completion(raw_path, dates)
    if not passed:
        logger.error("B1 Gap repair verification FAILED: some dates do not have exactly 20 valid files.")
        sys.exit(1)
    logger.info("🎉 All gap dates successfully repaired and verified against V1 20-file standard!")


if __name__ == "__main__":
    main()
