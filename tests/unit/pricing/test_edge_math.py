"""Unit, dimensional consistency, and property-based invariant tests for S1-04."""

from __future__ import annotations

import math
import random
from typing import Dict, List, Literal, Optional, Tuple

import pytest

from src.pricing.edge_math import (
    BookEdgeSummary,
    LevelEdge,
    QualifiedLevel,
    compute_level_edge,
    evaluate_book_edges,
)
from src.pricing.penetration_probe import (
    AskBook,
    FEE_BASE_RATIO,
    NoQualifiedLevelsError,
    PenetrationPolicy,
    compute_probe,
)


def _reference_m_threshold(
    k0: float,
    sigma_delta_frozen: float,
    friction_median: float,
    m_floor: float,
) -> float:
    """B5 derived read-only threshold formula."""
    return max(k0 * sigma_delta_frozen + friction_median, m_floor)


def _build_synthetic_p5_snapshot(
    rng: random.Random,
    target_type: Literal["TMAX", "TMIN"],
    is_bridge_active: bool,
    m_now_f: Optional[float],
    force_open_tail: bool = False,
) -> Dict[str, object]:
    """Build a synthetic P5 ForecastDistributionSnapshot candidate under Q-B1/Q-B2 rules."""
    # Contiguous half-degree partition (-inf, a+0.5), [a+0.5, a+2.5), ..., [b+0.5, +inf)
    low_anchor = rng.randint(40, 70)
    n_interior = 9
    edge0 = low_anchor + 0.5
    bins: List[Tuple[float, float]] = [(-math.inf, edge0)]
    cur = edge0
    for _ in range(n_interior):
        bins.append((cur, cur + 2.0))
        cur += 2.0
    bins.append((cur, math.inf))

    k_count = len(bins)
    if not is_bridge_active:
        raw_weights = [rng.random() + 1e-3 for _ in range(k_count)]
        tot = sum(raw_weights)
        probs = [w / tot for w in raw_weights]
        return {
            "target_type": target_type,
            "m_now_f": m_now_f,
            "is_bridge_active": False,
            "p_stay": None,
            "bins": bins,
            "bin_probs": probs,
        }

    assert m_now_f is not None
    if force_open_tail:
        m_now = (bins[-1][0] + 0.5) if target_type == "TMAX" else (bins[0][1] - 0.5)
    else:
        m_now = m_now_f

    # Find containing boundary bin index j ([lo, hi) convention)
    j_idx = next(
        idx for idx, (lo, hi) in enumerate(bins) if lo <= m_now < hi
    )

    if target_type == "TMAX":
        if j_idx == k_count - 1:
            p_stay = 1.0
            probs = [0.0] * (k_count - 1) + [1.0]
        else:
            p_stay = rng.uniform(0.0, 1.0)
            p_exceed = 1.0 - p_stay
            tail_weights = [rng.random() + 1e-4 for _ in range(j_idx, k_count)]
            s_w = sum(tail_weights)
            probs = [0.0] * k_count
            for offset, w in enumerate(tail_weights):
                idx = j_idx + offset
                probs[idx] = p_exceed * (w / s_w)
            # Point mass is CONTAINED within bin j alongside bin j exceedance mass
            probs[j_idx] += p_stay
    else:
        if j_idx == 0:
            p_stay = 1.0
            probs = [1.0] + [0.0] * (k_count - 1)
        else:
            p_stay = rng.uniform(0.0, 1.0)
            p_exceed = 1.0 - p_stay
            tail_weights = [rng.random() + 1e-4 for _ in range(0, j_idx + 1)]
            s_w = sum(tail_weights)
            probs = [0.0] * k_count
            for idx, w in enumerate(tail_weights):
                probs[idx] = p_exceed * (w / s_w)
            probs[j_idx] += p_stay

    return {
        "target_type": target_type,
        "m_now_f": m_now,
        "is_bridge_active": True,
        "p_stay": p_stay,
        "bins": bins,
        "bin_probs": probs,
        "boundary_idx": j_idx,
    }


