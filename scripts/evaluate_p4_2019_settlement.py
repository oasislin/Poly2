#!/usr/bin/env python3
"""
scripts/evaluate_p4_2019_settlement.py:
P4 Active 10 2019 Out-Of-Sample Settlement & Statutory Gate Verification Pipeline.

Statutory Authorization & Waiver:
- Waiver ID: P4-2019-OOS-SCOPE-WAIVER-001
- Authorized by: Eric Lin (2026-10-20)
- Pre-registration Basis: specs/preregistration-p4-active10-retrain.md + WAIVER-001
- Airgap Authorization Flag: evidence/preregistered_2019_authorization.flag

Execution Architecture & Boundary Separation:
================================================================================
Phase A (Developer Handover):
- Hard filtering implemented and verified: strictly KORD/KMIA * tmax * 12h~72h (11 leads).
- Excludes other 8 stations, all TMin, 6h (diagnostic only), 78h (no production pkl).
- Filter verification mode (`--test-filter`) provides reproducible proof without accessing 2019 data.
- Execution lock prevents premature execution by developer: developer NEVER reads 2019 data.

Phase B (Reviewer Execution):
- Reviewer independently reviews script source, scope filters, and test logs.
- Reviewer executes settlement with:
    python scripts/evaluate_p4_2019_settlement.py --execute-settlement --confirm-waiver P4-2019-OOS-SCOPE-WAIVER-001
- Reviewer independently audits raw metrics against statutory gate thresholds.
================================================================================
"""

import argparse
import json
import logging
import math
from pathlib import Path
import sys
from typing import Any, Callable, Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.metrics.calibration_audit import compute_weighted_ece
from src.utils.airgap import verify_year_whitelist

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("p4_2019_settlement")

EVIDENCE_DIR = PROJECT_ROOT / "evidence"
GEFS_DIR = PROJECT_ROOT / "data" / "processed" / "gefs_factors"
if not GEFS_DIR.exists():
    GEFS_DIR = PROJECT_ROOT / "data" / "processed" / "calib-dataset-v2.0" / "gefs_factors"
GHCN_DIR = PROJECT_ROOT / "data" / "processed" / "truth_ghcn_daily"
MODELS_DIR = PROJECT_ROOT / "data" / "models"
AUDIT_ARRAYS_DIR = PROJECT_ROOT / "data" / "processed" / "audit_arrays"

AUTHORIZATION_FLAG_FILE = EVIDENCE_DIR / "preregistered_2019_authorization.flag"
CLIMATE_CALIB_FILE = EVIDENCE_DIR / "p4_active10_climate_calibration.json"
MANIFEST_FILE = MODELS_DIR / "manifest.json"

OUT_CSV = EVIDENCE_DIR / "p4_2019_settlement_statistics.csv"
OUT_REPORT = EVIDENCE_DIR / "p4_2019_settlement_report.md"
OUT_PARQUET = AUDIT_ARRAYS_DIR / "2019_oos_p4_settlement_arrays.parquet"

# Statutory Scope Lock
ACTIVE_10_STATIONS = (
    "KORD", "KLGA", "KATL", "KDAL", "KSEA", "KLAX", "KHOU", "KMIA", "KSFO", "KAUS",
)
AUTHORIZED_STATIONS = ["KORD", "KMIA"]
AUTHORIZED_VARIABLE = "tmax"
AUTHORIZED_LEADS = [12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72]
SEASONS = ["Winter", "Spring", "Summer", "Autumn"]


