#!/usr/bin/env python3
"""Read-only M7 + P18 Batch Replay & Gap Guard Check over Real Recorded Sessions.

Strict Boundaries:
- Strictly read-only access to `data/market_recordings/` (`open(..., "r")`).
- Writes temporary audit logs inside `tempfile.TemporaryDirectory()` only; zero mutation of
  live recorder paths or running PIDs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.audit import (
    P10Query,
    P18ReplayFrameRetriever,
    ReplayScanStep,
    load_p13_session_readonly,
    probe_p18_gap_frame_abort,
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
from src.execution.executor import PhiPolicy, TradingExecutionConfig
from src.prediction.discrete_bin_engine import BinProbV11
from src.prediction.forecast_distribution_engine import ForecastDistributionSnapshotV11

REC_ROOT = PROJECT_ROOT / "data" / "market_recordings" / "PASSIVE_RECORD" / "2026-11-21"


class _ReplayQuotaProvider:
    def query_quota(self, q: QuotaQuery) -> QuotaSnapshot:
        return QuotaSnapshot(
            station_id=q.station_id, market_id=q.market_id, free_usd=500.0,
            station_active_locked_usd=0.0, market_held_usd=0.0, station_cap_usd=500.0,
            station_realized_loss_usd=0.0, station_loss_gate_tripped=False,
            account_drawdown_brake_tripped=False, b_eff_headroom_usd=500.0, blocked_reason=None,
        )


def _replay_exec_config() -> TradingExecutionConfig:
    return TradingExecutionConfig(
        min_order_size_shares=Decimal("5.0"), min_order_size_shares_provenance="FACT-004",
        min_notional_usd=Decimal("1.0"), min_notional_usd_provenance="FACT-004_PLACEHOLDER",
        forecast_age_limit_sec=86400.0, forecast_age_limit_sec_provenance="M7_REPLAY_SMOKE",
        max_book_staleness_sec=3600.0, max_book_staleness_sec_provenance="M7_REPLAY_SMOKE",
        pair_max_skew_sec=120.0, pair_max_skew_sec_provenance="M7_REPLAY_SMOKE",
        latency_ms=150, latency_ms_provenance="P8-T8-ALGO4-DESIGN v0.3 §4.2",
        heartbeat_timeout_sec=25.0, heartbeat_timeout_sec_provenance="configs/passive_book_recorder.example.yaml",
        rest_fallback_interval_sec=5.0, rest_fallback_interval_sec_provenance="configs/passive_book_recorder.example.yaml",
        enable_cross_side_split_routing=False, cross_side_split_routing_provenance="M7_REPLAY_SMOKE",
    )


def _replay_policy_bundle(signed_at: datetime) -> ExecutionPolicyBundle:
    return build_execution_policy_bundle(
        policy_version="m7-replay-smoke-v1", signed_at_utc=signed_at, is_overdue=False,
        w0_intent=0.20, min_order_usd_eff=2.5, p=1.5, tau_max_h=48.0,
        station_cap_usd=500.0, concurrent_days=2, w_provenance="M7_REPLAY_SMOKE",
        phi_policy=PhiPolicy(rho_0=0.5, k_slope=0.0, rho_min=0.1, rho_max=0.8, provenance="M7_REPLAY_SMOKE"),
        k0_threshold_coef=2.0,
        sigma_delta_frozen=SigmaDeltaFrozen(value=0.01, provenance="M7_REPLAY_SMOKE", freeze_cycle_id="c-smoke"),
        friction_median=0.005, m_floor=0.02, yellow_multiplier=0.5,
    )


def _build_replay_inputs_for_session(retriever: P18ReplayFrameRetriever) -> tuple[list[ForecastDistributionSnapshotV11], list[ReplayScanStep]]:
    forecasts: List[ForecastDistributionSnapshotV11] = []
    steps: List[ReplayScanStep] = []
    by_market_latest: Dict[tuple[str, str, str, str], Any] = {}
    for env in retriever.envelopes:
        if not env.gap_detected and env.payload.outcome == "YES":
            key = (env.station_id, env.target_date, env.bin_label, env.payload.market_id)
            by_market_latest[key] = env
    for (st, td, bin_lbl, mkt_id), env in list(sorted(by_market_latest.items()))[:6]:
        if env.payload.recv_ts_utc == retriever.envelopes[-1].payload.recv_ts_utc:
            continue
        bin_id = f"bin-{mkt_id[:8]}"
        t_scan = env.payload.recv_ts_utc + timedelta(milliseconds=5)
        fc = ForecastDistributionSnapshotV11(
            schema_version="p5.v1.1", forecast_id=f"fc-{st}-{td}-{mkt_id[:8]}",
            issue_ts_utc=t_scan - timedelta(minutes=5), station_id=st,
            target_date=datetime.fromisoformat(td).date(), target_type="TMAX", gefs_lead_hours=12,
            tau_hours=12.0, settle_close_utc=t_scan + timedelta(hours=12), model_hash="m7-smoke-v1",
            prior_mu0=60.0, prior_sigma0=2.5, family="gaussian", m_now_f=55.0, m_now_int_f=55,
            oracle_compliant=True, upstream_obs_fresh=True, is_bridge_active=True,
            p_stay_phys=0.05, p_bin_stay=0.05,
            bin_probs=(BinProbV11(bin_id, bin_lbl, 60, 61, 0.85), BinProbV11("other", "other", 62, None, 0.15)),
            sigma_delta_sample=0.02,
        )
        forecasts.append(fc)
        steps.append(
            ReplayScanStep(
                scan_ts_utc=t_scan, scan_clock="PRICE_CLOCK", station_id=st, target_date=td,
                bin_id=bin_id, bin_label=bin_lbl, market_id=mkt_id, yes_token_id=env.payload.token_id,
            )
        )
    return forecasts, steps


def _probe_gap_rows(retriever: P18ReplayFrameRetriever, cfg: TradingExecutionConfig) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for g in retriever.list_gap_frames():
        attempt = probe_p18_gap_frame_abort(retriever, g, config=cfg)
        rows.append(
            {
                "station_id": g.station_id,
                "bin_label": g.bin_label,
                "outcome": g.payload.outcome,
                "seq_id": g.seq_id,
                "gap_reason": g.gap_reason,
                "p18_terminal_status": attempt.terminal_status,
                "p18_reject_reason": attempt.reject_or_abort_reason,
            }
        )
    return rows


def _inspect_session(sdir: Path) -> Dict[str, Any]:
    loaded = load_p13_session_readonly(sdir)
    retriever = P18ReplayFrameRetriever(loaded.envelopes)
    cfg = _replay_exec_config()
    gap_rows = _probe_gap_rows(retriever, cfg)
    forecasts, steps = _build_replay_inputs_for_session(retriever)
    t_sign = loaded.envelopes[0].payload.recv_ts_utc - timedelta(hours=1)
    bundle = _replay_policy_bundle(t_sign)
    slot = P16SubscriptionSlot()
    light = LightLevelEvent("p16-smoke-green", "GREEN", "REPLAY_BASELINE", t_sign, None)
    slot.publish(light)

    with tempfile.TemporaryDirectory() as tmpd:
        out_root = Path(tmpd)
        replay_res = run_p13_batch_replay(
            p13_session_dir=sdir, audit_output_root=out_root, orig_session_id=sdir.name,
            exec_config=cfg, policy_bundle=bundle, forecasts=forecasts, scan_steps=steps,
            quota_provider=_ReplayQuotaProvider(), light_event=light, p16_slot=slot,
        )
        p10_view = query_p10_session_view(out_root, P10Query(execution_mode="PAPER"))

    return {
        "session_id": sdir.name, "files_scanned": loaded.summary.files_scanned,
        "valid_frames": loaded.summary.valid_frames, "corrupt_lines": len(loaded.summary.corrupt_lines),
        "partial_tail_skipped": loaded.summary.partial_tail_skipped_lines,
        "gap_frames_total": len(gap_rows),
        "gap_aborts_triggered": sum(1 for r in gap_rows if r["p18_terminal_status"] == "PAPER_MATCH_ABORTED_GAP"),
        "gap_samples": gap_rows[:10] if len(gap_rows) > 10 else gap_rows,
        "batch_replay": {
            "scans_executed": replay_res.scans_executed, "ordered_count": replay_res.ordered_count,
            "p1_logged": replay_res.p1_logged, "p3_logged": replay_res.p3_logged,
            "p17_logged": replay_res.p17_logged, "p19_logged": replay_res.p19_logged,
            "p10_render_status": p10_view.render_status, "p10_corrupt_lines": len(p10_view.corrupt_lines),
        },
    }


def main() -> int:
    sessions = sorted(p for p in REC_ROOT.iterdir() if p.is_dir())
    report = {
        "work_order_id": "P8-WO-20261122-M7-KICKOFF",
        "sessions": [_inspect_session(s) for s in sessions],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
