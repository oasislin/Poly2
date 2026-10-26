#!/usr/bin/env python3
"""
Physical Model Version Watchdog (ADR-0019 §二.6 / Ticket 02 / Phase 2 Task 08).

Implements startup-time fail-closed verification of physical model parameter files
and manifest.json checksums. Guarantees that:
- Deployed .pkl binaries match exactly the declared SHA256 in manifest.json.
- Injected contract manifest anchor matches canonical manifest SHA256.
- Injected contract model weights hashes match active binaries (Fail-Closed).
- All 22 statutory calibration grid cells (KORD/KMIA * 11 lead hours) are verified.
- 6h lead models are explicitly excluded from blocking enforcement (WARN-only).
- Defense-in-depth security: production bypass is strictly prohibited.
- Zero cross-layer dependencies (self-contained exception hierarchy).
"""

import hashlib
import json
import logging
import os
import pickle
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple, Union

from src.contract.parameter_contract import (
    AUTHORIZED_LEAD_HOURS,
    AUTHORIZED_STATIONS,
    TOTAL_AUTHORIZED_CELLS,
    PhysicalParamContract,
)

logger = logging.getLogger(__name__)

# Contract schema version (NOT model weights version).
# Bump ONLY when PhysicalParamContract dataclass fields change.
# MUST remain stable across EMOS retraining or manifest rebuilds.
CONTRACT_VERSION: str = "ADR-0019-Ticket01-v1"

# Explicitly EXCLUDES 6h lead per ADR-0019 / Ticket 01.
# Manifest may contain 6h models for KORD/KMIA but they are NOT part of the
# statutory consumption matrix. 6h drift → WARN-only, not blocking.
AUTHORIZED_LEADS_FOR_GUARD: Tuple[int, ...] = (
    AUTHORIZED_LEAD_HOURS  # EXPLICITLY EXCLUDES 6h per ADR-0019
)


class ContractGuardrailError(Exception):
    """契约层安全门禁与看门狗校验基类异常（零跨层依赖）."""

    pass


class StaleModelParametersError(ContractGuardrailError):
    """SHA256 不匹配或版本过旧 → 陈旧参数注入."""

    pass


class PickleCorruptionError(ContractGuardrailError):
    """文件缺失 / 0 字节 / pickle 损坏 / manifest 无法解析."""

    pass


class SecurityViolationError(ContractGuardrailError):
    """生产环境非法绕过."""

    pass


@dataclass(frozen=True)
class WatchdogVerificationReport:
    """看门狗校验结果（不可变）."""

    is_valid: bool
    verified_cells_count: int
    failed_entries: int
    skipped_6h_entries: int
    bypassed: bool
    checked_at: str


