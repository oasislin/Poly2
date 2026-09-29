"""
tests/unit/verification/test_p5_unified_spec_requirements.py:
Verification test suite for P5 Unified Remediation Specification
(specs/preregistration-p5-verification-spec.md).

Covers:
1. Input defense adapter & human-readable DataAssetError (Section 2.4).
2. Benjamini-Hochberg (BH) FDR correction & PIT effect size (Section 2.2).
3. Dual-track hybrid binning (decision track merging & benchmark bootstrap CI) (Section 2.1 & 3.3).
4. Refit protocol mirroring & statutory 3-family restriction (Section 3.1).
5. Smoothed 15-day rolling window LOYO climatology (Section 2.3).
"""

import math
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from scripts.standalone_reliability_check import (
    DataAssetError,
    validate_and_adapt_input_dataset,
    apply_benjamini_hochberg_fdr,
    compute_pit_effect_size,
    build_dual_track_reliability_table,
    refit_parameters_on_subset,
    _build_smoothed_loyo_climatology_cache,
    _vectorized_settlement_hit_probability,
    compute_brier_skill_scores,
)


# ==============================================================================
# Gate 2.4: Robust Input Defense & Adapter Tests
# ==============================================================================

def test_validate_and_adapt_raises_on_missing_column():
    df = pd.DataFrame({
        "station": ["KORD"],
        "date": ["2010-01-01"],
        "year": [2010],
        "month": [1],
        "mu_forecast": [30.0],
        "sigma_forecast": [2.5],
        "is_nan_obs": [False],
        "obs_tmax_f": [32.0],
    })
    # Requesting Min when only obs_tmax_f exists must raise human-readable DataAssetError
    with pytest.raises(DataAssetError) as exc_info:
        validate_and_adapt_input_dataset(df, requested_stations=["KORD"], target_obs_col="obs_tmin_f")
    
    msg = str(exc_info.value)
    assert "Input arrays missing required column 'obs_tmin_f'" in msg
    assert "Available columns:" in msg
    assert "obs_tmax_f" in msg


def test_validate_and_adapt_raises_on_missing_station():
    df = pd.DataFrame({
        "station": ["KORD", "KMIA"],
        "date": ["2010-01-01", "2010-01-01"],
        "year": [2010, 2010],
        "month": [1, 1],
        "mu_forecast": [30.0, 75.0],
        "sigma_forecast": [2.5, 2.0],
        "is_nan_obs": [False, False],
        "obs_tmax_f": [32.0, 76.0],
    })
    # Requesting KDEN when only KORD and KMIA exist must raise DataAssetError
    with pytest.raises(DataAssetError) as exc_info:
        validate_and_adapt_input_dataset(df, requested_stations=["KORD", "KDEN"], target_obs_col="obs_tmax_f")
    
    msg = str(exc_info.value)
    assert "Requested station 'KDEN' not found in input dataset" in msg
    assert "Available stations:" in msg
    assert "KMIA" in msg and "KORD" in msg


def test_validate_and_adapt_success():
    df = pd.DataFrame({
        "station": ["KORD", "KMIA", "KSFO"],
        "date": ["2010-01-01", "2010-01-01", "2010-01-01"],
        "year": [2010, 2010, 2010],
        "month": [1, 1, 1],
        "mu_forecast": [30.0, 75.0, 55.0],
        "sigma_forecast": [2.5, 2.0, 3.0],
        "is_nan_obs": [False, False, False],
        "obs_tmax_f": [32.0, 76.0, 57.0],
    })
    adapted = validate_and_adapt_input_dataset(df, requested_stations=["KORD", "KMIA"], target_obs_col="obs_tmax_f")
    assert len(adapted) == 2
    assert set(adapted["station"].unique()) == {"KORD", "KMIA"}


# ==============================================================================
# Gate 2.2: Benjamini-Hochberg (BH) FDR & PIT Effect Size Tests
# ==============================================================================

