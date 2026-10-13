import json

path = "storage/archive/20260718_203134_lowest-temperature-in-shanghai-on-july-18-2026.json"

with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

raw_obs = data.get("raw_data", {}).get("raw_observed")
print("Raw Observed Value:", raw_obs)

raw_forecast = data.get("raw_data", {}).get("raw_forecast")
print("Raw Forecast keys:", list(raw_forecast.keys()) if isinstance(raw_forecast, dict) else type(raw_forecast))
if isinstance(raw_forecast, dict):
    # Print keys other than open_meteo_response
    for k, v in raw_forecast.items():
        if k != '_raw_open_meteo_response':
            print(f"  {k} : {v}")
