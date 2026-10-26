"""
Unit tests for Parameter Table Converter (Phase 2 Task 08 - Ticket 03 / #136).

Validates:
- T1: Real CSV full conversion (cells == 22, KORD 11, KMIA 11)
- T2: Missing 1 cell raises ContractConversionError listing missing cell
- T3: Extra 23rd cell raises ContractConversionError listing extra cell
- T4: Duplicate cell raises ContractConversionError
- T5: Invalid station or invalid lead raises ContractConversionError
- T6: Missing required column raises ContractConversionError listing missing column
- T7: Boolean column containing '1' or 'yes' raises ContractConversionError
- T8: Variable inconsistent across rows raises ContractConversionError
- T9: to_dict -> from_dict roundtrip equality
- T13: Integration: contract injected into watchdog passes check()
- T14: manifest_sha256 matches compute_canonical_manifest_sha256 verbatim
"""

import csv
import json
from pathlib import Path
from typing import Dict, List

import pytest

from src.contract.param_table_converter import (
    ContractConversionError,
    convert_csv_to_contract,
    export_contract_to_json,
)
from src.contract.parameter_contract import (
    AUTHORIZED_LEAD_HOURS,
    AUTHORIZED_STATIONS,
    TOTAL_AUTHORIZED_CELLS,
    PhysicalParamContract,
)
from src.contract.version_watchdog import (
    CONTRACT_VERSION,
    ContractVersionWatchdog,
    compute_canonical_manifest_sha256,
)

METRICS_REAL_PATH = Path("evidence/audit_v2/p4blind_v2r01_metrics.csv")
COMPARISON_REAL_PATH = Path("evidence/audit_v2/p4blind_v2r01_comparison.csv")
MANIFEST_REAL_PATH = Path("data/models/manifest.json")


