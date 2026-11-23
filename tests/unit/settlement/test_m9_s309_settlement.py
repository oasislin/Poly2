"""TDD unit & acceptance tests for `S3-09` (`P9` schema, `M9` AWC/WU settlement, DST, `floor(x+0.5)`, `P15`)."""

from __future__ import annotations

import ast
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.audit.audit_logger import AsyncAuditLogger
from src.audit.p10_reader import P10Query, query_p10_session_view
from src.bankroll import (
    BankrollAccountManager,
    BankrollConfig,
    FillSettleLoopback,
    FreezeRequest,
)
from src.data_acquisition.settlement_metar_stream import RawMetarReport
from src.utils.causal_utils import verify_record_sha256_line


def _metar(
    station_id: str,
    obs_ts: datetime,
    raw_text: str,
    *,
    report_type: str = "METAR",
    is_cor: bool = False,
    dispatch_ts: datetime | None = None,
) -> RawMetarReport:
    return RawMetarReport(
        station_id=station_id,
        obs_ts_utc=obs_ts,
        dispatch_ts_utc=dispatch_ts or (obs_ts + timedelta(minutes=2)),
        report_type=report_type,  # type: ignore[arg-type]
        is_cor=is_cor,
        raw_text=raw_text,
        source_channel="AWC_METAR_TEST",
    )


def test_p9_awc_routine_metar_tgroup_body_speci_cor_and_negative_half_rounding(tmp_path: Path) -> None:
    """AWC routine METAR prefers T-group, excludes SPECI, respects pre/post-lock COR, and uses floor(x+0.5)."""
    from src.settlement.m9_settler import M9SettlementEngine, SettlementBinSpec

    # Target date 2026-01-15 in KORD (America/Chicago, CST = UTC-6): [2026-01-15T06:00Z, 2026-01-16T06:00Z)
    d = date(2026, 1, 15)
    reports = [
        # T-group -22.5°C -> exact -8.5°F -> floor(-8.5 + 0.5) = -8°F (NOT -9!)
        _metar("KORD", datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc), "METAR KORD 151200Z 00000KT M23/M25 RMK T12251250"),
        # SPECI with much hotter +5.0°C (41°F) MUST be ignored per ADR-0012 §5
        _metar("KORD", datetime(2026, 1, 15, 15, 0, tzinfo=timezone.utc), "SPECI KORD 151500Z 00000KT 05/00", report_type="SPECI"),
        # Body-only fallback (-20°C = -4°F) at a later obs time makes TMAX = -4°F vs TMIN = -8°F
        _metar("KORD", datetime(2026, 1, 15, 18, 0, tzinfo=timezone.utc), "METAR KORD 151800Z 00000KT M20/M22"),
        # Next-day first routine METAR at 06:10Z (dispatch 06:12Z) locks revisions!
        _metar("KORD", datetime(2026, 1, 16, 6, 10, tzinfo=timezone.utc), "METAR KORD 160610Z 00000KT M18/M20"),
        # Post-lock COR for 15th arriving AFTER 06:12Z lock must be ignored!
        _metar(
            "KORD",
            datetime(2026, 1, 15, 18, 0, tzinfo=timezone.utc),
            "METAR COR KORD 151800Z 00000KT 10/00 RMK T01000000",
            is_cor=True,
            dispatch_ts=datetime(2026, 1, 16, 6, 30, tzinfo=timezone.utc),
        ),
    ]

    bins_tmax = (
        SettlementBinSpec("bin-neg-10-below", None, -10),
        SettlementBinSpec("bin-neg-9-to-neg-4", -9, -4),
        SettlementBinSpec("bin-neg-3-above", -3, None),
    )
    bins_tmin = (
        SettlementBinSpec("bin-neg-9-below", None, -9),
        SettlementBinSpec("bin-neg-8-to-neg-7", -8, -7),
        SettlementBinSpec("bin-neg-6-above", -6, None),
    )

    engine = M9SettlementEngine()
    p9_tmax = engine.evaluate_settlement(
        session_id="sess-m9-1",
        execution_mode="PAPER",
        station_id="KORD",
        target_date=d,
        target_type="TMAX",
        market_id="mkt-kord-tmax",
        reports=reports,
        bins=bins_tmax,
        as_of_ts_utc=datetime(2026, 1, 16, 12, 0, tzinfo=timezone.utc),
    )
    assert p9_tmax.settled_temp_f_int == -4
    assert p9_tmax.winning_bin_id == "bin-neg-9-to-neg-4"
    assert p9_tmax.speci_excluded_count == 1
    assert p9_tmax.post_lock_cor_ignored_count == 1
    assert p9_tmax.oracle_source == "AWC_ROUTINE_METAR"

    # Evaluate TMIN strictly on the single -22.5°C (-8.5°F) T-group report to prove -8.5 -> -8
    p9_tmin = engine.evaluate_settlement(
        session_id="sess-m9-1",
        execution_mode="PAPER",
        station_id="KORD",
        target_date=d,
        target_type="TMIN",
        market_id="mkt-kord-tmin",
        reports=[r for r in reports if r.obs_ts_utc != datetime(2026, 1, 15, 18, 0, tzinfo=timezone.utc) or r.is_cor],
        bins=bins_tmin,
        as_of_ts_utc=datetime(2026, 1, 16, 12, 0, tzinfo=timezone.utc),
    )
    assert p9_tmin.settled_temp_f_exact == Decimal("-8.5")
    assert p9_tmin.settled_temp_f_int == -8
    assert p9_tmin.winning_bin_id == "bin-neg-8-to-neg-7"

    with AsyncAuditLogger(tmp_path / "m7", execution_mode="PAPER") as logger:
        logger.log_p9_settlement_truth(p9_tmax)
        logger.log_p9_settlement_truth(p9_tmin)
        logger.flush()

    p9_file = tmp_path / "m7" / "PAPER" / "2026-01-16" / "p9_settlement_truths.jsonl"
    lines = p9_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and all(verify_record_sha256_line(ln) for ln in lines)

    view = query_p10_session_view(tmp_path / "m7", P10Query(execution_mode="PAPER"))
    assert view.settlement_status == "READY"
    assert len(view.p9_events) == 2


