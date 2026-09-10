#!/usr/bin/env python3
"""
Lightweight Web Dashboard for Real-time GEFS Batch Download & System Monitoring.

Zero external dependencies (uses standard Python library).
Usage:
  python scripts/dashboard.py
  python scripts/dashboard.py --port 8080
"""

import argparse
import calendar
import http.server
import json
import os
import re
import socketserver
import time
import urllib.error
import urllib.request
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from src.data_acquisition.gefs_fetcher import check_data_link_health

import yaml

def _load_storage_root() -> Path:
    """Load storage root dynamically from environment or configs/default.yaml."""
    env_p = os.getenv("GEFS_DATA_ROOT")
    if env_p:
        return Path(env_p)
    cfg_file = BASE_DIR / "configs" / "default.yaml"
    if cfg_file.exists():
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                d = yaml.safe_load(f) or {}
                root = d.get("storage", {}).get("cold_storage_root")
                if root:
                    return Path(root)
        except (yaml.YAMLError, OSError, KeyError):
            pass
    return Path("/Volumes/EricSSD/Poly RawData/gefs_reforecast")

COLD_STORAGE_ROOT = _load_storage_root()
SLICES_PER_DAY = 20


class MatrixScanResult(NamedTuple):
    summary: List[dict]
    completed_slices: int
    expected_slices: int
    completed_days: int
    expected_days: int

# In-memory S3 health cache (10s TTL)
_s3_health_cache = {"data": None, "timestamp": 0}


def probe_s3_health():
    now = time.time()
    if _s3_health_cache["data"] and (now - _s3_health_cache["timestamp"] < 10.0):
        return _s3_health_cache["data"]

    res = check_data_link_health(timeout=3.0)
    _s3_health_cache["data"] = res
    _s3_health_cache["timestamp"] = now
    return res


def is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _extract_metadata_header(log_path: Path) -> Tuple[Optional[int], str, str]:
    """Extract PID, year range, and stations from log file header."""
    pid, year_range, stations = None, "未知", "ALL"
    if not log_path.exists():
        return pid, year_range, stations
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "# METADATA:" in line:
                    m = re.search(r"pid=(\d+).*?start_year=(\d+).*?end_year=(\d+).*?stations=([\w,]+)", line)
                    if m:
                        pid = int(m.group(1))
                        year_range = f"{m.group(2)}~{m.group(3)} 年"
                        stations = m.group(4)
    except (OSError, UnicodeDecodeError):
        pass
    return pid, year_range, stations


def _parse_latest_progress(tail_text: str) -> Optional[Dict[str, Any]]:
    """Parse latest [PROGRESS] line from tail text."""
    prog_lines = [line for line in tail_text.splitlines() if "[PROGRESS]" in line]
    if not prog_lines:
        return None
    m_head = re.search(
        r"\[PROGRESS\]\s+([A-Z0-9_]+)\s+([\d\-]+)\s+\(([\d\/]+\s+[\d\.]+%)\)\s*(?:\[已耗时\s*(\d+)s\])?\s*(?:\[\d+线程\])?\s*\|\s*(.*)",
        prog_lines[-1],
    )
    if not m_head:
        return None

    station, target_date, day_progress = m_head.group(1), m_head.group(2), m_head.group(3)
    elapsed = int(m_head.group(4)) if m_head.group(4) else 0
    members = {}
    pattern = r"(#\d+_[a-z0-9]+|c\d{2}|p\d{2})(?:\[([\w:\-]+)\])?:\s*([\d\.]+)%\(([\d\.]+)\/([\d\.]+)MB,\s*(\d+)KB\/s\)"
    for m_item in re.finditer(pattern, m_head.group(5)):
        raw_key = m_item.group(1)
        raw_detail = m_item.group(2) or ""
        parts = raw_detail.split(":")
        var_lbl = parts[0] if len(parts) > 0 else ""
        win_lbl = parts[1] if len(parts) > 1 else ""
        sub_lbl = parts[2] if len(parts) > 2 else ""
        members[raw_key] = {
            "key": raw_key,
            "var": var_lbl,
            "window": win_lbl,
            "subset": sub_lbl,
            "pct": float(m_item.group(3)),
            "downloaded_mb": float(m_item.group(4)),
            "total_mb": float(m_item.group(5)),
            "speed_kb": int(m_item.group(6)),
        }
    return {
        "station": station,
        "target_date": target_date,
        "day_progress": day_progress,
        "elapsed_seconds": elapsed,
        "members": members,
    }


