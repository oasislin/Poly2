"""
W3 Offline Replay and Performance Analysis Engine (Phase 2 Wave 3 / W3-D).
Governed by docs/w3_polymarket_ingestion_preregistration.md Rev.1.1 (Work Order P7-W3-TASK3-AUTH-001).

Implements:
1. D-1: Threshold Sweep Framework (2% to 15% edge replay, generating frequency-expectation curve).
2. D-2: Metric A (Lead-Lag Following: >3pp model jump followed by market mid-price in 1~3 snapshots).
3. D-3: Metric B (Calibration Realization: Model vs Market Brier Score comparison against official settlement).
4. Full integration with B-4 evaluation ledger snapshots and Annex A mandatory disclosure notices.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import numpy as np

logger = logging.getLogger(__name__)

# Statutory Criteria Constants from Rev.1.1
D1_SWEEP_THRESHOLDS = tuple(round(t, 2) for t in np.arange(0.02, 0.151, 0.01))  # 2% to 15%
D2_JUMP_THRESHOLD = 0.03         # D-2: |Delta P_model| > 3 percentage points (0.03)
D2_FOLLOW_MAX_SNAPSHOTS = 3       # D-2: within subsequent 1 to 3 snapshots
MIN_DEPTH_REQUIRED = 10.0         # B-5: size >= 10 contracts


@dataclass(frozen=True)
class ThresholdSweepPoint:
    """Single point on the D-1 frequency-expectation curve."""
    threshold: float
    signal_count: int
    signal_frequency_rate: float
    mean_edge: float
    median_edge: float
    min_edge: float
    max_edge: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LeadLagJumpEvent:
    """A single model probability jump event evaluated for market following."""
    market_slug: str
    token_id: str
    bracket_label: str
    jump_time_iso: str
    jump_delta_model: float
    market_deltas_next: Tuple[float, ...]  # Deltas in subsequent 1..3 snapshots
    is_followed: bool
    follow_lag: Optional[int]              # 1, 2, 3 or None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MetricAResult:
    """D-2 Metric A (Lead-Lag Following) evaluation result."""
    total_jump_events: int
    followed_events: int
    follow_rate: float
    average_lag: Optional[float]
    verdict: str  # "RETAIN_PROBE_LAYER" or "CUT_PROBE_LAYER"
    events: List[LeadLagJumpEvent] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_jump_events": self.total_jump_events,
            "followed_events": self.followed_events,
            "follow_rate": round(self.follow_rate, 4),
            "average_lag": round(self.average_lag, 2) if self.average_lag is not None else None,
            "verdict": self.verdict,
            "events": [e.to_dict() for e in self.events],
        }


@dataclass(frozen=True)
class MetricBResult:
    """D-3 Metric B (Calibration Realization) evaluation result."""
    sample_count: int
    model_brier_score: float
    market_brier_score: float
    brier_skill_score: float
    model_mean_prob: float
    market_mean_prob: float
    realized_hit_rate: float
    verdict: str  # "TRUE_EV_ADVANTAGE" or "RAISE_THRESHOLD_OR_CUT_PROBE"
    limitation_disclosure: str = (
        "Per Annex A Clause 1, market implied probabilities exclude unquoted brackets, "
        "which may slightly compress middle bracket probabilities."
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_count": self.sample_count,
            "model_brier_score": round(self.model_brier_score, 6),
            "market_brier_score": round(self.market_brier_score, 6),
            "brier_skill_score": round(self.brier_skill_score, 6),
            "model_mean_prob": round(self.model_mean_prob, 6),
            "market_mean_prob": round(self.market_mean_prob, 6),
            "realized_hit_rate": round(self.realized_hit_rate, 6),
            "verdict": self.verdict,
            "limitation_disclosure": self.limitation_disclosure,
        }


@dataclass(frozen=True)
class OfflineReplaySummary:
    """Consolidated offline analysis output across D-1, D-2, and D-3."""
    analysis_id: str
    timestamp_iso: str
    total_snapshots_analyzed: int
    total_brackets_analyzed: int
    d1_threshold_curve: List[ThresholdSweepPoint]
    d2_metric_a: MetricAResult
    d3_metric_b: Optional[MetricBResult]
    divergence_count: int
    input_suspect_count: int
    quarantined_signal_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "timestamp_iso": self.timestamp_iso,
            "total_snapshots_analyzed": self.total_snapshots_analyzed,
            "total_brackets_analyzed": self.total_brackets_analyzed,
            "d1_threshold_curve": [p.to_dict() for p in self.d1_threshold_curve],
            "d2_metric_a": self.d2_metric_a.to_dict(),
            "d3_metric_b": self.d3_metric_b.to_dict() if self.d3_metric_b else None,
            "divergence_count": self.divergence_count,
            "input_suspect_count": self.input_suspect_count,
            "quarantined_signal_count": self.quarantined_signal_count,
        }


class W3OfflineReplayAnalyzer:
    """
    Offline analysis engine executing criteria D-1, D-2, and D-3 on B-4 ledgers.
    """

    def __init__(self, sweep_thresholds: Optional[Sequence[float]] = None):
        self.sweep_thresholds = tuple(sweep_thresholds or D1_SWEEP_THRESHOLDS)

    def sweep_thresholds_d1(
        self,
        snapshots: List[Dict[str, Any]],
    ) -> List[ThresholdSweepPoint]:
        """
        D-1: Replay B-4 full ledger records against thresholds 2% to 15%.
        Produces frequency-expectation curve points.
        """
        all_records = []
        for snap in snapshots:
            # Skip if snapshot is quarantined under INPUT_SUSPECT
            if snap.get("summary", {}).get("is_input_suspect", False):
                continue
            for rec in snap.get("records", []):
                # Must have ask price, sufficient depth, and no quarantine
                ask = rec.get("best_ask")
                ask_size = rec.get("best_ask_size", 0.0)
                edge = rec.get("edge")
                tags = rec.get("tags", [])

                if ask is not None and ask_size >= MIN_DEPTH_REQUIRED and "QUARANTINED" not in tags and edge is not None:
                    all_records.append(rec)

        total_eligible = len(all_records)
        curve_points: List[ThresholdSweepPoint] = []

        for th in self.sweep_thresholds:
            qualifying_edges = [
                float(r["edge"]) for r in all_records if float(r["edge"]) >= th
            ]
            count = len(qualifying_edges)
            rate = (count / total_eligible) if total_eligible > 0 else 0.0

            if count > 0:
                mean_e = float(np.mean(qualifying_edges))
                med_e = float(np.median(qualifying_edges))
                min_e = float(np.min(qualifying_edges))
                max_e = float(np.max(qualifying_edges))
            else:
                mean_e = 0.0
                med_e = 0.0
                min_e = 0.0
                max_e = 0.0

            curve_points.append(
                ThresholdSweepPoint(
                    threshold=th,
                    signal_count=count,
                    signal_frequency_rate=round(rate, 6),
                    mean_edge=round(mean_e, 6),
                    median_edge=round(med_e, 6),
                    min_edge=round(min_e, 6),
                    max_edge=round(max_e, 6),
                )
            )

        return curve_points

    def evaluate_metric_a_lead_lag_d2(
        self,
        chronological_snapshots: List[Dict[str, Any]],
    ) -> MetricAResult:
        """
        D-2: Metric A (Lead-Lag Following).
        Evaluates whether a model probability jump > 3pp is followed by market mid-price
        moving in the same direction within 1..3 subsequent snapshots.
        """
        # Group records by (market_slug, token_id) ordered chronologically
        time_series: Dict[Tuple[str, str], List[Tuple[datetime, float, Optional[float], str]]] = {}

        for snap in chronological_snapshots:
            ts_str = snap.get("timestamp_iso", "")
            try:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except Exception:
                continue

            slug = snap.get("market_slug", "")
            for rec in snap.get("records", []):
                tid = rec.get("token_id", "")
                m_prob = float(rec.get("model_probability", 0.0))
                mid = rec.get("mid_price")
                lbl = rec.get("bracket_label", "")
                key = (slug, tid)
                if key not in time_series:
                    time_series[key] = []
                time_series[key].append((dt, m_prob, mid, lbl))

        jump_events: List[LeadLagJumpEvent] = []

        for (slug, tid), series in time_series.items():
            if len(series) < 2:
                continue

            for idx in range(1, len(series)):
                prev_dt, prev_p, prev_mid, _ = series[idx - 1]
                curr_dt, curr_p, curr_mid, lbl = series[idx]

                delta_p = curr_p - prev_p

                # Check D-2 jump condition: |Delta P_model| > 3 percentage points (0.03)
                if abs(delta_p) > D2_JUMP_THRESHOLD:
                    # Look ahead up to D2_FOLLOW_MAX_SNAPSHOTS (1..3)
                    market_deltas: List[float] = []
                    is_followed = False
                    follow_lag = None

                    sign_model = 1.0 if delta_p > 0 else -1.0

                    base_mid = curr_mid if curr_mid is not None else prev_mid

                    for fwd in range(1, D2_FOLLOW_MAX_SNAPSHOTS + 1):
                        fwd_idx = idx + fwd
                        if fwd_idx < len(series):
                            _, _, next_mid, _ = series[fwd_idx]
                            if next_mid is not None and base_mid is not None:
                                d_mkt = next_mid - base_mid
                                market_deltas.append(round(d_mkt, 6))
                                # Check if market moved in the same direction
                                if not is_followed and (d_mkt * sign_model > 1e-4):
                                    is_followed = True
                                    follow_lag = fwd

                    jump_events.append(
                        LeadLagJumpEvent(
                            market_slug=slug,
                            token_id=tid,
                            bracket_label=lbl,
                            jump_time_iso=curr_dt.isoformat(),
                            jump_delta_model=round(delta_p, 6),
                            market_deltas_next=tuple(market_deltas),
                            is_followed=is_followed,
                            follow_lag=follow_lag,
                        )
                    )

        total_jumps = len(jump_events)
        followed_count = sum(1 for e in jump_events if e.is_followed)
        follow_rate = (followed_count / total_jumps) if total_jumps > 0 else 0.0

        valid_lags = [e.follow_lag for e in jump_events if e.follow_lag is not None]
        avg_lag = float(np.mean(valid_lags)) if valid_lags else None

        # Statutory Criterion D-2:
        # Follow significant -> retain probe layer; Market precedes / no follow -> cut probe layer
        verdict = "RETAIN_PROBE_LAYER" if follow_rate >= 0.50 else "CUT_PROBE_LAYER"

        return MetricAResult(
            total_jump_events=total_jumps,
            followed_events=followed_count,
            follow_rate=follow_rate,
            average_lag=avg_lag,
            verdict=verdict,
            events=jump_events,
        )

    def evaluate_metric_b_calibration_d3(
        self,
        snapshots: List[Dict[str, Any]],
        official_settlements: Dict[str, str],  # market_slug -> winning_token_id
    ) -> Optional[MetricBResult]:
        """
        D-3: Metric B (Calibration Realization).
        Compares Model Brier Score vs Market Brier Score on threshold-exceeding signals
        against official settlement outcomes.
        """
        eval_pairs: List[Tuple[float, float, int]] = []  # (p_model, p_market, y_true)

        for snap in snapshots:
            slug = snap.get("market_slug", "")
            winning_tid = official_settlements.get(slug)
            if not winning_tid:
                continue  # Market not yet settled

            # Sum of mid-prices for market implied probability normalization
            records = snap.get("records", [])
            valid_mids = [r.get("mid_price") for r in records if r.get("mid_price") is not None]
            total_mid = sum(valid_mids) if valid_mids else 0.0

            for rec in records:
                # Must be a threshold-exceeding signal (edge >= 0.05) or positive EV tag
                edge = rec.get("edge")
                tags = rec.get("tags", [])
                if edge is None or edge < 0.05 or "QUARANTINED" in tags:
                    continue

                m_prob = float(rec.get("model_probability", 0.0))
                mid = rec.get("mid_price")
                if mid is None:
                    continue

                # Normalized market implied probability
                p_mkt = (mid / total_mid) if total_mid > 1e-6 else mid
                tid = rec.get("token_id", "")
                y_true = 1 if tid == winning_tid else 0

                eval_pairs.append((m_prob, p_mkt, y_true))

        if not eval_pairs:
            logger.info("No settled signal pairs available for Metric B calculation")
            return None

        n = len(eval_pairs)
        model_sq_errors = [(p - y) ** 2 for p, _, y in eval_pairs]
        mkt_sq_errors = [(q - y) ** 2 for _, q, y in eval_pairs]

        bs_model = float(np.mean(model_sq_errors))
        bs_mkt = float(np.mean(mkt_sq_errors))

        # Brier Skill Score: 1 - (BS_model / BS_market)
        bss = 1.0 - (bs_model / bs_mkt) if bs_mkt > 1e-12 else 0.0

        model_mean_p = float(np.mean([p for p, _, _ in eval_pairs]))
        mkt_mean_p = float(np.mean([q for _, q, _ in eval_pairs]))
        hit_rate = float(np.mean([y for _, _, y in eval_pairs]))

        # Criterion D-3:
        # Model significantly outperforms market (BSS > 0) -> TRUE_EV_ADVANTAGE
        # No advantage or worse (BSS <= 0) -> RAISE_THRESHOLD_OR_CUT_PROBE
        verdict = "TRUE_EV_ADVANTAGE" if bss > 0.0 else "RAISE_THRESHOLD_OR_CUT_PROBE"

        return MetricBResult(
            sample_count=n,
            model_brier_score=bs_model,
            market_brier_score=bs_mkt,
            brier_skill_score=bss,
            model_mean_prob=model_mean_p,
            market_mean_prob=mkt_mean_p,
            realized_hit_rate=hit_rate,
            verdict=verdict,
        )

    def run_full_offline_analysis(
        self,
        snapshots: List[Dict[str, Any]],
        official_settlements: Optional[Dict[str, str]] = None,
    ) -> OfflineReplaySummary:
        """
        Execute complete D-1, D-2, and D-3 analysis and return consolidated summary.
        """
        analysis_id = f"offline_analysis_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        ts_iso = datetime.now(timezone.utc).isoformat()

        # Sort snapshots chronologically for D-2 lead-lag
        sorted_snaps = sorted(snapshots, key=lambda s: s.get("timestamp_iso", ""))

        d1_curve = self.sweep_thresholds_d1(sorted_snaps)
        d2_metric_a = self.evaluate_metric_a_lead_lag_d2(sorted_snaps)
        d3_metric_b = (
            self.evaluate_metric_b_calibration_d3(sorted_snaps, official_settlements)
            if official_settlements
            else None
        )

        total_brackets = sum(len(s.get("records", [])) for s in sorted_snaps)
        div_count = sum(s.get("summary", {}).get("divergence_count", 0) for s in sorted_snaps)
        suspect_count = sum(1 for s in sorted_snaps if s.get("summary", {}).get("is_input_suspect", False))
        quarantined_count = sum(s.get("summary", {}).get("quarantined_signals", 0) for s in sorted_snaps)

        return OfflineReplaySummary(
            analysis_id=analysis_id,
            timestamp_iso=ts_iso,
            total_snapshots_analyzed=len(sorted_snaps),
            total_brackets_analyzed=total_brackets,
            d1_threshold_curve=d1_curve,
            d2_metric_a=d2_metric_a,
            d3_metric_b=d3_metric_b,
            divergence_count=div_count,
            input_suspect_count=suspect_count,
            quarantined_signal_count=quarantined_count,
        )
