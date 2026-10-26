#!/usr/bin/env python3
"""
Parameter Table Converter (Phase 2 Task 08 - Ticket 03 / #136).

Converts V2 continuous calibration blind test CSVs (metrics and comparison)
into a frozen, statutory 22-grid PhysicalParamContract instance and serialized JSON.
Strictly adheres to ADR-0019 §三 and zero numerical threshold recalculation rules.
"""

import argparse
import csv
import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from src.contract.parameter_contract import (
    AUTHORIZED_LEAD_HOURS,
    AUTHORIZED_STATIONS,
    TOTAL_AUTHORIZED_CELLS,
    CellCalibrationRecord,
    PhysicalParamContract,
)
from src.contract.version_watchdog import (
    CONTRACT_VERSION,
    ContractGuardrailError,
    compute_canonical_manifest_sha256,
)

logger = logging.getLogger(__name__)

# Statutory columns required in metrics CSV
REQUIRED_METRICS_COLUMNS = {
    "station",
    "lead_hours",
    "cell",
    "s_oos",
    "fstd_lo",
    "fstd_hi",
    "fstd_in",
    "ece_2f",
    "pit_mean",
    "pit_var",
    "reject_uniform",
    "neff",
    "cvm_stat",
    "cvm_p",
    "ece_range",
}

# Statutory columns required in comparison CSV
REQUIRED_COMPARISON_COLUMNS = {
    "station",
    "lead_hours",
    "v1_coverage_90",
    "v1_coverage_90_pass",
}


class ContractConversionError(ContractGuardrailError):
    """CSV 转 22 格法定契约过程中的结构、格式或网格校验失败异常."""

    pass


def _parse_strict_bool(val: Any, col_name: str, station: str, lead: int) -> bool:
    """Parse strict boolean. Only 'true' or 'false' (case-insensitive) permitted."""
    s = str(val).strip().lower()
    if s == "true":
        return True
    if s == "false":
        return False
    raise ContractConversionError(
        f"Invalid boolean value '{val}' in column '{col_name}' for cell ({station}, {lead}h). "
        f"Strictly only 'True' or 'False' allowed (values like '1', 'yes', '0' are rejected)."
    )


def _parse_strict_float(val: Any, col_name: str, station: str, lead: int) -> float:
    """Parse strict float without NaN/inf."""
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            raise ValueError(f"NaN/Inf not permitted: {f}")
        return f
    except (ValueError, TypeError) as exc:
        raise ContractConversionError(
            f"Invalid numeric value '{val}' in column '{col_name}' for cell ({station}, {lead}h): {exc}"
        ) from exc


def _read_and_validate_csv(
    file_path: Path, required_columns: Set[str], label: str
) -> List[Dict[str, str]]:
    """Read CSV file and verify presence of all statutory required columns."""
    if not file_path.exists():
        raise ContractConversionError(f"{label} CSV file not found: {file_path}")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise ContractConversionError(f"{label} CSV is empty or invalid header: {file_path}")
            header_set = set(reader.fieldnames)
            missing_cols = required_columns - header_set
            if missing_cols:
                raise ContractConversionError(
                    f"{label} CSV missing required columns: {sorted(missing_cols)} in {file_path}"
                )
            return list(reader)
    except Exception as exc:
        if isinstance(exc, ContractConversionError):
            raise
        raise ContractConversionError(f"Failed to read {label} CSV at {file_path}: {exc}") from exc


def _parse_grid_key(row: Dict[str, str], row_idx: int) -> Tuple[str, int]:
    """Extract and validate (station, lead_hours) statutory tuple from row."""
    station = str(row.get("station", "")).strip().upper()
    lead_str = str(row.get("lead_hours", "")).strip()

    if station not in AUTHORIZED_STATIONS:
        raise ContractConversionError(
            f"Row {row_idx}: Unauthorized station '{station}'. Expected one of {AUTHORIZED_STATIONS}"
        )

    try:
        lead = int(lead_str)
    except (ValueError, TypeError) as exc:
        raise ContractConversionError(
            f"Row {row_idx}: Invalid lead_hours '{lead_str}' for station '{station}': {exc}"
        ) from exc

    if lead not in AUTHORIZED_LEAD_HOURS:
        raise ContractConversionError(
            f"Row {row_idx}: Unauthorized lead_hours '{lead}'. Expected one of {AUTHORIZED_LEAD_HOURS}"
        )

    return station, lead


