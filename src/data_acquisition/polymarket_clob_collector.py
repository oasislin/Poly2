"""
Polymarket CLOB Read-Only Data Ingestion Module (Phase 2 Wave 3 / W3-A).
Governed by docs/w3_polymarket_ingestion_preregistration.md Rev.1.0 (Work Order P7-W3-TASK1-AUTH-001).

Implements:
1. Market Discovery & Daily Subscription Checklist (C-1)
2. Periodic Snapshot Scheduler: Baseline 60m (A-1) + Settlement Probe T-12h/15m (A-2) with official T-0 (A-3)
3. Conservative Orderbook Pricing: Best Ask / Best Bid (B-1), NO_QUOTE handling (B-2), raw depth recording (B-5)
4. Data Provenance Tagging: DATA_PROVENANCE = "POLYMARKET_LIVE_CLOB" (E-2) & PROB_STATIC reservation (A-4)
5. Zero Authentication & Zero Trading Calls (C5 / E-1)
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
import requests

logger = logging.getLogger(__name__)

# Mandatory Data Provenance Constant (Rev.1.0 E-2)
DATA_PROVENANCE_LIVE = "POLYMARKET_LIVE_CLOB"
DATA_PROVENANCE_SYNTHETIC = "SYNTHETIC_INJECTED_REPLAY"

# Default Endpoints
GAMMA_API_BASE_URL = "https://gamma-api.polymarket.com"
CLOB_API_BASE_URL = "https://clob.polymarket.com"

# Station mappings for weather markets
KNOWN_CITY_TO_STATION: Dict[str, str] = {
    "chicago": "KORD",
    "miami": "KMIA",
    "nyc": "KLGA",
    "new york": "KLGA",
    "atlanta": "KATL",
    "dallas": "KDFW",
    "los angeles": "KLAX",
    "seattle": "KSEA",
    "san francisco": "KSFO",
    "houston": "KIAH",
    "denver": "KBKF",
    "austin": "KAUS",
    "london": "EGLL",
}


@dataclass(frozen=True)
class OrderBookLevel:
    """Single price-quantity tier in a CLOB orderbook."""
    price: float
    size: float


@dataclass(frozen=True)
class CLOBQuote:
    """
    Conservative side quote extraction for a discrete token.
    B-1: Conservative execution price (Ask for buy, Bid for sell).
    B-2: Missing side marked as NO_QUOTE.
    B-5: Raw best level depth recorded for downstream minimum size filter.
    """
    token_id: str
    best_ask: Optional[float]
    best_bid: Optional[float]
    mid_price: Optional[float]
    best_ask_size: float
    best_bid_size: float
    quote_status: str  # 'NORMAL', 'NO_QUOTE', 'EMPTY_BOOK'
    raw_asks: List[OrderBookLevel] = field(default_factory=list)
    raw_bids: List[OrderBookLevel] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_id": self.token_id,
            "best_ask": self.best_ask,
            "best_bid": self.best_bid,
            "mid_price": self.mid_price,
            "best_ask_size": self.best_ask_size,
            "best_bid_size": self.best_bid_size,
            "quote_status": self.quote_status,
            "raw_asks": [{"price": lvl.price, "size": lvl.size} for lvl in self.raw_asks],
            "raw_bids": [{"price": lvl.price, "size": lvl.size} for lvl in self.raw_bids],
        }


@dataclass(frozen=True)
class MarketTokenBracket:
    """Discrete temperature contract bracket and token identifier."""
    token_id: str
    bracket_label: str
    outcome: str  # Usually 'Yes' or 'No'
    condition_id: str


@dataclass(frozen=True)
class PolymarketTemperatureMarket:
    """
    Strongly-typed metadata for an active temperature prediction market.
    A-3: official_settlement_time is canonical T-0 from Polymarket contract specification.
    """
    event_id: str
    slug: str
    title: str
    city: str
    station_id: Optional[str]
    target_date_str: str
    official_settlement_time: datetime
    brackets: List[MarketTokenBracket] = field(default_factory=list)
    raw_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "slug": self.slug,
            "title": self.title,
            "city": self.city,
            "station_id": self.station_id,
            "target_date_str": self.target_date_str,
            "official_settlement_time_iso": self.official_settlement_time.isoformat(),
            "brackets": [
                {
                    "token_id": b.token_id,
                    "bracket_label": b.bracket_label,
                    "outcome": b.outcome,
                    "condition_id": b.condition_id,
                }
                for b in self.brackets
            ],
            "raw_metadata": self.raw_metadata,
        }


@dataclass(frozen=True)
class SnapshotRecord:
    """
    Standardized market snapshot ledger entry.
    E-2: Explicit data_provenance mandatory.
    A-4: prob_static_flag pre-registered for Phase 2 Wave 3 evaluation.
    """
    snapshot_id: str
    timestamp_iso: str
    snapshot_layer: str  # 'BASELINE_60M' or 'SETTLEMENT_PROBE_15M'
    data_provenance: str  # Must equal DATA_PROVENANCE_LIVE
    market_slug: str
    station_id: Optional[str]
    settlement_time_iso: str
    hours_to_settlement: float
    quotes: Dict[str, CLOBQuote] = field(default_factory=dict)
    prob_static_flag: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp_iso": self.timestamp_iso,
            "snapshot_layer": self.snapshot_layer,
            "data_provenance": self.data_provenance,
            "market_slug": self.market_slug,
            "station_id": self.station_id,
            "settlement_time_iso": self.settlement_time_iso,
            "hours_to_settlement": self.hours_to_settlement,
            "quotes": {tid: q.to_dict() for tid, q in self.quotes.items()},
            "prob_static_flag": self.prob_static_flag,
            "metadata": self.metadata,
        }


def parse_iso_datetime(dt_str: str) -> datetime:
    """Robust ISO 8601 string parsing returning timezone-aware UTC datetime."""
    if not dt_str:
        return datetime.now(timezone.utc)
    # Normalize Z to +00:00
    cleaned = dt_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception as e:
        logger.warning(f"Failed to parse datetime '{dt_str}', using fallback: {e}")
        return datetime.now(timezone.utc)


def calculate_snapshot_cadence(settlement_time: datetime, current_time: datetime) -> str:
    """
    Determine sampling cadence based on distance to official settlement time T-0.
    A-1: Baseline 60m frequency.
    A-2: Settlement probe 15m frequency starting from T-12h.
    A-3: T-0 is strictly the official market settlement timestamp.
    """
    delta_seconds = (settlement_time - current_time).total_seconds()
    hours_left = delta_seconds / 3600.0

    if hours_left < 0.0:
        return "POST_SETTLEMENT"
    if hours_left <= 12.0:
        return "SETTLEMENT_PROBE_15M"
    return "BASELINE_60M"


def parse_order_book_payload(token_id: str, payload: Dict[str, Any]) -> CLOBQuote:
    """
    Parse raw CLOB /book JSON payload into strongly-typed conservative CLOBQuote.
    B-1: Buy side uses lowest ask (best_ask), sell side uses highest bid (best_bid).
         Midpoint is only calculated for monitoring/divergence, never for EV.
    B-2: If either ask or bid is missing, quote_status = 'NO_QUOTE'.
    B-5: Raw best level size recorded.
    """
    raw_asks_data = payload.get("asks", [])
    raw_bids_data = payload.get("bids", [])

    parsed_asks: List[OrderBookLevel] = []
    for item in raw_asks_data:
        try:
            p = float(item.get("price", 0.0))
            s = float(item.get("size", 0.0))
            if s > 0:
                parsed_asks.append(OrderBookLevel(price=p, size=s))
        except (ValueError, TypeError):
            continue

    parsed_bids: List[OrderBookLevel] = []
    for item in raw_bids_data:
        try:
            p = float(item.get("price", 0.0))
            s = float(item.get("size", 0.0))
            if s > 0:
                parsed_bids.append(OrderBookLevel(price=p, size=s))
        except (ValueError, TypeError):
            continue

    # Sort asks ascending by price (lowest ask is best ask)
    parsed_asks.sort(key=lambda lvl: lvl.price)
    # Sort bids descending by price (highest bid is best bid)
    parsed_bids.sort(key=lambda lvl: lvl.price, reverse=True)

    has_asks = len(parsed_asks) > 0
    has_bids = len(parsed_bids) > 0

    if not has_asks and not has_bids:
        return CLOBQuote(
            token_id=token_id,
            best_ask=None,
            best_bid=None,
            mid_price=None,
            best_ask_size=0.0,
            best_bid_size=0.0,
            quote_status="EMPTY_BOOK",
            raw_asks=[],
            raw_bids=[],
        )

    best_ask = parsed_asks[0].price if has_asks else None
    best_ask_size = parsed_asks[0].size if has_asks else 0.0

    best_bid = parsed_bids[0].price if has_bids else None
    best_bid_size = parsed_bids[0].size if has_bids else 0.0

    if not has_asks or not has_bids:
        # B-2: Missing one side -> NO_QUOTE
        return CLOBQuote(
            token_id=token_id,
            best_ask=best_ask,
            best_bid=best_bid,
            mid_price=None,
            best_ask_size=best_ask_size,
            best_bid_size=best_bid_size,
            quote_status="NO_QUOTE",
            raw_asks=parsed_asks,
            raw_bids=parsed_bids,
        )

    # Both sides present: NORMAL quote
    mid_price = (best_ask + best_bid) / 2.0
    return CLOBQuote(
        token_id=token_id,
        best_ask=best_ask,
        best_bid=best_bid,
        mid_price=mid_price,
        best_ask_size=best_ask_size,
        best_bid_size=best_bid_size,
        quote_status="NORMAL",
        raw_asks=parsed_asks,
        raw_bids=parsed_bids,
    )


class PolymarketReadOnlyCLOBClient:
    """
    Public, Read-Only Client for Polymarket CLOB and Gamma APIs.
    C5 / E-1: Strictly zero private keys, zero authentication, zero order placement methods.
    """

    def __init__(
        self,
        clob_url: str = CLOB_API_BASE_URL,
        gamma_url: str = GAMMA_API_BASE_URL,
        session: Optional[requests.Session] = None,
        proxy: Optional[str] = None,
        timeout: int = 15,
    ):
        self.clob_url = clob_url.rstrip("/")
        self.gamma_url = gamma_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

        # Configure proxy if specified or environment set
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        elif "HTTP_PROXY" in os.environ or "HTTPS_PROXY" in os.environ:
            pass  # requests picks up environment automatically
        else:
            # Check for local default clash port 7897
            default_local_proxy = "http://127.0.0.1:7897"
            try:
                # Lightweight socket probe without logging error
                import socket
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.2)
                res = s.connect_ex(("127.0.0.1", 7897))
                s.close()
                if res == 0:
                    self.session.proxies.update({"http": default_local_proxy, "https": default_local_proxy})
            except Exception:
                pass

        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PolyPredict/1.0",
            "Accept": "application/json",
        })

    def fetch_order_book(self, token_id: str) -> CLOBQuote:
        """
        Fetch orderbook snapshot from CLOB public endpoint GET /book?token_id={token_id}.
        Conservative price and depth extracted via parse_order_book_payload.
        """
        url = f"{self.clob_url}/book"
        try:
            resp = self.session.get(url, params={"token_id": token_id}, timeout=self.timeout)
            if resp.status_code == 200:
                return parse_order_book_payload(token_id, resp.json())
            logger.warning(f"CLOB /book returned {resp.status_code} for token {token_id}")
            return CLOBQuote(
                token_id=token_id,
                best_ask=None,
                best_bid=None,
                mid_price=None,
                best_ask_size=0.0,
                best_bid_size=0.0,
                quote_status="NO_QUOTE",
            )
        except Exception as e:
            logger.error(f"Error fetching CLOB orderbook for token {token_id}: {e}")
            return CLOBQuote(
                token_id=token_id,
                best_ask=None,
                best_bid=None,
                mid_price=None,
                best_ask_size=0.0,
                best_bid_size=0.0,
                quote_status="NO_QUOTE",
            )

    def fetch_public_time(self) -> Optional[int]:
        """Fetch server time from CLOB public endpoint GET /time."""
        url = f"{self.clob_url}/time"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                return int(resp.text.strip())
        except Exception as e:
            logger.warning(f"Failed to fetch CLOB server time: {e}")
        return None

    def search_temperature_events(self, city: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search active temperature events for a given city via Gamma public-search."""
        url = f"{self.gamma_url}/public-search"
        params = {"q": f"highest temperature {city}", "limit_per_type": limit}
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code == 200:
                events = resp.json().get("events", [])
                return [
                    e for e in events
                    if e.get("active") and not e.get("closed")
                ]
        except Exception as e:
            logger.error(f"Error querying Gamma API for city '{city}': {e}")
        return []

    def fetch_event_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """Fetch detailed event specification by slug via Gamma API."""
        url = f"{self.gamma_url}/events/slug/{slug}"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"Error querying event by slug '{slug}': {e}")
        return None


