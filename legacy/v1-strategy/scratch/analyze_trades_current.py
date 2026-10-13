import sqlite3
import os

DB_PATH = "storage/arbitrage.db"

def analyze():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Overall stats
    cursor.execute("""
        SELECT status, COUNT(*), SUM(stake_usdc), SUM(realized_pnl) 
        FROM trades 
        GROUP BY status
    """)
    rows = cursor.fetchall()
    print("=== OVERALL STATS ===")
    total_stake = 0
    for row in rows:
        print(f"Status: {row[0]:<10} | Count: {row[1]:<5} | Sum Stake: {row[2]:<10.2f} | Sum PnL: {row[3]:<10.2f}")
        total_stake += row[2]
    print(f"Total Stake (All Trades): {total_stake:.2f}")
        
    # 2. Win rate
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
    
    # 3. Group by market_id to see where the losses are coming from (top 15 worst)
    cursor.execute("""
        SELECT market_id, COUNT(*), SUM(stake_usdc), SUM(realized_pnl), 
               SUM(case when status='WON' then 1 else 0 end) as wins,
               SUM(case when status='LOST' then 1 else 0 end) as losses,
               SUM(case when status='PENDING' then 1 else 0 end) as pending
        FROM trades
        GROUP BY market_id
        ORDER BY SUM(realized_pnl) ASC
        LIMIT 20
    """)
    by_market = cursor.fetchall()
    print("\n=== TOP 20 LOSING MARKETS ===")
    for m in by_market:
        print(f"Market: {m[0][:60]:<60} | Count: {m[1]:<3} | Stake: {m[2]:<8.2f} | PnL: {m[3]:<8.2f} | W/L/P: {m[4]}/{m[5]}/{m[6]}")

    # 4. Show trades that were lost
    cursor.execute("""
        SELECT id, market_id, condition, trade_type, stake_usdc, ask_price, expected_value, real_prob, status, realized_pnl, settlement_date
        FROM trades
        WHERE status = 'LOST'
        ORDER BY stake_usdc DESC
        LIMIT 20
    """)
    lost_trades = cursor.fetchall()
    print("\n=== TOP 20 LARGEST LOST TRADES ===")
    for t in lost_trades:
        print(f"ID: {t[0]:<4} | Date: {t[10]} | Market: {t[1][:40]:<40} | Cond: {t[2]:<10} | Type: {t[3]:<3} | Stake: {t[4]:<6.2f} | Ask: {t[5]:<5.2f} | EV: {t[6]:<5.2f} | Prob: {t[7]:<5.2f} | PnL: {t[9]:.2f}")

    conn.close()

if __name__ == '__main__':
    analyze()
