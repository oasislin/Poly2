"""
Unit test suite for adaptive variance inflation sigma_adj engine (Phase 2 Task 08 - Ticket 07).
Validates ADR-0019 §4 formula compliance, F-2 lock state enforcement, boundary defenses, and zero float AST gate.
"""

import ast
import json
import math
from pathlib import Path
import pytest

from src.contract.parameter_contract import PhysicalParamContract
from src.pricing.sigma_adj import (
    ADR_SIGMA_ADJ_REFERENCE,
    CellRecordProtocol,
    F2LockNotReleasedError,
    InvalidSigmaAdjInputError,
    InvalidSigmaAdjPolicyError,
    ParameterContractProtocol,
    SigmaAdjLockState,
    SigmaAdjPolicy,
    compute_sigma_adj,
    load_sigma_adj_policy,
    sigma_adj_for_cell,
)


@pytest.fixture
def released_policy() -> SigmaAdjPolicy:
    """Fixture providing a mock released policy matching ADR-0019 §4 baseline."""
    return SigmaAdjPolicy(
        exponent=0.5,
        floor=1.0,
        provenance="unit_test_released_policy",
        lock_state="F2_RELEASED",
    )


@pytest.fixture
def physical_contract() -> PhysicalParamContract:
    """Load authorized 22-cell physical parameter contract."""
    contract_path = Path("data/contracts/physical_param_contract.json")
    with contract_path.open("r", encoding="utf-8") as fp:
        raw_dict = json.load(fp)
    return PhysicalParamContract.from_dict(raw_dict)


def test_t01_22_cells_real_s_oos_full_comparison(released_policy, physical_contract):
    """T01: compare sigma_adj against math.sqrt(max(1.0, s_oos)) across all 22 cells."""
    assert len(physical_contract.cells) == 22
    sigma_eff = 2.0

    for (station, lead_hours), cell in physical_contract.cells.items():
        val = compute_sigma_adj(s_oos=cell.s_oos, sigma_eff=sigma_eff, policy=released_policy)
        expected = math.sqrt(max(1.0, cell.s_oos)) * sigma_eff
        assert abs(val - expected) <= 1e-12, f"Cell ({station}, {lead_hours}) mismatch: {val} vs {expected}"


def test_t02_kord_below_one_exact_equality(released_policy, physical_contract):
    """T02: KORD cells with s_oos < 1.0 have sigma_adj == sigma_eff (exact equality)."""
    sub_one_cells = [
        ("KORD", 12),
        ("KORD", 36),
        ("KORD", 60),
        ("KORD", 66),
    ]
    sigma_eff = 2.5

    for station, lead in sub_one_cells:
        cell = physical_contract.get_cell(station, lead)
        assert cell.s_oos < 1.0
        sigma_adj = compute_sigma_adj(s_oos=cell.s_oos, sigma_eff=sigma_eff, policy=released_policy)
        assert sigma_adj == sigma_eff


def test_t03_kmia_30h_maximum_ratio(released_policy, physical_contract):
    """T03: KMIA_30h achieves maximum ratio 1.167832 within 1e-6."""
    cell = physical_contract.get_cell("KMIA", 30)
    assert cell.s_oos == pytest.approx(1.363831, abs=1e-6)

    sigma_eff = 1.0
    sigma_adj = compute_sigma_adj(s_oos=cell.s_oos, sigma_eff=sigma_eff, policy=released_policy)
    ratio = sigma_adj / sigma_eff
    assert abs(ratio - 1.167832) <= 1e-6


def test_t04_s_oos_unity_exact_equality(released_policy):
    """T04: s_oos = 1.0 produces exact equality sigma_adj == sigma_eff."""
    sigma_eff = 3.2
    sigma_adj = compute_sigma_adj(s_oos=1.0, sigma_eff=sigma_eff, policy=released_policy)
    assert sigma_adj == sigma_eff


