"""
Unit tests for Parameter Table Converter (Phase 2 Task 08 - Ticket 03 / #136).

Validates:
- T1: Real CSV full conversion (cells == 22, KORD 11, KMIA 11)
- T2: Missing 1 cell raises ContractConversionError listing missing cell
- T3: Extra 23rd cell raises ContractConversionError (_parse_grid_key rejects lead 6)
- T4: Duplicate cell raises ContractConversionError
- T5: Invalid station or invalid lead raises ContractConversionError
- T6: Missing required column raises ContractConversionError listing missing column
- T7: Boolean column containing '1' or 'yes' raises ContractConversionError
- T8: Variable inconsistent across rows raises ContractConversionError
- T9: to_dict -> from_dict roundtrip equality
- T13: Integration: contract injected into watchdog passes check()
- T14: manifest_sha256 matches compute_canonical_manifest_sha256 verbatim
- Export: export_contract_to_json writes valid formatted JSON
- T16: Model weights derived from manifest with 88 models and M-1 manifest_path check
- T17: Structural assertion of 4 seasons x max variable per cell across 22 cells
- T18: Missing model file in manifest raises ContractConversionError
- T21: Bidirectional mechanical cell column alignment check (station/lead/variable)
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
    """T1: Real CSV full conversion produces exactly 22 statutory cells and 88 model weights."""
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
    assert len(contract.model_weights_sha256) == 88

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
    """T2: Omission of a single statutory cell raises ContractConversionError listing missing cell."""
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
        convert_csv_to_contract(m_file, c_file, manifest_path=MANIFEST_REAL_PATH)

    assert "missing 1 cells" in str(exc_info.value)


def test_t3_extra_23rd_cell_raises_error(tmp_path: Path):
    """T3: Inclusion of a non-statutory lead 6h raises ContractConversionError via _parse_grid_key."""
    m_rows = _read_csv_rows(METRICS_REAL_PATH)
    c_rows = _read_csv_rows(COMPARISON_REAL_PATH)

    # Add a row with non-statutory lead 6h
    extra_m = dict(m_rows[0])
    extra_m["lead_hours"] = "6"
    extra_m["cell"] = "KORD_6h_tmax"

    extra_c = dict(c_rows[0])
    extra_c["lead_hours"] = "6"
    extra_c["cell"] = "KORD_6h_tmax"

    m_rows.append(extra_m)
    c_rows.append(extra_c)

    m_file = tmp_path / "metrics_extra.csv"
    c_file = tmp_path / "comp_extra.csv"
    _write_csv_rows(m_file, m_rows)
    _write_csv_rows(c_file, c_rows)

    with pytest.raises(ContractConversionError, match=r"Unauthorized lead_hours '6'"):
        convert_csv_to_contract(m_file, c_file, manifest_path=MANIFEST_REAL_PATH)


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
        convert_csv_to_contract(m_file, c_file, manifest_path=MANIFEST_REAL_PATH)


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
        convert_csv_to_contract(m_file, c_file, manifest_path=MANIFEST_REAL_PATH)


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
        convert_csv_to_contract(m_file, c_file, manifest_path=MANIFEST_REAL_PATH)


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
        convert_csv_to_contract(m_file, c_file, manifest_path=MANIFEST_REAL_PATH)

    # Set boolean to 'yes'
    m_rows[0]["fstd_in"] = "yes"
    _write_csv_rows(m_file, m_rows)
    with pytest.raises(ContractConversionError, match=r"Strictly only 'True' or 'False' allowed"):
        convert_csv_to_contract(m_file, c_file, manifest_path=MANIFEST_REAL_PATH)


def test_t8_variable_inconsistency_across_rows_raises_error(tmp_path: Path):
    """T8: Variable mismatch across rows raises ContractConversionError."""
    m_rows = _read_csv_rows(METRICS_REAL_PATH)
    c_rows = _read_csv_rows(COMPARISON_REAL_PATH)

    # Change one cell in metrics and comparison to tmin
    m_rows[5]["cell"] = "KORD_42h_tmin"
    c_rows[5]["cell"] = "KORD_42h_tmin"

    m_file = tmp_path / "metrics_inconsistent_var.csv"
    c_file = tmp_path / "comp_inconsistent_var.csv"
    _write_csv_rows(m_file, m_rows)
    _write_csv_rows(c_file, c_rows)

    with pytest.raises(ContractConversionError, match=r"Variable mismatch across rows"):
        convert_csv_to_contract(m_file, c_file, manifest_path=MANIFEST_REAL_PATH)


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
    assert len(loaded["model_weights_sha256"]) == 88


def test_t16_model_weights_derived_from_manifest():
    """T16: Model weights derived from manifest with 88 models, and M-1 manifest_path=None check."""
    # M-1 check: manifest_path=None raises ContractConversionError
    with pytest.raises(ContractConversionError, match="manifest_path cannot be None"):
        convert_csv_to_contract(
            metrics_csv_path=METRICS_REAL_PATH,
            comparison_csv_path=COMPARISON_REAL_PATH,
            manifest_path=None,
        )

    # Normal derivation
    contract = convert_csv_to_contract(
        metrics_csv_path=METRICS_REAL_PATH,
        comparison_csv_path=COMPARISON_REAL_PATH,
        manifest_path=MANIFEST_REAL_PATH,
    )
    weights = contract.model_weights_sha256
    assert len(weights) == 88
    for fname, sha in weights.items():
        assert fname.endswith(".pkl")
        assert len(sha) == 64
        assert all(c in "0123456789abcdef" for c in sha)
        assert "_lead6h" not in fname  # 6h explicitly excluded


def test_t17_structural_assertion_seasons_and_variable_consistency():
    """T17: Structural assertion: each cell has 4 seasons of max variable, identical across 22 cells."""
    contract = convert_csv_to_contract(
        metrics_csv_path=METRICS_REAL_PATH,
        comparison_csv_path=COMPARISON_REAL_PATH,
        manifest_path=MANIFEST_REAL_PATH,
    )
    seasons = {"Winter", "Spring", "Summer", "Autumn"}
    weights = contract.model_weights_sha256

    for station in AUTHORIZED_STATIONS:
        for lead in AUTHORIZED_LEAD_HOURS:
            for season in seasons:
                expected_fname = f"{station}_{season}_Max_lead{lead}h.pkl"
                assert expected_fname in weights, f"Missing expected model: {expected_fname}"


def test_t18_missing_manifest_model_raises_error(tmp_path: Path):
    """T18: Omission of a required model file from manifest raises ContractConversionError."""
    with open(MANIFEST_REAL_PATH, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    # Delete one required seasonal model from manifest -> triggers inconsistent set error
    del manifest_data["models"]["KORD_Winter_Max_lead12h.pkl"]

    tampered_manifest = tmp_path / "tampered_manifest.json"
    tampered_manifest.write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ContractConversionError, match=r"Inconsistent \(season, variable\) set for cell \('KORD', 12\)"):
        convert_csv_to_contract(
            metrics_csv_path=METRICS_REAL_PATH,
            comparison_csv_path=COMPARISON_REAL_PATH,
            manifest_path=tampered_manifest,
        )

    # Also test deleting all 4 seasons of a cell -> triggers missing cell coverage error
    for s in ["Spring", "Summer", "Autumn"]:
        del manifest_data["models"][f"KORD_{s}_Max_lead12h.pkl"]
    tampered_manifest.write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ContractConversionError, match=r"Missing model weights coverage for 1 statutory cells"):
        convert_csv_to_contract(
            metrics_csv_path=METRICS_REAL_PATH,
            comparison_csv_path=COMPARISON_REAL_PATH,
            manifest_path=tampered_manifest,
        )


def test_t21_mechanical_cell_column_alignment_assertion(tmp_path: Path):
    """T21: (R-1 / B-1) Mechanical cell string alignment check against station/lead/variable."""
    m_rows = _read_csv_rows(METRICS_REAL_PATH)
    c_rows = _read_csv_rows(COMPARISON_REAL_PATH)

    # 1. Metrics cell station mismatch
    bad_m = [dict(r) for r in m_rows]
    bad_m[0]["cell"] = "KMIA_12h_tmax"  # row station is KORD
    m_file1 = tmp_path / "m1.csv"
    _write_csv_rows(m_file1, bad_m)
    with pytest.raises(ContractConversionError, match="Cell station segment 'KMIA' does not match"):
        convert_csv_to_contract(m_file1, COMPARISON_REAL_PATH, MANIFEST_REAL_PATH)

    # 2. Metrics cell lead mismatch
    bad_m = [dict(r) for r in m_rows]
    bad_m[0]["cell"] = "KORD_18h_tmax"  # row lead is 12
    m_file2 = tmp_path / "m2.csv"
    _write_csv_rows(m_file2, bad_m)
    with pytest.raises(ContractConversionError, match="Cell lead segment '18h' does not match"):
        convert_csv_to_contract(m_file2, COMPARISON_REAL_PATH, MANIFEST_REAL_PATH)

    # 3. Comparison cell station mismatch
    bad_c = [dict(r) for r in c_rows]
    bad_c[0]["cell"] = "KMIA_12h_tmax"  # row station is KORD
    c_file3 = tmp_path / "c3.csv"
    _write_csv_rows(c_file3, bad_c)
    with pytest.raises(ContractConversionError, match="Cell station segment 'KMIA' does not match"):
        convert_csv_to_contract(METRICS_REAL_PATH, c_file3, MANIFEST_REAL_PATH)

    # 4. Comparison cell lead mismatch
    bad_c = [dict(r) for r in c_rows]
    bad_c[0]["cell"] = "KORD_24h_tmax"  # row lead is 12
    c_file4 = tmp_path / "c4.csv"
    _write_csv_rows(c_file4, bad_c)
    with pytest.raises(ContractConversionError, match="Cell lead segment '24h' does not match"):
        convert_csv_to_contract(METRICS_REAL_PATH, c_file4, MANIFEST_REAL_PATH)

    # 5. Variable mismatch between metrics and comparison
    bad_c = [dict(r) for r in c_rows]
    bad_c[0]["cell"] = "KORD_12h_tmin"  # metrics has tmax
    c_file5 = tmp_path / "c5.csv"
    _write_csv_rows(c_file5, bad_c)
    with pytest.raises(ContractConversionError, match="Variable mismatch between metrics"):
        convert_csv_to_contract(METRICS_REAL_PATH, c_file5, MANIFEST_REAL_PATH)
