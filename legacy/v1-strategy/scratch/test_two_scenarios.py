import os
import sys
import json
import sqlite3
import datetime
import pytz
import glob
from unittest.mock import patch
import numpy as np

# 将 src 目录加入 python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analyst import analyze_single_market, check_condition
from src.strategy import calculate_single_strategy
from src.config import CONFIG

DB_PATH = "storage/arbitrage.db"
CACHE_DB_PATH = "storage/weather_cache.db"
TEST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scratch", "backtest_temp_2")

def get_observed_extreme(station_id, is_lowest, date_str):
    conn = sqlite3.connect(CACHE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT obs_extreme FROM weather_daily_cache WHERE station_id=? AND is_lowest=? AND date=?",
        (station_id.upper(), 1 if is_lowest else 0, date_str)
    )
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def find_winning_condition(market_id, station_id, is_lowest, date_str, ranges):
    # 1. 尝试从 trades 表中寻找 WON 的 YES 合约
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT condition FROM trades WHERE market_id=? AND status='WON' AND trade_type='YES' LIMIT 1",
        (market_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]
        
    # 2. 备用：从 weather_daily_cache 中获取实况温度并匹配
    obs_temp = get_observed_extreme(station_id, is_lowest, date_str)
    if obs_temp is not None:
        for r in ranges:
            cond = r["condition"]
            if check_condition(obs_temp, cond):
                return cond
    return None

def find_closest_archive(market_id, trade_timestamp):
    archives = glob.glob(f"storage/archive/*_{market_id}.json")
    if not archives:
        return None
        
    closest_archive = None
    min_diff = float("inf")
    
    for a in archives:
        bn = os.path.basename(a)
        time_part = bn.split("_")[0] + "_" + bn.split("_")[1]
        try:
            dt = datetime.datetime.strptime(time_part, "%Y%m%d_%H%M%S")
            # 假设 archive 记录的时间是本地时间，将其转换为 timestamp
            archive_ts = dt.timestamp()
            diff = abs(archive_ts - trade_timestamp)
            if diff < min_diff:
                min_diff = diff
                closest_archive = a
        except Exception:
            continue
            
    # 如果时间偏差在一小时内，认为匹配成功
    if min_diff < 3600:
        return closest_archive
    return closest_archive # 如果没有更好的，仍然返回最接近的

def run_simulation_on_archive(archive_path, params, mock_time_str, timezone_str):
    os.makedirs(TEST_DIR, exist_ok=True)
    
    import src.analyst
    import src.strategy
    old_analyst_dir = src.analyst.PROTOCOLS_DIR
    old_strategy_dir = src.strategy.PROTOCOLS_DIR
    src.analyst.PROTOCOLS_DIR = TEST_DIR
    src.strategy.PROTOCOLS_DIR = TEST_DIR
    
    old_risk_config = dict(CONFIG.get("risk_control_lock", {}))
    CONFIG["risk_control_lock"] = dict(old_risk_config)
    for k, v in params.items():
        CONFIG["risk_control_lock"][k] = v

    with open(archive_path, "r", encoding="utf-8") as f:
        archive_data = json.load(f)
        
    raw_forecast = archive_data["raw_data"]["raw_forecast"]
    raw_observed = archive_data["raw_data"].get("raw_observed")
    market_snapshot = archive_data["raw_data"]["market_snapshot"]
    market_id = market_snapshot["market_id"]
    
    temp_snap_path = os.path.join(TEST_DIR, f"market_snapshot_{market_id}.json")
    with open(temp_snap_path, "w", encoding="utf-8") as f_snap:
        json.dump(market_snapshot, f_snap, indent=2, ensure_ascii=False)
        
    tz = pytz.timezone(timezone_str)
    # 解析 mock_time_str (YYYY-MM-DD HH:MM:SS) 为本地时区
    mock_dt = tz.localize(datetime.datetime.strptime(mock_time_str, "%Y-%m-%d %H:%M:%S"))
    
    class MockDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return mock_dt
            
    mock_positions = {"YES": {}, "NO": {}}

    try:
        with patch("src.weather_cache.get_api_cache", return_value=raw_forecast), \
             patch("src.weather_cache.fetch_wunderground_hourly_observed_today", return_value=raw_observed if isinstance(raw_observed, list) else [{"local_time": "2026-07-22 12:00:00", "temp": float(raw_observed), "hour": 12} if raw_observed else None]), \
             patch("src.strategy.get_current_holdings", return_value=mock_positions), \
             patch("src.analyst.datetime.datetime", MockDateTime):
             
            prob_filename = analyze_single_market(temp_snap_path)
            prob_path = os.path.join(TEST_DIR, prob_filename)
            sig_filename = calculate_single_strategy(temp_snap_path, prob_path)
            sig_path = os.path.join(TEST_DIR, sig_filename)
            
            with open(sig_path, "r", encoding="utf-8") as f_s:
                sig_output = json.load(f_s)
            
            return sig_output, market_snapshot
    except Exception as e:
        print(f"模拟运行出错 ({market_id}): {e}")
        return None, None
    finally:
        CONFIG["risk_control_lock"] = old_risk_config
        src.analyst.PROTOCOLS_DIR = old_analyst_dir
        src.strategy.PROTOCOLS_DIR = old_strategy_dir
        import shutil
        shutil.rmtree(TEST_DIR, ignore_errors=True)

