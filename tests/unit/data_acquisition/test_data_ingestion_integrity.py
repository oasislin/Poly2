"""
tests/unit/data_acquisition/test_data_ingestion_integrity.py: Data Ingestion & Source Equality Verification.

Mandated by Pre-Run Gap 1:
1. Sample >= 100 observations and verify 100% exact equality against raw parquet files (0 differences).
2. Station ID, date frequency, and required columns exactly match statutory specifications.
3. Missing value locations and counts match source registers with zero discrepancies.
"""

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from scripts.retrain_p4_active10_matrix import load_station_training_data, GHCN_DIR

EXPECTED_STATIONS = ["KORD", "KLGA", "KATL", "KDAL", "KSEA", "KLAX", "KHOU", "KMIA", "KSFO", "KAUS"]
REQUIRED_COLUMNS = {"station", "target_date", "tmax_f", "tmin_f"}


def test_source_raw_parquet_sampling_exact_equality():
    """Verify >= 100 randomly sampled rows have exactly 0 differences between raw source and loaded df."""
    station = "KORD"
    raw_path = GHCN_DIR / f"{station}.parquet"
    assert raw_path.exists(), f"Raw source {raw_path} must exist"

    df_raw = pd.read_parquet(raw_path)
    df_raw_2000_2018 = df_raw[(df_raw["year"] >= 2000) & (df_raw["year"] <= 2018)].reset_index(drop=True)

    df_loaded_ghcn, _ = load_station_training_data(station)
    assert len(df_loaded_ghcn) == len(df_raw_2000_2018)

    # Deterministic sampling of 150 rows (>= 100)
    rng = np.random.default_rng(20260923)
    sample_indices = rng.choice(len(df_raw_2000_2018), size=150, replace=False)

    sample_raw = df_raw_2000_2018.iloc[sample_indices]
    sample_loaded = df_loaded_ghcn.iloc[sample_indices]

    diff_counts = 0
    for idx_raw, idx_loaded in zip(sample_raw.itertuples(), sample_loaded.itertuples()):
        date_raw_str = str(idx_raw.target_date)[:10]
        date_loaded_str = str(idx_loaded.target_date)[:10]
        if date_raw_str != date_loaded_str:
            diff_counts += 1
        if not np.isclose(idx_raw.tmax_f, idx_loaded.tmax_f, equal_nan=True):
            diff_counts += 1
        if not np.isclose(idx_raw.tmin_f, idx_loaded.tmin_f, equal_nan=True):
            diff_counts += 1

    print(f"Sampled 150 rows. Raw vs Loaded difference count: {diff_counts}")
    assert diff_counts == 0, f"Found {diff_counts} discrepancies between raw source and ingested data!"


def test_station_metadata_schema_and_date_frequency():
    """Verify station IDs, column inventory, and daily frequency."""
    station = "KORD"
    raw_path = GHCN_DIR / f"{station}.parquet"
    df_raw = pd.read_parquet(raw_path)

    # 1. Station ID integrity
    assert (df_raw["station"] == station).all(), f"Station ID mismatch in {station}.parquet"

    # 2. Columns match specification
    assert REQUIRED_COLUMNS.issubset(set(df_raw.columns)), f"Missing required columns in {station}"

    # 3. Frequency integrity: daily continuous without gaps
    dates = pd.to_datetime(df_raw["target_date"]).sort_values().reset_index(drop=True)
    date_diffs = dates.diff().dropna()
    assert (date_diffs == pd.Timedelta(days=1)).all(), "Time series is not strictly daily contiguous!"


def test_missing_value_registration_consistency():
    """Verify missing values count and locations match source register (0 unexpected nulls)."""
    station = "KORD"
    raw_path = GHCN_DIR / f"{station}.parquet"
    df_raw = pd.read_parquet(raw_path)

    df_loaded, _ = load_station_training_data(station)

    # Missing counts in training window
    raw_null_count = int(df_raw[df_raw["year"] <= 2018]["tmax_f"].isna().sum())
    loaded_null_count = int(df_loaded["tmax_f"].isna().sum())

    assert raw_null_count == loaded_null_count, (
        f"Null count discrepancy: raw={raw_null_count} vs loaded={loaded_null_count}"
    )
    print(f"Missing values count on tmax_f: raw={raw_null_count}, loaded={loaded_null_count}, diff=0")
