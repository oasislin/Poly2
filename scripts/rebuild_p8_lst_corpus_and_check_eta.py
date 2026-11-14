#!/usr/bin/env python3
"""
Task 1 — Rebuild strictly separate LST-day-boundary pre-2019 (608-day) & 2019 corpora (_lst suffix)
and run eta_s(t) sensitivity comparison against frozen Inspection A table.

Day boundary definition:
- Calendar day `local_date` uses fixed Local Standard Time (KORD: Etc/GMT+6 CST; KMIA: Etc/GMT+5 EST),
  matching GHCN-Daily / NWS CLI `[00:00 LST, 23:59 LST]`.
- Intraday replay clock axis `06:00..20:00` remains local wall-clock (`America/Chicago` / `America/New_York`),
  keeping solar-cycle alignment untouched (`23:00-01:00` boundary shift only) while strictly isolating
  `local_date` so midnight `00:00-00:59 CDT/EDT` belongs to the prior LST day.
- Also logs pure-LST clock sensitivity as diagnostic comparison.

Read-only toward raw/frozen assets: writes only NEW *_lst artifacts under evidence/.
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
from sklearn.isotonic import IsotonicRegression

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_p8_inspection_a_eta_calibration import (
    CONTRACT_PATH,
    MIN_MADISHF_OBS_PER_DAY,
    PRE2019_YEARS,
    SEASONS,
    SIGMA_INST_PHYSICAL_FLOOR,
    STATION_TIMEZONES,
    STATIONS,
    T_GRID,
    TRAIN_ARRAYS_PATH,
    classify_position_bucket,
    format_hour,
    load_station_priors,
    rho_weight,
    settle_half_up,
    sha256_file,
)

LST_TIMEZONES = {
    "KORD": "Etc/GMT+6",
    "KMIA": "Etc/GMT+5",
}

FROZEN_ETA_CSV = PROJECT_ROOT / "evidence" / "p8_inspection_a_eta_s_calibration_20261113.csv"
GHCN_DIR = PROJECT_ROOT / "data" / "processed" / "truth_ghcn_daily"

OUT_608_5MIN_LST = PROJECT_ROOT / "evidence" / "p8_608d_5min_lst.parquet"
OUT_608_SNAP_LST = PROJECT_ROOT / "evidence" / "p8_608d_snapshots_lst.parquet"
OUT_2019_5MIN_LST = PROJECT_ROOT / "evidence" / "p8_2019_5min_lst.parquet"
OUT_ETA_LST_CSV = PROJECT_ROOT / "evidence" / "p8_eta_s_calibration_lst.csv"
OUT_ETA_LST_JSON = PROJECT_ROOT / "evidence" / "p8_eta_s_calibration_lst.json"


def _qc_clean_lst_day_boundary(
    df_raw: pd.DataFrame,
    station: str,
    allowed_years: Tuple[int, ...],
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """QC clean 5-min IEM data with LST calendar day boundary and preserved wall-clock hour_f."""
    tz_lst = LST_TIMEZONES[station]
    tz_wall = STATION_TIMEZONES[station]

    df = df_raw.copy()
    df["valid_utc"] = pd.to_datetime(df["valid_utc"], utc=True)
    df["lst_dt"] = df["valid_utc"].dt.tz_convert(tz_lst)
    df["wall_dt"] = df["valid_utc"].dt.tz_convert(tz_wall)
    df["local_date"] = df["lst_dt"].dt.date

    if df["lst_dt"].dt.year.max() > max(allowed_years):
        raise ValueError(f"Airgap/year violation for {station}: max lst year {df['lst_dt'].dt.year.max()} > {max(allowed_years)}")

    df = df[df["lst_dt"].dt.year.isin(allowed_years)].copy()
    df_valid = df.dropna(subset=["temp_f"]).sort_values("valid_utc").copy()

    oor_mask = (df_valid["temp_f"] < -40.0) | (df_valid["temp_f"] > 135.0)
    oor_count = int(oor_mask.sum())
    df_valid = df_valid[~oor_mask].copy()

    df_valid["dt_min"] = df_valid.groupby("local_date")["valid_utc"].diff().dt.total_seconds() / 60.0
    df_valid["dtemp_abs"] = df_valid.groupby("local_date")["temp_f"].diff().abs()
    jump_mask = (df_valid["dtemp_abs"] > 15.0) & (df_valid["dt_min"] <= 15.0)
    jump_count = int(jump_mask.sum())
    df_valid = df_valid[~jump_mask].copy()

    madishf = df_valid[df_valid["raw_metar"].astype(str).str.contains("MADISHF", na=False)]
    vc_mad = madishf.groupby("local_date").size()
    candidate_dates = set(vc_mad[vc_mad >= MIN_MADISHF_OBS_PER_DAY].index)

    sub = df_valid[df_valid["local_date"].isin(candidate_dates)].copy()
    sub["lst_hour_f"] = sub["lst_dt"].dt.hour + sub["lst_dt"].dt.minute / 60.0
    sub["wall_hour_f"] = sub["wall_dt"].dt.hour + sub["wall_dt"].dt.minute / 60.0
    # Relative elapsed wall-clock hour anchored at local_date (DST post-midnight 00:00..00:59 of d+1 maps to 24.0..24.99)
    sub["wall_same_day"] = sub["wall_dt"].dt.date == sub["local_date"]
    sub["hour_f"] = np.where(sub["wall_same_day"], sub["wall_hour_f"], sub["wall_hour_f"] + 24.0)

    day_span = sub.groupby("local_date")["lst_hour_f"].agg(["min", "max"])
    excluded_partial = sorted(str(d) for d in day_span[day_span["min"] > 14.0].index)
    keep_dates = set(day_span[day_span["min"] <= 14.0].index)
    sub = sub[sub["local_date"].isin(keep_dates)].copy()
    sub["station"] = station
    sub["local_date_str"] = sub["local_date"].astype(str)

    meta = {
        "timezone_day_boundary": tz_lst,
        "timezone_intraday_clock": tz_wall,
        "qc_out_of_range_dropped": oor_count,
        "qc_short_step_jump_dropped": jump_count,
        "madishf_candidate_days": int(len(candidate_dates)),
        "excluded_partial_boundary_days": excluded_partial,
        "retained_valid_days": int(len(keep_dates)),
        "date_min": str(min(keep_dates)),
        "date_max": str(max(keep_dates)),
    }
    return sub, meta


def main() -> int:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if contract.get("s_oos_version") != "v2_2000_2018_oof_cv":
        raise RuntimeError(f"Unexpected contract s_oos_version: {contract.get('s_oos_version')}")
    contract_cells = contract["cells"]
    train_arrays = pd.read_parquet(TRAIN_ARRAYS_PATH)
    frozen_eta_df = pd.read_csv(FROZEN_ETA_CSV)

    pre_frames = []
    pre_meta: Dict[str, Any] = {}
    snap_rows: List[Dict[str, Any]] = []
    eta_lst_rows: List[Dict[str, Any]] = []

    for st in STATIONS:
        raw_parts = []
        hashes = {}
        for yr in PRE2019_YEARS:
            p = PROJECT_ROOT / "data" / "raw" / "iem" / st / f"{yr}.parquet"
            hashes[p.name] = sha256_file(p)
            raw_parts.append(pd.read_parquet(p))
        sub_lst, meta = _qc_clean_lst_day_boundary(pd.concat(raw_parts, ignore_index=True), st, PRE2019_YEARS)
        meta["input_hashes"] = hashes
        pre_meta[st] = meta
        pre_frames.append(sub_lst[["station", "valid_utc", "local_date_str", "hour_f", "lst_hour_f", "temp_f", "raw_metar"]])

        s_oos_18 = float(contract_cells[f"{st}_18h"]["s_oos"])
        c_18 = math.sqrt(max(1.0, s_oos_18))
        priors_df = load_station_priors(st, set(sub_lst["local_date"].unique()), train_arrays, c_18)

        ghcn_df = pd.read_parquet(GHCN_DIR / f"{st}.parquet")
        ghcn_df["target_date_d"] = pd.to_datetime(ghcn_df["target_date"]).dt.date
        ghcn_map = dict(zip(ghcn_df["target_date_d"], ghcn_df["tmax_f"].astype(float)))

        for seas in SEASONS:
            spri = priors_df[priors_df["season"] == seas]
            dates = spri.index
            mu0_all = spri["mu_0"].to_numpy(dtype=float)
            s0_all = spri["sigma_0"].to_numpy(dtype=float)
            sobs = sub_lst[sub_lst["local_date"].isin(dates)]
            tfin_all = sobs.groupby("local_date")["temp_f"].max().reindex(dates).to_numpy(dtype=float)
            ghcn_all = np.array([ghcn_map[d] for d in dates], dtype=float)
            s0_sq_mean = float(np.mean(s0_all ** 2))

            raw_rows_wall = []
            raw_rows_pure_lst = []
            slice_data = []
            for h in T_GRID:
                hf = float(h)
                s_h = sobs[sobs["hour_f"] <= hf + 1e-9].sort_values("valid_utc")
                agg = s_h.groupby("local_date").agg(mt=("temp_f", "max"), xt=("temp_f", "last")).reindex(dates)
                mt_arr = agg["mt"].to_numpy(dtype=float)
                xt_arr = agg["xt"].to_numpy(dtype=float)
                ok = ~np.isnan(mt_arr) & ~np.isnan(xt_arr) & ~np.isnan(tfin_all)
                mt_ok, xt_ok, tf_ok, g_ok = mt_arr[ok], xt_arr[ok], tfin_all[ok], ghcn_all[ok]
                mu0_ok, s0_ok, d_ok = mu0_all[ok], s0_all[ok], dates[ok]
                m_int_ok = np.array([float(settle_half_up(float(x))) for x in mt_ok], dtype=float)
                mu_r_ok = rho_weight(hf) * np.maximum(0.0, mu0_ok - m_int_ok)
                rem_pos_ok = np.maximum(0.0, tf_ok - mt_ok)
                eta_raw_mse = float(np.mean((rem_pos_ok - mu_r_ok) ** 2) / s0_sq_mean)
                raw_rows_wall.append((hf, int(ok.sum()), eta_raw_mse))

                # Diagnostic pure-LST clock axis sensitivity
                s_hl = sobs[sobs["lst_hour_f"] <= hf + 1e-9].sort_values("valid_utc")
                mtl = s_hl.groupby("local_date")["temp_f"].max().reindex(dates).to_numpy(dtype=float)
                okl = ~np.isnan(mtl) & ~np.isnan(tfin_all)
                mil = np.array([float(settle_half_up(float(x))) for x in mtl[okl]], dtype=float)
                mrl = rho_weight(hf) * np.maximum(0.0, mu0_all[okl] - mil)
                reml = np.maximum(0.0, tfin_all[okl] - mtl[okl])
                raw_rows_pure_lst.append((hf, int(okl.sum()), float(np.mean((reml - mrl) ** 2) / s0_sq_mean)))

                slice_data.append((hf, d_ok, mt_ok, xt_ok, m_int_ok, tf_ok, g_ok, mu0_ok, s0_ok))

            iso_wall = IsotonicRegression(increasing=False, y_min=0.0, y_max=1.0)
            eta_cal_wall = iso_wall.fit_transform(
                T_GRID,
                [min(1.0, max(0.0, r[2])) for r in raw_rows_wall],
                sample_weight=[r[1] for r in raw_rows_wall],
            )
            iso_pl = IsotonicRegression(increasing=False, y_min=0.0, y_max=1.0)
            eta_cal_pl = iso_pl.fit_transform(
                T_GRID,
                [min(1.0, max(0.0, r[2])) for r in raw_rows_pure_lst],
                sample_weight=[r[1] for r in raw_rows_pure_lst],
            )

            for idx, (hf, d_ok, mt_ok, xt_ok, m_int_ok, tf_ok, g_ok, mu0_ok, s0_ok) in enumerate(slice_data):
                eta_wall_val = float(eta_cal_wall[idx])
                eta_pl_val = float(eta_cal_pl[idx])
                eta_fro_val = float(
                    frozen_eta_df[
                        (frozen_eta_df["station"] == st)
                        & (frozen_eta_df["season"] == seas)
                        & (frozen_eta_df["t_hour"] == hf)
                    ].iloc[0]["eta_calibrated"]
                )
                eta_lst_rows.append(
                    {
                        "station": st,
                        "season": seas,
                        "t_hour": hf,
                        "t_label": format_hour(hf),
                        "n_days": int(len(d_ok)),
                        "eta_lst_daybound_wallclock": round(eta_wall_val, 6),
                        "eta_pure_lst_clock": round(eta_pl_val, 6),
                        "eta_frozen_dst": round(eta_fro_val, 6),
                        "diff_daybound_minus_frozen": round(eta_wall_val - eta_fro_val, 6),
                        "diff_pure_lst_minus_frozen": round(eta_pl_val - eta_fro_val, 6),
                    }
                )

                sr_frozen = np.maximum(s0_ok * math.sqrt(max(eta_fro_val, 0.0)), SIGMA_INST_PHYSICAL_FLOOR)
                rho0 = rho_weight(hf)
                for j in range(len(d_ok)):
                    mt_j = float(mt_ok[j])
                    xt_j = float(xt_ok[j])
                    m_int_j = float(m_int_ok[j])
                    mu0_j = float(mu0_ok[j])
                    tf_j = float(tf_ok[j])
                    g_j = float(g_ok[j])
                    snap_rows.append(
                        {
                            "station": st,
                            "season": seas,
                            "local_date": str(d_ok[j]),
                            "t_hour": hf,
                            "mu_0": mu0_j,
                            "sigma_0": float(s0_ok[j]),
                            "eta": eta_fro_val,
                            "sigma_rem": float(sr_frozen[j]),
                            "mt": mt_j,
                            "xt": xt_j,
                            "m_int": m_int_j,
                            "tfin": tf_j,
                            "ghcn_tmax_f": g_j,
                            "rho": rho0,
                            "heat_term": max(0.0, mu0_j - m_int_j),
                            "cooling_drop": max(0.0, mt_j - xt_j),
                            "y_raw": 1.0 if tf_j <= mt_j + 1e-6 else 0.0,
                            "y_raw_ghcn_settle": 1.0 if settle_half_up(g_j) <= m_int_j else 0.0,
                            "pos_bucket": classify_position_bucket(mt_j - mu0_j),
                        }
                    )

    pd.concat(pre_frames, ignore_index=True).to_parquet(OUT_608_5MIN_LST, index=False)
    pd.DataFrame(snap_rows).to_parquet(OUT_608_SNAP_LST, index=False)

    # 2. 2019 LST rebuild
    y19_frames = []
    y19_meta: Dict[str, Any] = {}
    for st in STATIONS:
        p19 = PROJECT_ROOT / "data" / "raw" / "iem" / st / "2019.parquet"
        sub19, m19 = _qc_clean_lst_day_boundary(pd.read_parquet(p19), st, (2019,))
        m19["input_sha256"] = sha256_file(p19)
        y19_meta[st] = m19
        y19_frames.append(sub19[["station", "valid_utc", "local_date_str", "hour_f", "lst_hour_f", "temp_f", "raw_metar"]])
    pd.concat(y19_frames, ignore_index=True).to_parquet(OUT_2019_5MIN_LST, index=False)

    eta_comp_df = pd.DataFrame(eta_lst_rows)
    eta_comp_df.to_csv(OUT_ETA_LST_CSV, index=False)

    max_abs_daybound = float(eta_comp_df["diff_daybound_minus_frozen"].abs().max())
    mean_abs_daybound = float(eta_comp_df["diff_daybound_minus_frozen"].abs().mean())
    max_abs_purelst = float(eta_comp_df["diff_pure_lst_minus_frozen"].abs().max())
    mean_abs_purelst = float(eta_comp_df["diff_pure_lst_minus_frozen"].abs().mean())

    summary_payload = {
        "schema_version": "p8_lst_corpus_and_eta_sensitivity_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "pre2019_608d_lst_metadata": pre_meta,
        "y2019_lst_metadata": y19_meta,
        "eta_sensitivity_232_rows": {
            "lst_daybound_wallclock_max_abs_diff": round(max_abs_daybound, 6),
            "lst_daybound_wallclock_mean_abs_diff": round(mean_abs_daybound, 6),
            "lst_daybound_material_gt_0p02": bool(max_abs_daybound > 0.02),
            "pure_lst_clock_max_abs_diff_diagnostic": round(max_abs_purelst, 6),
            "pure_lst_clock_mean_abs_diff_diagnostic": round(mean_abs_purelst, 6),
        },
        "outputs": {
            "pre2019_5min_lst": str(OUT_608_5MIN_LST.relative_to(PROJECT_ROOT)),
            "pre2019_snapshots_lst": str(OUT_608_SNAP_LST.relative_to(PROJECT_ROOT)),
            "y2019_5min_lst": str(OUT_2019_5MIN_LST.relative_to(PROJECT_ROOT)),
            "eta_lst_csv": str(OUT_ETA_LST_CSV.relative_to(PROJECT_ROOT)),
        },
    }
    OUT_ETA_LST_JSON.write_text(json.dumps(summary_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== TASK 1: LST DAY-BOUNDARY CORPUS REBUILD & ETA SENSITIVITY ===")
    print("608d retained days:", {k: v["retained_valid_days"] for k, v in pre_meta.items()}, "snapshots:", len(snap_rows))
    print("2019 retained days:", {k: v["retained_valid_days"] for k, v in y19_meta.items()})
    print("eta_s sensitivity:", json.dumps(summary_payload["eta_sensitivity_232_rows"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
