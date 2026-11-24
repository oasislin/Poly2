"""Strictly read-only `M10 v1` view aggregator and static HTML renderer (`S3-10`)."""

from __future__ import annotations

from dataclasses import dataclass
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


def _read_alerts_status_readonly(alerts_status_path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if alerts_status_path is None or not alerts_status_path.exists():
        return None
    try:
        with alerts_status_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _render_watchdog_badge_strip(alerts_status: Optional[Mapping[str, Any]]) -> str:
    if not alerts_status:
        return ""
    checks = alerts_status.get("checks") if isinstance(alerts_status.get("checks"), Mapping) else {}
    overall = str(alerts_status.get("overall_severity") or "UNKNOWN")
    checked_ts = str(alerts_status.get("checked_ts_utc") or "-")
    pills = []
    for name in ("gap_rate", "corrupt_lines", "token_coverage", "disk_watchdog"):
        st = str((checks.get(name) or {}).get("status") or "UNKNOWN") if isinstance(checks.get(name), Mapping) else "UNKNOWN"
        cls = "pill-ready" if st == "OK" else ("pill-pending" if st == "WARN" else "pill-loss")
        pills.append(f'<span class="pill {cls}">{_esc(name)}: {_esc(st)}</span>')
    return (
        '<div class="kv"><div class="k">watchdog_summary (read-only)</div>'
        f'<div class="v">{_esc(overall)} ({_esc(checked_ts)})<br/>'
        f"{' '.join(pills)}</div></div>"
    )


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
) -> M10DashboardModel:
    """Aggregate read-only `M7` traces, safety limits, and `M9` settlements into an `M10` model."""
    query = P10Query(
        execution_mode=execution_mode,
        date_range=date_range,
        session_id=session_id,
        station_id=station_id,
        target_date=None,
    )
    view = query_p10_session_view(audit_root=audit_root, query=query, p13_root=p13_root)

    if risk_panel_override is not None:
        risk_panel = risk_panel_override
    else:
        safety = load_gateway_safety_config(safety_config_path)
        ledger_day = utc_date or (date_range[1] if date_range is not None else datetime.now(timezone.utc).date())
        daily_used = _read_daily_used_readonly(safety.daily_ledger_path, ledger_day)
        daily_remaining = max(_ZERO, safety.max_daily_cumulative_usd - daily_used)
        circuit_open, consecutive_failures = _derive_circuit_status(view.p3_events)
        resolved_model_hash = _derive_model_hash(view, model_hash)
        risk_panel = GatewayRiskPanelSnapshot(
            execution_mode=safety.execution_mode,
            max_single_order_usd=safety.max_single_order_usd,
            max_daily_cumulative_usd=safety.max_daily_cumulative_usd,
            daily_used_usd=daily_used,
            daily_remaining_usd=daily_remaining,
            circuit_open=circuit_open,
            consecutive_failures=consecutive_failures,
            light_status=_derive_light_status(view),
            model_hash=resolved_model_hash,
            model_frozen=model_frozen,
            safety_config_sha256=safety.config_sha256,
        )

    decision_rows = _build_decision_rows(view.joined_chains)
    settlement_rows, total_realized_pnl_usd = _build_settlement_rows(view, decision_rows)
    city_cards = _build_city_date_aggregations(decision_rows, settlement_rows)
    daily_pnl_series = _build_daily_cumulative_pnl_series(settlement_rows)

    total_filled_usd = sum((row["filled_usd"] for row in decision_rows), _ZERO)
    total_fee_paid_usd = sum((row["fee_paid_usd"] for row in decision_rows), _ZERO)
    model_hashes = _unique_non_empty(
        [risk_panel.model_hash, *(row["model_hash"] for row in decision_rows)]
    )
    config_hashes = _unique_non_empty(
        [
            *(row["config_hash"] for row in decision_rows),
            *(str(ev.get("config_hash") or "") for ev in view.p19_events),
        ]
    )
    policy_overdue_count = sum(1 for row in decision_rows if row["policy_overdue"])

    return M10DashboardModel(
        execution_mode=execution_mode,
        render_status=view.render_status,
        tail_status=view.tail_status,
        settlement_status=view.settlement_status,
        risk_panel=risk_panel,
        view=view,
        decision_rows=decision_rows,
        settlement_rows=settlement_rows,
        p19_rows=view.p19_events,
        model_hashes=model_hashes,
        config_hashes=config_hashes,
        policy_overdue_count=policy_overdue_count,
        total_filled_usd=total_filled_usd,
        total_fee_paid_usd=total_fee_paid_usd,
        total_realized_pnl_usd=total_realized_pnl_usd,
        corrupt_count=len(view.corrupt_lines),
        partial_tail_count=view.partial_tail_skipped_lines,
        valid_lines=view.valid_lines,
        missing_forecast_fk_count=view.missing_forecast_fk_count,
        city_cards=city_cards,
        daily_pnl_series=daily_pnl_series,
        alerts_status=_read_alerts_status_readonly(alerts_status_path),
    )


