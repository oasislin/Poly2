"""Read-Only `P8` Calibration Stream Aggregator (`M7 -> M8`).

Anchors:
- `P8-T4-M4M5-INTERFACE v1.0 §3.2`: strictly offline read-only aggregation over M7 JSONL logs
  (`P17`, `P1`, `P3`, `P19`). Zero bypass writes into M8 ledgers or P6 runtime parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.audit.p10_reader import P10Query, query_p10_session_view
from src.audit.p19_events import ExecutionMode
from src.utils.causal_utils import ensure_utc_datetime, parse_utc_timestamp


@dataclass(frozen=True)
class CalibrationAggregateBatch:
    """`P8 CalibrationAggregateBatch` matching `P8-T4-M4M5-INTERFACE v1.0 §3.2`."""

    window_start_utc: datetime
    window_end_utc: datetime
    execution_mode_filter: ExecutionMode
    model_hash: Optional[str]
    config_hash: Optional[str]
    n_forecast_samples: int
    sigma_delta_quantiles: Dict[str, float]
    empirical_slippage_vs_best_ask_median: Optional[float]
    n_slippage_fills: int
    idle_rate_by_tau: Dict[str, float]
    policy_overdue_ratio: float


def _quantile_sorted(sorted_vals: List[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return float(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)


def _in_window(
    rec: Mapping[str, Any],
    ts_key: str,
    start: datetime,
    end: datetime,
    model_hash: Optional[str],
    config_hash: Optional[str],
) -> bool:
    raw_ts = rec.get(ts_key)
    if not isinstance(raw_ts, str):
        return False
    ts = parse_utc_timestamp(raw_ts, field_name=f"p8.{ts_key}")
    if not (start <= ts <= end):
        return False
    if model_hash is not None and rec.get("model_hash") != model_hash:
        return False
    if config_hash is not None and rec.get("config_hash") != config_hash:
        return False
    return True


def _tau_bucket_label(tau_hours: float) -> str:
    if tau_hours >= 24.0:
        return "tau_ge_24h"
    if tau_hours >= 6.0:
        return "tau_6h_24h"
    return "tau_lt_6h"


def _compute_idle_rate_by_tau(p1_rows: List[Mapping[str, Any]]) -> Dict[str, float]:
    buckets: Dict[str, Tuple[int, int]] = {"tau_ge_24h": (0, 0), "tau_6h_24h": (0, 0), "tau_lt_6h": (0, 0)}
    for rec in p1_rows:
        best_edge = rec.get("best_ask_edge")
        m_thresh = rec.get("m_threshold")
        if best_edge is None or m_thresh is None or float(best_edge) < float(m_thresh):
            continue
        label = _tau_bucket_label(float(rec.get("tau_hours", 0.0)))
        crossed, idle = buckets[label]
        is_idle = 1 if rec.get("decision_outcome") == "IDLE_BUDGET_EXHAUSTED" else 0
        buckets[label] = (crossed + 1, idle + is_idle)
    return {k: (idle / crossed if crossed > 0 else 0.0) for k, (crossed, idle) in buckets.items()}


def _compute_slippage_metrics(p3_rows: List[Mapping[str, Any]]) -> Tuple[Optional[float], int]:
    slippages: List[float] = []
    for rec in p3_rows:
        if rec.get("terminal_status") not in ("FILLED", "PARTIAL"):
            continue
        raw_slip = rec.get("slippage_vs_best_ask")
        if raw_slip is None:
            continue
        slippages.append(float(Decimal(str(raw_slip))))
    if not slippages:
        return None, 0
    return float(median(slippages)), len(slippages)


def aggregate_p8_calibration_batch(
    audit_root: Path,
    *,
    execution_mode: ExecutionMode,
    window_start_utc: datetime,
    window_end_utc: datetime,
    model_hash: Optional[str] = None,
    config_hash: Optional[str] = None,
) -> CalibrationAggregateBatch:
    """Strictly read-only aggregation over M7 JSONL logs emitting `CalibrationAggregateBatch`."""
    start = ensure_utc_datetime(window_start_utc, field_name="window_start_utc")
    end = ensure_utc_datetime(window_end_utc, field_name="window_end_utc")
    view = query_p10_session_view(
        audit_root,
        P10Query(execution_mode=execution_mode, date_range=(start.date(), end.date())),
    )
    p17_rows = [r for r in view.p17_snapshots if _in_window(r, "issue_ts_utc", start, end, model_hash, config_hash)]
    p1_rows = [r for r in view.p1_events if _in_window(r, "scan_ts_utc", start, end, model_hash, config_hash)]
    p3_rows = [r for r in view.p3_events if _in_window(r, "decision_ts_utc", start, end, model_hash, config_hash)]

    sigmas = sorted(float(r["sigma_delta_sample"]) for r in p17_rows if r.get("sigma_delta_sample") is not None)
    q_map = (
        {"p50": _quantile_sorted(sigmas, 0.50), "p90": _quantile_sorted(sigmas, 0.90), "p95": _quantile_sorted(sigmas, 0.95)}
        if sigmas
        else {}
    )
    slip_med, slip_n = _compute_slippage_metrics(p3_rows)
    overdue_cnt = sum(1 for r in p1_rows if r.get("policy_overdue"))
    overdue_ratio = overdue_cnt / len(p1_rows) if p1_rows else 0.0
    return CalibrationAggregateBatch(
        window_start_utc=start,
        window_end_utc=end,
        execution_mode_filter=execution_mode,
        model_hash=model_hash,
        config_hash=config_hash,
        n_forecast_samples=len(p17_rows),
        sigma_delta_quantiles=q_map,
        empirical_slippage_vs_best_ask_median=slip_med,
        n_slippage_fills=slip_n,
        idle_rate_by_tau=_compute_idle_rate_by_tau(p1_rows),
        policy_overdue_ratio=overdue_ratio,
    )


__all__ = [
    "CalibrationAggregateBatch",
    "aggregate_p8_calibration_batch",
]
