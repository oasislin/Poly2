"""
Unit tests for physical parameter domain governance (Ticket 26 / ADR-0019 Appendix A).
Validates:
- Tier 1 mathematical domain enforcement (Fail-Closed).
- Tier 2 effective domain schema & F-2 lock enforcement.
- Cross-field invariant CF-1 (fstd_lo < fstd_hi).
- Integration delegation via CellCalibrationRecord.__post_init__.
- AST gates (G-AST-1, G-AST-2, G-AST-3).
- Mechanical field coverage derivation without manual drift.
"""

import ast
from dataclasses import fields
import glob
import json
import math
from pathlib import Path
from typing import Any, Dict
import pytest

from src.contract.parameter_contract import (
    CellCalibrationRecord,
)
from src.contract.parameter_domains import (
    CrossFieldInvariantViolation,
    F2LockNotReleasedError,
    IDENTITY_FIELDS,
    PARAMETER_DOMAINS,
    ParameterDomainViolation,
    describe_domains,
    get_domain,
    require_effective_domain,
    validate_cell_parameters,
    validate_parameter,
)


def _make_valid_cell_dict() -> Dict[str, Any]:
    """Helper returning a dictionary representation of a valid 22-grid cell."""
    return {
        "station": "KORD",
        "lead_hours": 12,
        "variable": "tmax",
        "s_oos": 1.052,
        "fstd_lo": 0.825,
        "fstd_hi": 1.215,
        "fstd_in": True,
        "ece_2f": 0.0115,
        "v1_coverage_90": 0.915,
        "v1_coverage_90_pass": True,
        "pit_mean": 0.502,
        "pit_var": 0.0841,
        "reject_uniform": False,
        "neff": 312.5,
        "cvm_stat": 0.045,
        "cvm_p": 0.82,
        "ece_range": 0.013,
    }


def test_t01_real_contract_cells_satisfy_domain_validation():
    """T01: 真实产物 22 格全字段 validate_cell_parameters 返回 True（只读，不写回）。"""
    contract_path = Path("data/contracts/physical_param_contract.json")
    assert contract_path.exists(), "physical_param_contract.json must exist"
    with open(contract_path, "r", encoding="utf-8") as f:
        contract = json.load(f)

    cells = contract["cells"]
    assert len(cells) == 22, f"Expected 22 cells, found {len(cells)}"
    for cell_key, cell_data in cells.items():
        assert (
            validate_cell_parameters(cell_data) is True
        ), f"Cell {cell_key} failed domain validation"


def test_t02_s_oos_negative_rejected():
    """T02: s_oos = -1.0 必须被拒（方差比必须 >= 0）。"""
    with pytest.raises(ParameterDomainViolation):
        validate_parameter("s_oos", -1.0)


def test_t03_pit_var_negative_rejected():
    """T03: pit_var = -1.0 必须被拒（方差必须 >= 0）。"""
    with pytest.raises(ParameterDomainViolation):
        validate_parameter("pit_var", -1.0)


def test_t04_pit_var_upper_bound_closed():
    """T04: pit_var = 0.25 必须接受（Popoviciu 不等式上界为闭区间）。"""
    assert validate_parameter("pit_var", 0.25) is True


def test_t05_pit_var_upper_bound_exceeded_rejected():
    """T05: pit_var = 0.2501 必须被拒（超出 Popoviciu 不等式上界 0.25）。"""
    with pytest.raises(ParameterDomainViolation):
        validate_parameter("pit_var", 0.2501)


def test_t06_v1_coverage_90_exceeded_rejected():
    """T06: v1_coverage_90 = 1.5 必须被拒（覆盖率必须 <= 1.0）。"""
    with pytest.raises(ParameterDomainViolation):
        validate_parameter("v1_coverage_90", 1.5)


def test_t07_ece_2f_high_value_accepted_math_domain():
    """T07: ece_2f = 0.9 必须接受（证明是数学定义域而非业务质量阈值）。"""
    assert validate_parameter("ece_2f", 0.9) is True


def test_t08_neff_zero_rejected_open_bound():
    """T08: neff = 0.0 必须被拒（有效样本量下界为开区间）。"""
    with pytest.raises(ParameterDomainViolation):
        validate_parameter("neff", 0.0)


def test_t09_neff_strictly_positive_accepted():
    """T09: neff = 1e-9 必须接受（严格正即落入定义域）。"""
    assert validate_parameter("neff", 1e-9) is True


def test_t10_cvm_p_bounds_rejected_and_accepted():
    """T10: cvm_p = 1.2 拒绝，cvm_p = 0.0 接受（概率测度双闭 [0, 1]）。"""
    with pytest.raises(ParameterDomainViolation):
        validate_parameter("cvm_p", 1.2)
    assert validate_parameter("cvm_p", 0.0) is True
    assert validate_parameter("cvm_p", 1.0) is True


def test_t11_ece_range_exceeded_rejected():
    """T11: ece_range = 1.5001 必须被拒（ECE 必须 <= 1.0）。"""
    with pytest.raises(ParameterDomainViolation):
        validate_parameter("ece_range", 1.5001)


def test_t12_nan_and_inf_rejected():
    """T12: s_oos = NaN / +inf 独立拦截，不依赖上游 parser。"""
    with pytest.raises(ParameterDomainViolation):
        validate_parameter("s_oos", float("nan"))
    with pytest.raises(ParameterDomainViolation):
        validate_parameter("s_oos", float("inf"))
    with pytest.raises(ParameterDomainViolation):
        validate_parameter("s_oos", float("-inf"))