def _esc(val: Any) -> str:
    return html.escape("-" if val is None else str(val), quote=True)


def _fmt_cell(val: Any, *, prefix: str = "", suffix: str = "") -> str:
    if val is None or val == "":
        return _esc(_UNPERSISTED)
    return _esc(f"{prefix}{val}{suffix}")


def _render_bin_distribution_html(dist_bins: Sequence[Mapping[str, Any]]) -> str:
    if not dist_bins:
        return f'<div class="empty">{_esc(_UNPERSISTED)} (P17.bin_probs 缺失)</div>'
    items: List[str] = []
    for b in dist_bins:
        p_raw = b.get("p_model")
        try:
            pct = max(0.0, min(100.0, float(p_raw) * 100.0)) if p_raw is not None else 0.0
            pct_label = f"{pct:.2f}%"
        except Exception:
            pct = 0.0
            pct_label = _UNPERSISTED
        cls = "bin-row bin-picked" if b.get("is_selected") else "bin-row"
        tags = []
        if b.get("is_selected"):
            tags.append("★选中")
        if b.get("is_dead_bin"):
            tags.append("DEAD")
        if b.get("is_boundary_bin"):
            tags.append("BOUNDARY")
        tag_txt = f" [{' · '.join(tags)}]" if tags else ""
        items.append(
            f'<div class="{cls}">'
            f'<span class="bin-lbl">{_esc(b.get("label"))}{_esc(tag_txt)}</span>'
            f'<span class="bin-bar"><span class="bin-fill" style="width:{pct:.1f}%"></span></span>'
            f'<span class="bin-pct">{_esc(pct_label)}</span>'
            "</div>"
        )
    return '<div class="bin-bar-list">' + "".join(items) + "</div>"


