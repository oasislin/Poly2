import requests
import json
import datetime
import pytz

def get_history():
    url = "https://api.weather.com/v1/location/RPLL:9:PH/observations/historical.json"
    params = {
        "apiKey": "e1f10a1e78da46f5b10a1e78da96f525",
        "units": "m",
        "startDate": "20260719",
        "endDate": "20260719"
    }
    r = requests.get(url, params=params, timeout=15)
    if r.status_code == 200:
        data = r.json()
        observations = data.get("observations", [])
        print(f"Total observations: {len(observations)}")
        tz = pytz.timezone("Asia/Manila")
        max_t = -99.0
        for obs in observations:
            valid_time = obs.get("valid_time_gmt")
            temp = obs.get("temp")
            dt_local = datetime.datetime.fromtimestamp(valid_time, tz)
            print(f"  Local Time: {dt_local.strftime('%Y-%m-%d %H:%M:%S')} | Temp: {temp}°C")
            if temp is not None:
                max_t = max(max_t, temp)
        print("Max Temp:", max_t)
    else:
        print("Failed to fetch:", r.status_code, r.text)

if __name__ == '__main__':
    get_history()