def test_dst_spring_23h_and_fall_25h_day_windows_exclude_adjacent_days() -> None:
    """DST transitions (23h spring-forward, 25h fall-back) maintain exact station local midnight bounds."""
    from src.settlement.m9_settler import M9SettlementEngine, SettlementBinSpec

    engine = M9SettlementEngine()
    bins = (SettlementBinSpec("b-all", None, None),)

    # 1. Spring forward in Chicago: 2026-03-08 (CST UTC-6 -> CDT UTC-5 at 02:00 local = 08:00Z)
    # Local day runs [2026-03-08T06:00Z, 2026-03-09T05:00Z) -> 23 hours!
    d_spring = date(2026, 3, 8)
    spring_reports = [
        # 05:55Z is Mar 7 23:55 local (excluded!)
        _metar("KORD", datetime(2026, 3, 8, 5, 55, tzinfo=timezone.utc), "METAR KORD 080555Z 00000KT 30/20 RMK T03000200"),
        # 18:00Z is inside Mar 8 local (+10.0°C = 50°F)
        _metar("KORD", datetime(2026, 3, 8, 18, 0, tzinfo=timezone.utc), "METAR KORD 081800Z 00000KT 10/05 RMK T01000050"),
        # 05:00Z on Mar 9 is Mar 9 00:00 CDT (excluded as next day!)
        _metar("KORD", datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc), "METAR KORD 090500Z 00000KT 25/10 RMK T02500100"),
    ]
    res_spring = engine.evaluate_settlement(
        session_id="sess-dst",
        execution_mode="PAPER",
        station_id="KORD",
        target_date=d_spring,
        target_type="TMAX",
        market_id="mkt-spring",
        reports=spring_reports,
        bins=bins,
        as_of_ts_utc=datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc),
    )
    assert (res_spring.settle_close_utc - res_spring.day_start_utc) == timedelta(hours=23)
    assert res_spring.settled_temp_f_int == 50

    # 2. Fall back in Chicago: 2026-11-01 (CDT UTC-5 -> CST UTC-6 at 02:00 local = 07:00Z)
    # Local day runs [2026-11-01T05:00Z, 2026-11-02T06:00Z) -> 25 hours!
    d_fall = date(2026, 11, 1)
    fall_reports = [
        # 05:30Z on Nov 2 is Nov 1 23:30 CST (STILL included on 25h day! +15.0°C = 59°F)
        _metar("KORD", datetime(2026, 11, 2, 5, 30, tzinfo=timezone.utc), "METAR KORD 020530Z 00000KT 15/05 RMK T01500050"),
        # 06:00Z on Nov 2 is Nov 2 00:00 CST (next day lock report, excluded from Nov 1!)
        _metar("KORD", datetime(2026, 11, 2, 6, 0, tzinfo=timezone.utc), "METAR KORD 020600Z 00000KT 30/10 RMK T03000100"),
    ]
    res_fall = engine.evaluate_settlement(
        session_id="sess-dst",
        execution_mode="PAPER",
        station_id="KORD",
        target_date=d_fall,
        target_type="TMAX",
        market_id="mkt-fall",
        reports=fall_reports,
        bins=bins,
        as_of_ts_utc=datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc),
    )
    assert (res_fall.settle_close_utc - res_fall.day_start_utc) == timedelta(hours=25)
    assert res_fall.settled_temp_f_int == 59


