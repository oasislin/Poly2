"""S3-11 Offline P13 Delayed-Replay Scheduler & EXEC4 Option-1 Fee Probe Wiring.

Strictly offline and outside frozen `src/execution/`:
- Reads recorded `P13` JSONL streams in causal `(recv_ts_utc, seq_id)` order
- Drives `DeterministicDecider` across synthetic clock ticks with `replay_delay_ms`
- Logs `p17.v3` and `p1.v3` with `capture_replay_mode="REPLAY_P13"` via `AsyncAuditLogger`
- Wires `enable_official_fee_rate_probe` (offline default `False`), `clob_host=safety.clob_host`,
  and `fee_rate_timeout_sec=0.5` (`EXEC4` Option 1)
- Never connects to any live or paper order submission endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import AbstractSet, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from src.audit.audit_logger import AsyncAuditLogger
from src.audit.p13_reader import P13SessionLoad, P18ReplayFrameRetriever, load_p13_session_readonly
from src.bankroll.manager import BankrollAccountManager
from src.bankroll.models import FillSettleLoopback, FreezeRequest
from src.data_acquisition.settlement_metar_stream import (
    RawMetarSource,
    compute_local_day_window_utc,
    resolve_station_timezone,
)
from src.decision.engine import (
    DeterministicDecider,
    ExecutionPolicyBundle,
    LightLevelEvent,
    P16SubscriptionSlot,
    QuotaProvider,
    ScanClock,
    ScanDecisionEvent,
)
from src.execution.clob_gateway import DEFAULT_GATEWAY_CONFIG_PATH, load_gateway_safety_config
from src.execution.executor import (
    ExecutionAttemptLog,
    OrderExecutionContext,
    ReplayMatcher,
    TradingExecutionConfig,
)
from src.prediction.forecast_distribution_engine import ForecastDistributionSnapshotV11
from src.settlement.m9_settler import (
    M9SettlementEngine,
    MarketPositionClaim,
    SettlementBinSpec,
    SettlementPendingError,
    next_day_et_deadline_utc,
)
from src.utils.causal_utils import ensure_utc_datetime


@dataclass(frozen=True)
class OfflineScheduleTarget:
    """One market bin target evaluated at each synthetic schedule tick."""

    station_id: str
    target_date: str
    bin_id: str
    bin_label: str
    market_id: str
    yes_token_id: str
    target_type: str = "TMAX"
    include_no_side: bool = False


@dataclass(frozen=True)
class OfflineSchedulerConfig:
    """Configuration for S3-11 offline delayed-replay decision scheduling."""

    p13_session_dir: Path
    audit_output_root: Path
    orig_session_id: str
    safety_config_path: Path = DEFAULT_GATEWAY_CONFIG_PATH
    cadence_sec: float = 60.0
    replay_delay_ms: int = 0
    scan_clock: ScanClock = "PRICE_CLOCK"
    enable_official_fee_rate_probe: bool = False
    fee_rate_timeout_sec: float = 0.5
    enable_p18_matching: bool = False
    enable_m9_settlement: bool = False


@dataclass(frozen=True)
class OfflineScheduleSummary:
    """Structured summary of an offline S3-11 delayed-replay schedule run."""

    orig_session_id: str
    clob_host_wired: str
    probe_enabled: bool
    ticks_executed: int
    decisions_logged: int
    p17_logged: int
    ordered_count: int
    p13_valid_frames: int
    p13_corrupt_lines: int
    consumed_frame_seqs: Tuple[int, ...]
    outcome_counts: Tuple[Tuple[str, int], ...] = ()
    degradation_counts: Tuple[Tuple[str, int], ...] = ()
    p3_logged: int = 0
    p9_logged: int = 0
    filled_count: int = 0


def generate_synthetic_clock_ticks(
    start_utc: datetime,
    end_utc: datetime,
    cadence_sec: float,
) -> Tuple[datetime, ...]:
    """Generate deterministic UTC synthetic clock ticks `[start_utc, end_utc]`."""
    if cadence_sec <= 0:
        raise ValueError(f"cadence_sec must be > 0, got {cadence_sec}")
    t_start = ensure_utc_datetime(start_utc, field_name="schedule.start_utc")
    t_end = ensure_utc_datetime(end_utc, field_name="schedule.end_utc")
    if t_end < t_start:
        raise ValueError("end_utc must be >= start_utc")
    step = timedelta(seconds=float(cadence_sec))
    ticks: List[datetime] = []
    cur = t_start
    while cur <= t_end:
        ticks.append(cur)
        cur = cur + step
    return tuple(ticks)


def build_wired_decider(
    *,
    exec_config: TradingExecutionConfig,
    safety_config_path: Path = DEFAULT_GATEWAY_CONFIG_PATH,
    p16_slot: Optional[P16SubscriptionSlot] = None,
    enable_official_fee_rate_probe: bool = False,
    fee_rate_timeout_sec: float = 0.5,
) -> Tuple[DeterministicDecider, str]:
    """Construct `DeterministicDecider` with EXEC4 Option-1 `clob_host` & probe wiring."""
    safety = load_gateway_safety_config(safety_config_path)
    decider = DeterministicDecider(
        exec_config=exec_config,
        p16_slot=p16_slot,
        enable_official_fee_rate_probe=enable_official_fee_rate_probe,
        clob_host=safety.clob_host,
        fee_rate_timeout_sec=fee_rate_timeout_sec,
    )
    return decider, safety.clob_host


def _resolve_schedule_ticks(
    cfg: OfflineSchedulerConfig,
    loaded: P13SessionLoad,
    explicit_ticks: Optional[Sequence[datetime]],
) -> Tuple[datetime, ...]:
    if explicit_ticks is not None:
        return tuple(
            sorted(ensure_utc_datetime(t, field_name="schedule.tick_utc") for t in explicit_ticks)
        )
    if not loaded.envelopes:
        return ()
    ts_list = [ensure_utc_datetime(e.payload.recv_ts_utc, field_name="p13.recv_ts_utc") for e in loaded.envelopes]
    return generate_synthetic_clock_ticks(min(ts_list), max(ts_list), cfg.cadence_sec)


def _evaluate_tick_target(
    *,
    tick_utc: datetime,
    target: OfflineScheduleTarget,
    cfg: OfflineSchedulerConfig,
    retriever: P18ReplayFrameRetriever,
    decider: DeterministicDecider,
    exec_config: TradingExecutionConfig,
    forecasts: Sequence[ForecastDistributionSnapshotV11],
    policy_bundle: ExecutionPolicyBundle,
    quota_provider: QuotaProvider,
    light_event: Optional[LightLevelEvent],
    book_pairs: Optional[Dict] = None,
) -> ScanDecisionEvent:
    book_as_of = tick_utc - timedelta(milliseconds=max(0, int(cfg.replay_delay_ms)))
    causal_fc = [
        fc for fc in forecasts
        if ensure_utc_datetime(fc.issue_ts_utc, field_name="fc.issue_ts_utc") <= tick_utc
    ]
    pairs = book_pairs if book_pairs is not None else retriever.retrieve_decision_book_pairs(
        as_of_ts_utc=book_as_of,
        max_book_staleness_sec=exec_config.max_book_staleness_sec,
        pair_max_skew_sec=exec_config.pair_max_skew_sec,
    )
    pair = pairs.get((target.station_id, target.target_date, target.bin_label, target.market_id))
    return decider.evaluate_bin(
        orig_session_id=cfg.orig_session_id,
        execution_mode="PAPER",
        scan_clock=cfg.scan_clock,
        scan_ts_utc=tick_utc,
        station_id=target.station_id,
        target_date=target.target_date,
        bin_id=target.bin_id,
        market_id=target.market_id,
        yes_token_id=target.yes_token_id,
        forecasts=causal_fc,
        policy_bundle=policy_bundle,
        quota_provider=quota_provider,
        dual_pair=pair,
        include_no_side=target.include_no_side,
        target_type=target.target_type,
        light_event=light_event,
        capture_replay_mode="REPLAY_P13",
    )


def _match_and_bookkeep_ordered(
    *,
    ev: ScanDecisionEvent,
    cfg: OfflineSchedulerConfig,
    retriever: P18ReplayFrameRetriever,
    matcher: ReplayMatcher,
    quota_provider: QuotaProvider,
    logger: AsyncAuditLogger,
    open_claims: Dict[Tuple[str, str, str], MarketPositionClaim],
) -> Optional[ExecutionAttemptLog]:
    if ev.decision_outcome != "ORDERED" or ev.slice_plan is None or not ev.slice_plan.should_submit:
        return None
    if isinstance(quota_provider, BankrollAccountManager):
        rec = quota_provider.freeze_for_order(FreezeRequest(
            decision_id=ev.decision_id, idempotency_key=f"p14-{ev.decision_id}",
            station_id=ev.station_id, market_id=ev.market_id, token_id=ev.token_id,
            target_freeze_usd=ev.slice_plan.target_usd, requested_ts_utc=ev.scan_ts_utc,
        ))
        if not rec.accepted:
            return None
    dec_seq = retriever.find_latest_seq_before(ev.token_id, ev.scan_ts_utc)
    ctx = OrderExecutionContext(
        decision_id=ev.decision_id, session_id=cfg.orig_session_id, station_id=ev.station_id,
        market_id=ev.market_id, yes_token_id=ev.token_id, model_hash=ev.model_hash,
        config_hash=ev.config_hash, decision_ts_utc=ev.scan_ts_utc,
        decision_best_ask=ev.best_ask_price or 0.0, submit_ts_utc=ev.scan_ts_utc,
        decision_seq_id=dec_seq, execution_mode="PAPER",
    )
    attempt = matcher.match_order(
        context=ctx, plan=ev.slice_plan, recorded_envelopes=retriever.get_token_stream(ev.token_id),
    )
    logger.log_p3_execution_attempt(attempt)
    if isinstance(quota_provider, BankrollAccountManager):
        quota_provider.settle_order_fill(FillSettleLoopback(
            decision_id=ev.decision_id, attempt_id=attempt.attempt_id, station_id=ev.station_id,
            market_id=ev.market_id, filled_usd=attempt.filled_usd, terminal_status=attempt.terminal_status,
            settled_ts_utc=attempt.final_ts_utc, reject_or_abort_reason=attempt.reject_or_abort_reason,
            fee_paid_usd=attempt.fee_paid_usd,
        ))
    if attempt.filled_shares > Decimal("0"):
        mkey = (ev.station_id, ev.target_date, ev.target_type)
        prev = open_claims.get(mkey)
        shares = attempt.filled_shares + (prev.held_shares if prev else Decimal("0"))
        cost = attempt.filled_usd + (prev.cost_basis_usd or Decimal("0") if prev else Decimal("0"))
        open_claims[mkey] = MarketPositionClaim(ev.market_id, ev.bin_id, shares, cost)
    return attempt


def run_m9_settlement_pass(
    *,
    forecasts: Sequence[ForecastDistributionSnapshotV11],
    now_utc: datetime,
    metar_source: RawMetarSource,
    logger: AsyncAuditLogger,
    session_id: str,
    bankroll: Optional[BankrollAccountManager] = None,
    open_claims: Optional[Dict[Tuple[str, str, str], MarketPositionClaim]] = None,
    settled_keys: Optional[Set[Tuple[str, str, str]]] = None,
) -> int:
    """Evaluate `M9 P9` settlement for newly closed markets (`issue_ts_utc <= settle_close_utc`)."""
    engine = M9SettlementEngine(audit_logger=logger)
    seen = settled_keys if settled_keys is not None else set()
    claims = open_claims if open_claims is not None else {}
    by_mkt: Dict[Tuple[str, str, str], ForecastDistributionSnapshotV11] = {}
    for fc in forecasts:
        if ensure_utc_datetime(fc.issue_ts_utc, field_name="fc.issue_ts_utc") <= ensure_utc_datetime(fc.settle_close_utc, field_name="fc.settle_close_utc"):
            by_mkt[(fc.station_id, fc.target_date.isoformat(), fc.target_type)] = fc
    count = 0
    for mkey, fc in sorted(by_mkt.items()):
        if mkey in seen or now_utc < fc.settle_close_utc:
            continue
        t_date = date.fromisoformat(mkey[1])
        day_start, settle_close = compute_local_day_window_utc(t_date, resolve_station_timezone(fc.station_id))
        fetch_end = min(now_utc, next_day_et_deadline_utc(t_date))
        try:
            reports = metar_source.fetch_window(fc.station_id, day_start, max(fetch_end, settle_close))
            bins = tuple(SettlementBinSpec(b.bin_id, b.lower_int_f, b.upper_int_f) for b in fc.bin_probs)
            claim = claims.pop(mkey, None)
            if claim is not None and bankroll is not None:
                engine.settle_and_release_p15(
                    session_id=session_id, execution_mode="PAPER", station_id=fc.station_id,
                    target_date=t_date, target_type=fc.target_type, claim=claim,
                    reports=reports, bins=bins, bankroll=bankroll, as_of_ts_utc=now_utc,
                )
            else:
                p9 = engine.evaluate_settlement(
                    session_id=session_id, execution_mode="PAPER", station_id=fc.station_id,
                    target_date=t_date, target_type=fc.target_type, market_id=f"p9-{fc.station_id}-{mkey[1]}",
                    reports=reports, bins=bins, as_of_ts_utc=now_utc,
                )
                logger.log_p9_settlement_truth(p9)
            seen.add(mkey)
            count += 1
        except SettlementPendingError:
            continue
    return count


def _log_initial_p17_forecasts(
    logger: AsyncAuditLogger,
    forecasts: Sequence[ForecastDistributionSnapshotV11],
    *,
    session_id: str,
    config_hash: str,
    skip_ids: AbstractSet[str],
) -> None:
    for fc in forecasts:
        if fc.forecast_id not in skip_ids:
            logger.log_p17_forecast_snapshot(
                fc, session_id=session_id, config_hash=config_hash, capture_replay_mode="REPLAY_P13"
            )


def _run_tick_targets(
    *,
    tick_utc: datetime,
    targets: Sequence[OfflineScheduleTarget],
    cfg: OfflineSchedulerConfig,
    retriever: P18ReplayFrameRetriever,
    decider: DeterministicDecider,
    exec_config: TradingExecutionConfig,
    forecasts: Sequence[ForecastDistributionSnapshotV11],
    policy_bundle: ExecutionPolicyBundle,
    quota_provider: QuotaProvider,
    light_event: Optional[LightLevelEvent],
    matcher: Optional[ReplayMatcher],
    logger: AsyncAuditLogger,
    claims: Dict[Tuple[str, str, str], MarketPositionClaim],
    consumed_seqs: List[int],
    outcomes: Dict[str, int],
    degradations: Dict[str, int],
) -> Tuple[int, int]:
    ordered_inc, filled_inc = 0, 0
    pairs = retriever.retrieve_decision_book_pairs(
        as_of_ts_utc=tick_utc - timedelta(milliseconds=max(0, int(cfg.replay_delay_ms))),
        max_book_staleness_sec=exec_config.max_book_staleness_sec, pair_max_skew_sec=exec_config.pair_max_skew_sec,
    )
    for target in targets:
        ev = _evaluate_tick_target(
            tick_utc=tick_utc, target=target, cfg=cfg, retriever=retriever, decider=decider,
            exec_config=exec_config, forecasts=forecasts, policy_bundle=policy_bundle,
            quota_provider=quota_provider, light_event=light_event, book_pairs=pairs,
        )
        logger.log_p1_scan_decision(ev)
        consumed_seqs.append(ev.book_frame_ref)
        outcomes[ev.decision_outcome] = outcomes.get(ev.decision_outcome, 0) + 1
        if ev.degradation_reason:
            degradations[ev.degradation_reason] = degradations.get(ev.degradation_reason, 0) + 1
        if ev.decision_outcome == "ORDERED":
            ordered_inc += 1
            if matcher is not None:
                att = _match_and_bookkeep_ordered(
                    ev=ev, cfg=cfg, retriever=retriever, matcher=matcher,
                    quota_provider=quota_provider, logger=logger, open_claims=claims,
                )
                filled_inc += 1 if (att and att.terminal_status in ("FILLED", "PARTIAL")) else 0
    return ordered_inc, filled_inc


def _execute_audit_replay_loop(
    cfg: OfflineSchedulerConfig,
    *,
    ticks: Tuple[datetime, ...],
    targets: Sequence[OfflineScheduleTarget],
    retriever: P18ReplayFrameRetriever,
    decider: DeterministicDecider,
    exec_config: TradingExecutionConfig,
    forecasts: Sequence[ForecastDistributionSnapshotV11],
    policy_bundle: ExecutionPolicyBundle,
    quota_provider: QuotaProvider,
    light_event: Optional[LightLevelEvent],
    p17_forecast_ids_to_skip: Optional[AbstractSet[str]] = None,
    metar_source: Optional[RawMetarSource] = None,
    settled_keys: Optional[Set[Tuple[str, str, str]]] = None,
    open_claims: Optional[Dict[Tuple[str, str, str], MarketPositionClaim]] = None,
    p19_sink_setter: Optional[Callable[[Optional[Callable]], None]] = None,
) -> Tuple[Dict[str, int], int, int, Tuple[int, ...], Dict[str, int], Dict[str, int]]:
    """Run forecast/decision/P18-match/M9-settlement replay loop into M7 audit logger (offline only)."""
    ordered_cnt, filled_cnt, skip_ids = 0, 0, p17_forecast_ids_to_skip or set()
    consumed_seqs: List[int] = []
    outcomes: Dict[str, int] = {}
    degradations: Dict[str, int] = {}
    matcher = ReplayMatcher(exec_config) if cfg.enable_p18_matching else None
    claims = open_claims if open_claims is not None else {}
    with AsyncAuditLogger(cfg.audit_output_root, execution_mode="PAPER") as logger:
        if p19_sink_setter is not None:
            p19_sink_setter(logger.log_p19_capital_event)
        _log_initial_p17_forecasts(logger, forecasts, session_id=cfg.orig_session_id, config_hash=policy_bundle.config_hash, skip_ids=skip_ids)
        for tick_utc in ticks:
            o_inc, f_inc = _run_tick_targets(
                tick_utc=tick_utc, targets=targets, cfg=cfg, retriever=retriever, decider=decider,
                exec_config=exec_config, forecasts=forecasts, policy_bundle=policy_bundle,
                quota_provider=quota_provider, light_event=light_event, matcher=matcher, logger=logger,
                claims=claims, consumed_seqs=consumed_seqs, outcomes=outcomes, degradations=degradations,
            )
            ordered_cnt, filled_cnt = ordered_cnt + o_inc, filled_cnt + f_inc
        if cfg.enable_m9_settlement and metar_source is not None:
            bankroll = quota_provider if isinstance(quota_provider, BankrollAccountManager) else None
            run_m9_settlement_pass(
                forecasts=forecasts, now_utc=(ticks[-1] if ticks else datetime.now(timezone.utc)),
                metar_source=metar_source, logger=logger, session_id=cfg.orig_session_id,
                bankroll=bankroll, open_claims=claims, settled_keys=settled_keys,
            )
        logger.flush()
        if p19_sink_setter is not None:
            p19_sink_setter(None)
        written = logger.stats().written_by_stream
    return written, ordered_cnt, filled_cnt, tuple(consumed_seqs), outcomes, degradations


def run_s311_offline_schedule(
    cfg: OfflineSchedulerConfig,
    *,
    exec_config: TradingExecutionConfig,
    policy_bundle: ExecutionPolicyBundle,
    forecasts: Sequence[ForecastDistributionSnapshotV11],
    targets: Sequence[OfflineScheduleTarget],
    quota_provider: QuotaProvider,
    clock_ticks: Optional[Sequence[datetime]] = None,
    light_event: Optional[LightLevelEvent] = None,
    p16_slot: Optional[P16SubscriptionSlot] = None,
    p17_forecast_ids_to_skip: Optional[AbstractSet[str]] = None,
    metar_source: Optional[RawMetarSource] = None,
    settled_keys: Optional[Set[Tuple[str, str, str]]] = None,
    open_claims: Optional[Dict[Tuple[str, str, str], MarketPositionClaim]] = None,
    p19_sink_setter: Optional[Callable[[Optional[Callable]], None]] = None,
) -> OfflineScheduleSummary:
    """Execute S3-11 offline delayed-replay schedule (`P13 -> M4 -> [M5 P18] -> [M9 P9] -> M7`)."""
    loaded = load_p13_session_readonly(cfg.p13_session_dir)
    ordered_envs = sorted(
        loaded.envelopes,
        key=lambda e: (ensure_utc_datetime(e.payload.recv_ts_utc, field_name="p13.recv_ts_utc"), e.seq_id),
    )
    retriever = P18ReplayFrameRetriever(ordered_envs)
    ticks = _resolve_schedule_ticks(cfg, loaded, clock_ticks)
    decider, clob_host = build_wired_decider(
        exec_config=exec_config, safety_config_path=cfg.safety_config_path,
        p16_slot=p16_slot, enable_official_fee_rate_probe=cfg.enable_official_fee_rate_probe,
        fee_rate_timeout_sec=cfg.fee_rate_timeout_sec,
    )
    written, ordered_cnt, filled_cnt, consumed_seqs, outcomes, degradations = _execute_audit_replay_loop(
        cfg, ticks=ticks, targets=targets, retriever=retriever, decider=decider,
        exec_config=exec_config, forecasts=forecasts, policy_bundle=policy_bundle,
        quota_provider=quota_provider, light_event=light_event,
        p17_forecast_ids_to_skip=p17_forecast_ids_to_skip, metar_source=metar_source,
        settled_keys=settled_keys, open_claims=open_claims, p19_sink_setter=p19_sink_setter,
    )
    return OfflineScheduleSummary(
        orig_session_id=cfg.orig_session_id, clob_host_wired=clob_host,
        probe_enabled=cfg.enable_official_fee_rate_probe, ticks_executed=len(ticks),
        decisions_logged=written["p1"], p17_logged=written["p17"], ordered_count=ordered_cnt,
        p13_valid_frames=loaded.summary.valid_frames, p13_corrupt_lines=len(loaded.summary.corrupt_lines),
        consumed_frame_seqs=consumed_seqs, outcome_counts=tuple(sorted(outcomes.items())),
        degradation_counts=tuple(sorted(degradations.items())),
        p3_logged=written.get("p3", 0), p9_logged=written.get("p9", 0), filled_count=filled_cnt,
    )


__all__ = [
    "OfflineScheduleSummary",
    "OfflineScheduleTarget",
    "OfflineSchedulerConfig",
    "build_wired_decider",
    "generate_synthetic_clock_ticks",
    "run_s311_offline_schedule",
]
