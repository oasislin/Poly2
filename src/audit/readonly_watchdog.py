"""Read-only M3/M7/M10 monitoring and 4-class watchdog evaluator (`S3-13`).

Implements ``P8-M7-DESIGN v1.0`` strictly read-only over:
- ``data/market_recordings/`` (`P13` JSONL + ``latest_session.json``)
- ``data/audit_logs/`` (via ``P10`` read-only scanner + JSONL tail inspection)
- Optional ``M10`` rendered HTML CLI output & ledger maintenance annotations

All persisted state, status snapshots, and transition alerts are physically
isolated inside ``alerts_dir`` (default ``data/alerts/``). Never modifies or
deletes inspected recordings/audit files and never signals live recorder PIDs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from statistics import median
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from scripts.record_status import _parse_valid_envelope
from src.audit.p10_reader import P10Query, query_p10_session_view
from src.execution.clob_gateway import ExecutionMode

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RECORDINGS_ROOT = REPO_ROOT / "data" / "market_recordings"
DEFAULT_AUDIT_ROOT = REPO_ROOT / "data" / "audit_logs"
DEFAULT_ALERTS_DIR = REPO_ROOT / "data" / "alerts"
DEFAULT_LEDGER_PATH = REPO_ROOT / "docs" / "audit" / "P8-PROJECT-TASKS_全量任务分解台账.md"

Severity = str  # "OK" | "WARN" | "CRITICAL"
_SEVERITY_RANK: Dict[str, int] = {"OK": 0, "WARN": 1, "CRITICAL": 2}

# Pinned thresholds aligned with P8-M7-DESIGN v1.0 §2.1-§3.2
ROLLOVER_START_UTC = dt_time(0, 4, 30)
ROLLOVER_END_UTC = dt_time(0, 7, 0)
ROLLOVER_DURATION_SEC = 150.0
GAP_RATE_WARN = 0.01
GAP_RATE_CRITICAL = 0.05
GAP_MIN_FRAMES = 60
GAP_SLIDING_WINDOW_SEC = 900.0
SILENCE_WARN_SEC = 120.0
SILENCE_CRITICAL_SEC = 300.0
SILENCE_RECOVER_MAX_SEC = 60.0
GAP_RECOVER_STREAK = 3
GLOBAL_STALL_MIN_STATIONS = 3

TAIL_STALL_MIN_POLLS = 3
TAIL_STALL_MIN_AGE_SEC = 90.0

# Pinned baseline parameters for token coverage (§2.3 / WO 2.b-1)
TOKEN_WARMUP_SEC = 180.0
TOKEN_BASELINE_LOOKBACK_SEC = 86400.0
TOKEN_MIN_HEALTHY_FRAMES = 10
TOKEN_WARN_RATIO = 0.80
TOKEN_CRITICAL_RATIO = 0.50
TOKEN_RECOVER_RATIO = 0.85
TOKEN_RECOVER_STREAK = 2

# Pinned disk watermark & growth-window parameters (§2.4 / WO 2.b-2)
DISK_FREE_WARN_RATIO = 0.20
DISK_FREE_WARN_BYTES = 10 * 1024**3
DISK_FREE_CRIT_RATIO = 0.10
DISK_FREE_CRIT_BYTES = 4 * 1024**3
DISK_ETA_CRIT_HOURS = 24.0
DISK_RECENT_WINDOW_SEC = 3600.0
DISK_SAMPLE_MIN_STEP_SEC = 300.0
DISK_BASELINE_WINDOW_SEC = 86400.0
DISK_SAMPLE_RETENTION_SEC = 90000.0
DISK_GROWTH_MULTIPLIER = 3.0
DISK_GROWTH_FLOOR_BPH = 512 * 1024**2

ALERT_COOLDOWN_SEC = 300.0
_GIB = float(1024**3)
_MIB = float(1024**2)
_UTC_OFFSET_8 = timezone(timedelta(hours=8))
_M3_WINDOW_RE = re.compile(
    r"(?:(?P<date>\d{4}-\d{2}-\d{2})\s+)?(?P<sh>\d{2}):(?P<sm>\d{2})[–-](?P<eh>\d{2}):(?P<em>\d{2})"
)


@dataclass(frozen=True)
class WatchdogConfig:
    """Configuration for read-only M3/M7/M10 watchdog checks."""

    recordings_root: Path = DEFAULT_RECORDINGS_ROOT
    audit_root: Path = DEFAULT_AUDIT_ROOT
    alerts_dir: Path = DEFAULT_ALERTS_DIR
    ledger_path: Optional[Path] = DEFAULT_LEDGER_PATH
    m10_html_path: Optional[Path] = None
    execution_modes: Tuple[ExecutionMode, ...] = ("PAPER", "LIVE")
    expected_stations: Tuple[str, ...] = ("KATL", "KDAL", "KLGA", "KMIA", "KORD", "KSEA")
    verify_sha256: bool = True
    expect_recorder_running: bool = True


def _parse_iso_utc(raw: Optional[str]) -> Optional[datetime]:
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _ensure_alerts_dir_isolated(cfg: WatchdogConfig) -> Path:
    alerts_res = cfg.alerts_dir.resolve()
    forbidden: List[Path] = [
        cfg.recordings_root.resolve(),
        cfg.audit_root.resolve(),
        (REPO_ROOT / "docs" / "audit").resolve(),
        (REPO_ROOT / "evidence").resolve(),
    ]
    if cfg.m10_html_path is not None:
        forbidden.append(cfg.m10_html_path.resolve())
    for root in forbidden:
        if alerts_res == root or root in alerts_res.parents:
            raise ValueError(f"alerts_dir ({alerts_res}) must be isolated outside {root}")
    return alerts_res


def _atomic_write_text_in_alerts(alerts_dir: Path, target: Path, text: str) -> None:
    target_res = target.resolve()
    alerts_res = alerts_dir.resolve()
    if target_res != alerts_res and alerts_res not in target_res.parents:
        raise ValueError(f"Refusing write outside alerts_dir: {target_res}")
    target_res.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_res.parent / f".{target_res.name}.{os.getpid()}.tmp"
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, target_res)


def _read_json_readonly(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _is_in_rollover_grace(now_utc: datetime) -> bool:
    t = now_utc.astimezone(timezone.utc).timetz().replace(tzinfo=None)
    return ROLLOVER_START_UTC <= t <= ROLLOVER_END_UTC


def _parse_ledger_m3_maintenance(ledger_path: Optional[Path]) -> List[Dict[str, Any]]:
    if ledger_path is None or not ledger_path.exists():
        return []
    try:
        with ledger_path.open("r", encoding="utf-8") as fh:
            m3_line = next((ln for ln in fh if ln.startswith("| **`M3`** |")), "")
    except Exception:
        return []
    if not m3_line or "主动指令" not in m3_line:
        return []
    windows: List[Dict[str, Any]] = []
    cur_date: Optional[str] = None
    for match in _M3_WINDOW_RE.finditer(m3_line):
        if match.group("date"):
            cur_date = match.group("date")
        if not cur_date:
            continue
        day = datetime.strptime(cur_date, "%Y-%m-%d").date()
        start_local = datetime(
            day.year, day.month, day.day, int(match.group("sh")), int(match.group("sm")), tzinfo=_UTC_OFFSET_8
        )
        end_local = datetime(
            day.year, day.month, day.day, int(match.group("eh")), int(match.group("em")), tzinfo=_UTC_OFFSET_8
        )
        if end_local < start_local:
            end_local += timedelta(days=1)
        windows.append(
            {
                "source": "ledger_m3",
                "status": "PAUSED" if "暂停休眠中" in m3_line else "CLOSED_RESUMED",
                "start_utc": start_local.astimezone(timezone.utc),
                "end_utc": end_local.astimezone(timezone.utc),
            }
        )
    return windows


def _load_maintenance_context(
    alerts_dir: Path, ledger_path: Optional[Path], now_utc: datetime
) -> Tuple[bool, List[Dict[str, str]]]:
    active = False
    records: List[Dict[str, str]] = []
    mw = _read_json_readonly(alerts_dir / "maintenance_window.json")
    if mw is not None:
        status = str(mw.get("status") or "")
        st_dt = _parse_iso_utc(mw.get("stopped_at_utc"))
        end_dt = _parse_iso_utc(mw.get("resumed_at_utc")) or _parse_iso_utc(mw.get("until_utc"))
        records.append({"source": "maintenance_window.json", "status": status})
        if status.startswith("ACTIVE") and (end_dt is None or now_utc <= end_dt):
            if st_dt is None or now_utc >= st_dt:
                active = True
    for win in _parse_ledger_m3_maintenance(ledger_path):
        in_span = win["start_utc"] <= now_utc <= (win["end_utc"] + timedelta(minutes=2))
        if win["status"] == "PAUSED" or in_span:
            active = True
            records.append(
                {
                    "source": win["source"],
                    "status": win["status"],
                    "start_utc": win["start_utc"].isoformat(),
                    "end_utc": win["end_utc"].isoformat(),
                }
            )
    return active, records


def _empty_station_scan() -> Dict[str, Any]:
    return {
        "frames": 0,
        "gap_count": 0,
        "gap_reasons": {},
        "last_recorded_ts_utc": None,
        "last_recv_ts_utc": None,
        "tokens": set(),
        "yes_tokens": set(),
        "no_tokens": set(),
        "recent_tokens": set(),
        "recent_yes_tokens": set(),
        "recent_no_tokens": set(),
    }


def _scan_p13_file_readonly(
    path: Path,
    recordings_root: Path,
    verify_sha256: bool,
    cutoff_recent: datetime,
    sessions: Dict[str, Dict[str, Any]],
    corrupt_items: List[Dict[str, Any]],
    trailing_tails: List[Dict[str, Any]],
    frame_events: List[Tuple[datetime, bool]],
) -> Tuple[int, int]:
    rel = path.relative_to(recordings_root).parts
    fb_sid = rel[-2] if len(rel) >= 2 else "unknown"
    fb_station = path.stem.removeprefix("p13_book_stream_") or "UNKNOWN"
    valid_count = 0
    byte_offset = 0
    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            raw_bytes = len(raw_line.encode("utf-8"))
            if not raw_line.endswith("\n"):
                if raw_line.strip():
                    trailing_tails.append(
                        {"file_path": str(path), "line_no": line_no, "byte_offset": byte_offset, "content_len": raw_bytes}
                    )
                byte_offset += raw_bytes
                continue
            byte_offset += raw_bytes
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                obj = _parse_valid_envelope(stripped, verify_sha256=verify_sha256)
            except Exception as exc:
                corrupt_items.append({"file_path": str(path), "line_no": line_no, "reason": f"P13_{type(exc).__name__}"})
                continue
            valid_count += 1
            _accumulate_p13_record(obj, fb_sid, fb_station, cutoff_recent, sessions, frame_events)
    return valid_count, path.stat().st_size


def _record_token_into_station(
    st_b: Dict[str, Any], payload: Mapping[str, Any], rec_dt: Optional[datetime], cutoff_recent: datetime
) -> None:
    tok_id = str(payload.get("token_id") or "")
    if not tok_id:
        return
    outcome = str(payload.get("outcome") or "YES").upper()
    st_b["tokens"].add(tok_id)
    if outcome == "YES":
        st_b["yes_tokens"].add(tok_id)
    elif outcome == "NO":
        st_b["no_tokens"].add(tok_id)
    if rec_dt is not None and rec_dt >= cutoff_recent:
        st_b["recent_tokens"].add(tok_id)
        if outcome == "YES":
            st_b["recent_yes_tokens"].add(tok_id)
        elif outcome == "NO":
            st_b["recent_no_tokens"].add(tok_id)


def _accumulate_p13_record(
    obj: Mapping[str, Any],
    fb_sid: str,
    fb_station: str,
    cutoff_recent: datetime,
    sessions: Dict[str, Dict[str, Any]],
    frame_events: List[Tuple[datetime, bool]],
) -> None:
    sid, st_id = str(obj.get("session_id") or fb_sid), str(obj.get("station_id") or fb_station)
    sb = sessions.setdefault(
        sid,
        {"frames": 0, "gap_count": 0, "gap_reasons": {}, "corrupt_lines": 0, "first_ts": None, "last_ts": None, "stations": {}},
    )
    st_b = sb["stations"].setdefault(st_id, _empty_station_scan())
    payload, is_gap = obj["payload"], bool(obj.get("gap_detected"))
    sb["frames"] += 1
    st_b["frames"] += 1
    if is_gap:
        reason = str(obj.get("gap_reason") or "UNSPECIFIED")
        sb["gap_count"] += 1
        st_b["gap_count"] += 1
        sb["gap_reasons"][reason] = sb["gap_reasons"].get(reason, 0) + 1
        st_b["gap_reasons"][reason] = st_b["gap_reasons"].get(reason, 0) + 1
    rec_ts, recv_ts = obj.get("recorded_ts_utc"), payload.get("recv_ts_utc")
    rec_dt = _parse_iso_utc(rec_ts)
    if rec_dt is not None:
        frame_events.append((rec_dt, is_gap))
        sb["first_ts"] = rec_dt if (sb["first_ts"] is None or rec_dt < sb["first_ts"]) else sb["first_ts"]
        sb["last_ts"] = rec_dt if (sb["last_ts"] is None or rec_dt > sb["last_ts"]) else sb["last_ts"]
    if rec_ts and (st_b["last_recorded_ts_utc"] is None or rec_ts > st_b["last_recorded_ts_utc"]):
        st_b["last_recorded_ts_utc"] = rec_ts
    if recv_ts and (st_b["last_recv_ts_utc"] is None or recv_ts > st_b["last_recv_ts_utc"]):
        st_b["last_recv_ts_utc"] = recv_ts
    _record_token_into_station(st_b, payload, rec_dt, cutoff_recent)


def _scan_recordings_readonly(
    cfg: WatchdogConfig, now_utc: datetime
) -> Dict[str, Any]:
    root = cfg.recordings_root
    exists = root.exists()
    latest = _read_json_readonly(root / "latest_session.json") if exists else None
    sessions: Dict[str, Dict[str, Any]] = {}
    corrupt_items: List[Dict[str, Any]] = []
    trailing_tails: List[Dict[str, Any]] = []
    frame_events: List[Tuple[datetime, bool]] = []
    valid_lines = 0
    total_bytes = 0
    cutoff_recent = now_utc - timedelta(seconds=GAP_SLIDING_WINDOW_SEC)
    if exists:
        for path in sorted(root.rglob("p13_book_stream_*.jsonl")):
            v_cnt, f_bytes = _scan_p13_file_readonly(
                path, root, cfg.verify_sha256, cutoff_recent, sessions, corrupt_items, trailing_tails, frame_events
            )
            valid_lines += v_cnt
            total_bytes += f_bytes
    for item in corrupt_items:
        rel = Path(item["file_path"]).relative_to(root).parts
        sid = rel[-2] if len(rel) >= 2 else "unknown"
        if sid in sessions:
            sessions[sid]["corrupt_lines"] += 1
    return {
        "exists": exists,
        "latest_session": latest,
        "sessions": sessions,
        "corrupt_items": corrupt_items,
        "trailing_tails": trailing_tails,
        "frame_events": frame_events,
        "valid_lines": valid_lines,
        "disk_bytes": total_bytes,
    }


def _scan_audit_and_m10_readonly(cfg: WatchdogConfig) -> Dict[str, Any]:
    corrupt_items: List[Dict[str, Any]] = []
    trailing_tails: List[Dict[str, Any]] = []
    valid_lines = 0
    total_bytes = 0
    render_statuses: Dict[str, str] = {}
    if cfg.audit_root.exists():
        for mode in cfg.execution_modes:
            mode_dir = cfg.audit_root / mode
            if not mode_dir.exists():
                continue
            view = query_p10_session_view(
                audit_root=cfg.audit_root,
                query=P10Query(execution_mode=mode),
            )
            render_statuses[mode] = view.render_status
            valid_lines += view.valid_lines
            for c in view.corrupt_lines:
                corrupt_items.append({"file_path": c.file_path, "line_no": c.line_no, "reason": c.reason})
        for path in sorted(cfg.audit_root.rglob("*.jsonl")):
            total_bytes += path.stat().st_size
            _collect_unterminated_tail(path, trailing_tails)
    m10_info: Dict[str, Any] = {"configured": cfg.m10_html_path is not None}
    if cfg.m10_html_path is not None:
        m10_info["exists"] = cfg.m10_html_path.exists()
        if cfg.m10_html_path.exists():
            with cfg.m10_html_path.open("r", encoding="utf-8") as fh:
                html_text = fh.read()
            m10_info["size_bytes"] = cfg.m10_html_path.stat().st_size
            m10_info["degraded_banner_present"] = "DEGRADED_CORRUPT_LINES" in html_text
    return {
        "valid_lines": valid_lines,
        "corrupt_items": corrupt_items,
        "trailing_tails": trailing_tails,
        "disk_bytes": total_bytes,
        "render_statuses": render_statuses,
        "m10_html": m10_info,
    }


def _collect_unterminated_tail(path: Path, trailing_tails: List[Dict[str, Any]]) -> None:
    byte_offset = 0
    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            raw_bytes = len(raw_line.encode("utf-8"))
            if not raw_line.endswith("\n") and raw_line.strip():
                trailing_tails.append(
                    {"file_path": str(path), "line_no": line_no, "byte_offset": byte_offset, "content_len": raw_bytes}
                )
            byte_offset += raw_bytes


def _select_active_session(rec_scan: Mapping[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    sessions = rec_scan["sessions"]
    latest = rec_scan["latest_session"]
    if isinstance(latest, Mapping) and latest.get("session_id") in sessions:
        sid = str(latest["session_id"])
        return sid, sessions[sid]
    if not sessions:
        return (str(latest["session_id"]), None) if isinstance(latest, Mapping) and latest.get("session_id") else (None, None)
    latest_sid = max(
        sessions.keys(),
        key=lambda k: (
            sessions[k]["last_ts"].isoformat() if sessions[k]["last_ts"] is not None else "",
            k,
        ),
    )
    return latest_sid, sessions[latest_sid]


def _compute_window_gap_counts(
    rec_scan: Mapping[str, Any], active_sess: Optional[Mapping[str, Any]], now_utc: datetime
) -> Tuple[int, int, float]:
    cutoff = now_utc - timedelta(seconds=GAP_SLIDING_WINDOW_SEC)
    win_events = [ev for ev in rec_scan["frame_events"] if ev[0] >= cutoff]
    if len(win_events) >= GAP_MIN_FRAMES:
        eval_frames, eval_gaps = len(win_events), sum(1 for _, g in win_events if g)
    elif active_sess is not None:
        eval_frames, eval_gaps = int(active_sess["frames"]), int(active_sess["gap_count"])
    else:
        eval_frames, eval_gaps = len(rec_scan["frame_events"]), sum(1 for _, g in rec_scan["frame_events"] if g)
    return eval_frames, eval_gaps, eval_gaps / max(1, eval_frames)


def _evaluate_gap_rate_check(
    cfg: WatchdogConfig,
    rec_scan: Mapping[str, Any],
    now_utc: datetime,
    in_rollover: bool,
    in_maintenance: bool,
    state: Dict[str, Any],
    pid_alive_fn: Callable[[int], bool],
) -> Dict[str, Any]:
    active_sid, active_sess = _select_active_session(rec_scan)
    scopes: List[Dict[str, Any]] = []
    if not rec_scan["exists"]:
        sev = "OK" if in_maintenance else ("CRITICAL" if cfg.expect_recorder_running else "WARN")
        reason = "PLANNED_MAINTENANCE_STOP" if in_maintenance else "RECORDING_ROOT_MISSING"
        state["gap_healthy_streak"] = 0
        return {"status": sev, "metrics": {"recordings_root_exists": False}, "thresholds": _gap_thresholds(), "triggered_scopes": [{"scope": "recordings_root", "reason": reason}]}

    pid_alive = _check_latest_pid_alive(rec_scan["latest_session"], pid_alive_fn)
    active_corrupt = int(active_sess["corrupt_lines"]) if active_sess else len(rec_scan["corrupt_items"])
    if cfg.expect_recorder_running and pid_alive is False and not in_rollover:
        if active_corrupt == 0 and not rec_scan["trailing_tails"] and in_maintenance:
            return {"status": "OK", "metrics": {"planned_maintenance_stop": True, "active_session_id": active_sid, "pid_alive": False}, "thresholds": _gap_thresholds(), "triggered_scopes": [{"scope": "recorder_process", "reason": "PLANNED_MAINTENANCE_STOP"}]}
        scopes.append({"scope": "recorder_process", "reason": "RECORDER_PROCESS_DOWN"})

    eval_frames, eval_gaps, gap_rate = _compute_window_gap_counts(rec_scan, active_sess, now_utc)
    station_silence = _compute_station_silences(cfg.expected_stations, active_sess, now_utc)
    max_silence = max(station_silence.values()) if station_silence else 0.0
    crit_silent = [st for st, sec in sorted(station_silence.items()) if sec > SILENCE_CRITICAL_SEC]
    warn_silent = [st for st, sec in sorted(station_silence.items()) if SILENCE_WARN_SEC < sec <= SILENCE_CRITICAL_SEC]
    raw_sev = _classify_gap_severity(eval_frames, gap_rate, crit_silent, warn_silent, scopes, in_rollover, in_maintenance, max_silence)
    final_sev, streak = _apply_gap_hysteresis(raw_sev, gap_rate, max_silence, state)
    return {
        "status": final_sev,
        "metrics": {"active_session_id": active_sid, "pid_alive": pid_alive, "frames_evaluated": eval_frames, "gaps_evaluated": eval_gaps, "gap_rate": round(gap_rate, 6), "max_silence_sec": round(max_silence, 2), "station_silence_sec": {k: round(v, 2) for k, v in sorted(station_silence.items())}, "recover_streak": streak, "recover_required": GAP_RECOVER_STREAK, "rollover_grace_active": in_rollover, "planned_maintenance_active": in_maintenance},
        "thresholds": _gap_thresholds(),
        "triggered_scopes": scopes,
    }


def _gap_thresholds() -> Dict[str, Any]:
    return {
        "gap_rate_warn": GAP_RATE_WARN,
        "gap_rate_critical": GAP_RATE_CRITICAL,
        "gap_min_frames": GAP_MIN_FRAMES,
        "silence_warn_sec": SILENCE_WARN_SEC,
        "silence_critical_sec": SILENCE_CRITICAL_SEC,
        "recover_max_silence_sec": SILENCE_RECOVER_MAX_SEC,
        "recover_streak": GAP_RECOVER_STREAK,
        "rollover_grace_sec": ROLLOVER_DURATION_SEC,
    }


def _check_latest_pid_alive(latest: Any, pid_alive_fn: Callable[[int], bool]) -> Optional[bool]:
    if not isinstance(latest, Mapping):
        return None
    pids = [int(latest[k]) for k in ("supervisor_pid", "child_pid") if isinstance(latest.get(k), int)]
    if not pids:
        return None
    return any(pid_alive_fn(p) for p in pids)


def _compute_station_silences(
    expected_stations: Sequence[str], active_sess: Optional[Mapping[str, Any]], now_utc: datetime
) -> Dict[str, float]:
    out: Dict[str, float] = {}
    st_map = active_sess["stations"] if active_sess else {}
    for st_id in expected_stations:
        st_b = st_map.get(st_id)
        if st_b is None:
            continue
        ts_candidates = [_parse_iso_utc(st_b.get("last_recv_ts_utc")), _parse_iso_utc(st_b.get("last_recorded_ts_utc"))]
        valid_ts = [t for t in ts_candidates if t is not None]
        if valid_ts:
            out[st_id] = max(0.0, (now_utc - max(valid_ts)).total_seconds())
    return out


def _classify_gap_severity(
    frames: int,
    gap_rate: float,
    crit_silent: List[str],
    warn_silent: List[str],
    scopes: List[Dict[str, Any]],
    in_rollover: bool,
    in_maintenance: bool,
    max_silence: float,
) -> Severity:
    sev = "OK"
    has_proc_down = any(s.get("reason") == "RECORDER_PROCESS_DOWN" for s in scopes)
    if has_proc_down:
        sev = "CRITICAL"
    if frames >= GAP_MIN_FRAMES and gap_rate > GAP_RATE_CRITICAL:
        sev = "CRITICAL"
        scopes.append({"scope": "gap_rate", "reason": "GAP_RATE_CRITICAL", "value": round(gap_rate, 6)})
    elif frames >= GAP_MIN_FRAMES and gap_rate > GAP_RATE_WARN:
        sev = _max_sev(sev, "WARN")
        scopes.append({"scope": "gap_rate", "reason": "GAP_RATE_WARN", "value": round(gap_rate, 6)})
    if not (in_rollover and max_silence <= ROLLOVER_DURATION_SEC) and not in_maintenance:
        if len(crit_silent) >= GLOBAL_STALL_MIN_STATIONS:
            sev = "CRITICAL"
            scopes.append({"scope": ",".join(crit_silent), "reason": "GLOBAL_STREAM_STALL"})
        elif crit_silent:
            sev = "CRITICAL"
            for st in crit_silent:
                scopes.append({"scope": st, "reason": "STATION_SILENCE_CRITICAL"})
        elif warn_silent:
            sev = _max_sev(sev, "WARN")
            for st in warn_silent:
                scopes.append({"scope": st, "reason": "STATION_SILENCE_WARN"})
    return sev


def _apply_gap_hysteresis(raw_sev: Severity, gap_rate: float, max_silence: float, state: Dict[str, Any]) -> Tuple[Severity, int]:
    prev_sev = str(state.get("gap_active_severity") or "OK")
    if raw_sev != "OK":
        state["gap_healthy_streak"] = 0
        state["gap_active_severity"] = _max_sev(prev_sev, raw_sev) if prev_sev != "OK" else raw_sev
        return state["gap_active_severity"], 0
    if prev_sev == "OK":
        state["gap_healthy_streak"] = 0
        return "OK", 0
    healthy_for_recovery = max_silence <= SILENCE_RECOVER_MAX_SEC and gap_rate <= GAP_RATE_WARN
    streak = int(state.get("gap_healthy_streak") or 0) + (1 if healthy_for_recovery else 0)
    if streak >= GAP_RECOVER_STREAK:
        state["gap_healthy_streak"] = 0
        state["gap_active_severity"] = "OK"
        return "OK", streak
    state["gap_healthy_streak"] = streak
    return prev_sev, streak


def _evaluate_corrupt_lines_check(
    rec_scan: Mapping[str, Any], audit_scan: Mapping[str, Any], now_utc: datetime, state: Dict[str, Any]
) -> Dict[str, Any]:
    all_corrupt = list(rec_scan["corrupt_items"]) + list(audit_scan["corrupt_items"])
    all_tails = list(rec_scan["trailing_tails"]) + list(audit_scan["trailing_tails"])
    valid_total = int(rec_scan["valid_lines"]) + int(audit_scan["valid_lines"])
    corrupt_count = len(all_corrupt)
    corrupt_rate = corrupt_count / max(1, valid_total + corrupt_count)

    stalled_tails: List[Dict[str, Any]] = []
    tracker: Dict[str, Dict[str, Any]] = state.setdefault("tail_stall_tracker", {})
    seen_files = {t["file_path"] for t in all_tails}
    for fp in list(tracker.keys()):
        if fp not in seen_files:
            tracker.pop(fp, None)
    for t in all_tails:
        fp = t["file_path"]
        prev = tracker.get(fp)
        if prev and prev.get("byte_offset") == t["byte_offset"]:
            prev["streak"] = int(prev.get("streak") or 1) + 1
            first_ts = _parse_iso_utc(prev.get("first_seen_ts")) or now_utc
            age_sec = (now_utc - first_ts).total_seconds()
            if prev["streak"] >= TAIL_STALL_MIN_POLLS and age_sec > TAIL_STALL_MIN_AGE_SEC:
                stalled_tails.append({"scope": fp, "reason": "TAIL_WRITE_STALLED", "age_sec": round(age_sec, 1)})
        else:
            tracker[fp] = {"byte_offset": t["byte_offset"], "first_seen_ts": now_utc.isoformat(), "streak": 1}

    scopes: List[Dict[str, Any]] = [
        {"scope": f"{c['file_path']}:{c['line_no']}", "reason": c["reason"]} for c in all_corrupt
    ] + stalled_tails
    sev = "CRITICAL" if corrupt_count >= 1 else ("WARN" if stalled_tails else "OK")
    return {
        "status": sev,
        "metrics": {
            "valid_lines": valid_total,
            "corrupt_lines": corrupt_count,
            "corrupt_rate": round(corrupt_rate, 6),
            "incomplete_trailing_lines": len(all_tails),
            "stalled_tail_count": len(stalled_tails),
            "audit_render_statuses": audit_scan["render_statuses"],
            "m10_html": audit_scan["m10_html"],
        },
        "thresholds": {
            "corrupt_lines_critical_min": 1,
            "tail_stall_min_polls": TAIL_STALL_MIN_POLLS,
            "tail_stall_min_age_sec": TAIL_STALL_MIN_AGE_SEC,
        },
        "triggered_scopes": scopes,
    }


def _score_station_token_coverage(
    st_id: str,
    st_b: Mapping[str, Any],
    session_age: float,
    hist_baselines: Mapping[str, int],
    sess_peaks: Dict[str, int],
) -> Tuple[int, int, int, int, float]:
    cur_tot = len(st_b["tokens"])
    cur_yes = len(st_b["yes_tokens"])
    cur_no = len(st_b["no_tokens"])
    hist_b = int(hist_baselines.get(st_id, 0))
    if session_age >= TOKEN_WARMUP_SEC:
        sess_peaks[st_id] = max(int(sess_peaks.get(st_id, 0)), cur_tot)
        baseline = max(sess_peaks[st_id], hist_b)
    else:
        baseline = hist_b if hist_b > 0 else cur_tot
    ratio = cur_tot / max(1, baseline) if baseline > 0 else 1.0
    return cur_tot, cur_yes, cur_no, baseline, ratio


def _evaluate_token_coverage_check(
    cfg: WatchdogConfig,
    rec_scan: Mapping[str, Any],
    now_utc: datetime,
    in_rollover: bool,
    in_maintenance: bool,
    state: Dict[str, Any],
) -> Dict[str, Any]:
    active_sid, active_sess = _select_active_session(rec_scan)
    if active_sess is None:
        return {"status": "OK", "metrics": {"active_session_id": active_sid, "warmup_active": False, "stations": {}}, "thresholds": _token_thresholds(), "triggered_scopes": []}
    s_first = active_sess.get("first_ts")
    session_age = (now_utc - s_first).total_seconds() if s_first is not None else 0.0
    in_warmup = session_age < TOKEN_WARMUP_SEC

    hist_baselines = _compute_historical_token_baselines(rec_scan["sessions"], active_sid, now_utc)
    sess_peaks = state.setdefault("session_token_peaks", {}).setdefault(active_sid or "default", {})
    per_station: Dict[str, Any] = {}
    scopes: List[Dict[str, Any]] = []
    raw_sev = "OK"
    for st_id, st_b in sorted(active_sess["stations"].items()):
        cur_tot, cur_yes, cur_no, baseline, ratio = _score_station_token_coverage(
            st_id, st_b, session_age, hist_baselines, sess_peaks
        )
        per_station[st_id] = {"current": cur_tot, "YES": cur_yes, "NO": cur_no, "baseline": baseline, "ratio": round(ratio, 4)}
        if not in_warmup and not in_maintenance:
            raw_sev = _classify_station_token_alert(st_id, cur_tot, cur_yes, cur_no, baseline, ratio, raw_sev, scopes)
    final_sev, streak = _apply_token_hysteresis(raw_sev, per_station, in_warmup or in_maintenance, state)
    return {
        "status": final_sev,
        "metrics": {"active_session_id": active_sid, "session_age_sec": round(session_age, 1), "warmup_active": in_warmup, "recover_streak": streak, "recover_required": TOKEN_RECOVER_STREAK, "stations": per_station},
        "thresholds": _token_thresholds(),
        "triggered_scopes": scopes,
    }


def _token_thresholds() -> Dict[str, Any]:
    return {
        "warmup_sec": TOKEN_WARMUP_SEC,
        "baseline_lookback_sec": TOKEN_BASELINE_LOOKBACK_SEC,
        "baseline_aggregation": "median_24h_healthy_sessions_and_post_180s_peak",
        "min_healthy_frames": TOKEN_MIN_HEALTHY_FRAMES,
        "warn_ratio": TOKEN_WARN_RATIO,
        "critical_ratio": TOKEN_CRITICAL_RATIO,
        "recover_ratio": TOKEN_RECOVER_RATIO,
        "recover_streak": TOKEN_RECOVER_STREAK,
    }


def _compute_historical_token_baselines(
    sessions: Mapping[str, Mapping[str, Any]], active_sid: Optional[str], now_utc: datetime
) -> Dict[str, int]:
    cutoff = now_utc - timedelta(seconds=TOKEN_BASELINE_LOOKBACK_SEC)
    by_station: Dict[str, List[int]] = {}
    for sid, sb in sessions.items():
        if sid == active_sid or int(sb.get("corrupt_lines", 0)) > 0 or int(sb.get("frames", 0)) < TOKEN_MIN_HEALTHY_FRAMES:
            continue
        f_ts, l_ts = sb.get("first_ts"), sb.get("last_ts")
        if f_ts is None or l_ts is None or l_ts < cutoff or (l_ts - f_ts).total_seconds() < TOKEN_WARMUP_SEC:
            continue
        for st_id, st_b in sb["stations"].items():
            if len(st_b["yes_tokens"]) > 0 and len(st_b["no_tokens"]) > 0:
                by_station.setdefault(st_id, []).append(len(st_b["tokens"]))
    return {st_id: int(round(median(vals))) for st_id, vals in by_station.items() if vals}


def _classify_station_token_alert(
    st_id: str,
    cur_tot: int,
    cur_yes: int,
    cur_no: int,
    baseline: int,
    ratio: float,
    cur_sev: Severity,
    scopes: List[Dict[str, Any]],
) -> Severity:
    side_missing = (cur_yes == 0 and cur_no > 0) or (cur_no == 0 and cur_yes > 0)
    if side_missing:
        scopes.append({"scope": st_id, "reason": "TOKEN_SIDE_MISSING", "YES": cur_yes, "NO": cur_no})
        return "CRITICAL"
    if baseline > 0 and (cur_tot == 0 or ratio <= TOKEN_CRITICAL_RATIO):
        scopes.append({"scope": st_id, "reason": "TOKEN_COVERAGE_COLLAPSE", "ratio": round(ratio, 4)})
        return "CRITICAL"
    if baseline > 0 and ratio <= TOKEN_WARN_RATIO:
        scopes.append({"scope": st_id, "reason": "TOKEN_COVERAGE_DROP", "ratio": round(ratio, 4)})
        return _max_sev(cur_sev, "WARN")
    return cur_sev


def _apply_token_hysteresis(
    raw_sev: Severity, per_station: Mapping[str, Mapping[str, Any]], suppressed: bool, state: Dict[str, Any]
) -> Tuple[Severity, int]:
    prev_sev = str(state.get("token_active_severity") or "OK")
    if suppressed:
        return ("OK" if prev_sev == "OK" else prev_sev), int(state.get("token_healthy_streak") or 0)
    if raw_sev != "OK":
        state["token_healthy_streak"] = 0
        state["token_active_severity"] = _max_sev(prev_sev, raw_sev) if prev_sev != "OK" else raw_sev
        return state["token_active_severity"], 0
    if prev_sev == "OK":
        state["token_healthy_streak"] = 0
        return "OK", 0
    all_recovered = all(
        (m["ratio"] > TOKEN_RECOVER_RATIO and m["YES"] > 0 and m["NO"] > 0) for m in per_station.values()
    )
    streak = int(state.get("token_healthy_streak") or 0) + (1 if all_recovered else 0)
    if streak >= TOKEN_RECOVER_STREAK:
        state["token_healthy_streak"] = 0
        state["token_active_severity"] = "OK"
        return "OK", streak
    state["token_healthy_streak"] = streak
    return prev_sev, streak


def _disk_thresholds() -> Dict[str, Any]:
    return {
        "free_warn_ratio": DISK_FREE_WARN_RATIO,
        "free_warn_bytes": DISK_FREE_WARN_BYTES,
        "free_crit_ratio": DISK_FREE_CRIT_RATIO,
        "free_crit_bytes": DISK_FREE_CRIT_BYTES,
        "eta_crit_hours": DISK_ETA_CRIT_HOURS,
        "recent_window_sec": DISK_RECENT_WINDOW_SEC,
        "sample_min_step_sec": DISK_SAMPLE_MIN_STEP_SEC,
        "baseline_window_sec": DISK_BASELINE_WINDOW_SEC,
        "growth_multiplier": DISK_GROWTH_MULTIPLIER,
        "growth_floor_bph": DISK_GROWTH_FLOOR_BPH,
    }


def _evaluate_disk_watchdog_check(
    cfg: WatchdogConfig,
    rec_scan: Mapping[str, Any],
    audit_scan: Mapping[str, Any],
    now_utc: datetime,
    state: Dict[str, Any],
    disk_usage_fn: Callable[[Path], Any],
) -> Dict[str, Any]:
    probe_target = cfg.recordings_root if cfg.recordings_root.exists() else cfg.alerts_dir
    usage = disk_usage_fn(probe_target)
    free_bytes, total_bytes = int(usage.free), int(usage.total)
    free_ratio = free_bytes / max(1, total_bytes)
    tracked_bytes = int(rec_scan["disk_bytes"]) + int(audit_scan["disk_bytes"])
    growth_bph, baseline_bph, eta_hours = _update_disk_growth_metrics(tracked_bytes, free_bytes, now_utc, state)
    scopes: List[Dict[str, Any]] = []
    sev = "OK"
    if free_ratio < DISK_FREE_CRIT_RATIO or free_bytes < DISK_FREE_CRIT_BYTES:
        sev = "CRITICAL"
        scopes.append({"scope": str(probe_target), "reason": "DISK_CRITICAL_EXHAUSTION"})
    elif free_ratio < DISK_FREE_WARN_RATIO or free_bytes < DISK_FREE_WARN_BYTES:
        sev = "WARN"
        scopes.append({"scope": str(probe_target), "reason": "DISK_LOW_FREE_SPACE"})
    if eta_hours is not None and eta_hours < DISK_ETA_CRIT_HOURS:
        sev = "CRITICAL"
        scopes.append({"scope": str(probe_target), "reason": "DISK_ETA_UNDER_24H", "eta_full_hours": round(eta_hours, 2)})
    if growth_bph is not None and baseline_bph is not None and growth_bph >= max(DISK_GROWTH_MULTIPLIER * baseline_bph, float(DISK_GROWTH_FLOOR_BPH)):
        sev = _max_sev(sev, "WARN")
        scopes.append({"scope": str(probe_target), "reason": "DISK_GROWTH_ANOMALY", "growth_mib_per_h": round(growth_bph / _MIB, 2)})
    return {
        "status": sev,
        "metrics": {"recordings_bytes": int(rec_scan["disk_bytes"]), "audit_logs_bytes": int(audit_scan["disk_bytes"]), "tracked_bytes": tracked_bytes, "free_bytes": free_bytes, "total_bytes": total_bytes, "free_gib": round(free_bytes / _GIB, 3), "free_ratio": round(free_ratio, 4), "growth_bytes_per_hour": round(growth_bph, 2) if growth_bph is not None else None, "trailing_24h_avg_bph": round(baseline_bph, 2) if baseline_bph is not None else None, "eta_full_hours": round(eta_hours, 2) if eta_hours is not None else None},
        "thresholds": _disk_thresholds(),
        "triggered_scopes": scopes,
    }


def _update_disk_growth_metrics(
    tracked_bytes: int, free_bytes: int, now_utc: datetime, state: Dict[str, Any]
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    samples: List[Dict[str, Any]] = state.setdefault("disk_samples", [])
    retention_cut = now_utc - timedelta(seconds=DISK_SAMPLE_RETENTION_SEC)
    parsed: List[Tuple[datetime, int]] = []
    for s in samples:
        dt = _parse_iso_utc(s.get("ts_utc"))
        if dt is not None and dt >= retention_cut:
            parsed.append((dt, int(s.get("total_bytes", 0))))
    parsed.append((now_utc, tracked_bytes))
    parsed.sort(key=lambda item: item[0])
    state["disk_samples"] = [{"ts_utc": dt.isoformat(), "total_bytes": b} for dt, b in parsed]

    recent_cut = now_utc - timedelta(seconds=DISK_RECENT_WINDOW_SEC)
    recent_pts = [p for p in parsed if p[0] >= recent_cut]
    growth_bph: Optional[float] = None
    if len(recent_pts) >= 2:
        dt_sec = (recent_pts[-1][0] - recent_pts[0][0]).total_seconds()
        if dt_sec >= DISK_SAMPLE_MIN_STEP_SEC:
            growth_bph = max(0, recent_pts[-1][1] - recent_pts[0][1]) / (dt_sec / 3600.0)

    base_pts = [p for p in parsed if p[0] < recent_cut]
    if len(base_pts) < 2 and len(parsed) >= 2 and (parsed[-1][0] - parsed[0][0]).total_seconds() >= DISK_RECENT_WINDOW_SEC:
        base_pts = parsed
    baseline_bph: Optional[float] = None
    if len(base_pts) >= 2:
        b_sec = (base_pts[-1][0] - base_pts[0][0]).total_seconds()
        if b_sec >= DISK_RECENT_WINDOW_SEC:
            baseline_bph = max(0, base_pts[-1][1] - base_pts[0][1]) / (b_sec / 3600.0)

    eta_hours = (free_bytes / growth_bph) if (growth_bph is not None and growth_bph > 0) else None
    return growth_bph, baseline_bph, eta_hours


def _emit_alert_events(
    alerts_dir: Path, checks: Mapping[str, Mapping[str, Any]], now_utc: datetime, state: Dict[str, Any]
) -> List[Dict[str, Any]]:
    emitted_map: Dict[str, Dict[str, Any]] = state.setdefault("last_emitted_alerts", {})
    events: List[Dict[str, Any]] = []
    for name, check in checks.items():
        sev = str(check["status"])
        prev = emitted_map.get(name, {})
        prev_sev = str(prev.get("severity") or "OK")
        prev_ts = _parse_iso_utc(prev.get("ts_utc"))
        if sev == "OK" and prev_sev == "OK":
            continue
        escalated = _SEVERITY_RANK[sev] > _SEVERITY_RANK[prev_sev]
        resolved = sev == "OK" and prev_sev != "OK"
        cooldown_due = prev_ts is None or (now_utc - prev_ts).total_seconds() >= ALERT_COOLDOWN_SEC
        if escalated or resolved or cooldown_due:
            ev = {
                "schema_version": "watchdog_alert.v1",
                "emitted_ts_utc": now_utc.isoformat(),
                "check_name": name,
                "previous_severity": prev_sev,
                "severity": sev,
                "triggered_scopes": check["triggered_scopes"],
            }
            events.append(ev)
            emitted_map[name] = {"severity": sev, "ts_utc": now_utc.isoformat()}
    if events:
        day_file = alerts_dir / now_utc.date().isoformat() / "alerts.jsonl"
        existing = day_file.read_text(encoding="utf-8") if day_file.exists() else ""
        addition = "".join(json.dumps(ev, ensure_ascii=False, sort_keys=True) + "\n" for ev in events)
        _atomic_write_text_in_alerts(alerts_dir, day_file, existing + addition)
    return events


def _max_sev(a: Severity, b: Severity) -> Severity:
    return a if _SEVERITY_RANK[a] >= _SEVERITY_RANK[b] else b


def run_watchdog_once(
    cfg: WatchdogConfig,
    *,
    now_utc: Optional[datetime] = None,
    disk_usage_fn: Callable[[Path], Any] = shutil.disk_usage,
    pid_alive_fn: Callable[[int], bool] = _is_pid_alive,
) -> Dict[str, Any]:
    """Execute one strictly read-only 4-class watchdog poll and persist snapshot inside ``alerts_dir``."""
    cur_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    alerts_dir = _ensure_alerts_dir_isolated(cfg)
    state = _read_json_readonly(alerts_dir / "watchdog_state.json") or {}

    in_rollover = _is_in_rollover_grace(cur_utc)
    in_maintenance, maint_records = _load_maintenance_context(alerts_dir, cfg.ledger_path, cur_utc)
    rec_scan = _scan_recordings_readonly(cfg, cur_utc)
    audit_scan = _scan_audit_and_m10_readonly(cfg)

    checks = {
        "gap_rate": _evaluate_gap_rate_check(cfg, rec_scan, cur_utc, in_rollover, in_maintenance, state, pid_alive_fn),
        "corrupt_lines": _evaluate_corrupt_lines_check(rec_scan, audit_scan, cur_utc, state),
        "token_coverage": _evaluate_token_coverage_check(cfg, rec_scan, cur_utc, in_rollover, in_maintenance, state),
        "disk_watchdog": _evaluate_disk_watchdog_check(cfg, rec_scan, audit_scan, cur_utc, state, disk_usage_fn),
    }
    overall = "OK"
    for chk in checks.values():
        overall = _max_sev(overall, chk["status"])

    events = _emit_alert_events(alerts_dir, checks, cur_utc, state)
    snapshot = {
        "schema_version": "watchdog.v1",
        "checked_ts_utc": cur_utc.isoformat(),
        "overall_severity": overall,
        "planned_windows_active": bool(in_rollover or in_maintenance),
        "planned_window_details": {"rollover_grace": in_rollover, "maintenance": maint_records},
        "checks": checks,
        "emitted_events_count": len(events),
    }
    _atomic_write_text_in_alerts(alerts_dir, alerts_dir / "watchdog_state.json", json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    _atomic_write_text_in_alerts(alerts_dir, alerts_dir / "watchdog_status.json", json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
    return snapshot
