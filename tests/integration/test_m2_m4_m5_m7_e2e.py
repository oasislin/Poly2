"""End-to-End Integration Test: M2 (P5 v1.1) -> M4 -> M5 (P18) -> M7 (P1/P3/P12/P17/P19 + P8 + P10)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict

import pytest

from src.audit import (
    P10Query,
    ReplayScanStep,
    aggregate_p8_calibration_batch,
    query_p10_session_view,
    run_p13_batch_replay,
)
from src.decision.engine import (
    ExecutionPolicyBundle,
    LightLevelEvent,
    P16SubscriptionSlot,
    QuotaQuery,
    QuotaSnapshot,
    SigmaDeltaFrozen,
    build_execution_policy_bundle,
)
from src.execution.executor import PhiPolicy
from src.execution.stub_generator import (
    build_p4_v11_stub_envelope,
    build_stub_forecast_v11,
    default_stub_trading_config,
    generate_regression_stub_bundle,
)
from src.prediction.discrete_bin_engine import BinProbV11

_P1_REQUIRED_KEYS = {
    "schema_version", "decision_id", "session_id", "execution_mode", "scan_clock",
    "scan_ts_utc", "station_id", "target_date", "target_type", "bin_id", "token_id",
    "market_id", "model_hash", "config_hash", "policy_version", "policy_overdue",
    "forecast_id", "book_frame_ref", "best_ask_price", "best_ask_edge", "m_threshold",
    "tau_hours", "b_budget_usd", "w_tau", "s_edge", "g_cap_usd", "held_usd", "headroom_d",
    "decision_outcome", "target_slice_usd", "scaler_policy_id", "scaler_provisional",
    "scaler_provenance", "light_status", "p16_event_id", "degradation_reason", "record_sha256",
}

_P3_REQUIRED_KEYS = {
    "schema_version", "attempt_id", "decision_id", "idempotency_key", "session_id",
    "execution_mode", "capture_replay_mode", "replay_source_seq_id", "latency_injected_ms",
    "station_id", "market_id", "token_id", "model_hash", "config_hash", "decision_ts_utc",
    "decision_best_ask", "decision_est_vwap", "decision_qual_depth_shares", "order_type",
    "limit_price", "target_shares", "target_usd", "submit_ts_utc", "final_ts_utc",
    "terminal_status", "reject_or_abort_reason", "filled_shares", "filled_usd",
    "actual_avg_fill_price", "fee_paid_usd", "fill_rate", "slippage_vs_best_ask",
    "slippage_vs_est_vwap", "execution_legs", "record_sha256",
}


class _StatefulQuotaProvider:
    def __init__(self, initial_held: Dict[str, float]) -> None:
        self._held = dict(initial_held)

    def query_quota(self, query: QuotaQuery) -> QuotaSnapshot:
        held = self._held.get(query.market_id, 0.0)
        headroom = max(0.0, 500.0 - sum(self._held.values()))
        blocked = "STATION_HEADROOM_EXHAUSTED" if headroom <= 0.0 else None
        return QuotaSnapshot(
            station_id=query.station_id, market_id=query.market_id, free_usd=headroom,
            station_active_locked_usd=sum(self._held.values()), market_held_usd=held,
            station_cap_usd=500.0, station_realized_loss_usd=0.0,
            station_loss_gate_tripped=False, account_drawdown_brake_tripped=False,
            b_eff_headroom_usd=headroom, blocked_reason=blocked,
        )

    def credit_fill(self, market_id: str, usd: float) -> None:
        self._held[market_id] = self._held.get(market_id, 0.0) + usd


def _make_e2e_bundle(t_base: datetime) -> ExecutionPolicyBundle:
    return build_execution_policy_bundle(
        policy_version="e2e-pol-v1", signed_at_utc=t_base - timedelta(hours=1), is_overdue=False,
        w0_intent=0.25, min_order_usd_eff=2.5, p=1.5, tau_max_h=48.0, station_cap_usd=500.0,
        concurrent_days=2, w_provenance="e2e",
        phi_policy=PhiPolicy(rho_0=0.5, k_slope=0.0, rho_min=0.2, rho_max=0.8, provenance="e2e"),
        k0_threshold_coef=2.0,
        sigma_delta_frozen=SigmaDeltaFrozen(value=0.01, provenance="e2e", freeze_cycle_id="c-e2e"),
        friction_median=0.005, m_floor=0.02, yellow_multiplier=0.5,
    )


def _write_e2e_stub_p13(p13_dir: Path, t0: datetime, session_id: str, stub_envs) -> None:
    p13_dir.mkdir(parents=True, exist_ok=True)
    extra_rescue_yes, _ = build_p4_v11_stub_envelope(
        session_id=session_id, seq_id=11, frame_seq=11, token_id="tok-kord-rescue-yes",
        market_id="mkt-rescue", condition_id="0xcres", station_id="KORD", target_date="2026-11-21",
        bin_label="56-57°F", outcome="YES", regime="bid_only", recv_ts_utc=t0 + timedelta(seconds=1),
        asks=(), bids=((0.20, 40.0),),
    )
    extra_rescue_no, _ = build_p4_v11_stub_envelope(
        session_id=session_id, seq_id=12, frame_seq=12, token_id="tok-kord-rescue-no",
        market_id="mkt-rescue", condition_id="0xcres", station_id="KORD", target_date="2026-11-21",
        bin_label="56-57°F", outcome="NO", regime="two_sided", recv_ts_utc=t0 + timedelta(seconds=1),
        asks=((0.72, 20.0),), bids=((0.68, 100.0),),
    )
    with (p13_dir / "p13_book_stream_KORD.jsonl").open("w", encoding="utf-8") as fh:
        for env in list(stub_envs) + [extra_rescue_yes, extra_rescue_no]:
            fh.write(env.to_json_line() + "\n")


def _assert_p10_and_p8_results(audit_root: Path, p13_dir: Path, t0: datetime) -> None:
    view = query_p10_session_view(audit_root, P10Query(execution_mode="PAPER"), p13_root=p13_dir)
    assert view.render_status == "OK" and view.corrupt_lines == () and view.missing_forecast_fk_count == 0
    for rec_p1 in view.p1_events:
        assert _P1_REQUIRED_KEYS.issubset(rec_p1.keys())
        assert rec_p1["light_status"] == "YELLOW" and rec_p1["p16_event_id"] == "p16-yellow-e2e"
    assert any(ch.p13_record is not None for ch in view.joined_chains)
    outcomes = {r["bin_id"]: r["decision_outcome"] for r in view.p1_events}
    assert outcomes == {"bin-56-57": "ORDERED", "bin-60p": "BLOCKED_NO_BOOK_DEPTH"}

    p3 = view.p3_events[0]
    assert _P3_REQUIRED_KEYS.issubset(p3.keys()) and p3["terminal_status"] == "FILLED"
    assert p3["submit_ts_utc"] == (t0 + timedelta(milliseconds=75)).isoformat()
    assert p3["execution_legs"][0]["leg_source"] == "NO_BID_SPLIT_SELL"
    assert Decimal(p3["execution_legs"][0]["implied_yes_price"]) == Decimal("0.32")

    p19_types = [e["event_type"] for e in view.p19_events]
    assert p19_types == ["LIGHT_LEVEL_APPLIED", "FREEZE", "FILL_SETTLE_CONVERSION"]
    assert view.p19_events[1]["active_locked_usd_after"] > 0.0

    p8_batch = aggregate_p8_calibration_batch(
        audit_root, execution_mode="PAPER",
        window_start_utc=t0 - timedelta(days=1), window_end_utc=t0 + timedelta(days=1),
    )
    assert p8_batch.n_forecast_samples == 1 and p8_batch.n_slippage_fills == 1
    assert p8_batch.empirical_slippage_vs_best_ask_median == pytest.approx(0.0)


def _make_e2e_forecast(t0: datetime):
    return build_stub_forecast_v11(
        station_id="KORD", target_date_str="2026-11-21", issue_ts_utc=t0 - timedelta(minutes=10),
        settle_close_utc=datetime(2026, 11, 22, 6, 0, tzinfo=timezone.utc),
        bin_probs=(
            BinProbV11("bin-56-57", "56-57°F", 56, 57, 0.55),
            BinProbV11("bin-58-59", "58-59°F", 58, 59, 0.35),
            BinProbV11("bin-60p", "60°F or above", 60, None, 0.10),
        ),
    )


def test_m2_m4_m5_m7_full_e2e_flow_protocols_quota_and_light_passthrough(tmp_path: Path) -> None:
    stub = generate_regression_stub_bundle(datetime(2026, 11, 21, 14, 0, 0, tzinfo=timezone.utc))
    t0 = stub["base_ts"]
    p13_dir = tmp_path / "p13_src"
    _write_e2e_stub_p13(p13_dir, t0, stub["session_id"], stub["envelopes"])
    forecast, bundle = _make_e2e_forecast(t0), _make_e2e_bundle(t0)
    p16_slot = P16SubscriptionSlot()
    light_ev = LightLevelEvent("p16-yellow-e2e", "YELLOW", "E2E_YELLOW_DRIFT", t0 - timedelta(minutes=1), "KORD")
    p16_slot.publish(light_ev)
    quota_provider = _StatefulQuotaProvider({"mkt-exhausted": 495.0})
    audit_root = tmp_path / "audit_logs"
    steps = [
        ReplayScanStep(
            scan_ts_utc=t0 + timedelta(milliseconds=50), scan_clock="PRICE_CLOCK", station_id="KORD",
            target_date="2026-11-21", bin_id="bin-56-57", bin_label="56-57°F", market_id="mkt-rescue",
            yes_token_id="tok-kord-rescue-yes", no_token_id="tok-kord-rescue-no",
            include_no_side=True, submit_delay_ms=25,
        ),
        ReplayScanStep(
            scan_ts_utc=t0 + timedelta(milliseconds=60), scan_clock="PRICE_CLOCK", station_id="KORD",
            target_date="2026-11-21", bin_id="bin-60p", bin_label="60°F or above", market_id="mkt-60p",
            yes_token_id="tok-kord-60p-yes", no_token_id="tok-kord-60p-no", include_no_side=False,
        ),
    ]
    summary = run_p13_batch_replay(
        p13_session_dir=p13_dir, audit_output_root=audit_root, orig_session_id=stub["session_id"],
        exec_config=default_stub_trading_config(), policy_bundle=bundle, forecasts=[forecast],
        scan_steps=steps, quota_provider=quota_provider, light_event=light_ev, p16_slot=p16_slot,
    )
    assert summary.scans_executed == 2 and summary.ordered_count == 1 and summary.p19_logged == 3
    _assert_p10_and_p8_results(audit_root, p13_dir, t0)

    quota_provider.credit_fill("mkt-exhausted", 10.0)
    exhaust_audit = tmp_path / "audit_exhaust"
    run_p13_batch_replay(
        p13_session_dir=p13_dir, audit_output_root=exhaust_audit, orig_session_id=stub["session_id"],
        exec_config=default_stub_trading_config(), policy_bundle=bundle, forecasts=[forecast],
        scan_steps=[steps[0]], quota_provider=quota_provider, light_event=light_ev, p16_slot=p16_slot,
    )
    ex_view = query_p10_session_view(exhaust_audit, P10Query(execution_mode="PAPER"))
    assert ex_view.p1_events[0]["decision_outcome"] == "IDLE_BUDGET_EXHAUSTED"
    assert ex_view.p1_events[0]["headroom_d"] == 0.0
