"""
================================================================================
🔥 冒烟测试：验证金融参数标定内存优化效果
================================================================================
测试目标：
 1. 使用 100 个场景、1组参数组合运行完整流程
 2. 监控内存使用情况
 3. 验证结果格式正确性
================================================================================
"""

import os
import sys
import json
import sqlite3
import datetime
import pytz
import glob
import shutil
import time
import psutil
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analyst import check_condition
from src.config import CONFIG

DB_PATH = os.path.join(PROJECT_ROOT, "storage", "arbitrage.db")
CACHE_DB_PATH = os.path.join(PROJECT_ROOT, "storage", "weather_cache.db")
TEST_DIR = os.path.join(PROJECT_ROOT, "scratch", "smoke_test")
PROB_CACHE_DIR = os.path.join(TEST_DIR, "prob_cache")

def get_memory_usage():
    """获取当前进程内存使用情况（MB）"""
    process = psutil.Process()
    return process.memory_info().rss / 1024 / 1024

def get_timezone_for_station(station_id):
    timezone_map = {
        "RKSI": "Asia/Seoul", "KNYC": "America/New_York", "EGLL": "Europe/London",
        "RJTT": "Asia/Tokyo", "VHHH": "Asia/Hong_Kong", "ZSSS": "Asia/Shanghai",
    }
    return timezone_map.get(station_id.upper(), "UTC")

def strip_prob_output(prob_output):
    """剥离无用大字段"""
    if prob_output is None:
        return None
    keep_keys = {"protocol_version", "timestamp", "market_id", "target_date", 
                 "ref_hour", "total_effective_members", "probability_distribution", 
                 "_raw_member_temps", "_simulated_sigma"}
    stripped = {k: v for k, v in prob_output.items() if k in keep_keys}
    return stripped

def run_analyst_on_archive(archive_path, s_mid, s_trop, mock_time_str, timezone_str):
    pid_dir = os.path.join(TEST_DIR, f"analyst_worker_{os.getpid()}")
    os.makedirs(pid_dir, exist_ok=True)
    
    import src.analyst
    old_analyst_dir = src.analyst.PROTOCOLS_DIR
    src.analyst.PROTOCOLS_DIR = pid_dir
    
    old_risk_config = dict(CONFIG.get("risk_control_lock", {}))
    CONFIG["risk_control_lock"] = dict(old_risk_config)
    CONFIG["risk_control_lock"]["obs_error_sigma_baseline_mid_lat"] = s_mid
    CONFIG["risk_control_lock"]["obs_error_sigma_baseline_tropics"] = s_trop

    try:
        with open(archive_path, "r", encoding="utf-8") as f:
            archive_data = json.load(f)
            
        raw_forecast = archive_data["raw_data"]["raw_forecast"]
        raw_observed = archive_data["raw_data"].get("raw_observed")
        market_snapshot = archive_data["raw_data"]["market_snapshot"]
        market_id = market_snapshot["market_id"]
        
        temp_snap_path = os.path.join(pid_dir, f"market_snapshot_{market_id}.json")
        with open(temp_snap_path, "w", encoding="utf-8") as f_snap:
            json.dump(market_snapshot, f_snap, ensure_ascii=False)
            
        tz = pytz.timezone(timezone_str)
        mock_dt = tz.localize(datetime.datetime.strptime(mock_time_str, "%Y-%m-%d %H:%M:%S"))
        
        class MockDateTime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return mock_dt

        with patch("src.weather_cache.get_api_cache", return_value=raw_forecast), \
             patch("src.weather_cache.fetch_wunderground_hourly_observed_today", return_value=raw_observed if isinstance(raw_observed, list) else [{"local_time": "2026-07-22 12:00:00", "temp": float(raw_observed), "hour": 12} if raw_observed else None]), \
             patch("src.analyst.datetime.datetime", MockDateTime), \
             patch("builtins.print"):
             
            prob_filename = src.analyst.analyze_single_market(temp_snap_path)
            prob_path = os.path.join(pid_dir, prob_filename)
            with open(prob_path, "r", encoding="utf-8") as f_p:
                prob_output = json.load(f_p)
        
        return strip_prob_output(prob_output)
    except Exception as e:
        print(f"  [WARN] analyst error: {e}")
        return None
    finally:
        CONFIG["risk_control_lock"] = old_risk_config
        src.analyst.PROTOCOLS_DIR = old_analyst_dir
        shutil.rmtree(pid_dir, ignore_errors=True)

