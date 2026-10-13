import requests
import json
import datetime
import pytz

PROXIES = None # Or use default proxies if needed

def get_history():
    # Let's query the TWC v1 history API for ZSPD on July 18, 2026
    url = "https://api.weather.com/v1/location/ZSPD:9:CN/observations/historical.json"
    params = {
        "apiKey": "e1f10a1e78da46f5b10a1e78da96f525",
        "units": "m",
        "startDate": "20260718",
        "endDate": "20260718"
    }
    
    # We can check if there's a cached response first
    from src.weather_cache import get_api_cache
    cached = get_api_cache(url, params, expire_seconds=9999999)
    if cached:
        print("Using cached response")
        data = cached
    else:
        print("Fetching from API...")
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
        else:
            print("Failed to fetch:", r.status_code, r.text)
            return
            
    observations = data.get("observations", [])
    print(f"Total observations: {len(observations)}")
    tz = pytz.timezone("Asia/Shanghai")
    for obs in observations:
        valid_time = obs.get("valid_time_gmt")
        temp = obs.get("temp")
        dt_local = datetime.datetime.fromtimestamp(valid_time, tz)
        print(f"  Local Time: {dt_local.strftime('%Y-%m-%d %H:%M:%S')} | Temp: {temp}°C")

if __name__ == '__main__':
    get_history()
