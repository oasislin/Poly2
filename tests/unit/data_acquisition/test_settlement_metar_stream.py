"""Unit and frame-by-frame acceptance tests for M1 (S3-01) settlement-isomorphic METAR stream."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
import json
import math
from pathlib import Path
import re
from typing import Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

import pytest

from src.data_acquisition.settlement_metar_stream import (
    CausalInputError,
    ForbiddenIntradaySourceError,
    FreshnessPolicy,
    HistoricalShadowMetarAdapter,
    LiveAwcMetarAdapter,
    MissingDispatchPolicy,
    PaperReplayMetarAdapter,
    RawMetarReport,
    SettlementIsomorphicParser,
    SettlementMetarStreamEngine,
    UnknownStationTimezoneError,
    celsius_to_fahrenheit_exact,
    classify_report_type,
    compute_local_day_window_utc,
    extract_settlement_reference_int,
    resolve_station_timezone,
    settle_round_pos_inf,
    verify_p12_json_line,
)
from src.data_processing.constants import ACTIVE_10_STATIONS
from src.utils.decimal_guard import DecimalOperandBoundsError


def _dt(iso_str: str) -> datetime:
    return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))


def _default_freshness() -> FreshnessPolicy:
    return FreshnessPolicy(
        physical_age_limit_sec=5400.0,
        dispatch_age_limit_sec=3600.0,
        require_dispatch_age=False,
        provenance="TEST_CONSERVATIVE_POLICY_V0",
    )


def _strict_missing_dispatch() -> MissingDispatchPolicy:
    return MissingDispatchPolicy(
        mode="REJECT",
        provenance="TEST_FAIL_CLOSED_REJECT",
    )


def test_active_10_stations_all_resolve_valid_iana_timezones() -> None:
    assert len(ACTIVE_10_STATIONS) == 10
    for st in ACTIVE_10_STATIONS:
        tz = resolve_station_timezone(st)
        assert isinstance(tz, ZoneInfo)
    with pytest.raises(UnknownStationTimezoneError):
        resolve_station_timezone("XXXX")


def test_exact_decimal_conversion_and_pos_inf_half_rounding_isolated_from_global_prec() -> None:
    """Verify ADR-0012 §5 official negative half-degree example and thread-context isolation."""
    with localcontext() as hostile_ctx:
        hostile_ctx.prec = 6  # hostile tiny precision must NOT affect guarded Decimal functions
        assert celsius_to_fahrenheit_exact(Decimal("-22.5")) == Decimal("-8.5")
        assert settle_round_pos_inf(Decimal("-8.5")) == -8
        assert settle_round_pos_inf(celsius_to_fahrenheit_exact(Decimal("-22.5"))) == -8
        assert settle_round_pos_inf(celsius_to_fahrenheit_exact(Decimal("-22.6"))) == -9
        assert settle_round_pos_inf(Decimal("-0.5")) == 0
        assert settle_round_pos_inf(Decimal("-0.50001")) == -1
        assert settle_round_pos_inf(Decimal("0.5")) == 1
        assert settle_round_pos_inf(Decimal("68.5")) == 69
        assert settle_round_pos_inf(Decimal("68.49999")) == 68

    # Over-precision 17-digit operand is rejected structurally
    with pytest.raises(DecimalOperandBoundsError):
        celsius_to_fahrenheit_exact(Decimal("20.123456789012345"))


def test_max_and_min_commute_with_floor_x_plus_half() -> None:
    """Verify v0.3 §1.2 max/floor & min/floor commutation across tenths of °C including ties."""
    temps_c = [Decimal(n) / Decimal("10") for n in range(-300, 451)]  # -30.0°C .. +45.0°C
    temps_f = [celsius_to_fahrenheit_exact(tc) for tc in temps_c]

    for idx in range(0, len(temps_f) - 10, 7):
        subset = temps_f[idx : idx + 11]
        assert settle_round_pos_inf(max(subset)) == max(settle_round_pos_inf(x) for x in subset)
        assert settle_round_pos_inf(min(subset)) == min(settle_round_pos_inf(x) for x in subset)


def test_metar_parser_tgroup_priority_body_fallback_and_classification() -> None:
    # 1. T-group 0.1°C takes priority over integer body TT/TD
    raw_tgroup = "METAR KORD 181451Z 27010KT 10SM CLR 20/15 A3001 RMK AO2 SLP162 T02030150"
    tc, tier = SettlementIsomorphicParser.parse_temperature_c(raw_tgroup)
    assert tc == Decimal("20.3")
    assert tier == "AWC_METAR_TGROUP"
    assert classify_report_type(raw_tgroup) == "METAR"

    # 2. Negative T-group (-22.5°C -> -8.5°F -> -8°F)
    raw_neg = "METAR KORD 151151Z 31012KT 10SM FEW020 M23/M27 A3020 RMK AO2 T12251270"
    tc_neg, tier_neg = SettlementIsomorphicParser.parse_temperature_c(raw_neg)
    assert tc_neg == Decimal("-22.5")
    assert tier_neg == "AWC_METAR_TGROUP"
    assert settle_round_pos_inf(celsius_to_fahrenheit_exact(tc_neg)) == -8

    # 3. Missing dewpoint in T-group (T0206////)
    tc_nodp, tier_nodp = SettlementIsomorphicParser.parse_temperature_c(
        "KORD 181551Z 27008KT 10SM CLR 21/// A3000 RMK AO2 T0206////"
    )
    assert tc_nodp == Decimal("20.6")
    assert tier_nodp == "AWC_METAR_TGROUP"

    # 4. Missing T-group falls back to body TT/TD
    raw_body = "KORD 181620Z 27008KT 10SM CLR M05/M10 A3000 RMK AO2"
    tc_body, tier_body = SettlementIsomorphicParser.parse_temperature_c(raw_body)
    assert tc_body == Decimal("-5")
    assert tier_body == "AWC_METAR_BODY"
    # Unlabeled routine off-nominal-hour report counts as routine METAR per official wording
    assert classify_report_type(raw_body) == "METAR"

    # 5. SPECI line is classified as SPECI
    assert classify_report_type("SPECI KORD 181612Z 27015G25KT 10SM FEW040 25/14 A2998 RMK AO2 T02500140") == "SPECI"

    # 6. Completely missing temperature
    tc_miss, tier_miss = SettlementIsomorphicParser.parse_temperature_c("METAR KORD 181751Z AUTO ////")
    assert tc_miss is None
    assert tier_miss == "MISSING"

    # 7. Routine METAR mentioning SPECI inside remarks still counts as METAR; -0.0°C normalizes cleanly
    raw_rmk_speci = "METAR KORD 181851Z 27005KT 10SM CLR M00/M02 A3000 RMK AO2 T10001020 PREV SPECI"
    assert classify_report_type(raw_rmk_speci) == "METAR"
    tc_zero, tier_zero = SettlementIsomorphicParser.parse_temperature_c(raw_rmk_speci)
    assert tc_zero == Decimal("0.0")
    assert not tc_zero.is_signed()
    assert tier_zero == "AWC_METAR_TGROUP"
    assert settle_round_pos_inf(celsius_to_fahrenheit_exact(tc_zero)) == 32


def test_freshness_policy_physical_and_dispatch_age_limits() -> None:
    rep = RawMetarReport(
        station_id="KATL",
        obs_ts_utc=_dt("2026-07-15T14:51:00Z"),
        dispatch_ts_utc=_dt("2026-07-15T15:05:00Z"),
        report_type="METAR",
        is_cor=False,
        raw_text="METAR KATL 151451Z 22008KT 10SM CLR 30/20 A3000 RMK AO2 T03000200",
        source_channel="PAPER_REPLAY",
    )
    policy = FreshnessPolicy(
        physical_age_limit_sec=1800.0,  # 30 min
        dispatch_age_limit_sec=600.0,   # 10 min
        require_dispatch_age=True,
        provenance="TEST_TIGHT_AGE_POLICY",
    )
    engine = SettlementMetarStreamEngine(
        source=PaperReplayMetarAdapter([rep]),
        freshness_policy=policy,
        missing_dispatch_policy=_strict_missing_dispatch(),
    )
    # At 15:10Z: physical_age = 19m <= 30m, dispatch_age = 5m <= 10m -> OK
    ev_ok = engine.evaluate_as_of(
        station_id="KATL",
        target_date=date(2026, 7, 15),
        as_of_ts_utc=_dt("2026-07-15T15:10:00Z"),
        session_id="sess-fresh",
        execution_mode="PAPER",
        model_hash="m",
        config_hash="c",
    )
    assert ev_ok.state.freshness_ok is True
    assert ev_ok.state.gap_flags == ()

    # At 15:18Z: physical_age = 27m <= 30m, dispatch_age = 13m > 10m -> DISPATCH_AGE_EXCEEDED
    ev_disp = engine.evaluate_as_of(
        station_id="KATL",
        target_date=date(2026, 7, 15),
        as_of_ts_utc=_dt("2026-07-15T15:18:00Z"),
        session_id="sess-fresh",
        execution_mode="PAPER",
        model_hash="m",
        config_hash="c",
    )
    assert ev_disp.state.freshness_ok is False
    assert "DISPATCH_AGE_EXCEEDED" in ev_disp.state.gap_flags
    assert "PHYSICAL_AGE_EXCEEDED" not in ev_disp.state.gap_flags

    # At 15:30Z: physical_age = 39m > 30m AND dispatch_age = 25m > 10m -> BOTH flagged
    ev_both = engine.evaluate_as_of(
        station_id="KATL",
        target_date=date(2026, 7, 15),
        as_of_ts_utc=_dt("2026-07-15T15:30:00Z"),
        session_id="sess-fresh",
        execution_mode="PAPER",
        model_hash="m",
        config_hash="c",
    )
    assert ev_both.state.freshness_ok is False
    assert "PHYSICAL_AGE_EXCEEDED" in ev_both.state.gap_flags
    assert "DISPATCH_AGE_EXCEEDED" in ev_both.state.gap_flags


def test_dst_23h_spring_forward_and_25h_fall_back_windows() -> None:
    chi = resolve_station_timezone("KORD")  # America/Chicago

    # 2026-03-08: US DST spring forward (23 hours)
    start_sf, end_sf = compute_local_day_window_utc(date(2026, 3, 8), chi)
    assert (end_sf - start_sf) == timedelta(hours=23)
    assert start_sf == _dt("2026-03-08T06:00:00Z")
    assert end_sf == _dt("2026-03-09T05:00:00Z")

    # 2026-11-01: US DST fall back (25 hours)
    start_fb, end_fb = compute_local_day_window_utc(date(2026, 11, 1), chi)
    assert (end_fb - start_fb) == timedelta(hours=25)
    assert start_fb == _dt("2026-11-01T05:00:00Z")
    assert end_fb == _dt("2026-11-02T06:00:00Z")

    # Observation at 2026-11-02T05:51:00Z is 2026-11-01 23:51 CST -> belongs to 2026-11-01!
    late_local_rep = RawMetarReport(
        station_id="KORD",
        obs_ts_utc=_dt("2026-11-02T05:51:00Z"),
        dispatch_ts_utc=_dt("2026-11-02T05:53:00Z"),
        report_type="METAR",
        is_cor=False,
        raw_text="METAR KORD 020551Z 27005KT 10SM CLR 15/10 A3000 RMK AO2 T01500100",
        source_channel="PAPER_REPLAY",
    )
    engine = SettlementMetarStreamEngine(
        source=PaperReplayMetarAdapter([late_local_rep]),
        freshness_policy=_default_freshness(),
        missing_dispatch_policy=_strict_missing_dispatch(),
    )
    ev = engine.evaluate_as_of(
        station_id="KORD",
        target_date=date(2026, 11, 1),
        as_of_ts_utc=_dt("2026-11-02T05:55:00Z"),
        session_id="sess-dst",
        execution_mode="PAPER",
        model_hash="mhash",
        config_hash="chash",
    )
    assert ev.state.routine_obs_count == 1
    assert ev.state.m_now_int_f == 59  # 15.0°C = 59.0°F
    assert ev.state.settle_close_utc == _dt("2026-11-02T06:00:00Z")


def test_speci_excluded_from_m_now_but_preserved_in_archival_and_p12() -> None:
    reports = [
        RawMetarReport(
            station_id="KORD",
            obs_ts_utc=_dt("2026-07-15T18:51:00Z"),
            dispatch_ts_utc=_dt("2026-07-15T18:53:00Z"),
            report_type="METAR",
            is_cor=False,
            raw_text="METAR KORD 151851Z 20010KT 10SM FEW050 28/18 A2995 RMK AO2 T02800180",
            source_channel="PAPER_REPLAY",
        ),
        # Hot SPECI (32.0°C = 89.6°F -> 90°F) MUST NOT enter bridge m_now!
        RawMetarReport(
            station_id="KORD",
            obs_ts_utc=_dt("2026-07-15T19:15:00Z"),
            dispatch_ts_utc=_dt("2026-07-15T19:17:00Z"),
            report_type="SPECI",
            is_cor=False,
            raw_text="SPECI KORD 151915Z 20015G25KT 10SM SCT050 32/18 A2993 RMK AO2 T03200180",
            source_channel="PAPER_REPLAY",
        ),
    ]
    engine = SettlementMetarStreamEngine(
        source=PaperReplayMetarAdapter(reports),
        freshness_policy=_default_freshness(),
        missing_dispatch_policy=_strict_missing_dispatch(),
    )
    ev = engine.evaluate_as_of(
        station_id="KORD",
        target_date=date(2026, 7, 15),
        as_of_ts_utc=_dt("2026-07-15T19:20:00Z"),
        session_id="sess-speci",
        execution_mode="PAPER",
        model_hash="mhash",
        config_hash="chash",
    )
    assert ev.state.oracle_compliant is True
    assert ev.state.m_now_exact_f == Decimal("82.4")  # 28.0°C = 82.4°F
    assert ev.state.m_now_int_f == 82
    assert ev.state.routine_obs_count == 1
    assert ev.state.specis_seen_count == 1
    # Full archival stream preserves BOTH METAR and SPECI
    assert len(ev.archival_observations) == 2
    assert any(o.report_type == "SPECI" and o.temp_c_dec == Decimal("32.0") for o in ev.archival_observations)

    # P12 JSONL serialization and canonical SHA256 integrity
    line = ev.coverage_ledger.to_json_line()
    assert verify_p12_json_line(line) is True
    parsed = json.loads(line)
    assert parsed["schema_version"] == "p12.v1"
    assert parsed["specis_seen_count"] == 1
    assert parsed["total_reports_archived_count"] == 2
    assert parsed["metar_obs_count_window"] == 1
    # Tampering breaks SHA256 verification
    parsed["specis_seen_count"] = 99
    assert verify_p12_json_line(json.dumps(parsed)) is False


def test_causal_no_lookahead_and_missing_dispatch_policy_rules() -> None:
    # 0s lag assumption is forbidden structurally
    with pytest.raises(ValueError, match="strictly > 0.0"):
        MissingDispatchPolicy(
            mode="CONSERVATIVE_LAG_BOUND",
            conservative_lag_bound_sec=0.0,
            provenance="ILLEGAL_ZERO_LAG",
        )

    rep_with_dispatch = RawMetarReport(
        station_id="KLGA",
        obs_ts_utc=_dt("2026-07-15T14:51:00Z"),
        dispatch_ts_utc=_dt("2026-07-15T14:56:00Z"),
        report_type="METAR",
        is_cor=False,
        raw_text="METAR KLGA 151451Z 18008KT 10SM CLR 25/15 A3000 RMK AO2 T02500150",
        source_channel="PAPER_REPLAY",
    )
    engine_reject = SettlementMetarStreamEngine(
        source=PaperReplayMetarAdapter([rep_with_dispatch]),
        freshness_policy=_default_freshness(),
        missing_dispatch_policy=_strict_missing_dispatch(),
    )
    # At 14:54Z (after obs_ts 14:51Z, before dispatch_ts 14:56Z): MUST BE HIDDEN!
    ev_early = engine_reject.evaluate_as_of(
        station_id="KLGA",
        target_date=date(2026, 7, 15),
        as_of_ts_utc=_dt("2026-07-15T14:54:00Z"),
        session_id="sess-causal",
        execution_mode="PAPER",
        model_hash="mhash",
        config_hash="chash",
    )
    assert ev_early.state.m_now_int_f is None
    assert ev_early.state.freshness_ok is False

    # At 14:56Z (dispatch_ts reached): NOW VISIBLE!
    ev_visible = engine_reject.evaluate_as_of(
        station_id="KLGA",
        target_date=date(2026, 7, 15),
        as_of_ts_utc=_dt("2026-07-15T14:56:00Z"),
        session_id="sess-causal",
        execution_mode="PAPER",
        model_hash="mhash",
        config_hash="chash",
    )
    assert ev_visible.state.m_now_int_f == 77
    assert ev_visible.state.dispatch_age_available is True
    assert ev_visible.state.dispatch_age_sec == 0.0
    assert ev_visible.state.physical_age_sec == 300.0
    assert ev_visible.state.freshness_ok is True

    # Historical shadow archive with dispatch_ts_utc=None
    shadow_adapter = HistoricalShadowMetarAdapter(
        [
            {
                "station_id": "KLGA",
                "obs_ts_utc": "2026-07-15T15:51:00Z",
                "dispatch_ts_utc": None,
                "raw_text": "METAR KLGA 151551Z 18008KT 10SM CLR 26/15 A3000 RMK AO2 T02600150",
            }
        ]
    )
    # 1. Mode REJECT excludes missing-dispatch reports
    ev_rej = SettlementMetarStreamEngine(
        source=shadow_adapter,
        freshness_policy=_default_freshness(),
        missing_dispatch_policy=_strict_missing_dispatch(),
    ).evaluate_as_of(
        station_id="KLGA",
        target_date=date(2026, 7, 15),
        as_of_ts_utc=_dt("2026-07-15T16:30:00Z"),
        session_id="sess-hist",
        execution_mode="PAPER",
        model_hash="mhash",
        config_hash="chash",
    )
    assert ev_rej.state.m_now_int_f is None
    assert "MISSING_DISPATCH_TS_REJECTED" in ev_rej.state.gap_flags

    # 2. Mode CONSERVATIVE_LAG_BOUND (e.g. 1200s = 20min bound)
    lag_policy = MissingDispatchPolicy(
        mode="CONSERVATIVE_LAG_BOUND",
        conservative_lag_bound_sec=1200.0,
        provenance="MEASURED_P99_ARCHIVE_LAG_1200S",
    )
    engine_lag = SettlementMetarStreamEngine(
        source=shadow_adapter,
        freshness_policy=_default_freshness(),
        missing_dispatch_policy=lag_policy,
    )
    # At 16:05Z (only 14 min after obs_ts): still hidden under 20 min lag bound!
    ev_lag_early = engine_lag.evaluate_as_of(
        station_id="KLGA",
        target_date=date(2026, 7, 15),
        as_of_ts_utc=_dt("2026-07-15T16:05:00Z"),
        session_id="sess-hist",
        execution_mode="PAPER",
        model_hash="mhash",
        config_hash="chash",
    )
    assert ev_lag_early.state.m_now_int_f is None

    # At 16:15Z (24 min after obs_ts >= 20 min bound): admitted with dispatch_age_available=False!
    ev_lag_ok = engine_lag.evaluate_as_of(
        station_id="KLGA",
        target_date=date(2026, 7, 15),
        as_of_ts_utc=_dt("2026-07-15T16:15:00Z"),
        session_id="sess-hist",
        execution_mode="PAPER",
        model_hash="mhash",
        config_hash="chash",
    )
    assert ev_lag_ok.state.m_now_int_f == 79  # 26.0°C = 78.8°F -> 79°F
    assert ev_lag_ok.state.dispatch_age_available is False
    assert ev_lag_ok.state.dispatch_age_sec is None
    assert "MISSING_DISPATCH_TS_BOUNDED" in ev_lag_ok.state.gap_flags
    assert ev_lag_ok.state.freshness_ok is True

    # If FreshnessPolicy requires dispatch_age, missing dispatch_age fails freshness_ok
    strict_fresh = FreshnessPolicy(
        physical_age_limit_sec=5400.0,
        dispatch_age_limit_sec=1800.0,
        require_dispatch_age=True,
        provenance="STRICT_DISPATCH_REQUIRED",
    )
    ev_lag_fail_fresh = SettlementMetarStreamEngine(
        source=shadow_adapter,
        freshness_policy=strict_fresh,
        missing_dispatch_policy=lag_policy,
    ).evaluate_as_of(
        station_id="KLGA",
        target_date=date(2026, 7, 15),
        as_of_ts_utc=_dt("2026-07-15T16:15:00Z"),
        session_id="sess-hist",
        execution_mode="PAPER",
        model_hash="mhash",
        config_hash="chash",
    )
    assert ev_lag_fail_fresh.state.freshness_ok is False
    assert "DISPATCH_AGE_UNAVAILABLE" in ev_lag_fail_fresh.state.gap_flags


def test_wu_intraday_source_strictly_rejected_and_naive_timestamps_rejected() -> None:
    wu_report = RawMetarReport(
        station_id="KORD",
        obs_ts_utc=_dt("2026-07-15T14:51:00Z"),
        dispatch_ts_utc=_dt("2026-07-15T14:55:00Z"),
        report_type="METAR",
        is_cor=False,
        raw_text="METAR KORD 151451Z 27008KT 10SM CLR 25/15 A3000 RMK AO2 T02500150",
        source_channel="WEATHER_UNDERGROUND_DAILY",
    )
    with pytest.raises(ForbiddenIntradaySourceError):
        PaperReplayMetarAdapter([wu_report])

    with pytest.raises(CausalInputError):
        RawMetarReport(
            station_id="KORD",
            obs_ts_utc=datetime(2026, 7, 15, 14, 51, 0),  # naive!
            dispatch_ts_utc=None,
            report_type="METAR",
            is_cor=False,
            raw_text="METAR KORD 151451Z 27008KT 10SM CLR 25/15 A3000 RMK AO2 T02500150",
            source_channel="AWC_LIVE",
        )


def test_live_awc_adapter_offline_mock_and_paper_jsonl_roundtrip(tmp_path: Path) -> None:
    mock_payload = [
        {
            "icaoId": "KORD",
            "obsTime": int(_dt("2026-07-15T14:51:00Z").timestamp()),
            "receiptTime": "2026-07-15T14:54:00Z",
            "metarType": "METAR",
            "rawOb": "METAR KORD 151451Z 27008KT 10SM CLR 25/15 A3000 RMK AO2 T02500150",
        },
        {
            "icaoId": "KORD",
            "obsTime": int(_dt("2026-07-15T15:10:00Z").timestamp()),
            "receiptTime": "2026-07-15T15:12:00Z",
            "metarType": "SPECI",
            "rawOb": "SPECI KORD 151510Z 27018KT 10SM SCT040 29/15 A2998 RMK AO2 T02900150",
        },
    ]
    captured_params: Dict[str, object] = {}

    def fake_get(url: str, params: Dict[str, object], timeout: float) -> object:
        captured_params.update(params)
        assert "aviationweather.gov/api/data/metar" in url
        return mock_payload

    adapter = LiveAwcMetarAdapter(
        http_get=fake_get,
        clock_utc=lambda: _dt("2026-07-15T16:00:00Z"),
    )
    fetched = adapter.fetch_window("KORD", _dt("2026-07-15T05:00:00Z"), _dt("2026-07-16T05:00:00Z"))
    assert len(fetched) == 2
    assert captured_params["ids"] == "KORD"
    assert fetched[0].report_type == "METAR"
    assert fetched[1].report_type == "SPECI"

    # PaperReplayMetarAdapter JSONL round-trip
    jsonl_path = tmp_path / "metar_replay.jsonl"
    rows = [
        {
            "station_id": "KORD",
            "obs_ts_utc": "2026-07-15T14:51:00Z",
            "dispatch_ts_utc": "2026-07-15T14:54:00Z",
            "raw_text": "METAR KORD 151451Z 27008KT 10SM CLR 25/15 A3000 RMK AO2 T02500150",
        }
    ]
    jsonl_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    loaded = PaperReplayMetarAdapter.from_jsonl(jsonl_path)
    out = loaded.fetch_window("KORD", _dt("2026-07-15T05:00:00Z"), _dt("2026-07-16T05:00:00Z"))
    assert len(out) == 1
    assert out[0].dispatch_ts_utc == _dt("2026-07-15T14:54:00Z")


def _independent_polymarket_contract_oracle_prefix_int(
    *,
    target_date: date,
    station_tz_name: str,
    reports: Sequence[RawMetarReport],
    as_of_utc: Optional[datetime],
) -> Optional[int]:
    """100% independent test-side implementation of Polymarket literal contract wording.

    Does NOT call `SettlementMetarStreamEngine` or `SettlementIsomorphicParser`, eliminating any
    circular validation risk in the S3-01 acceptance test.
    """
    tz = ZoneInfo(station_tz_name)
    next_day = target_date + timedelta(days=1)
    start_utc = datetime(target_date.year, target_date.month, target_date.day, tzinfo=tz).astimezone(timezone.utc)
    end_utc = datetime(next_day.year, next_day.month, next_day.day, tzinfo=tz).astimezone(timezone.utc)
    et_deadline = datetime(
        next_day.year, next_day.month, next_day.day, 23, 59, 0, tzinfo=ZoneInfo("America/New_York")
    ).astimezone(timezone.utc)

    # Lock point if post-close or full-day settlement
    lock_ts: Optional[datetime] = None
    if as_of_utc is None or as_of_utc >= end_utc:
        next_day_routines = [
            (r.dispatch_ts_utc or r.obs_ts_utc)
            for r in reports
            if r.obs_ts_utc >= end_utc
            and not r.raw_text.lstrip().upper().startswith("SPECI")
            and (
                as_of_utc is None
                or (r.obs_ts_utc <= as_of_utc and r.dispatch_ts_utc is not None and r.dispatch_ts_utc <= as_of_utc)
            )
        ]
        lock_ts = min(next_day_routines + [et_deadline])

    by_obs: Dict[datetime, List[RawMetarReport]] = {}
    for r in reports:
        if r.raw_text.lstrip().upper().startswith("SPECI"):
            continue
        if not (start_utc <= r.obs_ts_utc < end_utc):
            continue
        if as_of_utc is not None:
            if r.obs_ts_utc > as_of_utc or r.dispatch_ts_utc is None or r.dispatch_ts_utc > as_of_utc:
                continue
        eff = r.dispatch_ts_utc or r.obs_ts_utc
        if lock_ts is not None and r.is_cor and eff > lock_ts:
            continue
        by_obs.setdefault(r.obs_ts_utc, []).append(r)

    vals_int: List[int] = []
    for _, grp in by_obs.items():
        chosen = sorted(
            grp, key=lambda r: (1 if r.is_cor else 0, r.dispatch_ts_utc or r.obs_ts_utc, r.sequence_hint)
        )[-1]
        raw = chosen.raw_text
        # T-group first, else body TT/TD
        m_t = re.search(r"(?:^|\s)T([01])(\d{3})(?:[01]\d{3}|////)(?=\s|$)", raw)
        if m_t:
            c_dec = Decimal(m_t.group(2)) / Decimal("10")
            if m_t.group(1) == "1":
                c_dec = -c_dec
        else:
            body = re.split(r"\bRMK\b", raw, maxsplit=1, flags=re.IGNORECASE)[0]
            m_b = re.search(r"(?:^|\s)(M?\d{2})/(?:M?\d{2}|//)(?=\s|$)", body)
            if not m_b:
                continue
            tok = m_b.group(1)
            c_dec = Decimal(-int(tok[1:])) if tok.startswith("M") else Decimal(int(tok))
        f_dec = c_dec * Decimal("9") / Decimal("5") + Decimal("32")
        # Independent floor(x + 0.5) using exact integer arithmetic via rational denominator 100
        # f_dec has at most 2 decimal places for tenths of °C
        f_times_200 = int(f_dec * Decimal("200"))
        vals_int.append(math.floor((f_times_200 + 100) / 200))

    return max(vals_int) if vals_int else None


def test_s3_01_acceptance_frame_by_frame_settlement_isomorphism() -> None:
    """Official S3-01 acceptance gate: paper replay M_now matches settlement oracle frame-by-frame.

    Exercises a full local winter/cold-front day at KORD (America/Chicago, CST = UTC-6) with:
    1. Empty pre-first-report frame (None)
    2. Negative exact .5°F tie (-22.5°C = -8.5°F -> -8°F)
    3. Body-only TT/TD fallback without T-group (M21/M26 -> -21°C = -5.8°F -> -6°F)
    4. Off-nominal-hour unlabeled routine report (no METAR prefix; counts as routine!)
    5. SPECI spike hotter than any routine report (+5.0°C = 41°F -> MUST BE IGNORED in M_now!)
    6. Erroneous routine spike (-5.0°C = 23°F) subsequently retracted downward by COR (-17.5°C = 0.5°F -> 1°F)
    7. Upward COR setting final daily high (-16.0°C = 3.2°F -> 3°F)
    8. Next-day first routine METAR locking settlement, followed by an ignored post-lock COR (+10°C = 50°F)
    """
    target_day = date(2026, 1, 15)  # KORD CST: [2026-01-15T06:00Z, 2026-01-16T06:00Z)
    timeline_reports: List[RawMetarReport] = [
        # 1. Negative half-degree exact tie: -22.5°C -> -8.5°F -> -8°F
        RawMetarReport(
            station_id="KORD",
            obs_ts_utc=_dt("2026-01-15T06:51:00Z"),
            dispatch_ts_utc=_dt("2026-01-15T06:55:00Z"),
            report_type="METAR",
            is_cor=False,
            raw_text="METAR KORD 150651Z 31010KT 10SM CLR M23/M28 A3030 RMK AO2 T12251280",
            source_channel="PAPER_REPLAY",
            sequence_hint=1,
        ),
        # 2. Body-only fallback (no T-group): M21/M26 -> -21°C = -5.8°F -> -6°F
        RawMetarReport(
            station_id="KORD",
            obs_ts_utc=_dt("2026-01-15T09:51:00Z"),
            dispatch_ts_utc=_dt("2026-01-15T09:55:00Z"),
            report_type="METAR",
            is_cor=False,
            raw_text="METAR KORD 150951Z 30008KT 10SM CLR M21/M26 A3028 RMK AO2",
            source_channel="PAPER_REPLAY",
            sequence_hint=2,
        ),
        # 3. Unlabeled off-nominal-hour routine report: -19.5°C = -3.1°F -> -3°F
        RawMetarReport(
            station_id="KORD",
            obs_ts_utc=_dt("2026-01-15T13:20:00Z"),
            dispatch_ts_utc=_dt("2026-01-15T13:24:00Z"),
            report_type="METAR",
            is_cor=False,
            raw_text="KORD 151320Z 29009KT 10SM CLR M20/M25 A3025 RMK AO2 T11951250",
            source_channel="PAPER_REPLAY",
            sequence_hint=3,
        ),
        # 4. Hot SPECI (+5.0°C = 41°F): MUST NOT alter M_now
        RawMetarReport(
            station_id="KORD",
            obs_ts_utc=_dt("2026-01-15T15:12:00Z"),
            dispatch_ts_utc=_dt("2026-01-15T15:14:00Z"),
            report_type="SPECI",
            is_cor=False,
            raw_text="SPECI KORD 151512Z 25020KT 10SM SCT040 05/M05 A3010 RMK AO2 T00501050",
            source_channel="PAPER_REPLAY",
            sequence_hint=4,
        ),
        # 5a. Erroneous routine spike (-5.0°C = 23°F) at 17:51Z
        RawMetarReport(
            station_id="KORD",
            obs_ts_utc=_dt("2026-01-15T17:51:00Z"),
            dispatch_ts_utc=_dt("2026-01-15T17:55:00Z"),
            report_type="METAR",
            is_cor=False,
            raw_text="METAR KORD 151751Z 26012KT 10SM FEW050 M05/M22 A3015 RMK AO2 T10501220",
            source_channel="PAPER_REPLAY",
            sequence_hint=5,
        ),
        # 5b. Downward COR for 17:51Z correcting erroneous spike down to -17.5°C = +0.5°F -> 1°F
        RawMetarReport(
            station_id="KORD",
            obs_ts_utc=_dt("2026-01-15T17:51:00Z"),
            dispatch_ts_utc=_dt("2026-01-15T18:05:00Z"),
            report_type="METAR",
            is_cor=True,
            raw_text="METAR COR KORD 151751Z 26012KT 10SM FEW050 M18/M22 A3015 RMK AO2 T11751220",
            source_channel="PAPER_REPLAY",
            sequence_hint=6,
        ),
        # 6a. Routine obs at 20:51Z: -17.0°C = 1.4°F -> 1°F
        RawMetarReport(
            station_id="KORD",
            obs_ts_utc=_dt("2026-01-15T20:51:00Z"),
            dispatch_ts_utc=_dt("2026-01-15T20:54:00Z"),
            report_type="METAR",
            is_cor=False,
            raw_text="METAR KORD 152051Z 26010KT 10SM CLR M17/M22 A3014 RMK AO2 T11701220",
            source_channel="PAPER_REPLAY",
            sequence_hint=7,
        ),
        # 6b. Upward COR for 20:51Z before lock: -16.0°C = 3.2°F -> 3°F (true settled high!)
        RawMetarReport(
            station_id="KORD",
            obs_ts_utc=_dt("2026-01-15T20:51:00Z"),
            dispatch_ts_utc=_dt("2026-01-15T21:10:00Z"),
            report_type="METAR",
            is_cor=True,
            raw_text="METAR COR KORD 152051Z 26010KT 10SM CLR M16/M22 A3014 RMK AO2 T11601220",
            source_channel="PAPER_REPLAY",
            sequence_hint=8,
        ),
        # 7. Next-day first routine METAR (2026-01-16T06:51Z dispatched at 06:55Z) -> LOCKS target_day!
        RawMetarReport(
            station_id="KORD",
            obs_ts_utc=_dt("2026-01-16T06:51:00Z"),
            dispatch_ts_utc=_dt("2026-01-16T06:55:00Z"),
            report_type="METAR",
            is_cor=False,
            raw_text="METAR KORD 160651Z 26008KT 10SM CLR M18/M23 A3016 RMK AO2 T11801230",
            source_channel="PAPER_REPLAY",
            sequence_hint=9,
        ),
        # 8. Late post-lock COR for 20:51Z dispatched at 07:30Z AFTER lock -> MUST BE IGNORED!
        RawMetarReport(
            station_id="KORD",
            obs_ts_utc=_dt("2026-01-15T20:51:00Z"),
            dispatch_ts_utc=_dt("2026-01-16T07:30:00Z"),
            report_type="METAR",
            is_cor=True,
            raw_text="METAR COR KORD 152051Z 26010KT 10SM CLR 10/M05 A3014 RMK AO2 T01001050",
            source_channel="PAPER_REPLAY",
            sequence_hint=10,
        ),
    ]

    engine = SettlementMetarStreamEngine(
        source=PaperReplayMetarAdapter(timeline_reports),
        freshness_policy=_default_freshness(),
        missing_dispatch_policy=_strict_missing_dispatch(),
    )

    scan_frames = [
        (_dt("2026-01-15T06:30:00Z"), None),   # before first report
        (_dt("2026-01-15T06:53:00Z"), None),   # obs_ts passed, dispatch_ts not yet reached
        (_dt("2026-01-15T07:00:00Z"), -8),     # -22.5°C = -8.5°F -> -8°F
        (_dt("2026-01-15T10:00:00Z"), -6),     # body fallback -21°C -> -6°F
        (_dt("2026-01-15T13:30:00Z"), -3),     # unlabeled off-hour routine -19.5°C -> -3°F
        (_dt("2026-01-15T15:30:00Z"), -3),     # hot SPECI ignored! still -3°F
        (_dt("2026-01-15T18:00:00Z"), 23),     # erroneous spike before COR
        (_dt("2026-01-15T18:10:00Z"), 1),      # downward COR applied -> -17.5°C = 0.5°F -> 1°F
        (_dt("2026-01-15T21:00:00Z"), 1),      # 20:51Z initial -17.0°C -> 1°F
        (_dt("2026-01-15T21:15:00Z"), 3),      # upward COR -> -16.0°C = 3.2°F -> 3°F
        (_dt("2026-01-16T05:59:00Z"), 3),      # 1 min before local midnight
        (_dt("2026-01-16T07:45:00Z"), 3),      # post-lock late COR ignored -> locked at 3°F!
    ]

    full_day_settled_int = _independent_polymarket_contract_oracle_prefix_int(
        target_date=target_day,
        station_tz_name="America/Chicago",
        reports=timeline_reports,
        as_of_utc=None,
    )
    assert full_day_settled_int == 3

    matched_frames = 0
    for scan_ts, expected_int in scan_frames:
        ev = engine.evaluate_as_of(
            station_id="KORD",
            target_date=target_day,
            as_of_ts_utc=scan_ts,
            session_id="sess-s3-01-accept",
            execution_mode="PAPER",
            model_hash="model_v1",
            config_hash="cfg_v1",
        )
        indep_prefix_int = _independent_polymarket_contract_oracle_prefix_int(
            target_date=target_day,
            station_tz_name="America/Chicago",
            reports=timeline_reports,
            as_of_utc=scan_ts,
        )
        ref_prefix_int = extract_settlement_reference_int(
            station_id="KORD",
            target_date=target_day,
            reports=timeline_reports,
            as_of_ts_utc=scan_ts,
        )

        # Frame-by-frame isomorphism assertions
        assert ev.state.oracle_compliant is True
        assert ev.state.m_now_int_f == expected_int
        assert ev.state.m_now_int_f == indep_prefix_int
        assert ev.state.m_now_int_f == ref_prefix_int
        assert verify_p12_json_line(ev.coverage_ledger.to_json_line()) is True
        matched_frames += 1

    # Mechanical acceptance boolean sunk into code
    acceptance_pass = matched_frames == len(scan_frames)
    assert acceptance_pass is True

    # Verify final post-lock evaluation recorded POST_LOCK_COR_IGNORED and preserved SPECI count
    final_ev = engine.evaluate_as_of(
        station_id="KORD",
        target_date=target_day,
        as_of_ts_utc=_dt("2026-01-16T07:45:00Z"),
        session_id="sess-s3-01-accept",
        execution_mode="PAPER",
        model_hash="model_v1",
        config_hash="cfg_v1",
    )
    assert final_ev.state.m_now_int_f == full_day_settled_int == 3
    assert final_ev.state.specis_seen_count == 1
    assert final_ev.state.cor_overwrites_count == 2
    assert "POST_LOCK_COR_IGNORED" in final_ev.state.gap_flags


def test_post_close_lock_monotonic_under_conservative_lag_bound() -> None:
    """Patch 1: lock time aligns with effective causal availability under CONSERVATIVE_LAG_BOUND."""
    reports = [
        RawMetarReport(
            station_id="KORD",
            obs_ts_utc=_dt("2026-01-15T18:00:00Z"),
            dispatch_ts_utc=_dt("2026-01-15T18:05:00Z"),
            report_type="METAR",
            is_cor=False,
            raw_text="METAR KORD 151800Z 20/10 RMK T02000100",
            source_channel="PAPER_REPLAY",
            sequence_hint=1,
        ),
        # COR arrives at 06:55Z: before next-day METAR bounded visibility (06:51Z + 20m = 07:11Z)
        RawMetarReport(
            station_id="KORD",
            obs_ts_utc=_dt("2026-01-15T18:00:00Z"),
            dispatch_ts_utc=_dt("2026-01-16T06:55:00Z"),
            report_type="METAR",
            is_cor=True,
            raw_text="METAR COR KORD 151800Z 25/10 RMK T02500100",
            source_channel="PAPER_REPLAY",
            sequence_hint=2,
        ),
        # Late post-lock COR at 07:20Z (> 07:11Z): MUST be ignored once lock activates
        RawMetarReport(
            station_id="KORD",
            obs_ts_utc=_dt("2026-01-15T18:00:00Z"),
            dispatch_ts_utc=_dt("2026-01-16T07:20:00Z"),
            report_type="METAR",
            is_cor=True,
            raw_text="METAR COR KORD 151800Z 30/10 RMK T03000100",
            source_channel="PAPER_REPLAY",
            sequence_hint=3,
        ),
        # Next-day routine METAR with missing dispatch_ts_utc -> bounded lock at 06:51 + 20m = 07:11Z
        RawMetarReport(
            station_id="KORD",
            obs_ts_utc=_dt("2026-01-16T06:51:00Z"),
            dispatch_ts_utc=None,
            report_type="METAR",
            is_cor=False,
            raw_text="METAR KORD 160651Z 10/05 RMK T01000050",
            source_channel="HISTORICAL_SHADOW",
            sequence_hint=4,
        ),
    ]
    engine = SettlementMetarStreamEngine(
        source=PaperReplayMetarAdapter(reports),
        freshness_policy=FreshnessPolicy(
            physical_age_limit_sec=100000.0,
            provenance="TEST_POST_CLOSE_LOCK",
        ),
        missing_dispatch_policy=MissingDispatchPolicy(
            mode="CONSERVATIVE_LAG_BOUND",
            conservative_lag_bound_sec=1200.0,
            provenance="TEST_LAG_BOUND_1200S",
        ),
    )

    ev_before_lock = engine.evaluate_as_of(
        station_id="KORD",
        target_date=date(2026, 1, 15),
        as_of_ts_utc=_dt("2026-01-16T07:05:00Z"),
        session_id="sess-lock-mono",
        execution_mode="PAPER",
        model_hash="m",
        config_hash="c",
    )
    assert ev_before_lock.state.m_now_int_f == 77  # 25.0°C = 77°F

    # After 07:11Z lock activates: 06:55Z COR MUST NOT be retroactively revoked (stays 77°F),
    # while 07:20Z COR MUST be rejected.
    ev_after_lock = engine.evaluate_as_of(
        station_id="KORD",
        target_date=date(2026, 1, 15),
        as_of_ts_utc=_dt("2026-01-16T07:25:00Z"),
        session_id="sess-lock-mono",
        execution_mode="PAPER",
        model_hash="m",
        config_hash="c",
    )
    assert ev_after_lock.state.m_now_int_f == 77
    assert "POST_LOCK_COR_IGNORED" in ev_after_lock.state.gap_flags


def test_live_awc_adapter_naive_utc_timestamps_and_historical_date_param(tmp_path: Path) -> None:
    """Patch 2: AWC adapter parses naive UTC API strings and supplies `date=` for past windows."""
    captured_params: Dict[str, object] = {}

    def fake_get(url: str, params: Dict[str, object], timeout: float) -> object:
        captured_params.clear()
        captured_params.update(params)
        return [
            {
                "icaoId": "KORD",
                "reportTime": "2026-07-10 14:51:00",
                "receiptTime": "2026-07-10 14:54:00",
                "metarType": "METAR",
                "rawOb": "METAR KORD 101451Z 27008KT 10SM CLR 25/15 A3000 RMK AO2 T02500150",
            }
        ]

    adapter = LiveAwcMetarAdapter(
        http_get=fake_get,
        clock_utc=lambda: _dt("2026-07-15T16:00:00Z"),
    )
    past_start = _dt("2026-07-10T05:00:00Z")
    past_end = _dt("2026-07-11T05:00:00Z")
    out = adapter.fetch_window("KORD", past_start, past_end)
    assert len(out) == 1
    assert out[0].obs_ts_utc == _dt("2026-07-10T14:51:00Z")
    assert out[0].dispatch_ts_utc == _dt("2026-07-10T14:54:00Z")
    assert captured_params["date"] == "2026-07-11T05:00:00Z"
    assert captured_params["hours"] == 25

    # Core replay adapter still strictly rejects naive ISO strings
    bad_jsonl = tmp_path / "naive.jsonl"
    bad_jsonl.write_text(
        json.dumps(
            {
                "station_id": "KORD",
                "obs_ts_utc": "2026-07-10 14:51:00",
                "dispatch_ts_utc": "2026-07-10 14:54:00",
                "raw_text": "METAR KORD 101451Z 25/15",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CausalInputError):
        PaperReplayMetarAdapter.from_jsonl(bad_jsonl)


def test_wmo_equals_terminated_tgroup_and_body_temp_parsing() -> None:
    """Patch 3: WMO `=` terminator attached without whitespace must not hide T-group or TT/TD."""
    tc_t, tier_t = SettlementIsomorphicParser.parse_temperature_c(
        "METAR KORD 181451Z 27010KT 10SM CLR 20/15 A3001 RMK AO2 SLP162 T02030150="
    )
    assert tc_t == Decimal("20.3")
    assert tier_t == "AWC_METAR_TGROUP"

    tc_b, tier_b = SettlementIsomorphicParser.parse_temperature_c(
        "METAR KORD 181451Z 27010KT 10SM CLR M05/M10="
    )
    assert tc_b == Decimal("-5")
    assert tier_b == "AWC_METAR_BODY"
