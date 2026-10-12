import sqlite3
import os

DB_PATH = "storage/weather_cache.db"

def inspect():
    if not os.path.exists(DB_PATH):
        print("Database not found")
        return
        
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = c.fetchall()
    print("Tables:", tables)
    
    for t in tables:
        t_name = t[0]
        print(f"\n=== Table {t_name} schema ===")
        c.execute(f"PRAGMA table_info({t_name})")
        print(c.fetchall())
        
        c.execute(f"SELECT COUNT(*) FROM {t_name}")
        count = c.fetchone()[0]
        print(f"Row count: {count}")
        
        c.execute(f"SELECT * FROM {t_name} LIMIT 10")
        rows = c.fetchall()
        print(f"Sample 10 rows:")
        for r in rows:
            print(r)
            
    conn.close()

if __name__ == '__main__':
    inspect()
