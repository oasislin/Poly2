"""
Unit Tests for Polymarket CLOB Read-Only Data Ingestion Module (Phase 2 Wave 3 / W3-A).
Governed by docs/w3_polymarket_ingestion_preregistration.md Rev.1.0 & Work Order P7-W3-TASK1-AUTH-001.

Validates:
1. Normal Orderbook parsing: Conservative best ask/bid, mid price, raw depth (B-1, B-5).
2. Missing Side parsing: NO_QUOTE handling when ask or bid is missing (B-2).
3. Empty Book parsing: EMPTY_BOOK handling when both sides are empty.
4. Cadence Scheduler: Baseline 60m vs Settlement Probe 15m (A-1, A-2, A-3).
5. Data Provenance & Ledger Persistence: DATA_PROVENANCE == 'POLYMARKET_LIVE_CLOB' (E-2) & PROB_STATIC reservation (A-4).
6. Market Discovery & Daily Subscription Checklist (C-1).
7. C5 Security Boundary: Strictly zero private keys, zero trading endpoints.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch
import pytest

from src.data_acquisition.polymarket_clob_collector import (
    CLOB_API_BASE_URL,
    DATA_PROVENANCE_LIVE,
    GAMMA_API_BASE_URL,
    KNOWN_CITY_TO_STATION,
    CLOBQuote,
    MarketTokenBracket,
    OrderBookLevel,
    PolymarketCLOBCollector,
    PolymarketReadOnlyCLOBClient,
    PolymarketTemperatureMarket,
    SnapshotRecord,
    calculate_snapshot_cadence,
    parse_iso_datetime,
    parse_order_book_payload,
)


class TestCLOBOrderBookParsing:
    """Tests for orderbook parsing according to criteria B-1, B-2, and B-5."""

    def test_normal_order_book_conservative_pricing(self):
        """
        Normal orderbook with multiple ask and bid levels.
        B-1: Buy uses best ask (lowest ask), sell uses best bid (highest bid).
        B-5: Raw best tier sizes recorded.
        """
        raw_payload = {
            "market": "0x123",
            "asset_id": "token_abc",
            "asks": [
                {"price": "0.45", "size": "100.0"},
                {"price": "0.42", "size": "25.0"},  # Best ask (lowest)
                {"price": "0.48", "size": "50.0"},
            ],
            "bids": [
                {"price": "0.38", "size": "40.0"},  # Best bid (highest)
                {"price": "0.35", "size": "80.0"},
                {"price": "0.32", "size": "120.0"},
            ],
        }

        quote = parse_order_book_payload("token_abc", raw_payload)

        assert quote.quote_status == "NORMAL"
        assert quote.token_id == "token_abc"
        # B-1: Lowest ask is 0.42
        assert quote.best_ask == pytest.approx(0.42)
        assert quote.best_ask_size == pytest.approx(25.0)
        # B-1: Highest bid is 0.38
        assert quote.best_bid == pytest.approx(0.38)
        assert quote.best_bid_size == pytest.approx(40.0)
        # Midpoint is (0.42 + 0.38) / 2 = 0.40
        assert quote.mid_price == pytest.approx(0.40)
        assert len(quote.raw_asks) == 3
        assert len(quote.raw_bids) == 3

    def test_missing_bid_side_marked_no_quote(self):
        """
        B-2: When bid side is missing, quote_status must be NO_QUOTE.
        best_bid must be None.
        """
        raw_payload = {
            "market": "0x123",
            "asset_id": "token_xyz",
            "asks": [
                {"price": "0.55", "size": "50.0"},
            ],
            "bids": [],
        }

        quote = parse_order_book_payload("token_xyz", raw_payload)

        assert quote.quote_status == "NO_QUOTE"
        assert quote.best_ask == pytest.approx(0.55)
        assert quote.best_ask_size == pytest.approx(50.0)
        assert quote.best_bid is None
        assert quote.best_bid_size == 0.0
        assert quote.mid_price is None

    def test_missing_ask_side_marked_no_quote(self):
        """
        B-2: When ask side is missing, quote_status must be NO_QUOTE.
        best_ask must be None.
        """
        raw_payload = {
            "market": "0x123",
            "asset_id": "token_xyz",
            "asks": [],
            "bids": [
                {"price": "0.20", "size": "100.0"},
            ],
        }

        quote = parse_order_book_payload("token_xyz", raw_payload)

        assert quote.quote_status == "NO_QUOTE"
        assert quote.best_ask is None
        assert quote.best_ask_size == 0.0
        assert quote.best_bid == pytest.approx(0.20)
        assert quote.best_bid_size == pytest.approx(100.0)
        assert quote.mid_price is None

    def test_empty_order_book_marked_empty_book(self):
        """
        Empty book: Both asks and bids empty.
        quote_status must be EMPTY_BOOK, both sides None.
        """
        raw_payload = {
            "market": "0x123",
            "asset_id": "token_empty",
            "asks": [],
            "bids": [],
        }

        quote = parse_order_book_payload("token_empty", raw_payload)

        assert quote.quote_status == "EMPTY_BOOK"
        assert quote.best_ask is None
        assert quote.best_bid is None
        assert quote.mid_price is None
        assert quote.best_ask_size == 0.0
        assert quote.best_bid_size == 0.0


class TestCadenceScheduler:
    """Tests for cadence scheduler rules A-1, A-2, and A-3."""

    def test_baseline_layer_frequency_outside_12h(self):
        """
        A-1: More than 12h away from T-0 -> BASELINE_60M.
        """
        current_time = datetime(2026, 10, 11, 0, 0, 0, tzinfo=timezone.utc)
        settlement_time = datetime(2026, 10, 11, 18, 0, 0, tzinfo=timezone.utc)  # 18h away

        cadence = calculate_snapshot_cadence(settlement_time, current_time)
        assert cadence == "BASELINE_60M"

    def test_settlement_probe_layer_frequency_within_12h(self):
        """
        A-2: Within 12h of T-0 -> SETTLEMENT_PROBE_15M.
        """
        current_time = datetime(2026, 10, 11, 8, 0, 0, tzinfo=timezone.utc)
        settlement_time = datetime(2026, 10, 11, 18, 0, 0, tzinfo=timezone.utc)  # 10h away

        cadence = calculate_snapshot_cadence(settlement_time, current_time)
        assert cadence == "SETTLEMENT_PROBE_15M"

    def test_boundary_exact_12h(self):
        """Exact 12.0 hours away triggers probe layer."""
        current_time = datetime(2026, 10, 11, 6, 0, 0, tzinfo=timezone.utc)
        settlement_time = datetime(2026, 10, 11, 18, 0, 0, tzinfo=timezone.utc)  # exactly 12h

        cadence = calculate_snapshot_cadence(settlement_time, current_time)
        assert cadence == "SETTLEMENT_PROBE_15M"

    def test_post_settlement_layer_when_past_t0(self):
        """
        POST_SETTLEMENT fix: When current time is past official settlement T-0,
        cadence must be POST_SETTLEMENT.
        """
        current_time = datetime(2026, 10, 11, 19, 0, 0, tzinfo=timezone.utc)  # 1h past
        settlement_time = datetime(2026, 10, 11, 18, 0, 0, tzinfo=timezone.utc)

        cadence = calculate_snapshot_cadence(settlement_time, current_time)
        assert cadence == "POST_SETTLEMENT"


class TestSnapshotCollectionAndPersistence:
    """Tests for snapshot collection, E-2 data provenance, and A-4 prob_static reservation."""

    def test_collect_market_snapshot_and_provenance(self):
        """Test snapshot creation across market brackets with explicit POLYMARKET_LIVE_CLOB tag."""
        mock_client = MagicMock(spec=PolymarketReadOnlyCLOBClient)
        mock_client.fetch_order_book.side_effect = lambda tid: CLOBQuote(
            token_id=tid,
            best_ask=0.50,
            best_bid=0.46,
            mid_price=0.48,
            best_ask_size=15.0,
            best_bid_size=20.0,
            quote_status="NORMAL",
        )

        market = PolymarketTemperatureMarket(
            event_id="evt_001",
            slug="highest-temp-chicago-oct-12",
            title="Highest temperature in Chicago on October 12?",
            city="Chicago",
            station_id="KORD",
            target_date_str="2026-10-12",
            official_settlement_time=datetime(2026, 10, 12, 18, 0, 0, tzinfo=timezone.utc),
            brackets=[
                MarketTokenBracket("tok_1", "60-61°F", "Yes", "cond_1"),
                MarketTokenBracket("tok_2", "62-63°F", "Yes", "cond_2"),
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            collector = PolymarketCLOBCollector(client=mock_client, storage_base_dir=Path(tmpdir))
            eval_time = datetime(2026, 10, 12, 10, 0, 0, tzinfo=timezone.utc)  # 8h to T-0 -> 15m probe

            record = collector.collect_market_snapshot(market, now_utc=eval_time)

            # Assertions
            assert record.snapshot_layer == "SETTLEMENT_PROBE_15M"
            assert record.data_provenance == DATA_PROVENANCE_LIVE  # E-2
            assert record.prob_static_flag is False  # A-4 pre-registered
            assert record.station_id == "KORD"
            assert len(record.quotes) == 2
            assert record.quotes["tok_1"].best_ask == 0.50

            # Test persistence to disk
            saved_path = collector.save_snapshot_record(record)
            assert saved_path.exists()

            with open(saved_path, "r", encoding="utf-8") as f:
                saved_json = json.load(f)

            assert saved_json["data_provenance"] == "POLYMARKET_LIVE_CLOB"
            assert saved_json["snapshot_layer"] == "SETTLEMENT_PROBE_15M"
            assert saved_json["station_id"] == "KORD"
            assert "quotes" in saved_json
            assert saved_json["prob_static_flag"] is False


class TestMarketDiscoveryAndChecklist:
    """Tests for market discovery and daily checklist persistence (C-1)."""

    def test_discover_active_temperature_markets(self):
        """Verify discovery across city mappings and manifest saving."""
        mock_client = MagicMock(spec=PolymarketReadOnlyCLOBClient)
        mock_client.search_temperature_events.return_value = [
            {"slug": "highest-temp-miami-oct-12", "active": True, "closed": False}
        ]
        mock_client.fetch_event_by_slug.return_value = {
            "id": "1002",
            "title": "Highest temperature in Miami on October 12?",
            "endDate": "2026-10-12T18:00:00Z",
            "markets": [
                {
                    "id": "m1",
                    "groupItemTitle": "84-85°F",
                    "clobTokenIds": json.dumps(["tok_mia_1", "tok_mia_2"]),
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            collector = PolymarketCLOBCollector(client=mock_client, storage_base_dir=Path(tmpdir))
            markets = collector.discover_active_temperature_markets(cities=["miami"])

            assert len(markets) == 1
            m = markets[0]
            assert m.station_id == "KMIA"
            assert m.city == "Miami"
            assert len(m.brackets) == 1
            assert m.brackets[0].token_id == "tok_mia_1"

            # Save manifest
            manifest_file = collector.save_subscription_manifest(markets, date_str="20261012")
            assert manifest_file.exists()

            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)

            assert manifest_data["total_markets"] == 1
            assert manifest_data["data_provenance"] == DATA_PROVENANCE_LIVE
            assert manifest_data["markets"][0]["station_id"] == "KMIA"


class TestC5SecurityBoundaries:
    """Rigorous verification of C5 / E-1 security and zero private key guarantees."""

    def test_strictly_zero_private_keys_or_signers(self):
        """Assert no private keys, signers, or credentials exist in collector attributes."""
        client = PolymarketReadOnlyCLOBClient()
        forbidden_terms = ["key", "secret", "signer", "private", "wallet", "passphrase", "mnemonic"]

        for attr in dir(client):
            lower_attr = attr.lower()
            for term in forbidden_terms:
                assert term not in lower_attr, f"Forbidden sensitive attribute found: {attr}"

    def test_strictly_zero_trading_methods(self):
        """Assert client exposes no order placement, cancellation, or trading execution methods."""
        client = PolymarketReadOnlyCLOBClient()
        forbidden_methods = [
            "place_order", "create_order", "submit_order",
            "cancel_order", "cancel_all", "trade", "buy", "sell"
        ]

        for method in forbidden_methods:
            assert not hasattr(client, method), f"Forbidden trading method found on read-only client: {method}"
