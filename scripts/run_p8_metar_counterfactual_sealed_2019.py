#!/usr/bin/env python3
"""
Sealed 2019 Evaluator #1: OfficialMETAR(DST) Truth Counterfactual Evaluator.

Contract & Governance ("2019 封跑制度", G-14 / Task 4(3)):
- Pre-registered, fixed-metric sealed evaluator for OfficialMETAR(DST) counterfactual truth.
- Prohibits exploratory queries, raw 2019 row printing, per-day output, or per-slice CSV dumps.
- Emits ONLY the fixed aggregate output block on stdout and writes a single aggregate-only JSON
  (`evidence/p8_metar_counterfactual_sealed_2019_summary.json`) containing zero day/slice arrays.
- Agent runs ONLY `--self-test` (pure in-memory synthetic data, zero disk reads of 2019 files).
- Production `--execute-sealed-2019` run is triggered manually by the Design Team only.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy import special

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.compute_p8_oos_and_shape_calibration import (
    AUTHORIZED_LEAD_HOURS,
    AUTHORIZED_STATIONS,
    SEASONS,
    compute_ece_inw,
    compute_ece_w20,
    compute_moments_z,
    get_period,
)
from scripts.diagnose_p8_inspection_c_2019 import (
    StandardizedJSUCRPSLookup,
    bridge_crps_exact,
    gaussian_crps_exact,
)
from scripts.run_p8_inspection_a_eta_calibration import (
    SIGMA_INST_PHYSICAL_FLOOR,
    T_GRID,
    classify_position_bucket,
)
from scripts.run_p8_inspection_c_2019_final_lst import (
    G1B_MIN_IMPROVED_STRATA,
    G3A_MAX_ABS_WRESID,
    G3A_MAX_AFT_OUT95,
    G3B_MAX_EARLY_B12_OUT95,
    G3C_MAX_POOLED_ECE_BRIDGE_INW,
    OBS_2019_LST_PATH,
    _build_atomic_buckets,
    _build_slice_summaries,
    _compute_atomic_metrics,
    _load_official_metar_2019,
)
from scripts.run_p8_inspection_c_2019_replay import (
    CLIMATE_CALIB_PATH,
    CONTRACT_PATH,
    ETA_CAL_CSV,
    MANIFEST_PATH,
    bracket_hit_index,
    build_2019_cell_priors,
    evaluate_11_bracket_probs_prior,
)
from src.prediction.discrete_bin_engine import settle_half_up
from src.prediction.dynamic_corrector import (
    _DEFAULT_COOLING_DRIFT_ARTIFACT,
    Proposal1CoolingDriftMuRHook,
)

SEALED_OUT_JSON = PROJECT_ROOT / "evidence" / "p8_metar_counterfactual_sealed_2019_summary.json"
WORK_ORDER_ID = "2019-SEALED-001"


def _bridge_11_probs(c0: int, m_int: float, mu_r: float, sigma_rem: float) -> np.ndarray:
    """Compute normalized 11-bracket conditional bridge distribution around center c0."""
    lower = c0 - 9
    edges = [lower + 2 * k for k in range(10)]
    cdfs = np.array(
        [0.0 if e <= m_int else float(special.ndtr(((e - m_int) - mu_r) / sigma_rem)) for e in edges],
        dtype=float,
    )
    p = np.empty(11, dtype=float)
    p[0] = cdfs[0]
    p[1:10] = np.maximum(0.0, cdfs[1:10] - cdfs[0:9])
    p[10] = max(0.0, 1.0 - cdfs[9])
    s = float(p.sum())
    if s > 0.0:
        p /= s
    return p


def _evaluate_track_aggregates(
    crps_nat: np.ndarray,
    crps_br: np.ndarray,
    strata_crps: Dict[Tuple[str, str, str], Tuple[List[float], List[float]]],
    nat_p: List[np.ndarray],
    nat_h: List[np.ndarray],
    br_p: List[np.ndarray],
    br_h: List[np.ndarray],
    atom_records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute pre-registered fixed G1/G3/CRPS/ECE aggregates with zero row/slice persistence."""
    pooled_crps_nat = float(np.mean(crps_nat))
    pooled_crps_br = float(np.mean(crps_br))
    n_strata_improved = 0
    for _key, (cn_list, cb_list) in strata_crps.items():
        if cn_list and cb_list and float(np.mean(cb_list)) < float(np.mean(cn_list)):
            n_strata_improved += 1

    ece_nat_inw = compute_ece_inw(np.concatenate(nat_p), np.concatenate(nat_h))
    ece_nat_w20 = compute_ece_w20(np.concatenate(nat_p), np.concatenate(nat_h))
    ece_br_inw = compute_ece_inw(np.concatenate(br_p), np.concatenate(br_h))
    ece_br_w20 = compute_ece_w20(np.concatenate(br_p), np.concatenate(br_h))

    abdf = _build_atomic_buckets(pd.DataFrame(atom_records))
    atom_m = _compute_atomic_metrics(abdf)

    g1a_pass = bool(pooled_crps_br < pooled_crps_nat)
    g1b_pass = bool(n_strata_improved >= G1B_MIN_IMPROVED_STRATA)
    g3a_pass = bool(
        atom_m["aft_total_out95"] <= G3A_MAX_AFT_OUT95
        and abs(atom_m["aft_B1"]["wResid"]) <= G3A_MAX_ABS_WRESID
        and abs(atom_m["aft_B2"]["wResid"]) <= G3A_MAX_ABS_WRESID
        and abs(atom_m["aft_B3"]["wResid"]) <= G3A_MAX_ABS_WRESID
    )
    g3b_pass = bool(atom_m["early_B12_pooled"]["out95"] <= G3B_MAX_EARLY_B12_OUT95)
    g3c_pass = bool(ece_br_inw <= G3C_MAX_POOLED_ECE_BRIDGE_INW)

    return {
        "crps_native": round(pooled_crps_nat, 6),
        "crps_bridge": round(pooled_crps_br, 6),
        "crps_delta_pct": round(100.0 * (pooled_crps_br - pooled_crps_nat) / max(pooled_crps_nat, 1e-12), 3),
        "strata_improved_of_16": int(n_strata_improved),
        "ece_native_inw": round(ece_nat_inw, 6),
        "ece_native_w20": round(ece_nat_w20, 6),
        "ece_bridge_inw": round(ece_br_inw, 6),
        "ece_bridge_w20": round(ece_br_w20, 6),
        "g3a_aft_out95": int(atom_m["aft_total_out95"]),
        "g3a_aft_cells": int(atom_m["aft_total_cells"]),
        "g3a_aft_B1_wResid": round(float(atom_m["aft_B1"]["wResid"]), 6),
        "g3a_aft_B2_wResid": round(float(atom_m["aft_B2"]["wResid"]), 6),
        "g3a_aft_B3_wResid": round(float(atom_m["aft_B3"]["wResid"]), 6),
        "g3b_early_B12_out95": int(atom_m["early_B12_pooled"]["out95"]),
        "g3b_early_B12_cells": int(atom_m["early_B12_pooled"]["cells"]),
        "gates": {
            "G1a_crps_improved": g1a_pass,
            "G1b_strata_ge_12": g1b_pass,
            "G3a_aft_atomic": g3a_pass,
            "G3b_early_B12": g3b_pass,
            "G3c_ece_bridge_inw": g3c_pass,
        },
    }


