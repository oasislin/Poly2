"""Single authoritative fee-adjusted edge calculation utilities for M4 and M5.

Specification anchor: `项目方案 (v3.0) §8.5 附录 B` (`S1-04`, 2026-11-18).
Reads `AskBook` and `FEE_BASE_RATIO` from `src.pricing.penetration_probe`
without modifying any F-2 locked file.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Tuple

from src.pricing.penetration_probe import AskBook, FEE_BASE_RATIO


@dataclass(frozen=True)
class LevelEdge:
    """Fee-adjusted marginal edge metrics for a single ask price level."""

    price: float
    q_eff: float
    net_ev: float
    edge: float


@dataclass(frozen=True)
class QualifiedLevel:
    """Ask book level whose fee-adjusted relative edge meets threshold `m`."""

    price: float
    size: float
    q_eff: float
    net_ev: float
    edge: float


@dataclass(frozen=True)
class BookEdgeSummary:
    """Ask book scan result returned by `evaluate_book_edges` without exceptions on `edge < m`."""

    best_ask_edge: float
    qualified_levels: Tuple[QualifiedLevel, ...]
    qual_depth_shares: float


def _validate_finite_non_bool(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite numeric value, got {type(value).__name__}")
    val = float(value)
    if not math.isfinite(val):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return val


def compute_level_edge(
    price: float,
    p_model: float,
    fee_rate: float = FEE_BASE_RATIO,
) -> LevelEdge:
    """Compute fee-adjusted effective cost `q_eff`, `net_ev`, and relative `edge`.

    Matches `penetration_probe.py#L168-L169` and ruling B5 (taker fee only; no extra
    spread deduction because ask price already embeds spread):
        q_eff = price * (1 + fee_rate * (1 - price))
        net_ev = p_model - q_eff
        edge = (p_model - q_eff) / q_eff
    """
    p = _validate_finite_non_bool(price, "price")
    if not (0.0 < p < 1.0):
        raise ValueError(f"price must be in (0, 1), got {price!r}")

    prob = _validate_finite_non_bool(p_model, "p_model")
    if not (0.0 <= prob <= 1.0):
        raise ValueError(f"p_model must be in [0, 1], got {p_model!r}")

    fee = _validate_finite_non_bool(fee_rate, "fee_rate")
    if fee < 0.0:
        raise ValueError(f"fee_rate must be non-negative, got {fee_rate!r}")

    q_eff = p * (1.0 + fee * (1.0 - p))
    if q_eff <= 0.0 or not math.isfinite(q_eff):
        raise ValueError(f"q_eff must be positive and finite, got {q_eff!r}")

    net_ev = prob - q_eff
    edge = net_ev / q_eff
    return LevelEdge(price=p, q_eff=q_eff, net_ev=net_ev, edge=edge)


def evaluate_book_edges(
    ask_book: AskBook,
    p_model: float,
    m: float,
    fee_rate: float = FEE_BASE_RATIO,
) -> BookEdgeSummary:
    """Evaluate all ask levels against threshold `m` without raising on `best_ask_edge < m`.

    Allows M4 dual-clock scans to log negative/sub-threshold observations into P1
    (`ScanDecisionEvent`) while sharing the exact `q_eff` and `edge` math with M5.
    """
    if not isinstance(ask_book, AskBook):
        raise TypeError(f"ask_book must be an AskBook, got {type(ask_book).__name__}")

    threshold = _validate_finite_non_bool(m, "m")
    best_price = ask_book.levels[0][0]
    best_ask_edge = compute_level_edge(best_price, p_model, fee_rate=fee_rate).edge

    qualified = []
    qual_depth = 0.0
    for lvl_price, lvl_size in ask_book.levels:
        lvl_edge = compute_level_edge(lvl_price, p_model, fee_rate=fee_rate)
        if lvl_edge.edge >= threshold:
            qualified.append(
                QualifiedLevel(
                    price=lvl_edge.price,
                    size=lvl_size,
                    q_eff=lvl_edge.q_eff,
                    net_ev=lvl_edge.net_ev,
                    edge=lvl_edge.edge,
                )
            )
            qual_depth += lvl_size
        else:
            # AskBook enforces strictly increasing prices (and thus decreasing edge
            # for fee_rate <= 1); stopping once a level falls below `m` keeps the
            # contiguous top-of-book depth prefix coherent for M5 walking.
            break

    return BookEdgeSummary(
        best_ask_edge=best_ask_edge,
        qualified_levels=tuple(qualified),
        qual_depth_shares=qual_depth,
    )


__all__ = [
    "BookEdgeSummary",
    "LevelEdge",
    "QualifiedLevel",
    "compute_level_edge",
    "evaluate_book_edges",
]
