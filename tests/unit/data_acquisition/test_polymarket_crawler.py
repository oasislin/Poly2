"""
Unit tests for PolymarketCrawler (Ticket 01 of M0').
"""

import json
from unittest.mock import MagicMock, patch
import pytest

from src.data_acquisition.polymarket_crawler import PolymarketCrawler, PolymarketMarketEvent


def test_extract_site_from_description_denver_kbkf():
    crawler = PolymarketCrawler()
    desc = """
    This market will resolve to the temperature range that contains the highest temperature recorded by NOAA at the Buckley Space Force Base Station in degrees Fahrenheit on 3 Sep '26.
    The resolution source for this market will be information from NOAA, specifically the highest reading under the "Temp" column for all times on this day, available here: https://www.weather.gov/wrh/timeseries?site=kbkf
    If NOAA data is unavailable, https://www.wunderground.com/history/daily/us/co/aurora/KBKF will be used.
    """
    wrh_site, wunder_site, unit = crawler.extract_site_from_description(desc)
    assert wrh_site == "KBKF"
    assert wunder_site == "KBKF"
    assert unit == "Fahrenheit"


def test_extract_site_from_description_celsius():
    crawler = PolymarketCrawler()
    desc = """
    This market will resolve to the temperature recorded by NOAA at London City Airport Station in degrees Celsius on 3 Sep '26.
    https://www.weather.gov/wrh/timeseries?site=eglc
    """
    wrh_site, wunder_site, unit = crawler.extract_site_from_description(desc)
    assert wrh_site == "EGLC"
    assert unit == "Celsius"


def test_determine_winning_bracket():
    crawler = PolymarketCrawler()
    markets = [
        {"groupItemTitle": "86-87°F", "outcomePrices": '["0.01", "0.99"]'},
        {"groupItemTitle": "88-89°F", "outcomePrices": '["0.98", "0.02"]'},
        {"groupItemTitle": "90-91°F", "outcomePrices": '["0.01", "0.99"]'},
    ]
    assert crawler.determine_winning_bracket(markets) == "88-89°F"


def test_determine_winning_bracket_flag():
    crawler = PolymarketCrawler()
    markets = [
        {"groupItemTitle": "86-87°F", "winner": False},
        {"groupItemTitle": "88-89°F", "winner": True},
    ]
    assert crawler.determine_winning_bracket(markets) == "88-89°F"


def test_fetch_event_details_mock():
    crawler = PolymarketCrawler()
    fake_payload = {
        "id": "12345",
        "slug": "highest-temperature-in-denver-on-september-3-2026",
        "title": "Highest temperature in Denver on September 3?",
        "description": "https://www.weather.gov/wrh/timeseries?site=kbkf",
        "volume": "45200.5",
        "liquidity": "12800.0",
        "endDate": "2026-09-03T12:00:00Z",
        "markets": [{"groupItemTitle": "88-89°F", "winner": True}],
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = fake_payload

    with patch.object(crawler.session, "get", return_value=mock_resp):
        event = crawler.fetch_event_details("highest-temperature-in-denver-on-september-3-2026", city="Denver")

    assert event is not None
    assert event.event_id == "12345"
    assert event.stated_wrh_site == "KBKF"
    assert event.winning_bracket == "88-89°F"
    assert event.volume_usd == 45200.5
    assert event.status == "resolved"
