import sqlite3
import os

DB_PATH = "storage/weather_cache.db"

def check_cache():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM weather_daily_cache WHERE station_id='RJTT' AND date='2026-07-19'")
    print(c.fetchall())
    conn.close()

if __name__ == '__main__':
    check_cache()
