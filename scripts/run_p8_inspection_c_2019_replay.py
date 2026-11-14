#!/usr/bin/env python3
"""
Task 4 — P8-ALGO Inspection C: 2019 Full-Year D+0 5-Minute Replay & Bridge-ECE Audit Engine.

Strict compliance:
- Consumes strictly v2 (2000-2018 OOF) s_oos, Round-2 rho_s,se(t) released mu_R curves wired
  in src/prediction/dynamic_corrector.py (Proposal1CoolingDriftMuRHook), and Inspection A eta_s(t).
- Warm-starts causal b30 from 2018-11..2018-12 residuals prior to 2019-01-01 (zero future leakage).
- Replays full 2019 5-min MADISHF observations (QC filtered matching TemperatureSanitizer gates)
  across all 22 statutory (station in {KORD, KMIA}, lead in 12h..72h) cells and 29 half-hour grid points.
- Outputs co-originated (ECE_native, ECE_bridge, ECE_gauss, Delta_bridge) across all 16
  (station x season x early/late) strata under both `inw` (8 strata) and `w20` (20 bins),
  2019 strictly-OOS intraday atom calibration checks (Criteria 1 / 2' / 3), and all 3 owner focus items:
    (1) KORD Spring/Autumn afternoon transition window (6 residual cells from Round 2)
    (2) KMIA Winter early (native ECE vs bridge ECE breakdown)
    (3) KMIA_12h 0.0183 flagged reading re-read under v2 contract s_oos
- Does NOT declare alpha PASS/FAIL verdict: outputs complete raw metrics for owner sign-off.
"""

from __future__ import annotations

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

from scripts.compute_p8_oos_and_shape_calibration import (
    AUTHORIZED_LEAD_HOURS,
    AUTHORIZED_STATIONS,
    SEASONS,
    compute_ece_inw,
    compute_ece_w20,
    compute_moments_z,
    get_period,
    get_season,
)
from scripts.run_p6_fullgrid_tmax import construct_true_model_cdf
from scripts.run_p8_inspection_a_eta_calibration import (
    MIN_MADISHF_OBS_PER_DAY,
    POSITION_BUCKETS,
    SIGMA_INST_PHYSICAL_FLOOR,
    STATION_TIMEZONES,
    T_GRID,
    classify_position_bucket,
    format_hour,
    sha256_file,
    wilson_ci,
)
from src.prediction.discrete_bin_engine import settle_half_up
from src.prediction.dynamic_corrector import (
    _DEFAULT_COOLING_DRIFT_ARTIFACT,
    Proposal1CoolingDriftMuRHook,
)

CONTRACT_PATH = PROJECT_ROOT / "data" / "contracts" / "physical_param_contract.json"
MANIFEST_PATH = PROJECT_ROOT / "data" / "models" / "manifest.json"
CLIMATE_CALIB_PATH = PROJECT_ROOT / "evidence" / "p4_active10_climate_calibration.json"
ETA_CAL_CSV = PROJECT_ROOT / "evidence" / "p8_inspection_a_eta_s_calibration_20261113.csv"
GEFS_DIR = PROJECT_ROOT / "data" / "processed" / "calib-dataset-v2.0" / "gefs_factors"
GHCN_DIR = PROJECT_ROOT / "data" / "processed" / "truth_ghcn_daily"
IEM_DIR = PROJECT_ROOT / "data" / "raw" / "iem"
KMIA_12H_FOLDS_DIR = PROJECT_ROOT / "evidence" / "fullgrid_tmax" / "cells" / "KMIA_12h"

OUT_JSON = PROJECT_ROOT / "evidence" / "p8_inspection_c_2019_replay_20261114.json"
OUT_STRATA_CSV = PROJECT_ROOT / "evidence" / "p8_inspection_c_2019_16strata_20261114.csv"
OUT_CELLS_CSV = PROJECT_ROOT / "evidence" / "p8_inspection_c_2019_22cells_20261114.csv"
OUT_ATOM_CSV = PROJECT_ROOT / "evidence" / "p8_inspection_c_2019_atom_696_20261114.csv"
OUT_REPORT_MD = PROJECT_ROOT / "evidence" / "p8_inspection_c_2019_replay_report_20261114.md"