def test_benjamini_hochberg_fdr_known_cases():
    # Test on known 4-sample p-value series
    raw_p = np.array([0.01, 0.04, 0.03, 0.20])
    q_vals = apply_benjamini_hochberg_fdr(raw_p)

    # Verification:
    # Sorted p: p_(1)=0.01, p_(2)=0.03, p_(3)=0.04, p_(4)=0.20
    # Raw q:
    # k=1: 0.01 * 4 / 1 = 0.04
    # k=2: 0.03 * 4 / 2 = 0.06
    # k=3: 0.04 * 4 / 3 = 0.05333...
    # k=4: 0.20 * 4 / 4 = 0.20
    # Backward cumulative min:
    # q_(4) = 0.20
    # q_(3) = min(0.05333, 0.20) = 0.05333...
    # q_(2) = min(0.06, 0.05333) = 0.05333...
    # q_(1) = min(0.04, 0.05333) = 0.04
    # Realigned to [0.01, 0.04, 0.03, 0.20]:
    # q_vals: [0.04, 0.05333..., 0.05333..., 0.20]
    assert math.isclose(q_vals[0], 0.04, abs_tol=1e-5)
    assert math.isclose(q_vals[1], 4.0 * 0.04 / 3.0, abs_tol=1e-5)
    assert math.isclose(q_vals[2], 4.0 * 0.04 / 3.0, abs_tol=1e-5)
    assert math.isclose(q_vals[3], 0.20, abs_tol=1e-5)


def test_benjamini_hochberg_fdr_monotonicity():
    rng = np.random.default_rng(42)
    p_vals = rng.uniform(0.001, 0.999, size=100)
    q_vals = apply_benjamini_hochberg_fdr(p_vals)

    order = np.argsort(p_vals)
    sorted_q = q_vals[order]
    # Sorted q must be monotonically non-decreasing
    assert np.all(np.diff(sorted_q) >= -1e-9)
    # Must be bounded in [0, 1]
    assert np.all(q_vals >= 0.0)
    assert np.all(q_vals <= 1.0)


def test_pit_effect_size_uniform_vs_biased():
    rng = np.random.default_rng(20260923)
    # 1. Ideal uniform PIT: effect size should be small, no alert
    pit_ideal = rng.uniform(0.0, 1.0, size=2000)
    d_eff_ideal, alert_ideal = compute_pit_effect_size(pit_ideal)
    assert d_eff_ideal < 0.05
    assert alert_ideal is False

    # 2. Heavily skewed/biased PIT: effect size should exceed 0.08 and trigger alert
    pit_biased = np.concatenate([np.full(500, 0.05), np.full(500, 0.95)])
    d_eff_biased, alert_biased = compute_pit_effect_size(pit_biased)
    assert d_eff_biased > 0.08
    assert alert_biased is True


# ==============================================================================
# Gate 2.1 & 3.3: Dual-Track Hybrid Binning Tests
# ==============================================================================

def test_dual_track_merges_small_bins():
    # Create dataset where lower probabilities [0, 0.15) have very few samples (< 30)
    # and upper probabilities have ample samples
    rng = np.random.default_rng(42)
    p_sparse = np.array([0.02, 0.03, 0.07, 0.08, 0.12, 0.14])  # 6 items across 3 initial bins
    h_sparse = np.zeros_like(p_sparse)

    p_dense = rng.uniform(0.20, 0.80, size=500)
    h_dense = (rng.uniform(0.0, 1.0, size=500) < p_dense).astype(float)

    df_exp = pd.DataFrame({
        "p_pred": np.concatenate([p_sparse, p_dense]),
        "hit": np.concatenate([h_sparse, h_dense]),
    })

    res = build_dual_track_reliability_table(df_exp, num_bins=20, min_n_per_bin=30)
    dec_tbl = res["decision_table"]
    bench_tbl = res["benchmark_table"]

    # Decision track: all active strata must satisfy sample_count_n >= 30
    assert (dec_tbl["sample_count_n"] >= 30).all()

    # Benchmark track: maintains fixed 20 equal-width bins
    assert len(bench_tbl) == 20

    # Weighted ECE and 95% bootstrap CI must be valid
    assert res["ece_ci_lower"] <= res["weighted_ece"] + 1e-6
    assert res["weighted_ece"] <= res["ece_ci_upper"] + 1e-6


