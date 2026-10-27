"""
Comprehensive unit tests for Q7 Coverage Dual-Track Separation (Ticket 06 / Phase 2 Task 08).
Enforces exact behavior equivalence, strict context isolation, and architectural decoupling.
"""

import ast
import json
import math
from pathlib import Path
import pytest

from scripts.evaluate_p4_2019_settlement import compute_model_90_coverage_bounds
from src.pricing.coverage_dual_track import (
    CoverageInterval,
    CoverageRate,
    CoverageTrackMisuseError,
    ExactCoverageTrack,
    GaussianProxyCoverageTrack,
    InvalidCoverageInputError,
    NOMINAL_INTERVAL_LEVEL,
    TrackContext,
    UnsupportedDistributionFamilyError,
    Z_90_HALF_WIDTH,
)


def test_t01_johnsonsu_bounds_vs_reference():
    """T01: johnsonsu exact bounds match settlement audit reference within 1e-12."""
    calib_path = Path("evidence/p4_active10_climate_calibration.json")
    with open(calib_path, "r", encoding="utf-8") as f:
        calib_data = json.load(f)

    shape_params = calib_data["KORD"]["seasons"]["Winter"]["shape_params"]
    mu, sigma_eff = 28.5, 3.2

    track = ExactCoverageTrack()
    exact_low, exact_high = track.bounds(
        mu=mu,
        sigma_eff=sigma_eff,
        family="johnsonsu",
        shape_params=shape_params,
        context=TrackContext.OFFLINE_AUDIT,
    )
    ref_low, ref_high = compute_model_90_coverage_bounds(
        mu=mu,
        sigma=sigma_eff,
        family="johnsonsu",
        shape_params=shape_params,
    )

    assert abs(exact_low - ref_low) <= 1e-12
    assert abs(exact_high - ref_high) <= 1e-12


def test_t02_evt_hybrid_bounds_exact_match():
    """T02: evt_hybrid bounds use u_left/u_right exactly matching reference convention."""
    shape_params = {"u_left": -2.45, "u_right": 2.15}
    mu, sigma_eff = 50.0, 4.0

    track = ExactCoverageTrack()
    low, high = track.bounds(
        mu=mu,
        sigma_eff=sigma_eff,
        family="evt_hybrid",
        shape_params=shape_params,
        context=TrackContext.OFFLINE_AUDIT,
    )
    ref_low, ref_high = compute_model_90_coverage_bounds(
        mu=mu,
        sigma=sigma_eff,
        family="evt_hybrid",
        shape_params=shape_params,
    )

    assert low == ref_low
    assert high == ref_high
    assert low == mu + sigma_eff * (-2.45)
    assert high == mu + sigma_eff * 2.15


def test_t03_gaussian_bounds_formula():
    """T03: gaussian bounds match mu +/- Z_90_HALF_WIDTH * sigma_eff within 1e-12."""
    mu, sigma_eff = 10.0, 2.0
    track = ExactCoverageTrack()
    low, high = track.bounds(
        mu=mu,
        sigma_eff=sigma_eff,
        family="gaussian",
        shape_params={},
        context=TrackContext.OFFLINE_AUDIT,
    )
    expected_low = mu - Z_90_HALF_WIDTH * sigma_eff
    expected_high = mu + Z_90_HALF_WIDTH * sigma_eff

    assert abs(low - expected_low) <= 1e-12
    assert abs(high - expected_high) <= 1e-12


def test_t04_gaussian_proxy_interval_formula():
    """T04: proxy interval matches mu +/- Z_90_HALF_WIDTH * sigma_eff within 1e-12."""
    mu, sigma_eff = 15.0, 3.5
    proxy = GaussianProxyCoverageTrack()
    interval = proxy.interval(
        mu=mu,
        sigma_eff=sigma_eff,
        context=TrackContext.ONLINE_PRICING,
    )

    expected_low = mu - Z_90_HALF_WIDTH * sigma_eff
    expected_high = mu + Z_90_HALF_WIDTH * sigma_eff

    assert abs(interval.lower - expected_low) <= 1e-12
    assert abs(interval.upper - expected_high) <= 1e-12
    assert interval.interval_level == NOMINAL_INTERVAL_LEVEL
    assert interval.interval_level == 0.9


