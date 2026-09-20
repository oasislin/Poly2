#!/usr/bin/env python3
"""
Unit tests for DatasetPartitioner (Ticket 2.2-03 / Issue #16).

Verifies:
1. round_to_nearest_6h properly rounds continuous lead times.
2. get_season properly maps months (3-5: Spring, 6-8: Summer, 9-11: Autumn, 12-2: Winter).
3. Nominal target time calculation (15:00 LT for Max, 06:00 LT for Min) with station UTC offsets (ZSPD: UTC+8, KDEN: UTC-7).
4. Mapping to the 5 discrete matrix training nodes (Max: 54h, 30h, 6h; Min: 48h, 24h).
5. Dataset partitioning producing exact 40 matrix subsets (2 stations x 4 seasons x 5 nodes).
"""

from datetime import date, datetime, timezone
import numpy as np
import pandas as pd
import pytest

from src.modeling.partitioner import DatasetPartitioner


class TestLeadTimeCalculations:
    """Test rounding and nominal local time lead calculations."""

    @pytest.mark.parametrize("input_hours,expected_bucket", [
        (5.8, 6),
        (6.0, 6),
        (8.9, 6),
        (9.1, 12),
        (29.5, 30),
        (32.9, 30),
        (53.2, 54),
        (47.8, 48),
        (24.1, 24),
    ])
    def test_round_to_nearest_6h(self, input_hours, expected_bucket):
        assert DatasetPartitioner.round_to_nearest_6h(input_hours) == expected_bucket

    def test_nominal_lead_time_zspd(self):
        """ZSPD is UTC+8.
        00Z init today to today 15:00 LT Max:
        Today 15:00 LT = Today 07:00 UTC -> Lead time = 7h -> round_to_nearest_6h = 6h.
        00Z init today to tomorrow 15:00 LT Max:
        Tomorrow 15:00 LT = Tomorrow 07:00 UTC -> Lead time = 31h -> round_to_nearest_6h = 30h.
        00Z init today to day-after-tomorrow 15:00 LT Max:
        Day+2 15:00 LT = Day+2 07:00 UTC -> Lead time = 55h -> round_to_nearest_6h = 54h.
        """
        partitioner = DatasetPartitioner()
        
        # Today max from today 00Z
        lead_today_max = partitioner.compute_nominal_lead_hours(
            station_id="ZSPD",
            target_type="max",
            init_datetime=datetime(2019, 1, 1, 0, 0),
            target_date=date(2019, 1, 1),
        )
        assert np.isclose(lead_today_max, 7.0)
        assert DatasetPartitioner.round_to_nearest_6h(lead_today_max) == 6

        # Tomorrow max from today 00Z
        lead_tomorrow_max = partitioner.compute_nominal_lead_hours(
            station_id="ZSPD",
            target_type="max",
            init_datetime=datetime(2019, 1, 1, 0, 0),
            target_date=date(2019, 1, 2),
        )
        assert np.isclose(lead_tomorrow_max, 31.0)
        assert DatasetPartitioner.round_to_nearest_6h(lead_tomorrow_max) == 30

        # Day+2 max from today 00Z
        lead_day2_max = partitioner.compute_nominal_lead_hours(
            station_id="ZSPD",
            target_type="max",
            init_datetime=datetime(2019, 1, 1, 0, 0),
            target_date=date(2019, 1, 3),
        )
        assert np.isclose(lead_day2_max, 55.0)
        assert DatasetPartitioner.round_to_nearest_6h(lead_day2_max) == 54

    def test_nominal_lead_time_min_temp_zspd(self):
        """ZSPD is UTC+8.
        00Z init today to tomorrow 06:00 LT Min:
        Tomorrow 06:00 LT = Today 22:00 UTC -> Lead time = 22h -> round_to_nearest_6h = 24h.
        00Z init today to day+2 06:00 LT Min:
        Day+2 06:00 LT = Tomorrow 22:00 UTC -> Lead time = 46h -> round_to_nearest_6h = 48h.
        """
        partitioner = DatasetPartitioner()
        lead_min_day1 = partitioner.compute_nominal_lead_hours(
            station_id="ZSPD",
            target_type="min",
            init_datetime=datetime(2019, 1, 1, 0, 0),
            target_date=date(2019, 1, 2),
        )
        assert np.isclose(lead_min_day1, 22.0)
        assert DatasetPartitioner.round_to_nearest_6h(lead_min_day1) == 24

        lead_min_day2 = partitioner.compute_nominal_lead_hours(
            station_id="ZSPD",
            target_type="min",
            init_datetime=datetime(2019, 1, 1, 0, 0),
            target_date=date(2019, 1, 3),
        )
        assert np.isclose(lead_min_day2, 46.0)
        assert DatasetPartitioner.round_to_nearest_6h(lead_min_day2) == 48


