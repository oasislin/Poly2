"""
src/utils/airgap.py: 2019 Out-Of-Sample Airgap Hard Guardrail.

Strictly enforces zero lookahead and access restrictions into the 2019 blind test holdout:
1. 2019 data is strictly sealed as the ultimate blind holdout.
2. Any loading or evaluation function attempting to access 2019 data (files, year parameters,
   or un-filtered dataframe rows) must present a valid pre-registration authorization flag:
   evidence/preregistered_2019_authorization.flag
3. The authorization flag CANNOT be a simple boolean toggle; it MUST embed a frozen
   statutory gates specification (all thresholds explicitly locked).
4. Without verified pre-registration authorization, an AirgapViolationError is raised unconditionally.
"""

import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, Optional, Sequence, Union
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
AUTHORIZATION_FLAG_FILE = PROJECT_ROOT / "evidence" / "preregistered_2019_authorization.flag"
SEALED_YEAR = 2019

# Mandatory frozen gate schema required in authorization flag
REQUIRED_GATE_FIELDS = [
    "ks_p_value_min",
    "weighted_ece_7bin_max",
    "variance_ratio_s_oos_bounds",
    "pit_mean_bounds",
    "coverage_90_bounds",
]


class AirgapViolationError(PermissionError):
    """Raised when an unauthorized attempt is made to access 2019 blind holdout data."""
    pass


def load_authorization_flag() -> Optional[Dict[str, Any]]:
    """Load and validate authorization flag from evidence/preregistered_2019_authorization.flag."""
    if not AUTHORIZATION_FLAG_FILE.exists():
        return None
    try:
        content = AUTHORIZATION_FLAG_FILE.read_text(encoding="utf-8")
        auth = json.loads(content)
        # Verify required pre-registration schema fields
        required_top = [
            "preregistration_id",
            "authorized_by",
            "allowed_scope",
            "frozen_gate_thresholds",
            "status",
        ]
        if not all(k in auth for k in required_top):
            return None
        # Verify frozen gate thresholds are embedded
        gates = auth.get("frozen_gate_thresholds", {})
        if not all(k in gates for k in REQUIRED_GATE_FIELDS):
            return None
        if auth.get("status") != "AUTHORIZED":
            return None
        return auth
    except Exception:
        return None


def is_2019_authorized() -> bool:
    """Check whether valid pre-registration authorization for 2019 evaluation exists."""
    return load_authorization_flag() is not None


def verify_year_whitelist(
    years: Union[int, Iterable[int]],
    source_description: str = "",
) -> None:
    """
    Enforce year whitelist. Raises AirgapViolationError if 2019 is included
    without explicit pre-registration authorization flag.
    """
    if isinstance(years, int):
        target_years = [years]
    else:
        target_years = list(years)

    if SEALED_YEAR in target_years:
        if not is_2019_authorized():
            desc = f" from '{source_description}'" if source_description else ""
            flag_str = (
                str(AUTHORIZATION_FLAG_FILE.relative_to(PROJECT_ROOT))
                if AUTHORIZATION_FLAG_FILE.is_relative_to(PROJECT_ROOT)
                else str(AUTHORIZATION_FLAG_FILE)
            )
            raise AirgapViolationError(
                f"AIRGAP VIOLATION: Attempted to load sealed {SEALED_YEAR} blind holdout data{desc}. "
                f"Access is strictly forbidden without a verified authorization file at "
                f"'{flag_str}'. "
                f"The authorization flag must embed frozen gate threshold specifications. "
                f"All exploratory development and tuning must use 2000-2018 Block-CV."
            )


def verify_file_path(file_path: Union[str, Path], source_description: str = "") -> None:
    """
    Check if a file path specifically points to 2019 holdout data
    (e.g., gefs_factors/*/2019.parquet, audit_arrays/2019_oos_*.parquet).
    """
    p_str = str(file_path)
    # Match patterns like 2019.parquet, 2019_oos, or /2019/
    is_2019_path = bool(
        re.search(r"2019\.parquet", p_str)
        or re.search(r"2019_oos", p_str)
        or re.search(r"[/_\\]2019[/_\\]", p_str)
    )
    if is_2019_path and not is_2019_authorized():
        desc = f" ({source_description})" if source_description else ""
        raise AirgapViolationError(
            f"AIRGAP VIOLATION: File path '{p_str}' accesses sealed {SEALED_YEAR} data{desc}. "
            f"Pre-registration authorization flag missing or invalid."
        )


def sanitize_dataframe(
    df: pd.DataFrame,
    year_col: str = "year",
    date_col: Optional[str] = None,
    source_description: str = "",
) -> pd.DataFrame:
    """
    Sanitize a dataframe (such as full GHCN-Daily truth records).
    If 2019 data is present:
    - If unauthorized, strips 2019 rows with an audit assertion, or raises if only 2019 was requested.
    - If authorized, permits 2019 rows.
    """
    if df.empty:
        return df

    has_2019 = False
    if year_col in df.columns:
        has_2019 = bool((df[year_col] == SEALED_YEAR).any())
    elif date_col in df.columns:
        dt_series = pd.to_datetime(df[date_col])
        has_2019 = bool((dt_series.dt.year == SEALED_YEAR).any())

    if has_2019 and not is_2019_authorized():
        desc = f" from '{source_description}'" if source_description else ""
        # If the entire dataframe is only 2019 data, access was strictly intended for 2019 -> raise
        total_rows = len(df)
        rows_2019 = int((df[year_col] == SEALED_YEAR).sum()) if year_col in df.columns else int((pd.to_datetime(df[date_col]).dt.year == SEALED_YEAR).sum())
        if rows_2019 == total_rows:
            raise AirgapViolationError(
                f"AIRGAP VIOLATION: Entire dataframe of {total_rows} rows belongs to sealed {SEALED_YEAR}{desc}. "
                f"Access denied."
            )
        # Otherwise, filter out 2019 rows to protect downstream pipeline from leakage
        if year_col in df.columns:
            return df[df[year_col] != SEALED_YEAR].copy()
        else:
            return df[pd.to_datetime(df[date_col]).dt.year != SEALED_YEAR].copy()

    return df


def filter_safe_years(
    years: Iterable[int],
    source_description: str = "",
) -> Sequence[int]:
    """Filter years to exclude 2019 unless authorized."""
    target_years = list(years)
    verify_year_whitelist(target_years, source_description)
    return target_years