def _render_decision_chain_card(
    row: Mapping[str, Any],
    settle_row: Optional[Mapping[str, Any]],
) -> str:
    w = row.get("weather_stage") or {}
    pe = row.get("prob_edge_stage") or {}
    sz = row.get("sizing_stage") or {}
    p13 = row.get("p13_book_stage")
    dist_html = _render_bin_distribution_html(row.get("distribution_bins") or ())

    if p13:
        asks_txt = ", ".join(f"{lvl[0]}×{lvl[1]}" for lvl in p13.get("asks_top3", ())) or _UNPERSISTED
        bids_txt = ", ".join(f"{lvl[0]}×{lvl[1]}" for lvl in p13.get("bids_top3", ())) or _UNPERSISTED
        p13_body = (
            f"<div>frame={_fmt_cell(p13.get('frame_seq'))} | src={_fmt_cell(p13.get('data_source'))} "
            f"| side={_esc(p13.get('single_side') or 'two_sided')}</div>"
            f"<div>asks_top3: <code>{_esc(asks_txt)}</code> | bids_top3: <code>{_esc(bids_txt)}</code></div>"
            f"<div>fee_rate={_fmt_cell(p13.get('fee_rate'))} | min_shares={_fmt_cell(p13.get('min_order_size_shares'))}</div>"
        )
    else:
        p13_body = f"<div>P13 盘口帧: {_esc(_UNPERSISTED)} (或未传 --p13-root)</div>"

    if settle_row is not None:
        p9_body = (
            f"<div>settlement_id: <code>{_esc(settle_row.get('settlement_id'))}</code></div>"
            f"<div>winning_bin_id=<strong>{_esc(settle_row.get('winning_bin_id'))}</strong> "
            f"| settled_temp_f_int={_fmt_cell(settle_row.get('settled_temp_f_int'), suffix=' °F')} "
            f"| oracle={_esc(settle_row.get('oracle_source'))}</div>"
            f"<div>payout=${_esc(settle_row.get('payout_usd'))} - cost=${_esc(settle_row.get('cost_basis_usd'))} "
            f"= <strong>realized_pnl=${_esc(settle_row.get('realized_pnl_usd'))}</strong></div>"
        )
    else:
        p9_body = f"<div>结算状态: PENDING_P9 ({_esc(_UNPERSISTED)})</div>"

    replay_mode = row.get("capture_replay_mode")
    replay_suffix = f" | mode={_esc(replay_mode)}" if replay_mode else ""
    return (
        '<details class="chain-card" open>'
        f"<summary><code>{_esc(row['decision_id'])}</code> | {_esc(row['station_id'])} "
        f"{_esc(row['target_date'])} ({_esc(row.get('target_type') or '-')}) | "
        f"bin=<strong>{_esc(row['bin_id'])}</strong> | {_esc(row['decision_outcome'])} "
        f"| terminal={_esc(row['terminal_status'])} | filled=${_esc(row['filled_usd'])}{replay_suffix}</summary>"
        '<div class="stage-grid">'
        '<div class="stage-box">'
        "<h3>① 决策时点天气 (P17 · 非 P9 结算真值)</h3>"
        f"<div>瞬时观测温: {_fmt_cell(w.get('latest_obs_temp_f'), suffix=' °F')} "
        f"(@ {_fmt_cell(w.get('latest_obs_ts_utc'))}, 源={_fmt_cell(w.get('obs_source_mode'))})</div>"
        f"<div>日内极值 m_now: {_fmt_cell(w.get('m_now_f'), suffix=' °F')} (int={_fmt_cell(w.get('m_now_int_f'))}) "
        f"| bridge={_fmt_cell(w.get('is_bridge_active'))} | fresh={_fmt_cell(w.get('upstream_obs_fresh'))}</div>"
        f"<div>先验: family={_fmt_cell(w.get('family'))}, mu0={_fmt_cell(w.get('prior_mu0'))}, "
        f"sigma0={_fmt_cell(w.get('prior_sigma0'))}, lead={_fmt_cell(w.get('gefs_lead_hours'), suffix='h')}, "
        f"tau={_fmt_cell(w.get('tau_hours'), suffix='h')}</div>"
        "</div>"
        '<div class="stage-box">'
        "<h3>② 模型全档分布 (P17.bin_probs · 所选档高亮)</h3>"
        f"{dist_html}"
        "</div>"
        '<div class="stage-box">'
        "<h3>③ 所选档概率与 I 值 / 边际优势</h3>"
        f"<div>selected_bin_p_model={_fmt_cell(pe.get('selected_bin_p_model'))} "
        f"| best_ask_price={_fmt_cell(pe.get('best_ask_price'))}</div>"
        f"<div>I值 (net_ev / i_value)={_fmt_cell(pe.get('i_value'))} "
        f"| q_eff={_fmt_cell(pe.get('best_ask_q_eff'))} | fee_rate={_fmt_cell(pe.get('applied_fee_rate'))}</div>"
        f"<div>best_ask_edge={_fmt_cell(pe.get('best_ask_edge'))} vs m_threshold={_fmt_cell(pe.get('m_threshold'))}</div>"
        "</div>"
        '<div class="stage-box">'
        "<h3>④ 仓位公式与三段裁剪对照 (1:N 聚合)</h3>"
        f"<div>B=${_fmt_cell(sz.get('b_budget_usd'))} × w(τ)={_fmt_cell(sz.get('w_tau'))} "
        f"× [s(edge)={_fmt_cell(sz.get('s_edge'))} × λ(L)={_fmt_cell(sz.get('lambda_l'))}] "
        f"= G=${_fmt_cell(sz.get('g_cap_usd'))}</div>"
        f"<div>G=${_fmt_cell(sz.get('g_cap_usd'))} →[Δ_G→D=${_fmt_cell(sz.get('delta_g_to_d'))}]→ "
        f"D=${_fmt_cell(sz.get('headroom_d'))} →[Δ_D→slice=${_fmt_cell(sz.get('delta_d_to_slice'))}]→ "
        f"slice=${_fmt_cell(sz.get('target_slice_usd'))} →[Δ_slice→fill=${_fmt_cell(sz.get('delta_slice_to_fill'))}]→ "
        f"filled=${_esc(sz.get('filled_usd'))} (attempts={_esc(row.get('attempt_count'))}, fee=${_esc(sz.get('fee_paid_usd'))})</div>"
        f"<div>b_eff_headroom=${_fmt_cell(sz.get('b_eff_headroom_usd'))} | pov_cap=${_fmt_cell(sz.get('pov_cap_usd'))} "
        f"| reject_reason={_fmt_cell(sz.get('reject_reason'))}</div>"
        "</div>"
        '<div class="stage-box">'
        "<h3>⑤ CLOB 盘口快照与 LIVE 修正预留</h3>"
        f"{p13_body}"
        '<div class="reserved-live-slot">LIVE 深度修正终注：未落盘 / 预留槽（待 S3-15 LIVE 轨启用，当前 PAPER 不解冻）</div>'
        "</div>"
        '<div class="stage-box">'
        "<h3>⑥ M9 结算回填关联 (P9)</h3>"
        f"{p9_body}"
        "</div>"
        "</div>"
        "</details>"
    )


