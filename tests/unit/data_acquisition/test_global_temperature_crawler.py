"""
Unit tests for the standalone Global Temperature Markets Crawler and Rule Parser.
"""

from scripts.crawl_all_temperature_settlement_sources import (
    GlobalTemperatureCrawler,
    CrawlerSelfInspector,
    TemperatureMarketRecord,
)


def test_parse_settlement_rules_us_highest():
    crawler = GlobalTemperatureCrawler()
    title = "Highest temperature in NYC on September 2?"
    desc = """This market will resolve to the temperature range that contains the highest temperature recorded by NOAA at the LaGuardia Airport Station in degrees Fahrenheit on 2 Sep '26.
The resolution source for this market will be information from NOAA, specifically the highest reading under the "Temp" column for all times on this day, available here: https://www.weather.gov/wrh/timeseries?site=klga
This market will resolve off of the Hourly Data provided using the "Show Hourly Data" button.
"""
    rules = crawler.parse_settlement_rules(title, desc)
    assert rules["metric_type"] == "MAX_TEMP"
    assert rules["unit"] == "Fahrenheit"
    assert rules["stated_station_id"] == "KLGA"
    assert "LaGuardia" in rules["stated_station_name"]
    assert rules["stated_agency"] == "NOAA NWS (National Weather Service)"
    assert rules["has_hourly_filter"] is True
    assert "site=klga" in rules["resolution_url"]


def test_parse_settlement_rules_us_lowest():
    crawler = GlobalTemperatureCrawler()
    title = "Lowest temperature in Denver on September 3?"
    desc = """This market will resolve to the temperature range that contains the lowest temperature recorded by NOAA at the Buckley Space Force Base Station in degrees Fahrenheit on 3 Sep '26.
The resolution source for this market will be information from NOAA, specifically the lowest reading under the "Temp" column for all times on this day, available here: https://www.weather.gov/wrh/timeseries?site=kbkf
"""
    rules = crawler.parse_settlement_rules(title, desc)
    assert rules["metric_type"] == "MIN_TEMP"
    assert rules["unit"] == "Fahrenheit"
    assert rules["stated_station_id"] == "KBKF"
    assert "Buckley" in rules["stated_station_name"]
    assert rules["stated_agency"] == "NOAA NWS (National Weather Service)"


def test_parse_settlement_rules_hong_kong():
    crawler = GlobalTemperatureCrawler()
    title = "Lowest temperature in Hong Kong on September 4?"
    desc = """This market will resolve to the temperature range that contains the lowest temperature recorded by the Hong Kong Observatory in degrees Celsius on 4 Sep '26.
The resolution source for this market will be information from the Hong Kong Observatory, specifically the "Absolute Daily Min (deg. C)" the specified date once information is finalized in the relevant "Daily Extract", available here: https://www.weather.gov.hk/en/cis/climat.htm
"""
    rules = crawler.parse_settlement_rules(title, desc)
    assert rules["metric_type"] == "MIN_TEMP"
    assert rules["unit"] == "Celsius"
    assert rules["stated_station_id"] == "HKO"
    assert rules["stated_agency"] == "Hong Kong Observatory (HKO)"
    assert "climat.htm" in rules["resolution_url"]


def test_parse_settlement_rules_international_nws():
    crawler = GlobalTemperatureCrawler()
    title = "Highest temperature in London on September 3?"
    desc = """This market will resolve to the temperature range that contains the highest temperature recorded by NOAA at the London City Airport Station in degrees Celsius on 3 Sep '26.
The resolution source for this market will be information from NOAA, specifically the highest reading under the "Temp" column for all times on this day, available here: https://www.weather.gov/wrh/timeseries?site=eglc
"""
    rules = crawler.parse_settlement_rules(title, desc)
    assert rules["metric_type"] == "MAX_TEMP"
    assert rules["unit"] == "Celsius"
    assert rules["stated_station_id"] == "EGLC"
    assert rules["stated_agency"] == "NOAA NWS (National Weather Service)"


def test_parse_settlement_rules_wunderground():
    crawler = GlobalTemperatureCrawler()
    title = "Highest temperature in Amsterdam on April 15?"
    desc = """The resolution source for this market will be the Weather Underground Daily Observations table, available here: https://www.wunderground.com/history/daily/nl/schiphol/EHAM.
This market will resolve in degrees Celsius."""
    rules = crawler.parse_settlement_rules(title, desc)
    assert rules["metric_type"] == "MAX_TEMP"
    assert rules["unit"] == "Celsius"
    assert rules["stated_station_id"] == "EHAM"
    assert rules["stated_agency"] == "Weather Underground"


def test_crawler_self_inspector_diagnostics():
    sample_records = [
        TemperatureMarketRecord(
            event_id="1",
            slug="highest-temp-nyc",
            title="Highest temperature in NYC on Sep 1",
            city="NYC",
            target_date_str="2026-09-01",
            status="resolved",
            metric_type="MAX_TEMP",
            unit="Fahrenheit",
            settlement_oracle="UMA Optimistic Oracle",
            stated_agency="NOAA NWS",
            stated_station_id="KLGA",
            stated_station_name="LaGuardia Airport",
            resolution_url="https://www.weather.gov/wrh/timeseries?site=klga",
            secondary_fallback_source="Weather Underground",
            has_hourly_filter=True,
            has_rounding_clause=True,
            volume_usd=1000.0,
            liquidity_usd=500.0,
            winning_bracket="76-77°F",
            bracket_count=8,
            rule_description_snippet="sample snippet",
            crawled_at="2026-09-04T00:00:00Z",
        ),
        TemperatureMarketRecord(
            event_id="2",
            slug="lowest-temp-nyc",
            title="Lowest temperature in NYC on Sep 1",
            city="NYC",
            target_date_str="2026-09-01",
            status="resolved",
            metric_type="MIN_TEMP",
            unit="Fahrenheit",
            settlement_oracle="UMA Optimistic Oracle",
            stated_agency="NOAA NWS",
            stated_station_id="KLGA",
            stated_station_name="LaGuardia Airport",
            resolution_url="https://www.weather.gov/wrh/timeseries?site=klga",
            secondary_fallback_source="Weather Underground",
            has_hourly_filter=True,
            has_rounding_clause=True,
            volume_usd=800.0,
            liquidity_usd=400.0,
            winning_bracket="68-69°F",
            bracket_count=8,
            rule_description_snippet="sample snippet",
            crawled_at="2026-09-04T00:00:00Z",
        ),
    ]

    inspector = CrawlerSelfInspector(sample_records)
    audit = inspector.run_full_self_check()
    assert audit["total_markets_crawled"] == 2
    assert audit["metric_distribution"]["highest_temperature_markets"] == 1
    assert audit["metric_distribution"]["lowest_temperature_markets"] == 1
    assert "NYC" in audit["dual_direction_coverage"]["dual_coverage_cities"]
