"""Smoke and unit tests for S1-05 read-only passive orderbook recorder (P4 + P13)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

from src.data_acquisition.passive_book_recorder import (
    FieldMappingConfig,
    MarketSubscriptionMeta,
    PassiveBookRecorder,
    RecorderConfig,
    compute_record_sha256,
    extract_fee_rate,
)


def _sample_meta(fee_rate: float = 0.05, prov: str = "API_RUNTIME") -> MarketSubscriptionMeta:
    return MarketSubscriptionMeta(
        token_id="tok-kord-58-59",
        market_id="mkt-1001",
        condition_id="0xcond1001",
        station_id="KORD",
        target_date="2026-11-18",
        bin_label="58-59°F",
        tick_size=0.01,
        min_order_size_shares=5.0,
        min_notional_usd=1.0,
        fee_rate=fee_rate,
        fee_rate_provenance=prov,  # type: ignore[arg-type]
        neg_risk=True,
    )


class _StubResp:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Dict[str, Any]:
        return self._payload


class _StubHttpSession:
    def __init__(self, book_payload: Dict[str, Any]) -> None:
        self._book_payload = book_payload

    def get(self, url: str, params: Dict[str, Any] | None = None, timeout: int = 10) -> _StubResp:
        assert "/book" in url
        return _StubResp(self._book_payload)


def test_config_yaml_loads_and_centralizes_field_mapping() -> None:
    cfg_path = Path("configs/passive_book_recorder.example.yaml")
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg = RecorderConfig.from_yaml_dict(raw)

    assert cfg.stations == ("KORD", "KMIA")
    assert cfg.capture_mode == "PASSIVE_RECORD"
    assert cfg.field_mapping.default_fee_rate_fallback == 0.05
    assert cfg.field_mapping.fee_schedule_key == "feeSchedule"


def test_extract_fee_rate_prefers_runtime_gamma_and_falls_back_to_fact001() -> None:
    fm = FieldMappingConfig()
    rate_rt, prov_rt = extract_fee_rate(
        {"feesEnabled": True, "feeSchedule": {"rate": 0.01, "exponent": 1}}, fm
    )
    assert rate_rt == pytest.approx(0.01)
    assert prov_rt == "API_RUNTIME"

    rate_fb, prov_fb = extract_fee_rate({"feesEnabled": True}, fm)
    assert rate_fb == pytest.approx(0.05)
    assert prov_fb == "FACT-001"


def test_smoke_ws_and_rest_frames_envelope_sha256_gap_and_async_jsonl(tmp_path: Path) -> None:
    cfg = RecorderConfig(
        stations=("KORD",),
        capture_mode="PASSIVE_RECORD",
        output_root=str(tmp_path),
    )
    stub_rest_book = {
        "market": "0xcond1001",
        "asset_id": "tok-kord-58-59",
        "timestamp": "1795008800000",
        # CLOB returns asks descending and bids ascending
        "asks": [{"price": "0.14", "size": "40"}, {"price": "0.12", "size": "20"}],
        "bids": [{"price": "0.08", "size": "15"}, {"price": "0.10", "size": "30"}],
        "min_order_size": "5",
        "tick_size": "0.01",
        "neg_risk": True,
    }
    recorder = PassiveBookRecorder(
        config=cfg,
        session_id="sess-smoke-01",
        http_session=_StubHttpSession(stub_rest_book),  # type: ignore[arg-type]
    )
    recorder.register_markets([_sample_meta()])

    # 1. Synthetic WS book frame (notice WS omits min_order_size & neg_risk and sends unsorted levels)
    ws_frame_1 = {
        "event_type": "book",
        "asset_id": "tok-kord-58-59",
        "timestamp": "1795008753406",
        "asks": [{"price": "0.15", "size": "60"}, {"price": "0.11", "size": "25"}],
        "bids": [{"price": "0.07", "size": "12"}, {"price": "0.09", "size": "18"}],
        "tick_size": "0.01",
    }
    t1 = datetime(2026, 11, 18, 12, 0, 1, tzinfo=timezone.utc)
    env1 = recorder.handle_ws_message(ws_frame_1, recv_ts_utc=t1)
    assert env1 is not None
    assert env1.seq_id == 1
    assert env1.gap_detected is False
    assert env1.payload.frame_seq == 1
    assert env1.payload.data_source == "CLOB_WS"
    assert env1.payload.ask_book.levels == ((0.11, 25.0), (0.15, 60.0))
    assert env1.payload.best_bid == pytest.approx(0.09)
    assert env1.payload.min_order_size_shares == 5.0
    assert env1.payload.neg_risk is True

    # 2. Synthetic WS tick_size_change updates cached tick_size dynamically
    tick_evt = {
        "event_type": "tick_size_change",
        "asset_id": "tok-kord-58-59",
        "new_tick_size": "0.001",
    }
    assert recorder.handle_ws_message(tick_evt) is None
    assert recorder.meta_by_token["tok-kord-58-59"].tick_size == pytest.approx(0.001)

    # 3. Heartbeat timeout marks gap and REST fallback writes P13 with CLOB_REST & gap_detected=True
    recorder.mark_gap("WS_HEARTBEAT_TIMEOUT")
    rest_envs = recorder.poll_rest_fallback_once()
    assert len(rest_envs) == 1
    env2 = rest_envs[0]
    assert env2.seq_id == 2
    assert env2.gap_detected is True
    assert env2.gap_reason == "WS_HEARTBEAT_TIMEOUT"
    assert env2.payload.frame_seq == 2
    assert env2.payload.data_source == "CLOB_REST"
    assert env2.payload.snapshot_ts_utc is not None

    recorder.flush_and_close()

    # 4. Verify persisted JSONL files, schema keys, and SHA256 verification
    jsonl_files = list(tmp_path.rglob("p13_book_stream_KORD.jsonl"))
    assert len(jsonl_files) == 1
    lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    for line in lines:
        obj = json.loads(line)
        recorded_hash = obj.pop("record_sha256")
        assert compute_record_sha256(obj) == recorded_hash
        assert obj["schema_version"] == "p13.v1"
        assert obj["capture_mode"] == "PASSIVE_RECORD"
        assert "asks" in obj["payload"] and "bids" in obj["payload"]
