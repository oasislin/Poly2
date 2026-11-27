#!/usr/bin/env python3
"""Safely compress historical M7 JSONL audit logs (`dir_date < today_utc`) to `.jsonl.gz`."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import gzip
import hashlib
import os
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple


def _iter_historical_jsonl_files(
    audit_root: Path, *, execution_mode: str, today_utc: date
) -> Iterable[Path]:
    modes = ("PAPER", "LIVE") if execution_mode == "ALL" else (execution_mode,)
    for mode in modes:
        mode_dir = audit_root / mode
        if not mode_dir.is_dir():
            continue
        for day_dir in sorted(p for p in mode_dir.iterdir() if p.is_dir()):
            try:
                dir_date = date.fromisoformat(day_dir.name)
            except ValueError:
                continue
            if dir_date >= today_utc:
                continue
            for jsonl in sorted(day_dir.glob("*.jsonl")):
                if jsonl.is_file():
                    yield jsonl


def _verify_gzip_matches_source(gz_path: Path, *, expected_bytes: int, expected_sha256: str) -> None:
    actual_bytes = 0
    hasher = hashlib.sha256()
    with gzip.open(gz_path, "rb") as gz_in:
        while True:
            chunk = gz_in.read(1024 * 1024)
            if not chunk:
                break
            actual_bytes += len(chunk)
            hasher.update(chunk)
    if actual_bytes != expected_bytes or hasher.hexdigest() != expected_sha256:
        raise ValueError(f"Gzip integrity mismatch for {gz_path}")


def archive_single_jsonl(src: Path, *, dry_run: bool = False) -> Tuple[int, int]:
    """Compress one historical `.jsonl` atomically with SHA-256 verification and return `(src_bytes, gz_bytes)`."""
    src_bytes = src.stat().st_size
    if dry_run:
        return src_bytes, src_bytes
    tmp_gz = src.with_name(src.name + f".gz.{os.getpid()}.tmp")
    final_gz = src.with_name(src.name + ".gz")
    hasher = hashlib.sha256()
    total_read = 0
    try:
        with src.open("rb") as fin, gzip.open(tmp_gz, "wb", compresslevel=6) as gz_out:
            while True:
                chunk = fin.read(1024 * 1024)
                if not chunk:
                    break
                total_read += len(chunk)
                hasher.update(chunk)
                gz_out.write(chunk)
        _verify_gzip_matches_source(tmp_gz, expected_bytes=total_read, expected_sha256=hasher.hexdigest())
        os.replace(tmp_gz, final_gz)
        src.unlink()
    except Exception:
        if tmp_gz.exists():
            tmp_gz.unlink()
        raise
    return src_bytes, final_gz.stat().st_size


def archive_historical_logs(
    *, audit_root: Path, execution_mode: str = "PAPER", today_utc: Optional[date] = None, dry_run: bool = False
) -> List[Tuple[Path, int, int]]:
    """Archive all eligible historical JSONL files strictly older than `today_utc`."""
    ref_day = today_utc or datetime.now(timezone.utc).date()
    results: List[Tuple[Path, int, int]] = []
    for path in _iter_historical_jsonl_files(audit_root, execution_mode=execution_mode, today_utc=ref_day):
        before_b, after_b = archive_single_jsonl(path, dry_run=dry_run)
        results.append((path, before_b, after_b))
    return results


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Archive historical M7 audit logs (< today UTC) to .jsonl.gz")
    parser.add_argument("--audit-root", type=Path, default=Path("data/audit_logs"))
    parser.add_argument("--execution-mode", choices=("PAPER", "LIVE", "ALL"), default="PAPER")
    parser.add_argument("--today-utc", type=str, default=None, help="Override UTC reference date YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", default=False)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    ref_day = date.fromisoformat(args.today_utc) if args.today_utc else datetime.now(timezone.utc).date()
    rows = archive_historical_logs(
        audit_root=args.audit_root, execution_mode=args.execution_mode, today_utc=ref_day, dry_run=args.dry_run
    )
    total_before = sum(r[1] for r in rows)
    total_after = sum(r[2] for r in rows)
    for path, b_in, b_out in rows:
        ratio = (b_out / b_in * 100.0) if b_in else 100.0
        print(f"{'[DRY-RUN] ' if args.dry_run else ''}{path}: {b_in} -> {b_out} bytes ({ratio:.1f}%)")
    print(f"files={len(rows)} total_before={total_before} total_after={total_after} today_utc={ref_day.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