def parse_log_file(log_path: Path):
    if not log_path.exists():
        return None

    stat = log_path.stat()
    age_seconds = time.time() - stat.st_mtime
    pid, year_range, stations = _extract_metadata_header(log_path)
    is_alive = is_pid_running(pid) if pid is not None else (age_seconds < 45.0)

    tail_text = ""
    try:
        with open(log_path, "rb") as f:
            read_len = min(stat.st_size, 4096)
            f.seek(stat.st_size - read_len)
            tail_text = f.read(read_len).decode("utf-8", errors="ignore")
    except Exception:
        pass

    latest_progress = _parse_latest_progress(tail_text)
    return {
        "log_name": log_path.name,
        "pid": pid,
        "is_alive": is_alive,
        "year_range": year_range or "批量下载窗口",
        "stations": stations or "全站点",
        "last_update_age": int(age_seconds),
        "latest_progress": latest_progress,
    }


def _read_state_csv_dates(path: Path) -> List[str]:
    """Extract valid 8-digit date strings from a state CSV."""
    dates = []
    if not path.exists():
        return dates
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 2 and parts[1].strip() == "done":
                    d_str = parts[0].strip()
                    if len(d_str) == 8 and d_str.isdigit():
                        dates.append(d_str)
    except Exception:
        pass
    return dates


def _load_b2_completed_dates(data_dir: Optional[Path] = None) -> set:
    data_dir = data_dir or (BASE_DIR / "data")
    completed = set()
    if not data_dir.exists():
        return completed
    for state_file in sorted(data_dir.glob("gefs_b2_download_state*.csv")):
        completed.update(_read_state_csv_dates(state_file))
    return completed


def _is_valid_in_flight_slice(p: Path) -> bool:
    """Filter out macOS shadows, idx files, and pre-existing B1 stock files (3872/c1fa)."""
    name = p.name
    if not name.endswith(".grib2") or name.startswith("._") or name.endswith(".idx"):
        return False
    if "__" in name:
        prefix = name.split("__")[0]
        if prefix.endswith("3872") or prefix.endswith("c1fa"):
            return False
    return True


def _count_in_flight_slices(
    active_dates: set,
    completed_dates: set,
    storage_root: Optional[Path] = None,
) -> Dict[str, int]:
    """Count slice files (.grib2) on disk for active dates not yet in completed_dates."""
    root = storage_root or COLD_STORAGE_ROOT
    in_flight = {}
    if not root.exists() or not active_dates:
        return in_flight

    for d_str in active_dates:
        if d_str in completed_dates or len(d_str) != 8 or not d_str.isdigit():
            continue
        yr = d_str[:4]
        target_dir = root / d_str
        if target_dir.exists():
            try:
                cnt = len([p for p in target_dir.glob("*.grib2") if _is_valid_in_flight_slice(p)])
                if cnt > 0:
                    in_flight[yr] = in_flight.get(yr, 0) + min(cnt, SLICES_PER_DAY)
            except Exception:
                pass
    return in_flight


