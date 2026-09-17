#!/usr/bin/env python3
"""
IEM Precision Sample Auditor (Phase 1.5 Task 04 QC Gate §4.1).

Randomly samples N station-days across the generated IEM dataset, extracts
the raw METAR text, parses the RMK T-group with an independent regex,
and asserts zero deviation against the Parquet dataset values:
assert abs(dataset_temp_c - raw_t_group_c) < 1e-5
assert abs(dataset_temp_f - raw_t_group_f) < 1e-4
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from src.data_processing.constants import ACTIVE_11_STATIONS
from src.utils.logger import get_logger

logger = get_logger("poly.scripts.audit_iem_precision")

DEFAULT_SAMPLE_COUNT: int = 20
DEFAULT_RANDOM_SEED: int = 42
T_GROUP_REGEX = re.compile(r"\bT([01])(\d{3})([01])(\d{3})\b")
TOLERANCE_CELSIUS: float = 1e-5
TOLERANCE_FAHRENHEIT: float = 1e-4


def _independent_parse_t_group(metar_text: str) -> Tuple[Optional[float], Optional[float]]:
    """Independent regex parser for METAR RMK T-group."""
    match = T_GROUP_REGEX.search(metar_text)
    if not match:
        return None, None
    sign_t, val_t = match.group(1), float(match.group(2)) / 10.0
    sign_d, val_d = match.group(3), float(match.group(4)) / 10.0
    temp_c = -val_t if sign_t == "1" else val_t
    dew_c = -val_d if sign_d == "1" else val_d
    return temp_c, dew_c


def _collect_available_parquet_files(data_dir: Path) -> List[Tuple[str, int, Path]]:
    """Scan data directory for all valid station-year parquet files."""
    available: List[Tuple[str, int, Path]] = []
    for st in ACTIVE_11_STATIONS:
        st_dir = data_dir / st
        if not st_dir.exists():
            continue
        for pq in sorted(st_dir.glob("*.parquet")):
            try:
                yr = int(pq.stem)
                available.append((st, yr, pq))
            except ValueError:
                continue
    return available


def audit_precision_samples(
    data_dir: Path,
    sample_count: int = DEFAULT_SAMPLE_COUNT,
    seed: int = DEFAULT_RANDOM_SEED,
) -> Tuple[List[Dict[str, Any]], bool]:
    """Perform independent precision sampling audit across parquet files."""
    files = _collect_available_parquet_files(data_dir)
    if not files:
        logger.error(f"No parquet files found in {data_dir} across active 11 stations.")
        return [], False

    random.seed(seed)
    # Shuffle available files and sample
    sampled_files = random.sample(files, min(sample_count, len(files)))
    results: List[Dict[str, Any]] = []
    all_passed = True

    for st, yr, pq_path in sampled_files:
        df = pd.read_parquet(pq_path)
        # Filter to rows that have RMK T-group parsed
        df_t = df[df["t_group_parsed"] == True]
        if df_t.empty:
            continue

        sample_row = df_t.sample(n=1, random_state=seed).iloc[0]
        raw_metar = sample_row["raw_metar"]
        ds_temp_c = float(sample_row["temp_c"])
        ds_temp_f = float(sample_row["temp_f"])

        indep_t_c, _ = _independent_parse_t_group(raw_metar)
        if indep_t_c is None:
            continue

        indep_t_f = round(indep_t_c * 1.8 + 32.0, 4)
        err_c = abs(ds_temp_c - indep_t_c)
        err_f = abs(ds_temp_f - indep_t_f)

        passed = err_c < TOLERANCE_CELSIUS and err_f < TOLERANCE_FAHRENHEIT
        if not passed:
            all_passed = False

        results.append({
            "station": st,
            "year": yr,
            "valid_utc": str(sample_row["valid_utc"]),
            "raw_metar": raw_metar,
            "dataset_temp_c": ds_temp_c,
            "t_group_temp_c": indep_t_c,
            "dataset_temp_f": ds_temp_f,
            "t_group_temp_f": indep_t_f,
            "error_c": err_c,
            "error_f": err_f,
            "passed": passed,
        })

        if len(results) >= sample_count:
            break

    return results, all_passed


def format_audit_table(results: List[Dict[str, Any]]) -> str:
    """Format audit results as a Markdown table."""
    lines = [
        "| # | Station | Timestamp (UTC) | Dataset (°C) | RMK T-Group (°C) | Dataset (°F) | RMK T-Group (°F) | Deviation | Status |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for idx, r in enumerate(results, start=1):
        status = "✅ PASS" if r["passed"] else "❌ FAIL"
        lines.append(
            f"| {idx} | `{r['station']}` | `{r['valid_utc'][:16]}` | {r['dataset_temp_c']:.1f}°C | "
            f"{r['t_group_temp_c']:.1f}°C | {r['dataset_temp_f']:.2f}°F | {r['t_group_temp_f']:.2f}°F | "
            f"{r['error_c']:.5f}°C | {status} |"
        )
    return "\n".join(lines)


def main() -> int:
    """CLI entry point for precision sample audit."""
    parser = argparse.ArgumentParser(description="Audit IEM dataset precision against raw T-group")
    parser.add_argument("--data-dir", type=str, default="data/raw/iem", help="IEM data directory")
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLE_COUNT, help="Sample count (default: 20)")
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED, help="Random seed")
    args = parser.parse_args()

    results, passed = audit_precision_samples(Path(args.data_dir), args.samples, args.seed)
    print(format_audit_table(results))
    print(f"\nPrecision Audit Result: {len(results)} samples audited. Passed: {passed}")
    return 0 if passed and len(results) >= args.samples else 1


if __name__ == "__main__":
    sys.exit(main())
