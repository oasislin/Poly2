"""Light-mode financial dashboard CSS & static SVG PnL chart for M10."""

from __future__ import annotations

from datetime import date
from typing import Any, List, Mapping, Optional, Sequence

from src.ui.m10_formatting import esc

_LIGHT_CSS_BASE = """
  :root {
    --bg: #f4f6f9; --card: #ffffff; --sub: #f8fafc; --border: #e2e8f0;
    --text: #0f172a; --muted: #64748b; --blue: #2563eb; --green: #059669;
    --red: #dc2626; --amber: #d97706;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Segoe UI", sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; }
  .wrap { max-width: 1400px; margin: 0 auto; padding: 16px 22px 44px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 16px 18px; margin-bottom: 14px; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04); }
  h1, h2 { margin: 0 0 10px; font-size: 15px; font-weight: 700; color: var(--text); }
  .ticker-bar { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 10px; font-size: 13px; }
  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; margin-bottom: 14px; }
  .kpi-card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04); }
  .kpi-title { font-size: 12px; font-weight: 600; color: var(--muted); margin-bottom: 4px; }
  .kpi-main { font-size: 24px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1.25; }
  .kpi-sub { font-size: 12px; color: var(--muted); margin-top: 6px; }
  .split-grid { display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr); gap: 14px; margin-bottom: 14px; }
  @media (max-width: 980px) { .split-grid { grid-template-columns: 1fr; } }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; }
  .kv { background: var(--sub); border: 1px solid var(--border); border-radius: 8px; padding: 9px 11px; }
  .kv .k { font-size: 11px; color: var(--muted); font-weight: 600; }
  .kv .v { font-size: 14px; font-weight: 600; word-break: break-all; margin-top: 2px; font-variant-numeric: tabular-nums; }
  .pos { color: var(--green); } .neg { color: var(--red); } .muted { color: var(--muted); }
  .badge-open { color: var(--red); } .badge-closed { color: var(--green); }
  .note-muted { font-size: 12px; color: var(--muted); margin: 0 0 8px; }
  .meter { height: 6px; background: #e2e8f0; border-radius: 999px; overflow: hidden; margin-top: 6px; }
  .meter-fill { height: 100%; background: var(--blue); border-radius: 999px; }
  .filter-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-bottom: 8px; font-size: 12px; }
  .filter-lbl { font-weight: 700; color: #334155; min-width: 68px; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; text-decoration: none; border: 1px solid transparent; }
  .pill-link { background: #f1f5f9; color: #334155; border-color: #cbd5e1; }
  .pill-link:hover { background: #e2e8f0; }
  .pill-active { background: #2563eb; color: #ffffff; border-color: #1d4ed8; }
  .pill-win, .pill-ready { background: #ecfdf5; color: #047857; border-color: #a7f3d0; }
  .pill-loss { background: #fef2f2; color: #b91c1c; border-color: #fecaca; }
  .pill-pending, .pill-warn { background: #fffbeb; color: #b45309; border-color: #fde68a; }
  .pill-info, .pill-split { background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe; }
  .pill-empty { background: #f1f5f9; color: #475569; border-color: #cbd5e1; }
"""

