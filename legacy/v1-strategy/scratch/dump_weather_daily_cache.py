import sqlite3
import os

DB_PATH = "storage/weather_cache.db"

def dump_cache():
    if not os.path.exists(DB_PATH):
        print("Database not found")
        return
        
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Let's inspect the schema of weather_daily_cache
    c.execute("PRAGMA table_info(weather_daily_cache)")
    print("Schema:", c.fetchall())
    
    # Print some records
    c.execute("SELECT * FROM weather_daily_cache WHERE date IN ('2026-07-18', '2026-07-19') OR station_id IN ('ZSPD', 'RJTT') LIMIT 50")
    rows = c.fetchall()
    print("Rows found:", len(rows))
    for r in rows:
        print(r)
        
    conn.close()

if __name__ == '__main__':
    dump_cache()
