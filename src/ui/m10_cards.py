"""Modular light-mode stock-dashboard card & drawer renderers for M10."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlencode

from src.ui.m10_consistency import ChainTimelineVerification, M10ConsistencyReport, render_chain_timeline_html
from src.ui.m10_formatting import (
    TimezoneMode,
    describe_decision_plain,
    describe_heartbeat_text,
    describe_watchdog_freshness,
    esc,
    format_dual_ts,
    format_station_now,
    format_target_type_label,
    get_station_display_name,
)

_ZERO = Decimal("0")
_UNPERSISTED = "未落盘"


def _fmt_cell(val: Any, *, prefix: str = "", suffix: str = "") -> str:
    if val is None or val == "":
        return esc(_UNPERSISTED)
    return esc(f"{prefix}{val}{suffix}")


def _pnl_cls(val: Decimal) -> str:
    if val > _ZERO:
        return "pos"
    if val < _ZERO:
        return "neg"
    return "muted"


def _fmt_signed_usd(val: Decimal) -> str:
    sign = "+" if val > _ZERO else ("-" if val < _ZERO else "")
    return f"{sign}${abs(val)}"


def render_watchdog_badge_strip(alerts_status: Optional[Mapping[str, Any]]) -> str:
    """Render compact read-only watchdog status strip with snapshot freshness."""
    if not alerts_status:
        return ""
    checks = alerts_status.get("checks") if isinstance(alerts_status.get("checks"), Mapping) else {}
    overall = str(alerts_status.get("overall_severity") or "UNKNOWN")
    checked_ts = str(alerts_status.get("checked_ts_utc") or "-")
    age_txt, stale = describe_watchdog_freshness(alerts_status)
    pills = []
    for name in ("gap_rate", "corrupt_lines", "token_coverage", "disk_watchdog"):
        st = str((checks.get(name) or {}).get("status") or "UNKNOWN") if isinstance(checks.get(name), Mapping) else "UNKNOWN"
        cls = "pill-ready" if st == "OK" else ("pill-pending" if st == "WARN" else "pill-loss")
        pills.append(f'<span class="pill {cls}">{esc(name)}: {esc(st)}</span>')
    stale_note = f' <span class="pill pill-pending">{esc(age_txt)}</span>' if stale else f' <span class="muted">({esc(age_txt)})</span>'
    return (
        '<div class="kv"><div class="k">watchdog_summary (read-only)</div>'
        f'<div class="v">{esc(overall)} ({esc(checked_ts)}){stale_note}<br/>'
        f"{' '.join(pills)}</div></div>"
    )


def render_top_ticker_bar(model: Any, live_meta: Optional[Mapping[str, Any]], tz_mode: TimezoneMode) -> str:
    """Render top market/engine heartbeat and consistency ticker strip."""
    rp = model.risk_panel
    hb_txt, hb_cls = describe_heartbeat_text(getattr(model, "latest_activity_ts_utc", None))
    light = rp.light_status or "UNSET"
    light_cls = "pill-win" if light == "GREEN" else ("pill-pending" if light == "YELLOW" else ("pill-loss" if light == "RED" else "pill-empty"))
    cb_cls = "pill-loss" if rp.circuit_open else "pill-win"
    cb_txt = f"熔断 OPEN ({rp.consecutive_failures})" if rp.circuit_open else "熔断 CLOSED"
    rep: Optional[M10ConsistencyReport] = model.consistency_report
    cons_status = rep.overall_status if rep else "PASS"
    cons_cls = "pill-win" if cons_status == "PASS" else ("pill-pending" if cons_status == "WARN" else "pill-loss")
    pass_n = sum(1 for c in rep.checks if c.status == "PASS") if rep else 0
    total_n = len(rep.checks) if rep else 0
    wd_pill = ""
    if model.alerts_status:
        ov = str(model.alerts_status.get("overall_severity") or "UNKNOWN")
        age_txt, stale = describe_watchdog_freshness(model.alerts_status)
        wd_cls = "pill-pending" if stale else ("pill-win" if ov == "OK" else "pill-loss")
        wd_pill = f'<span class="pill {wd_cls}">巡检 {esc(ov)} · {esc(age_txt)}</span>'
    tz_lbl = {"both": "北京+站点双显", "bjt": "仅北京时间", "station": "优先站点当地时间"}.get(tz_mode, tz_mode)
    win_lbl = esc((live_meta or {}).get("window_label") or "全量加载")
    return (
        '<section class="card ticker-bar" aria-label="系统运行状态条">'
        f'<div><strong>引擎状态：</strong><span class="pill {hb_cls}">{esc(hb_txt)}</span> '
        f'<span class="pill {light_cls}">信号灯 {esc(light)}</span> '
        f'<span class="pill {cb_cls}">{esc(cb_txt)}</span> {wd_pill}</div>'
        f'<div><span class="pill pill-info">统计范围: {win_lbl}</span> '
        f'<span class="pill pill-empty">时区: {esc(tz_lbl)}</span> '
        f'<a href="#consistency-panel" class="pill {cons_cls}">逻辑核验 {esc(cons_status)} ({pass_n}/{total_n})</a></div>'
        "</section>"
    )


def _resolve_tier_pool_usd(model: Any) -> Decimal:
    acct = getattr(model, "latest_account_p19", None)
    if isinstance(acct, Mapping) and acct.get("tier_pool_usd") is not None:
        return Decimal(str(acct["tier_pool_usd"]))
    for ev in reversed(model.p19_rows):
        if ev.get("tier_pool_usd") is not None:
            return Decimal(str(ev["tier_pool_usd"]))
    return Decimal("2000")


def _render_kpi_cash_and_pnl(model: Any) -> str:
    p19 = getattr(model, "latest_account_p19", None) or (model.p19_rows[-1] if model.p19_rows else None)
    unsettled = sum((Decimal(str(c.get("unsettled_exposure_usd", 0))) for c in model.city_cards), _ZERO)
    settled_n = sum(int(c.get("settled_count", 0)) for c in model.city_cards)
    win_n = sum(int(c.get("win_count", 0)) for c in model.city_cards)
    pnl_val = model.total_realized_pnl_usd
    if p19:
        p19_free = Decimal(str(p19.get("free_usd_after", p19.get("free_cash_usd", 0))))
        locked_txt = f"${p19.get('active_locked_usd_after', p19.get('active_locked_usd', '0'))}"
        pool_usd = _resolve_tier_pool_usd(model)
        ref_free = pool_usd + pnl_val - unsettled - Decimal(str(p19.get("active_locked_usd_after", 0) or 0))
        diff = p19_free - ref_free
        main_txt = f"${ref_free}"
        mismatch = (
            f' <span class="pill pill-pending">上游重启未继承持仓 (差额 ${esc(abs(diff))})</span>'
            if abs(diff) > Decimal("0.01")
            else ""
        )
        cash_sub = (
            f"已扣未结算含费投入 ${unsettled} (冻结 {locked_txt}) · "
            f"P19 最新落盘=${p19_free}{mismatch}"
        )
    else:
        main_txt = "暂无 P19 记录"
        cash_sub = f"区间成交含费投入 ${model.total_filled_usd + model.total_fee_paid_usd} · 手续费 ${model.total_fee_paid_usd}"
    return (
        '<div class="kpi-card">'
        '<div class="kpi-title">参考实际可用余额 vs P19 落盘余额</div>'
        f'<div class="kpi-main">{esc(main_txt)}</div>'
        f'<div class="kpi-sub">{cash_sub}</div></div>'
        '<div class="kpi-card">'
        '<div class="kpi-title">区间已实现净盈亏 &amp; 战绩</div>'
        f'<div class="kpi-main {_pnl_cls(pnl_val)}">{esc(_fmt_signed_usd(pnl_val))}</div>'
        f'<div class="kpi-sub">已结算 {settled_n} 盘口 (胜 {win_n} 场) · 待结算敞口 ${esc(unsettled)}</div></div>'
    )


def _render_kpi_funnel_and_risk(model: Any, live_meta: Optional[Mapping[str, Any]]) -> str:
    outcomes: Mapping[str, int] = getattr(model, "period_p1_outcomes", None) or {}
    total_scans = getattr(model, "total_p1_scanned", None)
    if total_scans is None:
        total_scans = len(model.decision_rows)
    ordered_n = outcomes.get("ORDERED") if outcomes else sum(1 for r in model.decision_rows if r.get("decision_outcome") == "ORDERED")
    filled_rows = [r for r in model.decision_rows if r.get("terminal_status") in ("FILLED", "PARTIAL")]
    p3_rows = [r for r in model.decision_rows if int(r.get("attempt_count") or 0) > 0]
    rp = model.risk_panel
    pct = 0.0
    if rp.max_daily_cumulative_usd > _ZERO:
        pct = max(0.0, min(100.0, float(rp.daily_used_usd / rp.max_daily_cumulative_usd) * 100.0))
    frozen_txt = "FROZEN" if rp.model_frozen else "UNFROZEN"
    del live_meta
    return (
        '<div class="kpi-card">'
        '<div class="kpi-title">区间成交与下单漏斗 (全量无截断)</div>'
        f'<div class="kpi-main pos">{len(filled_rows)} 笔成交 <span style="font-size:15px">(${esc(model.total_filled_usd)})</span></div>'
        f'<div class="kpi-sub">下单尝试 {len(p3_rows)} 次 · 触发信号 {ordered_n} 次 · 累计扫描 {total_scans} 次</div></div>'
        '<div class="kpi-card" aria-label="风险参数面板">'
        '<div class="kpi-title">风险参数面板 (只读硬限额与冻结锁)</div>'
        f'<div class="kpi-main" style="font-size:18px">单笔≤${esc(rp.max_single_order_usd)} · 日余 ${esc(rp.daily_remaining_usd)}</div>'
        f'<div class="meter"><div class="meter-fill" style="width:{pct:.1f}%"></div></div>'
        f'<div class="kpi-sub">日已用 ${esc(rp.daily_used_usd)} / ${esc(rp.max_daily_cumulative_usd)} · <code>{esc(rp.model_hash or "-")}</code> ({frozen_txt})</div></div>'
    )


def render_portfolio_kpis(model: Any, live_meta: Optional[Mapping[str, Any]]) -> str:
    """Render 4 stock-portfolio style KPI cards."""
    return '<section class="kpi-grid">' + _render_kpi_cash_and_pnl(model) + _render_kpi_funnel_and_risk(model, live_meta) + "</section>"


def _page_link(base_params: Mapping[str, str], target_page: int, label: str, *, active: bool = False, disabled: bool = False, anchor: str = "") -> str:
    if disabled:
        return f'<span class="pill pill-empty" style="opacity:.45">{esc(label)}</span>'
    cls = "pill pill-active" if active else "pill pill-link"
    qs = urlencode({**base_params, "page": str(target_page)})
    return f'<a href="/?{esc(qs)}{anchor}" class="{cls}">{esc(label)}</a>'


def render_pagination_bar(
    base_params: Optional[Mapping[str, str]],
    *,
    page: int,
    total_pages: int,
    total_items: int,
    anchor: str = "",
) -> str:
    """Render pure-anchor pagination bar (`首页/上一页/页码/下一页/末页`)."""
    if not base_params or total_pages <= 1:
        return ""
    pages = sorted({1, total_pages, *{p for p in range(max(1, page - 2), min(total_pages, page + 2) + 1)}})
    nums: List[str] = []
    prev_p = 0
    for p in pages:
        if prev_p and p - prev_p > 1:
            nums.append('<span class="muted">…</span>')
        nums.append(_page_link(base_params, p, str(p), active=(p == page), anchor=anchor))
        prev_p = p
    return (
        '<div class="filter-row" style="margin:8px 0 4px">'
        f'<span class="muted">第 <strong>{page}</strong> / {total_pages} 页 (共 {total_items} 条)</span>'
        + _page_link(base_params, 1, "首页", disabled=(page <= 1), anchor=anchor)
        + _page_link(base_params, max(1, page - 1), "上一页", disabled=(page <= 1), anchor=anchor)
        + "".join(nums)
        + _page_link(base_params, min(total_pages, page + 1), "下一页", disabled=(page >= total_pages), anchor=anchor)
        + _page_link(base_params, total_pages, "末页", disabled=(page >= total_pages), anchor=anchor)
        + "</div>"
    )


def render_unified_orders_table(
    model: Any,
    tz_mode: TimezoneMode,
    *,
    action_filter: str = "p3",
    page: int = 1,
    page_size: Optional[int] = None,
    base_params: Optional[Mapping[str, str]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Render unified paginated orders/decisions table opening detail popup on click."""
    all_matched = filter_and_sort_display_rows(model.decision_rows, action_filter=action_filter, limit=None)
    total_n = len(all_matched)
    total_pages = max(1, (total_n + page_size - 1) // page_size) if (page_size and total_n) else 1
    safe_p = max(1, min(total_pages, int(page)))
    page_rows = all_matched[(safe_p - 1) * page_size : safe_p * page_size] if page_size is not None else all_matched
    settle_map = {
        (str(s.get("session_id") or ""), str(s.get("station_id") or ""), str(s.get("target_date") or ""), str(s.get("target_type") or ""), str(s.get("market_id") or "")): s
        for s in model.settlement_rows
    }
    trs = "\n".join(_render_unified_order_row(r, settle_map, tz_mode, base_params) for r in page_rows)
    pager = render_pagination_bar(base_params, page=safe_p, total_pages=total_pages, total_items=total_n, anchor="#recent-filled-table")
    body = (
        f'{pager}<div class="table-scroll"><table><thead><tr>'
        '<th>时间</th><th>城市站点</th><th>盘口日期与类型</th><th>押注档位</th>'
        '<th>状态</th><th>成交/目标额</th><th>结算状态</th><th>为什么买 / 放弃原因</th><th>因果详情</th>'
        f'</tr></thead><tbody>{trs}</tbody></table></div>{pager}'
        if page_rows
        else '<div class="empty">当前筛选条件下暂无符合的委托或成交记录。</div>'
    )
    filled_cnt = sum(1 for r in model.decision_rows if r.get("terminal_status") in ("FILLED", "PARTIAL") or Decimal(str(r.get("filled_shares") or 0)) > _ZERO)
    html_out = (
        '<section id="recent-filled-table" class="card" aria-label="委托与成交订单一览">'
        f'<h2>最近成交与委托订单一览 (共 {total_n} 条 · 已成交 {filled_cnt} 笔 · 第 {safe_p}/{total_pages} 页 · 点击查看独立详情页)</h2>'
        f'{body}</section>'
    )
    return html_out, page_rows


def _render_unified_order_row(
    r: Mapping[str, Any],
    settle_map: Mapping[Tuple[str, str, str, str, str], Mapping[str, Any]],
    tz_mode: TimezoneMode,
    base_params: Optional[Mapping[str, str]],
) -> str:
    st_id = str(r.get("station_id") or "")
    dec_id = str(r.get("decision_id") or "")
    badge_txt, badge_cls, why_txt = describe_decision_plain(r)
    key = (str(r.get("session_id") or ""), st_id, str(r.get("target_date") or ""), str(r.get("target_type") or ""), str(r.get("market_id") or ""))
    s = settle_map.get(key)
    if s is not None:
        pnl = Decimal(str(s.get("realized_pnl_usd") or 0))
        settle_cell = f'<span class="pill {"pill-win" if pnl >= _ZERO else "pill-loss"}">已结算 {_fmt_signed_usd(pnl)}</span>'
    else:
        settle_cell = '<span class="pill pill-pending">待结算</span>'
    sz = r.get("sizing_stage") if isinstance(r.get("sizing_stage"), Mapping) else {}
    amt_cell = f'<strong>${esc(r.get("filled_usd"))}</strong> <span class="muted">(费 ${esc(r.get("fee_paid_usd"))})</span>' if Decimal(str(r.get("filled_shares") or 0)) > _ZERO else f'<span class="muted">目标 ${esc(sz.get("target_slice_usd") or 0)}</span>'
    if base_params:
        detail_qs = urlencode({**base_params, "id": dec_id})
        link_html = f'<a href="/decision?{esc(detail_qs)}" target="_blank" rel="noopener" class="pill pill-info">查看详情 ↗</a>'
    else:
        link_html = f'<a href="#dec-{esc(dec_id)}" class="pill pill-info">查看因果详情</a>'
    return (
        f'<tr><td title="UTC: {esc(r.get("scan_ts_utc"))}">{esc(format_dual_ts(r.get("scan_ts_utc"), st_id, tz_mode, compact=True))}</td>'
        f'<td><strong>{esc(get_station_display_name(st_id))}</strong></td>'
        f'<td>{esc(r.get("target_date"))} · {esc(format_target_type_label(r.get("target_type")))}</td>'
        f'<td><strong>{esc(r.get("bin_id"))}</strong></td>'
        f'<td><span class="pill {badge_cls}">{esc(badge_txt)}</span></td>'
        f'<td>{amt_cell}</td><td>{settle_cell}</td>'
        f'<td style="max-width:340px">{esc(why_txt)}</td><td>{link_html}</td></tr>'
    )


def render_recent_filled_table(
    model: Any,
    tz_mode: TimezoneMode,
    *,
    page: int = 1,
    page_size: Optional[int] = None,
    base_params: Optional[Mapping[str, str]] = None,
    shown_ids: Optional[set[str]] = None,
) -> str:
    """Render paginated compact summary table of recent FILLED/PARTIAL orders."""
    filled = sorted(
        [r for r in model.decision_rows if r.get("terminal_status") in ("FILLED", "PARTIAL") or Decimal(str(r.get("filled_shares") or 0)) > _ZERO],
        key=lambda r: str(r.get("scan_ts_utc") or ""),
        reverse=True,
    )
    total_f = len(filled)
    total_pages = max(1, (total_f + page_size - 1) // page_size) if (page_size and total_f) else 1
    safe_p = max(1, page)
    page_rows = filled[(safe_p - 1) * page_size : safe_p * page_size] if page_size is not None else filled
    settle_map = {
        (str(s.get("session_id") or ""), str(s.get("station_id") or ""), str(s.get("target_date") or ""), str(s.get("target_type") or ""), str(s.get("market_id") or "")): s
        for s in model.settlement_rows
    }
    trs = "\n".join(_render_recent_filled_row(r, settle_map, tz_mode, shown_ids=shown_ids, base_params=base_params) for r in page_rows)
    pager = render_pagination_bar(base_params, page=min(safe_p, total_pages), total_pages=total_pages, total_items=total_f, anchor="#recent-filled-table")
    if page_rows:
        body = (
            f'{pager}<div class="table-scroll"><table><thead><tr>'
            '<th>下单时间</th><th>城市站点</th><th>盘口日期与类型</th><th>押注档位</th>'
            '<th>终态</th><th>成交额</th><th>手续费</th><th>结算状态</th><th>因果详情</th>'
            f'</tr></thead><tbody>{trs}</tbody></table></div>{pager}'
        )
    elif total_f > 0:
        back = _page_link(base_params, 1, "回到第 1 页查看成交单", anchor="#recent-filled-table") if base_params else ""
        body = f'<div class="empty">第 {safe_p} 页已超出已成交列表（共 {total_f} 笔已成交，位于第 1~{total_pages} 页）。 {back}</div>'
    else:
        body = '<div class="empty">当前筛选范围内暂无已成交订单（可切换上方「近7日 / 全部」或查看下方「有下单尝试」了解放弃/撤单原因）。</div>'
    return (
        '<section id="recent-filled-table" class="card" aria-label="最近成交订单一览">'
        f'<h2>最近成交订单一览 (共 {total_f} 笔 · 当前展示 {len(page_rows)} 笔 · 按时间倒序)</h2>'
        f'{body}</section>'
    )


def _render_recent_filled_row(
    r: Mapping[str, Any],
    settle_map: Mapping[Tuple[str, str, str, str, str], Mapping[str, Any]],
    tz_mode: TimezoneMode,
    *,
    shown_ids: Optional[set[str]] = None,
    base_params: Optional[Mapping[str, str]] = None,
) -> str:
    st_id = str(r.get("station_id") or "")
    dec_id = str(r.get("decision_id") or "")
    key = (str(r.get("session_id") or ""), st_id, str(r.get("target_date") or ""), str(r.get("target_type") or ""), str(r.get("market_id") or ""))
    s = settle_map.get(key)
    if s is not None:
        pnl = Decimal(str(s.get("realized_pnl_usd") or 0))
        settle_cell = f'<span class="pill {"pill-win" if pnl >= _ZERO else "pill-loss"}">已结算 {_fmt_signed_usd(pnl)}</span>'
    else:
        settle_cell = '<span class="pill pill-pending">待结算</span>'
    term = str(r.get("terminal_status") or "-")
    term_cls = "pill-win" if term == "FILLED" else "pill-pending"
    if shown_ids is None or dec_id in shown_ids or not base_params:
        href = f"#dec-{esc(dec_id)}"
    else:
        href = f"/?{esc(urlencode({**base_params, 'action': 'filled', 'page': '1'}))}#dec-{esc(dec_id)}"
    return (
        f'<tr><td title="UTC: {esc(r.get("scan_ts_utc"))}">{esc(format_dual_ts(r.get("scan_ts_utc"), st_id, tz_mode, compact=True))}</td>'
        f'<td><strong>{esc(get_station_display_name(st_id))}</strong></td>'
        f'<td>{esc(r.get("target_date"))} · {esc(format_target_type_label(r.get("target_type")))}</td>'
        f'<td><strong>{esc(r.get("bin_id"))}</strong></td>'
        f'<td><span class="pill {term_cls}">{esc(term)}</span></td>'
        f'<td><strong>${esc(r.get("filled_usd"))}</strong> <span class="muted">({esc(r.get("filled_shares"))} sh)</span></td>'
        f'<td>${esc(r.get("fee_paid_usd"))}</td>'
        f'<td>{settle_cell}</td>'
        f'<td><a href="{href}" class="pill pill-info">查看因果详情</a></td></tr>'
    )


def render_city_holdings_card(city_cards: Sequence[Mapping[str, Any]], tz_mode: TimezoneMode) -> str:
    """Render collapsed-by-default city holdings watchlist with non-empty markets sorted first."""
    if not city_cards:
        return '<div class="empty">当前筛选范围内暂无城市盘口记录。</div>'
    now_utc = datetime.now(timezone.utc)
    blocks: List[str] = []
    for city in city_cards:
        st_id = str(city.get("station_id") or "")
        pnl = Decimal(str(city.get("total_realized_pnl_usd", 0)))
        unsettled = Decimal(str(city.get("unsettled_exposure_usd", 0)))
        mrows = sorted(city.get("market_rows", ()), key=lambda m: str(m.get("target_date") or ""), reverse=True)
        mrows.sort(key=lambda m: 1 if m.get("is_empty_market") else 0)
        day_blocks = [_render_market_day_item(mrow, tz_mode) for mrow in mrows]
        blocks.append(
            f'<details id="city-{esc(st_id)}" class="city-card"><summary>'
            f'<strong>{esc(format_station_now(st_id, now_utc))}</strong> · '
            f'<span style="font-weight:700">{esc(get_station_display_name(st_id))}</span> | '
            f'投入 ${esc(city.get("total_invested_usd"))} | '
            f'敞口 ${esc(unsettled)} | '
            f'<span class="{_pnl_cls(pnl)}" style="font-weight:700">盈亏 {esc(_fmt_signed_usd(pnl))}</span> | '
            f'胜 {esc(city.get("win_count"))}/{esc(city.get("settled_count"))}'
            f'</summary><div class="city-card-body">{"".join(day_blocks)}</div></details>'
        )
    return "\n".join(blocks)


def _render_market_day_item(mrow: Mapping[str, Any], tz_mode: TimezoneMode) -> str:
    del tz_mode
    pnl_val = mrow.get("realized_pnl_usd")
    pnl_text = f"${pnl_val}" if pnl_val is not None else "-"
    st_cls = "pill-ready" if mrow.get("settlement_status") == "READY" else "pill-pending"
    outcome = str(mrow.get("outcome") or "-")
    out_cls = "pill-win" if outcome == "WIN" else ("pill-loss" if outcome == "LOSS" else "pill-empty")
    empty_tag = ' <span class="pill pill-empty">空盘口（有决策未成交）</span>' if mrow.get("is_empty_market") else ""
    split_tag = ' <span class="pill pill-split">同日多盘口独立核算</span>' if mrow.get("multi_market_same_day") else ""
    dec_ids = mrow.get("decision_ids") or ()
    sample_decs = ", ".join(str(x) for x in dec_ids[:3]) or "-"
    suffix_cnt = f" 等 {len(dec_ids)} 条" if len(dec_ids) > 3 else ""
    mkt_dom_id = esc(f"{mrow.get('station_id')}-{mrow.get('target_date')}-{mrow.get('target_type')}-{mrow.get('market_id')}-{mrow.get('session_id')}")
    return (
        f'<details id="mkt-{mkt_dom_id}" class="market-day-card"><summary>'
        f'{esc(mrow.get("target_date"))} · {esc(format_target_type_label(mrow.get("target_type")))} | '
        f'投入 ${esc(mrow.get("invested_usd"))} | 盈亏 {esc(pnl_text)} | '
        f'<span class="pill {st_cls}">{esc(mrow.get("settlement_status"))}</span> '
        f'<span class="pill {out_cls}">{esc(outcome)}</span>{empty_tag}{split_tag}</summary>'
        '<div class="market-day-detail">'
        f'market=<code>{esc(mrow.get("market_id") or "-")}</code> | '
        f'session=<code>{esc(mrow.get("session_id") or "-")}</code> | '
        f'决策={esc(mrow.get("decision_count"))} (成交={esc(mrow.get("filled_decision_count"))}) | '
        f'winning_bin={esc(mrow.get("winning_bin_id") or "-")} | '
        f'样本=<code>{esc(sample_decs)}</code>{esc(suffix_cnt)}</div></details>'
    )


def render_bin_distribution_html(dist_bins: Sequence[Mapping[str, Any]]) -> str:
    """Render P17 probability distribution bars with picked/boundary/dead tags."""
    if not dist_bins:
        return f'<div class="empty">{esc(_UNPERSISTED)} (P17.bin_probs 缺失)</div>'
    items: List[str] = []
    for b in dist_bins:
        p_raw = b.get("p_model")
        try:
            pct = max(0.0, min(100.0, float(p_raw) * 100.0)) if p_raw is not None else 0.0
            pct_label = f"{pct:.2f}%"
        except Exception:
            pct, pct_label = 0.0, _UNPERSISTED
        cls = "bin-row bin-picked" if b.get("is_selected") else "bin-row"
        tags = ([t for cond, t in ((b.get("is_selected"), "★选中"), (b.get("is_dead_bin"), "DEAD"), (b.get("is_boundary_bin"), "BOUNDARY")) if cond])
        tag_txt = f" [{' · '.join(tags)}]" if tags else ""
        items.append(
            f'<div class="{cls}"><span class="bin-lbl">{esc(b.get("label"))}{esc(tag_txt)}</span>'
            f'<span class="bin-bar"><span class="bin-fill" style="width:{pct:.1f}%"></span></span>'
            f'<span class="bin-pct">{esc(pct_label)}</span></div>'
        )
    return '<div class="bin-bar-list">' + "".join(items) + "</div>"


def filter_and_sort_display_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    action_filter: str = "all",
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Filter decision rows for card display, putting FILLED/PARTIAL first under p3."""
    if action_filter == "filled":
        filtered = [r for r in rows if r.get("terminal_status") in ("FILLED", "PARTIAL") or Decimal(str(r.get("filled_shares") or 0)) > _ZERO]
    elif action_filter == "p3":
        filtered = [r for r in rows if int(r.get("attempt_count") or 0) > 0 or r.get("decision_outcome") == "ORDERED"]
        filled_part = sorted([r for r in filtered if r.get("terminal_status") in ("FILLED", "PARTIAL")], key=lambda r: str(r.get("scan_ts_utc") or ""), reverse=True)
        rest_part = sorted([r for r in filtered if r.get("terminal_status") not in ("FILLED", "PARTIAL")], key=lambda r: str(r.get("scan_ts_utc") or ""), reverse=True)
        filtered = filled_part + rest_part
    elif action_filter == "actionable":
        filtered = sorted([r for r in rows if r.get("decision_outcome") != "BLOCKED_NO_BOOK_DEPTH"], key=lambda r: str(r.get("scan_ts_utc") or ""), reverse=True)
    else:
        filtered = sorted(list(rows), key=lambda r: str(r.get("scan_ts_utc") or ""), reverse=True)
    return filtered[: max(1, int(limit))] if limit is not None else filtered


def render_decision_story_card(
    row: Mapping[str, Any],
    settle_row: Optional[Mapping[str, Any]],
    chain_ver: Optional[ChainTimelineVerification] = None,
    *,
    tz_mode: TimezoneMode = "both",
    default_open: bool = False,
) -> str:
    """Render one expandable order/decision story card with 6-step causal stepper."""
    badge_txt, badge_cls, why_txt = describe_decision_plain(row)
    st_id = str(row.get("station_id") or "")
    ts_fmt = format_dual_ts(row.get("scan_ts_utc"), st_id, tz_mode, compact=True)
    open_attr = " open" if default_open else ""
    card_cls = "chain-card chain-filled" if row.get("terminal_status") in ("FILLED", "PARTIAL") else "chain-card"
    replay_mode = row.get("capture_replay_mode")
    replay_tag = f' <span class="pill pill-info">mode={esc(replay_mode)}</span>' if replay_mode else ""
    pnl_pill = ""
    if settle_row is not None:
        pnl_d = Decimal(str(settle_row.get("realized_pnl_usd") or 0))
        pnl_pill = f' <span class="pill {"pill-win" if pnl_d >= _ZERO else "pill-loss"}">结算 {_fmt_signed_usd(pnl_d)}</span>'
    body = _render_card_stage_boxes(row, settle_row) + render_chain_timeline_html(chain_ver, station_id=st_id, tz_mode=tz_mode) + _render_raw_meta_drawer(row)
    dec_anchor = esc(row.get("decision_id") or "")
    return (
        f'<details id="dec-{dec_anchor}" class="{card_cls}"{open_attr}><summary>'
        '<div class="chain-head">'
        f'<div><span class="pill {badge_cls}">{esc(badge_txt)}</span> '
        f'<strong>{esc(st_id)}</strong> · {esc(row.get("target_date"))} ({esc(format_target_type_label(row.get("target_type")))}) · '
        f'押注 <strong>{esc(row.get("bin_id"))}</strong>{pnl_pill}{replay_tag}</div>'
        f'<div class="muted" title="UTC: {esc(row.get("scan_ts_utc"))}">{esc(ts_fmt)} · filled=${esc(row.get("filled_usd"))}</div>'
        f'</div><div class="chain-why">{esc(why_txt)}</div>'
        f'</summary>{body}</details>'
    )


def _render_card_stage_boxes(row: Mapping[str, Any], settle_row: Optional[Mapping[str, Any]]) -> str:
    w, pe, sz = row.get("weather_stage") or {}, row.get("prob_edge_stage") or {}, row.get("sizing_stage") or {}
    p13 = row.get("p13_book_stage")
    if p13:
        asks = ", ".join(f"{lvl[0]}×{lvl[1]}" for lvl in p13.get("asks_top3", ())) or _UNPERSISTED
        bids = ", ".join(f"{lvl[0]}×{lvl[1]}" for lvl in p13.get("bids_top3", ())) or _UNPERSISTED
        p13_body = (
            f"<div>frame={_fmt_cell(p13.get('frame_seq'))} | src={_fmt_cell(p13.get('data_source'))} "
            f"| side={esc(p13.get('single_side') or 'two_sided')}</div>"
            f"<div>asks_top3: <code>{esc(asks)}</code> | bids_top3: <code>{esc(bids)}</code></div>"
            f"<div>fee_rate={_fmt_cell(p13.get('fee_rate'))} | min_shares={_fmt_cell(p13.get('min_order_size_shares'))}</div>"
        )
    else:
        p13_body = f"<div>P13 盘口帧: 暂无对应快照 (book_frame_ref={esc(row.get('book_frame_ref') or '-')})</div>"
    if settle_row is not None:
        p9_body = (
            f"<div>settlement_id: <code>{esc(settle_row.get('settlement_id'))}</code></div>"
            f"<div>winning_bin_id=<strong>{esc(settle_row.get('winning_bin_id'))}</strong> | settled_temp_f_int={_fmt_cell(settle_row.get('settled_temp_f_int'), suffix=' °F')}</div>"
            f"<div>payout=${esc(settle_row.get('payout_usd'))} - cost=${esc(settle_row.get('cost_basis_usd'))} = <strong>realized_pnl=${esc(settle_row.get('realized_pnl_usd'))}</strong></div>"
        )
    else:
        p9_body = f"<div>结算状态: PENDING_P9 ({esc(_UNPERSISTED)})</div>"
    return (
        '<div class="stage-grid">'
        f'<div class="stage-box"><h3>① 决策时点天气 (P17)</h3><div>瞬时观测温: {_fmt_cell(w.get("latest_obs_temp_f"), suffix=" °F")} (源={_fmt_cell(w.get("obs_source_mode"))})</div>'
        f'<div>日内极值 m_now: {_fmt_cell(w.get("m_now_f"), suffix=" °F")} | tau={_fmt_cell(w.get("tau_hours"), suffix="h")} | lead={_fmt_cell(w.get("gefs_lead_hours"), suffix="h")}</div></div>'
        f'<div class="stage-box"><h3>② 模型全档概率分布</h3>{render_bin_distribution_html(row.get("distribution_bins") or ())}</div>'
        f'<div class="stage-box"><h3>③ 为什么买 / 扣费后净优势</h3><div>selected_bin_p_model={_fmt_cell(pe.get("selected_bin_p_model"))} | best_ask_price={_fmt_cell(pe.get("best_ask_price"))}</div>'
        f'<div>I值 (net_ev / i_value)={_fmt_cell(pe.get("i_value"))} | q_eff={_fmt_cell(pe.get("best_ask_q_eff"))} | fee_rate={_fmt_cell(pe.get("applied_fee_rate"))}</div>'
        f'<div>best_ask_edge={_fmt_cell(pe.get("best_ask_edge"))} vs m_threshold={_fmt_cell(pe.get("m_threshold"))}</div></div>'
        f'<div class="stage-box"><h3>④ 仓位计算与三段裁剪</h3><div>B=${_fmt_cell(sz.get("b_budget_usd"))} × w(τ)={_fmt_cell(sz.get("w_tau"))} × [s(edge)={_fmt_cell(sz.get("s_edge"))} × λ(L)={_fmt_cell(sz.get("lambda_l"))}] = G=${_fmt_cell(sz.get("g_cap_usd"))}</div>'
        f'<div>G=${_fmt_cell(sz.get("g_cap_usd"))} →[Δ_G→D=${_fmt_cell(sz.get("delta_g_to_d"))}]→ D=${_fmt_cell(sz.get("headroom_d"))} →[Δ_D→slice=${_fmt_cell(sz.get("delta_d_to_slice"))}]→ slice=${_fmt_cell(sz.get("target_slice_usd"))} →[Δ_slice→fill=${_fmt_cell(sz.get("delta_slice_to_fill"))}]→ filled=${esc(sz.get("filled_usd"))} (attempts={esc(row.get("attempt_count"))}, fee=${esc(sz.get("fee_paid_usd"))})</div>'
        f'<div>b_eff_headroom=${_fmt_cell(sz.get("b_eff_headroom_usd"))} | pov_cap=${_fmt_cell(sz.get("pov_cap_usd"))} | reject_reason={_fmt_cell(sz.get("reject_reason"))}</div></div>'
        f'<div class="stage-box"><h3>⑤ CLOB 盘口快照 (P13)</h3>{p13_body}<div class="reserved-live-slot">LIVE 深度修正终注：未落盘 / 预留槽（待 S3-15 LIVE 轨启用，当前 PAPER 不解冻）</div></div>'
        f'<div class="stage-box"><h3>⑥ 官方结算对账 (P9)</h3>{p9_body}</div>'
        '</div>'
    )


def _render_raw_meta_drawer(row: Mapping[str, Any]) -> str:
    return (
        f'<details id="raw-{esc(row.get("decision_id") or "")}" style="margin-top:8px;font-size:11px;color:#64748b"><summary>原始审计索引字段 (UUID / 双哈希 / 原始 UTC)</summary>'
        f'<div style="margin-top:4px">decision_id=<code>{esc(row.get("decision_id"))}</code> | '
        f'forecast_id=<code>{esc(row.get("forecast_id"))}</code> | '
        f'market_id=<code>{esc(row.get("market_id"))}</code> | '
        f'model_hash=<code>{esc(row.get("model_hash"))}</code> | '
        f'config_hash=<code>{esc(row.get("config_hash"))}</code> | '
        f'scan_ts_utc=<code>{esc(row.get("scan_ts_utc"))}</code> | '
        f'terminal=<code>{esc(row.get("terminal_status"))}</code> | '
        f'outcome=<code>{esc(row.get("decision_outcome"))}</code></div></details>'
    )


def render_audit_drawers(model: Any, table_rows: Sequence[Mapping[str, Any]], tz_mode: TimezoneMode) -> str:
    """Render collapsible bottom drawers for P9 settlement, P19 ledger, 16-col trace & M7 integrity."""
    s_trs = "".join(
        f"<tr><td><code>{esc(r['settlement_id'])}</code></td><td>{esc(r['station_id'])}</td><td>{esc(r['target_date'])}</td>"
        f"<td>{esc(r['target_type'])}</td><td><strong>{esc(r['winning_bin_id'])}</strong></td><td>{esc(r['settled_temp_f_int'])} °F</td>"
        f"<td>{esc(r['oracle_source'])}</td><td>{'YES' if r['reconciled'] else 'NO'}</td><td>{esc(r['realized_pnl_usd'])}</td></tr>"
        for r in model.settlement_rows
    ) or f'<tr><td colspan="9" class="empty">Settlement Status: {esc(model.settlement_status)} (awaiting P9).</td></tr>'
    p19_trs = "".join(
        f"<tr><td>{esc(format_dual_ts(ev.get('event_ts_utc'), ev.get('station_id'), tz_mode, compact=True))}</td>"
        f"<td>{esc(ev.get('event_type'))}</td><td>{esc(ev.get('station_id'))}</td><td>{esc(ev.get('light_status'))}</td>"
        f"<td>{esc(ev.get('free_usd_after'))}</td><td>{esc(ev.get('active_locked_usd_after'))}</td>"
        f"<td>{esc(ev.get('station_realized_pnl_usd'))}</td><td>{esc(ev.get('reason'))}</td></tr>"
        for ev in reversed(model.p19_rows[-100:])
    ) or '<tr><td colspan="8" class="empty">No P19 capital events recorded.</td></tr>'
    d_trs = "".join(
        f"<tr><td><code>{esc(r['decision_id'])}</code></td><td>{esc(r['scan_ts_utc'])}</td><td>{esc(r['station_id'])}</td>"
        f"<td>{esc(r['target_date'])}</td><td>{esc(r['target_type'])}</td><td>{esc(r['bin_id'])}</td>"
        f"<td>{esc(r['decision_outcome'])}</td><td>{esc(r['terminal_status'])}</td><td>{esc(r['filled_usd'])}</td><td>{esc(r['gateway_stages'])}</td></tr>"
        for r in table_rows
    ) or '<tr><td colspan="10" class="empty">No decision traces in current filter.</td></tr>'
    return (
        '<details id="drawer-p9" class="audit-drawer"><summary>'
        f'M9 官方结算与盈亏对账明细 ({len(model.settlement_rows)} 条 · {esc(model.settlement_status)})</summary>'
        '<div class="table-scroll" style="margin-top:8px"><table><thead><tr>'
        '<th>settlement_id</th><th>站点</th><th>日期</th><th>类型</th><th>中奖档</th><th>结算温</th><th>真值源</th><th>已对账</th><th>净盈亏</th>'
        f'</tr></thead><tbody>{s_trs}</tbody></table></div></details>'
        '<details id="drawer-p19" class="audit-drawer"><summary>'
        f'M6 资金账本流水 P19 (共 {len(model.p19_rows)} 条 · 展示最新 100 条)</summary>'
        '<div class="table-scroll" style="margin-top:8px"><table><thead><tr>'
        '<th>时间</th><th>事件类型</th><th>站点</th><th>信号灯</th><th>可用余额</th><th>冻结中</th><th>站盈亏</th><th>原因</th>'
        f'</tr></thead><tbody>{p19_trs}</tbody></table></div></details>'
        '<details id="drawer-m7" class="audit-drawer"><summary>'
        f'原始决策与执行底层表 (展示 {len(table_rows)} 条) &amp; M7 完整性详情</summary>'
        '<div class="grid" style="margin:10px 0">'
        f'<div class="kv"><div class="k">render_status</div><div class="v">{esc(model.render_status)}</div></div>'
        f'<div class="kv"><div class="k">tail_status</div><div class="v">{esc(model.tail_status)}</div></div>'
        f'<div class="kv"><div class="k">valid / corrupt / skipped_tail</div><div class="v">{model.valid_lines} / {model.corrupt_count} / {model.partial_tail_count}</div></div>'
        f'<div class="kv"><div class="k">missing_forecast_fk</div><div class="v">{model.missing_forecast_fk_count}</div></div>'
        f'<div class="kv"><div class="k">policy_overdue_count</div><div class="v">{model.policy_overdue_count}</div></div>'
        f'<div class="kv"><div class="k">observed_model_hashes</div><div class="v"><code>{esc(", ".join(model.model_hashes) or "-")}</code></div></div>'
        f'<div class="kv"><div class="k">observed_config_hashes</div><div class="v"><code>{esc(", ".join(model.config_hashes) or "-")}</code></div></div>'
        f'<div class="kv"><div class="k">safety_config_sha256</div><div class="v"><code>{esc(model.risk_panel.safety_config_sha256)}</code></div></div>'
        f'{render_watchdog_badge_strip(model.alerts_status)}'
        '</div><div class="table-scroll"><table><thead><tr>'
        '<th>decision_id</th><th>scan_ts_utc</th><th>站点</th><th>日期</th><th>类型</th><th>档位</th><th>结果</th><th>终态</th><th>成交额</th><th>网关阶段</th>'
        f'</tr></thead><tbody>{d_trs}</tbody></table></div></details>'
    )