def test_wu_fallback_time_gate_and_lowest_bin_fallback() -> None:
    """WU fallback forbidden before 11:59 PM ET next day; falls back to WU then LOWEST_BIN_FALLBACK."""
    from src.settlement.m9_settler import (
        M9SettlementEngine,
        SettlementBinSpec,
        SettlementPendingError,
        WuDailySummary,
    )

    class _FakeWuSource:
        def __init__(self, summary: WuDailySummary | None) -> None:
            self.summary = summary
            self.calls = 0

        def fetch_daily(self, station_id: str, target_date: date) -> WuDailySummary | None:
            self.calls += 1
            return self.summary

    d = date(2026, 11, 20)  # ET next day 23:59 = 2026-11-22T04:59Z (EST=UTC-5)
    bins = (
        SettlementBinSpec("bin-low", None, 55),
        SettlementBinSpec("bin-mid", 56, 65),
        SettlementBinSpec("bin-high", 66, None),
    )

    wu_ok = _FakeWuSource(WuDailySummary("KORD", d, Decimal("61.5"), Decimal("44.0"), "https://wu.example/KORD"))
    engine_wu = M9SettlementEngine(wu_source=wu_ok)

    # Before 2026-11-22T04:59Z with 0 AWC METARs -> strictly pending (WU forbidden before deadline!)
    with pytest.raises(SettlementPendingError, match="11:59 PM ET"):
        engine_wu.evaluate_settlement(
            session_id="sess-wu",
            execution_mode="PAPER",
            station_id="KORD",
            target_date=d,
            target_type="TMAX",
            market_id="mkt-wu",
            reports=[],
            bins=bins,
            as_of_ts_utc=datetime(2026, 11, 22, 4, 30, tzinfo=timezone.utc),
        )
    assert wu_ok.calls == 0

    # After 2026-11-22T04:59Z -> WU fallback allowed: 61.5 -> 62 -> bin-mid
    p9_wu = engine_wu.evaluate_settlement(
        session_id="sess-wu",
        execution_mode="PAPER",
        station_id="KORD",
        target_date=d,
        target_type="TMAX",
        market_id="mkt-wu",
        reports=[],
        bins=bins,
        as_of_ts_utc=datetime(2026, 11, 22, 5, 5, tzinfo=timezone.utc),
    )
    assert wu_ok.calls == 1
    assert p9_wu.oracle_source == "WU_FALLBACK_DAILY"
    assert p9_wu.settled_temp_f_int == 62
    assert p9_wu.winning_bin_id == "bin-mid"

    # Both AWC and WU missing after deadline -> LOWEST_BIN_FALLBACK selects lowest bin
    engine_empty = M9SettlementEngine(wu_source=_FakeWuSource(None))
    p9_low = engine_empty.evaluate_settlement(
        session_id="sess-low",
        execution_mode="PAPER",
        station_id="KORD",
        target_date=d,
        target_type="TMAX",
        market_id="mkt-low",
        reports=[],
        bins=bins,
        as_of_ts_utc=datetime(2026, 11, 22, 5, 5, tzinfo=timezone.utc),
    )
    assert p9_low.oracle_source == "LOWEST_BIN_FALLBACK"
    assert p9_low.fallback_to_lowest_bin is True
    assert p9_low.winning_bin_id == "bin-low"


