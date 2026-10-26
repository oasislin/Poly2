#!/usr/bin/env python3
"""
scripts/trigger_model_retest.py:
Physical Model Retest Trigger & Contract Update Audit Pipeline.

Execution Pipeline (5 Stages):
1. Stage 1: 2019 Out-Of-Sample Settlement Evaluation (scripts/evaluate_p4_2019_settlement.py)
2. Stage 2: Category 2 V2.0 Evaluation Ruler Upgrade (scripts/audit_v2/reliability_v2.py)
3. Stage 3: 22-Cell Physical Parameter Contract Extraction (convert_csv_to_contract)
4. Stage 4: Read-Only Validator & Version Watchdog Dual Verification
5. Stage 5: M-5 Four-Tier Asset Reconciliation & Structured Audit Logging

Safety Interlocks (Fail-Closed):
- Default mode is --dry-run (simulation/preflight only).
- Real execution requires explicit --confirm-retest <WAIVER_ID> with a non-placeholder waiver.
- Zero bare exceptions; all errors mapped to RetestPipelineError family.
"""

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple, Union

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.contract.param_table_converter import (
    ContractConversionError,
    ContractGuardrailError,
    convert_csv_to_contract,
    export_contract_to_json,
)
from src.contract.param_table_validator import (
    PhysicalParamTableValidator,
)
from src.contract.parameter_contract import PhysicalParamContract
from src.contract.version_watchdog import (
    ContractVersionWatchdog,
    ManifestIntegrityError,
    PickleCorruptionError,
    SecurityViolationError,
    StaleModelParametersError,
    WatchdogVerificationReport,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("trigger_model_retest")


class RetestPipelineError(Exception):
    """Base exception for model retest pipeline failures."""
    pass


class RetestExecutionError(RetestPipelineError):
    """Raised when Stage 1 or Stage 2 execution subprocess fails."""
    pass


class RetestAuditError(RetestPipelineError):
    """Raised when Stage 3, 4, or 5 validation / audit fails."""
    pass


@dataclass
class RetestPipelineConfig:
    """Configuration for physical model retest pipeline."""
    project_root: Path = field(default_factory=lambda: PROJECT_ROOT)
    dry_run: bool = True
    waiver_id: str = ""
    metrics_csv: Path = field(default_factory=lambda: PROJECT_ROOT / "evidence" / "audit_v2" / "p4blind_v2r01_metrics.csv")
    comparison_csv: Path = field(default_factory=lambda: PROJECT_ROOT / "evidence" / "audit_v2" / "p4blind_v2r01_comparison.csv")
    manifest_path: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "models" / "manifest.json")
    contract_output: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "contracts" / "physical_param_contract.json")
    audit_output: Path = field(default_factory=lambda: PROJECT_ROOT / "evidence" / "audit_v2" / "retest_pipeline_audit.json")


def validate_waiver(waiver_id: str, dry_run: bool) -> None:
    """Validate that real execution possesses an explicit, non-placeholder waiver ID."""
    if dry_run:
        return
    cleaned = waiver_id.strip() if waiver_id else ""
    invalid_placeholders = {"", "TODO", "NONE", "PLACEHOLDER", "NULL", "UNDEFINED"}
    if not cleaned or cleaned.upper() in invalid_placeholders:
        raise RetestPipelineError(
            f"Real execution requires explicit valid --confirm-retest <WAIVER_ID>; received: '{waiver_id}'"
        )


