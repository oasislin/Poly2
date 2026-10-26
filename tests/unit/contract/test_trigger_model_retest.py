"""
tests/unit/contract/test_trigger_model_retest.py:
Unit tests for the physical model retest trigger & audit pipeline.
Covers:
- Fail-closed waiver validation interlock
- Stage 1-4 failure propagation to RetestPipelineError family
- M-5 four-tier asset reconciliation (22 cells, 88 weights, 144 master, 176 full)
- Audit log JSON structure, relative paths, and checksum verification
- Standards compliance: skipped stages do not claim passed: true
- Watchdog anchor verification with contract object passed
"""

import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from scripts.trigger_model_retest import (
    RetestAuditError,
    RetestExecutionError,
    RetestPipelineConfig,
    RetestPipelineError,
    execute_retest_pipeline,
    reconcile_m5_asset_counts,
    run_stage1_settlement,
    run_stage2_ruler_upgrade,
    run_stage3_contract_conversion,
    run_stage4_gate_verification,
    validate_waiver,
)
from src.contract.param_table_converter import ContractConversionError
from src.contract.parameter_contract import PhysicalParamContract
from src.contract.version_watchdog import WatchdogVerificationReport


def test_validate_waiver_fails_when_real_execution_and_empty_waiver():
    """Real execution without waiver must fail-closed."""
    with pytest.raises(RetestPipelineError, match="Real execution requires explicit valid"):
        validate_waiver("", dry_run=False)


def test_validate_waiver_fails_when_placeholder_waiver():
    """Placeholder waiver values like TODO or NONE must fail-closed."""
    for placeholder in ["TODO", "NONE", "PLACEHOLDER", "   "]:
        with pytest.raises(RetestPipelineError, match="Real execution requires explicit valid"):
            validate_waiver(placeholder, dry_run=False)


def test_validate_waiver_passes_when_valid_waiver():
    """Valid waiver ID passes validation."""
    validate_waiver("P4-2019-OOS-SCOPE-WAIVER-001", dry_run=False)


def test_validate_waiver_passes_when_dry_run():
    """Dry-run does not require waiver."""
    validate_waiver("", dry_run=True)


def test_stage1_settlement_failure_raises_retest_execution_error(tmp_path):
    """Subprocess failure in Stage 1 must be mapped to RetestExecutionError."""
    config = RetestPipelineConfig(
        project_root=tmp_path,
        dry_run=False,
        waiver_id="P4-2019-OOS-SCOPE-WAIVER-001",
    )
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, ["cmd"])):
        with pytest.raises(RetestExecutionError, match="Stage 1 failed"):
            run_stage1_settlement(config)


def test_stage2_ruler_failure_raises_retest_execution_error(tmp_path):
    """Subprocess failure in Stage 2 must be mapped to RetestExecutionError."""
    config = RetestPipelineConfig(
        project_root=tmp_path,
        dry_run=False,
        waiver_id="P4-2019-OOS-SCOPE-WAIVER-001",
    )
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, ["cmd"])):
        with pytest.raises(RetestExecutionError, match="Stage 2 failed"):
            run_stage2_ruler_upgrade(config)


def test_stage3_conversion_failure_raises_retest_audit_error(tmp_path):
    """Contract conversion failure in Stage 3 must be mapped to RetestAuditError."""
    config = RetestPipelineConfig(
        project_root=tmp_path,
        dry_run=True,
        metrics_csv=tmp_path / "metrics.csv",
        comparison_csv=tmp_path / "comparison.csv",
    )
    with patch(
        "scripts.trigger_model_retest.convert_csv_to_contract",
        side_effect=ContractConversionError("conversion failed"),
    ):
        with pytest.raises(RetestAuditError, match="Stage 3 contract extraction failed"):
            run_stage3_contract_conversion(config)


def test_stage4_validator_failure_raises_retest_audit_error(tmp_path):
    """Validator failure in Stage 4 must be mapped to RetestAuditError."""
    mock_contract = MagicMock()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")

    with patch(
        "scripts.trigger_model_retest.PhysicalParamTableValidator.validate",
        side_effect=ContractConversionError("Schema invalid"),
    ):
        with pytest.raises(RetestAuditError, match="Stage 4 schema validation failed"):
            run_stage4_gate_verification(mock_contract, manifest_path)


def test_stage4_watchdog_failure_raises_retest_audit_error(tmp_path):
    """Watchdog report is_valid=False must raise RetestAuditError."""
    mock_contract = MagicMock()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")

    fake_report = WatchdogVerificationReport(
        is_valid=False,
        verified_cells_count=22,
        failed_entries=1,
        skipped_6h_entries=64,
        bypassed=False,
        checked_at="2026-10-26T12:00:00Z",
    )
    with patch("scripts.trigger_model_retest.PhysicalParamTableValidator.validate", return_value=True):
        with patch("scripts.trigger_model_retest.ContractVersionWatchdog.check", return_value=fake_report):
            with pytest.raises(RetestAuditError, match="Watchdog check returned is_valid=False"):
                run_stage4_gate_verification(mock_contract, manifest_path)