def test_t05_exact_track_misuse_online_pricing():
    """T05: ExactCoverageTrack invoked or initialized with ONLINE_PRICING raises misuse."""
    track = ExactCoverageTrack()
    with pytest.raises(CoverageTrackMisuseError):
        track.bounds(
            mu=0.0,
            sigma_eff=1.0,
            family="gaussian",
            shape_params={},
            context=TrackContext.ONLINE_PRICING,
        )

    with pytest.raises(CoverageTrackMisuseError):
        track.bounds(
            mu=0.0,
            sigma_eff=1.0,
            family="gaussian",
            shape_params={},
            context="OFFLINE_AUDIT",  # type: ignore[arg-type]
        )

    with pytest.raises(CoverageTrackMisuseError):
        track.bounds(
            mu=0.0,
            sigma_eff=1.0,
            family="gaussian",
            shape_params={},
            context=None,  # type: ignore[arg-type]
        )

    with pytest.raises(CoverageTrackMisuseError):
        track.coverage(
            mu=0.0,
            sigma_eff=1.0,
            family="gaussian",
            shape_params={},
            observations=[0.0],
            context=TrackContext.ONLINE_PRICING,
        )

    with pytest.raises(CoverageTrackMisuseError):
        ExactCoverageTrack(context=TrackContext.ONLINE_PRICING)


def test_t06_gaussian_proxy_misuse_offline_audit():
    """T06: GaussianProxyCoverageTrack invoked or initialized with OFFLINE_AUDIT raises misuse."""
    proxy = GaussianProxyCoverageTrack()
    with pytest.raises(CoverageTrackMisuseError):
        proxy.interval(
            mu=0.0,
            sigma_eff=1.0,
            context=TrackContext.OFFLINE_AUDIT,
        )

    with pytest.raises(CoverageTrackMisuseError):
        proxy.interval(
            mu=0.0,
            sigma_eff=1.0,
            context="ONLINE_PRICING",  # type: ignore[arg-type]
        )

    with pytest.raises(CoverageTrackMisuseError):
        proxy.interval(
            mu=0.0,
            sigma_eff=1.0,
            context=None,  # type: ignore[arg-type]
        )

    with pytest.raises(CoverageTrackMisuseError):
        GaussianProxyCoverageTrack(context=TrackContext.OFFLINE_AUDIT)


def test_t07_type_isolation_no_field_cross_talk():
    """T07: CoverageInterval has no coverage_rate; CoverageRate has no lower/upper."""
    interval = CoverageInterval(lower=1.0, upper=2.0, interval_level=0.9)
    rate = CoverageRate(hits=9, total=10, coverage_rate=0.9, interval_level=0.9)

    with pytest.raises(AttributeError):
        _ = interval.coverage_rate  # type: ignore[attr-defined]

    with pytest.raises(AttributeError):
        _ = rate.lower  # type: ignore[attr-defined]

    with pytest.raises(AttributeError):
        _ = rate.upper  # type: ignore[attr-defined]


def test_t08_unsupported_family_rejection():
    """T08: unknown distribution family raises UnsupportedDistributionFamilyError."""
    track = ExactCoverageTrack()
    with pytest.raises(UnsupportedDistributionFamilyError):
        track.bounds(
            mu=0.0,
            sigma_eff=1.0,
            family="student_t",
            shape_params={},
            context=TrackContext.OFFLINE_AUDIT,
        )


def test_t09_invalid_sigma_eff_inputs():
    """T09: non-positive or non-finite sigma_eff raises InvalidCoverageInputError."""
    exact_track = ExactCoverageTrack()
    proxy_track = GaussianProxyCoverageTrack()
    invalid_sigmas = [0.0, -1.0, float("nan"), float("inf"), float("-inf")]

    for bad_sigma in invalid_sigmas:
        with pytest.raises(InvalidCoverageInputError):
            exact_track.bounds(
                mu=0.0,
                sigma_eff=bad_sigma,
                family="gaussian",
                shape_params={},
                context=TrackContext.OFFLINE_AUDIT,
            )
        with pytest.raises(InvalidCoverageInputError):
            proxy_track.interval(
                mu=0.0,
                sigma_eff=bad_sigma,
                context=TrackContext.ONLINE_PRICING,
            )


