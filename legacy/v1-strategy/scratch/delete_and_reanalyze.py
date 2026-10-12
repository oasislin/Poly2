import sqlite3
import os

DB_PATH = "storage/arbitrage.db"
BACKUP_PATH = "storage/arbitrage_backup_before_delete_100.db"

def reanalyze():
    if not os.path.exists(DB_PATH):
        print("Database not found")
        return
        
    # Backup database
    if not os.path.exists(BACKUP_PATH):
        import shutil
        shutil.copyfile(DB_PATH, BACKUP_PATH)
        print(f"Backed up database to {BACKUP_PATH}")
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Delete ID 438 and 442
    cursor.execute("DELETE FROM trades WHERE id IN (438, 442)")
    conn.commit()
    print("Deleted trades with ID 438 and 442")
    
    # 2. Overall stats
    cursor.execute("""
        SELECT status, COUNT(*), SUM(stake_usdc), SUM(realized_pnl) 
        FROM trades 
        GROUP BY status
    """)
    rows = cursor.fetchall()
    print("\n=== NEW OVERALL STATS ===")
    total_stake = 0
    for row in rows:
        print(f"Status: {row[0]:<10} | Count: {row[1]:<5} | Sum Stake: {row[2]:<10.2f} | Sum PnL: {row[3]:<10.2f}")
        total_stake += row[2]
    print(f"Total Stake (All Trades): {total_stake:.2f}")
    
    # 3. New win rate
    cursor.execute("""
        SELECT COUNT(*) FROM trades WHERE status = 'WON'
    """)
    won = cursor.fetchone()[0]
    cursor.execute("""
        SELECT COUNT(*) FROM trades WHERE status = 'LOST'
    """)
    lost = cursor.fetchone()[0]
    total_settled = won + lost
    win_rate = won / total_settled if total_settled > 0 else 0
    print(f"Total Settled: {total_settled}")
    print(f"Win Rate (settled): {win_rate:.2%}")
    
    # 4. Group by market_id to see where the losses are coming from (top 15 worst)
    cursor.execute("""
        SELECT market_id, COUNT(*), SUM(stake_usdc), SUM(realized_pnl), 
               SUM(case when status='WON' then 1 else 0 end) as wins,
               SUM(case when status='LOST' then 1 else 0 end) as losses,
               SUM(case when status='PENDING' then 1 else 0 end) as pending
        FROM trades
        GROUP BY market_id
        ORDER BY SUM(realized_pnl) ASC
        LIMIT 15
    """)
    by_market = cursor.fetchall()
    print("\n=== TOP 15 LOSING MARKETS ===")
    for m in by_market:
        print(f"Market: {m[0][:60]:<60} | Count: {m[1]:<3} | Stake: {m[2]:<8.2f} | PnL: {m[3]:<8.2f} | W/L/P: {m[4]}/{m[5]}/{m[6]}")

    # 5. List largest lost trades
    cursor.execute("""
        SELECT id, market_id, condition, trade_type, stake_usdc, ask_price, expected_value, real_prob, status, realized_pnl, settlement_date, station_id
        FROM trades
        WHERE status = 'LOST'
        ORDER BY stake_usdc DESC
        LIMIT 25
    """)
    losses = cursor.fetchall()
    
    CACHE_PATH = "storage/weather_cache.db"
    conn_cache = sqlite3.connect(CACHE_PATH) if os.path.exists(CACHE_PATH) else None
    
    print("\n=== TOP 25 LARGEST LOST TRADES (REMAINING) ===")
    for row in losses:
        trade_id, market_id, condition, trade_type, stake, ask_price, ev, real_prob, status, pnl, settlement_date, station_id = row
        
        # Get actual value from weather cache
        actual_temp = None
        source = "Unknown"
        is_lowest = 1 if ("lowest" in market_id.lower() or "lowest" in condition.lower()) else 0
        
        if conn_cache:
            c_cache = conn_cache.cursor()
            try:
                c_cache.execute("SELECT obs_extreme FROM weather_daily_cache WHERE station_id = ? AND date = ? AND is_lowest = ?", (station_id, settlement_date, is_lowest))
                res = c_cache.fetchone()
                if res:
                    actual_temp = res[0]
                    source = "daily_cache"
            except Exception:
                pass
                
        print(f"ID: {trade_id:<4} | Date: {settlement_date} | Market: {market_id[:35]:<35} | Cond: {condition:<6} | Type: {trade_type:<3} | Stake: {stake:<6.2f} | Price: {ask_price:<5.2f} | EV: {ev:<5.2f} | Prob: {real_prob:<5.2f} | Actual: {actual_temp} (lowest={is_lowest})")

    if conn_cache:
        conn_cache.close()
    conn.close()

if __name__ == '__main__':
    reanalyze()
