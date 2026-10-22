"""
Unit tests for Physical Parameter Consumption Contract (Ticket 01 / Phase 2 Task 08).
Validates ADR-0019 specifications:
- Strongly typed, immutable CellCalibrationRecord with mandatory & indirect consumption fields.
- Zero hardcoded threshold constants or fallback defaults (Fail-Closed).
- Dynamic PhysicalForecastOutput with Decimal discrete probabilities.
- 22-cell structure (KORD/KMIA * 11 lead hours) without global averaging.
- Frozen immutability preventing downstream tampering.
"""

from dataclasses import FrozenInstanceError
from decimal import Decimal
import pytest

from src.contract.parameter_contract import (
    CellCalibrationRecord,
    PhysicalForecastOutput,
    PhysicalParamContract,
    AUTHORIZED_STATIONS,
    AUTHORIZED_LEAD_HOURS,
    TOTAL_AUTHORIZED_CELLS,
)


def _make_sample_record(station: str = "KORD", lead_hours: int = 12) -> CellCalibrationRecord:
    """Helper to generate a valid test record with all fields explicitly supplied."""
    return CellCalibrationRecord(
        station=station,
        lead_hours=lead_hours,
        variable="tmax",
        s_oos=1.052,
        fstd_lo=0.825,
        fstd_hi=1.215,
        fstd_in=True,
        ece_2f=0.0115,
        v1_coverage_90=0.915,
        v1_coverage_90_pass=True,
        pit_mean=0.502,
        pit_var=0.0841,
        reject_uniform=False,
        neff=312.5,
        cvm_stat=0.045,
        cvm_p=0.892,
        ece_range=0.0078,
    )


def test_cell_calibration_record_creation_and_frozen():
    """Verify record initializes properly and enforces immutability."""
    record = _make_sample_record("KMIA", 30)
    assert record.station == "KMIA"
    assert record.lead_hours == 30
    assert record.variable == "tmax"
    assert record.s_oos == 1.052
    assert record.fstd_in is True
    assert record.v1_coverage_90_pass is True

    # Immutability check
    with pytest.raises(FrozenInstanceError):
        record.s_oos = 1.35  # type: ignore


def test_cell_calibration_record_no_defaults_fail_closed():
    """Verify record cannot be instantiated with missing fields (no defaults allowed)."""
    with pytest.raises(TypeError):
        # Missing s_oos, fstd_lo, etc.
        CellCalibrationRecord(  # type: ignore
            station="KORD",
            lead_hours=12,
            variable="tmax",
        )


def test_cell_calibration_record_dict_roundtrip():
    """Verify to_dict and from_dict preserve all fields exactly."""
    record = _make_sample_record("KORD", 24)
    d = record.to_dict()
    assert d["station"] == "KORD"
    assert d["lead_hours"] == 24
    assert d["s_oos"] == 1.052
    assert d["reject_uniform"] is False

    reconstructed = CellCalibrationRecord.from_dict(d)
    assert reconstructed == record


def test_cell_calibration_record_from_dict_missing_field_raises_key_error():
    """Verify deserialization fails closed if any field is missing (no fallback defaults)."""
    record = _make_sample_record("KORD", 12)
    d = record.to_dict()
    del d["s_oos"]  # Remove mandatory field

    with pytest.raises(KeyError, match="s_oos"):
        CellCalibrationRecord.from_dict(d)


def test_physical_forecast_output_creation_and_roundtrip():
    """Verify PhysicalForecastOutput correctly preserves Decimal probabilities and roundtrips."""
    p_j = {
        "bin_below_70": Decimal("0.0500"),
        "bin_70_72": Decimal("0.1500"),
        "bin_72_74": Decimal("0.6000"),
        "bin_above_74": Decimal("0.2000"),
    }
    output = PhysicalForecastOutput(
        station="KORD",
        lead_hours=18,
        variable="tmax",
        mu_calib=72.45,
        sig_eff=1.85,
        distribution_family="johnson_su",
        p_j=p_j,
    )

    assert output.station == "KORD"
    assert output.lead_hours == 18
    assert output.mu_calib == 72.45
    assert output.p_j["bin_72_74"] == Decimal("0.6000")

    d = output.to_dict()
    assert d["p_j"]["bin_72_74"] == "0.6000"

    reconstructed = PhysicalForecastOutput.from_dict(d)
    assert reconstructed.station == "KORD"
    assert reconstructed.p_j == p_j
    assert isinstance(reconstructed.p_j["bin_72_74"], Decimal)


def test_physical_param_contract_get_cell_success():
    """Verify querying an existing cell returns the record."""
    r12 = _make_sample_record("KORD", 12)
    r18 = _make_sample_record("KORD", 18)
    contract = PhysicalParamContract(
        contract_version="1.0.0",
        manifest_sha256="test_sha256_mock_hash",
        model_weights_sha256={"KORD_tmax": "hash123"},
        created_at="2026-10-21T00:00:00Z",
        cells={("KORD", 12): r12, ("KORD", 18): r18},
    )

    cell = contract.get_cell("KORD", 12)
    assert cell.station == "KORD"
    assert cell.lead_hours == 12
    assert cell == r12


