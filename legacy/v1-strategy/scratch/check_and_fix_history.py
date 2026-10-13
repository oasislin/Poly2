import sqlite3
import os
import requests
import json
import re
import sys

# Add project root to python path to use imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analyst import check_condition
from src.config import PROXIES

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage", "arbitrage.db")

def parse_weather_condition(question_text):
    deg_match = re.search(r"(\d+)(?:\s*(?:°C|°F|°|C|F|degrees))", question_text, re.IGNORECASE)
    if not deg_match:
        return None
    val = deg_match.group(1)
    q_lower = question_text.lower()
    if "or below" in q_lower or "under" in q_lower or "less than" in q_lower:
        return f"<={val}"
    elif "or higher" in q_lower or "or above" in q_lower or "at least" in q_lower:
        return f">={val}"
    elif "between" in q_lower or " to " in q_lower:
        nums = re.findall(r"(\d+)", question_text)
        between_idx = q_lower.find("between")
        if between_idx != -1:
            nums_after = re.findall(r"(\d+)", question_text[between_idx:])
            if len(nums_after) >= 2:
                return f"{nums_after[0]}-{nums_after[1]}"
        if len(nums) >= 2:
            return f"{nums[0]}-{nums[1]}"
        return val
    else:
        return val

def check_and_fix_history():
    if not os.path.exists(DB_PATH):
        print(f"Database {DB_PATH} not found!")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 查找所有已结算的交易
    cursor.execute("""
        SELECT id, market_id, station_id, condition, stake_usdc, ask_price, status, realized_pnl, settlement_date, trade_type 
        FROM trades 
        WHERE status != 'PENDING'
    """)
    trades = cursor.fetchall()
    
    print(f"Total settled trades in history: {len(trades)}")
    print("-" * 80)
    
    mismatch_count = 0
    fixed_count = 0
    
    for t_id, m_id, station_id, condition, stake_usdc, ask_price, local_status, local_pnl, settlement_date, trade_type in trades:
        correct_status = None
        correct_pnl = None
        resolution_source = None
        actual_temp = None
        
        # 1. 优先尝试从 Polymarket 官方结算结果获取
        try:
            gamma_url = f"https://gamma-api.polymarket.com/events?slug={m_id}"
            res = requests.get(gamma_url, proxies=PROXIES, timeout=10)
            if res.status_code == 200:
                events = res.json()
                if events and isinstance(events, list):
                    event = events[0]
                    # 只有在事件官方 closed 时才采用官方结果
                    if event.get("closed") is True:
                        winning_condition = None
                        markets = event.get("markets", [])
                        for m in markets:
                            outcome_prices_str = m.get("outcomePrices")
                            if isinstance(outcome_prices_str, str):
                                try:
                                    prices = json.loads(outcome_prices_str)
                                except:
                                    prices = []
                            else:
                                prices = outcome_prices_str
                                
                            if prices and len(prices) >= 2:
                                if float(prices[0]) > 0.99:
                                    winning_condition = parse_weather_condition(m.get("question", ""))
                                    break
                                    
                        if winning_condition is not None:
                            is_yes_win = (condition == winning_condition)
                            is_win = is_yes_win if trade_type.upper() == 'YES' else (not is_yes_win)
                            correct_status = 'WON' if is_win else 'LOST'
                            resolution_source = f"Polymarket官方 (赢家档位: {winning_condition})"
        except Exception as e:
            print(f"Error fetching Gamma API for Trade ID {t_id}: {e}")
            
        # 2. 如果官方未关闭/无结果，回退至气象站观测数据计算
        if correct_status is None:
            is_lowest = "lowest" in m_id.lower() or "lowest" in condition.lower()
            from src.weather_cache import get_cached_stats, save_cached_stats, fetch_wunderground_daily_history, fetch_openmeteo_daily_history
            
            actual_obs = None
            # 读缓存
            try:
                cached_res = get_cached_stats(station_id, [settlement_date], is_lowest)
                if settlement_date in cached_res:
                    _, actual_obs = cached_res[settlement_date]
            except Exception as e:
                print(f"Error reading cache for Trade ID {t_id}: {e}")
                
            # 缓存未命中，尝试拉取 Wunderground
            if actual_obs is None:
                try:
                    wu_data = fetch_wunderground_daily_history(station_id)
                    day_wu = wu_data.get(settlement_date)
                    if day_wu:
                        actual_obs = day_wu["min_temp"] if is_lowest else day_wu["max_temp"]
                        if actual_obs is not None:
                            save_cached_stats(station_id, settlement_date, is_lowest, actual_obs, actual_obs)
                except Exception as e:
                    pass
                    
            # 尝试拉取 Open-Meteo
            if actual_obs is None:
                try:
                    om_data = fetch_openmeteo_daily_history(station_id)
                    day_om = om_data.get(settlement_date)
                    if day_om:
                        actual_obs = day_om["min_temp"] if is_lowest else day_om["max_temp"]
                        if actual_obs is not None:
                            save_cached_stats(station_id, settlement_date, is_lowest, actual_obs, actual_obs)
                except Exception as e:
                    pass
                    
            if actual_obs is not None:
                actual_temp = round(actual_obs)
                is_yes_win = check_condition(actual_temp, condition)
                is_win = is_yes_win if trade_type.upper() == 'YES' else (not is_yes_win)
                correct_status = 'WON' if is_win else 'LOST'
                resolution_source = f"气象数据结算 (站: {station_id}, 实测温: {actual_temp}°C, 类型: {'最低温' if is_lowest else '最高温'})"
            else:
                print(f"Trade ID {t_id} ({m_id}): 无法获取气象数据，跳过核对。")
                continue
                
        # 3. 计算正确的 PnL
        if correct_status == 'WON':
            correct_pnl = round(stake_usdc * (1.0 / ask_price - 1.0), 2)
        else:
            correct_pnl = -stake_usdc
            
        # 4. 对比并修正
        if local_status != correct_status or abs(local_pnl - correct_pnl) > 0.01:
            mismatch_count += 1
            print(f"发现不一致！交易ID {t_id} ({m_id}):")
            print(f"  核对来源: {resolution_source}")
            print(f"  投注详情: {trade_type} | 档位: {condition} | 本金: {stake_usdc} USDC | 价格: {ask_price}")
            print(f"  当前库状态: {local_status} (PnL: {local_pnl:+.2f} USDC)")
            print(f"  应有状态  : {correct_status} (PnL: {correct_pnl:+.2f} USDC)")
            
            # 执行订正
            cursor.execute("""
                UPDATE trades 
                SET status = ?, realized_pnl = ? 
                WHERE id = ?
            """, (correct_status, correct_pnl, t_id))
            fixed_count += 1
            print(f"  [已修正] 交易ID {t_id} 已在数据库中更新为 {correct_status} (PnL: {correct_pnl:+.2f} USDC)")
            print("-" * 80)
            
    conn.commit()
    conn.close()
    
    print(f"\n核对完毕。共发现 {mismatch_count} 处状态错误，成功修正 {fixed_count} 处。")

if __name__ == "__main__":
    check_and_fix_history()
