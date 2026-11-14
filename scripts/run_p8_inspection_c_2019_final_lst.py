#!/usr/bin/env python3
"""
P8-ALGO Inspection C Final Pre-Registered Run (Branch A: GHCN LST + 5-min LST + Regularized Identifiable mu_R).

Gating Primary Universe (Appendix I Pre-Registered Gates):
- Truth: GHCN(LST) (from data/processed/truth_ghcn_daily/{station}.parquet)
- Observation stream: evidence/p8_2019_5min_lst.parquet (LST day boundary, 06:00-20:00 wall clock)
- Bridge Drift Hook: Proposal1CoolingDriftMuRHook -> evidence/p8_mu_r_lst_identifiable_calibration_20261114.json
- Frozen eta_s(t): evidence/p8_inspection_a_eta_s_calibration_20261113.csv
- S_oos Contract: v2_2000_2018_oof_cv
- Strictly code-computed booleans for G1 (G1a, G1b), G2 (G2a_608, G2a_2019, G2b), G3 (G3a, G3b, G3c),
  Tier B concentration condition, and Tier A / B / C verdict mapping.

Two Parallel Non-Gating Outputs:
1. METAR(DST) settlement-perspective bias breakdown (G-15 quantitative input).
2. M_t = OfficialMETAR(LST) observation-stream sensitivity (quantifying MADISHF 1C quantization noise).
"""

from __future__ import annotations

import itertools
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy import special, stats

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.calibrate_p8_mu_r_lst_identifiable import (
    OUT_JSON as IDENT_CAL_JSON,
    bridge_expectation,
)
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
    grade_w2_cell,
    verify_crps_formulas,
)
from scripts.rebuild_p8_lst_corpus_and_check_eta import LST_TIMEZONES
from scripts.run_p8_inspection_a_eta_calibration import (
    POSITION_BUCKETS,
    SIGMA_INST_PHYSICAL_FLOOR,
    STATION_TIMEZONES,
    T_GRID,
    classify_position_bucket,
    format_hour,
    wilson_ci,
)
from src.modeling.climatology import ClimatologyCalculator
from src.prediction.discrete_bin_engine import settle_half_up
from src.prediction.dynamic_corrector import (
    _DEFAULT_COOLING_DRIFT_ARTIFACT,
    Proposal1CoolingDriftMuRHook,
)
from scripts.run_p8_inspection_c_2019_replay import (
    CLIMATE_CALIB_PATH,
    CONTRACT_PATH,
    ETA_CAL_CSV,
    GHCN_DIR,
    IEM_DIR,
    MANIFEST_PATH,
    bracket_hit_index,
    build_2019_cell_priors,
    evaluate_11_bracket_probs_prior,
    evaluate_kmia_12h_v2_reread,
)

OBS_2019_LST_PATH = PROJECT_ROOT / "evidence" / "p8_2019_5min_lst.parquet"
OUT_JSON = PROJECT_ROOT / "evidence" / "p8_inspection_c_2019_final_lst_20261114.json"
OUT_STRATA_CSV = PROJECT_ROOT / "evidence" / "p8_inspection_c_2019_final_16strata_lst_20261114.csv"
OUT_W2_CSV = PROJECT_ROOT / "evidence" / "p8_inspection_c_2019_final_w2_22cells_lst_20261114.csv"
OUT_SLICE_232_CSV = PROJECT_ROOT / "evidence" / "p8_inspection_c_2019_final_slices_232_lst_20261114.csv"
OUT_ATOM_696_CSV = PROJECT_ROOT / "evidence" / "p8_inspection_c_2019_final_atom_696_lst_20261114.csv"
OUT_REPORT_MD = PROJECT_ROOT / "evidence" / "p8_inspection_c_2019_final_lst_report_20261114.md"

# Appendix I Pre-Registered Thresholds
G1B_MIN_IMPROVED_STRATA: int = 12
G2A_MAX_ABS_SLICE_DIFF_F: float = 2.0
G2B_MAX_STRATUM_CRPS_DEG_RATIO: float = 0.20
G3A_MAX_AFT_OUT95: int = 25
G3A_MAX_ABS_WRESID: float = 0.05
G3B_MAX_EARLY_B12_OUT95: int = 20
G3C_MAX_POOLED_ECE_BRIDGE_INW: float = 0.020


def _build_slice_summaries(obs_df: pd.DataFrame, stations: Tuple[str, ...]) -> Dict[Tuple[str, float], pd.DataFrame]:
    """Build per-(station, t_hour) running max/instant observation summaries."""
    summaries: Dict[Tuple[str, float], pd.DataFrame] = {}
    for st in stations:
        sub = obs_df[obs_df["station"] == st].copy()
        tfin_all = sub.groupby("local_date")["temp_f"].max()
        for h in T_GRID:
            hf = float(h)
            s_h = sub[sub["hour_f"] <= hf + 1e-9].sort_values("valid_utc")
            agg = s_h.groupby("local_date").agg(mt=("temp_f", "max"), xt=("temp_f", "last"))
            agg["tfin_all"] = agg.index.map(tfin_all)
            summaries[(st, hf)] = agg
    return summaries


def _compute_atomic_metrics(abdf: pd.DataFrame) -> Dict[str, Any]:
    """Aggregate G3a / G3b atomic out95 & family wResid on a filtered atomic bucket dataframe."""
    def _agg(sub: pd.DataFrame) -> Dict[str, Any]:
        if sub.empty:
            return {"cells": 0, "n_obs": 0, "wMAE": 0.0, "wResid": 0.0, "out95": 0}
        w = sub["n_bucket"].to_numpy(dtype=float)
        return {
            "cells": int(len(sub)),
            "n_obs": int(sub["n_bucket"].sum()),
            "wMAE": round(float(np.average(sub["abs_resid_after"], weights=w)), 6),
            "wResid": round(float(np.average(sub["resid_after"], weights=w)), 6),
            "out95": int(sub["outside_ci_after"].sum()),
        }

    early_b = abdf[abdf["t_hour"] <= 13.5]
    aft_b = abdf[abdf["t_hour"] >= 14.0]
    eb12 = early_b[early_b["pos_bucket"].isin(["B1_below_anchor", "B2_near_anchor"])]
    return {
        "early_B12_pooled": _agg(eb12),
        "early_B1": _agg(early_b[early_b["pos_bucket"] == "B1_below_anchor"]),
        "early_B2": _agg(early_b[early_b["pos_bucket"] == "B2_near_anchor"]),
        "early_B3": _agg(early_b[early_b["pos_bucket"] == "B3_at_or_above"]),
        "aft_total_cells": int(len(aft_b)),
        "aft_total_out95": int(aft_b["outside_ci_after"].sum()),
        "aft_kord_out95": int(aft_b[aft_b["station"] == "KORD"]["outside_ci_after"].sum()),
        "aft_kmia_out95": int(aft_b[aft_b["station"] == "KMIA"]["outside_ci_after"].sum()),
        "aft_B1": _agg(aft_b[aft_b["pos_bucket"] == "B1_below_anchor"]),
        "aft_B2": _agg(aft_b[aft_b["pos_bucket"] == "B2_near_anchor"]),
        "aft_B3": _agg(aft_b[aft_b["pos_bucket"] == "B3_at_or_above"]),
    }