def test_physical_param_contract_get_cell_missing_raises_key_error():
    """Verify querying a non-existent cell raises KeyError."""
    r12 = _make_sample_record("KORD", 12)
    contract = PhysicalParamContract(
        contract_version="1.0.0",
        manifest_sha256="test_sha256_mock_hash",
        model_weights_sha256={},
        created_at="2026-10-21T00:00:00Z",
        cells={("KORD", 12): r12},
    )

    with pytest.raises(KeyError, match="Cell \\('KMIA', 30\\) not found"):
        contract.get_cell("KMIA", 30)


def test_physical_param_contract_validation_success():
    """Verify validation passes when all 22 authorized cells are present."""
    cells = {}
    for st in AUTHORIZED_STATIONS:
        for lead in AUTHORIZED_LEAD_HOURS:
            cells[(st, lead)] = _make_sample_record(st, lead)

    assert len(cells) == TOTAL_AUTHORIZED_CELLS
    contract = PhysicalParamContract(
        contract_version="1.0.0",
        manifest_sha256="mock_manifest_sha",
        model_weights_sha256={"model": "hash"},
        created_at="2026-10-21T00:00:00Z",
        cells=cells,
    )
    assert contract.validate_cells_coverage() is True


def test_physical_param_contract_validation_missing_cell_raises():
    """Verify validation fails and raises ValueError if any cell is missing."""
    cells = {}
    for st in AUTHORIZED_STATIONS:
        for lead in AUTHORIZED_LEAD_HOURS:
            # Skip KMIA 72h
            if st == "KMIA" and lead == 72:
                continue
            cells[(st, lead)] = _make_sample_record(st, lead)

    assert len(cells) == 21
    contract = PhysicalParamContract(
        contract_version="1.0.0",
        manifest_sha256="mock_manifest_sha",
        model_weights_sha256={},
        created_at="2026-10-21T00:00:00Z",
        cells=cells,
    )
    with pytest.raises(ValueError, match="Missing 1 required calibration cells: KMIA_72h"):
        contract.validate_cells_coverage()


def test_physical_param_contract_no_global_averaging_defense():
    """Verify cell values are strictly independent (no global averaging)."""
    r_kord = _make_sample_record("KORD", 12)
    r_kmia = CellCalibrationRecord(
        station="KMIA",
        lead_hours=30,
        variable="tmax",
        s_oos=1.364,
        fstd_lo=0.825,
        fstd_hi=1.251,
        fstd_in=False,
        ece_2f=0.0125,
        v1_coverage_90=0.859890,
        v1_coverage_90_pass=True,
        pit_mean=0.505,
        pit_var=0.0885,
        reject_uniform=False,
        neff=295.0,
        cvm_stat=0.052,
        cvm_p=0.812,
        ece_range=0.0082,
    )
    contract = PhysicalParamContract(
        contract_version="1.0.0",
        manifest_sha256="sha",
        model_weights_sha256={},
        created_at="2026-10-21T00:00:00Z",
        cells={("KORD", 12): r_kord, ("KMIA", 30): r_kmia},
    )
    cell1 = contract.get_cell("KORD", 12)
    cell2 = contract.get_cell("KMIA", 30)

    assert cell1.s_oos != cell2.s_oos
    assert cell1.fstd_in is True
    assert cell2.fstd_in is False


def test_physical_param_contract_dict_roundtrip():
    """Verify complete PhysicalParamContract dict serialization."""
    cells = {
        ("KORD", 12): _make_sample_record("KORD", 12),
        ("KMIA", 18): _make_sample_record("KMIA", 18),
    }
    contract = PhysicalParamContract(
        contract_version="1.0.0",
        manifest_sha256="abc123sha",
        model_weights_sha256={"KORD_tmax": "sha_weight_1"},
        created_at="2026-10-21T12:00:00Z",
        cells=cells,
    )
    d = contract.to_dict()

    assert d["contract_version"] == "1.0.0"
    assert d["manifest_sha256"] == "abc123sha"
    assert d["model_weights_sha256"] == {"KORD_tmax": "sha_weight_1"}
    assert d["created_at"] == "2026-10-21T12:00:00Z"
    assert "cells" in d
    assert len(d["cells"]) == 2

    reconstructed = PhysicalParamContract.from_dict(d)
    assert reconstructed.contract_version == "1.0.0"
    assert reconstructed.manifest_sha256 == "abc123sha"
    assert reconstructed.model_weights_sha256 == {"KORD_tmax": "sha_weight_1"}
    assert reconstructed.get_cell("KORD", 12) == contract.get_cell("KORD", 12)
    assert reconstructed.get_cell("KMIA", 18) == contract.get_cell("KMIA", 18)


def test_physical_param_contract_key_mismatch_raises_value_error():
    """Verify from_dict detects outer key mismatching inner cell identity."""
    record = _make_sample_record("KORD", 12)
    d = {
        "contract_version": "1.0.0",
        "manifest_sha256": "sha",
        "model_weights_sha256": {},
        "created_at": "2026-10-21T00:00:00Z",
        "cells": {
            "KMIA_30h": record.to_dict()  # Mismatch: key says KMIA_30h but record is KORD_12h
        },
    }
    with pytest.raises(ValueError, match="Cell key mismatch: outer key 'KMIA_30h' does not match"):
        PhysicalParamContract.from_dict(d)
