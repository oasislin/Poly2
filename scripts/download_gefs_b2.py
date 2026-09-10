#!/usr/bin/env python3
"""GEFS Reforecast B2 Multi-Threaded Batch Downloader with Dashboard Integration.

Downloads non-stock fxx segments:
  - Short lead: [12, 18] (6-12h, 12-18h windows)
  - Long lead: [60, 66, 72, 78] (54-60h, 60-66h, 66-72h, 72-78h windows)
Across 2000-2019 x 5 members x 2 variables into external storage.

Features:
  - Bounded multi-threading with adaptive backoff to prevent IP banning.
  - S3 link health heartbeats.
  - Formatted progress logging strictly aligned with scripts/dashboard.py.
  - CSV state machine for seamless resumability.
"""

import argparse
import concurrent.futures
import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
import os
from pathlib import Path
import random
import struct
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from herbie import Herbie
from src.data_acquisition.gefs_fetcher import GEFSFetcher, check_data_link_health

logger = logging.getLogger("gefs_b2_downloader")

# Frozen Task A Union Segments (ADR-0008 D1/D4 & docs/reports/gefs_fxx_union_probe.md):
# Full union = [12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72, 78]
# Stock B1 covers: [24, 30, 36] and [42, 48, 54]
# New B2 gaps: [12, 18] (short window) and [60, 66, 72, 78] (long window)
B2_SHORT_WINDOW = [12, 18]
B2_LONG_WINDOW = [60, 66, 72, 78]
B2_WINDOWS = [B2_SHORT_WINDOW, B2_LONG_WINDOW]
B2_VARIABLES = ["tmax_2m", "tmin_2m"]
B2_MEMBERS = [0, 1, 2, 3, 4]
MEMBER_LABELS = {0: "c00", 1: "p01", 2: "p02", 3: "p03", 4: "p04"}

HEARTBEAT_INTERVAL_SECONDS = 5.0
THREAD_JOIN_TIMEOUT_SECONDS = 1.0
DEFAULT_BACKOFF_BASE = 2.0
DEFAULT_JITTER_MIN = 0.5
DEFAULT_JITTER_MAX = 2.0


@dataclass
class SliceResult:
    slice_idx: int
    member_label: str
    var_name: str
    window_label: str
    subset_hash: str
    size_bytes: int
    speed_kbps: int
    is_new: bool


@dataclass
class SliceDownloadTask:
    slice_idx: int
    dt: datetime
    var: str
    member: int
    window: List[int]
    raw_dir: str
    max_retries: int
    fetcher: GEFSFetcher


_active_slices_lock = threading.Lock()
_active_slices: Dict[str, dict] = {}


def _load_default_storage_root() -> str:
    """Load storage root dynamically from env or configs/default.yaml."""
    env_p = os.getenv("GEFS_DATA_ROOT")
    if env_p:
        return env_p
    cfg_file = Path(__file__).resolve().parents[1] / "configs" / "default.yaml"
    if cfg_file.exists():
        try:
            import yaml
            with open(cfg_file, "r", encoding="utf-8") as f:
                d = yaml.safe_load(f) or {}
                root = d.get("storage", {}).get("cold_storage_root")
                if root:
                    return str(root)
        except (yaml.YAMLError, OSError, KeyError) as exc:
            logger.debug(f"Failed to load storage config: {exc}")
    return "data/raw"


def _resolve_herbie_save_dir(raw_dir: str) -> str:
    """Normalize raw directory for Herbie to prevent duplicate gefs_reforecast nesting."""
    p = Path(raw_dir).resolve()
    if p.name == "gefs_reforecast":
        return str(p.parent)
    return str(p)


def parse_args():
    """Parse CLI arguments for B2 downloader."""
    parser = argparse.ArgumentParser(description="GEFS B2 Multi-Threaded Batch Downloader")
    parser.add_argument("--start-year", type=int, default=2000, help="Start year (inclusive)")
    parser.add_argument("--end-year", type=int, default=2019, help="End year (inclusive)")
    parser.add_argument("--threads", type=int, default=5, help="Worker threads (default 5)")
    parser.add_argument(
        "--raw-dir",
        type=str,
        default=_load_default_storage_root(),
        help="Target cold storage directory (automatically adapted to Herbie)",
    )
    parser.add_argument("--log-file", type=str, default=None, help="Path to write dashboard log")
    parser.add_argument("--state-file", type=str, default="data/gefs_b2_download_state.csv", help="State CSV")
    parser.add_argument("--max-retries", type=int, default=3, help="Retries per slice")
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        default=True,
        help="Continue downloading subsequent days if a single day fails (default: True)",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def count_grib2_messages(path: Path) -> int:
    """Accurately count GRIB2 messages using WMO Section 0 byte offsets."""
    try:
        with open(path, "rb") as fp:
            count = 0
            while True:
                header = fp.read(16)
                if not header or len(header) < 16:
                    break
                if header[:4] != b"GRIB" or header[7] != 2:
                    return -1
                msg_len = struct.unpack(">Q", header[8:16])[0]
                fp.seek(fp.tell() - 16 + msg_len)
                fp.seek(fp.tell() - 4)
                if fp.read(4) != b"7777":
                    return -1
                count += 1
                cur = fp.tell()
                fp.seek(0, 2)
                if cur >= fp.tell():
                    break
                fp.seek(cur)
            return count
    except Exception:
        return -1


