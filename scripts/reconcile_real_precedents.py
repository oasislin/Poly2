#!/usr/bin/env python3
"""
Empirical Precedent Reconciliation Engine:
Pulls real resolved events from Polymarket Gamma API, queries actual NWS WRH (Synoptic API)
observations for each event date, and validates genuine ground truth against market winning brackets.
"""

from datetime import datetime, timezone, timedelta
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import zoneinfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Add root to pythonpath
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from src.data_acquisition.nws_wrh_collector import NwsWrhAdapter
from src.data_analysis.settlement_station_auditor import SettlementStationAuditor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PrecedentReconciliation")

CITY_CONFIG = {
    "Denver": {
        "timezone": "America/Denver",
        "primary_station": "KBKF",
        "candidates": ["KBKF", "KDEN"],
    },
    "Chicago": {
        "timezone": "America/Chicago",
        "primary_station": "KORD",
        "candidates": ["KORD", "KMDW"],
    },
    "NYC": {
        "timezone": "America/New_York",
        "primary_station": "KLGA",
        "candidates": ["KLGA", "KNYC", "KJFK"],
    },
    "Miami": {
        "timezone": "America/New_York",
        "primary_station": "KMIA",
        "candidates": ["KMIA"],
    },
    "Dallas": {
        "timezone": "America/Chicago",
        "primary_station": "KDAL",
        "candidates": ["KDAL", "KDFW"],
    },
    "Seattle": {
        "timezone": "America/Los_Angeles",
        "primary_station": "KSEA",
        "candidates": ["KSEA"],
    },
    "Atlanta": {
        "timezone": "America/New_York",
        "primary_station": "KATL",
        "candidates": ["KATL"],
    },
    "Los Angeles": {
        "timezone": "America/Los_Angeles",
        "primary_station": "KLAX",
        "candidates": ["KLAX"],
    },
    "San Francisco": {
        "timezone": "America/Los_Angeles",
        "primary_station": "KSFO",
        "candidates": ["KSFO"],
    },
}


def build_resilient_session() -> requests.Session:
    """Build requests session with automatic retry on SSL/network errors."""
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def fetch_resolved_events_for_city(
    session: requests.Session, city: str, max_events: int = 5
) -> List[Dict[str, Any]]:
    """Fetch resolved events for a city from Polymarket Gamma API."""
    logger.info(f"Querying resolved events for {city}...")
    try:
        r = session.get(
            "https://gamma-api.polymarket.com/public-search",
            params={"q": f"highest temperature {city}", "limit_per_type": 30},
            timeout=20,
        )
        if r.status_code != 200:
            return []
        events_data = r.json().get("events", [])
    except Exception as e:
        logger.warning(f"Error querying search for {city}: {e}")
        return []

    resolved = []
    # If NYC, ensure the 3 recent WRH events and 2 legacy WU events are audited
    if city == "NYC":
        specific_slugs = [
            "highest-temperature-in-nyc-on-september-2-2026",
            "highest-temperature-in-nyc-on-september-1-2026",
            "highest-temperature-in-nyc-on-august-31-2026",
            "highest-temperature-in-nyc-on-july-15",
            "highest-temperature-in-nyc-on-october-5",
        ]
        candidate_slugs = specific_slugs + [ev.get("slug") for ev in events_data if ev.get("slug") not in specific_slugs]
    else:
        candidate_slugs = [ev.get("slug") for ev in events_data if ev.get("slug")]

    for slug in candidate_slugs:
        try:
            time.sleep(0.1)  # Throttle
            ev_r = session.get(f"https://gamma-api.polymarket.com/events/slug/{slug}", timeout=15)
            if ev_r.status_code != 200:
                continue
            data = ev_r.json()
            markets = data.get("markets", [])
            winner = None
            for m in markets:
                prices = m.get("outcomePrices")
                if prices:
                    try:
                        p = json.loads(prices) if isinstance(prices, str) else prices
                        if p and float(p[0]) >= 0.90:
                            winner = m.get("groupItemTitle")
                            break
                    except Exception:
                        pass
                if m.get("winner") is True:
                    winner = m.get("groupItemTitle")
                    break

            if winner:
                end_date_str = data.get("endDate", "")
                desc = data.get("description", "")
                era = "Era 2 (NWS WRH)" if "weather.gov/wrh" in desc else "Era 1 (Wunderground)"
                resolved.append({
                    "slug": slug,
                    "title": data.get("title"),
                    "endDate": end_date_str,
                    "winner": winner,
                    "description": desc,
                    "era": era,
                    "volume": float(data.get("volume", 0.0) or 0.0),
                })
                if len(resolved) >= (5 if city == "NYC" else max_events):
                    break
        except Exception as e:
            logger.warning(f"Error fetching event {slug}: {e}")
            continue

    logger.info(f"Found {len(resolved)} resolved events for {city}")
    return resolved


