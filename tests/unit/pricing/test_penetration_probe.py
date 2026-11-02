"""
Unit tests for market penetration probe and trade EV engine (Phase 2 Task 08 - Ticket 08).
Validates DR-2026-1014-01 / P7-ALGO-2 M1 pricing safe capacity and EV calculation.
"""

import ast
import math
from pathlib import Path
import pytest

from src.pricing import (
    F2LockNotReleasedError as ExportedF2LockNotReleasedError,
    PenetrationF2LockNotReleasedError,
)
from src.pricing.penetration_probe import (
    FEE_BASE_PROVENANCE,
    FEE_BASE_RATIO,
    AskBook,
    F2LockNotReleasedError,
    InvalidOrderBookError,
    InvalidPenetrationPolicyError,
    InvalidProbabilityError,
    NoQualifiedLevelsError,
    PenetrationError,
    PenetrationPolicy,
    ProbeResult,
    compute_probe,
    load_penetration_policy,
)
from src.pricing.sigma_adj import (
    F2LockNotReleasedError as SigmaAdjF2LockNotReleasedError,
    SigmaAdjError,
    SigmaAdjLockState,
)


@pytest.fixture
def released_policy() -> PenetrationPolicy:
    """Fixture providing a mock released policy with 2% min_edge."""
    return PenetrationPolicy(
        min_edge=0.02,
        provenance="unit_test_released_policy",
        lock_state=SigmaAdjLockState.RELEASED,
    )


def test_t01_single_level_qualification_s_target(released_policy):
    """T01: single level orderbook qualification sets s_target = level size."""
    book = AskBook(levels=((0.40, 150.0),))
    p_hat = 0.50  # q_eff = 0.412, edge = (0.50 - 0.412)/0.412 = 0.2136 >= 0.02
    res = compute_probe(book=book, p_hat=p_hat, policy=released_policy)

    assert res.s_target == 150.0
    assert res.qualified_levels == (0,)
    assert res.p_bar == 0.40


def test_t02_multilevel_partial_qualification(released_policy):
    """T02: only qualifying levels under fee-inclusive edge contribute to p_bar and s_target."""
    book = AskBook(
        levels=(
            (0.40, 100.0),  # q_eff = 0.412, edge = 0.2136 >= 0.02 (qualifies)
            (0.48, 200.0),  # q_eff = 0.49248, edge = 0.01527 < 0.02 (excluded)
            (0.52, 300.0),  # q_eff = 0.53248, edge = -0.0610 < 0.02 (excluded)
        )
    )
    p_hat = 0.50
    res = compute_probe(book=book, p_hat=p_hat, policy=released_policy)

    assert res.qualified_levels == (0,)
    assert res.s_target == 100.0
    assert res.p_bar == 0.40


def test_t03_p_bar_weighted_average_accuracy(released_policy):
    """T03: p_bar depth-weighted average matches analytical formula within 1e-12."""
    levels = (
        (0.35, 80.0),
        (0.45, 120.0),
    )
    book = AskBook(levels=levels)
    p_hat = 0.60
    res = compute_probe(book=book, p_hat=p_hat, policy=released_policy)

    expected_p_bar = (0.35 * 80.0 + 0.45 * 120.0) / (80.0 + 120.0)
    assert abs(res.p_bar - expected_p_bar) <= 1e-12


def test_t04_q_eff_formula_accuracy(released_policy):
    """T04: q_eff matches p_bar * (1 + fee_base * (1 - p_bar)) within 1e-12."""
    book = AskBook(levels=((0.40, 100.0), (0.50, 100.0)))
    p_hat = 0.55
    res = compute_probe(book=book, p_hat=p_hat, policy=released_policy)

    p_bar = res.p_bar
    expected_q_eff = p_bar * (1.0 + FEE_BASE_RATIO * (1.0 - p_bar))
    assert abs(res.q_eff - expected_q_eff) <= 1e-12


def test_t05_net_ev_and_edge_post_fee_accuracy(released_policy):
    """T05: net_ev = p_hat - q_eff and edge = net_ev / q_eff within 1e-12."""
    book = AskBook(levels=((0.40, 100.0),))
    p_hat = 0.60
    res = compute_probe(book=book, p_hat=p_hat, policy=released_policy)

    expected_net_ev = p_hat - res.q_eff
    expected_edge = expected_net_ev / res.q_eff
    assert abs(res.net_ev - expected_net_ev) <= 1e-12
    assert abs(res.edge - expected_edge) <= 1e-12