def _assert_p5_qb1_qb2_invariants(snap: Dict[str, object]) -> None:
    """Assert Q-B1 (4 invariants + open-end corollary) and Q-B2 state matrix."""
    target_type = snap["target_type"]
    m_now = snap["m_now_f"]
    is_active = snap["is_bridge_active"]
    p_stay = snap["p_stay"]
    bins = snap["bins"]
    probs = snap["bin_probs"]

    # Q-B2 state matrix
    if is_active:
        assert m_now is not None
        assert p_stay is not None
    else:
        assert p_stay is None

    # Q-B1.1 probability simplex
    assert len(probs) == len(bins)
    assert all(0.0 <= p <= 1.0 for p in probs)
    assert abs(sum(probs) - 1.0) <= 1e-5

    # Q-B1.2 boundary atom domain
    if is_active:
        assert 0.0 <= p_stay <= 1.0  # type: ignore[operator]
        j_idx = next(i for i, (lo, hi) in enumerate(bins) if lo <= m_now < hi)

        # Q-B1.3 polarity-sensitive dead bin zeroing
        if target_type == "TMAX":
            for k in range(j_idx):
                assert bins[k][1] <= m_now
                assert probs[k] == 0.0
            if math.isinf(bins[j_idx][1]) and bins[j_idx][1] > 0:
                assert probs[-1] == pytest.approx(1.0, abs=1e-12)
                assert p_stay == pytest.approx(1.0, abs=1e-12)
        else:
            for k in range(j_idx + 1, len(bins)):
                assert bins[k][0] >= m_now
                assert probs[k] == 0.0
            if math.isinf(bins[j_idx][0]) and bins[j_idx][0] < 0:
                assert probs[0] == pytest.approx(1.0, abs=1e-12)
                assert p_stay == pytest.approx(1.0, abs=1e-12)

        # Q-B1.4 point mass containment law (NOT additive on top of bin_probs[j])
        assert probs[j_idx] + 1e-12 >= p_stay  # type: ignore[operator]


class TestEdgeMathCore:
    """Validate compute_level_edge and evaluate_book_edges against penetration_probe."""

    def test_compute_level_edge_matches_penetration_probe_formula(self) -> None:
        price = 0.40
        p_model = 0.55
        lvl = compute_level_edge(price=price, p_model=p_model)

        expected_q_eff = price * (1.0 + FEE_BASE_RATIO * (1.0 - price))
        expected_net_ev = p_model - expected_q_eff
        expected_edge = expected_net_ev / expected_q_eff

        assert isinstance(lvl, LevelEdge)
        assert lvl.price == price
        assert lvl.q_eff == pytest.approx(expected_q_eff, rel=1e-12, abs=1e-12)
        assert lvl.net_ev == pytest.approx(expected_net_ev, rel=1e-12, abs=1e-12)
        assert lvl.edge == pytest.approx(expected_edge, rel=1e-12, abs=1e-12)

    def test_dynamic_fee_rate_supports_nov20_transition(self) -> None:
        book = AskBook(levels=((0.50, 20.0), (0.52, 30.0)))
        res_old = evaluate_book_edges(book, p_model=0.60, m=0.05, fee_rate=0.05)
        res_new = evaluate_book_edges(book, p_model=0.60, m=0.05, fee_rate=0.01)

        assert res_old.best_ask_edge == pytest.approx((0.60 - 0.5125) / 0.5125)
        assert res_new.best_ask_edge == pytest.approx((0.60 - 0.5025) / 0.5025)
        assert res_new.best_ask_edge > res_old.best_ask_edge

    def test_no_exception_when_best_ask_below_m_while_compute_probe_raises(self) -> None:
        book = AskBook(levels=((0.60, 15.0), (0.65, 25.0)))
        p_model = 0.50  # negative edge relative to 0.60
        m = 0.04

        summary = evaluate_book_edges(ask_book=book, p_model=p_model, m=m)
        assert isinstance(summary, BookEdgeSummary)
        assert summary.best_ask_edge < 0.0
        assert summary.qualified_levels == ()
        assert summary.qual_depth_shares == 0.0

        locked_policy = PenetrationPolicy(
            min_edge=m, provenance="test_edge_math", lock_state="F2_RELEASED"
        )
        with pytest.raises(NoQualifiedLevelsError):
            compute_probe(book=book, p_hat=p_model, policy=locked_policy)

    def test_allows_zero_probability_dead_bin_scan_without_exception(self) -> None:
        book = AskBook(levels=((0.01, 50.0),))
        summary = evaluate_book_edges(ask_book=book, p_model=0.0, m=0.02)
        assert summary.best_ask_edge == pytest.approx(-1.0)
        assert summary.qualified_levels == ()
        assert summary.qual_depth_shares == 0.0

    def test_partial_qualification_and_consistent_per_level_edges(self) -> None:
        book = AskBook(levels=((0.30, 10.0), (0.35, 20.0), (0.50, 40.0)))
        summary = evaluate_book_edges(ask_book=book, p_model=0.45, m=0.20)
        # Level 0: q_eff=0.30*(1+0.05*0.7)=0.3105 => edge=+0.449275 >= 0.20
        # Level 1: q_eff=0.35*(1+0.05*0.65)=0.361375 => edge=+0.245244 >= 0.20
        # Level 2: q_eff=0.50*(1+0.05*0.50)=0.5125 => edge=-0.121951 < 0.20
        assert len(summary.qualified_levels) == 2
        assert all(isinstance(q, QualifiedLevel) for q in summary.qualified_levels)
        assert summary.qual_depth_shares == pytest.approx(30.0)
        assert summary.qualified_levels[0].edge == pytest.approx(summary.best_ask_edge)
        assert summary.qualified_levels[0].edge > summary.qualified_levels[1].edge >= 0.20

    @pytest.mark.parametrize(
        ("price", "p_model", "fee_rate"),
        [
            (0.0, 0.5, 0.05),
            (1.0, 0.5, 0.05),
            (0.5, -0.01, 0.05),
            (0.5, 1.01, 0.05),
            (0.5, 0.5, -0.001),
            (math.nan, 0.5, 0.05),
            (True, 0.5, 0.05),
        ],
    )
    def test_input_domain_validation(self, price: float, p_model: float, fee_rate: float) -> None:
        with pytest.raises(ValueError):
            compute_level_edge(price=price, p_model=p_model, fee_rate=fee_rate)