def test_dual_track_wide_bin_flag():
    # If bins merge and span delta_p > 0.15, must be tagged WIDE-BIN
    df_exp = pd.DataFrame({
        # Only 5 samples in [0, 0.20]
        "p_pred": [0.01, 0.05, 0.10, 0.12, 0.18] + list(np.linspace(0.30, 0.70, 200)),
        "hit": [0, 0, 0, 0, 0] + list((np.linspace(0.30, 0.70, 200) > 0.5).astype(float)),
    })
    res = build_dual_track_reliability_table(df_exp, num_bins=20, min_n_per_bin=30)
    dec_tbl = res["decision_table"]

    wide_bins = dec_tbl[dec_tbl["bin_width"] > 0.15]
    assert not wide_bins.empty
    assert (wide_bins["label"] == "WIDE-BIN").all()


# ==============================================================================
# Gate 3.1: Refit Protocol Mirroring & Statutory 3-Family Restriction
# ==============================================================================

def test_refit_rejects_unauthorized_family():
    df_dummy = pd.DataFrame({
        "station": ["KORD"],
        "date": ["2010-01-01"],
        "year": [2010],
        "is_nan_obs": [False],
        "resid_calibrated": [1.0],
        "sigma_forecast": [2.0],
    })
    # Student-t is strictly prohibited
    with pytest.raises(ValueError) as exc:
        refit_parameters_on_subset(df_dummy, mapping_config={"KORD": "studentt"})
    assert "Invalid distribution family 'studentt'" in str(exc.value)
    assert "Allowed families are strictly: ['gaussian', 'johnsonsu', 'evt']" in str(exc.value)


def test_refit_johnsonsu_multistart():
    rng = np.random.default_rng(42)
    # Generate skewed residual sample
    z = rng.standard_t(df=5, size=200) + 0.5
    df_jsu = pd.DataFrame({
        "station": ["KMIA"] * 200,
        "date": [f"2010-01-{i%28+1:02d}" for i in range(200)],
        "year": [2010] * 200,
        "is_nan_obs": [False] * 200,
        "resid_calibrated": z * 2.0,
        "sigma_forecast": [2.0] * 200,
    })
    r6, _ = refit_parameters_on_subset(df_jsu, mapping_config={"KMIA": "johnsonsu"})
    params = r6["johnsonsu_parameters"]
    assert "gamma" in params and "delta" in params and "xi" in params and "lambda" in params
    assert params["delta"] > 0
    assert params["lambda"] > 0


def test_refit_evt_tail_structure():
    rng = np.random.default_rng(42)
    z = rng.standard_t(df=3, size=300)  # Heavy tailed
    df_evt = pd.DataFrame({
        "station": ["KSFO"] * 300,
        "date": [f"2010-01-{i%28+1:02d}" for i in range(300)],
        "year": [2010] * 300,
        "is_nan_obs": [False] * 300,
        "resid_calibrated": z * 2.5,
        "sigma_forecast": [2.5] * 300,
    })
    _, r7 = refit_parameters_on_subset(df_evt, mapping_config={"KSFO": "evt"})
    evt_params = r7["stations"]["KSFO"]
    assert "u_left" in evt_params and "u_right" in evt_params
    assert "gpd_left" in evt_params and "gpd_right" in evt_params
    assert evt_params["u_left"] < evt_params["u_right"]
    assert evt_params["gpd_left"]["scale_beta"] > 0
    assert evt_params["gpd_right"]["scale_beta"] > 0


# ==============================================================================
# Gate 2.3: Smoothed 15-Day Rolling LOYO Climatology Tests
# ==============================================================================

