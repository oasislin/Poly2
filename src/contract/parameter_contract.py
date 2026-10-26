#!/usr/bin/env python3
"""
Physical Parameter Consumption Contract (ADR-0019 / Ticket 01 / Phase 2 Task 08).

Defines strongly-typed, immutable data models and schemas for consuming calibrated
physical forecast and out-of-sample diagnostic parameters.
Guarantees:
- Strict uncoupling between physical modeling layers and downstream trading sizing.
- Immutable, cell-level data structure (station x lead_hours).
- Enforcement of 22 authorized cells (KORD & KMIA, 12h~72h).
- Strict defense against global averaging.
- ZERO hardcoded threshold constants or synthetic defaults (Fail-Closed).
"""

from dataclasses import asdict, dataclass
from decimal import Decimal
import math
import re
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Set, Tuple


# W2 Scope Authorized Grid Constants (Structural Dimensions, NOT Thresholds)
AUTHORIZED_STATIONS: Tuple[str, ...] = ("KORD", "KMIA")
AUTHORIZED_LEAD_HOURS: Tuple[int, ...] = (12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72)
TOTAL_AUTHORIZED_CELLS: int = len(AUTHORIZED_STATIONS) * len(AUTHORIZED_LEAD_HOURS)  # 22

# Model filename regex pattern in manifest (ADR-0019 / Ticket 25).
# Key space semantic: filename of individual physical model file in manifest.json.
# Explicitly PROHIBITED: using cell key '{station}_{lead}h' as keys in model_weights_sha256.
# Note: Validation of non-empty and set completeness belongs to param_table_validator / watchdog.
MODEL_FILENAME_PATTERN: str = (
    r"^[A-Z]{4}_(Winter|Spring|Summer|Autumn)_(Max|Min)_lead(6|12|18|24|30|36|42|48|54|60|66|72)h(_[a-z]+)?\.pkl$"
)
_COMPILED_MODEL_FILENAME_PATTERN = re.compile(MODEL_FILENAME_PATTERN)
_HEX64_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _parse_strict_bool(value: Any, field_name: str) -> bool:
    """
    Strict boolean parser (ADR-0019 / Ticket 25).
    Accepts strictly bool instances, or strings exactly equal to 'True' or 'False'.
    Rejects integer 1/0, lowercase 'true'/'false', 'yes', etc. with ValueError.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value == "True":
            return True
        if value == "False":
            return False
    raise ValueError(
        f"Invalid strict boolean for field '{field_name}': {repr(value)}. "
        f"Must be strictly bool (True/False) or str 'True'/'False'."
    )


def _parse_finite_float(value: Any, field_name: str) -> float:
    """
    Strict finite float parser (ADR-0019 / Ticket 25).
    Converts value to float and enforces math.isfinite().
    Rejects NaN, +inf, -inf with ValueError.
    """
    try:
        val = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid float for field '{field_name}': {repr(value)}"
        ) from exc
    if not math.isfinite(val):
        raise ValueError(
            f"Float field '{field_name}' must be finite, got {val}"
        )
    return val


@dataclass(frozen=True)
class CellCalibrationRecord:
    """
    Immutable calibration and diagnostic record for a single (station, lead_hours) cell.
    Implements ADR-0019 Parameter Consumption Matrix.
    Contains ZERO hardcoded thresholds or synthetic defaults.
    All fields MUST be explicitly provided from verified calibration artifacts.
    """

    # Physical Cell Identification
    station: str
    lead_hours: int
    variable: str

    # Mandatory Consumption Fields (ADR-0019 §三)
    s_oos: float  # Out-of-sample variance ratio (Var(resid) / mean(sig_eff^2))
    fstd_lo: float  # F-distribution lower bound under N_eff
    fstd_hi: float  # F-distribution upper bound under N_eff
    fstd_in: bool  # Upstream F-test boolean (whether s_oos in [fstd_lo, fstd_hi])
    ece_2f: float  # Direct 2°F bin Expected Calibration Error
    v1_coverage_90: float  # Nominal 90% interval empirical coverage
    v1_coverage_90_pass: bool  # Upstream G5 coverage gate pass boolean
    pit_mean: float  # PIT first moment (bias drift detector)
    pit_var: float  # PIT second central moment (uniformity indicator)
    reject_uniform: bool  # Upstream CvM goodness-of-fit rejection flag

    # Indirect Consumption & Diagnostic Fields (ADR-0019 §三)
    neff: float  # Effective degrees of freedom under lag-1 autocorrelation
    cvm_stat: float  # Cramer-von Mises test statistic
    cvm_p: float  # Cramer-von Mises p-value
    ece_range: float  # Full range ECE for auxiliary audit

    def to_dict(self) -> Dict[str, Any]:
        """Serialize record to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CellCalibrationRecord":
        """
        Deserialize record from dictionary with strict key presence and type validation.
        Fails closed on missing fields, NaN/inf floats, non-strict booleans, or unauthorized station/lead.
        """
        station = str(data["station"]).upper()
        if station not in AUTHORIZED_STATIONS:
            raise ValueError(
                f"Invalid station '{station}'. Authorized stations: {AUTHORIZED_STATIONS}"
            )
        lead_hours = int(data["lead_hours"])
        if lead_hours not in AUTHORIZED_LEAD_HOURS:
            raise ValueError(
                f"Invalid lead_hours '{lead_hours}'. Authorized lead hours: {AUTHORIZED_LEAD_HOURS}"
            )
        variable = str(data["variable"]).lower()

        return cls(
            station=station,
            lead_hours=lead_hours,
            variable=variable,
            s_oos=_parse_finite_float(data["s_oos"], "s_oos"),
            fstd_lo=_parse_finite_float(data["fstd_lo"], "fstd_lo"),
            fstd_hi=_parse_finite_float(data["fstd_hi"], "fstd_hi"),
            fstd_in=_parse_strict_bool(data["fstd_in"], "fstd_in"),
            ece_2f=_parse_finite_float(data["ece_2f"], "ece_2f"),
            v1_coverage_90=_parse_finite_float(data["v1_coverage_90"], "v1_coverage_90"),
            v1_coverage_90_pass=_parse_strict_bool(
                data["v1_coverage_90_pass"], "v1_coverage_90_pass"
            ),
            pit_mean=_parse_finite_float(data["pit_mean"], "pit_mean"),
            pit_var=_parse_finite_float(data["pit_var"], "pit_var"),
            reject_uniform=_parse_strict_bool(
                data["reject_uniform"], "reject_uniform"
            ),
            neff=_parse_finite_float(data["neff"], "neff"),
            cvm_stat=_parse_finite_float(data["cvm_stat"], "cvm_stat"),
            cvm_p=_parse_finite_float(data["cvm_p"], "cvm_p"),
            ece_range=_parse_finite_float(data["ece_range"], "ece_range"),
        )


