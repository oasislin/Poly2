#!/usr/bin/env python3
"""
Lightweight Web Dashboard for Real-time GEFS Batch Download & System Monitoring.

Zero external dependencies (uses standard Python library).
Usage:
  python scripts/dashboard.py
  python scripts/dashboard.py --port 8080
"""

import argparse
import http.server
import json
import os
import re
import socketserver
import time
import urllib.error
import urllib.request
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from src.data_acquisition.gefs_fetcher import check_data_link_health

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


def parse_log_file(log_path: Path):
    if not log_path.exists():
        return None

    stat = log_path.stat()
    mtime = stat.st_mtime
    age_seconds = time.time() - mtime

    # 1. Extract the latest # METADATA: header from the entire log file
    pid = None
    year_range = ""
    stations = ""
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "# METADATA:" in line:
                    m = re.search(r"pid=(\d+).*?start_year=(\d+).*?end_year=(\d+).*?stations=([\w,]+)", line)
                    if m:
                        pid = int(m.group(1))
                        year_range = f"{m.group(2)}~{m.group(3)} 年"
                        stations = m.group(4)
    except Exception:
        pass

    # 2. Check liveness: strictly by PID when available
    if pid is not None:
        is_alive = is_pid_running(pid)
    else:
        is_alive = (age_seconds < 45.0)

    # 3. Read last 4KB for latest progress line
    tail_text = ""
    try:
        with open(log_path, "rb") as f:
            f_size = stat.st_size
            read_len = min(f_size, 4096)
            f.seek(f_size - read_len)
            tail_text = f.read(read_len).decode("utf-8", errors="ignore")
    except Exception:
        pass

    latest_progress = None
    # Look for [PROGRESS] lines
    # e.g.: [PROGRESS] DENVER 2004-12-11 (347/366 94.8%) [已耗时 30s] | c00:45.5%(1.0/2.2MB,42KB/s) ...
    prog_lines = [line for line in tail_text.splitlines() if "[PROGRESS]" in line]
    if prog_lines:
        last_line = prog_lines[-1]
        m_head = re.search(r"\[PROGRESS\]\s+([A-Z]+)\s+([\d\-]+)\s+\(([\d\/]+\s+[\d\.]+%)\)\s*(?:\[已耗时\s*(\d+)s\])?\s*\|\s*(.*)", last_line)
        if m_head:
            station = m_head.group(1)
            target_date = m_head.group(2)
            day_progress = m_head.group(3)
            elapsed = int(m_head.group(4)) if m_head.group(4) else 0
            member_str = m_head.group(5)

            members = {}
            for m_item in re.finditer(r"(c\d{2}|p\d{2})(?:\[([\w]+)\])?:\s*([\d\.]+)%\(([\d\.]+)\/([\d\.]+)MB,\s*(\d+)KB\/s\)", member_str):
                mem_name = m_item.group(1)
                var_name = m_item.group(2) or ""
                pct = float(m_item.group(3))
                dl_mb = float(m_item.group(4))
                tot_mb = float(m_item.group(5))
                spd = int(m_item.group(6))
                members[mem_name] = {
                    "var": var_name,
                    "pct": pct,
                    "downloaded_mb": dl_mb,
                    "total_mb": tot_mb,
                    "speed_kb": spd,
                }

            latest_progress = {
                "station": station,
                "target_date": target_date,
                "day_progress": day_progress,
                "elapsed_seconds": elapsed,
                "members": members,
            }

    return {
        "log_name": log_path.name,
        "pid": pid,
        "is_alive": is_alive,
        "year_range": year_range or "批量下载窗口",
        "stations": stations or "全站点",
        "last_update_age": int(age_seconds),
        "latest_progress": latest_progress,
    }