def save_prob_cache_to_disk(s_mid, prob_list):
    """将 prob_cache 写入磁盘"""
    os.makedirs(PROB_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(PROB_CACHE_DIR, f"prob_cache_sigma_{s_mid:.2f}.json")
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(prob_list, f, ensure_ascii=False)
    return cache_path

def load_prob_cache_from_disk(s_mid):
    """从磁盘加载 prob_cache"""
    cache_path = os.path.join(PROB_CACHE_DIR, f"prob_cache_sigma_{s_mid:.2f}.json")
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def run_strategy_on_prob(archive_path, prob_output, params, mock_time_str, timezone_str):
    pid_dir = os.path.join(TEST_DIR, f"strat_worker_{os.getpid()}")
    os.makedirs(pid_dir, exist_ok=True)
    
    import src.strategy
    old_strategy_dir = src.strategy.PROTOCOLS_DIR
    src.strategy.PROTOCOLS_DIR = pid_dir
    
    old_risk_config = dict(CONFIG.get("risk_control_lock", {}))
    CONFIG["risk_control_lock"] = dict(old_risk_config)
    for k, v in params.items():
        CONFIG["risk_control_lock"][k] = v

    try:
        with open(archive_path, "r", encoding="utf-8") as f:
            archive_data = json.load(f)
            
        market_snapshot = archive_data["raw_data"]["market_snapshot"]
        market_id = market_snapshot["market_id"]
        
        temp_snap_path = os.path.join(pid_dir, f"market_snapshot_{market_id}.json")
        with open(temp_snap_path, "w", encoding="utf-8") as f_snap:
            json.dump(market_snapshot, f_snap, ensure_ascii=False)
            
        prob_filename = f"probability_report_{market_id}.json"
        temp_prob_path = os.path.join(pid_dir, prob_filename)
        with open(temp_prob_path, "w", encoding="utf-8") as f_p:
            json.dump(prob_output, f_p, ensure_ascii=False)

        mock_positions = {"YES": {}, "NO": {}}

        with patch("src.strategy.get_current_holdings", return_value=mock_positions), \
             patch("src.strategy.fetch_real_clob_book", return_value={"bids": [], "asks": []}), \
             patch("builtins.print"):
            sig_filename = src.strategy.calculate_single_strategy(temp_snap_path, temp_prob_path)
            sig_path = os.path.join(pid_dir, sig_filename)
            
            with open(sig_path, "r", encoding="utf-8") as f_s:
                sig_output = json.load(f_s)
        return sig_output
    except Exception as e:
        print(f"  [WARN] strategy error: {e}")
        return None
    finally:
        CONFIG["risk_control_lock"] = old_risk_config
        src.strategy.PROTOCOLS_DIR = old_strategy_dir
        shutil.rmtree(pid_dir, ignore_errors=True)

def evaluate_pnl(sig_output, winning_cond, market_snapshot):
    if not sig_output:
        return 0.0, 0.0, 0.0, 0, 0
        
    total_stake = 0.0
    total_payout = 0.0
    wins = 0
    total_bets = 0
    
    signals = sig_output.get("execution_signals", [])
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
        
        is_yes = (action == "BUY_YES")
        is_winning_cond = (cond == winning_cond)
        
        won = (is_yes and is_winning_cond) or (not is_yes and not is_winning_cond)
        
        if won:
            total_payout += shares
            wins += 1
            
    profit = total_payout - total_stake
    return total_stake, total_payout, profit, wins, total_bets

def main():
    print("=" * 80)
    print("🔥 冒烟测试：验证金融参数标定内存优化效果")
    print("=" * 80)
    
    os.makedirs(TEST_DIR, exist_ok=True)
    os.makedirs(PROB_CACHE_DIR, exist_ok=True)
    
    # 内存监控
    mem_log = []
    def log_memory(label):
        mem = get_memory_usage()
        mem_log.append((label, mem))
        print(f"  [MEM] {label}: {mem:.1f} MB")
    
    log_memory("程序启动")
    
    # 1. 加载数据（限制为 100 个场景）
    archives = glob.glob(os.path.join(PROJECT_ROOT, "storage/archive/*.json"))[:100]
    print(f"[*] 加载 {len(archives)} 个快照文件")
    
    conn = sqlite3.connect(CACHE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT station_id, date, is_lowest, obs_extreme FROM weather_daily_cache WHERE obs_extreme IS NOT NULL")
    obs_map = {(r[0].upper(), r[1], r[2]): r[3] for r in cursor.fetchall()}
    conn.close()
    
    log_memory("加载实况数据后")
    
    valid_scenarios = []
    for archive_path in archives:
        try:
            with open(archive_path, "r", encoding="utf-8") as f:
                archive_data = json.load(f)
        except Exception:
            continue
            
        raw_data = archive_data.get("raw_data", {})
        market_snapshot = raw_data.get("market_snapshot", {})
        raw_forecast = raw_data.get("raw_forecast", {})
        
        if not market_snapshot or not raw_forecast or "hourly" not in raw_forecast:
            continue
            
        market_id = market_snapshot.get("market_id", "")
        station_info = market_snapshot.get("station_info", {})
        station_id = station_info.get("station_id", "").upper()
        target_date = market_snapshot.get("target_date", "")
        ranges = market_snapshot.get("ranges", [])
        timestamp = market_snapshot.get("timestamp")
        
        if not station_id or not target_date or not ranges or not timestamp:
            continue
            
        is_lowest = 1 if "lowest" in market_id.lower() else 0
        obs_key = (station_id, target_date, is_lowest)
        if obs_key not in obs_map:
            continue
            
        obs_temp = obs_map[obs_key]
        winning_cond = None
        for r in ranges:
            cond = r.get("condition", "")
            if check_condition(obs_temp, cond):
                winning_cond = cond
                break
                
        if not winning_cond:
            continue
            
        timezone_str = station_info.get("timezone") or get_timezone_for_station(station_id)
        tz = pytz.timezone(timezone_str)
        mock_dt = datetime.datetime.fromtimestamp(timestamp, tz=pytz.utc).astimezone(tz)
        mock_time_str = mock_dt.strftime("%Y-%m-%d %H:%M:%S")
        
        trimmed_snapshot = {
            "market_id": market_id,
            "ranges": [{"range_id": r["range_id"], "condition": r["condition"], "ask_price": r.get("ask_price", 0.5)} for r in ranges],
            "station_info": {"timezone": timezone_str}
        }
        
        valid_scenarios.append({
            "market_id": market_id,
            "archive_path": archive_path,
            "mock_time_str": mock_time_str,
            "timezone_str": timezone_str,
            "winning_cond": winning_cond,
            "snapshot": trimmed_snapshot,
            "sigma_mid": 0.5  # 默认值
        })
    
    num_scenes = len(valid_scenarios)
    print(f"[+] 构建 {num_scenes} 个有效场景")
    log_memory("构建场景列表后")
    
    # 保存场景到磁盘
    scenarios_path = os.path.join(TEST_DIR, "valid_scenarios.json")
    with open(scenarios_path, "w", encoding="utf-8") as f:
        json.dump(valid_scenarios, f, ensure_ascii=False)
    
    # 2. 阶段 1：计算概率（使用单进程，便于内存监控）
    print("\n[*] 阶段 1/2：计算概率（单进程）")
    s_mid = 0.5
    s_trop = max(0.4, min(1.0, 0.8 * s_mid))
    prob_list = [None] * num_scenes
    
    t0 = time.time()
    for idx, scene in enumerate(valid_scenarios):
        prob_output = run_analyst_on_archive(
            scene["archive_path"], s_mid, s_trop, scene["mock_time_str"], scene["timezone_str"]
        )
        prob_list[idx] = prob_output
        
        if (idx + 1) % 20 == 0:
            elapsed = time.time() - t0
            rate = (idx + 1) / elapsed
            print(f"  [{idx+1}/{num_scenes}] 速度: {rate:.1f} 点/秒")
            log_memory(f"概率计算 {idx+1}/{num_scenes}")
    
    # 写入磁盘
    cache_path = save_prob_cache_to_disk(s_mid, prob_list)
    print(f"[+] 概率缓存写入: {cache_path}")
    log_memory("概率缓存写入磁盘后")
    
    # 释放内存
    del prob_list
    log_memory("释放概率列表后")
    
    # 3. 阶段 2：策略计算（单进程，便于内存监控）
    print("\n[*] 阶段 2/2：策略计算（单进程）")
    prob_list = load_prob_cache_from_disk(s_mid)
    log_memory("从磁盘加载概率缓存后")
    
    params = {
        "obs_error_sigma_baseline_mid_lat": s_mid,
        "obs_error_sigma_baseline_tropics": s_trop,
        "robust_kelly_theta": 1.5,
        "robust_kelly_model_uncertainty_eta": 0.25
    }
    
    total_stake = 0.0
    total_profit = 0.0
    total_bets = 0
    
    t0 = time.time()
    for idx, scene in enumerate(valid_scenarios):
        prob_out = prob_list[idx]
        if not prob_out:
            continue
            
        sig_output = run_strategy_on_prob(
            scene["archive_path"], prob_out, params, scene["mock_time_str"], scene["timezone_str"]
        )
        
        st, pay, prof, wins, bets = evaluate_pnl(sig_output, scene["winning_cond"], scene["snapshot"])
        total_stake += st
        total_profit += prof
        total_bets += bets
        
        if (idx + 1) % 20 == 0:
            elapsed = time.time() - t0
            rate = (idx + 1) / elapsed
            print(f"  [{idx+1}/{num_scenes}] 速度: {rate:.1f} 点/秒")
            log_memory(f"策略计算 {idx+1}/{num_scenes}")
    
    # 4. 输出结果
    roi = (total_profit / total_stake * 100) if total_stake > 0 else 0.0
    print(f"\n[+] 测试结果：")
    print(f"    - 下注总额: {total_stake:.2f} USDC")
    print(f"    - 总利润: {total_profit:.2f} USDC")
    print(f"    - ROI: {roi:.2f}%")
    print(f"    - 总下注次数: {total_bets}")
    
    # 内存统计
    print("\n[+] 内存使用统计：")
    max_mem = max(mem_log, key=lambda x: x[1])
    print(f"    峰值内存: {max_mem[1]:.1f} MB (在 {max_mem[0]})")
    for label, mem in mem_log:
        print(f"    {label}: {mem:.1f} MB")
    
    # 清理
    shutil.rmtree(TEST_DIR, ignore_errors=True)
    print("\n[+] 测试完成！临时文件已清理")
    
    # 验证
    assert total_bets > 0, "没有产生任何下注信号"
    assert total_stake > 0, "总仓位为零"
    print("✅ 所有验证通过！")

if __name__ == "__main__":
    main()
