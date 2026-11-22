"""TDD unit & structural security-gate tests for `S3-05b` CLOB EIP-712 gateway."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import subprocess
from typing import Any, Dict, List

import httpx
import pytest
from eth_account import Account

from src.audit.audit_logger import AsyncAuditLogger
from src.audit.p10_reader import P10Query, query_p10_session_view, read_verified_jsonl_file
from src.audit.p8_aggregator import aggregate_p8_calibration_batch
from src.execution.executor import (
    OrderExecutionContext,
    PlannedLegSlice,
    SlicePlan,
    TradingExecutionConfig,
)

# Fixed deterministic test key (Hardhat/Anvil public test key #0; NEVER real funds)
_TEST_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
_TEST_SIGNER_ADDR = Account.from_key(_TEST_PRIVATE_KEY).address


def _write_safety_config(
    path: Path,
    *,
    execution_mode: str = "PAPER",
    max_single_order_usd: str = "25",
    max_daily_cumulative_usd: str = "250",
    circuit_threshold: int = 5,
    max_reconnect_attempts: int = 3,
) -> Path:
    path.write_text(
        "\n".join(
            [
                f"execution_mode: {execution_mode}",
                "live_confirmation_env_var: POLY_LIVE_CONFIRM",
                "live_confirmation_expected_value: CONFIRM_LIVE",
                "clob_host: https://clob.polymarket.com",
                "chain_id: 137",
                "signature_type: 0",
                "tick_size_ttl_sec: 300.0",
                "use_system_proxy: false",
                f'max_single_order_usd: "{max_single_order_usd}"',
                f'max_daily_cumulative_usd: "{max_daily_cumulative_usd}"',
                'min_order_size_shares: "5"',
                'max_limit_price: "0.99"',
                "allowed_tick_sizes:",
                '  - "0.01"',
                '  - "0.001"',
                "require_neg_risk: true",
                "request_timeout_sec: 5.0",
                f"max_reconnect_attempts: {max_reconnect_attempts}",
                "backoff_base_sec: 0.01",
                "backoff_max_sec: 0.05",
                "backoff_jitter_ratio: 0.2",
                f"circuit_breaker_failure_threshold: {circuit_threshold}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _make_trading_config(*, enable_cross_side: bool = False) -> TradingExecutionConfig:
    return TradingExecutionConfig(
        min_order_size_shares=Decimal("5"),
        min_order_size_shares_provenance="FACT-004",
        min_notional_usd=Decimal("1"),
        min_notional_usd_provenance="FACT-004",
        forecast_age_limit_sec=3600.0,
        forecast_age_limit_sec_provenance="TEST",
        max_book_staleness_sec=60.0,
        max_book_staleness_sec_provenance="TEST",
        pair_max_skew_sec=5.0,
        pair_max_skew_sec_provenance="TEST",
        latency_ms=250,
        latency_ms_provenance="TEST",
        heartbeat_timeout_sec=25.0,
        heartbeat_timeout_sec_provenance="TEST",
        rest_fallback_interval_sec=5.0,
        rest_fallback_interval_sec_provenance="TEST",
        enable_cross_side_split_routing=enable_cross_side,
    )


def _make_context(
    *,
    decision_id: str = "dec-001",
    submit_ts_utc: datetime | None = None,
    execution_mode: str = "LIVE",
    idempotency_key: str | None = None,
) -> OrderExecutionContext:
    ts = submit_ts_utc or datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
    return OrderExecutionContext(
        decision_id=decision_id,
        session_id="sess-s305b-test",
        station_id="KORD",
        market_id="mkt-kord-001",
        yes_token_id="12345678901234567890",
        model_hash="frozen-model-hash-abc",
        config_hash="frozen-config-hash-xyz",
        decision_ts_utc=ts - timedelta(seconds=1),
        decision_best_ask=Decimal("0.40"),
        submit_ts_utc=ts,
        decision_seq_id=1,
        execution_mode=execution_mode,  # type: ignore[arg-type]
        idempotency_key=idempotency_key or f"idem-{decision_id}",
    )


def _make_plan(
    *,
    shares: Decimal = Decimal("10.00"),
    limit_price: Decimal = Decimal("0.40"),
    include_no_leg: bool = False,
) -> SlicePlan:
    leg = PlannedLegSlice(
        leg_source="NO_BID_SPLIT_SELL" if include_no_leg else "YES_ASK",
        source_token_id="12345678901234567890",
        implied_yes_price=limit_price,
        raw_source_price=limit_price,
        allocated_shares=shares,
        allocated_usd=shares * limit_price,
    )
    return SlicePlan(
        should_submit=True,
        target_usd=shares * limit_price,
        target_shares=shares,
        limit_price=limit_price,
        est_vwap=limit_price,
        qual_depth_shares=shares * Decimal("2"),
        order_type="IOC_FAK",
        abort_reason=None,
        leg_allocations=(leg,),
    )


def _set_creds_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLY_CLOB_PRIVATE_KEY", _TEST_PRIVATE_KEY)
    monkeypatch.setenv("POLY_CLOB_FUNDER", _TEST_SIGNER_ADDR)
    monkeypatch.setenv("POLY_CLOB_API_KEY", "test-api-key")
    monkeypatch.setenv("POLY_CLOB_API_SECRET", "dGVzdC1zZWNyZXQ=")
    monkeypatch.setenv("POLY_CLOB_API_PASSPHRASE", "test-passphrase")


class _MockClobRouter:
    """Stateful httpx.MockTransport backing py-clob-client HTTP requests."""

    def __init__(self, handler) -> None:
        self.requests: List[httpx.Request] = []
        self._handler = handler
        self.transport = httpx.MockTransport(self._dispatch)

    def _dispatch(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request, len(self.requests))

    @property
    def post_order_calls(self) -> List[httpx.Request]:
        return [r for r in self.requests if r.method == "POST" and r.url.path == "/order"]


def test_credentials_fail_closed_masking_and_gitignore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.execution.clob_credentials import (
        CredentialError,
        load_clob_credentials,
        resolve_live_startup_mode,
    )

    repo_root = Path(__file__).resolve().parents[3]
    git_ignore_proc = subprocess.run(
        ["git", "check-ignore", "-v", "config/credentials.local.yaml"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert git_ignore_proc.returncode == 0, "config/credentials.local.yaml must be gitignored"

    creds_file = tmp_path / "credentials.local.yaml"
    creds_file.write_text(
        "\n".join(
            [
                f'private_key: "{_TEST_PRIVATE_KEY}"',
                f'funder: "{_TEST_SIGNER_ADDR}"',
                "api_key: file-key",
                "api_secret: ZmlsZS1zZWNyZXQ=",
                "api_passphrase: file-pass",
                "signature_type: 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    loaded = load_clob_credentials(credentials_path=creds_file)
    assert loaded.api_key == "file-key"
    assert _TEST_PRIVATE_KEY not in repr(loaded)
    assert "ZmlsZS1zZWNyZXQ=" not in repr(loaded)
    assert loaded.redacted_dict()["private_key"] == "***REDACTED***"

    # Unquoted hex keys parsed by YAML as int must fail closed
    unquoted_file = tmp_path / "unquoted.local.yaml"
    unquoted_file.write_text(
        "\n".join(
            [
                f"private_key: {_TEST_PRIVATE_KEY}",
                f"funder: {_TEST_SIGNER_ADDR}",
                "api_key: file-key",
                "api_secret: ZmlsZS1zZWNyZXQ=",
                "api_passphrase: file-pass",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CredentialError):
        load_clob_credentials(credentials_path=unquoted_file)

    # Reject unexpected withdrawal/admin keys (least privilege enforcement)
    bad_file = tmp_path / "bad_creds.local.yaml"
    bad_file.write_text(
        creds_file.read_text(encoding="utf-8") + "withdraw_key: forbidden\n",
        encoding="utf-8",
    )
    with pytest.raises(CredentialError):
        load_clob_credentials(credentials_path=bad_file)

    # LIVE requested without creds or confirmation -> refuse LIVE, downgrade PAPER & alert
    alerts: List[str] = []
    decision = resolve_live_startup_mode(
        requested_mode="LIVE",
        confirmation_env_var="POLY_LIVE_CONFIRM",
        confirmation_expected_value="CONFIRM_LIVE",
        credentials_path=tmp_path / "missing.yaml",
        alert_callback=alerts.append,
    )
    assert decision.effective_mode == "PAPER"
    assert decision.downgraded_from_live is True
    assert len(alerts) == 1

    # With creds AND confirmation -> LIVE permitted
    _set_creds_env(monkeypatch)
    monkeypatch.setenv("POLY_LIVE_CONFIRM", "CONFIRM_LIVE")
    ok_decision = resolve_live_startup_mode(
        requested_mode="LIVE",
        confirmation_env_var="POLY_LIVE_CONFIRM",
        confirmation_expected_value="CONFIRM_LIVE",
        credentials_path=tmp_path / "missing.yaml",
        alert_callback=alerts.append,
    )
    assert ok_decision.effective_mode == "LIVE"
    assert ok_decision.credentials is not None


def test_sdk_eip712_signature_and_fak_full_fill_and_p3_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.execution.clob_gateway import ClobOrderGateway, EXPECTED_PY_CLOB_CLIENT_VERSION, LiveOrderRequest

    _set_creds_env(monkeypatch)
    monkeypatch.setenv("POLY_LIVE_CONFIRM", "CONFIRM_LIVE")
    cfg_path = _write_safety_config(tmp_path / "clob_gateway.yaml", execution_mode="LIVE")
    audit_root = tmp_path / "audit"
    ledger_path = tmp_path / "daily_usage.json"

    captured_payloads: List[Dict[str, Any]] = []

    def handler(request: httpx.Request, idx: int) -> httpx.Response:
        if request.url.path == "/tick-size":
            return httpx.Response(200, json={"minimum_tick_size": "0.01"})
        if request.url.path == "/neg-risk":
            return httpx.Response(200, json={"neg_risk": True})
        if request.url.path == "/fee-rate":
            return httpx.Response(200, json={"base_fee": 1000})
        if request.url.path == "/order" and request.method == "POST":
            body = json.loads(request.content.decode("utf-8"))
            captured_payloads.append(body)
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "orderID": "0xorder-full-001",
                    "status": "MATCHED",
                    "makingAmount": "4.000000",
                    "takingAmount": "10.000000",
                    "tradeIds": ["trade-1"],
                    "feeRate": "0.01",
                },
            )
        return httpx.Response(404, json={"error": "not_found"})

    router = _MockClobRouter(handler)
    with AsyncAuditLogger(audit_root, execution_mode="LIVE") as audit:
        gw = ClobOrderGateway(
            safety_config_path=cfg_path,
            audit_logger=audit,
            credentials_path=tmp_path / "none.yaml",
            daily_ledger_path=ledger_path,
            http_transport=router.transport,
            nonce_provider=lambda _ctx: 42,
        )
        assert gw.sdk_version == EXPECTED_PY_CLOB_CLIENT_VERSION == "0.34.6"
        res = gw.submit_order(
            LiveOrderRequest(
                context=_make_context(execution_mode="LIVE"),
                plan=_make_plan(shares=Decimal("10.00"), limit_price=Decimal("0.40")),
                tick_size=Decimal("0.01"),
                neg_risk=True,
                trading_config=_make_trading_config(),
                fee_rate=Decimal("0.01"),
                client_order_id="cid-full-001",
            )
        )
        audit.flush()

    assert res.terminal_status == "FILLED"
    assert res.filled_shares == Decimal("10.00")
    assert res.filled_usd == Decimal("4.0000")
    assert len(router.post_order_calls) == 1
    posted = captured_payloads[0]
    assert posted["orderType"] == "FAK"
    assert posted["order"]["signer"].lower() == _TEST_SIGNER_ADDR.lower()
    assert posted["order"]["nonce"] == "42"
    assert posted["order"]["signature"].startswith("0x") and len(posted["order"]["signature"]) == 132

    # Verify P3 JSONL contains pre-sign, request, response, and p3.v1 attempt and passes P10/P8 readers
    p3_file = audit_root / "LIVE" / "2026-11-22" / "p3_execution_attempts.jsonl"
    raw_scan = read_verified_jsonl_file(p3_file, verify_sha256=True)
    assert len(raw_scan.corrupt_lines) == 0
    stages = [r.get("stage") for r in raw_scan.records if r.get("schema_version") == "p3.gateway.v1"]
    assert "PRE_SIGN_SNAPSHOT" in stages
    assert "HTTP_REQUEST" in stages
    assert "HTTP_RESPONSE" in stages
    assert _TEST_PRIVATE_KEY not in p3_file.read_text(encoding="utf-8")

    view = query_p10_session_view(audit_root, P10Query(execution_mode="LIVE"))
    assert len(view.corrupt_lines) == 0
    assert any(r.get("terminal_status") == "FILLED" for r in view.p3_events)

    p8 = aggregate_p8_calibration_batch(
        audit_root,
        execution_mode="LIVE",
        window_start_utc=datetime(2026, 11, 22, 0, 0, tzinfo=timezone.utc),
        window_end_utc=datetime(2026, 11, 23, 0, 0, tzinfo=timezone.utc),
    )
    assert p8.n_slippage_fills == 1


def test_local_order_validations_and_cross_side_guard_block_before_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.execution.clob_gateway import ClobOrderGateway, LiveOrderRequest

    _set_creds_env(monkeypatch)
    monkeypatch.setenv("POLY_LIVE_CONFIRM", "CONFIRM_LIVE")
    cfg_path = _write_safety_config(tmp_path / "clob_gateway.yaml", execution_mode="LIVE")

    router = _MockClobRouter(lambda req, idx: httpx.Response(500, json={"unexpected": True}))
    with AsyncAuditLogger(tmp_path / "audit", execution_mode="LIVE") as audit:
        gw = ClobOrderGateway(
            safety_config_path=cfg_path,
            audit_logger=audit,
            credentials_path=tmp_path / "none.yaml",
            http_transport=router.transport,
        )
        # 1. Tick misalignment (0.405 with tick_size 0.01)
        r_tick = gw.submit_order(
            LiveOrderRequest(
                context=_make_context(decision_id="d-tick"),
                plan=_make_plan(shares=Decimal("10.00"), limit_price=Decimal("0.405")),
                tick_size=Decimal("0.01"),
                neg_risk=True,
                trading_config=_make_trading_config(),
            )
        )
        # 2. Below 5 shares
        r_min = gw.submit_order(
            LiveOrderRequest(
                context=_make_context(decision_id="d-min"),
                plan=_make_plan(shares=Decimal("4.99"), limit_price=Decimal("0.50")),
                tick_size=Decimal("0.01"),
                neg_risk=True,
                trading_config=_make_trading_config(),
            )
        )
        # 3. Missing neg_risk
        r_neg = gw.submit_order(
            LiveOrderRequest(
                context=_make_context(decision_id="d-neg"),
                plan=_make_plan(shares=Decimal("10.00"), limit_price=Decimal("0.50")),
                tick_size=Decimal("0.01"),
                neg_risk=False,
                trading_config=_make_trading_config(),
            )
        )
        # 4. Price > 0.99
        r_px = gw.submit_order(
            LiveOrderRequest(
                context=_make_context(decision_id="d-px"),
                plan=_make_plan(shares=Decimal("10.00"), limit_price=Decimal("0.995")),
                tick_size=Decimal("0.001"),
                neg_risk=True,
                trading_config=_make_trading_config(),
            )
        )
        # 5. Cross-side split routing safety lock in LIVE
        r_cross = gw.submit_order(
            LiveOrderRequest(
                context=_make_context(decision_id="d-cross"),
                plan=_make_plan(shares=Decimal("10.00"), limit_price=Decimal("0.50"), include_no_leg=True),
                tick_size=Decimal("0.01"),
                neg_risk=True,
                trading_config=_make_trading_config(enable_cross_side=False),
            )
        )
        audit.flush()

    assert all(r.terminal_status == "REJECTED" for r in (r_tick, r_min, r_neg, r_px, r_cross))
    assert r_cross.reject_or_abort_reason == "LIVE_CROSS_SIDE_SPLIT_DISABLED"
    assert len(router.requests) == 0


def test_fak_partial_fill_unfilled_reject_and_duplicate_callback_dedup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.execution.clob_gateway import ClobOrderGateway, LiveOrderRequest

    _set_creds_env(monkeypatch)
    monkeypatch.setenv("POLY_LIVE_CONFIRM", "CONFIRM_LIVE")
    cfg_path = _write_safety_config(tmp_path / "clob_gateway.yaml", execution_mode="LIVE")

    mode_seq = iter(["PARTIAL_DUP", "NO_MATCH_FAK", "HTTP_400_REJECT"])

    def handler(request: httpx.Request, _idx: int) -> httpx.Response:
        if request.url.path == "/tick-size":
            return httpx.Response(200, json={"minimum_tick_size": "0.001"})
        if request.url.path == "/neg-risk":
            return httpx.Response(200, json={"neg_risk": True})
        if request.url.path == "/fee-rate":
            return httpx.Response(200, json={"base_fee": 1000})
        if request.url.path == "/order":
            kind = next(mode_seq)
            if kind == "PARTIAL_DUP":
                # Duplicate fill/trade IDs reported in trades payload must NOT double-count
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "orderID": "0xorder-partial",
                        "status": "CANCELED",
                        "makingAmount": "2.500000",
                        "takingAmount": "5.000000",
                        "trades": [
                            {"id": "tr-1", "size": "5.00", "price": "0.50"},
                            {"id": "tr-1", "size": "5.00", "price": "0.50"},
                        ],
                    },
                )
            if kind == "NO_MATCH_FAK":
                return httpx.Response(
                    400,
                    json={"error": "no orders found to match with FAK order"},
                )
            return httpx.Response(400, json={"error": "Size lower than the minimum"})
        return httpx.Response(404)

    router = _MockClobRouter(handler)
    with AsyncAuditLogger(tmp_path / "audit", execution_mode="LIVE") as audit:
        gw = ClobOrderGateway(
            safety_config_path=cfg_path,
            audit_logger=audit,
            credentials_path=tmp_path / "none.yaml",
            http_transport=router.transport,
        )
        r_partial = gw.submit_order(
            LiveOrderRequest(
                context=_make_context(decision_id="d-part"),
                plan=_make_plan(shares=Decimal("10.00"), limit_price=Decimal("0.500")),
                tick_size=Decimal("0.001"),
                neg_risk=True,
                trading_config=_make_trading_config(),
            )
        )
        # Resubmitting same idempotency_key must deduplicate and never re-POST or double spend
        r_idem = gw.submit_order(
            LiveOrderRequest(
                context=_make_context(decision_id="d-part"),
                plan=_make_plan(shares=Decimal("10.00"), limit_price=Decimal("0.500")),
                tick_size=Decimal("0.001"),
                neg_risk=True,
                trading_config=_make_trading_config(),
            )
        )
        r_unfilled = gw.submit_order(
            LiveOrderRequest(
                context=_make_context(decision_id="d-unfilled"),
                plan=_make_plan(shares=Decimal("10.00"), limit_price=Decimal("0.400")),
                tick_size=Decimal("0.001"),
                neg_risk=True,
                trading_config=_make_trading_config(),
            )
        )
        r_reject = gw.submit_order(
            LiveOrderRequest(
                context=_make_context(decision_id="d-rej"),
                plan=_make_plan(shares=Decimal("10.00"), limit_price=Decimal("0.400")),
                tick_size=Decimal("0.001"),
                neg_risk=True,
                trading_config=_make_trading_config(),
            )
        )
        audit.flush()

    assert r_partial.terminal_status == "PARTIAL"
    assert r_partial.filled_shares == Decimal("5.00")
    assert r_partial.filled_usd == Decimal("2.5000")
    assert r_idem.filled_usd == Decimal("2.5000")
    assert gw.get_daily_used_usd(datetime(2026, 11, 22, tzinfo=timezone.utc).date()) == Decimal("2.5000")
    assert r_unfilled.terminal_status == "CANCELLED_UNFILLED"
    assert r_reject.terminal_status == "REJECTED"
    assert len(router.post_order_calls) == 3


def test_timeout_disconnect_lookup_before_retry_and_circuit_breaker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.execution.clob_gateway import ClobOrderGateway, LiveOrderRequest

    _set_creds_env(monkeypatch)
    monkeypatch.setenv("POLY_LIVE_CONFIRM", "CONFIRM_LIVE")
    cfg_path = _write_safety_config(
        tmp_path / "clob_gateway.yaml",
        execution_mode="LIVE",
        circuit_threshold=5,
        max_reconnect_attempts=2,
    )

    sleeps: List[float] = []
    alerts: List[str] = []
    scenario = {"mode": "READ_TIMEOUT_FOUND"}
    captured_nonces: List[str] = []

    def handler(request: httpx.Request, _idx: int) -> httpx.Response:
        if request.url.path == "/tick-size":
            return httpx.Response(200, json={"minimum_tick_size": "0.01"})
        if request.url.path == "/neg-risk":
            return httpx.Response(200, json={"neg_risk": True})
        if request.url.path == "/fee-rate":
            return httpx.Response(200, json={"base_fee": 1000})
        if request.url.path == "/order" and request.method == "POST":
            body = json.loads(request.content.decode("utf-8"))
            captured_nonces.append(str(body["order"]["nonce"]))
            if scenario["mode"] == "READ_TIMEOUT_FOUND":
                raise httpx.ReadTimeout("timed out after sending", request=request)
            if scenario["mode"] == "READ_TIMEOUT_ABSENT":
                raise httpx.RemoteProtocolError("server disconnected", request=request)
            raise httpx.ReadTimeout("persistent timeout", request=request)
        if request.url.path == "/data/orders":
            if scenario["mode"] == "READ_TIMEOUT_FOUND" and captured_nonces:
                return httpx.Response(
                    200,
                    json={
                        "next_cursor": "LTE=",
                        "data": [
                            {
                                "id": "0xreconciled-1",
                                "status": "MATCHED",
                                "nonce": captured_nonces[-1],
                                "size_matched": "10.00",
                                "price": "0.40",
                            }
                        ],
                    },
                )
            return httpx.Response(200, json={"next_cursor": "LTE=", "data": []})
        if request.url.path == "/data/trades":
            return httpx.Response(200, json={"next_cursor": "LTE=", "data": []})
        return httpx.Response(404)

    router = _MockClobRouter(handler)
    with AsyncAuditLogger(tmp_path / "audit", execution_mode="LIVE") as audit:
        gw = ClobOrderGateway(
            safety_config_path=cfg_path,
            audit_logger=audit,
            credentials_path=tmp_path / "none.yaml",
            http_transport=router.transport,
            sleep_fn=sleeps.append,
            alert_callback=alerts.append,
            nonce_provider=lambda ctx: abs(hash(ctx.decision_id)) % 100000,
        )
        # 1. Timeout where lookup finds the order already matched -> reconcile without duplicate POST
        r_found = gw.submit_order(
            LiveOrderRequest(
                context=_make_context(decision_id="d-to-found"),
                plan=_make_plan(shares=Decimal("10.00"), limit_price=Decimal("0.40")),
                tick_size=Decimal("0.01"),
                neg_risk=True,
                trading_config=_make_trading_config(),
            )
        )
        assert r_found.terminal_status == "FILLED"
        assert len(router.post_order_calls) == 1

        # 2. Ambiguous disconnect where lookup finds nothing -> fail closed (prefer miss over dup)
        scenario["mode"] = "READ_TIMEOUT_ABSENT"
        for i in range(5):
            r_miss = gw.submit_order(
                LiveOrderRequest(
                    context=_make_context(decision_id=f"d-miss-{i}"),
                    plan=_make_plan(shares=Decimal("10.00"), limit_price=Decimal("0.40")),
                    tick_size=Decimal("0.01"),
                    neg_risk=True,
                    trading_config=_make_trading_config(),
                )
            )
            assert r_miss.terminal_status == "REJECTED"

        # Should still have posted at most once per ambiguous attempt (no retry POSTs!)
        assert len(router.post_order_calls) == 6
        assert gw.circuit_open is True
        assert len(alerts) >= 1

        # 6th call blocked locally with zero HTTP requests until manual reset
        posts_before = len(router.post_order_calls)
        r_broken = gw.submit_order(
            LiveOrderRequest(
                context=_make_context(decision_id="d-broken"),
                plan=_make_plan(shares=Decimal("10.00"), limit_price=Decimal("0.40")),
                tick_size=Decimal("0.01"),
                neg_risk=True,
                trading_config=_make_trading_config(),
            )
        )
        assert r_broken.terminal_status == "REJECTED"
        assert r_broken.reject_or_abort_reason == "CIRCUIT_BREAKER_OPEN"
        assert len(router.post_order_calls) == posts_before

        # Manual reset restores operation
        gw.reset_circuit_breaker(operator="owner", reason="network restored")
        assert gw.circuit_open is False
        audit.flush()

    assert len(sleeps) >= 5


def test_dual_amount_gates_hot_reload_utc_rollover_and_paper_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.execution.clob_gateway import ClobOrderGateway, LiveOrderRequest

    _set_creds_env(monkeypatch)
    monkeypatch.setenv("POLY_LIVE_CONFIRM", "CONFIRM_LIVE")

    # 1. Structural PAPER test: transport is disabled and zero HTTP requests allowed
    cfg_paper = _write_safety_config(tmp_path / "paper.yaml", execution_mode="PAPER")
    router = _MockClobRouter(lambda req, idx: httpx.Response(200, json={}))
    with AsyncAuditLogger(tmp_path / "audit_paper", execution_mode="PAPER") as audit_p:
        gw_p = ClobOrderGateway(
            safety_config_path=cfg_paper,
            audit_logger=audit_p,
            credentials_path=tmp_path / "none.yaml",
            http_transport=router.transport,
        )
        assert gw_p.live_transport_enabled is False
        r_p = gw_p.submit_order(
            LiveOrderRequest(
                context=_make_context(decision_id="d-paper", execution_mode="PAPER"),
                plan=_make_plan(shares=Decimal("10.00"), limit_price=Decimal("0.40")),
                tick_size=Decimal("0.01"),
                neg_risk=True,
                trading_config=_make_trading_config(),
            )
        )
        audit_p.flush()
    assert r_p.terminal_status == "REJECTED"
    assert "PAPER" in (r_p.reject_or_abort_reason or "")
    assert len(router.requests) == 0

    # 2. Dual amount gates ($25 single / $250 UTC daily) + hot-reload without restart
    cfg_live = _write_safety_config(
        tmp_path / "live.yaml",
        execution_mode="LIVE",
        max_single_order_usd="25",
        max_daily_cumulative_usd="45",  # tight daily limit to exercise boundary cleanly
    )

    def ok_handler(request: httpx.Request, _idx: int) -> httpx.Response:
        if request.url.path == "/tick-size":
            return httpx.Response(200, json={"minimum_tick_size": "0.01"})
        if request.url.path == "/neg-risk":
            return httpx.Response(200, json={"neg_risk": True})
        if request.url.path == "/fee-rate":
            return httpx.Response(200, json={"base_fee": 1000})
        if request.url.path == "/order":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "orderID": "0xok",
                    "status": "MATCHED",
                    "makingAmount": "20.000000",
                    "takingAmount": "40.000000",
                },
            )
        return httpx.Response(404)

    live_router = _MockClobRouter(ok_handler)
    day1 = datetime(2026, 11, 22, 23, 55, tzinfo=timezone.utc)
    day2 = datetime(2026, 11, 23, 0, 5, tzinfo=timezone.utc)
    with AsyncAuditLogger(tmp_path / "audit_live", execution_mode="LIVE") as audit_l:
        gw_l = ClobOrderGateway(
            safety_config_path=cfg_live,
            audit_logger=audit_l,
            credentials_path=tmp_path / "none.yaml",
            http_transport=live_router.transport,
        )
        # > $25 single order rejected locally
        r_single = gw_l.submit_order(
            LiveOrderRequest(
                context=_make_context(decision_id="d-s1", submit_ts_utc=day1),
                plan=_make_plan(shares=Decimal("52.00"), limit_price=Decimal("0.50")),  # $26 > $25
                tick_size=Decimal("0.01"),
                neg_risk=True,
                trading_config=_make_trading_config(),
            )
        )
        assert r_single.reject_or_abort_reason == "SAFETY_GATE_SINGLE_ORDER_EXCEEDED"
        assert len(live_router.post_order_calls) == 0

        # Hot-reload: lower single cap to $18 -> $20 order now rejected immediately without restart
        _write_safety_config(
            cfg_live,
            execution_mode="LIVE",
            max_single_order_usd="18",
            max_daily_cumulative_usd="45",
        )
        r_hot = gw_l.submit_order(
            LiveOrderRequest(
                context=_make_context(decision_id="d-s2", submit_ts_utc=day1),
                plan=_make_plan(shares=Decimal("40.00"), limit_price=Decimal("0.50")),  # $20 > $18
                tick_size=Decimal("0.01"),
                neg_risk=True,
                trading_config=_make_trading_config(),
            )
        )
        assert r_hot.reject_or_abort_reason == "SAFETY_GATE_SINGLE_ORDER_EXCEEDED"

        # Raise single cap to $25, fill two $20 orders on day1 ($40 used); 3rd $20 hits $45 daily cap
        _write_safety_config(
            cfg_live,
            execution_mode="LIVE",
            max_single_order_usd="25",
            max_daily_cumulative_usd="45",
        )
        gw_l.submit_order(
            LiveOrderRequest(
                context=_make_context(decision_id="d-d1a", submit_ts_utc=day1),
                plan=_make_plan(shares=Decimal("40.00"), limit_price=Decimal("0.50")),
                tick_size=Decimal("0.01"),
                neg_risk=True,
                trading_config=_make_trading_config(),
            )
        )
        gw_l.submit_order(
            LiveOrderRequest(
                context=_make_context(decision_id="d-d1b", submit_ts_utc=day1),
                plan=_make_plan(shares=Decimal("40.00"), limit_price=Decimal("0.50")),
                tick_size=Decimal("0.01"),
                neg_risk=True,
                trading_config=_make_trading_config(),
            )
        )
        r_daily_block = gw_l.submit_order(
            LiveOrderRequest(
                context=_make_context(decision_id="d-d1c", submit_ts_utc=day1),
                plan=_make_plan(shares=Decimal("20.00"), limit_price=Decimal("0.50")),  # $40 + $10 > $45
                tick_size=Decimal("0.01"),
                neg_risk=True,
                trading_config=_make_trading_config(),
            )
        )
        assert r_daily_block.reject_or_abort_reason == "SAFETY_GATE_DAILY_LIMIT_EXCEEDED"

        # Next UTC day (00:05Z) resets daily allowance cleanly
        r_day2 = gw_l.submit_order(
            LiveOrderRequest(
                context=_make_context(decision_id="d-d2", submit_ts_utc=day2),
                plan=_make_plan(shares=Decimal("40.00"), limit_price=Decimal("0.50")),
                tick_size=Decimal("0.01"),
                neg_risk=True,
                trading_config=_make_trading_config(),
            )
        )
        assert r_day2.terminal_status == "FILLED"
        panel = gw_l.get_risk_panel_snapshot(
            utc_date=day2.date(),
            light_status="GREEN",
            model_hash="frozen-model-hash-abc",
            model_frozen=True,
        )
        assert panel.execution_mode == "LIVE"
        assert panel.daily_used_usd == Decimal("20.0000")
        assert panel.daily_remaining_usd == Decimal("25.0000")
        audit_l.flush()


def test_structural_four_invariants_across_repository() -> None:
    """Prove invariants i, iii, iv statically over src/ ASTs."""
    src_root = Path(__file__).resolve().parents[3] / "src"
    py_clob_importers: List[str] = []
    gateway_forbidden_imports: List[str] = []
    forbidden_prefixes = ("src.contract", "src.pricing", "src.prediction", "src.modeling")

    for py_file in sorted(src_root.rglob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        rel = py_file.relative_to(src_root.parent).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "py_clob_client" or alias.name.startswith("py_clob_client."):
                        py_clob_importers.append(rel)
                    if rel == "src/execution/clob_gateway.py" and alias.name.startswith(forbidden_prefixes):
                        gateway_forbidden_imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "py_clob_client" or node.module.startswith("py_clob_client."):
                    py_clob_importers.append(rel)
                if rel == "src/execution/clob_gateway.py" and node.module.startswith(forbidden_prefixes):
                    gateway_forbidden_imports.append(node.module)

    assert set(py_clob_importers) == {"src/execution/clob_gateway.py"}
    assert gateway_forbidden_imports == []


def test_pre_connect_reconnect_backoff_daily_ledger_persistence_and_mandatory_p3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify ConnectError retry after lookup, persistent UTC daily spend, and mandatory P3 logging."""
    from src.execution.clob_gateway import ClobOrderGateway, LiveOrderRequest

    _set_creds_env(monkeypatch)
    monkeypatch.setenv("POLY_LIVE_CONFIRM", "CONFIRM_LIVE")
    cfg_path = _write_safety_config(
        tmp_path / "clob_gateway.yaml",
        execution_mode="LIVE",
        max_single_order_usd="25",
        max_daily_cumulative_usd="30",
        max_reconnect_attempts=2,
    )
    ledger_path = tmp_path / "daily_usage.json"
    sleeps: List[float] = []
    post_attempts = {"n": 0}

    def handler(request: httpx.Request, _idx: int) -> httpx.Response:
        if request.url.path == "/tick-size":
            return httpx.Response(200, json={"minimum_tick_size": "0.01"})
        if request.url.path == "/neg-risk":
            return httpx.Response(200, json={"neg_risk": True})
        if request.url.path == "/fee-rate":
            return httpx.Response(200, json={"base_fee": 1000})
        if request.url.path == "/data/orders":
            return httpx.Response(200, json={"next_cursor": "LTE=", "data": []})
        if request.url.path == "/data/trades":
            return httpx.Response(200, json={"next_cursor": "LTE=", "data": []})
        if request.url.path == "/order" and request.method == "POST":
            post_attempts["n"] += 1
            if post_attempts["n"] == 1:
                raise httpx.ConnectError("pre-connect socket failure", request=request)
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "orderID": "0xreconnected",
                    "status": "MATCHED",
                    "makingAmount": "20.000000",
                    "takingAmount": "40.000000",
                },
            )
        return httpx.Response(404)

    router = _MockClobRouter(handler)
    with AsyncAuditLogger(tmp_path / "audit1", execution_mode="LIVE") as audit1:
        with pytest.raises(TypeError):
            ClobOrderGateway(safety_config_path=cfg_path, audit_logger=None)  # type: ignore[arg-type]

        gw1 = ClobOrderGateway(
            safety_config_path=cfg_path,
            audit_logger=audit1,
            credentials_path=tmp_path / "none.yaml",
            daily_ledger_path=ledger_path,
            http_transport=router.transport,
            sleep_fn=sleeps.append,
        )
        r_ok = gw1.submit_order(
            LiveOrderRequest(
                context=_make_context(decision_id="d-conn"),
                plan=_make_plan(shares=Decimal("40.00"), limit_price=Decimal("0.50")),
                tick_size=Decimal("0.01"),
                neg_risk=True,
                trading_config=_make_trading_config(),
            )
        )
        assert r_ok.terminal_status == "FILLED"
        assert post_attempts["n"] == 2
        assert len(sleeps) == 1
        audit1.flush()

    # Restarting gateway loads persisted UTC daily spend ($20 used -> $15 order exceeds $30 cap!)
    with AsyncAuditLogger(tmp_path / "audit2", execution_mode="LIVE") as audit2:
        gw2 = ClobOrderGateway(
            safety_config_path=cfg_path,
            audit_logger=audit2,
            credentials_path=tmp_path / "none.yaml",
            daily_ledger_path=ledger_path,
            http_transport=router.transport,
        )
        r_blocked = gw2.submit_order(
            LiveOrderRequest(
                context=_make_context(decision_id="d-after-restart"),
                plan=_make_plan(shares=Decimal("30.00"), limit_price=Decimal("0.50")),  # $15
                tick_size=Decimal("0.01"),
                neg_risk=True,
                trading_config=_make_trading_config(),
            )
        )
        assert r_blocked.reject_or_abort_reason == "SAFETY_GATE_DAILY_LIMIT_EXCEEDED"
        # Closed AsyncAuditLogger blocks submission fail-closed (Invariant ii)
        audit2.close()
        with pytest.raises(RuntimeError):
            gw2.submit_order(
                LiveOrderRequest(
                    context=_make_context(decision_id="d-closed-logger"),
                    plan=_make_plan(shares=Decimal("10.00"), limit_price=Decimal("0.50")),
                    tick_size=Decimal("0.01"),
                    neg_risk=True,
                    trading_config=_make_trading_config(),
                )
            )


def test_repo_default_gateway_config_and_fail_closed_missing_limits(tmp_path: Path) -> None:
    """Committed `configs/clob_gateway.yaml` defaults to PAPER + $25/$250 with zero code fallback."""
    from src.execution.clob_gateway import (
        DEFAULT_GATEWAY_CONFIG_PATH,
        GatewayConfigError,
        load_gateway_safety_config,
    )

    repo_root = Path(__file__).resolve().parents[3]
    real_cfg = load_gateway_safety_config(repo_root / DEFAULT_GATEWAY_CONFIG_PATH)
    assert real_cfg.execution_mode == "PAPER"
    assert real_cfg.max_single_order_usd == Decimal("25")
    assert real_cfg.max_daily_cumulative_usd == Decimal("250")
    assert real_cfg.min_order_size_shares == Decimal("5")
    assert real_cfg.max_limit_price == Decimal("0.99")
    assert real_cfg.circuit_breaker_failure_threshold == 5

    bad_cfg = tmp_path / "missing_cap.yaml"
    bad_cfg.write_text("execution_mode: PAPER\n", encoding="utf-8")
    with pytest.raises(GatewayConfigError):
        load_gateway_safety_config(bad_cfg)


