"""Unit tests for S3-16 `src/calibration/ece_evaluator.py` and `scripts/run_s316_ece_pilot.py`."""

from __future__ import annotations

import ast
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.calibration.ece_evaluator import (
    AUTO_BINNING_UPGRADE_MARKETS,
    ARITHMETIC_MIN_MARKETS_FOR_20_BINS,
    EceEvaluationConfig,
    ForecastBinObservation,
    compute_order_flow_weighted_ece,
    derive_ece_anchors_from_policy,
    evaluate_ece_from_directories,
    evaluate_ece_from_observations,
    join_forecasts_with_p9_truths,
    render_ece_pilot_markdown,
)
from src.prediction.discrete_bin_engine import BinProbV11
from src.prediction.forecast_distribution_engine import ForecastDistributionSnapshotV11

REPO_ROOT = Path(__file__).resolve().parents[3]


def _sign_jsonl(payload: Dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "record_sha256"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    body["record_sha256"] = hashlib.sha256(canonical).hexdigest()
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _obs(fid: str, p_model: float, hit: float, *, st: str = "KORD", bid: str = "58-59F") -> ForecastBinObservation:
    t0 = datetime(2026, 11, 26, 12, 0, 0, tzinfo=timezone.utc)
    return ForecastBinObservation(
        forecast_id=fid, station_id=st, target_date="2026-11-26", target_type="TMAX",
        bin_id=bid, label=bid, p_model=p_model, hit=hit, settled_temp_f_int=58,
        issue_ts_utc=t0, settle_close_utc=t0 + timedelta(hours=10),
    )


def test_ece_synthetic_calibration_regimes_recovery() -> None:
    cfg = EceEvaluationConfig(num_prob_bins=10, min_bin_samples=30, min_settled_markets=30, is_pilot=False)

    # 1) Perfectly calibrated: 40x (p=0.25, 10 hits) + 40x (p=0.75, 30 hits) -> ECE == 0.0
    perfect: List[ForecastBinObservation] = []
    for i in range(40):
        perfect.append(_obs(f"p-lo-{i}", 0.25, 1.0 if i < 10 else 0.0, bid="bin_a"))
        perfect.append(_obs(f"p-hi-{i}", 0.75, 1.0 if i < 30 else 0.0, bid="bin_b"))
    rep_perf = evaluate_ece_from_observations(perfect, config=cfg, corpus_source="SYNTH", n_settled_markets=40)
    assert rep_perf.status == "OK"
    assert abs((rep_perf.sample_weighted_ece or 0.0) - 0.0) < 1e-12
    assert abs((rep_perf.equal_bin_ece or 0.0) - 0.0) < 1e-12
    assert len(rep_perf.reliability_curve) == 2

    # 2) Overconfident: p=0.95 hits 65% (+0.30 err) and p=0.05 hits 35% (+0.30 err) -> ECE == 0.30
    overconf: List[ForecastBinObservation] = []
    for i in range(40):
        overconf.append(_obs(f"o-hi-{i}", 0.95, 1.0 if i < 26 else 0.0))
        overconf.append(_obs(f"o-lo-{i}", 0.05, 1.0 if i < 14 else 0.0))
    rep_over = evaluate_ece_from_observations(overconf, config=cfg, corpus_source="SYNTH", n_settled_markets=40)
    assert abs((rep_over.sample_weighted_ece or 0.0) - 0.30) < 1e-9
    assert abs((rep_over.equal_bin_ece or 0.0) - 0.30) < 1e-9

    # 3) Underconfident: p=0.65 hits 95% (+0.30 err) and p=0.35 hits 5% (+0.30 err) -> ECE == 0.30
    underconf: List[ForecastBinObservation] = []
    for i in range(40):
        underconf.append(_obs(f"u-hi-{i}", 0.65, 1.0 if i < 38 else 0.0))
        underconf.append(_obs(f"u-lo-{i}", 0.35, 1.0 if i < 2 else 0.0))
    rep_under = evaluate_ece_from_observations(underconf, config=cfg, corpus_source="SYNTH", n_settled_markets=40)
    assert abs((rep_under.sample_weighted_ece or 0.0) - 0.30) < 1e-9


def test_p9_join_causality_latest_pre_close_and_integer_bin_hit() -> None:
    close_ts = datetime(2026, 11, 27, 6, 0, 0, tzinfo=timezone.utc)
    t_early = close_ts - timedelta(hours=12)
    t_late = close_ts - timedelta(hours=2)
    t_post = close_ts + timedelta(minutes=1)
    bins_early = (BinProbV11("le_57F", "57°F or below", None, 57, 0.2), BinProbV11("58-59F", "58-59°F", 58, 59, 0.5), BinProbV11("ge_60F", "60°F or higher", 60, None, 0.3))
    bins_late = (BinProbV11("le_57F", "57°F or below", None, 57, 0.1), BinProbV11("58-59F", "58-59°F", 58, 59, 0.8), BinProbV11("ge_60F", "60°F or higher", 60, None, 0.1))

    def _snap(fid: str, issue: datetime, bins: tuple[BinProbV11, ...], st: str = "KORD", td: date = date(2026, 11, 26)) -> ForecastDistributionSnapshotV11:
        return ForecastDistributionSnapshotV11(
            schema_version="p5.v1.1", forecast_id=fid, issue_ts_utc=issue, station_id=st,
            target_date=td, target_type="TMAX", gefs_lead_hours=24, tau_hours=10.0,
            settle_close_utc=close_ts, model_hash="mh-v1", prior_mu0=58.0, prior_sigma0=2.0,
            family="gaussian", m_now_f=None, m_now_int_f=None, oracle_compliant=True,
            upstream_obs_fresh=True, is_bridge_active=False, p_stay_phys=None, p_bin_stay=None,
            bin_probs=bins, sigma_delta_sample=0.0,
        )

    snaps = [
        _snap("fc-early", t_early, bins_early),
        _snap("fc-late", t_late, bins_late),
        _snap("fc-post", t_post, bins_late),
        _snap("fc-unsettled", t_late, bins_late, st="KMIA"),
    ]
    p9_recs = [{"station_id": "KORD", "target_date": "2026-11-26", "target_type": "TMAX", "settled_temp_f_int": 59, "settle_close_utc": close_ts.isoformat()}]
    obs, n_mkts, n_unset, n_post = join_forecasts_with_p9_truths(snaps, p9_recs, snapshot_mode="latest_pre_close")
    assert (n_mkts, n_unset, n_post) == (1, 1, 1)
    assert len(obs) == 3
    assert {o.forecast_id for o in obs} == {"fc-late"}  # latest pre-close only
    hits = {o.bin_id: o.hit for o in obs}
    assert hits == {"le_57F": 0.0, "58-59F": 1.0, "ge_60F": 0.0}
    rep = evaluate_ece_from_observations(obs, config=EceEvaluationConfig(), corpus_source="UNIT", n_settled_markets=n_mkts)
    assert len(rep.per_station_breakdown) == 1 and rep.per_station_breakdown[0].station_id == "KORD"
    assert any(b.warning_low_n for b in rep.prob_bins)


def test_read_only_directory_evaluation_pending_and_populated_pilot_report(tmp_path: Path) -> None:
    audit_root = tmp_path / "audit_logs"
    p5_dir = tmp_path / "live_p5"
    day_dir = audit_root / "PAPER" / "2026-11-26"
    day_dir.mkdir(parents=True)
    p5_dir.mkdir(parents=True)
    close_ts = datetime(2026, 11, 27, 6, 0, 0, tzinfo=timezone.utc)
    issue_ts = close_ts - timedelta(hours=10)
    snap = ForecastDistributionSnapshotV11(
        schema_version="p5.v1.1", forecast_id="fc-ro-1", issue_ts_utc=issue_ts, station_id="KORD",
        target_date=date(2026, 11, 26), target_type="TMAX", gefs_lead_hours=24, tau_hours=10.0,
        settle_close_utc=close_ts, model_hash="mh-ro", prior_mu0=58.0, prior_sigma0=2.0,
        family="gaussian", m_now_f=None, m_now_int_f=None, oracle_compliant=True,
        upstream_obs_fresh=True, is_bridge_active=False, p_stay_phys=None, p_bin_stay=None,
        bin_probs=(BinProbV11("le_57F", "57°F or below", None, 57, 0.2), BinProbV11("ge_58F", "58°F or higher", 58, None, 0.8)),
        sigma_delta_sample=0.0,
    )
    p17_file = day_dir / "p17_forecast_snapshots.jsonl"
    p17_file.write_text(snap.to_p17_json_line(session_id="s-ro", execution_mode="PAPER", config_hash="ch") + "\n", encoding="utf-8")
    p5_payload = snap.to_p17_dict_without_hash(session_id="s-ro", execution_mode="PAPER", config_hash="ch")
    p5_payload["forecast_origin"] = "REALTIME_LIVE_PULL"
    p5_file = p5_dir / "p5_live_20261126.jsonl"
    p5_file.write_text(_sign_jsonl(p5_payload) + "\n", encoding="utf-8")

    # Pending P9 state returns PENDING_SETTLEMENT_DATA cleanly
    reps_pending = evaluate_ece_from_directories(audit_root=audit_root, live_p5_dir=p5_dir)
    assert reps_pending["AUDIT_P17_CONSUMED"].status == "PENDING_SETTLEMENT_DATA"
    assert reps_pending["AUDIT_P17_CONSUMED"].n_unsettled_forecasts == 1

    # Populated P9 truth evaluates both tracks without mutating source files
    p9_file = day_dir / "p9_settlement_truths.jsonl"
    p9_file.write_text(_sign_jsonl({
        "schema_version": "p9.v1", "settlement_id": "set-1", "settled_ts_utc": (close_ts + timedelta(hours=1)).isoformat(),
        "session_id": "s-ro", "execution_mode": "PAPER", "station_id": "KORD", "station_timezone": "America/Chicago",
        "target_date": "2026-11-26", "target_type": "TMAX", "market_id": "m-1", "winning_bin_id": "ge_58F",
        "oracle_source": "AWC_ROUTINE_METAR", "oracle_source_tier": "AWC_METAR_TGROUP",
        "day_start_utc": (close_ts - timedelta(hours=24)).isoformat(),
        "settle_close_utc": close_ts.isoformat(), "revision_lock_ts_utc": (close_ts + timedelta(hours=1)).isoformat(),
        "qualifying_obs_count": 24, "speci_excluded_count": 0, "cor_included_count": 0,
        "post_lock_cor_ignored_count": 0, "settled_temp_f_exact": "59.0", "settled_temp_f_int": 59,
        "fallback_to_lowest_bin": False, "wu_fallback_reason": None,
    }) + "\n", encoding="utf-8")
    before_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (p17_file, p5_file, p9_file)}
    reps = evaluate_ece_from_directories(audit_root=audit_root, live_p5_dir=p5_dir)
    after_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (p17_file, p5_file, p9_file)}
    assert before_hashes == after_hashes
    assert reps["AUDIT_P17_CONSUMED"].status == "OK"
    assert abs((reps["AUDIT_P17_CONSUMED"].sample_weighted_ece or 0.0) - 0.20) < 1e-12
    md = render_ece_pilot_markdown(reps, stale_trend_summary="Active cycles=1 | cumulative=130/198 (65.66%).")
    assert md.startswith("# PILOT_NOT_FOR_THRESHOLD_JUDGMENT")