def test_t06_p_hat_boundary_equals_ask_price(released_policy):
    """T06: when p_hat equals ask price, fee-inclusive edge is negative and excluded."""
    book = AskBook(
        levels=(
            (0.40, 100.0),  # q_eff = 0.412, edge = 0.2136 >= 0.02
            (0.50, 200.0),  # q_eff = 0.5125, edge = -0.0244 < 0.02 -> excluded
        )
    )
    p_hat = 0.50
    res = compute_probe(book=book, p_hat=p_hat, policy=released_policy)

    assert 1 not in res.qualified_levels
    assert res.qualified_levels == (0,)
    assert res.s_target == 100.0


def test_t07_no_qualified_levels_fails_closed(released_policy):
    """T07: no levels meeting min_edge raises NoQualifiedLevelsError (never returns 0)."""
    book = AskBook(levels=((0.55, 100.0), (0.60, 200.0)))
    p_hat = 0.50  # all edge_j <= -0.09 < 0.02
    with pytest.raises(NoQualifiedLevelsError):
        compute_probe(book=book, p_hat=p_hat, policy=released_policy)


def test_t08_load_penetration_policy_fails_with_pointer():
    """T08: load_penetration_policy raises F2LockNotReleasedError mentioning #156."""
    with pytest.raises(F2LockNotReleasedError) as exc_info:
        load_penetration_policy()
    assert "#156" in str(exc_info.value)


def test_t09_locked_policy_rejected_in_compute_probe():
    """T09: compute_probe raises F2LockNotReleasedError on externally crafted locked policy."""
    locked_policy = PenetrationPolicy(
        min_edge=0.02,
        provenance="tampered",
        lock_state=SigmaAdjLockState.LOCKED,
    )
    book = AskBook(levels=((0.40, 100.0),))
    with pytest.raises(F2LockNotReleasedError):
        compute_probe(book=book, p_hat=0.50, policy=locked_policy)

    locked_str_policy = PenetrationPolicy(
        min_edge=0.02,
        provenance="tampered",
        lock_state="F-2 LOCKED",  # type: ignore[arg-type]
    )
    with pytest.raises(F2LockNotReleasedError):
        compute_probe(book=book, p_hat=0.50, policy=locked_str_policy)


def test_t10_invalid_min_edge_rejected():
    """T10: negative or non-finite min_edge raises InvalidPenetrationPolicyError."""
    bad_edges = [-0.1, -1.0, float("nan"), float("inf"), float("-inf")]
    for bad_edge in bad_edges:
        with pytest.raises(InvalidPenetrationPolicyError):
            PenetrationPolicy(
                min_edge=bad_edge,
                provenance="test",
                lock_state=SigmaAdjLockState.RELEASED,
            )


def test_t11_invalid_p_hat_rejected(released_policy):
    """T11: p_hat outside (0, 1) or non-finite raises InvalidProbabilityError."""
    book = AskBook(levels=((0.40, 100.0),))
    bad_p_hats = [0.0, 1.0, -0.1, 1.5, float("nan"), float("inf")]
    for bad_p in bad_p_hats:
        with pytest.raises(InvalidProbabilityError):
            compute_probe(book=book, p_hat=bad_p, policy=released_policy)


def test_t12_invalid_order_book_structures():
    """T12: empty book, non-sorted, size <= 0, or price outside (0, 1) raises InvalidOrderBookError."""
    with pytest.raises(InvalidOrderBookError):
        AskBook(levels=())

    with pytest.raises(InvalidOrderBookError):
        AskBook(levels=((0.5, 0.0),))

    with pytest.raises(InvalidOrderBookError):
        AskBook(levels=((0.5, -10.0),))

    with pytest.raises(InvalidOrderBookError):
        AskBook(levels=((0.0, 100.0),))

    with pytest.raises(InvalidOrderBookError):
        AskBook(levels=((1.0, 100.0),))

    with pytest.raises(InvalidOrderBookError):
        AskBook(levels=((-0.1, 100.0),))

    with pytest.raises(InvalidOrderBookError):
        AskBook(levels=((0.45, 10.0), (0.40, 20.0)))

    with pytest.raises(InvalidOrderBookError):
        AskBook(levels=((0.40, 10.0), (0.40, 20.0)))