class PolymarketCLOBCollector:
    """
    Orchestrates market discovery, snapshot ingestion, and standardized ledger persistence.
    Governed by Rev.1.0 specifications (P7-W3-TASK1-AUTH-001).
    """

    def __init__(
        self,
        client: Optional[PolymarketReadOnlyCLOBClient] = None,
        storage_base_dir: Optional[Path] = None,
    ):
        self.client = client or PolymarketReadOnlyCLOBClient()
        self.storage_base_dir = storage_base_dir or Path("data/clob")

    def discover_active_temperature_markets(
        self,
        cities: Optional[List[str]] = None,
    ) -> List[PolymarketTemperatureMarket]:
        """
        C-1: 拉取 Polymarket 活跃温度类合约清单，逐日落盘。
        Discovers all active temperature prediction markets matching monitored cities.
        """
        target_cities = cities or list(KNOWN_CITY_TO_STATION.keys())
        discovered_markets: List[PolymarketTemperatureMarket] = []
        seen_slugs = set()

        for city_raw in target_cities:
            city_lower = city_raw.lower()
            station_id = KNOWN_CITY_TO_STATION.get(city_lower)
            events = self.client.search_temperature_events(city_raw, limit=10)

            for ev in events:
                slug = ev.get("slug")
                if not slug or slug in seen_slugs:
                    continue
                seen_slugs.add(slug)

                # Fetch detailed event with market brackets
                detail = self.client.fetch_event_by_slug(slug)
                if not detail:
                    continue

                end_date_str = detail.get("endDate") or ev.get("endDate") or ""
                official_t0 = parse_iso_datetime(end_date_str)

                # Extract bracket tokens
                brackets: List[MarketTokenBracket] = []
                for m in detail.get("markets", []):
                    bracket_title = m.get("groupItemTitle") or m.get("question") or "Unknown"
                    cond_id = str(m.get("conditionId") or m.get("id") or "")
                    clob_token_ids_raw = m.get("clobTokenIds")

                    token_id = ""
                    if isinstance(clob_token_ids_raw, str):
                        try:
                            parsed_ids = json.loads(clob_token_ids_raw)
                            if parsed_ids:
                                token_id = str(parsed_ids[0])
                        except Exception:
                            pass
                    elif isinstance(clob_token_ids_raw, list) and clob_token_ids_raw:
                        token_id = str(clob_token_ids_raw[0])

                    if token_id:
                        brackets.append(
                            MarketTokenBracket(
                                token_id=token_id,
                                bracket_label=bracket_title,
                                outcome="Yes",
                                condition_id=cond_id,
                            )
                        )

                market = PolymarketTemperatureMarket(
                    event_id=str(detail.get("id", "")),
                    slug=slug,
                    title=detail.get("title", ""),
                    city=city_raw.capitalize(),
                    station_id=station_id,
                    target_date_str=end_date_str[:10] if end_date_str else "",
                    official_settlement_time=official_t0,
                    brackets=brackets,
                    raw_metadata=detail,
                )
                discovered_markets.append(market)

        return discovered_markets

    def save_subscription_manifest(
        self,
        markets: List[PolymarketTemperatureMarket],
        date_str: Optional[str] = None,
    ) -> Path:
        """
        C-1: Persist daily active temperature markets subscription checklist to disk.
        """
        manifest_date = date_str or datetime.now(timezone.utc).strftime("%Y%m%d")
        manifest_dir = self.storage_base_dir / "manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / f"subscription_manifest_{manifest_date}.json"

        manifest_payload = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "data_provenance": DATA_PROVENANCE_LIVE,
            "total_markets": len(markets),
            "markets": [m.to_dict() for m in markets],
        }

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_payload, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved daily subscription manifest ({len(markets)} markets) to {manifest_path}")
        return manifest_path

    def collect_market_snapshot(
        self,
        market: PolymarketTemperatureMarket,
        now_utc: Optional[datetime] = None,
    ) -> SnapshotRecord:
        """
        Collect a point-in-time orderbook snapshot across all brackets of a market.
        A-1 / A-2: Cadence determined by distance to official T-0.
        E-2: Explicit DATA_PROVENANCE_LIVE stamped.
        A-4: prob_static_flag pre-registered.
        """
        current_time = now_utc or datetime.now(timezone.utc)
        cadence = calculate_snapshot_cadence(market.official_settlement_time, current_time)
        hours_left = (market.official_settlement_time - current_time).total_seconds() / 3600.0

        quotes: Dict[str, CLOBQuote] = {}
        for bracket in market.brackets:
            quote = self.client.fetch_order_book(bracket.token_id)
            quotes[bracket.token_id] = quote

        snapshot_id = f"{market.slug}_{current_time.strftime('%Y%m%dT%H%M%SZ')}"
        record = SnapshotRecord(
            snapshot_id=snapshot_id,
            timestamp_iso=current_time.isoformat(),
            snapshot_layer=cadence,
            data_provenance=DATA_PROVENANCE_LIVE,
            market_slug=market.slug,
            station_id=market.station_id,
            settlement_time_iso=market.official_settlement_time.isoformat(),
            hours_to_settlement=round(hours_left, 4),
            quotes=quotes,
            prob_static_flag=False,  # A-4: Reserved for probability evaluation in stage 3/4
            metadata={
                "title": market.title,
                "city": market.city,
                "bracket_count": len(market.brackets),
            },
        )
        return record

    def save_snapshot_record(self, record: SnapshotRecord) -> Path:
        """
        Persist standard snapshot record to daily partitioned directory.
        """
        day_str = record.timestamp_iso[:10]
        snapshot_dir = self.storage_base_dir / "snapshots" / day_str
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        file_path = snapshot_dir / f"{record.snapshot_id}.json"

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(record.to_dict(), f, indent=2, ensure_ascii=False)

        logger.info(f"Persisted snapshot record {record.snapshot_id} to {file_path}")
        return file_path
