"""Regression tests for restarting `S3-11` scheduler with `M6/P19` balance & `open_claims` recovery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

from src.bankroll.manager import BankrollAccountManager
from src.bankroll.models import BankrollConfig, FreezeRequest
from src.bankroll.recovery import recover_bankroll_and_claims_from_audit
from src.calibration.policy_ledger import PolicyParameterLedger, issue_policy_bundle
from src.data_acquisition.settlement_metar_stream import RawMetarReport
from src.decision.engine import PhiPolicy, SigmaDeltaFrozen
from src.decision.offline_scheduler import OfflineScheduleTarget, OfflineSchedulerConfig, run_s311_offline_schedule
from src.execution.stub_generator import build_p4_v11_stub_envelope, default_stub_trading_config
from src.prediction.discrete_bin_engine import BinProbV11
from src.prediction.forecast_distribution_engine import ForecastDistributionSnapshotV11


def _sample_policy(t0: datetime):
    ledger = PolicyParameterLedger.create_initial_placeholder(
        policy_version="p6-restart-test",
        created_ts_utc=t0 - timedelta(hours=2),
        sigma_delta_frozen=SigmaDeltaFrozen(0.02, "test", "cyc"),
        phi_policy=PhiPolicy(Decimal("0.30"), Decimal("0.0"), Decimal("0.10"), Decimal("0.50")),
        friction_median=0.01,
    )
    return issue_policy_bundle(ledger)


def test_restart_recovers_bankroll_balance_open_claims_and_settles_next_day(tmp_path: Path) -> None:
    t_dec = datetime(2026, 11, 25, 18, 0, 0, tzinfo=timezone.utc)
    settle_close = datetime(2026, 11, 26, 6, 0, 0, tzinfo=timezone.utc)
    p13_dir = tmp_path / "p13_restart"
    p13_dir.mkdir(parents=True)
    e1, _ = build_p4_v11_stub_envelope(
        session_id="rec-restart", seq_id=1, frame_seq=1, token_id="tok-y",
        market_id="mkt-1", condition_id="c1", station_id="KORD", target_date="2026-11-25",
        bin_label="58-59°F", outcome="YES", regime="two_sided", recv_ts_utc=t_dec,
        asks=((0.25, 20.0), (0.28, 300.0)), bids=((0.22, 100.0),),
    )
    e2, _ = build_p4_v11_stub_envelope(
        session_id="rec-restart", seq_id=2, frame_seq=2, token_id="tok-y",
        market_id="mkt-1", condition_id="c1", station_id="KORD", target_date="2026-11-25",
        bin_label="58-59°F", outcome="YES", regime="two_sided", recv_ts_utc=t_dec + timedelta(milliseconds=160),
        asks=((0.26, 400.0),), bids=((0.22, 100.0),),
    )
    (p13_dir / "p13_book_stream_KORD.jsonl").write_text(e1.to_json_line() + "\n" + e2.to_json_line() + "\n", encoding="utf-8")

    fc = ForecastDistributionSnapshotV11(
        schema_version="p5.v1.1", forecast_id="fc-restart-1", issue_ts_utc=t_dec - timedelta(hours=1),
        station_id="KORD", target_date=t_dec.date(), target_type="TMAX", gefs_lead_hours=24,
        tau_hours=12.0, settle_close_utc=settle_close, model_hash="mh-restart", prior_mu0=58.5,
        prior_sigma0=2.0, family="gaussian", m_now_f=None, m_now_int_f=None, oracle_compliant=True,
        upstream_obs_fresh=True, is_bridge_active=False, p_stay_phys=None, p_bin_stay=None,
        bin_probs=(
            BinProbV11("le_57F", "57°F or below", None, 57, 0.15),
            BinProbV11("58-59F", "58-59°F", 58, 59, 0.70),
            BinProbV11("ge_60F", "60°F or higher", 60, None, 0.15),
        ),
        sigma_delta_sample=0.0,
    )
    target = OfflineScheduleTarget("KORD", "2026-11-25", "58-59F", "58-59°F", "mkt-1", "tok-y")
    policy = _sample_policy(t_dec)
    audit_dir = tmp_path / "audit_logs"

    # Run 1: execute fill BEFORE settlement (simulating mid-day fill before process restart).
    sink_ref1 = [None]
    mgr1 = BankrollAccountManager(
        BankrollConfig("s311-exec18", "PAPER", policy.policy_version, policy.config_hash),
        p19_sink=lambda ev: sink_ref1[0](ev) if sink_ref1[0] is not None else None,
    )
    cfg = OfflineSchedulerConfig(
        p13_session_dir=p13_dir, audit_output_root=audit_dir, orig_session_id="rec-restart",
        replay_delay_ms=0, enable_p18_matching=True, enable_m9_settlement=False,
    )
    s1 = run_s311_offline_schedule(
        cfg, exec_config=default_stub_trading_config(), policy_bundle=policy, forecasts=[fc],
        targets=[target], quota_provider=mgr1, clock_ticks=(t_dec,),
        p19_sink_setter=lambda fn: sink_ref1.__setitem__(0, fn),
    )
    assert s1.filled_count == 1
    expected_free_after_fill = mgr1._free_usd
    expected_held = mgr1.held_total_usd
    expected_fee = mgr1.fee_paid_total_usd
    assert expected_free_after_fill < Decimal("2000")
    p19_count_before_restart = len(next(audit_dir.rglob("p19_capital_events.jsonl")).read_text(encoding="utf-8").splitlines())

    # Simulate process restart: brand new BankrollAccountManager + read-only recovery from audit_dir.
    emitted_during_recovery = []
    sink_ref2 = [None]
    mgr2 = BankrollAccountManager(
        BankrollConfig("s311-exec18", "PAPER", policy.policy_version, policy.config_hash),
        p19_sink=lambda ev: emitted_during_recovery.append(ev) if sink_ref2[0] is None else sink_ref2[0](ev),
    )
    recovered = recover_bankroll_and_claims_from_audit(audit_dir, execution_mode="PAPER")
    mgr2.restore_from_audit_history(
        open_held_by_market=recovered.open_held_by_market,
        open_fee_by_market=recovered.open_fee_by_market,
        total_fee_paid_usd=recovered.total_fee_paid_usd,
        realized_pnl_by_station=recovered.realized_pnl_by_station,
        settled_attempt_ids=recovered.settled_attempt_ids,
        settled_p15_ids=recovered.settled_p15_ids,
        tier_pool_usd=recovered.tier_pool_usd,
        light_status=recovered.light_status,
    )
    assert emitted_during_recovery == []
    assert mgr2.conservation_residual_usd == Decimal("0")
    assert mgr2._free_usd == expected_free_after_fill
    assert mgr2.held_total_usd == expected_held
    assert mgr2.fee_paid_total_usd == expected_fee
    assert ("KORD", "2026-11-25", "TMAX") in recovered.open_claims
    assert "mkt-1" in recovered.open_claims[("KORD", "2026-11-25", "TMAX")]

    # A new FREEZE + UNFREEZE after restart must preserve pre-restart balance (NOT reset to 2000.0).
    p19_captured = []
    sink_ref2[0] = p19_captured.append
    rec = mgr2.freeze_for_order(FreezeRequest(
        decision_id="post-restart-dec", idempotency_key="p14-post-restart",
        station_id="KMIA", market_id="mkt-kmia", token_id="tok-kmia",
        target_freeze_usd=Decimal("5.0"), requested_ts_utc=t_dec + timedelta(minutes=5),
    ))
    assert rec.accepted is True
    assert Decimal(str(p19_captured[-1].free_usd_after)) == expected_free_after_fill - Decimal("5.0")
    mgr2.release_unfill(
        decision_id="post-restart-dec", attempt_id="att-post",
        ts_utc=t_dec + timedelta(minutes=6), reason="TEST_UNFREEZE",
    )
    assert Decimal(str(p19_captured[-1].free_usd_after)) == expected_free_after_fill
    assert len(next(audit_dir.rglob("p19_capital_events.jsonl")).read_text(encoding="utf-8").splitlines()) == p19_count_before_restart

    # Next-day M9 settlement on recovered claims & bankroll succeeds cleanly via settle_and_release_p15!
    class _StubMetarSource:
        def fetch_window(self, station_id: str, start_utc: datetime, end_utc: datetime):
            return (
                RawMetarReport("KORD", t_dec, t_dec, "METAR", False, "METAR KORD 251800Z 00000KT CLR 15/05 A3000 RMK AO2 T01480050", "AWC_LIVE", 1),
            )

    cfg_settle = OfflineSchedulerConfig(
        p13_session_dir=p13_dir, audit_output_root=audit_dir, orig_session_id="rec-restart",
        replay_delay_ms=0, enable_p18_matching=False, enable_m9_settlement=True,
    )
    s2 = run_s311_offline_schedule(
        cfg_settle, exec_config=default_stub_trading_config(), policy_bundle=policy, forecasts=[fc],
        targets=[], quota_provider=mgr2, clock_ticks=(settle_close + timedelta(minutes=5),),
        p17_forecast_ids_to_skip=recovered.seen_p17_ids, metar_source=_StubMetarSource(),
        settled_keys=recovered.settled_p9_keys, open_claims=recovered.open_claims,
        p19_sink_setter=lambda fn: sink_ref2.__setitem__(0, fn),
    )
    assert s2.p9_logged == 1
    assert mgr2.held_total_usd == Decimal("0")
    assert mgr2.realized_pnl_total_usd > Decimal("0")
    assert mgr2.conservation_residual_usd == Decimal("0")
    p9_obj = json.loads(next(audit_dir.rglob("p9_settlement_truths.jsonl")).read_text(encoding="utf-8").splitlines()[-1])
    assert p9_obj["winning_bin_id"] == "58-59F"
