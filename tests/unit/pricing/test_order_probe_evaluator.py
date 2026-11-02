"""
Cross-Module Contract & Integration Tests for Pricing Layer (Phase 2 Task 08 - Ticket 09).
Validates dual-track coverage three non-mixing rules, performance latency,
sigma_adj calibration consistency, and orderbook penetration probe EV invariants.
"""

import ast
import json
import math
from pathlib import Path
import statistics
import time
from typing import Any, Dict, List, Tuple
import pytest

from scripts.evaluate_p4_2019_settlement import compute_model_90_coverage_bounds
from src.contract.parameter_contract import PhysicalParamContract
from src.pricing import (
    FEE_BASE_RATIO,
    NOMINAL_INTERVAL_LEVEL,
    Z_90_HALF_WIDTH,
    AskBook,
    CoverageInterval,
    CoverageRate,
    CoverageTrackMisuseError,
    ExactCoverageTrack,
    GaussianProxyCoverageTrack,
    NoQualifiedLevelsError,
    PenetrationError,
    PenetrationF2LockNotReleasedError,
    PenetrationPolicy,
    SigmaAdjError,
    SigmaAdjLockState,
    SigmaAdjPolicy,
    TrackContext,
    compute_probe,
    compute_sigma_adj,
    load_penetration_policy,
    load_sigma_adj_policy,
    sigma_adj_for_cell,
)
from src.pricing.sigma_adj import F2LockNotReleasedError as SigmaAdjF2LockNotReleasedError


@pytest.fixture
def released_probe_policy() -> PenetrationPolicy:
    """Fixture providing released test penetration policy with 2% min_edge."""
    return PenetrationPolicy(
        min_edge=0.02,
        provenance="unit_test_released_probe_policy",
        lock_state=SigmaAdjLockState.RELEASED,
    )


@pytest.fixture
def released_sigma_policy() -> SigmaAdjPolicy:
    """Fixture providing released test sigma_adj policy matching ADR-0019 baseline."""
    return SigmaAdjPolicy(
        exponent=0.5,
        floor=1.0,
        provenance="unit_test_released_sigma_policy",
        lock_state=SigmaAdjLockState.RELEASED,
    )


def test_t01_track_context_misuse_prevention():
    """T01: bounds, coverage, and interval reject conflicting, None, or string contexts."""
    exact = ExactCoverageTrack()
    proxy = GaussianProxyCoverageTrack()
    shape_dummy: Dict[str, Any] = {"gamma": 0.0, "delta": 1.0, "xi": 0.0, "lambda": 1.0}

    # Exact track rejects ONLINE_PRICING, None, and bare strings
    with pytest.raises(CoverageTrackMisuseError):
        exact.bounds(70.0, 2.0, "gaussian", shape_dummy, context=TrackContext.ONLINE_PRICING)
    with pytest.raises(CoverageTrackMisuseError):
        exact.bounds(70.0, 2.0, "gaussian", shape_dummy, context=None)  # type: ignore[arg-type]
    with pytest.raises(CoverageTrackMisuseError):
        exact.bounds(70.0, 2.0, "gaussian", shape_dummy, context="OFFLINE_AUDIT")  # type: ignore[arg-type]

    with pytest.raises(CoverageTrackMisuseError):
        exact.coverage(70.0, 2.0, "gaussian", shape_dummy, [71.0], context=TrackContext.ONLINE_PRICING)
    with pytest.raises(CoverageTrackMisuseError):
        exact.coverage(70.0, 2.0, "gaussian", shape_dummy, [71.0], context=None)  # type: ignore[arg-type]
    with pytest.raises(CoverageTrackMisuseError):
        exact.coverage(70.0, 2.0, "gaussian", shape_dummy, [71.0], context="OFFLINE_AUDIT")  # type: ignore[arg-type]

    # Proxy track rejects OFFLINE_AUDIT, None, and bare strings
    with pytest.raises(CoverageTrackMisuseError):
        proxy.interval(70.0, 2.0, context=TrackContext.OFFLINE_AUDIT)
    with pytest.raises(CoverageTrackMisuseError):
        proxy.interval(70.0, 2.0, context=None)  # type: ignore[arg-type]
    with pytest.raises(CoverageTrackMisuseError):
        proxy.interval(70.0, 2.0, context="ONLINE_PRICING")  # type: ignore[arg-type]


