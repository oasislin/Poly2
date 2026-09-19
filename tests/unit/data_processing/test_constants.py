"""
Unit tests and contract integrity tests for station metadata and constants (Task 07).
Validates that all Active 11 US trading stations have complete, uncorrupted six-element attributes,
and verifies that decommissioned stations (KDCA) are strictly banished.
"""

from zoneinfo import ZoneInfo
import pytest

from src.data_processing.constants import (
    ACTIVE_11_STATIONS,
    STATION_COORDINATES,
    STATION_DEFAULT_UNITS,
    STATION_METADATA,
    STATION_TIMEZONES,
)


class TestStationUniverseIntegrity:
    """Validate Active 11 station set structure, completeness, and decommissioning isolation."""

    def test_active_11_stations_composition(self):
        expected_11 = {
            "KORD",
            "KLGA",
            "KATL",
            "KDAL",
            "KSEA",
            "KLAX",
            "KHOU",
            "KMIA",
            "KSFO",
            "KBKF",
            "KAUS",
        }
        assert set(ACTIVE_11_STATIONS) == expected_11
        assert len(ACTIVE_11_STATIONS) == 11

    def test_decommissioned_kdca_strictly_banished(self):
        """KDCA was retired in 1b53879 and must not exist in active universe or metadata."""
        assert "KDCA" not in ACTIVE_11_STATIONS
        assert "KDCA" not in STATION_METADATA

    def test_all_active_stations_present_in_metadata(self):
        for st in ACTIVE_11_STATIONS:
            assert st in STATION_METADATA, f"Station {st} missing from STATION_METADATA"


class TestSixElementMetadataContracts:
    """Validate the 6-factor element completeness and data typing for all Active 11 stations."""

    REQUIRED_KEYS = {
        "station_id",
        "name",
        "city",
        "country",
        "latitude",
        "longitude",
        "elevation",
        "timezone",
        "temperature_unit",
        "polymarket_id",
        "audit_status",
        "nws_native",
        "iem_network",
        "historical_coverage_pct",
        "update_lag_p50_min",
        "daily_recs_count",
        "active_polymarket",
        "liquidity_usd",
        "coastal_microclimate",
        "microclimate_score",
    }

    @pytest.mark.parametrize("station", ACTIVE_11_STATIONS)
    def test_station_required_fields_presence(self, station):
        meta = STATION_METADATA[station]
        missing = self.REQUIRED_KEYS - set(meta.keys())
        assert not missing, f"Station {station} missing metadata fields: {missing}"

    @pytest.mark.parametrize("station", ACTIVE_11_STATIONS)
    def test_geographic_coordinates_element(self, station):
        """Element 1 & 2: Coordinates (Lat/Lon) and Elevation."""
        meta = STATION_METADATA[station]
        lat = meta["latitude"]
        lon = meta["longitude"]
        elev = meta["elevation"]

        assert isinstance(lat, float)
        assert 24.0 <= lat <= 50.0, f"{station} latitude {lat} outside US continental range"

        assert isinstance(lon, float)
        assert -130.0 <= lon <= -65.0, f"{station} longitude {lon} outside US continental range"

        assert isinstance(elev, float)
        assert elev >= 0.0, f"{station} elevation {elev} must be non-negative"

    @pytest.mark.parametrize("station", ACTIVE_11_STATIONS)
    def test_timezone_element(self, station):
        """Element 3: Timezone string and IANA validity."""
        meta = STATION_METADATA[station]
        tz_str = meta["timezone"]
        assert isinstance(tz_str, str)
        # Must load cleanly into Python standard ZoneInfo
        tz = ZoneInfo(tz_str)
        assert tz is not None
        assert tz_str.startswith("America/")

    @pytest.mark.parametrize("station", ACTIVE_11_STATIONS)
    def test_temperature_unit_element(self, station):
        """Element 4: Native Temperature Unit (US ASOS is Fahrenheit)."""
        meta = STATION_METADATA[station]
        unit = meta["temperature_unit"]
        assert unit == "F", f"{station} native unit must be 'F', got '{unit}'"

    @pytest.mark.parametrize("station", ACTIVE_11_STATIONS)
    def test_reporting_characteristics_element(self, station):
        """Element 5: Reporting frequency, lag, coverage, and microclimate profile."""
        meta = STATION_METADATA[station]

        # Reporting rate
        daily_recs = meta["daily_recs_count"]
        assert isinstance(daily_recs, int)
        # KBKF is sparse reporting (25/day), standard ASOS is ~310/day
        assert daily_recs >= 20, f"{station} daily_recs_count unexpectedly low: {daily_recs}"

        # Update lag
        lag = meta["update_lag_p50_min"]
        assert isinstance(lag, float)
        assert 10.0 <= lag <= 35.0, f"{station} update lag {lag} outside normal bounds"

        # Historical coverage
        cov = meta["historical_coverage_pct"]
        assert isinstance(cov, float)
        assert 90.0 <= cov <= 100.0, f"{station} coverage {cov}% outside valid range"

        # Microclimate score & coastal flag
        score = meta["microclimate_score"]
        assert isinstance(score, float)
        assert 60.0 <= score <= 100.0, f"{station} microclimate score {score} invalid"
        assert isinstance(meta["coastal_microclimate"], bool)

    @pytest.mark.parametrize("station", ACTIVE_11_STATIONS)
    def test_network_and_audit_element(self, station):
        """Element 6: Network tags, audit admission status, and polymarket flags."""
        meta = STATION_METADATA[station]

        assert meta["station_id"] == station
        assert meta["country"] == "us"
        assert meta["nws_native"] is True

        network = meta["iem_network"]
        assert isinstance(network, str)
        assert network.endswith("_ASOS"), f"{station} network {network} must be an ASOS network"

        assert isinstance(meta["audit_status"], str)
        assert meta["audit_status"].startswith("ADMITTED_")

        assert meta["active_polymarket"] is True
        assert meta["liquidity_usd"] > 0.0


class TestDerivedLookupMappings:
    """Verify synchronization across derived lookup dicts."""

    def test_derived_dictionaries_contain_all_active_stations(self):
        for st in ACTIVE_11_STATIONS:
            assert st in STATION_COORDINATES, f"{st} missing in STATION_COORDINATES"
            assert st in STATION_TIMEZONES, f"{st} missing in STATION_TIMEZONES"
            assert st in STATION_DEFAULT_UNITS, f"{st} missing in STATION_DEFAULT_UNITS"

            # Check coordinate fields
            coord = STATION_COORDINATES[st]
            assert "latitude" in coord
            assert "longitude" in coord
            assert "elevation" in coord
            assert "timezone" in coord

            # Check timezone match
            assert STATION_TIMEZONES[st] == STATION_METADATA[st]["timezone"]
            # Check default unit match
            assert STATION_DEFAULT_UNITS[st] == "F"