def _evt_tail_cdf(z: float, st_params: Dict[str, Any]) -> float:
    """Inline copy of src.modeling.resampling.evaluate_evt_tail_cdf (Scheme B, verbatim)."""
    if math.isinf(z):
        return 1.0 if z > 0 else 0.0
    u_l, u_r = st_params["u_left"], st_params["u_right"]
    xi_l, beta_l = st_params["gpd_left"]["shape_xi"], st_params["gpd_left"]["scale_beta"]
    xi_r, beta_r = st_params["gpd_right"]["shape_xi"], st_params["gpd_right"]["scale_beta"]
    if z < u_l:
        val = 1.0 + xi_l * (u_l - z) / beta_l
        return 0.0 if val <= 0 else float(0.05 * (val ** (-1.0 / xi_l)))
    elif z > u_r:
        val = 1.0 + xi_r * (z - u_r) / beta_r
        return 1.0 if val <= 0 else float(1.0 - 0.05 * (val ** (-1.0 / xi_r)))
    phi_ul = stats.norm.cdf(u_l)
    phi_ur = stats.norm.cdf(u_r)
    denom = max(1e-12, phi_ur - phi_ul)
    core_prob = (stats.norm.cdf(z) - phi_ul) / denom
    return float(0.05 + 0.90 * core_prob)


def get_season(month: int) -> str:
    """Meteorological season mapping strictly aligned with manifest keys."""
    if month in (12, 1, 2):
        return "Winter"
    elif month in (3, 4, 5):
        return "Spring"
    elif month in (6, 7, 8):
        return "Summer"
    return "Autumn"


def filter_candidate_cell(station: str, variable: str, lead_hours: int) -> Tuple[bool, str]:
    """Hard-filtering gate enforcing WAIVER-001 boundary."""
    st_upper = station.upper()
    var_lower = variable.lower()

    if st_upper not in AUTHORIZED_STATIONS:
        return False, f"EXCLUDED_STATION: '{station}' not in authorized list (sealed, pending own 20-fold CV)"
    if var_lower not in ("tmax", "max"):
        return False, f"EXCLUDED_VARIABLE: '{variable}' != 'tmax' (P6-TMIN-CV-LOCK kept locked, not running)"
    if lead_hours == 6:
        return False, "EXCLUDED_LEAD_6H: 6h is PHASE-CLUSTER diagnostic only, not settled (D6-Q4)"
    if lead_hours == 78:
        return False, "EXCLUDED_LEAD_78H: 78h has no production pkl, excluded"
    if lead_hours not in AUTHORIZED_LEADS:
        return False, f"EXCLUDED_LEAD: lead_hours={lead_hours} not in authorized list {AUTHORIZED_LEADS}"
    return True, f"AUTHORIZED: {st_upper}_{lead_hours}h_{var_lower}"


def construct_model_cdf(
    mu: float,
    sigma: float,
    family: str,
    shape_params: Dict[str, Any],
) -> Callable[[float], float]:
    """Construct exact cumulative distribution function matching model family."""
    def cdf_fn(x: float) -> float:
        z = (x - mu) / sigma
        if family == "johnsonsu":
            g = float(shape_params["gamma"])
            d = float(shape_params["delta"])
            xi = float(shape_params["xi"])
            lam = float(shape_params["lambda"])
            zn = g + d * np.arcsinh((z - xi) / lam)
            return float(stats.norm.cdf(zn))
        elif family == "evt_hybrid":
            return float(_evt_tail_cdf(z, shape_params))
        return float(stats.norm.cdf(z))
    return cdf_fn


def compute_model_90_coverage_bounds(
    mu: float,
    sigma: float,
    family: str,
    shape_params: Dict[str, Any],
) -> Tuple[float, float]:
    """Calculate analytical 5% and 95% quantile bounds for non-Gaussian/Gaussian models."""
    z_q05 = -1.6448536269514722
    z_q95 = 1.6448536269514722

    if family == "johnsonsu":
        g = float(shape_params["gamma"])
        d = float(shape_params["delta"])
        xi = float(shape_params["xi"])
        lam = float(shape_params["lambda"])
        z_low = xi + lam * math.sinh((z_q05 - g) / d)
        z_high = xi + lam * math.sinh((z_q95 - g) / d)
    elif family == "evt_hybrid":
        z_low = float(shape_params["u_left"])
        z_high = float(shape_params["u_right"])
    else:
        z_low = z_q05
        z_high = z_q95

    return mu + sigma * z_low, mu + sigma * z_high


