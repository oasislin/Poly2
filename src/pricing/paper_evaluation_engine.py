"""
Paper Trading Evaluation Engine and Probability Pipeline Integration (Phase 2 Wave 3 / W3-B).
Governed by docs/w3_polymarket_ingestion_preregistration.md Rev.1.0 (Work Order P7-W3-TASK2-AUTH-001).

Implements:
1. Probability Pipeline Alignment to Polymarket Contract Brackets
2. B-1: Conservative Side Price Mapping (Ask for Buy, Bid for Sell, Midpoint for Display/Monitoring)
3. B-2: NO_QUOTE Handling on Missing Book Sides
4. B-3: Positive EV Threshold (Edge = Model Prob - Best Ask >= 0.05 -> POSITIVE_EV_SIGNAL)
5. B-4: Full Ledger Evaluation Persistence (All brackets recorded regardless of signal status)
6. B-5: Minimum Depth Protection (Best ask size >= 10 contracts required for tradable signal)
7. B-6: Model-Market Divergence Monitoring (|Model Prob - Mid Price| > 0.15 -> MODEL_MARKET_DIVERGENCE, non-blocking)
8. A-4: PROB_STATIC Reservation & Tracking (Unchanged model probabilities flagged across snapshots)
9. E-2: Mandatory DATA_PROVENANCE = "POLYMARKET_LIVE_CLOB" Tagging
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np
from scipy.special import ndtr

from src.data_acquisition.polymarket_clob_collector import (
    DATA_PROVENANCE_LIVE,
    CLOBQuote,
    MarketTokenBracket,
    PolymarketTemperatureMarket,
    SnapshotRecord,
)

logger = logging.getLogger(__name__)

# Statutory Criteria Constants (Rev.1.0)
MIN_POSITIVE_EV_EDGE = 0.05       # B-3: edge >= 5 percentage points (0.05)
MIN_ORDERBOOK_DEPTH = 10.0        # B-5: best level size >= 10 contracts
DIVERGENCE_THRESHOLD = 0.15       # B-6: |model_prob - mid_price| > 0.15 (15 percentage points)
PROB_STATIC_EPSILON = 1e-6        # A-4: probability stability threshold across snapshots

# Climatological/Forecast priors for Active 10 stations (Fahrenheit Mean & StdDev)
DEFAULT_STATION_PRIORS: Dict[str, Tuple[float, float]] = {
    "KORD": (62.0, 3.5),   # Chicago O'Hare
    "KMIA": (84.0, 2.0),   # Miami International
    "KLGA": (64.0, 3.2),   # NYC LaGuardia
    "KATL": (68.0, 3.0),   # Atlanta
    "KDFW": (74.0, 3.5),   # Dallas Fort Worth
    "KLAX": (72.0, 2.5),   # Los Angeles
    "KSEA": (58.0, 2.8),   # Seattle
    "KSFO": (63.0, 2.5),   # San Francisco
    "KIAH": (78.0, 3.0),   # Houston
    "KBKF": (60.0, 4.0),   # Denver Buckley
    "KAUS": (77.0, 3.2),   # Austin
    "EGLL": (55.0, 2.5),   # London Heathrow
}


def parse_bracket_bounds(label: str) -> Tuple[float, float]:
    """
    Parse a Polymarket discrete bracket label into continuous Fahrenheit interval [lower_bound, upper_bound).
    Applies standard NWS WRH half-degree continuity correction (+/- 0.5°F).
    Examples:
        '55°F or below' -> (-inf, 55.5)
        '56-57°F'       -> (55.5, 57.5)
        '58-59°F'       -> (57.5, 59.5)
        '76°F or above' -> (75.5, +inf)
        '<=50°F'        -> (-inf, 50.5)
        '>=70°F'        -> (69.5, +inf)
        '60°F'          -> (59.5, 60.5)
    """
    cleaned = label.strip()

    # 1. Interval: 56-57°F or 56 - 57 F
    m_range = re.search(r"(\d+)\s*[-–—]\s*(\d+)", cleaned)
    if m_range:
        lo = float(m_range.group(1)) - 0.5
        hi = float(m_range.group(2)) + 0.5
        return (lo, hi)

    # 2. Left Tail: <= T or T or below / or less
    m_lte = re.search(
        r"(?:≤|<=|<)\s*(\d+)|(\d+)\s*°?[FC]?\s*(?:or below|or less)",
        cleaned,
        re.IGNORECASE,
    )
    if m_lte:
        val = float(m_lte.group(1) or m_lte.group(2))
        return (-np.inf, val + 0.5)

    # 3. Right Tail: >= T or T or above / or more / or higher
    m_gte = re.search(
        r"(?:≥|>=|>)\s*(\d+)|(\d+)\s*°?[FC]?\s*(?:or above|or more|or higher)",
        cleaned,
        re.IGNORECASE,
    )
    if m_gte:
        val = float(m_gte.group(1) or m_gte.group(2))
        return (val - 0.5, np.inf)

    # 4. Single degree: 60°F
    m_single = re.search(r"(\d+)", cleaned)
    if m_single:
        val = float(m_single.group(1))
        return (val - 0.5, val + 0.5)

    return (-np.inf, np.inf)


def compute_bracket_probabilities(
    brackets: List[MarketTokenBracket],
    cdf_fn: Optional[Callable[[float], float]] = None,
    mu: Optional[float] = None,
    sigma: Optional[float] = None,
    station_id: Optional[str] = None,
) -> Dict[str, float]:
    """
    Integrate continuous cumulative distribution function across discrete contract brackets.
    Enforces simplex normalization (sum == 1.0).
    """
    # Determine CDF
    if cdf_fn is None:
        if mu is None or sigma is None:
            prior_mu, prior_sigma = DEFAULT_STATION_PRIORS.get(station_id or "KORD", (65.0, 3.0))
            mu = prior_mu if mu is None else mu
            sigma = prior_sigma if sigma is None else sigma
        # Gaussian CDF using scipy.special.ndtr
        cdf_fn = lambda x: float(ndtr((x - mu) / sigma))

    raw_probs: Dict[str, float] = {}
    for b in brackets:
        lo, hi = parse_bracket_bounds(b.bracket_label)
        cdf_hi = 1.0 if np.isposinf(hi) else float(cdf_fn(hi))
        cdf_lo = 0.0 if np.isneginf(lo) else float(cdf_fn(lo))
        prob = max(0.0, cdf_hi - cdf_lo)
        raw_probs[b.token_id] = prob

    total_p = sum(raw_probs.values())
    if total_p > 1e-12:
        return {tid: p / total_p for tid, p in raw_probs.items()}
    # Fallback uniform
    uniform_p = 1.0 / len(brackets) if brackets else 0.0
    return {b.token_id: uniform_p for b in brackets}


@dataclass(frozen=True)
class BracketEvaluationRecord:
    """
    Single contract bracket paper evaluation record.
    B-4: Fully serialized and persisted regardless of whether EV threshold is crossed.
    """
    token_id: str
    bracket_label: str
    model_probability: float
    best_ask: Optional[float]
    best_bid: Optional[float]
    mid_price: Optional[float]
    best_ask_size: float
    best_bid_size: float
    edge: Optional[float]
    is_signal: bool
    eval_status: str
    tags: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_id": self.token_id,
            "bracket_label": self.bracket_label,
            "model_probability": round(self.model_probability, 6),
            "best_ask": round(self.best_ask, 6) if self.best_ask is not None else None,
            "best_bid": round(self.best_bid, 6) if self.best_bid is not None else None,
            "mid_price": round(self.mid_price, 6) if self.mid_price is not None else None,
            "best_ask_size": round(self.best_ask_size, 4),
            "best_bid_size": round(self.best_bid_size, 4),
            "edge": round(self.edge, 6) if self.edge is not None else None,
            "is_signal": self.is_signal,
            "eval_status": self.eval_status,
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class MarketEvaluationSnapshot:
    """
    Complete evaluation snapshot across all brackets of a market.
    E-2: Explicit data_provenance == DATA_PROVENANCE_LIVE.
    B-4: Full ledger structure.
    """
    evaluation_id: str
    timestamp_iso: str
    snapshot_id: str
    market_slug: str
    station_id: Optional[str]
    settlement_time_iso: str
    data_provenance: str
    records: List[BracketEvaluationRecord] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "timestamp_iso": self.timestamp_iso,
            "snapshot_id": self.snapshot_id,
            "market_slug": self.market_slug,
            "station_id": self.station_id,
            "settlement_time_iso": self.settlement_time_iso,
            "data_provenance": self.data_provenance,
            "records": [r.to_dict() for r in self.records],
            "summary": self.summary,
        }


class PaperEvaluationEngine:
    """
    Evaluates market orderbook snapshots against physical model probability distributions.
    Executes criteria B-1 through B-6, A-4, and E-2.
    """

    def __init__(self, storage_base_dir: Optional[Path] = None):
        self.storage_base_dir = storage_base_dir or Path("data/clob/evaluations")
        # Cache for previous model probabilities to support A-4 PROB_STATIC detection
        self._prev_model_probs: Dict[str, float] = {}

    def evaluate_market_snapshot(
        self,
        market: PolymarketTemperatureMarket,
        snapshot: SnapshotRecord,
        model_probs: Optional[Dict[str, float]] = None,
        mu: Optional[float] = None,
        sigma: Optional[float] = None,
        cdf_fn: Optional[Callable[[float], float]] = None,
    ) -> MarketEvaluationSnapshot:
        """
        Evaluate orderbook quotes for all brackets in a market.
        B-1: Conservative ask/bid prices.
        B-2: Missing quotes marked NO_QUOTE.
        B-3: Edge >= 0.05 marked POSITIVE_EV_SIGNAL.
        B-4: Full ledger evaluation.
        B-5: Min depth >= 10 contracts.
        B-6: Divergence > 0.15 marked MODEL_MARKET_DIVERGENCE.
        A-4: Unchanged model probability flagged PROB_STATIC.
        """
        eval_time_iso = datetime.now(timezone.utc).isoformat()
        evaluation_id = f"eval_{snapshot.snapshot_id}"

        # 1. Compute model probabilities if not provided explicitly
        if model_probs is None:
            model_probs = compute_bracket_probabilities(
                brackets=market.brackets,
                cdf_fn=cdf_fn,
                mu=mu,
                sigma=sigma,
                station_id=market.station_id,
            )

        records: List[BracketEvaluationRecord] = []
        positive_ev_count = 0
        divergence_count = 0
        static_count = 0
        no_quote_count = 0

        for bracket in market.brackets:
            tid = bracket.token_id
            m_prob = model_probs.get(tid, 0.0)
            quote = snapshot.quotes.get(tid)

            tags: List[str] = []

            # A-4: Check PROB_STATIC (model probability identical to prior snapshot)
            if tid in self._prev_model_probs:
                prev_p = self._prev_model_probs[tid]
                if abs(m_prob - prev_p) <= PROB_STATIC_EPSILON:
                    tags.append("PROB_STATIC")
                    static_count += 1
            # Update cache
            self._prev_model_probs[tid] = m_prob

            # B-2: Missing quote or unpopulated book side
            if quote is None or quote.quote_status in ["NO_QUOTE", "EMPTY_BOOK"]:
                tags.append("NO_QUOTE")
                no_quote_count += 1
                record = BracketEvaluationRecord(
                    token_id=tid,
                    bracket_label=bracket.bracket_label,
                    model_probability=m_prob,
                    best_ask=quote.best_ask if quote else None,
                    best_bid=quote.best_bid if quote else None,
                    mid_price=None,
                    best_ask_size=quote.best_ask_size if quote else 0.0,
                    best_bid_size=quote.best_bid_size if quote else 0.0,
                    edge=None,
                    is_signal=False,
                    eval_status="NO_QUOTE",
                    tags=tuple(tags),
                )
                records.append(record)
                continue

            # B-1: Best ask for buying, best bid for selling
            best_ask = quote.best_ask
            best_bid = quote.best_bid
            mid_price = quote.mid_price
            best_ask_size = quote.best_ask_size
            best_bid_size = quote.best_bid_size

            # B-6: Model-Market Divergence Monitoring (|model_prob - mid_price| > 0.15)
            if mid_price is not None:
                div = abs(m_prob - mid_price)
                if div > DIVERGENCE_THRESHOLD:
                    tags.append("MODEL_MARKET_DIVERGENCE")
                    divergence_count += 1

            # Edge calculation (Buying side)
            assert best_ask is not None
            edge = m_prob - best_ask

            # B-3 & B-5: Positive EV & Minimum Depth Gate
            is_positive_ev = edge >= MIN_POSITIVE_EV_EDGE
            has_sufficient_depth = best_ask_size >= MIN_ORDERBOOK_DEPTH

            if is_positive_ev:
                tags.append("POSITIVE_EV_SIGNAL")
                if has_sufficient_depth:
                    is_signal = True
                    eval_status = "APPROVED_POSITIVE_EV"
                    positive_ev_count += 1
                else:
                    is_signal = False
                    eval_status = "INSUFFICIENT_DEPTH"
                    tags.append("INSUFFICIENT_DEPTH")
            else:
                is_signal = False
                eval_status = "BELOW_EDGE_THRESHOLD" if edge >= 0.0 else "NEGATIVE_EV"

            record = BracketEvaluationRecord(
                token_id=tid,
                bracket_label=bracket.bracket_label,
                model_probability=m_prob,
                best_ask=best_ask,
                best_bid=best_bid,
                mid_price=mid_price,
                best_ask_size=best_ask_size,
                best_bid_size=best_bid_size,
                edge=edge,
                is_signal=is_signal,
                eval_status=eval_status,
                tags=tuple(tags),
            )
            records.append(record)

        summary = {
            "total_brackets": len(market.brackets),
            "evaluated_count": len(records),
            "positive_ev_signals": positive_ev_count,
            "divergence_count": divergence_count,
            "static_prob_count": static_count,
            "no_quote_count": no_quote_count,
        }

        eval_snapshot = MarketEvaluationSnapshot(
            evaluation_id=evaluation_id,
            timestamp_iso=eval_time_iso,
            snapshot_id=snapshot.snapshot_id,
            market_slug=market.slug,
            station_id=market.station_id,
            settlement_time_iso=market.official_settlement_time.isoformat(),
            data_provenance=DATA_PROVENANCE_LIVE,
            records=records,
            summary=summary,
        )
        return eval_snapshot

    def save_evaluation_snapshot(self, eval_snapshot: MarketEvaluationSnapshot) -> Path:
        """
        B-4: Persist standardized full evaluation ledger to daily partitioned directory.
        """
        day_str = eval_snapshot.timestamp_iso[:10]
        out_dir = self.storage_base_dir / day_str
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"{eval_snapshot.evaluation_id}.json"

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(eval_snapshot.to_dict(), f, indent=2, ensure_ascii=False)

        logger.info(f"Persisted evaluation snapshot to {file_path}")
        return file_path
