"""
tests/unit/modeling/test_p4_retraining_integrity.py: Comprehensive Integrity Gate Verification for P4 Retrained Models & Evidence.
"""

import json
from pathlib import Path
import pickle
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

# Round 3 Historical Baseline Anchors (18h TMAX OOS)
ROUND3_ANCHORS = {
    "KORD": {"mae": 2.5935041424958394, "sigma_star": 3.250475406976349},
    "KMIA": {"mae": 1.3617658451188503, "sigma_star": 1.7067203854008448},
    "KSFO": {"mae": 3.21664235132114, "sigma_star": 4.031463333598556},
}


def test_p4_universe_960_node_completeness():
    """断言 1: 960 格计数完备性断言 (800 法定交易主节点 + 160 补全辅助节点)."""
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

    # Categorization count check
    statuses = [m["status"] for m in data["models"].values()]
    assert statuses.count("STATUTORY_TRADING_MASTER") == 720
    assert statuses.count("POOLED-FALLBACK") == 80
    assert statuses.count("AUXILIARY_POOLED_FALLBACK") == 160


def test_p4_per_cell_physical_floors_and_no_interpolation():
    """断言 2: 逐格 c_train >= 0.90, 逐格 EMOS c >= 0.90 与逐格 is_interpolated = False 断言."""
    manifest_path = MODELS_DIR / "manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    c_train_vals = []
    emos_c_vals = []
    interpolated_flags = []

    for rel_path, info in data["models"].items():
        # Check manifest fields
        c_train_vals.append(info["c_train"])
        emos_c_vals.append(info["params"]["c"])

        # Check pkl metadata directly
        pkl_path = MODELS_DIR / rel_path
        assert pkl_path.exists(), f"Model pkl missing: {pkl_path}"
        with open(pkl_path, "rb") as f:
            obj = pickle.load(f)
        meta = obj["metadata"]
        interpolated_flags.append(meta.get("is_interpolated", False))
        assert meta["params"]["c"] >= 0.90, f"EMOS c floor violation: {rel_path}"
        assert meta["c_train"] >= 0.90, f"c_train floor violation: {rel_path}"

    # Minimum checks across entire 960-model matrix
    min_c_train = min(c_train_vals)
    min_emos_c = min(emos_c_vals)
    assert min_c_train >= 0.90, f"Global min c_train {min_c_train} < 0.90"
    assert min_emos_c >= 0.90, f"Global min EMOS c {min_emos_c} < 0.90"
    assert not any(interpolated_flags), "Found interpolated model in 960 matrix!"


def test_p4_pooled_fallback_and_inventory_consistency():
    """断言 3: POOLED-FALLBACK 标注与模型普查清册 100% 一致性断言."""
    manifest_path = MODELS_DIR / "manifest.json"
    inv_path = EVIDENCE_DIR / "model_inventory_audit.csv"

    with open(manifest_path, "r", encoding="utf-8") as f:
        mf = json.load(f)
    df_inv = pd.read_csv(inv_path)

    assert len(df_inv) == 960, f"Inventory must have 960 rows, got {len(df_inv)}"
    inv_map = {row["model_filename"].replace("data/models/", ""): row["status"] for _, row in df_inv.iterrows()}

    for rel_path, info in mf["models"].items():
        assert rel_path in inv_map, f"Model {rel_path} not found in inventory audit"
        assert info["status"] == inv_map[rel_path], f"Status mismatch for {rel_path}: {info['status']} vs {inv_map[rel_path]}"

    # Verify counts in inventory audit
    assert (df_inv["status"] == "STATUTORY_TRADING_MASTER").sum() == 720
    assert (df_inv["status"] == "POOLED-FALLBACK").sum() == 80
    assert (df_inv["status"] == "AUXILIARY_POOLED_FALLBACK").sum() == 160


def test_p4_distribution_selection_competition_audit():
    """断言 4: 分布竞争留痕审计完备性与 KMIA/KORD 竞争决议断言 (40 站×季单元)."""
    audit_path = EVIDENCE_DIR / "p4_distribution_selection_audit.csv"
    assert audit_path.exists(), f"{audit_path} must exist"

    df = pd.read_csv(audit_path)
    assert len(df) == 40, f"Expected 40 rows (10 stations * 4 seasons), got {len(df)}"
    assert set(df["station"].unique()) == set(STATIONS)
    assert set(df["season"].unique()) == set(SEASONS)

    # Verify KMIA decision in all 4 seasons
    kmia_rows = df[df["station"] == "KMIA"]
    assert len(kmia_rows) == 4
    for _, row in kmia_rows.iterrows():
        assert row["jsu_triggered"] is True or row["jsu_triggered"] == "True"
        assert row["evt_triggered"] is True or row["evt_triggered"] == "True"
        assert row["final_selected_family"] == "evt_hybrid"

    # Verify family distribution counts
    family_counts = df["final_selected_family"].value_counts().to_dict()
    assert family_counts["evt_hybrid"] == 28
    assert family_counts["gaussian"] == 7
    assert family_counts["johnsonsu"] == 5


def test_p4_anchor_three_stations_mean_layer_invariance():
    """断言 5: 锚点三站 (KORD, KMIA, KSFO) 18h TMAX 均值层历史复现与对账断言."""
    # Check that historical Round 3 anchors are preserved in evidence
    r3_stats_path = EVIDENCE_DIR / "round3_recomputed_statistics.csv"
    assert r3_stats_path.exists()
    df_r3 = pd.read_csv(r3_stats_path)

    for st, anchors in ROUND3_ANCHORS.items():
        st_row = df_r3[df_r3["station"] == st].iloc[0]
        # Bitwise identical match to historical MAE & sigma*
        assert abs(st_row["mae"] - anchors["mae"]) == 0.0, f"{st} MAE drifted from Round 3 anchor!"
        assert abs(st_row["implied_sigma_star"] - anchors["sigma_star"]) == 0.0, f"{st} sigma* drifted!"
