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


class ManifestIntegrityError(ContractGuardrailError):
    """manifest.json 文件缺失 / 损坏 / 非法 JSON / 结构或必要字段缺失."""

    pass


class StaleModelParametersError(ContractGuardrailError):
    """SHA256 不匹配或版本过旧 → 陈旧参数注入."""

    pass


class PickleCorruptionError(ContractGuardrailError):
    """物理模型 .pkl 文件缺失 / 0 字节 / pickle 反序列化损坏."""

    pass


class SecurityViolationError(ContractGuardrailError):
    """生产环境非法绕过."""

    pass


@dataclass(frozen=True)
class WatchdogVerificationReport:
    """看门狗校验结果（不可变）."""

    is_valid: bool
    """True 当且仅当全量校验真实执行且全部通过；跳过/绕过一律为 False."""
    verified_cells_count: int
    """通过校验的法定网格单元数（22 格完全覆盖）."""
    failed_entries: int
    """校验失败的模型条目数。Fail-Closed 模式下遇错即抛出异常，正常返回时恒为 0（保留供扩展诊断）."""
    skipped_6h_entries: int
    """跳过校验的 6h lead 模型条目数（按 ADR-0019 豁免，仅记录 warning）."""
    bypassed: bool
    """是否处于测试环境受控绕过状态."""
    checked_at: str
    """ISO 格式的 UTC 时间戳."""