_LIGHT_CSS_DETAILS = """
  .table-scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { border-bottom: 1px solid var(--border); padding: 7px 9px; text-align: left; vertical-align: top; }
  th { color: #475569; font-weight: 600; background: var(--sub); white-space: nowrap; }
  .empty { color: var(--muted); text-align: center; padding: 16px; font-size: 13px; }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; color: #1d4ed8; background: #eff6ff; padding: 1px 4px; border-radius: 4px; }
  details.chain-card { background: var(--sub); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; margin-top: 10px; }
  details.chain-filled { background: #f0fdf4; border-color: #86efac; }
  details.chain-card summary { cursor: pointer; font-weight: 600; font-size: 13px; color: var(--text); list-style: none; }
  .chain-head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px; }
  .chain-why { font-size: 12px; font-weight: 500; color: #334155; margin-top: 4px; }
  .stepper { display: grid; grid-template-columns: repeat(auto-fit, minmax(175px, 1fr)); gap: 8px; margin-top: 10px; }
  .step-node { background: #ffffff; border: 1px solid var(--border); border-radius: 7px; padding: 8px 10px; font-size: 11px; }
  .step-node strong { display: block; color: var(--text); margin-bottom: 2px; }
  .step-pass { border-left: 3px solid var(--green); }
  .step-warn { border-left: 3px solid var(--amber); }
  .step-fail { border-left: 3px solid var(--red); }
  .stage-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 10px; margin-top: 10px; }
  .stage-box { background: #ffffff; border: 1px solid var(--border); border-radius: 7px; padding: 10px 12px; font-size: 12px; }
  .stage-box h3 { margin: 0 0 6px; font-size: 13px; color: #1e293b; }
  .bin-bar-list { display: flex; flex-direction: column; gap: 4px; }
  .bin-row { display: grid; grid-template-columns: 150px 1fr 56px; align-items: center; gap: 8px; padding: 2px 4px; border-radius: 4px; }
  .bin-picked { background: #eff6ff; border: 1px solid #93c5fd; font-weight: 700; }
  .bin-bar { height: 8px; background: #e2e8f0; border-radius: 4px; overflow: hidden; display: block; }
  .bin-fill { height: 100%; background: #60a5fa; display: block; }
  .bin-picked .bin-fill { background: #f59e0b; }
  .bin-pct { text-align: right; font-variant-numeric: tabular-nums; }
  .reserved-live-slot { margin-top: 6px; padding: 4px 8px; border-radius: 4px; background: #f1f5f9; color: #64748b; font-style: italic; }
  details.city-card { background: var(--sub); border: 1px solid var(--border); border-radius: 8px; padding: 9px 12px; margin-top: 8px; }
  details.city-card > summary { cursor: pointer; font-size: 13px; color: var(--text); }
  .city-card-body { margin-top: 8px; padding-left: 12px; border-left: 2px solid #cbd5e1; }
  details.market-day-card { background: #ffffff; border: 1px solid var(--border); border-radius: 6px; padding: 7px 10px; margin-top: 6px; }
  details.market-day-card > summary { cursor: pointer; font-size: 12px; color: var(--text); }
  .market-day-detail { margin-top: 5px; font-size: 11px; color: var(--muted); }
  details.audit-drawer { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 12px 16px; margin-bottom: 12px; }
  details.audit-drawer > summary { cursor: pointer; font-size: 14px; font-weight: 700; color: var(--text); }
  .pnl-svg { max-width: 100%; height: auto; background: #ffffff; border: 1px solid var(--border); border-radius: 8px; display: block; }
"""


def build_light_stylesheet(is_live: bool) -> str:
    """Build complete light-mode CSS with mode-isolated banner class."""
    banner_css = (
        ".mode-banner-live { background: #b91c1c; color: #ffffff; padding: 11px 22px; "
        "font-weight: 700; font-size: 15px; letter-spacing: 0.03em; border-bottom: 3px solid #ef4444; }"
        if is_live
        else ".mode-banner-paper { background: #334155; color: #f8fafc; padding: 11px 22px; "
        "font-weight: 700; font-size: 15px; letter-spacing: 0.03em; border-bottom: 3px solid #64748b; }"
    )
    return banner_css + _LIGHT_CSS_BASE + _LIGHT_CSS_DETAILS


def _compute_svg_coords(series: Sequence[Mapping[str, Any]], width: int, height: int) -> tuple[List[float], List[float], float, float, float]:
    pad_l, pad_r, pad_t, pad_b = 68, 22, 20, 36
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    y_vals = [float(pt["cumulative_realized_pnl_usd"]) for pt in series]
    min_y, max_y = min(0.0, min(y_vals)), max(0.0, max(y_vals))
    if max_y - min_y < 1e-9:
        min_y, max_y = min_y - 1.0, max_y + 1.0
    else:
        margin = (max_y - min_y) * 0.14
        min_y, max_y = min_y - margin, max_y + margin
    parsed: List[Optional[date]] = []
    for pt in series:
        try:
            parsed.append(date.fromisoformat(str(pt["settlement_date"])))
        except Exception:
            parsed.append(None)
    valid_days = [d for d in parsed if d is not None]
    if len(valid_days) == len(series) and len(series) > 1:
        span = max(1, (valid_days[-1] - valid_days[0]).days)
        xs = [pad_l + plot_w * ((d - valid_days[0]).days / span) for d in valid_days]
    elif len(series) == 1:
        xs = [pad_l + plot_w * 0.5]
    else:
        xs = [pad_l + plot_w * (idx / (len(series) - 1)) for idx in range(len(series))]
    ys = [pad_t + plot_h * (1.0 - (v - min_y) / (max_y - min_y)) for v in y_vals]
    return xs, ys, min_y, max_y, pad_t + plot_h * (1.0 - (0.0 - min_y) / (max_y - min_y))