def _to_rel_path(path: Union[str, Path], root: Path) -> str:
    """Convert path to workspace-relative path string for portable logging."""
    p = Path(path)
    try:
        return str(p.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(p)


def compute_file_sha256(path: Path) -> str:
    """Compute hex SHA256 of a file, returning missing indicator if absent."""
    if not path.is_file():
        return f"MISSING:{path.name}"
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_git_commit(cwd: Path) -> str:
    """Retrieve execution-time Git HEAD SHA256 (records invocation base commit)."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return "UNKNOWN_COMMIT"


def _compute_manifest_m5_counts(manifest_path: Path) -> Tuple[int, int]:
    """Calculate (trading_master_models, full_watchdog_models) from manifest."""
    try:
        content = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        raise RetestAuditError(f"Failed to read manifest for M-5 counting: {e}") from e

    models = content.get("models", {})
    full_count = 0
    master_count = 0
    auth_leads = {12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72}
    auth_stations = {"KORD", "KMIA"}

    for _, meta in models.items():
        st = meta.get("station")
        lead = meta.get("lead_hours")
        if st in auth_stations and lead in auth_leads:
            full_count += 1
            if meta.get("status") != "AUXILIARY_POOLED_FALLBACK":
                master_count += 1

    return master_count, full_count


def reconcile_m5_asset_counts(contract: PhysicalParamContract, manifest_path: Path) -> Dict[str, Any]:
    """Mechanically reconcile four-tier M-5 asset counts."""
    master_count, full_count = _compute_manifest_m5_counts(manifest_path)
    consumption_cells = len(contract.cells)
    model_weights = len(contract.model_weights_sha256)

    checks = {
        "statutory_consumption_cells": (consumption_cells, 22),
        "statutory_model_weights": (model_weights, 88),
        "trading_master_models": (master_count, 144),
        "full_watchdog_models": (full_count, 176),
    }

    for name, (observed, expected) in checks.items():
        if observed != expected:
            raise RetestAuditError(
                f"M-5 count mismatch: {name}={observed} != {expected}"
            )

    return {
        "statutory_consumption_cells": consumption_cells,
        "statutory_model_weights": model_weights,
        "trading_master_models": master_count,
        "full_watchdog_models": full_count,
        "all_passed": True,
    }


def _run_stage_subprocess(cmd: List[str], cwd: Path, stage_label: str) -> Dict[str, Any]:
    """Execute a stage subprocess with standard logging and error translation."""
    logger.info("[%s] Running: %s", stage_label, " ".join(cmd))
    try:
        subprocess.run(cmd, cwd=cwd, check=True)
    except subprocess.CalledProcessError as e:
        raise RetestExecutionError(f"{stage_label} failed with exit code {e.returncode}") from e
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as e:
        raise RetestExecutionError(f"{stage_label} invocation error: {e}") from e

    return {"status": "PASSED", "passed": True, "command": " ".join(cmd)}


def run_stage1_settlement(config: RetestPipelineConfig) -> Dict[str, Any]:
    """Execute Stage 1: 2019 out-of-sample settlement evaluation."""
    if config.dry_run:
        logger.info("[Stage 1] Skipped (dry-run simulation mode)")
        return {"status": "SKIPPED", "passed": None, "command": "SKIPPED", "reason": "dry_run mode"}

    cmd = [
        sys.executable,
        str(config.project_root / "scripts" / "evaluate_p4_2019_settlement.py"),
        "--execute-settlement",
        "--confirm-waiver",
        config.waiver_id,
    ]
    return _run_stage_subprocess(cmd, config.project_root, "Stage 1")


def run_stage2_ruler_upgrade(config: RetestPipelineConfig) -> Dict[str, Any]:
    """Execute Stage 2: Category 2 V2.0 evaluation ruler upgrade."""
    if config.dry_run:
        logger.info("[Stage 2] Skipped (dry-run simulation mode)")
        return {"status": "SKIPPED", "passed": None, "command": "SKIPPED", "reason": "dry_run mode"}

    cmd = [
        sys.executable,
        str(config.project_root / "scripts" / "audit_v2" / "reliability_v2.py"),
        "--run",
    ]
    return _run_stage_subprocess(cmd, config.project_root, "Stage 2")


def run_stage3_contract_conversion(config: RetestPipelineConfig) -> PhysicalParamContract:
    """Execute Stage 3: extract 22-cell parameters and export contract."""
    logger.info("[Stage 3] Extracting contract from CSVs: %s, %s", config.metrics_csv, config.comparison_csv)
    try:
        contract = convert_csv_to_contract(
            metrics_csv_path=config.metrics_csv,
            comparison_csv_path=config.comparison_csv,
            manifest_path=config.manifest_path,
        )
        if not config.dry_run:
            export_contract_to_json(contract, config.contract_output)
    except (ContractConversionError, ContractGuardrailError, KeyError, ValueError, TypeError, FileNotFoundError, OSError) as e:
        raise RetestAuditError(f"Stage 3 contract extraction failed: {e}") from e

    return contract


def run_stage4_gate_verification(
    contract: PhysicalParamContract,
    manifest_path: Path,
    contract_path: Optional[Path] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Execute Stage 4: validator schema check and watchdog SHA256 integrity."""
    logger.info("[Stage 4] Verifying contract schema & manifest watchdog")
    try:
        validator_ok = PhysicalParamTableValidator.validate(contract)
        if not dry_run and contract_path is not None and contract_path.exists():
            validator_ok = validator_ok and PhysicalParamTableValidator.validate_json(contract_path)
    except (ContractConversionError, ContractGuardrailError, ValueError, TypeError, FileNotFoundError, json.JSONDecodeError) as e:
        raise RetestAuditError(f"Stage 4 schema validation failed: {e}") from e

    try:
        watchdog = ContractVersionWatchdog(manifest_path=manifest_path, contract=contract)
        report: WatchdogVerificationReport = watchdog.check()
    except (ContractGuardrailError, ManifestIntegrityError, StaleModelParametersError,
            SecurityViolationError, PickleCorruptionError, FileNotFoundError) as e:
        raise RetestAuditError(f"Stage 4 watchdog verification error: {e}") from e

    if not report.is_valid:
        raise RetestAuditError(
            f"Watchdog check returned is_valid=False: failed_entries={report.failed_entries}"
        )

    return {
        "status": "PASSED",
        "passed": True,
        "validator_passed": validator_ok,
        "watchdog_passed": report.is_valid,
        "verified_cells_count": report.verified_cells_count,
        "skipped_6h_entries": report.skipped_6h_entries,
    }


def _collect_file_checksums(config: RetestPipelineConfig) -> Dict[str, str]:
    """Gather SHA256 checksums of all relevant pipeline assets."""
    files = {
        "evaluate_script": config.project_root / "scripts" / "evaluate_p4_2019_settlement.py",
        "reliability_script": config.project_root / "scripts" / "audit_v2" / "reliability_v2.py",
        "manifest_json": config.manifest_path,
        "settlement_stats_csv": config.project_root / "evidence" / "p4_2019_settlement_statistics.csv",
        "settlement_arrays_parquet": config.project_root / "data" / "processed" / "audit_arrays" / "2019_oos_p4_settlement_arrays.parquet",
        "metrics_csv": config.metrics_csv,
        "comparison_csv": config.comparison_csv,
        "contract_json": config.contract_output,
    }
    return {k: compute_file_sha256(v) for k, v in files.items()}


def run_stage5_audit_logging(
    config: RetestPipelineConfig,
    stage_results: Dict[str, Any],
    m5_results: Dict[str, Any],
    checksums: Dict[str, str],
) -> Path:
    """Execute Stage 5: structure and write pipeline audit record with relative paths."""
    all_stages_passed = (
        not config.dry_run
        and all(s.get("passed") is True for s in stage_results.values())
        and m5_results.get("all_passed") is True
    )

    audit_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": get_git_commit(config.project_root),
        "pipeline_mode": "dry-run" if config.dry_run else "execute",
        "status": "DRY_RUN_COMPLETED" if config.dry_run else ("PASSED" if all_stages_passed else "FAILED"),
        "waiver_id": config.waiver_id,
        "stages": stage_results,
        "asset_counts": {
            "statutory_consumption_cells": m5_results["statutory_consumption_cells"],
            "statutory_model_weights": m5_results["statutory_model_weights"],
            "trading_master_models": m5_results["trading_master_models"],
            "full_watchdog_models": m5_results["full_watchdog_models"],
        },
        "m5_reconciliation": m5_results,
        "file_checksums": checksums,
        "all_stages_passed": all_stages_passed if not config.dry_run else None,
    }

    try:
        config.audit_output.parent.mkdir(parents=True, exist_ok=True)
        config.audit_output.write_text(json.dumps(audit_data, indent=2), encoding="utf-8")
        logger.info("[Stage 5] Pipeline audit successfully written to %s", config.audit_output)
    except OSError as e:
        raise RetestAuditError(f"Stage 5 audit file writing failed: {e}") from e

    return config.audit_output


