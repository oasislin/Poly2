#!/usr/bin/env python3
"""
Batch Feature Store Builder for Observation Features (Phase 1.5 Task 06).

Slices 11 stations x 27 years (2000-2026) raw IEM ASOS records into production
daily features with ADR-0009 dual-track extremes, 2020 leap-year DOY projection,
and vintage tiering tags.

Outputs:
- data/processed/features/{station}/{year}.parquet
- data/processed/features/manifest.json

Engineering discipline: Every single function <= 50 lines.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from src.data_processing.constants import ACTIVE_11_STATIONS, STATION_METADATA
from src.data_processing.slicer import ObservationSlicer, validate_active_station
from src.utils.logger import get_logger

logger = get_logger("poly.scripts.build_feature_store")

DEFAULT_START_YEAR: int = 2000
DEFAULT_END_YEAR: int = 2026
DEFAULT_RAW_DIR: str = "data/raw/iem"
DEFAULT_OUT_DIR: str = "data/processed/features"
HASH_CHUNK_SIZE: int = 65536


def _parse_cli_arguments() -> argparse.Namespace:
    """Parse CLI arguments for feature store batch processing."""
    parser = argparse.ArgumentParser(description="Build Feature Store v2 for Active 11 Stations (2000-2026)")
    parser.add_argument("--stations", nargs="+", default=list(ACTIVE_11_STATIONS), help="Stations to process")
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR, help="Start year inclusive")
    parser.add_argument("--end-year", type=int, default=DEFAULT_END_YEAR, help="End year inclusive")
    parser.add_argument("--raw-dir", type=str, default=DEFAULT_RAW_DIR, help="Raw observations root directory")
    parser.add_argument("--out-dir", type=str, default=DEFAULT_OUT_DIR, help="Output features root directory")
    parser.add_argument("--force", action="store_true", help="Force recomputation even if partition exists")
    parser.add_argument("--dry-run", action="store_true", help="Print schedule without writing files")
    return parser.parse_args()


def _compute_file_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash using streaming buffer."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(HASH_CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def _get_git_commit() -> str:
    """Retrieve current HEAD commit SHA."""
    try:
        cmd = ["git", "rev-parse", "HEAD"]
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def _load_boundary_padding(file_path: Path, is_tail: bool, window_days: int = 2) -> Optional[pd.DataFrame]:
    """Load leading or trailing boundary slice from adjacent year file to eliminate code duplication."""
    if not file_path.exists():
        return None
    df = pd.read_parquet(file_path)
    if df.empty or "valid_utc" not in df.columns:
        return None
    ts = pd.to_datetime(df["valid_utc"])
    cutoff = (ts.max() - pd.Timedelta(days=window_days)) if is_tail else (ts.min() + pd.Timedelta(days=window_days))
    mask = (ts >= cutoff) if is_tail else (ts <= cutoff)
    return df[mask]


def _load_raw_with_padding(raw_dir: Path, station: str, year: int) -> pd.DataFrame:
    """Load year parquet and pad with boundary slices from adjacent years."""
    st_dir = raw_dir / station
    main_file = st_dir / f"{year}.parquet"
    if not main_file.exists():
        return pd.DataFrame()

    dfs = [pd.read_parquet(main_file)]
    prev_df = _load_boundary_padding(st_dir / f"{year - 1}.parquet", is_tail=True)
    if prev_df is not None:
        dfs.insert(0, prev_df)

    next_df = _load_boundary_padding(st_dir / f"{year + 1}.parquet", is_tail=False)
    if next_df is not None:
        dfs.append(next_df)

    return pd.concat(dfs, ignore_index=True)


def _process_station_year(
    slicer: ObservationSlicer,
    raw_dir: Path,
    out_dir: Path,
    station: str,
    year: int,
    force: bool,
) -> Optional[Dict[str, Any]]:
    """Slice and save one station-year partition atomically."""
    st_norm = validate_active_station(station)
    target_path = out_dir / st_norm / f"{year}.parquet"
    if target_path.exists() and not force:
        logger.info(f"Skipping existing partition: {target_path}")
        existing_df = pd.read_parquet(target_path)
        return {
            "station": st_norm,
            "year": year,
            "path": str(target_path.resolve().relative_to(repo_root.resolve())),
            "row_count": len(existing_df),
            "sha256": _compute_file_sha256(target_path),
            "divergence_days": int(existing_df["has_speci_divergence"].sum()),
        }

    raw_df = _load_raw_with_padding(raw_dir, st_norm, year)
    if raw_df.empty:
        logger.warning(f"No raw data found for {st_norm} year {year}")
        return None

    features_df = slicer.slice_dataframe(raw_df, station=st_norm, target_year=year)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_suffix(".tmp.parquet")
    features_df.to_parquet(tmp_path, index=False, engine="pyarrow", compression="snappy")
    tmp_path.replace(target_path)

    sha = _compute_file_sha256(target_path)
    div_count = int(features_df["has_speci_divergence"].sum()) if "has_speci_divergence" in features_df else 0
    return {
        "station": st_norm,
        "year": year,
        "path": str(target_path.resolve().relative_to(repo_root.resolve())),
        "row_count": len(features_df),
        "sha256": sha,
        "divergence_days": div_count,
    }


def _build_and_save_manifest(
    out_dir: Path,
    entries: List[Dict[str, Any]],
    stations: List[str],
    start_year: int,
    end_year: int,
) -> Path:
    """Compile central manifest.json with full provenance and audit metadata."""
    manifest_data = {
        "version": "2.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _get_git_commit(),
        "year_range": [start_year, end_year],
        "stations": {
            st: {
                "timezone": STATION_METADATA[st]["timezone"],
                "name": STATION_METADATA[st]["name"],
            }
            for st in sorted(stations)
        },
        "total_files": len(entries),
        "total_station_days": sum(e["row_count"] for e in entries),
        "total_divergence_days": sum(e["divergence_days"] for e in entries),
        "files": entries,
    }
    manifest_file = out_dir / "manifest.json"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)
    logger.info(f"Saved manifest to {manifest_file}")
    return manifest_file


def main() -> None:
    """Main batch orchestration routine."""
    args = _parse_cli_arguments()
    raw_dir = Path(args.raw_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stations = [validate_active_station(s) for s in args.stations]
    logger.info(f"Starting Feature Store v2 build: {len(stations)} stations x [{args.start_year}, {args.end_year}]")

    if args.dry_run:
        print(f"[Dry Run] Would build {len(stations) * (args.end_year - args.start_year + 1)} partitions.")
        return

    slicer = ObservationSlicer()
    entries: List[Dict[str, Any]] = []
    t0 = time.time()

    for st in stations:
        for y in range(args.start_year, args.end_year + 1):
            info = _process_station_year(slicer, raw_dir, out_dir, st, y, args.force)
            if info:
                entries.append(info)

    elapsed = time.time() - t0
    manifest_path = _build_and_save_manifest(out_dir, entries, stations, args.start_year, args.end_year)
    total_days = sum(e["row_count"] for e in entries)
    print(f"\n=== Feature Store v2 Build Completed in {elapsed:.2f}s ===")
    print(f"Total Partitions: {len(entries)}/{len(stations) * (args.end_year - args.start_year + 1)}")
    print(f"Total Station-Days: {total_days}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
