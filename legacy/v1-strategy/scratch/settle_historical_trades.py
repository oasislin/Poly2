import os
import sqlite3
import datetime
import requests
import sys

# Add project root to python path to use imports if needed
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analyst import resolve_station_coordinates, check_condition
from src.config import PROXIES, setup_logger

logger = setup_logger("HistoricalSettlement")

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage", "arbitrage.db")

def settle_trades():
    if not os.path.exists(DB_PATH):
        print(f"Database {DB_PATH} not found!")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get all pending trades
    cursor.execute("SELECT id, market_id, station_id, condition, stake_usdc, ask_price, settlement_date, trade_type FROM trades WHERE status = 'PENDING'")
    pending_trades = cursor.fetchall()

    if not pending_trades:
        print("No pending trades found!")
        conn.close()
        return

    print(f"Found {len(pending_trades)} pending trades. Starting historical settlement...")

    timezone_map = {
        "RKSI": "Asia/Seoul",
        "KNYC": "America/New_York",
        "EGLL": "Europe/London",
        "RJTT": "Asia/Tokyo",
        "VHHH": "Asia/Hong_Kong",
        "ZSSS": "Asia/Shanghai",
        "DALL": "America/Chicago"
    }

    for trade_id, m_id, station_id, condition, stake_usdc, ask_price, settlement_date, trade_type in pending_trades:
        print(f"\nProcessing Trade ID: {trade_id} | Market: {m_id} | Station: {station_id} | Date: {settlement_date} | Type: {trade_type}")
        try:
            lat, lon = resolve_station_coordinates(station_id)
            print(f"Resolved Coordinates: lat={lat}, lon={lon}")

            # Use Open-Meteo Archive API for historical data
            url = "https://archive-api.open-meteo.com/v1/archive"
            params = {
                "latitude": lat,
                "longitude": lon,
                "start_date": settlement_date,
                "end_date": settlement_date,
                "hourly": "temperature_2m",
                "timezone": timezone_map.get(station_id.upper(), "UTC")
            }

            print(f"Querying Open-Meteo Archive API with params: {params}")
            response = requests.get(url, params=params, proxies=PROXIES, timeout=15)
            if response.status_code != 200:
                print(f"Error fetching data: {response.status_code} - {response.text}")
                continue

            data = response.json()
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])
            temps = hourly.get("temperature_2m", [])

            # Filter temperatures for the target date (in local time as returned by the API)
            day_indices = [idx for idx, t_str in enumerate(times) if t_str.startswith(settlement_date)]
            if not day_indices:
                print(f"No temperature data found for date {settlement_date}")
                continue

            day_temps = [temps[idx] for idx in day_indices if temps[idx] is not None]
            if not day_temps:
                print(f"No valid temperature values found for date {settlement_date}")
                continue

            actual_max_temp = max(day_temps)
            # Weather station resolution: round to integer Celsius
            actual_calibrated_temp = round(actual_max_temp)

            is_yes_win = check_condition(actual_calibrated_temp, condition)
            is_win = is_yes_win if trade_type.upper() == 'YES' else (not is_yes_win)

            status = 'WON' if is_win else 'LOST'
            if is_win:
                pnl = round(stake_usdc * (1.0 / ask_price - 1.0), 2)
            else:
                pnl = -stake_usdc

            print(f"Actual Max Temp: {actual_max_temp}°C (calibrated: {actual_calibrated_temp}°C)")
            print(f"Condition '{condition}' matches: {is_yes_win} | Trade Win: {is_win}")
            print(f"Outcome: {status} | PnL: {pnl} USDC")

            cursor.execute(
                "UPDATE trades SET status = ?, realized_pnl = ? WHERE id = ?",
                (status, pnl, trade_id)
            )
            conn.commit()
            print(f"Updated Trade ID {trade_id} successfully.")

        except Exception as e:
            print(f"Exception settling trade {trade_id}: {str(e)}")

    # Print final summary
    print("\n=== Final Settle Summary ===")
    cursor.execute("SELECT COUNT(*), SUM(stake_usdc), SUM(realized_pnl) FROM trades")
    total_count, total_stake, total_pnl = cursor.fetchone()
    
    cursor.execute("SELECT status, COUNT(*), SUM(realized_pnl) FROM trades GROUP BY status")
    status_stats = cursor.fetchall()
    
    print(f"Total Trades: {total_count}")
    print(f"Total Stake: {total_stake:.2f} USDC")
    print(f"Total Realized PnL: {total_pnl:.2f} USDC")
    for status, count, pnl in status_stats:
        pnl_val = pnl if pnl is not None else 0.0
        print(f" - {status}: {count} trades, PnL: {pnl_val:.2f} USDC")

    conn.close()

if __name__ == "__main__":
    settle_trades()