def load_clean_2019_5min(station: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Load strictly 2019 5-min IEM MADISHF observations with QC gates matching Inspection A."""
    tz = STATION_TIMEZONES[station]
    p = IEM_DIR / station / "2019.parquet"
    df = pd.read_parquet(p)
    df["valid_utc"] = pd.to_datetime(df["valid_utc"], utc=True)
    df["local_dt"] = df["valid_utc"].dt.tz_convert(tz)
    df["local_date"] = df["local_dt"].dt.date

    df_valid = df.dropna(subset=["temp_f"]).sort_values("local_dt").copy()
    oor_mask = (df_valid["temp_f"] < -40.0) | (df_valid["temp_f"] > 135.0)
    oor_count = int(oor_mask.sum())
    df_valid = df_valid[~oor_mask].copy()

    df_valid["dt_min"] = df_valid.groupby("local_date")["local_dt"].diff().dt.total_seconds() / 60.0
    df_valid["dtemp_abs"] = df_valid.groupby("local_date")["temp_f"].diff().abs()
    jump_mask = (df_valid["dtemp_abs"] > 15.0) & (df_valid["dt_min"] <= 15.0)
    jump_count = int(jump_mask.sum())
    df_valid = df_valid[~jump_mask].copy()

    madishf = df_valid[df_valid["raw_metar"].str.contains("MADISHF", na=False)]
    vc_mad = madishf.groupby("local_date").size()
    candidate_dates = set(vc_mad[vc_mad >= MIN_MADISHF_OBS_PER_DAY].index)

    sub = df_valid[df_valid["local_date"].isin(candidate_dates)].copy()
    sub["hour_f"] = sub["local_dt"].dt.hour + sub["local_dt"].dt.minute / 60.0
    day_span = sub.groupby("local_date")["hour_f"].agg(["min", "max"])
    excluded_partial = sorted(str(d) for d in day_span[day_span["min"] > 14.0].index)
    keep_dates = set(day_span[day_span["min"] <= 14.0].index)
    sub = sub[sub["local_date"].isin(keep_dates)].copy()

    # Keep strictly 2019 local dates
    sub = sub[pd.to_datetime(sub["local_date"]).dt.year == 2019].copy()
    retained_dates = sorted(sub["local_date"].unique())

    meta = {
        "input_sha256": sha256_file(p),
        "qc_out_of_range_dropped": oor_count,
        "qc_short_step_jump_dropped": jump_count,
        "madishf_candidate_days": int(len(candidate_dates)),
        "excluded_partial_boundary_days": excluded_partial,
        "retained_valid_days": int(len(retained_dates)),
        "date_min": str(retained_dates[0]),
        "date_max": str(retained_dates[-1]),
    }
    return sub, meta


def build_2019_cell_priors(
    station: str,
    lead_hours: int,
    manifest_models: Dict[str, Any],
    climate_calib: Dict[str, Any],
    contract_cells: Dict[str, Any],
) -> pd.DataFrame:
    """Assemble 2019 daily priors with causal 2018-11..2018-12 b30 warmup and v2 s_oos."""
    ghcn = pd.read_parquet(GHCN_DIR / f"{station}.parquet").copy()
    ghcn["target_date"] = pd.to_datetime(ghcn["target_date"]).dt.date
    ghcn = ghcn[ghcn["year"].isin([2018, 2019])][["target_date", "tmax_f", "tmax_f_cli_rounded"]].copy()

    g18 = pd.read_parquet(GEFS_DIR / station / "2018.parquet")
    g19 = pd.read_parquet(GEFS_DIR / station / "2019.parquet")
    gefs = pd.concat([g18, g19], ignore_index=True)
    gefs = gefs[(gefs["variable"] == "tmax") & (gefs["lead_hours"] == lead_hours)].copy()
    gefs["target_date"] = pd.to_datetime(gefs["target_date"]).dt.date
    gefs["temp_f"] = (gefs["value_K"] - 273.15) * 1.8 + 32.0

    ens = gefs.groupby("target_date")["temp_f"].agg(
        ens_mean="mean",
        ens_var=lambda x: float(np.var(x, ddof=1)) if len(x) > 1 else 0.0,
    ).reset_index()

    merged = pd.merge(ghcn, ens, on="target_date", how="inner").sort_values("target_date").reset_index(drop=True)
    merged["season"] = [get_season(str(d)) for d in merged["target_date"]]
    merged["year"] = pd.to_datetime(merged["target_date"]).dt.year

    # Restrict warmup tail to >= 2018-11-01 before computing causal b30
    merged = merged[merged["target_date"] >= datetime(2018, 11, 1).date()].reset_index(drop=True)

    mu_raw_list, sig_eff_list = [], []
    for _, row in merged.iterrows():
        key = f"{station}_{row['season']}_Max_lead{lead_hours}h.pkl"
        meta = manifest_models[key]
        params = meta["params"]
        a, b, c, d = float(params["a"]), float(params["b"]), float(params["c"]), float(params["d"])
        c_train = float(meta.get("c_train", 1.0))
        mu_raw_list.append(a + b * float(row["ens_mean"]))
        sig_eff_list.append(math.sqrt(c * c + d * d * float(row["ens_var"])) * c_train)

    merged["mu_raw"] = np.array(mu_raw_list, dtype=float)
    merged["sigma_eff"] = np.array(sig_eff_list, dtype=float)
    merged["raw_resid"] = merged["tmax_f"].astype(float) - merged["mu_raw"]
    merged["b30"] = merged["raw_resid"].shift(1).rolling(30, min_periods=10).mean().fillna(0.0)
    merged["mu_0"] = merged["mu_raw"] + merged["b30"]

    cell_key = f"{station}_{lead_hours}h"
    s_oos_v2 = float(contract_cells[cell_key]["s_oos"])
    c_v2 = math.sqrt(max(1.0, s_oos_v2))
    s_oos_v1 = float(contract_cells[cell_key]["s_oos_historical"]["v1_2019_in_sample"]["s_oos"])
    c_v1 = math.sqrt(max(1.0, s_oos_v1))

    merged["s_oos_v2"] = s_oos_v2
    merged["c_v2"] = c_v2
    merged["c_v1"] = c_v1
    merged["sigma_0"] = merged["sigma_eff"] * c_v2

    df19 = merged[merged["year"] == 2019].copy().reset_index(drop=True)
    return df19


def evaluate_11_bracket_probs_prior(
    mu_0: float,
    sigma_0: float,
    family: str,
    shape_p: Dict[str, Any],
    c0: int,
    mm_mu: float,
    mm_sig: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Compute 11 bracket probs for native family, moment-matched gauss, and raw gauss."""
    lower = c0 - 9
    edges = [lower + 2 * k for k in range(10)]  # length 10 interior boundaries
    cdf_nat = construct_true_model_cdf(mu_0, sigma_0, family, shape_p)

    def _from_cdf(fn) -> np.ndarray:
        vals = [float(np.clip(fn(e), 0.0, 1.0)) for e in edges]
        probs = np.empty(11, dtype=float)
        probs[0] = vals[0]
        for i in range(1, 10):
            probs[i] = max(0.0, vals[i] - vals[i - 1])
        probs[10] = max(0.0, 1.0 - vals[9])
        s = probs.sum()
        if s > 0:
            probs /= s
        return probs

    p_nat = _from_cdf(cdf_nat)
    p_mm = _from_cdf(lambda x: float(special.ndtr((x - mm_mu) / max(1e-8, mm_sig))))
    p_raw = _from_cdf(lambda x: float(special.ndtr((x - mu_0) / max(1e-8, sigma_0))))
    hits_cont = np.zeros(11, dtype=float)
    return p_nat, p_mm, p_raw, hits_cont


def bracket_hit_index(y_val: float, c0: int) -> int:
    """Return 0..10 bracket index for realized tmax matching DiscreteBinEngine/audit_v2 intervals."""
    lower = c0 - 9
    if y_val < lower:
        return 0
    if y_val >= c0 + 9:
        return 10
    idx = int(math.floor((y_val - lower) / 2.0)) + 1
    return max(1, min(9, idx))


def evaluate_kmia_12h_v2_reread(
    s_oos_v2: float,
    s_oos_v1: float,
) -> Dict[str, Any]:
    """Re-read KMIA_12h 2000-2018 20-fold Block-CV in-window & w20 ECE under v2 contract s_oos."""
    c_v2 = math.sqrt(max(1.0, s_oos_v2))
    c_v1 = math.sqrt(max(1.0, s_oos_v1))

    folds = []
    for r in range(20):
        fp = KMIA_12H_FOLDS_DIR / f"cv_fold_{r}_predictions.parquet"
        folds.append(pd.read_parquet(fp))
    df_all = pd.concat(folds, ignore_index=True)

    p_base = df_all["p_pred"].to_numpy(dtype=float)
    hits = df_all["hit"].to_numpy(dtype=float)

    # Recompute exact 7-bin family CDF with sigma scaled by c_v2 and c_v1
    mu_arr = df_all["mu"].to_numpy(dtype=float)
    sig_arr = df_all["sigma"].to_numpy(dtype=float)
    bc_arr = df_all["bin_center"].to_numpy(dtype=float)
    fam_arr = df_all["selected_family"].to_numpy()
    sp_arr = [json.loads(s) if isinstance(s, str) and s else {} for s in df_all["family_shape_params"]]

    # Fast grouped evaluation by identical (target_date, mu, sigma) row blocks (7 rows/day)
    n_rows = len(df_all)
    p_v2 = np.empty(n_rows, dtype=float)
    p_v1 = np.empty(n_rows, dtype=float)
    p_recomp_c1 = np.empty(n_rows, dtype=float)

    for i in range(0, n_rows, 7):
        mu_i = float(mu_arr[i])
        sig_i = float(sig_arr[i])
        fam_i = str(fam_arr[i])
        sp_i = sp_arr[i]
        bcs = bc_arr[i : i + 7]
        fn_c1 = construct_true_model_cdf(mu_i, sig_i, fam_i, sp_i)
        fn_v2 = construct_true_model_cdf(mu_i, sig_i * c_v2, fam_i, sp_i)
        fn_v1 = construct_true_model_cdf(mu_i, sig_i * c_v1, fam_i, sp_i)
        for j in range(7):
            lo_b, hi_b = bcs[j] - 0.5, bcs[j] + 0.5
            p_recomp_c1[i + j] = max(0.0, fn_c1(hi_b) - fn_c1(lo_b))
            p_v2[i + j] = max(0.0, fn_v2(hi_b) - fn_v2(lo_b))
            p_v1[i + j] = max(0.0, fn_v1(hi_b) - fn_v1(lo_b))

    return {
        "n_bin_samples": int(n_rows),
        "n_daily_samples": int(n_rows // 7),
        "s_oos_v2": s_oos_v2,
        "c_v2": round(c_v2, 6),
        "s_oos_v1": s_oos_v1,
        "c_v1": round(c_v1, 6),
        "blockcv_inw_ece_raw_c1_stored": round(compute_ece_inw(p_base, hits), 6),
        "blockcv_inw_ece_raw_c1_recomputed": round(compute_ece_inw(p_recomp_c1, hits), 6),
        "blockcv_inw_ece_v2_c": round(compute_ece_inw(p_v2, hits), 6),
        "blockcv_inw_ece_v1_c": round(compute_ece_inw(p_v1, hits), 6),
        "blockcv_w20_ece_raw_c1_stored": round(compute_ece_w20(p_base, hits), 6),
        "blockcv_w20_ece_v2_c": round(compute_ece_w20(p_v2, hits), 6),
        "blockcv_w20_ece_v1_c": round(compute_ece_w20(p_v1, hits), 6),
    }


def main() -> int:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if contract.get("s_oos_version") != "v2_2000_2018_oof_cv":
        raise RuntimeError(f"Expected v2_2000_2018_oof_cv contract, got {contract.get('s_oos_version')}")
    contract_cells = contract["cells"]

    manifest_models = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["models"]
    climate_calib = json.loads(CLIMATE_CALIB_PATH.read_text(encoding="utf-8"))
    eta_df = pd.read_csv(ETA_CAL_CSV)
    eta_map = {
        (str(r.station), str(r.season), float(r.t_hour)): float(r.eta_calibrated)
        for r in eta_df.itertuples()
    }

    # Verify live Proposal1CoolingDriftMuRHook defaults to Round-2 rho_s,se(t) released artifact
    hook = Proposal1CoolingDriftMuRHook.from_calibration_artifact()
    assert _DEFAULT_COOLING_DRIFT_ARTIFACT.name == "p8_mu_r_rho_released_calibration_20261114.json"
    assert hook._resolve_curve("KORD", "Spring") is not None and "rho_values" in hook._resolve_curve("KORD", "Spring")

    # Precompute Z moments per (station, season)
    moment_map: Dict[Tuple[str, str], Tuple[str, Dict[str, Any], float, float]] = {}
    for st in AUTHORIZED_STATIONS:
        for seas in SEASONS:
            info = climate_calib[st]["seasons"][seas]
            fam = str(info.get("selected_family", "gaussian"))
            sp = info.get("shape_params", {}) or {}
            ez, stdz = compute_moments_z(fam, sp)
            moment_map[(st, seas)] = (fam, sp, ez, stdz)

    # Load clean 2019 5-min data
    iem_2019: Dict[str, pd.DataFrame] = {}
    iem_meta: Dict[str, Any] = {}
    day_summaries: Dict[Tuple[str, float], pd.DataFrame] = {}
    for st in AUTHORIZED_STATIONS:
        sub, meta = load_clean_2019_5min(st)
        iem_2019[st] = sub
        iem_meta[st] = meta
        tfin_all = sub.groupby("local_date")["temp_f"].max()
        # Daytime window end (20:00) for clean intraday step consistency diagnostic
        tfin_20 = sub[sub["hour_f"] <= 20.0 + 1e-9].groupby("local_date")["temp_f"].max()
        for h in T_GRID:
            hf = float(h)
            s_h = sub[sub["hour_f"] <= hf + 1e-9].sort_values("local_dt")
            agg = s_h.groupby("local_date").agg(mt=("temp_f", "max"), xt=("temp_f", "last"))
            agg["tfin_all"] = agg.index.map(tfin_all)
            agg["tfin_day"] = agg.index.map(tfin_20)
            day_summaries[(st, hf)] = agg

    # Collectors for 16 strata & 22 cells
    # Keys: (station, season, period)
    strata_acc: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for st in AUTHORIZED_STATIONS:
        for seas in SEASONS:
            for per in ("early", "late"):
                strata_acc[(st, seas, per)] = {
                    "nat_p": [], "nat_h": [],
                    "mm_p": [], "mm_h": [],
                    "rawg_p": [], "rawg_h": [],
                    "br_all_p": [], "br_all_h": [],
                    "br_early_p": [], "br_early_h": [],
                    "br_aft_p": [], "br_aft_h": [],
                    "n_days_leads": 0,
                    "brier_nat": [], "brier_mm": [], "brier_br": [],
                }

    cell_rows: List[Dict[str, Any]] = []
    atom_obs_records: List[Dict[str, Any]] = []
    b30_warmup_examples: Dict[str, Any] = {}

    for st in AUTHORIZED_STATIONS:
        valid_5min_dates = set(iem_2019[st]["local_date"].unique())
        for lead in AUTHORIZED_LEAD_HOURS:
            per = get_period(lead)
            df19 = build_2019_cell_priors(st, lead, manifest_models, climate_calib, contract_cells)
            df19 = df19[df19["target_date"].isin(valid_5min_dates)].copy().reset_index(drop=True)

            # Record Jan 1 b30 warmup proof for KORD_18h and KMIA_12h
            if (st == "KORD" and lead == 18) or (st == "KMIA" and lead == 12):
                d0 = df19.iloc[0]
                b30_warmup_examples[f"{st}_{lead}h_day1"] = {
                    "target_date": str(d0["target_date"]),
                    "b30_warm": round(float(d0["b30"]), 6),
                    "mu_raw": round(float(d0["mu_raw"]), 6),
                    "mu_0": round(float(d0["mu_0"]), 6),
                    "sigma_eff": round(float(d0["sigma_eff"]), 6),
                    "sigma_0_v2": round(float(d0["sigma_0"]), 6),
                    "c_v2": round(float(d0["c_v2"]), 6),
                }

            c_nat_p, c_nat_h = [], []
            c_mm_p, c_mm_h = [], []
            c_rawg_p, c_rawg_h = [], []
            c_br_p, c_br_h = [], []
            c_br_e_p, c_br_e_h = [], []
            c_br_a_p, c_br_a_h = [], []
            c_cov90 = []
            c_resids = []

            dates_arr = df19["target_date"].tolist()
            seas_arr = df19["season"].tolist()
            mu0_arr = df19["mu_0"].to_numpy(dtype=float)
            s0_arr = df19["sigma_0"].to_numpy(dtype=float)
            y_arr = df19["tmax_f"].to_numpy(dtype=float)

            # Daily prior native / gauss bracket evaluation + coverage + bias
            c0_list: List[int] = []
            hit_vec_list: List[np.ndarray] = []

            for i in range(len(df19)):
                seas = seas_arr[i]
                mu0 = float(mu0_arr[i])
                s0 = float(s0_arr[i])
                yi = float(y_arr[i])
                fam, sp, ez, stdz = moment_map[(st, seas)]
                mm_mu = mu0 + s0 * ez
                mm_sig = s0 * stdz
                c0 = int(round(mu0))
                c0_list.append(c0)

                p_nat, p_mm, p_raw, _ = evaluate_11_bracket_probs_prior(mu0, s0, fam, sp, c0, mm_mu, mm_sig)
                h_idx = bracket_hit_index(yi, c0)
                hv = np.zeros(11, dtype=float)
                hv[h_idx] = 1.0
                hit_vec_list.append(hv)

                acc = strata_acc[(st, seas, per)]
                acc["nat_p"].append(p_nat)
                acc["nat_h"].append(hv)
                acc["mm_p"].append(p_mm)
                acc["mm_h"].append(hv)
                acc["rawg_p"].append(p_raw)
                acc["rawg_h"].append(hv)
                acc["n_days_leads"] += 1
                acc["brier_nat"].append(float(np.sum((p_nat - hv) ** 2)))
                acc["brier_mm"].append(float(np.sum((p_mm - hv) ** 2)))

                c_nat_p.append(p_nat); c_nat_h.append(hv)
                c_mm_p.append(p_mm); c_mm_h.append(hv)
                c_rawg_p.append(p_raw); c_rawg_h.append(hv)
                c_resids.append(yi - mu0)

                # Native 90% analytical coverage
                if fam == "johnsonsu":
                    lq = mu0 + s0 * float(stats.johnsonsu.ppf(0.05, sp["gamma"], sp["delta"], loc=sp["xi"], scale=sp["lambda"]))
                    uq = mu0 + s0 * float(stats.johnsonsu.ppf(0.95, sp["gamma"], sp["delta"], loc=sp["xi"], scale=sp["lambda"]))
                else:
                    lq = mu0 - 1.6448536 * s0
                    uq = mu0 + 1.6448536 * s0
                c_cov90.append(1.0 if (lq <= yi <= uq) else 0.0)

            # Intraday 29-slice 5-min D+0 replay loop using live Proposal1CoolingDriftMuRHook
            for hf_np in T_GRID:
                hf = float(hf_np)
                obs_slice = day_summaries[(st, hf)].reindex(dates_arr)
                mt_vec = obs_slice["mt"].to_numpy(dtype=float)
                xt_vec = obs_slice["xt"].to_numpy(dtype=float)
                tfin_vec = obs_slice["tfin_all"].to_numpy(dtype=float)

                for i in range(len(df19)):
                    mt = mt_vec[i]
                    xt = xt_vec[i]
                    if np.isnan(mt) or np.isnan(xt):
                        continue
                    seas = seas_arr[i]
                    mu0 = float(mu0_arr[i])
                    s0 = float(s0_arr[i])
                    m_int = float(settle_half_up(float(mt)))
                    eta = eta_map[(st, seas, hf)]
                    sigma_rem = max(s0 * math.sqrt(max(eta, 0.0)), SIGMA_INST_PHYSICAL_FLOOR)

                    res_mu = hook.compute(
                        t_local=hf,
                        extreme_m=m_int,
                        instant_x_t=float(xt),
                        mu_0=mu0,
                        target_type="max",
                        station_id=st,
                        season=seas,
                    )
                    mu_r = res_mu.mu_r

                    # 11-bracket telescoping left-limit conditional probabilities
                    c0 = c0_list[i]
                    lower = c0 - 9
                    edges = [lower + 2 * k for k in range(10)]
                    cdfs = np.array(
                        [0.0 if e <= m_int else float(special.ndtr(((e - m_int) - mu_r) / sigma_rem)) for e in edges],
                        dtype=float,
                    )
                    p_cond = np.empty(11, dtype=float)
                    p_cond[0] = cdfs[0]
                    p_cond[1:10] = np.maximum(0.0, cdfs[1:10] - cdfs[0:9])
                    p_cond[10] = max(0.0, 1.0 - cdfs[9])
                    ps = p_cond.sum()
                    if ps > 0:
                        p_cond /= ps

                    hv = hit_vec_list[i]
                    acc = strata_acc[(st, seas, per)]
                    acc["br_all_p"].append(p_cond); acc["br_all_h"].append(hv)
                    acc["brier_br"].append(float(np.sum((p_cond - hv) ** 2)))
                    c_br_p.append(p_cond); c_br_h.append(hv)

                    if hf <= 13.5:
                        acc["br_early_p"].append(p_cond); acc["br_early_h"].append(hv)
                        c_br_e_p.append(p_cond); c_br_e_h.append(hv)
                    else:
                        acc["br_aft_p"].append(p_cond); acc["br_aft_h"].append(hv)
                        c_br_a_p.append(p_cond); c_br_a_h.append(hv)

                    # Canonical 18h intraday no-new-high atomic observation log (matching Inspection A / Round 2)
                    if lead == 18:
                        p_no_new = float(special.ndtr(-mu_r / sigma_rem))
                        y_raw = 1.0 if float(tfin_vec[i]) <= float(mt) + 1e-6 else 0.0
                        pb = classify_position_bucket(float(mt) - mu0)
                        atom_obs_records.append(
                            {
                                "station": st,
                                "season": seas,
                                "local_date": str(dates_arr[i]),
                                "t_hour": hf,
                                "pos_bucket": pb,
                                "cooling_drop": max(0.0, float(mt) - float(xt)),
                                "y_raw": y_raw,
                                "p_after": p_no_new,
                                "mu_r": mu_r,
                                "sigma_rem": sigma_rem,
                            }
                        )

            # Cell metrics
            np_arr = np.concatenate(c_nat_p); nh_arr = np.concatenate(c_nat_h)
            mp_arr = np.concatenate(c_mm_p); mh_arr = np.concatenate(c_mm_h)
            rp_arr = np.concatenate(c_rawg_p); rh_arr = np.concatenate(c_rawg_h)
            bp_arr = np.concatenate(c_br_p); bh_arr = np.concatenate(c_br_h)
            bep_arr = np.concatenate(c_br_e_p); beh_arr = np.concatenate(c_br_e_h)
            bap_arr = np.concatenate(c_br_a_p); bah_arr = np.concatenate(c_br_a_h)

            ece_nat_inw = compute_ece_inw(np_arr, nh_arr)
            ece_nat_w20 = compute_ece_w20(np_arr, nh_arr)
            ece_mm_inw = compute_ece_inw(mp_arr, mh_arr)
            ece_mm_w20 = compute_ece_w20(mp_arr, mh_arr)
            ece_rawg_inw = compute_ece_inw(rp_arr, rh_arr)
            ece_rawg_w20 = compute_ece_w20(rp_arr, rh_arr)
            ece_br_inw = compute_ece_inw(bp_arr, bh_arr)
            ece_br_w20 = compute_ece_w20(bp_arr, bh_arr)
            ece_bre_inw = compute_ece_inw(bep_arr, beh_arr)
            ece_bra_inw = compute_ece_inw(bap_arr, bah_arr)

            res_v = np.array(c_resids, dtype=float)
            s_oos_2019 = float(np.var(res_v, ddof=1) / np.mean(s0_arr ** 2))
            cell_rows.append(
                {
                    "cell": f"{st}_{lead}h",
                    "station": st,
                    "lead_hours": lead,
                    "period": per,
                    "n_days": int(len(df19)),
                    "c_v2": round(float(df19["c_v2"].iloc[0]), 6),
                    "s_oos_2019_after_c_v2": round(s_oos_2019, 6),
                    "bias_f": round(float(np.mean(res_v)), 4),
                    "mae_f": round(float(np.mean(np.abs(res_v))), 4),
                    "cov90_native": round(float(np.mean(c_cov90)), 4),
                    "ece_native_inw": round(ece_nat_inw, 6),
                    "ece_mm_gauss_inw": round(ece_mm_inw, 6),
                    "ece_raw_gauss_inw": round(ece_rawg_inw, 6),
                    "ece_bridge_inw": round(ece_br_inw, 6),
                    "delta_bridge_inw": round(ece_br_inw - ece_nat_inw, 6),
                    "delta_bridge_vs_gauss_inw": round(ece_br_inw - ece_mm_inw, 6),
                    "ece_bridge_early_inw": round(ece_bre_inw, 6),
                    "ece_bridge_aft_inw": round(ece_bra_inw, 6),
                    "ece_native_w20": round(ece_nat_w20, 6),
                    "ece_mm_gauss_w20": round(ece_mm_w20, 6),
                    "ece_raw_gauss_w20": round(ece_rawg_w20, 6),
                    "ece_bridge_w20": round(ece_br_w20, 6),
                    "delta_bridge_w20": round(ece_br_w20 - ece_nat_w20, 6),
                }
            )

    # Assemble 16-strata table
    strata_rows: List[Dict[str, Any]] = []
    for st in AUTHORIZED_STATIONS:
        for seas in SEASONS:
            fam = moment_map[(st, seas)][0]
            for per in ("early", "late"):
                acc = strata_acc[(st, seas, per)]
                np_a = np.concatenate(acc["nat_p"]); nh_a = np.concatenate(acc["nat_h"])
                mp_a = np.concatenate(acc["mm_p"]); mh_a = np.concatenate(acc["mm_h"])
                rp_a = np.concatenate(acc["rawg_p"]); rh_a = np.concatenate(acc["rawg_h"])
                bp_a = np.concatenate(acc["br_all_p"]); bh_a = np.concatenate(acc["br_all_h"])
                bep_a = np.concatenate(acc["br_early_p"]); beh_a = np.concatenate(acc["br_early_h"])
                bap_a = np.concatenate(acc["br_aft_p"]); bah_a = np.concatenate(acc["br_aft_h"])

                en_inw = compute_ece_inw(np_a, nh_a)
                em_inw = compute_ece_inw(mp_a, mh_a)
                er_inw = compute_ece_inw(rp_a, rh_a)
                eb_inw = compute_ece_inw(bp_a, bh_a)
                ebe_inw = compute_ece_inw(bep_a, beh_a)
                eba_inw = compute_ece_inw(bap_a, bah_a)

                en_w20 = compute_ece_w20(np_a, nh_a)
                em_w20 = compute_ece_w20(mp_a, mh_a)
                er_w20 = compute_ece_w20(rp_a, rh_a)
                eb_w20 = compute_ece_w20(bp_a, bh_a)
                ebe_w20 = compute_ece_w20(bep_a, beh_a)
                eba_w20 = compute_ece_w20(bap_a, bah_a)

                strata_rows.append(
                    {
                        "station": st,
                        "season": seas,
                        "period": per,
                        "family": fam,
                        "n_cell_days": int(acc["n_days_leads"]),
                        "n_bridge_evals": int(len(bp_a) // 11),
                        "brier_native": round(float(np.mean(acc["brier_nat"])), 6),
                        "brier_mm_gauss": round(float(np.mean(acc["brier_mm"])), 6),
                        "brier_bridge": round(float(np.mean(acc["brier_br"])), 6),
                        "ece_native_inw": round(en_inw, 6),
                        "ece_mm_gauss_inw": round(em_inw, 6),
                        "ece_raw_gauss_inw": round(er_inw, 6),
                        "ece_bridge_inw": round(eb_inw, 6),
                        "ece_bridge_early_inw": round(ebe_inw, 6),
                        "ece_bridge_aft_inw": round(eba_inw, 6),
                        "delta_bridge_inw": round(eb_inw - en_inw, 6),
                        "delta_bridge_vs_mm_gauss_inw": round(eb_inw - em_inw, 6),
                        "delta_native_vs_mm_gauss_inw": round(en_inw - em_inw, 6),
                        "ece_native_w20": round(en_w20, 6),
                        "ece_mm_gauss_w20": round(em_w20, 6),
                        "ece_raw_gauss_w20": round(er_w20, 6),
                        "ece_bridge_w20": round(eb_w20, 6),
                        "ece_bridge_early_w20": round(ebe_w20, 6),
                        "ece_bridge_aft_w20": round(eba_w20, 6),
                        "delta_bridge_w20": round(eb_w20 - en_w20, 6),
                        "delta_bridge_vs_mm_gauss_w20": round(eb_w20 - em_w20, 6),
                        "delta_native_vs_mm_gauss_w20": round(en_w20 - em_w20, 6),
                    }
                )

    # Atomic 696-bucket 2019 out-of-sample check (reusing 18h canonical replay)
    atom_df = pd.DataFrame(atom_obs_records)
    atom_bucket_rows: List[Dict[str, Any]] = []
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
                    atom_bucket_rows.append(
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
    abdf = pd.DataFrame(atom_bucket_rows)

    def _agg_atom(sub: pd.DataFrame) -> Dict[str, Any]:
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

    early_b3_cool_2019 = atom_df[
        (atom_df["t_hour"] <= 13.5)
        & (atom_df["pos_bucket"] == "B3_at_or_above")
        & (atom_df["cooling_drop"] > 0.05)
    ]

    atom_2019_summary = {
        "total_nonempty_cells": int(len(abdf)),
        "early_B12_pooled": _agg_atom(eb12),
        "early_B1": _agg_atom(early_b[early_b["pos_bucket"] == "B1_below_anchor"]),
        "early_B2": _agg_atom(early_b[early_b["pos_bucket"] == "B2_near_anchor"]),
        "early_B3": _agg_atom(early_b[early_b["pos_bucket"] == "B3_at_or_above"]),
        "early_B3_cooling_subset": {
            "n_obs": int(len(early_b3_cool_2019)),
            "emp_no_new": round(float(early_b3_cool_2019["y_raw"].mean()), 6) if len(early_b3_cool_2019) else None,
            "pred_after": round(float(early_b3_cool_2019["p_after"].mean()), 6) if len(early_b3_cool_2019) else None,
            "resid": round(float(early_b3_cool_2019["y_raw"].mean() - early_b3_cool_2019["p_after"].mean()), 6)
            if len(early_b3_cool_2019)
            else None,
        },
        "aft_total_cells": int(len(aft_b)),
        "aft_total_out95": int(aft_b["outside_ci_after"].sum()),
        "aft_kord_out95": int(aft_b[aft_b["station"] == "KORD"]["outside_ci_after"].sum()),
        "aft_kmia_out95": int(aft_b[aft_b["station"] == "KMIA"]["outside_ci_after"].sum()),
        "aft_B1": _agg_atom(aft_b[aft_b["pos_bucket"] == "B1_below_anchor"]),
        "aft_B2": _agg_atom(aft_b[aft_b["pos_bucket"] == "B2_near_anchor"]),
        "aft_B3": _agg_atom(aft_b[aft_b["pos_bucket"] == "B3_at_or_above"]),
    }

    # Focus Item 1: KORD Spring/Autumn afternoon transition window & Round-2 6 residual cells
    round2_6_keys = [
        ("KORD", "Spring", 14.0, "B2_near_anchor"),
        ("KORD", "Spring", 14.0, "B3_at_or_above"),
        ("KORD", "Spring", 14.5, "B2_near_anchor"),
        ("KORD", "Spring", 14.5, "B3_at_or_above"),
        ("KORD", "Spring", 15.5, "B2_near_anchor"),
        ("KORD", "Autumn", 14.0, "B3_at_or_above"),
    ]
    focus1_round2_6_in_2019 = []
    for st, seas, hf, pb in round2_6_keys:
        row = abdf[
            (abdf["station"] == st)
            & (abdf["season"] == seas)
            & (abdf["t_hour"] == hf)
            & (abdf["pos_bucket"] == pb)
        ]
        if not row.empty:
            focus1_round2_6_in_2019.append(row.iloc[0].to_dict())

    focus1_kord_spring_autumn_aft = {}
    for seas in ("Spring", "Autumn"):
        sub = aft_b[(aft_b["station"] == "KORD") & (aft_b["season"] == seas)]
        w = sub["n_bucket"].to_numpy(dtype=float)
        focus1_kord_spring_autumn_aft[seas] = {
            "cells": int(len(sub)),
            "n_obs": int(sub["n_bucket"].sum()),
            "out95": int(sub["outside_ci_after"].sum()),
            "wMAE": round(float(np.average(sub["abs_resid_after"], weights=w)), 6),
            "wResid": round(float(np.average(sub["resid_after"], weights=w)), 6),
        }

    # Focus Item 2: KMIA Winter early
    focus2_kmia_winter_early = [
        r for r in strata_rows if r["station"] == "KMIA" and r["season"] == "Winter" and r["period"] == "early"
    ][0]

    # Focus Item 3: KMIA_12h v2 reread (both 2000-2018 Block-CV & 2019 OOS)
    s_oos_kmia12_v2 = float(contract_cells["KMIA_12h"]["s_oos"])
    s_oos_kmia12_v1 = float(contract_cells["KMIA_12h"]["s_oos_historical"]["v1_2019_in_sample"]["s_oos"])
    focus3_blockcv = evaluate_kmia_12h_v2_reread(s_oos_kmia12_v2, s_oos_kmia12_v1)
    focus3_2019 = [r for r in cell_rows if r["cell"] == "KMIA_12h"][0]

    # Save CSV/JSON outputs
    pd.DataFrame(strata_rows).to_csv(OUT_STRATA_CSV, index=False)
    pd.DataFrame(cell_rows).to_csv(OUT_CELLS_CSV, index=False)
    abdf.to_csv(OUT_ATOM_CSV, index=False)

    # Pooled ECE summaries across all 22 cells (must flatten each stratum's list of 11-bin vectors to 1D)
    all_nat_p = np.concatenate([np.concatenate(strata_acc[(st, s, p)]["nat_p"]) for st in AUTHORIZED_STATIONS for s in SEASONS for p in ("early", "late")])
    all_nat_h = np.concatenate([np.concatenate(strata_acc[(st, s, p)]["nat_h"]) for st in AUTHORIZED_STATIONS for s in SEASONS for p in ("early", "late")])
    all_mm_p = np.concatenate([np.concatenate(strata_acc[(st, s, p)]["mm_p"]) for st in AUTHORIZED_STATIONS for s in SEASONS for p in ("early", "late")])
    all_br_p = np.concatenate([np.concatenate(strata_acc[(st, s, p)]["br_all_p"]) for st in AUTHORIZED_STATIONS for s in SEASONS for p in ("early", "late")])
    all_br_h = np.concatenate([np.concatenate(strata_acc[(st, s, p)]["br_all_h"]) for st in AUTHORIZED_STATIONS for s in SEASONS for p in ("early", "late")])
    assert all_nat_p.ndim == 1 and all_nat_h.ndim == 1 and all_mm_p.ndim == 1 and all_br_p.ndim == 1 and all_br_h.ndim == 1

    pooled_summary = {
        "ece_native_inw": round(compute_ece_inw(all_nat_p, all_nat_h), 6),
        "ece_mm_gauss_inw": round(compute_ece_inw(all_mm_p, all_nat_h), 6),
        "ece_bridge_inw": round(compute_ece_inw(all_br_p, all_br_h), 6),
        "delta_bridge_inw": round(compute_ece_inw(all_br_p, all_br_h) - compute_ece_inw(all_nat_p, all_nat_h), 6),
        "ece_native_w20": round(compute_ece_w20(all_nat_p, all_nat_h), 6),
        "ece_mm_gauss_w20": round(compute_ece_w20(all_mm_p, all_nat_h), 6),
        "ece_bridge_w20": round(compute_ece_w20(all_br_p, all_br_h), 6),
        "delta_bridge_w20": round(compute_ece_w20(all_br_p, all_br_h) - compute_ece_w20(all_nat_p, all_nat_h), 6),
    }

    payload = {
        "schema_version": "p8_inspection_c_2019_replay_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_scope": "2019-01-01 .. 2019-12-30 (5-min MADISHF D+0 replay + 2018-11..12 causal b30 warmup)",
        "contract_s_oos_version": contract.get("s_oos_version"),
        "active_mu_r_artifact": _DEFAULT_COOLING_DRIFT_ARTIFACT.name,
        "iem_2019_metadata": iem_meta,
        "b30_warmup_examples": b30_warmup_examples,
        "pooled_summary": pooled_summary,
        "strata_16": strata_rows,
        "cells_22": cell_rows,
        "intraday_atom_2019_oos_18h": atom_2019_summary,
        "focus_items": {
            "focus_1_kord_spring_autumn_aft": focus1_kord_spring_autumn_aft,
            "focus_1_round2_6_cells_in_2019": focus1_round2_6_in_2019,
            "focus_2_kmia_winter_early": focus2_kmia_winter_early,
            "focus_3_kmia_12h_blockcv_v2_reread": focus3_blockcv,
            "focus_3_kmia_12h_2019_oos": focus3_2019,
        },
        "owner_signoff_status": "PENDING_OWNER_ALPHA_VERDICT",
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # Build comprehensive markdown report (no subjective verdict declared)
    lines = [
        "# P8-ALGO 检验 C（2019 全年 D+0 5 分钟回放判决跑批原始指标报告）",
        "",
        "> **性质声明**：本报告严格按 `SPEC v2.0` 与 `Phase 2 执行文件 v2.2 §4.7` 回传 2019 独立盲测年全年回放全量原始观测数值，**不签发任何方案 `α` 放行/终止结论，由业主审阅后终裁签字**。",
        "",
        f"- **执行日期**: `2026-11-14` | **脚本**: [`scripts/run_p8_inspection_c_2019_replay.py`](../scripts/run_p8_inspection_c_2019_replay.py)",
        f"- **现役接线工件**: `{_DEFAULT_COOLING_DRIFT_ARTIFACT.name}`（Round-2 `ρ_s,se(t)` 释放曲线 via `Proposal1CoolingDriftMuRHook`）",
        f"- **方差膨胀契约**: `{contract.get('s_oos_version')}`（严格 zero-2019 折外 `s_oos`）",
        f"- **2019 5 分钟 MADISHF 数据覆盖**: `KORD` `{iem_meta['KORD']['retained_valid_days']}` 日（`{iem_meta['KORD']['date_min']}..{iem_meta['KORD']['date_max']}`），`KMIA` `{iem_meta['KMIA']['retained_valid_days']}` 日（`{iem_meta['KMIA']['date_min']}..{iem_meta['KMIA']['date_max']}`）；`b30` 使用 `2018-11..2018-12` 预热因果滚算（如 `KORD_18h 2019-01-01 b30={b30_warmup_examples['KORD_18h_day1']['b30_warm']:+.4f}°F`，`KMIA_12h 2019-01-01 b30={b30_warmup_examples['KMIA_12h_day1']['b30_warm']:+.4f}°F`）",
        "",
        "## 一、 三数同源并产全量汇总（`22 格 × 2019 全年 × 11 档 2°F`）",
        "",
        f"- **全池 `inw` 8 谱带加权 ECE**：`ECE_native = {pooled_summary['ece_native_inw']:.6f}`, `ECE_mm_gauss = {pooled_summary['ece_mm_gauss_inw']:.6f}`, `ECE_bridge = {pooled_summary['ece_bridge_inw']:.6f}`, `Δ_bridge (bridge - native) = {pooled_summary['delta_bridge_inw']:+.6f}`",
        f"- **全池 `w20` 20 等宽桶加权 ECE**：`ECE_native = {pooled_summary['ece_native_w20']:.6f}`, `ECE_mm_gauss = {pooled_summary['ece_mm_gauss_w20']:.6f}`, `ECE_bridge = {pooled_summary['ece_bridge_w20']:.6f}`, `Δ_bridge (bridge - native) = {pooled_summary['delta_bridge_w20']:+.6f}`",
        "",
        "## 二、 16 层 `站 × 季 × 早晚段` 三数同源对照表（`Phase 2 v2.2#L224-230`）",
        "",
        "| 站 | 季 | 段 | 族 | 日×格数 | ECE_native (inw) | ECE_mm_gauss (inw) | ECE_bridge (inw) | `Δ_bridge` (inw) | `bridge_early` (inw) | `bridge_aft` (inw) | ECE_native (w20) | ECE_bridge (w20) | `Δ_bridge` (w20) |",
        "|:---|:---|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in strata_rows:
        lines.append(
            f"| {r['station']} | {r['season']} | {r['period']} | {r['family']} | {r['n_cell_days']} | "
            f"{r['ece_native_inw']:.6f} | {r['ece_mm_gauss_inw']:.6f} | {r['ece_bridge_inw']:.6f} | {r['delta_bridge_inw']:+.6f} | "
            f"{r['ece_bridge_early_inw']:.6f} | {r['ece_bridge_aft_inw']:.6f} | "
            f"{r['ece_native_w20']:.6f} | {r['ece_bridge_w20']:.6f} | {r['delta_bridge_w20']:+.6f} |"
        )

    lines.extend(
        [
            "",
            "## 三、 2019 独立盲测日内原子校准对照（`18h` 5 分钟流）",
            "",
            "| 时段 | 位置桶 | 2019 格数 | 2019 观测条数 | 2019 wMAE | 2019 wResid | 2019 out95 | 608 天标定 wResid (对照) | 608 天 out95 (对照) |",
            "|:---|:---|---:|---:|---:|---:|---:|---:|---:|",
            f"| 06:00–13:30 | early_B12_pooled | {atom_2019_summary['early_B12_pooled']['cells']} | {atom_2019_summary['early_B12_pooled']['n_obs']} | {atom_2019_summary['early_B12_pooled']['wMAE']:.6f} | {atom_2019_summary['early_B12_pooled']['wResid']:+.6f} | {atom_2019_summary['early_B12_pooled']['out95']} | -0.019668 | 25 |",
            f"| 06:00–13:30 | early_B1 | {atom_2019_summary['early_B1']['cells']} | {atom_2019_summary['early_B1']['n_obs']} | {atom_2019_summary['early_B1']['wMAE']:.6f} | {atom_2019_summary['early_B1']['wResid']:+.6f} | {atom_2019_summary['early_B1']['out95']} | -0.006161 | 1 |",
            f"| 06:00–13:30 | early_B2 | {atom_2019_summary['early_B2']['cells']} | {atom_2019_summary['early_B2']['n_obs']} | {atom_2019_summary['early_B2']['wMAE']:.6f} | {atom_2019_summary['early_B2']['wResid']:+.6f} | {atom_2019_summary['early_B2']['out95']} | -0.089582 | 24 |",
            f"| 06:00–13:30 | early_B3 | {atom_2019_summary['early_B3']['cells']} | {atom_2019_summary['early_B3']['n_obs']} | {atom_2019_summary['early_B3']['wMAE']:.6f} | {atom_2019_summary['early_B3']['wResid']:+.6f} | {atom_2019_summary['early_B3']['out95']} | -0.005357 | 21 |",
            f"| 14:00–20:00 | aft_B1 | {atom_2019_summary['aft_B1']['cells']} | {atom_2019_summary['aft_B1']['n_obs']} | {atom_2019_summary['aft_B1']['wMAE']:.6f} | {atom_2019_summary['aft_B1']['wResid']:+.6f} | {atom_2019_summary['aft_B1']['out95']} | -0.007051 | 0 |",
            f"| 14:00–20:00 | aft_B2 | {atom_2019_summary['aft_B2']['cells']} | {atom_2019_summary['aft_B2']['n_obs']} | {atom_2019_summary['aft_B2']['wMAE']:.6f} | {atom_2019_summary['aft_B2']['wResid']:+.6f} | {atom_2019_summary['aft_B2']['out95']} | -0.006238 | 3 |",
            f"| 14:00–20:00 | aft_B3 | {atom_2019_summary['aft_B3']['cells']} | {atom_2019_summary['aft_B3']['n_obs']} | {atom_2019_summary['aft_B3']['wMAE']:.6f} | {atom_2019_summary['aft_B3']['wResid']:+.6f} | {atom_2019_summary['aft_B3']['out95']} | -0.004230 | 3 |",
            "",
            f"- 2019 午后总出界格数 = `{atom_2019_summary['aft_total_out95']}/{atom_2019_summary['aft_total_cells']}`（`KORD {atom_2019_summary['aft_kord_out95']}/156`, `KMIA {atom_2019_summary['aft_kmia_out95']}/156`）",
            f"- 2019 早段 B3 冷却子集 `(n={atom_2019_summary['early_B3_cooling_subset']['n_obs']})`：实测 `{atom_2019_summary['early_B3_cooling_subset']['emp_no_new']}` vs 预测 `{atom_2019_summary['early_B3_cooling_subset']['pred_after']}`，残差 `{atom_2019_summary['early_B3_cooling_subset']['resid']}`",
            "",
            "## 四、 业主指定三项重点观察项",
            "",
            "### 观察项 ①｜KORD 春秋午后过渡窗（含 Round-2 残留 6 格族）",
            "",
            f"- `KORD Spring 14:00–20:00`（`cells={focus1_kord_spring_autumn_aft['Spring']['cells']}`, `n_obs={focus1_kord_spring_autumn_aft['Spring']['n_obs']}`）：`2019 out95 = {focus1_kord_spring_autumn_aft['Spring']['out95']}`, `wMAE = {focus1_kord_spring_autumn_aft['Spring']['wMAE']:.6f}`, `wResid = {focus1_kord_spring_autumn_aft['Spring']['wResid']:+.6f}`",
            f"- `KORD Autumn 14:00–20:00`（`cells={focus1_kord_spring_autumn_aft['Autumn']['cells']}`, `n_obs={focus1_kord_spring_autumn_aft['Autumn']['n_obs']}`）：`2019 out95 = {focus1_kord_spring_autumn_aft['Autumn']['out95']}`, `wMAE = {focus1_kord_spring_autumn_aft['Autumn']['wMAE']:.6f}`, `wResid = {focus1_kord_spring_autumn_aft['Autumn']['wResid']:+.6f}`",
            "",
            "| 站 | 季 | 时分 | 桶 | 2019 n | 2019 实测 emp | 2019 预测 pred | 2019 残差 | 2019 Wilson 95% CI | 2019 是否出界 |",
            "|:---|:---|:---|:---|---:|---:|---:|---:|:---|:---:|",
        ]
    )
    for r in focus1_round2_6_in_2019:
        lines.append(
            f"| {r['station']} | {r['season']} | {r['t_label']} | {r['pos_bucket']} | {r['n_bucket']} | {r['emp_no_new_raw']:.4f} | {r['pred_after']:.4f} | {r['resid_after']:+.4f} | [{r['wilson95_lo']:.4f}, {r['wilson95_hi']:.4f}] | `{r['outside_ci_after']}` |"
        )

    lines.extend(
        [
            "",
            "### 观察项 ②｜KMIA Winter early（原生最差格 vs 桥后对照）",
            "",
            f"- `KMIA Winter early`（`12h–30h`, `n_cell_days={focus2_kmia_winter_early['n_cell_days']}`）：",
            f"  - `inw`（8 谱带）：`ECE_native = {focus2_kmia_winter_early['ece_native_inw']:.6f}`, `ECE_mm_gauss = {focus2_kmia_winter_early['ece_mm_gauss_inw']:.6f}`, `ECE_bridge = {focus2_kmia_winter_early['ece_bridge_inw']:.6f}`（早段 `{focus2_kmia_winter_early['ece_bridge_early_inw']:.6f}` / 午后 `{focus2_kmia_winter_early['ece_bridge_aft_inw']:.6f}`），`Δ_bridge = {focus2_kmia_winter_early['delta_bridge_inw']:+.6f}`",
            f"  - `w20`（20 桶）：`ECE_native = {focus2_kmia_winter_early['ece_native_w20']:.6f}`, `ECE_mm_gauss = {focus2_kmia_winter_early['ece_mm_gauss_w20']:.6f}`, `ECE_bridge = {focus2_kmia_winter_early['ece_bridge_w20']:.6f}`（早段 `{focus2_kmia_winter_early['ece_bridge_early_w20']:.6f}` / 午后 `{focus2_kmia_winter_early['ece_bridge_aft_w20']:.6f}`），`Δ_bridge = {focus2_kmia_winter_early['delta_bridge_w20']:+.6f}`",
            "",
            "### 观察项 ③｜KMIA_12h 交易窗 ECE `0.0183` 挂旗读数在 v2 契约下的重读值",
            "",
            f"1. **2000–2018 20 折 Block-CV 原生挂旗同源重读（`n_bins={focus3_blockcv['n_bin_samples']}`, `{focus3_blockcv['n_daily_samples']}` 折·日）**：",
            f"   - 无膨胀旧挂旗基准（`c = 1.0000`）：`inw ECE = {focus3_blockcv['blockcv_inw_ece_raw_c1_stored']:.6f}`（重算 `{focus3_blockcv['blockcv_inw_ece_raw_c1_recomputed']:.6f}`），`w20 ECE = {focus3_blockcv['blockcv_w20_ece_raw_c1_stored']:.6f}`",
            f"   - **`v2` 契约重读（`s_oos = {focus3_blockcv['s_oos_v2']:.6f}`, `c = {focus3_blockcv['c_v2']:.6f}`）**：`inw ECE = {focus3_blockcv['blockcv_inw_ece_v2_c']:.6f}`, `w20 ECE = {focus3_blockcv['blockcv_w20_ece_v2_c']:.6f}`",
            f"   - 废弃 `v1` 参照（`s_oos = {focus3_blockcv['s_oos_v1']:.6f}`, `c = {focus3_blockcv['c_v1']:.6f}`）：`inw ECE = {focus3_blockcv['blockcv_inw_ece_v1_c']:.6f}`, `w20 ECE = {focus3_blockcv['blockcv_w20_ece_v1_c']:.6f}`",
            f"2. **2019 独立盲测 `KMIA_12h`（`v2` 契约 `c = {focus3_2019['c_v2']:.6f}`, `n={focus3_2019['n_days']}`）**：",
            f"   - `inw`: `ECE_native = {focus3_2019['ece_native_inw']:.6f}`, `ECE_mm_gauss = {focus3_2019['ece_mm_gauss_inw']:.6f}`, `ECE_bridge = {focus3_2019['ece_bridge_inw']:.6f}`, `Δ_bridge = {focus3_2019['delta_bridge_inw']:+.6f}`",
            f"   - `w20`: `ECE_native = {focus3_2019['ece_native_w20']:.6f}`, `ECE_mm_gauss = {focus3_2019['ece_mm_gauss_w20']:.6f}`, `ECE_bridge = {focus3_2019['ece_bridge_w20']:.6f}`, `Δ_bridge = {focus3_2019['delta_bridge_w20']:+.6f}`",
            f"   - 先验二阶与覆率：`s_oos_2019_after_c_v2 = {focus3_2019['s_oos_2019_after_c_v2']:.6f}`, `Bias = {focus3_2019['bias_f']:+.4f}°F`, `MAE = {focus3_2019['mae_f']:.4f}°F`, `Cov90_native = {focus3_2019['cov90_native']:.4f}`",
            "",
            "## 五、 22 格 2019 全网格逐格明细",
            "",
            "| Cell | Period | n | c_v2 | s_oos_2019 (after c_v2) | Bias(°F) | MAE(°F) | Cov90 | ECE_native (inw) | ECE_bridge (inw) | Δ_bridge (inw) | ECE_native (w20) | ECE_bridge (w20) |",
            "|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for r in cell_rows:
        lines.append(
            f"| {r['cell']} | {r['period']} | {r['n_days']} | {r['c_v2']:.4f} | {r['s_oos_2019_after_c_v2']:.4f} | {r['bias_f']:+.4f} | {r['mae_f']:.4f} | {r['cov90_native']:.4f} | "
            f"{r['ece_native_inw']:.6f} | {r['ece_bridge_inw']:.6f} | {r['delta_bridge_inw']:+.6f} | {r['ece_native_w20']:.6f} | {r['ece_bridge_w20']:.6f} |"
        )

    lines.extend(
        [
            "",
            "## 六、 产物索引",
            "",
            f"- 汇总 JSON: [`{OUT_JSON.name}`]({OUT_JSON.name})",
            f"- 16 层明细 CSV: [`{OUT_STRATA_CSV.name}`]({OUT_STRATA_CSV.name})",
            f"- 22 格明细 CSV: [`{OUT_CELLS_CSV.name}`]({OUT_CELLS_CSV.name})",
            f"- 2019 日内 696 桶原子残差 CSV: [`{OUT_ATOM_CSV.name}`]({OUT_ATOM_CSV.name})",
        ]
    )
    OUT_REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=== INSPECTION C 2019 REPLAY SUMMARY (NO VERDICT SIGNED) ===")
    print("Pooled:", json.dumps(pooled_summary))
    print("Focus 1 aft KORD Spring/Autumn:", json.dumps(focus1_kord_spring_autumn_aft))
    print("Focus 2 KMIA Winter early:", json.dumps({k: focus2_kmia_winter_early[k] for k in ["ece_native_inw", "ece_mm_gauss_inw", "ece_bridge_inw", "delta_bridge_inw", "ece_native_w20", "ece_bridge_w20", "delta_bridge_w20"]}))
    print("Focus 3 KMIA_12h Block-CV reread:", json.dumps(focus3_blockcv))
    print("Focus 3 KMIA_12h 2019 OOS:", json.dumps(focus3_2019))
    print("Atom 2019 aft_total_out95:", atom_2019_summary["aft_total_out95"], "/", atom_2019_summary["aft_total_cells"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
