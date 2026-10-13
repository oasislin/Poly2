import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage", "arbitrage.db")

def reset_trades():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 将 7月14日上海最高温的两个订单重置为 PENDING 状态
    cursor.execute("""
        UPDATE trades 
        SET status = 'PENDING', realized_pnl = 0.0 
        WHERE market_id = 'highest-temperature-in-shanghai-on-july-14-2026'
    """)
    print(f"Reset {cursor.rowcount} trades successfully.")
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    reset_trades()
