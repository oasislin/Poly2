"""Single Authorized Polymarket CLOB `EIP-712` (`IOC_FAK`) Order Gateway (`S3-05b`).

Anchors:
- `P8-T4-M4M5-INTERFACE v1.1 §2.3` (`LIVE` vs `PAPER` dual-track routing, `IOC_FAK`)
- `P8-FACTS-LEDGER FACT-003 / FACT-004 / FACT-005 / FACT-006` (tick rules, 5 shares, `negRisk`, `FAK`)
- `P8-WO-20261123-S305B-GATEWAY-DEV v3` (Four Invariants, fail-closed creds, dual safety gates,
  lookup-before-retry idempotency, >=5 failure circuit breaker, read-only risk panel snapshot)

Security Invariants:
  i.   Only module in `src/` permitted to import `py_clob_client` or POST live CLOB orders.
  ii.  Every attempt logs `PRE_SIGN_SNAPSHOT`, requests, responses/reconciles, exceptions, and
       final `p3.v1` `ExecutionAttemptLog` via mandatory `AsyncAuditLogger`.
  iii. `PAPER` mode disables the live HTTP/SDK transport structurally; zero live orders can fire.
  iv.  Read-only over `model_hash`, parameter contracts, and pricing parameters.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import importlib.metadata as importlib_metadata
import json
import logging
from pathlib import Path
import random
import threading
import time
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple
import uuid

import httpx
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    ApiCreds,
    OpenOrderParams,
    OrderArgs,
    OrderType,
    PartialCreateOrderOptions,
    TradeParams,
)
from py_clob_client.exceptions import PolyApiException
from py_clob_client.http_helpers import helpers as clob_http_helpers
import yaml

from src.audit.audit_logger import AsyncAuditLogger, GatewayP3TraceEvent, GatewayTraceStage
from src.execution.clob_credentials import (
    ClobCredentials,
    StartupModeDecision,
    resolve_live_startup_mode,
)
from src.execution.executor import (
    ExecutionAttemptLog,
    ExecutionMode,
    FillLegRecord,
    OrderExecutionContext,
    SlicePlan,
    TerminalStatus,
    TradingExecutionConfig,
    compute_taker_fee_usd_raw,
    quantize_polymarket_fee_usd,
    validate_cross_side_routing,
)
from src.utils.causal_utils import ensure_utc_datetime
from src.utils.decimal_guard import exact_decimal_context, to_guarded_decimal

logger = logging.getLogger(__name__)

EXPECTED_PY_CLOB_CLIENT_VERSION = "0.34.6"
DEFAULT_GATEWAY_CONFIG_PATH = Path("configs/clob_gateway.yaml")
_GATEWAY_TRACE_NS = uuid.UUID("c4b18e73-5a12-4d91-9b34-202611230305")
_SHARES_STEP = Decimal("0.01")
_CLOB_HTTP_LOCK = threading.Lock()


class GatewayConfigError(RuntimeError):
    """Raised on missing, malformed, or unsafe gateway configuration."""


class GatewayVersionError(RuntimeError):
    """Raised when `py-clob-client` does not match locked `EXPECTED_PY_CLOB_CLIENT_VERSION`."""


@dataclass(frozen=True)
class GatewaySafetyConfig:
    """Validated config-driven execution & dual amount gate parameters (hot-reloaded per order)."""

    execution_mode: ExecutionMode
    live_confirmation_env_var: str
    live_confirmation_expected_value: str
    clob_host: str
    chain_id: int
    signature_type: int
    tick_size_ttl_sec: float
    use_system_proxy: bool
    max_single_order_usd: Decimal
    max_daily_cumulative_usd: Decimal
    daily_ledger_path: Path
    min_order_size_shares: Decimal
    max_limit_price: Decimal
    allowed_tick_sizes: Tuple[Decimal, ...]
    require_neg_risk: bool
    request_timeout_sec: float
    max_reconnect_attempts: int
    backoff_base_sec: float
    backoff_max_sec: float
    backoff_jitter_ratio: float
    circuit_breaker_failure_threshold: int
    config_sha256: str


@dataclass(frozen=True)
class LiveOrderRequest:
    """Explicit order submission bundle handed to `ClobOrderGateway.submit_order`."""

    context: OrderExecutionContext
    plan: SlicePlan
    tick_size: Decimal
    neg_risk: bool
    trading_config: TradingExecutionConfig
    fee_rate: Decimal = Decimal("0.01")
    fee_rate_bps: int = 0
    client_order_id: Optional[str] = None


@dataclass(frozen=True)
class GatewayRiskPanelSnapshot:
    """Read-only risk parameter panel state reserved for `S3-10` acceptance."""

    execution_mode: ExecutionMode
    max_single_order_usd: Decimal
    max_daily_cumulative_usd: Decimal
    daily_used_usd: Decimal
    daily_remaining_usd: Decimal
    circuit_open: bool
    consecutive_failures: int
    light_status: Optional[str]
    model_hash: Optional[str]
    model_frozen: bool
    safety_config_sha256: str


def verify_locked_sdk_version() -> str:
    """Fail-closed check that `py-clob-client` matches the locked adjudicated version."""
    installed = importlib_metadata.version("py-clob-client")
    if installed != EXPECTED_PY_CLOB_CLIENT_VERSION:
        raise GatewayVersionError(
            f"Locked py-clob-client=={EXPECTED_PY_CLOB_CLIENT_VERSION} required, got {installed!r}"
        )
    return installed


def _require_key(raw: Mapping[str, Any], key: str) -> Any:
    if key not in raw or raw[key] is None:
        raise GatewayConfigError(f"Missing required gateway config parameter: {key!r}")
    return raw[key]


def load_gateway_safety_config(config_path: Path) -> GatewaySafetyConfig:
    """Load & strictly validate gateway safety parameters from YAML (zero hardcoded defaults)."""
    path = Path(config_path)
    if not path.exists():
        raise GatewayConfigError(f"Gateway safety config file not found: {path}")
    raw_bytes = path.read_bytes()
    cfg_sha = hashlib.sha256(raw_bytes).hexdigest()
    try:
        parsed = yaml.safe_load(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise GatewayConfigError(f"Malformed gateway safety YAML {path}: {exc}") from exc
    if not isinstance(parsed, Mapping):
        raise GatewayConfigError(f"Gateway safety config {path} must be a YAML mapping")

    mode_raw = str(_require_key(parsed, "execution_mode")).strip().upper()
    if mode_raw not in ("PAPER", "LIVE"):
        raise GatewayConfigError(f"Unsupported execution_mode={mode_raw!r}")
    mode: ExecutionMode = "LIVE" if mode_raw == "LIVE" else "PAPER"

    max_single = to_guarded_decimal(
        _require_key(parsed, "max_single_order_usd"), name="safety.max_single_order_usd"
    )
    max_daily = to_guarded_decimal(
        _require_key(parsed, "max_daily_cumulative_usd"), name="safety.max_daily_cumulative_usd"
    )
    min_shares = to_guarded_decimal(
        _require_key(parsed, "min_order_size_shares"), name="safety.min_order_size_shares"
    )
    max_price = to_guarded_decimal(
        _require_key(parsed, "max_limit_price"), name="safety.max_limit_price"
    )
    if max_single <= Decimal("0") or max_daily <= Decimal("0") or min_shares <= Decimal("0"):
        raise GatewayConfigError("Safety amount and share limits must be strictly > 0")
    if max_daily < max_single:
        raise GatewayConfigError("max_daily_cumulative_usd must be >= max_single_order_usd")
    if not (Decimal("0") < max_price < Decimal("1")):
        raise GatewayConfigError(f"max_limit_price must lie in (0, 1), got {max_price}")

    raw_ticks = _require_key(parsed, "allowed_tick_sizes")
    if not isinstance(raw_ticks, Sequence) or isinstance(raw_ticks, (str, bytes)) or not raw_ticks:
        raise GatewayConfigError("allowed_tick_sizes must be a non-empty sequence")
    ticks = tuple(
        to_guarded_decimal(item, name=f"safety.tick[{idx}]")
        for idx, item in enumerate(raw_ticks)
    )
    if any(t <= Decimal("0") or t >= Decimal("1") for t in ticks):
        raise GatewayConfigError("All allowed_tick_sizes must be in (0, 1)")

    timeout_sec = float(_require_key(parsed, "request_timeout_sec"))
    max_reconnect = int(_require_key(parsed, "max_reconnect_attempts"))
    backoff_base = float(_require_key(parsed, "backoff_base_sec"))
    backoff_max = float(_require_key(parsed, "backoff_max_sec"))
    jitter_ratio = float(_require_key(parsed, "backoff_jitter_ratio"))
    cb_threshold = int(_require_key(parsed, "circuit_breaker_failure_threshold"))
    if timeout_sec <= 0.0 or max_reconnect < 0 or backoff_base < 0.0 or backoff_max < backoff_base:
        raise GatewayConfigError("Invalid gateway timeout / backoff configuration")
    if not (0.0 <= jitter_ratio <= 1.0):
        raise GatewayConfigError(f"backoff_jitter_ratio must be in [0, 1], got {jitter_ratio}")
    if cb_threshold < 1:
        raise GatewayConfigError("circuit_breaker_failure_threshold must be >= 1")

    raw_daily_ledger = _require_key(parsed, "daily_ledger_path")
    daily_ledger_str = str(raw_daily_ledger).strip() if raw_daily_ledger is not None else ""
    if not daily_ledger_str:
        raise GatewayConfigError("Gateway safety config 'daily_ledger_path' must be non-empty")

    return GatewaySafetyConfig(
        execution_mode=mode,
        live_confirmation_env_var=str(_require_key(parsed, "live_confirmation_env_var")),
        live_confirmation_expected_value=str(_require_key(parsed, "live_confirmation_expected_value")),
        clob_host=str(_require_key(parsed, "clob_host")).rstrip("/"),
        chain_id=int(_require_key(parsed, "chain_id")),
        signature_type=int(_require_key(parsed, "signature_type")),
        tick_size_ttl_sec=float(_require_key(parsed, "tick_size_ttl_sec")),
        use_system_proxy=bool(_require_key(parsed, "use_system_proxy")),
        max_single_order_usd=max_single,
        max_daily_cumulative_usd=max_daily,
        daily_ledger_path=Path(daily_ledger_str),
        min_order_size_shares=min_shares,
        max_limit_price=max_price,
        allowed_tick_sizes=ticks,
        require_neg_risk=bool(_require_key(parsed, "require_neg_risk")),
        request_timeout_sec=timeout_sec,
        max_reconnect_attempts=max_reconnect,
        backoff_base_sec=backoff_base,
        backoff_max_sec=backoff_max,
        backoff_jitter_ratio=jitter_ratio,
        circuit_breaker_failure_threshold=cb_threshold,
        config_sha256=cfg_sha,
    )


def _is_fak_unfilled_error(message: str) -> bool:
    low = message.lower()
    return "no orders found to match with fak" in low or "no match" in low and "fak" in low


def _is_pre_connect_error(exc: Exception) -> bool:
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return True
    return False


def _is_ambiguous_network_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPError):
        return True
    if isinstance(exc, PolyApiException):
        if exc.status_code is None:
            return True
        return exc.status_code in (408, 425, 429, 500, 502, 503, 504)
    return False


class _TrackingHttpxClient(httpx.Client):
    """Thin httpx.Client capturing exact RequestError subclass before SDK wraps it."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.last_request_error: Optional[Exception] = None

    def request(self, *args: Any, **kwargs: Any) -> httpx.Response:
        self.last_request_error = None
        try:
            return super().request(*args, **kwargs)
        except Exception as exc:
            self.last_request_error = exc
            raise


