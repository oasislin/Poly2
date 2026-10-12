import os
import sys

# Add project root to python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.weather_cache as weather_cache
from src.bias_corrector import get_bias_corrector

def test_integration():
    station_id = "ZSSS" # Shanghai Hongqiao Airport
    timezone = "Asia/Shanghai"
    
    print("=== Test 1: Fetch Wunderground Daily History ===")
    daily_history = weather_cache.fetch_wunderground_daily_history(station_id)
    print(f"Fetched {len(daily_history)} days of Wunderground history.")
    # Print first 5 dates
    dates = sorted(list(daily_history.keys()))
    for d in dates[:5]:
        print(f"  Date: {d} | Max: {daily_history[d]['max_temp']}°C | Min: {daily_history[d]['min_temp']}°C")
        
    print("\n=== Test 2: Fetch Wunderground Observed Today ===")
    observed_max = weather_cache.fetch_wunderground_observed_today(station_id, False, timezone)
    observed_min = weather_cache.fetch_wunderground_observed_today(station_id, True, timezone)
    print(f"Observed Max Today: {observed_max}°C")
    print(f"Observed Min Today: {observed_min}°C")
    
    print("\n=== Test 3: Run Bias Corrector ===")
    corrector = get_bias_corrector("MovingWindowBiasCorrector")
    # ZSSS coordinates
    lat, lon = 31.198, 121.336
    # Target date: today
    import datetime
    import pytz
    tz = pytz.timezone(timezone)
    today_str = datetime.datetime.now(tz).strftime("%Y-%m-%d")
    
    print(f"Target Date: {today_str} | Station: {station_id} | lowest=False")
    bias, std = corrector.get_bias(
        station_id=station_id,
        lat=lat,
        lon=lon,
        timezone=timezone,
        target_date=today_str,
        is_lowest=False,
        window_days=7
    )
    print(f"Result -> Bias: {bias:+.3f}°C | StdDev: {std}")

if __name__ == "__main__":
    test_integration()
