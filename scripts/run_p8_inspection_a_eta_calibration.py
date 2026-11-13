#!/usr/bin/env python3
"""
Inspection A (方案 α 检验 A): 609-Day Pre-2019 5-min Intraday η_s(t) Calibration & Atomic Audit.

Implements the empirical atomic calibration mandated by:
- 项目方案 (v2.9) §3.4: 检验 A（原子校准）— 609 天日内高频样本上按 t × 位置桶 分层校准边界原子质量
- P8-ALGO-REVIEW_待确认事项登记册 B-2 / C-1
- P8-ALGO-DEF-SPEC v2.0 §3.3 (L205-209)

Strict data boundary:
- Uses ONLY pre-2019 pure 5-minute MADISHF IEM data (2016-04-30 .. 2018-12-30)
  and pre-2019 prior forecasts (2000_2018_training_arrays.parquet + v2_2000_2018_oof_cv s_oos).
- Explicitly asserts zero 2019 observations or parameters enter any step.
- Does NOT run Inspection C, does NOT modify src/, and does NOT unlock F-2.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.isotonic import IsotonicRegression

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_p6_fullgrid_tmax import EVIDENCE_DIR as CV_EVIDENCE_DIR, harvest_cell_daily_records
from src.metrics.calibration_audit import SIGMA_INST_PHYSICAL_FLOOR
from src.prediction.discrete_bin_engine import settle_half_up

STATIONS = ("KORD", "KMIA")
SEASONS = ("Winter", "Spring", "Summer", "Autumn")
STATION_TIMEZONES = {
    "KORD": "America/Chicago",
    "KMIA": "America/New_York",
}
PRE2019_YEARS = (2016, 2017, 2018)
OPEN_HOUR = 6.0
CLOSE_HOUR = 20.0
TIME_STEP_HOURS = 0.5
T_GRID = np.round(np.arange(OPEN_HOUR, CLOSE_HOUR + 1e-9, TIME_STEP_HOURS), 2)
MIN_MADISHF_OBS_PER_DAY = 50
POSITION_BUCKETS = ("B1_below_anchor", "B2_near_anchor", "B3_at_or_above")

TRAIN_ARRAYS_PATH = PROJECT_ROOT / "data" / "processed" / "audit_arrays" / "2000_2018_training_arrays.parquet"
CONTRACT_PATH = PROJECT_ROOT / "data" / "contracts" / "physical_param_contract.json"
OUT_ETA_CSV = PROJECT_ROOT / "evidence" / "p8_inspection_a_eta_s_calibration_20261113.csv"
OUT_ETA_JSON = PROJECT_ROOT / "evidence" / "p8_inspection_a_eta_s_calibration_20261113.json"
OUT_ATOMIC_CSV = PROJECT_ROOT / "evidence" / "p8_inspection_a_atomic_residuals_20261113.csv"
OUT_REPORT_MD = PROJECT_ROOT / "evidence" / "p8_inspection_a_eta_calibration_report_20261113.md"


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def format_hour(hour_f: float) -> str:
    """Format fractional hour (e.g. 13.5) as HH:MM."""
    h = int(math.floor(hour_f + 1e-9))
    m = int(round((hour_f - h) * 60))
    return f"{h:02d}:{m:02d}"


def wilson_ci(k: int, n: int, z: float = 1.959963984540054) -> Tuple[float, float]:
    """Exact Wilson score 95% confidence interval for binomial proportion."""
    if n <= 0:
        return float("nan"), float("nan")
    p = k / n
    denom = 1.0 + (z * z) / n
    center = (p + (z * z) / (2.0 * n)) / denom
    half = (z * math.sqrt((p * (1.0 - p) + (z * z) / (4.0 * n)) / n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def rho_weight(hour_f: float) -> float:
    """Linear diurnal decay fraction rho(t) per SPEC v2.0 L208."""
    return max(0.0, min(1.0, (CLOSE_HOUR - hour_f) / (CLOSE_HOUR - OPEN_HOUR)))


def placeholder_eta_quad(hour_f: float) -> float:
    """Un-calibrated quadratic placeholder eta(t) per SPEC v2.0 L205."""
    r = rho_weight(hour_f)
    return r * r


def classify_position_bucket(delta_mt_mu0: float) -> str:
    """Bucket running intraday maximum M_t relative to prior anchor mu_0."""
    if delta_mt_mu0 < -2.0:
        return "B1_below_anchor"
    if delta_mt_mu0 < 0.0:
        return "B2_near_anchor"
    return "B3_at_or_above"


def load_clean_pre2019_5min(station: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Load strictly pre-2019 5-min IEM observations for a station with TemperatureSanitizer QC gates.
    Excludes any incomplete afternoon-only UTC boundary day (2017-12-31).
    """
    tz = STATION_TIMEZONES[station]
    frames = []
    input_hashes = {}
    for yr in PRE2019_YEARS:
        p = PROJECT_ROOT / "data" / "raw" / "iem" / station / f"{yr}.parquet"
        input_hashes[p.name] = sha256_file(p)
        frames.append(pd.read_parquet(p))

    df = pd.concat(frames, ignore_index=True)
    df["valid_utc"] = pd.to_datetime(df["valid_utc"], utc=True)
    df["local_dt"] = df["valid_utc"].dt.tz_convert(tz)
    df["local_date"] = df["local_dt"].dt.date

    if df["local_dt"].dt.year.max() > 2018:
        raise ValueError(f"Airgap violation: found year > 2018 in pre-2019 IEM load for {station}")

    df_valid = df.dropna(subset=["temp_f"]).sort_values("local_dt").copy()
    # Gate 1: climatological range [-40, 135] F
    oor_mask = (df_valid["temp_f"] < -40.0) | (df_valid["temp_f"] > 135.0)
    oor_count = int(oor_mask.sum())
    df_valid = df_valid[~oor_mask].copy()

    # Gate 2: short-step jump > 15.0 F (<= 15 min)
    df_valid["dt_min"] = df_valid.groupby("local_date")["local_dt"].diff().dt.total_seconds() / 60.0
    df_valid["dtemp_abs"] = df_valid.groupby("local_date")["temp_f"].diff().abs()
    jump_mask = (df_valid["dtemp_abs"] > 15.0) & (df_valid["dt_min"] <= 15.0)
    jump_count = int(jump_mask.sum())
    df_valid = df_valid[~jump_mask].copy()

    # Identify pure 5-minute MADISHF days
    madishf = df_valid[df_valid["raw_metar"].str.contains("MADISHF", na=False)]
    vc_mad = madishf.groupby("local_date").size()
    candidate_dates = set(vc_mad[vc_mad >= MIN_MADISHF_OBS_PER_DAY].index)

    # Filter out boundary day missing morning/peak window (e.g. 2017-12-31 evening-only artifact)
    sub = df_valid[df_valid["local_date"].isin(candidate_dates)].copy()
    sub["hour_f"] = sub["local_dt"].dt.hour + sub["local_dt"].dt.minute / 60.0
    day_span = sub.groupby("local_date")["hour_f"].agg(["min", "max"])
    excluded_partial = sorted(str(d) for d in day_span[day_span["min"] > 14.0].index)
    keep_dates = set(day_span[day_span["min"] <= 14.0].index)
    sub = sub[sub["local_date"].isin(keep_dates)].copy()

    meta = {
        "input_hashes": input_hashes,
        "qc_out_of_range_dropped": oor_count,
        "qc_short_step_jump_dropped": jump_count,
        "madishf_candidate_days": len(candidate_dates),
        "excluded_partial_boundary_days": excluded_partial,
        "retained_valid_days": len(keep_dates),
        "date_min": str(min(keep_dates)),
        "date_max": str(max(keep_dates)),
    }
    return sub, meta