def is_valid_grib2_slice(file_path: Path, expected_messages: int) -> bool:
    """Verify GRIB2 slice is intact and contains exact expected message count per WMO standard."""
    if not file_path.exists() or file_path.stat().st_size == 0:
        return False
    return count_grib2_messages(file_path) == expected_messages


def _execute_herbie_download(
    h: Herbie,
    search: str,
    local_path: Path,
    expected_messages: int,
    max_retries: int,
) -> int:
    """Execute Herbie download with retry loop and return valid slice size."""
    for attempt in range(1, max_retries + 1):
        try:
            local_path.unlink(missing_ok=True)
            h.download(search=search, overwrite=True)
            if is_valid_grib2_slice(local_path, expected_messages):
                return local_path.stat().st_size
            raise ValueError(
                f"Corrupted or incomplete GRIB2 slice (expected {expected_messages} msgs): {local_path.name}"
            )
        except Exception as exc:
            logger.warning(f"Retry {attempt}/{max_retries} for {local_path.name}: {exc}")
            if attempt < max_retries:
                time.sleep((DEFAULT_BACKOFF_BASE * attempt) + random.uniform(DEFAULT_JITTER_MIN, DEFAULT_JITTER_MAX))
    raise RuntimeError(f"Failed to download valid slice after {max_retries} retries: {local_path.name}")


def download_single_slice(
    h: Herbie,
    search: str,
    local_path: Path,
    expected_messages: int,
    expected_bytes: int = 0,
    meta: Optional[dict] = None,
    max_retries: int = 3,
) -> SliceResult:
    """Download single Herbie slice with structural GRIB2 validation and live tracking."""
    if meta is None:
        meta = {"idx": 0, "mem": "c00", "var": "unknown", "win": "unknown", "subset": ""}

    if is_valid_grib2_slice(local_path, expected_messages):
        return SliceResult(
            meta["idx"], meta["mem"], meta["var"], meta["win"], meta["subset"],
            local_path.stat().st_size, 0, is_new=False
        )

    s_key = f"#{meta['idx']:02d}_{meta['mem']}"
    with _active_slices_lock:
        _active_slices[s_key] = {
            "idx": meta["idx"], "mem": meta["mem"], "var": meta["var"],
            "win": meta["win"], "subset": meta["subset"], "path": local_path,
            "expected_bytes": expected_bytes, "start_t": time.perf_counter(),
        }

    try:
        t0 = time.perf_counter()
        sz = _execute_herbie_download(h, search, local_path, expected_messages, max_retries)
        dt = max(time.perf_counter() - t0, 0.001)
        spd = int((sz / 1024.0) / dt)
        return SliceResult(
            meta["idx"], meta["mem"], meta["var"], meta["win"], meta["subset"],
            sz, spd, is_new=True
        )
    finally:
        with _active_slices_lock:
            _active_slices.pop(s_key, None)


def _resolve_slice_expectations(h: Any, search: str, fallback_msgs: int) -> Tuple[int, int]:
    """Resolve authoritative message count and byte size from remote NOAA index."""
    if hasattr(h, "inventory") and callable(getattr(h, "inventory")):
        try:
            idx_df = h.inventory(search)
            if idx_df is not None and not idx_df.empty:
                exp_msgs = len(idx_df)
                if "start_byte" in idx_df and "end_byte" in idx_df:
                    exp_bytes = int((idx_df["end_byte"] - idx_df["start_byte"] + 1).sum())
                else:
                    exp_bytes = 0
                return exp_msgs, exp_bytes
        except Exception as exc:
            logger.debug(f"Remote index inventory lookup skipped: {exc}")
    return fallback_msgs, 0