def scan_matrix():
    raw_dir = BASE_DIR / "data" / "raw" / "gefs" / "cropped"
    proc_dir = BASE_DIR / "data" / "processed" / "gefs"

    summary = []
    total_expected = 0
    total_completed = 0

    for yr in range(2000, 2020):
        # 2000 init starts at 2000-01-01 (365 days due to boundary clamp); other leap years have 366
        tot = 365 if yr == 2000 else (366 if yr in [2004, 2008, 2012, 2016] else 365)
        sh_cnt = 0
        den_cnt = 0

        # Check processed
        if (proc_dir / str(yr) / "shanghai").exists():
            sh_cnt = max(sh_cnt, len(list((proc_dir / str(yr) / "shanghai").glob("*.nc"))))
        if (proc_dir / str(yr) / "denver").exists():
            den_cnt = max(den_cnt, len(list((proc_dir / str(yr) / "denver").glob("*.nc"))))

        # Check raw cropped
        if (raw_dir / str(yr) / "shanghai").exists():
            sh_cnt = max(sh_cnt, len(list((raw_dir / str(yr) / "shanghai").glob("*.nc"))))
        if (raw_dir / str(yr) / "denver").exists():
            den_cnt = max(den_cnt, len(list((raw_dir / str(yr) / "denver").glob("*.nc"))))

        sh_done = (sh_cnt >= tot)
        den_done = (den_cnt >= tot)
        status = "done" if (sh_done and den_done) else ("in_progress" if (sh_cnt > 0 or den_cnt > 0) else "pending")

        total_expected += tot * 2
        total_completed += sh_cnt + den_cnt

        summary.append({
            "year": yr,
            "total_days": tot,
            "sh_cnt": sh_cnt,
            "den_cnt": den_cnt,
            "sh_pct": round((sh_cnt / tot) * 100, 1),
            "den_pct": round((den_cnt / tot) * 100, 1),
            "overall_pct": round(((sh_cnt + den_cnt) / (tot * 2)) * 100, 1),
            "status": status,
        })

    return summary, total_completed, total_expected


def scan_recent_files(limit=6):
    raw_dir = BASE_DIR / "data" / "raw" / "gefs" / "cropped"
    proc_dir = BASE_DIR / "data" / "processed" / "gefs"

    files = []
    for d in [raw_dir, proc_dir]:
        if d.exists():
            for p in d.glob("**/*.nc"):
                try:
                    files.append((p.stat().st_mtime, p.stat().st_size, p))
                except Exception:
                    pass

    files.sort(key=lambda x: x[0], reverse=True)
    res = []
    now = time.time()
    for mtime, sz, p in files[:limit]:
        age_s = int(now - mtime)
        res.append({
            "name": p.name,
            "path": str(p.relative_to(BASE_DIR)),
            "size_kb": round(sz / 1024, 1),
            "time_str": datetime.fromtimestamp(mtime).strftime("%H:%M:%S"),
            "age_str": f"{age_s}秒前" if age_s < 60 else f"{age_s//60}分{age_s%60}秒前",
        })
    return res


def discover_running_processes():
    """Discover active download_gefs_batch processes directly from OS."""
    import subprocess
    active_procs = []
    try:
        res = subprocess.run(["ps", "-eo", "pid,command"], capture_output=True, text=True, check=True)
        for line in res.stdout.splitlines():
            if "download_gefs_batch.py" in line and "grep" not in line:
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
                        log_path = Path(m_log.group(1)) if m_log else BASE_DIR / f"logs/worker_{s_yr}_{e_yr}.log"
                        active_procs.append({
                            "pid": pid,
                            "year_range": f"{s_yr}~{e_yr} 年",
                            "log_path": log_path,
                        })
    except Exception:
        pass
    return active_procs