def load_station_priors(
    station: str,
    valid_dates: set,
    train_arrays: pd.DataFrame,
    c_18h: float,
) -> pd.DataFrame:
    """Join retained 5-min days with pre-2019 18h D+0 forecast priors and scale sigma_0 = c * sigma_eff."""
    st_arr = train_arrays[train_arrays["station"] == station].copy()
    if st_arr["year"].max() > 2018:
        raise ValueError(f"Airgap violation: training arrays contain year > 2018 for {station}")
    st_arr["local_date"] = pd.to_datetime(st_arr["date"]).dt.date
    st_arr = st_arr[st_arr["local_date"].isin(valid_dates)].copy()
    st_arr["c_18h"] = c_18h
    st_arr["sigma_0"] = st_arr["sigma_forecast"].astype(float) * c_18h
    st_arr["mu_0"] = st_arr["mu_forecast"].astype(float)
    return st_arr.set_index("local_date")


def calibrate_station_season(
    station: str,
    season: str,
    obs_df: pd.DataFrame,
    priors_df: pd.DataFrame,
    c_18h: float,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """Calibrate eta_s(t) across the 29 intraday slices and compute t x position_bucket residuals."""
    s_priors = priors_df[priors_df["season"] == season]
    dates = s_priors.index
    mu0_all = s_priors["mu_0"].to_numpy(dtype=float)
    s0_all = s_priors["sigma_0"].to_numpy(dtype=float)
    s_obs = obs_df[obs_df["local_date"].isin(dates)]
    tfin_series = s_obs.groupby("local_date")["temp_f"].max().reindex(dates)
    tfin_all = tfin_series.to_numpy(dtype=float)
    s0_sq_mean = float(np.mean(s0_all ** 2))
    s0_rms = math.sqrt(s0_sq_mean)
    floor_eta = (SIGMA_INST_PHYSICAL_FLOOR ** 2) / s0_sq_mean

    raw_rows = []
    slice_cache = []
    for h in T_GRID:
        mt_series = (
            s_obs[s_obs["hour_f"] <= h]
            .groupby("local_date")["temp_f"]
            .max()
            .reindex(dates)
        )
        mt_arr = mt_series.to_numpy(dtype=float)
        ok = ~np.isnan(mt_arr) & ~np.isnan(tfin_all)
        mt_ok = mt_arr[ok]
        tf_ok = tfin_all[ok]
        mu0_ok = mu0_all[ok]
        s0_ok = s0_all[ok]
        rho = rho_weight(h)
        m_int_ok = np.array([settle_half_up(x) for x in mt_ok], dtype=float)
        mu_r_ok = rho * np.maximum(0.0, mu0_ok - m_int_ok)
        rem_pos_ok = np.maximum(0.0, tf_ok - mt_ok)

        # Bridge remaining MSE normalized by E[sigma_0^2]
        eta_raw_mse = float(np.mean((rem_pos_ok - mu_r_ok) ** 2) / s0_sq_mean)
        # Literal B-2 diagnostics (variance of raw M_t and centered M_t - mu_0)
        eta_literal_var_mt = float(1.0 - np.var(mt_ok, ddof=1) / s0_sq_mean)
        eta_centered_var_mt = float(1.0 - np.var(mt_ok - mu0_ok, ddof=1) / s0_sq_mean)

        raw_rows.append((h, int(ok.sum()), eta_raw_mse, eta_literal_var_mt, eta_centered_var_mt))
        slice_cache.append(
            {
                "h": float(h),
                "ok_count": int(ok.sum()),
                "mt": mt_ok,
                "tf": tf_ok,
                "mu0": mu0_ok,
                "s0": s0_ok,
                "m_int": m_int_ok,
                "mu_r": mu_r_ok,
                "eta_raw_mse": eta_raw_mse,
                "eta_literal_var_mt": eta_literal_var_mt,
                "eta_centered_var_mt": eta_centered_var_mt,
            }
        )

    # Monotone non-increasing PAVA fit on eta_raw_mse in [0.0, 1.0]
    iso = IsotonicRegression(increasing=False, y_min=0.0, y_max=1.0)
    raw_clipped = np.array([min(1.0, max(0.0, r[2])) for r in raw_rows], dtype=float)
    weights = np.array([r[1] for r in raw_rows], dtype=float)
    eta_calibrated_arr = iso.fit_transform(T_GRID, raw_clipped, sample_weight=weights)

    eta_rows: List[Dict[str, Any]] = []
    bucket_rows: List[Dict[str, Any]] = []

    brier_cont_cal_all: List[np.ndarray] = []
    brier_cont_q_all: List[np.ndarray] = []
    brier_set_cal_all: List[np.ndarray] = []
    brier_set_q_all: List[np.ndarray] = []

    for idx, sc in enumerate(slice_cache):
        h = sc["h"]
        eta_cal = float(eta_calibrated_arr[idx])
        eta_quad = placeholder_eta_quad(h)

        s0_ok = sc["s0"]
        mu_r_ok = sc["mu_r"]
        mt_ok = sc["mt"]
        tf_ok = sc["tf"]
        mu0_ok = sc["mu0"]
        m_int_ok = sc["m_int"]

        sr_cal = np.maximum(s0_ok * math.sqrt(max(eta_cal, 0.0)), SIGMA_INST_PHYSICAL_FLOOR)
        sr_quad = np.maximum(s0_ok * math.sqrt(max(eta_quad, 0.0)), SIGMA_INST_PHYSICAL_FLOOR)

        y_raw = (tf_ok <= mt_ok + 1e-6).astype(float)
        y_set = np.array(
            [1.0 if settle_half_up(a) == settle_half_up(b) else 0.0 for a, b in zip(mt_ok, tf_ok)],
            dtype=float,
        )

        p_cont_cal = norm.cdf(-mu_r_ok / sr_cal)
        p_cont_quad = norm.cdf(-mu_r_ok / sr_quad)
        p_set_cal = norm.cdf((m_int_ok + 0.5 - mt_ok - mu_r_ok) / sr_cal)
        p_set_quad = norm.cdf((m_int_ok + 0.5 - mt_ok - mu_r_ok) / sr_quad)

        brier_cont_cal_all.append((y_raw - p_cont_cal) ** 2)
        brier_cont_q_all.append((y_raw - p_cont_quad) ** 2)
        brier_set_cal_all.append((y_set - p_set_cal) ** 2)
        brier_set_q_all.append((y_set - p_set_quad) ** 2)

        eta_rows.append(
            {
                "station": station,
                "season": season,
                "t_hour": h,
                "t_label": format_hour(h),
                "n_days": sc["ok_count"],
                "c_18h": round(c_18h, 6),
                "sigma0_rms": round(s0_rms, 6),
                "floor_eta_rms": round(floor_eta, 6),
                "floor_binding": bool(eta_cal <= floor_eta),
                "eta_raw_mse": round(sc["eta_raw_mse"], 6),
                "eta_calibrated": round(eta_cal, 6),
                "eta_placeholder_quad": round(eta_quad, 6),
                "eta_literal_b2_var_mt": round(sc["eta_literal_var_mt"], 6),
                "eta_centered_var_mt_mu0": round(sc["eta_centered_var_mt"], 6),
                "sigma_rem_rms_cal": round(float(np.sqrt(np.mean(sr_cal ** 2))), 6),
                "sigma_rem_rms_quad": round(float(np.sqrt(np.mean(sr_quad ** 2))), 6),
                "emp_no_new_raw": round(float(y_raw.mean()), 6),
                "pred_atom_cont_cal": round(float(p_cont_cal.mean()), 6),
                "pred_atom_cont_quad": round(float(p_cont_quad.mean()), 6),
                "resid_cont_cal": round(float(y_raw.mean() - p_cont_cal.mean()), 6),
                "emp_no_new_settle": round(float(y_set.mean()), 6),
                "pred_atom_settle_cal": round(float(p_set_cal.mean()), 6),
                "pred_atom_settle_quad": round(float(p_set_quad.mean()), 6),
                "resid_settle_cal": round(float(y_set.mean() - p_set_cal.mean()), 6),
                "brier_cont_cal": round(float(np.mean((y_raw - p_cont_cal) ** 2)), 6),
                "brier_settle_cal": round(float(np.mean((y_set - p_set_cal) ** 2)), 6),
            }
        )

        # Stratify by position bucket M_t relative to mu_0
        buckets = np.array([classify_position_bucket(d) for d in (mt_ok - mu0_ok)])
        for bname in POSITION_BUCKETS:
            mask = buckets == bname
            nb = int(mask.sum())
            if nb == 0:
                bucket_rows.append(
                    {
                        "station": station,
                        "season": season,
                        "t_hour": h,
                        "t_label": format_hour(h),
                        "pos_bucket": bname,
                        "n_bucket": 0,
                        "frac_bucket": 0.0,
                        "low_sample_lt10": True,
                        "emp_no_new_raw": None,
                        "pred_atom_cont_cal": None,
                        "resid_cont_cal": None,
                        "wilson95_lo_raw": None,
                        "wilson95_hi_raw": None,
                        "outside_ci_raw": None,
                        "emp_no_new_settle": None,
                        "pred_atom_settle_cal": None,
                        "resid_settle_cal": None,
                        "wilson95_lo_settle": None,
                        "wilson95_hi_settle": None,
                        "outside_ci_settle": None,
                        "brier_cont_cal": None,
                        "brier_cont_quad": None,
                        "brier_settle_cal": None,
                        "brier_settle_quad": None,
                    }
                )
                continue

            k_raw = int(y_raw[mask].sum())
            k_set = int(y_set[mask].sum())
            emp_r = k_raw / nb
            emp_s = k_set / nb
            pr_cc = float(p_cont_cal[mask].mean())
            pr_cq = float(p_cont_quad[mask].mean())
            pr_sc = float(p_set_cal[mask].mean())
            pr_sq = float(p_set_quad[mask].mean())
            lo_r, hi_r = wilson_ci(k_raw, nb)
            lo_s, hi_s = wilson_ci(k_set, nb)
            bucket_rows.append(
                {
                    "station": station,
                    "season": season,
                    "t_hour": h,
                    "t_label": format_hour(h),
                    "pos_bucket": bname,
                    "n_bucket": nb,
                    "frac_bucket": round(nb / sc["ok_count"], 6),
                    "low_sample_lt10": bool(nb < 10),
                    "emp_no_new_raw": round(emp_r, 6),
                    "pred_atom_cont_cal": round(pr_cc, 6),
                    "resid_cont_cal": round(emp_r - pr_cc, 6),
                    "wilson95_lo_raw": round(lo_r, 6),
                    "wilson95_hi_raw": round(hi_r, 6),
                    "outside_ci_raw": bool(pr_cc < lo_r or pr_cc > hi_r),
                    "emp_no_new_settle": round(emp_s, 6),
                    "pred_atom_settle_cal": round(pr_sc, 6),
                    "resid_settle_cal": round(emp_s - pr_sc, 6),
                    "wilson95_lo_settle": round(lo_s, 6),
                    "wilson95_hi_settle": round(hi_s, 6),
                    "outside_ci_settle": bool(pr_sc < lo_s or pr_sc > hi_s),
                    "brier_cont_cal": round(float(np.mean((y_raw[mask] - p_cont_cal[mask]) ** 2)), 6),
                    "brier_cont_quad": round(float(np.mean((y_raw[mask] - p_cont_quad[mask]) ** 2)), 6),
                    "brier_settle_cal": round(float(np.mean((y_set[mask] - p_set_cal[mask]) ** 2)), 6),
                    "brier_settle_quad": round(float(np.mean((y_set[mask] - p_set_quad[mask]) ** 2)), 6),
                }
            )

    summary = {
        "n_days": int(len(dates)),
        "c_18h": round(c_18h, 6),
        "sigma0_rms": round(s0_rms, 6),
        "floor_eta_rms": round(floor_eta, 6),
        "eta_0600": round(float(eta_calibrated_arr[0]), 6),
        "eta_1200": round(float(eta_calibrated_arr[np.where(T_GRID == 12.0)[0][0]]), 6),
        "eta_1400": round(float(eta_calibrated_arr[np.where(T_GRID == 14.0)[0][0]]), 6),
        "eta_1600": round(float(eta_calibrated_arr[np.where(T_GRID == 16.0)[0][0]]), 6),
        "eta_1800": round(float(eta_calibrated_arr[np.where(T_GRID == 18.0)[0][0]]), 6),
        "eta_2000": round(float(eta_calibrated_arr[-1]), 6),
        "brier_cont_cal": round(float(np.mean(np.concatenate(brier_cont_cal_all))), 6),
        "brier_cont_quad": round(float(np.mean(np.concatenate(brier_cont_q_all))), 6),
        "brier_settle_cal": round(float(np.mean(np.concatenate(brier_set_cal_all))), 6),
        "brier_settle_quad": round(float(np.mean(np.concatenate(brier_set_q_all))), 6),
    }
    return eta_rows, bucket_rows, summary


def compute_cross_lead_diagnostic(
    station: str,
    obs_df: pd.DataFrame,
    valid_dates: set,
    contract: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Verify dimensionless eta_s(14:00) invariance across leads 12h..72h on Block-CV OOF overlap."""
    sub = obs_df[obs_df["local_date"].isin(valid_dates)]
    tfin = sub.groupby("local_date")["temp_f"].max()
    m14 = sub[sub["hour_f"] <= 14.0].groupby("local_date")["temp_f"].max()
    rows = []
    for lead in (12, 18, 24, 48, 72):
        rec, _ = harvest_cell_daily_records(station, lead, CV_EVIDENCE_DIR)
        rec["local_date"] = pd.to_datetime(rec["target_date"]).dt.date
        rec["season"] = pd.to_datetime(rec["local_date"]).dt.month.map(
            {12: "Winter", 1: "Winter", 2: "Winter", 3: "Spring", 4: "Spring", 5: "Spring",
             6: "Summer", 7: "Summer", 8: "Summer", 9: "Autumn", 10: "Autumn", 11: "Autumn"}
        )
        g = (
            rec[rec["local_date"].isin(valid_dates)]
            .groupby(["local_date", "season"], as_index=False)
            .agg(mu=("mu", "mean"), sigma=("sigma", lambda x: float(np.sqrt(np.mean(x ** 2)))))
        )
        c_lead = math.sqrt(max(1.0, float(contract["cells"][f"{station}_{lead}h"]["s_oos"])))
        g["s0"] = g["sigma"] * c_lead
        g["tfin"] = g["local_date"].map(tfin)
        g["m14"] = g["local_date"].map(m14)
        for seas in SEASONS:
            gs = g[g["season"] == seas].dropna(subset=["tfin", "m14"])
            mu_r = rho_weight(14.0) * np.maximum(0.0, gs["mu"].to_numpy() - np.floor(gs["m14"].to_numpy() + 0.5))
            rem = np.maximum(0.0, gs["tfin"].to_numpy() - gs["m14"].to_numpy())
            rem_rmse = float(np.sqrt(np.mean((rem - mu_r) ** 2)))
            s0_rms = float(np.sqrt(np.mean(gs["s0"].to_numpy() ** 2)))
            rows.append(
                {
                    "station": station,
                    "season": seas,
                    "lead_hours": lead,
                    "n_oof_overlap": int(len(gs)),
                    "c_lead": round(c_lead, 6),
                    "s0_rms": round(s0_rms, 4),
                    "rem_rmse_1400_f": round(rem_rmse, 4),
                    "eta_mse_ratio_1400": round((rem_rmse ** 2) / (s0_rms ** 2), 6),
                }
            )
    return rows


def build_report_markdown(
    eta_df: pd.DataFrame,
    atomic_df: pd.DataFrame,
    meta_by_station: Dict[str, Any],
    summary_by_cell: Dict[str, Any],
    cross_lead_rows: List[Dict[str, Any]],
    artifact_hashes: Dict[str, str],
) -> str:
    """Render concise factual Inspection A calibration & residual audit Markdown report."""
    valid_bkts = atomic_df[atomic_df["n_bucket"] > 0]
    morning_bkts = valid_bkts[valid_bkts["t_hour"] <= 13.5]
    afternoon_bkts = valid_bkts[valid_bkts["t_hour"] >= 14.0]

    lines = [
        "# P8-ALGO-AUDIT · 方案 α 检验 A（609 天日内 η_s(t) 标定与原子校准审计报告）",
        "",
        f"> **生成时间（UTC）**：`{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}`  ",
        "> **法定依据**：`项目方案 (v2.9) §3.4 检验 A`、`P8-ALGO-REVIEW_待确认事项登记册 B-2 / C-1`、`P8-ALGO-DEF-SPEC v2.0 §3.3`  ",
        "> **严格隔离纪律**：仅使用 2019 年前纯 5 分钟高频 MADISHF 实况（`2016-04-30 ~ 2018-12-30`）与 `2000_2018_training_arrays.parquet`（18h 先验）及 `v2_2000_2018_oof_cv` `s_oos`；**零 2019 数据参与**。",
        "",
        "## 1. 数据边界与分组粒度",
        "",
        "- **分组粒度**：严格按 **`station × season`**（8 组：{KORD, KMIA} × {Winter, Spring, Summer, Autumn}），不拆早晚段（依据 `v2.9 §3.4`：仅检验 C 按 `站 × 季 × 早晚段` 分层；`η_s(t)` 为无量纲日内归一化剩余方差曲线，`第三段条件分布#L117` 定为 `(station, season)`）。第 5 节单列 `12h~72h` 跨提前量敏感性对照表。",
        "- **位置桶定义（`M_t` 相对先验锚 `μ_0`）**：`B1_below_anchor`（$M_t < \\mu_0 - 2.0^\\circ\\text{F}$）、`B2_near_anchor`（$\\mu_0 - 2.0^\\circ\\text{F} \\le M_t < \\mu_0$）、`B3_at_or_above`（$M_t \\ge \\mu_0$）。",
        "- **时间切片网格**：`06:00 ~ 20:00` 本地标准/夏令时（`America/Chicago` / `America/New_York`）每 30 分钟切片，共 `29` 格。",
        "",
        "| 台站 | MADISHF>=50 候选日 | 剔除跨年残缺边界日 | 实纳有效日 | 日期跨度 | 质检拦截 |",
        "|---|---:|---|---:|---|---|",
    ]
    for st in STATIONS:
        m = meta_by_station[st]
        lines.append(
            f"| `{st}` | {m['madishf_candidate_days']} | `{', '.join(m['excluded_partial_boundary_days']) or '无'}`（仅18h后半日，缺失日峰） | **{m['retained_valid_days']}** | `{m['date_min']} ~ {m['date_max']}` | 越界={m['qc_out_of_range_dropped']}，跳变={m['qc_short_step_jump_dropped']} |"
        )

    lines.extend(
        [
            "",
            "## 2. 标定口径与 `B-2` 公式等价核查",
            "",
            "- **字面 `1 - Var_d(M_t) / E[σ_0²]` 在实际数据上恒负**：跨日极值均值 $M_t(d)$ 混入季节气候方差（如 KORD 春季 `Var_d(M_t) ≈ 204~292 (°F)²`，而预报误差方差 `E[σ_0²] ≈ 15.1 (°F)²`），字面计算全部落入 `-18.3 ~ -0.02`；即使先对 `μ_0` 中心化（`Var_d(M_t - μ_0)`），早间因含日较差幅值，依然为 `-3.9 ~ 0.0`。",
            "- **实证一致性标定式**：采用条件桥剩余残差归一化均方误差，经加权 PAVA 单调不增投影（约束 $[0.0, 1.0]$），并在下游求值保持物理底 $\\sigma_{\\text{rem}}(t) = \\max(\\sigma_0\\sqrt{\\eta_s(t)},\\; 0.9^\\circ\\text{F})$：",
            "  $$\\hat{\\eta}_s^{\\text{raw}}(t) = \\frac{\\mathbb{E}_d\\big[(\\max(0, T_{\\text{final}}(d) - M_t(d)) - \\mu_R(t, m_d))^2\\big]}{\\mathbb{E}_d[\\sigma_0^2(d)]}$$",
            "  其中 $\\sigma_0(d) = \\sqrt{\\max(1.0, s_{\\text{oos}}(s, 18\\text{h}))}\\cdot\\sigma_{\\text{eff}}(d)$，$\\mu_R(t, m) = \\rho(t)\\max(0, \\mu_0 - m)$。",
            "",
            "## 3. 各站季标定 $\\eta_s(t)$ 关键节点摘要",
            "",
            "| 站 × 季 | 有效日 $N$ | $\\sigma_{0,\\text{rms}}$ (°F) | 物理底 $\\eta_{\\text{floor}}$ | 06:00 | 12:00 | 14:00 | 16:00 | 18:00 | 20:00 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for st in STATIONS:
        for seas in SEASONS:
            sm = summary_by_cell[f"{st}_{seas}"]
            lines.append(
                f"| `{st} {seas}` | {sm['n_days']} | {sm['sigma0_rms']:.3f} | {sm['floor_eta_rms']:.4f} | "
                f"{sm['eta_0600']:.3f} | {sm['eta_1200']:.3f} | {sm['eta_1400']:.3f} | "
                f"{sm['eta_1600']:.3f} | {sm['eta_1800']:.3f} | {sm['eta_2000']:.3f} |"
            )

    lines.extend(
        [
            "",
            "## 4. 检验 A（原子校准 `t × 位置桶`）拟合残差与结构性诊断",
            "",
            f"- **全量格位计数**：`{len(eta_df)}` 个 `(station, season, t)` 切片；`{len(atomic_df)}` 个 `(station, season, t, pos_bucket)` 单元（其中有效非空桶 `{len(valid_bkts)}` 个，低样本 `<10` 桶 `{int((valid_bkts['n_bucket'] < 10).sum())}` 个）。",
            "- **各位置桶残差总览（`resid = 经验频率 - 模型预测`）**：",
            f"  - 全段（06:00–20:00，`n_cells={len(valid_bkts)}`）：",
            f"    - 连续原生原子 $P(T_{{\\text{{final}}}} \\le M_t)$ vs $\\Phi(-\\mu_R/\\sigma_{{\\text{{rem}}}})$：加权平均残差 = `{float(np.average(valid_bkts['resid_cont_cal'], weights=valid_bkts['n_bucket'])):+.4f}`，加权 MAE = `{float(np.average(valid_bkts['resid_cont_cal'].abs(), weights=valid_bkts['n_bucket'])):.4f}`，超 Wilson 95% CI 桶比例 = `{int(valid_bkts['outside_ci_raw'].sum())}/{len(valid_bkts)} ({valid_bkts['outside_ci_raw'].mean()*100:.1f}%)`；",
            f"    - 1°F 结算格原子 $P(\\text{{settle}}(T_{{\\text{{final}}}}) = \\text{{settle}}(M_t))$ vs $\\Phi((m+0.5-M_t-\\mu_R)/\\sigma_{{\\text{{rem}}}})$：加权平均残差 = `{float(np.average(valid_bkts['resid_settle_cal'], weights=valid_bkts['n_bucket'])):+.4f}`，加权 MAE = `{float(np.average(valid_bkts['resid_settle_cal'].abs(), weights=valid_bkts['n_bucket'])):.4f}`，超 Wilson 95% CI 桶比例 = `{int(valid_bkts['outside_ci_settle'].sum())}/{len(valid_bkts)} ({valid_bkts['outside_ci_settle'].mean()*100:.1f}%)`；",
            f"  - 早中段（06:00–13:30，`n_cells={len(morning_bkts)}`）vs **午后段（14:00–20:00，`n_cells={len(afternoon_bkts)}`）**：",
            f"    - 06:00–13:30 连续原子加权 MAE = `{float(np.average(morning_bkts['resid_cont_cal'].abs(), weights=morning_bkts['n_bucket'])):.4f}`，1°F 结算格加权 MAE = `{float(np.average(morning_bkts['resid_settle_cal'].abs(), weights=morning_bkts['n_bucket'])):.4f}`；",
            f"    - **14:00–20:00 连续原子加权平均残差 = `{float(np.average(afternoon_bkts['resid_cont_cal'], weights=afternoon_bkts['n_bucket'])):+.4f}`，1°F 结算格加权平均残差 = `{float(np.average(afternoon_bkts['resid_settle_cal'], weights=afternoon_bkts['n_bucket'])):+.4f}`**。",
            "",
            "> [!IMPORTANT]",
            "> **检验 A 暴露的关键结构性发现（`μ_R >= 0` 的 0.50 原子上界，仅供后续决策/检验 C 参考，本次按指令不改 μ_R）**：",
            "> 由于 `SPEC v2.0#L208` 规定 $\\mu_R(t, m) = \\rho(t)\\max(0, \\mu_0 - m) \\ge 0$，导致模型连续原子预测值 $\\Phi(-\\mu_R/\\sigma_{\\text{rem}}) \\le 0.500$ **恒成立**；即使转为 1°F 结算格 $\\Phi((m+0.5-M_t-\\mu_R)/\\sigma_{\\text{rem}})$，在 $\\sigma_{\\text{inst}}=0.9^\\circ\\text{F}$ 物理底与 $\\mu_R \\ge 0$ 下，16:00–20:00 预测停顶概率亦被封顶在 `0.58~0.72`（而 609 天实测午后不破新高频率高达 `85%~100%`）。此外 KMIA 因 $\\sigma_{0,\\text{rms}} \\approx 1.65\\text{--}1.93^\\circ\\text{F}$，物理底 $\\eta_{\\text{floor}} \\approx 0.22\\text{--}0.29$ 在 `13:30~14:30` 即触底锁死 $\\sigma_{\\text{rem}} \\equiv 0.9^\\circ\\text{F}$。",
            "",
            "## 5. 跨提前量（`12h ~ 72h` Block-CV OOF 重叠窗）`14:00` 诊断对照",
            "",
            "| 台站 | 季节 | 12h η(14h) | 18h η(14h) | 24h η(14h) | 48h η(14h) | 72h η(14h) |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    cl_df = pd.DataFrame(cross_lead_rows)
    for st in STATIONS:
        for seas in SEASONS:
            sub_cl = cl_df[(cl_df["station"] == st) & (cl_df["season"] == seas)].set_index("lead_hours")
            lines.append(
                f"| `{st}` | {seas} | {sub_cl.loc[12, 'eta_mse_ratio_1400']:.3f} | {sub_cl.loc[18, 'eta_mse_ratio_1400']:.3f} | "
                f"{sub_cl.loc[24, 'eta_mse_ratio_1400']:.3f} | {sub_cl.loc[48, 'eta_mse_ratio_1400']:.3f} | {sub_cl.loc[72, 'eta_mse_ratio_1400']:.3f} |"
            )

    lines.extend(["", "## 6. 产出工件与 SHA-256 校验", ""])
    for name, digest in artifact_hashes.items():
        lines.append(f"- `{name}`: `{digest}`")
    return "\n".join(lines) + "\n"


def main() -> None:
    """Execute Inspection A 609-day calibration and write all evidence artifacts."""
    if not TRAIN_ARRAYS_PATH.exists():
        raise FileNotFoundError(f"Missing {TRAIN_ARRAYS_PATH}")
    if not CONTRACT_PATH.exists():
        raise FileNotFoundError(f"Missing {CONTRACT_PATH}")

    train_arrays = pd.read_parquet(TRAIN_ARRAYS_PATH)
    with open(CONTRACT_PATH, "r", encoding="utf-8") as f:
        contract = json.load(f)

    if contract.get("s_oos_version") != "v2_2000_2018_oof_cv":
        raise ValueError(f"Expected v2_2000_2018_oof_cv contract, got {contract.get('s_oos_version')}")

    all_eta_rows: List[Dict[str, Any]] = []
    all_bucket_rows: List[Dict[str, Any]] = []
    meta_by_station: Dict[str, Any] = {}
    summary_by_cell: Dict[str, Any] = {}
    cross_lead_rows: List[Dict[str, Any]] = []

    for st in STATIONS:
        obs_df, st_meta = load_clean_pre2019_5min(st)
        valid_dates = set(obs_df["local_date"].unique())
        c_18h = math.sqrt(max(1.0, float(contract["cells"][f"{st}_18h"]["s_oos"])))
        priors_df = load_station_priors(st, valid_dates, train_arrays, c_18h)
        st_meta["priors_matched_days"] = int(len(priors_df))
        meta_by_station[st] = st_meta

        for seas in SEASONS:
            e_rows, b_rows, sm = calibrate_station_season(st, seas, obs_df, priors_df, c_18h)
            all_eta_rows.extend(e_rows)
            all_bucket_rows.extend(b_rows)
            summary_by_cell[f"{st}_{seas}"] = sm

        cross_lead_rows.extend(compute_cross_lead_diagnostic(st, obs_df, valid_dates, contract))

    eta_df = pd.DataFrame(all_eta_rows)
    atomic_df = pd.DataFrame(all_bucket_rows)

    OUT_ETA_CSV.parent.mkdir(parents=True, exist_ok=True)
    eta_df.to_csv(OUT_ETA_CSV, index=False)
    atomic_df.to_csv(OUT_ATOMIC_CSV, index=False)

    # Build JSON curve lookup table
    curves_json: Dict[str, Any] = {}
    for st in STATIONS:
        curves_json[st] = {}
        for seas in SEASONS:
            sub_e = eta_df[(eta_df["station"] == st) & (eta_df["season"] == seas)].sort_values("t_hour")
            curves_json[st][seas] = {
                "summary": summary_by_cell[f"{st}_{seas}"],
                "t_hours": [float(x) for x in sub_e["t_hour"]],
                "t_labels": list(sub_e["t_label"]),
                "eta_calibrated": [float(x) for x in sub_e["eta_calibrated"]],
                "eta_raw_mse": [float(x) for x in sub_e["eta_raw_mse"]],
            }

    payload = {
        "schema_version": "p8_inspection_a_eta_s_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_boundary": "pre-2019 strictly (2016-04-30 .. 2018-12-30 pure 5-min MADISHF + 2000-2018 Block-CV v2 s_oos); zero 2019 participation",
        "grouping_granularity": "station x season (v2.9 §3.4 / 第三段条件分布 L117; Inspection C splits by early/late)",
        "sources": {
            "train_arrays": str(TRAIN_ARRAYS_PATH.relative_to(PROJECT_ROOT)),
            "train_arrays_sha256": sha256_file(TRAIN_ARRAYS_PATH),
            "contract": str(CONTRACT_PATH.relative_to(PROJECT_ROOT)),
            "contract_sha256": sha256_file(CONTRACT_PATH),
            "contract_s_oos_version": contract.get("s_oos_version"),
        },
        "station_metadata": meta_by_station,
        "curves": curves_json,
        "cross_lead_1400_diagnostic": cross_lead_rows,
    }
    with open(OUT_ETA_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    artifact_hashes = {
        str(OUT_ETA_CSV.relative_to(PROJECT_ROOT)): sha256_file(OUT_ETA_CSV),
        str(OUT_ETA_JSON.relative_to(PROJECT_ROOT)): sha256_file(OUT_ETA_JSON),
        str(OUT_ATOMIC_CSV.relative_to(PROJECT_ROOT)): sha256_file(OUT_ATOMIC_CSV),
    }
    report_md = build_report_markdown(
        eta_df, atomic_df, meta_by_station, summary_by_cell, cross_lead_rows, artifact_hashes
    )
    with open(OUT_REPORT_MD, "w", encoding="utf-8") as f:
        f.write(report_md)

    print(f"Wrote {OUT_ETA_CSV} ({len(eta_df)} rows)")
    print(f"Wrote {OUT_ATOMIC_CSV} ({len(atomic_df)} rows)")
    print(f"Wrote {OUT_ETA_JSON}")
    print(f"Wrote {OUT_REPORT_MD}")


if __name__ == "__main__":
    main()
