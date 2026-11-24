"""Strictly read-only `M10 v1` view aggregator and static HTML renderer (`S3-10`)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import html
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple

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
        rows.append(
            {
                "decision_id": chain.decision_id,
                "session_id": str(p1.get("session_id") or ""),
                "scan_ts_utc": str(p1.get("scan_ts_utc") or ""),
                "station_id": str(p1.get("station_id") or ""),
                "target_date": str(p1.get("target_date") or ""),
                "target_type": str(p1.get("target_type") or ""),
                "market_id": str(p1.get("market_id") or ""),
                "bin_id": str(p1.get("bin_id") or ""),
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
    )


def _esc(val: Any) -> str:
    return html.escape("-" if val is None else str(val), quote=True)


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