def _download_slice_with_backoff(
    task: SliceDownloadTask,
    meta: dict,
    var_clean: str,
    mem_lbl: str,
    window_lbl: str,
) -> SliceResult:
    """Attempt Herbie instantiation, search building and slice download with backoff."""
    last_exc = None
    for attempt in range(1, task.max_retries + 1):
        try:
            h = Herbie(
                task.dt,
                model="gefs_reforecast",
                product="GEFSv12/reforecast",
                member=task.member,
                fxx=0,
                variable_level=task.var,
                save_dir=_resolve_herbie_save_dir(task.raw_dir),
                verbose=False,
            )
            search = task.fetcher.build_search(task.var, task.window)
            local = h.get_localFilePath(search)
            meta["subset"] = local.name.split("__")[0].replace("subset_", "")

            exp_msgs, exp_bytes = _resolve_slice_expectations(h, search, len(task.window))
            return download_single_slice(h, search, local, exp_msgs, exp_bytes, meta, task.max_retries)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                f"[RETRY] Slice #{task.slice_idx:02d} ({var_clean}_{mem_lbl}_{window_lbl}) "
                f"attempt {attempt}/{task.max_retries} failed ({exc})."
            )
            if attempt < task.max_retries:
                sleep_s = (DEFAULT_BACKOFF_BASE * attempt) + random.uniform(DEFAULT_JITTER_MIN, DEFAULT_JITTER_MAX)
                time.sleep(sleep_s)

    raise RuntimeError(
        f"Failed slice #{task.slice_idx:02d} ({var_clean}_{mem_lbl}_{window_lbl}) "
        f"after {task.max_retries} retries: {last_exc}"
    )


def _worker_task(task: SliceDownloadTask) -> SliceResult:
    """Worker task wrapper for ThreadPoolExecutor."""
    window_lbl = f"{task.window[0]}-{task.window[-1]}h"
    var_clean = "tmax" if "tmax" in task.var else "tmin"
    mem_lbl = MEMBER_LABELS.get(task.member, f"m{task.member}")
    meta = {
        "idx": task.slice_idx,
        "mem": mem_lbl,
        "var": var_clean,
        "win": window_lbl,
        "subset": "",
    }
    return _download_slice_with_backoff(task, meta, var_clean, mem_lbl, window_lbl)


def _format_heartbeat_progress(
    target_dt_str: str,
    day_idx: int,
    total_days: int,
    elapsed_sec: int,
) -> str:
    """Format intermediate [PROGRESS] heartbeat message showing all active slice threads."""
    with _active_slices_lock:
        active_items = list(_active_slices.values())

    cur_pct = (day_idx / total_days) * 100.0 if total_days > 0 else 0.0
    if not active_items:
        detail = "正在连接源站并解析索引 (Connecting & Parsing Index)..."
        return f"[PROGRESS] B2_UNION {target_dt_str} ({day_idx}/{total_days} {cur_pct:.1f}%) [已耗时 {elapsed_sec}s] | {detail}"

    now = time.perf_counter()
    mem_strs = []
    for item in sorted(active_items, key=lambda x: x["idx"]):
        p = item["path"]
        sz = p.stat().st_size if p.exists() else 0
        exp = item["expected_bytes"]
        pct = min((sz / exp) * 100.0, 99.9) if exp > 0 else (99.9 if sz > 0 else 0.0)
        dt = max(now - item["start_t"], 0.001)
        spd = int((sz / 1024.0) / dt)
        dl_mb = sz / 1_048_576.0
        tot_mb = (exp / 1_048_576.0) if exp > 0 else dl_mb
        tag = f"#{item['idx']:02d}_{item['mem']}"
        detail_tag = f"{item['var']}:{item['win']}:{item['subset']}"
        mem_strs.append(f"{tag}[{detail_tag}]: {pct:.1f}%({dl_mb:.1f}/{tot_mb:.1f}MB, {spd}KB/s)")

    detail = " ".join(mem_strs)
    return f"[PROGRESS] B2_UNION {target_dt_str} ({day_idx}/{total_days} {cur_pct:.1f}%) [已耗时 {elapsed_sec}s] [{len(active_items)}线程] | {detail}"


def _heartbeat_loop(stop_event: threading.Event, target_dt_str: str, day_idx: int, tot_days: int) -> None:
    """Heartbeat background thread emitting [PROGRESS] logs periodically."""
    t0 = time.perf_counter()
    while not stop_event.wait(timeout=HEARTBEAT_INTERVAL_SECONDS):
        now = time.perf_counter()
        elapsed = int(now - t0)
        line = _format_heartbeat_progress(target_dt_str, day_idx, tot_days, elapsed)
        logger.info(line)


