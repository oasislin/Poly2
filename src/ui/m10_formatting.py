"""Read-only display formatting, station timezone & plain-language helpers for M10."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import html
from typing import Any, Dict, Literal, Mapping, Optional, Tuple
from zoneinfo import ZoneInfo

from src.data_processing.constants import STATION_METADATA

TimezoneMode = Literal["both", "bjt", "station"]
_BJT = ZoneInfo("Asia/Shanghai")
_BJT_LABEL = "北京"

_CITY_ZH: Dict[str, str] = {
    "KORD": "芝加哥",
    "KMIA": "迈阿密",
    "KLGA": "纽约",
    "KATL": "亚特兰大",
    "KDAL": "达拉斯",
    "KSEA": "西雅图",
    "KLAX": "洛杉矶",
    "KSFO": "旧金山",
    "KHOU": "休斯顿",
    "KDEN": "丹佛",
    "ZSPD": "上海",
}

_FALLBACK_TZ: Dict[str, str] = {
    "KORD": "America/Chicago",
    "KDAL": "America/Chicago",
    "KHOU": "America/Chicago",
    "KLGA": "America/New_York",
    "KATL": "America/New_York",
    "KMIA": "America/New_York",
    "KSEA": "America/Los_Angeles",
    "KLAX": "America/Los_Angeles",
    "KSFO": "America/Los_Angeles",
    "KDEN": "America/Denver",
}


def esc(val: Any) -> str:
    """HTML-escape any value with quote=True, rendering None as '-'."""
    return html.escape("-" if val is None else str(val), quote=True)


def get_station_tz_name(station_id: Optional[str]) -> str:
    """Resolve IANA timezone name for a station from STATION_METADATA."""
    sid = str(station_id or "").strip()
    meta = STATION_METADATA.get(sid)
    if isinstance(meta, Mapping) and isinstance(meta.get("timezone"), str):
        return str(meta["timezone"])
    return _FALLBACK_TZ.get(sid, "UTC")


def get_station_display_name(station_id: Optional[str]) -> str:
    """Return human-readable station label such as 'KMIA · 迈阿密'."""
    sid = str(station_id or "").strip()
    if not sid:
        return "-"
    zh = _CITY_ZH.get(sid)
    if zh:
        return f"{sid} · {zh}"
    meta = STATION_METADATA.get(sid)
    if isinstance(meta, Mapping) and meta.get("city"):
        return f"{sid} · {str(meta['city']).title()}"
    return sid


def parse_utc_ts(raw: Any) -> Optional[datetime]:
    """Parse ISO-8601 UTC timestamp string safely."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def format_dual_ts(
    raw: Any,
    station_id: Optional[str] = None,
    tz_mode: TimezoneMode = "both",
    *,
    compact: bool = False,
) -> str:
    """Format a UTC timestamp according to BJT/station timezone display mode."""
    dt = parse_utc_ts(raw)
    if dt is None:
        return "-" if raw in (None, "") else str(raw)
    bjt_dt = dt.astimezone(_BJT)
    bjt_fmt = "%m-%d %H:%M:%S" if compact else "%Y-%m-%d %H:%M:%S"
    bjt_txt = f"{_BJT_LABEL} {bjt_dt.strftime(bjt_fmt)} (+08)"
    if tz_mode == "bjt" or not station_id or station_id == "ALL":
        return bjt_txt
    tz_name = get_station_tz_name(station_id)
    try:
        st_dt = dt.astimezone(ZoneInfo(tz_name))
        abbr = st_dt.tzname() or "LOC"
        st_fmt = "%m-%d %H:%M:%S" if compact else "%Y-%m-%d %H:%M:%S"
        st_txt = f"当地 {st_dt.strftime(st_fmt)} {abbr}"
    except Exception:
        st_txt = f"UTC {dt.strftime('%H:%M:%S')}"
    if tz_mode == "station":
        return f"{st_txt} | {bjt_txt}" if not compact else st_txt
    return f"{bjt_txt} · {st_txt}"


def format_station_now(station_id: str, now_utc: Optional[datetime] = None) -> str:
    """Format current local clock time for a station card."""
    ref = now_utc or datetime.now(timezone.utc)
    tz_name = get_station_tz_name(station_id)
    try:
        st_dt = ref.astimezone(ZoneInfo(tz_name))
        return f"{st_dt.strftime('%m-%d %H:%M')} {st_dt.tzname() or ''}".strip()
    except Exception:
        return ref.strftime("%m-%d %H:%M UTC")


