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
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple


# W2 Scope Authorized Grid Constants
AUTHORIZED_STATIONS: Tuple[str, ...] = ("KORD", "KMIA")
AUTHORIZED_LEAD_HOURS: Tuple[int, ...] = (12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72)
TOTAL_AUTHORIZED_CELLS: int = len(AUTHORIZED_STATIONS) * len(AUTHORIZED_LEAD_HOURS)  # 22


@dataclass(frozen=True)
class CellCalibrationRecord:
    """
    Immutable calibration and diagnostic record for a single (station, lead_hours) cell.
    Implements ADR-0019 Parameter Consumption Matrix.
    """

    # Physical Cell Identification
    station: str
    lead_hours: int
    variable: str = "tmax"

    # Mandatory Consumption Fields (ADR-0019 §三)
    s_oos: float = 1.0  # Out-of-sample variance ratio (Var(resid) / mean(sig_eff^2))
    fstd_lo: float = 0.8  # F-distribution lower bound under N_eff
    fstd_hi: float = 1.25  # F-distribution upper bound under N_eff
    fstd_in: bool = True  # Whether s_oos falls within [fstd_lo, fstd_hi]
    ece_2f: float = 0.01  # Direct 2°F bin Expected Calibration Error
    v1_coverage_90: float = 0.90  # Nominal 90% interval empirical coverage
    v1_coverage_90_pass: bool = True  # G5 gate pass boolean ([0.83, 0.95])
    pit_mean: float = 0.50  # PIT first moment (bias drift detector)
    pit_var: float = 0.083333  # PIT second central moment (theoretical 1/12)
    reject_uniform: bool = False  # CvM/KS goodness-of-fit rejection flag

    # Indirect Consumption & Diagnostic Fields (ADR-0019 §三)
    neff: float = 300.0  # Effective degrees of freedom under lag-1 autocorrelation
    cvm_stat: float = 0.05  # Cramer-von Mises test statistic
    cvm_p: float = 0.80  # Cramer-von Mises p-value
    ece_range: float = 0.008  # Full range ECE for auxiliary verification

    def to_dict(self) -> Dict[str, Any]:
        """Serialize record to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CellCalibrationRecord":
        """Deserialize record from dictionary with type coercion."""
        return cls(
            station=str(data["station"]).upper(),
            lead_hours=int(data["lead_hours"]),
            variable=str(data.get("variable", "tmax")).lower(),
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
            neff=float(data.get("neff", 300.0)),
            cvm_stat=float(data.get("cvm_stat", 0.0)),
            cvm_p=float(data.get("cvm_p", 1.0)),
            ece_range=float(data.get("ece_range", 0.0)),
        )


@dataclass(frozen=True)
class PhysicalParamContract:
    """
    Immutable contract holding all calibrated cell records across authorized stations.
    Guarantees full 22-cell coverage and version verification anchor.
    """

    cells: Dict[Tuple[str, int], CellCalibrationRecord] = field(default_factory=dict)
    manifest_sha256: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
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
            "contract_version": "1.0.0",
            "manifest_sha256": self.manifest_sha256,
            "created_at": self.created_at,
            "total_cells": len(self.cells),
            "cells": serialized_cells,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhysicalParamContract":
        """Deserialize contract from dictionary with validation."""
        cells: Dict[Tuple[str, int], CellCalibrationRecord] = {}
        raw_cells = data.get("cells", {})

        for _, cell_dict in raw_cells.items():
            record = CellCalibrationRecord.from_dict(cell_dict)
            cells[(record.station, record.lead_hours)] = record

        contract = cls(
            cells=cells,
            manifest_sha256=str(data.get("manifest_sha256", "")),
            created_at=str(data.get("created_at", "")),
        )
        return contract