class TestSeasonalPartitioning:
    """Test 4-season grouping and slicing."""

    @pytest.mark.parametrize("month,expected_season", [
        (3, "Spring"), (4, "Spring"), (5, "Spring"),
        (6, "Summer"), (7, "Summer"), (8, "Summer"),
        (9, "Autumn"), (10, "Autumn"), (11, "Autumn"),
        (12, "Winter"), (1, "Winter"), (2, "Winter"),
    ])
    def test_get_season_from_month(self, month, expected_season):
        assert DatasetPartitioner.get_season(month) == expected_season
        assert DatasetPartitioner.get_season(date(2019, month, 15)) == expected_season

    def test_split_dataframe_by_season(self):
        dates = pd.date_range("2019-01-01", "2019-12-31", freq="D")
        df = pd.DataFrame({
            "target_date": dates.strftime("%Y-%m-%d"),
            "temp": np.random.normal(20, 5, len(dates)),
        })

        partitioner = DatasetPartitioner()
        seasonal_dfs = partitioner.split_by_season(df, date_col="target_date")

        assert set(seasonal_dfs.keys()) == {"Spring", "Summer", "Autumn", "Winter"}
        assert len(seasonal_dfs["Winter"]) == 31 + 28 + 31  # Jan(31) + Feb(28) + Dec(31) = 90
        assert len(seasonal_dfs["Spring"]) == 31 + 30 + 31  # Mar(31) + Apr(30) + May(31) = 92
        assert len(seasonal_dfs["Summer"]) == 30 + 31 + 31  # Jun(30) + Jul(31) + Aug(31) = 92
        assert len(seasonal_dfs["Autumn"]) == 30 + 31 + 30  # Sep(30) + Oct(31) + Nov(30) = 91
        assert sum(len(v) for v in seasonal_dfs.values()) == 365


class TestMatrixPartitionsGeneration:
    """Test generating the 40 standard training matrix partitions."""

    def test_get_all_matrix_keys(self):
        partitioner = DatasetPartitioner()
        keys = partitioner.get_all_matrix_keys()
        
        # 2 stations * 4 seasons * (3 max nodes + 2 min nodes = 5 nodes) = 40 keys
        assert len(keys) == 40
        
        # Check components
        stations = {k[0] for k in keys}
        seasons = {k[1] for k in keys}
        target_types = {k[2] for k in keys}
        lead_buckets = {k[3] for k in keys}

        assert stations == {"ZSPD", "KDEN"}
        assert seasons == {"Spring", "Summer", "Autumn", "Winter"}
        assert target_types == {"max", "min"}
        assert lead_buckets == {6, 24, 30, 48, 54}


class TestPartitionerPathSecurityAndIsolation:
    """Test blocking of deprecated/polluted legacy paths and Wunderground data."""

    def test_blocks_legacy_v1_suspect_path(self):
        partitioner = DatasetPartitioner()
        with pytest.raises(ValueError, match="strictly blocked"):
            partitioner.validate_safe_dataset_path("data/legacy-v1-suspect/processed/gefs")

    def test_blocks_wunderground_references(self):
        partitioner = DatasetPartitioner()
        with pytest.raises(ValueError, match="strictly blocked"):
            partitioner.validate_safe_dataset_path("data/raw/wunderground/kord")

    def test_allows_calib_dataset_v2(self):
        partitioner = DatasetPartitioner()
        safe_path = partitioner.validate_safe_dataset_path("data/processed/calib-dataset-v2.0")
        assert "calib-dataset-v2.0" in str(safe_path)


