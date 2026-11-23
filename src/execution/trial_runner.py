"""M5 (`S3-14`) `PAPER`-mode E2E Trial Runner, Preflight, Mock CLOB Exchange & `CLOB <-> P3` Reconcile."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
import json
import os
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple
import uuid

import httpx

from src.audit.audit_logger import AsyncAuditLogger, STREAM_FILENAMES
from src.audit.p10_reader import read_verified_jsonl_file
from src.bankroll.manager import BankrollAccountManager
from src.bankroll.models import BankrollConfig, BankrollStateSnapshot, FillSettleLoopback, FreezeRequest
from src.data_acquisition.passive_book_recorder import MarketBookSnapshot
from src.decision.engine import (
    DeterministicDecider,
    ExecutionPolicyBundle,
    PhiPolicy,
    ScanDecisionEvent,
    SigmaDeltaFrozen,
    build_execution_policy_bundle,
)
from src.execution.clob_gateway import (
    ClobOrderGateway,
    DEFAULT_GATEWAY_CONFIG_PATH,
    LiveOrderRequest,
    load_gateway_safety_config,
    verify_locked_sdk_version,
)
from src.execution.executor import (
    ExecutionAttemptLog,
    OrderExecutionContext,
    SlicePlan,
    TradingExecutionConfig,
    compute_taker_fee_usd_raw,
    quantize_polymarket_fee_usd,
)
from src.execution.stub_generator import (
    build_p4_v11_stub_envelope,
    build_stub_forecast_v11,
    default_stub_trading_config,
)
from src.prediction.forecast_distribution_engine import ForecastDistributionSnapshotV11

_POLYGON_USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
_POLY_CTF_EXCHANGE = "0x4bFb4155B35707903C39A5A4D8dA6b8B8982E54d"
_ERC20_ALLOWANCE_SELECTOR = "0xdd62ed3e"

PaperScenarioMode = Literal[
    "FILLED",
    "PARTIAL",
    "REJECTED",
    "TIMEOUT",
    "DISCONNECT",
    "TIMEOUT_RECOVER",
    "DELAYED_CALLBACK",
]


@dataclass(frozen=True)
class PaperOrderScenario:
    """Deterministic simulation directive queued for one order in `PaperMockClobExchange`."""

    mode: PaperScenarioMode
    partial_ratio: Decimal = Decimal("0.5")


@dataclass(frozen=True)
class MockCommittedOrder:
    """Authoritative exchange-side record stored by `PaperMockClobExchange` for `CLOB <-> P3` reconcile."""

    order_id: str
    attempt_id: str
    client_order_id: str
    nonce: int
    terminal_status: str
    filled_shares: Decimal
    filled_usd: Decimal
    fee_paid_usd: Decimal


class PaperMockClobExchange:
    """Strictly offline stateful mock CLOB exchange supporting fill/partial/reject/timeout/fault modes."""

    def __init__(self, *, fee_rate_bps: int = 50, partial_default_ratio: Decimal = Decimal("0.5")) -> None:
        self.fee_rate_bps = int(fee_rate_bps)
        self.partial_default_ratio = Decimal(partial_default_ratio)
        self._scenarios: Deque[PaperOrderScenario] = deque()
        self.committed_orders: Dict[str, MockCommittedOrder] = {}
        self._by_client_id: Dict[str, Dict[str, Any]] = {}
        self._delayed_polls: Dict[str, int] = {}
        self._disconnected_once: set[str] = set()
        self._seq = 0

    @property
    def fee_rate(self) -> Decimal:
        return Decimal(self.fee_rate_bps) / Decimal("10000")

    def queue_scenario(self, scenario: PaperOrderScenario) -> None:
        self._scenarios.append(scenario)

    def _next_scenario(self) -> PaperOrderScenario:
        if self._scenarios:
            return self._scenarios.popleft()
        return PaperOrderScenario(mode="FILLED")

    def submit(
        self,
        req: LiveOrderRequest,
        client_order_id: str,
        attempt_id: str,
        idem_key: str,
        nonce: int,
    ) -> Mapping[str, Any]:
        if client_order_id in self._by_client_id:
            return self._by_client_id[client_order_id]

        scenario = self._next_scenario()
        if scenario.mode == "DISCONNECT" and client_order_id not in self._disconnected_once:
            self._disconnected_once.add(client_order_id)
            raise ConnectionError("MOCK_PRE_CONNECT_DISCONNECT")

        self._seq += 1
        order_id = f"0xmock-{self._seq:06d}"
        shares = req.plan.target_shares
        limit_p = req.plan.limit_price

        if scenario.mode == "REJECTED":
            payload = {"success": False, "orderID": order_id, "errorMsg": "MOCK_CLOB_ORDER_REJECTED"}
            self._record_final(order_id, attempt_id, client_order_id, nonce, "REJECTED", Decimal("0"), Decimal("0"), Decimal("0.00000"), payload)
            return payload

        if scenario.mode == "TIMEOUT":
            payload = {"success": False, "orderID": order_id, "errorMsg": "TIMEOUT: no orders found to match with FAK"}
            self._record_final(order_id, attempt_id, client_order_id, nonce, "CANCELLED_UNFILLED", Decimal("0"), Decimal("0"), Decimal("0.00000"), payload)
            return payload

        fill_sh = shares
        terminal = "FILLED"
        if scenario.mode == "PARTIAL":
            fill_sh = (shares * scenario.partial_ratio).quantize(Decimal("0.01"))
            if fill_sh <= Decimal("0"):
                fill_sh = Decimal("1.00")
            if fill_sh >= shares:
                fill_sh = max(Decimal("0.01"), shares - Decimal("0.01"))
            terminal = "PARTIAL"

        filled_usd = fill_sh * limit_p
        fee_usd = quantize_polymarket_fee_usd(compute_taker_fee_usd_raw(fill_sh, limit_p, req.fee_rate))
        final_payload: Dict[str, Any] = {
            "success": True,
            "orderID": order_id,
            "status": "MATCHED",
            "takingAmount": str(fill_sh),
            "makingAmount": str(filled_usd),
        }
        self._record_final(order_id, attempt_id, client_order_id, nonce, terminal, fill_sh, filled_usd, fee_usd, final_payload)

        if scenario.mode == "TIMEOUT_RECOVER":
            raise TimeoutError("MOCK_READ_TIMEOUT_AFTER_EXCHANGE_MATCH")

        if scenario.mode == "DELAYED_CALLBACK":
            self._delayed_polls[client_order_id] = 1
            return {"success": True, "orderID": order_id, "status": "LIVE"}

        return final_payload

    def _record_final(
        self,
        order_id: str,
        attempt_id: str,
        client_order_id: str,
        nonce: int,
        terminal_status: str,
        filled_shares: Decimal,
        filled_usd: Decimal,
        fee_paid_usd: Decimal,
        payload: Dict[str, Any],
    ) -> None:
        self._by_client_id[client_order_id] = payload
        self.committed_orders[attempt_id] = MockCommittedOrder(
            order_id=order_id,
            attempt_id=attempt_id,
            client_order_id=client_order_id,
            nonce=nonce,
            terminal_status=terminal_status,
            filled_shares=filled_shares,
            filled_usd=filled_usd,
            fee_paid_usd=fee_paid_usd,
        )

    def lookup(self, client_order_id: str, attempt_id: str, nonce: int) -> Optional[Mapping[str, Any]]:
        if client_order_id not in self._by_client_id:
            return None
        remaining_delays = self._delayed_polls.get(client_order_id, 0)
        if remaining_delays > 0:
            self._delayed_polls[client_order_id] = remaining_delays - 1
            return {"success": True, "orderID": self._by_client_id[client_order_id]["orderID"], "status": "LIVE"}
        return self._by_client_id[client_order_id]


@dataclass(frozen=True)
class AllowanceProbeResult:
    """Read-only Polygon ERC20 `allowance` probe outcome (zero `Approve` transactions)."""

    status: Literal["OK_READONLY", "PLACEHOLDER_NO_RPC_READONLY", "RPC_UNAVAILABLE_READONLY"]
    raw_allowance_units: Optional[int]
    detail: str


@dataclass(frozen=True)
class GammaProbeResult:
    """Read-only Gamma public API market metadata check (D-A2 follow-up, zero credentials)."""

    status: Literal["OK_READONLY", "PLACEHOLDER_NO_GAMMA_READONLY", "GAMMA_UNAVAILABLE_READONLY"]
    markets_sampled: int
    detail: str


@dataclass(frozen=True)
class PreflightReport:
    """Consolidated S3-14 startup preflight gate report."""

    ok: bool
    sdk_version: str
    execution_mode: str
    credentials_fail_closed: bool
    yaml_complete: bool
    audit_logger_online: bool
    daily_ledger_path: str
    allowance_probe: AllowanceProbeResult
    gamma_probe: GammaProbeResult = field(
        default_factory=lambda: GammaProbeResult("PLACEHOLDER_NO_GAMMA_READONLY", 0, "skipped")
    )
    errors: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "sdk_version": self.sdk_version,
            "execution_mode": self.execution_mode,
            "credentials_fail_closed": self.credentials_fail_closed,
            "yaml_complete": self.yaml_complete,
            "audit_logger_online": self.audit_logger_online,
            "daily_ledger_path": self.daily_ledger_path,
            "allowance_probe": {
                "status": self.allowance_probe.status,
                "raw_allowance_units": self.allowance_probe.raw_allowance_units,
                "detail": self.allowance_probe.detail,
            },
            "gamma_probe": {
                "status": self.gamma_probe.status,
                "markets_sampled": self.gamma_probe.markets_sampled,
                "detail": self.gamma_probe.detail,
            },
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class TrialStepResult:
    """Single end-to-end `M4 -> M5(PAPER) -> M6 -> M7` pipeline execution output."""

    scan_event: ScanDecisionEvent
    attempt_log: Optional[ExecutionAttemptLog]
    freeze_accepted: bool
    settled_cash_usd: Decimal
    conservation_residual_usd: Decimal


@dataclass(frozen=True)
class ClobP3ReconcileReport:
    """Two-layer `CLOB (mock) <-> P3` JSONL & `P14` conservation audit report."""

    ok: bool
    clob_order_count: int
    p3_attempt_count: int
    corrupt_p3_lines: int
    mismatched_attempts: Tuple[str, ...]
    conservation_residual_usd: Decimal

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "clob_order_count": self.clob_order_count,
            "p3_attempt_count": self.p3_attempt_count,
            "corrupt_p3_lines": self.corrupt_p3_lines,
            "mismatched_attempts": list(self.mismatched_attempts),
            "conservation_residual_usd": str(self.conservation_residual_usd),
        }


def query_readonly_erc20_allowance(
    *,
    rpc_url: Optional[str],
    token_contract: str = _POLYGON_USDC_E,
    owner_address: Optional[str] = None,
    spender_address: str = _POLY_CTF_EXCHANGE,
    rpc_transport: Optional[httpx.BaseTransport] = None,
    timeout_sec: float = 5.0,
) -> AllowanceProbeResult:
    """Execute read-only Polygon `eth_call` (`allowance(owner,spender)`); never submits transactions."""
    if not owner_address or (not rpc_url and rpc_transport is None):
        return AllowanceProbeResult(
            status="PLACEHOLDER_NO_RPC_READONLY",
            raw_allowance_units=None,
            detail="Read-only placeholder (no owner/RPC passed; zero Approve tx, zero creds required)",
        )
    owner_clean = owner_address.lower().removeprefix("0x").rjust(64, "0")
    spender_clean = spender_address.lower().removeprefix("0x").rjust(64, "0")
    call_data = f"{_ERC20_ALLOWANCE_SELECTOR}{owner_clean}{spender_clean}"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": token_contract, "data": call_data}, "latest"],
    }
    target = rpc_url or "https://polygon-rpc.invalid"
    try:
        with httpx.Client(transport=rpc_transport, timeout=timeout_sec, trust_env=False) as client:
            resp = client.post(target, json=payload)
            resp.raise_for_status()
            body = resp.json()
            raw_hex = str(body.get("result") or "0x0")
            units = int(raw_hex, 16)
            return AllowanceProbeResult(
                status="OK_READONLY",
                raw_allowance_units=units,
                detail="Verified read-only ERC20 allowance via eth_call",
            )
    except Exception as exc:
        return AllowanceProbeResult(
            status="RPC_UNAVAILABLE_READONLY",
            raw_allowance_units=None,
            detail=f"Read-only RPC skipped/unavailable: {type(exc).__name__}: {exc}",
        )


def query_readonly_gamma_metadata(
    *,
    gamma_url: Optional[str] = None,
    gamma_transport: Optional[httpx.BaseTransport] = None,
    timeout_sec: float = 5.0,
) -> GammaProbeResult:
    """Read-only public Gamma markets metadata probe (`D-A2`, zero auth/credentials)."""
    if not gamma_url and gamma_transport is None:
        return GammaProbeResult(
            status="PLACEHOLDER_NO_GAMMA_READONLY",
            markets_sampled=0,
            detail="Read-only placeholder (no Gamma URL passed; zero auth required)",
        )
    target = gamma_url or "https://gamma-api.polymarket.com/markets?limit=1"
    try:
        with httpx.Client(transport=gamma_transport, timeout=timeout_sec, trust_env=False) as client:
            resp = client.get(target)
            resp.raise_for_status()
            payload = resp.json()
            count = len(payload) if isinstance(payload, list) else (1 if isinstance(payload, dict) else 0)
            return GammaProbeResult(
                status="OK_READONLY",
                markets_sampled=count,
                detail="Verified read-only public Gamma metadata endpoint",
            )
    except Exception as exc:
        return GammaProbeResult(
            status="GAMMA_UNAVAILABLE_READONLY",
            markets_sampled=0,
            detail=f"Read-only Gamma skipped/unavailable: {type(exc).__name__}: {exc}",
        )


def run_preflight_checks(
    *,
    safety_config_path: Path = DEFAULT_GATEWAY_CONFIG_PATH,
    audit_logger: AsyncAuditLogger,
    rpc_url: Optional[str] = None,
    owner_address: Optional[str] = None,
    spender_address: str = _POLY_CTF_EXCHANGE,
    token_contract: str = _POLYGON_USDC_E,
    rpc_transport: Optional[httpx.BaseTransport] = None,
    gamma_url: Optional[str] = None,
    gamma_transport: Optional[httpx.BaseTransport] = None,
) -> PreflightReport:
    """Verify SDK lock, fail-closed PAPER mode, YAML completeness, M7 logger, and read-only allowance."""
    errors: List[str] = []
    sdk_ver = ""
    try:
        sdk_ver = verify_locked_sdk_version()
    except Exception as exc:
        errors.append(f"SDK_LOCK_FAILED:{exc}")

    yaml_ok = False
    ledger_str = ""
    exec_mode = "UNKNOWN"
    try:
        safety = load_gateway_safety_config(safety_config_path)
        yaml_ok = True
        exec_mode = safety.execution_mode
        ledger_str = str(safety.daily_ledger_path)
        if safety.execution_mode != "PAPER":
            errors.append(f"NON_PAPER_CONFIG:{safety.execution_mode}")
    except Exception as exc:
        errors.append(f"YAML_CONFIG_ERROR:{exc}")

    creds_fail_closed = False
    if yaml_ok and not errors:
        try:
            gw = ClobOrderGateway(safety_config_path=safety_config_path, audit_logger=audit_logger)
            snap = gw.preflight_safety_snapshot()
            creds_fail_closed = (snap["effective_mode"] == "PAPER") and (snap["live_transport_enabled"] is False)
            if not creds_fail_closed:
                errors.append("CREDENTIALS_NOT_FAIL_CLOSED_TO_PAPER")
        except Exception as exc:
            errors.append(f"GATEWAY_INIT_ERROR:{exc}")

    logger_online = False
    try:
        stats = audit_logger.stats()
        logger_online = (not audit_logger._closed) and stats.error_count == 0
        if not logger_online:
            errors.append("AUDIT_LOGGER_OFFLINE")
    except Exception as exc:
        errors.append(f"AUDIT_LOGGER_ERROR:{exc}")

    allowance = query_readonly_erc20_allowance(
        rpc_url=rpc_url,
        token_contract=token_contract,
        owner_address=owner_address,
        spender_address=spender_address,
        rpc_transport=rpc_transport,
    )
    gamma = query_readonly_gamma_metadata(
        gamma_url=gamma_url,
        gamma_transport=gamma_transport,
    )
    return PreflightReport(
        ok=len(errors) == 0,
        sdk_version=sdk_ver,
        execution_mode=exec_mode,
        credentials_fail_closed=creds_fail_closed,
        yaml_complete=yaml_ok,
        audit_logger_online=logger_online,
        daily_ledger_path=ledger_str,
        allowance_probe=allowance,
        gamma_probe=gamma,
        errors=tuple(errors),
    )


class TrialRunner:
    """Orchestrates `PAPER` pipeline `M4 -> M5(ClobOrderGateway PAPER) -> M6(Bankroll P14) -> M7`."""

    def __init__(
        self,
        *,
        session_id: str,
        decider: DeterministicDecider,
        gateway: ClobOrderGateway,
        bankroll: BankrollAccountManager,
        audit_logger: AsyncAuditLogger,
        exchange: PaperMockClobExchange,
        policy_bundle: ExecutionPolicyBundle,
    ) -> None:
        if gateway.effective_mode != "PAPER" or audit_logger.execution_mode != "PAPER":
            raise ValueError("TrialRunner is strictly restricted to PAPER mode")
        self.session_id = session_id
        self.decider = decider
        self.gateway = gateway
        self.bankroll = bankroll
        self.audit_logger = audit_logger
        self.exchange = exchange
        self.policy_bundle = policy_bundle
        self._seq = 0
        self._logged_forecast_ids: set[str] = set()

    def step_bin(
        self,
        *,
        scan_ts_utc: datetime,
        station_id: str,
        target_date: str,
        bin_id: str,
        market_id: str,
        yes_token_id: str,
        forecasts: Sequence[ForecastDistributionSnapshotV11],
        yes_frame: MarketBookSnapshot,
        tick_size: Decimal,
        neg_risk: bool,
        exec_config: TradingExecutionConfig,
        no_frame: Optional[MarketBookSnapshot] = None,
    ) -> TrialStepResult:
        """Run one bin scan -> pre-order P14 freeze -> PAPER gateway -> post-order P14 loopback."""
        self._seq += 1
        for fc in forecasts:
            if fc.forecast_id not in self._logged_forecast_ids:
                self.audit_logger.log_p17_forecast_snapshot(
                    fc, session_id=self.session_id, config_hash=self.policy_bundle.config_hash
                )
                self._logged_forecast_ids.add(fc.forecast_id)

        scan_event = self.decider.evaluate_bin(
            orig_session_id=self.session_id,
            execution_mode="PAPER",
            scan_clock="PRICE_CLOCK",
            scan_ts_utc=scan_ts_utc,
            station_id=station_id,
            target_date=target_date,
            bin_id=bin_id,
            market_id=market_id,
            yes_token_id=yes_token_id,
            forecasts=list(forecasts),
            policy_bundle=self.policy_bundle,
            quota_provider=self.bankroll,
            yes_frame=yes_frame,
            no_frame=no_frame,
            include_no_side=no_frame is not None,
        )
        self.audit_logger.log_p1_scan_decision(scan_event)

        plan: Optional[SlicePlan] = scan_event.slice_plan
        if scan_event.decision_outcome != "ORDERED" or plan is None or not plan.should_submit:
            snap = self.bankroll.snapshot_state()
            return TrialStepResult(scan_event, None, False, Decimal("0"), snap.conservation_residual_usd)

        est_fee = quantize_polymarket_fee_usd(
            compute_taker_fee_usd_raw(plan.target_shares, plan.limit_price, self.exchange.fee_rate)
        )
        freeze_amt = (plan.target_usd + est_fee).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
        idem_key = f"idem-{scan_event.decision_id}"
        freeze_rec = self.bankroll.freeze_for_order(
            FreezeRequest(
                decision_id=scan_event.decision_id,
                idempotency_key=idem_key,
                station_id=station_id,
                market_id=market_id,
                token_id=yes_token_id,
                target_freeze_usd=freeze_amt,
                requested_ts_utc=scan_ts_utc,
            )
        )
        if not freeze_rec.accepted:
            snap = self.bankroll.snapshot_state()
            return TrialStepResult(scan_event, None, False, Decimal("0"), snap.conservation_residual_usd)

        best_ask = Decimal(str(scan_event.best_ask_price or plan.limit_price))
        ctx = OrderExecutionContext(
            decision_id=scan_event.decision_id,
            session_id=self.session_id,
            station_id=station_id,
            market_id=market_id,
            yes_token_id=yes_token_id,
            model_hash=scan_event.model_hash,
            config_hash=scan_event.config_hash,
            decision_ts_utc=scan_ts_utc,
            decision_best_ask=best_ask,
            submit_ts_utc=scan_ts_utc,
            decision_seq_id=self._seq,
            execution_mode="PAPER",
            idempotency_key=idem_key,
        )
        req = LiveOrderRequest(
            context=ctx,
            plan=plan,
            tick_size=tick_size,
            neg_risk=neg_risk,
            trading_config=exec_config,
            fee_rate=self.exchange.fee_rate,
            fee_rate_bps=self.exchange.fee_rate_bps,
        )
        attempt = self.gateway.submit_paper_simulated_order(
            req,
            paper_submit=self.exchange.submit,
            paper_lookup=self.exchange.lookup,
        )
        settled_usd = self.bankroll.settle_order_fill(
            FillSettleLoopback(
                decision_id=scan_event.decision_id,
                attempt_id=attempt.attempt_id,
                station_id=station_id,
                market_id=market_id,
                filled_usd=attempt.filled_usd,
                fee_paid_usd=attempt.fee_paid_usd,
                terminal_status=attempt.terminal_status,
                settled_ts_utc=attempt.final_ts_utc,
                reject_or_abort_reason=attempt.reject_or_abort_reason,
            )
        )
        snap = self.bankroll.snapshot_state()
        return TrialStepResult(scan_event, attempt, True, settled_usd, snap.conservation_residual_usd)


def reconcile_clob_and_p3(
    *,
    audit_root: Path,
    execution_mode: Literal["PAPER", "LIVE"],
    utc_date: date,
    exchange: PaperMockClobExchange,
    bankroll_snapshot: Optional[BankrollStateSnapshot] = None,
    session_id: Optional[str] = None,
) -> ClobP3ReconcileReport:
    """Two-layer reconcile: mock CLOB orders <-> `P3` `ExecutionAttemptLog` + `P14` residual."""
    p3_path = Path(audit_root) / execution_mode / utc_date.isoformat() / STREAM_FILENAMES["p3"]
    stream = read_verified_jsonl_file(p3_path, verify_sha256=True)
    p3_attempts: Dict[str, Mapping[str, Any]] = {}
    mismatches: List[str] = []

    for rec in stream.records:
        if rec.get("schema_version") == "p3.v1":
            if session_id is not None and rec.get("session_id") != session_id:
                continue
            aid = str(rec.get("attempt_id") or "")
            if aid in p3_attempts:
                mismatches.append(f"DUPLICATE_P3_ATTEMPT:{aid}")
            p3_attempts[aid] = rec

    for aid, mock_ord in exchange.committed_orders.items():
        rec = p3_attempts.get(aid)
        if rec is None:
            mismatches.append(f"MISSING_IN_P3:{aid}")
            continue
        if str(rec.get("terminal_status")) != mock_ord.terminal_status:
            mismatches.append(f"STATUS_MISMATCH:{aid}")
        if Decimal(str(rec.get("filled_shares", "0"))) != mock_ord.filled_shares:
            mismatches.append(f"SHARES_MISMATCH:{aid}")
        if Decimal(str(rec.get("filled_usd", "0"))) != mock_ord.filled_usd:
            mismatches.append(f"USD_MISMATCH:{aid}")
        if Decimal(str(rec.get("fee_paid_usd", "0"))) != mock_ord.fee_paid_usd:
            mismatches.append(f"FEE_MISMATCH:{aid}")

    for aid in p3_attempts:
        if aid not in exchange.committed_orders:
            mismatches.append(f"MISSING_IN_CLOB:{aid}")

    residual = bankroll_snapshot.conservation_residual_usd if bankroll_snapshot is not None else Decimal("0")
    ok = len(stream.corrupt_lines) == 0 and len(mismatches) == 0 and residual == Decimal("0")
    return ClobP3ReconcileReport(
        ok=ok,
        clob_order_count=len(exchange.committed_orders),
        p3_attempt_count=len(p3_attempts),
        corrupt_p3_lines=len(stream.corrupt_lines),
        mismatched_attempts=tuple(mismatches),
        conservation_residual_usd=residual,
    )


def run_cli_self_test(*, safety_config_path: Path, state_dir: Path) -> Dict[str, Any]:
    """Run an offline deterministic `PAPER` self-test + preflight + reconcile in `state_dir`."""
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    t0 = datetime.now(timezone.utc)
    session_id = f"sess-cli-{uuid.uuid4().hex[:8]}"
    audit_root = state_dir / "m7"
    policy = build_execution_policy_bundle(
        policy_version="p6.v2",
        signed_at_utc=t0,
        is_overdue=False,
        w0_intent=0.10,
        min_order_usd_eff=2.0,
        p=1.5,
        tau_max_h=24.0,
        station_cap_usd=60.0,
        concurrent_days=2,
        w_provenance="CLI_SELF_TEST",
        phi_policy=PhiPolicy(rho_0=Decimal("0.40"), k_slope=Decimal("0"), rho_min=Decimal("0.20"), rho_max=Decimal("0.60")),
        k0_threshold_coef=1.0,
        sigma_delta_frozen=SigmaDeltaFrozen(0.01, "SELF_TEST", "cyc-self"),
        friction_median=0.005,
        m_floor=0.01,
        yellow_multiplier=0.5,
    )
    exchange = PaperMockClobExchange(fee_rate_bps=50)
    with AsyncAuditLogger(audit_root, execution_mode="PAPER") as logger:
        preflight = run_preflight_checks(safety_config_path=safety_config_path, audit_logger=logger)
        if not preflight.ok:
            return {"ok": False, "preflight": preflight.to_dict()}
        bankroll = BankrollAccountManager(
            BankrollConfig(
                session_id=session_id,
                execution_mode="PAPER",
                policy_version="p6.v2",
                config_hash=policy.config_hash,
                initial_pool_usd=Decimal("2000.00"),
                full_deployment=False,
            ),
            audit_logger=logger,
        )
        # Keep self-test ledger isolated inside state_dir
        gateway = ClobOrderGateway(
            safety_config_path=safety_config_path,
            audit_logger=logger,
            daily_ledger_path=state_dir / "daily_usage.json",
        )
        runner = TrialRunner(
            session_id=session_id,
            decider=DeterministicDecider(exec_config=default_stub_trading_config()),
            gateway=gateway,
            bankroll=bankroll,
            audit_logger=logger,
            exchange=exchange,
            policy_bundle=policy,
        )
        fc = build_stub_forecast_v11(
            target_date_str=t0.date().isoformat(),
            issue_ts_utc=t0,
            settle_close_utc=t0 + timedelta(hours=10),
        )
        yes_frame = build_p4_v11_stub_envelope(
            session_id=session_id,
            seq_id=1,
            frame_seq=1,
            token_id="tok-self",
            market_id="mkt-self",
            condition_id="cond-self",
            station_id="KORD",
            target_date=t0.date().isoformat(),
            bin_label="58-59°F",
            outcome="YES",
            regime="two_sided",
            recv_ts_utc=t0,
            asks=((0.25, 200.0),),
            bids=((0.24, 200.0),),
        )[0].payload
        for idx, mode in enumerate(("FILLED", "PARTIAL")):
            exchange.queue_scenario(PaperOrderScenario(mode=mode))  # type: ignore[arg-type]
            runner.step_bin(
                scan_ts_utc=t0 + timedelta(seconds=idx),
                station_id="KORD",
                target_date=t0.date().isoformat(),
                bin_id="bin-58-59",
                market_id=f"mkt-self-{idx}",
                yes_token_id="tok-self",
                forecasts=[fc],
                yes_frame=yes_frame,
                tick_size=Decimal("0.01"),
                neg_risk=True,
                exec_config=default_stub_trading_config(),
            )
        logger.flush()
    reconcile = reconcile_clob_and_p3(
        audit_root=audit_root,
        execution_mode="PAPER",
        utc_date=t0.date(),
        exchange=exchange,
        bankroll_snapshot=bankroll.snapshot_state(),
        session_id=session_id,
    )
    return {"ok": preflight.ok and reconcile.ok, "preflight": preflight.to_dict(), "reconcile": reconcile.to_dict()}


def write_runner_state(state_dir: Path, payload: Mapping[str, Any]) -> Path:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "runner_state.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(payload), sort_keys=True, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def read_runner_state(state_dir: Path) -> Dict[str, Any]:
    path = Path(state_dir) / "runner_state.json"
    if not path.exists():
        return {"status": "STOPPED", "pid": None}
    return dict(json.loads(path.read_text(encoding="utf-8")))
