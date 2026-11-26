"""S2-02 (`D-A1`) Read-Only `P13` Dual-Track Book-Walking Simulator & Draft Report Builder.

Anchors:
- `P8-D6-POLICY-CLOSURE v1.0 §八 L132` (`>= 200` valid slices, `>= 4` stations, `>= 72h` `0.01`-era)
- `P8-D6-POLICY-CLOSURE v1.0 §九 9.1–9.2` (`YES_ONLY` vs `DUAL_MERGED` parallel metrics & safety guardrail)
- `P8-T8-ALGO4-DESIGN v0.3 §4.3 L173` (`plan_slice` + `ReplayMatcher` walk, excluding aborted/unfilled)

Strict boundaries:
- Zero calls to `sign_off_and_issue`; never writes `policy_ledger.json` or `data/audit_logs/`.
- Zero edits to `src/execution/`, `src/pricing/`, `src/data_acquisition/`, or `evidence/`.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import statistics
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple

from src.audit.p13_reader import MarketKey, load_p13_session_readonly
from src.data_acquisition.passive_book_recorder import MarketBookRecordEnvelope
from src.execution.executor import (
    ExecutionAttemptLog,
    OrderExecutionContext,
    PhiPolicy,
    ReplayMatcher,
    TradingExecutionConfig,
    plan_slice,
)
from src.execution.orderbook_views import MergedYesAskView, build_merged_yes_ask_view

TrackName = Literal["YES_ONLY", "DUAL_MERGED"]
DEFAULT_SLICE_GRID_USD: Tuple[Decimal, ...] = (
    Decimal("5.00"),
    Decimal("25.00"),
    Decimal("53.13"),
    Decimal("104.55"),
    Decimal("171.14"),
    Decimal("250.00"),
)
MIN_S202_VALID_SLICES = 200
MIN_S202_STATIONS = 4
MIN_S202_HOURS = 72.0


@dataclass(frozen=True)
class BookWalkCalibrationConfig:
    """Explicitly parameterized S2-02 book-walking configuration with proposal provenance."""

    slice_notional_grid_usd: Tuple[Decimal, ...] = DEFAULT_SLICE_GRID_USD
    wing_prob_low: float = 0.02
    wing_prob_high: float = 0.25
    pair_max_skew_sec: float = 5.0
    max_book_staleness_sec: float = 60.0
    latency_ms: int = 150
    heartbeat_timeout_sec: float = 25.0
    rest_fallback_interval_sec: float = 5.0
    min_order_size_shares: Decimal = Decimal("5")
    min_notional_usd: Decimal = Decimal("1.0")
    sample_cadence_sec: float = 1800.0
    enable_cross_side_split_routing: bool = False
    phi_policy: PhiPolicy = PhiPolicy(
        rho_0=Decimal("0.30"), k_slope=Decimal("0"),
        rho_min=Decimal("0.10"), rho_max=Decimal("0.50"),
        provenance="P8-CAPITAL-CONFIG v1.0 §7 / M8 tests",
    )


@dataclass(frozen=True)
class SliceFillSample:
    """Single valid (`FILLED` / `PARTIAL`) P18 simulated slice sample."""

    track: TrackName
    session_id: str
    station_id: str
    target_date: str
    bin_label: str
    market_id: str
    decision_ts_utc: str
    slice_usd: float
    decision_best_ask: float
    actual_avg_fill_price: float
    slippage_vs_best_ask: float
    fill_rate: float
    terminal_status: str


@dataclass(frozen=True)
class TrackWalkSummary:
    """Aggregated slippage & status breakdown for one track (`YES_ONLY` or `DUAL_MERGED`)."""

    track: TrackName
    valid_fill_count: int
    filled_count: int
    partial_count: int
    status_counts: Dict[str, int]
    plan_abort_counts: Dict[str, int]
    stations_covered: Tuple[str, ...]
    friction_median: Optional[float]
    friction_mean: Optional[float]
    friction_p25: Optional[float]
    friction_p75: Optional[float]
    friction_p90: Optional[float]
    per_station_median: Dict[str, float]
    per_station_count: Dict[str, int]
    per_slice_median: Dict[str, float]
    sample_fills: Tuple[SliceFillSample, ...]


@dataclass(frozen=True)
class CorpusCoverageSummary:
    """Verified input P13 corpus statistics for `§8 L132` compliance checks."""

    session_count: int
    files_scanned: int
    total_frames: int
    clean_frames: int
    gap_frames: int
    corrupt_lines: int
    fee_rates_seen: Tuple[str, ...]
    fee_era_001_only: bool
    first_ts_utc: Optional[str]
    last_ts_utc: Optional[str]
    campaign_span_hours: float
    net_recorded_hours: float


@dataclass(frozen=True)
class PolicyDraftSummary:
    """Read-only candidate draft for Layer-2 sign-off (`sign_off_and_issue` NOT called)."""

    recommended_track: TrackName
    recommended_friction_median: Optional[float]
    yes_only_friction_median: Optional[float]
    dual_merged_friction_median: Optional[float]
    suggested_new_policy_version: str
    draft_rationale: str
    ledger_write_performed: bool
    signoff_status: str


@dataclass(frozen=True)
class DualTrackCalibrationReport:
    """Complete `S2-02` dual-track report (`§8 L132` + `§9.1/§9.2`) and policy draft."""

    corpus: CorpusCoverageSummary
    config_summary: Dict[str, Any]
    yes_only: TrackWalkSummary
    dual_merged: TrackWalkSummary
    wing_total_ticks: int
    wing_yes_ask_availability_pct: float
    wing_dual_merged_availability_pct: float
    wing_availability_abs_gain_pct: float
    qualified_depth_gain_median_ratio: Optional[float]
    complement_spread_count: int
    complement_spread_p10: Optional[float]
    complement_spread_p50: Optional[float]
    complement_spread_p90: Optional[float]
    inverted_cross_count: int
    inverted_cross_rate_pct: float
    valid_slices_ge_200: bool
    stations_ge_4: bool
    span_ge_72h: bool
    net_recorded_ge_72h: bool
    gate_passed: bool
    policy_draft: PolicyDraftSummary

    def to_dict(self) -> Dict[str, Any]:
        """Serialize report cleanly into a JSON-compatible dictionary."""
        return _report_to_dict(self)

    def to_markdown(self) -> str:
        """Render complete human-readable S2-02 dual-track calibration report."""
        return _render_report_markdown(self)


def _quantiles(sorted_vals: Sequence[float]) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    if not sorted_vals:
        return None, None, None, None
    n = len(sorted_vals)
    return (
        float(statistics.median(sorted_vals)),
        float(sorted_vals[n // 4]),
        float(sorted_vals[(3 * n) // 4]),
        float(sorted_vals[min(n - 1, int(0.9 * n))]),
    )


def build_execution_config(cfg: BookWalkCalibrationConfig) -> TradingExecutionConfig:
    """Convert `BookWalkCalibrationConfig` into `TradingExecutionConfig` for `ReplayMatcher`."""
    return TradingExecutionConfig(
        min_order_size_shares=cfg.min_order_size_shares,
        min_order_size_shares_provenance="FACT-004 / Gamma orderMinSize=5",
        min_notional_usd=cfg.min_notional_usd,
        min_notional_usd_provenance="P8-CAPITAL-CONFIG v1.1 §7 placeholder",
        forecast_age_limit_sec=21600.0,
        forecast_age_limit_sec_provenance="S2-02 offline calibration",
        max_book_staleness_sec=cfg.max_book_staleness_sec,
        max_book_staleness_sec_provenance="S2-02 proposal",
        pair_max_skew_sec=cfg.pair_max_skew_sec,
        pair_max_skew_sec_provenance="P8-RECORDER-NO-SIDE-DESIGN v0.1 §3.1",
        latency_ms=cfg.latency_ms,
        latency_ms_provenance="S2-02 RTT proposal",
        heartbeat_timeout_sec=cfg.heartbeat_timeout_sec,
        heartbeat_timeout_sec_provenance="configs/passive_book_recorder.example.yaml#L23",
        rest_fallback_interval_sec=cfg.rest_fallback_interval_sec,
        rest_fallback_interval_sec_provenance="configs/passive_book_recorder.example.yaml#L24",
        enable_cross_side_split_routing=cfg.enable_cross_side_split_routing,
    )


def discover_p13_session_groups(output_root: Path) -> List[Tuple[str, Tuple[Path, ...]]]:
    """Discover all `PASSIVE_RECORD` session directories grouped by `session_id`."""
    passive_root = Path(output_root) / "PASSIVE_RECORD"
    scan_root = passive_root if passive_root.exists() else Path(output_root)
    grouped: Dict[str, List[Path]] = {}
    for p in sorted(scan_root.rglob("p13_book_stream_*.jsonl")):
        sdir = p.parent
        grouped.setdefault(sdir.name, [])
        if sdir not in grouped[sdir.name]:
            grouped[sdir.name].append(sdir)
    return [(sid, tuple(sorted(dirs))) for sid, dirs in sorted(grouped.items())]


def load_all_p13_sessions(
    output_root: Path, *, verify_sha256: bool = True
) -> Tuple[List[Tuple[str, Tuple[MarketBookRecordEnvelope, ...]]], CorpusCoverageSummary]:
    """Read-only load of all P13 sessions grouped by `session_id`, verifying integrity."""
    groups = discover_p13_session_groups(output_root)
    sessions: List[Tuple[str, Tuple[MarketBookRecordEnvelope, ...]]] = []
    files_scanned = corrupt_lines = gap_frames = total_frames = clean_frames = 0
    net_sec = 0.0
    fee_rates: set[str] = set()
    first_ts: Optional[datetime] = None
    last_ts: Optional[datetime] = None
    for sid, dirs in groups:
        envs, fs, cl, gp = _load_single_session_group(dirs, verify_sha256=verify_sha256)
        files_scanned += fs
        corrupt_lines += cl
        gap_frames += gp
        total_frames += len(envs)
        clean_frames += sum(1 for e in envs if not e.gap_detected)
        for e in envs:
            fee_rates.add(f"{float(e.payload.fee_rate):.4g}")
        if envs:
            t0, t1 = envs[0].payload.recv_ts_utc, envs[-1].payload.recv_ts_utc
            net_sec += max(0.0, (t1 - t0).total_seconds())
            first_ts = t0 if first_ts is None or t0 < first_ts else first_ts
            last_ts = t1 if last_ts is None or t1 > last_ts else last_ts
        sessions.append((sid, tuple(envs)))
    span_h = ((last_ts - first_ts).total_seconds() / 3600.0) if (first_ts and last_ts) else 0.0
    corpus = CorpusCoverageSummary(
        session_count=len(sessions), files_scanned=files_scanned, total_frames=total_frames,
        clean_frames=clean_frames, gap_frames=gap_frames, corrupt_lines=corrupt_lines,
        fee_rates_seen=tuple(sorted(fee_rates)), fee_era_001_only=(fee_rates == {"0.01"}),
        first_ts_utc=first_ts.isoformat() if first_ts else None,
        last_ts_utc=last_ts.isoformat() if last_ts else None,
        campaign_span_hours=round(span_h, 4), net_recorded_hours=round(net_sec / 3600.0, 4),
    )
    return sessions, corpus


def _load_single_session_group(
    dirs: Sequence[Path], *, verify_sha256: bool
) -> Tuple[List[MarketBookRecordEnvelope], int, int, int]:
    envs: List[MarketBookRecordEnvelope] = []
    files = corrupt = gaps = 0
    for sdir in dirs:
        loaded = load_p13_session_readonly(sdir, verify_sha256=verify_sha256)
        files += loaded.summary.files_scanned
        corrupt += len(loaded.summary.corrupt_lines)
        gaps += loaded.summary.gap_frames_count
        envs.extend(loaded.envelopes)
    envs.sort(key=lambda e: (e.payload.recv_ts_utc, e.seq_id))
    return envs, files, corrupt, gaps


@dataclass
class _TrackAccumulator:
    track: TrackName
    samples: List[SliceFillSample]
    statuses: Dict[str, int]
    aborts: Dict[str, int]

    @classmethod
    def create(cls, track: TrackName) -> "_TrackAccumulator":
        return cls(track=track, samples=[], statuses={}, aborts={})


@dataclass
class _MetricAccumulator:
    wing_total: int = 0
    wing_yes_avail: int = 0
    wing_dual_avail: int = 0
    depth_ratios: List[float] = None  # type: ignore[assignment]
    comp_spreads: List[float] = None  # type: ignore[assignment]
    paired_ticks: int = 0
    inverted_cross: int = 0

    def __post_init__(self) -> None:
        self.depth_ratios = []
        self.comp_spreads = []


def _select_causal_pair(
    latest_yes: Optional[MarketBookRecordEnvelope],
    latest_no: Optional[MarketBookRecordEnvelope],
    as_of: datetime,
    cfg: BookWalkCalibrationConfig,
) -> Tuple[Optional[MarketBookRecordEnvelope], Optional[MarketBookRecordEnvelope], bool]:
    y = latest_yes if (latest_yes and (as_of - latest_yes.payload.recv_ts_utc).total_seconds() <= cfg.max_book_staleness_sec) else None
    n = latest_no if (latest_no and (as_of - latest_no.payload.recv_ts_utc).total_seconds() <= cfg.max_book_staleness_sec) else None
    synced = False
    if y is not None and n is not None:
        skew = abs((y.payload.recv_ts_utc - n.payload.recv_ts_utc).total_seconds())
        if skew > cfg.pair_max_skew_sec:
            if y.payload.recv_ts_utc >= n.payload.recv_ts_utc:
                n = None
            else:
                y = None
        else:
            synced = True
    return y, n, synced


def _record_tick_metrics(
    acc: _MetricAccumulator,
    y_env: Optional[MarketBookRecordEnvelope],
    n_env: Optional[MarketBookRecordEnvelope],
    synced: bool,
    vy: MergedYesAskView,
    vd: MergedYesAskView,
    cfg: BookWalkCalibrationConfig,
) -> None:
    y_ok = (not vy.inverted_cross) and (vy.ask_book is not None)
    d_ok = (not vd.inverted_cross) and (vd.ask_book is not None)
    n_snap = n_env.payload if n_env is not None else None
    y_snap = y_env.payload if y_env is not None else None
    if synced:
        acc.paired_ticks += 1
        if vd.inversion_reason == "CROSS_VIEW_INVERTED_SPREAD":
            acc.inverted_cross += 1
        if y_snap and y_snap.ask_book and n_snap and n_snap.bid_book:
            acc.comp_spreads.append(float(y_snap.ask_book.levels[0][0]) + float(n_snap.bid_book.levels[0][0]) - 1.0)
    ref_p = vd.ask_book.levels[0][0] if vd.ask_book else ((1.0 - n_snap.best_bid) if (n_snap and n_snap.best_bid) else None)
    is_wing = (y_snap is not None and y_snap.single_side == "bid_only") or (
        ref_p is not None and cfg.wing_prob_low <= ref_p <= cfg.wing_prob_high
    )
    if is_wing:
        acc.wing_total += 1
        acc.wing_yes_avail += int(y_ok)
        acc.wing_dual_avail += int(d_ok)
    if y_ok and d_ok and vy.ask_book and vd.ask_book:
        dy = sum(sz for _, sz in vy.ask_book.levels)
        dd = sum(sz for _, sz in vd.ask_book.levels)
        if dy > 0.0:
            acc.depth_ratios.append(dd / dy)


def _walk_track_slices(
    acc: _TrackAccumulator,
    matcher: ReplayMatcher,
    view: MergedYesAskView,
    *,
    sid: str,
    mkey: MarketKey,
    y_env: Optional[MarketBookRecordEnvelope],
    n_env: Optional[MarketBookRecordEnvelope],
    as_of: datetime,
    window: Sequence[MarketBookRecordEnvelope],
    cfg: BookWalkCalibrationConfig,
) -> None:
    if view.inverted_cross or view.ask_book is None:
        return
    station_id, target_date, bin_label, market_id = mkey
    best_ask = Decimal(str(view.ask_book.levels[0][0]))
    include_no = acc.track == "DUAL_MERGED"
    yes_tok = y_env.payload.token_id if y_env is not None else f"missing-yes-{market_id}"
    yes_seq = y_env.seq_id if y_env is not None else (n_env.seq_id if n_env is not None else 0)
    no_tok = n_env.payload.token_id if (include_no and n_env is not None) else None
    no_seq = n_env.seq_id if (include_no and n_env is not None) else None
    for d_usd in cfg.slice_notional_grid_usd:
        plan = plan_slice(
            d_usd, view, 1.0, 0.0, cfg.phi_policy,
            min_order_size_shares=matcher.config.min_order_size_shares,
            min_notional_usd=matcher.config.min_notional_usd,
        )
        if not plan.should_submit:
            rk = plan.abort_reason or "ABORT"
            acc.aborts[rk] = acc.aborts.get(rk, 0) + 1
            continue
        ctx = OrderExecutionContext(
            decision_id=f"s202-{acc.track}-{sid}-{yes_seq}-{d_usd}",
            session_id=sid, station_id=station_id, market_id=market_id,
            yes_token_id=yes_tok, model_hash="s202-calib", config_hash="s202-calib",
            decision_ts_utc=as_of, decision_best_ask=best_ask, submit_ts_utc=as_of,
            decision_seq_id=yes_seq, include_no_side=include_no,
            no_token_id=no_tok, no_decision_seq_id=no_seq,
        )
        res = matcher.match_order(context=ctx, plan=plan, recorded_envelopes=window)
        acc.statuses[res.terminal_status] = acc.statuses.get(res.terminal_status, 0) + 1
        _append_fill_if_valid(acc, res, d_usd=float(d_usd), mkey=mkey, sid=sid, as_of=as_of)


def _append_fill_if_valid(
    acc: _TrackAccumulator,
    res: ExecutionAttemptLog,
    *,
    d_usd: float,
    mkey: MarketKey,
    sid: str,
    as_of: datetime,
) -> None:
    if res.terminal_status not in ("FILLED", "PARTIAL"):
        return
    if res.slippage_vs_best_ask is None or res.actual_avg_fill_price is None:
        return
    _, target_date, bin_label, market_id = mkey
    acc.samples.append(
        SliceFillSample(
            track=acc.track, session_id=sid, station_id=res.station_id,
            target_date=target_date, bin_label=bin_label, market_id=market_id,
            decision_ts_utc=as_of.isoformat(), slice_usd=d_usd,
            decision_best_ask=float(res.decision_best_ask),
            actual_avg_fill_price=float(res.actual_avg_fill_price),
            slippage_vs_best_ask=float(res.slippage_vs_best_ask),
            fill_rate=float(res.fill_rate), terminal_status=res.terminal_status,
        )
    )


def _coalesce_tick_burst(
    mk_envs: Sequence[MarketBookRecordEnvelope],
    start_idx: int,
    latest_yes: Optional[MarketBookRecordEnvelope],
    latest_no: Optional[MarketBookRecordEnvelope],
    burst_window_sec: float = 0.1,
) -> Tuple[int, Optional[MarketBookRecordEnvelope], Optional[MarketBookRecordEnvelope], datetime]:
    base_ts = mk_envs[start_idx].payload.recv_ts_utc
    idx = start_idx
    as_of = base_ts
    while idx < len(mk_envs):
        env = mk_envs[idx]
        if (env.payload.recv_ts_utc - base_ts).total_seconds() > burst_window_sec:
            break
        if not env.gap_detected:
            if env.payload.outcome == "YES":
                latest_yes = env
            else:
                latest_no = env
            as_of = env.payload.recv_ts_utc
        idx += 1
    return idx - 1, latest_yes, latest_no, as_of


def _simulate_market_stream(
    sid: str,
    mkey: MarketKey,
    mk_envs: Sequence[MarketBookRecordEnvelope],
    matcher: ReplayMatcher,
    cfg: BookWalkCalibrationConfig,
    yes_acc: _TrackAccumulator,
    dual_acc: _TrackAccumulator,
    metrics: _MetricAccumulator,
) -> None:
    ts_list = [e.payload.recv_ts_utc for e in mk_envs]
    horizon_sec = matcher.config.max_silent_gap_sec + 10.0
    latest_yes: Optional[MarketBookRecordEnvelope] = None
    latest_no: Optional[MarketBookRecordEnvelope] = None
    last_sample: Optional[datetime] = None
    idx = 0
    while idx < len(mk_envs):
        env = mk_envs[idx]
        if env.gap_detected:
            idx += 1
            continue
        if last_sample is not None and (env.payload.recv_ts_utc - last_sample).total_seconds() < cfg.sample_cadence_sec:
            if env.payload.outcome == "YES":
                latest_yes = env
            else:
                latest_no = env
            idx += 1
            continue
        end_burst, latest_yes, latest_no, as_of = _coalesce_tick_burst(mk_envs, idx, latest_yes, latest_no)
        last_sample = as_of
        y_env, n_env, synced = _select_causal_pair(latest_yes, latest_no, as_of, cfg)
        if y_env is not None or n_env is not None:
            vy = build_merged_yes_ask_view(y_env.payload if y_env else None, None, include_no_side=False)
            vd = build_merged_yes_ask_view(y_env.payload if y_env else None, n_env.payload if n_env else None, include_no_side=True)
            _record_tick_metrics(metrics, y_env, n_env, synced, vy, vd, cfg)
            end_idx = bisect_right(ts_list, datetime.fromtimestamp(as_of.timestamp() + horizon_sec, tz=as_of.tzinfo))
            window = mk_envs[end_burst + 1 : end_idx]
            _walk_track_slices(yes_acc, matcher, vy, sid=sid, mkey=mkey, y_env=y_env, n_env=None, as_of=as_of, window=window, cfg=cfg)
            _walk_track_slices(dual_acc, matcher, vd, sid=sid, mkey=mkey, y_env=y_env, n_env=n_env, as_of=as_of, window=window, cfg=cfg)
        idx = end_burst + 1


def _summarize_track(acc: _TrackAccumulator) -> TrackWalkSummary:
    vals = sorted(s.slippage_vs_best_ask for s in acc.samples)
    med, p25, p75, p90 = _quantiles(vals)
    by_st: Dict[str, List[float]] = {}
    by_sl: Dict[str, List[float]] = {}
    for s in acc.samples:
        by_st.setdefault(s.station_id, []).append(s.slippage_vs_best_ask)
        by_sl.setdefault(f"{s.slice_usd:.2f}", []).append(s.slippage_vs_best_ask)
    stride = max(1, len(acc.samples) // 10) if acc.samples else 1
    sampled = tuple(acc.samples[::stride][:10])
    return TrackWalkSummary(
        track=acc.track, valid_fill_count=len(acc.samples),
        filled_count=acc.statuses.get("FILLED", 0),
        partial_count=acc.statuses.get("PARTIAL", 0),
        status_counts=dict(sorted(acc.statuses.items())),
        plan_abort_counts=dict(sorted(acc.aborts.items())),
        stations_covered=tuple(sorted(by_st.keys())),
        friction_median=med, friction_mean=(float(statistics.mean(vals)) if vals else None),
        friction_p25=p25, friction_p75=p75, friction_p90=p90,
        per_station_median={k: float(statistics.median(v)) for k, v in sorted(by_st.items())},
        per_station_count={k: len(v) for k, v in sorted(by_st.items())},
        per_slice_median={k: float(statistics.median(v)) for k, v in sorted(by_sl.items(), key=lambda kv: float(kv[0]))},
        sample_fills=sampled,
    )


def _build_policy_draft(
    yes_sum: TrackWalkSummary, dual_sum: TrackWalkSummary, cfg: BookWalkCalibrationConfig
) -> PolicyDraftSummary:
    rec_track: TrackName = "DUAL_MERGED" if cfg.enable_cross_side_split_routing else "YES_ONLY"
    rec_val = dual_sum.friction_median if rec_track == "DUAL_MERGED" else yes_sum.friction_median
    val_str = f"{rec_val:.6f}" if rec_val is not None else "None"
    return PolicyDraftSummary(
        recommended_track=rec_track, recommended_friction_median=rec_val,
        yes_only_friction_median=yes_sum.friction_median,
        dual_merged_friction_median=dual_sum.friction_median,
        suggested_new_policy_version="p6-s202-v1.0",
        draft_rationale=(
            f"S2-02 D-A1 empirical P18 book-walk calibration on 0.01-era P13 corpus "
            f"({yes_sum.valid_fill_count} YES_ONLY fills / {len(yes_sum.stations_covered)} stations): "
            f"enable_cross_side_split_routing=False -> YES_ONLY median={val_str} per D-6 §9.2."
        ),
        ledger_write_performed=False,
        signoff_status="DRAFT_ONLY_NO_SIGNOFF_EXECUTED",
    )


def _assemble_report(
    corpus: CorpusCoverageSummary,
    cfg: BookWalkCalibrationConfig,
    yes_sum: TrackWalkSummary,
    dual_sum: TrackWalkSummary,
    metrics: _MetricAccumulator,
) -> DualTrackCalibrationReport:
    w_tot = metrics.wing_total
    w_y_pct = (100.0 * metrics.wing_yes_avail / w_tot) if w_tot else 0.0
    w_d_pct = (100.0 * metrics.wing_dual_avail / w_tot) if w_tot else 0.0
    depth_med = float(statistics.median(metrics.depth_ratios)) if metrics.depth_ratios else None
    comp_sorted = sorted(metrics.comp_spreads)
    c_med, _, _, c_p90 = _quantiles(comp_sorted)
    c_p10 = float(comp_sorted[int(0.1 * len(comp_sorted))]) if comp_sorted else None
    inv_rate = (100.0 * metrics.inverted_cross / metrics.paired_ticks) if metrics.paired_ticks else 0.0
    v_ge_200 = yes_sum.valid_fill_count >= MIN_S202_VALID_SLICES and dual_sum.valid_fill_count >= MIN_S202_VALID_SLICES
    s_ge_4 = len(yes_sum.stations_covered) >= MIN_S202_STATIONS and len(dual_sum.stations_covered) >= MIN_S202_STATIONS
    span_ok = corpus.campaign_span_hours >= MIN_S202_HOURS
    net_ok = corpus.net_recorded_hours >= MIN_S202_HOURS
    gate_ok = bool(corpus.fee_era_001_only and corpus.corrupt_lines == 0 and v_ge_200 and s_ge_4 and span_ok and net_ok)
    return DualTrackCalibrationReport(
        corpus=corpus,
        config_summary={
            "slice_notional_grid_usd": [str(x) for x in cfg.slice_notional_grid_usd],
            "wing_prob_band": [cfg.wing_prob_low, cfg.wing_prob_high],
            "pair_max_skew_sec": cfg.pair_max_skew_sec, "max_book_staleness_sec": cfg.max_book_staleness_sec,
            "latency_ms": cfg.latency_ms, "max_silent_gap_sec": cfg.heartbeat_timeout_sec + cfg.rest_fallback_interval_sec,
            "sample_cadence_sec": cfg.sample_cadence_sec, "rho_0": str(cfg.phi_policy.rho_0),
        },
        yes_only=yes_sum, dual_merged=dual_sum, wing_total_ticks=w_tot,
        wing_yes_ask_availability_pct=round(w_y_pct, 4),
        wing_dual_merged_availability_pct=round(w_d_pct, 4),
        wing_availability_abs_gain_pct=round(w_d_pct - w_y_pct, 4),
        qualified_depth_gain_median_ratio=round(depth_med, 6) if depth_med is not None else None,
        complement_spread_count=len(comp_sorted),
        complement_spread_p10=c_p10, complement_spread_p50=c_med, complement_spread_p90=c_p90,
        inverted_cross_count=metrics.inverted_cross, inverted_cross_rate_pct=round(inv_rate, 6),
        valid_slices_ge_200=v_ge_200, stations_ge_4=s_ge_4, span_ge_72h=span_ok,
        net_recorded_ge_72h=net_ok, gate_passed=gate_ok,
        policy_draft=_build_policy_draft(yes_sum, dual_sum, cfg),
    )


def run_p13_book_walk_sessions(
    sessions: Sequence[Tuple[str, Sequence[MarketBookRecordEnvelope]]],
    corpus: CorpusCoverageSummary,
    config: Optional[BookWalkCalibrationConfig] = None,
) -> DualTrackCalibrationReport:
    """Run deterministic `P18` dual-track book-walking calibration across loaded P13 sessions."""
    cfg = config or BookWalkCalibrationConfig()
    matcher = ReplayMatcher(build_execution_config(cfg))
    yes_acc = _TrackAccumulator.create("YES_ONLY")
    dual_acc = _TrackAccumulator.create("DUAL_MERGED")
    metrics = _MetricAccumulator()
    for sid, envs in sessions:
        by_mkt: Dict[MarketKey, List[MarketBookRecordEnvelope]] = {}
        for e in envs:
            k: MarketKey = (e.station_id, e.target_date, e.bin_label, e.payload.market_id)
            by_mkt.setdefault(k, []).append(e)
        for mkey in sorted(by_mkt.keys()):
            mk_envs = sorted(by_mkt[mkey], key=lambda x: (x.payload.recv_ts_utc, x.seq_id))
            _simulate_market_stream(sid, mkey, mk_envs, matcher, cfg, yes_acc, dual_acc, metrics)
    return _assemble_report(corpus, cfg, _summarize_track(yes_acc), _summarize_track(dual_acc), metrics)


def run_s202_calibration(
    output_root: Path = Path("data/market_recordings"),
    *,
    config: Optional[BookWalkCalibrationConfig] = None,
    verify_sha256: bool = True,
) -> DualTrackCalibrationReport:
    """Load P13 sessions read-only from `output_root` and execute `S2-02` dual-track calibration."""
    sessions, corpus = load_all_p13_sessions(output_root, verify_sha256=verify_sha256)
    return run_p13_book_walk_sessions(sessions, corpus, config=config)


def _track_to_dict(t: TrackWalkSummary) -> Dict[str, Any]:
    return {
        "track": t.track, "valid_fill_count": t.valid_fill_count, "filled_count": t.filled_count,
        "partial_count": t.partial_count, "status_counts": t.status_counts,
        "plan_abort_counts": t.plan_abort_counts, "stations_covered": list(t.stations_covered),
        "friction_median": t.friction_median, "friction_mean": t.friction_mean,
        "friction_p25": t.friction_p25, "friction_p75": t.friction_p75, "friction_p90": t.friction_p90,
        "per_station_median": t.per_station_median, "per_station_count": t.per_station_count,
        "per_slice_median": t.per_slice_median,
        "sample_fills": [vars(s) for s in t.sample_fills],
    }


def _report_to_dict(r: DualTrackCalibrationReport) -> Dict[str, Any]:
    return {
        "corpus": vars(r.corpus), "config_summary": r.config_summary,
        "yes_only": _track_to_dict(r.yes_only), "dual_merged": _track_to_dict(r.dual_merged),
        "wing_total_ticks": r.wing_total_ticks,
        "wing_yes_ask_availability_pct": r.wing_yes_ask_availability_pct,
        "wing_dual_merged_availability_pct": r.wing_dual_merged_availability_pct,
        "wing_availability_abs_gain_pct": r.wing_availability_abs_gain_pct,
        "qualified_depth_gain_median_ratio": r.qualified_depth_gain_median_ratio,
        "complement_spread_count": r.complement_spread_count, "complement_spread_p10": r.complement_spread_p10,
        "complement_spread_p50": r.complement_spread_p50, "complement_spread_p90": r.complement_spread_p90,
        "inverted_cross_count": r.inverted_cross_count, "inverted_cross_rate_pct": r.inverted_cross_rate_pct,
        "gate_checks": {
            "valid_slices_ge_200": r.valid_slices_ge_200, "stations_ge_4": r.stations_ge_4,
            "span_ge_72h": r.span_ge_72h, "net_recorded_ge_72h": r.net_recorded_ge_72h,
            "gate_passed": r.gate_passed,
        },
        "policy_draft": vars(r.policy_draft),
    }


def _render_report_markdown(r: DualTrackCalibrationReport) -> str:
    fmt = lambda v: f"{v:.6f}" if v is not None else "None"
    lines = [
        "# S2-02 (D-A1) Dual-Track P13 Book-Walking Calibration Report",
        f"- Corpus: sessions={r.corpus.session_count}, files={r.corpus.files_scanned}, total_frames={r.corpus.total_frames}, clean={r.corpus.clean_frames}, corrupt={r.corpus.corrupt_lines}, fee_rates={list(r.corpus.fee_rates_seen)}, span={r.corpus.campaign_span_hours:.2f}h, net={r.corpus.net_recorded_hours:.2f}h",
        f"- Gate (§8 L132): slices>=200={r.valid_slices_ge_200}, stations>=4={r.stations_ge_4}, span>=72h={r.span_ge_72h}, net>=72h={r.net_recorded_ge_72h} => gate_passed={r.gate_passed}",
        f"- YES_ONLY: valid_fills={r.yes_only.valid_fill_count} (FILLED={r.yes_only.filled_count}, PARTIAL={r.yes_only.partial_count}), stations={list(r.yes_only.stations_covered)}, median={fmt(r.yes_only.friction_median)}, p25={fmt(r.yes_only.friction_p25)}, p75={fmt(r.yes_only.friction_p75)}, p90={fmt(r.yes_only.friction_p90)}",
        f"- DUAL_MERGED: valid_fills={r.dual_merged.valid_fill_count} (FILLED={r.dual_merged.filled_count}, PARTIAL={r.dual_merged.partial_count}), stations={list(r.dual_merged.stations_covered)}, median={fmt(r.dual_merged.friction_median)}, p25={fmt(r.dual_merged.friction_p25)}, p75={fmt(r.dual_merged.friction_p75)}, p90={fmt(r.dual_merged.friction_p90)}",
        f"- §9.1 Dual Metrics: wing_ticks={r.wing_total_ticks}, wing_yes_avail={r.wing_yes_ask_availability_pct:.2f}%, wing_dual_avail={r.wing_dual_merged_availability_pct:.2f}%, gain={r.wing_availability_abs_gain_pct:+.2f}pp, depth_gain_med_ratio={r.qualified_depth_gain_median_ratio}, complement(p10/p50/p90)={fmt(r.complement_spread_p10)}/{fmt(r.complement_spread_p50)}/{fmt(r.complement_spread_p90)}, inverted_cross={r.inverted_cross_count} ({r.inverted_cross_rate_pct:.4f}%)",
        f"- Per-Station YES_ONLY: {r.yes_only.per_station_median} | counts={r.yes_only.per_station_count}",
        f"- Per-Station DUAL_MERGED: {r.dual_merged.per_station_median} | counts={r.dual_merged.per_station_count}",
        f"- Per-Slice YES_ONLY: {r.yes_only.per_slice_median}",
        f"- Per-Slice DUAL_MERGED: {r.dual_merged.per_slice_median}",
        f"- Draft (§9.2): track={r.policy_draft.recommended_track}, friction_median={fmt(r.policy_draft.recommended_friction_median)}, version={r.policy_draft.suggested_new_policy_version}, ledger_written={r.policy_draft.ledger_write_performed}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    rep = run_s202_calibration(verify_sha256=True)
    print(rep.to_markdown())
    print("\n===JSON_PAYLOAD===")
    print(json.dumps(rep.to_dict(), indent=2, ensure_ascii=False))
