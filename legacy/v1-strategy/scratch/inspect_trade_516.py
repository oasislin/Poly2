import sqlite3
import os

DB_PATH = "storage/arbitrage.db"

def check_516():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT *, datetime(timestamp, 'unixepoch', 'localtime') FROM trades WHERE id = 516")
    print(c.fetchone())
    conn.close()

if __name__ == '__main__':
    check_516()
