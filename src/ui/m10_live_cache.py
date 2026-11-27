"""Strictly read-only in-memory incremental M7 audit cache & live M10 HTML renderer."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlencode
import json

from src.audit.audit_logger import STREAM_FILENAMES, AuditStreamName
from src.audit.p10_reader import (
    CorruptLineRecord,
    P10Query,
    P10SessionView,
    RenderStatus,
    _build_join_chains,
    _iter_date_dirs,
    _matches_query,
    _resolve_stream_file,
    read_verified_jsonl_file,
)
from src.execution.clob_gateway import DEFAULT_GATEWAY_CONFIG_PATH, ExecutionMode
from src.ui.m10_formatting import TimezoneMode, esc, get_station_display_name
from src.ui.m10_p13_cache import IncrementalP13Lookup
from src.ui.m10_theme import build_live_poll_script
from src.ui.m10_view import build_m10_dashboard_model_from_view, render_decision_detail_html, render_m10_dashboard_html
from src.utils.causal_utils import verify_record_sha256_line

_STATIONS = ("ALL", "KORD", "KMIA", "KLGA", "KATL", "KDAL", "KSEA")
_PERIOD_LABELS = (("today", "今日"), ("week", "近7日"), ("month", "本月"), ("year", "本年"), ("all", "全部"))
_TARGET_TYPES = (("ALL", "全部标的"), ("TMAX", "最高温 TMAX"), ("TMIN", "最低温 TMIN"))
_ACTIONS = (("p3", "有下单尝试(成交置顶)"), ("filled", "仅已成交"), ("actionable", "有信号动作"), ("all", "全部扫描"))
_TZ_MODES = (("both", "北京+站点双显"), ("bjt", "仅北京时间"), ("station", "优先站点当地"))


@dataclass
class _PlainFileCursor:
    inode: int = -1
    offset: int = 0
    partial_tail: int = 0
    corrupt: List[CorruptLineRecord] = field(default_factory=list)
    records: List[Dict[str, Any]] = field(default_factory=list)
    p1_actionable: List[Dict[str, Any]] = field(default_factory=list)
    p1_recent: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=500))
    p1_valid_count: int = 0
    p1_outcomes: Dict[str, int] = field(default_factory=dict)
    p1_dim_outcomes: Dict[Tuple[str, str, str], int] = field(default_factory=dict)


@dataclass(frozen=True)
class _GzCachedFile:
    inode: int
    size: int
    mtime_ns: int
    corrupt: Tuple[CorruptLineRecord, ...]
    records: Tuple[Dict[str, Any], ...]
    p1_actionable: Tuple[Dict[str, Any], ...]
    p1_recent: Tuple[Dict[str, Any], ...]
    p1_valid_count: int
    p1_outcomes: Mapping[str, int]
    p1_dim_outcomes: Mapping[Tuple[str, str, str], int]


def _append_p1_record(cur: _PlainFileCursor, obj: Dict[str, Any]) -> None:
    cur.p1_valid_count += 1
    out = str(obj.get("decision_outcome") or "UNKNOWN")
    st = str(obj.get("station_id") or "")
    tt = str(obj.get("target_type") or "").upper()
    cur.p1_outcomes[out] = cur.p1_outcomes.get(out, 0) + 1
    dim_key = (st, tt, out)
    cur.p1_dim_outcomes[dim_key] = cur.p1_dim_outcomes.get(dim_key, 0) + 1
    if out != "BLOCKED_NO_BOOK_DEPTH":
        cur.p1_actionable.append(obj)
    cur.p1_recent.append(obj)


def _ingest_jsonl_line(
    raw_line: str, path_str: str, line_no: int, cur: _PlainFileCursor, stream: AuditStreamName
) -> None:
    stripped = raw_line.strip()
    if not stripped:
        return
    try:
        obj = json.loads(stripped)
    except Exception as exc:
        cur.corrupt.append(CorruptLineRecord(path_str, line_no, f"JSON_ERROR:{type(exc).__name__}"))
        return
    if not verify_record_sha256_line(stripped):
        cur.corrupt.append(CorruptLineRecord(path_str, line_no, "SHA256_MISMATCH"))
        return
    if stream == "p1":
        _append_p1_record(cur, obj)
    else:
        cur.records.append(obj)


def _reset_cursor(cur: _PlainFileCursor, inode: int) -> None:
    cur.inode, cur.offset = inode, 0
    cur.corrupt.clear()
    cur.records.clear()
    cur.p1_actionable.clear()
    cur.p1_recent.clear()
    cur.p1_valid_count = 0
    cur.p1_outcomes.clear()
    cur.p1_dim_outcomes.clear()


def _update_plain_cursor(path: Path, stream: AuditStreamName, cur: _PlainFileCursor) -> Tuple[int, int]:
    st = path.stat()
    if st.st_ino != cur.inode or st.st_size < cur.offset:
        _reset_cursor(cur, st.st_ino)
    skipped_bytes = cur.offset
    if st.st_size == cur.offset:
        with path.open("rb") as fb:
            fb.seek(max(0, st.st_size - 1))
            tail = fb.read(1) if st.st_size > 0 else b"\n"
        cur.partial_tail = 0 if tail == b"\n" else 1
        return 0, skipped_bytes
    with path.open("rb") as fb:
        fb.seek(cur.offset)
        chunk = fb.read()
    last_nl = chunk.rfind(b"\n")
    if last_nl < 0:
        cur.partial_tail = 1
        return 0, skipped_bytes
    cur.partial_tail = 0 if last_nl == len(chunk) - 1 else 1
    complete_bytes = chunk[: last_nl + 1]
    cur.offset += len(complete_bytes)
    for idx, line in enumerate(complete_bytes.decode("utf-8", errors="replace").splitlines(keepends=True), start=1):
        _ingest_jsonl_line(line, str(path), idx, cur, stream)
    return len(complete_bytes), skipped_bytes


class IncrementalAuditCache:
    """Thread-safe (caller-locked) in-memory incremental reader with lazy date-window loading."""

    def __init__(
        self,
        *,
        audit_root: Path,
        execution_mode: ExecutionMode = "PAPER",
        p1_window_size: int = 500,
        p13_root: Optional[Path] = None,
    ) -> None:
        self.audit_root = Path(audit_root)
        self.execution_mode: ExecutionMode = execution_mode
        self.p1_window_size = max(50, int(p1_window_size))
        self._plain: Dict[Tuple[str, AuditStreamName, Path], _PlainFileCursor] = {}
        self._gz: Dict[Tuple[str, AuditStreamName, Path], _GzCachedFile] = {}
        self._p13_cache = IncrementalP13Lookup(p13_root)
        self.last_refresh_utc: Optional[datetime] = None
        self.last_bytes_read: int = 0
        self.last_bytes_skipped: int = 0

    def list_available_dates(self) -> Tuple[str, ...]:
        """List available YYYY-MM-DD audit folders without reading file contents."""
        mode_root = self.audit_root / self.execution_mode
        return tuple(d.name for d in _iter_date_dirs(mode_root, P10Query(execution_mode=self.execution_mode)))

    def _load_gz_entry(self, key: Tuple[str, AuditStreamName, Path], path: Path, stream: AuditStreamName) -> None:
        st = path.stat()
        prev = self._gz.get(key)
        if prev is not None and (prev.inode, prev.size, prev.mtime_ns) == (st.st_ino, st.st_size, st.st_mtime_ns):
            self.last_bytes_skipped += st.st_size
            return
        res = read_verified_jsonl_file(path, verify_sha256=True)
        self.last_bytes_read += st.st_size
        if stream != "p1":
            self._gz[key] = _GzCachedFile(st.st_ino, st.st_size, st.st_mtime_ns, res.corrupt_lines, res.records, (), (), 0, {}, {})
            return
        outcomes, dim_outcomes, actionable = {}, {}, []
        for r in res.records:
            out = str(r.get("decision_outcome") or "UNKNOWN")
            dk = (str(r.get("station_id") or ""), str(r.get("target_type") or "").upper(), out)
            outcomes[out] = outcomes.get(out, 0) + 1
            dim_outcomes[dk] = dim_outcomes.get(dk, 0) + 1
            if out != "BLOCKED_NO_BOOK_DEPTH":
                actionable.append(r)
        self._gz[key] = _GzCachedFile(
            st.st_ino, st.st_size, st.st_mtime_ns, res.corrupt_lines, (),
            tuple(actionable), tuple(res.records[-self.p1_window_size :]), res.valid_lines, outcomes, dim_outcomes,
        )

    def _refresh_one_file(self, dname: str, stream: AuditStreamName, target: Path) -> None:
        key = (dname, stream, target)
        if target.suffix == ".gz":
            self._load_gz_entry(key, target, stream)
            return
        cur = self._plain.get(key)
        if cur is None:
            cur = _PlainFileCursor(p1_recent=deque(maxlen=self.p1_window_size))
            self._plain[key] = cur
        read_b, skip_b = _update_plain_cursor(target, stream, cur)
        self.last_bytes_read += read_b
        self.last_bytes_skipped += skip_b

    def refresh(
        self,
        *,
        target_dates: Optional[Sequence[str]] = None,
        extra_streams: Optional[Sequence[Tuple[str, AuditStreamName]]] = None,
    ) -> Tuple[str, ...]:
        """Incrementally read only directories inside `target_dates` (or all if None)."""
        mode_root = self.audit_root / self.execution_mode
        all_dirs = _iter_date_dirs(mode_root, P10Query(execution_mode=self.execution_mode))
        avail = tuple(d.name for d in all_dirs)
        allowed = set(target_dates) if target_dates is not None else set(avail)
        self.last_bytes_read = 0
        self.last_bytes_skipped = 0
        for ddir in all_dirs:
            if ddir.name not in allowed:
                continue
            for stream, fname in STREAM_FILENAMES.items():
                target = _resolve_stream_file(ddir, fname)
                if target.exists():
                    self._refresh_one_file(ddir.name, stream, target)
        for dname, stream in extra_streams or ():
            if dname in allowed:
                continue
            target = _resolve_stream_file(mode_root / dname, STREAM_FILENAMES[stream])
            if target.exists():
                self._refresh_one_file(dname, stream, target)
        self.last_refresh_utc = datetime.now(timezone.utc)
        return avail

    def _collect_stream(
        self, stream: AuditStreamName, date_names: Sequence[str], query: P10Query, *, include_recent_p1: bool = True
    ) -> Tuple[List[Dict[str, Any]], List[CorruptLineRecord], int]:
        rows, corrupts, tails, allowed = [], [], 0, set(date_names)
        for (dname, strm, _), cur in self._plain.items():
            if strm != stream or dname not in allowed:
                continue
            corrupts.extend(cur.corrupt)
            tails += cur.partial_tail
            src = (cur.p1_actionable + (list(cur.p1_recent) if include_recent_p1 else [])) if stream == "p1" else cur.records
            rows.extend(r for r in src if _matches_query(r, query))
        for (dname, strm, _), gz in self._gz.items():
            if strm != stream or dname not in allowed:
                continue
            corrupts.extend(gz.corrupt)
            src = (list(gz.p1_actionable) + (list(gz.p1_recent) if include_recent_p1 else [])) if stream == "p1" else gz.records
            rows.extend(r for r in src if _matches_query(r, query))
        return rows, corrupts, tails

    def _p1_totals(
        self, date_names: Sequence[str], *, station_id: Optional[str] = None, target_type: Optional[str] = None
    ) -> Tuple[int, Dict[str, int]]:
        allowed = set(date_names)
        st_f = station_id if (station_id and station_id != "ALL") else None
        tt_f = target_type.upper() if (target_type and target_type != "ALL") else None
        total, outcomes = 0, {}
        sources: List[Tuple[str, AuditStreamName, Mapping[Tuple[str, str, str], int]]] = [
            (d, s, c.p1_dim_outcomes) for (d, s, _), c in self._plain.items()
        ] + [(d, s, g.p1_dim_outcomes) for (d, s, _), g in self._gz.items()]
        for dname, strm, dim_map in sources:
            if strm != "p1" or dname not in allowed:
                continue
            for (st, tt, out), cnt in dim_map.items():
                if (st_f and st != st_f) or (tt_f and tt != tt_f):
                    continue
                total += cnt
                outcomes[out] = outcomes.get(out, 0) + cnt
        return total, outcomes

    def _latest_account_p19(self, avail_dates: Sequence[str]) -> Optional[Dict[str, Any]]:
        for dname in reversed(avail_dates):
            recs: List[Dict[str, Any]] = []
            for (dn, strm, _), cur in self._plain.items():
                if dn == dname and strm == "p19":
                    recs.extend(cur.records)
            for (dn, strm, _), gz in self._gz.items():
                if dn == dname and strm == "p19":
                    recs.extend(gz.records)
            if recs:
                return max(recs, key=lambda r: str(r.get("event_ts_utc") or ""))
        return None

    def build_live_view(
        self,
        query: P10Query,
        *,
        only_actionable: bool = True,
        limit: int = 50,
        target_type: Optional[str] = None,
        action_filter: Optional[str] = None,
    ) -> Tuple[P10SessionView, Dict[str, Any]]:
        """Build a full-window-accurate `P10SessionView` with lazy directory loading."""
        del limit  # Pagination happens in card rendering so KPIs/city/PnL stay exact.
        avail_dates = self.list_available_dates()
        selected_dates = [d.name for d in _iter_date_dirs(self.audit_root / query.execution_mode, query)]
        extras = _compute_extra_streams(avail_dates, selected_dates)
        self.refresh(target_dates=selected_dates, extra_streams=extras)
        if not selected_dates:
            empty_view = P10SessionView(query.execution_mode, "NO_AUDIT_RECORDS", "NONE", "PENDING_P9", (), (), (), (), (), (), 0, (), 0, 0)
            return empty_view, self._build_meta(avail_dates, (), query, target_type, 0, {})

        effective_action = action_filter or ("actionable" if only_actionable else "all")
        by_stream, corrupts, tails = _collect_all_streams(
            self, selected_dates, avail_dates, query, include_recent_p1=(effective_action == "all")
        )
        matched_valid = sum(len(v) for v in by_stream.values())
        p13_index = self._p13_cache.lookup_for_p1(by_stream["p1"])
        chains, missing_fk = _build_join_chains(by_stream, p13_index)
        status: RenderStatus = "DEGRADED_CORRUPT_LINES" if corrupts else ("NO_AUDIT_RECORDS" if matched_valid == 0 else "OK")
        view = P10SessionView(
            execution_mode=query.execution_mode, render_status=status,
            tail_status="CONCURRENT_TAIL_SKIPPED" if tails > 0 else "NONE",
            settlement_status="READY" if by_stream.get("p9") else "PENDING_P9",
            p1_events=by_stream["p1"], p3_events=by_stream["p3"], p12_ledgers=by_stream["p12"],
            p17_snapshots=by_stream["p17"], p19_events=by_stream["p19"], joined_chains=chains,
            valid_lines=matched_valid, corrupt_lines=tuple(corrupts),
            partial_tail_skipped_lines=tails, missing_forecast_fk_count=missing_fk, p9_events=by_stream.get("p9", ()),
        )
        total_p1, outcomes = self._p1_totals(selected_dates, station_id=query.station_id, target_type=target_type)
        return view, self._build_meta(avail_dates, selected_dates, query, target_type, total_p1, outcomes)

    def _build_meta(
        self, avail_dates: Tuple[str, ...], selected_dates: Sequence[str], query: P10Query,
        target_type: Optional[str], total_p1: int, outcomes: Dict[str, int],
    ) -> Dict[str, Any]:
        del query, target_type
        return {
            "available_dates": avail_dates, "selected_dates": tuple(selected_dates),
            "total_p1_seen": total_p1, "p1_outcomes": outcomes,
            "bytes_read": self.last_bytes_read, "bytes_skipped": self.last_bytes_skipped,
            "last_refresh_utc": self.last_refresh_utc, "latest_account_p19": self._latest_account_p19(avail_dates),
        }


def _compute_extra_streams(avail_dates: Sequence[str], selected_dates: Sequence[str]) -> List[Tuple[str, AuditStreamName]]:
    extras: List[Tuple[str, AuditStreamName]] = []
    if avail_dates and avail_dates[-1] not in selected_dates:
        extras.append((avail_dates[-1], "p19"))
    if selected_dates:
        try:
            prev_day = (date.fromisoformat(selected_dates[0]) - timedelta(days=1)).isoformat()
            if prev_day in avail_dates and prev_day not in selected_dates:
                extras.append((prev_day, "p17"))
            next_day = (date.fromisoformat(selected_dates[-1]) + timedelta(days=1)).isoformat()
            if next_day in avail_dates and next_day not in selected_dates:
                extras.append((next_day, "p9"))
        except Exception:
            pass
    return extras


def _collect_all_streams(
    cache: IncrementalAuditCache, selected_dates: Sequence[str], avail_dates: Sequence[str],
    query: P10Query, *, include_recent_p1: bool,
) -> Tuple[Dict[AuditStreamName, Tuple[Dict[str, Any], ...]], List[CorruptLineRecord], int]:
    by_stream: Dict[AuditStreamName, Tuple[Dict[str, Any], ...]] = {}
    corrupts: List[CorruptLineRecord] = []
    tails = 0
    for strm in STREAM_FILENAMES:
        recs, corr, t = cache._collect_stream(strm, selected_dates, query, include_recent_p1=include_recent_p1)
        corrupts.extend(corr)
        tails += t
        if strm == "p1":
            recs = _dedup_p1_bounded(recs, p3_recs=())
        by_stream[strm] = tuple(recs)
    p3_ids = {str(r.get("decision_id") or "") for r in by_stream["p3"] if r.get("decision_id")}
    if len(by_stream["p1"]) > 2000:
        by_stream["p1"] = tuple(_dedup_p1_bounded(by_stream["p1"], p3_ids=p3_ids, max_non_p3=2000))
    if selected_dates:
        try:
            prev_day = (date.fromisoformat(selected_dates[0]) - timedelta(days=1)).isoformat()
            if prev_day in avail_dates and prev_day not in selected_dates:
                extra_p17, _, _ = cache._collect_stream("p17", [prev_day], query, include_recent_p1=False)
                by_stream["p17"] = tuple(extra_p17) + by_stream["p17"]
            next_day = (date.fromisoformat(selected_dates[-1]) + timedelta(days=1)).isoformat()
            if next_day in avail_dates and next_day not in selected_dates:
                extra_p9, _, _ = cache._collect_stream("p9", [next_day], query, include_recent_p1=False)
                sel_set = set(selected_dates)
                by_stream["p9"] = by_stream["p9"] + tuple(r for r in extra_p9 if str(r.get("target_date") or "") in sel_set)
        except Exception:
            pass
    return by_stream, corrupts, tails


def _dedup_p1_bounded(
    recs: Iterable[Dict[str, Any]],
    *,
    p3_recs: Sequence[Dict[str, Any]] = (),
    p3_ids: Optional[set[str]] = None,
    max_non_p3: Optional[int] = None,
) -> List[Dict[str, Any]]:
    del p3_recs
    by_id: Dict[str, Dict[str, Any]] = {}
    for r in recs:
        did = str(r.get("decision_id") or "")
        if did:
            by_id[did] = r
    ordered = sorted(by_id.values(), key=lambda r: str(r.get("scan_ts_utc") or ""), reverse=True)
    if max_non_p3 is None or len(ordered) <= max_non_p3:
        return ordered
    keep_ids = p3_ids or set()
    p3_rows = [r for r in ordered if str(r.get("decision_id") or "") in keep_ids]
    other_rows = [r for r in ordered if str(r.get("decision_id") or "") not in keep_ids][:max_non_p3]
    return p3_rows + other_rows


def resolve_period_date_range(
    period: str, utc_date_str: Optional[str], avail_dates: Sequence[str], *, now_utc: Optional[datetime] = None
) -> Tuple[Optional[Tuple[date, date]], str]:
    """Resolve `(date_range, human_window_label)` from period or explicit UTC date."""
    if utc_date_str and utc_date_str != "ALL":
        d = date.fromisoformat(utc_date_str)
        return (d, d), f"指定 UTC 日 {d.isoformat()}"
    utc_today = (now_utc or datetime.now(timezone.utc)).date()
    if period == "today":
        if avail_dates and utc_today.isoformat() not in avail_dates:
            anchor = date.fromisoformat(avail_dates[-1])
        else:
            anchor = utc_today
        bjt_start = datetime(anchor.year, anchor.month, anchor.day, tzinfo=timezone.utc) + timedelta(hours=8)
        return (anchor, anchor), f"今日 (UTC {anchor.isoformat()} · 北京 {bjt_start.strftime('%m-%d %H:%M')}~次日08:00)"
    if period == "week":
        start = utc_today - timedelta(days=6)
        return (start, utc_today), f"近7日 ({start.isoformat()} ~ {utc_today.isoformat()})"
    if period == "month":
        start = utc_today.replace(day=1)
        return (start, utc_today), f"本月 ({start.isoformat()} ~ {utc_today.isoformat()})"
    if period == "year":
        start = utc_today.replace(month=1, day=1)
        return (start, utc_today), f"本年 ({start.isoformat()} ~ {utc_today.isoformat()})"
    return None, "全部历史日志"


def _build_query_link(params: Mapping[str, str], label: str, active: bool) -> str:
    cls = "pill pill-active" if active else "pill pill-link"
    return f'<a href="/?{esc(urlencode(params))}" class="{cls}">{esc(label)}</a>'


def _render_live_controls_html(
    *, refresh_sec: int, period: str, action_filter: str, station_id: Optional[str],
    target_type: Optional[str], tz_mode: TimezoneMode, utc_date_str: Optional[str],
    limit: int, page: int, meta: Mapping[str, Any],
) -> str:
    base = {
        "refresh": str(refresh_sec), "period": period, "action": action_filter,
        "station": station_id or "ALL", "target_type": target_type or "ALL",
        "tz": tz_mode, "date": utc_date_str or "ALL", "limit": str(limit), "page": str(page),
    }
    p_links = "".join(_build_query_link({**base, "period": p, "date": "ALL", "page": "1"}, lbl, period == p and not utc_date_str) for p, lbl in _PERIOD_LABELS)
    st_links = "".join(_build_query_link({**base, "station": st, "page": "1"}, "全部城市" if st == "ALL" else get_station_display_name(st), (station_id or "ALL") == st) for st in _STATIONS)
    tt_links = "".join(_build_query_link({**base, "target_type": tt, "page": "1"}, lbl, (target_type or "ALL") == tt) for tt, lbl in _TARGET_TYPES)
    act_links = "".join(_build_query_link({**base, "action": act, "page": "1"}, lbl, action_filter == act) for act, lbl in _ACTIONS)
    tz_links = "".join(_build_query_link({**base, "tz": tz}, lbl, tz_mode == tz) for tz, lbl in _TZ_MODES)
    ref_links = "".join(_build_query_link({**base, "refresh": str(s)}, f"{s}s" if s > 0 else "暂停", refresh_sec == s) for s in (10, 15, 30, 60, 0))
    lim_links = "".join(_build_query_link({**base, "limit": str(n), "page": "1"}, f"{n}条/页", limit == n) for n in (20, 50, 100, 200))
    dates = ("ALL",) + tuple(reversed((meta.get("available_dates") or ())[-10:]))
    dt_links = "".join(_build_query_link({**base, "date": d, "page": "1"}, "按周期" if d == "ALL" else d, (utc_date_str or "ALL") == d) for d in dates)
    ts_utc: Optional[datetime] = meta.get("last_refresh_utc")
    bjt_txt = ts_utc.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S +08") if ts_utc else "-"
    poll_mode_txt = f"无刷新仅更新数据 (每 {refresh_sec}s · 保留展开与滚动)" if refresh_sec > 0 else "已暂停自动更新"
    return (
        '<section class="card" aria-label="实时筛选控制条">'
        f'<div class="filter-row"><span class="filter-lbl">时间周期</span>{p_links} <span style="margin-left:8px" class="muted">刷新:</span>{ref_links}</div>'
        f'<div class="filter-row"><span class="filter-lbl">城市站点</span>{st_links}</div>'
        f'<div class="filter-row"><span class="filter-lbl">温度标的</span>{tt_links} <span style="margin-left:8px" class="filter-lbl">订单视图</span>{act_links}</div>'
        f'<div class="filter-row"><span class="filter-lbl">时区显示</span>{tz_links} <span style="margin-left:8px" class="filter-lbl">每页</span>{lim_links}</div>'
        f'<div class="filter-row"><span class="filter-lbl">指定UTC日</span>{dt_links}</div>'
        f'<div class="note-muted" style="margin:4px 0 0">上次刷新: <code>{esc(bjt_txt)}</code> | {esc(poll_mode_txt)} | '
        f'本次增量读取: <code>{esc(meta.get("bytes_read", 0))}</code> B (缓存跳过 <code>{esc(meta.get("bytes_skipped", 0))}</code> B)</div>'
        '</section>'
    )


def render_live_m10_html(
    cache: IncrementalAuditCache,
    *,
    safety_config_path: Path = DEFAULT_GATEWAY_CONFIG_PATH,
    alerts_status_path: Optional[Path] = None,
    refresh_sec: int = 15,
    only_actionable: bool = True,
    station_id: Optional[str] = None,
    utc_date_str: Optional[str] = None,
    limit: int = 50,
    page: int = 1,
    period: str = "today",
    target_type: str = "ALL",
    action_filter: Optional[str] = None,
    tz_mode: TimezoneMode = "both",
) -> str:
    """Render live read-only M10 HTML from incremental cache with DOM-preserving data polling."""
    avail_dates = cache.list_available_dates()
    parsed_date = date.fromisoformat(utc_date_str) if (utc_date_str and utc_date_str != "ALL") else None
    date_range, win_label = resolve_period_date_range(period, utc_date_str, avail_dates)
    norm_station = None if (not station_id or station_id == "ALL") else station_id
    norm_tt = None if (not target_type or target_type == "ALL") else target_type.upper()
    eff_action = action_filter or ("p3" if only_actionable else "all")
    query = P10Query(execution_mode=cache.execution_mode, date_range=date_range, station_id=norm_station, target_date=None)
    view, meta = cache.build_live_view(query, only_actionable=only_actionable, limit=limit, target_type=norm_tt, action_filter=eff_action)
    meta["window_label"] = win_label
    meta["base_params"] = {
        "refresh": str(refresh_sec), "period": period, "action": eff_action,
        "station": norm_station or "ALL", "target_type": norm_tt or "ALL",
        "tz": tz_mode, "date": parsed_date.isoformat() if parsed_date else "ALL", "limit": str(limit),
    }
    model = build_m10_dashboard_model_from_view(
        view=view, execution_mode=cache.execution_mode, safety_config_path=safety_config_path,
        utc_date=parsed_date or (date_range[1] if date_range else None), date_range=date_range,
        alerts_status_path=alerts_status_path, target_type=norm_tt,
        period_p1_outcomes=meta.get("p1_outcomes"), total_p1_scanned=meta.get("total_p1_seen"),
        latest_account_p19=meta.get("latest_account_p19"),
    )
    controls = _render_live_controls_html(
        refresh_sec=refresh_sec, period=period, action_filter=eff_action, station_id=norm_station,
        target_type=norm_tt, tz_mode=tz_mode, utc_date_str=parsed_date.isoformat() if parsed_date else None,
        limit=limit, page=page, meta=meta,
    )
    return render_m10_dashboard_html(
        model, live_head_meta_html="", live_controls_html=controls,
        live_poll_script_html=build_live_poll_script(refresh_sec),
        tz_mode=tz_mode, action_filter=eff_action, limit=limit, page=page, live_meta=meta,
    )


def render_live_decision_detail_html(
    cache: IncrementalAuditCache,
    *,
    decision_id: str,
    safety_config_path: Path = DEFAULT_GATEWAY_CONFIG_PATH,
    alerts_status_path: Optional[Path] = None,
    utc_date_str: Optional[str] = None,
    period: str = "today",
    station_id: Optional[str] = None,
    target_type: str = "ALL",
    tz_mode: TimezoneMode = "both",
    back_query: Optional[Mapping[str, str]] = None,
) -> str:
    """Render read-only popup detail page for a single `decision_id`."""
    avail_dates = cache.list_available_dates()
    parsed_date = date.fromisoformat(utc_date_str) if (utc_date_str and utc_date_str != "ALL") else None
    date_range, _ = resolve_period_date_range(period, utc_date_str, avail_dates)
    norm_station = None if (not station_id or station_id == "ALL") else station_id
    norm_tt = None if (not target_type or target_type == "ALL") else target_type.upper()
    query = P10Query(execution_mode=cache.execution_mode, date_range=date_range, station_id=norm_station, target_date=None)
    view, meta = cache.build_live_view(query, action_filter="all")
    if not any(str(r.get("decision_id") or "") == decision_id for r in view.p1_events):
        view, meta = cache.build_live_view(P10Query(execution_mode=cache.execution_mode), action_filter="all")
        norm_tt = None
    model = build_m10_dashboard_model_from_view(
        view=view, execution_mode=cache.execution_mode, safety_config_path=safety_config_path,
        utc_date=parsed_date or (date_range[1] if date_range else None), date_range=date_range,
        alerts_status_path=alerts_status_path, target_type=norm_tt,
        latest_account_p19=meta.get("latest_account_p19"),
    )
    back_url = f"/?{urlencode(back_query)}" if back_query else "/"
    return render_decision_detail_html(model, decision_id, tz_mode=tz_mode, back_url=back_url)
