#!/usr/bin/env python3
"""
Parameter Table Read-Only Validator (Phase 2 Task 08 - Ticket 03 / #136).

Strictly verifies PhysicalParamContract data integrity, exact 22-grid cell coverage,
outer key vs inner record alignment, non-empty 64-hex model weights, and field structure
without modifying files or recalculating numerical thresholds.
"""

from collections.abc import Mapping
import json
from pathlib import Path
from typing import List, Optional, Set, Tuple, Union

from src.contract.param_table_converter import ContractConversionError
from src.contract.parameter_contract import (
    AUTHORIZED_LEAD_HOURS,
    AUTHORIZED_STATIONS,
    TOTAL_AUTHORIZED_CELLS,
    CellCalibrationRecord,
    PhysicalParamContract,
)
from src.contract.version_watchdog import CONTRACT_VERSION


class PhysicalParamTableValidator:
    """
    Read-only statutory validator for PhysicalParamContract.
    Enforces exact 22 grid cells, key consistency, statutory model weights, and schema validity.
    """

    @classmethod
    def validate(cls, contract: PhysicalParamContract) -> bool:
        """
        Validate PhysicalParamContract in memory.
        Raises ContractConversionError on any discrepancy, returns True if valid.
        """
        cls._validate_schema_version(contract.contract_version)
        cls._validate_exact_22_cells(contract.cells)
        cls._validate_cell_records(contract.cells)
        cls._validate_model_weights(contract.model_weights_sha256)
        return True

    @classmethod
    def validate_json(cls, json_path: Union[str, Path]) -> bool:
        """
        Load contract JSON from disk and perform read-only structural validation.
        """
        path = Path(json_path)
        if not path.exists():
            raise ContractConversionError(f"Contract JSON file not found: {path}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            raise ContractConversionError(f"Failed to parse contract JSON at {path}: {exc}") from exc

        try:
            contract = PhysicalParamContract.from_dict(data)
        except Exception as exc:
            raise ContractConversionError(f"Contract deserialization failed: {exc}") from exc

        return cls.validate(contract)

    @classmethod
    def _validate_schema_version(cls, version: str) -> None:
        """Enforce contract schema version gate."""
        if version != CONTRACT_VERSION:
            raise ContractConversionError(
                f"Contract schema version mismatch: expected='{CONTRACT_VERSION}', actual='{version}'"
            )

    @classmethod
    def _validate_exact_22_cells(
        cls, cells: Mapping[Tuple[str, int], CellCalibrationRecord]
    ) -> None:
        """Enforce EXACTLY 22 statutory grid cells coverage."""
        if not isinstance(cells, Mapping):
            raise ContractConversionError(f"Contract cells must be a Mapping, got {type(cells).__name__}")

        expected_cells: Set[Tuple[str, int]] = {
            (s, h) for s in AUTHORIZED_STATIONS for h in AUTHORIZED_LEAD_HOURS
        }
        actual_cells = set(cells.keys())

        missing = expected_cells - actual_cells
        extra = actual_cells - expected_cells

        if missing or extra or len(actual_cells) != TOTAL_AUTHORIZED_CELLS:
            errs: List[str] = []
            if missing:
                errs.append(f"missing {len(missing)} cells: {sorted(missing)}")
            if extra:
                errs.append(f"extra {len(extra)} cells: {sorted(extra)}")
            raise ContractConversionError(
                f"Statutory 22-grid mismatch (got {len(actual_cells)}, expected {TOTAL_AUTHORIZED_CELLS}): "
                f"{'; '.join(errs)}"
            )

    @classmethod
    def _validate_cell_records(
        cls, cells: Mapping[Tuple[str, int], CellCalibrationRecord]
    ) -> None:
        """Verify outer key alignment and field sanity across cell records."""
        common_var: Optional[str] = None

        for (st, lead), record in cells.items():
            if not isinstance(record, CellCalibrationRecord):
                raise ContractConversionError(
                    f"Cell ({st}, {lead}h) record must be CellCalibrationRecord, got {type(record).__name__}"
                )

            # Outer key vs inner record alignment check
            if record.station != st or record.lead_hours != lead:
                raise ContractConversionError(
                    f"Outer key ({st}, {lead}h) mismatches inner record identification "
                    f"({record.station}, {record.lead_hours}h)"
                )

            # Variable consistency check across 22 cells
            if common_var is None:
                common_var = record.variable
            elif record.variable != common_var:
                raise ContractConversionError(
                    f"Inconsistent variable across grid: expected '{common_var}', "
                    f"got '{record.variable}' in cell ({st}, {lead}h)"
                )

    @classmethod
    def _validate_model_weights(
        cls, model_weights: Mapping[str, str]
    ) -> None:
        """
        Enforce non-empty statutory model weights and 64-hex lowercase hashes (M-2).
        """
        if not model_weights:
            raise ContractConversionError(
                "Contract model_weights_sha256 cannot be empty; "
                "must contain statutory physical model weights"
            )
        for fname, sha in model_weights.items():
            if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
                raise ContractConversionError(
                    f"Model '{fname}' has invalid SHA256 in contract model_weights_sha256: '{sha}'. "
                    f"Must be 64-character lowercase hexadecimal."
                )