def get_full_status():
    # 1. Scan running processes & active logs
    running_procs = discover_running_processes()
    running_pids = {p["pid"] for p in running_procs}

    candidate_logs = []
    logs_dir = BASE_DIR / "logs"
    if logs_dir.exists():
        candidate_logs.extend(sorted(logs_dir.glob("*.log")))
    for p in sorted(BASE_DIR.glob("download_*.log")):
        candidate_logs.append(p)
    for rp in running_procs:
        if rp["log_path"] not in candidate_logs and rp["log_path"].exists():
            candidate_logs.append(rp["log_path"])

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
            # Only keep workers that are actively running OR updated within the last 180s
            if w["is_alive"] or (w["pid"] in running_pids) or w["last_update_age"] < 180:
                workers.append(w)
                seen_logs.add(p.name)

    # If a process is running in pure console stdout mode (no log file on disk), display it directly
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

    # 2. 20-year Matrix
    matrix, completed, expected = scan_matrix()

    # 3. Recent files
    recent = scan_recent_files(6)

    # 4. S3 Health
    health = probe_s3_health()

    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "s3_health": health,
        "workers": workers,
        "matrix": matrix,
        "progress_summary": {
            "completed_days": completed,
            "expected_days": expected,
            "overall_pct": round((completed / expected) * 100, 2) if expected > 0 else 0.0,
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
          2000-2019 年代际高精度物理概率模型数据管道 · 5 集合成员并发下载监测
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
        <div class="text-slate-400 text-xs font-semibold uppercase tracking-wider">总完成度 (20 年代际)</div>
        <div class="mt-2 flex items-baseline gap-2">
          <span id="total-pct" class="text-3xl font-extrabold text-emerald-400">0.0%</span>
          <span id="total-counts" class="text-xs text-slate-400">0 / 14,610 天</span>
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
        <div class="mt-2 text-3xl font-extrabold text-indigo-400">2 个</div>
        <div class="text-xs text-slate-400 mt-2">上海 (ZSPD) · 丹佛 (KDEN)</div>
      </div>

      <div class="glass-card p-5 rounded-2xl">
        <div class="text-slate-400 text-xs font-semibold uppercase tracking-wider">集合成员架构</div>
        <div class="mt-2 text-3xl font-extrabold text-amber-400">5 成员</div>
        <div class="text-xs text-slate-400 mt-2">c00 (控制) + p01~p04 (扰动)</div>
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
          20 年代际全景热力大盘 (2000 ~ 2019)
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
        document.getElementById('total-counts').innerText = sum.completed_days + ' / ' + sum.expected_days + ' 天';
        document.getElementById('total-bar').style.width = sum.overall_pct + '%';

        // 3. Workers
        const wContainer = document.getElementById('workers-container');
        const aliveWorkers = data.workers.filter(w => w.is_alive);
        document.getElementById('active-workers-count').innerText = aliveWorkers.length + ' 个活跃';

        if (data.workers.length === 0) {
          wContainer.innerHTML = '<div class="col-span-full glass-card p-8 rounded-2xl text-center text-slate-400">当前未启动任何 download_gefs_batch 下载进程</div>';
        } else {
          wContainer.innerHTML = data.workers.map(w => {
            const statusBadge = w.is_alive 
              ? '<span class="px-2.5 py-1 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-xs font-semibold flex items-center gap-1.5"><span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>正在运行</span>'
              : '<span class="px-2.5 py-1 rounded-lg bg-slate-800 text-slate-400 text-xs font-medium">已退出 / 空闲</span>';

            let progressContent = '';
            if (w.latest_progress && w.latest_progress.members) {
              const p = w.latest_progress;
              const mems = p.members;
              const memKeys = ['c00', 'p01', 'p02', 'p03', 'p04'];

              progressContent = `
                <div class="space-y-3 mt-4 pt-4 border-t border-slate-800">
                  <div class="flex justify-between items-center text-xs">
                    <span class="font-bold text-cyan-300 tracking-wider">🎯 当前拉取: ${p.station} ${p.target_date}</span>
                    <span class="text-slate-400 font-mono">年进度: ${p.day_progress} · 已耗时 ${p.elapsed_seconds}s</span>
                  </div>

                  <div class="space-y-2">
                    ${memKeys.map(k => {
                      const m = mems[k] || { pct: 0, downloaded_mb: 0, total_mb: 0, speed_kb: 0 };
                      const isDone = m.pct >= 100;
                      const barColor = isDone ? 'bg-emerald-500' : 'bg-gradient-to-r from-cyan-500 to-blue-500';
                      return `
                        <div>
                          <div class="flex justify-between text-xs font-mono mb-1">
                            <span class="text-slate-300 font-bold">${k}${m.var ? ` <span class="text-cyan-400 text-[10px] font-normal">[${m.var}]</span>` : ''}</span>
                            <span class="text-slate-400">${m.pct.toFixed(1)}% (${m.downloaded_mb.toFixed(1)}/${m.total_mb.toFixed(1)}MB) <span class="text-cyan-400">${m.speed_kb}KB/s</span></span>
                          </div>
                          <div class="w-full bg-slate-800/90 h-2 rounded-full overflow-hidden">
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
                <div>沪: ${item.sh_cnt}/${item.total_days}</div>
                <div>丹: ${item.den_cnt}/${item.total_days}</div>
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
                <span class="text-slate-400 font-mono text-xs">${f.size_kb} KB</span>
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
