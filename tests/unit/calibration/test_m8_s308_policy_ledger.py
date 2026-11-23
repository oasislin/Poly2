"""TDD tests for `S3-08` (`M8` Parameter Ledger, `P6` Policy Issuer, Overdue Hold & `P16` Broadcaster)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest

from src.audit.audit_logger import AsyncAuditLogger
from src.audit.p10_reader import P10Query, query_p10_session_view
from src.audit.p8_aggregator import CalibrationAggregateBatch
from src.bankroll import BankrollAccountManager, BankrollConfig, TierStepUpEvent
from src.decision.engine import (
    DeterministicDecider,
    P16SubscriptionSlot,
    PhiPolicy,
    SigmaDeltaFrozen,
)
from src.execution.stub_generator import (
    build_p4_v11_stub_envelope,
    build_stub_forecast_v11,
    default_stub_trading_config,
)


def _base_ledger(now: datetime):
    from src.calibration.policy_ledger import ParameterLedgerEntry, PolicyParameterLedger

    return PolicyParameterLedger.create_initial_placeholder(
        policy_version="p6.v2-placeholder",
        created_ts_utc=now - timedelta(days=31),
        sigma_delta_frozen=SigmaDeltaFrozen(
            value=0.02,
            provenance="2019_OFFLINE_PRIOR",
            freeze_cycle_id="cycle-init",
        ),
        phi_policy=PhiPolicy(
            rho_0=Decimal("0.30"),
            k_slope=Decimal("0.0"),
            rho_min=Decimal("0.10"),
            rho_max=Decimal("0.50"),
        ),
        extra_metadata={"source": ParameterLedgerEntry(name="k0_threshold_coef", value=2.0, basis="P8-CAPITAL-CONFIG §7")},
    )


def test_ledger_covers_all_nine_entries_roundtrips_json_and_blocks_none_friction(tmp_path: Path) -> None:
    """`friction_median is None` blocks production `P6` signing; ledger roundtrips all 9 `§7` params."""
    from src.calibration.policy_ledger import (
        PolicyParameterLedger,
        PolicySigningBlockedError,
        issue_policy_bundle,
    )

    t0 = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)
    ledger = _base_ledger(t0)

    # All 9 P8-CAPITAL-CONFIG §7 entries are tracked explicitly
    assert set(ledger.entries.keys()) == {
        "k0_threshold_coef",
        "concurrent_days",
        "w0_intent",
        "p",
        "phi_policy",
        "scan_schedule",
        "friction_median",
        "platform_min_order",
        "yellow_multiplier",
    }
    assert ledger.friction_median is None

    ledger_path = tmp_path / "m8_policy_ledger.json"
    ledger.save(ledger_path)
    reloaded = PolicyParameterLedger.load(ledger_path)
    assert reloaded.to_dict() == ledger.to_dict()

    # Fail-Closed: production P6 signing is physically blocked while friction_median is None
    with pytest.raises(PolicySigningBlockedError, match="friction_median is None"):
        issue_policy_bundle(reloaded, signed_at_utc=t0, is_overdue=False)


def test_human_signoff_bumps_config_hash_and_rejects_p8_bypass_mutation(tmp_path: Path) -> None:
    """Layer 1 & 2: P8 aggregation emits read-only proposal only; human sign-off updates version & config_hash."""
    from src.calibration.policy_ledger import (
        build_monthly_review_proposal,
        issue_policy_bundle,
        sign_off_and_issue,
    )

    t0 = datetime(2026, 11, 27, 0, 15, 0, tzinfo=timezone.utc)
    ledger = _base_ledger(t0)
    batch = CalibrationAggregateBatch(
        window_start_utc=t0 - timedelta(days=30),
        window_end_utc=t0,
        execution_mode_filter="PAPER",
        model_hash="frozen-model-hash-v2",
        config_hash="placeholder",
        n_forecast_samples=75,
        sigma_delta_quantiles={"p50": 0.015, "p90": 0.032, "iqr_sigma": 0.018},
        empirical_slippage_vs_best_ask_median=0.012,
        n_slippage_fills=42,
        idle_rate_by_tau={"tau_ge_24h": 0.10, "tau_6h_24h": 0.05, "tau_lt_6h": 0.02},
        policy_overdue_ratio=0.0,
    )

    proposal = build_monthly_review_proposal(
        ledger=ledger,
        calibration_batch=batch,
        generated_ts_utc=t0,
        pooled_ece=0.014,
    )
    # Layer 1 never auto-mutates ledger parameters
    assert ledger.friction_median is None
    assert proposal.recommended_friction_median == pytest.approx(0.012)
    assert proposal.recommended_light_level == "GREEN"
    assert proposal.eligible_for_human_signoff is True

    # Layer 2 human sign-off updates friction_median -> produces valid P6 bundle & new config_hash
    updated_ledger, bundle_v1 = sign_off_and_issue(
        ledger=ledger,
        operator="owner-eric",
        rationale="S2-02 post-11-26 measured friction_median sign-off",
        new_policy_version="p6.v3",
        signed_at_utc=t0,
        friction_median=0.012,
    )
    assert updated_ledger.friction_median == pytest.approx(0.012)
    assert len(updated_ledger.replacement_history) == 1
    assert bundle_v1.policy_version == "p6.v3"
    assert bundle_v1.is_overdue is False
    assert bundle_v1.risk_gate.friction_median == pytest.approx(0.012)
    assert bundle_v1.risk_gate.yellow_multiplier == pytest.approx(0.5)

    # Re-issuing with different yellow_multiplier must change config_hash (`config_hash v2` invariant)
    ledger_y = updated_ledger.with_updated_yellow_multiplier(0.25, updated_ts_utc=t0, reason="test-y")
    bundle_y = issue_policy_bundle(ledger_y, signed_at_utc=t0, is_overdue=False)
    assert bundle_y.config_hash != bundle_v1.config_hash


def test_is_overdue_conservative_hold_preserves_frozen_params_across_m4_m6_m7(tmp_path: Path) -> None:
    """Layer 3 (`B6`): overdue bundle keeps exact frozen params/hash & marks `policy_overdue=True` in M7."""
    from src.calibration.policy_ledger import (
        build_overdue_hold_bundle,
        is_review_overdue,
        sign_off_and_issue,
    )

    t0 = datetime(2026, 11, 27, 0, 15, 0, tzinfo=timezone.utc)
    ledger = _base_ledger(t0)
    ledger_signed, bundle_ok = sign_off_and_issue(
        ledger=ledger,
        operator="owner-eric",
        rationale="initial D-A1 fill",
        new_policy_version="p6.v3",
        signed_at_utc=t0,
        friction_median=0.012,
    )
    t_overdue = t0 + timedelta(days=30, hours=1)
    assert is_review_overdue(ledger_signed, as_of_utc=t_overdue) is True

    hold = build_overdue_hold_bundle(
        ledger=ledger_signed,
        current_bundle=bundle_ok,
        as_of_utc=t_overdue,
    )
    assert hold.bundle.is_overdue is True
    assert hold.bundle.policy_version == bundle_ok.policy_version
    assert hold.bundle.config_hash == bundle_ok.config_hash
    assert hold.bundle.risk_gate == bundle_ok.risk_gate
    assert hold.bundle.w_policy == bundle_ok.w_policy
    assert hold.bundle.phi_policy == bundle_ok.phi_policy
    assert "OVERDUE" in hold.reminder_message.upper()

    # Downstream M4 + M6 keep operating conservatively without halt or shrink while logging policy_overdue=True
    with AsyncAuditLogger(tmp_path / "m7", execution_mode="PAPER") as audit_logger:
        mgr = BankrollAccountManager(
            BankrollConfig(
                session_id="sess-m8-overdue",
                execution_mode="PAPER",
                policy_version=hold.bundle.policy_version,
                config_hash=hold.bundle.config_hash,
                initial_pool_usd=Decimal("2000"),
                is_overdue=hold.bundle.is_overdue,
            ),
            audit_logger=audit_logger,
        )
        decider = DeterministicDecider(exec_config=default_stub_trading_config())
        fc = build_stub_forecast_v11(
            target_date_str="2026-12-27",
            issue_ts_utc=t_overdue - timedelta(minutes=10),
            settle_close_utc=t_overdue + timedelta(hours=10),
        )
        yf = build_p4_v11_stub_envelope(
            session_id="sess-m8-overdue",
            seq_id=1,
            frame_seq=1,
            token_id="tok-ov",
            market_id="mkt-ov",
            condition_id="cond-ov",
            station_id="KORD",
            target_date="2026-12-27",
            bin_label="58-59°F",
            outcome="YES",
            regime="two_sided",
            recv_ts_utc=t_overdue - timedelta(seconds=1),
            asks=((0.25, 200.0),),
            bids=((0.24, 200.0),),
        )[0].payload
        ev = decider.evaluate_bin(
            orig_session_id="sess-m8-overdue",
            execution_mode="PAPER",
            scan_clock="PRICE_CLOCK",
            scan_ts_utc=t_overdue,
            station_id="KORD",
            target_date="2026-12-27",
            bin_id="bin-58-59",
            market_id="mkt-ov",
            yes_token_id="tok-ov",
            forecasts=[fc],
            policy_bundle=hold.bundle,
            quota_provider=mgr,
            yes_frame=yf,
            include_no_side=False,
        )
        audit_logger.log_p1_scan_decision(ev)
        audit_logger.flush()

    assert ev.policy_overdue is True
    assert ev.decision_outcome == "ORDERED"
    view = query_p10_session_view(tmp_path / "m7", P10Query(execution_mode="PAPER", date_range=(t_overdue.date(), t_overdue.date())))
    assert len(view.p1_events) == 1
    assert view.p1_events[0]["policy_overdue"] is True


def test_p16_dual_broadcaster_reaches_m4_and_m6_with_typed_reasons_and_a1_isolation(tmp_path: Path) -> None:
    """`P16Broadcaster` delivers light & step-up events to both `M4` and `M6`, rejecting untyped YELLOW."""
    from src.calibration.policy_ledger import P16Broadcaster

    t0 = datetime(2026, 11, 27, 1, 0, 0, tzinfo=timezone.utc)
    slot = P16SubscriptionSlot()
    step_events: list[TierStepUpEvent] = []

    with AsyncAuditLogger(tmp_path / "m7", execution_mode="PAPER") as audit_logger:
        mgr = BankrollAccountManager(
            BankrollConfig(
                session_id="sess-p16",
                execution_mode="PAPER",
                policy_version="p6.v3",
                config_hash="cfg-hash-v3",
                initial_pool_usd=Decimal("2000"),
                full_deployment=False,
            ),
            audit_logger=audit_logger,
        )
        broadcaster = P16Broadcaster(
            m4_slot=slot,
            m6_bankroll=mgr,
            extra_step_up_listeners=[step_events.append],
        )

        # Untyped YELLOW reason forbidden per D-6 §五
        with pytest.raises(ValueError, match="YELLOW"):
            broadcaster.broadcast_light_level(
                event_id="p16-bad-yellow",
                level="YELLOW",
                reason="ARBITRARY_REASON",
                emitted_ts_utc=t0,
            )

        ev_yellow = broadcaster.broadcast_light_level(
            event_id="p16-y1",
            level="YELLOW",
            reason="YELLOW_MILD_CALIBRATION_DRIFT",
            emitted_ts_utc=t0,
        )
        assert slot.latest_event == ev_yellow
        assert mgr.snapshot_state().light_status == "YELLOW"

        ev_red = broadcaster.broadcast_light_level(
            event_id="p16-r1",
            level="RED",
            reason="RED_ECE_GT_0_040",
            emitted_ts_utc=t0 + timedelta(minutes=1),
        )
        assert slot.latest_event == ev_red
        assert mgr.snapshot_state().light_status == "RED"

        # TierStepUpEvent activates M6 drawdown brake on +$1,000 tier step-up
        step = broadcaster.broadcast_tier_step_up(
            event_id="p16-step-1",
            added_usd=Decimal("1000"),
            new_tier_pool_usd=Decimal("3000"),
            emitted_ts_utc=t0 + timedelta(minutes=2),
            reason="TWO_CONSECUTIVE_GREEN_MONTHS",
        )
        assert step_events == [step]
        snap = mgr.snapshot_state()
        assert snap.tier_pool_usd == Decimal("3000")
        assert snap.drawdown_brake_enabled is True
        audit_logger.flush()

    view = query_p10_session_view(tmp_path / "m7", P10Query(execution_mode="PAPER", date_range=(t0.date(), t0.date())))
    assert [e["event_type"] for e in view.p19_events] == [
        "LIGHT_LEVEL_APPLIED",
        "LIGHT_LEVEL_APPLIED",
        "TIER_STEP_UP",
    ]
