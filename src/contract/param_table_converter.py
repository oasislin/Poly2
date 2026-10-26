#!/usr/bin/env python3
"""
Parameter Table Converter (Phase 2 Task 08 - Ticket 03 / #136).

Converts V2 continuous calibration blind test CSVs (metrics and comparison)
into a frozen, statutory 22-grid PhysicalParamContract instance and serialized JSON.
Strictly adheres to ADR-0019 §三, zero numerical threshold recalculation rules,
and derives statutory model weights directly from manifest.json.
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
    AUTHORIZED_LEADS_FOR_GUARD,
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

# Statutory columns required in comparison CSV (including cell for mechanical alignment)
REQUIRED_COMPARISON_COLUMNS = {
    "station",
    "lead_hours",
    "cell",
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
        if not math.isfinite(f):
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


def _load_csv_grid_map(
    rows: List[Dict[str, str]], label: str
) -> Dict[Tuple[str, int], Dict[str, str]]:
    """Map CSV rows by (station, lead_hours) with duplicate checking."""
    grid_map: Dict[Tuple[str, int], Dict[str, str]] = {}
    for idx, row in enumerate(rows, start=1):
        key = _parse_grid_key(row, idx)
        if key in grid_map:
            raise ContractConversionError(f"Duplicate cell found in {label} CSV: {key}")
        grid_map[key] = row
    return grid_map


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


def _parse_and_validate_cell_str(
    cell_str: str, station: str, lead: int, source_label: str
) -> str:
    """
    Validate cell column string format and mechanical alignment with station and lead.
    (R-1 / B-1). Format must be '<station>_<lead>h_<variable>'.
    """
    parts = cell_str.split("_")
    if len(parts) != 3:
        raise ContractConversionError(
            f"Invalid cell format '{cell_str}' in {source_label}: "
            f"expected '<station>_<lead>h_<variable>', got '{cell_str}'"
        )
    st_part, lead_part, var_part = parts[0].upper(), parts[1].lower(), parts[2].lower()
    if st_part != station:
        raise ContractConversionError(
            f"Cell station segment '{st_part}' does not match row station '{station}' "
            f"in {source_label} for cell '{cell_str}'"
        )
    expected_lead = f"{lead}h"
    if lead_part != expected_lead:
        raise ContractConversionError(
            f"Cell lead segment '{lead_part}' does not match row lead '{expected_lead}' "
            f"in {source_label} for cell '{cell_str}'"
        )
    if not var_part:
        raise ContractConversionError(
            f"Empty variable segment in cell '{cell_str}' in {source_label}"
        )
    return var_part


def _build_single_cell_record(
    station: str,
    lead: int,
    m_row: Dict[str, str],
    c_row: Dict[str, str],
    expected_var: Optional[str] = None,
) -> Tuple[CellCalibrationRecord, str]:
    """Parse a single cell calibration record from joined metrics and comparison rows."""
    m_cell = str(m_row.get("cell", "")).strip()
    c_cell = str(c_row.get("cell", "")).strip()

    m_var = _parse_and_validate_cell_str(m_cell, station, lead, "metrics CSV")
    c_var = _parse_and_validate_cell_str(c_cell, station, lead, "comparison CSV")

    if m_var != c_var:
        raise ContractConversionError(
            f"Variable mismatch between metrics ('{m_var}') and comparison ('{c_var}') "
            f"for cell ({station}, {lead}h)"
        )

    if expected_var is not None and m_var != expected_var:
        raise ContractConversionError(
            f"Variable mismatch across rows: expected '{expected_var}', got '{m_var}' "
            f"for cell ({station}, {lead}h)"
        )

    record = CellCalibrationRecord(
        station=station,
        lead_hours=lead,
        variable=m_var,
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
    return record, m_var


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


def _extract_model_weights_from_manifest(
    manifest_dict: Dict[str, Any]
) -> Dict[str, str]:
    """
    Extract model file SHA256 hashes for statutory betting contract from manifest.
    Filter conditions per ADR-0019 / Ticket 03:
    - station in AUTHORIZED_STATIONS
    - lead_hours in AUTHORIZED_LEADS_FOR_GUARD (12..72h, explicitly excludes 6h)
    - str(meta.get("variable", "")).lower() == "max"

    CRITICAL RULES:
    - Do NOT filter by status (Ruling D6: AUX tags have no permission/exclusion meaning;
      60h lead across all seasons is labeled AUXILIARY_POOLED_FALLBACK).
    - Do NOT determine variable via filename substring; use meta['variable'].
    - Variable 'min' (88 models) is explicitly excluded for Phase 2 Task 08 Class 1 scope;
      will be extended when tmin enters betting layer.
    """
    if "models" not in manifest_dict or not isinstance(manifest_dict["models"], dict):
        raise ContractConversionError("Manifest missing 'models' dictionary")

    models = manifest_dict["models"]
    weights_map: Dict[str, str] = {}
    seasons_by_cell: Dict[Tuple[str, int], Set[Tuple[str, str]]] = {}

    for fname, meta in models.items():
        if not isinstance(meta, dict):
            raise ContractConversionError(f"Model entry '{fname}' metadata must be a dictionary")

        station_raw = meta.get("station")
        lead_raw = meta.get("lead_hours")
        var_raw = meta.get("variable")
        if station_raw is None or lead_raw is None or var_raw is None:
            continue

        station = str(station_raw).upper()
        try:
            lead = int(lead_raw)
        except (ValueError, TypeError):
            continue

        var = str(var_raw).lower()

        # Strict filter per ADR-0019 / Ruling D6
        if station in AUTHORIZED_STATIONS and lead in AUTHORIZED_LEADS_FOR_GUARD and var == "max":
            sha = str(meta.get("sha256", "")).lower()
            if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
                raise ContractConversionError(
                    f"Model '{fname}' has invalid SHA256 in manifest: '{sha}' (must be 64-hex)"
                )
            weights_map[fname] = sha
            season = str(meta.get("season", ""))
            seasons_by_cell.setdefault((station, lead), set()).add((season, var))

    # Structural assertions (without hardcoding magic numbers):
    # 1. Exactly 22 statutory cells must be present in seasons_by_cell
    expected_cells = {
        (st, lead) for st in AUTHORIZED_STATIONS for lead in AUTHORIZED_LEADS_FOR_GUARD
    }
    missing_cells = expected_cells - set(seasons_by_cell.keys())
    if missing_cells:
        raise ContractConversionError(
            f"Missing model weights coverage for {len(missing_cells)} statutory cells: {sorted(missing_cells)}"
        )

    # 2. Every cell must have a non-empty (season, variable) set, and all 22 cells must have identical sets
    first_set = next(iter(seasons_by_cell.values()))
    if not first_set:
        raise ContractConversionError("Empty (season, variable) set for model weights")
    for cell, s_set in seasons_by_cell.items():
        if s_set != first_set:
            raise ContractConversionError(
                f"Inconsistent (season, variable) set for cell {cell}: expected {first_set}, got {s_set}"
            )
        if any(v != "max" for _, v in s_set):
            raise ContractConversionError(
                f"Non-max variable detected in model weights set for cell {cell}: {s_set}"
            )

    return weights_map


def _load_manifest_sha_and_weights(
    manifest_path: Optional[Union[str, Path]]
) -> Tuple[str, Dict[str, str]]:
    """
    Resolve canonical SHA256 and statutory weights from manifest.json.
    (M-1: Fails closed with ContractConversionError if manifest_path is None or missing).
    """
    if manifest_path is None:
        raise ContractConversionError(
            "manifest_path cannot be None; manifest is required for statutory model weights and canonical hash"
        )
    m_file = Path(manifest_path)
    if not m_file.exists():
        raise ContractConversionError(f"Manifest file not found: {m_file}")

    try:
        with open(m_file, "r", encoding="utf-8") as f:
            manifest_dict = json.load(f)
    except Exception as exc:
        raise ContractConversionError(f"Failed to read manifest JSON at {m_file}: {exc}") from exc

    canonical_sha = compute_canonical_manifest_sha256(manifest_dict)
    weights_map = _extract_model_weights_from_manifest(manifest_dict)
    return canonical_sha, weights_map


def convert_csv_to_contract(
    metrics_csv_path: Union[str, Path],
    comparison_csv_path: Union[str, Path],
    manifest_path: Optional[Union[str, Path]] = None,
    *,
    created_at: Optional[str] = None,
) -> PhysicalParamContract:
    """
    Convert V2 metrics and comparison CSVs into a statutory 22-grid PhysicalParamContract.
    Strictly verifies EXACT 22 cell coverage, fail-closed type validation, and ADR-0019 alignment.
    Derives model_weights_sha256 directly from manifest.json (external injection prohibited).
    """
    m_path = Path(metrics_csv_path)
    c_path = Path(comparison_csv_path)

    m_rows = _read_and_validate_csv(m_path, REQUIRED_METRICS_COLUMNS, "Metrics")
    c_rows = _read_and_validate_csv(c_path, REQUIRED_COMPARISON_COLUMNS, "Comparison")

    m_map = _load_csv_grid_map(m_rows, "metrics")
    c_map = _load_csv_grid_map(c_rows, "comparison")

    _assert_exact_22_cells(set(m_map.keys()))
    _assert_exact_22_cells(set(c_map.keys()))

    cells_dict = _build_cells_dict(m_map, c_map)
    manifest_sha, weights_map = _load_manifest_sha_and_weights(manifest_path)
    ts = created_at or datetime.now(timezone.utc).isoformat()

    return PhysicalParamContract(
        contract_version=CONTRACT_VERSION,
        manifest_sha256=manifest_sha,
        model_weights_sha256=weights_map,
        created_at=ts,
        cells=cells_dict,
    )


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
    print(f"Total cells: {len(contract.cells)}, Weights: {len(contract.model_weights_sha256)}, Version: {contract.contract_version}")


if __name__ == "__main__":
    main()
