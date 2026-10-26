"""
Security and anti-pollution integration tests for parameter contract (Ticket 05 / Phase 2 Task 08).
Enforces the four core defense barriers:
1. End-to-end version stamp tampering blocking (Fail-Closed).
2. End-to-end missing physical model file blocking (PickleCorruptionError).
3. Anti-global-averaging structural assertions (non-zero pvariance, zero magic numbers).
4. Station divergence heterogeneity assertions (KORD != KMIA without uncontrolled adjectives).
5. Anti-pollution static AST scan across active trading source modules.
6. Anti-pollution runtime model directory SHA256 zero drift verification.
7. Read-only deep frozen immutability assertions (MappingProxyType + Frozen dataclass).
8. End-to-end controlled parameter domain injection rejection.
"""

import ast
import copy
from dataclasses import FrozenInstanceError
import glob
import hashlib
import json
import os
from pathlib import Path
import pickle
import statistics
from typing import Any, Dict, List, Optional
import pytest

from src.contract.parameter_contract import (
    CellCalibrationRecord,
    PhysicalParamContract,
)
from src.contract.parameter_domains import ParameterDomainViolation
from src.contract.version_watchdog import (
    ContractVersionWatchdog,
    PickleCorruptionError,
    StaleModelParametersError,
)


def _setup_sandbox_models(
    tmp_path: Path,
    manifest_data: Dict[str, Any],
    tamper_file: Optional[str] = None,
    omit_file: Optional[str] = None,
) -> Path:
    """Helper to assemble a sandbox models directory without touching real data/models/."""
    tmp_manifest = tmp_path / "manifest.json"
    with open(tmp_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f)

    src_dir = Path("data/models")
    for fname in manifest_data["models"].keys():
        src_file = src_dir / fname
        if not src_file.exists() or fname == omit_file:
            continue
        dst_file = tmp_path / fname
        if fname == tamper_file:
            with open(dst_file, "wb") as mf:
                pickle.dump({"tampered": True}, mf)
        else:
            os.symlink(src_file.resolve(), dst_file)
    return tmp_manifest


def _load_contract_and_manifest():
    """Helper to load statutory contract, manifest data, and primary target model."""
    with open("data/contracts/physical_param_contract.json", "r", encoding="utf-8") as f:
        contract = PhysicalParamContract.from_dict(json.load(f))
    with open("data/models/manifest.json", "r", encoding="utf-8") as f:
        manifest_data = json.load(f)
    target_model_name = next(iter(contract.model_weights_sha256.keys()))
    return contract, manifest_data, target_model_name


def _compute_file_hashes(paths: List[str]) -> Dict[str, str]:
    """Helper to compute sha256 checksums for a list of file paths."""
    hashes = {}
    for p in paths:
        with open(p, "rb") as f:
            hashes[p] = hashlib.sha256(f.read()).hexdigest()
    return hashes


def test_tc_sec_01_version_tamper_blocks_transaction(tmp_path):
    """TC-SEC-01: 端到端版本戳篡改阻断：磁盘模型 SHA256 错配即刻抛 StaleModelParametersError。"""
    contract, manifest_data, target_model_name = _load_contract_and_manifest()
    tmp_manifest = _setup_sandbox_models(
        tmp_path, manifest_data, tamper_file=target_model_name
    )

    watchdog = ContractVersionWatchdog(manifest_path=tmp_manifest, contract=contract)
    with pytest.raises(StaleModelParametersError) as exc_info:
        watchdog.check()
    assert (
        target_model_name in str(exc_info.value)
        or "SHA256 mismatch" in str(exc_info.value)
    )


def test_tc_sec_02_missing_model_blocks_transaction(tmp_path):
    """TC-SEC-02: 端到端缺失模型文件阻断：删除任一授权模型即刻抛 PickleCorruptionError。"""
    contract, manifest_data, target_model_name = _load_contract_and_manifest()
    tmp_manifest = _setup_sandbox_models(
        tmp_path, manifest_data, omit_file=target_model_name
    )

    watchdog = ContractVersionWatchdog(manifest_path=tmp_manifest, contract=contract)
    with pytest.raises(PickleCorruptionError) as exc_info:
        watchdog.check()
    assert "Missing model parameter file" in str(exc_info.value)


def test_tc_sec_03_anti_global_averaging_heterogeneity():
    """TC-SEC-03: 防全局均值化断言：关键参数在 22 格中必须满足 pvariance > 0（零魔法数）。"""
    with open("data/contracts/physical_param_contract.json", "r", encoding="utf-8") as f:
        contract = PhysicalParamContract.from_dict(json.load(f))

    assert len(contract.cells) == 22, f"Expected exactly 22 cells, got {len(contract.cells)}"
    target_fields = ["s_oos", "ece_2f", "v1_coverage_90", "pit_mean"]
    for field_name in target_fields:
        vals = [getattr(cell, field_name) for cell in contract.cells.values()]
        assert len(vals) == 22, f"Expected 22 values for '{field_name}', got {len(vals)}"
        var = statistics.pvariance(vals)
        assert var > 0, f"Field '{field_name}' degenerated to global constant"


