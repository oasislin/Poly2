"""Isolated per-station per-market-day safety gate for PAPER / P18 simulation."""

from __future__ import annotations

import json
import os
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from src.execution.clob_gateway import load_gateway_safety_config
from src.execution.executor import ExecutionAttemptLog
from src.utils.decimal_guard import to_guarded_decimal

DEFAULT_PAPER_DAILY_LEDGER_PATH = Path("data/gateway/paper_daily_usage.json")


def _market_day_key(station_id: str, target_date: str) -> str:
    return f"{station_id}|{target_date}"


def _load_market_day_ledger(path: Path) -> Dict[str, Decimal]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Decimal] = {}
    for k, v in raw.items():
        if isinstance(k, str):
            try:
                out[k] = Decimal(str(v))
            except Exception:
                continue
    return out


def _atomic_write_ledger(path: Path, data: Dict[str, Decimal]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({k: str(v) for k, v in sorted(data.items())}, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


class PaperSafetyGate:
    """Enforce single-order ($25) and per-station per-market-day ($250) caps in PAPER mode."""

    def __init__(
        self,
        *,
        max_single_order_usd: Decimal,
        max_daily_cumulative_usd: Decimal,
        ledger_path: Path = DEFAULT_PAPER_DAILY_LEDGER_PATH,
    ) -> None:
        self.max_single_order_usd = Decimal(str(max_single_order_usd))
        self.max_daily_cumulative_usd = Decimal(str(max_daily_cumulative_usd))
        self.ledger_path = Path(ledger_path)
        self._used_by_market_day: Dict[str, Decimal] = _load_market_day_ledger(self.ledger_path)

    @classmethod
    def from_config_path(
        cls,
        safety_config_path: Path,
        *,
        ledger_path: Path = DEFAULT_PAPER_DAILY_LEDGER_PATH,
    ) -> "PaperSafetyGate":
        safety = load_gateway_safety_config(safety_config_path)
        return cls(
            max_single_order_usd=safety.max_single_order_usd,
            max_daily_cumulative_usd=safety.max_daily_cumulative_usd,
            ledger_path=ledger_path,
        )

    def used_usd(self, station_id: str, target_date: str) -> Decimal:
        return self._used_by_market_day.get(_market_day_key(station_id, target_date), Decimal("0"))

    def check_order(
        self,
        notional_usd: Decimal,
        *,
        station_id: str,
        target_date: str,
    ) -> Optional[str]:
        notional = Decimal(str(notional_usd))
        if notional > self.max_single_order_usd:
            return "SAFETY_GATE_SINGLE_ORDER_EXCEEDED"
        if self.used_usd(station_id, target_date) + notional > self.max_daily_cumulative_usd:
            return "SAFETY_GATE_DAILY_LIMIT_EXCEEDED"
        return None

    def record_fill(
        self,
        filled_usd: Decimal,
        *,
        station_id: str,
        target_date: str,
    ) -> None:
        filled = Decimal(str(filled_usd))
        if filled <= Decimal("0"):
            return
        mkey = _market_day_key(station_id, target_date)
        self._used_by_market_day[mkey] = self._used_by_market_day.get(mkey, Decimal("0")) + filled
        _atomic_write_ledger(self.ledger_path, self._used_by_market_day)


def build_safety_rejected_attempt(
    *,
    ev: Any,
    session_id: str,
    reason: str,
    latency_ms: Optional[int] = None,
) -> ExecutionAttemptLog:
    """Build a `P3 REJECTED` log record when `PaperSafetyGate` blocks a slice."""
    plan = ev.slice_plan
    return ExecutionAttemptLog(
        schema_version="p3.v1",
        attempt_id=f"p3-gate-{ev.decision_id}",
        decision_id=ev.decision_id,
        idempotency_key=f"p3-gate-{ev.decision_id}",
        session_id=session_id,
        execution_mode="PAPER",
        capture_replay_mode="REPLAY_P13",
        replay_source_seq_id=None,
        latency_injected_ms=latency_ms,
        station_id=ev.station_id,
        market_id=ev.market_id,
        token_id=ev.token_id,
        model_hash=ev.model_hash,
        config_hash=ev.config_hash,
        decision_ts_utc=ev.scan_ts_utc,
        decision_best_ask=to_guarded_decimal(ev.best_ask_price or 0.0, name="p3.best_ask"),
        decision_est_vwap=plan.est_vwap,
        decision_qual_depth_shares=plan.qual_depth_shares,
        order_type="IOC_FAK",
        limit_price=plan.limit_price,
        target_shares=plan.target_shares,
        target_usd=plan.target_usd,
        submit_ts_utc=ev.scan_ts_utc,
        final_ts_utc=ev.scan_ts_utc,
        terminal_status="REJECTED",
        reject_or_abort_reason=reason,
        filled_shares=Decimal("0"),
        filled_usd=Decimal("0"),
        actual_avg_fill_price=None,
        fee_paid_usd=Decimal("0.00000"),
        fill_rate=Decimal("0"),
        slippage_vs_best_ask=None,
        slippage_vs_est_vwap=None,
        execution_legs=(),
    )


__all__ = [
    "DEFAULT_PAPER_DAILY_LEDGER_PATH",
    "PaperSafetyGate",
    "build_safety_rejected_attempt",
]