def compute_canonical_manifest_sha256(manifest: Dict[str, Any]) -> str:
    """
    Compute canonical, deterministic SHA256 of manifest dictionary.
    Single source of truth for manifest hashing used across version watchdog
    and parameter contract converters (ADR-0019 / Ticket 03 D-1).
    """
    serialized = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


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

        :param skip_when_env: Name of environment variable to check for test bypass.
            Takes effect ONLY when its value is strictly literal '1'.
            In production (POLY_ENV in ('production', 'prod')), any attempt to set this
            variable to '1' raises SecurityViolationError. When unset or not '1', full check runs.
        :return: WatchdogVerificationReport with verification results.
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
        if skip_when_env is None:
            return None

        env_val = os.environ.get(skip_when_env)
        poly_env = (os.environ.get("POLY_ENV") or "").lower()
        is_production = poly_env in ("production", "prod")

        # Defense Line 2: If in production and bypass variable is set to allowed value "1", strictly reject.
        # If variable is not set (or not "1"), ignore skip_when_env and proceed with full check.
        if is_production:
            if env_val == "1":
                raise SecurityViolationError(
                    f"Cannot bypass contract watchdog in production environment "
                    f"(POLY_ENV='{poly_env}', {skip_when_env}='1')"
                )
            return None

        # Defense Line 3: In non-production, bypass ONLY when variable is strictly literal "1".
        if env_val == "1":
            logger.critical(
                "[ContractWatchdog] TEST BYPASS ACTIVATED via env '%s'='1' - STRICTLY PROHIBITED IN PRODUCTION",
                skip_when_env,
            )
            return WatchdogVerificationReport(
                is_valid=False,
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
            raise ManifestIntegrityError(
                f"Manifest file not found: {self.manifest_path}"
            )

        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ManifestIntegrityError(
                f"Failed to parse manifest JSON at {self.manifest_path}: {exc}"
            ) from exc

        if not isinstance(manifest, dict):
            raise ManifestIntegrityError(
                f"Manifest root must be a JSON object, got {type(manifest).__name__}"
            )

        if "models" not in manifest or not isinstance(manifest["models"], dict):
            raise ManifestIntegrityError("Manifest missing 'models' dictionary")

        return manifest

    @staticmethod
    def _compute_canonical_manifest_sha256(manifest: Dict[str, Any]) -> str:
        """Deprecated shim: 委托公开函数，保持既有调用点不变。"""
        return compute_canonical_manifest_sha256(manifest)

    def _verify_contract_anchors(self, canonical_sha256: str) -> None:
        """
        Verify injected contract version and manifest SHA256 anchors.
        Enforces schema version gate: contract artifacts across different schema
        versions are strictly rejected (StaleModelParametersError).
        """
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

    def _parse_model_entry(self, fname: str, meta: Any) -> Tuple[str, int]:
        """Parse and validate station and lead_hours from manifest model entry."""
        if not isinstance(meta, dict):
            raise ManifestIntegrityError(
                f"Model entry '{fname}' metadata must be a dictionary"
            )

        station_raw = meta.get("station")
        lead_raw = meta.get("lead_hours")
        if station_raw is None or lead_raw is None:
            raise ManifestIntegrityError(
                f"Model entry '{fname}' missing required fields ('station', 'lead_hours')"
            )

        station = str(station_raw).upper()
        try:
            lead = int(lead_raw)
        except (ValueError, TypeError) as exc:
            raise ManifestIntegrityError(
                f"Model entry '{fname}' has invalid 'lead_hours': {lead_raw}"
            ) from exc

        return station, lead

    @staticmethod
    def _handle_non_statutory_lead(fname: str, station: str, lead: int) -> int:
        """Handle logging and exemption counter for models with non-statutory leads."""
        if lead == 6:
            logger.warning(
                "[ContractWatchdog] 6h lead model SKIPPED from betting contract verification: "
                "station=%s, model=%s",
                station,
                fname,
            )
            return 1
        logger.debug(
            "[ContractWatchdog] Non-statutory lead model SKIPPED: "
            "station=%s, lead=%s, model=%s",
            station,
            lead,
            fname,
        )
        return 0

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
        verified_contract_files: Set[str] = set()
        skipped_6h = 0

        for fname, meta in models.items():
            station, lead = self._parse_model_entry(fname, meta)

            if station not in AUTHORIZED_STATIONS:
                continue

            if lead not in AUTHORIZED_LEADS_FOR_GUARD:
                skipped_6h += self._handle_non_statutory_lead(fname, station, lead)
                continue

            self._verify_single_model_file(fname, meta)
            seen_cells.add((station, lead))
            if self.contract and fname in self.contract.model_weights_sha256:
                verified_contract_files.add(fname)

        expected_total = TOTAL_AUTHORIZED_CELLS  # 22
        if len(seen_cells) != expected_total:
            raise ContractGuardrailError(
                f"Incomplete statutory cell coverage: verified={len(seen_cells)} "
                f"expected={expected_total} (missing {expected_total - len(seen_cells)} cells)"
            )

        self._verify_contract_weights_complete(verified_contract_files)

        return len(seen_cells), skipped_6h

    def _verify_single_model_file(
        self, fname: str, meta: Dict[str, Any]
    ) -> None:
        """Verify existence, size, pickle integrity, and SHA256 for a single model file."""
        declared_sha = meta.get("sha256")
        if declared_sha is None:
            raise ManifestIntegrityError(f"Model entry '{fname}' missing 'sha256'")

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
        expected_manifest_sha = str(declared_sha).lower()
        if actual_sha256 != expected_manifest_sha:
            raise StaleModelParametersError(
                f"Model SHA256 mismatch for '{fname}': "
                f"expected='{expected_manifest_sha}', actual='{actual_sha256}'"
            )

        self._verify_contract_weight_match(fname, actual_sha256)

    def _verify_contract_weight_match(
        self, fname: str, actual_sha256: str
    ) -> None:
        """Verify model file SHA256 against injected contract weights map."""
        if self.contract is None:
            return

        if not self.contract.model_weights_sha256:
            logger.warning(
                "[ContractWatchdog] Injected contract has empty model_weights_sha256; "
                "skipping binary hash match (historical compatibility branch)"
            )
            return

        if fname not in self.contract.model_weights_sha256:
            return

        expected_contract_sha = str(
            self.contract.model_weights_sha256[fname]
        ).lower()
        if actual_sha256 != expected_contract_sha:
            raise StaleModelParametersError(
                f"Contract model_weights_sha256 mismatch for model '{fname}': "
                f"expected='{expected_contract_sha}', actual='{actual_sha256}'"
            )

    def _verify_contract_weights_complete(
        self, verified_files: Set[str]
    ) -> None:
        """
        Assert all model weights declared in injected contract were verified against active models.
        (ADR-0019 / Ticket 03 D-3).
        """
        if self.contract is None or not self.contract.model_weights_sha256:
            return

        declared_files = set(self.contract.model_weights_sha256.keys())
        unverified = declared_files - verified_files
        if unverified:
            raise StaleModelParametersError(
                f"Contract contains {len(unverified)} model weight entries not verified against manifest: "
                f"{sorted(unverified)}"
            )
