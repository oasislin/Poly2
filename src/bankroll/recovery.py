"""Read-only M7 audit-log recovery for `BankrollAccountManager` and `open_claims`."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Set, Tuple

from src.audit.p10_reader import (
    P10Query,
    _iter_date_dirs,
    _open_jsonl_readonly,
    _resolve_stream_file,
    read_verified_jsonl_file,
)
from src.audit.p19_events import ExecutionMode
from src.settlement.m9_settler import MarketPositionClaim

_ZERO = Decimal("0")


@dataclass(frozen=True)
class RecoveredAuditState:
    """Recovered pre-restart state built purely read-only from `data/audit_logs/<MODE>/`."""

    seen_p17_ids: Set[str]
    settled_p9_keys: Set[Tuple[str, str, str]]
    open_claims: Dict[Tuple[str, str, str], Dict[str, MarketPositionClaim]]
    open_held_by_market: Dict[Tuple[str, str], Decimal]
    open_fee_by_market: Dict[Tuple[str, str], Decimal]
    total_fee_paid_usd: Decimal
    realized_pnl_by_station: Dict[str, Decimal]
    settled_attempt_ids: Set[str]
    settled_p15_ids: Dict[str, Decimal]
    tier_pool_usd: Optional[Decimal]
    light_status: Optional[str]


def _to_dec(val: Any) -> Decimal:
    if val is None or val == "":
        return _ZERO
    return Decimal(str(val))


def _scan_p17_p9_p19(
    date_dirs: Iterable[Path], *, execution_mode: ExecutionMode
) -> Tuple[Set[str], Dict[Tuple[str, str, str], Dict[str, Any]], Optional[Decimal], Optional[str]]:
    seen_p17: Set[str] = set()
    p9_by_key: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    tier_pool: Optional[Decimal] = None
    light: Optional[str] = None
    for ddir in date_dirs:
        for r in read_verified_jsonl_file(_resolve_stream_file(ddir, "p17_forecast_snapshots.jsonl"), verify_sha256=False).records:
            if r.get("execution_mode") == execution_mode and r.get("forecast_id"):
                seen_p17.add(str(r["forecast_id"]))
        for r in read_verified_jsonl_file(_resolve_stream_file(ddir, "p9_settlement_truths.jsonl"), verify_sha256=False).records:
            if r.get("execution_mode") == execution_mode:
                p9_by_key[(str(r["station_id"]), str(r["target_date"]), str(r["target_type"]))] = r
        for r in read_verified_jsonl_file(_resolve_stream_file(ddir, "p19_capital_events.jsonl"), verify_sha256=False).records:
            if r.get("execution_mode") != execution_mode:
                continue
            if r.get("event_type") == "TIER_STEP_UP" and r.get("tier_pool_usd") is not None:
                tier_pool = _to_dec(r["tier_pool_usd"])
            if r.get("event_type") == "LIGHT_LEVEL_APPLIED" and r.get("light_status"):
                light = str(r["light_status"])
    return seen_p17, p9_by_key, tier_pool, light


def _load_filled_p3_attempts(
    date_dirs: Iterable[Path], *, execution_mode: ExecutionMode
) -> Dict[str, Dict[str, Any]]:
    by_attempt: Dict[str, Dict[str, Any]] = {}
    for ddir in date_dirs:
        path = _resolve_stream_file(ddir, "p3_execution_attempts.jsonl")
        for r in read_verified_jsonl_file(path, verify_sha256=False).records:
            if r.get("execution_mode") != execution_mode or r.get("schema_version") == "p3.gateway.v1":
                continue
            if _to_dec(r.get("filled_shares")) > _ZERO and r.get("attempt_id"):
                by_attempt[str(r["attempt_id"])] = r
    return by_attempt


def _stream_p1_metadata_for_decisions(
    date_dirs: Iterable[Path], target_decision_ids: Set[str]
) -> Dict[str, Tuple[str, str, str, str, str]]:
    if not target_decision_ids:
        return {}
    meta: Dict[str, Tuple[str, str, str, str, str]] = {}
    for ddir in date_dirs:
        path = _resolve_stream_file(ddir, "p1_scan_decisions.jsonl")
        if not path.exists():
            continue
        with _open_jsonl_readonly(path) as fh:
            for raw in fh:
                if not raw.endswith("\n") or not raw.strip():
                    continue
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue
                did = str(obj.get("decision_id") or "")
                if did in target_decision_ids:
                    meta[did] = (
                        str(obj.get("station_id") or ""),
                        str(obj.get("target_date") or ""),
                        str(obj.get("target_type") or "TMAX"),
                        str(obj.get("market_id") or ""),
                        str(obj.get("bin_id") or ""),
                    )
                    if len(meta) == len(target_decision_ids):
                        return meta
    return meta


def _accumulate_claim(
    open_claims: Dict[Tuple[str, str, str], Dict[str, MarketPositionClaim]],
    mkey: Tuple[str, str, str],
    market_id: str,
    bin_id: str,
    shares: Decimal,
    cost: Decimal,
) -> None:
    bucket = open_claims.setdefault(mkey, {})
    prev = bucket.get(market_id)
    new_shares = shares + (prev.held_shares if prev else _ZERO)
    new_cost = cost + (prev.cost_basis_usd or _ZERO if prev else _ZERO)
    bucket[market_id] = MarketPositionClaim(market_id, bin_id, new_shares, new_cost)


def recover_bankroll_and_claims_from_audit(
    audit_root: Path, *, execution_mode: ExecutionMode = "PAPER"
) -> RecoveredAuditState:
    """Reconstruct open claims, held cost basis, cumulative fees, and realized PnL from M7 logs."""
    date_dirs = _iter_date_dirs(Path(audit_root) / execution_mode, P10Query(execution_mode=execution_mode))
    seen_p17, p9_by_key, tier_pool, light = _scan_p17_p9_p19(date_dirs, execution_mode=execution_mode)
    filled_attempts = _load_filled_p3_attempts(date_dirs, execution_mode=execution_mode)
    dec_ids = {str(r.get("decision_id")) for r in filled_attempts.values() if r.get("decision_id")}
    p1_meta = _stream_p1_metadata_for_decisions(date_dirs, dec_ids)
    open_claims: Dict[Tuple[str, str, str], Dict[str, MarketPositionClaim]] = {}
    open_held, open_fee, pnl_by_st, settled_p15, total_fee = {}, {}, {}, {}, _ZERO
    for att in filled_attempts.values():
        info = p1_meta.get(str(att.get("decision_id") or ""))
        if info is None:
            continue
        st_id, t_date, t_type, mkt_id, bin_id = info
        shares, filled_usd, fee_usd = _to_dec(att.get("filled_shares")), _to_dec(att.get("filled_usd")), _to_dec(att.get("fee_paid_usd"))
        total_fee += fee_usd
        mkey = (st_id, t_date, t_type)
        p9 = p9_by_key.get(mkey)
        if p9 is not None:
            pnl = (shares if bin_id == p9.get("winning_bin_id") else _ZERO) - filled_usd
            pnl_by_st[st_id] = pnl_by_st.get(st_id, _ZERO) + pnl
            if p9.get("settlement_id"):
                sid = str(p9["settlement_id"])
                settled_p15[sid] = settled_p15.get(sid, _ZERO) + pnl
        else:
            mk = (st_id, mkt_id)
            open_held[mk] = open_held.get(mk, _ZERO) + filled_usd
            open_fee[mk] = open_fee.get(mk, _ZERO) + fee_usd
            _accumulate_claim(open_claims, mkey, mkt_id, bin_id, shares, filled_usd)
    return RecoveredAuditState(
        seen_p17_ids=seen_p17, settled_p9_keys=set(p9_by_key.keys()), open_claims=open_claims,
        open_held_by_market=open_held, open_fee_by_market=open_fee, total_fee_paid_usd=total_fee,
        realized_pnl_by_station=pnl_by_st, settled_attempt_ids=set(filled_attempts.keys()),
        settled_p15_ids=settled_p15, tier_pool_usd=tier_pool, light_status=light,
    )