def _build_atomic_buckets(atom_df: pd.DataFrame) -> pd.DataFrame:
    """Group canonical 18h snapshot records into (station, season, t_hour, pos_bucket) cells."""
    rows: List[Dict[str, Any]] = []
    for st in AUTHORIZED_STATIONS:
        for seas in SEASONS:
            for h in T_GRID:
                hf = float(h)
                for b in POSITION_BUCKETS:
                    sub = atom_df[
                        (atom_df["station"] == st)
                        & (atom_df["season"] == seas)
                        & (atom_df["t_hour"] == hf)
                        & (atom_df["pos_bucket"] == b)
                    ]
                    nb = int(len(sub))
                    if nb == 0:
                        continue
                    kb = int(sub["y_raw"].sum())
                    emp = kb / nb
                    prd = float(sub["p_after"].mean())
                    lo, hi = wilson_ci(kb, nb)
                    rows.append(
                        {
                            "station": st,
                            "season": seas,
                            "t_hour": hf,
                            "t_label": format_hour(hf),
                            "pos_bucket": b,
                            "n_bucket": nb,
                            "k_no_new": kb,
                            "emp_no_new_raw": round(emp, 6),
                            "pred_after": round(prd, 6),
                            "resid_after": round(emp - prd, 6),
                            "abs_resid_after": round(abs(emp - prd), 6),
                            "wilson95_lo": round(lo, 6),
                            "wilson95_hi": round(hi, 6),
                            "outside_ci_after": bool(prd < lo or prd > hi),
                        }
                    )
    return pd.DataFrame(rows)


