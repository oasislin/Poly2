"""Unit tests for M7 Audit Logging, P10 Read-Only Queries, P18 Frame Retrieval, and P8 Aggregation."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.run_s303_shadow_smoke import evaluate_sealed_2019_corpus
from src.audit import (
    AsyncAuditLogger,
    P10Query,
    P18ReplayFrameRetriever,
    aggregate_p8_calibration_batch,
    build_capital_event_log,
    load_p13_session_readonly,
    probe_p18_gap_frame_abort,
    query_p10_session_view,
)
from src.data_acquisition.settlement_metar_stream import (
    FreshnessPolicy,
    MissingDispatchPolicy,
    PaperReplayMetarAdapter,
    RawMetarReport,
    SettlementMetarStreamEngine,
)
from src.decision.engine import (
    DeterministicDecider,
    ExecutionPolicyBundle,
    LightLevelEvent,
    P16SubscriptionSlot,
    QuotaSnapshot,
    SigmaDeltaFrozen,
    build_execution_policy_bundle,
)
from src.execution.executor import PhiPolicy
from src.execution.stub_generator import (
    build_p4_v11_stub_envelope,
    default_stub_trading_config,
    generate_regression_stub_bundle,
)
from src.prediction.dynamic_corrector import SpecV2BaselineMuRHook
from src.prediction.forecast_distribution_engine import (
    ConstantEtaProvider,
    ForecastDistributionEngine,
    PriorAffineFamilyModel,
    build_integer_bin_ladder,
)
from src.utils.causal_utils import verify_record_sha256_line


def _make_sample_m1_eval():
    obs_ts = datetime(2026, 7, 15, 13, 0, tzinfo=timezone.utc)
    issue_ts = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)
    adapter = PaperReplayMetarAdapter(
        [
            RawMetarReport(
                station_id="KORD",
                obs_ts_utc=obs_ts,
                dispatch_ts_utc=obs_ts + timedelta(minutes=2),
                report_type="METAR",
                is_cor=False,
                raw_text="METAR KORD 151300Z 00000KT 10SM CLR 25/15 A3000 RMK T02500150",
                source_channel="AWC_METAR",
            )
        ]
    )
    m1 = SettlementMetarStreamEngine(
        source=adapter,
        freshness_policy=FreshnessPolicy(physical_age_limit_sec=7200.0, provenance="test"),
        missing_dispatch_policy=MissingDispatchPolicy(mode="REJECT", provenance="test"),
    )
    return m1.evaluate_as_of(
        station_id="KORD", target_date=date(2026, 7, 15), as_of_ts_utc=issue_ts,
        session_id="sess-m7", execution_mode="PAPER", model_hash="mhash_v1",
        config_hash="cfghash_v1", gfs_available=True, gfs_completeness_ratio=1.0,
    )


def _make_sample_p5_and_p12():
    ev = _make_sample_m1_eval()
    issue_ts = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)
    m2 = ForecastDistributionEngine(
        freshness_policy=FreshnessPolicy(physical_age_limit_sec=7200.0, provenance="test"),
        eta_provider=ConstantEtaProvider(eta_s=0.25, provenance="test"),
        mu_r_hook=SpecV2BaselineMuRHook(),
    )
    bins = build_integer_bin_ladder(first_interior_start_f=74, num_interior_bins=5, bin_width_f=2)
    snap, _ = m2.build_snapshot(
        station_id="KORD", target_date=date(2026, 7, 15), target_type="TMAX",
        issue_ts_utc=issue_ts, settle_close_utc=datetime(2026, 7, 16, 5, 0, tzinfo=timezone.utc),
        gefs_lead_hours=24, model_hash="mhash_v1",
        prior=PriorAffineFamilyModel(mu0=80.0, sigma0=3.5, family="gaussian"),
        bins=bins, p11_state=ev.state, sigma_delta_sample=0.42,
    )
    return ev.coverage_ledger, snap


def _make_bundle(*, is_overdue: bool = False) -> ExecutionPolicyBundle:
    return build_execution_policy_bundle(
        policy_version="pol-v1", signed_at_utc=datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc),
        is_overdue=is_overdue, w0_intent=0.20, min_order_usd_eff=2.5, p=1.5, tau_max_h=48.0,
        station_cap_usd=500.0, concurrent_days=2, w_provenance="test",
        phi_policy=PhiPolicy(rho_0=0.5, k_slope=0.0, rho_min=0.1, rho_max=0.8, provenance="test"),
        k0_threshold_coef=2.0,
        sigma_delta_frozen=SigmaDeltaFrozen(value=0.01, provenance="test", freeze_cycle_id="c1"),
        friction_median=0.005, m_floor=0.02, yellow_multiplier=0.5,
    )


def test_async_audit_logger_partitions_verifies_sha256_and_enforces_mode_isolation(tmp_path: Path) -> None:
    p12, snap = _make_sample_p5_and_p12()
    bundle = _make_bundle()
    ts = datetime(2026, 7, 15, 14, 1, tzinfo=timezone.utc)
    p19 = build_capital_event_log(
        event_ts_utc=ts, session_id="sess-m7", execution_mode="PAPER", station_id="KORD",
        event_type="LIGHT_LEVEL_APPLIED", free_usd_after=500.0, active_locked_usd_after=0.0,
        policy_version=bundle.policy_version, config_hash=bundle.config_hash,
        is_overdue=False, light_status="GREEN", reason="MONTHLY_GREEN",
    )
    with AsyncAuditLogger(tmp_path, execution_mode="PAPER") as logger:
        logger.log_p12_coverage_ledger(p12)
        logger.log_p17_forecast_snapshot(snap, session_id="sess-m7", config_hash=bundle.config_hash)
        logger.log_p19_capital_event(p19)
        live_p19 = build_capital_event_log(
            event_ts_utc=ts, session_id="sess-live", execution_mode="LIVE", station_id="KORD",
            event_type="GATE_LIVE_SWITCH", free_usd_after=500.0, active_locked_usd_after=0.0,
            policy_version=bundle.policy_version, config_hash=bundle.config_hash,
            is_overdue=False, reason="SWITCH",
        )
        with pytest.raises(ValueError, match="Mode isolation breach"):
            logger.log_p19_capital_event(live_p19)
        logger.flush()
        st = logger.stats()
    assert st.error_count == 0 and st.written_by_stream["p19"] == 1
    for fname in ("p12_weather_coverage.jsonl", "p17_forecast_snapshots.jsonl", "p19_capital_events.jsonl"):
        lines = (tmp_path / "PAPER" / "2026-07-15" / fname).read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1 and verify_record_sha256_line(lines[0])


def test_p10_reader_degradation_filter_empty_tail_and_corrupt_quarantine(tmp_path: Path) -> None:
    empty_view = query_p10_session_view(tmp_path, P10Query(execution_mode="PAPER"))
    assert empty_view.render_status == "NO_AUDIT_RECORDS"
    assert empty_view.tail_status == "NONE"

    p12, snap = _make_sample_p5_and_p12()
    bundle = _make_bundle()
    with AsyncAuditLogger(tmp_path, execution_mode="PAPER") as logger:
        logger.log_p17_forecast_snapshot(snap, session_id="sess-m7", config_hash=bundle.config_hash)
        logger.log_p12_coverage_ledger(p12)

    p12_path = tmp_path / "PAPER" / "2026-07-15" / "p12_weather_coverage.jsonl"
    tampered = json.loads(p12_path.read_text(encoding="utf-8").splitlines()[0])
    tampered["station_id"] = "KMIA"
    with p12_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(tampered) + "\n")
        fh.write('{"partial_unterminated": true')

    view = query_p10_session_view(tmp_path, P10Query(execution_mode="PAPER"))
    assert view.render_status == "DEGRADED_CORRUPT_LINES"
    assert view.tail_status == "CONCURRENT_TAIL_SKIPPED"
    assert view.settlement_status == "PENDING_P9"
    assert view.partial_tail_skipped_lines == 1
    assert len(view.corrupt_lines) == 1 and view.corrupt_lines[0].reason == "SHA256_MISMATCH"

    clean_audit = tmp_path / "clean"
    with AsyncAuditLogger(clean_audit, execution_mode="PAPER") as logger:
        logger.log_p12_coverage_ledger(p12)
    filtered_empty = query_p10_session_view(clean_audit, P10Query(execution_mode="PAPER", station_id="KMIA"))
    assert filtered_empty.render_status == "NO_AUDIT_RECORDS"


def test_p13_reader_handles_partial_tail_and_probes_gap_abort(tmp_path: Path) -> None:
    bundle = generate_regression_stub_bundle()
    t0 = bundle["base_ts"]
    gap_env, _ = build_p4_v11_stub_envelope(
        session_id=bundle["session_id"], seq_id=99, frame_seq=99, token_id="tok-kord-5859-yes",
        market_id="mkt-5859", condition_id="0xc5859", station_id="KORD", target_date="2026-11-21",
        bin_label="58-59°F", outcome="YES", regime="two_sided", recv_ts_utc=t0 + timedelta(seconds=1),
        asks=((0.40, 20.0),), bids=((0.35, 25.0),), gap_detected=True,
        gap_reason="WS_RECONNECT:ConnectionClosedError",
    )
    envelopes = list(bundle["envelopes"]) + [gap_env]
    sdir = tmp_path / "sess-stub"
    sdir.mkdir()
    with (sdir / "p13_book_stream_KORD.jsonl").open("w", encoding="utf-8") as fh:
        for env in envelopes:
            fh.write(env.to_json_line() + "\n")
        fh.write('{"schema_version":"p13.v1","incomplete_tail":1')

    loaded = load_p13_session_readonly(sdir)
    assert loaded.summary.corrupt_lines == () and loaded.summary.partial_tail_skipped_lines == 1
    assert loaded.summary.valid_frames == len(envelopes) and loaded.summary.gap_frames_count == 1

    retriever = P18ReplayFrameRetriever(loaded.envelopes)
    attempt = probe_p18_gap_frame_abort(
        retriever, retriever.list_gap_frames()[0], config=default_stub_trading_config()
    )
    assert attempt.terminal_status == "PAPER_MATCH_ABORTED_GAP"
    assert attempt.reject_or_abort_reason == "PAPER_MATCH_ABORTED_GAP:R2_HIT_GAP:WS_RECONNECT:ConnectionClosedError"


def test_p8_aggregator_reads_only_m7_logs_and_computes_overdue_ratio(tmp_path: Path) -> None:
    p12, snap = _make_sample_p5_and_p12()
    bundle = _make_bundle(is_overdue=True)
    stub = generate_regression_stub_bundle()
    ts = datetime(2026, 7, 15, 14, 5, tzinfo=timezone.utc)
    two_sided_yes = stub["envelopes"][0].payload
    fresh_yes = two_sided_yes.__class__(
        **{**two_sided_yes.__dict__, "snapshot_ts_utc": ts - timedelta(seconds=1), "recv_ts_utc": ts - timedelta(seconds=1)}
    )
    slot = P16SubscriptionSlot()
    slot.publish(LightLevelEvent("p16-1", "YELLOW", "MILD_DRIFT", ts, "KORD"))
    ev_p1 = DeterministicDecider(exec_config=default_stub_trading_config(), p16_slot=slot).evaluate_bin(
        orig_session_id="sess-m7", execution_mode="PAPER", scan_clock="PRICE_CLOCK", scan_ts_utc=ts,
        station_id="KORD", target_date="2026-07-15", bin_id=snap.bin_probs[3].bin_id,
        market_id=fresh_yes.market_id, yes_token_id=fresh_yes.token_id, forecasts=[snap],
        policy_bundle=bundle,
        quota=QuotaSnapshot("KORD", fresh_yes.market_id, 500.0, 0.0, 500.0, 500.0, 0.0, False, False, 0.0, "CAP_FULL"),
        yes_frame=fresh_yes,
    )
    with AsyncAuditLogger(tmp_path, execution_mode="PAPER") as logger:
        logger.log_p12_coverage_ledger(p12)
        logger.log_p17_forecast_snapshot(snap, session_id="sess-m7", config_hash=bundle.config_hash)
        logger.log_p1_scan_decision(ev_p1)

    batch = aggregate_p8_calibration_batch(
        tmp_path, execution_mode="PAPER",
        window_start_utc=datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc),
        window_end_utc=datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc),
    )
    assert batch.n_forecast_samples == 1 and batch.sigma_delta_quantiles["p50"] == pytest.approx(0.42)
    assert batch.policy_overdue_ratio == pytest.approx(1.0) and batch.n_slippage_fills == 0


def test_s303_sealed_corpus_evaluator_runs_m2_bridge_without_reading_2019_disk() -> None:
    d0, d_empty = date(2019, 7, 15), date(2019, 12, 31)
    prior_dfs = {
        "KORD": pd.DataFrame([
            {"target_date": d0, "season": "summer", "mu_0": 80.0, "sigma_0": 3.5},
            {"target_date": d_empty, "season": "winter", "mu_0": 32.0, "sigma_0": 3.5},
        ])
    }
    obs_summaries = {
        ("KORD", 12.0): pd.DataFrame({"mt": [74.0]}, index=[d0]),
        ("KORD", 16.0): pd.DataFrame({"mt": [79.0]}, index=[d0]),
    }
    eta_p = ConstantEtaProvider(eta_s=0.25, provenance="synthetic_sealed_test")
    engine = ForecastDistributionEngine(
        freshness_policy=FreshnessPolicy(physical_age_limit_sec=86400.0, provenance="test"),
        eta_provider=eta_p, mu_r_hook=SpecV2BaselineMuRHook(),
    )
    res = evaluate_sealed_2019_corpus(
        prior_dfs=prior_dfs, obs_summaries=obs_summaries, t_grid=(12.0, 16.0),
        engine=engine, eta_provider=eta_p,
        climate_calib={
            "KORD": {
                "seasons": {
                    "summer": {"selected_family": "gaussian", "shape_params": {}},
                    "winter": {"selected_family": "gaussian", "shape_params": {}},
                }
            }
        },
    )
    assert res["n_evaluable_day_leads"] == 1 and res["n_empty_day_leads"] == 1
    assert res["empty_day_by_station"] == {"KORD": 1} and res["empty_day_by_month"] == {"M12": 1}
    assert res["n_bridge_evals"] == 2
    assert res["p5_invariants_pass_rate"] == 1.0 and res["monotone_m_now_rate"] == 1.0
    assert res["sigma_rem_le_sigma0_rate"] == 1.0 and res["dead_bin_zero_rate"] == 1.0
    assert res["sealed_morphology_passed"] is True
