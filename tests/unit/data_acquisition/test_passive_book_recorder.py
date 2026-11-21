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

    assert cfg.stations == ("KORD", "KMIA", "KLGA", "KATL", "KDAL", "KSEA")
    assert cfg.capture_mode == "PASSIVE_RECORD"
    assert cfg.max_tokens_per_ws == 200
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
    t1 = datetime.now(timezone.utc).replace(microsecond=0)
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
        assert obj["payload"]["outcome"] == "YES"
        assert obj["payload"]["single_side"] is None
        assert "asks" in obj["payload"] and "bids" in obj["payload"]


def test_single_side_books_persist_honestly_and_both_empty_marks_gap(tmp_path: Path) -> None:
    cfg = RecorderConfig(stations=("KSEA",), output_root=str(tmp_path))
    recorder = PassiveBookRecorder(config=cfg, session_id="sess-single-side")
    meta = MarketSubscriptionMeta(
        token_id="tok-ksea-37f-no",
        market_id="mkt-37f",
        condition_id="0xcond37",
        station_id="KSEA",
        target_date="2026-11-21",
        bin_label="37°F or below",
        tick_size=0.001,
        min_order_size_shares=5.0,
        min_notional_usd=1.0,
        fee_rate=0.01,
        fee_rate_provenance="API_RUNTIME",
        neg_risk=True,
        outcome="NO",
    )
    recorder.register_markets([meta])

    # 1. bid_only tail frame (asks=[], bids non-empty) must persist with gap_detected=False
    env_bid_only = recorder.handle_ws_message(
        {
            "event_type": "book",
            "asset_id": "tok-ksea-37f-no",
            "timestamp": "1795009000000",
            "asks": [],
            "bids": [{"price": "0.99", "size": "150"}, {"price": "0.995", "size": "200"}],
        },
        recv_ts_utc=datetime(2026, 11, 21, 1, 0, 0, tzinfo=timezone.utc),
    )
    assert env_bid_only is not None
    assert env_bid_only.gap_detected is False
    assert env_bid_only.gap_reason is None
    assert env_bid_only.payload.ask_book is None
    assert env_bid_only.payload.bid_book is not None
    assert env_bid_only.payload.best_bid == pytest.approx(0.995)
    assert env_bid_only.payload.single_side == "bid_only"
    assert env_bid_only.payload.outcome == "NO"

    # 2. ask_only tail frame (bids=[], asks non-empty) must persist with gap_detected=False
    env_ask_only = recorder.handle_ws_message(
        {
            "event_type": "book",
            "asset_id": "tok-ksea-37f-no",
            "timestamp": "1795009001000",
            "asks": [{"price": "0.999", "size": "500"}],
            "bids": [],
        },
        recv_ts_utc=datetime(2026, 11, 21, 1, 0, 1, tzinfo=timezone.utc),
    )
    assert env_ask_only is not None
    assert env_ask_only.gap_detected is False
    assert env_ask_only.payload.bid_book is None
    assert env_ask_only.payload.best_bid is None
    assert env_ask_only.payload.ask_book is not None
    assert env_ask_only.payload.single_side == "ask_only"

    # 3. Both asks and bids empty must NOT write a frame and must stamp gap on next valid frame
    env_both_empty = recorder.handle_ws_message(
        {
            "event_type": "book",
            "asset_id": "tok-ksea-37f-no",
            "timestamp": "1795009002000",
            "asks": [],
            "bids": [],
        },
        recv_ts_utc=datetime(2026, 11, 21, 1, 0, 2, tzinfo=timezone.utc),
    )
    assert env_both_empty is None
    env_recovered = recorder.handle_ws_message(
        {
            "event_type": "book",
            "asset_id": "tok-ksea-37f-no",
            "timestamp": "1795009003000",
            "asks": [{"price": "0.999", "size": "100"}],
            "bids": [{"price": "0.990", "size": "50"}],
        },
        recv_ts_utc=datetime(2026, 11, 21, 1, 0, 3, tzinfo=timezone.utc),
    )
    assert env_recovered is not None
    assert env_recovered.gap_detected is True
    assert env_recovered.gap_reason is not None and env_recovered.gap_reason.startswith("INVALID_OR_EMPTY_BOOK")

    recorder.flush_and_close()
    lines = list(tmp_path.rglob("p13_book_stream_KSEA.jsonl"))[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    p0 = json.loads(lines[0])
    assert p0["payload"]["asks"] == []
    assert p0["payload"]["single_side"] == "bid_only"
    assert p0["payload"]["outcome"] == "NO"


def test_discover_subscribes_yes_and_no_tokens_and_filters_legacy_slugs(tmp_path: Path) -> None:
    class _StubGammaHttp:
        def get(self, url: str, params: Dict[str, Any] | None = None, timeout: int = 15) -> _StubResp:
            assert "/public-search" in url
            return _StubResp(
                {
                    "events": [
                        {
                            "slug": "polyv2-highest-temperature-atomic-in-nyc-on-october-27-2026",
                            "closed": False,
                            "endDate": "2026-10-27T12:00:00Z",
                            "markets": [
                                {
                                    "id": "stale-1",
                                    "conditionId": "0xstale",
                                    "clobTokenIds": json.dumps(["stale-yes", "stale-no"]),
                                }
                            ],
                        },
                        {
                            "slug": "highest-temperature-in-nyc-on-november-21-2026",
                            "closed": False,
                            "endDate": "2026-11-21T12:00:00Z",
                            "markets": [
                                {
                                    "id": "mkt-nyc-51",
                                    "conditionId": "0xcond51",
                                    "endDateIso": "2026-11-21",
                                    "groupItemTitle": "51°F or below",
                                    "outcomes": json.dumps(["Yes", "No"]),
                                    "clobTokenIds": json.dumps(["tok-yes-51", "tok-no-51"]),
                                    "feesEnabled": True,
                                    "feeSchedule": {"rate": 0.01},
                                    "orderPriceMinTickSize": 0.001,
                                    "orderMinSize": 5,
                                    "negRisk": True,
                                }
                            ],
                        },
                    ]
                }
            )

    cfg = RecorderConfig(stations=("KLGA",), output_root=str(tmp_path))
    recorder = PassiveBookRecorder(config=cfg, session_id="sess-dual", http_session=_StubGammaHttp())  # type: ignore[arg-type]
    metas = recorder.discover_active_temperature_markets()
    recorder.flush_and_close()

    assert [m.token_id for m in metas] == ["tok-yes-51", "tok-no-51"]
    assert [m.outcome for m in metas] == ["YES", "NO"]
    assert "stale-yes" not in recorder.meta_by_token
    assert recorder.meta_by_token["tok-no-51"].fee_rate == pytest.approx(0.01)


def test_partition_token_shards_and_stop_event_interrupts_ws_wait(tmp_path: Path) -> None:
    import asyncio
    from src.data_acquisition.passive_book_recorder import partition_token_shards

    tokens = [f"tok-{i}" for i in range(405)]
    shards = partition_token_shards(tokens, max_tokens_per_ws=200)
    assert tuple(len(s) for s in shards) == (200, 200, 5)

    # _recv_or_stop must wake immediately when stop_event is set despite 25s heartbeat timeout
    class _HangingWs:
        async def recv(self) -> str:
            await asyncio.sleep(60.0)
            return "{}"

    async def _run_stop_check() -> Any:
        stop_ev = asyncio.Event()
        asyncio.get_running_loop().call_later(0.03, stop_ev.set)
        return await PassiveBookRecorder._recv_or_stop(_HangingWs(), timeout_sec=25.0, stop_event=stop_ev)

    res = asyncio.run(_run_stop_check())
    assert res.__class__ is object  # _STOP_SIGNAL sentinel


def test_daily_rotation_cutover_and_supervisor_graceful_restart(tmp_path: Path) -> None:
    from scripts.run_passive_book_recorder_daily import (
        compute_next_cutover_utc,
        generate_session_id,
        run_daily_supervisor,
    )

    t_before = datetime(2026, 11, 21, 0, 4, 30, tzinfo=timezone.utc)
    assert compute_next_cutover_utc(t_before, 0, 5) == datetime(2026, 11, 21, 0, 5, 0, tzinfo=timezone.utc)

    t_after = datetime(2026, 11, 21, 0, 5, 0, tzinfo=timezone.utc)
    assert compute_next_cutover_utc(t_after, 0, 5) == datetime(2026, 11, 22, 0, 5, 0, tzinfo=timezone.utc)

    s1 = generate_session_id(t_before)
    s2 = generate_session_id(t_after)
    assert s1 != s2 and s1.startswith("rec-20261121T000430Z-")

    class _FakeProc:
        def __init__(self, pid: int) -> None:
            self.pid = pid
            self.returncode: int | None = None
            self.terminated = False

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = 0

        def wait(self, timeout: float | None = None) -> int:
            self.returncode = 0
            return 0

        def kill(self) -> None:
            self.returncode = -9

    times = iter(
        [
            datetime(2026, 11, 21, 0, 4, 58, tzinfo=timezone.utc),
            datetime(2026, 11, 21, 0, 4, 59, tzinfo=timezone.utc),
            datetime(2026, 11, 21, 0, 5, 1, tzinfo=timezone.utc),
            datetime(2026, 11, 21, 0, 5, 1, tzinfo=timezone.utc),
            datetime(2026, 11, 21, 0, 5, 2, tzinfo=timezone.utc),
        ]
    )
    spawned: list[tuple[list[str], _FakeProc]] = []

    def _fake_popen(cmd: list[str], cwd: str | None = None) -> _FakeProc:
        proc = _FakeProc(pid=100 + len(spawned))
        spawned.append((cmd, proc))
        return proc

    rc = run_daily_supervisor(
        config_path=Path("configs/passive_book_recorder.example.yaml"),
        cutover_hhmm="00:05",
        max_cycles=2,
        output_root=tmp_path,
        now_fn=lambda: next(times, datetime(2026, 11, 22, 0, 6, 0, tzinfo=timezone.utc)),
        popen_fn=_fake_popen,  # type: ignore[arg-type]
        sleep_fn=lambda _sec: None,
    )
    assert rc == 0
    assert len(spawned) == 2
    assert spawned[0][1].terminated is True
    sid_1 = spawned[0][0][spawned[0][0].index("--session-id") + 1]
    sid_2 = spawned[1][0][spawned[1][0].index("--session-id") + 1]
    assert sid_1 != sid_2
    latest_ptr = json.loads((tmp_path / "latest_session.json").read_text(encoding="utf-8"))
    assert latest_ptr["session_id"] == sid_2
    assert latest_ptr["schema_version"] == "latest_session.v1"


def test_shard_gap_propagates_to_all_shard_tokens_and_async_rest_nonblocking(tmp_path: Path) -> None:
    import asyncio
    import time

    meta_a = _sample_meta()
    meta_b = MarketSubscriptionMeta(
        **{
            **meta_a.__dict__,
            "token_id": "tok-kord-60-61",
            "market_id": "mkt-1002",
            "condition_id": "0xcond1002",
            "bin_label": "60-61°F",
        }
    )
    cfg = RecorderConfig(
        stations=("KORD",),
        capture_mode="PASSIVE_RECORD",
        output_root=str(tmp_path),
        max_tokens_per_ws=10,
    )
    rec = PassiveBookRecorder(config=cfg, session_id="rec-gap-async-01")
    rec.register_markets([meta_a, meta_b])
    rec._token_shard = {meta_a.token_id: 0, meta_b.token_id: 0}

    rec.mark_gap("WS_RECONNECT:TestReset", shard_index=0)
    raw_payload = {"bids": [{"price": "0.40", "size": "10"}], "asks": [{"price": "0.45", "size": "10"}]}
    env_a = rec.record_raw_book_frame(raw_payload, meta_a, data_source="CLOB_REST")
    env_b = rec.record_raw_book_frame(raw_payload, meta_b, data_source="CLOB_REST")
    assert env_a.gap_detected is True and env_a.gap_reason == "WS_RECONNECT:TestReset"
    assert env_b.gap_detected is True and env_b.gap_reason == "WS_RECONNECT:TestReset"

    def _slow_rest(token_id: str) -> Dict[str, Any]:
        time.sleep(0.08)
        return {"bids": [{"price": "0.41", "size": "5"}], "asks": [{"price": "0.46", "size": "5"}]}

    rec._fetch_rest_book_payload = _slow_rest  # type: ignore[method-assign]

    async def _run() -> float:
        ticks = 0

        async def _ticker() -> None:
            nonlocal ticks
            for _ in range(4):
                await asyncio.sleep(0.02)
                ticks += 1

        t_task = asyncio.create_task(_ticker())
        envs = await rec.poll_rest_fallback_async(token_ids=[meta_a.token_id, meta_b.token_id])
        await t_task
        assert len(envs) == 2
        return float(ticks)

    ticks_observed = asyncio.run(_run())
    assert ticks_observed >= 2
    rec.flush_and_close()