def _generate_filter_test_candidates() -> List[Tuple[str, str, int, bool, str]]:
    """Generate structured battery of authorized and unauthorized test cells."""
    candidates = []
    # 22 Authorized cells (2 stations * 11 leads)
    for st in AUTHORIZED_STATIONS:
        for lead in AUTHORIZED_LEADS:
            candidates.append((st, "tmax", lead, True, f"Authorized {st} TMax"))

    # Unauthorized stations (other 8)
    for st in [s for s in ACTIVE_10_STATIONS if s not in AUTHORIZED_STATIONS]:
        candidates.append((st, "tmax", 18, False, f"Unauthorized station {st}"))

    # Unauthorized variable (TMin)
    for st in ["KORD", "KMIA", "KLGA"]:
        candidates.append((st, "tmin", 18, False, f"TMin variable for {st}"))

    # Excluded leads (6h, 78h, 84h)
    for st in AUTHORIZED_STATIONS:
        candidates.append((st, "tmax", 6, False, f"6h diagnostic for {st}"))
        candidates.append((st, "tmax", 78, False, f"78h missing pkl for {st}"))
        candidates.append((st, "tmax", 84, False, f"84h out-of-grid for {st}"))
    return candidates


def run_filter_verification_battery() -> bool:
    """Phase A: Run filter isolation test battery (does NOT touch 2019 data)."""
    candidates = _generate_filter_test_candidates()
    print("=" * 80)
    print("  PHASE A: P4-2019 SETTLEMENT HARD-FILTER VERIFICATION BATTERY")
    print("=" * 80)
    print(f"\nEvaluating {len(candidates)} test cell candidates against hard filter...\n")

    passed = 0
    auth_cnt = 0
    for st, var, lead, expected_auth, desc in candidates:
        is_auth, reason = filter_candidate_cell(st, var, lead)
        test_ok = (is_auth == expected_auth)
        if test_ok:
            passed += 1
        tag = "PASS" if test_ok else "FAIL"
        if is_auth:
            auth_cnt += 1
            print(f"  [{tag}] [AUTHORIZED] cell={st}_{lead}h_{var} ({desc}) -> {reason}")
        else:
            print(f"  [{tag}] [EXCLUDED]   cell={st}_{lead}h_{var} ({desc}) -> {reason}")

    print("\n" + "-" * 80)
    print(f"Summary: Total={len(candidates)}, Authorized={auth_cnt}, Excluded={len(candidates) - auth_cnt}")
    print(f"Filter Battery Assertion: {passed}/{len(candidates)} tests matched isolation policy.")
    print("-" * 80)

    assert auth_cnt == 22, f"Expected 22 authorized cells, got {auth_cnt}"
    assert passed == len(candidates), "Not all filter test assertions passed!"
    print("\n✅ HARD-FILTER VERIFICATION PASSED: All unauthorized cells strictly blocked.")
    print("=" * 80)
    return True


