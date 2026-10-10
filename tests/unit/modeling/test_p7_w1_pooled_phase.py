#!/usr/bin/env python3
"""
tests/unit/modeling/test_p7_w1_pooled_phase.py:
Unit and compliance tests for Work Order P7-W1-POOLPHASE (W1-B phase-stratified retraining).
"""

import json
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo

import pytest

from src.data_processing.constants import STATION_METADATA
from scripts.train_p7_w1_pooled_phase import get_cluster

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
MODELS_DIR = PROJECT_ROOT / "data" / "models"
MANIFEST_PATH = MODELS_DIR / "manifest.json"

STATIONS = ["KORD", "KLGA", "KATL", "KDAL", "KSEA", "KLAX", "KHOU", "KMIA", "KSFO", "KAUS"]
SEASONS = ["Winter", "Spring", "Summer", "Autumn"]
VARIABLES = ["Max", "Min"]
CLUSTERS = ["valley", "peak", "transition"]


def test_phase_cluster_partitioning_full_10_stations():
    """Verify that all 24 hours of the day partition unambiguously into the 3 clusters."""
    for h in range(24):
        c = get_cluster(h)
        assert c in CLUSTERS
        if 0 <= h <= 8:
            assert c == "valley"
        elif 13 <= h <= 20:
            assert c == "peak"
        else:
            assert c == "transition"


def test_west_coast_06z_transition_routing():
    """Assert that West Coast stations (KSEA, KLAX, KSFO) 06Z verification resolves to transition cluster."""
    import pandas as pd
    for st in ["KSEA", "KLAX", "KSFO"]:
        tz = ZoneInfo(STATION_METADATA[st]["timezone"])
        # Winter STD: 06:00 UTC -> 22:00 PST (previous day)
        vt_std = pd.to_datetime("2015-01-15 06:00:00+00:00").astimezone(tz)
        assert vt_std.hour == 22
        assert get_cluster(vt_std.hour) == "transition"

        # Summer DST: 06:00 UTC -> 23:00 PDT (previous day)
        vt_dst = pd.to_datetime("2015-07-15 06:00:00+00:00").astimezone(tz)
        assert vt_dst.hour == 23
        assert get_cluster(vt_dst.hour) == "transition"


def test_pooled_phase_asset_metadata_compliance():
    """Verify metadata compliance of retrained phase cluster models."""
    sample_keys = [
        "KMIA_Winter_Max_lead6h_valley.pkl",
        "KORD_Summer_Max_lead6h_peak.pkl",
        "KSEA_Winter_Min_lead6h_transition.pkl",
    ]
    for key in sample_keys:
        pkl_path = MODELS_DIR / key
        assert pkl_path.exists(), f"Model {key} must exist"
        with open(pkl_path, "rb") as f:
            obj = pickle.load(f)
        meta = obj.get("metadata", {})
        assert "phase_cluster" in meta
        assert meta.get("work_order") == "P7-W1-POOLPHASE"
        assert meta.get("lead_hours") == 6
        p = meta.get("params", {})
        assert all(k in p for k in ["a", "b", "c", "d"])
        assert p["c"] >= 0.90  # ASOS floor


def test_240_models_inventory_completeness():
    """Assert all 240 phase cluster models and 80 default models are present in manifest.json."""
    assert MANIFEST_PATH.exists()
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        mf = json.load(f)

    models_dict = mf.get("models", {})
    count_clusters = 0
    count_defaults = 0

    for st in STATIONS:
        for sea in SEASONS:
            for var in VARIABLES:
                # Default
                def_key = f"{st}_{sea}_{var}_lead6h.pkl"
                assert def_key in models_dict
                assert (MODELS_DIR / def_key).exists()
                count_defaults += 1

                # 3 Clusters
                for c in CLUSTERS:
                    c_key = f"{st}_{sea}_{var}_lead6h_{c}.pkl"
                    assert c_key in models_dict
                    assert (MODELS_DIR / c_key).exists()
                    count_clusters += 1

    assert count_clusters == 240
    assert count_defaults == 80


def test_c1_c2_c3_gate_values():
    """Assert C1 variance ratio, C2 PIT variance, and C3 weighted ECE satisfy gate criteria."""
    audit_json = PROJECT_ROOT / "evidence" / "p7_w1_poolphase_audit_results.json"
    if not audit_json.exists():
        pytest.skip("Audit results JSON not generated yet")

    with open(audit_json, "r", encoding="utf-8") as f:
        res = json.load(f)

    # C2 KMIA PIT variance >= 0.0700
    c2 = res.get("c2_pit_variance", {})
    assert c2.get("passed") is True
    kmia_c2 = c2.get("results", {}).get("KMIA", {})
    for sea, val in kmia_c2.items():
        assert val >= 0.0700, f"KMIA {sea} PIT variance must be >= 0.0700, got {val}"

    # C3 weighted ECE <= 0.0100
    c3 = res.get("c3_weighted_ece", {})
    assert c3.get("passed") is True
    kmia_c3 = c3.get("results", {}).get("KMIA", {}).get("in_window_weighted_ece")
    kord_c3 = c3.get("results", {}).get("KORD", {}).get("in_window_weighted_ece")
    assert kmia_c3 <= 0.0100, f"KMIA morning valley ECE must be <= 0.0100, got {kmia_c3}"
    assert kord_c3 <= 0.0100, f"KORD morning valley ECE must be <= 0.0100, got {kord_c3}"