def _read_csv_rows(path: Path) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_csv_rows(path: Path, rows: List[Dict[str, str]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_t1_real_csv_full_conversion():
    """T1: Real CSV full conversion produces exactly 22 statutory cells (11 KORD, 11 KMIA)."""
    if not METRICS_REAL_PATH.exists() or not COMPARISON_REAL_PATH.exists():
        pytest.skip("Real evidence CSV files not found")

    contract = convert_csv_to_contract(
        metrics_csv_path=METRICS_REAL_PATH,
        comparison_csv_path=COMPARISON_REAL_PATH,
        manifest_path=MANIFEST_REAL_PATH,
    )

    assert isinstance(contract, PhysicalParamContract)
    assert len(contract.cells) == TOTAL_AUTHORIZED_CELLS  # 22
    assert contract.contract_version == CONTRACT_VERSION

    kord_cells = [c for c in contract.cells.values() if c.station == "KORD"]
    kmia_cells = [c for c in contract.cells.values() if c.station == "KMIA"]
    assert len(kord_cells) == 11
    assert len(kmia_cells) == 11

    # Check that leads match exactly 12..72
    kord_leads = sorted([c.lead_hours for c in kord_cells])
    kmia_leads = sorted([c.lead_hours for c in kmia_cells])
    assert kord_leads == list(AUTHORIZED_LEAD_HOURS)
    assert kmia_leads == list(AUTHORIZED_LEAD_HOURS)

    # Check variable is tmax
    assert all(c.variable == "tmax" for c in contract.cells.values())


def test_t2_missing_single_cell_raises_error(tmp_path: Path):
    """T2: Omission of a single statutory cell raises ContractConversionError listing the missing cell."""
    m_rows = _read_csv_rows(METRICS_REAL_PATH)
    c_rows = _read_csv_rows(COMPARISON_REAL_PATH)

    # Omit KORD 72h
    m_rows = [r for r in m_rows if not (r["station"] == "KORD" and r["lead_hours"] == "72")]
    c_rows = [r for r in c_rows if not (r["station"] == "KORD" and r["lead_hours"] == "72")]

    m_file = tmp_path / "metrics_missing.csv"
    c_file = tmp_path / "comp_missing.csv"
    _write_csv_rows(m_file, m_rows)
    _write_csv_rows(c_file, c_rows)

    with pytest.raises(ContractConversionError, match=r"missing 1 cells.*KORD.*72") as exc_info:
        convert_csv_to_contract(m_file, c_file)

    assert "missing 1 cells" in str(exc_info.value)


def test_t3_extra_23rd_cell_raises_error(tmp_path: Path):
    """T3: Inclusion of a 23rd cell (or non-statutory cell) raises ContractConversionError listing extra."""
    m_rows = _read_csv_rows(METRICS_REAL_PATH)
    c_rows = _read_csv_rows(COMPARISON_REAL_PATH)

    # Duplicate a row but with non-statutory lead 6h
    extra_m = dict(m_rows[0])
    extra_m["lead_hours"] = "6"
    extra_m["cell"] = "KORD_6h_tmax"

    extra_c = dict(c_rows[0])
    extra_c["lead_hours"] = "6"

    m_rows.append(extra_m)
    c_rows.append(extra_c)

    m_file = tmp_path / "metrics_extra.csv"
    c_file = tmp_path / "comp_extra.csv"
    _write_csv_rows(m_file, m_rows)
    _write_csv_rows(c_file, c_rows)

    with pytest.raises(ContractConversionError, match=r"Unauthorized lead_hours '6'"):
        convert_csv_to_contract(m_file, c_file)


def test_t4_duplicate_cell_raises_error(tmp_path: Path):
    """T4: Duplicate cell in either CSV raises ContractConversionError."""
    m_rows = _read_csv_rows(METRICS_REAL_PATH)
    c_rows = _read_csv_rows(COMPARISON_REAL_PATH)

    # Duplicate first row in metrics
    m_rows.append(dict(m_rows[0]))

    m_file = tmp_path / "metrics_dup.csv"
    c_file = tmp_path / "comp_dup.csv"
    _write_csv_rows(m_file, m_rows)
    _write_csv_rows(c_file, c_rows)

    with pytest.raises(ContractConversionError, match=r"Duplicate cell found in metrics CSV"):
        convert_csv_to_contract(m_file, c_file)


def test_t5_unauthorized_station_raises_error(tmp_path: Path):
    """T5: Cell with non-authorized station (e.g. KATL) raises ContractConversionError."""
    m_rows = _read_csv_rows(METRICS_REAL_PATH)
    c_rows = _read_csv_rows(COMPARISON_REAL_PATH)

    m_rows[0]["station"] = "KATL"
    m_file = tmp_path / "metrics_bad_st.csv"
    c_file = tmp_path / "comp_bad_st.csv"
    _write_csv_rows(m_file, m_rows)
    _write_csv_rows(c_file, c_rows)

    with pytest.raises(ContractConversionError, match=r"Unauthorized station 'KATL'"):
        convert_csv_to_contract(m_file, c_file)


def test_t6_missing_required_column_raises_error(tmp_path: Path):
    """T6: CSV missing a statutory column raises ContractConversionError listing the missing column."""
    m_rows = _read_csv_rows(METRICS_REAL_PATH)
    c_rows = _read_csv_rows(COMPARISON_REAL_PATH)

    # Remove s_oos from all metrics rows
    for r in m_rows:
        del r["s_oos"]

    m_file = tmp_path / "metrics_missing_col.csv"
    c_file = tmp_path / "comp_missing_col.csv"
    _write_csv_rows(m_file, m_rows)
    _write_csv_rows(c_file, c_rows)

    with pytest.raises(ContractConversionError, match=r"missing required columns:.*s_oos"):
        convert_csv_to_contract(m_file, c_file)


def test_t7_invalid_boolean_values_raise_error(tmp_path: Path):
    """T7: Boolean column containing '1' or 'yes' raises ContractConversionError."""
    m_rows = _read_csv_rows(METRICS_REAL_PATH)
    c_rows = _read_csv_rows(COMPARISON_REAL_PATH)

    # Set boolean to '1' instead of 'True'
    m_rows[0]["fstd_in"] = "1"

    m_file = tmp_path / "metrics_bool1.csv"
    c_file = tmp_path / "comp_bool1.csv"
    _write_csv_rows(m_file, m_rows)
    _write_csv_rows(c_file, c_rows)

    with pytest.raises(ContractConversionError, match=r"Strictly only 'True' or 'False' allowed"):
        convert_csv_to_contract(m_file, c_file)

    # Set boolean to 'yes'
    m_rows[0]["fstd_in"] = "yes"
    _write_csv_rows(m_file, m_rows)
    with pytest.raises(ContractConversionError, match=r"Strictly only 'True' or 'False' allowed"):
        convert_csv_to_contract(m_file, c_file)


def test_t8_variable_inconsistency_raises_error(tmp_path: Path):
    """T8: Variable mismatch across rows raises ContractConversionError."""
    m_rows = _read_csv_rows(METRICS_REAL_PATH)
    c_rows = _read_csv_rows(COMPARISON_REAL_PATH)

    # Change one cell to tmin
    m_rows[5]["cell"] = "KORD_42h_tmin"

    m_file = tmp_path / "metrics_inconsistent_var.csv"
    c_file = tmp_path / "comp_inconsistent_var.csv"
    _write_csv_rows(m_file, m_rows)
    _write_csv_rows(c_file, c_rows)

    with pytest.raises(ContractConversionError, match=r"Variable mismatch across rows"):
        convert_csv_to_contract(m_file, c_file)


def test_t9_to_dict_from_dict_roundtrip():
    """T9: Contract converted from CSV undergoes perfect to_dict -> from_dict roundtrip."""
    contract = convert_csv_to_contract(
        metrics_csv_path=METRICS_REAL_PATH,
        comparison_csv_path=COMPARISON_REAL_PATH,
        manifest_path=MANIFEST_REAL_PATH,
    )
    d = contract.to_dict()
    recovered = PhysicalParamContract.from_dict(d)

    assert recovered.contract_version == contract.contract_version
    assert recovered.manifest_sha256 == contract.manifest_sha256
    assert recovered.model_weights_sha256 == contract.model_weights_sha256
    assert recovered.created_at == contract.created_at
    assert len(recovered.cells) == len(contract.cells)

    for key, orig_rec in contract.cells.items():
        rec_recovered = recovered.cells[key]
        assert rec_recovered.station == orig_rec.station
        assert rec_recovered.lead_hours == orig_rec.lead_hours
        assert rec_recovered.s_oos == orig_rec.s_oos
        assert rec_recovered.fstd_in == orig_rec.fstd_in
        assert rec_recovered.v1_coverage_90_pass == orig_rec.v1_coverage_90_pass


def test_t13_integration_contract_injected_watchdog():
    """T13: Injected contract passes ContractVersionWatchdog.check() without errors."""
    contract = convert_csv_to_contract(
        metrics_csv_path=METRICS_REAL_PATH,
        comparison_csv_path=COMPARISON_REAL_PATH,
        manifest_path=MANIFEST_REAL_PATH,
    )

    watchdog = ContractVersionWatchdog(
        manifest_path=MANIFEST_REAL_PATH, contract=contract
    )
    report = watchdog.check()

    assert report.is_valid is True
    assert report.verified_cells_count == TOTAL_AUTHORIZED_CELLS  # 22
    assert report.failed_entries == 0
    assert report.skipped_6h_entries == 64
    assert report.bypassed is False


def test_t14_manifest_sha256_matches_public_function():
    """T14: contract.manifest_sha256 exactly matches compute_canonical_manifest_sha256 verbatim."""
    with open(MANIFEST_REAL_PATH, "r", encoding="utf-8") as f:
        manifest_dict = json.load(f)
    expected_sha = compute_canonical_manifest_sha256(manifest_dict)

    contract = convert_csv_to_contract(
        metrics_csv_path=METRICS_REAL_PATH,
        comparison_csv_path=COMPARISON_REAL_PATH,
        manifest_path=MANIFEST_REAL_PATH,
    )

    assert contract.manifest_sha256 == expected_sha
    assert len(contract.manifest_sha256) == 64


def test_export_contract_to_json(tmp_path: Path):
    """Test export_contract_to_json writes formatted valid JSON."""
    contract = convert_csv_to_contract(
        metrics_csv_path=METRICS_REAL_PATH,
        comparison_csv_path=COMPARISON_REAL_PATH,
        manifest_path=MANIFEST_REAL_PATH,
    )
    out_file = tmp_path / "contracts" / "param_contract.json"
    written_path = export_contract_to_json(contract, out_file)

    assert written_path.exists()
    with open(written_path, "r", encoding="utf-8") as f:
        loaded = json.load(f)

    assert loaded["contract_version"] == CONTRACT_VERSION
    assert len(loaded["cells"]) == 22
    assert "KORD_12h" in loaded["cells"]