def test_smoothed_loyo_climatology_excludes_target_year():
    # Construct 3 years of daily observations for KORD
    rows = []
    for yr in [2001, 2002, 2003]:
        dates = pd.date_range(f"{yr}-01-01", periods=365, freq="D")
        for d_idx, dt in enumerate(dates):
            d = d_idx + 1
            # Target day 180: yr 2001 has 80°F, yr 2002 has 85°F, yr 2003 has 120°F (extreme outlier)
            temp = 120.0 if yr == 2003 and d == 180 else 80.0 + (yr - 2001)
            rows.append({
                "station": "KORD",
                "year": yr,
                "month": dt.month,
                "date": dt.strftime("%Y-%m-%d"),
                "obs_tmax_f": temp,
                "is_nan_obs": False,
            })
    df_raw = pd.DataFrame(rows)
    cache = _build_smoothed_loyo_climatology_cache(df_raw, target_obs_col="obs_tmax_f")

    # Evaluating year 2003 on day 180: must NOT contain the 120.0 outlier from 2003!
    pool_2003 = cache.get(("KORD", 180, 2003))
    assert pool_2003 is not None and len(pool_2003) > 0
    assert not np.any(pool_2003 >= 115.0)

    # Evaluating year 2001 on day 180: must contain the 120.0 from 2003!
    pool_2001 = cache.get(("KORD", 180, 2001))
    assert pool_2001 is not None and len(pool_2001) > 0
    assert np.any(pool_2001 >= 115.0)


def test_smoothed_loyo_climatology_circular_continuity():
    # Day 1 window includes days 359 to 8 (wrapping around 365)
    rows = []
    for yr in [2001, 2002]:
        # Day 365 (Dec 31)
        rows.append({"station": "KMIA", "year": yr, "month": 12, "date": f"{yr}-12-31", "obs_tmax_f": 70.0, "is_nan_obs": False})
        # Day 1 (Jan 1)
        rows.append({"station": "KMIA", "year": yr, "month": 1, "date": f"{yr}-01-01", "obs_tmax_f": 72.0, "is_nan_obs": False})
    df_raw = pd.DataFrame(rows)
    cache = _build_smoothed_loyo_climatology_cache(df_raw, target_obs_col="obs_tmax_f")

    # Pool for day 1 in 2001 should include day 365 from 2002 (70.0) and day 1 from 2002 (72.0)
    pool_d1 = cache.get(("KMIA", 1, 2001))
    assert pool_d1 is not None and len(pool_d1) > 0
    assert 70.0 in pool_d1
    assert 72.0 in pool_d1


# ==============================================================================
# Spec Revision #4 Annex B: 0.35 Semantics Unification Tests
# ==============================================================================

def test_035_scalar_routing_success():
    """Annex B1: Single scalar PIT = 0.35 routes legally into bin 8 ([0.35, 0.40))."""
    from scripts.standalone_reliability_check import route_pit_value, pit_to_bin
    assert pit_to_bin(0.35) == 8
    assert route_pit_value(0.35) == 8
    assert route_pit_value("0.35") == 8


def test_stream_level_degeneracy_detection():
    """Annex B2: Stream-level zero variance (all identical values) triggers DataAssetError."""
    from scripts.standalone_reliability_check import (
        check_stream_degeneracy,
        route_stream,
        analyze_pit_stream,
        DataAssetError,
    )
    # 1. Normal varied stream should pass
    varied = [0.1, 0.2, 0.35, 0.4, 0.8]
    check_stream_degeneracy(varied)

    # 2. Identical stream (0.35 x 1000) must trigger DataAssetError
    with pytest.raises(DataAssetError) as exc_info:
        check_stream_degeneracy([0.35] * 1000)
    assert "degenerate: zero variance" in str(exc_info.value)

    # 3. Any other identical constant stream (e.g. 0.70 x 50) must also trigger
    with pytest.raises(DataAssetError) as exc_info2:
        check_stream_degeneracy([0.70] * 50)
    assert "degenerate: zero variance" in str(exc_info2.value)

    # 4. Stream analysis entry point on fixture stream_identical.csv must trigger
    fix_dir = Path("tests/fixtures/p5_selfcheck")
    identical_csv = fix_dir / "stream_identical.csv"
    with pytest.raises(DataAssetError):
        analyze_pit_stream(str(identical_csv))

    with pytest.raises(DataAssetError):
        route_stream(str(identical_csv), check_degeneracy=True)

    # 5. Non-degenerate stream_uniform.csv must pass stream analysis
    uniform_csv = fix_dir / "stream_uniform.csv"
    res = analyze_pit_stream(str(uniform_csv))
    assert res["row_count"] == 1000