def extract_real_daily_max(
    wrh_adapter: NwsWrhAdapter,
    station: str,
    date_str: str,
    tz_str: str,
) -> Tuple[Optional[float], int]:
    """
    Fetch real Synoptic observation records for a local calendar day and compute daily max temp °F.
    Returns: (max_temp_f, valid_records_count)
    """
    try:
        tz = zoneinfo.ZoneInfo(tz_str)
        # Parse date from ISO (e.g. '2026-09-02T12:00:00Z' or '2026-09-02')
        dt_target = datetime.fromisoformat(date_str.replace("Z", "+00:00")).astimezone(tz)
        local_day_start = datetime(dt_target.year, dt_target.month, dt_target.day, 0, 0, 0, tzinfo=tz)
        local_day_end = datetime(dt_target.year, dt_target.month, dt_target.day, 23, 59, 59, tzinfo=tz)

        # Buffer by 1 hour on each side
        utc_start = local_day_start.astimezone(timezone.utc) - timedelta(hours=1)
        utc_end = local_day_end.astimezone(timezone.utc) + timedelta(hours=1)

        records = wrh_adapter.fetch_raw_series(station, utc_start, utc_end)
        # Filter strictly to local calendar day
        day_records = [
            r for r in records
            if local_day_start <= r.timestamp.astimezone(tz) <= local_day_end
        ]

        temps_f = [r.temp_f for r in day_records if r.temp_f is not None]
        if not temps_f:
            # Fallback to temp_c converted to F if temp_f is None
            temps_f = [
                (r.temp_c * 9.0 / 5.0 + 32.0) for r in day_records if r.temp_c is not None
            ]

        if temps_f:
            return round(max(temps_f), 2), len(day_records)
        return None, len(day_records)
    except Exception as e:
        logger.warning(f"Error fetching real observations for {station} on {date_str}: {e}")
        return None, 0


def run_full_reconciliation() -> Dict[str, Any]:
    """Run end-to-end real empirical precedent reconciliation."""
    session = build_resilient_session()
    wrh_adapter = NwsWrhAdapter()
    auditor = SettlementStationAuditor()

    reconciliation_results = {}

    for city, cfg in CITY_CONFIG.items():
        events = fetch_resolved_events_for_city(session, city, max_events=4)
        city_audits = []

        for ev in events:
            date_str = ev["endDate"]
            winner = ev["winner"]
            candidate_obs = {}
            candidate_recs_count = {}

            for cand in cfg["candidates"]:
                time.sleep(0.2)  # Throttle Synoptic queries
                val, count = extract_real_daily_max(
                    wrh_adapter, cand, date_str, cfg["timezone"]
                )
                candidate_obs[cand] = val
                candidate_recs_count[cand] = count

            # Audit against real observation
            prec_record = auditor.audit_precedent(
                target_date=date_str[:10],
                event_title=ev["title"],
                event_slug=ev["slug"],
                winning_bracket=winner,
                declared_station=cfg["primary_station"],
                candidate_max_temps=candidate_obs,
            )

            city_audits.append({
                "target_date": prec_record.target_date,
                "event_title": prec_record.event_title,
                "event_slug": prec_record.event_slug,
                "winning_bracket": prec_record.winning_bracket,
                "declared_station": prec_record.declared_station,
                "candidate_observations": prec_record.candidate_observations,
                "candidate_records_count": candidate_recs_count,
                "matched_candidate": prec_record.matched_candidate,
                "audit_verdict": str(prec_record.audit_verdict),
                "era": ev.get("era", "Era 1 (Wunderground)"),
                "notes": prec_record.notes,
            })

        reconciliation_results[city] = {
            "city": city,
            "primary_station": cfg["primary_station"],
            "timezone": cfg["timezone"],
            "total_precedents_found": len(city_audits),
            "precedents": city_audits,
        }

    # Save to disk
    out_file = repo_root / "data/processed/real_settlement_precedents.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(reconciliation_results, f, indent=2, ensure_ascii=False)

    logger.info(f"Successfully saved real settlement precedents to {out_file}")
    return reconciliation_results


if __name__ == "__main__":
    run_full_reconciliation()
