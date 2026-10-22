"""
Physical parameter contract and calibration data facade for Polymarket trading layers (ADR-0019).
"""

from src.contract.parameter_contract import (
    CellCalibrationRecord,
    PhysicalParamContract,
    AUTHORIZED_STATIONS,
    AUTHORIZED_LEAD_HOURS,
)

__all__ = [
    "CellCalibrationRecord",
    "PhysicalParamContract",
    "AUTHORIZED_STATIONS",
    "AUTHORIZED_LEAD_HOURS",
]
