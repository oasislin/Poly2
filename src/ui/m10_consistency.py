"""Read-only M10 execution-order & cross-module consistency verifier (`P17->P13->P1->P3->P19->P9`)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import html
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple

from src.audit.p10_reader import DecisionJoinChain, P10SessionView
from src.ui.m10_formatting import TimezoneMode, esc, format_dual_ts

CheckStatus = Literal["PASS", "WARN", "FAIL"]
_ZERO = Decimal("0")
_TOL = Decimal("0.01")


@dataclass(frozen=True)
class ConsistencyCheckItem:
    """Single mechanical cross-module consistency check result."""

    name: str
    status: CheckStatus
    observed: str
    rule: str


@dataclass(frozen=True)
class ChainTimelineVerification:
    """6-step causal timeline and verification outcome for one decision chain."""

    decision_id: str
    status: CheckStatus
    issues: Tuple[str, ...]
    steps: Tuple[Tuple[str, str, str], ...]


@dataclass(frozen=True)
class M10ConsistencyReport:
    """Aggregated read-only consistency report for M10."""

    overall_status: CheckStatus
    checks: Tuple[ConsistencyCheckItem, ...]
    chain_verifications: Mapping[str, ChainTimelineVerification]


def _esc(val: Any) -> str:
    return html.escape("-" if val is None else str(val), quote=True)


def _to_dec(val: Any) -> Optional[Decimal]:
    if val is None or val == "":
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None


def _parse_utc(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _pick_p3_attempt_ts(p3_attempts: Sequence[Mapping[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
    subs = [str(r.get("submit_ts_utc")) for r in p3_attempts if r.get("submit_ts_utc")]
    fins = [str(r.get("final_ts_utc")) for r in p3_attempts if r.get("final_ts_utc")]
    return (min(subs) if subs else None), (max(fins) if fins else None)


def _build_chain_steps(
    chain: DecisionJoinChain,
    settle_row: Optional[Mapping[str, Any]],
) -> Tuple[Tuple[str, str, str], ...]:
    p1 = chain.p1_record
    p17 = chain.p17_record or {}
    p13_pl = (chain.p13_record or {}).get("payload") if isinstance((chain.p13_record or {}).get("payload"), Mapping) else {}
    attempts = [r for r in chain.p3_records if r.get("schema_version") != "p3.gateway.v1"]
    p3_sub, p3_fin = _pick_p3_attempt_ts(attempts)
    p19_ts = [str(r.get("event_ts_utc")) for r in chain.p19_records if r.get("event_ts_utc")]
    p17_ts = p17.get("issue_ts_utc") or p17.get("obs_ts_utc")
    p9_ts = settle_row.get("settled_ts_utc") if settle_row else None
    p3_txt = f"{len(attempts)} attempt(s)" + (f" / final={attempts[-1].get('terminal_status')}" if attempts else "")
    p19_txt = f"{len(chain.p19_records)} event(s)" + (f" ({chain.p19_records[-1].get('event_type')})" if chain.p19_records else "")
    p9_txt = f"win={settle_row.get('winning_bin_id')} pnl=${settle_row.get('realized_pnl_usd')}" if settle_row else "PENDING_P9"
    return (
        ("① P17 预测生成", str(p17_ts or "-"), f"forecast_id={p1.get('forecast_id') or '-'}"),
        ("② P13 盘口帧", str(p13_pl.get("recv_ts_utc") or "-"), f"frame_seq={p1.get('book_frame_ref') or '-'}"),
        ("③ P1 决策判断", str(p1.get("scan_ts_utc") or "-"), f"{p1.get('decision_outcome') or '-'} ({p1.get('reject_reason') or 'OK'})"),
        ("④ P3 撮合尝试", str(p3_fin or p3_sub or "-"), p3_txt),
        ("⑤ P19 资金账本", str(max(p19_ts) if p19_ts else "-"), p19_txt),
        ("⑥ P9 官方结算", str(p9_ts or "-"), p9_txt),
    )


def _collect_order_issues(
    chain: DecisionJoinChain,
    attempts: Sequence[Mapping[str, Any]],
    settle_row: Optional[Mapping[str, Any]],
) -> List[str]:
    p1, p17 = chain.p1_record, chain.p17_record
    p13_pl = (chain.p13_record or {}).get("payload") if isinstance((chain.p13_record or {}).get("payload"), Mapping) else {}
    p17_dt = _parse_utc((p17 or {}).get("issue_ts_utc") or (p17 or {}).get("obs_ts_utc"))
    p13_dt = _parse_utc(p13_pl.get("recv_ts_utc"))
    p1_dt = _parse_utc(p1.get("scan_ts_utc"))
    p3_sub_s, p3_fin_s = _pick_p3_attempt_ts(attempts)
    p3_dt = _parse_utc(p3_sub_s or p3_fin_s)
    p19_dts = [d for d in (_parse_utc(r.get("event_ts_utc")) for r in chain.p19_records) if d is not None]
    p9_dt = _parse_utc(settle_row.get("settled_ts_utc")) if settle_row else None

    issues: List[str] = []
    pairs = (
        ("OUT_OF_ORDER:P17>P1", p17_dt, p1_dt),
        ("OUT_OF_ORDER:P13>P1", p13_dt, p1_dt),
        ("OUT_OF_ORDER:P1>P3", p1_dt, p3_dt),
        ("OUT_OF_ORDER:P3>P19", p3_dt, max(p19_dts) if p19_dts else None),
        ("OUT_OF_ORDER:P19>P9", min(p19_dts) if p19_dts else None, p9_dt),
    )
    for label, a_dt, b_dt in pairs:
        if a_dt and b_dt and a_dt > b_dt:
            issues.append(label)
    if p1.get("decision_outcome") == "ORDERED" and not attempts:
        issues.append("MISSING_LINK:ORDERED_WITHOUT_P3")
    return issues


def _check_chain_order_and_fields(
    chain: DecisionJoinChain,
    settle_row: Optional[Mapping[str, Any]],
) -> ChainTimelineVerification:
    p1, p17 = chain.p1_record, chain.p17_record
    attempts = [r for r in chain.p3_records if r.get("schema_version") != "p3.gateway.v1"]
    issues = _collect_order_issues(chain, attempts, settle_row)
    fc_id = p1.get("forecast_id")
    if isinstance(fc_id, str) and not fc_id.startswith("MISSING") and p17 is None:
        issues.append("MISSING_P17_FK")
    if p17 is not None:
        if p1.get("model_hash") and p17.get("model_hash") and p1.get("model_hash") != p17.get("model_hash"):
            issues.append("MODEL_HASH_MISMATCH")
        if p1.get("config_hash") and p17.get("config_hash") and p1.get("config_hash") != p17.get("config_hash"):
            issues.append("CONFIG_HASH_MISMATCH")
    for r3 in attempts:
        if r3.get("station_id") and p1.get("station_id") and r3.get("station_id") != p1.get("station_id"):
            issues.append("STATION_MISMATCH_P1_P3")
        if r3.get("market_id") and p1.get("market_id") and r3.get("market_id") != p1.get("market_id"):
            issues.append("MARKET_MISMATCH_P1_P3")
    target_usd = _to_dec(p1.get("target_slice_usd"))
    filled_usd = sum((_to_dec(r.get("filled_usd")) or _ZERO for r in attempts), _ZERO)
    if target_usd is not None and filled_usd > target_usd + _TOL:
        issues.append("OVERFILL_GT_TARGET_SLICE")
    fail_issues = [i for i in issues if not i.startswith("MISSING_LINK:")]
    status: CheckStatus = "FAIL" if fail_issues else ("WARN" if issues else "PASS")
    return ChainTimelineVerification(
        decision_id=chain.decision_id, status=status,
        issues=tuple(dict.fromkeys(issues)), steps=_build_chain_steps(chain, settle_row),
    )


def _eval_order_check(vers: Sequence[ChainTimelineVerification]) -> ConsistencyCheckItem:
    out_of_order = sum(1 for v in vers if any(i.startswith("OUT_OF_ORDER:") for i in v.issues))
    missing_link = sum(1 for v in vers if any(i.startswith("MISSING_LINK:") for i in v.issues))
    status: CheckStatus = "FAIL" if out_of_order > 0 else ("WARN" if missing_link > 0 else "PASS")
    return ConsistencyCheckItem(
        name="1. 时序顺序校验 (P17<=P13<=P1<=P3<=P19<=P9)",
        status=status,
        observed=f"chains={len(vers)}, out_of_order={out_of_order}, missing_link={missing_link}",
        rule="FAIL if out_of_order > 0; WARN if missing_link > 0; else PASS",
    )


def _eval_fk_hash_check(view: P10SessionView, vers: Sequence[ChainTimelineVerification]) -> ConsistencyCheckItem:
    hash_err = sum(1 for v in vers if "MODEL_HASH_MISMATCH" in v.issues or "CONFIG_HASH_MISMATCH" in v.issues)
    fk_err = int(view.missing_forecast_fk_count)
    status: CheckStatus = "FAIL" if (fk_err > 0 or hash_err > 0) else "PASS"
    return ConsistencyCheckItem(
        name="2. 预测->决策外键与双哈希一致",
        status=status,
        observed=f"missing_forecast_fk={fk_err}, hash_mismatch={hash_err}",
        rule="FAIL if missing_forecast_fk > 0 or hash_mismatch > 0; else PASS",
    )


def _eval_p1_p3_alignment(view: P10SessionView, vers: Sequence[ChainTimelineVerification]) -> ConsistencyCheckItem:
    p1_ids = {str(r.get("decision_id")) for r in view.p1_events if r.get("decision_id")}
    attempts = [r for r in view.p3_events if r.get("schema_version") != "p3.gateway.v1"]
    orphan_p3 = sum(1 for r in attempts if str(r.get("decision_id")) not in p1_ids)
    mismatch_cnt = sum(
        1 for v in vers if any(i in ("STATION_MISMATCH_P1_P3", "MARKET_MISMATCH_P1_P3", "OVERFILL_GT_TARGET_SLICE") for i in v.issues)
    )
    status: CheckStatus = "FAIL" if (orphan_p3 > 0 or mismatch_cnt > 0) else "PASS"
    return ConsistencyCheckItem(
        name="3. 决策->执行口径一致 (无孤儿P3/不超目标额)",
        status=status,
        observed=f"p3_attempts={len(attempts)}, orphan_p3={orphan_p3}, field_or_overfill_err={mismatch_cnt}",
        rule="FAIL if orphan_p3 > 0 or field_or_overfill_err > 0; else PASS",
    )


def _eval_capital_conservation(view: P10SessionView) -> ConsistencyCheckItem:
    attempts = [r for r in view.p3_events if r.get("schema_version") != "p3.gateway.v1"]
    filled_attempts = [r for r in attempts if r.get("terminal_status") in ("FILLED", "PARTIAL")]
    p19_refs = {str(ev.get("related_ref_id")) for ev in view.p19_events if ev.get("related_ref_id")}
    unlinked_fills = (
        sum(
            1 for r in filled_attempts
            if str(r.get("decision_id")) not in p19_refs and str(r.get("attempt_id")) not in p19_refs
        )
        if view.p19_events else len(filled_attempts)
    )
    residual_txt = "N/A (no full-bucket snapshot)"
    residual_fail = False
    for ev in reversed(view.p19_events):
        free = _to_dec(ev.get("free_cash_usd") if "free_cash_usd" in ev else ev.get("free_usd_after"))
        locked = _to_dec(ev.get("active_locked_usd") if "active_locked_usd" in ev else ev.get("active_locked_usd_after"))
        held = _to_dec(ev.get("held_position_cost_usd") if "held_position_cost_usd" in ev else ev.get("held_cost_usd"))
        fee = _to_dec(ev.get("cumulative_fee_paid_usd") if "cumulative_fee_paid_usd" in ev else ev.get("fee_paid_usd"))
        pool = _to_dec(ev.get("tier_pool_usd"))
        pnl = _to_dec(ev.get("realized_pnl_usd") if "realized_pnl_usd" in ev else ev.get("station_realized_pnl_usd"))
        if None not in (free, locked, held, fee, pool, pnl):
            res = free + locked + held + fee - (pool + pnl)
            residual_txt = str(res)
            residual_fail = abs(res) > _TOL
            break
    status: CheckStatus = "FAIL" if (residual_fail or (view.p19_events and unlinked_fills > 0)) else (
        "WARN" if unlinked_fills > 0 else "PASS"
    )
    return ConsistencyCheckItem(
        name="4. 执行->资金账本守恒 (P3成交 vs P19)",
        status=status,
        observed=f"p19_events={len(view.p19_events)}, filled_p3={len(filled_attempts)}, unlinked_fills={unlinked_fills}, bucket_residual={residual_txt}",
        rule="FAIL if bucket_residual > 0.01 or unlinked_fills > 0 with P19 stream present; else PASS",
    )


def _eval_settlement_reconciliation(settlement_rows: Sequence[Mapping[str, Any]]) -> ConsistencyCheckItem:
    if not settlement_rows:
        return ConsistencyCheckItem(
            name="5. 结算->盈亏对账一致 (P9 vs M6/P15)",
            status="PASS",
            observed="settled_rows=0 (PENDING_P9)",
            rule="PASS when no P9 settled yet; FAIL if payout-cost != realized_pnl",
        )
    mismatch = 0
    unreconciled = 0
    for row in settlement_rows:
        if not row.get("reconciled"):
            unreconciled += 1
        payout = _to_dec(row.get("payout_usd")) or _ZERO
        cost = _to_dec(row.get("cost_basis_usd")) or _ZERO
        pnl = _to_dec(row.get("realized_pnl_usd")) or _ZERO
        if row.get("matched_decision_count", 0) > 0 and abs((payout - cost) - pnl) > Decimal("0.0001"):
            mismatch += 1
    status: CheckStatus = "FAIL" if mismatch > 0 else ("WARN" if unreconciled > 0 else "PASS")
    return ConsistencyCheckItem(
        name="5. 结算->盈亏对账一致 (P9 vs M6/P15)",
        status=status,
        observed=f"settled_rows={len(settlement_rows)}, pnl_mismatch={mismatch}, unreconciled={unreconciled}",
        rule="FAIL if pnl_mismatch > 0; WARN if unreconciled > 0; else PASS",
    )


def evaluate_m10_consistency(
    view: P10SessionView,
    decision_rows: Sequence[Mapping[str, Any]],
    settlement_rows: Sequence[Mapping[str, Any]],
) -> M10ConsistencyReport:
    """Mechanically verify execution order and cross-stream consistency from raw M7 traces."""
    del decision_rows  # kept for clean uniform signature with M10DashboardModel builders
    settle_by_scope = {
        (
            str(s.get("session_id") or ""),
            str(s.get("station_id") or ""),
            str(s.get("target_date") or ""),
            str(s.get("target_type") or ""),
            str(s.get("market_id") or ""),
        ): s
        for s in settlement_rows
    }
    chain_map: Dict[str, ChainTimelineVerification] = {}
    for ch in view.joined_chains:
        p1 = ch.p1_record
        scope = (
            str(p1.get("session_id") or ""), str(p1.get("station_id") or ""),
            str(p1.get("target_date") or ""), str(p1.get("target_type") or ""), str(p1.get("market_id") or ""),
        )
        chain_map[ch.decision_id] = _check_chain_order_and_fields(ch, settle_by_scope.get(scope))

    vers = tuple(chain_map.values())
    checks = (
        _eval_order_check(vers),
        _eval_fk_hash_check(view, vers),
        _eval_p1_p3_alignment(view, vers),
        _eval_capital_conservation(view),
        _eval_settlement_reconciliation(settlement_rows),
    )
    overall: CheckStatus = (
        "FAIL" if any(c.status == "FAIL" for c in checks)
        else ("WARN" if any(c.status == "WARN" for c in checks) else "PASS")
    )
    return M10ConsistencyReport(overall_status=overall, checks=checks, chain_verifications=chain_map)


_PLAIN_CHECK_NOTES: Dict[str, str] = {
    "1.": "确认每笔交易严格按「预测 → 盘口 → 决策 → 下单 → 资金 → 结算」顺序发生，没有倒序或断链。",
    "2.": "确认每次决策都能唯一关联到当时的气象预测快照，且模型与策略配置指纹一致。",
    "3.": "确认每笔下单都源自合法决策，且实际成交额未超出计划切片额度。",
    "4.": "确认每笔成交都已在资金账本留痕，且「可用 + 冻结 + 持仓 + 手续费 = 本金 + 已实现盈亏」。",
    "5.": "确认官方结算真值算出的赔付减去含费成本，与账本记录的净盈亏完全一致。",
}


def _status_pill(status: CheckStatus) -> str:
    cls = "pill-win" if status == "PASS" else ("pill-pending" if status == "WARN" else "pill-loss")
    return f'<span class="pill {cls}">{esc(status)}</span>'


def _step_css_class(step_label: str, issues: Sequence[str]) -> str:
    if not issues:
        return "step-pass"
    tokens = {
        "P17": ("P17", "MODEL_HASH", "CONFIG_HASH"),
        "P13": ("P13",),
        "P1": ("P1>", "P1_", "ORDERED_WITHOUT_P3"),
        "P3": ("P3", "OVERFILL"),
        "P19": ("P19",),
        "P9": ("P9",),
    }
    for key, markers in tokens.items():
        if key in step_label and any(m in iss for iss in issues for m in markers):
            return "step-warn" if all(iss.startswith("MISSING_LINK:") for iss in issues if any(m in iss for m in markers)) else "step-fail"
    return "step-pass"


def render_consistency_panel_html(report: Optional[M10ConsistencyReport]) -> str:
    """Render read-only HTML summary table for the 5 cross-module consistency checks."""
    if report is None:
        return ""
    trs = "\n".join(
        f"<tr><td><strong>{esc(c.name)}</strong><div class='note-muted' style='margin:2px 0 0'>{esc(_PLAIN_CHECK_NOTES.get(c.name[:2], ''))}</div></td>"
        f"<td>{_status_pill(c.status)}</td>"
        f"<td><code>{esc(c.observed)}</code></td><td class='note-muted'>{esc(c.rule)}</td></tr>"
        for c in report.checks
    )
    return (
        '<details id="consistency-panel" class="audit-drawer" open>'
        f"<summary>执行逻辑顺序与结果一致性核验 {_status_pill(report.overall_status)} "
        '<span class="note-muted" style="font-weight:400;margin-left:8px">（严格基于 M7 原始日志字段机械比对，不重算、不修改）</span></summary>'
        '<div class="table-scroll" style="margin-top:10px">'
        "<table><thead><tr><th>核验项与通俗说明</th><th>结论</th><th>原始观测值</th><th>判定规则</th></tr></thead>"
        f"<tbody>{trs}</tbody></table></div></details>"
    )


def render_chain_timeline_html(
    ver: Optional[ChainTimelineVerification],
    *,
    station_id: Optional[str] = None,
    tz_mode: TimezoneMode = "both",
) -> str:
    """Render 6-step causal stepper (`P17->P13->P1->P3->P19->P9`) inside a chain card."""
    if ver is None:
        return ""
    issue_txt = ", ".join(ver.issues) if ver.issues else "全部时序与口径一致"
    nodes = "\n".join(
        f'<div class="step-node {_step_css_class(step, ver.issues)}">'
        f"<strong>{esc(step)}</strong>"
        f'<div class="muted" title="UTC: {esc(ts)}">{esc(format_dual_ts(ts, station_id, tz_mode, compact=True))}</div>'
        f'<div style="margin-top:3px">{esc(detail)}</div></div>'
        for step, ts, detail in ver.steps
    )
    return (
        '<div class="stage-box" style="margin-top:10px">'
        f"<h3>因果执行顺序反推与核验 {_status_pill(ver.status)} <span class='note-muted'>({esc(issue_txt)})</span></h3>"
        f'<div class="stepper">{nodes}</div>'
        "</div>"
    )
