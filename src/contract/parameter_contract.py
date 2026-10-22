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
from typing import Any, Dict, List, Tuple


# W2 Scope Authorized Grid Constants (Structural Dimensions, NOT Thresholds)
AUTHORIZED_STATIONS: Tuple[str, ...] = ("KORD", "KMIA")
AUTHORIZED_LEAD_HOURS: Tuple[int, ...] = (12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72)
TOTAL_AUTHORIZED_CELLS: int = len(AUTHORIZED_STATIONS) * len(AUTHORIZED_LEAD_HOURS)  # 22


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
        Deserialize record from dictionary with strict key presence.
        Fails closed on missing fields; zero fallback defaults.
        """
        return cls(
            station=str(data["station"]).upper(),
            lead_hours=int(data["lead_hours"]),
            variable=str(data["variable"]).lower(),
            s_oos=float(data["s_oos"]),
            fstd_lo=float(data["fstd_lo"]),
            fstd_hi=float(data["fstd_hi"]),
            fstd_in=bool(data["fstd_in"]),
            ece_2f=float(data["ece_2f"]),
            v1_coverage_90=float(data["v1_coverage_90"]),
            v1_coverage_90_pass=bool(data["v1_coverage_90_pass"]),
            pit_mean=float(data["pit_mean"]),
            pit_var=float(data["pit_var"]),
            reject_uniform=bool(data["reject_uniform"]),
            neff=float(data["neff"]),
            cvm_stat=float(data["cvm_stat"]),
            cvm_p=float(data["cvm_p"]),
            ece_range=float(data["ece_range"]),
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
    model_weights_sha256: Dict[str, str]
    created_at: str
    cells: Dict[Tuple[str, int], CellCalibrationRecord]

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
        Pure structure check; contains ZERO numerical threshold checks.
        Raises ValueError with missing cell keys if validation fails.
        """
        missing: List[str] = []
        for st in AUTHORIZED_STATIONS:
            for lead in AUTHORIZED_LEAD_HOURS:
                if (st, lead) not in self.cells:
                    missing.append(f"{st}_{lead}h")

        if missing:
            raise ValueError(
                f"Missing {len(missing)} required calibration cells: {', '.join(missing)}. "
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
            "model_weights_sha256": self.model_weights_sha256,
            "created_at": self.created_at,
            "total_cells": len(self.cells),
            "cells": serialized_cells,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhysicalParamContract":
        """
        Deserialize contract from dictionary with strict validation.
        Validates outer key consistency with internal cell identity.
        Fails closed with KeyError if any required metadata is missing.
        """
        cells: Dict[Tuple[str, int], CellCalibrationRecord] = {}
        raw_cells = data["cells"]

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
            model_weights_sha256=dict(data["model_weights_sha256"]),
            created_at=str(data["created_at"]),
            cells=cells,
        )
        return contract
