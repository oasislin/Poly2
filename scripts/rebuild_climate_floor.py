#!/usr/bin/env python3
"""
Batch Climate Floor Rebuilder CLI (Phase 1.5 Task 05).

Rebuilds 366-day daily climatological baseline and smooth variance floor across
the active 11 US trading stations using 2000-2018 IEM ASOS observations.
Strictly Out-Of-Sample (OOS): strictly enforces end_year <= 2018.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from src.data_processing.constants import ACTIVE_11_STATIONS
from src.modeling.climate_floor import (
    DAYS_IN_LEAP_YEAR,
    DEFAULT_HALF_WINDOW_DAYS,
    DEFAULT_SMOOTH_SIGMA_DAYS,
    DEFAULT_WINDOW_DAYS,
    FLOOR_ABS_MIN_F,
    FLOOR_PHYSICAL_MAX_F,
    FLOOR_PHYSICAL_MIN_F,
    TARGET_TYPE_MAX,
    TARGET_TYPE_MIN,
    TRAIN_END_YEAR,
    TRAIN_START_YEAR,
    VALID_TARGET_TYPES,
    ClimateFloorBuilder,
    ClimateFloorConfig,
    ClimateFloorRegistry,
    ClimateFloorTable,
    validate_station_id,
    validate_year_range,
)
from src.utils.logger import get_logger

logger = get_logger("poly.scripts.rebuild_climate_floor")

DEFAULT_RAW_DIR: Path = Path("data/raw/iem")
DEFAULT_OUTPUT_DIR: Path = Path("data/processed/climate_floor")
DEFAULT_CONFIG_OUT: Path = Path("configs/climate_floor_v2.json")
HASH_CHUNK_SIZE_BYTES: int = 65536


def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 checksum of a file using buffered streaming."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(HASH_CHUNK_SIZE_BYTES):
            h.update(chunk)
    return h.hexdigest()


def get_git_commit_sha() -> str:
    """Retrieve current Git commit SHA."""
    try:
        cmd = ["git", "rev-parse", "HEAD"]
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def _add_dataset_args(parser: argparse.ArgumentParser) -> None:
    """Add station and I/O path CLI arguments."""
    parser.add_argument(
        "--stations",
        nargs="+",
        default=list(ACTIVE_11_STATIONS),
        help="Station codes to process (default: all active 11 stations).",
    )
    parser.add_argument(
        "--all-11",
        action="store_true",
        help="Explicit flag to process all 11 active trading stations.",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help="Path to raw IEM parquet observations directory.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to save output climate floor parquet tables.",
    )
    parser.add_argument(
        "--config-out",
        type=Path,
        default=DEFAULT_CONFIG_OUT,
        help="Path to save central climate floor JSON configuration.",
    )


def _add_model_args(parser: argparse.ArgumentParser) -> None:
    """Add temporal, algorithm, and execution CLI arguments."""
    parser.add_argument(
        "--start-year",
        type=int,
        default=TRAIN_START_YEAR,
        help=f"Historical training start year (default: {TRAIN_START_YEAR}).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=TRAIN_END_YEAR,
        help=f"Historical training end year (default: {TRAIN_END_YEAR}, max allowed).",
    )
    parser.add_argument(
        "--smooth-sigma",
        type=float,
        default=DEFAULT_SMOOTH_SIGMA_DAYS,
        help=f"Periodic circular Gaussian smoothing sigma in days (default: {DEFAULT_SMOOTH_SIGMA_DAYS}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without persisting output files to disk.",
    )


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Rebuild 366-day climatological variance floor for active 11 stations (Task 05)."
    )
    _add_dataset_args(parser)
    _add_model_args(parser)
    return parser.parse_args()


def validate_requested_stations(stations: Sequence[str]) -> List[str]:
    """Validate that all requested stations are within the active 11 universe."""
    validated: List[str] = []
    for st in stations:
        st_norm = validate_station_id(st)
        if st_norm not in validated:
            validated.append(st_norm)
    return validated


def _summarize_table_stats(table: ClimateFloorTable) -> Dict[str, float]:
    """Compute summary statistics for a ClimateFloorTable."""
    sigmas = np.array([p.sigma_clim for p in table.points])
    return {
        "min_sigma": float(np.min(sigmas)),
        "max_sigma": float(np.max(sigmas)),
        "mean_sigma": float(np.mean(sigmas)),
        "p50_sigma": float(np.median(sigmas)),
    }


def write_manifest_file(
    output_dir: Path,
    config_path: Path,
    saved_files: List[Path],
    summary_stats: Dict[str, Dict[str, Any]],
    start_year: int,
    end_year: int,
) -> Path:
    """Generate and write manifest.json capturing provenance and checksums."""
    manifest_data: Dict[str, Any] = {
        "version": "2.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit_sha": get_git_commit_sha(),
        "train_period": f"{start_year}-{end_year}",
        "station_count": len(summary_stats),
        "files": {},
        "summary": summary_stats,
    }

    all_files = list(saved_files)
    if config_path.exists():
        all_files.append(config_path)

    for f in all_files:
        manifest_data["files"][f.name] = {
            "path": str(f),
            "size_bytes": f.stat().st_size,
            "sha256": compute_file_sha256(f),
        }

    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as fp:
        json.dump(manifest_data, fp, indent=2)
    logger.info(f"Wrote manifest to {manifest_path}")
    return manifest_path


def run_batch_rebuild(
    stations: Sequence[str],
    raw_dir: Path,
    output_dir: Path,
    config_out: Path,
    start_year: int = TRAIN_START_YEAR,
    end_year: int = TRAIN_END_YEAR,
    smooth_sigma: float = DEFAULT_SMOOTH_SIGMA_DAYS,
    dry_run: bool = False,
) -> Tuple[ClimateFloorRegistry, Dict[str, Dict[str, Any]]]:
    """Execute batch climate floor rebuilding across requested stations."""
    valid_stations = validate_requested_stations(stations)
    validate_year_range(start_year, end_year)

    cfg = ClimateFloorConfig(
        train_start_year=start_year,
        train_end_year=end_year,
        smooth_sigma_days=smooth_sigma,
    )
    builder = ClimateFloorBuilder(config=cfg)
    registry = ClimateFloorRegistry()
    summary_stats: Dict[str, Dict[str, Any]] = {}

    for idx, st in enumerate(valid_stations, start=1):
        logger.info(f"[{idx}/{len(valid_stations)}] Processing {st} ({start_year}-{end_year})...")
        tables = builder.build_station(station=st, raw_dir=raw_dir)
        st_summary: Dict[str, Any] = {}
        for t_type, table in tables.items():
            registry.register_table(table)
            st_summary[t_type] = _summarize_table_stats(table)
        summary_stats[st] = st_summary
        logger.info(
            f"  {st} TMAX sigma: [{st_summary['max']['min_sigma']:.2f}, {st_summary['max']['max_sigma']:.2f}] °F, "
            f"TMIN sigma: [{st_summary['min']['min_sigma']:.2f}, {st_summary['min']['max_sigma']:.2f}] °F"
        )

    if not dry_run:
        saved_parquets = registry.save_to_parquet_dir(output_dir)
        registry.save_to_json(config_out)
        write_manifest_file(
            output_dir=output_dir,
            config_path=config_out,
            saved_files=saved_parquets,
            summary_stats=summary_stats,
            start_year=start_year,
            end_year=end_year,
        )

    return registry, summary_stats


def main() -> int:
    """CLI entrypoint."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_arguments()
    try:
        stations = list(ACTIVE_11_STATIONS) if args.all_11 else args.stations
        registry, stats = run_batch_rebuild(
            stations=stations,
            raw_dir=args.raw_dir,
            output_dir=args.output_dir,
            config_out=args.config_out,
            start_year=args.start_year,
            end_year=args.end_year,
            smooth_sigma=args.smooth_sigma,
            dry_run=args.dry_run,
        )
        print("\n=== Phase 1.5 Task 05 Climate Floor Rebuild Summary ===")
        print(f"Total stations processed: {len(stats)}")
        print(f"Training period: {args.start_year}-{args.end_year} (Strictly OOS)")
        print(f"Smoothing sigma: {args.smooth_sigma} days (Circular Gaussian)")
        print(f"Absolute floor min: {FLOOR_ABS_MIN_F} °F")
        print("\nStation | TMAX Sigma (Min/P50/Max) | TMIN Sigma (Min/P50/Max)")
        print("-" * 65)
        for st, s in stats.items():
            max_s = f"{s['max']['min_sigma']:.2f} / {s['max']['p50_sigma']:.2f} / {s['max']['max_sigma']:.2f}"
            min_s = f"{s['min']['min_sigma']:.2f} / {s['min']['p50_sigma']:.2f} / {s['min']['max_sigma']:.2f}"
            print(f"{st:7s} | {max_s:24s} | {min_s:24s}")
        print("=" * 65)
        return 0
    except Exception as e:
        logger.error(f"Batch rebuild failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