def _load_manifest_and_climate() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Load production model manifest and station climate calibrations."""
    if not MANIFEST_FILE.exists():
        raise FileNotFoundError(f"Manifest file {MANIFEST_FILE} not found")
    if not CLIMATE_CALIB_FILE.exists():
        raise FileNotFoundError(f"Climate calibration file {CLIMATE_CALIB_FILE} not found")
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))["models"]
    climate = json.loads(CLIMATE_CALIB_FILE.read_text(encoding="utf-8"))
    return manifest, climate


def _load_cell_eval_data(station: str, lead_hours: int) -> pd.DataFrame:
    """Load and merge 2019 GHCN truth and GEFS factors for a single cell."""
    ghcn_file = GHCN_DIR / f"{station}.parquet"
    df_ghcn = pd.read_parquet(ghcn_file)
    df_ghcn["target_date"] = pd.to_datetime(df_ghcn["target_date"]).dt.date
    df_ghcn_2019 = df_ghcn[df_ghcn["year"] == 2019][["target_date", "tmax_f", "month"]].dropna().copy()
    df_ghcn_2019["season"] = df_ghcn_2019["month"].apply(get_season)

    gefs_file = GEFS_DIR / station / "2019.parquet"
    df_gefs = pd.read_parquet(gefs_file)
    df_gefs["target_date"] = pd.to_datetime(df_gefs["target_date"]).dt.date
    df_gefs["temp_f"] = (df_gefs["value_K"] - 273.15) * 1.8 + 32.0

    gefs_cell = df_gefs[(df_gefs["variable"] == "tmax") & (df_gefs["lead_hours"] == lead_hours)]
    ens_stats = gefs_cell.groupby("target_date")["temp_f"].agg(
        ens_mean="mean",
        ens_var=lambda x: float(np.var(x, ddof=1)) if len(x) > 1 else 0.0,
    ).reset_index()

    merged = pd.merge(df_ghcn_2019, ens_stats, on="target_date", how="inner")
    return merged.sort_values("target_date").reset_index(drop=True)


def _compute_cell_predictions_and_metrics(
    station: str,
    lead_hours: int,
    merged: pd.DataFrame,
    manifest: Dict[str, Any],
    climate: Dict[str, Any],
    thresholds: Dict[str, Any],
) -> Tuple[Dict[str, Any], pd.DataFrame]:
    """Compute calibrated moments, PIT, statutory 7-bin ECE, and gate results."""
    cell_name = f"{station}_{lead_hours}h_tmax"
    raw_resids = []
    raw_sigmas = []
    c_trains = []
    models_meta_list = []

    for _, row in merged.iterrows():
        season = row["season"]
        model_key = f"{station}_{season}_Max_lead{lead_hours}h.pkl"
        meta = manifest[model_key]
        params = meta["params"]
        a, b, c, d = params["a"], params["b"], params["c"], params["d"]
        mu_raw = a + b * float(row["ens_mean"])
        sig_raw = math.sqrt(c * c + d * d * float(row["ens_var"]))
        raw_resids.append(float(row["tmax_f"]) - mu_raw)
        raw_sigmas.append(sig_raw)
        c_trains.append(float(meta.get("c_train", 1.0)))
        models_meta_list.append((season, meta))

    # Causal 30-day trailing bias
    b30 = pd.Series(raw_resids).shift(1).rolling(30, min_periods=10).mean().fillna(0.0).values
    mu_calib = (merged["ens_mean"].values * [manifest[f"{station}_{s}_Max_lead{lead_hours}h.pkl"]["params"]["b"] for s in merged["season"]]
                + [manifest[f"{station}_{s}_Max_lead{lead_hours}h.pkl"]["params"]["a"] for s in merged["season"]] + b30)
    sig_eff = np.array(raw_sigmas) * np.array(c_trains)

    pit_values, all_7_probs, all_7_hits, cov_90_hits, cov_90_gauss_hits = [], [], [], [], []
    y_obs = merged["tmax_f"].values

    for i in range(len(y_obs)):
        season = merged.at[i, "season"]
        st_season_info = climate[station]["seasons"].get(season, {})
        family = st_season_info.get("selected_family", "gaussian")
        shape_p = st_season_info.get("shape_params", {}) or {}
        cdf_fn = construct_model_cdf(mu_calib[i], sig_eff[i], family, shape_p)

        u_val = float(np.clip(cdf_fn(y_obs[i]), 1e-6, 1.0 - 1e-6))
        pit_values.append(u_val)

        # Statutory 7 discrete brackets around center
        c0 = int(round(mu_calib[i]))
        for k in range(-3, 4):
            bk = c0 + k
            pk = max(0.0, cdf_fn(bk + 0.5) - cdf_fn(bk - 0.5))
            hk = 1.0 if (bk - 0.5 <= y_obs[i] < bk + 0.5) else 0.0
            all_7_probs.append(pk)
            all_7_hits.append(hk)

        # Analytical 90% coverage (primary gate)
        low_q, high_q = compute_model_90_coverage_bounds(mu_calib[i], sig_eff[i], family, shape_p)
        cov_90_hits.append(1.0 if (low_q <= y_obs[i] <= high_q) else 0.0)
        # Gaussian proxy 90% coverage (auxiliary audit disclosure per preregistration §1.2)
        cov_90_gauss_hits.append(1.0 if (mu_calib[i] - 1.64485 * sig_eff[i] <= y_obs[i] <= mu_calib[i] + 1.64485 * sig_eff[i]) else 0.0)

    u_arr = np.array(pit_values)
    res_arr = y_obs - mu_calib

    ks_stat, ks_p_val = stats.kstest(u_arr, "uniform")
    var_resid = float(np.var(res_arr, ddof=1))
    mean_sig_eff_sq = float(np.mean(sig_eff ** 2))
    s_oos = float(var_resid / mean_sig_eff_sq) if mean_sig_eff_sq > 0 else 0.0
    pit_mean = float(np.mean(u_arr))
    cov_90 = float(np.mean(cov_90_hits))
    cov_90_gauss = float(np.mean(cov_90_gauss_hits))
    ece_7bin = compute_weighted_ece(all_7_probs, [int(h) for h in all_7_hits], num_bins=20)

    ks_pass = bool(ks_p_val >= thresholds["ks_p_value_min"])
    ece_pass = bool(ece_7bin <= thresholds["weighted_ece_7bin_max"])
    s_oos_pass = bool(thresholds["variance_ratio_s_oos_bounds"][0] <= s_oos <= thresholds["variance_ratio_s_oos_bounds"][1])
    pit_mean_pass = bool(thresholds["pit_mean_bounds"][0] <= pit_mean <= thresholds["pit_mean_bounds"][1])
    cov_90_pass = bool(thresholds["coverage_90_bounds"][0] <= cov_90 <= thresholds["coverage_90_bounds"][1])

    stat_entry = {
        "station": station,
        "lead_hours": lead_hours,
        "cell": cell_name,
        "n_samples": len(merged),
        "calib_mae": float(np.mean(np.abs(res_arr))),
        "s_oos": s_oos,
        "s_oos_pass": s_oos_pass,
        "ks_stat": float(ks_stat),
        "ks_p_val": float(ks_p_val),
        "ks_pass": ks_pass,
        "ece_7bin": ece_7bin,
        "ece_7bin_pass": ece_pass,
        "pit_mean": pit_mean,
        "pit_mean_pass": pit_mean_pass,
        "coverage_90_exact": cov_90,
        "coverage_90_gaussian_proxy": cov_90_gauss,
        "coverage_90": cov_90,
        "coverage_90_pass": cov_90_pass,
        "all_gates_pass": bool(ks_pass and ece_pass and s_oos_pass and pit_mean_pass and cov_90_pass),
    }

    merged["cell"] = cell_name
    merged["mu_calib"] = mu_calib
    merged["sigma_calib"] = sig_eff
    merged["pit_u"] = pit_values
    return stat_entry, merged


def _export_settlement_artifacts(
    df_stats: pd.DataFrame,
    df_all: pd.DataFrame,
    waiver_id: str,
) -> None:
    """Save statistics CSV, audit Parquet arrays, and Markdown report."""
    df_stats.to_csv(OUT_CSV, index=False)
    df_all.to_parquet(OUT_PARQUET, index=False)
    report_lines = [
        "# P4 Active 10 2019 Out-Of-Sample Settlement Report",
        "",
        f"- **Waiver ID**: {waiver_id}",
        "- **Authorized Scope**: KORD / KMIA * TMax * 12h~72h (11 leads, 22 cells)",
        "- **Execution Date**: 2026-10-20",
        "",
        "## Statutory Gate Results",
        "",
        df_stats.to_markdown(index=False),
        "",
    ]
    OUT_REPORT.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\nArtifacts saved: CSV -> {OUT_CSV}, Parquet -> {OUT_PARQUET}, Report -> {OUT_REPORT}")


def execute_blind_settlement(waiver_id: str) -> None:
    """Phase B: Full Out-Of-Sample Settlement Execution (Reviewer Only)."""
    print("=" * 80)
    print(f"  PHASE B: EXECUTING 2019 OUT-OF-SAMPLE SETTLEMENT ({waiver_id})")
    print("=" * 80)

    if not AUTHORIZATION_FLAG_FILE.exists():
        raise PermissionError(f"Authorization flag not found at {AUTHORIZATION_FLAG_FILE}")

    flag = json.loads(AUTHORIZATION_FLAG_FILE.read_text(encoding="utf-8"))
    assert flag.get("status") == "AUTHORIZED", "Flag status != AUTHORIZED"
    assert flag.get("waiver_id") == waiver_id, f"Flag waiver_id {flag.get('waiver_id')} != {waiver_id}"

    thresholds = flag["frozen_gate_thresholds"]
    verify_year_whitelist(2019, source_description=f"p4_2019_settlement:{waiver_id}")

    manifest, climate = _load_manifest_and_climate()
    stats_list, records_list = [], []

    # Dynamic filter over all active 10 stations and potential leads
    for st in ACTIVE_10_STATIONS:
        for var in ["tmax", "tmin"]:
            for lead in [6, 12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72, 78]:
                is_auth, reason = filter_candidate_cell(st, var, lead)
                if not is_auth:
                    logger.info("[FILTER_EXCLUDED] %s_%dh_%s -> %s", st, lead, var, reason)
                    continue

                print(f"Evaluating authorized cell: {st}_{lead}h_{var}...")
                df_cell = _load_cell_eval_data(st, lead)
                stat_entry, df_annotated = _compute_cell_predictions_and_metrics(
                    st, lead, df_cell, manifest, climate, thresholds
                )
                stats_list.append(stat_entry)
                records_list.append(df_annotated)
                print(f"  -> MAE={stat_entry['calib_mae']:.2f}°F, s_oos={stat_entry['s_oos']:.4f}, "
                      f"KS p={stat_entry['ks_p_val']:.4e}, ECE={stat_entry['ece_7bin']:.2%}")

    df_stats = pd.DataFrame(stats_list)
    df_all = pd.concat(records_list, ignore_index=True)
    _export_settlement_artifacts(df_stats, df_all, waiver_id)
    print("\nPhase B settlement execution completed.")


def main():
    parser = argparse.ArgumentParser(description="P4 2019 Blind Settlement Pipeline")
    parser.add_argument("--test-filter", action="store_true", help="Phase A: Run filter isolation test battery (does NOT touch 2019 data)")
    parser.add_argument("--execute-settlement", action="store_true", help="Phase B: Execute settlement (Reviewer only)")
    parser.add_argument("--confirm-waiver", type=str, default="", help="Phase B: Confirm waiver ID")

    args = parser.parse_args()

    if args.test_filter:
        success = run_filter_verification_battery()
        sys.exit(0 if success else 1)

    if args.execute_settlement:
        if args.confirm_waiver != "P4-2019-OOS-SCOPE-WAIVER-001":
            print("ERROR: Execution requires waiver confirmation: --confirm-waiver P4-2019-OOS-SCOPE-WAIVER-001")
            sys.exit(1)
        execute_blind_settlement(args.confirm_waiver)
        sys.exit(0)

    print("=" * 80)
    print("  [PHASE A SAFETY INTERLOCK] P4 2019 Blind Settlement Script")
    print("=" * 80)
    print("  Developer execution of 2019 blind evaluation is strictly locked.")
    print("  To run Phase A filter verification battery: python scripts/evaluate_p4_2019_settlement.py --test-filter")
    print("  To run Phase B settlement (Reviewer only):  python scripts/evaluate_p4_2019_settlement.py --execute-settlement --confirm-waiver P4-2019-OOS-SCOPE-WAIVER-001")
    print("=" * 80)


if __name__ == "__main__":
    main()
