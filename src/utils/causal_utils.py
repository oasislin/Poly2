"""Shared UTC timestamp enforcement and canonical M7 JSONL SHA256 helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping


class CausalInputError(ValueError):
    """Raised when timestamps are naive or violate causal ordering preconditions."""


def ensure_utc_datetime(dt: datetime, *, field_name: str) -> datetime:
    """Validate that `dt` is timezone-aware and normalize it to UTC."""
    if not isinstance(dt, datetime):
        raise CausalInputError(f"{field_name} must be a datetime, got {type(dt).__name__}")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise CausalInputError(f"{field_name} must be timezone-aware UTC, got naive {dt!r}")
    return dt.astimezone(timezone.utc)


def parse_utc_timestamp(
    value: Any,
    *,
    field_name: str,
    assume_naive_utc: bool = False,
) -> datetime:
    """Parse datetime / epoch / ISO string to UTC; naive strings require explicit opt-in."""
    if isinstance(value, datetime):
        return ensure_utc_datetime(value, field_name=field_name)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise CausalInputError(f"{field_name} cannot be an empty string")
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None or dt.utcoffset() is None:
            if assume_naive_utc:
                return dt.replace(tzinfo=timezone.utc)
            raise CausalInputError(f"{field_name} must be timezone-aware UTC, got naive {dt!r}")
        return dt.astimezone(timezone.utc)
    raise CausalInputError(f"{field_name}: unsupported timestamp value {value!r}")


def compute_record_sha256(record_without_hash: Mapping[str, Any]) -> str:
    """Compute canonical 64-hex SHA256 matching `P8-T2-M7-LOGGING v1.0 §1.4`."""
    canonical = json.dumps(
        record_without_hash,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def verify_record_sha256_line(line: str) -> bool:
    """Verify canonical `record_sha256` integrity of a serialized M7 JSONL line."""
    data = json.loads(line)
    expected = data.pop("record_sha256", None)
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    return compute_record_sha256(data) == expected


__all__ = [
    "CausalInputError",
    "compute_record_sha256",
    "ensure_utc_datetime",
    "parse_utc_timestamp",
    "verify_record_sha256_line",
]