def test_t13_ast_float_literal_only_fee_base_ratio():
    """T13: penetration_probe.py float literal strictly restricted to {0.05} at constant."""
    target_path = Path("src/pricing/penetration_probe.py")
    tree = ast.parse(target_path.read_text(encoding="utf-8"))

    floats = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, float)
    ]
    assert len(floats) == 1, f"Found unexpected float constants: {floats}"
    assert floats[0] == 0.05

    top_assigns = [
        n
        for n in tree.body
        if (
            isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "FEE_BASE_RATIO" for t in n.targets)
        )
        or (isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == "FEE_BASE_RATIO")
    ]
    assert len(top_assigns) == 1


def test_t14_sub_min_edge_levels_invariant_exclusion(released_policy):
    """T14: invariant check ensuring every excluded level has fee-inclusive edge < min_edge."""
    book = AskBook(
        levels=(
            (0.40, 10.0),   # q_eff = 0.412, edge = 0.2136 >= 0.02 -> 0 qualifies
            (0.45, 30.0),   # q_eff = 0.462375, edge = 0.08137 >= 0.02 -> 1 qualifies
            (0.495, 40.0),  # q_eff = 0.50749875, edge = -0.01477 < 0.02 -> 2 excluded
            (0.55, 20.0),   # q_eff = 0.562375, edge = -0.1109 < 0.02 -> 3 excluded
        )
    )
    p_hat = 0.50
    res = compute_probe(book=book, p_hat=p_hat, policy=released_policy)

    assert res.qualified_levels == (0, 1)
    for idx, (price, size) in enumerate(book.levels):
        level_q_eff = price * (1.0 + FEE_BASE_RATIO * (1.0 - price))
        level_edge = (p_hat - level_q_eff) / level_q_eff
        if idx in res.qualified_levels:
            assert level_edge >= released_policy.min_edge
        else:
            assert level_edge < released_policy.min_edge


def test_t15_f2_error_inheritance_hierarchy():
    """T15: probe F2LockNotReleasedError inherits from both PenetrationError and SigmaAdjF2LockNotReleasedError."""
    assert issubclass(F2LockNotReleasedError, PenetrationError)
    assert issubclass(F2LockNotReleasedError, SigmaAdjF2LockNotReleasedError)
    assert issubclass(F2LockNotReleasedError, SigmaAdjError)
    assert F2LockNotReleasedError is PenetrationF2LockNotReleasedError
    assert issubclass(PenetrationF2LockNotReleasedError, ExportedF2LockNotReleasedError)


def test_t16_aggregate_edge_invariant_and_r1_r2_counterexamples(released_policy):
    """T16: R-1 fails closed to NoQualifiedLevelsError; R-2 capacity=300.0; aggregate edge >= min_edge."""
    # R-1: single level (0.50, 300.0) with p_hat=0.52 has q_eff=0.5125, edge=0.014634 < 0.02
    # Must raise NoQualifiedLevelsError instead of returning inconsistent s_target=300.0
    r1_book = AskBook(levels=((0.50, 300.0),))
    with pytest.raises(NoQualifiedLevelsError):
        compute_probe(book=r1_book, p_hat=0.52, policy=released_policy)

    # R-2: multilevel book ((0.40, 100), (0.45, 200), (0.50, 300)) with p_hat=0.52
    # Level 0 (0.40): q_eff=0.412, edge=0.2621 >= 0.02 (qualifies)
    # Level 1 (0.45): q_eff=0.462375, edge=0.1246 >= 0.02 (qualifies)
    # Level 2 (0.50): q_eff=0.5125, edge=0.01463 < 0.02 (excluded)
    r2_book = AskBook(levels=((0.40, 100.0), (0.45, 200.0), (0.50, 300.0)))
    r2_res = compute_probe(book=r2_book, p_hat=0.52, policy=released_policy)

    assert r2_res.qualified_levels == (0, 1)
    assert r2_res.s_target == 300.0
    expected_p_bar = (0.40 * 100.0 + 0.45 * 200.0) / 300.0
    assert abs(r2_res.p_bar - expected_p_bar) <= 1e-12
    assert r2_res.edge >= released_policy.min_edge