def _render_city_aggregation_cards(city_cards: Sequence[Mapping[str, Any]]) -> str:
    if not city_cards:
        return '<div class="empty">暂无城市/日期盘口聚合数据。</div>'
    blocks: List[str] = []
    for city in city_cards:
        day_blocks: List[str] = []
        for mrow in city.get("market_rows", ()):
            pnl_text = (
                f"${mrow['realized_pnl_usd']}"
                if mrow.get("realized_pnl_usd") is not None
                else "-"
            )
            status_cls = "pill-ready" if mrow.get("settlement_status") == "READY" else "pill-pending"
            outcome = str(mrow.get("outcome") or "-")
            if outcome == "WIN":
                out_cls = "pill-win"
            elif outcome == "LOSS":
                out_cls = "pill-loss"
            else:
                out_cls = "pill-empty"
            empty_tag = (
                ' <span class="pill pill-empty">空盘口（有决策未成交）</span>'
                if mrow.get("is_empty_market")
                else ""
            )
            split_tag = (
                ' <span class="pill pill-split">同日多盘口独立核算</span>'
                if mrow.get("multi_market_same_day")
                else ""
            )
            decs = ", ".join(str(x) for x in mrow.get("decision_ids", ())) or "-"
            day_blocks.append(
                '<details class="market-day-card">'
                "<summary>"
                f"{_esc(mrow.get('target_date'))} | "
                f"{_esc(mrow.get('target_type') or '-')} | "
                f"<code>{_esc(mrow.get('market_id') or '-')}</code> | "
                f"投入(含费): ${_esc(mrow.get('invested_usd'))} | "
                f"已结算盈亏: {_esc(pnl_text)} | "
                f"未结算敞口: ${_esc(mrow.get('unsettled_exposure_usd'))} | "
                f'<span class="pill {status_cls}">{_esc(mrow.get("settlement_status"))}</span> '
                f'<span class="pill {out_cls}">{_esc(outcome)}</span>'
                f"{empty_tag}{split_tag}"
                "</summary>"
                '<div class="market-day-detail">'
                f"session=<code>{_esc(mrow.get('session_id') or '-')}</code> | "
                f"决策数={_esc(mrow.get('decision_count'))} (成交={_esc(mrow.get('filled_decision_count'))}) | "
                f"decisions=<code>{_esc(decs)}</code> | "
                f"winning_bin={_esc(mrow.get('winning_bin_id') or '-')} | "
                f"settlement_id=<code>{_esc(mrow.get('settlement_id') or '-')}</code>"
                "</div>"
                "</details>"
            )
        blocks.append(
            '<details class="city-card" open>'
            "<summary>"
            f"<strong>{_esc(city.get('station_id'))}</strong> | "
            f"累计投入(含费): ${_esc(city.get('total_invested_usd'))} | "
            f"累计已结算盈亏: ${_esc(city.get('total_realized_pnl_usd'))} | "
            f"未结算敞口: ${_esc(city.get('unsettled_exposure_usd'))} | "
            f"已结算单数/胜场: {_esc(city.get('settled_count'))} / {_esc(city.get('win_count'))}"
            "</summary>"
            '<div class="city-card-body">'
            + "\n".join(day_blocks)
            + "</div>"
            "</details>"
        )
    return "\n".join(blocks)