def execute_retest_pipeline(config: RetestPipelineConfig) -> Dict[str, Any]:
    """Orchestrate end-to-end 5-stage retest and audit pipeline."""
    validate_waiver(config.waiver_id, config.dry_run)
    stages: Dict[str, Any] = {}

    stages["stage1_settlement"] = run_stage1_settlement(config)
    stages["stage2_ruler_upgrade"] = run_stage2_ruler_upgrade(config)

    contract = run_stage3_contract_conversion(config)
    stages["stage3_contract_conversion"] = {
        "status": "PASSED",
        "passed": True,
        "metrics_csv": _to_rel_path(config.metrics_csv, config.project_root),
        "comparison_csv": _to_rel_path(config.comparison_csv, config.project_root),
        "output_json": _to_rel_path(config.contract_output, config.project_root),
    }

    stages["stage4_gate_verification"] = run_stage4_gate_verification(
        contract, config.manifest_path, config.contract_output, config.dry_run
    )

    m5_results = reconcile_m5_asset_counts(contract, config.manifest_path)
    stages["stage5_m5_reconciliation"] = m5_results

    checksums = _collect_file_checksums(config)
    audit_file = run_stage5_audit_logging(config, stages, m5_results, checksums)

    return {
        "all_stages_passed": (not config.dry_run),
        "pipeline_mode": "dry-run" if config.dry_run else "execute",
        "audit_file": _to_rel_path(audit_file, config.project_root),
        "asset_counts": m5_results,
    }


