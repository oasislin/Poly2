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
    compute_canonical_manifest_sha256,
)
from src.contract.param_table_converter import (
    ContractConversionError,
    convert_csv_to_contract,
    export_contract_to_json,
)
from src.contract.param_table_validator import (
    PhysicalParamTableValidator,
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
    "compute_canonical_manifest_sha256",
    "ContractConversionError",
    "convert_csv_to_contract",
    "export_contract_to_json",
    "PhysicalParamTableValidator",
]
