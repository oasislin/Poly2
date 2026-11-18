"""Read-only M3 passive orderbook recorder implementing P4 snapshots and P13 JSONL envelopes.

Protocol anchors:
- `项目方案 (v3.0) §8.2 P13 / §8.4 P4`
- `P8-T2-M7-LOGGING v1.0 §2.6 & §3`
- `P8-FACTS-LEDGER v0.2`

Strict safety boundary: read-only market data & Gamma metadata only.
Never holds private keys, never signs orders, never submits orders,
and never modifies any file inside `src/pricing/` F-2 locked zone.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import queue
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple
import uuid

import requests

from src.pricing.penetration_probe import AskBook

logger = logging.getLogger(__name__)

CaptureMode = Literal["PASSIVE_RECORD", "LIVE_STREAM", "PAPER_SHADOW"]
DataSource = Literal["CLOB_WS", "CLOB_REST"]
FeeRateProvenance = Literal["API_RUNTIME", "FACT-001"]

CITY_BY_STATION: Dict[str, str] = {
    "KORD": "Chicago",
    "KLGA": "NYC",
    "KATL": "Atlanta",
    "KDAL": "Dallas",
    "KSEA": "Seattle",
    "KLAX": "Los Angeles",
    "KHOU": "Houston",
    "KMIA": "Miami",
    "KSFO": "San Francisco",
    "KAUS": "Austin",
}


class InvalidBidBookError(ValueError):
    """Raised when BidBook fails strict descending price / bounds invariants."""


@dataclass(frozen=True)
class BidBook:
    """Symmetric read-only bid book holding (price, size) sorted descending (best bid first)."""

    levels: Tuple[Tuple[float, float], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.levels, (tuple, list)) or len(self.levels) == 0:
            raise InvalidBidBookError("BidBook levels cannot be empty")
        normalized: List[Tuple[float, float]] = []
        for idx, lvl in enumerate(self.levels):
            if not isinstance(lvl, (tuple, list)) or len(lvl) != 2:
                raise InvalidBidBookError(f"Bid level {idx} must be (price, size)")
            price, size = lvl
            if isinstance(price, bool) or not (0.0 < float(price) < 1.0):
                raise InvalidBidBookError(f"Bid level {idx} price must be in (0, 1)")
            if isinstance(size, bool) or float(size) <= 0.0:
                raise InvalidBidBookError(f"Bid level {idx} size must be > 0")
            normalized.append((float(price), float(size)))

        for idx in range(len(normalized) - 1):
            if normalized[idx][0] <= normalized[idx + 1][0]:
                raise InvalidBidBookError(
                    "BidBook levels must be strictly decreasing (best bid first)"
                )
        object.__setattr__(self, "levels", tuple(normalized))

    @property
    def best_price(self) -> float:
        return self.levels[0][0]


@dataclass(frozen=True)
class FieldMappingConfig:
    """Centralized field-mapping configuration isolating external API schema from P4/P13."""

    tick_size_key: str = "tick_size"
    gamma_tick_size_key: str = "orderPriceMinTickSize"
    min_order_size_key: str = "min_order_size"
    gamma_min_order_size_key: str = "orderMinSize"
    fee_schedule_key: str = "feeSchedule"
    fee_rate_field: str = "rate"
    fees_enabled_key: str = "feesEnabled"
    neg_risk_key: str = "neg_risk"
    gamma_neg_risk_key: str = "negRisk"
    default_fee_rate_fallback: float = 0.05
    default_min_order_size_shares: float = 5.0
    min_notional_usd_default: Optional[float] = 1.0


@dataclass(frozen=True)
class MarketSubscriptionMeta:
    """Mutable-refreshed read-only market metadata cache paired with each subscribed token."""

    token_id: str
    market_id: str
    condition_id: str
    station_id: str
    target_date: str
    bin_label: str
    tick_size: float
    min_order_size_shares: float
    min_notional_usd: Optional[float]
    fee_rate: float
    fee_rate_provenance: FeeRateProvenance
    neg_risk: Optional[bool]


@dataclass(frozen=True)
class RecorderConfig:
    """Configuration for read-only passive orderbook recording."""

    stations: Tuple[str, ...] = ("KORD", "KMIA")
    capture_mode: CaptureMode = "PASSIVE_RECORD"
    output_root: str = "data/market_recordings"
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    clob_rest_base_url: str = "https://clob.polymarket.com"
    clob_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    ws_disable_system_proxy: bool = True
    heartbeat_interval_sec: float = 10.0
    heartbeat_timeout_sec: float = 25.0
    rest_fallback_interval_sec: float = 5.0
    reconnect_backoff_sec: Tuple[float, ...] = (1.0, 2.0, 5.0, 10.0)
    field_mapping: FieldMappingConfig = field(default_factory=FieldMappingConfig)

    @classmethod
    def from_yaml_dict(cls, raw: Mapping[str, Any]) -> "RecorderConfig":
        fm_raw = raw.get("field_mapping") or {}
        fm = FieldMappingConfig(**fm_raw)
        rec = raw.get("recording") or {}
        ep = raw.get("endpoints") or {}
        return cls(
            stations=tuple(raw.get("stations") or ("KORD", "KMIA")),
            capture_mode=rec.get("capture_mode", "PASSIVE_RECORD"),
            output_root=str(rec.get("output_root", "data/market_recordings")),
            gamma_base_url=str(ep.get("gamma_base_url", "https://gamma-api.polymarket.com")),
            clob_rest_base_url=str(ep.get("clob_rest_base_url", "https://clob.polymarket.com")),
            clob_ws_url=str(ep.get("clob_ws_url", "wss://ws-subscriptions-clob.polymarket.com/ws/market")),
            ws_disable_system_proxy=bool(ep.get("ws_disable_system_proxy", True)),
            heartbeat_interval_sec=float(rec.get("heartbeat_interval_sec", 10.0)),
            heartbeat_timeout_sec=float(rec.get("heartbeat_timeout_sec", 25.0)),
            rest_fallback_interval_sec=float(rec.get("rest_fallback_interval_sec", 5.0)),
            reconnect_backoff_sec=tuple(float(x) for x in rec.get("reconnect_backoff_sec", (1.0, 2.0, 5.0, 10.0))),
            field_mapping=fm,
        )


@dataclass(frozen=True)
class MarketBookSnapshot:
    """P4 MarketBookSnapshot carrying locked AskBook wrapper, optional BidBook, and metadata."""

    token_id: str
    market_id: str
    condition_id: str
    snapshot_ts_utc: Optional[datetime]
    recv_ts_utc: datetime
    ask_book: AskBook
    bid_book: Optional[BidBook]
    best_bid: Optional[float]
    bid_top10: Tuple[Tuple[float, float], ...]
    tick_size: float
    min_order_size_shares: float
    min_notional_usd: Optional[float]
    fee_rate: float
    fee_rate_provenance: FeeRateProvenance
    neg_risk: Optional[bool]
    data_source: DataSource
    frame_seq: int

    def to_serializable_dict(self) -> Dict[str, Any]:
        return {
            "token_id": self.token_id,
            "market_id": self.market_id,
            "condition_id": self.condition_id,
            "snapshot_ts_utc": (
                self.snapshot_ts_utc.isoformat() if self.snapshot_ts_utc is not None else None
            ),
            "recv_ts_utc": self.recv_ts_utc.isoformat(),
            "frame_seq": self.frame_seq,
            "data_source": self.data_source,
            "tick_size": self.tick_size,
            "min_order_size_shares": self.min_order_size_shares,
            "min_notional_usd": self.min_notional_usd,
            "fee_rate": self.fee_rate,
            "fee_rate_provenance": self.fee_rate_provenance,
            "neg_risk": self.neg_risk,
            "best_bid": self.best_bid,
            "asks": [[p, s] for p, s in self.ask_book.levels],
            "bids": [[p, s] for p, s in self.bid_book.levels] if self.bid_book is not None else [],
            "bid_top10": [[p, s] for p, s in self.bid_top10],
        }


def compute_record_sha256(record_without_hash: Mapping[str, Any]) -> str:
    """Compute canonical SHA256 over compact sorted JSON matching P8-T2-M7-LOGGING §1.4."""
    canonical = json.dumps(
        record_without_hash,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class MarketBookRecordEnvelope:
    """P13 envelope wrapping a single P4 snapshot for both M7 audit and P18 paper replay."""

    schema_version: str
    seq_id: int
    session_id: str
    capture_mode: CaptureMode
    gap_detected: bool
    gap_reason: Optional[str]
    recorded_ts_utc: datetime
    station_id: str
    target_date: str
    bin_label: str
    payload: MarketBookSnapshot

    def to_json_line(self) -> str:
        base: Dict[str, Any] = {
            "schema_version": self.schema_version,
            "seq_id": self.seq_id,
            "session_id": self.session_id,
            "capture_mode": self.capture_mode,
            "gap_detected": self.gap_detected,
            "gap_reason": self.gap_reason,
            "recorded_ts_utc": self.recorded_ts_utc.isoformat(),
            "station_id": self.station_id,
            "target_date": self.target_date,
            "bin_label": self.bin_label,
            "payload": self.payload.to_serializable_dict(),
        }
        base["record_sha256"] = compute_record_sha256(base)
        return json.dumps(base, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _parse_exchange_timestamp(raw_ts: Any) -> Optional[datetime]:
    """Parse exchange epoch ms or ISO timestamp strictly; return None without fabrication."""
    if raw_ts is None or raw_ts == "":
        return None
    try:
        if isinstance(raw_ts, (int, float)) or (isinstance(raw_ts, str) and raw_ts.isdigit()):
            val = float(raw_ts)
            if val > 1e12:
                val /= 1000.0
            return datetime.fromtimestamp(val, tz=timezone.utc)
        if isinstance(raw_ts, str):
            return datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None
    return None


def _normalize_levels(raw_levels: Iterable[Any], reverse: bool) -> List[Tuple[float, float]]:
    """Aggregate/deduplicate and sort raw CLOB price levels cleanly."""
    merged: Dict[float, float] = {}
    for entry in raw_levels:
        if isinstance(entry, Mapping):
            p_raw, s_raw = entry.get("price"), entry.get("size")
        elif isinstance(entry, (tuple, list)) and len(entry) >= 2:
            p_raw, s_raw = entry[0], entry[1]
        else:
            continue
        if p_raw is None or s_raw is None:
            continue
        p = float(p_raw)
        s = float(s_raw)
        if not (0.0 < p < 1.0) or s <= 0.0:
            continue
        merged[p] = merged.get(p, 0.0) + s
    return sorted(merged.items(), key=lambda item: item[0], reverse=reverse)


def extract_fee_rate(
    gamma_market: Mapping[str, Any],
    mapping: FieldMappingConfig,
) -> Tuple[float, FeeRateProvenance]:
    """Resolve fee_rate using D1 authoritative source (Gamma feeSchedule.rate -> FACT-001)."""
    schedule = gamma_market.get(mapping.fee_schedule_key)
    fees_enabled = gamma_market.get(mapping.fees_enabled_key)
    if fees_enabled is True and isinstance(schedule, Mapping):
        raw_rate = schedule.get(mapping.fee_rate_field)
        if raw_rate is not None:
            try:
                rate = float(raw_rate)
                if rate >= 0.0:
                    return rate, "API_RUNTIME"
            except (TypeError, ValueError):
                pass
    return float(mapping.default_fee_rate_fallback), "FACT-001"


def build_p4_snapshot_from_raw(
    raw_frame: Mapping[str, Any],
    meta: MarketSubscriptionMeta,
    mapping: FieldMappingConfig,
    data_source: DataSource,
    frame_seq: int,
    recv_ts_utc: Optional[datetime] = None,
) -> MarketBookSnapshot:
    """Build validated P4 MarketBookSnapshot from a raw CLOB REST `/book` or WS `book` frame."""
    recv_ts = recv_ts_utc or datetime.now(timezone.utc)
    snapshot_ts = _parse_exchange_timestamp(raw_frame.get("timestamp"))

    raw_asks = raw_frame.get("asks") or []
    asks_sorted = _normalize_levels(raw_asks, reverse=False)
    if not asks_sorted:
        raise ValueError(f"Empty or invalid ask side for token {meta.token_id}")
    ask_book = AskBook(levels=tuple(asks_sorted))

    raw_bids = raw_frame.get("bids") or []
    bids_sorted = _normalize_levels(raw_bids, reverse=True)
    bid_book = BidBook(levels=tuple(bids_sorted)) if bids_sorted else None
    best_bid = bid_book.best_price if bid_book is not None else None
    bid_top10 = tuple(bids_sorted[:10])

    tick_raw = raw_frame.get(mapping.tick_size_key)
    tick_size = float(tick_raw) if tick_raw is not None else meta.tick_size

    min_sz_raw = raw_frame.get(mapping.min_order_size_key)
    min_order_size_shares = (
        float(min_sz_raw) if min_sz_raw is not None else meta.min_order_size_shares
    )

    neg_risk_raw = raw_frame.get(mapping.neg_risk_key)
    neg_risk = bool(neg_risk_raw) if neg_risk_raw is not None else meta.neg_risk

    return MarketBookSnapshot(
        token_id=meta.token_id,
        market_id=meta.market_id,
        condition_id=meta.condition_id,
        snapshot_ts_utc=snapshot_ts,
        recv_ts_utc=recv_ts,
        ask_book=ask_book,
        bid_book=bid_book,
        best_bid=best_bid,
        bid_top10=bid_top10,
        tick_size=tick_size,
        min_order_size_shares=min_order_size_shares,
        min_notional_usd=meta.min_notional_usd,
        fee_rate=meta.fee_rate,
        fee_rate_provenance=meta.fee_rate_provenance,
        neg_risk=neg_risk,
        data_source=data_source,
        frame_seq=frame_seq,
    )


class AsyncJsonlSink:
    """Non-blocking daemon writer writing P13 JSONL envelopes by day/session/station."""

    def __init__(self, output_root: Path, capture_mode: CaptureMode, session_id: str) -> None:
        self._output_root = Path(output_root)
        self._capture_mode = capture_mode
        self._session_id = session_id
        self._queue: queue.Queue[Optional[Tuple[Path, str]]] = queue.Queue()
        self._written_count = 0
        self._closed = False
        self._thread = threading.Thread(target=self._worker, name="p13-jsonl-writer", daemon=True)
        self._thread.start()

    @property
    def written_count(self) -> int:
        return self._written_count

    def resolve_path(self, station_id: str, recorded_ts_utc: datetime) -> Path:
        day_dir = recorded_ts_utc.astimezone(timezone.utc).strftime("%Y-%m-%d")
        return (
            self._output_root
            / self._capture_mode
            / day_dir
            / self._session_id
            / f"p13_book_stream_{station_id}.jsonl"
        )

    def submit(self, envelope: MarketBookRecordEnvelope) -> Path:
        if self._closed:
            raise RuntimeError("AsyncJsonlSink is already closed")
        path = self.resolve_path(envelope.station_id, envelope.recorded_ts_utc)
        line = envelope.to_json_line()
        self._queue.put((path, line))
        return path

    def flush(self) -> None:
        self._queue.join()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._queue.put(None)
            self._thread.join(timeout=5.0)

    def _worker(self) -> None:
        handles: Dict[Path, Any] = {}
        try:
            while True:
                item = self._queue.get()
                try:
                    if item is None:
                        break
                    path, line = item
                    fh = handles.get(path)
                    if fh is None:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        fh = open(path, "a", encoding="utf-8", buffering=1)
                        handles[path] = fh
                    fh.write(line + "\n")
                    self._written_count += 1
                finally:
                    self._queue.task_done()
        finally:
            for fh in handles.values():
                try:
                    fh.flush()
                    fh.close()
                except Exception:
                    pass


class PassiveBookRecorder:
    """Read-only M3 collector orchestrating WS book/tick updates, gap tracking, REST fallback, and P13 sink."""

    def __init__(
        self,
        config: RecorderConfig,
        session_id: Optional[str] = None,
        http_session: Optional[requests.Session] = None,
    ) -> None:
        self.config = config
        self.session_id = session_id or f"rec-{uuid.uuid4().hex[:12]}"
        self._http = http_session or requests.Session()
        self._frame_seq = 0
        self._seq_id = 0
        self._pending_gap_reason: Optional[str] = None
        self._meta_by_token: Dict[str, MarketSubscriptionMeta] = {}
        self._sink = AsyncJsonlSink(
            output_root=Path(config.output_root),
            capture_mode=config.capture_mode,
            session_id=self.session_id,
        )

    @property
    def meta_by_token(self) -> Mapping[str, MarketSubscriptionMeta]:
        return self._meta_by_token

    def register_markets(self, metas: Sequence[MarketSubscriptionMeta]) -> None:
        for meta in metas:
            self._meta_by_token[meta.token_id] = meta

    def discover_active_temperature_markets(self, max_events_per_station: int = 3) -> List[MarketSubscriptionMeta]:
        """Discover active temperature markets from Gamma public-search using centralized mapping."""
        fm = self.config.field_mapping
        discovered: List[MarketSubscriptionMeta] = []
        for station in self.config.stations:
            city = CITY_BY_STATION.get(station)
            if not city:
                logger.warning("Skipping unknown station %s not in CITY_BY_STATION", station)
                continue
            resp = self._http.get(
                f"{self.config.gamma_base_url}/public-search",
                params={"q": f"Highest temperature in {city}", "limit_per_type": 8},
                timeout=15,
            )
            resp.raise_for_status()
            events = [e for e in (resp.json().get("events") or []) if not e.get("closed")]
            events.sort(key=lambda e: e.get("endDate") or "")
            for ev in events[:max_events_per_station]:
                for mkt in ev.get("markets") or []:
                    token_raw = mkt.get("clobTokenIds")
                    if not token_raw:
                        continue
                    token_ids = json.loads(token_raw) if isinstance(token_raw, str) else token_raw
                    if not token_ids:
                        continue
                    yes_token = str(token_ids[0])
                    fee_rate, fee_prov = extract_fee_rate(mkt, fm)
                    tick_val = mkt.get(fm.gamma_tick_size_key)
                    min_sz_val = mkt.get(fm.gamma_min_order_size_key)
                    neg_val = mkt.get(fm.gamma_neg_risk_key)
                    meta = MarketSubscriptionMeta(
                        token_id=yes_token,
                        market_id=str(mkt.get("id", "")),
                        condition_id=str(mkt.get("conditionId", "")),
                        station_id=station,
                        target_date=str(mkt.get("endDateIso") or (mkt.get("endDate") or "")[:10]),
                        bin_label=str(mkt.get("groupItemTitle") or ""),
                        tick_size=float(tick_val) if tick_val is not None else 0.01,
                        min_order_size_shares=(
                            float(min_sz_val)
                            if min_sz_val is not None
                            else fm.default_min_order_size_shares
                        ),
                        min_notional_usd=fm.min_notional_usd_default,
                        fee_rate=fee_rate,
                        fee_rate_provenance=fee_prov,
                        neg_risk=bool(neg_val) if neg_val is not None else None,
                    )
                    self._meta_by_token[yes_token] = meta
                    discovered.append(meta)
        return discovered

    def mark_gap(self, reason: str) -> None:
        """Mark an explicit transport/heartbeat gap to be stamped on the next P13 envelope."""
        self._pending_gap_reason = reason

    def handle_ws_message(
        self,
        raw_message: Mapping[str, Any],
        recv_ts_utc: Optional[datetime] = None,
    ) -> Optional[MarketBookRecordEnvelope]:
        """Process a single decoded WS JSON frame (`book` or `tick_size_change`)."""
        event_type = raw_message.get("event_type") or raw_message.get("type")
        if event_type == "tick_size_change":
            asset_id = str(raw_message.get("asset_id") or "")
            new_tick = raw_message.get("new_tick_size") or raw_message.get("tick_size")
            if asset_id in self._meta_by_token and new_tick is not None:
                old = self._meta_by_token[asset_id]
                self._meta_by_token[asset_id] = MarketSubscriptionMeta(
                    token_id=old.token_id,
                    market_id=old.market_id,
                    condition_id=old.condition_id,
                    station_id=old.station_id,
                    target_date=old.target_date,
                    bin_label=old.bin_label,
                    tick_size=float(new_tick),
                    min_order_size_shares=old.min_order_size_shares,
                    min_notional_usd=old.min_notional_usd,
                    fee_rate=old.fee_rate,
                    fee_rate_provenance=old.fee_rate_provenance,
                    neg_risk=old.neg_risk,
                )
            return None

        if event_type != "book":
            return None

        token_id = str(raw_message.get("asset_id") or raw_message.get("token_id") or "")
        meta = self._meta_by_token.get(token_id)
        if meta is None:
            return None

        return self.record_raw_book_frame(
            raw_frame=raw_message,
            meta=meta,
            data_source="CLOB_WS",
            recv_ts_utc=recv_ts_utc,
        )

    def poll_rest_fallback_once(self) -> List[MarketBookRecordEnvelope]:
        """Fetch CLOB REST `/book` for registered tokens (honestly labeled `CLOB_REST`)."""
        envelopes: List[MarketBookRecordEnvelope] = []
        for token_id, meta in self._meta_by_token.items():
            try:
                resp = self._http.get(
                    f"{self.config.clob_rest_base_url}/book",
                    params={"token_id": token_id},
                    timeout=10,
                )
                resp.raise_for_status()
                env = self.record_raw_book_frame(
                    raw_frame=resp.json(),
                    meta=meta,
                    data_source="CLOB_REST",
                )
                if env is not None:
                    envelopes.append(env)
            except Exception as exc:
                self.mark_gap(f"REST_POLL_ERROR:{type(exc).__name__}")
                logger.warning("REST fallback failed for token=%s: %s", token_id, exc)
        return envelopes

    def record_raw_book_frame(
        self,
        raw_frame: Mapping[str, Any],
        meta: MarketSubscriptionMeta,
        data_source: DataSource,
        recv_ts_utc: Optional[datetime] = None,
    ) -> Optional[MarketBookRecordEnvelope]:
        now = recv_ts_utc or datetime.now(timezone.utc)
        self._frame_seq += 1
        try:
            snap = build_p4_snapshot_from_raw(
                raw_frame=raw_frame,
                meta=meta,
                mapping=self.config.field_mapping,
                data_source=data_source,
                frame_seq=self._frame_seq,
                recv_ts_utc=now,
            )
        except ValueError as exc:
            self.mark_gap(f"INVALID_OR_EMPTY_BOOK:{exc}")
            return None

        self._seq_id += 1
        gap_reason = self._pending_gap_reason
        self._pending_gap_reason = None
        envelope = MarketBookRecordEnvelope(
            schema_version="p13.v1",
            seq_id=self._seq_id,
            session_id=self.session_id,
            capture_mode=self.config.capture_mode,
            gap_detected=gap_reason is not None,
            gap_reason=gap_reason,
            recorded_ts_utc=now,
            station_id=meta.station_id,
            target_date=meta.target_date,
            bin_label=meta.bin_label,
            payload=snap,
        )
        self._sink.submit(envelope)
        return envelope

    async def run_ws_loop(self, stop_event: Optional[asyncio.Event] = None) -> None:
        """Connect to CLOB Market WS with heartbeat timeout detection, reconnect, and REST fallback."""
        import websockets

        token_ids = list(self._meta_by_token.keys())
        if not token_ids:
            raise ValueError("No markets registered before run_ws_loop")

        backoff_idx = 0
        while stop_event is None or not stop_event.is_set():
            try:
                connect_kwargs: Dict[str, Any] = {"open_timeout": 10, "close_timeout": 5}
                if self.config.ws_disable_system_proxy:
                    connect_kwargs["proxy"] = None
                async with websockets.connect(self.config.clob_ws_url, **connect_kwargs) as ws:
                    await ws.send(json.dumps({"assets_ids": token_ids, "type": "market"}))
                    backoff_idx = 0
                    last_ping = time.monotonic()
                    while stop_event is None or not stop_event.is_set():
                        now_mono = time.monotonic()
                        if now_mono - last_ping >= self.config.heartbeat_interval_sec:
                            await ws.send("PING")
                            last_ping = now_mono
                        try:
                            raw = await asyncio.wait_for(
                                ws.recv(),
                                timeout=self.config.heartbeat_timeout_sec,
                            )
                        except asyncio.TimeoutError:
                            self.mark_gap("WS_HEARTBEAT_TIMEOUT")
                            self.poll_rest_fallback_once()
                            raise ConnectionError("WebSocket heartbeat timeout triggered REST fallback")

                        if raw == "PONG":
                            continue
                        decoded = json.loads(raw)
                        frames = decoded if isinstance(decoded, list) else [decoded]
                        for frame in frames:
                            if isinstance(frame, Mapping):
                                self.handle_ws_message(frame)
            except Exception as exc:
                if stop_event is not None and stop_event.is_set():
                    break
                if self._pending_gap_reason is None:
                    self.mark_gap(f"WS_RECONNECT:{type(exc).__name__}")
                self.poll_rest_fallback_once()
                delay = self.config.reconnect_backoff_sec[
                    min(backoff_idx, len(self.config.reconnect_backoff_sec) - 1)
                ]
                backoff_idx += 1
                await asyncio.sleep(delay)

    def flush_and_close(self) -> None:
        self._sink.flush()
        self._sink.close()


__all__ = [
    "AsyncJsonlSink",
    "BidBook",
    "CITY_BY_STATION",
    "CaptureMode",
    "DataSource",
    "FeeRateProvenance",
    "FieldMappingConfig",
    "InvalidBidBookError",
    "MarketBookRecordEnvelope",
    "MarketBookSnapshot",
    "MarketSubscriptionMeta",
    "PassiveBookRecorder",
    "RecorderConfig",
    "build_p4_snapshot_from_raw",
    "compute_record_sha256",
    "extract_fee_rate",
]
