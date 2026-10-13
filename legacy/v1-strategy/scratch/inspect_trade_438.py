import sqlite3
import os

DB_PATH = "storage/arbitrage.db"

def inspect_trade():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT *, datetime(timestamp, 'unixepoch', 'localtime') FROM trades WHERE id = 438")
    print(c.fetchone())
    conn.close()

if __name__ == '__main__':
    inspect_trade()