class ContractVersionWatchdog:
    """
    Physical model version watchdog implementing ADR-0019 §二.6.
    Ensures active model binaries and manifest.json match expected SHA256 hashes
    and adhere to the 22 statutory time x city calibration grid.
    """

    def __init__(
        self,
        manifest_path: Union[str, Path] = "data/models/manifest.json",
        contract: Optional[PhysicalParamContract] = None,
    ) -> None:
        self.manifest_path = Path(manifest_path)
        self.contract = contract

    def check(
        self, *, skip_when_env: Optional[str] = None
    ) -> WatchdogVerificationReport:
        """
        Verify manifest checksums and physical model parameter binaries.
        Executes three defense lines and a four-step fail-closed workflow.
        """
        bypass_report = self._handle_bypass_defense(skip_when_env)
        if bypass_report is not None:
            return bypass_report

        manifest = self._load_manifest()
        canonical_sha256 = self._compute_canonical_manifest_sha256(manifest)
        self._verify_contract_anchors(canonical_sha256)

        verified_cells_count, skipped_6h = self._verify_model_weights(manifest)

        return WatchdogVerificationReport(
            is_valid=True,
            verified_cells_count=verified_cells_count,
            failed_entries=0,
            skipped_6h_entries=skipped_6h,
            bypassed=False,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )

    def _handle_bypass_defense(
        self, skip_when_env: Optional[str]
    ) -> Optional[WatchdogVerificationReport]:
        """Enforce production mutual exclusion and test environment bypass."""
        poly_env = (os.environ.get("POLY_ENV") or "").lower()
        is_production = poly_env in ("production", "prod")

        if skip_when_env is None:
            return None

        if is_production:
            raise SecurityViolationError(
                f"Cannot bypass contract watchdog in production environment (POLY_ENV='{poly_env}')"
            )

        if os.environ.get(skip_when_env) == "1":
            logger.critical(
                "[ContractWatchdog] TEST BYPASS ACTIVATED via env '%s' - STRICTLY PROHIBITED IN PRODUCTION",
                skip_when_env,
            )
            return WatchdogVerificationReport(
                is_valid=True,
                verified_cells_count=0,
                failed_entries=0,
                skipped_6h_entries=0,
                bypassed=True,
                checked_at=datetime.now(timezone.utc).isoformat(),
            )

        return None

    def _load_manifest(self) -> Dict[str, Any]:
        """Load manifest.json from disk with structural fail-closed assertions."""
        if not self.manifest_path.exists():
            raise PickleCorruptionError(f"Manifest file not found: {self.manifest_path}")

        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, ValueError) as exc:
            raise PickleCorruptionError(
                f"Failed to parse manifest JSON at {self.manifest_path}: {exc}"
            ) from exc

        if not isinstance(manifest, dict):
            raise PickleCorruptionError(
                f"Manifest root must be a JSON object, got {type(manifest).__name__}"
            )

        if "models" not in manifest or not isinstance(manifest["models"], dict):
            raise PickleCorruptionError("Manifest missing 'models' dictionary")

        return manifest

    @staticmethod
    def _compute_canonical_manifest_sha256(manifest: Dict[str, Any]) -> str:
        """Compute canonical, deterministic SHA256 of manifest dictionary."""
        serialized = json.dumps(
            manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    def _verify_contract_anchors(self, canonical_sha256: str) -> None:
        """Verify injected contract version and manifest SHA256 anchors."""
        if self.contract is None:
            return

        if self.contract.contract_version != CONTRACT_VERSION:
            raise StaleModelParametersError(
                f"Contract contract_version mismatch: "
                f"expected='{CONTRACT_VERSION}', actual='{self.contract.contract_version}'"
            )

        if self.contract.manifest_sha256 != canonical_sha256:
            raise StaleModelParametersError(
                f"Contract manifest_sha256 mismatch: "
                f"expected='{self.contract.manifest_sha256}', actual='{canonical_sha256}'"
            )

    def _verify_model_weights(
        self, manifest: Dict[str, Any]
    ) -> Tuple[int, int]:
        """
        Verify physical model binaries across statutory grid cells against manifest.
        Tracks distinct (station, lead_hours) cell coverage.
        Returns (distinct_verified_cells_count, skipped_6h_count).
        """
        models = manifest["models"]
        seen_cells: Set[Tuple[str, int]] = set()
        skipped_6h = 0

        for fname, meta in models.items():
            if not isinstance(meta, dict):
                raise PickleCorruptionError(
                    f"Model entry '{fname}' metadata must be a dictionary"
                )

            station = str(meta["station"]).upper()
            lead = int(meta["lead_hours"])

            if station not in AUTHORIZED_STATIONS:
                continue

            if lead not in AUTHORIZED_LEADS_FOR_GUARD:
                if lead == 6:
                    logger.warning(
                        "[ContractWatchdog] 6h lead model SKIPPED from betting contract verification: "
                        "station=%s, model=%s",
                        station,
                        fname,
                    )
                    skipped_6h += 1
                continue

            cell_key = f"{station}_{lead}h"
            self._verify_single_model_file(fname, meta, cell_key)
            seen_cells.add((station, lead))

        expected_total = TOTAL_AUTHORIZED_CELLS  # 22
        if len(seen_cells) != expected_total:
            raise ContractGuardrailError(
                f"Incomplete statutory cell coverage: verified={len(seen_cells)} "
                f"expected={expected_total} (missing {expected_total - len(seen_cells)} cells)"
            )

        return len(seen_cells), skipped_6h

    def _verify_single_model_file(
        self, fname: str, meta: Dict[str, Any], cell_key: str
    ) -> None:
        """Verify existence, size, pickle integrity, and SHA256 for a single model file."""
        file_path = self.manifest_path.parent / fname

        if not file_path.exists():
            raise PickleCorruptionError(
                f"Missing model parameter file declared in manifest: {file_path}"
            )

        if file_path.stat().st_size == 0:
            raise PickleCorruptionError(
                f"Model parameter file is 0 bytes corrupt: {file_path}"
            )

        with open(file_path, "rb") as f:
            content = f.read()

        try:
            pickle.loads(content)
        except (pickle.UnpicklingError, EOFError, AttributeError, ValueError, TypeError) as exc:
            raise PickleCorruptionError(
                f"Failed to unpickle model file (corrupt): {file_path}: {exc}"
            ) from exc

        actual_sha256 = hashlib.sha256(content).hexdigest().lower()
        declared_sha256 = str(meta["sha256"]).lower()
        if actual_sha256 != declared_sha256:
            raise StaleModelParametersError(
                f"Model SHA256 mismatch for '{fname}': "
                f"expected='{declared_sha256}', actual='{actual_sha256}'"
            )

        if self.contract is not None and self.contract.model_weights_sha256:
            if cell_key not in self.contract.model_weights_sha256:
                raise StaleModelParametersError(
                    f"Contract model_weights_sha256 missing cell '{cell_key}': "
                    f"expected in contract model_weights_sha256"
                )
            expected_contract_sha = str(
                self.contract.model_weights_sha256[cell_key]
            ).lower()
            if actual_sha256 != expected_contract_sha:
                raise StaleModelParametersError(
                    f"Contract model_weights_sha256 mismatch for cell '{cell_key}': "
                    f"expected='{expected_contract_sha}', actual='{actual_sha256}'"
                )
