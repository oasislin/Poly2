"""P19 CapitalEventLog schema (`M6 -> M7`, `P8-T2-M7-LOGGING v1.0 §2.4`)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any, Dict, Literal, Optional
import uuid

from src.utils.causal_utils import compute_record_sha256, ensure_utc_datetime

ExecutionMode = Literal["PAPER", "LIVE"]
CapitalEventType = Literal[
    "FREEZE",
    "UNFREEZE",
    "FILL_SETTLE_CONVERSION",
    "STATION_LOSS_GATE_TRIP",
    "ACCOUNT_DRAWDOWN_BRAKE_TRIP",
    "LIGHT_LEVEL_APPLIED",
    "TIER_STEP_UP",
    "POLICY_OVERDUE_MARK",
    "GATE_LIVE_SWITCH",
]
_P19_UUID_NS = uuid.UUID("a32e10a4-7b18-4f24-8e21-202611210019")


@dataclass(frozen=True)
class CapitalEventLog:
    """Typed `P19 CapitalEventLog` matching `P8-T2-M7-LOGGING v1.0 §2.4`."""

    schema_version: str
    event_id: str
    event_ts_utc: datetime
    session_id: str
    execution_mode: ExecutionMode
    station_id: Optional[str]
    event_type: CapitalEventType
    light_status: Optional[str]
    tier_pool_usd: Optional[float]
    free_usd_after: float
    active_locked_usd_after: float
    station_realized_pnl_usd: Optional[float]
    policy_version: str
    config_hash: str
    is_overdue: bool
    related_ref_id: Optional[str]
    reason: str

    def __post_init__(self) -> None:
        if self.schema_version != "p19.v1":
            raise ValueError(f"Expected p19.v1, got {self.schema_version!r}")
        ensure_utc_datetime(self.event_ts_utc, field_name="p19.event_ts_utc")
        if self.execution_mode not in ("PAPER", "LIVE"):
            raise ValueError(f"Invalid P19 execution_mode={self.execution_mode!r}")

    def to_dict_without_hash(self) -> Dict[str, Any]:
        """Serialize canonical fields excluding `record_sha256`."""
        ts = ensure_utc_datetime(self.event_ts_utc, field_name="p19.event_ts_utc")
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_ts_utc": ts.isoformat(),
            "session_id": self.session_id,
            "execution_mode": self.execution_mode,
            "station_id": self.station_id,
            "event_type": self.event_type,
            "light_status": self.light_status,
            "tier_pool_usd": self.tier_pool_usd,
            "free_usd_after": float(self.free_usd_after),
            "active_locked_usd_after": float(self.active_locked_usd_after),
            "station_realized_pnl_usd": self.station_realized_pnl_usd,
            "policy_version": self.policy_version,
            "config_hash": self.config_hash,
            "is_overdue": bool(self.is_overdue),
            "related_ref_id": self.related_ref_id,
            "reason": self.reason,
        }

    def to_json_line(self) -> str:
        """Render canonical JSONL line with `record_sha256` integrity digest."""
        payload = self.to_dict_without_hash()
        payload["record_sha256"] = compute_record_sha256(payload)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_capital_event_log(
    *,
    event_ts_utc: datetime,
    session_id: str,
    execution_mode: ExecutionMode,
    station_id: Optional[str],
    event_type: CapitalEventType,
    free_usd_after: float,
    active_locked_usd_after: float,
    policy_version: str,
    config_hash: str,
    is_overdue: bool,
    reason: str,
    light_status: Optional[str] = None,
    tier_pool_usd: Optional[float] = None,
    station_realized_pnl_usd: Optional[float] = None,
    related_ref_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> CapitalEventLog:
    """Construct a deterministic `CapitalEventLog` record (`p19.v1`)."""
    ts = ensure_utc_datetime(event_ts_utc, field_name="p19.event_ts_utc")
    eid = event_id or str(
        uuid.uuid5(_P19_UUID_NS, f"{session_id}|{ts.isoformat()}|{event_type}|{station_id}|{related_ref_id}")
    )
    return CapitalEventLog(
        schema_version="p19.v1",
        event_id=eid,
        event_ts_utc=ts,
        session_id=session_id,
        execution_mode=execution_mode,
        station_id=station_id,
        event_type=event_type,
        light_status=light_status,
        tier_pool_usd=tier_pool_usd,
        free_usd_after=free_usd_after,
        active_locked_usd_after=active_locked_usd_after,
        station_realized_pnl_usd=station_realized_pnl_usd,
        policy_version=policy_version,
        config_hash=config_hash,
        is_overdue=is_overdue,
        related_ref_id=related_ref_id,
        reason=reason,
    )


__all__ = [
    "CapitalEventLog",
    "CapitalEventType",
    "ExecutionMode",
    "build_capital_event_log",
]
