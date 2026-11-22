"""Fail-Closed Credential Loader & LIVE Startup Mode Gate (`S3-05b`).

Loads Polymarket CLOB L1 signer & L2 trading-only API credentials exclusively
from environment variables or gitignored local YAML (`config/credentials.local.yaml`),
enforces least-privilege checks (no withdrawal keys), redacts secrets in logs, and
downgrades `LIVE -> PAPER` with alert whenever credentials or secondary confirmation
are missing or invalid.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
from typing import Any, Callable, Dict, Mapping, Optional

import yaml

from src.execution.executor import ExecutionMode

logger = logging.getLogger(__name__)

DEFAULT_CREDENTIALS_PATH = Path("config/credentials.local.yaml")
_HEX_KEY_RE = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")
_HEX_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_FORBIDDEN_CREDENTIAL_KEYS = frozenset(
    {
        "withdraw_key",
        "withdrawal_key",
        "withdrawal_secret",
        "withdraw_secret",
        "withdrawal_address",
        "transfer_key",
        "admin_private_key",
        "seed_phrase",
        "mnemonic",
    }
)
_REDACTED = "***REDACTED***"


class CredentialError(RuntimeError):
    """Raised on missing, malformed, or over-privileged CLOB credentials."""


@dataclass(frozen=True)
class ClobCredentials:
    """Redacted container for L1 trading signer + L2 CLOB API credentials."""

    private_key: str
    funder: str
    api_key: str
    api_secret: str
    api_passphrase: str
    signature_type: int = 2
    source: str = "unknown"

    def __post_init__(self) -> None:
        if not _HEX_KEY_RE.match(self.private_key or ""):
            raise CredentialError("Invalid L1 private_key format (expected 64 hex chars)")
        if not _HEX_ADDR_RE.match(self.funder or ""):
            raise CredentialError("Invalid funder address format (expected 0x-prefixed 40 hex chars)")
        if not self.api_key or not self.api_secret or not self.api_passphrase:
            raise CredentialError("Incomplete L2 API credentials (api_key/api_secret/api_passphrase)")
        if self.signature_type not in (0, 1, 2):
            raise CredentialError(f"Unsupported Polymarket signature_type={self.signature_type}")

    def __repr__(self) -> str:
        return (
            "ClobCredentials("
            f"funder={self.funder!r}, api_key={self.api_key!r}, "
            f"signature_type={self.signature_type}, source={self.source!r}, "
            f"private_key={_REDACTED!r}, api_secret={_REDACTED!r}, api_passphrase={_REDACTED!r})"
        )

    __str__ = __repr__

    def redacted_dict(self) -> Dict[str, Any]:
        """Return audit-safe metadata with all secret fields masked."""
        return {
            "funder": self.funder,
            "api_key": self.api_key,
            "signature_type": self.signature_type,
            "source": self.source,
            "private_key": _REDACTED,
            "api_secret": _REDACTED,
            "api_passphrase": _REDACTED,
        }


@dataclass(frozen=True)
class StartupModeDecision:
    """Result of evaluating `execution_mode` against dual confirmation & credentials."""

    effective_mode: ExecutionMode
    downgraded_from_live: bool
    reason: str
    credentials: Optional[ClobCredentials] = None


def _reject_forbidden_keys(mapping: Mapping[str, Any]) -> None:
    bad = sorted(k for k in mapping if str(k).lower() in _FORBIDDEN_CREDENTIAL_KEYS and mapping[k])
    if bad:
        raise CredentialError(
            f"Least-privilege credential violation: disallowed non-trading keys present: {bad}"
        )


def _read_yaml_credentials(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise CredentialError(f"Credentials file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CredentialError(f"Failed parsing credentials YAML {path}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise CredentialError(f"Credentials YAML {path} must be a mapping")
    _reject_forbidden_keys(raw)
    return dict(raw)


def load_clob_credentials(
    *,
    credentials_path: Optional[Path] = None,
    environ: Optional[Mapping[str, str]] = None,
    default_signature_type: int = 2,
) -> ClobCredentials:
    """Load trading credentials from env vars first, then `config/credentials.local.yaml`."""
    env = environ if environ is not None else os.environ
    for forbidden in _FORBIDDEN_CREDENTIAL_KEYS:
        env_key = f"POLY_CLOB_{forbidden.upper()}"
        if env.get(env_key):
            raise CredentialError(f"Least-privilege violation: disallowed env var {env_key} is set")

    env_pk = env.get("POLY_CLOB_PRIVATE_KEY", "").strip()
    env_funder = env.get("POLY_CLOB_FUNDER", "").strip()
    env_key = env.get("POLY_CLOB_API_KEY", "").strip()
    env_secret = env.get("POLY_CLOB_API_SECRET", "").strip()
    env_pass = env.get("POLY_CLOB_API_PASSPHRASE", "").strip()
    env_sig = env.get("POLY_CLOB_SIGNATURE_TYPE", "").strip()

    if any([env_pk, env_funder, env_key, env_secret, env_pass]):
        if not all([env_pk, env_funder, env_key, env_secret, env_pass]):
            raise CredentialError("Partial POLY_CLOB_* environment credentials; all 5 fields required")
        sig_type = int(env_sig) if env_sig else default_signature_type
        return ClobCredentials(
            private_key=env_pk,
            funder=env_funder,
            api_key=env_key,
            api_secret=env_secret,
            api_passphrase=env_pass,
            signature_type=sig_type,
            source="env:POLY_CLOB_*",
        )

    target_path = credentials_path if credentials_path is not None else DEFAULT_CREDENTIALS_PATH
    data = _read_yaml_credentials(target_path)
    for hex_field in ("private_key", "funder"):
        if isinstance(data.get(hex_field), int):
            raise CredentialError(
                f"Credential field {hex_field!r} must be a quoted hex string in {target_path}"
            )
    sig_val = data.get("signature_type", default_signature_type)
    return ClobCredentials(
        private_key=str(data.get("private_key", "")).strip(),
        funder=str(data.get("funder", "")).strip(),
        api_key=str(data.get("api_key", "")).strip(),
        api_secret=str(data.get("api_secret", "")).strip(),
        api_passphrase=str(data.get("api_passphrase", "")).strip(),
        signature_type=int(sig_val),
        source=f"file:{target_path}",
    )


def resolve_live_startup_mode(
    *,
    requested_mode: ExecutionMode,
    confirmation_env_var: str,
    confirmation_expected_value: str,
    credentials_path: Optional[Path] = None,
    environ: Optional[Mapping[str, str]] = None,
    default_signature_type: int = 2,
    alert_callback: Optional[Callable[[str], None]] = None,
) -> StartupModeDecision:
    """Enforce fail-closed `LIVE` activation: confirm env var + valid creds, else downgrade `PAPER`."""
    if requested_mode != "LIVE":
        return StartupModeDecision(
            effective_mode="PAPER",
            downgraded_from_live=False,
            reason="DEFAULT_OR_CONFIG_PAPER",
            credentials=None,
        )

    env = environ if environ is not None else os.environ
    actual_confirm = env.get(confirmation_env_var, "")
    if actual_confirm != confirmation_expected_value:
        msg = (
            f"LIVE startup refused: secondary confirmation {confirmation_env_var!r} "
            "missing or mismatched; downgraded to PAPER"
        )
        logger.error(msg)
        if alert_callback is not None:
            alert_callback(msg)
        return StartupModeDecision(
            effective_mode="PAPER",
            downgraded_from_live=True,
            reason="MISSING_LIVE_SECONDARY_CONFIRMATION",
            credentials=None,
        )

    try:
        creds = load_clob_credentials(
            credentials_path=credentials_path,
            environ=env,
            default_signature_type=default_signature_type,
        )
    except CredentialError as exc:
        msg = f"LIVE startup refused: {exc}; downgraded to PAPER"
        logger.error(msg)
        if alert_callback is not None:
            alert_callback(msg)
        return StartupModeDecision(
            effective_mode="PAPER",
            downgraded_from_live=True,
            reason=f"CREDENTIAL_VALIDATION_FAILED:{exc}",
            credentials=None,
        )

    return StartupModeDecision(
        effective_mode="LIVE",
        downgraded_from_live=False,
        reason="LIVE_CONFIRMED_WITH_VALID_CREDENTIALS",
        credentials=creds,
    )


__all__ = [
    "ClobCredentials",
    "CredentialError",
    "DEFAULT_CREDENTIALS_PATH",
    "StartupModeDecision",
    "load_clob_credentials",
    "resolve_live_startup_mode",
]