@dataclass(frozen=True)
class PhysicalForecastOutput:
    """
    Strongly-typed online physical forecast output for a single cell (ADR-0019 §三).
    Encapsulates calibrated mean, effective dispersion, distribution family, and discrete probabilities.
    Contains ZERO hardcoded thresholds or synthetic defaults.
    """

    station: str
    lead_hours: int
    variable: str
    mu_calib: float
    sig_eff: float
    distribution_family: str
    p_j: Dict[str, Decimal]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize forecast output to dictionary with stringified Decimal probabilities."""
        return {
            "station": self.station,
            "lead_hours": self.lead_hours,
            "variable": self.variable,
            "mu_calib": self.mu_calib,
            "sig_eff": self.sig_eff,
            "distribution_family": self.distribution_family,
            "p_j": {bin_name: str(prob) for bin_name, prob in self.p_j.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhysicalForecastOutput":
        """Deserialize forecast output from dictionary with Decimal conversion."""
        raw_p_j = data["p_j"]
        return cls(
            station=str(data["station"]).upper(),
            lead_hours=int(data["lead_hours"]),
            variable=str(data["variable"]).lower(),
            mu_calib=float(data["mu_calib"]),
            sig_eff=float(data["sig_eff"]),
            distribution_family=str(data["distribution_family"]),
            p_j={str(bin_name): Decimal(str(prob)) for bin_name, prob in raw_p_j.items()},
        )


@dataclass(frozen=True)
class PhysicalParamContract:
    """
    Immutable contract holding all calibrated cell records across authorized stations.
    Guarantees full 22-cell coverage and version verification anchors.
    Contains ZERO hardcoded thresholds, gate decisions, or fallback defaults.
    """

    contract_version: str
    manifest_sha256: str
    model_weights_sha256: Mapping[str, str]
    created_at: str
    cells: Mapping[Tuple[str, int], CellCalibrationRecord]

    def __post_init__(self) -> None:
        """
        Validate model_weights_sha256 structure if present and enforce true immutability.
        Note: Does not enforce non-empty (responsibility of param_table_validator).
        """
        # Validate model weights key format and hex SHA if non-empty
        for fname, sha in self.model_weights_sha256.items():
            if not _COMPILED_MODEL_FILENAME_PATTERN.match(fname):
                raise ValueError(
                    f"Invalid model filename key '{fname}' in model_weights_sha256: "
                    f"must match pattern {MODEL_FILENAME_PATTERN}. "
                    f"Key space semantic MUST be manifest model filename (not cell key)."
                )
            if not _HEX64_PATTERN.match(sha):
                raise ValueError(
                    f"Invalid SHA256 hex string for model '{fname}': '{sha}'. "
                    f"Must be 64-character lowercase hexadecimal."
                )

        # Freeze dictionaries with MappingProxyType for deep immutability (R-B / D3)
        object.__setattr__(
            self, "cells", MappingProxyType(dict(self.cells))
        )
        object.__setattr__(
            self, "model_weights_sha256", MappingProxyType(dict(self.model_weights_sha256))
        )

    def get_cell(self, station: str, lead_hours: int) -> CellCalibrationRecord:
        """
        Query a specific cell's calibration record.
        Raises KeyError if the cell does not exist in the contract.
        """
        key = (station.upper(), int(lead_hours))
        if key not in self.cells:
            raise KeyError(
                f"Cell {key} not found in physical parameter contract. "
                f"Available cells: {len(self.cells)}"
            )
        return self.cells[key]

    def validate_cells_coverage(self) -> bool:
        """
        Verify that all 22 authorized cells (KORD/KMIA * 11 lead hours) are present.
        Performs bidirectional check: validates zero missing cells and zero extra cells.
        Pure structure check; contains ZERO numerical threshold checks.
        Raises ValueError with missing/extra cell keys if validation fails.
        """
        expected_cells = {
            (st, lead) for st in AUTHORIZED_STATIONS for lead in AUTHORIZED_LEAD_HOURS
        }
        present_cells = set(self.cells.keys())

        missing_cells = expected_cells - present_cells
        extra_cells = present_cells - expected_cells

        if missing_cells or extra_cells:
            parts = []
            if missing_cells:
                missing_str = ", ".join(sorted(f"{st}_{lead}h" for st, lead in missing_cells))
                parts.append(f"missing {len(missing_cells)} cells: {missing_str}")
            if extra_cells:
                extra_str = ", ".join(sorted(f"{st}_{lead}h" for st, lead in extra_cells))
                parts.append(f"extra {len(extra_cells)} cells: {extra_str}")
            raise ValueError(
                f"Cell coverage mismatch: {'; '.join(parts)}. "
                f"Expected exactly {TOTAL_AUTHORIZED_CELLS} cells."
            )
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Serialize contract to dictionary suitable for JSON storage."""
        serialized_cells = {}
        for (st, lead), record in self.cells.items():
            cell_key = f"{st}_{lead}h"
            serialized_cells[cell_key] = record.to_dict()

        return {
            "contract_version": self.contract_version,
            "manifest_sha256": self.manifest_sha256,
            "model_weights_sha256": dict(self.model_weights_sha256),
            "created_at": self.created_at,
            "total_cells": len(self.cells),
            "cells": serialized_cells,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhysicalParamContract":
        """
        Deserialize contract from dictionary with strict validation.
        Validates outer key consistency with internal cell identity and total_cells.
        Fails closed with KeyError/ValueError if any required metadata is invalid or missing.
        """
        if "total_cells" not in data:
            raise ValueError("Missing mandatory field 'total_cells' in contract data")

        raw_cells = data["cells"]
        total_cells = int(data["total_cells"])
        if total_cells != len(raw_cells):
            raise ValueError(
                f"Field 'total_cells' ({total_cells}) does not match actual cell count ({len(raw_cells)})"
            )

        cells: Dict[Tuple[str, int], CellCalibrationRecord] = {}
        for expected_key, cell_dict in raw_cells.items():
            record = CellCalibrationRecord.from_dict(cell_dict)
            cell_key = f"{record.station}_{record.lead_hours}h"
            if expected_key != cell_key:
                raise ValueError(
                    f"Cell key mismatch: outer key '{expected_key}' does not match "
                    f"record identity '{cell_key}'"
                )
            cells[(record.station, record.lead_hours)] = record

        contract = cls(
            contract_version=str(data["contract_version"]),
            manifest_sha256=str(data["manifest_sha256"]),
            model_weights_sha256=dict(data.get("model_weights_sha256", {})),
            created_at=str(data["created_at"]),
            cells=cells,
        )
        return contract