def evaluate_pnl(sig_output, winning_cond, market_snapshot):
    """
    根据策略输出信号和实际获胜条件，计算模拟投注的 PnL。
    返回: (total_stake, total_payout, profit, wins, total_bets)
    """
    if not sig_output:
        return 0.0, 0.0, 0.0, 0, 0
        
    total_stake = 0.0
    total_payout = 0.0
    wins = 0
    total_bets = 0
    
    signals = sig_output.get("execution_signals", [])
    
    # 建立 range_id -> ask_price 映射
    range_prices = {r["range_id"]: r.get("ask_price", 0.5) for r in market_snapshot.get("ranges", [])}
    
    for sig in signals:
        action = sig["action"]
        stake = sig["recommended_stake_usdc"]
        cond = sig["condition"]
        range_id = sig["range_id"]
        
        if stake <= 0.0 or action not in ["BUY_YES", "BUY_NO"]:
            continue
            
        total_bets += 1
        price = range_prices.get(range_id, sig.get("market_ask", 0.5))
        if price <= 0:
            price = 0.01
            
        shares = stake / price
        total_stake += stake
        
        # 判断胜负
        is_yes = (action == "BUY_YES")
        is_winning_cond = (cond == winning_cond)
        
        # YES 合约：如果是 winning condition，则胜；否则负
        # NO 合约：如果不是 winning condition，则胜；否则负
        won = (is_yes and is_winning_cond) or (not is_yes and not is_winning_cond)
        
        if won:
            total_payout += shares # 结算为 1 USDC 每一股
            wins += 1
            
    profit = total_payout - total_stake
    return total_stake, total_payout, profit, wins, total_bets

def get_timezone_for_station(station_id):
    # 简单映射
    timezone_map = {
        "RKSI": "Asia/Seoul",
        "KNYC": "America/New_York",
        "EGLL": "Europe/London",
        "RJTT": "Asia/Tokyo",
        "VHHH": "Asia/Hong_Kong",
        "ZSSS": "Asia/Shanghai",
        "ZBAA": "Asia/Shanghai",
        "ZGGG": "Asia/Shanghai",
        "ZHHH": "Asia/Shanghai",
        "ZSQD": "Asia/Shanghai",
        "RCTP": "Asia/Taipei",
        "RCSS": "Asia/Taipei",
        "EHAM": "Europe/Amsterdam",
        "LFPG": "Europe/Paris",
        "LFPO": "Europe/Paris",
        "EDDM": "Europe/Berlin",
        "LEMD": "Europe/Madrid",
        "LIMC": "Europe/Rome",
        "EPWA": "Europe/Warsaw",
        "EFHK": "Europe/Helsinki",
        "FACT": "Africa/Johannesburg",
        "SAEZ": "America/Argentina/Buenos_Aires",
        "SBGR": "America/Sao_Paulo",
        "MPTO": "America/Panama",
        "MMMX": "America/Mexico_City",
        "CYYZ": "America/Toronto",
        "NZWN": "Pacific/Auckland",
        "WSSS": "Asia/Singapore",
        "WMKK": "Asia/Kuala_Lumpur",
        "RPLL": "Asia/Manila",
        "OPKC": "Asia/Karachi",
        "ATLA": "America/New_York",
        "HOUS": "America/Chicago",
        "CHIC": "America/Chicago",
        "AUST": "America/Chicago",
        "DENV": "America/Denver",
        "AURO": "America/Denver",
        "MIAI": "America/New_York",
        "MIAM": "America/New_York",
        "SEAT": "America/Los_Angeles",
        "DALL": "America/Chicago"
    }
    return timezone_map.get(station_id.upper(), "UTC")