class TestPartitionerTimeWallDiscipline:
    """Test strict out-of-sample time-wall boundaries for training and validation."""

    def test_training_time_wall_valid(self):
        partitioner = DatasetPartitioner()
        # Full training period (2000-2018) is valid
        partitioner.validate_time_wall(2000, 2018, split_type="train")
        # Subsets within [2000, 2018] are also valid
        partitioner.validate_time_wall(2010, 2015, split_type="train")

    def test_training_time_wall_rejects_2019_leakage(self):
        partitioner = DatasetPartitioner()
        with pytest.raises(ValueError, match="Training set violates OOS boundary"):
            partitioner.validate_time_wall(2000, 2019, split_type="train")

        with pytest.raises(ValueError, match="Training set violates OOS boundary"):
            partitioner.validate_time_wall(2019, 2019, split_type="train")

    def test_training_time_wall_rejects_pre_2000(self):
        partitioner = DatasetPartitioner()
        with pytest.raises(ValueError, match="cannot be prior to"):
            partitioner.validate_time_wall(1999, 2018, split_type="train")

    def test_validation_time_wall_valid(self):
        partitioner = DatasetPartitioner()
        partitioner.validate_time_wall(2019, 2019, split_type="validation")

    def test_validation_time_wall_rejects_non_2019(self):
        partitioner = DatasetPartitioner()
        with pytest.raises(ValueError, match="Validation set strictly locked"):
            partitioner.validate_time_wall(2018, 2018, split_type="validation")
        with pytest.raises(ValueError, match="Validation set strictly locked"):
            partitioner.validate_time_wall(2020, 2020, split_type="validation")


class TestPartitionerActive10Support:
    """Test timezone resolution and nominal lead time calculation across Active 10 trading stations."""

    @pytest.mark.parametrize("station_id", [
        "KORD", "KLGA", "KATL", "KDAL", "KSEA", "KLAX", "KHOU", "KMIA", "KSFO", "KAUS"
    ])
    def test_active_10_nominal_lead_hours_computable(self, station_id):
        partitioner = DatasetPartitioner()
        lead = partitioner.compute_nominal_lead_hours(
            station_id=station_id,
            target_type="max",
            init_datetime=datetime(2018, 7, 1, 0, 0),
            target_date=date(2018, 7, 2),
        )
        assert 10.0 <= lead <= 50.0
        assert partitioner.round_to_nearest_6h(lead) in [24, 30, 36, 42, 48]

    def test_unknown_or_decommissioned_station_raises(self):
        partitioner = DatasetPartitioner()
        with pytest.raises(ValueError, match="Unknown or non-compliant station_id"):
            partitioner.compute_nominal_lead_hours(
                station_id="KDCA",
                target_type="max",
                init_datetime=datetime(2018, 7, 1, 0, 0),
                target_date=date(2018, 7, 2),
            )

    def test_get_contained_lead_windows_active_10(self):
        partitioner = DatasetPartitioner()
        # For KORD on 2018-07-02 with default previous day 00Z init:
        windows = partitioner.get_contained_lead_windows(
            station_id="KORD",
            target_date=date(2018, 7, 2),
            init_time_utc=datetime(2018, 7, 1, 0, 0, tzinfo=timezone.utc),
        )
        assert len(windows) > 0
        assert all(w % 6 == 0 for w in windows)



class TestPartitionerCalibDatasetV2Alignment:
    """Test loading and aligning features and gefs_factors from calib-dataset-v2.0."""

    def test_load_aligned_dataset_kord_2018(self):
        partitioner = DatasetPartitioner()
        df = partitioner.load_aligned_dataset(
            station="KORD",
            years=[2018],
            target_type="max",
            lead_bucket=30,
        )
        assert not df.empty
        expected_cols = {
            "station",
            "target_date",
            "season",
            "target_type",
            "lead_hours",
            "ensemble_mean",
            "ensemble_variance",
            "observed_temp",
        }
        assert expected_cols.issubset(set(df.columns))
        # No NaNs in critical modeling columns
        assert df["ensemble_mean"].notna().all()
        assert df["ensemble_variance"].notna().all()
        assert df["observed_temp"].notna().all()
        # Physical variance is non-negative
        assert (df["ensemble_variance"] >= 0.0).all()

    def test_load_training_dataset_enforces_time_wall(self):
        partitioner = DatasetPartitioner()
        # Valid training period
        df_train = partitioner.load_training_dataset(
            station="KORD",
            start_year=2018,
            end_year=2018,
            target_type="max",
            lead_bucket=30,
        )
        assert len(df_train) > 0

        # Attempt to leak 2019 into training
        with pytest.raises(ValueError, match="Training set violates OOS boundary"):
            partitioner.load_training_dataset(
                station="KORD",
                start_year=2018,
                end_year=2019,
                target_type="max",
                lead_bucket=30,
            )

    def test_load_validation_dataset_enforces_2019_wall(self):
        partitioner = DatasetPartitioner()
        # Valid 2019
        df_val = partitioner.load_validation_dataset(
            station="KORD",
            target_type="max",
            lead_bucket=30,
        )
        assert len(df_val) > 0
        val_years = pd.to_datetime(df_val["target_date"]).dt.year.unique()
        assert list(val_years) == [2019]