def download_day_b2(
    fetcher: GEFSFetcher,
    dt: datetime,
    raw_dir: str,
    day_idx: int = 1,
    tot_days: Optional[int] = None,
    threads: int = 5,
    max_retries: int = 3,
) -> List[SliceResult]:
    """Download all B2 slices for one day in parallel with real-time heartbeat progress."""
    total_days = tot_days or ((date(dt.year, 12, 31) - date(dt.year, 1, 1)).days + 1)
    tasks = []
    slice_idx = 1
    for var in B2_VARIABLES:
        for mem in B2_MEMBERS:
            for window in B2_WINDOWS:
                tasks.append(
                    SliceDownloadTask(
                        slice_idx=slice_idx,
                        dt=dt,
                        var=var,
                        member=mem,
                        window=window,
                        raw_dir=raw_dir,
                        max_retries=max_retries,
                        fetcher=fetcher,
                    )
                )
                slice_idx += 1

    stop_event = threading.Event()
    hb_thread = threading.Thread(
        target=_heartbeat_loop,
        args=(stop_event, dt.strftime("%Y-%m-%d"), day_idx, total_days),
        daemon=True,
    )
    hb_thread.start()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
            return list(executor.map(_worker_task, tasks))
    finally:
        try:
            stop_event.set()
            hb_thread.join(timeout=THREAD_JOIN_TIMEOUT_SECONDS)
        except Exception as e:
            logger.debug(f"Heartbeat thread cleanup ignored: {e}")
        try:
            GEFSFetcher.reset_active_progress()
        except Exception as e:
            logger.debug(f"Active progress cleanup ignored: {e}")


def setup_loggers(log_file: Optional[str], start_year: int, end_year: int, verbose: bool = False) -> None:
    """Configure console and file loggers with dashboard-compatible metadata header."""
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        p = Path(log_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(
                f"# METADATA: pid={os.getpid()} start_year={start_year} end_year={end_year} "
                f"stations=ALL started_at={datetime.now().isoformat()}\n"
            )
        handlers.append(logging.FileHandler(p, mode="a", encoding="utf-8"))

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )


def format_progress_line(
    station_label: str,
    target_dt_str: str,
    day_idx: int,
    total_days: int,
    elapsed_sec: int,
    slice_results: Sequence[SliceResult],
) -> str:
    """Construct completed day progress line matching scripts/dashboard.py regex."""
    pct_day = (day_idx / total_days) * 100.0 if total_days > 0 else 100.0
    mem_parts = []
    for sr in sorted(slice_results, key=lambda x: x.slice_idx):
        mb = sr.size_bytes / 1_048_576.0
        tag = f"#{sr.slice_idx:02d}_{sr.member_label}"
        detail_tag = f"{sr.var_name}:{sr.window_label}:{sr.subset_hash}"
        mem_parts.append(f"{tag}[{detail_tag}]: 100.0%({mb:.1f}/{mb:.1f}MB, {sr.speed_kbps}KB/s)")

    items_str = " ".join(mem_parts) if mem_parts else "all slices verified"
    return f"[PROGRESS] {station_label} {target_dt_str} ({day_idx}/{total_days} {pct_day:.1f}%) [已耗时 {elapsed_sec}s] | {items_str}"



def load_state(state_file: Path) -> Dict[str, str]:
    """Load date completion state from CSV file."""
    state = {}
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                for row in reader:
                    if row and len(row) >= 2 and not row[0].startswith("#"):
                        state[row[0].strip()] = row[1].strip()
        except Exception as exc:
            logger.warning(f"Error loading state from {state_file}: {exc}")
    return state


