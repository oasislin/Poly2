"""Unit tests for S2-02 (`D-A1`) dual-track P13 book-walking simulator."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, List, Tuple

import pytest

from src.calibration.p13_book_walk import (
    BookWalkCalibrationConfig,
    CorpusCoverageSummary,
    run_p13_book_walk_sessions,
    run_s202_calibration,
)
from src.data_acquisition.passive_book_recorder import (
    BidBook,
    MarketBookRecordEnvelope,
    MarketBookSnapshot,
)
from src.execution.executor import PhiPolicy
from src.pricing.penetration_probe import AskBook

REPO_ROOT = Path(__file__).resolve().parents[3]


def _make_env(
    *,
    seq_id: int,
    station_id: str,
    market_id: str,
    token_id: str,
    outcome: str,
    ts: datetime,
    asks: Tuple[Tuple[float, float], ...],
    bids: Tuple[Tuple[float, float], ...],
    single_side: str | None = None,
) -> MarketBookRecordEnvelope:
    snap = MarketBookSnapshot(
        token_id=token_id,
        market_id=market_id,
        condition_id=f"cond-{market_id}",
        snapshot_ts_utc=ts,
        recv_ts_utc=ts,
        ask_book=AskBook(levels=asks) if asks else None,
        bid_book=BidBook(levels=bids) if bids else None,
        best_bid=bids[0][0] if bids else None,
        bid_top10=bids,
        tick_size=0.01,
        min_order_size_shares=5.0,
        min_notional_usd=1.0,
        fee_rate=0.01,
        fee_rate_provenance="API_RUNTIME",
        neg_risk=True,
        data_source="MOCK_P13",
        frame_seq=seq_id,
        outcome=outcome,  # type: ignore[arg-type]
        single_side=single_side,  # type: ignore[arg-type]
    )
    return MarketBookRecordEnvelope(
        schema_version="p13.v1",
        seq_id=seq_id,
        session_id="sess-synth-s202",
        capture_mode="PASSIVE_RECORD",
        gap_detected=False,
        gap_reason=None,
        recorded_ts_utc=ts,
        station_id=station_id,
        target_date="2026-11-26",
        bin_label="50-51°F",
        payload=snap,
    )


def test_synthetic_book_walk_recovers_injected_median_slippage() -> None:
    """Inject known ask depth producing exact 5% slippage on YES_ONLY and 0% via NO_BID_SPLIT_SELL."""
    t0 = datetime(2026, 11, 26, 12, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(milliseconds=200)
    stations = ("KORD", "KMIA", "KLGA", "KATL")
    envs: List[MarketBookRecordEnvelope] = []
    seq = 1
    # YES ask book: 10 sh @ 0.40 ($4.00) + 100 sh @ 0.44;
    # For d=$8.80 (floor(8.80/0.44)=20.00 sh) and phi rho_0=1.0 -> 20 sh = 10*0.40 + 10*0.44 -> avg_fill=0.42 -> slip=0.05
    for idx, st in enumerate(stations):
        mkt = f"mkt-{st}"
        for ts in (t0, t1):
            envs.append(
                _make_env(
                    seq_id=seq, station_id=st, market_id=mkt, token_id=f"tok-y-{st}",
                    outcome="YES", ts=ts, asks=((0.40, 10.0), (0.44, 100.0)), bids=((0.38, 50.0),),
                )
            )
            seq += 1
            # NO bid book: 100 sh @ 0.60 => implied YES ask @ 1-0.60 = 0.40 for full 20 shares => avg_fill=0.40 => slip=0.00!
            envs.append(
                _make_env(
                    seq_id=seq, station_id=st, market_id=mkt, token_id=f"tok-n-{st}",
                    outcome="NO", ts=ts + timedelta(milliseconds=20),
                    asks=((0.62, 50.0),), bids=((0.60, 100.0),),
                )
            )
            seq += 1

    corpus = CorpusCoverageSummary(
        session_count=1, files_scanned=4, total_frames=len(envs), clean_frames=len(envs),
        gap_frames=0, corrupt_lines=0, fee_rates_seen=("0.01",), fee_era_001_only=True,
        first_ts_utc=t0.isoformat(), last_ts_utc=t1.isoformat(),
        campaign_span_hours=80.0, net_recorded_hours=80.0,
    )
    cfg = BookWalkCalibrationConfig(
        slice_notional_grid_usd=(Decimal("8.80"),),
        latency_ms=150,
        phi_policy=PhiPolicy(rho_0=Decimal("1.0"), k_slope=Decimal("0"), rho_min=Decimal("0.1"), rho_max=Decimal("1.0")),
    )
    report = run_p13_book_walk_sessions([("sess-synth", envs)], corpus, config=cfg)
    assert report.yes_only.valid_fill_count == 4
    assert report.dual_merged.valid_fill_count == 4
    assert report.yes_only.friction_median == pytest.approx(0.05, abs=1e-9)
    assert report.dual_merged.friction_median == pytest.approx(0.00, abs=1e-9)
    assert report.policy_draft.ledger_write_performed is False
    assert report.policy_draft.recommended_track == "YES_ONLY"
    assert report.policy_draft.recommended_friction_median == pytest.approx(0.05, abs=1e-9)


def test_wing_bid_only_backfill_and_json_report_format(tmp_path: Path) -> None:
    """Verify bid_only YES wing bin receives NO_BID_SPLIT_SELL fill in DUAL_MERGED track only."""
    t0 = datetime(2026, 11, 26, 12, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(milliseconds=250)
    envs = [
        _make_env(
            seq_id=1, station_id="KSEA", market_id="mkt-wing", token_id="tok-y-wing",
            outcome="YES", ts=t0, asks=(), bids=((0.10, 50.0),), single_side="bid_only",
        ),
        _make_env(
            seq_id=2, station_id="KSEA", market_id="mkt-wing", token_id="tok-n-wing",
            outcome="NO", ts=t0, asks=((0.92, 50.0),), bids=((0.85, 200.0),),
        ),
        _make_env(
            seq_id=3, station_id="KSEA", market_id="mkt-wing", token_id="tok-n-wing",
            outcome="NO", ts=t1, asks=((0.92, 50.0),), bids=((0.85, 200.0),),
        ),
    ]
    # Write as session JSONL to test run_s202_calibration loader path end-to-end
    sdir = tmp_path / "PASSIVE_RECORD" / "2026-11-26" / "sess-wing"
    sdir.mkdir(parents=True)
    (sdir / "p13_book_stream_KSEA.jsonl").write_text(
        "\n".join(e.to_json_line() for e in envs) + "\n", encoding="utf-8"
    )
    cfg = BookWalkCalibrationConfig(
        slice_notional_grid_usd=(Decimal("5.00"),),
        latency_ms=150,
        phi_policy=PhiPolicy(rho_0=Decimal("0.5"), k_slope=Decimal("0"), rho_min=Decimal("0.1"), rho_max=Decimal("1.0")),
    )
    rep = run_s202_calibration(tmp_path, config=cfg, verify_sha256=True)
    assert rep.wing_yes_ask_availability_pct == 0.0
    assert rep.wing_dual_merged_availability_pct == 100.0
    assert rep.wing_availability_abs_gain_pct == 100.0
    assert rep.yes_only.valid_fill_count == 0
    assert rep.dual_merged.valid_fill_count == 1
    assert rep.dual_merged.friction_median == pytest.approx(0.0, abs=1e-9)
    assert rep.gate_passed is False
    assert "S2-02 (D-A1)" in rep.to_markdown()


def test_s202_book_walk_ast_function_length_under_50_lines() -> None:
    target = REPO_ROOT / "src/calibration/p13_book_walk.py"
    tree = ast.parse(target.read_text(encoding="utf-8"))
    ge_50 = [
        (node.name, (node.end_lineno or node.lineno) - node.lineno + 1)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and ((node.end_lineno or node.lineno) - node.lineno + 1) >= 50
    ]
    assert ge_50 == []