def _render_daily_pnl_svg(series: Sequence[Mapping[str, Any]]) -> str:
    if not series:
        return '<div class="empty">暂无已结算数据，按结算日累计盈亏 SVG 曲线如实留空。</div>'

    width, height = 760, 220
    pad_l, pad_r, pad_t, pad_b = 72, 24, 20, 38
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    parsed_dates: List[Optional[date]] = []
    for pt in series:
        try:
            parsed_dates.append(date.fromisoformat(str(pt["settlement_date"])))
        except Exception:
            parsed_dates.append(None)

    y_vals = [float(pt["cumulative_realized_pnl_usd"]) for pt in series]
    min_y = min(0.0, min(y_vals))
    max_y = max(0.0, max(y_vals))
    if max_y - min_y < 1e-9:
        min_y -= 1.0
        max_y += 1.0
    else:
        margin = (max_y - min_y) * 0.12
        min_y -= margin
        max_y += margin

    def _y_px(val: float) -> float:
        ratio = (val - min_y) / (max_y - min_y)
        return pad_t + plot_h * (1.0 - ratio)

    valid_days = [d for d in parsed_dates if d is not None]
    use_calendar_spacing = len(valid_days) == len(series) and len(series) > 1
    if use_calendar_spacing:
        d0 = valid_days[0]
        span_days = max(1, (valid_days[-1] - d0).days)
        x_coords = [
            pad_l + plot_w * ((d - d0).days / span_days)  # type: ignore[operator]
            for d in valid_days
        ]
    elif len(series) == 1:
        x_coords = [pad_l + plot_w * 0.5]
    else:
        x_coords = [pad_l + plot_w * (idx / (len(series) - 1)) for idx in range(len(series))]

    y_coords = [_y_px(val) for val in y_vals]
    zero_y = _y_px(0.0)
    poly_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(x_coords, y_coords))

    ticks = [max_y, 0.0, min_y] if min_y < 0.0 < max_y else [max_y, (max_y + min_y) / 2.0, min_y]
    y_tick_svg = "\n".join(
        f'<line x1="{pad_l}" y1="{_y_px(tv):.1f}" x2="{width - pad_r}" y2="{_y_px(tv):.1f}" '
        f'stroke="{"#64748b" if abs(tv) < 1e-9 else "#334155"}" '
        f'stroke-dasharray="{"4 4" if abs(tv) < 1e-9 else "2 4"}" stroke-width="1" />'
        f'<text x="{pad_l - 8}" y="{_y_px(tv) + 4:.1f}" text-anchor="end" fill="#94a3b8" font-size="11">${tv:.2f}</text>'
        for tv in ticks
    )

    circles_svg = "\n".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" '
        f'fill="{"#4ade80" if float(pt["cumulative_realized_pnl_usd"]) >= 0 else "#f87171"}" '
        f'stroke="#0f172a" stroke-width="1.5" '
        f'data-settlement-date="{_esc(pt["settlement_date"])}" '
        f'data-cumulative-pnl="{_esc(pt["cumulative_realized_pnl_usd"])}" />'
        f'<text x="{x:.1f}" y="{height - 14}" text-anchor="middle" fill="#cbd5e1" font-size="11">'
        f'{_esc(pt["settlement_date"])}</text>'
        f'<text x="{x:.1f}" y="{max(pad_t + 10, y - 9):.1f}" text-anchor="middle" fill="#f8fafc" font-size="10">'
        f'${_esc(pt["cumulative_realized_pnl_usd"])}</text>'
        for pt, x, y in zip(series, x_coords, y_coords)
    )

    polyline_svg = (
        f'<polyline fill="none" stroke="#38bdf8" stroke-width="2.5" points="{poly_points}" />'
        if len(series) >= 2
        else ""
    )

    return (
        f'<svg class="pnl-svg" viewBox="0 0 {width} {height}" width="100%" '
        'role="img" aria-label="按结算日累计已实现盈亏曲线">'
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{height - pad_b}" stroke="#64748b" stroke-width="1.2" />'
        f'<line x1="{pad_l}" y1="{height - pad_b}" x2="{width - pad_r}" y2="{height - pad_b}" stroke="#64748b" stroke-width="1.2" />'
        f"{y_tick_svg}"
        f'<line x1="{pad_l}" y1="{zero_y:.1f}" x2="{width - pad_r}" y2="{zero_y:.1f}" stroke="#94a3b8" stroke-dasharray="4 4" stroke-width="1" />'
        f"{polyline_svg}"
        f"{circles_svg}"
        "</svg>"
    )