def test_t05_s_oos_monotonically_non_decreasing(released_policy):
    """T05: sigma_adj is monotonically non-decreasing over s_oos domain."""
    s_oos_series = [0.0, 0.5, 1.0, 1.2, 1.5, 2.0]
    sigma_eff = 2.0
    values = [
        compute_sigma_adj(s_oos=s, sigma_eff=sigma_eff, policy=released_policy)
        for s in s_oos_series
    ]

    for i in range(len(values) - 1):
        assert values[i] <= values[i + 1]


def test_t06_s_oos_zero_floor_protection(released_policy):
    """T06: s_oos = 0.0 produces sigma_adj == sigma_eff via floor protection."""
    sigma_eff = 4.0
    sigma_adj = compute_sigma_adj(s_oos=0.0, sigma_eff=sigma_eff, policy=released_policy)
    assert sigma_adj == sigma_eff


def test_t07_sigma_eff_scaling_homogeneity(released_policy):
    """T07: doubling sigma_eff doubles sigma_adj exactly."""
    s_oos = 1.4
    base_sigma_eff = 2.0
    val_1 = compute_sigma_adj(s_oos=s_oos, sigma_eff=base_sigma_eff, policy=released_policy)
    val_2 = compute_sigma_adj(s_oos=s_oos, sigma_eff=base_sigma_eff * 2.0, policy=released_policy)
    assert (val_2 / val_1) == pytest.approx(2.0, abs=1e-12)


def test_t08_policy_degeneration_to_adr0019(released_policy):
    """T08: (0.5, 1.0) policy degenerates to ADR-0019 §4 formula within 1e-12."""
    test_cases = [0.2, 0.8, 1.0, 1.35, 1.8, 2.5]
    sigma_eff = 1.8

    for s in test_cases:
        calculated = compute_sigma_adj(s_oos=s, sigma_eff=sigma_eff, policy=released_policy)
        adr_formula = math.sqrt(max(1.0, s)) * sigma_eff
        assert abs(calculated - adr_formula) <= 1e-12


def test_t09_invalid_sigma_eff_inputs(released_policy):
    """T09: non-positive or non-finite sigma_eff raises InvalidSigmaAdjInputError."""
    bad_sigmas = [0.0, -1.0, float("nan"), float("inf"), float("-inf")]
    for bad_val in bad_sigmas:
        with pytest.raises(InvalidSigmaAdjInputError):
            compute_sigma_adj(s_oos=1.0, sigma_eff=bad_val, policy=released_policy)


def test_t10_invalid_s_oos_inputs(released_policy):
    """T10: negative or non-finite s_oos raises InvalidSigmaAdjInputError."""
    bad_s_oos = [-1.0, float("nan"), float("inf"), float("-inf")]
    for bad_val in bad_s_oos:
        with pytest.raises(InvalidSigmaAdjInputError):
            compute_sigma_adj(s_oos=bad_val, sigma_eff=1.0, policy=released_policy)


def test_t11_sigma_adj_for_cell_unknown_station(released_policy, physical_contract):
    """T11: sigma_adj_for_cell raises KeyError on unknown cell without fallback."""
    with pytest.raises(KeyError):
        sigma_adj_for_cell(
            contract=physical_contract,
            station="KATL",
            lead_hours=12,
            sigma_eff=1.0,
            policy=released_policy,
        )


def test_t12_22_cells_no_cross_cell_aggregation(released_policy, physical_contract):
    """T12: sigma_adj_for_cell matches compute_sigma_adj per cell within 1e-12."""
    for (station, lead_hours), cell in physical_contract.cells.items():
        cell_adj = sigma_adj_for_cell(
            contract=physical_contract,
            station=station,
            lead_hours=lead_hours,
            sigma_eff=2.0,
            policy=released_policy,
        )
        direct_adj = compute_sigma_adj(
            s_oos=cell.s_oos,
            sigma_eff=2.0,
            policy=released_policy,
        )
        assert abs(cell_adj - direct_adj) <= 1e-12


def test_t13_load_policy_fails_with_f2_lock():
    """T13: load_sigma_adj_policy raises F2LockNotReleasedError with #156 pointer."""
    with pytest.raises(F2LockNotReleasedError) as exc_info:
        load_sigma_adj_policy()
    assert "#156" in str(exc_info.value)