def test_t13_unknown_field_name_rejected():
    """T13: 未知字段名抛 ParameterDomainViolation，禁止静默跳过。"""
    with pytest.raises(ParameterDomainViolation):
        validate_parameter("s_oos_v2", 1.0)
    with pytest.raises(ParameterDomainViolation):
        get_domain("non_existent_field")


def test_t14_bool_field_strict_type_enforcement():
    """T14: 布尔字段传 1 / 'true' / 1.0 必须抛 ParameterDomainViolation。"""
    for bad_value in [1, 0, "true", "True", "False", 1.0, 0.0]:
        with pytest.raises(ParameterDomainViolation):
            validate_parameter("fstd_in", bad_value)
        with pytest.raises(ParameterDomainViolation):
            validate_parameter("v1_coverage_90_pass", bad_value)
        with pytest.raises(ParameterDomainViolation):
            validate_parameter("reject_uniform", bad_value)


def test_t15_cross_field_invariant_cf1():
    """T15: fstd_lo == fstd_hi 及 fstd_lo > fstd_hi 必须抛 CrossFieldInvariantViolation。"""
    rec_equal = _make_valid_cell_dict()
    rec_equal["fstd_lo"] = 1.0
    rec_equal["fstd_hi"] = 1.0
    with pytest.raises(CrossFieldInvariantViolation):
        validate_cell_parameters(rec_equal)

    rec_inverted = _make_valid_cell_dict()
    rec_inverted["fstd_lo"] = 1.2
    rec_inverted["fstd_hi"] = 0.8
    with pytest.raises(CrossFieldInvariantViolation):
        validate_cell_parameters(rec_inverted)


def test_t16_require_effective_domain_locked():
    """T16: require_effective_domain('s_oos') 必须抛 F2LockNotReleasedError，消息含 F-2 LOCKED。"""
    with pytest.raises(F2LockNotReleasedError) as exc_info:
        require_effective_domain("s_oos")
    assert "F-2 LOCKED" in str(exc_info.value)
    assert "Phase 2 Task 08 - Ticket 23" in str(exc_info.value)


def test_t17_describe_domains_contract_audit():
    """T17: describe_domains() 返回 14 项，状态受控且 Tier 2 全部为 None。"""
    domains = describe_domains()
    assert len(domains) == 14
    for d in domains:
        assert d["consume_status"] in {"必须消费", "间接消费", "不消费"}
        assert d["tier2_lower"] is None
        assert d["tier2_upper"] is None
        assert "definition_source" in d and len(d["definition_source"]) > 0


def test_t18_contract_integration_from_dict_delegation():
    """T18: 契约层集成：CellCalibrationRecord.from_dict 传 s_oos=-1.0 抛 ValueError。"""
    bad_data = _make_valid_cell_dict()
    bad_data["s_oos"] = -1.0
    with pytest.raises(ValueError):
        CellCalibrationRecord.from_dict(bad_data)


def test_t19_ast_gates_compliance():
    """T19: 机械核验 G-AST-1 / G-AST-2 / G-AST-3 门禁。"""
    # G-AST-1: src/contract/ 下除 parameter_domains.py 外所有 .py 的浮点字面量 == 0
    contract_py_files = glob.glob("src/contract/*.py")
    assert len(contract_py_files) >= 4, (
        f"G-AST-1 scan target hazard: expected >= 4 contract files, found {len(contract_py_files)}"
    )
    for file_path in contract_py_files:
        if file_path.endswith("parameter_domains.py"):
            continue
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=file_path)
        float_literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, float)
        ]
        assert (
            len(float_literals) == 0
        ), f"G-AST-1 violation in {file_path}: found floats {float_literals}"

    # G-AST-2: parameter_domains.py 内浮点字面量集合 ⊆ {0.0, 0.25, 1.0}
    with open("src/contract/parameter_domains.py", "r", encoding="utf-8") as f:
        domains_tree = ast.parse(f.read())
    domain_floats = {
        node.value
        for node in ast.walk(domains_tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, float)
    }
    allowed_floats = {0.0, 0.25, 1.0}
    assert domain_floats.issubset(
        allowed_floats
    ), f"G-AST-2 violation: {domain_floats - allowed_floats}"

    # G-AST-3: parameter_domains.py import 仅来自 stdlib
    allowed_modules = {"dataclasses", "types", "typing", "math"}
    for node in ast.walk(domains_tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert (
                    alias.name in allowed_modules
                ), f"G-AST-3 violation: import {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            assert (
                node.module in allowed_modules
            ), f"G-AST-3 violation: from {node.module} import ..."


def test_t20_parameter_domains_derived_coverage():
    """T20: PARAMETER_DOMAINS 键集合机械派生，必须完全等于 14 个受控字段。"""
    record_fields = {f.name for f in fields(CellCalibrationRecord)}
    identity_set = set(IDENTITY_FIELDS)
    controlled_fields = record_fields - identity_set

    assert len(controlled_fields) == 14
    assert set(PARAMETER_DOMAINS.keys()) == controlled_fields


def test_t21_regression_v1_coverage_90_admissible():
    """T21: 回归断言：v1_coverage_90=0.884615 且 pass=True 正常通过（未引入 0.90 推导）。"""
    cell_data = _make_valid_cell_dict()
    cell_data["v1_coverage_90"] = 0.884615
    cell_data["v1_coverage_90_pass"] = True
    rec = CellCalibrationRecord.from_dict(cell_data)
    assert rec.v1_coverage_90 == 0.884615
    assert rec.v1_coverage_90_pass is True