def render_m10_dashboard_html(model: M10DashboardModel) -> str:
    """Render a zero-script, zero-CDN, strictly read-only `M10 v1` standalone HTML report."""
    rp = model.risk_panel
    is_live = rp.execution_mode == "LIVE"
    banner_class = "mode-banner-live" if is_live else "mode-banner-paper"
    banner_css = (
        ".mode-banner-live { background: #b91c1c; color: #ffffff; padding: 14px 24px; "
        "font-weight: 700; font-size: 18px; letter-spacing: 0.04em; border-bottom: 3px solid #ef4444; }"
        if is_live
        else ".mode-banner-paper { background: #475569; color: #f8fafc; padding: 14px 24px; "
        "font-weight: 700; font-size: 18px; letter-spacing: 0.04em; border-bottom: 3px solid #64748b; }"
    )
    banner_label = "LIVE REAL-MONEY EXECUTION" if is_live else "PAPER SIMULATION MODE (READ-ONLY)"
    circuit_text = "OPEN" if rp.circuit_open else "CLOSED"
    light_text = rp.light_status or "UNSET"
    frozen_text = "FROZEN" if rp.model_frozen else "UNFROZEN"

    decision_trs = "\n".join(
        (
            "<tr>"
            f"<td><code>{_esc(r['decision_id'])}</code></td>"
            f"<td>{_esc(r['scan_ts_utc'])}</td>"
            f"<td>{_esc(r['station_id'])}</td>"
            f"<td>{_esc(r['target_date'])}</td>"
            f"<td>{_esc(r['bin_id'])}</td>"
            f"<td>{_esc(r['decision_outcome'])}</td>"
            f"<td><code>{_esc(r['model_hash'])}</code></td>"
            f"<td><code>{_esc(r['config_hash'])}</code></td>"
            f"<td>{'YES' if r['policy_overdue'] else 'NO'}</td>"
            f"<td><code>{_esc(r['forecast_id'])}</code></td>"
            f"<td>{_esc(r['book_frame_ref'])}</td>"
            f"<td>{_esc(r['terminal_status'])}</td>"
            f"<td>{_esc(r['filled_shares'])}</td>"
            f"<td>{_esc(r['filled_usd'])}</td>"
            f"<td>{_esc(r['fee_paid_usd'])}</td>"
            f"<td>{_esc(r['gateway_stages'])}</td>"
            "</tr>"
        )
        for r in model.decision_rows
    )
    if not decision_trs:
        decision_trs = '<tr><td colspan="16" class="empty">No P1->P3 joined decision traces found.</td></tr>'

    settle_by_scope = {
        (
            str(s.get("session_id") or ""),
            str(s.get("station_id") or ""),
            str(s.get("target_date") or ""),
            str(s.get("target_type") or ""),
            str(s.get("market_id") or ""),
        ): s
        for s in model.settlement_rows
    }
    decision_chain_cards = "\n".join(
        _render_decision_chain_card(
            r,
            settle_by_scope.get(
                (
                    str(r.get("session_id") or ""),
                    str(r.get("station_id") or ""),
                    str(r.get("target_date") or ""),
                    str(r.get("target_type") or ""),
                    str(r.get("market_id") or ""),
                )
            ),
        )
        for r in model.decision_rows
    )
    if not decision_chain_cards:
        decision_chain_cards = '<div class="empty">暂无决策链记录。</div>'

    settlement_trs = "\n".join(
        (
            "<tr>"
            f"<td><code>{_esc(r['settlement_id'])}</code></td>"
            f"<td>{_esc(r['station_id'])}</td>"
            f"<td>{_esc(r['target_date'])}</td>"
            f"<td>{_esc(r['target_type'])}</td>"
            f"<td><code>{_esc(r['market_id'])}</code></td>"
            f"<td><strong>{_esc(r['winning_bin_id'])}</strong></td>"
            f"<td>{_esc(r['settled_temp_f_int'])} °F</td>"
            f"<td>{_esc(r['oracle_source'])} ({_esc(r['oracle_source_tier'])})</td>"
            f"<td>{'YES' if r['fallback_to_lowest_bin'] else 'NO'}</td>"
            f"<td>{'YES' if r['reconciled'] else 'NO'}</td>"
            f"<td>{_esc(r['realized_pnl_usd'])}</td>"
            "</tr>"
        )
        for r in model.settlement_rows
    )
    if not settlement_trs:
        settlement_trs = (
            '<tr><td colspan="11" class="empty">'
            f"Settlement Status: {_esc(model.settlement_status)} (awaiting P9 settlement truth records)."
            "</td></tr>"
        )

    p19_trs = "\n".join(
        (
            "<tr>"
            f"<td><code>{_esc(ev.get('event_id'))}</code></td>"
            f"<td>{_esc(ev.get('event_ts_utc'))}</td>"
            f"<td>{_esc(ev.get('event_type'))}</td>"
            f"<td>{_esc(ev.get('station_id'))}</td>"
            f"<td>{_esc(ev.get('light_status'))}</td>"
            f"<td>{_esc(ev.get('free_usd_after'))}</td>"
            f"<td>{_esc(ev.get('active_locked_usd_after'))}</td>"
            f"<td>{_esc(ev.get('station_realized_pnl_usd'))}</td>"
            f"<td>{_esc(ev.get('reason'))}</td>"
            "</tr>"
        )
        for ev in model.p19_rows
    )
    if not p19_trs:
        p19_trs = '<tr><td colspan="9" class="empty">No P19 capital events recorded.</td></tr>'

    city_cards_html = _render_city_aggregation_cards(model.city_cards)
    daily_pnl_svg_html = _render_daily_pnl_svg(model.daily_pnl_series)
    watchdog_summary_html = _render_watchdog_badge_strip(model.alerts_status)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>M10 v1 Read-Only Monitor &amp; Settlement Reconciliation</title>
