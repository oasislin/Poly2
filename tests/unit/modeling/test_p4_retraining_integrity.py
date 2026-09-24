"""
tests/unit/modeling/test_p4_retraining_integrity.py: Integrity Gate Verification for P4 Retrained Models & Evidence.
"""

import json
from pathlib import Path
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EVIDENCE_DIR = PROJECT_ROOT / "evidence"
MODELS_DIR = PROJECT_ROOT / "data" / "models"

STATIONS = [
    "KORD", "KLGA", "KATL", "KDAL", "KSEA",
    "KLAX", "KHOU", "KMIA", "KSFO", "KAUS"
]
SEASONS = ["Winter", "Spring", "Summer", "Autumn"]


def test_p4_manifest_integrity():
    """Verify data/models/manifest.json contains 960 total models, 800 master, 160 auxiliary."""
    manifest_path = MODELS_DIR / "manifest.json"
    assert manifest_path.exists(), f"{manifest_path} must exist"

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["manifest_version"] == "2.1.0"
    assert data["status"] == "PRODUCTION_RETRAINED_V2"
    assert data["total_models"] == 960
    assert data["statutory_trading_nodes_count"] == 800
    assert data["auxiliary_nodes_count"] == 160
    assert len(data["models"]) == 960


def test_p4_distribution_selection_audit_integrity():
    """Verify p4_distribution_selection_audit.csv contains exactly 40 rows (10 stations * 4 seasons)."""
    audit_path = EVIDENCE_DIR / "p4_distribution_selection_audit.csv"
    assert audit_path.exists(), f"{audit_path} must exist"

    df = pd.read_csv(audit_path)
    assert len(df) == 40, f"Expected 40 rows (10 stations * 4 seasons), got {len(df)}"
    assert set(df["station"].unique()) == set(STATIONS)
    assert set(df["season"].unique()) == set(SEASONS)
    required_cols = [
        "station", "season", "n_samples",
        "skewness", "kurtosis_fisher", "jsu_triggered", "evt_triggered",
        "bic_gaussian", "bic_jsu", "bic_evt", "delta_bic_winner",
        "final_selected_family", "fallback_reason"
    ]
    for col in required_cols:
        assert col in df.columns, f"Missing column {col} in distribution selection audit"


def test_p4_variance_factors_integrity():
    """Verify p4_active10_training_variance_factors.json contains 10 stations and 4 seasons."""
    f_path = EVIDENCE_DIR / "p4_active10_training_variance_factors.json"
    assert f_path.exists(), f"{f_path} must exist"

    with open(f_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for st in STATIONS:
        assert st in data, f"Missing station {st} in p4 variance factors"
        st_data = data[st]
        assert st_data["training_years"] == "2000-2018"
        assert "seasonal_c_train" in st_data
        for season in SEASONS:
            assert season in st_data["seasonal_c_train"]
            c_val = st_data["seasonal_c_train"][season]
            assert 0.85 <= c_val <= 1.50


def test_p4_climate_calibration_integrity():
    """Verify p4_active10_climate_calibration.json contains 10 stations and 4 seasons with shapes."""
    f_path = EVIDENCE_DIR / "p4_active10_climate_calibration.json"
    assert f_path.exists(), f"{f_path} must exist"

    with open(f_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for st in STATIONS:
        assert st in data, f"Missing station {st} in p4 climate calibration"
        st_data = data[st]
        assert "seasons" in st_data
        for season in SEASONS:
            assert season in st_data["seasons"]
            s_data = st_data["seasons"][season]
            assert s_data["selected_family"] in ["gaussian", "johnsonsu", "evt_hybrid"]


def test_p4_model_inventory_audit_integrity():
    """Verify model_inventory_audit.csv contains 960 active retrained model entries."""
    f_path = EVIDENCE_DIR / "model_inventory_audit.csv"
    assert f_path.exists(), f"{f_path} must exist"

    df = pd.read_csv(f_path)
    assert len(df) == 960
    assert set(df["status"].unique()).issubset({
        "STATUTORY_TRADING_MASTER",
        "POOLED-FALLBACK",
        "AUXILIARY_POOLED_FALLBACK"
    })
    assert (df["status"] == "STATUTORY_TRADING_MASTER").sum() == 720
    assert (df["status"] == "POOLED-FALLBACK").sum() == 80
    assert (df["status"] == "AUXILIARY_POOLED_FALLBACK").sum() == 160