def update_state(state_file: Path, date_str: str, status: str) -> None:
    """Record date status to CSV state file."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "a", encoding="utf-8") as f:
        f.write(f"{date_str},{status},{datetime.now().isoformat()}\n")


def check_anti_ban_guard(fetcher: GEFSFetcher) -> None:
    """Periodic health probe to detect network latency spikes and prevent IP banning."""
    health = check_data_link_health(timeout=3.0)
    if not health.get("healthy", True):
        logger.warning(f"⚠️ S3链路状态异常: {health['message']}，自适应等待 10s 保护 IP 信誉...")
        time.sleep(10.0)
    elif health.get("rtt_ms") and health["rtt_ms"] > 1500:
        logger.warning(f"⚠️ S3响应延迟过高 ({health['rtt_ms']}ms)，微调冷却 3s...")
        time.sleep(3.0)

def _download_day_with_self_healing(
    fetcher: GEFSFetcher,
    dt: datetime,
    raw_dir: str,
    day_idx: int,
    tot_days: int,
    threads: int,
    max_retries: int,
) -> List[SliceResult]:
    """Execute download_day_b2 with day-level recovery retry loop."""
    d_str = dt.strftime("%Y-%m-%d")
    for attempt in range(1, max_retries + 1):
        try:
            return download_day_b2(fetcher, dt, raw_dir, day_idx, tot_days, threads, max_retries)
        except Exception as exc:
            logger.warning(
                f"⚠️ 日期 {d_str} 处理遇到异常 (尝试 {attempt}/{max_retries}): {exc}。"
                f"自愈重试未完成切片..."
            )
            time.sleep((DEFAULT_BACKOFF_BASE * attempt) + random.uniform(DEFAULT_JITTER_MIN, DEFAULT_JITTER_MAX))
    raise RuntimeError(f"Day {d_str} failed after {max_retries} attempts")


def _process_single_day_b2(
    fetcher: GEFSFetcher,
    d_curr: date,
    raw_dir: str,
    state_file: Path,
    state: Dict[str, str],
    day_idx: int,
    tot_days: int,
    threads: int,
    max_retries: int,
    continue_on_error: bool,
) -> int:
    """Execute download and state persistence for one day, returning new slices count."""
    d_str = d_curr.strftime("%Y%m%d")
    dt = datetime(d_curr.year, d_curr.month, d_curr.day, 0, 0)
    t_day_start = time.perf_counter()
    try:
        results = _download_day_with_self_healing(fetcher, dt, raw_dir, day_idx, tot_days, threads, max_retries)
    except Exception as exc:
        if not continue_on_error:
            raise
        logger.error(f"❌ 日期 {d_str} 最终失败: {exc}。标记为 failed 并继续下一天...")
        update_state(state_file, d_str, "failed")
        state[d_str] = "failed"
        return 0

    elapsed_sec = int(time.perf_counter() - t_day_start)
    new_count = sum(1 for r in results if r.is_new)
    update_state(state_file, d_str, "done")
    state[d_str] = "done"

    prog_line = format_progress_line("ALL", d_curr.isoformat(), day_idx, tot_days, elapsed_sec, results)
    logger.info(prog_line)
    return new_count


def process_year_b2(
    fetcher: GEFSFetcher,
    yr: int,
    raw_dir: str,
    state_file: Path,
    state: Dict[str, str],
    threads: int,
    max_retries: int,
    continue_on_error: bool = True,
) -> Tuple[int, int]:
    """Process all days of a single year."""
    d_curr = date(yr, 1, 1)
    d_end = date(yr, 12, 31)
    tot_days = (d_end - d_curr).days + 1
    new_slices, day_idx = 0, 0
    t0_year = time.time()

    while d_curr <= d_end:
        day_idx += 1
        d_str = d_curr.strftime("%Y%m%d")
        if state.get(d_str) == "done":
            d_curr += timedelta(days=1)
            continue

        if day_idx % 30 == 0:
            check_anti_ban_guard(fetcher)

        new_slices += _process_single_day_b2(
            fetcher, d_curr, raw_dir, state_file, state, day_idx, tot_days, threads, max_retries, continue_on_error
        )
        d_curr += timedelta(days=1)

    logger.info(f"Year {yr} completed in {time.time() - t0_year:.1f}s. New slices: {new_slices}")
    return tot_days, new_slices


def main():
    args = parse_args()
    log_file = args.log_file or f"logs/download_b2_{args.start_year}_{args.end_year}.log"
    setup_loggers(log_file, args.start_year, args.end_year, args.verbose)
    state_file = Path(args.state_file)
    state = load_state(state_file)
    fetcher = GEFSFetcher(cache_dir=args.raw_dir, verbose=args.verbose)

    logger.info(f"Starting B2 batch download ({args.start_year}-{args.end_year}) with {args.threads} threads...")
    logger.info(f"Target raw directory: {args.raw_dir}")

    total_days_processed = 0
    total_new_slices = 0
    for yr in range(args.start_year, args.end_year + 1):
        days, new_s = process_year_b2(
            fetcher, yr, args.raw_dir, state_file, state, args.threads, args.max_retries, args.continue_on_error
        )
        total_days_processed += days
        total_new_slices += new_s

    logger.info(f"🎉 B2 batch download fully finished! Days: {total_days_processed}, Slices: {total_new_slices}")


if __name__ == "__main__":
    main()