def render_light_daily_pnl_svg(series: Sequence[Mapping[str, Any]]) -> str:
    """Render light-mode static SVG cumulative realized PnL chart."""
    if not series:
        return '<div class="empty">暂无已结算数据，按结算日累计盈亏 SVG 曲线如实留空。</div>'
    width, height, pad_l, pad_r, pad_t, pad_b = 720, 220, 68, 22, 20, 36
    plot_h = height - pad_t - pad_b
    xs, ys, min_y, max_y, zero_y = _compute_svg_coords(series, width, height)
    ticks = [max_y, 0.0, min_y] if min_y < 0.0 < max_y else [max_y, (max_y + min_y) / 2.0, min_y]
    y_tick_svg = "".join(
        f'<line x1="{pad_l}" y1="{pad_t + plot_h * (1 - (tv - min_y) / (max_y - min_y)):.1f}" '
        f'x2="{width - pad_r}" y2="{pad_t + plot_h * (1 - (tv - min_y) / (max_y - min_y)):.1f}" '
        f'stroke="#e2e8f0" stroke-dasharray="3 3" stroke-width="1" />'
        f'<text x="{pad_l - 8}" y="{pad_t + plot_h * (1 - (tv - min_y) / (max_y - min_y)) + 4:.1f}" '
        f'text-anchor="end" fill="#64748b" font-size="11">${tv:.2f}</text>'
        for tv in ticks
    )
    circles_svg = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" '
        f'fill="{"#059669" if float(pt["cumulative_realized_pnl_usd"]) >= 0 else "#dc2626"}" '
        f'stroke="#ffffff" stroke-width="1.5" '
        f'data-settlement-date="{esc(pt["settlement_date"])}" '
        f'data-cumulative-pnl="{esc(pt["cumulative_realized_pnl_usd"])}" />'
        f'<text x="{x:.1f}" y="{height - 12}" text-anchor="middle" fill="#475569" font-size="10">{esc(pt["settlement_date"])}</text>'
        f'<text x="{x:.1f}" y="{max(pad_t + 10, y - 9):.1f}" text-anchor="middle" fill="#0f172a" font-size="10" font-weight="600">${esc(pt["cumulative_realized_pnl_usd"])}</text>'
        for pt, x, y in zip(series, xs, ys)
    )
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    poly = f'<polyline fill="none" stroke="#2563eb" stroke-width="2.5" points="{pts}" />' if len(series) >= 2 else ""
    return (
        f'<svg class="pnl-svg" viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="按结算日累计已实现盈亏曲线">'
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{height - pad_b}" stroke="#94a3b8" stroke-width="1.2" />'
        f'<line x1="{pad_l}" y1="{height - pad_b}" x2="{width - pad_r}" y2="{height - pad_b}" stroke="#94a3b8" stroke-width="1.2" />'
        f'{y_tick_svg}<line x1="{pad_l}" y1="{zero_y:.1f}" x2="{width - pad_r}" y2="{zero_y:.1f}" stroke="#64748b" stroke-dasharray="4 4" stroke-width="1.1" />'
        f'{poly}{circles_svg}</svg>'
    )


def build_live_poll_script(refresh_sec: int) -> str:
    """Build minimal same-origin read-only JS poller preserving <details> open states and scroll."""
    if int(refresh_sec) <= 0:
        return ""
    ms = int(refresh_sec) * 1000
    return (
        '<script data-m10-live-poll="1">\n'
        "(function(){\n"
        f"  var intervalMs = {ms}, busy = false;\n"
        "  async function refreshDataOnly(){\n"
        "    if (busy || document.hidden) return;\n"
        "    busy = true;\n"
        "    try {\n"
        '      var res = await fetch(window.location.href, { cache: "no-store" });\n'
        "      if (!res.ok) return;\n"
        "      var doc = new DOMParser().parseFromString(await res.text(), \"text/html\");\n"
        '      var cur = document.getElementById("m10-live-root"), nxt = doc.getElementById("m10-live-root");\n'
        "      if (!cur || !nxt) return;\n"
        "      var states = {}, sx = window.scrollX, sy = window.scrollY;\n"
        '      cur.querySelectorAll("details[id]").forEach(function(d){ states[d.id] = d.open; });\n'
        "      cur.replaceChildren.apply(cur, Array.from(nxt.childNodes).map(function(n){ return document.adoptNode(n); }));\n"
        '      cur.querySelectorAll("details[id]").forEach(function(d){ if (Object.prototype.hasOwnProperty.call(states, d.id)) d.open = states[d.id]; });\n'
        "      window.scrollTo(sx, sy);\n"
        "    } catch (_) {} finally { busy = false; }\n"
        "  }\n"
        "  setInterval(refreshDataOnly, intervalMs);\n"
        "})();\n"
        "</script>"
    )