def _load_metrics_map(
    rows: List[Dict[str, str]]
) -> Dict[Tuple[str, int], Dict[str, str]]:
    """Map metrics rows by (station, lead_hours) with duplicate checking."""
    metrics_map: Dict[Tuple[str, int], Dict[str, str]] = {}
    for idx, row in enumerate(rows, start=1):
        key = _parse_grid_key(row, idx)
        if key in metrics_map:
            raise ContractConversionError(f"Duplicate cell found in metrics CSV: {key}")
        metrics_map[key] = row
    return metrics_map


def _load_comparison_map(
    rows: List[Dict[str, str]]
) -> Dict[Tuple[str, int], Dict[str, str]]:
    """Map comparison rows by (station, lead_hours) with duplicate checking."""
    comp_map: Dict[Tuple[str, int], Dict[str, str]] = {}
    for idx, row in enumerate(rows, start=1):
        key = _parse_grid_key(row, idx)
        if key in comp_map:
            raise ContractConversionError(f"Duplicate cell found in comparison CSV: {key}")
        comp_map[key] = row
    return comp_map


def _assert_exact_22_cells(cells_keys: Set[Tuple[str, int]]) -> None:
    """Assert that cells set contains EXACTLY the 22 statutory grid cells."""
    expected_cells: Set[Tuple[str, int]] = {
        (s, h) for s in AUTHORIZED_STATIONS for h in AUTHORIZED_LEAD_HOURS
    }
    missing_cells = expected_cells - cells_keys
    extra_cells = cells_keys - expected_cells

    if missing_cells or extra_cells:
        msg_parts = []
        if missing_cells:
            msg_parts.append(f"missing {len(missing_cells)} cells: {sorted(missing_cells)}")
        if extra_cells:
            msg_parts.append(f"extra {len(extra_cells)} cells: {sorted(extra_cells)}")
        raise ContractConversionError(
            f"Statutory 22-grid mismatch (got {len(cells_keys)} cells): {'; '.join(msg_parts)}"
        )


def _build_single_cell_record(
    station: str,
    lead: int,
    m_row: Dict[str, str],
    c_row: Dict[str, str],
    expected_var: Optional[str] = None,
) -> Tuple[CellCalibrationRecord, str]:
    """Parse a single cell calibration record from joined metrics and comparison rows."""
    cell_raw = str(m_row.get("cell", "")).strip()
    var_parsed = cell_raw.rsplit("_", 1)[-1].lower() if "_" in cell_raw else ""
    if not var_parsed:
        raise ContractConversionError(
            f"Failed to parse variable from cell '{cell_raw}' for ({station}, {lead}h)"
        )

    if expected_var is not None and var_parsed != expected_var:
        raise ContractConversionError(
            f"Variable mismatch across rows: expected '{expected_var}', got '{var_parsed}' for ({station}, {lead}h)"
        )

    record = CellCalibrationRecord(
        station=station,
        lead_hours=lead,
        variable=var_parsed,
        s_oos=_parse_strict_float(m_row["s_oos"], "s_oos", station, lead),
        fstd_lo=_parse_strict_float(m_row["fstd_lo"], "fstd_lo", station, lead),
        fstd_hi=_parse_strict_float(m_row["fstd_hi"], "fstd_hi", station, lead),
        fstd_in=_parse_strict_bool(m_row["fstd_in"], "fstd_in", station, lead),
        ece_2f=_parse_strict_float(m_row["ece_2f"], "ece_2f", station, lead),
        v1_coverage_90=_parse_strict_float(c_row["v1_coverage_90"], "v1_coverage_90", station, lead),
        v1_coverage_90_pass=_parse_strict_bool(c_row["v1_coverage_90_pass"], "v1_coverage_90_pass", station, lead),
        pit_mean=_parse_strict_float(m_row["pit_mean"], "pit_mean", station, lead),
        pit_var=_parse_strict_float(m_row["pit_var"], "pit_var", station, lead),
        reject_uniform=_parse_strict_bool(m_row["reject_uniform"], "reject_uniform", station, lead),
        neff=_parse_strict_float(m_row["neff"], "neff", station, lead),
        cvm_stat=_parse_strict_float(m_row["cvm_stat"], "cvm_stat", station, lead),
        cvm_p=_parse_strict_float(m_row["cvm_p"], "cvm_p", station, lead),
        ece_range=_parse_strict_float(m_row["ece_range"], "ece_range", station, lead),
    )
    return record, var_parsed