def test_s316_ece_evaluator_ast_function_length_under_50_lines() -> None:
    for rel in ("src/calibration/ece_evaluator.py", "scripts/run_s316_ece_pilot.py"):
        target = REPO_ROOT / rel
        tree = ast.parse(target.read_text(encoding="utf-8"))
        ge_50 = [
            (node.name, (node.end_lineno or node.lineno) - node.lineno + 1)
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and ((node.end_lineno or node.lineno) - node.lineno + 1) >= 50
        ]
        assert ge_50 == [], f"{rel} has functions >= 50 lines: {ge_50}"


def test_auto_binning_upgrade_dual_weighting_anchors_zones_and_order_flow_ece() -> None:
    assert AUTO_BINNING_UPGRADE_MARKETS == 200
    assert ARITHMETIC_MIN_MARKETS_FOR_20_BINS == 55

    # 1) Formula-derived anchors scale dynamically with sigma_delta_frozen and k0
    anc = derive_ece_anchors_from_policy(sigma_delta_frozen=0.030, k0_threshold_coef=2.5)
    assert abs(anc.yellow_threshold - 0.030) < 1e-12
    assert abs(anc.red_threshold - 0.075) < 1e-12

    # 2) Auto binning upgrade trigger: 199 markets -> 10 bins; 200 markets -> 20 bins
    obs_199 = [_obs(f"f-{i}", 0.25, 1.0 if i % 4 == 0 else 0.0, st=f"S{i%6}", bid="58-59F") for i in range(199)]
    # Distinct (station_id, target_date) for 200 markets
    obs_200 = [
        ForecastBinObservation(
            forecast_id=f"fm-{i}", station_id=f"ST{i%6}",
            target_date=(date(2026, 10, 1) + timedelta(days=i // 6)).isoformat(),
            target_type="TMAX", bin_id="58-59F", label="58-59°F",
            p_model=0.25, hit=1.0 if i % 4 == 0 else 0.0, settled_temp_f_int=58,
            issue_ts_utc=datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc),
            settle_close_utc=datetime(2026, 11, 27, 6, 0, tzinfo=timezone.utc),
        )
        for i in range(200)
    ]
    cfg = EceEvaluationConfig(is_pilot=False, bootstrap_resamples=50)
    rep_199 = evaluate_ece_from_observations(obs_199, config=cfg, corpus_source="TEST", n_settled_markets=199)
    rep_200 = evaluate_ece_from_observations(obs_200, config=cfg, corpus_source="TEST", n_settled_markets=200)
    assert rep_199.num_prob_bins == 10 and rep_199.binning_upgrade.triggered is False and rep_199.judgment_zone == "RAMP_ZONE"
    assert rep_200.num_prob_bins == 20 and rep_200.binning_upgrade.triggered is True
    assert rep_200.inverse_variance_weighted_ece is not None and rep_200.noise_floor_ece is not None

    # 3) Mature zone >= 300 enforces point anchors directly
    rep_300 = evaluate_ece_from_observations(obs_200, config=cfg, corpus_source="TEST", n_settled_markets=300)
    assert rep_300.judgment_zone == "MATURE_ZONE" and rep_300.zoned_light_verdict == "GREEN"

    # 4) Order-flow weighted ECE weights ORDERED slices by target_slice_usd
    obs_of = [
        _obs("fc-good", 0.50, 1.0, bid="b_ok"),
        _obs("fc-good", 0.50, 0.0, bid="b_ok2"),
        _obs("fc-bad", 0.90, 0.0, bid="b_bad"),  # |0.90 - 0.0| = 0.90
    ]
    p1_orders = [
        {"decision_outcome": "ORDERED", "forecast_id": "fc-bad", "bin_id": "b_bad", "target_slice_usd": 100.0},
        {"decision_outcome": "ORDERED", "forecast_id": "fc-good", "bin_id": "b_ok", "target_slice_usd": 0.0},
        {"decision_outcome": "SKIP_EDGE_BELOW_M", "forecast_id": "fc-good", "bin_id": "b_ok2", "target_slice_usd": 50.0},
    ]
    of_ece, of_cnt, of_usd = compute_order_flow_weighted_ece(obs_of, p1_orders)
    assert of_cnt == 1 and abs(of_usd - 100.0) < 1e-12 and abs((of_ece or 0.0) - 0.90) < 1e-12
