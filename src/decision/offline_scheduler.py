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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from src.audit.audit_logger import AsyncAuditLogger
from src.audit.p13_reader import P13SessionLoad, P18ReplayFrameRetriever, load_p13_session_readonly
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
from src.execution.executor import TradingExecutionConfig
from src.prediction.forecast_distribution_engine import ForecastDistributionSnapshotV11
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
) -> ScanDecisionEvent:
    book_as_of = tick_utc - timedelta(milliseconds=max(0, int(cfg.replay_delay_ms)))
    causal_fc = [
        fc for fc in forecasts
        if ensure_utc_datetime(fc.issue_ts_utc, field_name="fc.issue_ts_utc") <= tick_utc
    ]
    pairs = retriever.retrieve_decision_book_pairs(
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
) -> Tuple[Dict[str, int], int, Tuple[int, ...]]:
    """Run forecast/decision replay loop into M7 audit logger (offline only)."""
    ordered_cnt = 0
    consumed_seqs: List[int] = []
    with AsyncAuditLogger(cfg.audit_output_root, execution_mode="PAPER") as logger:
        for fc in forecasts:
            logger.log_p17_forecast_snapshot(
                fc, session_id=cfg.orig_session_id, config_hash=policy_bundle.config_hash,
                capture_replay_mode="REPLAY_P13",
            )
        for tick_utc in ticks:
            for target in targets:
                ev = _evaluate_tick_target(
                    tick_utc=tick_utc, target=target, cfg=cfg, retriever=retriever,
                    decider=decider, exec_config=exec_config, forecasts=forecasts,
                    policy_bundle=policy_bundle, quota_provider=quota_provider, light_event=light_event,
                )
                logger.log_p1_scan_decision(ev)
                consumed_seqs.append(ev.book_frame_ref)
                ordered_cnt += 1 if ev.decision_outcome == "ORDERED" else 0
        logger.flush()
        written = logger.stats().written_by_stream
    return written, ordered_cnt, tuple(consumed_seqs)


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
) -> OfflineScheduleSummary:
    """Execute S3-11 offline delayed-replay schedule (`P13 -> M4 -> M7 p1.v3/p17.v3`)."""
    loaded = load_p13_session_readonly(cfg.p13_session_dir)
    ordered_envs = sorted(
        loaded.envelopes,
        key=lambda e: (ensure_utc_datetime(e.payload.recv_ts_utc, field_name="p13.recv_ts_utc"), e.seq_id),
    )
    retriever = P18ReplayFrameRetriever(ordered_envs)
    ticks = _resolve_schedule_ticks(cfg, loaded, clock_ticks)
    decider, clob_host = build_wired_decider(
        exec_config=exec_config,
        safety_config_path=cfg.safety_config_path,
        p16_slot=p16_slot,
        enable_official_fee_rate_probe=cfg.enable_official_fee_rate_probe,
        fee_rate_timeout_sec=cfg.fee_rate_timeout_sec,
    )
    written, ordered_cnt, consumed_seqs = _execute_audit_replay_loop(
        cfg, ticks=ticks, targets=targets, retriever=retriever, decider=decider,
        exec_config=exec_config, forecasts=forecasts, policy_bundle=policy_bundle,
        quota_provider=quota_provider, light_event=light_event,
    )
    return OfflineScheduleSummary(
        orig_session_id=cfg.orig_session_id, clob_host_wired=clob_host,
        probe_enabled=cfg.enable_official_fee_rate_probe, ticks_executed=len(ticks),
        decisions_logged=written["p1"], p17_logged=written["p17"], ordered_count=ordered_cnt,
        p13_valid_frames=loaded.summary.valid_frames, p13_corrupt_lines=len(loaded.summary.corrupt_lines),
        consumed_frame_seqs=consumed_seqs,
    )


__all__ = [
    "OfflineScheduleSummary",
    "OfflineScheduleTarget",
    "OfflineSchedulerConfig",
    "build_wired_decider",
    "generate_synthetic_clock_ticks",
    "run_s311_offline_schedule",
]