def test_tc_sec_04_station_divergence_heterogeneity():
    """TC-SEC-04: 双站分化特性断言：KORD 与 KMIA 在同一 lead 下至少存在一个时效取值不相等。"""
    with open("data/contracts/physical_param_contract.json", "r", encoding="utf-8") as f:
        contract = PhysicalParamContract.from_dict(json.load(f))

    leads = [12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72]
    target_fields = ["s_oos", "ece_2f", "v1_coverage_90"]

    for field_name in target_fields:
        diff_count = sum(
            1
            for lead in leads
            if getattr(contract.cells[("KORD", lead)], field_name)
            != getattr(contract.cells[("KMIA", lead)], field_name)
        )
        assert (
            diff_count >= 1
        ), f"Field '{field_name}' shows zero divergence between stations"


def test_tc_sec_05_anti_pollution_static_ast_scan():
    """TC-SEC-05: 防污染静态 AST 扫描：src/contract/ 与 src/risk/ 绝无向 data/models/ 写入的代码。"""
    active_sources = glob.glob("src/contract/*.py") + glob.glob("src/risk/*.py")
    assert (
        len(active_sources) >= 8
    ), f"Expected >= 8 active source files, found {len(active_sources)}"

    write_modes = {"w", "wb", "a", "ab", "w+", "wb+"}
    write_methods = {"write", "write_text", "write_bytes", "dump", "to_pickle"}
    for file_path in active_sources:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=file_path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr

            call_source = ast.unparse(node)
            has_models = "data/models" in call_source or "models_dir" in call_source

            has_write_mode = any(
                isinstance(a, ast.Constant) and a.value in write_modes
                for a in node.args
            ) or any(
                kw.arg == "mode"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value in write_modes
                for kw in node.keywords
            )

            assert not (
                func_name == "open" and has_models and has_write_mode
            ), f"Prohibited write to data/models in {file_path}:{node.lineno}"
            assert not (
                func_name in write_methods and has_models
            ), f"Prohibited dump to data/models in {file_path}:{node.lineno}"


def test_tc_sec_06_anti_pollution_runtime_hash_zero_drift():
    """TC-SEC-06: 防污染运行时哈希零漂移：真正读取 data/models/ 后，断言全部模型哈希 100% 保持不变。"""
    model_files = glob.glob("data/models/*.pkl") + ["data/models/manifest.json"]
    assert (
        len(model_files) >= 1200
    ), f"Expected >= 1200 model files, found {len(model_files)}"

    before_hashes = _compute_file_hashes(model_files)

    with open("data/contracts/physical_param_contract.json", "r", encoding="utf-8") as f:
        contract = PhysicalParamContract.from_dict(json.load(f))
    watchdog = ContractVersionWatchdog(contract=contract)
    report = watchdog.check()
    assert report.is_valid is True

    after_hashes = _compute_file_hashes(model_files)

    assert (
        before_hashes == after_hashes
    ), "Anti-pollution violation: hash drift detected in data/models!"


def test_tc_sec_07_read_only_deep_frozen_immutability():
    """TC-SEC-07: 只读字典防篡改（深冻结）：修改 MappingProxyType 抛 TypeError，修改属性抛 FrozenInstanceError。"""
    with open("data/contracts/physical_param_contract.json", "r", encoding="utf-8") as f:
        contract = PhysicalParamContract.from_dict(json.load(f))

    cell_key = ("KORD", 12)
    cell = contract.cells[cell_key]

    with pytest.raises(TypeError):
        contract.cells[cell_key] = cell

    with pytest.raises(TypeError):
        contract.model_weights_sha256["KORD_Winter_Max_lead12h.pkl"] = "a" * 64

    with pytest.raises(FrozenInstanceError):
        contract.manifest_sha256 = "b" * 64

    with pytest.raises(FrozenInstanceError):
        cell.s_oos = 99.0


def test_tc_sec_08_controlled_domain_end_to_end_injection_rejection():
    """TC-SEC-08: 受控域端到端集成拦截：反序列化非法脏值契约时即刻抛 ParameterDomainViolation / ValueError。"""
    with open("data/contracts/physical_param_contract.json", "r", encoding="utf-8") as f:
        base_data = json.load(f)

    bad_injections = [
        ("s_oos", -1.0),
        ("pit_var", -1.0),
        ("pit_var", 0.2501),
        ("v1_coverage_90", 1.5),
        ("neff", 0.0),
        ("cvm_p", 1.2),
        ("ece_range", 1.5001),
    ]

    for bad_field, bad_val in bad_injections:
        payload = copy.deepcopy(base_data)
        payload["cells"]["KORD_12h"][bad_field] = bad_val
        with pytest.raises((ParameterDomainViolation, ValueError)):
            PhysicalParamContract.from_dict(payload)
