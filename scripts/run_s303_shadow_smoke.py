#!/usr/bin/env python3
"""
S3-03 Shadow Smoke Runner: Live AWC METAR Smoke + Sealed 2019 Morphology Smoke.

Governance & Boundaries:
- Respects `2019 封跑制度` (`P8-ALGO-REVIEW §常设 2019 消费台账`): agent runs ONLY
  `--live-awc-smoke` (real aviationweather.gov connectivity smoke for M1 residual)
  and `--self-test` (synthetic morphology check, 0 real 2019 disk reads).
- Production `--execute-sealed-2019` runs ONLY when manually triggered by the Design Team;
  executes real `ForecastDistributionEngine` (`M2` + `Proposal1CoolingDriftMuRHook`) over the
  sealed 2019 corpus verifying aggregate convergence & invariants with zero w/phi fitting
  and zero day/row output.
- Zero touch to `M3` (`data/market_recordings/`, `passive_book_recorder.py`) or `src/pricing/`.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import math
from pathlib import Path
import sys
from typing import Any, Dict, List, Mapping, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_acquisition.settlement_metar_stream import (
    FreshnessPolicy,
    LiveAwcMetarAdapter,
    MissingDispatchPolicy,
    SettlementMetarStreamEngine,
    StationDayState,
    resolve_station_timezone,
)
from src.prediction.dynamic_corrector import MuRHook, SpecV2BaselineMuRHook
from src.prediction.forecast_distribution_engine import (
    CalibrationJsonEtaProvider,
    ConstantEtaProvider,
    EtaProvider,
    ForecastDistributionEngine,
    PriorAffineFamilyModel,
    build_integer_bin_ladder,
    compute_sigma_rem,
)
from src.utils.causal_utils import verify_record_sha256_line

ACTIVE_SMOKE_STATIONS: Tuple[str, ...] = ("KORD", "KMIA", "KLGA", "KATL", "KDAL", "KSEA")
LIVE_SMOKE_JSON = PROJECT_ROOT / "evidence" / "s303_live_awc_smoke_summary.json"
SEALED_2019_OUT_JSON = PROJECT_ROOT / "evidence" / "s303_2019_morphology_shadow_smoke_summary.json"
CALIB_ETA_CSV = PROJECT_ROOT / "evidence" / "p8_inspection_a_eta_calibration_20261113.csv"


@dataclass(frozen=True)
class StationLiveSmokeRow:
    station_id: str
    routine_reports: int
    total_archival_reports: int
    specis_seen: int
    oracle_compliant: bool
    m_now_tmax_f: float | None
    m_now_int_f: int | None
    p12_sha256_ok: bool
    p5_invariants_ok: bool
    sigma_rem: float


def _build_default_engine(
    eta_provider: EtaProvider | None = None,
    mu_r_hook: MuRHook | None = None,
) -> ForecastDistributionEngine:
    return ForecastDistributionEngine(
        freshness_policy=FreshnessPolicy(physical_age_limit_sec=86400.0, provenance="s303_shadow_smoke_policy"),
        eta_provider=eta_provider or ConstantEtaProvider(eta_s=0.25, provenance="s303_shadow_smoke_eta"),
        mu_r_hook=mu_r_hook or SpecV2BaselineMuRHook(),
    )


def _smoke_single_live_station(
    adapter: LiveAwcMetarAdapter, station_id: str, target_d: date, now_utc: datetime
) -> StationLiveSmokeRow:
    m1 = SettlementMetarStreamEngine(
        source=adapter,
        freshness_policy=FreshnessPolicy(physical_age_limit_sec=86400.0, provenance="s303_live_awc_smoke"),
        missing_dispatch_policy=MissingDispatchPolicy(
            mode="CONSERVATIVE_LAG_BOUND", provenance="awc_api_lag_bound_300s", conservative_lag_bound_sec=300.0
        ),
    )
    res = m1.evaluate_as_of(
        station_id=station_id, target_date=target_d, as_of_ts_utc=now_utc,
        session_id="s303-live-awc-smoke", execution_mode="PAPER",
        model_hash="shadow_smoke_v1", config_hash="shadow_smoke_cfg", gfs_available=False,
    )
    p12_ok = verify_record_sha256_line(res.coverage_ledger.to_json_line())
    prior_center = round(res.state.m_now_f) if res.state.m_now_f is not None else 60
    prior = PriorAffineFamilyModel(mu0=float(prior_center + 2), sigma0=3.5, family="gaussian")
    bins = build_integer_bin_ladder(first_interior_start_f=prior_center - 8, num_interior_bins=9, bin_width_f=2)
    _, report = _build_default_engine().build_snapshot(
        station_id=station_id, target_date=target_d, target_type="TMAX", issue_ts_utc=now_utc,
        settle_close_utc=res.state.settle_close_utc, gefs_lead_hours=24, model_hash="shadow_smoke_v1",
        prior=prior, bins=bins, p11_state=res.state,
    )
    return StationLiveSmokeRow(
        station_id=station_id, routine_reports=res.state.routine_obs_count,
        total_archival_reports=len(res.archival_observations), specis_seen=res.state.specis_seen_count,
        oracle_compliant=res.state.oracle_compliant, m_now_tmax_f=res.state.m_now_f,
        m_now_int_f=res.state.m_now_int_f, p12_sha256_ok=p12_ok and report.all_passed,
        p5_invariants_ok=report.all_passed, sigma_rem=compute_sigma_rem(prior.sigma0, 0.25),
    )


def run_live_awc_smoke(stations: Sequence[str] = ACTIVE_SMOKE_STATIONS) -> Dict[str, Any]:
    """Run live HTTPS read-only AWC METAR -> M1 -> M2 P5 v1.1 connectivity smoke."""
    now_utc = datetime.now(timezone.utc)
    target_d = now_utc.date()
    adapter = LiveAwcMetarAdapter(timeout_sec=15.0)
    rows: List[Dict[str, Any]] = []
    for st in stations:
        r = _smoke_single_live_station(adapter, st, target_d, now_utc)
        rows.append(
            {
                "station_id": r.station_id, "routine_reports": r.routine_reports,
                "total_archival_reports": r.total_archival_reports, "specis_seen": r.specis_seen,
                "oracle_compliant": r.oracle_compliant, "m_now_tmax_f": r.m_now_tmax_f,
                "m_now_int_f": r.m_now_int_f, "p12_sha256_ok": r.p12_sha256_ok,
                "p5_invariants_ok": r.p5_invariants_ok, "sigma_rem": round(r.sigma_rem, 4),
            }
        )
    all_ok = all(
        row["routine_reports"] > 0 and row["oracle_compliant"] and row["p5_invariants_ok"] and row["p12_sha256_ok"]
        for row in rows
    )
    summary = {
        "work_order_id": "P8-WO-20261122-S303-SMOKE", "mode": "LIVE_AWC_CONNECTIVITY_SMOKE",
        "run_utc": now_utc.isoformat(), "endpoint": LiveAwcMetarAdapter.BASE_URL,
        "stations_tested": len(rows), "all_stations_passed": all_ok, "results": rows,
    }
    LIVE_SMOKE_JSON.parent.mkdir(parents=True, exist_ok=True)
    LIVE_SMOKE_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def _build_p11_state(station_id: str, target_d: date, issue_ts: datetime, close_ts: datetime, m_val: float) -> StationDayState:
    m_int = int(math.floor(m_val + 0.5))
    return StationDayState(
        schema_version="p11.v0", state_id=f"s303-{station_id}-{target_d.isoformat()}-{issue_ts.isoformat()}",
        as_of_ts_utc=issue_ts, station_id=station_id, station_timezone=str(resolve_station_timezone(station_id)),
        target_date=target_d, day_start_utc=close_ts - timedelta(hours=24), settle_close_utc=close_ts,
        m_now_exact_f=Decimal(str(round(m_val, 3))), m_now_int_f=m_int,
        m_now_min_exact_f=Decimal(str(round(m_val - 10.0, 3))), m_now_min_int_f=m_int - 10,
        oracle_compliant=True, oracle_source_tier="T_GROUP_0_1C",
        latest_obs_utc=issue_ts - timedelta(minutes=15), latest_dispatch_ts_utc=issue_ts - timedelta(minutes=5),
        latest_instant_temp_f=Decimal(str(round(m_val - 0.5, 3))), physical_age_sec=900.0,
        dispatch_age_sec=300.0, dispatch_age_available=True, freshness_ok=True,
        freshness_policy_provenance="s303_shadow_smoke_policy", routine_obs_count=4,
        cor_overwrites_count=0, specis_seen_count=0, gap_flags=(),
    )


def _eval_trajectory_with_engine(
    station_id: str,
    target_d: date,
    steps: Sequence[Tuple[datetime, float, float]],
    prior: PriorAffineFamilyModel,
    engine: ForecastDistributionEngine,
    eta_provider: EtaProvider,
) -> Tuple[int, bool, bool, bool, bool]:
    close_ts = datetime(target_d.year, target_d.month, target_d.day, 23, 59, tzinfo=timezone.utc)
    center = int(round(prior.mu0))
    bins = build_integer_bin_ladder(first_interior_start_f=center - 8, num_interior_bins=9, bin_width_f=2)
    prev_m: int | None = None
    invariants_ok = monotone_m = sigma_ok = dead_zero_ok = True

    for issue_ts, m_val, local_hour in steps:
        p11 = _build_p11_state(station_id, target_d, issue_ts, close_ts, m_val)
        snap, rep = engine.build_snapshot(
            station_id=station_id, target_date=target_d, target_type="TMAX", issue_ts_utc=issue_ts,
            settle_close_utc=close_ts, gefs_lead_hours=24, model_hash="s303_bridge_v1",
            prior=prior, bins=bins, p11_state=p11,
        )
        invariants_ok = invariants_ok and rep.all_passed
        assert snap.m_now_int_f is not None
        if prev_m is not None and snap.m_now_int_f < prev_m:
            monotone_m = False
        prev_m = snap.m_now_int_f
        season = "summer" if target_d.month in (6, 7, 8) else ("winter" if target_d.month in (12, 1, 2) else ("spring" if target_d.month in (3, 4, 5) else "autumn"))
        eta_val = eta_provider.get_eta_s(station_id=station_id, season=season, t_local_hour=local_hour)
        if compute_sigma_rem(prior.sigma0, eta_val) > prior.sigma0 + 1e-12:
            sigma_ok = False
        if any(bp.upper_int_f is not None and bp.upper_int_f < snap.m_now_int_f and bp.p_model != 0.0 for bp in snap.bin_probs):
            dead_zero_ok = False
    return len(steps), invariants_ok, monotone_m, sigma_ok, dead_zero_ok


def run_synthetic_morphology_self_test() -> Dict[str, Any]:
    """Zero-2019-disk-read synthetic morphology convergence check for M1->M2 HurdleBridge."""
    prior = PriorAffineFamilyModel(mu0=79.5, sigma0=3.8, family="gaussian")
    base_d = date(2026, 7, 15)
    t0 = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    hours = (10.0, 14.0, 18.0)
    trajectories = {
        "warming_day": (72.2, 78.6, 82.4),
        "early_peak_cooling": (76.1, 76.1, 76.1),
        "tail_breakout": (74.0, 81.5, 89.2),
    }
    cases: List[Dict[str, Any]] = []
    eta_p = ConstantEtaProvider(eta_s=0.25, provenance="s303_self_test")
    engine = _build_default_engine(eta_p, SpecV2BaselineMuRHook())
    for name, m_seq in trajectories.items():
        steps = [(t0 + timedelta(hours=4 * i), m_v, hours[i]) for i, m_v in enumerate(m_seq)]
        _, inv, mono, sig, dead = _eval_trajectory_with_engine("KORD", base_d, steps, prior, engine, eta_p)
        cases.append({
            "trajectory": name, "invariants_ok": inv, "monotone_m_now": mono,
            "sigma_rem_converged": sig, "dead_bin_zeroed": dead,
        })
    all_pass = all(c["invariants_ok"] and c["monotone_m_now"] and c["sigma_rem_converged"] and c["dead_bin_zeroed"] for c in cases)
    return {
        "mode": "SYNTHETIC_SELF_TEST", "real_2019_files_accessed": 0,
        "all_morphologies_passed": all_pass, "cases": cases,
    }


def evaluate_sealed_2019_corpus(
    *,
    prior_dfs: Mapping[str, Any],
    obs_summaries: Mapping[Tuple[str, float], Any],
    t_grid: Sequence[float],
    engine: ForecastDistributionEngine,
    eta_provider: EtaProvider,
    climate_calib: Mapping[str, Any],
) -> Dict[str, Any]:
    """Run real `M2` `ForecastDistributionEngine` evaluations over sealed 2019 priors & METAR slices."""
    n_day_leads = n_evals = inv_ok = mono_ok = sig_ok = dead_ok = 0
    for st, df19 in prior_dfs.items():
        for row in df19.itertuples():
            n_day_leads += 1
            seas = str(row.season)
            fam = str(climate_calib[st]["seasons"][seas].get("selected_family", "gaussian"))
            sp = climate_calib[st]["seasons"][seas].get("shape_params", {}) or {}
            prior = PriorAffineFamilyModel(mu0=float(row.mu_0), sigma0=float(row.sigma_0), family=fam, shape_params=sp)
            steps = _collect_steps_for_day(st, row.target_date, obs_summaries, t_grid)
            if not steps:
                continue
            cnt, i_ok, m_ok, s_ok, d_ok = _eval_trajectory_with_engine(st, row.target_date, steps, prior, engine, eta_provider)
            n_evals += cnt
            inv_ok += int(i_ok)
            mono_ok += int(m_ok)
            sig_ok += int(s_ok)
            dead_ok += int(d_ok)
    denom = max(n_day_leads, 1)
    return {
        "work_order_id": "2019-SEALED-002", "task_id": "S3-03",
        "run_utc": datetime.now(timezone.utc).isoformat(), "n_day_leads": n_day_leads,
        "n_bridge_evals": n_evals, "p5_invariants_pass_rate": round(inv_ok / denom, 6),
        "monotone_m_now_rate": round(mono_ok / denom, 6), "sigma_rem_le_sigma0_rate": round(sig_ok / denom, 6),
        "dead_bin_zero_rate": round(dead_ok / denom, 6), "zero_w_phi_fitting": True,
        "sealed_morphology_passed": n_evals > 0 and inv_ok == n_day_leads and mono_ok == n_day_leads and sig_ok == n_day_leads and dead_ok == n_day_leads,
    }


def _collect_steps_for_day(
    station_id: str, target_d: date, obs_summaries: Mapping[Tuple[str, float], Any], t_grid: Sequence[float]
) -> List[Tuple[datetime, float, float]]:
    steps: List[Tuple[datetime, float, float]] = []
    for hf_raw in t_grid:
        hf = float(hf_raw)
        tbl = obs_summaries.get((station_id, hf))
        if tbl is None or target_d not in tbl.index:
            continue
        mt = float(tbl.loc[target_d, "mt"])
        if math.isnan(mt):
            continue
        ts = datetime(target_d.year, target_d.month, target_d.day, int(hf), 0, tzinfo=timezone.utc)
        steps.append((ts, mt, hf))
    return steps


def run_sealed_2019_morphology_smoke() -> Dict[str, Any]:
    """Sealed 2019 morphology smoke (Design Team manual execution ONLY; zero w/phi fitting)."""
    import pandas as pd
    from scripts.run_p8_inspection_a_eta_calibration import T_GRID
    from scripts.run_p8_inspection_c_2019_final_lst import OBS_2019_LST_PATH, _build_slice_summaries, _load_official_metar_2019
    from scripts.run_p8_inspection_c_2019_replay import (
        CLIMATE_CALIB_PATH, CONTRACT_PATH, MANIFEST_PATH, build_2019_cell_priors
    )
    from scripts.run_p8_metar_counterfactual_sealed_2019 import AUTHORIZED_LEAD_HOURS, AUTHORIZED_STATIONS
    from src.prediction.dynamic_corrector import Proposal1CoolingDriftMuRHook

    contract_cells = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))["cells"]
    manifest_models = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["models"]
    climate_calib = json.loads(CLIMATE_CALIB_PATH.read_text(encoding="utf-8"))
    eta_provider = CalibrationJsonEtaProvider.from_csv(CALIB_ETA_CSV) if CALIB_ETA_CSV.exists() else ConstantEtaProvider(0.25, "fallback")
    engine = _build_default_engine(eta_provider, Proposal1CoolingDriftMuRHook.from_calibration_artifact())

    metar_frames = [_load_official_metar_2019(st)[1] for st in AUTHORIZED_STATIONS]
    obs_summaries = _build_slice_summaries(pd.concat(metar_frames, ignore_index=True), AUTHORIZED_STATIONS)
    obs_lst = pd.read_parquet(OBS_2019_LST_PATH)
    prior_dfs = {
        st: build_2019_cell_priors(st, AUTHORIZED_LEAD_HOURS[0], manifest_models, climate_calib, contract_cells)
        for st in AUTHORIZED_STATIONS if not obs_lst[obs_lst["station"] == st].empty
    }
    summary = evaluate_sealed_2019_corpus(
        prior_dfs=prior_dfs, obs_summaries=obs_summaries, t_grid=T_GRID,
        engine=engine, eta_provider=eta_provider, climate_calib=climate_calib,
    )
    SEALED_2019_OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    SEALED_2019_OUT_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="S3-03 Live AWC & Sealed 2019 Morphology Shadow Smoke.")
    parser.add_argument("--live-awc-smoke", action="store_true", help="Run real AWC METAR -> M1 -> M2 connectivity smoke.")
    parser.add_argument("--self-test", action="store_true", help="Run zero-2019-read synthetic morphology check.")
    parser.add_argument("--execute-sealed-2019", action="store_true", help="Manually executed by Design Team only under 2019 封跑制度.")
    args = parser.parse_args()

    if args.live_awc_smoke:
        summary = run_live_awc_smoke()
        print("=== S3-03 LIVE AWC SMOKE SUMMARY ===")
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0 if summary["all_stations_passed"] else 1
    if args.self_test:
        res = run_synthetic_morphology_self_test()
        print("=== S3-03 SYNTHETIC MORPHOLOGY SELF-TEST ===")
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res["all_morphologies_passed"] else 1
    if args.execute_sealed_2019:
        res = run_sealed_2019_morphology_smoke()
        print("=== SEALED S3-03 2019 MORPHOLOGY SMOKE ===")
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res["sealed_morphology_passed"] else 1
    print("SEALED_GUARD: Pass --live-awc-smoke, --self-test, or --execute-sealed-2019 (Design Team manual trigger only).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