def test_t14_external_hardcoded_locked_policy_rejected():
    """T14: external policy with lock_state='F-2 LOCKED' is rejected by compute_sigma_adj."""
    locked_policy = SigmaAdjPolicy(
        exponent=0.5,
        floor=1.0,
        provenance="tampered_external",
        lock_state="F-2 LOCKED",
    )
    with pytest.raises(F2LockNotReleasedError):
        compute_sigma_adj(s_oos=1.2, sigma_eff=1.0, policy=locked_policy)

    enum_locked_policy = SigmaAdjPolicy(
        exponent=0.5,
        floor=1.0,
        provenance="tampered_external",
        lock_state=SigmaAdjLockState.LOCKED,
    )
    with pytest.raises(F2LockNotReleasedError):
        compute_sigma_adj(s_oos=1.2, sigma_eff=1.0, policy=enum_locked_policy)


def test_t15_invalid_policy_attributes_rejected():
    """T15: invalid exponent, floor, or lock_state raises InvalidSigmaAdjPolicyError."""
    # Exponent <= 0 or non-finite
    with pytest.raises(InvalidSigmaAdjPolicyError):
        SigmaAdjPolicy(exponent=0.0, floor=1.0, provenance="t", lock_state="F2_RELEASED")
    with pytest.raises(InvalidSigmaAdjPolicyError):
        SigmaAdjPolicy(exponent=-0.5, floor=1.0, provenance="t", lock_state="F2_RELEASED")
    with pytest.raises(InvalidSigmaAdjPolicyError):
        SigmaAdjPolicy(exponent=float("nan"), floor=1.0, provenance="t", lock_state="F2_RELEASED")

    # Floor < 1.0 or non-finite
    with pytest.raises(InvalidSigmaAdjPolicyError):
        SigmaAdjPolicy(exponent=0.5, floor=0.9, provenance="t", lock_state="F2_RELEASED")
    with pytest.raises(InvalidSigmaAdjPolicyError):
        SigmaAdjPolicy(exponent=0.5, floor=-1.0, provenance="t", lock_state="F2_RELEASED")
    with pytest.raises(InvalidSigmaAdjPolicyError):
        SigmaAdjPolicy(exponent=0.5, floor=float("inf"), provenance="t", lock_state="F2_RELEASED")

    # Lock state not allowed
    with pytest.raises(InvalidSigmaAdjPolicyError):
        SigmaAdjPolicy(exponent=0.5, floor=1.0, provenance="t", lock_state="RELEASED")
    with pytest.raises(InvalidSigmaAdjPolicyError):
        SigmaAdjPolicy(exponent=0.5, floor=1.0, provenance="t", lock_state="")


def test_t16_ast_zero_float_literal_in_sigma_adj():
    """T16: mechanical verification that src/pricing/sigma_adj.py contains 0 float literals."""
    target_path = Path("src/pricing/sigma_adj.py")
    tree = ast.parse(target_path.read_text(encoding="utf-8"))
    floats = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, float)
    ]
    assert len(floats) == 0, f"Found forbidden float literals in {target_path}: {floats}"


def test_no_namespace_leak():
    """D-1 gate: sigma_adj defines __all__ with no leaked modules or typing symbols."""
    import src.pricing.sigma_adj as m

    assert hasattr(m, "__all__"), "模块缺少 __all__"
    assert not ({"Enum", "Protocol", "dataclass", "math"} & set(m.__all__)), "标准库符号泄漏"


def test_lock_state_normalized():
    """D-2 gate: string lock_state is normalized to SigmaAdjLockState enum in __post_init__."""
    p = SigmaAdjPolicy(exponent=0.5, floor=1.0, provenance="t", lock_state="F2_RELEASED")
    assert isinstance(p.lock_state, SigmaAdjLockState)
    assert p.lock_state is SigmaAdjLockState.RELEASED
    p2 = SigmaAdjPolicy(exponent=0.5, floor=1.0, provenance="t", lock_state="F-2 LOCKED")
    assert p2.lock_state is SigmaAdjLockState.LOCKED
