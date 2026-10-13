import os
import json
import requests
import time

CITIES_PATH = "/Users/ericlin/SynologyDrive/Project/Polymarket天气套利/config/cities.json"
FALLBACK_STATION_MAP = {
    "RKSI": {"lat": 37.469, "lon": 126.451, "city": "Incheon", "timezone": "Asia/Seoul"},
    "KNYC": {"lat": 40.782, "lon": -73.965, "city": "New York", "timezone": "America/New_York"},
    "EGLL": {"lat": 51.470, "lon": -0.454, "city": "London", "timezone": "Europe/London"},
    "RJTT": {"lat": 35.552, "lon": 139.780, "city": "Tokyo", "timezone": "Asia/Tokyo"},
    "VHHH": {"lat": 22.308, "lon": 113.918, "city": "Hong Kong", "timezone": "Asia/Hong_Kong"},
    "ZSSS": {"lat": 31.198, "lon": 121.336, "city": "Shanghai", "timezone": "Asia/Shanghai"},
    
    # 解决 Polymarket 对赌协议描述中写错的非标准 ICAO 代码 ( typos )
    "ATLA": {"lat": 33.640, "lon": -84.428, "city": "Atlanta", "timezone": "America/New_York"},
    "HOUS": {"lat": 29.645, "lon": -95.279, "city": "Houston", "timezone": "America/Chicago"},
    "CHIC": {"lat": 41.974, "lon": -87.907, "city": "Chicago", "timezone": "America/Chicago"},
    "AUST": {"lat": 30.194, "lon": -97.670, "city": "Austin", "timezone": "America/Chicago"},
    "DENV": {"lat": 39.856, "lon": -104.673, "city": "Denver", "timezone": "America/Denver"},
    "AURO": {"lat": 39.856, "lon": -104.673, "city": "Denver", "timezone": "America/Denver"},
    "MIAI": {"lat": 25.793, "lon": -80.290, "city": "Miami", "timezone": "America/New_York"},
    "MIAM": {"lat": 25.793, "lon": -80.290, "city": "Miami", "timezone": "America/New_York"},
    "SEAT": {"lat": 47.448, "lon": -122.309, "city": "Seattle", "timezone": "America/Los_Angeles"},
    "DALL": {"lat": 32.899, "lon": -97.040, "city": "Dallas", "timezone": "America/Chicago"}
}

def resolve_from_awc(station_id):
    awc_url = "https://aviationweather.gov/api/data/stationinfo"
    url = f"{awc_url}?ids={station_id}&format=json"
    headers = {"User-Agent": "WeatherArbitrageBot/1.0.0 (huhuh@gemini.antigravity)"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            station_info = None
            if isinstance(data, list) and len(data) > 0:
                station_info = data[0]
            elif isinstance(data, dict):
                station_info = data
            if station_info and "lat" in station_info and "lon" in station_info:
                return float(station_info["lat"]), float(station_info["lon"])
    except Exception as e:
        print(f"Error calling AWC for {station_id}: {e}")
    return None

def main():
    with open(CITIES_PATH, "r", encoding="utf-8") as f:
        cities = json.load(f)

    updated = False
    for station_id, info in cities.items():
        lat = info.get("lat", 0.0)
        lon = info.get("lon", 0.0)
        if abs(lat) < 1e-5 and abs(lon) < 1e-5:
            print(f"Resolving coordinates for {station_id}...")
            # Try AWC
            coords = resolve_from_awc(station_id)
            if coords:
                info["lat"], info["lon"] = coords
                print(f"  Success (AWC): {coords}")
                updated = True
            # Try Fallback Map
            elif station_id in FALLBACK_STATION_MAP:
                fb = FALLBACK_STATION_MAP[station_id]
                info["lat"], info["lon"] = fb["lat"], fb["lon"]
                print(f"  Success (Fallback): ({fb['lat']}, {fb['lon']})")
                updated = True
            else:
                print(f"  Failed to resolve {station_id}!")
            time.sleep(0.5)

    if updated:
        with open(CITIES_PATH, "w", encoding="utf-8") as f:
            json.dump(cities, f, indent=2, ensure_ascii=False)
        print("Successfully updated cities.json with resolved coordinates!")
    else:
        print("No zero coordinates needed resolution or updated.")

if __name__ == "__main__":
    main()