class TestRulingB5DimensionalConsistency:
    """Property checks locking B5 threshold vs edge_math relative dimensionless units."""

    def test_m_threshold_and_edge_share_dimensionless_relative_return_unit(self) -> None:
        rng = random.Random(20261118)
        for _ in range(300):
            price = rng.uniform(0.02, 0.95)
            p_model = rng.uniform(0.01, 0.99)
            fee_rate = rng.choice([0.0, 0.01, 0.05])
            k0 = rng.uniform(1.0, 3.0)
            sigma_delta = rng.uniform(0.0, 0.06)
            friction_median = rng.uniform(0.0, 0.04)
            m_floor = rng.uniform(0.005, 0.03)

            m_threshold = _reference_m_threshold(k0, sigma_delta, friction_median, m_floor)
            lvl = compute_level_edge(price=price, p_model=p_model, fee_rate=fee_rate)
            book = AskBook(levels=((price, 10.0), (min(price + 0.01, 0.99), 25.0)))
            summary = evaluate_book_edges(book, p_model=p_model, m=m_threshold, fee_rate=fee_rate)

            # Scale shares by arbitrary multiplier N=100; edge and gate decision stay invariant
            scaled_book = AskBook(levels=((price, 1000.0), (min(price + 0.01, 0.99), 2500.0)))
            scaled_summary = evaluate_book_edges(
                scaled_book, p_model=p_model, m=m_threshold, fee_rate=fee_rate
            )
            assert scaled_summary.best_ask_edge == pytest.approx(summary.best_ask_edge)
            assert (len(scaled_summary.qualified_levels) > 0) == (lvl.edge >= m_threshold)

            # Verify net_ev == q_eff * edge (distinguishing absolute dollar gap from relative ratio)
            assert lvl.net_ev == pytest.approx(lvl.q_eff * lvl.edge, abs=1e-12)
            assert (lvl.edge >= m_threshold) == (lvl.net_ev >= m_threshold * lvl.q_eff - 1e-15)


class TestP5InvariantsPropertySuite:
    """N7 randomized property-based test checklist for P5 Q-B1 (4 invariants) & Q-B2."""

    def test_property_500_random_snapshots_tmax_and_tmin(self) -> None:
        rng = random.Random(778899)
        for idx in range(500):
            target_type: Literal["TMAX", "TMIN"] = "TMAX" if idx % 2 == 0 else "TMIN"
            mode = idx % 5
            if mode == 0:
                snap = _build_synthetic_p5_snapshot(rng, target_type, False, None)
            elif mode == 1:
                snap = _build_synthetic_p5_snapshot(rng, target_type, False, rng.uniform(45.0, 85.0))
            elif mode == 2:
                snap = _build_synthetic_p5_snapshot(
                    rng, target_type, True, 0.0, force_open_tail=True
                )
            else:
                m_now = rng.uniform(40.0, 92.0)
                snap = _build_synthetic_p5_snapshot(rng, target_type, True, m_now)
            _assert_p5_qb1_qb2_invariants(snap)