def main():
    original_params = {
        "obs_error_sigma_0": 0.6,
        "bias_window_days": 7,
        "obs_error_sigma_baseline_mid_lat": 1.2,
        "obs_error_sigma_baseline_tropics": 0.8
    }
    
    calibrated_params = {
        "obs_error_sigma_0": 1.2183,
        "bias_window_days": 6,
        "obs_error_sigma_baseline_mid_lat": 0.4899,
        "obs_error_sigma_baseline_tropics": 0.7673
    }

    # 1. 查询 2026-07-21 结算市场的交易时间
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT market_id, timestamp, datetime(timestamp, 'unixepoch'), station_id
        FROM trades 
        WHERE settlement_date='2026-07-21'
        ORDER BY timestamp ASC
    """)
    trade_cycles = cursor.fetchall()
    conn.close()
    
    print(f"[*] 共获取到 2026-07-21 结算事件的 {len(trade_cycles)} 次系统实际下注记录。")
    
    scenario_1_orig = {"stake": 0, "payout": 0, "profit": 0, "wins": 0, "bets": 0}
    scenario_1_cal = {"stake": 0, "payout": 0, "profit": 0, "wins": 0, "bets": 0}
    
    scenario_2_orig = {"stake": 0, "payout": 0, "profit": 0, "wins": 0, "bets": 0}
    scenario_2_cal = {"stake": 0, "payout": 0, "profit": 0, "wins": 0, "bets": 0}
    
    s1_count = 0
    s2_count = 0

    for market_id, ts, time_str, station_id in trade_cycles:
        # 分流场景
        # 场景一 (远期)：下注发生在 7月20日 (即 ts 对应 7月20日)
        # 场景二 (临场/当天)：下注发生在 7月21日 (即 ts 对应 7月21日)
        is_scenario_2 = time_str.startswith("2026-07-21")
        
        archive_path = find_closest_archive(market_id, ts)
        if not archive_path:
            continue
            
        timezone_str = get_timezone_for_station(station_id)
        
        # 运行原配置模拟
        sig_orig, snapshot = run_simulation_on_archive(archive_path, original_params, time_str, timezone_str)
        # 运行新标定参数模拟
        sig_cal, _ = run_simulation_on_archive(archive_path, calibrated_params, time_str, timezone_str)
        
        if not sig_orig or not sig_cal or not snapshot:
            continue
            
        # 确定该市场的获胜条件
        is_lowest = "lowest" in market_id.lower()
        winning_cond = find_winning_condition(market_id, station_id, is_lowest, "2026-07-21", snapshot.get("ranges", []))
        
        if not winning_cond:
            # 尝试通过 archive 的 realized_pnl 反推
            continue

        # 评估 PnL
        st_o, pay_o, prof_o, w_o, b_o = evaluate_pnl(sig_orig, winning_cond, snapshot)
        st_c, pay_c, prof_c, w_c, b_c = evaluate_pnl(sig_cal, winning_cond, snapshot)
        
        if is_scenario_2:
            s2_count += 1
            scenario_2_orig["stake"] += st_o
            scenario_2_orig["payout"] += pay_o
            scenario_2_orig["profit"] += prof_o
            scenario_2_orig["wins"] += w_o
            scenario_2_orig["bets"] += b_o
            
            scenario_2_cal["stake"] += st_c
            scenario_2_cal["payout"] += pay_c
            scenario_2_cal["profit"] += prof_c
            scenario_2_cal["wins"] += w_c
            scenario_2_cal["bets"] += b_c
        else:
            s1_count += 1
            scenario_1_orig["stake"] += st_o
            scenario_1_orig["payout"] += pay_o
            scenario_1_orig["profit"] += prof_o
            scenario_1_orig["wins"] += w_o
            scenario_1_orig["bets"] += b_o
            
            scenario_1_cal["stake"] += st_c
            scenario_1_cal["payout"] += pay_c
            scenario_1_cal["profit"] += prof_c
            scenario_1_cal["wins"] += w_c
            scenario_1_cal["bets"] += b_c

    print("\n" + "=" * 80)
    print("               🏁 历史交易场景对比测试结果 (2026-07-21 结算日)")
    print("=" * 80)
    
    print(f"\n📈 场景一：在 7月20日 (远期建仓，共 {s1_count} 个交易决策点)")
    print("-" * 80)
    print(f"配置模型     | {'下注总额':^12} | {'结算回款':^12} | {'净利润 (USDC)':^15} | {'胜率 / 总单':^15} | {'投资回报率(ROI)':^12}")
    print("-" * 80)
    
    roi_orig_s1 = (scenario_1_orig["profit"] / scenario_1_orig["stake"] * 100) if scenario_1_orig["stake"] > 0 else 0
    win_rate_orig_s1 = (scenario_1_orig["wins"] / scenario_1_orig["bets"] * 100) if scenario_1_orig["bets"] > 0 else 0
    print(f"原配置 (1.2°C) | {scenario_1_orig['stake']:10.2f} | {scenario_1_orig['payout']:10.2f} | {scenario_1_orig['profit']:+13.2f} | {scenario_1_orig['wins']:2d}/{scenario_1_orig['bets']:2d} ({win_rate_orig_s1:5.1f}%) | {roi_orig_s1:9.2f}%")
    
    roi_cal_s1 = (scenario_1_cal["profit"] / scenario_1_cal["stake"] * 100) if scenario_1_cal["stake"] > 0 else 0
    win_rate_cal_s1 = (scenario_1_cal["wins"] / scenario_1_cal["bets"] * 100) if scenario_1_cal["bets"] > 0 else 0
    print(f"新标定 (0.49°C) | {scenario_1_cal['stake']:10.2f} | {scenario_1_cal['payout']:10.2f} | {scenario_1_cal['profit']:+13.2f} | {scenario_1_cal['wins']:2d}/{scenario_1_cal['bets']:2d} ({win_rate_cal_s1:5.1f}%) | {roi_cal_s1:9.2f}%")
    
    print(f"\n📈 场景二：在 7月21日 (结算日当天临盘，共 {s2_count} 个交易决策点)")
    print("-" * 80)
    print(f"配置模型     | {'下注总额':^12} | {'结算回款':^12} | {'净利润 (USDC)':^15} | {'胜率 / 总单':^15} | {'投资回报率(ROI)':^12}")
    print("-" * 80)
    
    roi_orig_s2 = (scenario_1_orig["profit"] / scenario_1_orig["stake"] * 100) if scenario_1_orig["stake"] > 0 else 0 # 避免除零
    roi_orig_s2_act = (scenario_2_orig["profit"] / scenario_2_orig["stake"] * 100) if scenario_2_orig["stake"] > 0 else 0
    win_rate_orig_s2 = (scenario_2_orig["wins"] / scenario_2_orig["bets"] * 100) if scenario_2_orig["bets"] > 0 else 0
    print(f"原配置 (1.2°C) | {scenario_2_orig['stake']:10.2f} | {scenario_2_orig['payout']:10.2f} | {scenario_2_orig['profit']:+13.2f} | {scenario_2_orig['wins']:2d}/{scenario_2_orig['bets']:2d} ({win_rate_orig_s2:5.1f}%) | {roi_orig_s2_act:9.2f}%")
    
    roi_cal_s2 = (scenario_2_cal["profit"] / scenario_2_cal["stake"] * 100) if scenario_2_cal["stake"] > 0 else 0
    win_rate_cal_s2 = (scenario_2_cal["wins"] / scenario_2_cal["bets"] * 100) if scenario_2_cal["bets"] > 0 else 0
    print(f"新标定 (0.49°C) | {scenario_2_cal['stake']:10.2f} | {scenario_2_cal['payout']:10.2f} | {scenario_2_cal['profit']:+13.2f} | {scenario_2_cal['wins']:2d}/{scenario_2_cal['bets']:2d} ({win_rate_cal_s2:5.1f}%) | {roi_cal_s2:9.2f}%")
    print("=" * 80)

if __name__ == "__main__":
    main()
