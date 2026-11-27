"""Strictly read-only `M10 v1` view aggregator and static HTML renderer (`S3-10`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
import html
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple

from src.audit.p10_reader import (
    DecisionJoinChain,
    P10Query,
    P10SessionView,
    RenderStatus,
    TailStatus,
    query_p10_session_view,
)
from src.execution.clob_gateway import (
    DEFAULT_GATEWAY_CONFIG_PATH,
    ExecutionMode,
    GatewayRiskPanelSnapshot,
    load_gateway_safety_config,
)
from src.ui.m10_cards import (
    filter_and_sort_display_rows,
    render_audit_drawers,
    render_city_holdings_card,
    render_decision_story_card,
    render_pagination_bar,
    render_portfolio_kpis,
    render_recent_filled_table,
    render_top_ticker_bar,
    render_unified_orders_table,
)
from src.ui.m10_consistency import (
    ChainTimelineVerification,
    M10ConsistencyReport,
    evaluate_m10_consistency,
    render_consistency_panel_html,
)
from src.ui.m10_formatting import TimezoneMode, esc
from src.ui.m10_theme import build_light_stylesheet, render_light_daily_pnl_svg

_ZERO = Decimal("0")
_UNPERSISTED = "未落盘"


@dataclass(frozen=True)
class M10DashboardModel:
    """In-memory read-only `M10 v1` view model aggregated purely from `M7` & safety config."""

    execution_mode: ExecutionMode
    render_status: RenderStatus
    tail_status: TailStatus
    settlement_status: Literal["PENDING_P9", "READY"]
    risk_panel: GatewayRiskPanelSnapshot
    view: P10SessionView
    decision_rows: Tuple[Dict[str, Any], ...]
    settlement_rows: Tuple[Dict[str, Any], ...]
    p19_rows: Tuple[Dict[str, Any], ...]
    model_hashes: Tuple[str, ...]
    config_hashes: Tuple[str, ...]
    policy_overdue_count: int
    total_filled_usd: Decimal
    total_fee_paid_usd: Decimal
    total_realized_pnl_usd: Decimal
    corrupt_count: int
    partial_tail_count: int
    valid_lines: int
    missing_forecast_fk_count: int
    city_cards: Tuple[Dict[str, Any], ...] = ()
    daily_pnl_series: Tuple[Dict[str, Any], ...] = ()
    alerts_status: Optional[Dict[str, Any]] = None
    consistency_report: Optional[M10ConsistencyReport] = None
    period_p1_outcomes: Mapping[str, int] = field(default_factory=dict)
    total_p1_scanned: Optional[int] = None
    latest_account_p19: Optional[Dict[str, Any]] = None
    latest_activity_ts_utc: Optional[str] = None
    target_type_filter: Optional[str] = None


def _read_alerts_status_readonly(alerts_status_path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if alerts_status_path is None or not alerts_status_path.exists():
        return None
    try:
        with alerts_status_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _to_decimal(value: Any, default: Decimal = _ZERO) -> Decimal:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


def _read_daily_used_readonly(ledger_path: Path, utc_day: date) -> Decimal:
    if not ledger_path.exists():
        return _ZERO
    try:
        raw = json.loads(ledger_path.read_text(encoding="utf-8"))
    except Exception:
        return _ZERO
    if not isinstance(raw, dict):
        return _ZERO
    return _to_decimal(raw.get(utc_day.isoformat()), _ZERO)


def _derive_circuit_status(p3_events: Sequence[Dict[str, Any]]) -> Tuple[bool, int]:
    circuit_open = False
    consecutive_failures = 0
    for rec in p3_events:
        if rec.get("schema_version") == "p3.gateway.v1":
            stage = rec.get("stage")
            details = rec.get("details") if isinstance(rec.get("details"), dict) else {}
            if stage == "CIRCUIT_BREAKER":
                action = details.get("action")
                if action == "TRIPPED":
                    circuit_open = True
                    consecutive_failures = int(details.get("consecutive_failures", consecutive_failures or 5))
                elif action == "MANUAL_RESET":
                    circuit_open = False
                    consecutive_failures = 0
            elif stage == "EXCEPTION":
                consecutive_failures += 1
            elif stage == "CLOB_SUCCESS":
                consecutive_failures = 0
    return circuit_open, consecutive_failures


def _derive_light_status(view: P10SessionView) -> Optional[str]:
    light: Optional[str] = None
    for rec in view.p19_events:
        if rec.get("event_type") == "LIGHT_LEVEL_APPLIED" and rec.get("light_status"):
            light = str(rec["light_status"])
    if light is not None:
        return light
    for rec in view.p1_events:
        if rec.get("light_status"):
            light = str(rec["light_status"])
    return light


def _derive_model_hash(view: P10SessionView, explicit_model_hash: Optional[str]) -> Optional[str]:
    if explicit_model_hash:
        return explicit_model_hash
    for rec in reversed(view.p1_events):
        if rec.get("model_hash"):
            return str(rec["model_hash"])
    for rec in reversed(view.p17_snapshots):
        if rec.get("model_hash"):
            return str(rec["model_hash"])
    return None


def _resolve_consolidated_terminal_status(
    attempt_recs: Sequence[Dict[str, Any]],
    total_filled_shares: Decimal,
) -> str:
    if not attempt_recs:
        return "-"
    ordered = sorted(
        enumerate(attempt_recs),
        key=lambda item: (
            str(item[1].get("final_ts_utc") or item[1].get("submit_ts_utc") or ""),
            item[0],
        ),
    )
    last_status = str(ordered[-1][1].get("terminal_status") or "-")
    if len(ordered) == 1:
        return last_status
    if last_status == "FILLED":
        return "FILLED"
    if total_filled_shares > _ZERO:
        return "PARTIAL"
    return last_status


def _to_decimal_or_none(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _extract_weather_stage(
    p1: Mapping[str, Any],
    p17: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    src = p17 if p17 is not None else {}
    obs_temp = src.get("obs_temp_f") if src.get("obs_temp_f") is not None else src.get("latest_obs_temp_f")
    obs_ts = src.get("obs_ts_utc") if src.get("obs_ts_utc") is not None else src.get("latest_obs_ts_utc")
    obs_src = src.get("obs_source") if src.get("obs_source") is not None else src.get("obs_source_mode")
    return {
        "latest_obs_temp_f": obs_temp,
        "latest_obs_ts_utc": obs_ts,
        "obs_source_mode": obs_src,
        "m_now_f": src.get("m_now_f"),
        "m_now_int_f": src.get("m_now_int_f"),
        "prior_mu0": src.get("prior_mu0"),
        "prior_sigma0": src.get("prior_sigma0"),
        "family": src.get("family"),
        "gefs_lead_hours": src.get("gefs_lead_hours"),
        "tau_hours": src.get("tau_hours") if src.get("tau_hours") is not None else p1.get("tau_hours"),
        "issue_ts_utc": src.get("issue_ts_utc"),
        "is_bridge_active": src.get("is_bridge_active"),
        "upstream_obs_fresh": src.get("upstream_obs_fresh"),
    }


def _extract_distribution_bins(
    p17: Optional[Mapping[str, Any]],
    selected_bin_id: str,
) -> Tuple[Dict[str, Any], ...]:
    if p17 is None:
        return ()
    raw_bins = p17.get("bin_probs")
    if not isinstance(raw_bins, list):
        return ()
    out: List[Dict[str, Any]] = []
    for bp in raw_bins:
        if not isinstance(bp, Mapping):
            continue
        bid = str(bp.get("bin_id") or "")
        out.append(
            {
                "bin_id": bid,
                "label": str(bp.get("label") or bid),
                "p_model": bp.get("p_model"),
                "is_selected": bid == selected_bin_id,
                "is_dead_bin": bool(bp.get("is_dead_bin", False)),
                "is_boundary_bin": bool(bp.get("is_boundary_bin", False)),
            }
        )
    return tuple(out)


def _extract_prob_edge_stage(
    p1: Mapping[str, Any],
    dist_bins: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    selected_p_model = p1.get("selected_bin_p_model")
    if selected_p_model is None:
        selected_p_model = next((b["p_model"] for b in dist_bins if b["is_selected"]), None)
    net_ev = p1.get("net_ev")
    if net_ev is None:
        net_ev = p1.get("best_ask_net_ev") if p1.get("best_ask_net_ev") is not None else p1.get("i_value")
    q_eff = p1.get("q_eff") if p1.get("q_eff") is not None else p1.get("best_ask_q_eff")
    fee_applied = p1.get("fee_rate_applied") if p1.get("fee_rate_applied") is not None else p1.get("applied_fee_rate")
    return {
        "selected_bin_p_model": selected_p_model,
        "best_ask_price": p1.get("best_ask_price"),
        "best_ask_edge": p1.get("best_ask_edge"),
        "m_threshold": p1.get("m_threshold"),
        "applied_fee_rate": fee_applied,
        "best_ask_q_eff": q_eff,
        "best_ask_net_ev": net_ev,
        "i_value": net_ev,
    }


def _extract_sizing_stage(
    p1: Mapping[str, Any],
    attempt_recs: Sequence[Mapping[str, Any]],
    filled_usd: Decimal,
    fee_paid_usd: Decimal,
) -> Dict[str, Any]:
    g_cap = _to_decimal_or_none(p1.get("g_cap_usd"))
    headroom = _to_decimal_or_none(p1.get("headroom_d"))
    target_slice = _to_decimal_or_none(p1.get("target_slice_usd"))
    reject_reason = p1.get("reject_reason") if p1.get("reject_reason") is not None else p1.get("gateway_reject_reason")
    if reject_reason is None:
        reject_reason = next(
            (str(a["reject_or_abort_reason"]) for a in attempt_recs if a.get("reject_or_abort_reason")),
            None,
        )
    return {
        "b_budget_usd": _to_decimal_or_none(p1.get("b_budget_usd")),
        "w_tau": _to_decimal_or_none(p1.get("w_tau")),
        "s_edge": _to_decimal_or_none(p1.get("s_edge")),
        "g_cap_usd": g_cap,
        "held_usd": _to_decimal_or_none(p1.get("held_usd")),
        "headroom_d": headroom,
        "target_slice_usd": target_slice,
        "filled_usd": filled_usd,
        "fee_paid_usd": fee_paid_usd,
        "delta_g_to_d": (g_cap - headroom) if (g_cap is not None and headroom is not None) else None,
        "delta_d_to_slice": (headroom - target_slice) if (headroom is not None and target_slice is not None) else None,
        "delta_slice_to_fill": (target_slice - filled_usd) if target_slice is not None else None,
        "light_status": p1.get("light_status"),
        "scaler_policy_id": p1.get("scaler_policy_id"),
        "lambda_l": p1.get("lambda_l"),
        "b_eff_headroom_usd": p1.get("b_eff_headroom_usd"),
        "pov_cap_usd": p1.get("pov_cap_usd"),
        "reject_reason": reject_reason,
    }


def _extract_p13_book_stage(p13: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if p13 is None:
        return None
    payload = p13.get("payload")
    if not isinstance(payload, Mapping):
        return None
    asks = payload.get("asks") if isinstance(payload.get("asks"), list) else []
    bids = payload.get("bids") if isinstance(payload.get("bids"), list) else []
    if not bids and isinstance(payload.get("bid_top10"), list):
        bids = payload.get("bid_top10")
    return {
        "frame_seq": payload.get("frame_seq"),
        "data_source": payload.get("data_source"),
        "single_side": payload.get("single_side"),
        "best_bid": payload.get("best_bid"),
        "fee_rate": payload.get("fee_rate"),
        "min_order_size_shares": payload.get("min_order_size_shares"),
        "asks_top3": tuple(asks[:3]),
        "bids_top3": tuple(bids[:3]),
    }


def _build_decision_rows(chains: Sequence[DecisionJoinChain]) -> Tuple[Dict[str, Any], ...]:
    rows: List[Dict[str, Any]] = []
    for chain in chains:
        p1 = chain.p1_record
        attempt_recs: List[Dict[str, Any]] = []
        gateway_stages: List[str] = []
        for p3 in chain.p3_records:
            sv = p3.get("schema_version")
            if sv == "p3.gateway.v1":
                if p3.get("stage"):
                    gateway_stages.append(str(p3["stage"]))
            else:
                attempt_recs.append(p3)
        filled_usd = sum((_to_decimal(a.get("filled_usd")) for a in attempt_recs), _ZERO)
        filled_shares = sum((_to_decimal(a.get("filled_shares")) for a in attempt_recs), _ZERO)
        fee_paid_usd = sum((_to_decimal(a.get("fee_paid_usd")) for a in attempt_recs), _ZERO)
        terminal_status = _resolve_consolidated_terminal_status(attempt_recs, filled_shares)
        bin_id = str(p1.get("bin_id") or "")
        dist_bins = _extract_distribution_bins(chain.p17_record, bin_id)
        rows.append(
            {
                "decision_id": chain.decision_id,
                "session_id": str(p1.get("session_id") or ""),
                "capture_replay_mode": p1.get("capture_replay_mode"),
                "scan_ts_utc": str(p1.get("scan_ts_utc") or ""),
                "station_id": str(p1.get("station_id") or ""),
                "target_date": str(p1.get("target_date") or ""),
                "target_type": str(p1.get("target_type") or ""),
                "market_id": str(p1.get("market_id") or ""),
                "bin_id": bin_id,
                "decision_outcome": str(p1.get("decision_outcome") or ""),
                "model_hash": str(p1.get("model_hash") or ""),
                "config_hash": str(p1.get("config_hash") or ""),
                "policy_version": str(p1.get("policy_version") or ""),
                "policy_overdue": bool(p1.get("policy_overdue", False)),
                "forecast_id": str(p1.get("forecast_id") or ""),
                "forecast_fk_present": chain.p17_record is not None,
                "book_frame_ref": p1.get("book_frame_ref"),
                "p13_ref_present": chain.p13_record is not None,
                "terminal_status": terminal_status,
                "attempt_count": len(attempt_recs),
                "filled_shares": filled_shares,
                "filled_usd": filled_usd,
                "fee_paid_usd": fee_paid_usd,
                "gateway_stages": " -> ".join(gateway_stages) if gateway_stages else "-",
                "p19_count": len(chain.p19_records),
                "weather_stage": _extract_weather_stage(p1, chain.p17_record),
                "distribution_bins": dist_bins,
                "prob_edge_stage": _extract_prob_edge_stage(p1, dist_bins),
                "sizing_stage": _extract_sizing_stage(p1, attempt_recs, filled_usd, fee_paid_usd),
                "p13_book_stage": _extract_p13_book_stage(chain.p13_record),
            }
        )
    return tuple(rows)


def _matches_p9_settlement_scope(row: Dict[str, Any], p9: Dict[str, Any]) -> bool:
    if row["filled_shares"] <= _ZERO:
        return False
    p9_session = str(p9.get("session_id") or "")
    p9_station = str(p9.get("station_id") or "")
    p9_target_date = str(p9.get("target_date") or "")
    p9_target_type = str(p9.get("target_type") or "")
    p9_market_id = str(p9.get("market_id") or "")
    return (
        row["session_id"] == p9_session
        and row["station_id"] == p9_station
        and row["target_date"] == p9_target_date
        and row["target_type"] == p9_target_type
        and row["market_id"] == p9_market_id
    )


def _build_settlement_rows(
    view: P10SessionView,
    decision_rows: Sequence[Dict[str, Any]],
) -> Tuple[Tuple[Dict[str, Any], ...], Decimal]:
    p15_by_ref: Dict[str, Dict[str, Any]] = {}
    for ev in view.p19_events:
        ref = ev.get("related_ref_id")
        if ref:
            p15_by_ref[str(ref)] = ev

    rows: List[Dict[str, Any]] = []
    seen_settlement_ids: set[str] = set()
    total_pnl = _ZERO
    for p9 in view.p9_events:
        sid = str(p9.get("settlement_id") or "")
        if sid and sid in seen_settlement_ids:
            continue
        if sid:
            seen_settlement_ids.add(sid)

        st_id = str(p9.get("station_id") or "")
        t_date = str(p9.get("target_date") or "")
        win_bin = p9.get("winning_bin_id")
        p15 = p15_by_ref.get(sid)

        matched_decisions = [r for r in decision_rows if _matches_p9_settlement_scope(r, p9)]
        payout_usd = sum(
            (r["filled_shares"] for r in matched_decisions if r["bin_id"] == win_bin),
            _ZERO,
        )
        cost_basis_usd = sum(
            (r["filled_usd"] + r["fee_paid_usd"] for r in matched_decisions),
            _ZERO,
        )
        if matched_decisions:
            realized_pnl = payout_usd - cost_basis_usd
        elif p15 and p15.get("station_realized_pnl_usd") is not None:
            realized_pnl = _to_decimal(p15.get("station_realized_pnl_usd"))
        else:
            realized_pnl = _ZERO

        total_pnl += realized_pnl
        rows.append(
            {
                "settlement_id": sid,
                "session_id": str(p9.get("session_id") or ""),
                "settled_ts_utc": str(p9.get("settled_ts_utc") or ""),
                "station_id": st_id,
                "target_date": t_date,
                "target_type": str(p9.get("target_type") or ""),
                "market_id": str(p9.get("market_id") or ""),
                "winning_bin_id": win_bin,
                "oracle_source": str(p9.get("oracle_source") or ""),
                "oracle_source_tier": str(p9.get("oracle_source_tier") or ""),
                "settled_temp_f_int": p9.get("settled_temp_f_int"),
                "fallback_to_lowest_bin": bool(p9.get("fallback_to_lowest_bin", False)),
                "payout_usd": payout_usd,
                "cost_basis_usd": cost_basis_usd,
                "reconciled": bool(matched_decisions) or (p15 is not None),
                "realized_pnl_usd": realized_pnl,
                "free_usd_after": p15.get("free_usd_after") if p15 else None,
            }
        )
    return tuple(rows), total_pnl


def _unique_non_empty(values: Iterable[Optional[str]]) -> Tuple[str, ...]:
    seen: List[str] = []
    for val in values:
        if val and val not in seen:
            seen.append(val)
    return tuple(seen)


def _build_city_date_aggregations(
    decision_rows: Sequence[Dict[str, Any]],
    settlement_rows: Sequence[Dict[str, Any]],
) -> Tuple[Dict[str, Any], ...]:
    """Aggregate independent markets strictly by M7 §2.7 scope under each city.

    Domain invariant: each daily/market scope is independent; city totals only sum
    monetary amounts and counts (never cross-market probability or win-rate averaging).
    """
    decisions_by_scope: Dict[Tuple[str, str, str, str, str], List[Dict[str, Any]]] = {}
    for row in decision_rows:
        scope = (
            str(row.get("session_id") or ""),
            str(row.get("station_id") or ""),
            str(row.get("target_date") or ""),
            str(row.get("target_type") or ""),
            str(row.get("market_id") or ""),
        )
        decisions_by_scope.setdefault(scope, []).append(row)

    settle_by_scope: Dict[Tuple[str, str, str, str, str], Dict[str, Any]] = {}
    for s in settlement_rows:
        scope = (
            str(s.get("session_id") or ""),
            str(s.get("station_id") or ""),
            str(s.get("target_date") or ""),
            str(s.get("target_type") or ""),
            str(s.get("market_id") or ""),
        )
        settle_by_scope[scope] = s

    all_scopes = sorted(
        set(decisions_by_scope.keys()) | set(settle_by_scope.keys()),
        key=lambda sc: (sc[1], sc[2], sc[3], sc[4], sc[0]),
    )

    scopes_per_station_day: Dict[Tuple[str, str], int] = {}
    for _, st_id, t_date, _, _ in all_scopes:
        scopes_per_station_day[(st_id, t_date)] = scopes_per_station_day.get((st_id, t_date), 0) + 1

    by_station: Dict[str, List[Dict[str, Any]]] = {}
    for scope in all_scopes:
        session_id, st_id, t_date, t_type, market_id = scope
        scope_decs = decisions_by_scope.get(scope, [])
        p9 = settle_by_scope.get(scope)

        total_shares = sum((_to_decimal(d.get("filled_shares")) for d in scope_decs), _ZERO)
        if scope_decs:
            invested_usd = sum(
                (_to_decimal(d.get("filled_usd")) + _to_decimal(d.get("fee_paid_usd")) for d in scope_decs),
                _ZERO,
            )
        elif p9 is not None:
            invested_usd = _to_decimal(p9.get("cost_basis_usd"))
        else:
            invested_usd = _ZERO

        has_fill = total_shares > _ZERO or invested_usd > _ZERO
        is_settled = p9 is not None
        settlement_status: Literal["READY", "PENDING_P9"] = "READY" if is_settled else "PENDING_P9"
        realized_pnl_usd: Optional[Decimal] = _to_decimal(p9.get("realized_pnl_usd")) if is_settled else None
        unsettled_exposure_usd = _ZERO if is_settled else invested_usd

        is_empty_market = bool(scope_decs) and not has_fill
        reconciled = bool(p9.get("reconciled")) if p9 is not None else False
        winning_bin_id = p9.get("winning_bin_id") if p9 is not None else None
        payout_usd = _to_decimal(p9.get("payout_usd")) if p9 is not None else _ZERO

        if not is_settled:
            outcome = "未成交" if is_empty_market else "-"
        elif not has_fill and not reconciled:
            outcome = "未成交"
        elif scope_decs:
            won_bin = any(
                _to_decimal(d.get("filled_shares")) > _ZERO and d.get("bin_id") == winning_bin_id
                for d in scope_decs
            )
            outcome = "WIN" if (won_bin or payout_usd > _ZERO or (realized_pnl_usd or _ZERO) > _ZERO) else "LOSS"
        else:
            outcome = "WIN" if (realized_pnl_usd or _ZERO) > _ZERO else "LOSS"

        market_row = {
            "session_id": session_id,
            "station_id": st_id,
            "target_date": t_date,
            "target_type": t_type,
            "market_id": market_id,
            "decision_count": len(scope_decs),
            "filled_decision_count": sum(1 for d in scope_decs if _to_decimal(d.get("filled_shares")) > _ZERO),
            "has_fill": has_fill,
            "is_empty_market": is_empty_market,
            "invested_usd": invested_usd,
            "realized_pnl_usd": realized_pnl_usd,
            "unsettled_exposure_usd": unsettled_exposure_usd,
            "settlement_status": settlement_status,
            "outcome": outcome,
            "winning_bin_id": winning_bin_id,
            "settlement_id": str(p9.get("settlement_id") or "") if p9 is not None else None,
            "multi_market_same_day": scopes_per_station_day.get((st_id, t_date), 1) > 1,
            "decision_ids": tuple(str(d.get("decision_id") or "") for d in scope_decs),
        }
        by_station.setdefault(st_id, []).append(market_row)

    cards: List[Dict[str, Any]] = []
    for st_id in sorted(by_station.keys()):
        mrows = by_station[st_id]
        total_invested = sum((m["invested_usd"] for m in mrows), _ZERO)
        total_realized = sum(
            (m["realized_pnl_usd"] for m in mrows if m["realized_pnl_usd"] is not None),
            _ZERO,
        )
        unsettled_exposure = sum((m["unsettled_exposure_usd"] for m in mrows), _ZERO)
        settled_count = sum(
            1 for m in mrows if m["settlement_status"] == "READY" and (m["has_fill"] or m["outcome"] in ("WIN", "LOSS"))
        )
        win_count = sum(1 for m in mrows if m["outcome"] == "WIN")
        cards.append(
            {
                "station_id": st_id,
                "total_invested_usd": total_invested,
                "total_realized_pnl_usd": total_realized,
                "unsettled_exposure_usd": unsettled_exposure,
                "settled_count": settled_count,
                "win_count": win_count,
                "market_rows": tuple(mrows),
            }
        )
    return tuple(cards)


def _build_daily_cumulative_pnl_series(
    settlement_rows: Sequence[Dict[str, Any]],
) -> Tuple[Dict[str, Any], ...]:
    """Build chronological cumulative realized PnL points grouped strictly by settlement date.

    Days with zero settlements are omitted without synthetic interpolation.
    """
    daily_totals: Dict[str, Decimal] = {}
    for row in settlement_rows:
        settle_day = str(row.get("settled_ts_utc") or "").strip()[:10]
        if not settle_day:
            settle_day = str(row.get("target_date") or "").strip()[:10]
        if not settle_day:
            continue
        daily_totals[settle_day] = daily_totals.get(settle_day, _ZERO) + _to_decimal(row.get("realized_pnl_usd"))

    points: List[Dict[str, Any]] = []
    running = _ZERO
    for day_str in sorted(daily_totals.keys()):
        daily_pnl = daily_totals[day_str]
        running += daily_pnl
        points.append(
            {
                "settlement_date": day_str,
                "daily_realized_pnl_usd": daily_pnl,
                "cumulative_realized_pnl_usd": running,
            }
        )
    return tuple(points)


def _filter_view_by_target_type(view: P10SessionView, target_type: Optional[str]) -> P10SessionView:
    tt = (target_type or "").strip().upper()
    if not tt or tt == "ALL":
        return view
    all_p1_ids = {str(r.get("decision_id") or "") for r in view.p1_events if r.get("decision_id")}
    p1 = tuple(r for r in view.p1_events if str(r.get("target_type") or "").upper() == tt)
    keep_ids = {str(r.get("decision_id") or "") for r in p1 if r.get("decision_id")}
    p3 = tuple(r for r in view.p3_events if str(r.get("decision_id") or "") in keep_ids or str(r.get("decision_id") or "") not in all_p1_ids)
    p17 = tuple(r for r in view.p17_snapshots if str(r.get("target_type") or "").upper() == tt)
    p9 = tuple(r for r in view.p9_events if str(r.get("target_type") or "").upper() == tt)
    chains = tuple(ch for ch in view.joined_chains if str(ch.p1_record.get("target_type") or "").upper() == tt)
    missing_fk = sum(1 for ch in chains if isinstance(ch.p1_record.get("forecast_id"), str) and not ch.p1_record["forecast_id"].startswith("MISSING") and ch.p17_record is None)
    return P10SessionView(
        execution_mode=view.execution_mode, render_status=view.render_status, tail_status=view.tail_status,
        settlement_status="READY" if p9 else "PENDING_P9", p1_events=p1, p3_events=p3,
        p12_ledgers=view.p12_ledgers, p17_snapshots=p17, p19_events=view.p19_events,
        joined_chains=chains, valid_lines=view.valid_lines, corrupt_lines=view.corrupt_lines,
        partial_tail_skipped_lines=view.partial_tail_skipped_lines, missing_forecast_fk_count=missing_fk, p9_events=p9,
    )


def _derive_latest_activity_ts(view: P10SessionView, latest_p19: Optional[Mapping[str, Any]]) -> Optional[str]:
    candidates: List[str] = []
    for seq, key in ((view.p1_events, "scan_ts_utc"), (view.p3_events, "final_ts_utc"), (view.p17_snapshots, "issue_ts_utc"), (view.p19_events, "event_ts_utc"), (view.p9_events, "settled_ts_utc")):
        for rec in seq[-20:]:
            val = rec.get(key)
            if isinstance(val, str) and val:
                candidates.append(val)
    if latest_p19 and isinstance(latest_p19.get("event_ts_utc"), str):
        candidates.append(latest_p19["event_ts_utc"])
    return max(candidates) if candidates else None


def build_m10_dashboard_model_from_view(
    *,
    view: P10SessionView,
    execution_mode: ExecutionMode = "PAPER",
    safety_config_path: Path = DEFAULT_GATEWAY_CONFIG_PATH,
    utc_date: Optional[date] = None,
    date_range: Optional[Tuple[date, date]] = None,
    model_hash: Optional[str] = None,
    model_frozen: bool = True,
    risk_panel_override: Optional[GatewayRiskPanelSnapshot] = None,
    alerts_status_path: Optional[Path] = None,
    target_type: Optional[str] = None,
    period_p1_outcomes: Optional[Mapping[str, int]] = None,
    total_p1_scanned: Optional[int] = None,
    latest_account_p19: Optional[Dict[str, Any]] = None,
) -> M10DashboardModel:
    """Build an `M10DashboardModel` from a pre-loaded `P10SessionView` (shared by CLI & live cache)."""
    scoped_view = _filter_view_by_target_type(view, target_type)
    if risk_panel_override is not None:
        risk_panel = risk_panel_override
    else:
        safety = load_gateway_safety_config(safety_config_path)
        ledger_day = utc_date or (date_range[1] if date_range is not None else datetime.now(timezone.utc).date())
        daily_used = _read_daily_used_readonly(safety.daily_ledger_path, ledger_day)
        daily_remaining = max(_ZERO, safety.max_daily_cumulative_usd - daily_used)
        circuit_open, consecutive_failures = _derive_circuit_status(scoped_view.p3_events)
        risk_panel = GatewayRiskPanelSnapshot(
            execution_mode=safety.execution_mode, max_single_order_usd=safety.max_single_order_usd,
            max_daily_cumulative_usd=safety.max_daily_cumulative_usd, daily_used_usd=daily_used,
            daily_remaining_usd=daily_remaining, circuit_open=circuit_open, consecutive_failures=consecutive_failures,
            light_status=_derive_light_status(scoped_view), model_hash=_derive_model_hash(scoped_view, model_hash),
            model_frozen=model_frozen, safety_config_sha256=safety.config_sha256,
        )
    return _assemble_dashboard_model(
        scoped_view, execution_mode, risk_panel, alerts_status_path,
        target_type, period_p1_outcomes, total_p1_scanned, latest_account_p19,
    )


def _assemble_dashboard_model(
    view: P10SessionView,
    execution_mode: ExecutionMode,
    risk_panel: GatewayRiskPanelSnapshot,
    alerts_status_path: Optional[Path],
    target_type: Optional[str],
    period_p1_outcomes: Optional[Mapping[str, int]],
    total_p1_scanned: Optional[int],
    latest_account_p19: Optional[Dict[str, Any]],
) -> M10DashboardModel:
    decision_rows = _build_decision_rows(view.joined_chains)
    settlement_rows, total_realized_pnl_usd = _build_settlement_rows(view, decision_rows)
    city_cards = _build_city_date_aggregations(decision_rows, settlement_rows)
    daily_pnl_series = _build_daily_cumulative_pnl_series(settlement_rows)
    consistency_report = evaluate_m10_consistency(view, decision_rows, settlement_rows)
    total_filled_usd = sum((row["filled_usd"] for row in decision_rows), _ZERO)
    total_fee_paid_usd = sum((row["fee_paid_usd"] for row in decision_rows), _ZERO)
    model_hashes = _unique_non_empty([risk_panel.model_hash, *(row["model_hash"] for row in decision_rows)])
    config_hashes = _unique_non_empty([*(row["config_hash"] for row in decision_rows), *(str(ev.get("config_hash") or "") for ev in view.p19_events)])
    policy_overdue_count = sum(1 for row in decision_rows if row["policy_overdue"])
    acct_p19 = latest_account_p19 or (view.p19_events[-1] if view.p19_events else None)
    return M10DashboardModel(
        execution_mode=execution_mode, render_status=view.render_status, tail_status=view.tail_status,
        settlement_status=view.settlement_status, risk_panel=risk_panel, view=view, decision_rows=decision_rows,
        settlement_rows=settlement_rows, p19_rows=view.p19_events, model_hashes=model_hashes, config_hashes=config_hashes,
        policy_overdue_count=policy_overdue_count, total_filled_usd=total_filled_usd, total_fee_paid_usd=total_fee_paid_usd,
        total_realized_pnl_usd=total_realized_pnl_usd, corrupt_count=len(view.corrupt_lines),
        partial_tail_count=view.partial_tail_skipped_lines, valid_lines=view.valid_lines,
        missing_forecast_fk_count=view.missing_forecast_fk_count, city_cards=city_cards, daily_pnl_series=daily_pnl_series,
        alerts_status=_read_alerts_status_readonly(alerts_status_path), consistency_report=consistency_report,
        period_p1_outcomes=dict(period_p1_outcomes or {}), total_p1_scanned=total_p1_scanned,
        latest_account_p19=acct_p19, latest_activity_ts_utc=_derive_latest_activity_ts(view, acct_p19),
        target_type_filter=target_type,
    )


def build_m10_dashboard_model(
    *,
    audit_root: Path,
    execution_mode: ExecutionMode = "PAPER",
    safety_config_path: Path = DEFAULT_GATEWAY_CONFIG_PATH,
    utc_date: Optional[date] = None,
    date_range: Optional[Tuple[date, date]] = None,
    session_id: Optional[str] = None,
    station_id: Optional[str] = None,
    p13_root: Optional[Path] = None,
    model_hash: Optional[str] = None,
    model_frozen: bool = True,
    risk_panel_override: Optional[GatewayRiskPanelSnapshot] = None,
    alerts_status_path: Optional[Path] = None,
    target_type: Optional[str] = None,
) -> M10DashboardModel:
    """Aggregate read-only `M7` traces, safety limits, and `M9` settlements into an `M10` model."""
    query = P10Query(execution_mode=execution_mode, date_range=date_range, session_id=session_id, station_id=station_id, target_date=None)
    view = query_p10_session_view(audit_root=audit_root, query=query, p13_root=p13_root)
    return build_m10_dashboard_model_from_view(
        view=view, execution_mode=execution_mode, safety_config_path=safety_config_path, utc_date=utc_date,
        date_range=date_range, model_hash=model_hash, model_frozen=model_frozen,
        risk_panel_override=risk_panel_override, alerts_status_path=alerts_status_path, target_type=target_type,
    )


def _render_decision_cards_section(
    model: M10DashboardModel,
    *,
    tz_mode: TimezoneMode,
    action_filter: str,
    limit: Optional[int],
    page: int = 1,
    base_params: Optional[Mapping[str, str]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    settle_by_scope = {
        (str(s.get("session_id") or ""), str(s.get("station_id") or ""), str(s.get("target_date") or ""), str(s.get("target_type") or ""), str(s.get("market_id") or "")): s
        for s in model.settlement_rows
    }
    ver_by_id = model.consistency_report.chain_verifications if model.consistency_report else {}
    all_matched = filter_and_sort_display_rows(model.decision_rows, action_filter=action_filter, limit=None)
    page_size = max(1, int(limit)) if limit is not None else None
    total_pages = max(1, (len(all_matched) + page_size - 1) // page_size) if (page_size and all_matched) else 1
    safe_page = max(1, min(total_pages, int(page)))
    shown = all_matched[(safe_page - 1) * page_size : safe_page * page_size] if page_size is not None else all_matched
    auto_open_n = len(shown) if len(shown) <= 2 else 1
    cards_html = "\n".join(
        render_decision_story_card(
            r,
            settle_by_scope.get((str(r.get("session_id") or ""), str(r.get("station_id") or ""), str(r.get("target_date") or ""), str(r.get("target_type") or ""), str(r.get("market_id") or ""))),
            ver_by_id.get(str(r.get("decision_id") or "")),
            tz_mode=tz_mode,
            default_open=(idx < auto_open_n),
        )
        for idx, r in enumerate(shown)
    ) or '<div class="empty">当前筛选条件下暂无符合的决策或成交记录。</div>'
    pager = render_pagination_bar(base_params, page=safe_page, total_pages=total_pages, total_items=len(all_matched), anchor="#decision-story-list")
    header = (
        f'<h2>委托单与决策原因流水 (第 {safe_page}/{total_pages} 页 · 本页 {len(shown)} / 共 {len(all_matched)} 条 · 已成交优先置顶)</h2>'
        '<p class="note-muted">点开任意卡片可顺推或反推 6 步因果链条（①预测 P17 → ②盘口 P13 → ③决策 P1 → ④撮合 P3 → ⑤账本 P19 → ⑥结算 P9）。</p>'
    )
    return f'<section id="decision-story-list" class="card" aria-label="委托单与决策原因流水">{header}{pager}{cards_html}{pager}</section>', shown


def render_decision_detail_html(
    model: M10DashboardModel,
    decision_id: str,
    *,
    tz_mode: TimezoneMode = "both",
    back_url: str = "/",
) -> str:
    """Render standalone zero-script read-only popup detail page for a single decision."""
    rp = model.risk_panel
    is_live = rp.execution_mode == "LIVE"
    banner_class = "mode-banner-live" if is_live else "mode-banner-paper"
    banner_label = "LIVE REAL-MONEY EXECUTION" if is_live else "PAPER SIMULATION MODE (READ-ONLY)"
    row = next((r for r in model.decision_rows if str(r.get("decision_id") or "") == decision_id), None)
    if row is None:
        inner = (
            f'<div class="card"><h2>未找到该订单/决策记录</h2>'
            f'<p class="muted">decision_id=<code>{esc(decision_id)}</code> 未在当前查询范围内命中。</p>'
            f'<a href="{esc(back_url)}" class="pill pill-active">← 返回监控主页</a></div>'
        )
    else:
        settle_by_scope = {
            (str(s.get("session_id") or ""), str(s.get("station_id") or ""), str(s.get("target_date") or ""), str(s.get("target_type") or ""), str(s.get("market_id") or "")): s
            for s in model.settlement_rows
        }
        s_key = (str(row.get("session_id") or ""), str(row.get("station_id") or ""), str(row.get("target_date") or ""), str(row.get("target_type") or ""), str(row.get("market_id") or ""))
        ver = model.consistency_report.chain_verifications.get(decision_id) if model.consistency_report else None
        card_html = render_decision_story_card(row, settle_by_scope.get(s_key), ver, tz_mode=tz_mode, default_open=True)
        inner = (
            '<div class="card ticker-bar" aria-label="风险参数面板">'
            f'<div><strong>单笔因果全链路详情</strong> · <code>{esc(decision_id)}</code></div>'
            f'<div><a href="{esc(back_url)}" class="pill pill-active">← 返回监控主页</a></div></div>'
            f'<div class="card">{card_html}</div>'
        )
    return (
        '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8" />\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
        f'<title>M10 Order Detail - {esc(decision_id)}</title>\n'
        f'<style>{build_light_stylesheet(is_live)}</style>\n</head>\n<body>\n'
        f'<div class="{banner_class}">EXECUTION MODE: {esc(rp.execution_mode)} — {esc(banner_label)}</div>\n'
        f'<div class="wrap">{inner}</div>\n</body>\n</html>\n'
    )


def _build_orders_and_cards_blocks(
    model: M10DashboardModel,
    *,
    tz_mode: TimezoneMode,
    action_filter: str,
    limit: Optional[int],
    page: int,
    base_params: Optional[Mapping[str, str]],
) -> Tuple[str, str, List[Dict[str, Any]]]:
    page_size = max(1, int(limit)) if limit is not None else None
    if base_params is not None:
        orders_block, shown_rows = render_unified_orders_table(
            model, tz_mode, action_filter=action_filter, page=page, page_size=page_size, base_params=base_params
        )
        return orders_block, "", shown_rows
    cards_section, shown_rows = _render_decision_cards_section(
        model, tz_mode=tz_mode, action_filter=action_filter, limit=limit, page=page, base_params=None
    )
    shown_ids = {str(r.get("decision_id") or "") for r in shown_rows}
    orders_block = render_recent_filled_table(model, tz_mode, page=page, page_size=page_size, base_params=None, shown_ids=shown_ids)
    return orders_block, cards_section, shown_rows


def render_m10_dashboard_html(
    model: M10DashboardModel,
    *,
    live_head_meta_html: str = "",
    live_controls_html: str = "",
    live_poll_script_html: str = "",
    tz_mode: TimezoneMode = "both",
    action_filter: str = "all",
    limit: Optional[int] = None,
    page: int = 1,
    live_meta: Optional[Mapping[str, Any]] = None,
) -> str:
    """Render a zero-CDN, strictly read-only light-mode `M10` dashboard."""
    rp = model.risk_panel
    is_live = rp.execution_mode == "LIVE"
    banner_class = "mode-banner-live" if is_live else "mode-banner-paper"
    banner_label = "LIVE REAL-MONEY EXECUTION" if is_live else "PAPER SIMULATION MODE (READ-ONLY)"
    base_params = (live_meta or {}).get("base_params") if isinstance(live_meta, Mapping) else None
    orders_block, cards_section, shown_rows = _build_orders_and_cards_blocks(
        model, tz_mode=tz_mode, action_filter=action_filter, limit=limit, page=page, base_params=base_params
    )
    city_section = (
        '<section class="card" aria-label="城市与日期独立盘口聚合"><h2>分城市持仓与独立盘口 (含站点当地时间 · 点击展开明细)</h2>'
        '<p class="note-muted">每日/每盘口独立结算核算，城市汇总不做跨盘口概率平均。</p>'
        f'{render_city_holdings_card(model.city_cards, tz_mode)}</section>'
    )
    pnl_section = (
        '<section class="card" aria-label="按结算日累计盈亏曲线"><h2>累计已实现盈亏走势 (按结算日 · 零插值)</h2>'
        f'{render_light_daily_pnl_svg(model.daily_pnl_series)}</section>'
    )
    body = (
        f'<div class="{banner_class}">EXECUTION MODE: {esc(rp.execution_mode)} — {esc(banner_label)}</div>'
        f'<div id="m10-live-root" class="wrap">{render_top_ticker_bar(model, live_meta, tz_mode)}'
        f'{render_portfolio_kpis(model, live_meta)}{live_controls_html}'
        f'{orders_block}{city_section}{pnl_section}'
        f'{cards_section}{render_consistency_panel_html(model.consistency_report)}'
        f'{render_audit_drawers(model, shown_rows, tz_mode)}</div>'
    )
    return (
        '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8" />\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
        f'{live_head_meta_html}\n<title>M10 Read-Only Trading Monitor</title>\n'
        f'<style>{build_light_stylesheet(is_live)}</style>\n</head>\n<body>\n{body}\n{live_poll_script_html}\n</body>\n</html>\n'
    )