def scan_matrix(
    in_flight_by_year: Optional[Dict[str, int]] = None,
    data_dir: Optional[Path] = None,
) -> MatrixScanResult:
    in_flight_by_year = in_flight_by_year or {}
    completed_dates = _load_b2_completed_dates(data_dir)
    summary = []
    tot_exp_slices, tot_done_slices = 0, 0
    tot_exp_days, tot_done_days = 0, 0

    for yr in range(2000, 2020):
        days_in_year = 366 if calendar.isleap(yr) else 365
        year_prefix = str(yr)
        year_done_days = sum(1 for d in completed_dates if d.startswith(year_prefix))

        year_exp_slices = days_in_year * SLICES_PER_DAY
        in_flight_count = in_flight_by_year.get(year_prefix, 0)
        year_done_slices = (year_done_days * SLICES_PER_DAY) + in_flight_count

        pct = round((year_done_slices / year_exp_slices) * 100, 2)
        has_progress = (year_done_days > 0 or in_flight_count > 0)
        status = "done" if year_done_days >= days_in_year else ("in_progress" if has_progress else "pending")

        tot_exp_slices += year_exp_slices
        tot_done_slices += year_done_slices
        tot_exp_days += days_in_year
        tot_done_days += year_done_days

        summary.append({
            "year": yr,
            "total_days": days_in_year,
            "completed_days": year_done_days,
            "total_slices": year_exp_slices,
            "completed_slices": year_done_slices,
            "in_flight": in_flight_count,
            "overall_pct": pct,
            "status": status,
            "sh_cnt": year_done_days,
            "den_cnt": year_done_days,
        })

    return MatrixScanResult(summary, tot_done_slices, tot_exp_slices, tot_done_days, tot_exp_days)


def _format_file_item(mtime: float, sz: int, p: Path, now: float) -> dict:
    """Format single recent file entry with relative age and size."""
    age_s = max(0, int(now - mtime))
    return {
        "name": p.name,
        "path": f"{p.parent.name}/{p.name}",
        "size_kb": round(sz / 1024, 1),
        "size_mb": round(sz / (1024 * 1024), 2),
        "time_str": datetime.fromtimestamp(mtime).strftime("%H:%M:%S"),
        "age_str": f"{age_s}秒前" if age_s < 60 else f"{age_s//60}分{age_s%60}秒前",
    }


def scan_recent_files(
    active_dates: Optional[set] = None,
    storage_root: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    limit: int = 8,
) -> List[dict]:
    root = storage_root or COLD_STORAGE_ROOT
    if not root.exists():
        return []

    target_dates = {d for d in (active_dates or set()) if len(d) == 8 and d.isdigit()}
    dd = data_dir or (BASE_DIR / "data")
    if dd.exists():
        for sf in dd.glob("gefs_b2_download_state*.csv"):
            recent_csv_dates = _read_state_csv_dates(sf)[-3:]
            target_dates.update(recent_csv_dates)

    files = []
    now = time.time()
    for d_str in target_dates:
        td = root / d_str
        if td.exists():
            try:
                for p in td.glob("*.grib2"):
                    if not p.name.startswith("._") and not p.name.endswith(".idx"):
                        try:
                            files.append((p.stat().st_mtime, p.stat().st_size, p))
                        except Exception:
                            pass
            except Exception:
                pass

    files.sort(key=lambda x: x[0], reverse=True)
    return [_format_file_item(mtime, sz, p, now) for mtime, sz, p in files[:limit]]


def discover_running_processes():
    """Discover active download processes directly from OS."""
    import subprocess
    active_procs = []
    try:
        res = subprocess.run(["ps", "-eo", "pid,command"], capture_output=True, text=True, check=True)
        for line in res.stdout.splitlines():
            is_dl = ("download_gefs_batch.py" in line or "download_gefs_b2.py" in line)
            if is_dl and "grep" not in line:
                parts = line.strip().split(None, 1)
                if len(parts) == 2:
                    pid_str, cmd = parts
                    pid = int(pid_str) if pid_str.isdigit() else None
                    if pid and pid != os.getpid():
                        m_start = re.search(r"--start-year\s+(\d+)", cmd)
                        m_end = re.search(r"--end-year\s+(\d+)", cmd)
                        m_log = re.search(r"--log-file\s+([\S]+)", cmd)
                        s_yr = m_start.group(1) if m_start else "2000"
                        e_yr = m_end.group(1) if m_end else "2019"
                        def_log = f"logs/download_b2_{s_yr}_{e_yr}.log" if "download_gefs_b2" in line else f"logs/worker_{s_yr}_{e_yr}.log"
                        log_path = Path(m_log.group(1)) if m_log else BASE_DIR / def_log
                        active_procs.append({
                            "pid": pid,
                            "year_range": f"{s_yr} 年" if s_yr == e_yr else f"{s_yr}~{e_yr} 年",
                            "log_path": log_path,
                        })
    except Exception:
        pass
    return active_procs


