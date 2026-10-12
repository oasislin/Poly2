import sqlite3
import os

DB_PATH = "storage/arbitrage.db"
CACHE_PATH = "storage/weather_cache.db"

def inspect_losses():
    if not os.path.exists(DB_PATH):
        print("Database not found")
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Let's get the detailed information of the 25 largest losses.
    cursor.execute("""
        SELECT id, market_id, condition, trade_type, stake_usdc, ask_price, expected_value, real_prob, status, realized_pnl, settlement_date, station_id
        FROM trades
        WHERE status = 'LOST'
        ORDER BY stake_usdc DESC
        LIMIT 25
    """)
    losses = cursor.fetchall()
    
    conn_cache = sqlite3.connect(CACHE_PATH) if os.path.exists(CACHE_PATH) else None
    
    print("=== ANALYSIS OF LARGEST LOST TRADES ===")
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
            except Exception as e:
                print(f"Cache query error for trade {trade_id}:", e)
                pass
                
        print(f"\nTrade ID: {trade_id}")
        print(f"  Market: {market_id}")
        print(f"  Station: {station_id} | Date: {settlement_date}")
        print(f"  Condition: {condition} | Type: {trade_type} | Stake: {stake:.2f} | Ask: {ask_price:.2f}")
        print(f"  Algorithmic Prob: {real_prob:.2f} | Expected EV: {ev:.2f}")
        print(f"  Actual Temp (from cache): {actual_temp} (source: {source}, IsLowest: {is_lowest})")
        
        if actual_temp is not None:
            # check if US station or condition is Fahrenheit
            is_fahrenheit = False
            if station_id.upper() in ["KNYC", "ATLA", "HOUS", "CHIC", "AUST", "DENV", "MIAI", "MIAM", "SEAT", "DALL"] or station_id.upper().startswith("K"):
                is_fahrenheit = True
            
            actual_calibrated = None
            if is_fahrenheit:
                import math
                actual_calibrated = int(math.floor(actual_temp * 9.0 / 5.0 + 32.0))
                print(f"  Actual calibrated (Fahrenheit): {actual_calibrated}°F")
            else:
                actual_calibrated = round(actual_temp)
                print(f"  Actual calibrated (Celsius): {actual_calibrated}°C")
                
    if conn_cache:
        conn_cache.close()
    conn.close()

if __name__ == '__main__':
    inspect_losses()
