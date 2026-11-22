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
5. All dataframe sanitization events (stripping 2019 rows from multi-year tables) are explicitly
   logged and tracked in SANITIZATION_AUDIT for complete audit-trail visibility.

HISTORICAL SCRIPTS NOTE (ROUND 3):
Round 3's use of 2019 OOS data was historically authorized under Phase 1 statutory governance.
`scripts/evaluate_round3_oos.py` is now guarded by this airgap and will be intercepted if executed.
If future operational needs require re-running Round 3 evaluation, the Review Committee must
issue a dedicated pre-registration authorization flag, rather than adding exceptions/backdoors in code.
"""

import json
import logging
import numbers
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union
import pandas as pd

logger = logging.getLogger("airgap")

# Exposed audit trail for data sanitization events
SANITIZATION_AUDIT: Dict[str, Any] = {
    "total_sanitized_rows": 0,
    "events": [],
}


def get_sanitization_audit_log() -> Dict[str, Any]:
    """Retrieve copy of all sanitization events recorded during process execution."""
    return {
        "total_sanitized_rows": SANITIZATION_AUDIT["total_sanitized_rows"],
        "events": list(SANITIZATION_AUDIT["events"]),
    }


def reset_sanitization_audit_log() -> None:
    """Reset the in-memory sanitization audit log (primarily for unit testing)."""
    SANITIZATION_AUDIT["total_sanitized_rows"] = 0
    SANITIZATION_AUDIT["events"] = []


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
AUTHORIZATION_FLAG_FILE = PROJECT_ROOT / "evidence" / "preregistered_2019_authorization.flag"
SEALED_YEAR = 2019
TRAIN_START_YEAR = 2000
TRAIN_END_YEAR = 2018

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
        logger.warning(
            "AIRGAP SANITIZATION: Stripped %d rows belonging to sealed year %d from '%s'.",
            rows_2019,
            SEALED_YEAR,
            source_description or "unnamed_dataframe",
        )
        SANITIZATION_AUDIT["total_sanitized_rows"] += rows_2019
        SANITIZATION_AUDIT["events"].append({
            "timestamp": pd.Timestamp.now().isoformat(),
            "rows_sanitized": rows_2019,
            "source_description": source_description or "unnamed_dataframe",
        })

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


def enforce_training_year_seal(
    years: Union[int, Iterable[int]],
    source_description: str = "",
    min_train_year: int = TRAIN_START_YEAR,
    max_train_year: int = TRAIN_END_YEAR,
) -> List[int]:
    """
    Unconditionally block sealed 2019+ data (and out-of-window years) in any training or CV path.

    Unlike verify_year_whitelist(), this training-side guardrail explicitly bypasses
    evidence/preregistered_2019_authorization.flag: status=AUTHORIZED permits read-only
    out-of-sample evaluation ONLY and must NEVER permit 2019+ data into parameter fitting
    or Block-CV.
    """
    if isinstance(years, bool):
        raise AirgapViolationError(
            f"TRAINING AIRGAP VIOLATION: Invalid boolean year value in '{source_description}'."
        )
    if isinstance(years, numbers.Integral):
        target_years = [int(years)]
    else:
        target_years = []
        for y in years:
            if isinstance(y, bool) or not isinstance(y, numbers.Integral):
                raise AirgapViolationError(
                    f"TRAINING AIRGAP VIOLATION: Non-integer year '{y}' in '{source_description}'."
                )
            target_years.append(int(y))

    desc = f" in '{source_description}'" if source_description else ""
    if not target_years:
        raise AirgapViolationError(
            f"TRAINING AIRGAP VIOLATION: Empty training year collection{desc}. "
            f"Permitted training window: [{min_train_year}, {max_train_year}]."
        )

    bad_sealed = sorted({y for y in target_years if y >= SEALED_YEAR})
    if bad_sealed:
        raise AirgapViolationError(
            f"TRAINING AIRGAP VIOLATION: Attempted to feed sealed year(s) {bad_sealed}{desc}. "
            f"Training unconditionally seals {SEALED_YEAR}+ regardless of "
            f"'evidence/preregistered_2019_authorization.flag' (which authorizes read-only OOS "
            f"evaluation ONLY, never training). Permitted training window: "
            f"[{min_train_year}, {max_train_year}]."
        )

    out_of_window = sorted({y for y in target_years if y < min_train_year or y > max_train_year})
    if out_of_window:
        raise AirgapViolationError(
            f"TRAINING AIRGAP VIOLATION: Year(s) {out_of_window} outside permitted training window "
            f"[{min_train_year}, {max_train_year}]{desc}."
        )

    return target_years


def enforce_training_dataframe_seal(
    df: pd.DataFrame,
    year_col: Optional[str] = "year",
    date_col: Optional[str] = "target_date",
    source_description: str = "",
    min_train_year: int = TRAIN_START_YEAR,
    max_train_year: int = TRAIN_END_YEAR,
) -> pd.DataFrame:
    """
    Unconditionally verify that a training/CV DataFrame contains zero rows from >= 2019
    (or outside [min_train_year, max_train_year]), ignoring the OOS authorization flag.
    """
    if df.empty:
        return df

    years_found: List[int] = []
    if year_col and year_col in df.columns:
        years_found.extend(int(y) for y in pd.Series(df[year_col]).dropna().astype(int).unique())
    if date_col and date_col in df.columns:
        dt_years = pd.to_datetime(df[date_col]).dt.year.dropna().astype(int).unique()
        years_found.extend(int(y) for y in dt_years)

    if years_found:
        enforce_training_year_seal(
            sorted(set(years_found)),
            source_description=source_description,
            min_train_year=min_train_year,
            max_train_year=max_train_year,
        )
    return df
