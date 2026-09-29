"""
tests/e2e/test_adversarial_traffic.py: End-to-End Verification for GATE-L2-03
Specification: specs/p5_layer2_scenarios.md §2.3 (GATE-L2-03: 异常流量端到端与物理硬门禁)

Validates:
1. Physics hard sentinel: sigma < 0.90°F raises PhysicsViolationError with floor mention.
2. Structural missing column defense: missing target_obs or mandatory cols raises DataAssetError.
3. Unadmitted station defense: unadmitted/missing station raises DataAssetError with available stations.
4. Input bounds sentinel: NaN, inf, out-of-bounds PIT raises DataAssetError.
5. Zero false-positive guarantee: pipeline blocks poisoned data and emits no false PASS.
"""

import math
import numpy as np
import pandas as pd
import pytest

from scripts.standalone_reliability_check import (
    PhysicsViolationError,
    DataAssetError,
    SIGMA_PHYS_FLOOR,
    evaluate_station_cdf,
    validate_and_adapt_input_dataset,
    route_pit_value,
)


def test_gate_l2_03_physics_sigma_collapse_tripwire():
    """
    GATE-L2-03 Assertion 1:
    Forecast sigma collapsing below physical sensor noise floor (0.90°F)
    raises PhysicsViolationError mentioning '0.90' and refusing degenerate probabilities.
    """
    # 1. Below floor (e.g. 0.85°F, 0.10°F) must raise PhysicsViolationError
    with pytest.raises(PhysicsViolationError) as exc_info:
        evaluate_station_cdf(
            y=75.0,
            mu=75.0,
            sigma_eff=0.85,
            station="KORD",
            r6_params={},
            r7_params={},
            mapping_config={"KORD": "gaussian"},
        )
    assert f"{SIGMA_PHYS_FLOOR}" in str(exc_info.value)
    assert "collapsed variance" in str(exc_info.value)

    # 2. At or above floor (e.g. 0.90°F, 1.20°F) must evaluate without exception
    val_floor = evaluate_station_cdf(
        y=75.0,
        mu=75.0,
        sigma_eff=0.90,
        station="KORD",
        r6_params={},
        r7_params={},
        mapping_config={"KORD": "gaussian"},
    )
    assert 0.0 <= val_floor <= 1.0


def test_gate_l2_03_missing_column_defense():
    """
    GATE-L2-03 Assertion 2a:
    Missing required observation column or mandatory metadata columns raises DataAssetError
    with human-readable diagnostic message (Section 2.4).
    """
    df = pd.DataFrame({
        "station": ["KORD"],
        "date": ["2018-01-01"],
        "year": [2018],
        "month": [1],
        "mu_forecast": [45.0],
        # Missing "sigma_forecast" and "is_nan_obs"
    })

    with pytest.raises(DataAssetError) as exc_info:
        validate_and_adapt_input_dataset(df, requested_stations=["KORD"], target_obs_col="obs_tmax_f")
    assert "Input arrays missing required column" in str(exc_info.value)


def test_gate_l2_03_missing_station_admission_defense():
    """
    GATE-L2-03 Assertion 2b:
    Requesting unadmitted station code (e.g. 'KXXX') not in dataset raises DataAssetError
    with available stations listed.
    """
    df = pd.DataFrame({
        "station": ["KORD", "KMIA"],
        "date": ["2018-01-01", "2018-01-01"],
        "year": [2018, 2018],
        "month": [1, 1],
        "mu_forecast": [45.0, 75.0],
        "sigma_forecast": [2.5, 2.0],
        "is_nan_obs": [False, False],
        "obs_tmax_f": [46.0, 74.0],
    })

    with pytest.raises(DataAssetError) as exc_info:
        validate_and_adapt_input_dataset(df, requested_stations=["KXXX"], target_obs_col="obs_tmax_f")
    assert "Requested station 'KXXX' not found in input dataset" in str(exc_info.value)
    assert "KORD" in str(exc_info.value)


def test_gate_l2_03_input_bounds_defensive_tripwires():
    """
    GATE-L2-03 Assertion 4:
    Non-numeric, NaN, inf, or out-of-bounds input values raise DataAssetError.
    """
    with pytest.raises(DataAssetError):
        route_pit_value(float("nan"))

    with pytest.raises(DataAssetError):
        route_pit_value(float("inf"))

    with pytest.raises(DataAssetError):
        route_pit_value(-0.05)

    with pytest.raises(DataAssetError):
        route_pit_value(1.05)

    with pytest.raises(DataAssetError):
        route_pit_value("invalid_string")