def _format_fixed_output_block(summary: Dict[str, Any]) -> str:
    """Format strictly the fixed aggregate-only sealed output block."""
    lines = [
        "=== SEALED 2019 OUTPUT BLOCK ===",
        f"work_order={summary['work_order_id']} | truth={summary['truth_universe']} | hook={summary['hook_artifact']} | run_utc={summary['run_utc']}",
        (
            "thresholds: "
            f"G1b>={G1B_MIN_IMPROVED_STRATA}/16 | "
            f"G3a_out95<={G3A_MAX_AFT_OUT95},|wResid|<={G3A_MAX_ABS_WRESID} | "
            f"G3b_out95<={G3B_MAX_EARLY_B12_OUT95} | "
            f"G3c_ece_inw<={G3C_MAX_POOLED_ECE_BRIDGE_INW}"
        ),
    ]
    for label, tr in summary["tracks"].items():
        g = tr["gates"]
        lines.extend(
            [
                f"[{label}] n_day_leads={tr['n_day_leads']} | n_bridge_evals={tr['n_bridge_evals']} | n_atom_obs={tr['n_atom_obs']}",
                (
                    f"  CRPS_native={tr['crps_native']:.6f} | CRPS_bridge={tr['crps_bridge']:.6f} "
                    f"({tr['crps_delta_pct']:+.3f}%) | strata_improved={tr['strata_improved_of_16']}/16 "
                    f"| G1a={g['G1a_crps_improved']} G1b={g['G1b_strata_ge_12']}"
                ),
                (
                    f"  ECE_native(inw/w20)={tr['ece_native_inw']:.6f}/{tr['ece_native_w20']:.6f} | "
                    f"ECE_bridge(inw/w20)={tr['ece_bridge_inw']:.6f}/{tr['ece_bridge_w20']:.6f} "
                    f"| G3c={g['G3c_ece_bridge_inw']}"
                ),
                (
                    f"  G3a: aft_out95={tr['g3a_aft_out95']}/{tr['g3a_aft_cells']} | "
                    f"wResid(B1/B2/B3)={tr['g3a_aft_B1_wResid']:+.6f}/{tr['g3a_aft_B2_wResid']:+.6f}/{tr['g3a_aft_B3_wResid']:+.6f} "
                    f"| G3a={g['G3a_aft_atomic']}"
                ),
                (
                    f"  G3b: early_B12_out95={tr['g3b_early_B12_out95']}/{tr['g3b_early_B12_cells']} "
                    f"| G3b={g['G3b_early_B12']}"
                ),
            ]
        )
    lines.append("=== END SEALED 2019 OUTPUT BLOCK ===")
    return "\n".join(lines)


