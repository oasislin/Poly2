import sqlite3
import os

DB_PATH = "storage/arbitrage.db"

def inspect_tokyo():
    if not os.path.exists(DB_PATH):
        print("Database not found")
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, condition, trade_type, stake_usdc, ask_price, expected_value, real_prob, status, realized_pnl, datetime(timestamp, 'unixepoch', 'localtime')
        FROM trades
        WHERE market_id = 'lowest-temperature-in-tokyo-on-july-19-2026'
        ORDER BY timestamp
    """)
    rows = cursor.fetchall()
    print("=== TOKYO JULY 19 TRADES ===")
    for r in rows:
        print(f"ID: {r[0]:<4} | Cond: {r[1]:<10} | Type: {r[2]:<3} | Stake: {r[3]:<6.2f} | Price: {r[4]:<5.2f} | EV: {r[5]:<5.2f} | Prob: {r[6]:<5.2f} | Status: {r[7]:<6} | PnL: {r[8]:.2f} | Time: {r[9]}")
        
    conn.close()

if __name__ == '__main__':
    inspect_tokyo()
