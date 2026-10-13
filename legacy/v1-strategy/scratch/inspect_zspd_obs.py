import sqlite3
import json
import os

DB_PATH = "storage/weather_cache.db"

def inspect():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Search for ZSPD hourly api cache
    c.execute("SELECT params, response_json, updated_at FROM open_meteo_api_cache WHERE url LIKE '%conditions/historical/hourly/1day%' AND params LIKE '%ZSPD%'")
    rows = c.fetchall()
    print("Found ZSPD rows:", len(rows))
    for r in rows:
        params = json.loads(r[0])
        response = json.loads(r[1])
        updated_at = r[2]
        import datetime
        print("Updated at:", datetime.datetime.fromtimestamp(updated_at))
        times = response.get("validTimeLocal", [])
        temps = response.get("temperature", [])
        print("Total observations:", len(times))
        for t, temp in zip(times, temps):
            print(f"  {t} : {temp}")
            
    conn.close()

if __name__ == '__main__':
    inspect()
