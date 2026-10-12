import requests
import datetime
from src.analyst import resolve_station_coordinates

def test_query():
    station_id = "ZSPD"
    lat, lon = resolve_station_coordinates(station_id)
    print(f"ZSPD coordinates: lat={lat}, lon={lon}")
    
    url = "https://api.open-meteo.com/v1/forecast"
    
    # 1. Query with UTC
    params_utc = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m",
        "past_days": 7,
        "forecast_days": 1,
        "timezone": "UTC"
    }
    r_utc = requests.get(url, params=params_utc)
    data_utc = r_utc.json()
    hourly_utc = data_utc.get("hourly", {})
    times_utc = hourly_utc.get("time", [])
    temps_utc = hourly_utc.get("temperature_2m", [])
    
    day_indices_utc = [idx for idx, t_str in enumerate(times_utc) if t_str.startswith("2026-07-14")]
    day_temps_utc = [temps_utc[idx] for idx in day_indices_utc if temps_utc[idx] is not None]
    
    print("\n--- UTC Query (Current logic) ---")
    print(f"Number of hourly readings for 2026-07-14 UTC: {len(day_temps_utc)}")
    print(f"Readings: {day_temps_utc}")
    if day_temps_utc:
        print(f"Max temp UTC: {max(day_temps_utc)}")
        print(f"Rounded max temp UTC: {round(max(day_temps_utc))}")
        
    # 2. Query with Asia/Shanghai
    params_sh = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m",
        "past_days": 7,
        "forecast_days": 1,
        "timezone": "Asia/Shanghai"
    }
    r_sh = requests.get(url, params=params_sh)
    data_sh = r_sh.json()
    hourly_sh = data_sh.get("hourly", {})
    times_sh = hourly_sh.get("time", [])
    temps_sh = hourly_sh.get("temperature_2m", [])
    
    day_indices_sh = [idx for idx, t_str in enumerate(times_sh) if t_str.startswith("2026-07-14")]
    day_temps_sh = [temps_sh[idx] for idx in day_indices_sh if temps_sh[idx] is not None]
    
    print("\n--- Asia/Shanghai Query ---")
    print(f"Number of hourly readings for 2026-07-14 Asia/Shanghai: {len(day_temps_sh)}")
    print(f"Readings: {day_temps_sh}")
    if day_temps_sh:
        print(f"Max temp Asia/Shanghai: {max(day_temps_sh)}")
        print(f"Rounded max temp Asia/Shanghai: {round(max(day_temps_sh))}")

if __name__ == "__main__":
    test_query()
