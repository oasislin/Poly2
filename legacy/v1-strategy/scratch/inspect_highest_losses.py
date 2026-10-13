import sqlite3
import os

DB_PATH = "storage/arbitrage.db"

def inspect_highest():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Let's inspect ID 639 and 572
    c.execute("SELECT *, datetime(timestamp, 'unixepoch', 'localtime') FROM trades WHERE id IN (639, 572)")
    rows = c.fetchall()
    print("=== HIGHEST TEMP LOST TRADES DETAILS ===")
    for r in rows:
        print(f"ID: {r[0]} | Market: {r[2]} | Cond: {r[5]} | Type: {r[14]} | Stake: {r[6]} | Price: {r[7]} | EV: {r[8]} | Prob: {r[9]} | Status: {r[10]} | PnL: {r[13]} | Time: {r[15]} | Station: {r[4]}")
        
    conn.close()

if __name__ == '__main__':
    inspect_highest()