def _build_cells_dict(
    m_map: Dict[Tuple[str, int], Dict[str, str]],
    c_map: Dict[Tuple[str, int], Dict[str, str]],
) -> Dict[Tuple[str, int], CellCalibrationRecord]:
    """Build statutory 22 cells dictionary with variable consistency assertion."""
    cells_dict: Dict[Tuple[str, int], CellCalibrationRecord] = {}
    expected_var: Optional[str] = None

    for station in AUTHORIZED_STATIONS:
        for lead in AUTHORIZED_LEAD_HOURS:
            key = (station, lead)
            record, var_parsed = _build_single_cell_record(
                station, lead, m_map[key], c_map[key], expected_var
            )
            if expected_var is None:
                expected_var = var_parsed
            cells_dict[key] = record

    return cells_dict


def convert_csv_to_contract(
    metrics_csv_path: Union[str, Path],
    comparison_csv_path: Union[str, Path],
    manifest_path: Optional[Union[str, Path]] = None,
    *,
    model_weights_sha256: Optional[Dict[str, str]] = None,
    created_at: Optional[str] = None,
) -> PhysicalParamContract:
    """
    Convert V2 metrics and comparison CSVs into a statutory 22-grid PhysicalParamContract.
    Strictly verifies EXACT 22 cell coverage, fail-closed type validation, and ADR-0019 alignment.
    """
    m_path = Path(metrics_csv_path)
    c_path = Path(comparison_csv_path)

    m_rows = _read_and_validate_csv(m_path, REQUIRED_METRICS_COLUMNS, "Metrics")
    c_rows = _read_and_validate_csv(c_path, REQUIRED_COMPARISON_COLUMNS, "Comparison")

    m_map = _load_metrics_map(m_rows)
    c_map = _load_comparison_map(c_rows)

    _assert_exact_22_cells(set(m_map.keys()))
    _assert_exact_22_cells(set(c_map.keys()))

    cells_dict = _build_cells_dict(m_map, c_map)
    manifest_sha = _resolve_manifest_sha(manifest_path)
    weights_map = dict(model_weights_sha256 or {})
    ts = created_at or datetime.now(timezone.utc).isoformat()

    return PhysicalParamContract(
        contract_version=CONTRACT_VERSION,
        manifest_sha256=manifest_sha,
        model_weights_sha256=weights_map,
        created_at=ts,
        cells=cells_dict,
    )


def _resolve_manifest_sha(manifest_path: Optional[Union[str, Path]]) -> str:
    """Resolve canonical SHA256 of manifest.json if provided, else return empty string."""
    if manifest_path is None:
        return ""
    m_file = Path(manifest_path)
    if not m_file.exists():
        raise ContractConversionError(f"Manifest file not found: {m_file}")
    try:
        with open(m_file, "r", encoding="utf-8") as f:
            manifest_dict = json.load(f)
        return compute_canonical_manifest_sha256(manifest_dict)
    except Exception as exc:
        raise ContractConversionError(f"Failed to read/hash manifest at {m_file}: {exc}") from exc


def export_contract_to_json(
    contract: PhysicalParamContract, output_path: Union[str, Path]
) -> Path:
    """Serialize PhysicalParamContract instance to formatted JSON on disk."""
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    serialized_dict = contract.to_dict()
    out_file.write_text(json.dumps(serialized_dict, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_file


def main() -> None:
    """CLI entrypoint for parameter table converter."""
    parser = argparse.ArgumentParser(description="Convert V2 blind test CSVs to statutory contract JSON.")
    parser.add_argument("--metrics", required=True, help="Path to p4blind_v2r01_metrics.csv")
    parser.add_argument("--comparison", required=True, help="Path to p4blind_v2r01_comparison.csv")
    parser.add_argument("--manifest", default="data/models/manifest.json", help="Path to manifest.json")
    parser.add_argument("--output", default="data/contracts/physical_param_contract.json", help="Output path")
    args = parser.parse_args()

    contract = convert_csv_to_contract(
        metrics_csv_path=args.metrics,
        comparison_csv_path=args.comparison,
        manifest_path=args.manifest,
    )
    out_path = export_contract_to_json(contract, args.output)
    print(f"Contract successfully exported to: {out_path}")
    print(f"Total cells: {len(contract.cells)}, Version: {contract.contract_version}")


if __name__ == "__main__":
    main()