def test_stage4_watchdog_instantiates_with_contract(tmp_path):
    """Verify Stage 4 passes the contract object to ContractVersionWatchdog for anchor verification."""
    mock_contract = MagicMock()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")

    fake_report = WatchdogVerificationReport(
        is_valid=True,
        verified_cells_count=22,
        failed_entries=0,
        skipped_6h_entries=64,
        bypassed=False,
        checked_at="2026-10-26T12:00:00Z",
    )
    with patch("scripts.trigger_model_retest.PhysicalParamTableValidator.validate", return_value=True):
        with patch("scripts.trigger_model_retest.ContractVersionWatchdog") as mock_wd_cls:
            mock_wd_instance = MagicMock()
            mock_wd_instance.check.return_value = fake_report
            mock_wd_cls.return_value = mock_wd_instance

            res = run_stage4_gate_verification(mock_contract, manifest_path)
            assert res["status"] == "PASSED"
            mock_wd_cls.assert_called_once_with(manifest_path=manifest_path, contract=mock_contract)


def test_m5_reconciliation_exact_counts():
    """Verify real assets strictly conform to 22, 88, 144, 176 counts."""
    contract_path = Path("data/contracts/physical_param_contract.json")
    manifest_path = Path("data/models/manifest.json")
    assert contract_path.exists(), "Contract JSON must exist"
    assert manifest_path.exists(), "Manifest JSON must exist"

    raw_contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract = PhysicalParamContract.from_dict(raw_contract)

    result = reconcile_m5_asset_counts(contract, manifest_path)
    assert result["statutory_consumption_cells"] == 22
    assert result["statutory_model_weights"] == 88
    assert result["trading_master_models"] == 144
    assert result["full_watchdog_models"] == 176
    assert result["all_passed"] is True


def test_m5_reconciliation_failure_on_tampered_count():
    """Tampered contract count raises RetestAuditError."""
    mock_contract = MagicMock()
    mock_contract.cells = {f"cell_{i}": MagicMock() for i in range(21)}  # 21 instead of 22
    mock_contract.model_weights_sha256 = {f"m_{i}.pkl": "a" * 64 for i in range(88)}

    with pytest.raises(RetestAuditError, match="M-5 count mismatch: statutory_consumption_cells=21 != 22"):
        reconcile_m5_asset_counts(mock_contract, Path("data/models/manifest.json"))


def test_dry_run_full_pipeline_success(tmp_path):
    """Execute dry-run pipeline: verifies skipped stages do not claim passed: true."""
    audit_file = tmp_path / "retest_pipeline_audit.json"
    config = RetestPipelineConfig(
        dry_run=True,
        audit_output=audit_file,
    )
    summary = execute_retest_pipeline(config)
    assert summary["pipeline_mode"] == "dry-run"
    assert audit_file.exists()

    audit_data = json.loads(audit_file.read_text(encoding="utf-8"))
    # AGENTS.md rule: unexecuted stages must NOT claim passed: true
    assert audit_data["stages"]["stage1_settlement"]["status"] == "SKIPPED"
    assert audit_data["stages"]["stage1_settlement"]["passed"] is None
    assert audit_data["stages"]["stage2_ruler_upgrade"]["status"] == "SKIPPED"
    assert audit_data["stages"]["stage2_ruler_upgrade"]["passed"] is None
    assert audit_data["all_stages_passed"] is None
    assert audit_data["status"] == "DRY_RUN_COMPLETED"


def test_cli_execution_with_placeholder_waiver_fails_closed():
    """CLI execution with --confirm-retest TODO exits with code 1."""
    cmd = [sys.executable, "scripts/trigger_model_retest.py", "--confirm-retest", "TODO"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 1
    assert "Real execution requires explicit valid --confirm-retest <WAIVER_ID>" in res.stderr or "Real execution requires explicit valid" in res.stdout


def test_cli_execution_with_empty_waiver_fails_closed():
    """CLI execution with --confirm-retest '' exits with code 1."""
    cmd = [sys.executable, "scripts/trigger_model_retest.py", "--confirm-retest", ""]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 1
    assert "Real execution requires explicit valid --confirm-retest <WAIVER_ID>" in res.stderr or "Real execution requires explicit valid" in res.stdout


def test_cli_dry_run_exits_code_0():
    """CLI execution with default/dry-run exits with code 0."""
    cmd = [sys.executable, "scripts/trigger_model_retest.py", "--dry-run"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    assert "RETEST PIPELINE AUDIT SUMMARY" in res.stdout
