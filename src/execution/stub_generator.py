"""P4 v1.1 + DualSideBookPair stub generator (`S3-05` verification dataset builder).

Generates valid `p13.v1` envelopes carrying `P4 MarketBookSnapshot v1.1` (`single_side`,
`Optional[AskBook]`, `outcome: YES|NO`) covering:
1. `two_sided`, `bid_only`, `ask_only` regimes;
2. `DualSideBookPair` skewed timestamp fallback samples (`pair_max_skew_sec`);
3. Cross-view `buy Yes @ p <-> sell No @ (1 - p)` split/merge liquidity samples.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

from src.data_acquisition.passive_book_recorder import (
    BidBook,
    CaptureMode,
    MarketBookRecordEnvelope,
    MarketBookSnapshot,
    OutcomeSide,
    SingleSide,
)
from src.execution.executor import TradingExecutionConfig
from src.prediction.discrete_bin_engine import BinProbV11
from src.prediction.forecast_distribution_engine import ForecastDistributionSnapshotV11
from src.pricing.penetration_probe import AskBook
from src.utils.causal_utils import compute_record_sha256


def _resolve_stub_books(
    regime: Literal["two_sided", "bid_only", "ask_only"],
    asks: Sequence[Tuple[float, float]],
    bids: Sequence[Tuple[float, float]],
) -> Tuple[Optional[AskBook], Optional[BidBook], Optional[SingleSide]]:
    if regime == "two_sided":
        if not asks or not bids:
            raise ValueError("two_sided stub requires both asks and bids")
        return AskBook(levels=tuple(asks)), BidBook(levels=tuple(bids)), None
    if regime == "bid_only":
        if asks or not bids:
            raise ValueError("bid_only stub requires empty asks and non-empty bids")
        return None, BidBook(levels=tuple(bids)), "bid_only"
    if regime == "ask_only":
        if not asks or bids:
            raise ValueError("ask_only stub requires non-empty asks and empty bids")
        return AskBook(levels=tuple(asks)), None, "ask_only"
    raise ValueError(f"Unsupported stub regime: {regime!r}")


def build_p4_v11_stub_envelope(
    *,
    session_id: str,
    seq_id: int,
    frame_seq: int,
    token_id: str,
    market_id: str,
    condition_id: str,
    station_id: str,
    target_date: str,
    bin_label: str,
    outcome: OutcomeSide,
    regime: Literal["two_sided", "bid_only", "ask_only"],
    recv_ts_utc: datetime,
    asks: Sequence[Tuple[float, float]] = (),
    bids: Sequence[Tuple[float, float]] = (),
    tick_size: float = 0.01,
    fee_rate: float = 0.01,
    gap_detected: bool = False,
    gap_reason: Optional[str] = None,
    capture_mode: CaptureMode = "PASSIVE_RECORD",
) -> Tuple[MarketBookRecordEnvelope, Dict[str, Any]]:
    """Build both `MarketBookRecordEnvelope` (`P4 v1.1`) and canonical raw `P13` JSON dict."""
    ask_book, bid_book, single_side = _resolve_stub_books(regime, asks, bids)
    snap = MarketBookSnapshot(
        token_id=token_id, market_id=market_id, condition_id=condition_id,
        snapshot_ts_utc=recv_ts_utc - timedelta(milliseconds=12), recv_ts_utc=recv_ts_utc,
        ask_book=ask_book, bid_book=bid_book,
        best_bid=bid_book.best_price if bid_book is not None else None,
        bid_top10=tuple(bid_book.levels[:10]) if bid_book is not None else (),
        tick_size=tick_size, min_order_size_shares=5.0, min_notional_usd=1.0,
        fee_rate=fee_rate, fee_rate_provenance="API_RUNTIME", neg_risk=True,
        data_source="CLOB_WS", frame_seq=frame_seq, outcome=outcome, single_side=single_side,
    )
    env = MarketBookRecordEnvelope(
        schema_version="p13.v1", seq_id=seq_id, session_id=session_id,
        capture_mode=capture_mode, gap_detected=gap_detected, gap_reason=gap_reason,
        recorded_ts_utc=recv_ts_utc, station_id=station_id,
        target_date=target_date, bin_label=bin_label, payload=snap,
    )
    return env, json.loads(env.to_json_line())


def default_stub_trading_config() -> TradingExecutionConfig:
    return TradingExecutionConfig(
        min_order_size_shares=Decimal("5.0"),
        min_order_size_shares_provenance="FACT-004",
        min_notional_usd=Decimal("1.0"),
        min_notional_usd_provenance="FACT-004_PLACEHOLDER",
        forecast_age_limit_sec=21600.0,
        forecast_age_limit_sec_provenance="P8-T8-ALGO4-DESIGN v0.3 §3.2",
        max_book_staleness_sec=60.0,
        max_book_staleness_sec_provenance="P8-T8-ALGO4-DESIGN v0.3 §3.2",
        pair_max_skew_sec=5.0,
        pair_max_skew_sec_provenance="P8-RECORDER-NO-SIDE-DESIGN v0.1 §3.1",
        latency_ms=150,
        latency_ms_provenance="P8-T8-ALGO4-DESIGN v0.3 §4.2",
        heartbeat_timeout_sec=25.0,
        heartbeat_timeout_sec_provenance="configs/passive_book_recorder.example.yaml#L19",
        rest_fallback_interval_sec=5.0,
        rest_fallback_interval_sec_provenance="configs/passive_book_recorder.example.yaml#L20",
        enable_cross_side_split_routing=True,
        cross_side_split_routing_provenance="P8-RECORDER-NO-SIDE-DESIGN v0.1 §3.2",
    )


def build_stub_forecast_v11(
    *,
    station_id: str = "KORD",
    target_date_str: str = "2026-11-21",
    issue_ts_utc: datetime,
    settle_close_utc: datetime,
    bin_probs: Optional[Tuple[BinProbV11, ...]] = None,
) -> ForecastDistributionSnapshotV11:
    if bin_probs is None:
        bin_probs = (
            BinProbV11("bin-57below", "57°F or below", None, 57, 0.25),
            BinProbV11("bin-58-59", "58-59°F", 58, 59, 0.55),
            BinProbV11("bin-60plus", "60°F or above", 60, None, 0.20),
        )
    fc_id = compute_record_sha256({"st": station_id, "issue": issue_ts_utc.isoformat()})[:16]
    return ForecastDistributionSnapshotV11(
        schema_version="p5.v1.1",
        forecast_id=f"fc-{fc_id}",
        issue_ts_utc=issue_ts_utc,
        station_id=station_id,
        target_date=date.fromisoformat(target_date_str),
        target_type="TMAX",
        gefs_lead_hours=12,
        tau_hours=max(0.0, (settle_close_utc - issue_ts_utc).total_seconds() / 3600.0),
        settle_close_utc=settle_close_utc,
        model_hash="stub-model-hash-v1",
        prior_mu0=58.2,
        prior_sigma0=2.1,
        family="gaussian",
        m_now_f=55.0,
        m_now_int_f=55,
        oracle_compliant=True,
        upstream_obs_fresh=True,
        is_bridge_active=True,
        p_stay_phys=0.05,
        p_bin_stay=0.05,
        bin_probs=bin_probs,
        sigma_delta_sample=0.02,
    )


def _build_two_sided_5859_samples(sid: str, t0: datetime) -> List[Tuple[MarketBookRecordEnvelope, Dict[str, Any]]]:
    specs = [
        (1, "tok-kord-5859-yes", "YES", t0, ((0.40, 30.0), (0.42, 40.0)), ((0.35, 25.0),)),
        (2, "tok-kord-5859-no", "NO", t0 + timedelta(seconds=1), ((0.66, 20.0),), ((0.64, 50.0), (0.62, 40.0))),
        (3, "tok-kord-5859-yes", "YES", t0 + timedelta(seconds=2), ((0.40, 20.0), (0.42, 40.0)), ((0.35, 25.0),)),
        (4, "tok-kord-5859-no", "NO", t0 + timedelta(seconds=2), ((0.66, 20.0),), ((0.64, 80.0),)),
    ]
    return [
        build_p4_v11_stub_envelope(
            session_id=sid, seq_id=seq, frame_seq=seq, token_id=tok,
            market_id="mkt-5859", condition_id="0xc5859", station_id="KORD",
            target_date="2026-11-21", bin_label="58-59°F", outcome=out,
            regime="two_sided", recv_ts_utc=ts, asks=asks, bids=bids,
        )
        for seq, tok, out, ts, asks, bids in specs
    ]


def _build_single_side_and_skew_samples(sid: str, t0: datetime) -> List[Tuple[MarketBookRecordEnvelope, Dict[str, Any]]]:
    return [
        build_p4_v11_stub_envelope(
            session_id=sid, seq_id=5, frame_seq=5, token_id="tok-kord-60p-yes",
            market_id="mkt-60p", condition_id="0xc60p", station_id="KORD",
            target_date="2026-11-21", bin_label="60°F or above", outcome="YES",
            regime="bid_only", recv_ts_utc=t0, asks=(), bids=((0.02, 50.0),), tick_size=0.001,
        ),
        build_p4_v11_stub_envelope(
            session_id=sid, seq_id=6, frame_seq=6, token_id="tok-kord-60p-no",
            market_id="mkt-60p", condition_id="0xc60p", station_id="KORD",
            target_date="2026-11-21", bin_label="60°F or above", outcome="NO",
            regime="ask_only", recv_ts_utc=t0, asks=((0.985, 60.0),), bids=(), tick_size=0.001,
        ),
        build_p4_v11_stub_envelope(
            session_id=sid, seq_id=7, frame_seq=7, token_id="tok-kord-57b-yes",
            market_id="mkt-57b", condition_id="0xc57b", station_id="KORD",
            target_date="2026-11-21", bin_label="57°F or below", outcome="YES",
            regime="ask_only", recv_ts_utc=t0, asks=((0.10, 120.0),), bids=(),
        ),
        build_p4_v11_stub_envelope(
            session_id=sid, seq_id=8, frame_seq=8, token_id="tok-kord-57b-no",
            market_id="mkt-57b", condition_id="0xc57b", station_id="KORD",
            target_date="2026-11-21", bin_label="57°F or below", outcome="NO",
            regime="bid_only", recv_ts_utc=t0 - timedelta(seconds=12), asks=(), bids=((0.92, 90.0),),
        ),
        build_p4_v11_stub_envelope(
            session_id=sid, seq_id=9, frame_seq=9, token_id="tok-kord-rescue-yes",
            market_id="mkt-rescue", condition_id="0xcres", station_id="KORD",
            target_date="2026-11-21", bin_label="56-57°F", outcome="YES",
            regime="bid_only", recv_ts_utc=t0, asks=(), bids=((0.20, 40.0),),
        ),
        build_p4_v11_stub_envelope(
            session_id=sid, seq_id=10, frame_seq=10, token_id="tok-kord-rescue-no",
            market_id="mkt-rescue", condition_id="0xcres", station_id="KORD",
            target_date="2026-11-21", bin_label="56-57°F", outcome="NO",
            regime="two_sided", recv_ts_utc=t0, asks=((0.72, 20.0),), bids=((0.68, 100.0),),
        ),
    ]


def generate_regression_stub_bundle(base_ts: Optional[datetime] = None) -> Dict[str, Any]:
    """Generate comprehensive P4 v1.1 + DualSideBookPair + cross-view replay stub dataset."""
    t0 = base_ts or datetime(2026, 11, 21, 14, 0, 0, tzinfo=timezone.utc)
    sid = "sess-stub-reg-01"
    samples = _build_two_sided_5859_samples(sid, t0) + _build_single_side_and_skew_samples(sid, t0)
    return {
        "session_id": sid,
        "base_ts": t0,
        "envelopes": [env for env, _ in samples],
        "raw_dicts": [raw for _, raw in samples],
    }


__all__ = [
    "build_p4_v11_stub_envelope",
    "build_stub_forecast_v11",
    "default_stub_trading_config",
    "generate_regression_stub_bundle",
]
