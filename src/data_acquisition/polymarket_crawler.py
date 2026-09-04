"""
Polymarket Temperature Market Crawler and Rule Parser (Ticket 01 of M0').
Fetches active and historical temperature markets, parses metadata, rules, and precedents.
"""

from dataclasses import dataclass, field
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
import requests

logger = logging.getLogger(__name__)


@dataclass
class PolymarketMarketEvent:
    """Strongly-typed metadata for a Polymarket weather event."""
    event_id: str
    slug: str
    title: str
    city: str
    target_date_str: str
    status: str  # 'active', 'closed', 'resolved'
    description: str
    stated_wrh_site: Optional[str] = None
    stated_wunderground_site: Optional[str] = None
    unit: str = "Fahrenheit"  # 'Fahrenheit' or 'Celsius'
    volume_usd: float = 0.0
    liquidity_usd: float = 0.0
    winning_bracket: Optional[str] = None
    markets: List[Dict[str, Any]] = field(default_factory=list)


class PolymarketCrawler:
    """Crawler for Polymarket weather and temperature prediction markets."""

    BASE_URL = "https://gamma-api.polymarket.com"

    KNOWN_CITIES = [
        "Denver", "Chicago", "NYC", "London", "Miami", "Dallas",
        "Seattle", "Atlanta", "Los Angeles", "San Francisco",
        "Houston", "Paris", "Seoul", "Tokyo"
    ]

    def __init__(self, session: Optional[requests.Session] = None, timeout: int = 15):
        self.session = session if session else requests.Session()
        self.timeout = timeout

    @staticmethod
    def extract_site_from_description(description: str) -> Tuple[Optional[str], Optional[str], str]:
        """
        Extract NWS WRH site code, Wunderground site code, and temperature unit from rule text.
        Returns: (wrh_site, wunder_site, unit)
        """
        if not description:
            return None, None, "Fahrenheit"

        # Match site=<stid>
        wrh_match = re.search(r"site=([a-zA-Z0-9]+)", description)
        wrh_site = wrh_match.group(1).upper() if wrh_match else None

        # Match wunderground.com/.../<stid>
        wunder_match = re.search(
            r"wunderground\.com/history/daily/[^/]+/[^/]+/[^/]+/([a-zA-Z0-9]+)",
            description,
        )
        wunder_site = wunder_match.group(1).upper() if wunder_match else None

        # Check unit
        unit = "Celsius" if "degrees Celsius" in description or "displays °C" in description else "Fahrenheit"

        return wrh_site, wunder_site, unit

    @staticmethod
    def determine_winning_bracket(markets: List[Dict[str, Any]]) -> Optional[str]:
        """Determine winning market bracket from outcome prices or outcome status."""
        for m in markets:
            # Check outcomePrices
            prices = m.get("outcomePrices")
            if prices:
                try:
                    p_list = json.loads(prices) if isinstance(prices, str) else prices
                    if p_list and float(p_list[0]) >= 0.90:
                        return m.get("groupItemTitle")
                except Exception:
                    pass
            # Check winner flag
            if m.get("winner") is True:
                return m.get("groupItemTitle")
        return None

    def search_city_events(self, city: str, limit: int = 25) -> List[PolymarketMarketEvent]:
        """Search temperature events for a specific city."""
        query = f"highest temperature {city}"
        try:
            resp = self.session.get(
                f"{self.BASE_URL}/public-search",
                params={"q": query, "limit_per_type": limit},
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                logger.warning(f"Failed to search events for {city}: {resp.status_code}")
                return []
            events_data = resp.json().get("events", [])
        except Exception as e:
            logger.error(f"Exception searching events for {city}: {e}")
            return []

        parsed_events: List[PolymarketMarketEvent] = []
        for ev in events_data:
            slug = ev.get("slug")
            if not slug:
                continue
            event_obj = self.fetch_event_details(slug, city=city)
            if event_obj:
                parsed_events.append(event_obj)

        return parsed_events

    def fetch_event_details(self, slug: str, city: Optional[str] = None) -> Optional[PolymarketMarketEvent]:
        """Fetch detailed event payload and parse into PolymarketMarketEvent."""
        try:
            resp = self.session.get(f"{self.BASE_URL}/events/slug/{slug}", timeout=self.timeout)
            if resp.status_code != 200:
                return None
            data = resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch event details for {slug}: {e}")
            return None

        desc = data.get("description", "")
        wrh_site, wunder_site, unit = self.extract_site_from_description(desc)
        markets = data.get("markets", [])
        winner = self.determine_winning_bracket(markets)

        # Volume and liquidity
        volume = float(data.get("volume", 0.0) or 0.0)
        liquidity = float(data.get("liquidity", 0.0) or 0.0)
        status = "resolved" if winner else ("closed" if data.get("closed") else "active")

        # Determine target date
        end_date = data.get("endDate", "")

        return PolymarketMarketEvent(
            event_id=str(data.get("id", "")),
            slug=slug,
            title=data.get("title", ""),
            city=city or "Unknown",
            target_date_str=end_date,
            status=status,
            description=desc,
            stated_wrh_site=wrh_site,
            stated_wunderground_site=wunder_site,
            unit=unit,
            volume_usd=volume,
            liquidity_usd=liquidity,
            winning_bracket=winner,
            markets=markets,
        )
