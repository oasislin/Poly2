"""P4 v1.1 dual-side (YES + NO) orderbook parsing, pairing, and split/merge view builder.

Anchors:
- `P8-RECORDER-NO-SIDE-DESIGN v0.1 §2–§3`
- `项目方案 (v3.0) §8.4 A.1` (`P4 MarketBookSnapshot v1.1`)

Never mutates `src/pricing/` (`F-2` locked) or `src/data_acquisition/passive_book_recorder.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple

from src.data_acquisition.passive_book_recorder import (
    BidBook,
    MarketBookRecordEnvelope,
    MarketBookSnapshot,
    OutcomeSide,
    SingleSide,
)
from src.pricing.penetration_probe import AskBook
from src.utils.causal_utils import CausalInputError, ensure_utc_datetime, parse_utc_timestamp
from src.utils.decimal_guard import exact_decimal_context, to_guarded_decimal

LegSource = Literal["YES_ASK", "NO_BID_SPLIT_SELL"]


@dataclass(frozen=True)
class LeggedAskLevel:
    """Single ask liquidity slice on the synthetic/merged YES ask view with provenance."""

    implied_yes_price: Decimal
    size_shares: Decimal
    leg_source: LegSource
    source_token_id: str
    raw_source_price: Decimal
    fee_rate: Decimal
    tick_size: Decimal


@dataclass(frozen=True)
class DualSideBookPair:
    """Causally aligned `(YES, NO)` market book snapshot pair for one temperature bin."""

    station_id: str
    target_date: str
    bin_label: str
    market_id: str
    condition_id: str
    yes_frame: Optional[MarketBookSnapshot]
    no_frame: Optional[MarketBookSnapshot]
    skew_sec: Optional[float]
    skew_fallback: bool
    degraded_reason: Optional[str] = None


@dataclass(frozen=True)
class MergedYesAskView:
    """Merged YES ask book (`Ask(YES) ∪ (1 - Bid(NO))`) compatible with read-only `edge_math`."""

    ask_book: Optional[AskBook]
    legged_levels: Tuple[LeggedAskLevel, ...]
    best_bid_effective: Optional[Decimal]
    inverted_cross: bool
    has_yes_ask: bool
    has_no_bid_split: bool
    yes_single_side: Optional[SingleSide]
    no_single_side: Optional[SingleSide]
    used_tokens: Tuple[str, ...]
    inversion_reason: Optional[str] = None


def _resolve_single_side(
    raw_ss: Any,
    ask_book: Optional[AskBook],
    bid_book: Optional[BidBook],
) -> Optional[SingleSide]:
    if raw_ss in ("bid_only", "ask_only"):
        return raw_ss
    if ask_book is None and bid_book is not None:
        return "bid_only"
    if bid_book is None and ask_book is not None:
        return "ask_only"
    return None


def _build_snapshot_from_payload(payload: Mapping[str, Any]) -> MarketBookSnapshot:
    raw_asks = payload.get("asks") or []
    raw_bids = payload.get("bids") or []
    ask_book = AskBook(levels=tuple((float(p), float(s)) for p, s in raw_asks)) if raw_asks else None
    bid_book = BidBook(levels=tuple((float(p), float(s)) for p, s in raw_bids)) if raw_bids else None
    raw_outcome = str(payload.get("outcome") or "YES").upper()
    outcome: OutcomeSide = "NO" if raw_outcome == "NO" else "YES"
    snap_ts_raw = payload.get("snapshot_ts_utc")
    snap_ts = parse_utc_timestamp(snap_ts_raw, field_name="snapshot_ts_utc") if snap_ts_raw is not None else None
    bid_top10 = tuple((float(p), float(s)) for p, s in (payload.get("bid_top10") or []))
    best_bid = float(payload["best_bid"]) if payload.get("best_bid") is not None else None
    min_not = float(payload["min_notional_usd"]) if payload.get("min_notional_usd") is not None else None
    return MarketBookSnapshot(
        token_id=str(payload["token_id"]),
        market_id=str(payload["market_id"]),
        condition_id=str(payload["condition_id"]),
        snapshot_ts_utc=snap_ts,
        recv_ts_utc=parse_utc_timestamp(payload["recv_ts_utc"], field_name="recv_ts_utc"),
        ask_book=ask_book,
        bid_book=bid_book,
        best_bid=best_bid,
        bid_top10=bid_top10,
        tick_size=float(payload["tick_size"]),
        min_order_size_shares=float(payload["min_order_size_shares"]),
        min_notional_usd=min_not,
        fee_rate=float(payload["fee_rate"]),
        fee_rate_provenance=payload["fee_rate_provenance"],
        neg_risk=payload.get("neg_risk"),
        data_source=payload["data_source"],
        frame_seq=int(payload["frame_seq"]),
        outcome=outcome,
        single_side=_resolve_single_side(payload.get("single_side"), ask_book, bid_book),
    )


def parse_p4_snapshot_from_p13_dict(raw_envelope: Mapping[str, Any]) -> MarketBookRecordEnvelope:
    """Parse a serialized `P13` JSONL dict cleanly into `MarketBookRecordEnvelope` (`P4 v1.1`)."""
    payload = raw_envelope.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("P13 envelope missing dict 'payload'")
    return MarketBookRecordEnvelope(
        schema_version=str(raw_envelope["schema_version"]),
        seq_id=int(raw_envelope["seq_id"]),
        session_id=str(raw_envelope["session_id"]),
        capture_mode=raw_envelope["capture_mode"],
        gap_detected=bool(raw_envelope["gap_detected"]),
        gap_reason=raw_envelope.get("gap_reason"),
        recorded_ts_utc=parse_utc_timestamp(raw_envelope["recorded_ts_utc"], field_name="recorded_ts_utc"),
        station_id=str(raw_envelope["station_id"]),
        target_date=str(raw_envelope["target_date"]),
        bin_label=str(raw_envelope["bin_label"]),
        payload=_build_snapshot_from_payload(payload),
    )


def equivalent_complementary_price(price: Decimal | float | str) -> Decimal:
    """CTF split/merge price equivalence (`1 - p`) executed in exact Decimal context."""
    with exact_decimal_context(trap_inexact=True):
        p_dec = to_guarded_decimal(price, name="complementary_price")
        comp = Decimal("1") - p_dec
    if not (Decimal("0") < comp < Decimal("1")):
        raise ValueError(f"Complementary price out of (0, 1): price={p_dec}, 1-price={comp}")
    return comp


def _select_latest_clean_by_market(
    envelopes: Sequence[MarketBookRecordEnvelope],
    *,
    as_of: datetime,
    allow_gap_frames: bool,
) -> Dict[Tuple[str, str, str, str], Dict[OutcomeSide, MarketBookRecordEnvelope]]:
    latest_by_key: Dict[Tuple[str, str, str, str], Dict[OutcomeSide, MarketBookRecordEnvelope]] = {}
    for env in envelopes:
        recv_ts = ensure_utc_datetime(env.payload.recv_ts_utc, field_name="payload.recv_ts_utc")
        if recv_ts > as_of:
            raise CausalInputError(
                f"Future book frame recv_ts_utc={recv_ts.isoformat()} > as_of={as_of.isoformat()}"
            )
        if not allow_gap_frames and env.gap_detected:
            continue
        key = (env.station_id, env.target_date, env.bin_label, env.payload.market_id)
        slot = latest_by_key.setdefault(key, {})
        outcome = env.payload.outcome
        prev = slot.get(outcome)
        if prev is None or (recv_ts, env.seq_id) > (
            ensure_utc_datetime(prev.payload.recv_ts_utc, field_name="prev.recv_ts_utc"),
            prev.seq_id,
        ):
            slot[outcome] = env
    return latest_by_key


def _build_pair_entry(
    key: Tuple[str, str, str, str],
    slot: Dict[OutcomeSide, MarketBookRecordEnvelope],
    *,
    as_of: datetime,
    max_book_staleness_sec: float,
    pair_max_skew_sec: float,
) -> DualSideBookPair:
    station_id, target_date, bin_label, market_id = key
    yes_env, no_env = slot.get("YES"), slot.get("NO")
    yes_snap = (
        yes_env.payload
        if yes_env is not None and (as_of - yes_env.payload.recv_ts_utc).total_seconds() <= max_book_staleness_sec
        else None
    )
    no_snap = (
        no_env.payload
        if no_env is not None and (as_of - no_env.payload.recv_ts_utc).total_seconds() <= max_book_staleness_sec
        else None
    )
    ref_env = yes_env or no_env
    condition_id = (
        yes_snap.condition_id if yes_snap is not None else (
            no_snap.condition_id if no_snap is not None else (ref_env.payload.condition_id if ref_env is not None else "")
        )
    )
    if yes_snap is None and no_snap is None:
        return DualSideBookPair(
            station_id=station_id, target_date=target_date, bin_label=bin_label, market_id=market_id,
            condition_id=condition_id, yes_frame=None, no_frame=None, skew_sec=None,
            skew_fallback=False, degraded_reason="STALE_OR_MISSING_BOTH_LEGS",
        )
    skew_sec: Optional[float] = None
    skew_fallback = False
    degraded_reason: Optional[str] = None
    if yes_snap is not None and no_snap is not None:
        skew_sec = abs((yes_snap.recv_ts_utc - no_snap.recv_ts_utc).total_seconds())
        if skew_sec > pair_max_skew_sec:
            skew_fallback = True
            degraded_reason = f"PAIR_SKEW_FALLBACK:{skew_sec:.3f}s>{pair_max_skew_sec:.3f}s"
            if yes_snap.recv_ts_utc >= no_snap.recv_ts_utc:
                no_snap = None
            else:
                yes_snap = None
    return DualSideBookPair(
        station_id=station_id, target_date=target_date, bin_label=bin_label, market_id=market_id,
        condition_id=condition_id, yes_frame=yes_snap, no_frame=no_snap, skew_sec=skew_sec,
        skew_fallback=skew_fallback, degraded_reason=degraded_reason,
    )


def pair_dual_side_books(
    envelopes: Sequence[MarketBookRecordEnvelope],
    *,
    as_of_ts_utc: datetime,
    max_book_staleness_sec: float,
    pair_max_skew_sec: float,
    allow_gap_frames: bool = False,
) -> Dict[Tuple[str, str, str, str], DualSideBookPair]:
    """Select latest causal clean YES/NO snapshots per market and enforce `pair_max_skew_sec`."""
    as_of = ensure_utc_datetime(as_of_ts_utc, field_name="as_of_ts_utc")
    if max_book_staleness_sec < 0.0 or pair_max_skew_sec < 0.0:
        raise ValueError("max_book_staleness_sec and pair_max_skew_sec must be non-negative")
    latest_by_key = _select_latest_clean_by_market(
        envelopes, as_of=as_of, allow_gap_frames=allow_gap_frames
    )
    return {
        key: _build_pair_entry(
            key, slot, as_of=as_of, max_book_staleness_sec=max_book_staleness_sec, pair_max_skew_sec=pair_max_skew_sec
        )
        for key, slot in latest_by_key.items()
    }


def _extract_yes_ask_legs(yes_frame: Optional[MarketBookSnapshot]) -> List[LeggedAskLevel]:
    if yes_frame is None or yes_frame.ask_book is None:
        return []
    fee_dec = to_guarded_decimal(yes_frame.fee_rate, name="yes.fee_rate")
    tick_dec = to_guarded_decimal(yes_frame.tick_size, name="yes.tick_size")
    out: List[LeggedAskLevel] = []
    for p_raw, s_raw in yes_frame.ask_book.levels:
        p_dec = to_guarded_decimal(p_raw, name="yes.ask.price")
        s_dec = to_guarded_decimal(s_raw, name="yes.ask.size")
        out.append(
            LeggedAskLevel(
                implied_yes_price=p_dec,
                size_shares=s_dec,
                leg_source="YES_ASK",
                source_token_id=yes_frame.token_id,
                raw_source_price=p_dec,
                fee_rate=fee_dec,
                tick_size=tick_dec,
            )
        )
    return out


def _extract_no_bid_split_legs(no_frame: Optional[MarketBookSnapshot]) -> List[LeggedAskLevel]:
    """Map Bid(NO) @ p_b into equivalent Ask(YES) @ (1 - p_b) via CTF split+sell equivalence."""
    if no_frame is None or no_frame.bid_book is None:
        return []
    fee_dec = to_guarded_decimal(no_frame.fee_rate, name="no.fee_rate")
    tick_dec = to_guarded_decimal(no_frame.tick_size, name="no.tick_size")
    out: List[LeggedAskLevel] = []
    for p_raw, s_raw in no_frame.bid_book.levels:
        p_no_bid = to_guarded_decimal(p_raw, name="no.bid.price")
        p_imp_yes = equivalent_complementary_price(p_no_bid)
        s_dec = to_guarded_decimal(s_raw, name="no.bid.size")
        out.append(
            LeggedAskLevel(
                implied_yes_price=p_imp_yes,
                size_shares=s_dec,
                leg_source="NO_BID_SPLIT_SELL",
                source_token_id=no_frame.token_id,
                raw_source_price=p_no_bid,
                fee_rate=fee_dec,
                tick_size=tick_dec,
            )
        )
    return out


def _compute_effective_best_bid(
    yes_frame: Optional[MarketBookSnapshot],
    no_frame: Optional[MarketBookSnapshot],
    *,
    include_no_side: bool,
) -> Optional[Decimal]:
    bid_candidates: List[Decimal] = []
    if yes_frame is not None and yes_frame.best_bid is not None:
        bid_candidates.append(to_guarded_decimal(yes_frame.best_bid, name="yes.best_bid"))
    if (
        include_no_side
        and no_frame is not None
        and no_frame.ask_book is not None
        and len(no_frame.ask_book.levels) > 0
    ):
        bid_candidates.append(equivalent_complementary_price(no_frame.ask_book.levels[0][0]))
    return max(bid_candidates) if bid_candidates else None


def _check_book_inversion(
    yes_frame: Optional[MarketBookSnapshot],
    no_frame: Optional[MarketBookSnapshot],
    raw_all: Sequence[LeggedAskLevel],
    best_bid_eff: Optional[Decimal],
    *,
    include_no_side: bool,
    cross_arb_eps: Decimal,
) -> Tuple[bool, Optional[str]]:
    if yes_frame is not None and yes_frame.ask_book is not None and yes_frame.best_bid is not None:
        if yes_frame.ask_book.levels[0][0] <= yes_frame.best_bid:
            return True, "YES_INTRA_BOOK_INVERTED"
    if (
        include_no_side
        and no_frame is not None
        and no_frame.ask_book is not None
        and no_frame.best_bid is not None
        and no_frame.ask_book.levels[0][0] <= no_frame.best_bid
    ):
        return True, "NO_INTRA_BOOK_INVERTED"
    if raw_all and best_bid_eff is not None:
        # Strict epsilon tolerance prevents equality (ask_YES + ask_NO == 1.0) from false-tripping.
        with exact_decimal_context(trap_inexact=True):
            if raw_all[0].implied_yes_price < (best_bid_eff - cross_arb_eps):
                return True, "CROSS_VIEW_INVERTED_SPREAD"
    return False, None


def build_merged_yes_ask_view(
    yes_frame: Optional[MarketBookSnapshot],
    no_frame: Optional[MarketBookSnapshot] = None,
    *,
    include_no_side: bool = True,
    cross_arb_eps: Decimal = Decimal("0.0001"),
) -> MergedYesAskView:
    """Build combined `Ask(YES) ∪ (1 - Bid(NO))` view without mutating `F-2` `AskBook`."""
    yes_legs = _extract_yes_ask_legs(yes_frame)
    no_legs = _extract_no_bid_split_legs(no_frame) if include_no_side else []
    raw_all: List[LeggedAskLevel] = sorted(
        yes_legs + no_legs,
        key=lambda lvl: (lvl.implied_yes_price, 0 if lvl.leg_source == "YES_ASK" else 1),
    )
    merged_by_price: Dict[Decimal, Decimal] = {}
    for lvl in raw_all:
        with exact_decimal_context(trap_inexact=True):
            merged_by_price[lvl.implied_yes_price] = (
                merged_by_price.get(lvl.implied_yes_price, Decimal("0")) + lvl.size_shares
            )
    sorted_levels = tuple(
        (float(p), float(s)) for p, s in sorted(merged_by_price.items(), key=lambda kv: kv[0])
    )
    best_bid_eff = _compute_effective_best_bid(yes_frame, no_frame, include_no_side=include_no_side)
    inverted_cross, inversion_reason = _check_book_inversion(
        yes_frame, no_frame, raw_all, best_bid_eff,
        include_no_side=include_no_side, cross_arb_eps=cross_arb_eps,
    )
    used_tokens = tuple(
        dict.fromkeys(
            frame.token_id for frame in (yes_frame, no_frame if include_no_side else None) if frame is not None
        )
    )
    return MergedYesAskView(
        ask_book=AskBook(levels=sorted_levels) if sorted_levels else None,
        legged_levels=tuple(raw_all),
        best_bid_effective=best_bid_eff,
        inverted_cross=inverted_cross,
        has_yes_ask=bool(yes_legs),
        has_no_bid_split=bool(no_legs),
        yes_single_side=yes_frame.single_side if yes_frame is not None else None,
        no_single_side=no_frame.single_side if (include_no_side and no_frame is not None) else None,
        used_tokens=used_tokens,
        inversion_reason=inversion_reason,
    )


__all__ = [
    "DualSideBookPair",
    "LegSource",
    "LeggedAskLevel",
    "MergedYesAskView",
    "build_merged_yes_ask_view",
    "equivalent_complementary_price",
    "pair_dual_side_books",
    "parse_p4_snapshot_from_p13_dict",
]