def test_t10_johnsonsu_missing_required_keys_raises_key_error():
    """T10: missing required keys in shape_params raises KeyError without fallback."""
    track = ExactCoverageTrack()

    # Missing 'gamma'
    bad_params = {"delta": 1.5, "xi": 0.0, "lambda": 1.0}
    with pytest.raises(KeyError):
        track.bounds(
            mu=0.0,
            sigma_eff=1.0,
            family="johnsonsu",
            shape_params=bad_params,
            context=TrackContext.OFFLINE_AUDIT,
        )

    # Missing 'u_right' in evt_hybrid
    with pytest.raises(KeyError):
        track.bounds(
            mu=0.0,
            sigma_eff=1.0,
            family="evt_hybrid",
            shape_params={"u_left": -2.0},
            context=TrackContext.OFFLINE_AUDIT,
        )


def test_t11_coverage_rate_perfect_and_zero_hits():
    """T11: coverage rate self-consistency for 100% and 0% empirical hits."""
    track = ExactCoverageTrack()
    mu, sigma = 10.0, 1.0

    # Bounds are ~ [8.355, 11.645]
    all_hits = track.coverage(
        mu=mu,
        sigma_eff=sigma,
        family="gaussian",
        shape_params={},
        observations=[9.0, 10.0, 11.0],
        context=TrackContext.OFFLINE_AUDIT,
    )
    assert all_hits.hits == 3
    assert all_hits.total == 3
    assert all_hits.coverage_rate == 1.0
    assert all_hits.interval_level == NOMINAL_INTERVAL_LEVEL
    assert all_hits.interval_level == 0.9

    zero_hits = track.coverage(
        mu=mu,
        sigma_eff=sigma,
        family="gaussian",
        shape_params={},
        observations=[0.0, 20.0],
        context=TrackContext.OFFLINE_AUDIT,
    )
    assert zero_hits.hits == 0
    assert zero_hits.total == 2
    assert zero_hits.coverage_rate == 0.0

    with pytest.raises(InvalidCoverageInputError):
        track.coverage(
            mu=mu,
            sigma_eff=sigma,
            family="gaussian",
            shape_params={},
            observations=[],
            context=TrackContext.OFFLINE_AUDIT,
        )


def test_t12_ast_decoupling_assertions():
    """T12: AST decoupling check ensuring proxy and exact tracks share no internal logic."""
    target_path = Path("src/pricing/coverage_dual_track.py")
    tree = ast.parse(target_path.read_text(encoding="utf-8"))

    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    assert "ExactCoverageTrack" in classes
    assert "GaussianProxyCoverageTrack" in classes

    exact_src = ast.unparse(classes["ExactCoverageTrack"])
    proxy_src = ast.unparse(classes["GaussianProxyCoverageTrack"])

    # Proxy track must NOT contain non-Gaussian distribution concepts
    assert "johnsonsu" not in proxy_src
    assert "shape_params" not in proxy_src
    assert "evt_hybrid" not in proxy_src
    assert "ExactCoverageTrack" not in proxy_src

    # Exact track must NOT contain proxy track references
    assert "GaussianProxyCoverageTrack" not in exact_src
    assert "CoverageInterval" not in exact_src


def test_t13_float_literal_whitelist():
    """T13: module float literals strictly restricted to specified whitelist."""
    target_path = Path("src/pricing/coverage_dual_track.py")
    tree = ast.parse(target_path.read_text(encoding="utf-8"))

    floats = {
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, float)
    }
    whitelist = {1.6448536269514722, 0.05, 0.95, 0.0}
    assert floats.issubset(whitelist), f"Unexpected floats found: {floats - whitelist}"


def test_t14_zero_hit_g5_literal_in_src_pricing():
    """T14: G5 gate literal 0.83 must have zero hits across src/pricing."""
    pricing_files = list(Path("src/pricing").glob("*.py"))
    assert len(pricing_files) >= 2, f"Expected >= 2 files, found {len(pricing_files)}"

    for py_file in pricing_files:
        content = py_file.read_text(encoding="utf-8")
        assert "0.83" not in content, f"Found 0.83 in {py_file}"