def parse_args() -> argparse.Namespace:
    """Parse command line flags."""
    parser = argparse.ArgumentParser(
        description="Physical Model Retest Trigger & Contract Update Audit Pipeline"
    )
    parser.add_argument(
        "--confirm-retest",
        type=str,
        default=None,
        help="Execute real retest pipeline with statutory waiver ID",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicitly request dry-run simulation mode (default)",
    )
    parser.add_argument(
        "--audit-output",
        type=str,
        default="",
        help="Custom path for audit JSON (defaults to evidence/audit_v2/retest_pipeline_audit.json)",
    )
    return parser.parse_args()


def main() -> None:
    """CLI Entry point with fail-closed error interlocks."""
    args = parse_args()
    has_confirm_flag = any(arg.startswith("--confirm-retest") for arg in sys.argv[1:])

    try:
        if has_confirm_flag:
            validate_waiver(args.confirm_retest, dry_run=False)
            dry_run = False
            waiver_id = args.confirm_retest
        else:
            dry_run = True
            waiver_id = ""

        audit_path = (
            Path(args.audit_output)
            if args.audit_output
            else (PROJECT_ROOT / "evidence" / "audit_v2" / "retest_pipeline_audit.json")
        )
        config = RetestPipelineConfig(
            dry_run=dry_run, waiver_id=waiver_id, audit_output=audit_path
        )
        summary = execute_retest_pipeline(config)
        print("\n" + "=" * 80)
        print("  RETEST PIPELINE AUDIT SUMMARY")
        print("=" * 80)
        print(f"  Pipeline Mode : {summary['pipeline_mode']}")
        print(f"  Audit Output  : {summary['audit_file']}")
        print(f"  M-5 Counts    : {summary['asset_counts']}")
        print("=" * 80)
    except RetestPipelineError as e:
        logger.error("Retest Pipeline FAILED: %s", e)
        print(f"\n[FAIL-CLOSED] Retest Pipeline Aborted: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
