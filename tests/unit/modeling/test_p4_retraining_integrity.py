"""
tests/unit/modeling/test_p4_retraining_integrity.py: Comprehensive 7-Gate Verification for P4 Retrained Models & Evidence.
"""

import json
import math
from pathlib import Path
import pickle
import numpy as np
import pandas as pd
import pytest

from scripts.retrain_p4_active10_matrix import (
    fit_emos_cell,
    extract_cell_dataset,
    load_station_training_data,
    MODELS_DIR,
    EVIDENCE_DIR,
    STATIONS,
    SEASONS,
    SIGMA_INST_PHYSICAL_FLOOR,
)

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

    assert data["manifest_version"] == "2.2.0"
    assert data["status"] == "PRODUCTION_RETRAINED_V2"
    assert data["fitting_protocol"] == "STATUTORY_5_GUESS_MULTI_START"
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
        c_train_vals.append(info["c_train"])
        emos_c_vals.append(info["params"]["c"])

        pkl_path = MODELS_DIR / rel_path
        assert pkl_path.exists(), f"Model pkl missing: {pkl_path}"
        with open(pkl_path, "rb") as f:
            obj = pickle.load(f)
        meta = obj["metadata"]
        interpolated_flags.append(meta.get("is_interpolated", False))
        assert meta["params"]["c"] >= SIGMA_INST_PHYSICAL_FLOOR, f"EMOS c floor violation: {rel_path}"
        assert meta["c_train"] >= SIGMA_INST_PHYSICAL_FLOOR, f"c_train floor violation: {rel_path}"

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

    assert (df_inv["status"] == "STATUTORY_TRADING_MASTER").sum() == 720
    assert (df_inv["status"] == "POOLED-FALLBACK").sum() == 80
    assert (df_inv["status"] == "AUXILIARY_POOLED_FALLBACK").sum() == 160


def test_p4_distribution_selection_competition_audit():
    """断言 4: 分布竞争留痕审计完备性与 KMIA 100% JSU 录取断言 (40 站×季单元)."""
    audit_path = EVIDENCE_DIR / "p4_distribution_selection_audit.csv"
    assert audit_path.exists(), f"{audit_path} must exist"

    df = pd.read_csv(audit_path)
    assert len(df) == 40, f"Expected 40 rows (10 stations * 4 seasons), got {len(df)}"
    assert set(df["station"].unique()) == set(STATIONS)
    assert set(df["season"].unique()) == set(SEASONS)

    # Verify KMIA decision in all 4 seasons: JSU won BIC competition
    kmia_rows = df[df["station"] == "KMIA"]
    assert len(kmia_rows) == 4
    for _, row in kmia_rows.iterrows():
        assert row["jsu_triggered"] is True or row["jsu_triggered"] == "True"
        assert row["final_selected_family"] == "johnsonsu", f"KMIA must select johnsonsu, got {row['final_selected_family']}"

    # Verify family distribution counts
    family_counts = df["final_selected_family"].value_counts().to_dict()
    assert family_counts["johnsonsu"] == 23
    assert family_counts["gaussian"] == 13
    assert family_counts["evt_hybrid"] == 4


def test_p4_anchor_three_stations_mean_layer_invariance():
    """断言 5: 锚点三站 (KORD, KMIA, KSFO) 18h TMAX 均值层历史复现与对账断言."""
    r3_stats_path = EVIDENCE_DIR / "round3_recomputed_statistics.csv"
    assert r3_stats_path.exists()
    df_r3 = pd.read_csv(r3_stats_path)

    for st, anchors in ROUND3_ANCHORS.items():
        st_row = df_r3[df_r3["station"] == st].iloc[0]
        assert abs(st_row["mae"] - anchors["mae"]) == 0.0, f"{st} MAE drifted from Round 3 anchor!"
        assert abs(st_row["implied_sigma_star"] - anchors["sigma_star"]) == 0.0, f"{st} sigma* drifted!"


def test_p4_no_optimizer_boundary_stall():
    """断言 6: 优化器边界死锁全网格哨兵 (零触碰 1.35 截断上限，零趴死 0.90 底座)."""
    manifest_path = MODELS_DIR / "manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        mf = json.load(f)

    c_trains = [m["c_train"] for m in mf["models"].values()]
    emos_c_vals = [m["params"]["c"] for m in mf["models"].values()]

    # 1. Assert all 960 cells are strictly below 1.35 (distance > 0.01)
    boundary_touches = sum(c >= 1.34 for c in c_trains)
    assert boundary_touches == 0, f"Found {boundary_touches} models stalled at 1.35 ceiling!"

    # 2. Assert all 960 cells have EMOS c strictly above 0.90 (distance > 0.05)
    floor_stalls = sum(c <= 0.95 for c in emos_c_vals)
    assert floor_stalls == 0, f"Found {floor_stalls} models stalled at 0.90 floor!"
    assert min(emos_c_vals) >= 1.20, f"Global min EMOS c {min(emos_c_vals)} is unexpectedly low"


