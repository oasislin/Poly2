"""
SyntheticMarketMaker: Adversarial synthetic market maker for Polymarket order book simulation (Phase 2 Task 07 - Fix Ticket 01 / Issue #101).

Implements:
- Naive Consensus Pricing: Prices order books based purely on uncalibrated raw GEFS ensemble
  mean and dispersion, without EMOS calibration, without climatology variance floor,
  and without physical reachability / extreme truncation.
- Empirical Polymarket Spreads: Generates realistic buy/sell half-spreads (3~8 cents total spread).
- Tiered Depth & Impact Cost: Finite liquidity tiers ($100 ~ $500 per level) with widening spreads,
  preventing infinite liquidity exploitation.
- Intraday METAR Nudging: Naively shifts mean without physical irreversibility locks,
  preserving genuine structural alpha for the EMOS + ConstraintEnforcer pipeline.
"""

from dataclasses import dataclass
from decimal import Decimal
import logging
from typing import Dict, List, Optional
import numpy as np
from scipy.special import ndtr

from src.pricing.ev_engine import OrderBookLevel, OrderBookSnapshot
from src.prediction.discrete_bin_engine import DiscreteBin
from src.simulation.models import SimulatedOrderBook

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketMakerConfig:
    """Parameters controlling synthetic market maker quotation and depth behavior."""
    half_spread: float = 0.025         # Half spread (0.025 => 0.05 total spread / 5 cents)
    min_spread: float = 0.03           # Minimum total spread (3 cents)
    max_spread: float = 0.08           # Maximum total spread (8 cents)
    level2_spread_delta: float = 0.02  # Additional spread for Level 2 depth
    level3_spread_delta: float = 0.05  # Additional spread for Level 3 depth
    depth_level1_shares: float = 150.0 # First tier depth
    depth_level2_shares: float = 250.0 # Second tier depth
    depth_level3_shares: float = 400.0 # Third tier depth
    min_naive_std: float = 2.5         # Minimum naive standard deviation in °F
    min_price: float = 0.01            # Minimum contract price (1 cent)
    max_price: float = 0.99            # Maximum contract price (99 cents)
    intraday_nudge_weight: float = 0.3 # Naive nudge weight towards intraday obs


class SyntheticMarketMaker:
    """
    Adversarial synthetic market maker generating realistic, competitive CLOB quotes.
    Represents the uninformed/naive market consensus against which the model trades.
    """

    def __init__(self, config: Optional[MarketMakerConfig] = None):
        self.config = config or MarketMakerConfig()

    def compute_naive_probabilities(
        self,
        bins: List[DiscreteBin],
        ensemble_mean: float,
        ensemble_variance: float,
        observed_temp_f: Optional[float] = None,
    ) -> Dict[int, float]:
        """
        Compute naive market probabilities based strictly on raw uncalibrated ensemble statistics.
        Does NOT apply EMOS regression (a, b, c, d), climatological floor, or physical hard truncation.
        """
        raw_std = np.sqrt(max(0.0, ensemble_variance))
        naive_sigma = max(raw_std, self.config.min_naive_std)

        # Naive intraday nudge (if METAR obs observed, simple weighted average)
        if observed_temp_f is not None:
            w = self.config.intraday_nudge_weight
            naive_mu = (1.0 - w) * ensemble_mean + w * observed_temp_f
        else:
            naive_mu = ensemble_mean

        raw_probs: Dict[int, float] = {}
        for b in bins:
            cdf_high = 1.0 if np.isposinf(b.upper_bound_f) else float(ndtr((b.upper_bound_f - naive_mu) / naive_sigma))
            cdf_low = 0.0 if np.isneginf(b.lower_bound_f) else float(ndtr((b.lower_bound_f - naive_mu) / naive_sigma))
            raw_probs[b.bin_index] = max(0.0, cdf_high - cdf_low)

        # Normalize to probability simplex
        total_p = sum(raw_probs.values())
        if total_p <= 0.0:
            uniform = 1.0 / len(bins)
            return {b.bin_index: uniform for b in bins}

        return {idx: p / total_p for idx, p in raw_probs.items()}

    def generate_order_book(
        self,
        station_id: str,
        market_id: str,
        bin_info: DiscreteBin,
        naive_prob: float,
    ) -> SimulatedOrderBook:
        """
        Generate a multi-tiered order book around the naive consensus probability.
        Asks and Bids are symmetrically offset by the empirical spread and widen with depth.
        """
        p0 = float(naive_prob)
        half_sp = self.config.half_spread
        cfg = self.config

        # 1. Asks (Offers to sell to trader who wants to buy)
        ask_p1 = min(cfg.max_price, max(cfg.min_price + 0.01, round(p0 + half_sp, 2)))
        ask_p2 = min(cfg.max_price, max(ask_p1 + 0.01, round(ask_p1 + cfg.level2_spread_delta, 2)))
        ask_p3 = min(cfg.max_price, max(ask_p2 + 0.01, round(ask_p2 + cfg.level3_spread_delta, 2)))

        asks = [
            OrderBookLevel(price=float(ask_p1), size=cfg.depth_level1_shares),
            OrderBookLevel(price=float(ask_p2), size=cfg.depth_level2_shares),
            OrderBookLevel(price=float(ask_p3), size=cfg.depth_level3_shares),
        ]

        # 2. Bids (Offers to buy from trader who wants to sell)
        bid_p1 = max(cfg.min_price, min(ask_p1 - 0.01, round(p0 - half_sp, 2)))
        bid_p2 = max(cfg.min_price, min(bid_p1 - 0.01, round(bid_p1 - cfg.level2_spread_delta, 2)))
        bid_p3 = max(cfg.min_price, min(bid_p2 - 0.01, round(bid_p2 - cfg.level3_spread_delta, 2)))

        bids = [
            OrderBookLevel(price=float(bid_p1), size=cfg.depth_level1_shares),
            OrderBookLevel(price=float(bid_p2), size=cfg.depth_level2_shares),
            OrderBookLevel(price=float(bid_p3), size=cfg.depth_level3_shares),
        ]

        return SimulatedOrderBook(
            market_id=market_id,
            bin_index=bin_info.bin_index,
            station_id=station_id,
            bin_label=bin_info.label,
            bids=bids,
            asks=asks,
        )

    def generate_market_order_books(
        self,
        station_id: str,
        market_id: str,
        bins: List[DiscreteBin],
        ensemble_mean: float,
        ensemble_variance: float,
        observed_temp_f: Optional[float] = None,
    ) -> Dict[int, SimulatedOrderBook]:
        """Generate order books for all bins in a market contract."""
        naive_probs = self.compute_naive_probabilities(
            bins=bins,
            ensemble_mean=ensemble_mean,
            ensemble_variance=ensemble_variance,
            observed_temp_f=observed_temp_f,
        )

        order_books: Dict[int, SimulatedOrderBook] = {}
        for b in bins:
            p = naive_probs.get(b.bin_index, 0.0)
            order_books[b.bin_index] = self.generate_order_book(
                station_id=station_id,
                market_id=market_id,
                bin_info=b,
                naive_prob=p,
            )

        return order_books