def test_m9_p15_release_updates_bankroll_conserves_fees_and_forbids_legacy_wu(tmp_path: Path) -> None:
    """E2E P14->P9->P15 release settles held positions, keeps zero residual, and obeys ADR-0012 D5."""
    from src.settlement.m9_settler import M9SettlementEngine, MarketPositionClaim, SettlementBinSpec

    t0 = datetime(2026, 11, 22, 14, 0, tzinfo=timezone.utc)
    d = date(2026, 11, 22)
    bins = (
        SettlementBinSpec("bin-57-below", None, 57),
        SettlementBinSpec("bin-58-59", 58, 59),
        SettlementBinSpec("bin-60-above", 60, None),
    )
    reports = [
        _metar("KORD", datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc), "METAR KORD 221800Z 00000KT 15/05 RMK T01500050"),  # 59°F
        _metar("KORD", datetime(2026, 11, 23, 6, 5, tzinfo=timezone.utc), "METAR KORD 230605Z 00000KT 10/04 RMK T01000040"),   # lock
    ]

    with AsyncAuditLogger(tmp_path / "m7", execution_mode="PAPER") as logger:
        mgr = BankrollAccountManager(
            BankrollConfig(
                session_id="sess-p15",
                execution_mode="PAPER",
                policy_version="p6.v3",
                config_hash="hash-p15",
                initial_pool_usd=Decimal("2000.00"),
            ),
            audit_logger=logger,
        )
        # Position 1 on winning bin (held $20.00 ex-fee + $0.40 fee for 40 shares @ $0.50 -> pays $40.00)
        assert mgr.freeze_for_order(FreezeRequest("d-win", "i-win", "KORD", "mkt-win", "tok-w", Decimal("25.00"), t0)).accepted
        mgr.settle_order_fill(
            FillSettleLoopback("d-win", "a-win", "KORD", "mkt-win", Decimal("20.00"), "FILLED", t0 + timedelta(seconds=1), fee_paid_usd=Decimal("0.40"))
        )
        # Position 2 on losing bin (held $10.00 for 20 shares -> pays $0.00 -> PnL = -$10.00)
        assert mgr.freeze_for_order(FreezeRequest("d-lose", "i-lose", "KORD", "mkt-lose", "tok-l", Decimal("10.00"), t0)).accepted
        mgr.settle_order_fill(
            FillSettleLoopback("d-lose", "a-lose", "KORD", "mkt-lose", Decimal("10.00"), "FILLED", t0 + timedelta(seconds=1))
        )

        engine = M9SettlementEngine(audit_logger=logger)
        settle_ts = datetime(2026, 11, 23, 6, 10, tzinfo=timezone.utc)
        out_win = engine.settle_and_release_p15(
            session_id="sess-p15",
            execution_mode="PAPER",
            station_id="KORD",
            target_date=d,
            target_type="TMAX",
            claim=MarketPositionClaim(market_id="mkt-win", bin_id="bin-58-59", held_shares=Decimal("40.00")),
            reports=reports,
            bins=bins,
            bankroll=mgr,
            as_of_ts_utc=settle_ts,
        )
        out_lose = engine.settle_and_release_p15(
            session_id="sess-p15",
            execution_mode="PAPER",
            station_id="KORD",
            target_date=d,
            target_type="TMAX",
            claim=MarketPositionClaim(market_id="mkt-lose", bin_id="bin-60-above", held_shares=Decimal("20.00")),
            reports=reports,
            bins=bins,
            bankroll=mgr,
            as_of_ts_utc=settle_ts,
        )
        logger.flush()

    assert out_win.p9_record.winning_bin_id == "bin-58-59"
    assert out_win.p15_event.payout_usd == Decimal("40.00")
    assert out_win.realized_pnl_usd == Decimal("20.00")
    assert out_lose.p15_event.payout_usd == Decimal("0")
    assert out_lose.realized_pnl_usd == Decimal("-10.00")

    snap = mgr.snapshot_state()
    assert snap.held_total_usd == Decimal("0")
    assert snap.free_usd == Decimal("2009.60")
    assert snap.fee_paid_total_usd == Decimal("0.40")
    assert snap.realized_pnl_total_usd == Decimal("10.00")
    assert snap.conservation_residual_usd == Decimal("0")

    # AST check per ADR-0012 D5: zero import from wunderground legacy package
    repo_root = Path(__file__).resolve().parents[3]
    for py_file in (repo_root / "src/settlement").glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all("wunderground" not in a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert "wunderground" not in node.module
