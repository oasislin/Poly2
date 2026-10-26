"""
Unit tests for Parameter Table Validator (Phase 2 Task 08 - Ticket 03 / #136).

Validates:
- T10: Validator passes on valid contract
- T11: Validator fails on 23 cells (extra cell) and lists cell name
- T12: Validator fails on outer key != inner record identification
- Schema version mismatch fails
- Variable inconsistency across grid fails
- validate_json on disk artifact passes
"""

from pathlib import Path

import pytest

from src.contract.param_table_converter import (
    ContractConversionError,
    convert_csv_to_contract,
    export_contract_to_json,
)
from src.contract.param_table_validator import (
    PhysicalParamTableValidator,
)
from src.contract.parameter_contract import (
    CellCalibrationRecord,
    PhysicalParamContract,
)
from src.contract.version_watchdog import CONTRACT_VERSION

METRICS_REAL_PATH = Path("evidence/audit_v2/p4blind_v2r01_metrics.csv")
COMPARISON_REAL_PATH = Path("evidence/audit_v2/p4blind_v2r01_comparison.csv")
MANIFEST_REAL_PATH = Path("data/models/manifest.json")


def _get_valid_contract() -> PhysicalParamContract:
    return convert_csv_to_contract(
        metrics_csv_path=METRICS_REAL_PATH,
        comparison_csv_path=COMPARISON_REAL_PATH,
        manifest_path=MANIFEST_REAL_PATH,
    )


def test_t10_validator_valid_contract_passes():
    """T10: PhysicalParamTableValidator.validate passes without errors on a valid contract."""
    contract = _get_valid_contract()
    assert PhysicalParamTableValidator.validate(contract) is True


def test_t11_validator_23_cells_fails_and_lists_extra():
    """T11: Validator rejects contract with 23 cells and explicitly lists the extra cell."""
    contract = _get_valid_contract()
    cells_mutated = dict(contract.cells)

    # Add an illegal 23rd cell
    extra_record = CellCalibrationRecord(
        station="KATL",
        lead_hours=12,
        variable="tmax",
        s_oos=1.0,
        fstd_lo=0.8,
        fstd_hi=1.2,
        fstd_in=True,
        ece_2f=0.01,
        v1_coverage_90=0.9,
        v1_coverage_90_pass=True,
        pit_mean=0.5,
        pit_var=0.0833,
        reject_uniform=False,
        neff=300.0,
        cvm_stat=0.05,
        cvm_p=0.8,
        ece_range=0.01,
    )
    cells_mutated[("KATL", 12)] = extra_record

    tampered_contract = PhysicalParamContract(
        contract_version=contract.contract_version,
        manifest_sha256=contract.manifest_sha256,
        model_weights_sha256=contract.model_weights_sha256,
        created_at=contract.created_at,
        cells=cells_mutated,
    )

    with pytest.raises(ContractConversionError, match=r"extra 1 cells.*KATL.*12") as exc_info:
        PhysicalParamTableValidator.validate(tampered_contract)

    assert "got 23, expected 22" in str(exc_info.value)


def test_t12_validator_outer_key_mismatch_fails():
    """T12: Validator rejects contract where dictionary outer key mismatches inner record identification."""
    contract = _get_valid_contract()
    cells_mutated = dict(contract.cells)

    # Put KORD 12h record under key (KORD, 18)
    rec_kord_12 = cells_mutated[("KORD", 12)]
    cells_mutated[("KORD", 18)] = rec_kord_12

    tampered_contract = PhysicalParamContract(
        contract_version=contract.contract_version,
        manifest_sha256=contract.manifest_sha256,
        model_weights_sha256=contract.model_weights_sha256,
        created_at=contract.created_at,
        cells=cells_mutated,
    )

    with pytest.raises(ContractConversionError, match=r"Outer key \(KORD, 18h\) mismatches inner record"):
        PhysicalParamTableValidator.validate(tampered_contract)


