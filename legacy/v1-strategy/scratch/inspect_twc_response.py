import sqlite3
import json
import os

DB_PATH = "storage/weather_cache.db"

def inspect():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT params, response_json FROM open_meteo_api_cache WHERE url LIKE '%weather.com%conditions/historical/hourly/1day%'")
    rows = c.fetchall()
    print("Found rows:", len(rows))
    for r in rows:
        params = json.loads(r[0])
        response = json.loads(r[1])
        print("Params:", params)
        times = response.get("validTimeLocal", [])
        temps = response.get("temperature", [])
        print("Time sample:", times[:5])
        print("Temp sample:", temps[:5])
        # print first 5 items zipped
        for t, temp in list(zip(times, temps))[:10]:
            print(f"  {t} : {temp}")
            
    conn.close()

if __name__ == '__main__':
    inspect()
