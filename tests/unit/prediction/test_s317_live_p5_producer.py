"""Unit tests for S3-17 `src/prediction/live_p5_producer.py` (offline mocks + optional live smoke)."""

from __future__ import annotations

import ast
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence, Tuple

import numpy as np
import pytest
import xarray as xr

from src.data_acquisition.settlement_metar_stream import LiveAwcMetarAdapter
from src.data_processing.constants import STATION_METADATA
from src.prediction.forecast_distribution_engine import verify_p17_json_line
from src.prediction.live_p5_producer import (
    DEFAULT_FORECAST_ORIGIN,
    SUPPORTED_LIVE_STATIONS,
    LiveP5Producer,
    LiveP5ProducerConfig,
    discover_p13_market_ladders,
    kelvin_to_fahrenheit,
    load_p5_jsonl_snapshots,
    parse_polymarket_bin_label,
    resolve_latest_gefs_cycle_utc,
    serialize_p5_jsonl_record,
    write_p5_jsonl,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


class _FakeGefsFetcher:
    """Offline Herbie/GEFS double returning realistic 5-member Kelvin datasets."""

    def __init__(self, base_temp_f_by_station: Mapping[str, float]) -> None:
        self._temps = dict(base_temp_f_by_station)
        self.calls: list[dict[str, Any]] = []

    def download_realtime(
        self,
        region_bounds: Mapping[str, Tuple[float, float]],
        forecast_time: datetime,
        members: Sequence[int],
        fxx_hours: Sequence[int] | None = None,
    ) -> xr.Dataset:
        self.calls.append(
            {
                "region_bounds": dict(region_bounds),
                "forecast_time": forecast_time,
                "members": list(members),
                "fxx_hours": list(fxx_hours or []),
            }
        )
        lat_mid = 0.5 * (region_bounds["lat"][0] + region_bounds["lat"][1])
        lon_mid = 0.5 * (region_bounds["lon"][0] + region_bounds["lon"][1])
        base_f = 50.0
        for st, val_f in self._temps.items():
            st_lat = float(STATION_METADATA[st]["latitude"])
            st_lon = float(STATION_METADATA[st]["longitude"])
            if abs(st_lat - lat_mid) < 0.2 and abs(st_lon - lon_mid) < 0.2:
                base_f = val_f
                break
        offsets = np.linspace(-2.0, 2.0, num=len(members))
        vals_k = np.array([((base_f + off) - 32.0) * 5.0 / 9.0 + 273.15 for off in offsets])
        data = vals_k[:, None, None, None]
        return xr.Dataset(
            data_vars={"tmax": (("member", "step", "latitude", "longitude"), data)},
            coords={
                "member": list(members),
                "step": [timedelta(hours=int((fxx_hours or [24])[0]))],
                "latitude": [lat_mid],
                "longitude": [lon_mid],
            },
        )


def _make_mock_awc_http(issue_ts_utc: datetime) -> Any:
    obs_ts = issue_ts_utc - timedelta(minutes=25)
    rcpt_ts = issue_ts_utc - timedelta(minutes=20)
    obs_str = obs_ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    rcpt_str = rcpt_ts.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _http_get(url: str, params: Mapping[str, Any], timeout: float) -> list[dict[str, Any]]:
        code = str(params["ids"]).upper()
        return [
            {
                "icaoId": code,
                "obsTime": obs_str,
                "receiptTime": rcpt_str,
                "metarType": "METAR",
                "rawOb": f"METAR {code} 261453Z 27008KT 10SM CLR 10/02 A3012 RMK AO2 T01000022",
            }
        ]

    return _http_get


def test_live_p5_producer_six_stations_offline_mock_and_jsonl(tmp_path: Path) -> None:
    issue_ts = datetime(2026, 11, 26, 15, 0, 0, tzinfo=timezone.utc)
    target = date(2026, 11, 26)
    cycle = datetime(2026, 11, 26, 6, 0, 0, tzinfo=timezone.utc)
    temps = {"KORD": 44.0, "KMIA": 78.0, "KLGA": 50.0, "KATL": 62.0, "KDAL": 68.0, "KSEA": 48.0}
    fake_gefs = _FakeGefsFetcher(temps)
    awc_adapter = LiveAwcMetarAdapter(
        http_get=_make_mock_awc_http(issue_ts),
        clock_utc=lambda: issue_ts,
    )
    producer = LiveP5Producer(
        config=LiveP5ProducerConfig(stations=SUPPORTED_LIVE_STATIONS),
        gefs_fetcher=fake_gefs,
        metar_adapter=awc_adapter,
    )
    records = producer.produce_batch(target_date=target, issue_ts_utc=issue_ts, cycle_utc=cycle, lead_hours=24)
    assert [r.snapshot.station_id for r in records] == list(SUPPORTED_LIVE_STATIONS)
    assert len(fake_gefs.calls) == 6
    for rec in records:
        assert rec.forecast_origin == DEFAULT_FORECAST_ORIGIN == "REALTIME_LIVE_PULL"
        assert rec.invariant_report.all_passed is True
        assert rec.snapshot.is_bridge_active is True
        assert rec.snapshot.m_now_int_f == 50  # T0100 -> 10.0C -> 50.0F
        assert rec.gefs_summary.member_count == 5
        assert rec.gefs_summary.ens_std_f > 0.0

    out_file = write_p5_jsonl(records, tmp_path / "p5_live.jsonl", session_id="sess-s317-test")
    lines = out_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 6
    for line in lines:
        assert verify_p17_json_line(line) is True
        row = json.loads(line)
        assert row["schema_version"] == "p17.v3"
        assert row["forecast_origin"] == "REALTIME_LIVE_PULL"
        assert row["capture_replay_mode"] == "NONE"
        assert abs(sum(b["p_model"] for b in row["bin_probs"]) - 1.0) < 1e-6


def test_kelvin_conversion_and_cycle_resolution() -> None:
    assert abs(kelvin_to_fahrenheit(273.15) - 32.0) < 1e-9
    assert abs(kelvin_to_fahrenheit(75.5) - 75.5) < 1e-9
    cyc = resolve_latest_gefs_cycle_utc(datetime(2026, 11, 26, 16, 30, 0, tzinfo=timezone.utc))
    assert cyc == datetime(2026, 11, 26, 6, 0, 0, tzinfo=timezone.utc)


def test_live_p5_producer_ast_function_length_under_50_lines() -> None:
    for rel in ("src/prediction/live_p5_producer.py", "scripts/run_live_p5_producer.py"):
        target = REPO_ROOT / rel
        tree = ast.parse(target.read_text(encoding="utf-8"))
        ge_50 = [
            (node.name, (node.end_lineno or node.lineno) - node.lineno + 1)
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and ((node.end_lineno or node.lineno) - node.lineno + 1) >= 50
        ]
        assert ge_50 == [], f"{rel} has functions >= 50 lines: {ge_50}"


def test_polymarket_bin_label_parsing_ladder_discovery_and_p5_roundtrip(tmp_path: Path) -> None:
    from src.execution.stub_generator import build_p4_v11_stub_envelope

    b0 = parse_polymarket_bin_label("33°F or below")
    b1 = parse_polymarket_bin_label("34-35°F")
    b2 = parse_polymarket_bin_label("36°F or higher")
    assert (b0.bin_id, b0.lower_int_f, b0.upper_int_f) == ("le_33F", None, 33)
    assert (b1.bin_id, b1.lower_int_f, b1.upper_int_f) == ("34-35F", 34, 35)
    assert (b2.bin_id, b2.lower_int_f, b2.upper_int_f) == ("ge_36F", 36, None)

    rec_root = tmp_path / "recordings"
    sess = rec_root / "PASSIVE_RECORD" / "2026-11-26" / "rec-test-active"
    sess.mkdir(parents=True)
    t0 = datetime(2026, 11, 26, 12, 0, 0, tzinfo=timezone.utc)
    envs = [
        build_p4_v11_stub_envelope(
            session_id="rec-test-active", seq_id=i + 1, frame_seq=i + 1,
            token_id=f"tok-{i}", market_id=f"mkt-{i}", condition_id="c1",
            station_id="KORD", target_date="2026-11-26", bin_label=lbl,
            outcome="YES", regime="two_sided", recv_ts_utc=t0,
            asks=((0.50, 10.0),), bids=((0.48, 10.0),),
        )[0].to_json_line()
        for i, lbl in enumerate(("33°F or below", "34-35°F", "36°F or higher"))
    ]
    (sess / "p13_book_stream_20261126.jsonl").write_text("\n".join(envs) + "\n", encoding="utf-8")
    (rec_root / "latest_session.json").write_text(json.dumps({"session_id": "rec-test-active"}), encoding="utf-8")
    ladders = discover_p13_market_ladders(rec_root, active_only=True)
    assert [b.bin_id for b in ladders[("KORD", "2026-11-26")]] == ["le_33F", "34-35F", "ge_36F"]

    issue_ts = datetime(2026, 11, 26, 15, 0, 0, tzinfo=timezone.utc)
    producer = LiveP5Producer(
        config=LiveP5ProducerConfig(stations=("KORD",), gefs_members=(0, 1, 2, 3, 4)),
        gefs_fetcher=_FakeGefsFetcher({"KORD": 35.0}),
        metar_adapter=LiveAwcMetarAdapter(http_get=_make_mock_awc_http(issue_ts), clock_utc=lambda: issue_ts),
    )
    rec = producer.produce_station_snapshot(
        station_id="KORD", target_date=date(2026, 11, 26), issue_ts_utc=issue_ts,
        cycle_utc=datetime(2026, 11, 26, 6, 0, 0, tzinfo=timezone.utc),
        bins=ladders[("KORD", "2026-11-26")],
    )
    out = write_p5_jsonl([rec], tmp_path / "p5_out" / "p5.jsonl", session_id="s-rt")
    loaded = load_p5_jsonl_snapshots(tmp_path / "p5_out")
    assert len(loaded) == 1
    assert loaded[0].forecast_id == rec.snapshot.forecast_id
    assert [bp.bin_id for bp in loaded[0].bin_probs] == ["le_33F", "34-35F", "ge_36F"]


@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="Real network GEFS + AWC METAR smoke test requires RUN_NETWORK_TESTS=1",
)
def test_network_s317_live_p5_producer_smoke(tmp_path: Path) -> None:
    issue_ts = datetime.now(timezone.utc)
    target = issue_ts.date()
    producer = LiveP5Producer(
        config=LiveP5ProducerConfig(stations=("KORD",), gefs_members=(0, 1, 2, 3, 4)),
    )
    rec = producer.produce_station_snapshot(
        station_id="KORD",
        target_date=target,
        issue_ts_utc=issue_ts,
        lead_hours=24,
    )
    assert rec.forecast_origin == "REALTIME_LIVE_PULL"
    assert rec.gefs_summary.member_count == 5
    assert rec.invariant_report.all_passed is True
    out_file = write_p5_jsonl([rec], tmp_path / "net_smoke.jsonl", session_id="s317-net-smoke")
    assert verify_p17_json_line(out_file.read_text(encoding="utf-8").strip()) is True