def test_validator_schema_version_mismatch():
    """Validator rejects contract with outdated contract_version."""
    contract = _get_valid_contract()
    tampered_contract = PhysicalParamContract(
        contract_version="OLD-SCHEMA-v0",
        manifest_sha256=contract.manifest_sha256,
        model_weights_sha256=contract.model_weights_sha256,
        created_at=contract.created_at,
        cells=contract.cells,
    )

    with pytest.raises(ContractConversionError, match=r"Contract schema version mismatch"):
        PhysicalParamTableValidator.validate(tampered_contract)


def test_validator_inconsistent_variable_fails():
    """Validator rejects contract if a cell has a different variable than the rest."""
    contract = _get_valid_contract()
    cells_mutated = dict(contract.cells)

    orig_rec = cells_mutated[("KMIA", 24)]
    bad_var_rec = CellCalibrationRecord(
        station=orig_rec.station,
        lead_hours=orig_rec.lead_hours,
        variable="tmin",  # Inconsistent
        s_oos=orig_rec.s_oos,
        fstd_lo=orig_rec.fstd_lo,
        fstd_hi=orig_rec.fstd_hi,
        fstd_in=orig_rec.fstd_in,
        ece_2f=orig_rec.ece_2f,
        v1_coverage_90=orig_rec.v1_coverage_90,
        v1_coverage_90_pass=orig_rec.v1_coverage_90_pass,
        pit_mean=orig_rec.pit_mean,
        pit_var=orig_rec.pit_var,
        reject_uniform=orig_rec.reject_uniform,
        neff=orig_rec.neff,
        cvm_stat=orig_rec.cvm_stat,
        cvm_p=orig_rec.cvm_p,
        ece_range=orig_rec.ece_range,
    )
    cells_mutated[("KMIA", 24)] = bad_var_rec

    tampered_contract = PhysicalParamContract(
        contract_version=contract.contract_version,
        manifest_sha256=contract.manifest_sha256,
        model_weights_sha256=contract.model_weights_sha256,
        created_at=contract.created_at,
        cells=cells_mutated,
    )

    with pytest.raises(ContractConversionError, match=r"Inconsistent variable across grid"):
        PhysicalParamTableValidator.validate(tampered_contract)


def test_validate_json_on_disk(tmp_path: Path):
    """Test validate_json on serialized contract artifact on disk."""
    contract = _get_valid_contract()
    json_path = tmp_path / "valid_contract.json"
    export_contract_to_json(contract, json_path)

    assert PhysicalParamTableValidator.validate_json(json_path) is True


def test_validate_json_file_not_found(tmp_path: Path):
    """Test validate_json on nonexistent file raises ContractConversionError."""
    with pytest.raises(ContractConversionError, match=r"Contract JSON file not found"):
        PhysicalParamTableValidator.validate_json(tmp_path / "nonexistent.json")


def test_t22_validator_model_weights_validation():
    """T22: Validator enforces non-empty model_weights_sha256 and strict 64-hex lowercase hashes."""
    contract = _get_valid_contract()

    # 1. Empty model_weights_sha256 in contract raises ContractConversionError
    empty_weights_contract = PhysicalParamContract(
        contract_version=contract.contract_version,
        manifest_sha256=contract.manifest_sha256,
        model_weights_sha256={},
        created_at=contract.created_at,
        cells=contract.cells,
    )
    with pytest.raises(ContractConversionError, match="model_weights_sha256 cannot be empty"):
        PhysicalParamTableValidator.validate(empty_weights_contract)

    # 2. Direct unit test of _validate_model_weights rejecting invalid hashes
    valid_key = "KORD_Winter_Max_lead12h.pkl"
    with pytest.raises(ContractConversionError, match="invalid SHA256 in contract model_weights_sha256"):
        PhysicalParamTableValidator._validate_model_weights({valid_key: "short_hash"})

    with pytest.raises(ContractConversionError, match="invalid SHA256 in contract model_weights_sha256"):
        PhysicalParamTableValidator._validate_model_weights({valid_key: "g" * 64})  # 'g' is non-hex

