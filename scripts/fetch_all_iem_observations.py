#!/usr/bin/env python3
"""
Batch Orchestrator for IEM ASOS Observations (Phase 1.5 Task 04).

Fetches historical observations for the active 11 stations across 2000-2026.
Adheres to ISU IEM academic server etiquette (gentle rate limiting, exponential backoff).
Outputs:
- Parquet files: data/raw/iem/{station}/{year}.parquet
- Raw compressed CSV archives: data/raw/iem/{station}/{year}.csv.gz
- Central manifest: data/raw/iem/manifest.json
- Error ledger: data/raw/iem/fetch_errors.json (if any failures occur)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from src.data_processing.constants import ACTIVE_11_STATIONS
from src.pipeline.iem_adapter import IemAdapter, IemAdapterConfig
from src.utils.logger import get_logger

logger = get_logger("poly.scripts.fetch_all_iem")

DEFAULT_START_YEAR: int = 2000
DEFAULT_END_YEAR: int = 2026
DEFAULT_STORAGE_DIR: str = "data/raw/iem"
DEFAULT_REPORTS_DIR: str = "data/reports"
DEFAULT_RATE_LIMIT_DELAY: float = 1.0


@dataclass
class BatchExecutionStats:
    """Statistics accumulator for batch extraction."""
    total_requested: int = 0
    successful_count: int = 0
    skipped_resumed_count: int = 0
    failed_count: int = 0
    total_rows: int = 0
    nominal_count: int = 0
    degraded_count: int = 0


def _parse_cli_arguments() -> argparse.Namespace:
    """Parse and return command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Batch fetch IEM ASOS historical observations (2000-2026)"
    )
    parser.add_argument(
        "--stations",
        nargs="+",
        default=list(ACTIVE_11_STATIONS),
        help=f"List of stations to fetch (default: all active 11 stations: {list(ACTIVE_11_STATIONS)})",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=DEFAULT_START_YEAR,
        help=f"Start year inclusive (default: {DEFAULT_START_YEAR})",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=DEFAULT_END_YEAR,
        help=f"End year inclusive (default: {DEFAULT_END_YEAR})",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default=DEFAULT_STORAGE_DIR,
        help=f"Output storage directory (default: {DEFAULT_STORAGE_DIR})",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=DEFAULT_RATE_LIMIT_DELAY,
        help=f"Delay in seconds between requests (default: {DEFAULT_RATE_LIMIT_DELAY})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-download even if files already exist with matching checksums",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate parameters and schedule without performing network downloads",
    )
    return parser.parse_args()


def _validate_requested_stations(stations: Sequence[str]) -> List[str]:
    """Validate all requested stations belong to the approved universe."""
    validated: List[str] = []
    for st in stations:
        st_norm = st.strip().upper()
        if st_norm not in ACTIVE_11_STATIONS:
            raise ValueError(
                f"Station '{st_norm}' is not in active 11 stations: {ACTIVE_11_STATIONS}."
            )
        validated.append(st_norm)
    return validated


def _record_error(errors: List[Dict[str, Any]], station: str, year: int, err: Exception) -> None:
    """Append failure context to the error ledger."""
    errors.append({
        "station": station,
        "year": year,
        "error_type": type(err).__name__,
        "error_message": str(err),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })


def _save_error_ledger(out_dir: Path, errors: List[Dict[str, Any]]) -> None:
    """Persist error ledger if failures occurred."""
    if not errors:
        return
    error_file = out_dir / "fetch_errors.json"
    with open(error_file, "w", encoding="utf-8") as f:
        json.dump(errors, f, indent=2, ensure_ascii=False)
    logger.warning(f"Recorded {len(errors)} failures to {error_file}")


def _process_station_year(
    adapter: IemAdapter,
    station: str,
    year: int,
    force: bool,
    stats: BatchExecutionStats,
    errors: List[Dict[str, Any]],
    current_idx: int,
) -> None:
    """Process a single station-year with error containment."""
    prefix = f"[{current_idx}/{stats.total_requested}] {station} {year}"
    try:
        artifact = adapter.fetch_station_year(station=station, year=year, force=force)
        stats.successful_count += 1
        stats.total_rows += artifact.row_count
        if artifact.quality_flag == "nominal":
            stats.nominal_count += 1
        else:
            stats.degraded_count += 1
        logger.info(
            f"{prefix} -> {artifact.row_count} obs, quality={artifact.quality_flag}, "
            f"sha={artifact.manifest_entry['sha256'][:8]}..."
        )
    except Exception as e:
        stats.failed_count += 1
        _record_error(errors, station, year, e)
        logger.error(f"{prefix} FAILED: {e}", exc_info=True)


def run_batch_fetch(
    stations: Sequence[str],
    start_year: int,
    end_year: int,
    out_dir: Path,
    rate_limit: float = DEFAULT_RATE_LIMIT_DELAY,
    force: bool = False,
    dry_run: bool = False,
) -> Tuple[BatchExecutionStats, List[Dict[str, Any]]]:
    """Execute batch fetching of historical IEM data across stations and years."""
    val_stations = _validate_requested_stations(stations)
    years = list(range(start_year, end_year + 1))
    stats = BatchExecutionStats(total_requested=len(val_stations) * len(years))
    errors: List[Dict[str, Any]] = []

    if dry_run:
        logger.info(
            f"Dry-run plan: {len(val_stations)} stations {val_stations} × {len(years)} years "
            f"({start_year}..{end_year}) = {stats.total_requested} total station-years."
        )
        return stats, errors

    config = IemAdapterConfig(
        storage_dir=out_dir,
        reports_dir=Path(DEFAULT_REPORTS_DIR),
        rate_limit_delay=rate_limit,
    )

    t0 = time.perf_counter()
    with IemAdapter(config=config) as adapter:
        curr = 0
        for st in val_stations:
            for yr in years:
                curr += 1
                _process_station_year(adapter, st, yr, force, stats, errors, curr)

    elapsed_s = time.perf_counter() - t0
    logger.info(
        f"Batch fetch finished in {elapsed_s:.1f}s: {stats.successful_count}/{stats.total_requested} "
        f"successful, {stats.failed_count} failed, {stats.total_rows:,} total observations."
    )
    _save_error_ledger(out_dir, errors)
    return stats, errors


def main() -> int:
    """Main CLI entry point."""
    args = _parse_cli_arguments()
    try:
        stats, errors = run_batch_fetch(
            stations=args.stations,
            start_year=args.start_year,
            end_year=args.end_year,
            out_dir=Path(args.out_dir),
            rate_limit=args.rate_limit,
            force=args.force,
            dry_run=args.dry_run,
        )
        return 0 if stats.failed_count == 0 else 1
    except Exception as e:
        logger.error(f"Fatal error during batch execution: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
