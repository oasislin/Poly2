"""M8 (`S3-16`) Read-Only ECE Calibration Evaluator (`P5/P17 x P9` + Order-Flow Weighted ECE).

Strictly read-only over `data/audit_logs/` and `data/live_p5/`:
- Six adjudicated configuration defaults + programmatic `AUTO_BINNING_UPGRADE` (`>= 200` settled markets -> 20 bins).
- Permanent dual weighting (`sample_weighted_ece` work metric & `inverse_variance_weighted_ece` light input).
- Formula-anchored thresholds tied to `(sigma_delta_frozen, k0_threshold_coef)` and zoned decision semantics.
- Order-flow-weighted ECE over `ORDERED` `P1` decisions for `GATE-LIVE` relevance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple
import numpy as np

from src.audit.p10_reader import P10Query, query_p10_session_view, read_verified_jsonl_file
from src.audit.p19_events import ExecutionMode
from src.prediction.forecast_distribution_engine import ForecastDistributionSnapshotV11
from src.prediction.live_p5_producer import deserialize_p5_jsonl_record, load_p5_jsonl_snapshots
from src.utils.causal_utils import ensure_utc_datetime, parse_utc_timestamp

SnapshotSelectionMode = Literal["latest_pre_close", "all_pre_close"]
JudgmentZone = Literal["INSUFFICIENT_CORPUS", "RAMP_ZONE", "MATURE_ZONE"]
_JoinKey = Tuple[str, str, str]

TRANSITIONAL_PROB_BINS = 10
UPGRADED_PROB_BINS = 20
AUTO_BINNING_UPGRADE_MARKETS = 200
ARITHMETIC_MIN_MARKETS_FOR_20_BINS = 55  # ceil(20 * 30 / 11) = 55 station-days
DEFAULT_MATURE_ZONE_MARKETS = 300


@dataclass(frozen=True)
class EceAnchorSpec:
    """Formula-derived ECE light thresholds tied to `(sigma_delta_frozen, k0_threshold_coef)`."""

    sigma_delta_frozen: float
    k0_threshold_coef: float
    yellow_threshold: float
    red_threshold: float
    gate_live_max: float = 0.025
    formula_provenance: str = "YELLOW=1.0*sigma_delta_frozen; RED=k0*sigma_delta_frozen; GATE_LIVE=0.025"


def derive_ece_anchors_from_policy(
    *,
    sigma_delta_frozen: float = 0.020,
    k0_threshold_coef: float = 2.0,
    gate_live_max: float = 0.025,
) -> EceAnchorSpec:
    """Derive YELLOW (`1.0 * sigma_delta`) and RED (`k0 * sigma_delta`) anchors cleanly from `P6` scale."""
    sd = float(sigma_delta_frozen)
    k0 = float(k0_threshold_coef)
    if sd <= 0.0 or k0 <= 1.0:
        raise ValueError(f"Expected sigma_delta_frozen > 0 and k0 > 1.0, got sd={sd}, k0={k0}")
    return EceAnchorSpec(
        sigma_delta_frozen=sd,
        k0_threshold_coef=k0,
        yellow_threshold=1.0 * sd,
        red_threshold=k0 * sd,
        gate_live_max=float(gate_live_max),
    )


@dataclass(frozen=True)
class BinningUpgradeEvent:
    """Audit event emitted when `n_settled_markets >= auto_upgrade_markets` switches 10 -> 20 bins."""

    triggered: bool
    from_bins: int
    to_bins: int
    effective_bins: int
    threshold_markets: int
    arithmetic_floor_markets: int
    observed_markets: int


@dataclass(frozen=True)
class EceEvaluationConfig:
    """Configurable S3-16 formal parameters (constants logged with lifecycle paths, zero magic locks)."""

    num_prob_bins: int = TRANSITIONAL_PROB_BINS
    upgraded_prob_bins: int = UPGRADED_PROB_BINS
    auto_upgrade_markets: int = AUTO_BINNING_UPGRADE_MARKETS
    enable_auto_binning_upgrade: bool = True
    min_bin_samples: int = 30
    min_settled_markets: int = 30
    mature_review_markets: int = 60
    mature_zone_markets: int = DEFAULT_MATURE_ZONE_MARKETS
    snapshot_mode: SnapshotSelectionMode = "latest_pre_close"
    is_pilot: bool = True
    sigma_delta_frozen: float = 0.020
    k0_threshold_coef: float = 2.0
    gate_live_max: float = 0.025
    bootstrap_resamples: int = 400
    bootstrap_seed: int = 20261127
    green_threshold: Optional[float] = None
    red_threshold: Optional[float] = None

    def resolved_anchors(self) -> EceAnchorSpec:
        spec = derive_ece_anchors_from_policy(
            sigma_delta_frozen=self.sigma_delta_frozen,
            k0_threshold_coef=self.k0_threshold_coef,
            gate_live_max=self.gate_live_max,
        )
        y = float(self.green_threshold) if self.green_threshold is not None else spec.yellow_threshold
        r = float(self.red_threshold) if self.red_threshold is not None else spec.red_threshold
        return EceAnchorSpec(self.sigma_delta_frozen, self.k0_threshold_coef, y, r, self.gate_live_max)


@dataclass(frozen=True)
class ForecastBinObservation:
    """Single `(forecast_id, bin_id)` binary outcome paired with `P9` settlement truth."""

    forecast_id: str
    station_id: str
    target_date: str
    target_type: str
    bin_id: str
    label: str
    p_model: float
    hit: float
    settled_temp_f_int: Optional[int]
    issue_ts_utc: datetime
    settle_close_utc: datetime


@dataclass(frozen=True)
class EceBinSummary:
    """Aggregated calibration metrics for one probability stratum `[lower_p, upper_p)`."""

    stratum_id: int
    lower_p: float
    upper_p: float
    range_label: str
    count_n: int
    mean_p_model: Optional[float]
    empirical_freq: Optional[float]
    abs_bias: Optional[float]
    wilson_ci_low: Optional[float]
    wilson_ci_high: Optional[float]
    warning_low_n: bool


@dataclass(frozen=True)
class StationEceSummary:
    """Per-station ECE, Brier score, and settled sample counts."""

    station_id: str
    n_settled_markets: int
    n_bin_outcomes: int
    sample_weighted_ece: float
    inverse_variance_weighted_ece: float
    equal_bin_ece: float
    brier_score: float


@dataclass(frozen=True)
class ContractBinDiagnostic:
    """Secondary diagnostic breakdown grouped by normalized contract `bin_id`."""

    bin_id: str
    count_n: int
    mean_p_model: float
    empirical_freq: float
    abs_bias: float


@dataclass(frozen=True)
class EceEvaluationReport:
    """Complete read-only `S3-16` calibration report with dual weighting, zones & order-flow ECE."""

    is_pilot: bool
    status: Literal["OK", "PENDING_SETTLEMENT_DATA", "DEGRADED_CORRUPT_LINES"]
    corpus_source: str
    snapshot_mode: SnapshotSelectionMode
    num_prob_bins: int
    binning_upgrade: BinningUpgradeEvent
    judgment_zone: JudgmentZone
    anchors: EceAnchorSpec
    n_settled_markets: int
    n_bin_outcomes: int
    n_unsettled_forecasts: int
    n_post_close_excluded: int
    corrupt_lines_count: int
    sample_weighted_ece: Optional[float]
    inverse_variance_weighted_ece: Optional[float]
    equal_bin_ece: Optional[float]
    brier_score: Optional[float]
    noise_floor_ece: Optional[float]
    excess_ece_debiased: Optional[float]
    bootstrap_ci_low: Optional[float]
    bootstrap_ci_high: Optional[float]
    order_flow_weighted_ece: Optional[float]
    order_flow_matched_count: int
    order_flow_total_usd: float
    zoned_light_verdict: Literal["GREEN", "YELLOW", "RED", "PENDING"]
    zoned_verdict_reason: str
    insufficient_sample: bool
    prob_bins: Tuple[EceBinSummary, ...]
    reliability_curve: Tuple[Tuple[float, float, int], ...]
    per_station_breakdown: Tuple[StationEceSummary, ...]
    contract_bin_diagnostics: Tuple[ContractBinDiagnostic, ...]


def compute_wilson_ci(hits: float, n: int, *, z: float = 1.96) -> Tuple[float, float]:
    """Return `[lower, upper]` Wilson score confidence interval for binomial proportion."""
    if n <= 0:
        return 0.0, 1.0
    p_hat = min(1.0, max(0.0, float(hits) / float(n)))
    z2 = float(z) * float(z)
    denom = 1.0 + z2 / n
    center = (p_hat + z2 / (2.0 * n)) / denom
    half = float(z) * math.sqrt((p_hat * (1.0 - p_hat) / n) + (z2 / (4.0 * n * n))) / denom
    return max(0.0, center - half), min(1.0, center + half)


def _bin_hit_matches_p9(
    lower_int_f: Optional[int], upper_int_f: Optional[int], bin_id: str, p9_row: Mapping[str, Any]
) -> float:
    t_int = p9_row.get("settled_temp_f_int")
    if t_int is not None:
        val = int(t_int)
        lo_ok = lower_int_f is None or val >= int(lower_int_f)
        hi_ok = upper_int_f is None or val <= int(upper_int_f)
        return 1.0 if (lo_ok and hi_ok) else 0.0
    win_id = p9_row.get("winning_bin_id")
    if win_id is not None:
        return 1.0 if str(bin_id) == str(win_id) else 0.0
    raise ValueError("P9 record provides neither settled_temp_f_int nor winning_bin_id")


def _select_snapshots_for_eval(
    forecasts: Sequence[ForecastDistributionSnapshotV11],
    p9_by_key: Mapping[_JoinKey, Mapping[str, Any]],
    *,
    snapshot_mode: SnapshotSelectionMode,
) -> Tuple[List[ForecastDistributionSnapshotV11], int, int]:
    pre_close: Dict[_JoinKey, List[ForecastDistributionSnapshotV11]] = {}
    unsettled, post_close_excluded = 0, 0
    for fc in forecasts:
        key: _JoinKey = (fc.station_id, fc.target_date.isoformat(), fc.target_type)
        if key not in p9_by_key:
            unsettled += 1
            continue
        p9_close = parse_utc_timestamp(str(p9_by_key[key]["settle_close_utc"]), field_name="p9.settle_close_utc")
        issue_ts = ensure_utc_datetime(fc.issue_ts_utc, field_name="p5.issue_ts_utc")
        if issue_ts > p9_close:
            post_close_excluded += 1
            continue
        pre_close.setdefault(key, []).append(fc)
    chosen: List[ForecastDistributionSnapshotV11] = []
    for key in sorted(pre_close):
        items = sorted(pre_close[key], key=lambda s: ensure_utc_datetime(s.issue_ts_utc, field_name="p5.issue_ts_utc"))
        chosen.extend([items[-1]] if snapshot_mode == "latest_pre_close" else items)
    return chosen, unsettled, post_close_excluded


def join_forecasts_with_p9_truths(
    forecasts: Sequence[ForecastDistributionSnapshotV11],
    p9_records: Sequence[Mapping[str, Any]],
    *,
    snapshot_mode: SnapshotSelectionMode = "latest_pre_close",
) -> Tuple[Tuple[ForecastBinObservation, ...], int, int, int]:
    """Causally join `P5/P17` snapshots against settled `P9` truths on `(station_id, target_date, target_type)`."""
    p9_by_key: Dict[_JoinKey, Mapping[str, Any]] = {}
    for rec in p9_records:
        p9_by_key[(str(rec["station_id"]).upper(), str(rec["target_date"]), str(rec["target_type"]))] = rec
    chosen, unsettled, post_close = _select_snapshots_for_eval(forecasts, p9_by_key, snapshot_mode=snapshot_mode)
    obs: List[ForecastBinObservation] = []
    for fc in chosen:
        p9 = p9_by_key[(fc.station_id, fc.target_date.isoformat(), fc.target_type)]
        close_ts = parse_utc_timestamp(str(p9["settle_close_utc"]), field_name="p9.settle_close_utc")
        t_int = int(p9["settled_temp_f_int"]) if p9.get("settled_temp_f_int") is not None else None
        fc_obs = [
            ForecastBinObservation(
                forecast_id=fc.forecast_id, station_id=fc.station_id, target_date=fc.target_date.isoformat(),
                target_type=fc.target_type, bin_id=bp.bin_id, label=bp.label, p_model=float(bp.p_model),
                hit=_bin_hit_matches_p9(bp.lower_int_f, bp.upper_int_f, bp.bin_id, p9),
                settled_temp_f_int=t_int, issue_ts_utc=fc.issue_ts_utc, settle_close_utc=close_ts,
            )
            for bp in fc.bin_probs
        ]
        if round(sum(o.hit for o in fc_obs)) != 1:
            raise ValueError(f"Non-unit settlement hit sum across ladder for {fc.forecast_id}")
        obs.extend(fc_obs)
    return tuple(obs), len(chosen), unsettled, post_close


def _bucket_index(p_val: float, num_bins: int) -> int:
    return min(num_bins - 1, max(0, int(math.floor(min(1.0, max(0.0, float(p_val))) * num_bins))))


def _summarize_prob_bins(
    observations: Sequence[ForecastBinObservation], *, num_bins: int, min_bin_samples: int
) -> Tuple[Tuple[EceBinSummary, ...], float, float, float, float, float]:
    buckets: List[List[ForecastBinObservation]] = [[] for _ in range(num_bins)]
    for item in observations:
        buckets[_bucket_index(item.p_model, num_bins)].append(item)
    summaries: List[EceBinSummary] = []
    w_err, iv_num, iv_den, macro_biases, sq_err, nf_sum = 0.0, 0.0, 0.0, [], 0.0, 0.0
    total_n = len(observations)
    for b_idx, rows in enumerate(buckets):
        lo, hi = b_idx / num_bins, (b_idx + 1) / num_bins
        rng_lbl = f"[{lo:.2f}, {hi:.2f}{']' if b_idx == num_bins - 1 else ')'}"
        cnt = len(rows)
        if cnt > 0:
            mean_p, hits = sum(r.p_model for r in rows) / cnt, sum(r.hit for r in rows)
            emp = hits / cnt
            bias = abs(mean_p - emp)
            ci_l, ci_h = compute_wilson_ci(hits, cnt)
            p_clip = min(0.99, max(0.01, mean_p))
            inv_var = float(cnt) / (p_clip * (1.0 - p_clip))
            w_err += cnt * bias
            iv_num += inv_var * bias
            iv_den += inv_var
            macro_biases.append(bias)
            sq_err += sum((r.p_model - r.hit) ** 2 for r in rows)
            nf_sum += cnt * math.sqrt(2.0 * mean_p * max(0.0, 1.0 - mean_p) / (math.pi * cnt))
            summaries.append(EceBinSummary(b_idx + 1, lo, hi, rng_lbl, cnt, mean_p, emp, bias, ci_l, ci_h, cnt < min_bin_samples))
        else:
            summaries.append(EceBinSummary(b_idx + 1, lo, hi, rng_lbl, 0, None, None, None, None, None, False))
    w_ece = w_err / total_n if total_n > 0 else 0.0
    iv_ece = iv_num / iv_den if iv_den > 0.0 else 0.0
    eq_ece = sum(macro_biases) / len(macro_biases) if macro_biases else 0.0
    brier = sq_err / total_n if total_n > 0 else 0.0
    noise_floor = nf_sum / total_n if total_n > 0 else 0.0
    return tuple(summaries), w_ece, iv_ece, eq_ece, brier, noise_floor


def _resolve_binning_upgrade(config: EceEvaluationConfig, n_settled_markets: int) -> BinningUpgradeEvent:
    triggered = bool(config.enable_auto_binning_upgrade and n_settled_markets >= config.auto_upgrade_markets)
    eff = config.upgraded_prob_bins if triggered else config.num_prob_bins
    return BinningUpgradeEvent(
        triggered=triggered,
        from_bins=config.num_prob_bins,
        to_bins=config.upgraded_prob_bins,
        effective_bins=eff,
        threshold_markets=config.auto_upgrade_markets,
        arithmetic_floor_markets=ARITHMETIC_MIN_MARKETS_FOR_20_BINS,
        observed_markets=n_settled_markets,
    )


def _compute_bootstrap_ece_ci(
    observations: Sequence[ForecastBinObservation],
    *,
    num_bins: int,
    resamples: int,
    seed: int,
) -> Tuple[Optional[float], Optional[float]]:
    if not observations or resamples <= 0:
        return None, None
    by_mkt: Dict[_JoinKey, List[ForecastBinObservation]] = {}
    for o in observations:
        by_mkt.setdefault((o.station_id, o.target_date, o.target_type), []).append(o)
    clusters = list(by_mkt.values())
    if len(clusters) < 2:
        return None, None
    rng = np.random.default_rng(seed)
    scores: List[float] = []
    for _ in range(resamples):
        picked = rng.integers(0, len(clusters), size=len(clusters))
        sample_obs = [row for idx in picked for row in clusters[int(idx)]]
        _, w_ece, _, _, _, _ = _summarize_prob_bins(sample_obs, num_bins=num_bins, min_bin_samples=1)
        scores.append(w_ece)
    return float(np.quantile(scores, 0.025)), float(np.quantile(scores, 0.975))


def _resolve_zoned_verdict(
    *,
    n_settled_markets: int,
    config: EceEvaluationConfig,
    anchors: EceAnchorSpec,
    w_ece: Optional[float],
    ci_low: Optional[float],
) -> Tuple[JudgmentZone, Literal["GREEN", "YELLOW", "RED", "PENDING"], str]:
    if n_settled_markets < config.min_settled_markets or w_ece is None:
        return "INSUFFICIENT_CORPUS", "PENDING", f"PENDING_CORPUS_MIN_GATE:{n_settled_markets}<{config.min_settled_markets}"
    if n_settled_markets < config.mature_zone_markets:
        chk = ci_low if ci_low is not None else w_ece
        if chk > anchors.red_threshold:
            return "RAMP_ZONE", "RED", f"RAMP_CI_LOW_GT_RED:{chk:.4f}>{anchors.red_threshold:.4f}"
        if chk > anchors.yellow_threshold:
            return "RAMP_ZONE", "YELLOW", f"RAMP_CI_LOW_GT_YELLOW:{chk:.4f}>{anchors.yellow_threshold:.4f}"
        return "RAMP_ZONE", "GREEN", f"RAMP_CI_WITHIN_ANCHOR:ci_low={chk:.4f}<=yellow={anchors.yellow_threshold:.4f}"
    if w_ece > anchors.red_threshold:
        return "MATURE_ZONE", "RED", f"MATURE_POINT_GT_RED:{w_ece:.4f}>{anchors.red_threshold:.4f}"
    if w_ece > anchors.yellow_threshold:
        return "MATURE_ZONE", "YELLOW", f"MATURE_POINT_YELLOW_BAND:{w_ece:.4f}>{anchors.yellow_threshold:.4f}"
    return "MATURE_ZONE", "GREEN", f"MATURE_POINT_GREEN:{w_ece:.4f}<={anchors.yellow_threshold:.4f}"


def compute_order_flow_weighted_ece(
    observations: Sequence[ForecastBinObservation],
    p1_decisions: Sequence[Mapping[str, Any]],
) -> Tuple[Optional[float], int, float]:
    """Compute ECE weighted by `ORDERED` `P1` `target_slice_usd` across settled `(forecast_id, bin_id)` pairs."""
    weights: Dict[Tuple[str, str], float] = {}
    matched_orders = 0
    for rec in p1_decisions:
        if rec.get("decision_outcome") != "ORDERED":
            continue
        key = (str(rec.get("forecast_id") or ""), str(rec.get("bin_id") or ""))
        w = max(0.0, float(rec.get("target_slice_usd") or 0.0))
        if w > 0.0:
            weights[key] = weights.get(key, 0.0) + w
            matched_orders += 1
    weighted_pairs = [(o, weights[(o.forecast_id, o.bin_id)]) for o in observations if (o.forecast_id, o.bin_id) in weights]
    total_usd = sum(w for _, w in weighted_pairs)
    if total_usd <= 0.0:
        return None, 0, 0.0
    of_ece = sum(w * abs(o.p_model - o.hit) for o, w in weighted_pairs) / total_usd
    return of_ece, matched_orders, total_usd


def _summarize_stations(
    observations: Sequence[ForecastBinObservation], *, effective_bins: int, min_bin_samples: int
) -> Tuple[StationEceSummary, ...]:
    by_st: Dict[str, List[ForecastBinObservation]] = {}
    for item in observations:
        by_st.setdefault(item.station_id, []).append(item)
    out: List[StationEceSummary] = []
    for st in sorted(by_st):
        rows = by_st[st]
        _, w_ece, iv_ece, eq_ece, brier, _ = _summarize_prob_bins(
            rows, num_bins=effective_bins, min_bin_samples=min_bin_samples
        )
        n_mkts = len({(r.station_id, r.target_date, r.target_type) for r in rows})
        out.append(StationEceSummary(st, n_mkts, len(rows), w_ece, iv_ece, eq_ece, brier))
    return tuple(out)


def _summarize_contract_bins(observations: Sequence[ForecastBinObservation]) -> Tuple[ContractBinDiagnostic, ...]:
    by_bin: Dict[str, List[ForecastBinObservation]] = {}
    for item in observations:
        by_bin.setdefault(item.bin_id, []).append(item)
    return tuple(
        ContractBinDiagnostic(
            bid, len(rows), sum(r.p_model for r in rows) / len(rows), sum(r.hit for r in rows) / len(rows),
            abs(sum(r.p_model for r in rows) / len(rows) - sum(r.hit for r in rows) / len(rows)),
        )
        for bid, rows in sorted(by_bin.items())
    )


def evaluate_ece_from_observations(
    observations: Sequence[ForecastBinObservation],
    *,
    config: EceEvaluationConfig,
    corpus_source: str,
    n_settled_markets: int,
    n_unsettled_forecasts: int = 0,
    n_post_close_excluded: int = 0,
    corrupt_lines_count: int = 0,
    p1_decisions: Sequence[Mapping[str, Any]] = (),
) -> EceEvaluationReport:
    """Compute full `S3-16` ECE evaluation report with dual weighting, noise floor, zones & order-flow ECE."""
    upgrade = _resolve_binning_upgrade(config, n_settled_markets)
    eff_bins, anchors = upgrade.effective_bins, config.resolved_anchors()
    bins, w_ece, iv_ece, eq_ece, brier, nf_ece = _summarize_prob_bins(
        observations, num_bins=eff_bins, min_bin_samples=config.min_bin_samples
    )
    has_data = len(observations) > 0
    ci_l, ci_h = _compute_bootstrap_ece_ci(
        observations, num_bins=eff_bins, resamples=config.bootstrap_resamples, seed=config.bootstrap_seed
    ) if has_data else (None, None)
    zone, verdict, reason = _resolve_zoned_verdict(
        n_settled_markets=n_settled_markets, config=config, anchors=anchors,
        w_ece=w_ece if has_data else None, ci_low=ci_l,
    )
    of_ece, of_cnt, of_usd = compute_order_flow_weighted_ece(observations, p1_decisions) if has_data else (None, 0, 0.0)
    curve = tuple((b.mean_p_model, b.empirical_freq, b.count_n) for b in bins if b.count_n > 0 and b.mean_p_model is not None and b.empirical_freq is not None)
    status: Literal["OK", "PENDING_SETTLEMENT_DATA", "DEGRADED_CORRUPT_LINES"] = (
        "DEGRADED_CORRUPT_LINES" if corrupt_lines_count > 0 else ("OK" if has_data else "PENDING_SETTLEMENT_DATA")
    )
    return EceEvaluationReport(
        is_pilot=config.is_pilot, status=status, corpus_source=corpus_source, snapshot_mode=config.snapshot_mode,
        num_prob_bins=eff_bins, binning_upgrade=upgrade, judgment_zone=zone, anchors=anchors,
        n_settled_markets=n_settled_markets, n_bin_outcomes=len(observations),
        n_unsettled_forecasts=n_unsettled_forecasts, n_post_close_excluded=n_post_close_excluded,
        corrupt_lines_count=corrupt_lines_count, sample_weighted_ece=w_ece if has_data else None,
        inverse_variance_weighted_ece=iv_ece if has_data else None, equal_bin_ece=eq_ece if has_data else None,
        brier_score=brier if has_data else None, noise_floor_ece=nf_ece if has_data else None,
        excess_ece_debiased=max(0.0, w_ece - nf_ece) if has_data else None,
        bootstrap_ci_low=ci_l, bootstrap_ci_high=ci_h, order_flow_weighted_ece=of_ece,
        order_flow_matched_count=of_cnt, order_flow_total_usd=of_usd, zoned_light_verdict=verdict,
        zoned_verdict_reason=reason, insufficient_sample=n_settled_markets < config.min_settled_markets,
        prob_bins=bins, reliability_curve=curve,
        per_station_breakdown=_summarize_stations(observations, effective_bins=eff_bins, min_bin_samples=config.min_bin_samples),
        contract_bin_diagnostics=_summarize_contract_bins(observations),
    )


def _load_audit_snapshots_and_p1_readonly(
    audit_root: Path, execution_mode: ExecutionMode
) -> Tuple[Tuple[ForecastDistributionSnapshotV11, ...], Tuple[Dict[str, Any], ...], int]:
    view = query_p10_session_view(audit_root, P10Query(execution_mode=execution_mode))
    by_id: Dict[str, ForecastDistributionSnapshotV11] = {}
    for rec in view.p17_snapshots:
        raw = json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        snap, _ = deserialize_p5_jsonl_record(raw)
        by_id[snap.forecast_id] = snap
    ordered = tuple(sorted(by_id.values(), key=lambda s: (s.issue_ts_utc, s.station_id, s.target_date)))
    return ordered, tuple(dict(r) for r in view.p1_events), len(view.corrupt_lines)


def _load_p9_records_readonly(audit_root: Path, execution_mode: ExecutionMode) -> Tuple[Tuple[Dict[str, Any], ...], int]:
    mode_dir = Path(audit_root) / execution_mode
    if not mode_dir.exists():
        return (), 0
    recs: List[Dict[str, Any]] = []
    corrupt = 0
    for fp in sorted(mode_dir.rglob("p9_settlement_truths.jsonl")):
        res = read_verified_jsonl_file(fp, verify_sha256=True)
        corrupt += len(res.corrupt_lines)
        recs.extend(res.records)
    return tuple(recs), corrupt


def evaluate_ece_from_directories(
    *,
    audit_root: Path,
    live_p5_dir: Optional[Path] = None,
    execution_mode: ExecutionMode = "PAPER",
    config: Optional[EceEvaluationConfig] = None,
) -> Dict[str, EceEvaluationReport]:
    """Read-only dual-track ECE evaluation over `data/audit_logs/` and optional `data/live_p5/`."""
    cfg = config or EceEvaluationConfig()
    p9_recs, p9_corrupt = _load_p9_records_readonly(audit_root, execution_mode)
    p17_snaps, p1_events, p17_corrupt = _load_audit_snapshots_and_p1_readonly(audit_root, execution_mode)
    tracks: Dict[str, Tuple[Tuple[ForecastDistributionSnapshotV11, ...], int]] = {
        "AUDIT_P17_CONSUMED": (p17_snaps, p9_corrupt + p17_corrupt)
    }
    if live_p5_dir is not None and Path(live_p5_dir).exists():
        tracks["LIVE_P5_ALL_SNAPSHOTS"] = (load_p5_jsonl_snapshots(Path(live_p5_dir)), p9_corrupt)
    out: Dict[str, EceEvaluationReport] = {}
    for name, (snaps, c_cnt) in tracks.items():
        obs, n_mkts, n_unset, n_post = join_forecasts_with_p9_truths(snaps, p9_recs, snapshot_mode=cfg.snapshot_mode)
        out[name] = evaluate_ece_from_observations(
            obs, config=cfg, corpus_source=name, n_settled_markets=n_mkts,
            n_unsettled_forecasts=n_unset, n_post_close_excluded=n_post,
            corrupt_lines_count=c_cnt, p1_decisions=p1_events,
        )
    return out


def _render_single_track_section(name: str, rep: EceEvaluationReport) -> List[str]:
    lines = [
        f"## Track: `{name}` (`status={rep.status}`, `zone={rep.judgment_zone}`, `verdict={rep.zoned_light_verdict}`)",
        f"- `settled_markets={rep.n_settled_markets}` | `bin_outcomes={rep.n_bin_outcomes}` | `effective_bins={rep.num_prob_bins}` (`upgrade_triggered={rep.binning_upgrade.triggered}`) | `unsettled={rep.n_unsettled_forecasts}` | `corrupt={rep.corrupt_lines_count}`",
        f"- `sample_weighted_ece={rep.sample_weighted_ece}` | `inverse_variance_weighted_ece={rep.inverse_variance_weighted_ece}` | `noise_floor_ece={rep.noise_floor_ece}` | `excess_ece_debiased={rep.excess_ece_debiased}`",
        f"- `bootstrap_95_ci=[{rep.bootstrap_ci_low}, {rep.bootstrap_ci_high}]` | `order_flow_weighted_ece={rep.order_flow_weighted_ece}` (`orders={rep.order_flow_matched_count}`, `usd={rep.order_flow_total_usd:.2f}`)",
        "",
        "| Stratum | Range | `n` | `mean(p_model)` | `emp_freq` | `abs_bias` | Wilson 95% CI | Flag |",
        "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for b in rep.prob_bins:
        mp = f"{b.mean_p_model:.4f}" if b.mean_p_model is not None else "—"
        ef = f"{b.empirical_freq:.4f}" if b.empirical_freq is not None else "—"
        ab = f"{b.abs_bias:.4f}" if b.abs_bias is not None else "—"
        ci = f"[{b.wilson_ci_low:.3f}, {b.wilson_ci_high:.3f}]" if b.wilson_ci_low is not None and b.wilson_ci_high is not None else "—"
        flag = "WARNING_LOW_N" if b.warning_low_n else ("OK" if b.count_n > 0 else "NO_DATA")
        lines.append(f"| `{b.stratum_id}` | `{b.range_label}` | `{b.count_n}` | `{mp}` | `{ef}` | `{ab}` | `{ci}` | `{flag}` |")
    return lines


def render_ece_pilot_markdown(reports: Mapping[str, EceEvaluationReport], *, stale_trend_summary: str = "") -> str:
    """Render deterministic Markdown report for `docs/audit/` (read-only pilot or evaluation)."""
    is_pilot = any(r.is_pilot for r in reports.values())
    header = "# PILOT_NOT_FOR_THRESHOLD_JUDGMENT — S3-16 ECE Pilot Report" if is_pilot else "# S3-16 ECE Calibration Report"
    lines = [header, "", "> **Read-Only Discipline**: Consumes `data/audit_logs/` & `data/live_p5/` strictly read-only; zero runtime mutations."]
    if is_pilot:
        lines.append("> **Pilot Notice (`PILOT_NOT_FOR_THRESHOLD_JUDGMENT`)**: Mechanical pipeline validation only; formal threshold judgement awaits corpus minimum gate and owner sign-off.")
    if stale_trend_summary:
        lines.extend(["", "## STALE_OR_MISSING_BOTH_LEGS Trend", "", stale_trend_summary])
    for name, rep in reports.items():
        lines.extend(["", *_render_single_track_section(name, rep)])
    return "\n".join(lines) + "\n"
