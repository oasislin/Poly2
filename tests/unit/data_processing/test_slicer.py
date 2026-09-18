#!/usr/bin/env python3
"""
Unit and Contract Tests for Feature Slicer (Phase 1.5 Task 06).

Verifies:
1. DST 23h/25h adaptive calendar day slicing (Spring forward & Fall back).
2. resolve_day_of_year 2020 leap year calendar axis alignment.
3. ADR-0009 D3 dual-track separation (all_reports vs hourly_only & speci divergence).
4. Exclusion of explicit SPECI reports from nominal hourly window.
5. Data tiering tags: era1 / stress-test-only vs era2 / training-ready.
6. Active 11 station universe guard.
7. Station-specific nominal hourly window adaptation (KSFO :56, KBKF :58).
8. Divergence check boundary null-safety.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import pytest

from src.data_processing.slicer import (
    DEFAULT_HOURLY_WINDOW,
    ERA2_START_YEAR,
    STATION_HOURLY_WINDOWS,
    USAGE_STRESS_TEST_ONLY,
    USAGE_TRAINING_READY,
    VINTAGE_ERA1,
    VINTAGE_ERA2,
    DailyFeatureRecord,
    ObservationSlicer,
    celsius_to_fahrenheit,
    check_speci_divergence,
    fahrenheit_to_celsius,
    validate_active_station,
)
from src.modeling.climate_floor import resolve_day_of_year


class TestFeatureSlicerCore:
    """Unit test suite for ObservationSlicer functionality."""

    def test_station_universe_guard(self):
        """Active 11 station universe must be enforced, invalid/retired stations rejected."""
        assert validate_active_station("KORD") == "KORD"
        assert validate_active_station("kbkf ") == "KBKF"

        with pytest.raises(ValueError, match="not in active 11 stations"):
            validate_active_station("KDCA")

        with pytest.raises(ValueError, match="not in active 11 stations"):
            validate_active_station("ZSPD")

        with pytest.raises(ValueError, match="not in active 11 stations"):
            validate_active_station("KDEN")

    def test_doy_mapping_guard(self):
        """Verify resolve_day_of_year maps common year Mar 1 to 61 and leap year Feb 29 to 60."""
        # Common year (2021): Feb 28 is 59, Mar 1 is 61 (skipping 60)
        assert resolve_day_of_year("2021-02-28") == 59
        assert resolve_day_of_year("2021-03-01") == 61

        # Leap year (2020): Feb 28 is 59, Feb 29 is 60, Mar 1 is 61
        assert resolve_day_of_year("2020-02-28") == 59
        assert resolve_day_of_year("2020-02-29") == 60
        assert resolve_day_of_year("2020-03-01") == 61

        # End of year: Dec 31 is always 366
        assert resolve_day_of_year("2021-12-31") == 366
        assert resolve_day_of_year("2020-12-31") == 366

    def test_dst_spring_forward_23h(self):
        """Spring forward transition day (2024-03-10 in Chicago) has exactly 23 local hours."""
        tz = ZoneInfo("America/Chicago")
        ts_utc = pd.date_range("2024-03-10 00:00", "2024-03-11 12:00", freq="1h", tz="UTC")
        df_obs = pd.DataFrame({
            "valid_utc": ts_utc,
            "temp_c": [10.0 + (i % 5) for i in range(len(ts_utc))],
        })

        slicer = ObservationSlicer()
        res = slicer.slice_dataframe(df_obs, station="KORD", target_year=2024)

        row_mar10 = res[res["local_date"] == "2024-03-10"].iloc[0]
        assert row_mar10["total_obs_count"] == 23
        assert row_mar10["day_of_year"] == resolve_day_of_year("2024-03-10")

    def test_dst_fall_back_25h(self):
        """Fall back transition day (2024-11-03 in Chicago) has exactly 25 local hours."""
        tz = ZoneInfo("America/Chicago")
        ts_utc = pd.date_range("2024-11-03 00:00", "2024-11-04 12:00", freq="1h", tz="UTC")
        df_obs = pd.DataFrame({
            "valid_utc": ts_utc,
            "temp_c": [5.0 + (i % 4) for i in range(len(ts_utc))],
        })

        slicer = ObservationSlicer()
        res = slicer.slice_dataframe(df_obs, station="KORD", target_year=2024)

        row_nov3 = res[res["local_date"] == "2024-11-03"].iloc[0]
        assert row_nov3["total_obs_count"] == 25
        assert row_nov3["day_of_year"] == resolve_day_of_year("2024-11-03")

    def test_adr0009_dual_track_speci_divergence(self):
        """Verify ADR-0009 dual-track separation: SPECI spike captured in all_reports but filtered from hourly_only."""
        timestamps = [
            "2026-08-31 16:51:00+00:00",  # 11:51 CDT, 27.0°C
            "2026-08-31 17:51:00+00:00",  # 12:51 CDT, 28.0°C
            "2026-08-31 18:44:00+00:00",  # 13:44 CDT (SPECI spike), 31.0°C
            "2026-08-31 18:51:00+00:00",  # 13:51 CDT, 29.0°C
            "2026-08-31 19:51:00+00:00",  # 14:51 CDT, 29.4°C (peak hourly)
            "2026-08-31 20:51:00+00:00",  # 15:51 CDT, 29.0°C
        ]
        temps_c = [27.0, 28.0, 31.0, 29.0, 29.4, 29.0]
        raw_metars = [
            "KORD 311651Z 22010KT 10SM CLR 27/18 A2993",
            "KORD 311751Z 22011KT 10SM CLR 28/19 A2992",
            "SPECI KORD 311844Z 22013G19KT 10SM TS 30/20 A2992 RMK AO2 T03100200",
            "KORD 311851Z 20014KT 10SM -TSRA 29/20 A2991 RMK AO2 T02900200",
            "KORD 311951Z 21012KT 10SM SCT060 29/19 A2991 RMK AO2 T02940190",
            "KORD 312051Z 21010KT 10SM CLR 29/19 A2992 RMK AO2 T02900190",
        ]
        df_obs = pd.DataFrame({
            "valid_utc": pd.to_datetime(timestamps),
            "temp_c": temps_c,
            "raw_metar": raw_metars,
        })

        slicer = ObservationSlicer()
        res = slicer.slice_dataframe(df_obs, station="KORD", target_year=2026)

        assert len(res) == 1
        row = res.iloc[0]

        # Settlement truth must capture the SPECI spike (31.0°C / 87.8°F)
        assert row["tmax_daily_all_reports"] == 31.0
        assert row["tmax_daily_all_reports_f"] == 87.8

        # Hourly-only feature must filter out the 13:44 SPECI and retain 29.4°C (84.92°F)
        assert row["tmax_daily_hourly_only"] == 29.4
        assert row["tmax_daily_hourly_only_f"] == 84.92

        # Discrepancy indicator must trigger
        assert bool(row["has_speci_divergence"]) is True
        assert row["total_obs_count"] == 6
        assert row["hourly_obs_count"] == 5

    def test_speci_within_hourly_window_excluded(self):
        """A SPECI issued even within the :50-:55 minute window must be excluded from hourly_only."""
        timestamps = [
            "2026-08-31 18:51:00+00:00",  # routine METAR at :51
            "2026-08-31 18:52:00+00:00",  # SPECI issued at :52
        ]
        raw_metars = [
            "KORD 311851Z 20014KT 10SM -TSRA 28.0/20 A2991",
            "SPECI KORD 311852Z 22025G35KT 5SM +TSRA 32.0/20 A2990",
        ]
        df_obs = pd.DataFrame({
            "valid_utc": pd.to_datetime(timestamps),
            "temp_c": [28.0, 32.0],
            "raw_metar": raw_metars,
        })

        slicer = ObservationSlicer()
        res = slicer.slice_dataframe(df_obs, station="KORD", target_year=2026)
        row = res.iloc[0]

        # All reports sees the SPECI peak
        assert row["tmax_daily_all_reports"] == 32.0
        # Hourly only MUST NOT see the SPECI despite its :52 minute
        assert row["tmax_daily_hourly_only"] == 28.0
        assert row["hourly_obs_count"] == 1
        assert bool(row["has_speci_divergence"]) is True

    def test_divergence_check_boundary_safety(self):
        """Divergence check must handle nulls safely without 0.0 false alarms."""
        # Both identical -> False
        assert check_speci_divergence(30.0, 30.0, 15.0, 15.0) is False
        # Max differs -> True
        assert check_speci_divergence(31.0, 30.0, 15.0, 15.0) is True
        # Min differs -> True
        assert check_speci_divergence(30.0, 30.0, 14.0, 15.0) is True
        # Hourly missing while all exists -> True (divergence by definition)
        assert check_speci_divergence(30.0, None, 15.0, 15.0) is True
        # Hourly min missing while all min exists -> True
        assert check_speci_divergence(30.0, 30.0, 15.0, None) is True
        # Both completely empty -> False
        assert check_speci_divergence(None, None, None, None) is False

    def test_vintage_and_usage_tagging(self):
        """Verify vintage and usage metadata injection across Era 1 and Era 2."""
        slicer = ObservationSlicer()

        # Era 1 (2018)
        df_2018 = pd.DataFrame({
            "valid_utc": pd.date_range("2018-06-01 12:00", periods=6, freq="1h", tz="UTC"),
            "temp_c": [20.0] * 6,
        })
        res_2018 = slicer.slice_dataframe(df_2018, station="KORD", target_year=2018)
        assert res_2018.iloc[0]["vintage"] == VINTAGE_ERA1
        assert res_2018.iloc[0]["usage"] == USAGE_STRESS_TEST_ONLY

        # Era 2 (2019)
        df_2019 = pd.DataFrame({
            "valid_utc": pd.date_range("2019-06-01 12:00", periods=6, freq="1h", tz="UTC"),
            "temp_c": [20.0] * 6,
        })
        res_2019 = slicer.slice_dataframe(df_2019, station="KORD", target_year=2019)
        assert res_2019.iloc[0]["vintage"] == VINTAGE_ERA2
        assert res_2019.iloc[0]["usage"] == USAGE_TRAINING_READY

    def test_station_hourly_window_adaptation(self):
        """Verify KSFO (:56) and KBKF (:58) routine METARs are properly captured."""
        slicer = ObservationSlicer()

        # KBKF has routine METAR at minute 58
        df_bkf = pd.DataFrame({
            "valid_utc": pd.to_datetime([
                "2020-01-01 18:58:00+00:00",
                "2020-01-01 19:58:00+00:00",
                "2020-01-01 20:58:00+00:00",
                "2020-01-01 21:58:00+00:00",
            ]),
            "temp_c": [0.0, 2.0, 4.0, 3.0],
        })
        res_bkf = slicer.slice_dataframe(df_bkf, station="KBKF", target_year=2020)
        assert res_bkf.iloc[0]["hourly_obs_count"] == 4
        assert res_bkf.iloc[0]["tmax_daily_hourly_only"] == 4.0

        # KSFO has routine METAR at minute 56
        df_sfo = pd.DataFrame({
            "valid_utc": pd.to_datetime([
                "2020-01-01 18:56:00+00:00",
                "2020-01-01 19:56:00+00:00",
                "2020-01-01 20:56:00+00:00",
                "2020-01-01 21:56:00+00:00",
            ]),
            "temp_c": [12.0, 14.0, 15.0, 13.0],
        })
        res_sfo = slicer.slice_dataframe(df_sfo, station="KSFO", target_year=2020)
        assert res_sfo.iloc[0]["hourly_obs_count"] == 4
        assert res_sfo.iloc[0]["tmax_daily_hourly_only"] == 15.0
