"""
tests/unit/modeling/test_round3_r6_r7.py: Unit tests for R-6 and R-7 calibrations.
"""

import json
from pathlib import Path
import numpy as np
import pytest
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EVIDENCE_DIR = PROJECT_ROOT / "evidence"


def test_r6_kmia_parameters_file_integrity():
    """Verify R-6 KMIA parameters exist, are finite, and show negative skewness."""
    r6_file = EVIDENCE_DIR / "r6_kmia_parameters.json"
    assert r6_file.exists(), f"{r6_file} must exist"

    with open(r6_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["station"] == "KMIA"
    assert data["sample_count"] == 6940
    # Convective cold bias signature: negative skewness < -0.5
    assert data["raw_residual_moments"]["skewness"] < -0.5

    jsu = data["johnsonsu_parameters"]
    assert jsu["gamma"] > 0.0  # Positive gamma corresponds to negative skewness in scipy parametrization
    assert jsu["delta"] > 0.0
    assert jsu["lambda"] > 0.0
    assert jsu["train_ks_p_value"] >= 0.05


def test_r7_tail_parameters_file_integrity():
    """Verify R-7 EVT tail parameters exist for all 3 stations."""
    r7_file = EVIDENCE_DIR / "r7_tail_parameters.json"
    assert r7_file.exists(), f"{r7_file} must exist"

    with open(r7_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    for st in ["KORD", "KMIA", "KSFO"]:
        assert st in data["stations"]
        p = data["stations"][st]
        assert p["u_left"] < -1.0
        assert p["u_right"] > 1.0
        assert p["gpd_left"]["scale_beta"] > 0.0
        assert p["gpd_right"]["scale_beta"] > 0.0


def test_round3_settlement_gate_closure():
    """Verify Round 3 settlement results meet all statutory gate criteria."""
    csv_file = EVIDENCE_DIR / "round3_recomputed_statistics.csv"
    assert csv_file.exists(), f"{csv_file} must exist"

    import pandas as pd
    df = pd.read_csv(csv_file)
    assert len(df) == 3

    for _, row in df.iterrows():
        st = row["station"]
        # Gate 1: KS test p >= 0.05
        assert row["ks_p_value"] >= 0.05, f"{st} KS p-val {row['ks_p_value']} < 0.05"
        # Gate 2: 7-bin ECE <= 3.0%
        assert row["ece_7bin"] <= 0.030, f"{st} ECE {row['ece_7bin']} > 3%"
        # Variance ratio in [0.85, 1.15]
        assert 0.85 <= row["empirical_s_oos"] <= 1.15, f"{st} s_oos {row['empirical_s_oos']} out of [0.85, 1.15]"
        # Dual-directional 1: PIT mean in [0.46, 0.54]
        assert 0.46 <= row["pit_mean"] <= 0.54, f"{st} PIT mean {row['pit_mean']} out of bounds"
        # Dual-directional 2: 90% coverage in [83%, 95%]
        assert 0.83 <= row["coverage_90"] <= 0.95, f"{st} Coverage {row['coverage_90']} out of bounds"
