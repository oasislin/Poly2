"""
Unit tests for Physical Parameter Consumption Contract (Ticket 01 / Phase 2 Task 08).
Validates ADR-0019 specifications:
- Strongly typed, immutable CellCalibrationRecord with mandatory & indirect consumption fields.
- 22-cell structure (KORD/KMIA * 11 lead hours).
- Frozen immutability preventing downstream tampering.
- Prevention of global averaging.
"""

from dataclasses import FrozenInstanceError
import pytest

from src.contract.parameter_contract import (
    CellCalibrationRecord,
    PhysicalParamContract,
    AUTHORIZED_STATIONS,
    AUTHORIZED_LEAD_HOURS,
)


def _make_sample_record(station: str = "KORD", lead_hours: int = 12) -> CellCalibrationRecord:
    """Helper to generate a valid test record."""
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


def test_physical_param_contract_get_cell_success():
    """Verify querying an existing cell returns the record."""
    r12 = _make_sample_record("KORD", 12)
    r18 = _make_sample_record("KORD", 18)
    contract = PhysicalParamContract(
        cells={("KORD", 12): r12, ("KORD", 18): r18},
        manifest_sha256="test_sha256_mock_hash",
    )

    cell = contract.get_cell("KORD", 12)
    assert cell.station == "KORD"
    assert cell.lead_hours == 12
    assert cell == r12


def test_physical_param_contract_get_cell_missing_raises_key_error():
    """Verify querying a non-existent cell raises KeyError."""
    r12 = _make_sample_record("KORD", 12)
    contract = PhysicalParamContract(cells={("KORD", 12): r12})

    with pytest.raises(KeyError, match="Cell \\('KMIA', 30\\) not found"):
        contract.get_cell("KMIA", 30)


def test_physical_param_contract_validation_success():
    """Verify validation passes when all 22 authorized cells are present."""
    cells = {}
    for st in AUTHORIZED_STATIONS:
        for lead in AUTHORIZED_LEAD_HOURS:
            cells[(st, lead)] = _make_sample_record(st, lead)

    assert len(cells) == 22
    contract = PhysicalParamContract(cells=cells, manifest_sha256="mock_manifest_sha")
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
    contract = PhysicalParamContract(cells=cells)
    with pytest.raises(ValueError, match="Missing 1 required calibration cells: KMIA_72h"):
        contract.validate_cells_coverage()


def test_physical_param_contract_no_global_averaging_defense():
    """Verify cell values are strictly independent (no global averaging)."""
    r_kord = _make_sample_record("KORD", 12)
    r_kmia = CellCalibrationRecord(
        station="KMIA",
        lead_hours=30,
        variable="tmax",
        s_oos=1.364,  # Miami under-confident
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
    contract = PhysicalParamContract(cells={("KORD", 12): r_kord, ("KMIA", 30): r_kmia})
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
    contract = PhysicalParamContract(cells=cells, manifest_sha256="abc123sha")
    d = contract.to_dict()

    assert d["manifest_sha256"] == "abc123sha"
    assert "cells" in d
    assert len(d["cells"]) == 2

    reconstructed = PhysicalParamContract.from_dict(d)
    assert reconstructed.manifest_sha256 == "abc123sha"
    assert reconstructed.get_cell("KORD", 12) == contract.get_cell("KORD", 12)
    assert reconstructed.get_cell("KMIA", 18) == contract.get_cell("KMIA", 18)