def _load_official_metar_2019(station: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Load official non-MADISHF METAR rows in (1) DST daily settlement view & (2) LST intraday view."""
    df = pd.read_parquet(IEM_DIR / station / "2019.parquet").copy()
    df["valid_utc"] = pd.to_datetime(df["valid_utc"], utc=True)
    df = df.dropna(subset=["temp_f"]).copy()
    metar = df[~df["raw_metar"].astype(str).str.contains("MADISHF", na=False)].copy()
    oor = (metar["temp_f"] < -40.0) | (metar["temp_f"] > 135.0)
    metar = metar[~oor].sort_values("valid_utc").copy()

    # 1. DST calendar day view (NWS / Polymarket settlement perspective)
    tz_wall = STATION_TIMEZONES[station]
    metar["dst_dt"] = metar["valid_utc"].dt.tz_convert(tz_wall)
    metar["dst_date"] = metar["dst_dt"].dt.date
    metar_dst = metar[metar["dst_dt"].dt.year == 2019].copy()
    dst_daily = metar_dst.groupby("dst_date").agg(
        metar_dst_tmax_f=("temp_f", "max"),
        metar_dst_n_obs=("temp_f", "count"),
    ).reset_index().rename(columns={"dst_date": "target_date"})
    dst_daily["metar_dst_settled_f"] = [float(settle_half_up(float(x))) for x in dst_daily["metar_dst_tmax_f"]]

    # 2. LST calendar day boundary + wall-clock intraday hour_f (for Parallel Variant 2)
    tz_lst = LST_TIMEZONES[station]
    metar["lst_dt"] = metar["valid_utc"].dt.tz_convert(tz_lst)
    metar["local_date"] = metar["lst_dt"].dt.date
    metar_lst = metar[metar["lst_dt"].dt.year == 2019].copy()
    wall_h = metar_lst["dst_dt"].dt.hour + metar_lst["dst_dt"].dt.minute / 60.0
    same_day = metar_lst["dst_dt"].dt.date == metar_lst["local_date"]
    metar_lst["hour_f"] = np.where(same_day, wall_h, wall_h + 24.0)
    metar_lst["station"] = station

    return dst_daily, metar_lst[["station", "valid_utc", "local_date", "hour_f", "temp_f"]]


def main() -> int:
    # Check active calibration artifact & live hook wiring
    ident_cal = json.loads(IDENT_CAL_JSON.read_text(encoding="utf-8"))
    hook = Proposal1CoolingDriftMuRHook.from_calibration_artifact()
    assert _DEFAULT_COOLING_DRIFT_ARTIFACT.name == "p8_mu_r_lst_identifiable_calibration_20261114.json"
    assert hook._resolve_curve("KORD", "Spring") is not None

    g2a_608_pass = bool(ident_cal["acceptance_gates"]["g2a_608_tower_expectation_232_slices"]["pass"])
    g2a_608_max = float(ident_cal["acceptance_gates"]["g2a_608_tower_expectation_232_slices"]["max_abs_mean_ey_minus_mu0"])

    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if contract.get("s_oos_version") != "v2_2000_2018_oof_cv":
        raise RuntimeError(f"Expected v2_2000_2018_oof_cv contract, got {contract.get('s_oos_version')}")
    contract_cells = contract["cells"]
    manifest_models = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["models"]
    climate_calib = json.loads(CLIMATE_CALIB_PATH.read_text(encoding="utf-8"))
    eta_df = pd.read_csv(ETA_CAL_CSV)
    eta_map = {(str(r.station), str(r.season), float(r.t_hour)): float(r.eta_calibrated) for r in eta_df.itertuples()}

    # Family moments & CRPS lookups
    moment_map: Dict[Tuple[str, str], Tuple[str, Dict[str, Any], float, float]] = {}
    jsu_lookups: Dict[Tuple[str, str], StandardizedJSUCRPSLookup] = {}
    sample_sp = None
    for st in AUTHORIZED_STATIONS:
        for seas in SEASONS:
            info = climate_calib[st]["seasons"][seas]
            fam = str(info.get("selected_family", "gaussian"))
            sp = info.get("shape_params", {}) or {}
            ez, stdz = compute_moments_z(fam, sp)
            moment_map[(st, seas)] = (fam, sp, ez, stdz)
            if fam == "johnsonsu":
                jsu_lookups[(st, seas)] = StandardizedJSUCRPSLookup(sp)
                if sample_sp is None:
                    sample_sp = sp
    crps_formula_checks = verify_crps_formulas(sample_sp)

    # Fit strict 2000-2018 ClimatologyCalculator per station
    clim_calc = ClimatologyCalculator(train_start_year=2000, train_end_year=2018)
    for st in AUTHORIZED_STATIONS:
        ghcn_st = pd.read_parquet(GHCN_DIR / f"{st}.parquet").copy()
        ghcn_st["date"] = pd.to_datetime(ghcn_st["target_date"]).dt.strftime("%Y-%m-%d")
        ghcn_st = ghcn_st.rename(columns={"tmax_f": "temp_max"})
        ghcn_st["temp_min"] = ghcn_st["temp_max"]
        clim_calc.fit(ghcn_st, station_id=st, target_types=["max"])

    # Load Branch A 2019 LST 5-min observation stream
    obs_lst = pd.read_parquet(OBS_2019_LST_PATH).copy()
    obs_lst["valid_utc"] = pd.to_datetime(obs_lst["valid_utc"], utc=True)
    obs_lst["local_date"] = pd.to_datetime(obs_lst["local_date_str"]).dt.date
    day_summaries = _build_slice_summaries(obs_lst, AUTHORIZED_STATIONS)
    retained_dates_by_st = {st: set(obs_lst[obs_lst["station"] == st]["local_date"].unique()) for st in AUTHORIZED_STATIONS}

    # Load Parallel Official METAR 2019 streams (non-gating)
    metar_dst_daily_map: Dict[str, pd.DataFrame] = {}
    metar_lst_frames: List[pd.DataFrame] = []
    for st in AUTHORIZED_STATIONS:
        d_dst, d_mlst = _load_official_metar_2019(st)
        metar_dst_daily_map[st] = d_dst
        metar_lst_frames.append(d_mlst)
    metar_lst_df = pd.concat(metar_lst_frames, ignore_index=True)
    metar_summaries = _build_slice_summaries(metar_lst_df, AUTHORIZED_STATIONS)

    # Primary Branch A collectors
    strata_acc: Dict[Tuple[str, str, str], Dict[str, Any]] = {
        (st, seas, per): {
            "crps_nat": [], "crps_br": [], "rps_nat": [], "rps_br": [],
            "nat_p": [], "nat_h": [], "br_p": [], "br_h": [],
            "brier_nat": [], "brier_br": [], "n_days_leads": 0,
        }
        for st in AUTHORIZED_STATIONS
        for seas in SEASONS
        for per in ("early", "late")
    }
    w2_cell_rows: List[Dict[str, Any]] = []
    slice_acc_all: Dict[Tuple[str, str, float], List[float]] = {
        (st, seas, float(h)): [] for st in AUTHORIZED_STATIONS for seas in SEASONS for h in T_GRID
    }
    slice_acc_18h: Dict[Tuple[str, str, float], Dict[str, List[float]]] = {
        (st, seas, float(h)): {"ey": [], "mu0": []}
        for st in AUTHORIZED_STATIONS for seas in SEASONS for h in T_GRID
    }
    atom_obs_records: List[Dict[str, Any]] = []
    all_br_p, all_br_h, all_nat_p, all_nat_h = [], [], [], []
    all_br_st, all_br_seas, all_br_per = [], [], []

    # Parallel Variant 2 (Official METAR LST obs stream, canonical 18h + pooled CRPS/ECE) collectors
    m_obs_crps_br, m_obs_crps_5m = [], []
    m_obs_br_p, m_obs_br_h = [], []
    m_obs_5m_p, m_obs_5m_h = [], []
    m_obs_atom_records: List[Dict[str, Any]] = []

    # Parallel Variant 1 (METAR DST settlement perspective, 2019 comparison) collector
    g15_rows: List[Dict[str, Any]] = []

    for st in AUTHORIZED_STATIONS:
        valid_dates = retained_dates_by_st[st]
        for lead in AUTHORIZED_LEAD_HOURS:
            per = get_period(lead)
            df19 = build_2019_cell_priors(st, lead, manifest_models, climate_calib, contract_cells)
            df19 = df19[df19["target_date"].isin(valid_dates)].copy().reset_index(drop=True)

            dates_arr = df19["target_date"].tolist()
            seas_arr = df19["season"].tolist()
            mu0_arr = df19["mu_0"].to_numpy(dtype=float)
            s0_arr = df19["sigma_0"].to_numpy(dtype=float)
            y_arr = df19["tmax_f"].to_numpy(dtype=float)

            # G-15 settlement bias capture on 18h canonical dates (unique 2019 retained days per station)
            if lead == 18:
                mdst = metar_dst_daily_map[st]
                m_join = df19[["target_date", "season", "mu_0", "tmax_f"]].merge(mdst, on="target_date", how="inner")
                tfin_dst_ref = obs_lst[obs_lst["station"] == st].groupby("local_date")["temp_f"].max()
                for row in m_join.itertuples():
                    tf_val = tfin_dst_ref.get(row.target_date, np.nan)
                    g15_rows.append(
                        {
                            "station": st,
                            "season": row.season,
                            "target_date": str(row.target_date),
                            "ghcn_lst_f": float(row.tmax_f),
                            "madishf_lst_tfin_f": float(tf_val) if pd.notna(tf_val) else np.nan,
                            "metar_dst_raw_f": float(row.metar_dst_tmax_f),
                            "metar_dst_settled_f": float(row.metar_dst_settled_f),
                            "diff_metar_raw_minus_ghcn": float(row.metar_dst_tmax_f) - float(row.tmax_f),
                            "diff_metar_settle_minus_ghcn": float(row.metar_dst_settled_f) - float(row.tmax_f),
                            "diff_ghcn_minus_mu0": float(row.tmax_f) - float(row.mu_0),
                            "diff_metar_settle_minus_mu0": float(row.metar_dst_settled_f) - float(row.mu_0),
                        }
                    )

            crps_clim_arr = np.empty(len(df19), dtype=float)
            crps_nat_arr = np.empty(len(df19), dtype=float)
            cov90_arr = np.empty(len(df19), dtype=float)
            c0_list: List[int] = []
            hv_list: List[np.ndarray] = []
            rps_nat_arr = np.empty(len(df19), dtype=float)
            c_nat_p, c_nat_h = [], []
            c_br_p, c_br_h = [], []

            for i in range(len(df19)):
                dt = dates_arr[i]
                seas = seas_arr[i]
                mu0 = float(mu0_arr[i])
                s0 = float(s0_arr[i])
                yi = float(y_arr[i])
                fam, sp, ez, stdz = moment_map[(st, seas)]
                mm_mu = mu0 + s0 * ez
                mm_sig = s0 * stdz

                mu_cl, sig_cl = clim_calc.get_climatology(st, "max", dt)
                crps_clim_arr[i] = float(gaussian_crps_exact(np.array([yi]), np.array([mu_cl]), np.array([sig_cl]))[0])
                if fam == "johnsonsu":
                    crps_nat_arr[i] = float(jsu_lookups[(st, seas)].eval_crps(np.array([yi]), np.array([mu0]), np.array([s0]))[0])
                    lq = mu0 + s0 * float(stats.johnsonsu.ppf(0.05, sp["gamma"], sp["delta"], loc=sp["xi"], scale=sp["lambda"]))
                    uq = mu0 + s0 * float(stats.johnsonsu.ppf(0.95, sp["gamma"], sp["delta"], loc=sp["xi"], scale=sp["lambda"]))
                else:
                    crps_nat_arr[i] = float(gaussian_crps_exact(np.array([yi]), np.array([mu0]), np.array([s0]))[0])
                    lq = mu0 - 1.6448536 * s0
                    uq = mu0 + 1.6448536 * s0
                cov90_arr[i] = 1.0 if (lq <= yi <= uq) else 0.0

                c0 = int(round(mu0))
                c0_list.append(c0)
                p_nat, _, _, _ = evaluate_11_bracket_probs_prior(mu0, s0, fam, sp, c0, mm_mu, mm_sig)
                h_idx = bracket_hit_index(yi, c0)
                hv = np.zeros(11, dtype=float)
                hv[h_idx] = 1.0
                hv_list.append(hv)
                c_nat_p.append(p_nat); c_nat_h.append(hv)
                rps_nat_arr[i] = float(np.sum((np.cumsum(p_nat) - np.cumsum(hv)) ** 2))

                sc = strata_acc[(st, seas, per)]
                sc["nat_p"].append(p_nat); sc["nat_h"].append(hv)
                sc["brier_nat"].append(float(np.sum((p_nat - hv) ** 2)))
                sc["n_days_leads"] += 1
                all_nat_p.append(p_nat); all_nat_h.append(hv)

            # Intraday replay across all 29 half-hour slices
            for hf_np in T_GRID:
                hf = float(hf_np)
                obs_slice = day_summaries[(st, hf)].reindex(dates_arr)
                mt_vec = obs_slice["mt"].to_numpy(dtype=float)
                xt_vec = obs_slice["xt"].to_numpy(dtype=float)
                tfin_vec = obs_slice["tfin_all"].to_numpy(dtype=float)

                m_obs_slice = metar_summaries[(st, hf)].reindex(dates_arr)
                m_mt_vec = m_obs_slice["mt"].to_numpy(dtype=float)
                m_xt_vec = m_obs_slice["xt"].to_numpy(dtype=float)
                m_tfin_vec = m_obs_slice["tfin_all"].to_numpy(dtype=float)

                valid_idx = [i for i in range(len(df19)) if not (np.isnan(mt_vec[i]) or np.isnan(xt_vec[i]))]
                if not valid_idx:
                    continue

                m_int_v = np.empty(len(valid_idx), dtype=float)
                mu_r_v = np.empty(len(valid_idx), dtype=float)
                sr_v = np.empty(len(valid_idx), dtype=float)
                y_v = y_arr[valid_idx]
                mu0_v = mu0_arr[valid_idx]

                for j, i in enumerate(valid_idx):
                    mt_f = float(mt_vec[i])
                    xt_f = float(xt_vec[i])
                    seas = seas_arr[i]
                    mu0 = float(mu0_arr[i])
                    s0 = float(s0_arr[i])
                    m_int = float(settle_half_up(mt_f))
                    eta = eta_map[(st, seas, hf)]
                    sr = max(s0 * math.sqrt(max(eta, 0.0)), SIGMA_INST_PHYSICAL_FLOOR)
                    res_mu = hook.compute(
                        t_local=hf,
                        extreme_m=m_int,
                        instant_x_t=xt_f,
                        mu_0=mu0,
                        target_type="max",
                        station_id=st,
                        season=seas,
                    )
                    m_int_v[j] = m_int
                    mu_r_v[j] = res_mu.mu_r
                    sr_v[j] = sr

                cbr_v = bridge_crps_exact(y_v, m_int_v, mu_r_v, sr_v)
                ey_v = bridge_expectation(m_int_v, mu_r_v, sr_v)

                for j, i in enumerate(valid_idx):
                    seas = seas_arr[i]
                    m_int = float(m_int_v[j])
                    mu_r = float(mu_r_v[j])
                    sr = float(sr_v[j])
                    c0 = c0_list[i]
                    hv = hv_list[i]
                    slice_acc_all[(st, seas, hf)].append(float(ey_v[j] - mu0_v[j]))
                    if lead == 18:
                        slice_acc_18h[(st, seas, hf)]["ey"].append(float(ey_v[j]))
                        slice_acc_18h[(st, seas, hf)]["mu0"].append(float(mu0_v[j]))

                    lower = c0 - 9
                    edges = [lower + 2 * k for k in range(10)]
                    cdfs = np.array(
                        [0.0 if e <= m_int else float(special.ndtr(((e - m_int) - mu_r) / sr)) for e in edges],
                        dtype=float,
                    )
                    p_cond = np.empty(11, dtype=float)
                    p_cond[0] = cdfs[0]
                    p_cond[1:10] = np.maximum(0.0, cdfs[1:10] - cdfs[0:9])
                    p_cond[10] = max(0.0, 1.0 - cdfs[9])
                    ps = p_cond.sum()
                    if ps > 0:
                        p_cond /= ps

                    rps_br = float(np.sum((np.cumsum(p_cond) - np.cumsum(hv)) ** 2))
                    sc = strata_acc[(st, seas, per)]
                    sc["crps_nat"].append(float(crps_nat_arr[i]))
                    sc["crps_br"].append(float(cbr_v[j]))
                    sc["rps_nat"].append(float(rps_nat_arr[i]))
                    sc["rps_br"].append(rps_br)
                    sc["br_p"].append(p_cond); sc["br_h"].append(hv)
                    sc["brier_br"].append(float(np.sum((p_cond - hv) ** 2)))

                    c_br_p.append(p_cond); c_br_h.append(hv)
                    all_br_p.append(p_cond); all_br_h.append(hv)
                    all_br_st.append(st); all_br_seas.append(seas); all_br_per.append(per)

                    if lead == 18:
                        p_no_new = float(special.ndtr(-mu_r / sr))
                        y_raw = 1.0 if float(tfin_vec[i]) <= float(mt_vec[i]) + 1e-6 else 0.0
                        pb = classify_position_bucket(float(mt_vec[i]) - float(mu0_arr[i]))
                        atom_obs_records.append(
                            {
                                "station": st,
                                "season": seas,
                                "local_date": str(dates_arr[i]),
                                "t_hour": hf,
                                "pos_bucket": pb,
                                "cooling_drop": max(0.0, float(mt_vec[i]) - float(xt_vec[i])),
                                "y_raw": y_raw,
                                "p_after": p_no_new,
                                "mu_r": mu_r,
                                "sigma_rem": sr,
                            }
                        )

                        # Parallel Variant 2: OfficialMETAR(LST) obs stream on matching days (non-gating)
                        mmt = m_mt_vec[i]
                        mxt = m_xt_vec[i]
                        mtf = m_tfin_vec[i]
                        if not (np.isnan(mmt) or np.isnan(mxt) or np.isnan(mtf)):
                            m_m_int = float(settle_half_up(float(mmt)))
                            m_res = hook.compute(
                                t_local=hf,
                                extreme_m=m_m_int,
                                instant_x_t=float(mxt),
                                mu_0=float(mu0_arr[i]),
                                target_type="max",
                                station_id=st,
                                season=seas,
                            )
                            m_crps = float(
                                bridge_crps_exact(
                                    np.array([y_arr[i]]),
                                    np.array([m_m_int]),
                                    np.array([m_res.mu_r]),
                                    np.array([sr]),
                                )[0]
                            )
                            m_obs_crps_br.append(m_crps)
                            m_obs_crps_5m.append(float(cbr_v[j]))
                            mcdfs = np.array(
                                [0.0 if e <= m_m_int else float(special.ndtr(((e - m_m_int) - m_res.mu_r) / sr)) for e in edges],
                                dtype=float,
                            )
                            mp_cond = np.empty(11, dtype=float)
                            mp_cond[0] = mcdfs[0]
                            mp_cond[1:10] = np.maximum(0.0, mcdfs[1:10] - mcdfs[0:9])
                            mp_cond[10] = max(0.0, 1.0 - mcdfs[9])
                            mps = mp_cond.sum()
                            if mps > 0:
                                mp_cond /= mps
                            m_obs_br_p.append(mp_cond); m_obs_br_h.append(hv)
                            m_obs_5m_p.append(p_cond); m_obs_5m_h.append(hv)
                            m_obs_atom_records.append(
                                {
                                    "station": st,
                                    "season": seas,
                                    "t_hour": hf,
                                    "pos_bucket": classify_position_bucket(float(mmt) - float(mu0_arr[i])),
                                    "y_raw": 1.0 if float(mtf) <= float(mmt) + 1e-6 else 0.0,
                                    "p_after": float(special.ndtr(-m_res.mu_r / sr)),
                                }
                            )

            # W2 22-cell scorecard row (D1 = inw main, w20 companion)
            ece_nat_inw = compute_ece_inw(np.concatenate(c_nat_p), np.concatenate(c_nat_h))
            ece_nat_w20 = compute_ece_w20(np.concatenate(c_nat_p), np.concatenate(c_nat_h))
            ece_br_inw = compute_ece_inw(np.concatenate(c_br_p), np.concatenate(c_br_h))
            ece_br_w20 = compute_ece_w20(np.concatenate(c_br_p), np.concatenate(c_br_h))
            bias_val = float(np.mean(mu0_arr - y_arr))
            crps_nat_mean = float(np.mean(crps_nat_arr))
            crps_clim_mean = float(np.mean(crps_clim_arr))
            crpss_val = float(1.0 - crps_nat_mean / crps_clim_mean)
            cov90_val = float(np.mean(cov90_arr))

            d1_inw, d2, d3, d4, ov_inw, sc_inw = grade_w2_cell(ece_br_inw if False else ece_nat_inw, bias_val, crpss_val, cov90_val)
            d1_w20, _, _, _, ov_w20, sc_w20 = grade_w2_cell(ece_nat_w20, bias_val, crpss_val, cov90_val)
            w2_cell_rows.append(
                {
                    "cell": f"{st}_{lead}h",
                    "station": st,
                    "lead_hours": lead,
                    "period": per,
                    "n_days": int(len(df19)),
                    "c_v2": round(float(df19["c_v2"].iloc[0]), 6),
                    "ece_inw": round(ece_nat_inw, 6),
                    "ece_w20": round(ece_nat_w20, 6),
                    "ece_bridge_inw": round(ece_br_inw, 6),
                    "ece_bridge_w20": round(ece_br_w20, 6),
                    "bias_f": round(bias_val, 4),
                    "crps_native": round(crps_nat_mean, 4),
                    "crps_clim": round(crps_clim_mean, 4),
                    "crpss": round(crpss_val, 4),
                    "cov90": round(cov90_val, 4),
                    "tier_d1_inw": d1_inw,
                    "tier_d1_w20": d1_w20,
                    "tier_d2_bias": d2,
                    "tier_d3_crpss": d3,
                    "tier_d4_cov90": d4,
                    "overall_inw": ov_inw,
                    "scale_inw": sc_inw,
                    "overall_w20": ov_w20,
                    "scale_w20": sc_w20,
                }
            )

    # Summarize 16 strata + pooled CRPS/ECE (Branch A Gating)
    strata_rows: List[Dict[str, Any]] = []
    all_c_nat, all_c_br, all_r_nat, all_r_br = [], [], [], []
    n_strata_improved = 0
    max_strata_deg_ratio = -999.0

    for st in AUTHORIZED_STATIONS:
        for seas in SEASONS:
            fam = moment_map[(st, seas)][0]
            for per in ("early", "late"):
                sc = strata_acc[(st, seas, per)]
                cn = float(np.mean(sc["crps_nat"]))
                cb = float(np.mean(sc["crps_br"]))
                rn = float(np.mean(sc["rps_nat"]))
                rb = float(np.mean(sc["rps_br"]))
                deg_ratio = (cb - cn) / max(cn, 1e-12)
                improved = bool(cb < cn)
                if improved:
                    n_strata_improved += 1
                max_strata_deg_ratio = max(max_strata_deg_ratio, deg_ratio)

                en_inw = compute_ece_inw(np.concatenate(sc["nat_p"]), np.concatenate(sc["nat_h"]))
                eb_inw = compute_ece_inw(np.concatenate(sc["br_p"]), np.concatenate(sc["br_h"]))
                en_w20 = compute_ece_w20(np.concatenate(sc["nat_p"]), np.concatenate(sc["nat_h"]))
                eb_w20 = compute_ece_w20(np.concatenate(sc["br_p"]), np.concatenate(sc["br_h"]))

                all_c_nat.extend(sc["crps_nat"])
                all_c_br.extend(sc["crps_br"])
                all_r_nat.extend(sc["rps_nat"])
                all_r_br.extend(sc["rps_br"])

                strata_rows.append(
                    {
                        "station": st,
                        "season": seas,
                        "period": per,
                        "family": fam,
                        "n_cell_days": int(sc["n_days_leads"]),
                        "crps_native": round(cn, 6),
                        "crps_bridge": round(cb, 6),
                        "crps_diff_pct": round(100.0 * deg_ratio, 3),
                        "pass_g1_stratum_improved": improved,
                        "pass_g2b_deg_le_20pct": bool(deg_ratio <= G2B_MAX_STRATUM_CRPS_DEG_RATIO),
                        "rps_native": round(rn, 6),
                        "rps_bridge": round(rb, 6),
                        "ece_native_inw": round(en_inw, 6),
                        "ece_bridge_inw": round(eb_inw, 6),
                        "delta_bridge_inw": round(eb_inw - en_inw, 6),
                        "ece_native_w20": round(en_w20, 6),
                        "ece_bridge_w20": round(eb_w20, 6),
                    }
                )
    pd.DataFrame(strata_rows).to_csv(OUT_STRATA_CSV, index=False)
    pd.DataFrame(w2_cell_rows).to_csv(OUT_W2_CSV, index=False)

    pooled_crps_nat = float(np.mean(all_c_nat))
    pooled_crps_br = float(np.mean(all_c_br))
    pooled_rps_nat = float(np.mean(all_r_nat))
    pooled_rps_br = float(np.mean(all_r_br))
    pooled_ece_nat_inw = compute_ece_inw(np.concatenate(all_nat_p), np.concatenate(all_nat_h))
    pooled_ece_br_inw = compute_ece_inw(np.concatenate(all_br_p), np.concatenate(all_br_h))
    pooled_ece_nat_w20 = compute_ece_w20(np.concatenate(all_nat_p), np.concatenate(all_nat_h))
    pooled_ece_br_w20 = compute_ece_w20(np.concatenate(all_br_p), np.concatenate(all_br_h))

    # G2a 2019 232 slices
    slice_232_rows: List[Dict[str, Any]] = []
    for st in AUTHORIZED_STATIONS:
        for seas in SEASONS:
            for h in T_GRID:
                hf = float(h)
                diffs_all = slice_acc_all[(st, seas, hf)]
                ey18 = slice_acc_18h[(st, seas, hf)]["ey"]
                mu18 = slice_acc_18h[(st, seas, hf)]["mu0"]
                m_all = float(np.mean(diffs_all))
                m_18 = float(np.mean(ey18) - np.mean(mu18))
                slice_232_rows.append(
                    {
                        "station": st,
                        "season": seas,
                        "t_hour": hf,
                        "t_label": format_hour(hf),
                        "n_days_18h": int(len(ey18)),
                        "mean_ey_18h": round(float(np.mean(ey18)), 6),
                        "mean_mu0_18h": round(float(np.mean(mu18)), 6),
                        "diff_18h": round(m_18, 6),
                        "abs_diff_18h": round(abs(m_18), 6),
                        "diff_all_leads": round(m_all, 6),
                        "abs_diff_all_leads": round(abs(m_all), 6),
                        "pass_g2a_both_le_2_0": bool(abs(m_18) <= G2A_MAX_ABS_SLICE_DIFF_F and abs(m_all) <= G2A_MAX_ABS_SLICE_DIFF_F),
                    }
                )
    slice_232_df = pd.DataFrame(slice_232_rows)
    slice_232_df.to_csv(OUT_SLICE_232_CSV, index=False)
    g2a_2019_18h_max = float(slice_232_df["abs_diff_18h"].max())
    g2a_2019_all_max = float(slice_232_df["abs_diff_all_leads"].max())
    g2a_2019_pass = bool(g2a_2019_18h_max <= G2A_MAX_ABS_SLICE_DIFF_F and g2a_2019_all_max <= G2A_MAX_ABS_SLICE_DIFF_F)

    # 696-atom replay summary & G3 gates
    atom_df = pd.DataFrame(atom_obs_records)
    abdf = _build_atomic_buckets(atom_df)
    abdf.to_csv(OUT_ATOM_696_CSV, index=False)
    atom_metrics = _compute_atomic_metrics(abdf)

    g1a = bool(pooled_crps_br < pooled_crps_nat)
    g1b = bool(n_strata_improved >= G1B_MIN_IMPROVED_STRATA)
    g1 = bool(g1a and g1b)

    g2a = bool(g2a_608_pass and g2a_2019_pass)
    g2b = bool(max_strata_deg_ratio <= G2B_MAX_STRATUM_CRPS_DEG_RATIO)
    g2 = bool(g2a and g2b)

    g3a_out95 = bool(atom_metrics["aft_total_out95"] <= G3A_MAX_AFT_OUT95)
    g3a_b1 = bool(abs(atom_metrics["aft_B1"]["wResid"]) <= G3A_MAX_ABS_WRESID)
    g3a_b2 = bool(abs(atom_metrics["aft_B2"]["wResid"]) <= G3A_MAX_ABS_WRESID)
    g3a_b3 = bool(abs(atom_metrics["aft_B3"]["wResid"]) <= G3A_MAX_ABS_WRESID)
    g3a = bool(g3a_out95 and g3a_b1 and g3a_b2 and g3a_b3)
    g3b = bool(atom_metrics["early_B12_pooled"]["out95"] <= G3B_MAX_EARLY_B12_OUT95)
    g3c = bool(pooled_ece_br_inw <= G3C_MAX_POOLED_ECE_BRIDGE_INW)
    g3 = bool(g3a and g3b and g3c)

    # Concentration condition evaluation in code (for Tier B when G1 and G2 and not G3)
    station_seasons = [(st, seas) for st in AUTHORIZED_STATIONS for seas in SEASONS]
    best_tier_b_drop: List[Dict[str, Any]] = []
    # Precompute 2019 GHCN anomaly per (station, season) vs 2000-2018 baseline mu0 for attribution check
    g15_df = pd.DataFrame(g15_rows)
    ss_drift_map: Dict[Tuple[str, str], float] = {}
    for (st, seas), g in g15_df.groupby(["station", "season"]):
        ss_drift_map[(str(st), str(seas))] = float(g["diff_ghcn_minus_mu0"].mean())

    concentration_cond = False
    if g1 and g2 and (not g3):
        arr_st = np.array(all_br_st)
        arr_seas = np.array(all_br_seas)
        for k_drop in (1, 2):
            for combo in itertools.combinations(station_seasons, k_drop):
                drop_set = set(combo)
                keep_ab = abdf[~abdf.apply(lambda r: (r["station"], r["season"]) in drop_set, axis=1)]
                m_sub = _compute_atomic_metrics(keep_ab)
                keep_mask = np.array([(s, se) not in drop_set for s, se in zip(arr_st, arr_seas)], dtype=bool)
                # Subset pooled ECE_bridge(inw): concatenate arrays of kept evaluations
                kp = np.concatenate([all_br_p[i] for i, ok in enumerate(keep_mask) if ok])
                kh = np.concatenate([all_br_h[i] for i, ok in enumerate(keep_mask) if ok])
                sub_ece = compute_ece_inw(kp, kh)
                sub_g3 = bool(
                    m_sub["aft_total_out95"] <= G3A_MAX_AFT_OUT95
                    and abs(m_sub["aft_B1"]["wResid"]) <= G3A_MAX_ABS_WRESID
                    and abs(m_sub["aft_B2"]["wResid"]) <= G3A_MAX_ABS_WRESID
                    and abs(m_sub["aft_B3"]["wResid"]) <= G3A_MAX_ABS_WRESID
                    and m_sub["early_B12_pooled"]["out95"] <= G3B_MAX_EARLY_B12_OUT95
                    and sub_ece <= G3C_MAX_POOLED_ECE_BRIDGE_INW
                )
                if sub_g3:
                    # Check whether dropped strata have regime-drift attribution (|2019 bias| >= 0.40F or aft out95 spike)
                    attrs = [
                        {
                            "station": st_d,
                            "season": se_d,
                            "mean_ghcn_minus_mu0_f": round(ss_drift_map[(st_d, se_d)], 4),
                            "aft_out95": int(abdf[(abdf["station"] == st_d) & (abdf["season"] == se_d) & (abdf["t_hour"] >= 14.0)]["outside_ci_after"].sum()),
                        }
                        for (st_d, se_d) in combo
                    ]
                    best_tier_b_drop.append(
                        {
                            "k_dropped": k_drop,
                            "dropped": attrs,
                            "remaining_aft_out95": m_sub["aft_total_out95"],
                            "remaining_early_b12_out95": m_sub["early_B12_pooled"]["out95"],
                            "remaining_aft_wResid": {
                                "B1": m_sub["aft_B1"]["wResid"],
                                "B2": m_sub["aft_B2"]["wResid"],
                                "B3": m_sub["aft_B3"]["wResid"],
                            },
                            "remaining_pooled_ece_inw": round(sub_ece, 6),
                        }
                    )
            if best_tier_b_drop:
                break
        if best_tier_b_drop:
            concentration_cond = bool(
                all(abs(x["mean_ghcn_minus_mu0_f"]) >= 0.30 or x["aft_out95"] >= 10 for x in best_tier_b_drop[0]["dropped"])
            )

    if g1 and g2 and g3:
        verdict_code = "TIER_A"
        verdict_label = "A 档（放行可签）"
    elif g1 and g2 and (not g3) and concentration_cond:
        verdict_code = "TIER_B"
        verdict_label = "B 档（缩范围可签）"
    else:
        verdict_code = "TIER_C"
        verdict_label = "C 档（终止可签）"

    # Focus Item 1: KORD Spring / Autumn afternoon & Round-2 6 cells + per-stratum out95 table
    aft_only = abdf[abdf["t_hour"] >= 14.0]
    aft_out95_by_ss: List[Dict[str, Any]] = []
    for st in AUTHORIZED_STATIONS:
        for seas in SEASONS:
            sub = aft_only[(aft_only["station"] == st) & (aft_only["season"] == seas)]
            w = sub["n_bucket"].to_numpy(dtype=float)
            aft_out95_by_ss.append(
                {
                    "station": st,
                    "season": seas,
                    "cells": int(len(sub)),
                    "out95": int(sub["outside_ci_after"].sum()),
                    "wMAE": round(float(np.average(sub["abs_resid_after"], weights=w)), 6),
                    "wResid": round(float(np.average(sub["resid_after"], weights=w)), 6),
                    "mean_ghcn_minus_mu0_2019": round(ss_drift_map[(st, seas)], 4),
                }
            )

    round2_6_keys = [
        ("KORD", "Spring", 14.0, "B2_near_anchor"),
        ("KORD", "Spring", 14.0, "B3_at_or_above"),
        ("KORD", "Spring", 14.5, "B2_near_anchor"),
        ("KORD", "Spring", 14.5, "B3_at_or_above"),
        ("KORD", "Spring", 15.5, "B2_near_anchor"),
        ("KORD", "Autumn", 14.0, "B3_at_or_above"),
    ]
    focus1_6cells = []
    for st, seas, hf, pb in round2_6_keys:
        m = abdf[(abdf["station"] == st) & (abdf["season"] == seas) & (abdf["t_hour"] == hf) & (abdf["pos_bucket"] == pb)]
        if not m.empty:
            focus1_6cells.append(m.iloc[0].to_dict())

    # Focus Item 2: KMIA Winter early (CRPS, ECE_inw, W2, early atom)
    kmia_w_early_stratum = next(r for r in strata_rows if r["station"] == "KMIA" and r["season"] == "Winter" and r["period"] == "early")
    kmia_w_early_atom = _compute_atomic_metrics(abdf[(abdf["station"] == "KMIA") & (abdf["season"] == "Winter")])["early_B12_pooled"]

    # Focus Item 3: KMIA_12h v2 reread (inw YELLOW vs w20 0.0205 observation)
    c_kmia12_v2 = float(contract_cells["KMIA_12h"]["s_oos"])
    c_kmia12_v1 = float(contract_cells["KMIA_12h"]["s_oos_historical"]["v1_2019_in_sample"]["s_oos"])
    kmia12_cv_reread = evaluate_kmia_12h_v2_reread(c_kmia12_v2, c_kmia12_v1)
    kmia12_2019_cell = next(r for r in w2_cell_rows if r["cell"] == "KMIA_12h")

    # Non-Gating Parallel Output 1: METAR(DST) Settlement Perspective Breakdown (G-15 input)
    g15_summary: Dict[str, Any] = {"non_gating": True, "stations": {}}
    for st in AUTHORIZED_STATIONS:
        sg = g15_df[g15_df["station"] == st]
        d_raw = sg["diff_metar_raw_minus_ghcn"].to_numpy(dtype=float)
        d_set = sg["diff_metar_settle_minus_ghcn"].to_numpy(dtype=float)
        by_seas = {}
        for seas, sgg in sg.groupby("season"):
            ds = sgg["diff_metar_settle_minus_ghcn"].to_numpy(dtype=float)
            by_seas[str(seas)] = {
                "n_days": int(len(sgg)),
                "mean_metar_settle_minus_ghcn": round(float(np.mean(ds)), 4),
                "mean_abs_diff": round(float(np.mean(np.abs(ds))), 4),
                "frac_abs_ge_2f": round(float(np.mean(np.abs(ds) >= 2.0)), 4),
            }
        oct2 = sg[sg["target_date"] == "2019-10-02"]
        g15_summary["stations"][st] = {
            "n_days": int(len(sg)),
            "mean_metar_raw_minus_ghcn_f": round(float(np.mean(d_raw)), 4),
            "mean_metar_settle_minus_ghcn_f": round(float(np.mean(d_set)), 4),
            "mae_metar_settle_vs_ghcn_f": round(float(np.mean(np.abs(d_set))), 4),
            "frac_zero_diff": round(float(np.mean(np.abs(d_set) < 1e-6)), 4),
            "frac_abs_ge_2f": round(float(np.mean(np.abs(d_set) >= 2.0)), 4),
            "max_abs_diff_f": round(float(np.max(np.abs(d_set))), 4),
            "by_season": by_seas,
            "oct_02_check": oct2.iloc[0].to_dict() if not oct2.empty else None,
        }

    # Non-Gating Parallel Output 2: M_t = OfficialMETAR(LST) Obs-Stream Sensitivity
    m_abdf = _build_atomic_buckets(pd.DataFrame(m_obs_atom_records))
    m_atom_metrics = _compute_atomic_metrics(m_abdf)
    m_crps_mean = float(np.mean(m_obs_crps_br))
    m_crps_5m_matched = float(np.mean(m_obs_crps_5m))
    m_ece_inw = compute_ece_inw(np.concatenate(m_obs_br_p), np.concatenate(m_obs_br_h))
    m_ece_5m_matched = compute_ece_inw(np.concatenate(m_obs_5m_p), np.concatenate(m_obs_5m_h))
    parallel2_metar_obs = {
        "non_gating": True,
        "matched_18h_snapshots": int(len(m_obs_crps_br)),
        "crps_bridge_official_metar_lst": round(m_crps_mean, 6),
        "crps_bridge_5min_matched": round(m_crps_5m_matched, 6),
        "crps_diff_metar_minus_5min": round(m_crps_mean - m_crps_5m_matched, 6),
        "ece_bridge_inw_official_metar_lst": round(m_ece_inw, 6),
        "ece_bridge_inw_5min_matched": round(m_ece_5m_matched, 6),
        "ece_diff_metar_minus_5min": round(m_ece_inw - m_ece_5m_matched, 6),
        "atom_official_metar_lst": m_atom_metrics,
    }

    # W2 Summary counts under inw (primary) and w20 (companion)
    w2_df = pd.DataFrame(w2_cell_rows)
    w2_summary = {
        "total_cells": int(len(w2_df)),
        "inw_overall_counts": w2_df["overall_inw"].value_counts().to_dict(),
        "w20_overall_counts": w2_df["overall_w20"].value_counts().to_dict(),
        "inw_d1_counts": w2_df["tier_d1_inw"].value_counts().to_dict(),
        "w20_d1_counts": w2_df["tier_d1_w20"].value_counts().to_dict(),
    }

    payload = {
        "schema_version": "p8_inspection_c_2019_final_lst_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "branch": "A (Primary Truth = GHCN(LST); Primary Obs = 5-min MADISHF+IEM(LST))",
        "crps_formula_checks": crps_formula_checks,
        "pooled_gating_metrics": {
            "n_11bin_evals": int(len(all_br_p)),
            "crps_native": round(pooled_crps_nat, 6),
            "crps_bridge": round(pooled_crps_br, 6),
            "crps_change_pct": round(100.0 * (pooled_crps_br - pooled_crps_nat) / pooled_crps_nat, 3),
            "rps_native": round(pooled_rps_nat, 6),
            "rps_bridge": round(pooled_rps_br, 6),
            "ece_native_inw": round(pooled_ece_nat_inw, 6),
            "ece_bridge_inw": round(pooled_ece_br_inw, 6),
            "delta_bridge_inw": round(pooled_ece_br_inw - pooled_ece_nat_inw, 6),
            "ece_native_w20": round(pooled_ece_nat_w20, 6),
            "ece_bridge_w20": round(pooled_ece_br_w20, 6),
            "n_strata_crps_improved": n_strata_improved,
            "max_stratum_crps_deg_ratio": round(max_strata_deg_ratio, 6),
        },
        "atomic_gating_metrics": atom_metrics,
        "g2a_2019_232_slices": {
            "max_abs_diff_18h": round(g2a_2019_18h_max, 6),
            "max_abs_diff_all_leads": round(g2a_2019_all_max, 6),
            "threshold": G2A_MAX_ABS_SLICE_DIFF_F,
            "n_violations": int((~slice_232_df["pass_g2a_both_le_2_0"]).sum()),
            "pass": g2a_2019_pass,
            "top5_slices": slice_232_df.sort_values("abs_diff_18h", ascending=False).head(5).to_dict(orient="records"),
        },
        "pre_registered_gates": {
            "G1": {
                "G1a_pooled_crps_bridge_lt_native": g1a,
                "pooled_crps_bridge": round(pooled_crps_br, 6),
                "pooled_crps_native": round(pooled_crps_nat, 6),
                "G1b_strata_improved_ge_12_of_16": g1b,
                "n_strata_improved": n_strata_improved,
                "pass": g1,
            },
            "G2": {
                "G2a_608_max_abs_f": round(g2a_608_max, 6),
                "G2a_608_pass": g2a_608_pass,
                "G2a_2019_18h_max_abs_f": round(g2a_2019_18h_max, 6),
                "G2a_2019_all_leads_max_abs_f": round(g2a_2019_all_max, 6),
                "G2a_2019_pass": g2a_2019_pass,
                "G2a_pass": g2a,
                "G2b_max_stratum_deg_ratio": round(max_strata_deg_ratio, 6),
                "G2b_threshold": G2B_MAX_STRATUM_CRPS_DEG_RATIO,
                "G2b_pass": g2b,
                "pass": g2,
            },
            "G3": {
                "G3a_aft_out95": atom_metrics["aft_total_out95"],
                "G3a_aft_out95_pass_le_25": g3a_out95,
                "G3a_aft_B1_wResid": atom_metrics["aft_B1"]["wResid"],
                "G3a_aft_B2_wResid": atom_metrics["aft_B2"]["wResid"],
                "G3a_aft_B3_wResid": atom_metrics["aft_B3"]["wResid"],
                "G3a_pass": g3a,
                "G3b_early_B12_out95": atom_metrics["early_B12_pooled"]["out95"],
                "G3b_early_B12_cells": atom_metrics["early_B12_pooled"]["cells"],
                "G3b_pass_le_20": g3b,
                "G3c_pooled_ece_bridge_inw": round(pooled_ece_br_inw, 6),
                "G3c_pass_le_0_020": g3c,
                "pass": g3,
            },
            "concentration_cond": concentration_cond,
            "tier_b_drop_candidates": best_tier_b_drop,
            "verdict_code": verdict_code,
            "verdict_label": verdict_label,
        },
        "w2_22cell_summary": w2_summary,
        "focus_items": {
            "focus_1_aft_out95_by_station_season": aft_out95_by_ss,
            "focus_1_round2_6_cells_in_2019": focus1_6cells,
            "focus_2_kmia_winter_early_stratum": kmia_w_early_stratum,
            "focus_2_kmia_winter_early_atom": kmia_w_early_atom,
            "focus_3_kmia_12h_v2_cv_reread": kmia12_cv_reread,
            "focus_3_kmia_12h_2019_cell": kmia12_2019_cell,
        },
        "non_gating_parallel_1_metar_dst_settlement_g15": g15_summary,
        "non_gating_parallel_2_official_metar_lst_obs": parallel2_metar_obs,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # Build Markdown Verdict Report
    lines = [
        "# P8-ALGO 检验 C 2019 终跑与预注册判决报告（分支 A：GHCN(LST) + 5min(LST)）",
        "",
        f"- **执行日期**: 2026-11-14 | **脚本**: [`scripts/run_p8_inspection_c_2019_final_lst.py`](../scripts/run_p8_inspection_c_2019_final_lst.py)",
        "- **分支与输入**: 分支 A 主门禁宇宙 (`Truth = GHCN(LST)`，`Obs = evidence/p8_2019_5min_lst.parquet`)；现役 hook 加载 [`evidence/p8_mu_r_lst_identifiable_calibration_20261114.json`](p8_mu_r_lst_identifiable_calibration_20261114.json) 与 `v2_2000_2018_oof_cv` `s_oos`。",
        "",
        f"## 一、 预注册总裁决（严格代码布尔） → **`{verdict_label}`** (`{verdict_code}`)",
        "",
        f"- **G1（桥必须交付真实预测价值）**: `G1 = {g1}` (`G1a={g1a}`, `G1b={g1b}`)",
        f"  - G1a 全池连续 CRPS: 原始观测值 = `CRPS_bridge {pooled_crps_br:.6f}°F` vs `CRPS_native {pooled_crps_nat:.6f}°F` (`{payload['pooled_gating_metrics']['crps_change_pct']:+.2f}%`); 判定阈值 = `CRPS_bridge < CRPS_native`; 结论 = `{'通过' if g1a else '不通过'}`",
        f"  - G1b 分层改善数量: 原始观测值 = `{n_strata_improved}/16`; 判定阈值 = `≥ 12/16`; 结论 = `{'通过' if g1b else '不通过'}`",
        f"- **G2（桥不得出现结构性病态）**: `G2 = {g2}` (`G2a={g2a}`, `G2b={g2b}`)",
        f"  - G2a 232 切片塔性质偏差: 原始观测值 = `608d max={g2a_608_max:.4f}°F`, `2019(18h) max={g2a_2019_18h_max:.4f}°F`, `2019(22-cell) max={g2a_2019_all_max:.4f}°F`; 判定阈值 = 全部 232 切片 `≤ 2.0°F`; 结论 = `{'通过' if g2a else '不通过'}`",
        f"  - G2b 分层最大 CRPS 退化比: 原始观测值 = `{max_strata_deg_ratio:+.4f}` (`{max_strata_deg_ratio*100:+.2f}%`); 判定阈值 = `≤ +0.20 (+20%)`; 结论 = `{'通过' if g2b else '不通过'}`",
        f"- **G3（原子口径 OOS 与全池理性上限）**: `G3 = {g3}` (`G3a={g3a}`, `G3b={g3b}`, `G3c={g3c}`)",
        f"  - G3a 2019 午后原子: 原始观测值 = `out95 {atom_metrics['aft_total_out95']}/312`, `B1 wResid {atom_metrics['aft_B1']['wResid']:+.6f}`, `B2 wResid {atom_metrics['aft_B2']['wResid']:+.6f}`, `B3 wResid {atom_metrics['aft_B3']['wResid']:+.6f}`; 判定阈值 = `out95 ≤ 25/312` 且各族 `|wResid| ≤ 0.05`; 结论 = `{'通过' if g3a else '不通过'}`",
        f"  - G3b 2019 早段 B12: 原始观测值 = `out95 {atom_metrics['early_B12_pooled']['out95']}/{atom_metrics['early_B12_pooled']['cells']}`; 判定阈值 = `≤ 20`; 结论 = `{'通过' if g3b else '不通过'}`",
        f"  - G3c 全池理性上限: 原始观测值 = `ECE_bridge(inw) {pooled_ece_br_inw:.6f}` (native `{pooled_ece_nat_inw:.6f}`, Δ=`{pooled_ece_br_inw-pooled_ece_nat_inw:+.6f}`); 判定阈值 = `≤ 0.020`; 结论 = `{'通过' if g3c else '不通过'}`",
        f"- **B 档集中度条件**: `concentration_cond = {concentration_cond}` | 候选剔除方案 = `{json.dumps(best_tier_b_drop, ensure_ascii=False)}`",
        "",
        "## 二、 16 层 CRPS & ECE 分层表现",
        "",
        "| 站 | 季 | 时段 | 分布 | CRPS_nat | CRPS_br | Δ% | G1 | G2b | ECE_nat(inw) | ECE_br(inw) |",
        "|:--|:--|:---|:---|---:|---:|---:|:---:|:---:|---:|---:|",
    ]
    for r in strata_rows:
        lines.append(
            f"| {r['station']} | {r['season']} | {r['period']} | {r['family']} | {r['crps_native']:.4f} | {r['crps_bridge']:.4f} | {r['crps_diff_pct']:+.2f}% | {r['pass_g1_stratum_improved']} | {r['pass_g2b_deg_le_20pct']} | {r['ece_native_inw']:.6f} | {r['ece_bridge_inw']:.6f} |"
        )

    lines.extend(["", "## 三、 平行非门禁对照输出（不参与 A/B/C 裁决）", ""])
    lines.append(
        f"1. **METAR(DST) 结算视角偏差分解（G-15 输入）**: "
        + f"KORD `mean(METAR_settle - GHCN) = {g15_summary['stations']['KORD']['mean_metar_settle_minus_ghcn_f']:+.4f}°F` (`|diff|≥2°F: {g15_summary['stations']['KORD']['frac_abs_ge_2f']*100:.1f}%`, `2019-10-02 diff={g15_summary['stations']['KORD']['oct_02_check']['diff_metar_settle_minus_ghcn']:+.2f}°F`); "
        + f"KMIA `mean(METAR_settle - GHCN) = {g15_summary['stations']['KMIA']['mean_metar_settle_minus_ghcn_f']:+.4f}°F` (`|diff|≥2°F: {g15_summary['stations']['KMIA']['frac_abs_ge_2f']*100:.1f}%`)."
    )
    lines.append(
        f"2. **M_t = OfficialMETAR(LST) 观测流敏感性（量化 MADISHF 整度量化噪声）**: 匹配 18h 快照 `n={parallel2_metar_obs['matched_18h_snapshots']}`，"
        + f"`CRPS_bridge(OfficialMETAR) = {m_crps_mean:.6f}°F` vs `CRPS_bridge(5min) = {m_crps_5m_matched:.6f}°F` (`diff={m_crps_mean - m_crps_5m_matched:+.6f}`); "
        + f"`ECE_bridge_inw(OfficialMETAR) = {m_ece_inw:.6f}` vs `5min {m_ece_5m_matched:.6f}` (`diff={m_ece_inw - m_ece_5m_matched:+.6f}`); "
        + f"午后原子 `out95={m_atom_metrics['aft_total_out95']}/{m_atom_metrics['aft_total_cells']}`。"
    )

    OUT_REPORT_MD.write_text("\n".join(lines), encoding="utf-8")

    print("=== TASK 3: INSPECTION C 2019 FINAL LST VERDICT ===")
    print("pre_registered_gates:", json.dumps(payload["pre_registered_gates"], indent=2, ensure_ascii=False))
    print("pooled_gating_metrics:", json.dumps(payload["pooled_gating_metrics"], indent=2))
    print("w2_22cell_summary:", json.dumps(w2_summary, indent=2))
    print("kmia_12h_v2_reread:", json.dumps(kmia12_cv_reread, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
