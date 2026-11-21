"""Unit tests for read-only scripts/record_status.py and latest_session.json pointer."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from scripts.record_status import format_status_report, inspect_recording_status, main as status_main
from scripts.run_passive_book_recorder_daily import write_latest_session_pointer
from src.data_acquisition.passive_book_recorder import (
    MarketSubscriptionMeta,
    PassiveBookRecorder,
    RecorderConfig,
)


def _make_meta(
    token_id: str,
    station_id: str,
    outcome: str,
    fee_rate: float = 0.01,
    fee_prov: str = "API_RUNTIME",
) -> MarketSubscriptionMeta:
    return MarketSubscriptionMeta(
        token_id=token_id,
        market_id=f"mkt-{station_id}",
        condition_id=f"0x{station_id}",
        station_id=station_id,
        target_date="2026-11-21",
        bin_label="58-59°F",
        tick_size=0.01,
        min_order_size_shares=5.0,
        min_notional_usd=1.0,
        fee_rate=fee_rate,
        fee_rate_provenance=fee_prov,  # type: ignore[arg-type]
        neg_risk=True,
        outcome=outcome,  # type: ignore[arg-type]
    )


def test_record_status_handles_missing_root_gracefully(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "does_not_exist"
    rc = status_main(["--output-root", str(missing)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "does not exist" in out
    assert "(no sessions found)" in out


def test_record_status_aggregates_sessions_stations_gaps_single_side_and_provenance(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = RecorderConfig(stations=("KORD", "KSEA"), output_root=str(tmp_path))

    # Session 1 (older): KORD two-sided + gap frame
    rec1 = PassiveBookRecorder(config=cfg, session_id="rec-20261121T000500Z-aaa111")
    rec1.register_markets([_make_meta("tok-kord-yes", "KORD", "YES", 0.01, "API_RUNTIME")])
    rec1.handle_ws_message(
        {
            "event_type": "book",
            "asset_id": "tok-kord-yes",
            "asks": [{"price": "0.42", "size": "20"}],
            "bids": [{"price": "0.39", "size": "15"}],
        },
        recv_ts_utc=datetime(2026, 11, 21, 0, 10, 0, tzinfo=timezone.utc),
    )
    rec1.mark_gap("WS_HEARTBEAT_TIMEOUT")
    rec1.handle_ws_message(
        {
            "event_type": "book",
            "asset_id": "tok-kord-yes",
            "asks": [{"price": "0.43", "size": "25"}],
            "bids": [{"price": "0.40", "size": "18"}],
        },
        recv_ts_utc=datetime(2026, 11, 21, 0, 12, 0, tzinfo=timezone.utc),
    )
    rec1.flush_and_close()

    # Session 2 (active pointer): KSEA NO bid_only + KORD YES ask_only (FACT-001)
    sid2 = "rec-20261122T000500Z-bbb222"
    rec2 = PassiveBookRecorder(config=cfg, session_id=sid2)
    rec2.register_markets(
        [
            _make_meta("tok-ksea-no", "KSEA", "NO", 0.01, "API_RUNTIME"),
            _make_meta("tok-kord-yes", "KORD", "YES", 0.05, "FACT-001"),
        ]
    )
    rec2.handle_ws_message(
        {
            "event_type": "book",
            "asset_id": "tok-ksea-no",
            "asks": [],
            "bids": [{"price": "0.99", "size": "100"}],
        },
        recv_ts_utc=datetime(2026, 11, 22, 0, 6, 0, tzinfo=timezone.utc),
    )
    rec2.handle_ws_message(
        {
            "event_type": "book",
            "asset_id": "tok-kord-yes",
            "asks": [{"price": "0.50", "size": "30"}],
            "bids": [],
        },
        recv_ts_utc=datetime(2026, 11, 22, 0, 7, 0, tzinfo=timezone.utc),
    )
    rec2.flush_and_close()

    # Append \n-terminated corrupt line + unterminated trailing EOF partial line
    ksea_file = list(tmp_path.rglob("p13_book_stream_KSEA.jsonl"))[0]
    with ksea_file.open("a", encoding="utf-8") as fh:
        fh.write('{"partial_truncated_line": true\n')
        fh.write('{"unterminated_eof": ')

    write_latest_session_pointer(
        output_root=tmp_path,
        session_id=sid2,
        started_at_utc=datetime(2026, 11, 22, 0, 5, 0, tzinfo=timezone.utc),
        next_cutover_utc=datetime(2026, 11, 23, 0, 5, 0, tzinfo=timezone.utc),
        config_path=Path("configs/passive_book_recorder.example.yaml"),
        child_pid=43210,
        supervisor_pid=43200,
    )

    summary = inspect_recording_status(tmp_path)
    ov = summary["overall"]
    assert ov["frames"] == 4
    assert ov["corrupt_lines"] == 1
    assert ov["incomplete_trailing_lines"] == 1
    assert ov["gap_count"] == 1
    assert ov["single_side_counts"] == {"two_sided": 2, "bid_only": 1, "ask_only": 1}
    assert ov["single_side_ratios"]["single_side_total_pct"] == 50.0
    assert ov["fee_rate_provenance"] == {"API_RUNTIME": 3, "FACT-001": 1}
    assert ov["token_coverage"] == {"total": 2, "YES": 1, "NO": 1}
    assert ov["disk_bytes"] > 0

    by_sid = {s["session_id"]: s for s in summary["sessions"]}
    assert by_sid[sid2]["is_latest_session"] is True
    assert by_sid["rec-20261121T000500Z-aaa111"]["is_latest_session"] is False

    assert summary["stations"]["KORD"]["last_recorded_ts_utc"] == "2026-11-22T00:07:00+00:00"
    assert summary["stations"]["KORD"]["frames"] == 3
    assert summary["stations"]["KSEA"]["frames"] == 1
    assert summary["stations"]["KSEA"]["token_coverage"] == {"total": 1, "YES": 0, "NO": 1}

    report = format_status_report(summary)
    assert "*ACTIVE rec-20261122T000500Z-bbb222" in report
    assert status_main(["--output-root", str(tmp_path), "--json"]) == 0
    parsed_json = json.loads(capsys.readouterr().out)
    assert parsed_json["overall"]["frames"] == 4
