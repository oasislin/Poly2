"""End-to-End `P13` Batch Replay Engine & `P18` Gap Probe (`M7 + M4 + M5/P18`).

Wires strictly read-only `P18ReplayFrameRetriever` (`M7`) -> `pair_dual_side_books` ->
`DeterministicDecider` (`M4`) -> `ReplayMatcher` (`M5 / P18`) -> `AsyncAuditLogger` (`M7`),
including `submit_delay_ms` propagation and cumulative `P19` `FREEZE`/`UNFREEZE` accounting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from src.audit.audit_logger import AsyncAuditLogger
from src.audit.p13_reader import P13SessionLoad, P18ReplayFrameRetriever, load_p13_session_readonly
from src.audit.p19_events import build_capital_event_log
from src.data_acquisition.passive_book_recorder import MarketBookRecordEnvelope
from src.data_acquisition.settlement_metar_stream import CoverageLedgerEntry
from src.decision.engine import (
    DeterministicDecider,
    ExecutionPolicyBundle,
    LightLevelEvent,
    P16SubscriptionSlot,
    QuotaProvider,
    ScanClock,
    ScanDecisionEvent,
)
from src.execution.executor import (
    ExecutionAttemptLog,
    OrderExecutionContext,
    PlannedLegSlice,
    ReplayMatcher,
    SlicePlan,
    TradingExecutionConfig,
)
from src.prediction.forecast_distribution_engine import ForecastDistributionSnapshotV11
from src.utils.causal_utils import ensure_utc_datetime


@dataclass(frozen=True)
class ReplayScanStep:
    """One deterministic scan instruction referencing recorded `(station, date, bin, market)`."""

    scan_ts_utc: datetime
    scan_clock: ScanClock
    station_id: str
    target_date: str
    bin_id: str
    bin_label: str
    market_id: str
    yes_token_id: str
    no_token_id: Optional[str] = None
    include_no_side: bool = False
    target_type: str = "TMAX"
    submit_delay_ms: int = 0


@dataclass(frozen=True)
class BatchReplaySummary:
    """Aggregate summary of an end-to-end `P13` batch replay execution."""

    orig_session_id: str
    p13_files_scanned: int
    p13_valid_frames: int
    p13_corrupt_lines: int
    scans_executed: int
    ordered_count: int
    p1_logged: int
    p3_logged: int
    p17_logged: int
    p19_logged: int
    p12_logged: int
    filled_or_partial_count: int
    aborted_gap_count: int
    cancelled_unfilled_count: int


@dataclass
class _ReplayCounters:
    ordered: int = 0
    filled: int = 0
    aborted_gap: int = 0
    cancelled: int = 0


@dataclass
class _ReplayAccountTracker:
    free_usd: float
    active_locked_usd: float = 0.0

    def apply_freeze(self, target_usd: float) -> float:
        frozen = min(max(target_usd, 0.0), max(self.free_usd, 0.0))
        self.free_usd -= frozen
        self.active_locked_usd += frozen
        return frozen

    def apply_settlement_conversion(self, frozen_usd: float, filled_usd: float) -> float:
        used = min(max(filled_usd, 0.0), frozen_usd)
        refund = max(0.0, frozen_usd - used)
        self.free_usd += refund
        self.active_locked_usd = max(0.0, self.active_locked_usd - refund)
        return used

    def apply_unfreeze(self, frozen_usd: float) -> None:
        self.free_usd += frozen_usd
        self.active_locked_usd = max(0.0, self.active_locked_usd - frozen_usd)


@dataclass(frozen=True)
class _ReplayRuntime:
    orig_session_id: str
    retriever: P18ReplayFrameRetriever
    decider: DeterministicDecider
    matcher: ReplayMatcher
    exec_config: TradingExecutionConfig
    forecasts: Sequence[ForecastDistributionSnapshotV11]
    policy_bundle: ExecutionPolicyBundle
    quota_provider: QuotaProvider
    light_event: Optional[LightLevelEvent]
    logger: AsyncAuditLogger
    counters: _ReplayCounters
    account: _ReplayAccountTracker


def _build_replay_order_context(
    *,
    decision_id: str,
    session_id: str,
    station_id: str,
    market_id: str,
    yes_token_id: str,
    model_hash: str,
    config_hash: str,
    decision_ts_utc: datetime,
    submit_ts_utc: datetime,
    decision_best_ask: float,
    yes_seq: int,
    include_no_side: bool,
    no_token_id: Optional[str],
    no_seq: Optional[int],
) -> OrderExecutionContext:
    return OrderExecutionContext(
        decision_id=decision_id, session_id=session_id, station_id=station_id,
        market_id=market_id, yes_token_id=yes_token_id, model_hash=model_hash,
        config_hash=config_hash, decision_ts_utc=decision_ts_utc,
        decision_best_ask=decision_best_ask, submit_ts_utc=submit_ts_utc,
        decision_seq_id=yes_seq, include_no_side=include_no_side,
        no_token_id=no_token_id, no_decision_seq_id=no_seq, execution_mode="PAPER",
    )


def probe_p18_gap_frame_abort(
    retriever: P18ReplayFrameRetriever,
    gap_env: MarketBookRecordEnvelope,
    *,
    config: TradingExecutionConfig,
) -> ExecutionAttemptLog:
    """Probe deterministic `P18` `ReplayMatcher` response right across a recorded gap frame."""
    if not gap_env.gap_detected:
        raise ValueError(f"Expected gap_detected=True frame, got seq_id={gap_env.seq_id}")
    hit_ts = ensure_utc_datetime(gap_env.payload.recv_ts_utc, field_name="gap_env.recv_ts_utc")
    dec_ts = hit_ts - timedelta(milliseconds=config.latency_ms)
    stream = retriever.get_token_stream(gap_env.payload.token_id)
    dec_seq = retriever.find_latest_seq_before(gap_env.payload.token_id, hit_ts, strict_lt_seq=gap_env.seq_id)
    is_no = gap_env.payload.outcome == "NO"
    yes_tok, yes_seq = retriever.resolve_companion_yes_token(gap_env) if is_no else (gap_env.payload.token_id, dec_seq)
    ctx = _build_replay_order_context(
        decision_id=f"probe-gap-{gap_env.session_id}-{gap_env.seq_id}",
        session_id=gap_env.session_id, station_id=gap_env.station_id, market_id=gap_env.payload.market_id,
        yes_token_id=yes_tok, model_hash="p18_gap_probe", config_hash="p18_gap_probe",
        decision_ts_utc=dec_ts, submit_ts_utc=dec_ts, decision_best_ask=0.50, yes_seq=yes_seq,
        include_no_side=is_no, no_token_id=gap_env.payload.token_id if is_no else None,
        no_seq=dec_seq if is_no else None,
    )
    plan = SlicePlan(
        should_submit=True, abort_reason=None, order_type="IOC_FAK",
        target_shares=Decimal("10"), target_usd=Decimal("5.00"), limit_price=Decimal("0.50"),
        est_vwap=Decimal("0.50"), qual_depth_shares=Decimal("20"),
        leg_allocations=(
            PlannedLegSlice(
                leg_source="NO_BID_SPLIT_SELL" if is_no else "YES_ASK",
                source_token_id=gap_env.payload.token_id, implied_yes_price=Decimal("0.50"),
                raw_source_price=Decimal("0.50"), allocated_shares=Decimal("10"), allocated_usd=Decimal("5.00"),
            ),
        ),
    )
    eval_envs = retriever.get_token_stream(yes_tok) + stream if is_no else stream
    return ReplayMatcher(config).match_order(context=ctx, plan=plan, recorded_envelopes=eval_envs)


def _execute_single_order_attempt(
    step: ReplayScanStep, decision: ScanDecisionEvent, rt: _ReplayRuntime
) -> ExecutionAttemptLog:
    assert decision.slice_plan is not None
    t_scan = ensure_utc_datetime(step.scan_ts_utc, field_name="step.scan_ts_utc")
    sub_ts = t_scan + timedelta(milliseconds=int(step.submit_delay_ms))
    streams = list(rt.retriever.get_token_stream(step.yes_token_id))
    if step.include_no_side and step.no_token_id is not None:
        streams.extend(rt.retriever.get_token_stream(step.no_token_id))
    yes_seq = rt.retriever.find_latest_seq_before(step.yes_token_id, sub_ts)
    no_seq = (
        rt.retriever.find_latest_seq_before(step.no_token_id, sub_ts)
        if (step.include_no_side and step.no_token_id is not None)
        else None
    )
    ctx = _build_replay_order_context(
        decision_id=decision.decision_id, session_id=rt.orig_session_id,
        station_id=step.station_id, market_id=step.market_id, yes_token_id=step.yes_token_id,
        model_hash=decision.model_hash, config_hash=decision.config_hash,
        decision_ts_utc=decision.scan_ts_utc, submit_ts_utc=sub_ts,
        decision_best_ask=decision.best_ask_price or 0.0, yes_seq=yes_seq,
        include_no_side=step.include_no_side, no_token_id=step.no_token_id, no_seq=no_seq,
    )
    return rt.matcher.match_order(context=ctx, plan=decision.slice_plan, recorded_envelopes=streams)


def _log_initial_context_streams(
    rt: _ReplayRuntime,
    forecasts: Sequence[ForecastDistributionSnapshotV11],
    coverage_ledgers: Sequence[CoverageLedgerEntry],
) -> None:
    for led in coverage_ledgers:
        rt.logger.log_p12_coverage_ledger(led)
    for fc in forecasts:
        rt.logger.log_p17_forecast_snapshot(
            fc, session_id=rt.orig_session_id, config_hash=rt.policy_bundle.config_hash
        )
    if rt.light_event is not None:
        ev = rt.light_event
        rt.logger.log_p19_capital_event(
            build_capital_event_log(
                event_ts_utc=ev.emitted_ts_utc, session_id=rt.orig_session_id, execution_mode="PAPER",
                station_id=ev.station_id, event_type="LIGHT_LEVEL_APPLIED",
                free_usd_after=rt.account.free_usd, active_locked_usd_after=rt.account.active_locked_usd,
                policy_version=rt.policy_bundle.policy_version, config_hash=rt.policy_bundle.config_hash,
                is_overdue=rt.policy_bundle.is_overdue, light_status=ev.level,
                related_ref_id=ev.event_id, reason=ev.reason,
            )
        )


def _emit_order_p19_lifecycle(
    rt: _ReplayRuntime,
    decision: ScanDecisionEvent,
    attempt: ExecutionAttemptLog,
    frozen_usd: float,
) -> None:
    if attempt.terminal_status in ("FILLED", "PARTIAL"):
        rt.counters.filled += 1
        rt.account.apply_settlement_conversion(frozen_usd, float(attempt.filled_usd))
        ev_type, reason = "FILL_SETTLE_CONVERSION", f"PAPER_{attempt.terminal_status}:{decision.decision_id}"
    else:
        if attempt.terminal_status == "PAPER_MATCH_ABORTED_GAP":
            rt.counters.aborted_gap += 1
        elif attempt.terminal_status == "CANCELLED_UNFILLED":
            rt.counters.cancelled += 1
        rt.account.apply_unfreeze(frozen_usd)
        ev_type, reason = "UNFREEZE", f"PAPER_{attempt.terminal_status}:{attempt.reject_or_abort_reason}"

    rt.logger.log_p19_capital_event(
        build_capital_event_log(
            event_ts_utc=attempt.final_ts_utc, session_id=attempt.session_id, execution_mode="PAPER",
            station_id=attempt.station_id, event_type=ev_type, free_usd_after=rt.account.free_usd,
            active_locked_usd_after=rt.account.active_locked_usd,
            policy_version=rt.policy_bundle.policy_version, config_hash=rt.policy_bundle.config_hash,
            is_overdue=rt.policy_bundle.is_overdue, light_status=decision.light_status,
            related_ref_id=attempt.attempt_id, reason=reason,
        )
    )


def _process_single_scan_step(step: ReplayScanStep, rt: _ReplayRuntime) -> None:
    t_scan = ensure_utc_datetime(step.scan_ts_utc, field_name="step.scan_ts_utc")
    causal_fc = [f for f in rt.forecasts if ensure_utc_datetime(f.issue_ts_utc, field_name="fc.issue_ts_utc") <= t_scan]
    pairs = rt.retriever.retrieve_decision_book_pairs(
        as_of_ts_utc=t_scan,
        max_book_staleness_sec=rt.exec_config.max_book_staleness_sec,
        pair_max_skew_sec=rt.exec_config.pair_max_skew_sec,
    )
    pair = pairs.get((step.station_id, step.target_date, step.bin_label, step.market_id))
    decision = rt.decider.evaluate_bin(
        orig_session_id=rt.orig_session_id, execution_mode="PAPER", scan_clock=step.scan_clock,
        scan_ts_utc=t_scan, station_id=step.station_id, target_date=step.target_date,
        bin_id=step.bin_id, market_id=step.market_id, yes_token_id=step.yes_token_id,
        forecasts=causal_fc, policy_bundle=rt.policy_bundle, quota_provider=rt.quota_provider,
        dual_pair=pair, include_no_side=step.include_no_side, target_type=step.target_type,
        light_event=rt.light_event,
    )
    rt.logger.log_p1_scan_decision(decision)
    if decision.decision_outcome != "ORDERED" or decision.slice_plan is None or pair is None:
        return
    rt.counters.ordered += 1
    frozen_usd = rt.account.apply_freeze(float(decision.slice_plan.target_usd))
    sub_ts = t_scan + timedelta(milliseconds=int(step.submit_delay_ms))
    rt.logger.log_p19_capital_event(
        build_capital_event_log(
            event_ts_utc=sub_ts, session_id=rt.orig_session_id, execution_mode="PAPER",
            station_id=step.station_id, event_type="FREEZE", free_usd_after=rt.account.free_usd,
            active_locked_usd_after=rt.account.active_locked_usd,
            policy_version=rt.policy_bundle.policy_version, config_hash=rt.policy_bundle.config_hash,
            is_overdue=rt.policy_bundle.is_overdue, light_status=decision.light_status,
            related_ref_id=decision.decision_id, reason=f"PAPER_FREEZE:{decision.decision_id}",
        )
    )
    attempt = _execute_single_order_attempt(step, decision, rt)
    rt.logger.log_p3_execution_attempt(attempt)
    _emit_order_p19_lifecycle(rt, decision, attempt, frozen_usd)


def run_p13_batch_replay(
    *,
    p13_session_dir: Path,
    audit_output_root: Path,
    orig_session_id: str,
    exec_config: TradingExecutionConfig,
    policy_bundle: ExecutionPolicyBundle,
    forecasts: Sequence[ForecastDistributionSnapshotV11],
    scan_steps: Sequence[ReplayScanStep],
    quota_provider: QuotaProvider,
    coverage_ledgers: Sequence[CoverageLedgerEntry] = (),
    light_event: Optional[LightLevelEvent] = None,
    p16_slot: Optional[P16SubscriptionSlot] = None,
) -> BatchReplaySummary:
    """Execute end-to-end read-only `P13 -> M4 -> M5(P18) -> M7` batch paper replay."""
    loaded: P13SessionLoad = load_p13_session_readonly(p13_session_dir)
    counters = _ReplayCounters()
    account = _ReplayAccountTracker(free_usd=policy_bundle.w_policy.station_cap_usd)
    with AsyncAuditLogger(audit_output_root, execution_mode="PAPER") as logger:
        rt = _ReplayRuntime(
            orig_session_id=orig_session_id, retriever=P18ReplayFrameRetriever(loaded.envelopes),
            decider=DeterministicDecider(exec_config=exec_config, p16_slot=p16_slot),
            matcher=ReplayMatcher(config=exec_config), exec_config=exec_config,
            forecasts=forecasts, policy_bundle=policy_bundle, quota_provider=quota_provider,
            light_event=light_event, logger=logger, counters=counters, account=account,
        )
        _log_initial_context_streams(rt, forecasts, coverage_ledgers)
        for step in scan_steps:
            _process_single_scan_step(step, rt)
        logger.flush()
        st = logger.stats().written_by_stream
    return BatchReplaySummary(
        orig_session_id=orig_session_id, p13_files_scanned=loaded.summary.files_scanned,
        p13_valid_frames=loaded.summary.valid_frames, p13_corrupt_lines=len(loaded.summary.corrupt_lines),
        scans_executed=len(scan_steps), ordered_count=counters.ordered,
        p1_logged=st["p1"], p3_logged=st["p3"], p17_logged=st["p17"], p19_logged=st["p19"],
        p12_logged=st["p12"], filled_or_partial_count=counters.filled,
        aborted_gap_count=counters.aborted_gap, cancelled_unfilled_count=counters.cancelled,
    )


__all__ = [
    "BatchReplaySummary",
    "ReplayScanStep",
    "probe_p18_gap_frame_abort",
    "run_p13_batch_replay",
]
