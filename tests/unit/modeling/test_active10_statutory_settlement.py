"""
tests/unit/modeling/test_active10_statutory_settlement.py: Automated Regression & Gate Verification for Active 10 Stations.
"""

import json
from pathlib import Path
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EVIDENCE_DIR = PROJECT_ROOT / "evidence"
AUDIT_DIR = PROJECT_ROOT / "data" / "processed" / "audit_arrays"

STATIONS = [
    "KORD", "KLGA", "KATL", "KDAL", "KSEA",
    "KLAX", "KHOU", "KMIA", "KSFO", "KAUS"
]


def test_active10_training_variance_factors_integrity():
    """Verify active10_training_variance_factors.json exists and covers all 10 stations."""
    f_path = EVIDENCE_DIR / "active10_training_variance_factors.json"
    assert f_path.exists(), f"{f_path} must exist"

    with open(f_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for st in STATIONS:
        assert st in data, f"Missing station {st} in training variance factors"
        st_data = data[st]
        assert st_data["training_years"] == "2000-2018"
        assert st_data["training_samples"] >= 6900
        assert 1.0 <= st_data["frozen_c_train"] <= 1.25
        assert len(st_data["seasonal_parameters"]) == 4


def test_active10_climate_calibration_integrity():
    """Verify active10_climate_calibration.json exists and contains Johnson SU & EVT parameters."""
    f_path = EVIDENCE_DIR / "active10_climate_calibration.json"
    assert f_path.exists(), f"{f_path} must exist"

    with open(f_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "stations" in data
    for st in STATIONS:
        assert st in data["stations"], f"Missing station {st} in climate calibration"
        p = data["stations"][st]
        assert "johnsonsu_parameters" in p
        assert "evt_tail_parameters" in p
        evt = p["evt_tail_parameters"]
        assert evt["u_left"] < -1.0
        assert evt["u_right"] > 1.0
        assert evt["gpd_left"]["scale_beta"] > 0.0
        assert evt["gpd_right"]["scale_beta"] > 0.0
        assert 1.0 <= evt["kappa_evt"] <= 1.20


def test_active10_2019_oos_parquet_arrays_integrity():
    """Verify 2019 OOS Parquet file contains exactly 3,650 rows (365 days * 10 stations)."""
    p_path = AUDIT_DIR / "2019_oos_active10_arrays.parquet"
    assert p_path.exists(), f"{p_path} must exist"

    df = pd.read_parquet(p_path)
    assert len(df) == 3650, f"Expected 3650 rows, got {len(df)}"
    assert set(df["station"].unique()) == set(STATIONS)

    required_cols = [
        "station", "obs_tmax_f", "mu_forecast", "sigma_effective",
        "pit_value", "is_covered_90", "resid_calibrated"
    ]
    for col in required_cols:
        assert col in df.columns, f"Missing column {col} in parquet arrays"


def test_active10_recomputed_statistics_six_gates():
    """Verify all 10 stations pass the 6 statutory acceptance gates."""
    csv_path = EVIDENCE_DIR / "active10_recomputed_statistics.csv"
    assert csv_path.exists(), f"{csv_path} must exist"

    df = pd.read_csv(csv_path, comment="#")
    assert len(df) == 10

    for _, row in df.iterrows():
        st = row["station"]
        # Gate 1: Randomized PIT K-S test p >= 0.05
        assert row["ks_p_value"] >= 0.05, f"{st} Gate 1 Failed: KS p {row['ks_p_value']} < 0.05"
        # Gate 2: 7-bin weighted ECE <= 3.0%
        assert row["ece_7bin"] <= 0.030, f"{st} Gate 2 Failed: ECE {row['ece_7bin']} > 3.0%"
        # Auxiliary Modal Bracket ECE <= 6.0%
        assert row["ece_center_bin"] <= 0.060, f"{st} Modal Bracket ECE {row['ece_center_bin']} > 6.0%"
        # Gate 3: OOS variance ratio in [0.85, 1.15]
        assert 0.85 <= row["empirical_s_oos"] <= 1.15, f"{st} Gate 3 Failed: s_oos {row['empirical_s_oos']} out of [0.85, 1.15]"
        # Gate 4: PIT Mean in [0.46, 0.54]
        assert 0.46 <= row["pit_mean"] <= 0.54, f"{st} Gate 4 Failed: PIT mean {row['pit_mean']} out of [0.46, 0.54]"
        # Gate 5: 90% Nominal Coverage in [83%, 95%]
        assert 0.83 <= row["coverage_90"] <= 0.95, f"{st} Gate 5 Failed: Coverage {row['coverage_90']} out of [83%, 95%]"
        # Gate 6: All gates pass flag
        assert row["all_gates_pass"] is True or row["all_gates_pass"] == "True"