class _LiveClobTransport:
    """Encapsulated `py-clob-client` SDK transport; instantiated ONLY in verified `LIVE` mode."""

    def __init__(
        self,
        *,
        safety: GatewaySafetyConfig,
        credentials: ClobCredentials,
        http_transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self._safety = safety
        self._http_transport = http_transport
        self._client = ClobClient(
            host=safety.clob_host,
            chain_id=safety.chain_id,
            key=credentials.private_key,
            creds=ApiCreds(
                api_key=credentials.api_key,
                api_secret=credentials.api_secret,
                api_passphrase=credentials.api_passphrase,
            ),
            signature_type=credentials.signature_type,
            funder=credentials.funder,
            tick_size_ttl=safety.tick_size_ttl_sec,
        )
        client_kwargs: Dict[str, Any] = {
            "timeout": safety.request_timeout_sec,
            "trust_env": safety.use_system_proxy,
            "http2": http_transport is None,
        }
        if not safety.use_system_proxy and http_transport is None:
            client_kwargs["proxy"] = None
        if http_transport is not None:
            client_kwargs["transport"] = http_transport
        self._httpx_client = _TrackingHttpxClient(**client_kwargs)

    @property
    def last_request_error(self) -> Optional[Exception]:
        return self._httpx_client.last_request_error

    @contextmanager
    def _bound_http_client(self) -> Iterator[ClobClient]:
        with _CLOB_HTTP_LOCK:
            prev = clob_http_helpers._http_client
            clob_http_helpers._http_client = self._httpx_client
            try:
                yield self._client
            finally:
                clob_http_helpers._http_client = prev

    def sign_fak_buy_order(
        self,
        *,
        token_id: str,
        limit_price: Decimal,
        shares: Decimal,
        tick_size: Decimal,
        neg_risk: bool,
        nonce: int,
        fee_rate_bps: int,
    ) -> Any:
        order_args = OrderArgs(
            token_id=token_id,
            price=float(limit_price),
            size=float(shares),
            side="BUY",
            fee_rate_bps=fee_rate_bps,
            nonce=nonce,
        )
        options = PartialCreateOrderOptions(
            tick_size=str(tick_size),  # type: ignore[arg-type]
            neg_risk=neg_risk,
        )
        with self._bound_http_client() as client:
            return client.create_order(order_args, options)

    def post_signed_fak_order(self, signed_order: Any) -> Dict[str, Any]:
        with self._bound_http_client() as client:
            resp = client.post_order(signed_order, orderType=OrderType.FAK, post_only=False)
        return dict(resp) if isinstance(resp, Mapping) else {"raw": resp}

    def lookup_order_or_trades(
        self,
        *,
        order_id: Optional[str],
        token_id: str,
        nonce: int,
        signature: str,
    ) -> Optional[Dict[str, Any]]:
        with self._bound_http_client() as client:
            if order_id:
                try:
                    found = client.get_order(order_id)
                    if isinstance(found, Mapping) and found.get("id"):
                        return {"source": "get_order", "order": dict(found), "trades": []}
                except PolyApiException as exc:
                    if exc.status_code not in (404,):
                        raise
            orders_resp = client.get_orders(OpenOrderParams(asset_id=token_id))
            orders_list = (
                orders_resp.get("data", [])
                if isinstance(orders_resp, Mapping)
                else (orders_resp if isinstance(orders_resp, list) else [])
            )
            for item in orders_list:
                if not isinstance(item, Mapping):
                    continue
                if (
                    (order_id and item.get("id") == order_id)
                    or str(item.get("nonce", "")) == str(nonce)
                    or (signature and item.get("signature") == signature)
                ):
                    return {"source": "get_orders", "order": dict(item), "trades": []}

            trades_resp = client.get_trades(TradeParams(asset_id=token_id))
            trades_list = (
                trades_resp.get("data", [])
                if isinstance(trades_resp, Mapping)
                else (trades_resp if isinstance(trades_resp, list) else [])
            )
            matched_trades = [
                dict(t)
                for t in trades_list
                if isinstance(t, Mapping)
                and (
                    (order_id and (t.get("taker_order_id") == order_id or t.get("order_id") == order_id))
                    or str(t.get("nonce", "")) == str(nonce)
                )
            ]
            if matched_trades:
                return {"source": "get_trades", "order": None, "trades": matched_trades}
        return None


class ClobOrderGateway:
    """Fail-closed `LIVE`-only CLOB `IOC_FAK` gateway with dual safety gates & full `P3` logging."""

    def __init__(
        self,
        *,
        safety_config_path: Path = DEFAULT_GATEWAY_CONFIG_PATH,
        audit_logger: AsyncAuditLogger,
        credentials_path: Optional[Path] = None,
        daily_ledger_path: Optional[Path] = None,
        environ: Optional[Mapping[str, str]] = None,
        http_transport: Optional[httpx.BaseTransport] = None,
        alert_callback: Optional[Callable[[str], None]] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
        jitter_rng: Optional[random.Random] = None,
        nonce_provider: Optional[Callable[[OrderExecutionContext], int]] = None,
    ) -> None:
        if not isinstance(audit_logger, AsyncAuditLogger):
            raise TypeError("audit_logger must be an AsyncAuditLogger instance (Invariant ii)")
        self.sdk_version = verify_locked_sdk_version()
        self._safety_config_path = Path(safety_config_path)
        self._audit_logger = audit_logger
        self._credentials_path = credentials_path
        self._environ = environ
        self._http_transport = http_transport
        self._alert_callback = alert_callback
        self._sleep_fn = sleep_fn or time.sleep
        self._rng = jitter_rng or random.Random(20261123)
        self._nonce_provider = nonce_provider or self._default_nonce
        self._lock = threading.Lock()

        self._safety_config = load_gateway_safety_config(self._safety_config_path)
        self._daily_ledger_path = (
            Path(daily_ledger_path)
            if daily_ledger_path is not None
            else self._safety_config.daily_ledger_path
        )
        self._cached_mtime_ns: Optional[int] = self._safety_config_path.stat().st_mtime_ns
        self._startup_decision = self._resolve_mode(self._safety_config)
        self._transport: Optional[_LiveClobTransport] = (
            _LiveClobTransport(
                safety=self._safety_config,
                credentials=self._startup_decision.credentials,
                http_transport=self._http_transport,
            )
            if self._startup_decision.effective_mode == "LIVE"
            and self._startup_decision.credentials is not None
            else None
        )

        self._idempotency_cache: Dict[str, ExecutionAttemptLog] = {}
        self._seen_trade_ids: set[str] = set()
        self._daily_used_by_date: Dict[date, Decimal] = self._load_daily_ledger()
        self._daily_inflight_by_date: Dict[date, Decimal] = {}
        self._consecutive_failures = 0
        self._circuit_open = False
        self._trace_seq = 0

    @staticmethod
    def _default_nonce(ctx: OrderExecutionContext) -> int:
        digest = hashlib.sha256(f"{ctx.decision_id}|{ctx.yes_token_id}".encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") & ((1 << 53) - 1)

    @property
    def effective_mode(self) -> ExecutionMode:
        return self._startup_decision.effective_mode

    @property
    def live_transport_enabled(self) -> bool:
        """Structurally False in PAPER mode."""
        return self.effective_mode == "LIVE" and self._transport is not None

    @property
    def circuit_open(self) -> bool:
        return self._circuit_open

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    def _resolve_mode(self, safety: GatewaySafetyConfig) -> StartupModeDecision:
        if safety.execution_mode == "LIVE" and self._audit_logger.execution_mode != "LIVE":
            msg = (
                "LIVE startup refused: audit_logger execution_mode="
                f"{self._audit_logger.execution_mode!r} != LIVE; downgraded to PAPER"
            )
            logger.error(msg)
            if self._alert_callback is not None:
                self._alert_callback(msg)
            return StartupModeDecision(
                effective_mode="PAPER",
                downgraded_from_live=True,
                reason="AUDIT_LOGGER_MODE_NOT_LIVE",
                credentials=None,
            )
        return resolve_live_startup_mode(
            requested_mode=safety.execution_mode,
            confirmation_env_var=safety.live_confirmation_env_var,
            confirmation_expected_value=safety.live_confirmation_expected_value,
            credentials_path=self._credentials_path,
            environ=self._environ,
            default_signature_type=safety.signature_type,
            alert_callback=self._alert_callback,
        )

    def _refresh_safety_config(self) -> GatewaySafetyConfig:
        if not self._safety_config_path.exists():
            raise GatewayConfigError(f"Gateway safety config missing: {self._safety_config_path}")
        current_sha = hashlib.sha256(self._safety_config_path.read_bytes()).hexdigest()
        if current_sha != self._safety_config.config_sha256:
            reloaded = load_gateway_safety_config(self._safety_config_path)
            self._safety_config = reloaded
            self._cached_mtime_ns = self._safety_config_path.stat().st_mtime_ns
            new_decision = self._resolve_mode(reloaded)
            if new_decision.effective_mode != "LIVE":
                self._startup_decision = new_decision
                self._transport = None
            elif self._transport is None and new_decision.credentials is not None:
                self._startup_decision = new_decision
                self._transport = _LiveClobTransport(
                    safety=reloaded,
                    credentials=new_decision.credentials,
                    http_transport=self._http_transport,
                )
        return self._safety_config

    def _load_daily_ledger(self) -> Dict[date, Decimal]:
        if self._daily_ledger_path is None or not self._daily_ledger_path.exists():
            return {}
        raw = json.loads(self._daily_ledger_path.read_text(encoding="utf-8"))
        return {
            date.fromisoformat(k): to_guarded_decimal(v, name=f"daily_ledger[{k}]")
            for k, v in raw.items()
        }

    def _persist_daily_ledger(self) -> None:
        if self._daily_ledger_path is None:
            return
        self._daily_ledger_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {d.isoformat(): str(v) for d, v in sorted(self._daily_used_by_date.items())}
        tmp = self._daily_ledger_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        tmp.replace(self._daily_ledger_path)

    def get_daily_used_usd(self, utc_day: date) -> Decimal:
        """Return UTC daily cumulative filled notional (including partial fills)."""
        return self._daily_used_by_date.get(utc_day, Decimal("0"))

    def preflight_safety_snapshot(self) -> Dict[str, Any]:
        """Return read-only safety configuration & ledger readiness metadata for preflight checks."""
        with self._lock:
            safety = self._refresh_safety_config()
            ledger_parent_creatable = False
            if self._daily_ledger_path is not None:
                try:
                    self._daily_ledger_path.parent.mkdir(parents=True, exist_ok=True)
                    ledger_parent_creatable = self._daily_ledger_path.parent.exists()
                except OSError:
                    ledger_parent_creatable = False
            stats = self._audit_logger.stats()
            return {
                "sdk_version": self.sdk_version,
                "safety_config_mode": safety.execution_mode,
                "effective_mode": self.effective_mode,
                "live_transport_enabled": self.live_transport_enabled,
                "daily_ledger_path": str(self._daily_ledger_path) if self._daily_ledger_path else "",
                "ledger_dir_ready": ledger_parent_creatable,
                "max_single_order_usd": str(safety.max_single_order_usd),
                "max_daily_cumulative_usd": str(safety.max_daily_cumulative_usd),
                "config_sha256": safety.config_sha256,
                "audit_logger_online": (not self._audit_logger._closed) and stats.error_count == 0,
            }

    def get_risk_panel_snapshot(
        self,
        *,
        utc_date: Optional[date] = None,
        light_status: Optional[str] = None,
        model_hash: Optional[str] = None,
        model_frozen: bool = True,
    ) -> GatewayRiskPanelSnapshot:
        """Return read-only risk parameter panel fields required for `S3-10`."""
        safety = self._safety_config
        day = utc_date or datetime.now(timezone.utc).date()
        used = self.get_daily_used_usd(day)
        remaining = max(Decimal("0"), safety.max_daily_cumulative_usd - used)
        return GatewayRiskPanelSnapshot(
            execution_mode=self.effective_mode,
            max_single_order_usd=safety.max_single_order_usd,
            max_daily_cumulative_usd=safety.max_daily_cumulative_usd,
            daily_used_usd=used,
            daily_remaining_usd=remaining,
            circuit_open=self._circuit_open,
            consecutive_failures=self._consecutive_failures,
            light_status=light_status,
            model_hash=model_hash,
            model_frozen=model_frozen,
            safety_config_sha256=safety.config_sha256,
        )

    def reset_circuit_breaker(self, *, operator: str, reason: str) -> None:
        """Explicit manual reset of circuit breaker; automatic recovery is forbidden."""
        if not operator.strip() or not reason.strip():
            raise ValueError("Manual circuit breaker reset requires non-empty operator and reason")
        with self._lock:
            self._circuit_open = False
            self._consecutive_failures = 0
            now = datetime.now(timezone.utc)
            self._trace_seq += 1
            trace = GatewayP3TraceEvent(
                schema_version="p3.gateway.v1",
                trace_id=f"cb-reset-{self._trace_seq}",
                event_ts_utc=now,
                decision_ts_utc=now,
                session_id="manual-ops",
                execution_mode=self._audit_logger.execution_mode,
                decision_id="manual-circuit-reset",
                attempt_id="manual-circuit-reset",
                client_order_id="manual-circuit-reset",
                idempotency_key=f"cb-reset-{self._trace_seq}",
                station_id="ALL",
                market_id="ALL",
                token_id="ALL",
                model_hash="READONLY_UNTOUCHED",
                config_hash=self._safety_config.config_sha256,
                stage="CIRCUIT_BREAKER",
                details={"action": "MANUAL_RESET", "operator": operator, "reason": reason},
            )
            self._audit_logger.log_p3_gateway_trace(trace)

    def _emit_trace(
        self,
        *,
        req: LiveOrderRequest,
        attempt_id: str,
        client_order_id: str,
        idem_key: str,
        stage: GatewayTraceStage,
        details: Mapping[str, Any],
        event_ts: Optional[datetime] = None,
    ) -> None:
        self._trace_seq += 1
        ctx = req.context
        ts = event_ts or datetime.now(timezone.utc)
        tid = str(uuid.uuid5(_GATEWAY_TRACE_NS, f"{attempt_id}|{stage}|{self._trace_seq}"))
        self._audit_logger.log_p3_gateway_trace(
            GatewayP3TraceEvent(
                schema_version="p3.gateway.v1",
                trace_id=tid,
                event_ts_utc=ts,
                decision_ts_utc=ctx.decision_ts_utc,
                session_id=ctx.session_id,
                execution_mode=self._audit_logger.execution_mode,
                decision_id=ctx.decision_id,
                attempt_id=attempt_id,
                client_order_id=client_order_id,
                idempotency_key=idem_key,
                station_id=ctx.station_id,
                market_id=ctx.market_id,
                token_id=ctx.yes_token_id,
                model_hash=ctx.model_hash,
                config_hash=ctx.config_hash,
                stage=stage,
                details=details,
            )
        )

    def _record_terminal_attempt(
        self,
        *,
        req: LiveOrderRequest,
        attempt_id: str,
        idem_key: str,
        sub_ts: datetime,
        final_ts: datetime,
        terminal_status: TerminalStatus,
        reject_reason: Optional[str],
        filled_shares: Decimal,
        filled_usd: Decimal,
        fee_paid_usd: Decimal,
        fill_legs: Tuple[FillLegRecord, ...] = (),
    ) -> ExecutionAttemptLog:
        ctx = req.context
        plan = req.plan
        best_ask = to_guarded_decimal(ctx.decision_best_ask, name="p3.decision_best_ask", max_sig_digits=18)
        with exact_decimal_context():
            avg_px = (filled_usd / filled_shares) if filled_shares > Decimal("0") else None
            fill_rate = (
                (filled_shares / plan.target_shares)
                if plan.target_shares > Decimal("0")
                else Decimal("0")
            )
            slip_best = ((avg_px - best_ask) / best_ask) if avg_px is not None and best_ask > Decimal("0") else None
            slip_vwap = (
                ((avg_px - plan.est_vwap) / plan.est_vwap)
                if avg_px is not None and plan.est_vwap > Decimal("0")
                else None
            )
        log_entry = ExecutionAttemptLog(
            schema_version="p3.v1",
            attempt_id=attempt_id,
            decision_id=ctx.decision_id,
            idempotency_key=idem_key,
            session_id=ctx.session_id,
            execution_mode=self._audit_logger.execution_mode,
            capture_replay_mode="NONE",
            replay_source_seq_id=None,
            latency_injected_ms=None,
            station_id=ctx.station_id,
            market_id=ctx.market_id,
            token_id=ctx.yes_token_id,
            model_hash=ctx.model_hash,
            config_hash=ctx.config_hash,
            decision_ts_utc=ensure_utc_datetime(ctx.decision_ts_utc, field_name="p3.decision_ts_utc"),
            decision_best_ask=best_ask,
            decision_est_vwap=plan.est_vwap,
            decision_qual_depth_shares=plan.qual_depth_shares,
            order_type=plan.order_type,
            limit_price=plan.limit_price,
            target_shares=plan.target_shares,
            target_usd=plan.target_usd,
            submit_ts_utc=sub_ts,
            final_ts_utc=ensure_utc_datetime(final_ts, field_name="p3.final_ts_utc"),
            terminal_status=terminal_status,
            reject_or_abort_reason=reject_reason,
            filled_shares=filled_shares,
            filled_usd=filled_usd,
            actual_avg_fill_price=avg_px,
            fee_paid_usd=fee_paid_usd,
            fill_rate=fill_rate,
            slippage_vs_best_ask=slip_best,
            slippage_vs_est_vwap=slip_vwap,
            execution_legs=fill_legs,
        )
        self._audit_logger.log_p3_execution_attempt(log_entry)
        return log_entry

    def _reject_locally(
        self,
        *,
        req: LiveOrderRequest,
        attempt_id: str,
        client_order_id: str,
        idem_key: str,
        sub_ts: datetime,
        reason: str,
    ) -> ExecutionAttemptLog:
        self._emit_trace(
            req=req,
            attempt_id=attempt_id,
            client_order_id=client_order_id,
            idem_key=idem_key,
            stage="EXCEPTION",
            details={"local_reject_reason": reason},
            event_ts=sub_ts,
        )
        return self._record_terminal_attempt(
            req=req,
            attempt_id=attempt_id,
            idem_key=idem_key,
            sub_ts=sub_ts,
            final_ts=sub_ts,
            terminal_status="REJECTED",
            reject_reason=reason,
            filled_shares=Decimal("0"),
            filled_usd=Decimal("0"),
            fee_paid_usd=Decimal("0.00000"),
        )

    def _validate_local_order(
        self,
        req: LiveOrderRequest,
        safety: GatewaySafetyConfig,
        utc_day: date,
    ) -> Optional[str]:
        plan = req.plan
        if not plan.should_submit or plan.target_shares <= Decimal("0"):
            return f"PLAN_NOT_SUBMITTABLE:{plan.abort_reason or 'ZERO_SHARES'}"
        cross_err = validate_cross_side_routing(
            plan, execution_mode=self.effective_mode, config=req.trading_config
        )
        if cross_err is not None:
            return cross_err

        limit_p = to_guarded_decimal(plan.limit_price, name="order.limit_price")
        shares = to_guarded_decimal(plan.target_shares, name="order.target_shares")
        tick = to_guarded_decimal(req.tick_size, name="order.tick_size")

        if limit_p <= Decimal("0") or limit_p > safety.max_limit_price:
            return f"PRICE_OUT_OF_RANGE:{limit_p}>{safety.max_limit_price}"
        if tick not in safety.allowed_tick_sizes:
            return f"UNSUPPORTED_TICK_SIZE:{tick}"
        if (limit_p % tick) != Decimal("0"):
            return f"TICK_SIZE_MISALIGNED:{limit_p}%{tick}"
        if limit_p < tick or limit_p > (Decimal("1") - tick):
            return f"PRICE_BREAKS_TICK_BOUNDARY:{limit_p}"
        if shares < safety.min_order_size_shares:
            return f"BELOW_MIN_ORDER_SHARES:{shares}<{safety.min_order_size_shares}"
        if (shares % _SHARES_STEP) != Decimal("0"):
            return f"SHARES_PRECISION_EXCEEDS_2DP:{shares}"
        if safety.require_neg_risk and req.neg_risk is not True:
            return "NEG_RISK_REQUIRED_FOR_WEATHER_EVENT"

        notional_usd = shares * limit_p
        if notional_usd > safety.max_single_order_usd:
            return "SAFETY_GATE_SINGLE_ORDER_EXCEEDED"
        used_today = self._daily_used_by_date.get(utc_day, Decimal("0")) + self._daily_inflight_by_date.get(
            utc_day, Decimal("0")
        )
        if used_today + notional_usd > safety.max_daily_cumulative_usd:
            return "SAFETY_GATE_DAILY_LIMIT_EXCEEDED"
        return None

    def _compute_backoff_sec(self, safety: GatewaySafetyConfig, attempt_idx: int) -> float:
        raw = min(safety.backoff_max_sec, safety.backoff_base_sec * (2**attempt_idx))
        jitter = 1.0 + self._rng.uniform(-safety.backoff_jitter_ratio, safety.backoff_jitter_ratio)
        return max(0.0, raw * jitter)

    def _register_failure(
        self,
        *,
        req: LiveOrderRequest,
        safety: GatewaySafetyConfig,
        attempt_id: str,
        client_order_id: str,
        idem_key: str,
        reason: str,
    ) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= safety.circuit_breaker_failure_threshold and not self._circuit_open:
            self._circuit_open = True
            msg = (
                f"CLOB Gateway CIRCUIT BREAKER TRIPPED after {self._consecutive_failures} "
                f"consecutive failures (last={reason}); manual reset required"
            )
            logger.critical(msg)
            if self._alert_callback is not None:
                self._alert_callback(msg)
            self._emit_trace(
                req=req,
                attempt_id=attempt_id,
                client_order_id=client_order_id,
                idem_key=idem_key,
                stage="CIRCUIT_BREAKER",
                details={
                    "action": "TRIPPED",
                    "consecutive_failures": self._consecutive_failures,
                    "reason": reason,
                },
            )

    def _parse_fill_from_response(
        self,
        *,
        req: LiveOrderRequest,
        resp: Mapping[str, Any],
    ) -> Tuple[TerminalStatus, Optional[str], Decimal, Decimal, Decimal]:
        """Extract deduplicated FAK fill status, shares, notional USD, and taker fee."""
        trades_raw = resp.get("trades")
        filled_shares = Decimal("0")
        filled_usd = Decimal("0")
        if isinstance(trades_raw, Sequence) and not isinstance(trades_raw, (str, bytes)) and trades_raw:
            for tr in trades_raw:
                if not isinstance(tr, Mapping):
                    continue
                tid = str(tr.get("id") or "")
                if tid:
                    if tid in self._seen_trade_ids:
                        continue
                    self._seen_trade_ids.add(tid)
                tr_shares = to_guarded_decimal(tr.get("size", "0"), name="trade.size")
                tr_price = to_guarded_decimal(tr.get("price", req.plan.limit_price), name="trade.price")
                filled_shares += tr_shares
                filled_usd += tr_shares * tr_price
        else:
            for tid in resp.get("tradeIds") or ():
                tid_s = str(tid)
                if tid_s and tid_s in self._seen_trade_ids:
                    return "CANCELLED_UNFILLED", "DUPLICATE_TRADE_ID_IGNORED", Decimal("0"), Decimal("0"), Decimal("0.00000")
            for tid in resp.get("tradeIds") or ():
                if tid:
                    self._seen_trade_ids.add(str(tid))
            raw_taking = resp.get("takingAmount") or resp.get("size_matched") or "0"
            raw_making = resp.get("makingAmount")
            filled_shares = to_guarded_decimal(raw_taking, name="resp.takingAmount")
            if raw_making is not None:
                filled_usd = to_guarded_decimal(raw_making, name="resp.makingAmount")
            else:
                px = to_guarded_decimal(resp.get("price", req.plan.limit_price), name="resp.price")
                filled_usd = filled_shares * px

        target_sh = req.plan.target_shares
        if filled_shares > target_sh:
            filled_shares = target_sh
        if filled_shares <= Decimal("0"):
            err = str(resp.get("errorMsg") or resp.get("error") or "FAK_UNFILLED")
            if resp.get("success") is False and not _is_fak_unfilled_error(err):
                return "REJECTED", err, Decimal("0"), Decimal("0"), Decimal("0.00000")
            return "CANCELLED_UNFILLED", err, Decimal("0"), Decimal("0"), Decimal("0.00000")

        with exact_decimal_context():
            avg_px = filled_usd / filled_shares
            raw_fee = compute_taker_fee_usd_raw(filled_shares, avg_px, req.fee_rate)
            fee_usd = quantize_polymarket_fee_usd(raw_fee)
        status: TerminalStatus = "FILLED" if filled_shares >= target_sh else "PARTIAL"
        return status, None, filled_shares, filled_usd, fee_usd

    def _reconcile_on_error(
        self,
        *,
        req: LiveOrderRequest,
        safety: GatewaySafetyConfig,
        transport: _LiveClobTransport,
        attempt_id: str,
        client_order_id: str,
        idem_key: str,
        nonce: int,
        signature: str,
        post_exc: Exception,
    ) -> Tuple[Optional[Dict[str, Any]], bool]:
        """Run lookup (`查单`) with backoff+jitter before making any retry decision."""
        lookup_ok = False
        for r_idx in range(max(1, safety.max_reconnect_attempts)):
            self._sleep_fn(self._compute_backoff_sec(safety, r_idx))
            try:
                found = transport.lookup_order_or_trades(
                    order_id=None,
                    token_id=req.context.yes_token_id,
                    nonce=nonce,
                    signature=signature,
                )
                lookup_ok = True
                self._emit_trace(
                    req=req,
                    attempt_id=attempt_id,
                    client_order_id=client_order_id,
                    idem_key=idem_key,
                    stage="ORDER_RECONCILE",
                    details={
                        "found": found is not None,
                        "source": found["source"] if found else None,
                        "after_error": f"{type(post_exc).__name__}: {post_exc}",
                    },
                )
                if found is not None:
                    if found.get("trades"):
                        return {"trades": found["trades"], "success": True}, True
                    order_obj = found["order"] or {}
                    return {
                        "success": True,
                        "orderID": order_obj.get("id"),
                        "status": order_obj.get("status"),
                        "size_matched": order_obj.get("size_matched", "0"),
                        "price": order_obj.get("price", str(req.plan.limit_price)),
                    }, True
                return None, True
            except Exception as lookup_exc:
                self._emit_trace(
                    req=req,
                    attempt_id=attempt_id,
                    client_order_id=client_order_id,
                    idem_key=idem_key,
                    stage="EXCEPTION",
                    details={"lookup_retry": r_idx, "error": f"{type(lookup_exc).__name__}: {lookup_exc}"},
                )
        return None, lookup_ok

    def submit_order(self, req: LiveOrderRequest) -> ExecutionAttemptLog:
        """Validate, dual-gate check, EIP-712 sign, submit `IOC_FAK`, reconcile, and log `P3`."""
        with self._lock:
            ctx = req.context
            sub_ts = ensure_utc_datetime(ctx.submit_ts_utc, field_name="gateway.submit_ts_utc")
            utc_day = sub_ts.date()
            attempt_id = ctx.resolved_attempt_id(sub_ts)
            idem_key = ctx.resolved_idempotency_key(sub_ts)
            client_order_id = req.client_order_id or f"cid-{attempt_id}"

            # Invariant ii: PRE_SIGN_SNAPSHOT is always logged first via AsyncAuditLogger
            self._emit_trace(
                req=req,
                attempt_id=attempt_id,
                client_order_id=client_order_id,
                idem_key=idem_key,
                stage="PRE_SIGN_SNAPSHOT",
                details={
                    "requested_mode": ctx.execution_mode,
                    "gateway_effective_mode": self.effective_mode,
                    "target_shares": str(req.plan.target_shares),
                    "limit_price": str(req.plan.limit_price),
                    "target_usd": str(req.plan.target_usd),
                    "tick_size": str(req.tick_size),
                    "neg_risk": req.neg_risk,
                    "daily_used_before_usd": str(self._daily_used_by_date.get(utc_day, Decimal("0"))),
                },
                event_ts=sub_ts,
            )

            if idem_key in self._idempotency_cache:
                cached = self._idempotency_cache[idem_key]
                self._emit_trace(
                    req=req,
                    attempt_id=attempt_id,
                    client_order_id=client_order_id,
                    idem_key=idem_key,
                    stage="ORDER_RECONCILE",
                    details={"idempotency_deduplicated": True, "cached_attempt_id": cached.attempt_id},
                    event_ts=sub_ts,
                )
                return cached

            if self._circuit_open:
                return self._reject_locally(
                    req=req,
                    attempt_id=attempt_id,
                    client_order_id=client_order_id,
                    idem_key=idem_key,
                    sub_ts=sub_ts,
                    reason="CIRCUIT_BREAKER_OPEN",
                )

            try:
                safety = self._refresh_safety_config()
            except Exception as exc:
                self._register_failure(
                    req=req, safety=self._safety_config, attempt_id=attempt_id,
                    client_order_id=client_order_id, idem_key=idem_key, reason=str(exc),
                )
                return self._reject_locally(
                    req=req, attempt_id=attempt_id, client_order_id=client_order_id,
                    idem_key=idem_key, sub_ts=sub_ts, reason=f"GATEWAY_CONFIG_ERROR:{exc}",
                )

            # Invariant iii: structural PAPER mode lock
            if not self.live_transport_enabled or self._transport is None:
                return self._reject_locally(
                    req=req,
                    attempt_id=attempt_id,
                    client_order_id=client_order_id,
                    idem_key=idem_key,
                    sub_ts=sub_ts,
                    reason="PAPER_MODE_LIVE_SUBMIT_FORBIDDEN",
                )

            val_err = self._validate_local_order(req, safety, utc_day)
            if val_err is not None:
                return self._reject_locally(
                    req=req,
                    attempt_id=attempt_id,
                    client_order_id=client_order_id,
                    idem_key=idem_key,
                    sub_ts=sub_ts,
                    reason=val_err,
                )

            transport = self._transport
            nonce = self._nonce_provider(ctx)
            reserved_usd = req.plan.target_shares * req.plan.limit_price
            self._daily_inflight_by_date[utc_day] = (
                self._daily_inflight_by_date.get(utc_day, Decimal("0")) + reserved_usd
            )
            try:
                return self._execute_live_post(
                    req=req,
                    safety=safety,
                    transport=transport,
                    utc_day=utc_day,
                    attempt_id=attempt_id,
                    client_order_id=client_order_id,
                    idem_key=idem_key,
                    sub_ts=sub_ts,
                    nonce=nonce,
                )
            finally:
                self._daily_inflight_by_date[utc_day] = max(
                    Decimal("0"),
                    self._daily_inflight_by_date.get(utc_day, Decimal("0")) - reserved_usd,
                )

    def _execute_live_post(
        self,
        *,
        req: LiveOrderRequest,
        safety: GatewaySafetyConfig,
        transport: _LiveClobTransport,
        utc_day: date,
        attempt_id: str,
        client_order_id: str,
        idem_key: str,
        sub_ts: datetime,
        nonce: int,
    ) -> ExecutionAttemptLog:
        assert self.effective_mode == "LIVE"
        try:
            signed_order = transport.sign_fak_buy_order(
                token_id=req.context.yes_token_id,
                limit_price=req.plan.limit_price,
                shares=req.plan.target_shares,
                tick_size=req.tick_size,
                neg_risk=req.neg_risk,
                nonce=nonce,
                fee_rate_bps=req.fee_rate_bps,
            )
        except Exception as exc:
            self._emit_trace(
                req=req, attempt_id=attempt_id, client_order_id=client_order_id,
                idem_key=idem_key, stage="EXCEPTION", details={"sign_error": f"{type(exc).__name__}: {exc}"},
            )
            self._register_failure(
                req=req, safety=safety, attempt_id=attempt_id, client_order_id=client_order_id,
                idem_key=idem_key, reason=f"SIGN_ERROR:{exc}",
            )
            return self._record_terminal_attempt(
                req=req, attempt_id=attempt_id, idem_key=idem_key, sub_ts=sub_ts,
                final_ts=datetime.now(timezone.utc), terminal_status="REJECTED",
                reject_reason=f"SDK_SIGN_ERROR:{exc}", filled_shares=Decimal("0"),
                filled_usd=Decimal("0"), fee_paid_usd=Decimal("0.00000"),
            )

        signed_dict = signed_order.dict() if hasattr(signed_order, "dict") else {}
        sig_hex = str(signed_dict.get("signature", ""))
        self._emit_trace(
            req=req,
            attempt_id=attempt_id,
            client_order_id=client_order_id,
            idem_key=idem_key,
            stage="HTTP_REQUEST",
            details={
                "orderType": "FAK",
                "tokenId": signed_dict.get("tokenId"),
                "makerAmount": signed_dict.get("makerAmount"),
                "takerAmount": signed_dict.get("takerAmount"),
                "nonce": signed_dict.get("nonce"),
                "salt": signed_dict.get("salt"),
            },
        )

        resp_payload: Optional[Dict[str, Any]] = None
        last_err: Optional[Exception] = None
        max_post_attempts = 1 + safety.max_reconnect_attempts
        for post_try in range(max_post_attempts):
            try:
                resp_payload = transport.post_signed_fak_order(signed_order)
                break
            except PolyApiException as exc:
                last_err = exc
                raw_transport_err = transport.last_request_error
                if exc.status_code is not None and exc.status_code < 500 and exc.status_code not in (408, 425, 429):
                    err_str = str(exc.error_msg)
                    self._consecutive_failures = 0
                    self._emit_trace(
                        req=req, attempt_id=attempt_id, client_order_id=client_order_id,
                        idem_key=idem_key, stage="HTTP_RESPONSE",
                        details={"status_code": exc.status_code, "error": err_str},
                    )
                    status: TerminalStatus = "CANCELLED_UNFILLED" if _is_fak_unfilled_error(err_str) else "REJECTED"
                    out = self._record_terminal_attempt(
                        req=req, attempt_id=attempt_id, idem_key=idem_key, sub_ts=sub_ts,
                        final_ts=datetime.now(timezone.utc), terminal_status=status,
                        reject_reason=err_str, filled_shares=Decimal("0"),
                        filled_usd=Decimal("0"), fee_paid_usd=Decimal("0.00000"),
                    )
                    self._idempotency_cache[idem_key] = out
                    return out
                pre_connect = raw_transport_err is not None and _is_pre_connect_error(raw_transport_err)
            except Exception as exc:
                last_err = exc
                pre_connect = _is_pre_connect_error(exc)
                if not _is_ambiguous_network_error(exc) and not pre_connect:
                    self._emit_trace(
                        req=req, attempt_id=attempt_id, client_order_id=client_order_id,
                        idem_key=idem_key, stage="EXCEPTION", details={"error": f"{type(exc).__name__}: {exc}"},
                    )
                    self._register_failure(
                        req=req, safety=safety, attempt_id=attempt_id, client_order_id=client_order_id,
                        idem_key=idem_key, reason=str(exc),
                    )
                    return self._record_terminal_attempt(
                        req=req, attempt_id=attempt_id, idem_key=idem_key, sub_ts=sub_ts,
                        final_ts=datetime.now(timezone.utc), terminal_status="REJECTED",
                        reject_reason=f"POST_EXCEPTION:{type(exc).__name__}", filled_shares=Decimal("0"),
                        filled_usd=Decimal("0"), fee_paid_usd=Decimal("0.00000"),
                    )

            # Lookup order BEFORE any retry decision ("宁可漏单，不可重单")
            found_payload, lookup_ok = self._reconcile_on_error(
                req=req, safety=safety, transport=transport, attempt_id=attempt_id,
                client_order_id=client_order_id, idem_key=idem_key, nonce=nonce,
                signature=sig_hex, post_exc=last_err,
            )
            if found_payload is not None:
                resp_payload = found_payload
                break
            if not lookup_ok or not pre_connect or post_try + 1 >= max_post_attempts:
                reason = (
                    "RECONCILE_FAILED_NO_RETRY"
                    if not lookup_ok
                    else "AMBIGUOUS_TIMEOUT_ORDER_ABSENT_NO_RESEND"
                )
                self._register_failure(
                    req=req, safety=safety, attempt_id=attempt_id, client_order_id=client_order_id,
                    idem_key=idem_key, reason=f"{reason}:{last_err}",
                )
                out = self._record_terminal_attempt(
                    req=req, attempt_id=attempt_id, idem_key=idem_key, sub_ts=sub_ts,
                    final_ts=datetime.now(timezone.utc), terminal_status="REJECTED",
                    reject_reason=reason, filled_shares=Decimal("0"),
                    filled_usd=Decimal("0"), fee_paid_usd=Decimal("0.00000"),
                )
                self._idempotency_cache[idem_key] = out
                return out

        assert resp_payload is not None
        return self._finalize_order_response(
            req=req,
            utc_day=utc_day,
            attempt_id=attempt_id,
            client_order_id=client_order_id,
            idem_key=idem_key,
            sub_ts=sub_ts,
            resp_payload=resp_payload,
        )

    def _finalize_order_response(
        self,
        *,
        req: LiveOrderRequest,
        utc_day: date,
        attempt_id: str,
        client_order_id: str,
        idem_key: str,
        sub_ts: datetime,
        resp_payload: Mapping[str, Any],
    ) -> ExecutionAttemptLog:
        self._consecutive_failures = 0
        self._emit_trace(
            req=req,
            attempt_id=attempt_id,
            client_order_id=client_order_id,
            idem_key=idem_key,
            stage="HTTP_RESPONSE",
            details={
                "orderID": resp_payload.get("orderID"),
                "status": resp_payload.get("status"),
                "success": resp_payload.get("success"),
            },
        )
        status, reject_reason, filled_sh, filled_usd, fee_usd = self._parse_fill_from_response(
            req=req, resp=resp_payload
        )
        if filled_usd > Decimal("0"):
            self._daily_used_by_date[utc_day] = self._daily_used_by_date.get(utc_day, Decimal("0")) + filled_usd
            self._persist_daily_ledger()

        legs: Tuple[FillLegRecord, ...] = ()
        if filled_sh > Decimal("0"):
            avg_px = filled_usd / filled_sh
            legs = (
                FillLegRecord(
                    leg_source="YES_ASK",
                    source_token_id=req.context.yes_token_id,
                    implied_yes_price=avg_px,
                    raw_source_price=avg_px,
                    filled_shares=filled_sh,
                    fee_usd_raw=fee_usd,
                ),
            )
        out = self._record_terminal_attempt(
            req=req,
            attempt_id=attempt_id,
            idem_key=idem_key,
            sub_ts=sub_ts,
            final_ts=datetime.now(timezone.utc),
            terminal_status=status,
            reject_reason=reject_reason,
            filled_shares=filled_sh,
            filled_usd=filled_usd,
            fee_paid_usd=fee_usd,
            fill_legs=legs,
        )
        self._idempotency_cache[idem_key] = out
        return out

    def submit_paper_simulated_order(
        self,
        req: LiveOrderRequest,
        *,
        paper_submit: Callable[[LiveOrderRequest, str, str, str, int], Mapping[str, Any]],
        paper_lookup: Optional[Callable[[str, str, int], Optional[Mapping[str, Any]]]] = None,
    ) -> ExecutionAttemptLog:
        """PAPER-only simulated CLOB execution reusing safety gates, daily ledger, fault recovery & P3."""
        if self.effective_mode != "PAPER" or self.live_transport_enabled:
            raise RuntimeError("submit_paper_simulated_order is strictly restricted to PAPER mode")
        with self._lock:
            ctx = req.context
            sub_ts = ensure_utc_datetime(ctx.submit_ts_utc, field_name="gateway.submit_ts_utc")
            utc_day = sub_ts.date()
            attempt_id = ctx.resolved_attempt_id(sub_ts)
            idem_key = ctx.resolved_idempotency_key(sub_ts)
            client_order_id = req.client_order_id or f"cid-{attempt_id}"

            self._emit_trace(
                req=req,
                attempt_id=attempt_id,
                client_order_id=client_order_id,
                idem_key=idem_key,
                stage="PRE_SIGN_SNAPSHOT",
                details={
                    "requested_mode": ctx.execution_mode,
                    "gateway_effective_mode": self.effective_mode,
                    "paper_simulation": True,
                    "target_shares": str(req.plan.target_shares),
                    "limit_price": str(req.plan.limit_price),
                    "target_usd": str(req.plan.target_usd),
                    "daily_used_before_usd": str(self._daily_used_by_date.get(utc_day, Decimal("0"))),
                },
                event_ts=sub_ts,
            )
            if idem_key in self._idempotency_cache:
                return self._idempotency_cache[idem_key]
            if self._circuit_open:
                return self._reject_locally(
                    req=req, attempt_id=attempt_id, client_order_id=client_order_id,
                    idem_key=idem_key, sub_ts=sub_ts, reason="CIRCUIT_BREAKER_OPEN",
                )
            safety = self._refresh_safety_config()
            if safety.execution_mode != "PAPER":
                return self._reject_locally(
                    req=req, attempt_id=attempt_id, client_order_id=client_order_id,
                    idem_key=idem_key, sub_ts=sub_ts, reason="PAPER_MODE_REQUIRED_FOR_SIM",
                )
            val_err = self._validate_local_order(req, safety, utc_day)
            if val_err is not None:
                return self._reject_locally(
                    req=req, attempt_id=attempt_id, client_order_id=client_order_id,
                    idem_key=idem_key, sub_ts=sub_ts, reason=val_err,
                )

            nonce = self._nonce_provider(ctx)
            reserved_usd = req.plan.target_shares * req.plan.limit_price
            self._daily_inflight_by_date[utc_day] = (
                self._daily_inflight_by_date.get(utc_day, Decimal("0")) + reserved_usd
            )
            try:
                resp_payload = self._execute_paper_with_recovery(
                    req=req,
                    safety=safety,
                    attempt_id=attempt_id,
                    client_order_id=client_order_id,
                    idem_key=idem_key,
                    nonce=nonce,
                    sub_ts=sub_ts,
                    paper_submit=paper_submit,
                    paper_lookup=paper_lookup,
                )
                if isinstance(resp_payload, ExecutionAttemptLog):
                    return resp_payload
                return self._finalize_order_response(
                    req=req, utc_day=utc_day, attempt_id=attempt_id,
                    client_order_id=client_order_id, idem_key=idem_key,
                    sub_ts=sub_ts, resp_payload=resp_payload,
                )
            finally:
                self._daily_inflight_by_date[utc_day] = max(
                    Decimal("0"),
                    self._daily_inflight_by_date.get(utc_day, Decimal("0")) - reserved_usd,
                )

    def _execute_paper_with_recovery(
        self,
        *,
        req: LiveOrderRequest,
        safety: GatewaySafetyConfig,
        attempt_id: str,
        client_order_id: str,
        idem_key: str,
        nonce: int,
        sub_ts: datetime,
        paper_submit: Callable[[LiveOrderRequest, str, str, str, int], Mapping[str, Any]],
        paper_lookup: Optional[Callable[[str, str, int], Optional[Mapping[str, Any]]]],
    ) -> Mapping[str, Any] | ExecutionAttemptLog:
        max_attempts = 1 + safety.max_reconnect_attempts
        last_err: Optional[Exception] = None
        for post_try in range(max_attempts):
            try:
                resp = paper_submit(req, client_order_id, attempt_id, idem_key, nonce)
                if str(resp.get("status", "")).upper() in ("LIVE", "PENDING") and paper_lookup is not None:
                    for poll_idx in range(max_attempts):
                        self._sleep_fn(self._compute_backoff_sec(safety, poll_idx))
                        polled = paper_lookup(client_order_id, attempt_id, nonce)
                        self._emit_trace(
                            req=req, attempt_id=attempt_id, client_order_id=client_order_id,
                            idem_key=idem_key, stage="ORDER_RECONCILE",
                            details={"delayed_callback_poll": poll_idx + 1, "found": polled is not None},
                        )
                        if polled is not None and str(polled.get("status", "")).upper() not in ("LIVE", "PENDING"):
                            return polled
                return resp
            except (ConnectionError, TimeoutError, httpx.TransportError) as exc:
                last_err = exc
                self._emit_trace(
                    req=req, attempt_id=attempt_id, client_order_id=client_order_id,
                    idem_key=idem_key, stage="EXCEPTION",
                    details={"paper_fault": f"{type(exc).__name__}: {exc}", "try": post_try + 1},
                )
                found = paper_lookup(client_order_id, attempt_id, nonce) if paper_lookup is not None else None
                self._emit_trace(
                    req=req, attempt_id=attempt_id, client_order_id=client_order_id,
                    idem_key=idem_key, stage="ORDER_RECONCILE",
                    details={"lookup_before_retry": True, "found": found is not None},
                )
                if found is not None:
                    return found
                is_pre_connect = isinstance(exc, (ConnectionError, httpx.ConnectError))
                if not is_pre_connect or post_try + 1 >= max_attempts:
                    reason = f"PAPER_FAULT_UNRECOVERED:{type(exc).__name__}:{exc}"
                    self._register_failure(
                        req=req, safety=safety, attempt_id=attempt_id,
                        client_order_id=client_order_id, idem_key=idem_key, reason=reason,
                    )
                    out = self._record_terminal_attempt(
                        req=req, attempt_id=attempt_id, idem_key=idem_key, sub_ts=sub_ts,
                        final_ts=datetime.now(timezone.utc), terminal_status="REJECTED",
                        reject_reason=reason, filled_shares=Decimal("0"),
                        filled_usd=Decimal("0"), fee_paid_usd=Decimal("0.00000"),
                    )
                    self._idempotency_cache[idem_key] = out
                    return out
                self._sleep_fn(self._compute_backoff_sec(safety, post_try))
        raise RuntimeError(f"Unreachable paper execution loop failure: {last_err}")


__all__ = [
    "ClobOrderGateway",
    "DEFAULT_GATEWAY_CONFIG_PATH",
    "EXPECTED_PY_CLOB_CLIENT_VERSION",
    "GatewayConfigError",
    "GatewayRiskPanelSnapshot",
    "GatewaySafetyConfig",
    "GatewayVersionError",
    "LiveOrderRequest",
    "load_gateway_safety_config",
    "verify_locked_sdk_version",
]
