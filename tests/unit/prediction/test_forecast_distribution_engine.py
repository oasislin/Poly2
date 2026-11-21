"""Unit and P5 v1.1 four-invariant self-certification tests for M2 (S3-02)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
import math
from pathlib import Path
import random
from typing import Dict, List

import pytest
from scipy import stats

from src.data_acquisition.settlement_metar_stream import FreshnessPolicy, StationDayState
from src.modeling.gaussian_emos import GaussianEMOS
from src.prediction.discrete_bin_engine import DiscreteBinEngine
from src.prediction.dynamic_corrector import (
    MuRResult,
    Proposal1CoolingDriftMuRHook,
    SpecV2BaselineMuRHook,
    TruncatedDistribution,
)
from src.prediction.forecast_distribution_engine import (
    ASOS_PRT_INSTRUMENT_FLOOR_F,
    BinLadderValidationError,
    CalibrationJsonEtaProvider,
    CausalInputError,
    ConstantEtaProvider,
    ForecastDistributionEngine,
    IntegerBinSpec,
    PriorAffineFamilyModel,
    UnsupportedPriorFamilyError,
    build_integer_bin_ladder,
    compute_sigma_rem,
    select_latest_p11_state,
    validate_contiguous_bin_ladder,
    validate_p5_v11_invariants,
    verify_p17_json_line,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
ETA_CALIBRATION_PATH = REPO_ROOT / "evidence/p8_inspection_a_eta_s_calibration_20261113.json"


def _dt(iso_str: str) -> datetime:
    return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))


def _make_p11(
    *,
    station_id: str = "KORD",
    target_date: date = date(2026, 7, 15),
    as_of: str = "2026-07-15T18:00:00Z",
    latest_obs: str = "2026-07-15T17:51:00Z",
    latest_disp: str = "2026-07-15T17:54:00Z",
    m_now_exact_f: Decimal = Decimal("70.2"),
    m_now_int_f: int = 70,
    instant_temp_f: Decimal = Decimal("70.2"),
    oracle_compliant: bool = True,
    freshness_ok: bool = True,
) -> StationDayState:
    as_of_dt = _dt(as_of)
    obs_dt = _dt(latest_obs)
    disp_dt = _dt(latest_disp)
    return StationDayState(
        schema_version="p11.v1",
        state_id=f"st-{as_of}",
        as_of_ts_utc=as_of_dt,
        station_id=station_id,
        station_timezone="America/Chicago",
        target_date=target_date,
        day_start_utc=_dt("2026-07-15T05:00:00Z"),
        settle_close_utc=_dt("2026-07-16T05:00:00Z"),
        m_now_exact_f=m_now_exact_f,
        m_now_int_f=m_now_int_f,
        m_now_min_exact_f=m_now_exact_f,
        m_now_min_int_f=m_now_int_f,
        oracle_compliant=oracle_compliant,
        oracle_source_tier="AWC_METAR_TGROUP",
        latest_obs_utc=obs_dt,
        latest_dispatch_ts_utc=disp_dt,
        latest_instant_temp_f=instant_temp_f,
        physical_age_sec=(as_of_dt - obs_dt).total_seconds(),
        dispatch_age_sec=(as_of_dt - disp_dt).total_seconds(),
        dispatch_age_available=True,
        freshness_ok=freshness_ok,
        freshness_policy_provenance="TEST_POLICY",
        routine_obs_count=10,
        cor_overwrites_count=0,
        specis_seen_count=0,
        gap_flags=(),
    )


def _fresh_policy() -> FreshnessPolicy:
    return FreshnessPolicy(
        physical_age_limit_sec=5400.0,
        dispatch_age_limit_sec=3600.0,
        require_dispatch_age=True,
        provenance="TEST_M1_M2_FRESHNESS",
    )


def _evt_params() -> Dict[str, object]:
    return {
        "u_left": -1.643026466211049,
        "u_right": 1.548456145295596,
        "gpd_left": {"shape_xi": -0.09400616603981649, "scale_beta": 0.8465415249694024},
        "gpd_right": {"shape_xi": -0.12707424539336076, "scale_beta": 0.7254494892968121},
    }


def _jsu_params() -> Dict[str, float]:
    return {
        "gamma": -0.5456128894365957,
        "delta": 2.219244232534535,
        "xi": -0.5252050824607046,
        "lambda": 1.9238040450179095,
    }


def test_prior_affine_three_families_match_reference_and_reject_invalid() -> None:
    mu0, sigma0 = 75.0, 4.2
    xs = [55.0, 65.0, 70.0, 75.0, 80.0, 90.0]

    # 1. Gaussian
    m_g = PriorAffineFamilyModel(family="gaussian", mu0=mu0, sigma0=sigma0)
    for x in xs:
        assert math.isclose(m_g.cdf(x), float(stats.norm.cdf((x - mu0) / sigma0)), abs_tol=1e-12)

    # 2. Johnson SU
    jsu = _jsu_params()
    m_j = PriorAffineFamilyModel(family="johnsonsu", mu0=mu0, sigma0=sigma0, shape_params=jsu)
    for x in xs:
        z = (x - mu0) / sigma0
        ref = float(stats.johnsonsu.cdf(z, jsu["gamma"], jsu["delta"], loc=jsu["xi"], scale=jsu["lambda"]))
        assert math.isclose(m_j.cdf(x), ref, abs_tol=1e-12)

    # 3. EVT Hybrid
    evt = _evt_params()
    m_e = PriorAffineFamilyModel(family="evt_hybrid", mu0=mu0, sigma0=sigma0, shape_params=evt)
    vals = [m_e.cdf(x) for x in xs]
    assert all(0.0 <= vals[i] <= vals[i + 1] <= 1.0 for i in range(len(vals) - 1))
    assert m_e.cdf(-math.inf) == 0.0
    assert m_e.cdf(math.inf) == 1.0

    with pytest.raises(UnsupportedPriorFamilyError):
        PriorAffineFamilyModel(family="student_t", mu0=mu0, sigma0=sigma0)  # type: ignore[arg-type]


def test_contiguous_bin_ladder_guard_rejects_gaps_overlaps_and_floats() -> None:
    ladder = build_integer_bin_ladder(first_interior_start_f=68, num_interior_bins=4, bin_width_f=2)
    assert [(b.lower_int_f, b.upper_int_f) for b in ladder] == [
        (None, 67),
        (68, 69),
        (70, 71),
        (72, 73),
        (74, 75),
        (76, None),
    ]
    validate_contiguous_bin_ladder(ladder)

    # Reject float/half-degree boundary
    with pytest.raises(BinLadderValidationError, match="no floats/half-degrees"):
        IntegerBinSpec("bad", "bad", 68.5, 70.5)  # type: ignore[arg-type]

    # Reject 1-degree gap between bins
    with pytest.raises(BinLadderValidationError, match="Discontiguous"):
        validate_contiguous_bin_ladder(
            [
                IntegerBinSpec("le_67", "<=67", None, 67),
                IntegerBinSpec("69_70", "69-70", 69, 70),  # 68 missing!
                IntegerBinSpec("ge_71", ">=71", 71, None),
            ]
        )

    # Reject overlapping bins
    with pytest.raises(BinLadderValidationError, match="Discontiguous"):
        validate_contiguous_bin_ladder(
            [
                IntegerBinSpec("le_68", "<=68", None, 68),
                IntegerBinSpec("68_69", "68-69", 68, 69),  # overlaps 68!
                IntegerBinSpec("ge_70", ">=70", 70, None),
            ]
        )

    # Reject missing open tail
    with pytest.raises(BinLadderValidationError, match="upper-open"):
        validate_contiguous_bin_ladder(
            [
                IntegerBinSpec("le_67", "<=67", None, 67),
                IntegerBinSpec("68_69", "68-69", 68, 69),
            ]
        )


def test_p11_latest_wins_no_rollback_and_m1_to_m2_freshness_gate() -> None:
    engine = ForecastDistributionEngine(
        freshness_policy=_fresh_policy(),
        eta_provider=ConstantEtaProvider(eta_s=0.35, provenance="TEST_ETA_035"),
        mu_r_hook=SpecV2BaselineMuRHook(),
    )
    ladder = build_integer_bin_ladder(first_interior_start_f=68, num_interior_bins=4, bin_width_f=2)
    prior = PriorAffineFamilyModel(family="johnsonsu", mu0=73.0, sigma0=3.5, shape_params=_jsu_params())

    # 1. History contains fresh compliant state at 17:00Z, stale/uncompliant later state at 18:00Z,
    #    and future state at 19:00Z relative to issue_ts_utc=18:10Z.
    p11_old_fresh = _make_p11(
        as_of="2026-07-15T17:00:00Z",
        latest_obs="2026-07-15T16:51:00Z",
        latest_disp="2026-07-15T16:54:00Z",
        m_now_exact_f=Decimal("69.0"),
        m_now_int_f=69,
        freshness_ok=True,
    )
    p11_latest_stale = _make_p11(
        as_of="2026-07-15T18:00:00Z",
        latest_obs="2026-07-15T15:00:00Z",
        latest_disp="2026-07-15T15:05:00Z",
        m_now_exact_f=Decimal("71.0"),
        m_now_int_f=71,
        freshness_ok=False,
    )
    p11_future = _make_p11(
        as_of="2026-07-15T19:00:00Z",
        latest_obs="2026-07-15T18:51:00Z",
        latest_disp="2026-07-15T18:54:00Z",
        m_now_exact_f=Decimal("74.0"),
        m_now_int_f=74,
        freshness_ok=True,
    )

    winning = select_latest_p11_state(
        [p11_old_fresh, p11_latest_stale, p11_future],
        station_id="KORD",
        target_date=date(2026, 7, 15),
        as_of_ts_utc=_dt("2026-07-15T18:10:00Z"),
    )
    assert winning == p11_latest_stale

    # M2 MUST NOT roll back to p11_old_fresh! Degrades cleanly to Prior with p_stay_phys=p_bin_stay=None
    snap, rep = engine.build_snapshot(
        station_id="KORD",
        target_date=date(2026, 7, 15),
        target_type="TMAX",
        issue_ts_utc=_dt("2026-07-15T18:10:00Z"),
        settle_close_utc=_dt("2026-07-16T05:00:00Z"),
        gefs_lead_hours=18,
        model_hash="model_v1",
        prior=prior,
        bins=ladder,
        p11_history=[p11_old_fresh, p11_latest_stale, p11_future],
    )
    assert snap.upstream_obs_fresh is False
    assert snap.is_bridge_active is False
    assert snap.p_stay_phys is None
    assert snap.p_bin_stay is None
    assert snap.bin_probs[0].p_model > 0.0  # prior does NOT force dead bins to 0
    assert rep.all_passed is True

    # 2. Direct passing of a future P11 raises CausalInputError fail-closed
    with pytest.raises(CausalInputError, match="exceeds M2 issue_ts_utc"):
        engine.build_snapshot(
            station_id="KORD",
            target_date=date(2026, 7, 15),
            target_type="TMAX",
            issue_ts_utc=_dt("2026-07-15T18:10:00Z"),
            settle_close_utc=_dt("2026-07-16T05:00:00Z"),
            gefs_lead_hours=18,
            model_hash="model_v1",
            prior=prior,
            bins=ladder,
            p11_state=p11_future,
        )

    # 3. Age re-check at issue_ts_utc catches P11 whose own as_of was fresh but aged by issue_ts
    snap_aged, rep_aged = engine.build_snapshot(
        station_id="KORD",
        target_date=date(2026, 7, 15),
        target_type="TMAX",
        issue_ts_utc=_dt("2026-07-15T18:45:00Z"),  # latest_obs 16:51 -> 114m > 90m limit!
        settle_close_utc=_dt("2026-07-16T05:00:00Z"),
        gefs_lead_hours=18,
        model_hash="model_v1",
        prior=prior,
        bins=ladder,
        p11_state=p11_old_fresh,
    )
    assert snap_aged.upstream_obs_fresh is False
    assert snap_aged.is_bridge_active is False
    assert rep_aged.all_passed is True


def test_dual_p_stay_split_interior_exact_half_tie_negative_and_open_tail() -> None:
    """Verify P5 v1.1 dual fields across half-degree ties, negative temps, and open tails."""
    engine = ForecastDistributionEngine(
        freshness_policy=_fresh_policy(),
        eta_provider=ConstantEtaProvider(eta_s=0.01, provenance="TEST_LATE_DAY"),
        mu_r_hook=SpecV2BaselineMuRHook(),
    )
    # 1. sigma_rem honors 0.9°F instrument floor even when sigma0 * sqrt(eta_s) = 3.0 * 0.1 = 0.3
    assert compute_sigma_rem(3.0, 0.01) == ASOS_PRT_INSTRUMENT_FLOOR_F

    ladder = build_integer_bin_ladder(first_interior_start_f=68, num_interior_bins=4, bin_width_f=2)
    prior = PriorAffineFamilyModel(family="gaussian", mu0=73.0, sigma0=3.0)

    # Case A: exact .5°F tie on left boundary of interior bin [68, 69] (68.5°F -> 69 in [68,69],
    # WAIT: use 69.5°F -> 70 in [70, 71], while dead bin [68, 69] stops cleanly at 69.5!)
    p11_tie = _make_p11(
        as_of="2026-07-15T18:00:00Z",
        latest_obs="2026-07-15T17:51:00Z",
        latest_disp="2026-07-15T17:54:00Z",
        m_now_exact_f=Decimal("69.5"),
        m_now_int_f=70,
        instant_temp_f=Decimal("69.5"),
    )
    snap_tie, rep_tie = engine.build_snapshot(
        station_id="KORD",
        target_date=date(2026, 7, 15),
        target_type="TMAX",
        issue_ts_utc=_dt("2026-07-15T18:00:00Z"),
        settle_close_utc=_dt("2026-07-16T05:00:00Z"),
        gefs_lead_hours=18,
        model_hash="model_v1",
        prior=prior,
        bins=ladder,
        p11_state=p11_tie,
    )
    assert rep_tie.all_passed is True
    assert snap_tie.bin_probs[0].p_model == 0.0  # <=67
    assert snap_tie.bin_probs[1].p_model == 0.0  # 68-69 dead even at m_now=69.5 exact tie!
    assert snap_tie.p_stay_phys is not None and snap_tie.p_bin_stay is not None
    assert snap_tie.bin_probs[2].bin_id == "70-71F"
    assert snap_tie.bin_probs[2].p_model == snap_tie.p_bin_stay > snap_tie.p_stay_phys
    assert math.isclose(sum(b.p_model for b in snap_tie.bin_probs), 1.0, abs_tol=1e-12)

    # Case B: Open upper tail [76, +inf): p_bin_stay == 1.0 while p_stay_phys remains unclipped < 1.0!
    prior_warm = PriorAffineFamilyModel(family="gaussian", mu0=80.0, sigma0=4.0)
    p11_tail = _make_p11(
        as_of="2026-07-15T18:00:00Z",
        latest_obs="2026-07-15T17:51:00Z",
        latest_disp="2026-07-15T17:54:00Z",
        m_now_exact_f=Decimal("76.2"),
        m_now_int_f=76,
        instant_temp_f=Decimal("76.2"),
    )
    snap_tail, rep_tail = engine.build_snapshot(
        station_id="KORD",
        target_date=date(2026, 7, 15),
        target_type="TMAX",
        issue_ts_utc=_dt("2026-07-15T18:00:00Z"),
        settle_close_utc=_dt("2026-07-16T05:00:00Z"),
        gefs_lead_hours=18,
        model_hash="model_v1",
        prior=prior_warm,
        bins=ladder,
        p11_state=p11_tail,
    )
    assert rep_tail.all_passed is True
    assert rep_tail.boundary_is_open_tail is True
    assert snap_tail.p_bin_stay == 1.0
    assert snap_tail.bin_probs[-1].p_model == 1.0
    assert snap_tail.p_stay_phys is not None
    assert 0.0 < snap_tail.p_stay_phys < 0.5  # mu_r > 0 -> unclipped atom strictly < 0.5 and != 1.0!

    # Case C: Negative exact half-degree tie (-22.5°C = -8.5°F -> -8°F) on integer ladder
    neg_ladder = build_integer_bin_ladder(first_interior_start_f=-10, num_interior_bins=4, bin_width_f=2)
    prior_cold = PriorAffineFamilyModel(family="gaussian", mu0=-5.0, sigma0=3.0)
    p11_neg = _make_p11(
        as_of="2026-01-15T18:00:00Z",
        latest_obs="2026-01-15T17:51:00Z",
        latest_disp="2026-01-15T17:54:00Z",
        target_date=date(2026, 1, 15),
        m_now_exact_f=Decimal("-8.5"),
        m_now_int_f=-8,
        instant_temp_f=Decimal("-8.5"),
    )
    snap_neg, rep_neg = engine.build_snapshot(
        station_id="KORD",
        target_date=date(2026, 1, 15),
        target_type="TMAX",
        issue_ts_utc=_dt("2026-01-15T18:00:00Z"),
        settle_close_utc=_dt("2026-01-16T06:00:00Z"),
        gefs_lead_hours=18,
        model_hash="model_v1",
        prior=prior_cold,
        bins=neg_ladder,
        p11_state=p11_neg,
    )
    assert rep_neg.all_passed is True
    assert snap_neg.bin_probs[0].p_model == 0.0  # <= -11 dead
    assert snap_neg.bin_probs[1].p_model == 0.0  # [-10, -9] dead! -8.5°F belongs to -8 in [-8, -7]
    assert snap_neg.bin_probs[2].bin_id == "-8--7F"
    assert snap_neg.bin_probs[2].p_model == snap_neg.p_bin_stay > snap_neg.p_stay_phys


def test_calibrated_eta_evidence_loader_and_tmin_remains_unimplemented_until_w3() -> None:
    eta_provider = CalibrationJsonEtaProvider.from_json(ETA_CALIBRATION_PATH)
    eta_val = eta_provider.get_eta_s(station_id="KORD", season="Winter", t_local_hour=12.0)
    assert 0.0 < eta_val <= 1.0

    # CoolingDriftMuRHook injection works seamlessly for TMAX and allows negative mu_r
    p1_hook = Proposal1CoolingDriftMuRHook(curves={})
    engine = ForecastDistributionEngine(
        freshness_policy=_fresh_policy(),
        eta_provider=eta_provider,
        mu_r_hook=p1_hook,
    )
    ladder = build_integer_bin_ladder(first_interior_start_f=34, num_interior_bins=5, bin_width_f=2)
    prior = PriorAffineFamilyModel(family="evt_hybrid", mu0=38.0, sigma0=4.5, shape_params=_evt_params())
    p11_winter = _make_p11(
        target_date=date(2026, 1, 15),
        as_of="2026-01-15T19:00:00Z",
        latest_obs="2026-01-15T18:51:00Z",
        latest_disp="2026-01-15T18:54:00Z",
        m_now_exact_f=Decimal("37.0"),
        m_now_int_f=37,
    )
    snap, rep = engine.build_snapshot(
        station_id="KORD",
        target_date=date(2026, 1, 15),
        target_type="TMAX",
        issue_ts_utc=_dt("2026-01-15T19:00:00Z"),
        settle_close_utc=_dt("2026-01-16T06:00:00Z"),
        gefs_lead_hours=18,
        model_hash="model_v1",
        prior=prior,
        bins=ladder,
        p11_state=p11_winter,
    )
    assert rep.all_passed is True
    assert snap.family == "evt_hybrid"

    # Prior-only TMIN works cleanly without touching MuRHook
    snap_tmin_prior, rep_tmin_prior = engine.build_snapshot(
        station_id="KORD",
        target_date=date(2026, 1, 15),
        target_type="TMIN",
        issue_ts_utc=_dt("2026-01-15T19:00:00Z"),
        settle_close_utc=_dt("2026-01-16T06:00:00Z"),
        gefs_lead_hours=18,
        model_hash="model_v1",
        prior=prior,
        bins=ladder,
        p11_state=None,
    )
    assert snap_tmin_prior.is_bridge_active is False
    assert rep_tmin_prior.all_passed is True

    # Active bridge on TMIN MUST still raise NotImplementedError until W3 calibration
    with pytest.raises(NotImplementedError, match="W3"):
        engine.build_snapshot(
            station_id="KORD",
            target_date=date(2026, 1, 15),
            target_type="TMIN",
            issue_ts_utc=_dt("2026-01-15T19:00:00Z"),
            settle_close_utc=_dt("2026-01-16T06:00:00Z"),
            gefs_lead_hours=18,
            model_hash="model_v1",
            prior=prior,
            bins=ladder,
            p11_state=p11_winter,
        )


def test_p17_jsonl_serialization_and_120_case_p5_four_invariant_certification() -> None:
    """Comprehensive deterministic Monte Carlo self-certification of P5 v1.1 across 120 states."""
    rng = random.Random(20261121)
    families: List[PriorAffineFamilyModel] = [
        PriorAffineFamilyModel(family="gaussian", mu0=74.0, sigma0=4.0),
        PriorAffineFamilyModel(family="johnsonsu", mu0=74.0, sigma0=4.0, shape_params=_jsu_params()),
        PriorAffineFamilyModel(family="evt_hybrid", mu0=74.0, sigma0=4.0, shape_params=_evt_params()),
    ]
    ladder = build_integer_bin_ladder(first_interior_start_f=68, num_interior_bins=5, bin_width_f=2)

    tail_cases = 0
    interior_cases = 0
    prior_cases = 0
    last_snapshot = None

    for i in range(120):
        prior_base = families[i % 3]
        prior = PriorAffineFamilyModel(
            family=prior_base.family,
            mu0=rng.uniform(64.0, 84.0),
            sigma0=rng.uniform(0.7, 7.5),
            shape_params=prior_base.shape_params,
        )
        eta_val = rng.uniform(0.05, 1.0)
        eng = ForecastDistributionEngine(
            freshness_policy=_fresh_policy(),
            eta_provider=ConstantEtaProvider(eta_s=eta_val, provenance=f"MC_ETA_{i}"),
            mu_r_hook=SpecV2BaselineMuRHook(),
        )

        # Mix prior-only (every 6th), exact .5 ties, interior points, and lower/upper open tails
        if i % 6 == 0:
            p11 = None
            prior_cases += 1
        else:
            if i % 5 == 1:
                m_dec = Decimal(str(rng.choice([67.5, 69.5, 71.5, 73.5, 75.5, 77.5])))
            elif i % 5 == 2:
                m_dec = Decimal(str(rng.choice([65.0, 78.0, 81.5])))
            else:
                m_dec = Decimal(f"{rng.uniform(66.0, 80.0):.1f}")
            m_int = int(math.floor(float(m_dec) + 0.5))
            p11 = _make_p11(
                as_of="2026-07-15T18:00:00Z",
                latest_obs="2026-07-15T17:51:00Z",
                latest_disp="2026-07-15T17:54:00Z",
                m_now_exact_f=m_dec,
                m_now_int_f=m_int,
            )

        hour_utc = rng.choice([12, 15, 18, 21])
        issue_ts = _dt(f"2026-07-15T{hour_utc:02d}:00:00Z")
        snap, rep = eng.build_snapshot(
            station_id="KORD",
            target_date=date(2026, 7, 15),
            target_type="TMAX",
            issue_ts_utc=issue_ts,
            settle_close_utc=_dt("2026-07-16T05:00:00Z"),
            gefs_lead_hours=18,
            model_hash="model_mc_v1",
            prior=prior,
            bins=ladder,
            p11_state=p11 if (p11 is None or p11.as_of_ts_utc <= issue_ts) else None,
            sigma_delta_sample=1.1,
        )
        assert rep.all_passed is True, f"Case {i} failed: {rep.failures}"
        if snap.is_bridge_active:
            assert snap.p_stay_phys is not None and snap.p_bin_stay is not None
            if rep.boundary_is_open_tail:
                assert snap.p_bin_stay == 1.0
                tail_cases += 1
            else:
                assert snap.p_bin_stay >= snap.p_stay_phys
                interior_cases += 1
        last_snapshot = snap

    assert prior_cases > 0 and interior_cases > 0 and tail_cases > 0
    assert last_snapshot is not None
    # P17 JSONL + SHA256 integrity
    p17_line = last_snapshot.to_p17_json_line(
        session_id="sess-m2-p17",
        execution_mode="PAPER",
        config_hash="cfg_v1",
    )
    assert verify_p17_json_line(p17_line) is True
    p17_obj = json.loads(p17_line)
    assert p17_obj["schema_version"] == "p17.v1"
    assert "p5_schema_version" not in p17_obj
    # No .5°F fields anywhere in bin_probs
    assert all("lower_bound_f" not in b and "upper_bound_f" not in b for b in p17_obj["bin_probs"])
    assert isinstance(p17_obj["bin_probs"][1]["lower_int_f"], int)
    assert validate_p5_v11_invariants(last_snapshot).all_passed is True


def test_tmin_stale_p11_uses_tmin_extreme_not_tmax() -> None:
    """Spec (c)(1) fix: TMIN with stale P11 must use `m_now_min_*`, never `m_now_*` (TMAX)."""
    engine = ForecastDistributionEngine(
        freshness_policy=_fresh_policy(),
        eta_provider=ConstantEtaProvider(eta_s=0.35, provenance="TEST_TMIN_STALE"),
        mu_r_hook=SpecV2BaselineMuRHook(),
    )
    ladder = build_integer_bin_ladder(first_interior_start_f=60, num_interior_bins=4, bin_width_f=2)
    prior_tmin = PriorAffineFamilyModel(family="gaussian", mu0=61.0, sigma0=3.2)

    dt_stale = _dt("2026-07-15T18:00:00Z")
    obs_stale = _dt("2026-07-15T14:00:00Z")
    p11_distinct_max_min = StationDayState(
        schema_version="p11.v1",
        state_id="st-distinct",
        as_of_ts_utc=dt_stale,
        station_id="KORD",
        station_timezone="America/Chicago",
        target_date=date(2026, 7, 15),
        day_start_utc=_dt("2026-07-15T05:00:00Z"),
        settle_close_utc=_dt("2026-07-16T05:00:00Z"),
        m_now_exact_f=Decimal("85.0"),
        m_now_int_f=85,
        m_now_min_exact_f=Decimal("62.0"),
        m_now_min_int_f=62,
        oracle_compliant=True,
        oracle_source_tier="AWC_METAR_TGROUP",
        latest_obs_utc=obs_stale,
        latest_dispatch_ts_utc=obs_stale,
        latest_instant_temp_f=Decimal("83.0"),
        physical_age_sec=14400.0,
        dispatch_age_sec=14400.0,
        dispatch_age_available=True,
        freshness_ok=False,
        freshness_policy_provenance="TEST_POLICY",
        routine_obs_count=10,
        cor_overwrites_count=0,
        specis_seen_count=0,
        gap_flags=("PHYSICAL_AGE_EXCEEDED",),
    )

    snap, rep = engine.build_snapshot(
        station_id="KORD",
        target_date=date(2026, 7, 15),
        target_type="TMIN",
        issue_ts_utc=_dt("2026-07-15T18:05:00Z"),
        settle_close_utc=_dt("2026-07-16T05:00:00Z"),
        gefs_lead_hours=18,
        model_hash="model_tmin_v1",
        prior=prior_tmin,
        bins=ladder,
        p11_state=p11_distinct_max_min,
    )
    assert snap.is_bridge_active is False
    assert snap.m_now_f == 62.0
    assert snap.m_now_int_f == 62
    assert snap.p_stay_phys is None and snap.p_bin_stay is None
    assert rep.all_passed is True


def test_truncated_distribution_and_discrete_bin_engine_integer_wiring() -> None:
    """Spec (a)(1) fix: verify DiscreteBinEngine integer API and TruncatedDistribution hurdle export."""
    bins = DiscreteBinEngine.generate_integer_bins(
        first_interior_start_f=68, num_interior_bins=4, bin_width_f=2, station_id="KORD"
    )
    DiscreteBinEngine.validate_contiguous_integer_ladder(bins)

    base = GaussianEMOS(a=0.0, b=1.0, c=1.0, d=0.5, mu=76.0, sigma=3.6)
    mu_r_res = MuRResult(mu_r=2.0, scheme="spec_v2_baseline")
    dist_interior = TruncatedDistribution(
        base_distribution=base,
        target_type="max",
        extreme_m=69.5,
        instant_x_t=69.5,
        mu=76.0,
        sigma=3.6,
        mu_r_result=mu_r_res,
        sigma_rem=1.8,
    )
    p_phys = dist_interior.p_stay_phys()
    p_bin = dist_interior.p_bin_stay(bins)
    assert p_phys is not None and p_bin is not None
    assert math.isclose(p_phys, float(stats.norm.cdf(-2.0 / 1.8)), abs_tol=1e-12)
    assert p_bin > p_phys

    dist_tail = TruncatedDistribution(
        base_distribution=base,
        target_type="max",
        extreme_m=76.2,
        instant_x_t=76.2,
        mu=76.0,
        sigma=3.6,
        mu_r_result=mu_r_res,
        sigma_rem=1.8,
    )
    assert dist_tail.p_bin_stay(bins) == 1.0
    assert math.isclose(dist_tail.p_stay_phys() or -1.0, float(stats.norm.cdf(-2.0 / 1.8)), abs_tol=1e-12)

    dist_min = TruncatedDistribution(base_distribution=base, target_type="min", extreme_m=60.0)
    with pytest.raises(NotImplementedError, match="W3"):
        dist_min.hurdle_left_limit_cdf(60.0, sigma_rem=1.8)