def test_p4_multistart_determinism():
    """断言 7: 法定 5 初猜多起点协议机器可验证确定性复现断言 (随机抽样 5 格逐位一致)."""
    manifest_path = MODELS_DIR / "manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        mf = json.load(f)

    # Deterministically sample 5 disparate cells across matrix
    sample_keys = list(mf["models"].keys())[::200][:5]

    for k in sample_keys:
        info = mf["models"][k]
        st = info["station"]
        season = info["season"]
        var = "Max" if info["variable"] == "max" else "Min"
        lead = info["lead_hours"]

        df_ghcn, df_gefs = load_station_training_data(st)
        cell_df = extract_cell_dataset(df_ghcn, df_gefs, season, var, lead)
        adj_lead = lead + 6 if lead + 6 <= 72 else lead - 6
        adj_df = extract_cell_dataset(df_ghcn, df_gefs, season, var, adj_lead)

        params, _, _ = fit_emos_cell(cell_df, adjacent_df=adj_df)
        saved_p = info["params"]

        diff_a = abs(params[0] - saved_p["a"])
        diff_b = abs(params[1] - saved_p["b"])
        diff_c = abs(params[2] - saved_p["c"])
        diff_d = abs(params[3] - saved_p["d"])

        assert max(diff_a, diff_b, diff_c, diff_d) < 1e-9, (
            f"Multi-start determinism failed on {k}: diffs=({diff_a:.2e}, {diff_b:.2e}, {diff_c:.2e}, {diff_d:.2e})"
        )


def test_p4_evt_cdf_analytical_boundary_and_weights():
    """
    Gate 8: EVT CDF Path Weights & Analytical Integral Verification.
    Validates that:
    1. All calibrated EVT units adhere to physical bounds: u_l < u_r, beta > 0.
    2. Limits at infinity satisfy F(-inf) = 0.0 and F(+inf) = 1.0.
    3. Boundary values at u_l^- and u_r^+ evaluate exactly to 0.05 and 0.95 (0.05 tail mass).
    4. Analytical PPF inversion on tail quantile grids matches F(z) to within 1e-7.
    5. Tail regions exhibit strict monotonic non-decreasing behavior.
    """
    from scripts.standalone_reliability_check import _evaluate_evt_tail_cdf

    calib_path = EVIDENCE_DIR / "p4_active10_climate_calibration.json"
    with open(calib_path) as f:
        calib = json.load(f)

    evt_found = 0
    for st, data in calib.items():
        if not isinstance(data, dict) or "seasons" not in data:
            continue
        for season, sdata in data["seasons"].items():
            if sdata["selected_family"] == "evt_hybrid":
                evt_found += 1
                p = sdata["shape_params"]
                ul, ur = p["u_left"], p["u_right"]
                xil, betal = p["gpd_left"]["shape_xi"], p["gpd_left"]["scale_beta"]
                xir, betar = p["gpd_right"]["shape_xi"], p["gpd_right"]["scale_beta"]

                # 1. Physical parameter checks
                assert ul < ur, f"{st} {season}: u_left {ul} >= u_right {ur}"
                assert betal > 0.0, f"{st} {season}: beta_left {betal} <= 0"
                assert betar > 0.0, f"{st} {season}: beta_right {betar} <= 0"

                # 2. Exact limits at infinity
                assert _evaluate_evt_tail_cdf(float("-inf"), p) == 0.0
                assert _evaluate_evt_tail_cdf(float("inf"), p) == 1.0
                assert _evaluate_evt_tail_cdf(-10000.0, p) == 0.0
                assert abs(_evaluate_evt_tail_cdf(10000.0, p) - 1.0) < 1e-12

                # 3. Boundary values with 0.05 tail weight
                f_ul = _evaluate_evt_tail_cdf(ul - 1e-9, p)
                f_ur = _evaluate_evt_tail_cdf(ur + 1e-9, p)
                assert abs(f_ul - 0.05) < 1e-6, f"{st} {season}: f(ul^-)={f_ul} != 0.05"
                assert abs(f_ur - 0.95) < 1e-6, f"{st} {season}: f(ur^+)={f_ur} != 0.95"

                # 4. Analytical PPF inversion on tail quantile grid
                for p_target in [0.0001, 0.001, 0.01, 0.025, 0.049]:
                    val = (p_target / 0.05) ** (-xil)
                    z_p = ul - (betal / xil) * (val - 1.0)
                    f_eval = _evaluate_evt_tail_cdf(z_p, p)
                    assert abs(f_eval - p_target) < 1e-7, (
                        f"{st} {season}: Left tail target {p_target} evaluated to {f_eval}"
                    )

                for p_target in [0.951, 0.975, 0.99, 0.999, 0.9999]:
                    val = ((1.0 - p_target) / 0.05) ** (-xir)
                    z_p = ur + (betar / xir) * (val - 1.0)
                    f_eval = _evaluate_evt_tail_cdf(z_p, p)
                    assert abs(f_eval - p_target) < 1e-7, (
                        f"{st} {season}: Right tail target {p_target} evaluated to {f_eval}"
                    )

                # 5. Strict tail monotonicity
                z_left = np.linspace(-15.0, ul - 1e-5, 100)
                f_left = [_evaluate_evt_tail_cdf(z, p) for z in z_left]
                assert all(f_left[i] <= f_left[i + 1] + 1e-12 for i in range(len(f_left) - 1))

                z_right = np.linspace(ur + 1e-5, 15.0, 100)
                f_right = [_evaluate_evt_tail_cdf(z, p) for z in z_right]
                assert all(f_right[i] <= f_right[i + 1] + 1e-12 for i in range(len(f_right) - 1))

    assert evt_found == 4, f"Expected 4 EVT units, found {evt_found}"