def format_target_type_label(target_type: Optional[str]) -> str:
    """Format temperature contract type into human-friendly label."""
    tt = str(target_type or "").upper()
    if tt == "TMAX":
        return "最高温 TMAX"
    if tt == "TMIN":
        return "最低温 TMIN"
    return tt or "-"


def describe_decision_plain(row: Mapping[str, Any]) -> Tuple[str, str, str]:
    """Return `(badge_text, badge_cls, plain_reason)` without altering raw data."""
    term = str(row.get("terminal_status") or "-")
    outcome = str(row.get("decision_outcome") or "-")
    sz = row.get("sizing_stage") if isinstance(row.get("sizing_stage"), Mapping) else {}
    pe = row.get("prob_edge_stage") if isinstance(row.get("prob_edge_stage"), Mapping) else {}
    reason = str(sz.get("reject_reason") or "").strip()
    if term == "FILLED":
        return "已成交", "pill-win", f"模型概率高于卖价且盘口撮合成功，成交 ${row.get('filled_usd')}"
    if term == "PARTIAL":
        return "部分成交", "pill-pending", f"部分撮合成交 ${row.get('filled_usd')}，剩余未完全吃下"
    if term == "PAPER_MATCH_ABORTED_GAP":
        return "跳帧撤单", "pill-warn", f"150ms 延迟期间盘口无新帧 ({reason or 'GAP'})，安全放弃防陈旧价成交"
    if term in ("CANCELLED_UNFILLED", "REJECTED"):
        return "未成交", "pill-loss", f"下单尝试未成交 ({term}: {reason or '盘口深度/限价未满足'})"
    if outcome == "ORDERED":
        return "已发单", "pill-info", f"满足净优势门槛，目标下单 ${sz.get('target_slice_usd') or '-'}"
    if outcome == "SKIP_EDGE_BELOW_M":
        return (
            "利润不足跳过",
            "pill-empty",
            f"预期优势 {pe.get('best_ask_edge') or '-'} 低于门槛 {pe.get('m_threshold') or '-'}，不值得出手",
        )
    if outcome == "BLOCKED_BELOW_MIN_ORDER":
        return "金额过小跳过", "pill-empty", f"计算仓位低于最小下单门槛 ({reason or 'MIN_ORDER'})"
    if outcome == "BLOCKED_NO_BOOK_DEPTH":
        return "无卖盘跳过", "pill-empty", "当前盘口无有效卖单深度，等待行情"
    return outcome, "pill-empty", reason or "未触发成交"


def describe_watchdog_freshness(
    alerts_status: Optional[Mapping[str, Any]],
    now_utc: Optional[datetime] = None,
) -> Tuple[str, bool]:
    """Return `(age_text, is_stale)` for watchdog snapshot."""
    if not alerts_status:
        return "未接入巡检快照", False
    dt = parse_utc_ts(alerts_status.get("checked_ts_utc"))
    if dt is None:
        return "快照时间未知", True
    ref = now_utc or datetime.now(timezone.utc)
    age = max(timedelta(0), ref - dt)
    mins = int(age.total_seconds() // 60)
    if mins < 60:
        return f"{mins} 分钟前", False
    hours = mins // 60
    if hours < 24:
        return f"{hours} 小时前", hours >= 1
    return f"{hours // 24} 天前 (快照已过期)", True


def describe_heartbeat_text(
    latest_ts_raw: Optional[str],
    now_utc: Optional[datetime] = None,
) -> Tuple[str, str]:
    """Return `(heartbeat_text, pill_class)` from latest observed M7 timestamp."""
    dt = parse_utc_ts(latest_ts_raw)
    if dt is None:
        return "暂无活动记录", "pill-empty"
    ref = now_utc or datetime.now(timezone.utc)
    sec = max(0, int((ref - dt).total_seconds()))
    if sec <= 180:
        return f"运行中 · {sec} 秒前更新", "pill-win"
    if sec <= 3600:
        return f"近期活跃 · {sec // 60} 分钟前", "pill-pending"
    return f"最近记录于 {sec // 3600} 小时前", "pill-empty"