<style>
  :root {{ --bg: #0f172a; --panel: #1e293b; --border: #334155; --text: #e2e8f0; --muted: #94a3b8; }}
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; }}
  {banner_css}
  .wrap {{ max-width: 1360px; margin: 0 auto; padding: 20px 24px 40px; }}
  .card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px 20px; margin-bottom: 18px; }}
  h1, h2 {{ margin: 0 0 12px; font-size: 16px; color: #f8fafc; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }}
  .kv {{ background: #0f172a; border: 1px solid var(--border); border-radius: 6px; padding: 10px 12px; }}
  .kv .k {{ font-size: 12px; color: var(--muted); text-transform: uppercase; }}
  .kv .v {{ font-size: 15px; font-weight: 600; word-break: break-all; margin-top: 2px; }}
  .badge-open {{ color: #fca5a5; }}
  .badge-closed {{ color: #86efac; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ border-bottom: 1px solid var(--border); padding: 8px 10px; text-align: left; vertical-align: top; }}
  th {{ color: var(--muted); font-weight: 600; background: #0f172a; }}
  .empty {{ color: var(--muted); text-align: center; padding: 16px; }}
  code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: #93c5fd; }}
  details.chain-card {{ background: #0f172a; border: 1px solid var(--border); border-radius: 6px; padding: 10px 14px; margin-top: 12px; }}
  details.chain-card summary {{ cursor: pointer; font-weight: 600; font-size: 13px; color: #e2e8f0; }}
  .stage-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 10px; margin-top: 10px; }}
  .stage-box {{ background: #1e293b; border: 1px solid var(--border); border-radius: 6px; padding: 10px 12px; font-size: 12px; }}
  .stage-box h3 {{ margin: 0 0 6px; font-size: 13px; color: #cbd5e1; }}
  .bin-bar-list {{ display: flex; flex-direction: column; gap: 4px; }}
  .bin-row {{ display: grid; grid-template-columns: 150px 1fr 56px; align-items: center; gap: 8px; padding: 2px 4px; border-radius: 4px; }}
  .bin-picked {{ background: rgba(59, 130, 246, 0.22); border: 1px solid #60a5fa; font-weight: 700; }}
  .bin-bar {{ height: 8px; background: #0f172a; border-radius: 4px; overflow: hidden; display: block; }}
  .bin-fill {{ height: 100%; background: #38bdf8; display: block; }}
  .bin-picked .bin-fill {{ background: #fbbf24; }}
  .bin-pct {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .reserved-live-slot {{ margin-top: 6px; padding: 4px 8px; border-radius: 4px; background: #334155; color: #94a3b8; font-style: italic; }}
  details.city-card {{ background: #0f172a; border: 1px solid var(--border); border-radius: 6px; padding: 10px 14px; margin-top: 10px; }}
  details.city-card > summary {{ cursor: pointer; font-size: 14px; color: #f8fafc; }}
  .city-card-body {{ margin-top: 8px; padding-left: 14px; border-left: 2px solid #334155; }}
  details.market-day-card {{ background: #1e293b; border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; margin-top: 6px; }}
  details.market-day-card > summary {{ cursor: pointer; font-size: 13px; color: #e2e8f0; }}
  .market-day-detail {{ margin-top: 6px; font-size: 12px; color: #94a3b8; }}
  .pill {{ display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 11px; font-weight: 600; }}
  .pill-ready {{ background: #14532d; color: #bbf7d0; }}
  .pill-pending {{ background: #78350f; color: #fde68a; }}
  .pill-win {{ background: #166534; color: #86efac; }}
  .pill-loss {{ background: #7f1d1d; color: #fecaca; }}
  .pill-empty {{ background: #334155; color: #cbd5e1; }}
  .pill-split {{ background: #1e3a8a; color: #bfdbfe; }}
  .pnl-svg {{ max-width: 760px; height: auto; background: #0f172a; border: 1px solid var(--border); border-radius: 6px; display: block; }}
  .note-muted {{ font-size: 12px; color: var(--muted); margin: 0 0 8px; }}
</style>
</head>
<body>
  <div class="{banner_class}">
    EXECUTION MODE: {_esc(rp.execution_mode)} — {_esc(banner_label)}
  </div>
  <div class="wrap">
    <section class="card" aria-label="风险参数面板">
      <h2>风险参数面板 (Read-Only Gateway &amp; Risk Snapshot)</h2>
      <div class="grid">
        <div class="kv"><div class="k">execution_mode</div><div class="v">{_esc(rp.execution_mode)}</div></div>
        <div class="kv"><div class="k">max_single_order_usd</div><div class="v">${_esc(rp.max_single_order_usd)}</div></div>
        <div class="kv"><div class="k">max_daily_cumulative_usd</div><div class="v">${_esc(rp.max_daily_cumulative_usd)}</div></div>
        <div class="kv"><div class="k">daily_used_usd</div><div class="v">${_esc(rp.daily_used_usd)}</div></div>
        <div class="kv"><div class="k">daily_remaining_usd</div><div class="v">${_esc(rp.daily_remaining_usd)}</div></div>
        <div class="kv"><div class="k">circuit_breaker</div><div class="v {'badge-open' if rp.circuit_open else 'badge-closed'}">{circuit_text} (failures={rp.consecutive_failures})</div></div>
        <div class="kv"><div class="k">light_status</div><div class="v">{_esc(light_text)}</div></div>
        <div class="kv"><div class="k">model_hash / freeze</div><div class="v"><code>{_esc(rp.model_hash)}</code> ({frozen_text})</div></div>
        <div class="kv"><div class="k">safety_config_sha256</div><div class="v"><code>{_esc(rp.safety_config_sha256)}</code></div></div>
        {watchdog_summary_html}
      </div>
    </section>

    <section class="card">
      <h2>M7 Audit Integrity, Dual Hashes &amp; PnL Summary</h2>
      <div class="grid">
        <div class="kv"><div class="k">render_status</div><div class="v">{_esc(model.render_status)}</div></div>
        <div class="kv"><div class="k">settlement_status</div><div class="v">{_esc(model.settlement_status)}</div></div>
        <div class="kv"><div class="k">tail_status</div><div class="v">{_esc(model.tail_status)}</div></div>
        <div class="kv"><div class="k">valid / corrupt / skipped_tail</div><div class="v">{model.valid_lines} / {model.corrupt_count} / {model.partial_tail_count}</div></div>
        <div class="kv"><div class="k">missing_forecast_fk</div><div class="v">{model.missing_forecast_fk_count}</div></div>
        <div class="kv"><div class="k">policy_overdue_count</div><div class="v">{model.policy_overdue_count}</div></div>
        <div class="kv"><div class="k">total_filled_usd / fee_paid_usd</div><div class="v">${_esc(model.total_filled_usd)} / ${_esc(model.total_fee_paid_usd)}</div></div>
        <div class="kv"><div class="k">total_realized_pnl_usd</div><div class="v">${_esc(model.total_realized_pnl_usd)}</div></div>
        <div class="kv"><div class="k">observed_config_hashes</div><div class="v"><code>{_esc(', '.join(model.config_hashes) or '-')}</code></div></div>
        <div class="kv"><div class="k">observed_model_hashes</div><div class="v"><code>{_esc(', '.join(model.model_hashes) or '-')}</code></div></div>
      </div>
    </section>

    <section class="card" aria-label="城市与日期独立盘口聚合">
      <h2>城市 -&gt; 日期独立盘口聚合卡 (按 M7 §2.7 盘口独立核算)</h2>
      <p class="note-muted">每日/每盘口独立结算；城市级仅汇总投入、已结算盈亏、未结算敞口与单数/胜场，不做跨盘口概率平均或胜率加权。</p>
      {city_cards_html}
    </section>

    <section class="card" aria-label="按结算日累计盈亏曲线">
      <h2>按结算日累计已实现盈亏曲线 (Static SVG · 无数据日留空不补点)</h2>
      {daily_pnl_svg_html}
    </section>

    <section class="card">
      <h2>Decision-to-Execution Trace (P1 -&gt; P17 / P13 / P3)</h2>
      <table>
        <thead>
          <tr>
            <th>decision_id</th><th>scan_ts_utc</th><th>station</th><th>target_date</th><th>bin_id</th>
            <th>outcome</th><th>model_hash</th><th>config_hash</th><th>overdue</th>
            <th>forecast_id</th><th>book_frame</th><th>terminal</th><th>filled_sh</th>
            <th>filled_usd</th><th>fee_usd</th><th>gateway_stages</th>
          </tr>
        </thead>
        <tbody>{decision_trs}</tbody>
      </table>
      {decision_chain_cards}
    </section>

    <section class="card">
      <h2>M9 Official Settlement &amp; M6/P15 Reconciliation ({_esc(model.settlement_status)})</h2>
      <table>
        <thead>
          <tr>
            <th>settlement_id</th><th>station</th><th>target_date</th><th>type</th><th>market_id</th>
            <th>winning_bin_id</th><th>settled_temp_f_int</th><th>oracle</th><th>fallback</th>
            <th>p15_reconciled</th><th>realized_pnl_usd</th>
          </tr>
        </thead>
        <tbody>{settlement_trs}</tbody>
      </table>
    </section>

    <section class="card">
      <h2>M6 Capital Ledger Events (P19)</h2>
      <table>
        <thead>
          <tr>
            <th>event_id</th><th>event_ts_utc</th><th>event_type</th><th>station</th>
            <th>light</th><th>free_usd_after</th><th>locked_usd_after</th><th>realized_pnl</th><th>reason</th>
          </tr>
        </thead>
        <tbody>{p19_trs}</tbody>
      </table>
    </section>
  </div>
</body>
</html>
"""