def _collect_workers(candidate_logs: list, running_procs: list, running_pids: set) -> List[dict]:
    workers = []
    seen_logs = set()
    for p in candidate_logs:
        if p.name in seen_logs:
            continue
        w = parse_log_file(p)
        if w:
            for rp in running_procs:
                if rp["log_path"].name == p.name:
                    w["pid"] = rp["pid"]
                    w["is_alive"] = True
                    w["year_range"] = rp["year_range"]
                    break
            if w["is_alive"] or (w["pid"] in running_pids) or w["last_update_age"] < 180:
                workers.append(w)
                seen_logs.add(p.name)

    for rp in running_procs:
        if not any(w.get("pid") == rp["pid"] for w in workers):
            workers.append({
                "log_name": "控制台标准输出 (stdout)",
                "pid": rp["pid"],
                "is_alive": True,
                "year_range": rp["year_range"],
                "stations": "全站点",
                "last_update_age": 0,
                "latest_progress": None,
            })
    return workers


def _find_candidate_logs(running_procs: list) -> List[Path]:
    """Gather candidate log files from logs directory and active processes."""
    logs = list(sorted((BASE_DIR / "logs").glob("*.log"))) if (BASE_DIR / "logs").exists() else []
    logs.extend(sorted(BASE_DIR.glob("download_*.log")))
    for rp in running_procs:
        if rp["log_path"] not in logs and rp["log_path"].exists():
            logs.append(rp["log_path"])
    return logs


def _extract_active_dates(workers: list, completed_dates: Optional[set] = None) -> set:
    """Extract valid 8-digit target dates in progress across live workers (including stdout)."""
    dates = set()
    completed = completed_dates or set()
    for w in workers:
        if not w.get("is_alive"):
            continue
        lp = w.get("latest_progress")
        if lp:
            tgt = lp.get("target_date", "").replace("-", "").strip()
            if len(tgt) == 8 and tgt.isdigit():
                dates.add(tgt)
            continue
        # Fallback for stdout-only workers: deduce candidate active date from year_range & completed_dates
        yr_match = re.search(r"(\d{4})", w.get("year_range", ""))
        if yr_match:
            yr_str = yr_match.group(1)
            done_in_yr = sorted([d for d in completed if d.startswith(yr_str)])
            if not done_in_yr:
                dates.add(f"{yr_str}0101")
            else:
                try:
                    last_dt = datetime.strptime(done_in_yr[-1], "%Y%m%d")
                    dates.add((last_dt + timedelta(days=1)).strftime("%Y%m%d"))
                except Exception:
                    pass
    return dates


def get_full_status():
    running_procs = discover_running_processes()
    running_pids = {p["pid"] for p in running_procs}
    candidate_logs = _find_candidate_logs(running_procs)
    workers = _collect_workers(candidate_logs, running_procs, running_pids)
    completed_dates = _load_b2_completed_dates()

    active_dates = _extract_active_dates(workers, completed_dates)
    in_flight = _count_in_flight_slices(active_dates, completed_dates)
    matrix_res = scan_matrix(in_flight)
    recent = scan_recent_files(active_dates, limit=8)
    health = probe_s3_health()

    exp_s = matrix_res.expected_slices
    overall_pct = round((matrix_res.completed_slices / exp_s) * 100, 2) if exp_s > 0 else 0.0

    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "s3_health": health,
        "workers": workers,
        "matrix": matrix_res.summary,
        "progress_summary": {
            "completed_slices": matrix_res.completed_slices,
            "expected_slices": matrix_res.expected_slices,
            "completed_days": matrix_res.completed_days,
            "expected_days": matrix_res.expected_days,
            "overall_pct": overall_pct,
        },
        "recent_files": recent,
    }


HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NOAA GEFS 数据吞吐与下载实时监控大盘</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    @keyframes pulse-slow {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.85; transform: scale(0.99); }
    }
    .live-pulse { animation: pulse-slow 3s infinite ease-in-out; }
    .glass-card {
      background: rgba(30, 41, 59, 0.7);
      backdrop-filter: blur(12px);
      border: 1px solid rgba(255, 255, 255, 0.08);
    }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen p-4 md:p-8 font-sans antialiased">
  <div class="max-w-7xl mx-auto space-y-6">

    <!-- Header -->
    <header class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 bg-slate-900/80 p-6 rounded-2xl border border-slate-800 shadow-2xl">
      <div>
        <div class="flex items-center gap-3">
          <div class="w-3 h-3 rounded-full bg-emerald-500 animate-ping"></div>
          <h1 class="text-2xl md:text-3xl font-extrabold tracking-tight bg-gradient-to-r from-emerald-400 via-teal-300 to-cyan-400 bg-clip-text text-transparent">
            NOAA GEFS 自动化数据吞吐监控大盘
          </h1>
        </div>
        <p class="text-slate-400 text-sm mt-1">
          2000-2019 年代际高精度物理概率模型数据管道 · 全美 11 核心交易站点切片冷归档
        </p>
      </div>

      <div class="flex items-center gap-4">
        <div id="s3-pill" class="flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-800 border border-slate-700 text-sm">
          <span class="w-2.5 h-2.5 rounded-full bg-emerald-400"></span>
          <span id="s3-text" class="text-slate-300 font-medium">S3: 探测中...</span>
        </div>
        <div class="text-right">
          <div id="clock" class="text-lg font-mono font-bold text-slate-200">--:--:--</div>
          <div class="text-xs text-slate-500">2 秒自动无缝刷新</div>
        </div>
      </div>
    </header>

    <!-- Overview Stats Banner -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
      <div class="glass-card p-5 rounded-2xl">
        <div class="text-slate-400 text-xs font-semibold uppercase tracking-wider">总完成度 (切片视角 / 20 年代际)</div>
        <div class="mt-2 flex items-baseline gap-2">
          <span id="total-pct" class="text-3xl font-extrabold text-emerald-400">0.0%</span>
          <span id="total-counts" class="text-xs text-slate-400">0 / 146,100 切片 (0 / 7,305 天)</span>
        </div>
        <div class="w-full bg-slate-800 h-2 rounded-full mt-3 overflow-hidden">
          <div id="total-bar" class="bg-gradient-to-r from-emerald-500 to-teal-400 h-full rounded-full transition-all duration-500" style="width: 0%"></div>
        </div>
      </div>

      <div class="glass-card p-5 rounded-2xl">
        <div class="text-slate-400 text-xs font-semibold uppercase tracking-wider">活跃下载工作窗口</div>
        <div id="active-workers-count" class="mt-2 text-3xl font-extrabold text-cyan-400">0 个</div>
        <div class="text-xs text-slate-400 mt-2">并发进程状态与实时心跳</div>
      </div>

      <div class="glass-card p-5 rounded-2xl">
        <div class="text-slate-400 text-xs font-semibold uppercase tracking-wider">目标气象站点</div>
        <div class="mt-2 text-3xl font-extrabold text-indigo-400">11 个</div>
        <div class="text-xs text-slate-400 mt-2">全美 11 核心交易站点 (Polymarket 活跃盘口)</div>
      </div>

      <div class="glass-card p-5 rounded-2xl">
        <div class="text-slate-400 text-xs font-semibold uppercase tracking-wider">集合与切片规格</div>
        <div class="mt-2 text-3xl font-extrabold text-amber-400">20 切片/日</div>
        <div class="text-xs text-slate-400 mt-2">5 集合成员 × 4 任务 (TMAX/TMIN × 2 窗口)</div>
      </div>
    </div>

    <!-- Active Live Workers Section -->
    <section class="space-y-4">
      <div class="flex items-center justify-between">
        <h2 class="text-lg font-bold text-slate-200 flex items-center gap-2">
          <span class="inline-block w-2 h-5 bg-cyan-400 rounded-full"></span>
          活跃下载工作窗口（实时 5 成员分块切片进度与速度）
        </h2>
      </div>

      <div id="workers-container" class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- Worker Cards injected by JS -->
      </div>
    </section>

    <!-- 20-Year Matrix Section -->
    <section class="space-y-4">
      <div class="flex items-center justify-between">
        <h2 class="text-lg font-bold text-slate-200 flex items-center gap-2">
          <span class="inline-block w-2 h-5 bg-emerald-400 rounded-full"></span>
          20 年代际全景切片大盘 (2000 ~ 2019 · 146,100 切片)
        </h2>
      </div>

      <div id="matrix-grid" class="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-10 gap-3">
        <!-- Year Cards injected by JS -->
      </div>
    </section>

    <!-- Recent Files Stream -->
    <section class="space-y-4">
      <div class="flex items-center justify-between">
        <h2 class="text-lg font-bold text-slate-200 flex items-center gap-2">
          <span class="inline-block w-2 h-5 bg-indigo-400 rounded-full"></span>
          最近数据落盘流水 (心跳实时验活)
        </h2>
      </div>

      <div class="glass-card rounded-2xl overflow-hidden">
        <div id="recent-files-list" class="divide-y divide-slate-800 text-sm">
          <!-- Files injected by JS -->
        </div>
      </div>
    </section>

    <!-- Footer -->
    <footer class="text-center text-xs text-slate-500 py-4">
      Polymarket 温度量化系统 · Phase 1 高精度物理概率模型 · Dashboard v1.0
    </footer>
  </div>

  <script>
    async function updateDashboard() {
      try {
        const res = await fetch('/api/status');
        if (!res.ok) return;
        const data = await res.json();

        // 1. Clock & S3
        document.getElementById('clock').innerText = data.timestamp.split(' ')[1];
        const s3 = data.s3_health;
        const s3Pill = document.getElementById('s3-pill');
        const s3Text = document.getElementById('s3-text');
        if (s3.healthy) {
          s3Pill.className = "flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-950/60 border border-emerald-800/80 text-sm";
          s3Text.innerText = "NOAA S3: " + s3.message;
          s3Text.className = "text-emerald-300 font-medium";
        } else {
          s3Pill.className = "flex items-center gap-2 px-4 py-2 rounded-xl bg-rose-950/60 border border-rose-800/80 text-sm";
          s3Text.innerText = "NOAA S3: " + s3.message;
          s3Text.className = "text-rose-300 font-medium";
        }

        // 2. Summary
        const sum = data.progress_summary;
        document.getElementById('total-pct').innerText = sum.overall_pct + '%';
        document.getElementById('total-counts').innerText = 
          sum.completed_slices.toLocaleString() + ' / ' + sum.expected_slices.toLocaleString() + ' 切片 (' +
          sum.completed_days + ' / ' + sum.expected_days + ' 天)';
        document.getElementById('total-bar').style.width = sum.overall_pct + '%';

        // 3. Workers
        const wContainer = document.getElementById('workers-container');
        const aliveWorkers = data.workers.filter(w => w.is_alive);
        document.getElementById('active-workers-count').innerText = aliveWorkers.length + ' 个活跃';

        if (data.workers.length === 0) {
          wContainer.innerHTML = '<div class="col-span-full glass-card p-8 rounded-2xl text-center text-slate-400">当前未启动任何 download_gefs_b2 下载进程</div>';
        } else {
          wContainer.innerHTML = data.workers.map(w => {
            const statusBadge = w.is_alive 
              ? '<span class="px-2.5 py-1 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-xs font-semibold flex items-center gap-1.5"><span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>正在运行</span>'
              : '<span class="px-2.5 py-1 rounded-lg bg-slate-800 text-slate-400 text-xs font-medium">已退出 / 空闲</span>';

            let progressContent = '';
            if (w.latest_progress && w.latest_progress.members) {
              const p = w.latest_progress;
              const mems = p.members;
              const keys = Object.keys(mems).length > 0 ? Object.keys(mems) : ['c00', 'p01', 'p02', 'p03', 'p04'];

              progressContent = `
                <div class="space-y-3 mt-4 pt-4 border-t border-slate-800">
                  <div class="flex justify-between items-center text-xs">
                    <span class="font-bold text-cyan-300 tracking-wider">🎯 当前拉取: ${p.station} ${p.target_date}</span>
                    <span class="text-slate-400 font-mono">年进度: ${p.day_progress} · 已耗时 ${p.elapsed_seconds}s</span>
                  </div>

                  <div class="space-y-2.5">
                    ${keys.map(k => {
                      const m = mems[k] || { pct: 0, downloaded_mb: 0, total_mb: 0, speed_kb: 0, var: '', window: '', subset: '' };
                      const isDone = m.pct >= 100;
                      const barColor = isDone ? 'bg-emerald-500' : 'bg-gradient-to-r from-cyan-500 to-blue-500';
                      const varBadge = m.var ? `<span class="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 text-[10px] font-semibold uppercase">${m.var}</span>` : '';
                      const winBadge = m.window ? `<span class="px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 text-[10px] font-mono">${m.window}</span>` : '';
                      const subBadge = m.subset ? `<span class="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px] font-mono">subset_${m.subset}</span>` : '';
                      return `
                        <div class="bg-slate-900/40 p-2 rounded-xl border border-slate-800/60">
                          <div class="flex justify-between items-center text-xs font-mono mb-1.5">
                            <div class="flex items-center gap-1.5">
                              <span class="text-slate-200 font-bold">${k}</span>
                              ${varBadge}
                              ${winBadge}
                              ${subBadge}
                            </div>
                            <span class="text-slate-400">${m.pct.toFixed(1)}% (${m.downloaded_mb.toFixed(1)}/${m.total_mb.toFixed(1)}MB) <span class="text-cyan-400 font-bold">${m.speed_kb}KB/s</span></span>
                          </div>
                          <div class="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                            <div class="${barColor} h-full rounded-full transition-all duration-300" style="width: ${Math.min(m.pct, 100)}%"></div>
                          </div>
                        </div>
                      `;
                    }).join('')}
                  </div>
                </div>
              `;
            } else {
              progressContent = `<div class="text-xs text-slate-500 mt-4 py-2">暂无切片脉冲数据 (等待下一心跳时次)</div>`;
            }

            return `
              <div class="glass-card p-6 rounded-2xl border ${w.is_alive ? 'border-cyan-500/30' : 'border-slate-800'} shadow-xl">
                <div class="flex justify-between items-start">
                  <div>
                    <h3 class="text-base font-bold text-slate-100">${w.year_range}</h3>
                    <div class="text-xs text-slate-400 mt-0.5">PID: ${w.pid || 'N/A'} · 日志: ${w.log_name} (${w.last_update_age}秒前更新)</div>
                  </div>
                  ${statusBadge}
                </div>
                ${progressContent}
              </div>
            `;
          }).join('');
        }

        // 4. Matrix
        const mGrid = document.getElementById('matrix-grid');
        mGrid.innerHTML = data.matrix.map(item => {
          let cardBg = "bg-slate-900/60 border-slate-800 text-slate-500";
          let statusDot = "bg-slate-600";
          let pctColor = "text-slate-400";
          if (item.status === 'done') {
            cardBg = "bg-emerald-950/30 border-emerald-800/40 text-slate-200";
            statusDot = "bg-emerald-400";
            pctColor = "text-emerald-400 font-bold";
          } else if (item.status === 'in_progress') {
            cardBg = "bg-cyan-950/40 border-cyan-700/60 text-slate-100 ring-1 ring-cyan-500/40";
            statusDot = "bg-cyan-400 animate-pulse";
            pctColor = "text-cyan-300 font-bold";
          }

          return `
            <div class="p-3 rounded-xl border ${cardBg} flex flex-col justify-between text-xs">
              <div class="flex justify-between items-center">
                <span class="font-bold text-sm text-slate-200">${item.year}</span>
                <span class="w-2 h-2 rounded-full ${statusDot}"></span>
              </div>
              <div class="mt-2 space-y-0.5 text-[11px] text-slate-400">
                <div class="font-mono text-slate-300 font-semibold">${item.completed_slices.toLocaleString()} / ${item.total_slices.toLocaleString()} 切片</div>
                <div class="text-[10px] text-slate-500">${item.in_flight > 0 ? '已完 ' + item.completed_days + ' 天 (<span class="text-cyan-400 font-semibold">+' + item.in_flight + ' 在途</span>)' : '已完成: ' + item.completed_days + ' / ' + item.total_days + ' 天'}</div>
              </div>
              <div class="mt-2 pt-1.5 border-t border-slate-800/80 flex justify-between items-baseline">
                <span class="${pctColor}">${item.overall_pct}%</span>
              </div>
            </div>
          `;
        }).join('');

        // 5. Recent Files
        const fList = document.getElementById('recent-files-list');
        if (data.recent_files.length === 0) {
          fList.innerHTML = '<div class="p-4 text-slate-500 text-center">暂无落盘记录</div>';
        } else {
          fList.innerHTML = data.recent_files.map(f => `
            <div class="px-5 py-3 flex items-center justify-between hover:bg-slate-800/40 transition">
              <div class="flex items-center gap-3">
                <span class="text-emerald-400 font-mono text-xs">✨ ${f.time_str}</span>
                <span class="text-slate-300 font-mono text-xs">${f.path}</span>
              </div>
              <div class="flex items-center gap-4">
                <span class="text-slate-400 font-mono text-xs">${f.size_mb > 0 ? f.size_mb + ' MB' : f.size_kb + ' KB'}</span>
                <span class="text-slate-500 text-xs font-mono">(${f.age_str})</span>
              </div>
            </div>
          `).join('');
        }

      } catch (err) {
        console.error("Dashboard update error:", err);
      }
    }

    // Auto-refresh every 2s
    updateDashboard();
    setInterval(updateDashboard, 2000);
  </script>
</body>
</html>
"""


class DashboardHTTPHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        elif self.path.startswith("/api/status"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            status_data = get_full_status()
            self.wfile.write(json.dumps(status_data, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Silence default terminal request logs to keep console clean
        pass


def main():
    parser = argparse.ArgumentParser(description="Real-time Web Dashboard for GEFS Batch Ingestion")
    parser.add_argument("--port", type=int, default=8080, help="HTTP server port (default: 8080)")
    args = parser.parse_args()

    server_address = ("", args.port)
    # Enable SO_REUSEADDR
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(server_address, DashboardHTTPHandler) as httpd:
        print("=" * 75)
        print(f"🚀 NOAA GEFS 实时监控大盘已启动！")
        print(f"🌐 浏览器访问链接: http://localhost:{args.port}")
        print(f"💡 按 Ctrl + C 可退出监控服务")
        print("=" * 75)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n👋 监控大盘已关闭。")


if __name__ == "__main__":
    main()
