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
from src.contract.version_watchdog import (
    ContractGuardrailError,
    ManifestIntegrityError,
    StaleModelParametersError,
    PickleCorruptionError,
    SecurityViolationError,
    ContractVersionWatchdog,
    WatchdogVerificationReport,
    CONTRACT_VERSION,
    AUTHORIZED_LEADS_FOR_GUARD,
)

__all__ = [
    "CellCalibrationRecord",
    "PhysicalForecastOutput",
    "PhysicalParamContract",
    "AUTHORIZED_STATIONS",
    "AUTHORIZED_LEAD_HOURS",
    "TOTAL_AUTHORIZED_CELLS",
    "ContractGuardrailError",
    "ManifestIntegrityError",
    "StaleModelParametersError",
    "PickleCorruptionError",
    "SecurityViolationError",
    "ContractVersionWatchdog",
    "WatchdogVerificationReport",
    "CONTRACT_VERSION",
    "AUTHORIZED_LEADS_FOR_GUARD",
]
