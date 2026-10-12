import sqlite3
import os

DB_PATH = "storage/arbitrage.db"

def find_collapses():
    if not os.path.exists(DB_PATH):
        print("Database not found")
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Query all LOST trades where real_prob >= 0.80
    cursor.execute("""
        SELECT id, market_id, condition, trade_type, stake_usdc, ask_price, expected_value, real_prob, status, realized_pnl, settlement_date, station_id
        FROM trades
        WHERE status = 'LOST' AND real_prob >= 0.80
        ORDER BY real_prob DESC
    """)
    rows = cursor.fetchall()
    print(f"=== LOST TRADES WITH real_prob >= 0.80 (Count: {len(rows)}) ===")
    for r in rows:
        print(f"ID: {r[0]:<4} | Date: {r[10]} | Market: {r[1][:40]:<40} | Cond: {r[2]:<8} | Type: {r[3]:<3} | Stake: {r[4]:<6.2f} | Price: {r[5]:<5.2f} | Prob: {r[7]:<5.2f} | PnL: {r[9]:.2f}")
        
    # Query all WON trades where real_prob >= 0.80
    cursor.execute("""
        SELECT id, market_id, condition, trade_type, stake_usdc, ask_price, expected_value, real_prob, status, realized_pnl, settlement_date, station_id
        FROM trades
        WHERE status = 'WON' AND real_prob >= 0.80
        ORDER BY real_prob DESC
    """)
    rows_won = cursor.fetchall()
    print(f"\n=== WON TRADES WITH real_prob >= 0.80 (Count: {len(rows_won)}) ===")
    for r in rows_won:
        print(f"ID: {r[0]:<4} | Date: {r[10]} | Market: {r[1][:40]:<40} | Cond: {r[2]:<8} | Type: {r[3]:<3} | Stake: {r[4]:<6.2f} | Price: {r[5]:<5.2f} | Prob: {r[7]:<5.2f} | PnL: {r[9]:.2f}")
        
    conn.close()

if __name__ == '__main__':
    find_collapses()
