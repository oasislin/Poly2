"""
Physical parameter contract and calibration data facade for Polymarket trading layers (ADR-0019).
"""

from src.contract.parameter_contract import (
    CellCalibrationRecord,
    PhysicalForecastOutput,
    PhysicalParamContract,
    AUTHORIZED_STATIONS,
    AUTHORIZED_LEAD_HOURS,
    TOTAL_AUTHORIZED_CELLS,
)

__all__ = [
    "CellCalibrationRecord",
    "PhysicalForecastOutput",
    "PhysicalParamContract",
    "AUTHORIZED_STATIONS",
    "AUTHORIZED_LEAD_HOURS",
    "TOTAL_AUTHORIZED_CELLS",
]