def test_t02_track_construction_context_enforcement():
    """T02: constructor enforces allowed track context and rejects crossed or invalid contexts."""
    # Cross-track context rejected at construction
    with pytest.raises(CoverageTrackMisuseError):
        ExactCoverageTrack(context=TrackContext.ONLINE_PRICING)
    with pytest.raises(CoverageTrackMisuseError):
        GaussianProxyCoverageTrack(context=TrackContext.OFFLINE_AUDIT)

    # Bare string and invalid type rejected at construction
    with pytest.raises(CoverageTrackMisuseError):
        ExactCoverageTrack(context="OFFLINE_AUDIT")  # type: ignore[arg-type]
    with pytest.raises(CoverageTrackMisuseError):
        GaussianProxyCoverageTrack(context="ONLINE_PRICING")  # type: ignore[arg-type]

    # Legitimate matching context instantiates successfully
    exact_inst = ExactCoverageTrack(context=TrackContext.OFFLINE_AUDIT)
    proxy_inst = GaussianProxyCoverageTrack(context=TrackContext.ONLINE_PRICING)
    assert exact_inst.allowed_context == TrackContext.OFFLINE_AUDIT
    assert proxy_inst.allowed_context == TrackContext.ONLINE_PRICING


def test_t03_track_types_and_ast_subtree_isolation():
    """T03: output types have disjoint fields, classes do not inherit, and AST subtrees are strictly disjoint."""
    interval = CoverageInterval(lower=68.0, upper=72.0, interval_level=NOMINAL_INTERVAL_LEVEL)
    rate = CoverageRate(hits=9, total=10, coverage_rate=0.9, interval_level=NOMINAL_INTERVAL_LEVEL)

    assert not hasattr(interval, "coverage_rate")
    assert not hasattr(rate, "lower")
    assert not hasattr(rate, "upper")
    assert not issubclass(ExactCoverageTrack, GaussianProxyCoverageTrack)
    assert not issubclass(GaussianProxyCoverageTrack, ExactCoverageTrack)

    source = Path("src/pricing/coverage_dual_track.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}

    exact_ids = {
        n.id if isinstance(n, ast.Name) else n.attr
        for n in ast.walk(classes["ExactCoverageTrack"])
        if isinstance(n, (ast.Name, ast.Attribute))
    }
    proxy_ids = {
        n.id if isinstance(n, ast.Name) else n.attr
        for n in ast.walk(classes["GaussianProxyCoverageTrack"])
        if isinstance(n, (ast.Name, ast.Attribute))
    }

    assert proxy_ids.isdisjoint({"johnsonsu", "shape_params", "evt_hybrid", "ExactCoverageTrack"})
    assert exact_ids.isdisjoint({"GaussianProxyCoverageTrack", "CoverageInterval"})


def test_t04_exact_track_bounds_equivalence_with_settlement_script():
    """T04: exact bounds match scripts/evaluate_p4_2019_settlement within 1e-12 across 3 families."""
    calib_path = Path("evidence/p4_active10_climate_calibration.json")
    with calib_path.open("r", encoding="utf-8") as fp:
        calib = json.load(fp)

    family_samples: Dict[str, Tuple[str, str, Dict[str, Any]]] = {}
    for st, sdata in calib.items():
        for season, cdata in sdata.get("seasons", {}).items():
            fam = cdata.get("selected_family")
            if fam and fam not in family_samples:
                family_samples[fam] = (st, season, cdata.get("shape_params"))

    assert set(family_samples.keys()) == {"johnsonsu", "evt_hybrid", "gaussian"}

    exact = ExactCoverageTrack()
    mu = 72.5
    sigma_eff = 2.15
    for fam, (st, season, params) in family_samples.items():
        exp_low, exp_high = compute_model_90_coverage_bounds(mu, sigma_eff, fam, params)
        act_low, act_high = exact.bounds(mu, sigma_eff, fam, params, context=TrackContext.OFFLINE_AUDIT)
        assert abs(act_low - exp_low) <= 1e-12, f"Low mismatch for {fam} ({st}_{season}): {act_low} vs {exp_low}"
        assert abs(act_high - exp_high) <= 1e-12, f"High mismatch for {fam} ({st}_{season}): {act_high} vs {exp_high}"


def test_t05_gaussian_proxy_interval_formula_and_nominal_level():
    """T05: proxy interval matches mu +/- Z_90 * sigma_eff within 1e-12 and level repr is exactly '0.9'."""
    proxy = GaussianProxyCoverageTrack()
    mu = 68.75
    sigma_eff = 1.85
    res = proxy.interval(mu, sigma_eff, context=TrackContext.ONLINE_PRICING)

    half_width = Z_90_HALF_WIDTH * sigma_eff
    expected_lower = mu - half_width
    expected_upper = mu + half_width

    assert abs(res.lower - expected_lower) <= 1e-12, f"Lower bound: {res.lower} vs {expected_lower}"
    assert abs(res.upper - expected_upper) <= 1e-12, f"Upper bound: {res.upper} vs {expected_upper}"
    assert res.interval_level == NOMINAL_INTERVAL_LEVEL
    assert repr(res.interval_level) == "0.9", f"interval_level repr was {repr(res.interval_level)}"


def test_t06_dual_track_latency_p50_benchmark():
    """T06: dual tracks achieve p50 <= 10,000 ns across N=20,000 iterations using perf_counter_ns."""
    exact = ExactCoverageTrack()
    proxy = GaussianProxyCoverageTrack()
    shape = {"gamma": 0.1, "delta": 1.5, "xi": 0.0, "lambda": 1.0}

    # Warmup
    for _ in range(1000):
        exact.bounds(70.0, 2.0, "johnsonsu", shape, context=TrackContext.OFFLINE_AUDIT)
        proxy.interval(70.0, 2.0, context=TrackContext.ONLINE_PRICING)

    exact_ns: List[int] = []
    proxy_ns: List[int] = []
    for _ in range(20000):
        t0 = time.perf_counter_ns()
        exact.bounds(70.0, 2.0, "johnsonsu", shape, context=TrackContext.OFFLINE_AUDIT)
        t1 = time.perf_counter_ns()
        exact_ns.append(t1 - t0)

        t2 = time.perf_counter_ns()
        proxy.interval(70.0, 2.0, context=TrackContext.ONLINE_PRICING)
        t3 = time.perf_counter_ns()
        proxy_ns.append(t3 - t2)

    exact_p50 = float(statistics.median(exact_ns))
    exact_p90 = float(sorted(exact_ns)[int(0.9 * len(exact_ns))])
    proxy_p50 = float(statistics.median(proxy_ns))
    proxy_p90 = float(sorted(proxy_ns)[int(0.9 * len(proxy_ns))])

    assert exact_p50 <= 10000.0, f"Exact p50 exceeded: {exact_p50} ns (p90: {exact_p90} ns)"
    assert proxy_p50 <= 10000.0, f"Proxy p50 exceeded: {proxy_p50} ns (p90: {proxy_p90} ns)"


def test_t07_sigma_adj_22_cells_ratio_and_kmia_max_expansion(released_sigma_policy):
    """T07: 22 cells match ADR-0019 square root inflation within 1e-12 and KMIA_30h ratio is 1.167832."""
    contract_path = Path("data/contracts/physical_param_contract.json")
    with contract_path.open("r", encoding="utf-8") as fp:
        contract = PhysicalParamContract.from_dict(json.load(fp))

    assert len(contract.cells) == 22
    kmia_ratio = None
    for (st, lead), cell in contract.cells.items():
        sigma_adj = sigma_adj_for_cell(contract, st, lead, sigma_eff=2.0, policy=released_sigma_policy)
        ratio = sigma_adj / 2.0
        expected_ratio = math.sqrt(max(1.0, cell.s_oos))
        assert abs(ratio - expected_ratio) <= 1e-12, f"Cell ({st}, {lead}) ratio mismatch: {ratio} vs {expected_ratio}"
        if st == "KMIA" and lead == 30:
            kmia_ratio = ratio

    assert kmia_ratio is not None, "KMIA_30h was not found in contract cells"
    assert f"{kmia_ratio:.6f}" == "1.167832", f"KMIA_30h formatted ratio: {kmia_ratio:.8f}"


def test_t08_sigma_adj_overconfidence_floor_invariance(released_sigma_policy):
    """T08: overconfident cells with s_oos < 1.0 preserve exact equality sigma_adj == sigma_eff."""
    contract_path = Path("data/contracts/physical_param_contract.json")
    with contract_path.open("r", encoding="utf-8") as fp:
        contract = PhysicalParamContract.from_dict(json.load(fp))

    overconfident = [
        (st, lead, cell) for (st, lead), cell in contract.cells.items() if cell.s_oos < 1.0
    ]
    assert len(overconfident) == 4
    expected_cells = {("KORD", 12), ("KORD", 36), ("KORD", 60), ("KORD", 66)}
    assert {(st, lead) for st, lead, _ in overconfident} == expected_cells

    for st, lead, _ in overconfident:
        sigma_adj = sigma_adj_for_cell(contract, st, lead, sigma_eff=2.0, policy=released_sigma_policy)
        assert sigma_adj == 2.0, f"Overconfident cell ({st}, {lead}) adjusted {sigma_adj} != 2.0"


def test_t09_sigma_adj_f2_lock_rejection_and_policy_boundary():
    """T09: load_sigma_adj_policy raises with #156, and compute_sigma_adj rejects locked policies."""
    with pytest.raises(SigmaAdjF2LockNotReleasedError) as exc_info:
        load_sigma_adj_policy()
    assert "#156" in str(exc_info.value)

    pol_enum = SigmaAdjPolicy(exponent=0.5, floor=1.0, provenance="t", lock_state=SigmaAdjLockState.LOCKED)
    with pytest.raises(SigmaAdjF2LockNotReleasedError):
        compute_sigma_adj(s_oos=1.2, sigma_eff=2.0, policy=pol_enum)

    pol_str = SigmaAdjPolicy(exponent=0.5, floor=1.0, provenance="t", lock_state="F-2 LOCKED")  # type: ignore[arg-type]
    with pytest.raises(SigmaAdjF2LockNotReleasedError):
        compute_sigma_adj(s_oos=1.2, sigma_eff=2.0, policy=pol_str)


def test_t10_probe_qualification_depth_and_average_price(released_probe_policy):
    """T10: probe qualification depth, s_target, and p_bar match exact analytical formula."""
    book = AskBook(levels=((0.40, 100.0), (0.45, 200.0), (0.50, 300.0)))

    # Case 1: p_hat = 0.52 -> only levels 0 and 1 qualify under fee-inclusive edge
    r1 = compute_probe(book, p_hat=0.52, policy=released_probe_policy)
    assert r1.qualified_levels == (0, 1)
    assert r1.s_target == 300.0
    expected_p_bar_1 = (0.40 * 100.0 + 0.45 * 200.0) / 300.0
    assert abs(r1.p_bar - expected_p_bar_1) <= 1e-12

    # Case 2: p_hat = 0.60 -> all 3 levels qualify
    r2 = compute_probe(book, p_hat=0.60, policy=released_probe_policy)
    assert r2.qualified_levels == (0, 1, 2)
    assert r2.s_target == 600.0
    expected_p_bar_2 = 280.0 / 600.0
    assert abs(r2.p_bar - expected_p_bar_2) <= 1e-12


def test_t11_probe_fee_inclusive_edge_and_aggregation_monotonicity(released_probe_policy):
    """T11: R-1 fails closed to NoQualifiedLevelsError, and >= 3 books satisfy edge >= min_edge."""
    r1_book = AskBook(levels=((0.50, 300.0),))
    with pytest.raises(NoQualifiedLevelsError):
        compute_probe(r1_book, p_hat=0.52, policy=released_probe_policy)

    test_books = [
        (AskBook(levels=((0.40, 100.0), (0.45, 200.0), (0.50, 300.0))), 0.52),
        (AskBook(levels=((0.35, 50.0), (0.42, 150.0), (0.48, 250.0))), 0.55),
        (AskBook(levels=((0.20, 80.0), (0.30, 120.0))), 0.40),
    ]
    for book, p_hat in test_books:
        res = compute_probe(book, p_hat=p_hat, policy=released_probe_policy)
        assert res.edge >= released_probe_policy.min_edge, f"edge {res.edge} < {released_probe_policy.min_edge}"
        expected_edge = (p_hat - res.q_eff) / res.q_eff
        assert abs(res.edge - expected_edge) <= 1e-12, f"edge formula diff: {res.edge} vs {expected_edge}"


def test_t12_probe_f2_lock_dual_inheritance_and_rejection():
    """T12: probe F-2 lock raises with #156, rejects locked policies, and verifies dual inheritance."""
    with pytest.raises(PenetrationF2LockNotReleasedError) as exc_info:
        load_penetration_policy()
    assert "#156" in str(exc_info.value)
    assert isinstance(exc_info.value, PenetrationError)
    assert isinstance(exc_info.value, SigmaAdjF2LockNotReleasedError)
    assert issubclass(PenetrationF2LockNotReleasedError, PenetrationError)
    assert issubclass(PenetrationF2LockNotReleasedError, SigmaAdjF2LockNotReleasedError)

    book = AskBook(levels=((0.40, 100.0),))
    pol_enum = PenetrationPolicy(min_edge=0.02, provenance="t", lock_state=SigmaAdjLockState.LOCKED)
    with pytest.raises(PenetrationF2LockNotReleasedError):
        compute_probe(book, p_hat=0.50, policy=pol_enum)

    pol_str = PenetrationPolicy(min_edge=0.02, provenance="t", lock_state="F-2 LOCKED")  # type: ignore[arg-type]
    with pytest.raises(PenetrationF2LockNotReleasedError):
        compute_probe(book, p_hat=0.50, policy=pol_str)