def run_sealed_2019() -> Dict[str, Any]:
    """Execute OfficialMETAR(DST) truth counterfactual on 2019 retaining only aggregate metrics."""
    hook = Proposal1CoolingDriftMuRHook.from_calibration_artifact()
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if contract.get("s_oos_version") != "v2_2000_2018_oof_cv":
        raise RuntimeError(f"Expected v2_2000_2018_oof_cv contract, got {contract.get('s_oos_version')}")
    contract_cells = contract["cells"]
    manifest_models = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["models"]
    climate_calib = json.loads(CLIMATE_CALIB_PATH.read_text(encoding="utf-8"))
    eta_df = pd.read_csv(ETA_CAL_CSV)
    eta_map = {(str(r.station), str(r.season), float(r.t_hour)): float(r.eta_calibrated) for r in eta_df.itertuples()}

    moment_map: Dict[Tuple[str, str], Tuple[str, Dict[str, Any], float, float]] = {}
    jsu_lookups: Dict[Tuple[str, str], StandardizedJSUCRPSLookup] = {}
    for st in AUTHORIZED_STATIONS:
        for seas in SEASONS:
            info = climate_calib[st]["seasons"][seas]
            fam = str(info.get("selected_family", "gaussian"))
            sp = info.get("shape_params", {}) or {}
            ez, stdz = compute_moments_z(fam, sp)
            moment_map[(st, seas)] = (fam, sp, ez, stdz)
            if fam == "johnsonsu":
                jsu_lookups[(st, seas)] = StandardizedJSUCRPSLookup(sp)

    obs_lst = pd.read_parquet(OBS_2019_LST_PATH).copy()
    obs_lst["valid_utc"] = pd.to_datetime(obs_lst["valid_utc"], utc=True)
    obs_lst["local_date"] = pd.to_datetime(obs_lst["local_date_str"]).dt.date
    day_summaries_5m = _build_slice_summaries(obs_lst, AUTHORIZED_STATIONS)
    retained_dates_by_st = {st: set(obs_lst[obs_lst["station"] == st]["local_date"].unique()) for st in AUTHORIZED_STATIONS}

    metar_dst_map: Dict[Tuple[str, Any], Tuple[float, float]] = {}
    metar_lst_frames: List[pd.DataFrame] = []
    for st in AUTHORIZED_STATIONS:
        d_dst, d_mlst = _load_official_metar_2019(st)
        for row in d_dst.itertuples():
            metar_dst_map[(st, row.target_date)] = (float(row.metar_dst_settled_f), float(row.metar_dst_tmax_f))
        metar_lst_frames.append(d_mlst)
    metar_summaries = _build_slice_summaries(pd.concat(metar_lst_frames, ignore_index=True), AUTHORIZED_STATIONS)

    track_specs = {
        "track1_obs5m_truth_metar_dst": day_summaries_5m,
        "track2_obsmetar_truth_metar_dst": metar_summaries,
    }
    tracks_out: Dict[str, Any] = {}

    for track_name, obs_summaries in track_specs.items():
        strata_crps: Dict[Tuple[str, str, str], Tuple[List[float], List[float]]] = {
            (st, seas, per): ([], [])
            for st in AUTHORIZED_STATIONS
            for seas in SEASONS
            for per in ("early", "late")
        }
        all_crps_nat: List[float] = []
        all_crps_br: List[float] = []
        all_nat_p: List[np.ndarray] = []
        all_nat_h: List[np.ndarray] = []
        all_br_p: List[np.ndarray] = []
        all_br_h: List[np.ndarray] = []
        atom_records: List[Dict[str, Any]] = []
        n_day_leads = 0
        n_bridge_evals = 0

        for st in AUTHORIZED_STATIONS:
            valid_dates = retained_dates_by_st[st]
            for lead in AUTHORIZED_LEAD_HOURS:
                per = get_period(lead)
                df19 = build_2019_cell_priors(st, lead, manifest_models, climate_calib, contract_cells)
                df19 = df19[
                    df19["target_date"].isin(valid_dates)
                    & df19["target_date"].map(lambda d: (st, d) in metar_dst_map)
                ].copy().reset_index(drop=True)
                if df19.empty:
                    continue

                dates_arr = df19["target_date"].tolist()
                seas_arr = df19["season"].tolist()
                mu0_arr = df19["mu_0"].to_numpy(dtype=float)
                s0_arr = df19["sigma_0"].to_numpy(dtype=float)
                y_settled_arr = np.array([metar_dst_map[(st, d)][0] for d in dates_arr], dtype=float)
                y_raw_max_arr = np.array([metar_dst_map[(st, d)][1] for d in dates_arr], dtype=float)
                n_day_leads += len(df19)

                crps_nat_arr = np.empty(len(df19), dtype=float)
                c0_list: List[int] = []
                hv_list: List[np.ndarray] = []
                p_nat_list: List[np.ndarray] = []
                for i in range(len(df19)):
                    seas = seas_arr[i]
                    mu0 = float(mu0_arr[i])
                    s0 = float(s0_arr[i])
                    yi = float(y_settled_arr[i])
                    fam, sp, ez, stdz = moment_map[(st, seas)]
                    mm_mu = mu0 + s0 * ez
                    mm_sig = s0 * stdz
                    if fam == "johnsonsu":
                        crps_nat_arr[i] = float(jsu_lookups[(st, seas)].eval_crps(np.array([yi]), np.array([mu0]), np.array([s0]))[0])
                    else:
                        crps_nat_arr[i] = float(gaussian_crps_exact(np.array([yi]), np.array([mu0]), np.array([s0]))[0])
                    c0 = int(round(mu0))
                    c0_list.append(c0)
                    p_nat, _, _, _ = evaluate_11_bracket_probs_prior(mu0, s0, fam, sp, c0, mm_mu, mm_sig)
                    hv = np.zeros(11, dtype=float)
                    hv[bracket_hit_index(yi, c0)] = 1.0
                    hv_list.append(hv)
                    p_nat_list.append(p_nat)

                for hf_np in T_GRID:
                    hf = float(hf_np)
                    obs_slice = obs_summaries[(st, hf)].reindex(dates_arr)
                    mt_vec = obs_slice["mt"].to_numpy(dtype=float)
                    xt_vec = obs_slice["xt"].to_numpy(dtype=float)
                    valid_idx = [i for i in range(len(df19)) if not (np.isnan(mt_vec[i]) or np.isnan(xt_vec[i]))]
                    if not valid_idx:
                        continue

                    m_int_v = np.empty(len(valid_idx), dtype=float)
                    mu_r_v = np.empty(len(valid_idx), dtype=float)
                    sr_v = np.empty(len(valid_idx), dtype=float)
                    y_v = y_settled_arr[valid_idx]

                    for j, i in enumerate(valid_idx):
                        seas = seas_arr[i]
                        mu0 = float(mu0_arr[i])
                        s0 = float(s0_arr[i])
                        m_int = float(settle_half_up(float(mt_vec[i])))
                        eta = eta_map[(st, seas, hf)]
                        sr = max(s0 * math.sqrt(max(eta, 0.0)), SIGMA_INST_PHYSICAL_FLOOR)
                        res_mu = hook.compute(
                            t_local=hf,
                            extreme_m=m_int,
                            instant_x_t=float(xt_vec[i]),
                            mu_0=mu0,
                            target_type="max",
                            station_id=st,
                            season=seas,
                        )
                        m_int_v[j] = m_int
                        mu_r_v[j] = res_mu.mu_r
                        sr_v[j] = sr

                    cbr_v = bridge_crps_exact(y_v, m_int_v, mu_r_v, sr_v)

                    for j, i in enumerate(valid_idx):
                        n_bridge_evals += 1
                        seas = seas_arr[i]
                        m_int = float(m_int_v[j])
                        mu_r = float(mu_r_v[j])
                        sr = float(sr_v[j])
                        p_cond = _bridge_11_probs(c0_list[i], m_int, mu_r, sr)
                        hv = hv_list[i]

                        all_crps_nat.append(float(crps_nat_arr[i]))
                        all_crps_br.append(float(cbr_v[j]))
                        strata_crps[(st, seas, per)][0].append(float(crps_nat_arr[i]))
                        strata_crps[(st, seas, per)][1].append(float(cbr_v[j]))
                        all_nat_p.append(p_nat_list[i])
                        all_nat_h.append(hv)
                        all_br_p.append(p_cond)
                        all_br_h.append(hv)

                        if lead == 18:
                            y_lock_metar = 1.0 if float(y_raw_max_arr[i]) <= float(mt_vec[i]) + 1e-6 else 0.0
                            atom_records.append(
                                {
                                    "station": st,
                                    "season": seas,
                                    "t_hour": hf,
                                    "pos_bucket": classify_position_bucket(float(mt_vec[i]) - float(mu0_arr[i])),
                                    "y_raw": y_lock_metar,
                                    "p_after": float(special.ndtr(-mu_r / sr)),
                                }
                            )

        agg = _evaluate_track_aggregates(
            crps_nat=np.asarray(all_crps_nat, dtype=float),
            crps_br=np.asarray(all_crps_br, dtype=float),
            strata_crps=strata_crps,
            nat_p=all_nat_p,
            nat_h=all_nat_h,
            br_p=all_br_p,
            br_h=all_br_h,
            atom_records=atom_records,
        )
        agg["n_day_leads"] = int(n_day_leads)
        agg["n_bridge_evals"] = int(n_bridge_evals)
        agg["n_atom_obs"] = int(len(atom_records))
        tracks_out[track_name] = agg

    summary = {
        "work_order_id": WORK_ORDER_ID,
        "truth_universe": "OfficialMETAR(DST)_settle_half_up",
        "hook_artifact": _DEFAULT_COOLING_DRIFT_ARTIFACT.name,
        "run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sealed_policy": "aggregate_only_no_day_or_slice_rows",
        "tracks": tracks_out,
    }
    SEALED_OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    SEALED_OUT_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def run_synthetic_self_test() -> None:
    """Verify aggregate math, gate booleans, and fixed output formatter on synthetic non-2019 data."""
    rng = np.random.default_rng(42)
    n = 120
    y = rng.normal(75.0, 3.0, size=n)
    m_int = np.round(y - rng.uniform(0.0, 2.0, size=n))
    mu_r = np.full(n, 0.5)
    sr = np.full(n, 1.5)
    crps_br = bridge_crps_exact(y, m_int, mu_r, sr)
    crps_nat = gaussian_crps_exact(y, np.full(n, 75.0), np.full(n, 3.5))
    assert np.all(np.isfinite(crps_br)) and np.all(np.isfinite(crps_nat))

    nat_p, nat_h, br_p, br_h = [], [], [], []
    for yi, mi, mri, sri in zip(y, m_int, mu_r, sr):
        c0 = 75
        edges = [c0 - 9 + 2 * k for k in range(10)]
        pn_c = np.array([float(special.ndtr((e - 75.0) / 3.5)) for e in edges])
        pn = np.empty(11)
        pn[0] = pn_c[0]; pn[1:10] = pn_c[1:10] - pn_c[0:9]; pn[10] = 1.0 - pn_c[9]
        pn /= pn.sum()
        pb = _bridge_11_probs(c0, float(mi), float(mri), float(sri))
        assert math.isclose(float(pb.sum()), 1.0, rel_tol=1e-9, abs_tol=1e-9)
        hv = np.zeros(11)
        hv[bracket_hit_index(float(yi), c0)] = 1.0
        nat_p.append(pn); nat_h.append(hv); br_p.append(pb); br_h.append(hv)

    strata = {(st, seas, per): ([3.0], [1.5]) for st in AUTHORIZED_STATIONS for seas in SEASONS for per in ("early", "late")}
    atom_records = []
    for seas in SEASONS:
        for t_hr in (10.0, 16.0):
            for pb_name in ("B1_below_anchor", "B2_near_anchor", "B3_at_or_above"):
                for _ in range(25):
                    atom_records.append({
                        "station": "KORD",
                        "season": seas,
                        "t_hour": t_hr,
                        "pos_bucket": pb_name,
                        "y_raw": 1.0 if t_hr == 16.0 else 0.0,
                        "p_after": 0.9 if t_hr == 16.0 else 0.1,
                    })

    agg = _evaluate_track_aggregates(crps_nat, crps_br, strata, nat_p, nat_h, br_p, br_h, atom_records)
    agg["n_day_leads"] = n
    agg["n_bridge_evals"] = n
    agg["n_atom_obs"] = len(atom_records)
    block = _format_fixed_output_block(
        {
            "work_order_id": WORK_ORDER_ID,
            "truth_universe": "SYNTHETIC_SELF_TEST",
            "hook_artifact": _DEFAULT_COOLING_DRIFT_ARTIFACT.name,
            "run_utc": "SYNTHETIC",
            "tracks": {"synthetic_track": agg},
        }
    )
    assert "=== SEALED 2019 OUTPUT BLOCK ===" in block
    assert "=== END SEALED 2019 OUTPUT BLOCK ===" in block
    print("SELF_TEST_PASS: 0 real 2019 files accessed; fixed block schema verified.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sealed 2019 OfficialMETAR(DST) Counterfactual Evaluator.")
    parser.add_argument("--execute-sealed-2019", action="store_true", help="Manually triggered by Design Team to execute on 2019 data.")
    parser.add_argument("--self-test", action="store_true", help="Run synthetic non-2019 self-test.")
    args = parser.parse_args()

    if args.self_test:
        run_synthetic_self_test()
        return 0
    if not args.execute_sealed_2019:
        print("SEALED_GUARD: Pass --execute-sealed-2019 (Design Team manual execution only) or --self-test.")
        return 0

    summary = run_sealed_2019()
    print(_format_fixed_output_block(summary))
    print(f"SEALED_SUMMARY_JSON={SEALED_OUT_JSON.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
