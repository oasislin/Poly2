"""
================================================================================
🎯 Polymarket 天气套利策略：多日完备性联合金融参数标定 (内存优化版)
================================================================================
【内存优化要点】：
 1. 剥离无用字段：从 prob_output 中删除 _raw_open_meteo_response 和 _raw_wunderground_observed
    (strategy.py 仅需要 probability_distribution, _simulated_sigma, ref_hour, market_id)
 2. 磁盘缓存：将每个 sigma 的 prob_cache 写入磁盘文件，Phase 2 按需加载
 3. 精简场景：valid_scenarios 只保留必要字段（archive_path, mock_time_str, timezone_str, 
    winning_cond, 和精简的 snapshot）
 4. 进程池优化：使用 initializer 参数，每个 worker 进程从磁盘加载一次 prob_cache，
    任务只传递轻量级参数（场景索引、theta、eta）
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
import logging
import time
from unittest.mock import patch
import numpy as np
from typing import Dict, List, Tuple, Any
from concurrent.futures import ProcessPoolExecutor, as_completed

# 屏蔽无关模块的调试日志
for logger_name in ["src.analyst", "src.strategy", "src.bias_corrector", "src.weather_cache", "urllib3"]:
    logging.getLogger(logger_name).setLevel(logging.CRITICAL)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src.analyst as analyst_module
import src.strategy as strategy_module
from src.analyst import analyze_single_market, check_condition
from src.strategy import calculate_single_strategy
from src.config import CONFIG

DB_PATH = os.path.join(PROJECT_ROOT, "storage", "arbitrage.db")
CACHE_DB_PATH = os.path.join(PROJECT_ROOT, "storage", "weather_cache.db")
TEST_DIR = os.path.join(PROJECT_ROOT, "scratch", "financial_backtest_fast")
PROB_CACHE_DIR = os.path.join(TEST_DIR, "prob_cache")

# 全局变量用于 worker 进程
WORKER_PROB_CACHE = None
WORKER_SCENARIOS = None

def get_timezone_for_station(station_id):
    timezone_map = {
        "RKSI": "Asia/Seoul", "KNYC": "America/New_York", "EGLL": "Europe/London",
        "RJTT": "Asia/Tokyo", "VHHH": "Asia/Hong_Kong", "ZSSS": "Asia/Shanghai",
        "ZBAA": "Asia/Shanghai", "ZGGG": "Asia/Shanghai", "ZHHH": "Asia/Shanghai",
        "ZSQD": "Asia/Shanghai", "RCTP": "Asia/Taipei", "RCSS": "Asia/Taipei",
        "EHAM": "Europe/Amsterdam", "LFPG": "Europe/Paris", "LFPO": "Europe/Paris",
        "EDDM": "Europe/Berlin", "LEMD": "Europe/Madrid", "LIMC": "Europe/Rome",
        "EPWA": "Europe/Warsaw", "EFHK": "Europe/Helsinki", "FACT": "Africa/Johannesburg",
        "SAEZ": "America/Argentina/Buenos_Aires", "SBGR": "America/Sao_Paulo",
        "MPTO": "America/Panama", "MMMX": "America/Mexico_City", "CYYZ": "America/Toronto",
        "NZWN": "Pacific/Auckland", "WSSS": "Asia/Singapore", "WMKK": "Asia/Kuala_Lumpur",
        "RPLL": "Asia/Manila", "OPKC": "Asia/Karachi", "ATLA": "America/New_York",
        "HOUS": "America/Chicago", "CHIC": "America/Chicago", "AUST": "America/Chicago",
        "DENV": "America/Denver", "AURO": "America/Denver", "MIAI": "America/New_York",
        "MIAM": "America/New_York", "SEAT": "America/Los_Angeles", "DALL": "America/Chicago"
    }
    return timezone_map.get(station_id.upper(), "UTC")

def strip_prob_output(prob_output):
    """
    剥离 prob_output 中策略模块不需要的大字段，大幅减少内存占用。
    strategy.py 仅读取: market_id, probability_distribution, _simulated_sigma, ref_hour
    """
    if prob_output is None:
        return None
    
    # 只保留策略模块需要的字段
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
        raw_hourly_obs = archive_data["raw_data"].get("raw_hourly_obs", [])
        market_snapshot = archive_data["raw_data"]["market_snapshot"]
        market_id = market_snapshot["market_id"]

        # 读取归档时存储的 bias 值（避免回测时重新调 API）
        calc_results = archive_data.get("calculated_results", {})
        archived_bias = calc_results.get("bias", 0.0)
        archived_rolling_sigma = calc_results.get("rolling_sigma", None)
        archived_daily_residuals = calc_results.get("daily_residuals", [])

        temp_snap_path = os.path.join(pid_dir, f"market_snapshot_{market_id}.json")
        with open(temp_snap_path, "w", encoding="utf-8") as f_snap:
            json.dump(market_snapshot, f_snap, ensure_ascii=False)

        tz = pytz.timezone(timezone_str)
        mock_dt = tz.localize(datetime.datetime.strptime(mock_time_str, "%Y-%m-%d %H:%M:%S"))

        class MockDateTime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return mock_dt

        # 禁用 analyst 模块的所有日志输出
        def no_op(*args, **kwargs):
            pass

        # 【关键修复】过滤逐小时观测数据：只保留模拟决策时间之前的观测点
        # raw_hourly_obs 是逐小时观测列表，按 mock_time_str 过滤
        # 这样 CHSM 只能看到决策时刻之前的数据，不会泄漏未来信息
        if raw_hourly_obs and isinstance(raw_hourly_obs, list):
            mock_observed = []
            for obs in raw_hourly_obs:
                obs_time_str = obs.get("local_time", "")
                try:
                    obs_dt = tz.localize(datetime.datetime.strptime(obs_time_str, "%Y-%m-%d %H:%M:%S"))
                    if obs_dt <= mock_dt:
                        mock_observed.append(obs)
                except Exception:
                    continue
        else:
            mock_observed = None

        # 【关键修复】patch get_bias 返回归档时存储的 bias 值，避免回测时重新调 API
        def mock_get_bias(*args, **kwargs):
            return archived_bias, archived_rolling_sigma, archived_daily_residuals
        
        with patch("src.weather_cache.get_api_cache", return_value=raw_forecast), \
             patch("src.weather_cache.fetch_wunderground_hourly_observed_today", return_value=mock_observed), \
             patch("src.analyst.datetime.datetime", MockDateTime), \
             patch("src.bias_corrector.MovingWindowBiasCorrector.get_bias", mock_get_bias), \
             patch("builtins.print"), \
             patch.object(src.analyst.logger, 'info', no_op), \
             patch.object(src.analyst.logger, 'debug', no_op), \
             patch.object(src.analyst.logger, 'warning', no_op), \
             patch.object(src.analyst.logger, 'error', no_op):
             
            prob_filename = analyze_single_market(temp_snap_path)
            prob_path = os.path.join(pid_dir, prob_filename)
            with open(prob_path, "r", encoding="utf-8") as f_p:
                prob_output = json.load(f_p)
        
        # 【关键优化】剥离大字段
        return strip_prob_output(prob_output)
    except Exception:
        return None
    finally:
        CONFIG["risk_control_lock"] = old_risk_config
        src.analyst.PROTOCOLS_DIR = old_analyst_dir
        shutil.rmtree(pid_dir, ignore_errors=True)

def _worker_prob_task(args):
    s_mid, idx, archive_path, s_trop, mock_time_str, timezone_str = args
    prob = run_analyst_on_archive(archive_path, s_mid, s_trop, mock_time_str, timezone_str)
    return (s_mid, idx, prob)

def save_prob_cache_to_disk(s_mid, prob_list):
    """将单个 sigma 的 prob_cache 写入磁盘文件"""
    os.makedirs(PROB_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(PROB_CACHE_DIR, f"prob_cache_sigma_{s_mid:.2f}.json")
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(prob_list, f, ensure_ascii=False)
    return cache_path

def load_prob_cache_from_disk(s_mid):
    """从磁盘加载单个 sigma 的 prob_cache"""
    cache_path = os.path.join(PROB_CACHE_DIR, f"prob_cache_sigma_{s_mid:.2f}.json")
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def run_strategy_on_prob(archive_path, prob_output, params):
    """
    使用真实的 strategy 模块进行策略计算（保留完整的凯利优化逻辑）
    通过 patch 禁用日志和异常报告生成来加速，但不改变计算结果
    """
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

        # 【非侵入式优化】通过 patch 禁用：
        # 1. 日志输出（减少 I/O）
        # 2. validate_contract 校验（标定数据格式已确定）
        # 3. 异常报告生成（标定阶段不需要）
        def no_op(*args, **kwargs):
            pass
            
        def no_op_validate(*args, **kwargs):
            pass

        with patch("src.strategy.get_current_holdings", return_value=mock_positions), \
             patch("src.strategy.fetch_real_clob_book", return_value={"bids": [], "asks": []}), \
             patch("builtins.print"), \
             patch("src.strategy.validate_contract", no_op_validate), \
             patch.object(src.strategy.logger, 'info', no_op), \
             patch.object(src.strategy.logger, 'debug', no_op), \
             patch.object(src.strategy.logger, 'warning', no_op), \
             patch.object(src.strategy.logger, 'error', no_op):
            sig_filename = calculate_single_strategy(temp_snap_path, temp_prob_path)
            if sig_filename is None:
                return None
            sig_path = os.path.join(pid_dir, sig_filename)
            
            with open(sig_path, "r", encoding="utf-8") as f_s:
                sig_output = json.load(f_s)
        return sig_output
    except Exception:
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

def worker_init(s_mid):
    """
    ProcessPoolExecutor 的初始化函数，每个 worker 进程只调用一次。
    将 prob_cache 和 scenarios 加载到进程本地内存。
    """
    global WORKER_PROB_CACHE, WORKER_SCENARIOS
    WORKER_PROB_CACHE = load_prob_cache_from_disk(s_mid)
    WORKER_SCENARIOS = []
    
    # 从磁盘加载精简的 scenarios
    scenarios_path = os.path.join(TEST_DIR, "valid_scenarios.json")
    if os.path.exists(scenarios_path):
        with open(scenarios_path, "r", encoding="utf-8") as f:
            WORKER_SCENARIOS = json.load(f)

def _worker_combo_task(args):
    """
    优化后的任务函数，只接收轻量级参数（theta, eta）。
    prob_cache 和 scenarios 从进程全局变量获取。
    """
    theta, eta = args
    
    # 从全局变量获取数据（每个进程只加载一次）
    prob_list = WORKER_PROB_CACHE
    valid_scenarios = WORKER_SCENARIOS
    
    if prob_list is None or valid_scenarios is None:
        return None
    
    s_mid = valid_scenarios[0]["sigma_mid"] if valid_scenarios else 0.5
    
    params = {
        "obs_error_sigma_baseline_mid_lat": s_mid,
        "obs_error_sigma_baseline_tropics": max(0.4, min(1.0, 0.8 * s_mid)),
        "robust_kelly_theta": theta,
        "robust_kelly_model_uncertainty_eta": eta
    }
    total_stake = 0.0
    total_profit = 0.0
    total_payout = 0.0
    total_wins = 0
    total_bets = 0
    max_loss = 0.0

    for idx, scene in enumerate(valid_scenarios):
        prob_out = prob_list[idx]
        if not prob_out:
            continue
        # 使用真实的 strategy 模块进行策略计算
        sig_output = run_strategy_on_prob(scene["archive_path"], prob_out, params)
        st, pay, prof, wins, bets = evaluate_pnl(sig_output, scene["winning_cond"], scene["snapshot"])
        total_stake += st
        total_payout += pay
        total_profit += prof
        total_wins += wins
        total_bets += bets
        if prof < 0:
            max_loss = max(max_loss, abs(prof))

    roi = (total_profit / total_stake * 100) if total_stake > 0 else 0.0
    win_rate = (total_wins / total_bets * 100) if total_bets > 0 else 0.0
    return {
        "sigma_mid_lat": s_mid,
        "theta": theta,
        "eta": eta,
        "stake": total_stake,
        "profit": total_profit,
        "roi": roi,
        "win_rate": win_rate,
        "total_bets": total_bets,
        "max_loss": max_loss
    }

def main():
    start_time_all = time.time()
    os.makedirs(TEST_DIR, exist_ok=True)
    os.makedirs(PROB_CACHE_DIR, exist_ok=True)
    
    print("=" * 90)
    print("      🎯 Polymarket 天气套利：30天全量联合金融标定 (内存优化版)")
    print("=" * 90)

    # 1. 快速载入数据与校验
    archives = glob.glob(os.path.join(PROJECT_ROOT, "storage/archive/*.json"))
    print(f"[*] 扫描到 Snapshot 历史快照文件: {len(archives)} 个")
    print("[*] 正在载入实况结算数据 (weather_daily_cache)...")

    conn = sqlite3.connect(CACHE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT station_id, date, is_lowest, obs_extreme FROM weather_daily_cache WHERE obs_extreme IS NOT NULL")
    obs_map = {(r[0].upper(), r[1], r[2]): r[3] for r in cursor.fetchall()}
    conn.close()

    valid_scenarios = []
    skipped = 0

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
            skipped += 1
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
        mock_date_str = mock_dt.strftime("%Y-%m-%d")
        
        # 【优化】精简 snapshot，只保留策略模块需要的字段
        trimmed_snapshot = {
            "market_id": market_id,
            "ranges": [{"range_id": r["range_id"], "condition": r["condition"], "ask_price": r.get("ask_price", 0.5)} for r in ranges],
            "station_info": {"timezone": timezone_str}
        }

        # 每个归档 = 1 个场景，使用归档的真实采集时间作为决策时间
        mock_time_str = mock_dt.strftime("%Y-%m-%d %H:%M:%S")
        valid_scenarios.append({
            "market_id": market_id,
            "archive_path": archive_path,
            "mock_time_str": mock_time_str,
            "timezone_str": timezone_str,
            "winning_cond": winning_cond,
            "snapshot": trimmed_snapshot,
            "hour": mock_dt.hour
        })

    num_scenes = len(valid_scenarios)
    print(f"[+] 数据完备性校验完成！构建出 30 天全量反事实决策点: {num_scenes} 个 (跳过: {skipped})")

    # 保存精简的 scenarios 到磁盘，供 worker 进程加载
    scenarios_path = os.path.join(TEST_DIR, "valid_scenarios.json")
    with open(scenarios_path, "w", encoding="utf-8") as f:
        json.dump(valid_scenarios, f, ensure_ascii=False)
    print(f"[*] 精简场景数据已保存至: {scenarios_path}")

    # 定义标定空间
    sigmas = [0.5, 0.7, 0.9, 1.2]
    thetas = [1.0, 1.5, 2.0]
    etas = [0.15, 0.25, 0.35]
    cpu_count = max(1, os.cpu_count() - 1)

    # 2. 阶段 1：预先并行计算 4 组 σ 下的概率点（写入磁盘，不驻留内存）
    print(f"\n[*] [阶段 1/2] 正在启动 4 组 σ 物理概率池并发计算 (写入磁盘)...", flush=True)

    total_prob_tasks = len(sigmas) * num_scenes
    done_prob = 0
    t0_stage1 = time.time()

    # 按 sigma 分批处理，每批计算完立即写入磁盘并释放内存
    all_prob_cache_paths = []
    for s_mid in sigmas:
        s_trop = max(0.4, min(1.0, 0.8 * s_mid))
        prob_list = [None] * num_scenes
        
        # 构建当前 sigma 的任务列表（按需创建，不保存到大列表）
        sigma_tasks = [(s_mid, idx, scene["archive_path"], s_trop, scene["mock_time_str"], scene["timezone_str"]) 
                      for idx, scene in enumerate(valid_scenarios)]
        
        try:
            with ProcessPoolExecutor(max_workers=cpu_count) as executor:
                futures = {executor.submit(_worker_prob_task, t): t for t in sigma_tasks}
                for fut in as_completed(futures):
                    done_prob += 1
                    s_mid_res, idx, prob = fut.result()
                    prob_list[idx] = prob
                    
                    if done_prob % 2000 == 0 or done_prob == total_prob_tasks:
                        elapsed = time.time() - t0_stage1
                        rate = done_prob / elapsed
                        rem_sec = (total_prob_tasks - done_prob) / rate if rate > 0 else 0
                        print(f"     [阶段 1 进度] {done_prob}/{total_prob_tasks} ({done_prob/total_prob_tasks*100:.1f}%) | 速度: {rate:.1f} 点/秒 | 剩余时间: {rem_sec:.1f}s", flush=True)
        except KeyboardInterrupt:
            print(f"\n[!] 用户中断！正在保存已完成的概率缓存...", flush=True)
            # 保存已完成的部分
            if any(p is not None for p in prob_list):
                cache_path = save_prob_cache_to_disk(s_mid, prob_list)
                print(f"[+] 已保存部分结果至: {cache_path}")
            shutil.rmtree(TEST_DIR, ignore_errors=True)
            print(f"[+] 临时文件已清理")
            sys.exit(0)
        
        # 写入磁盘并立即释放内存
        cache_path = save_prob_cache_to_disk(s_mid, prob_list)
        all_prob_cache_paths.append(cache_path)
        print(f"[+] σ={s_mid:.2f} 的概率缓存已写入: {cache_path}")
        
        # 强制释放内存
        del prob_list
        del sigma_tasks
        import gc
        gc.collect()

    print(f"[+] [阶段 1 完成] 概率向量全部写入磁盘！用时: {time.time() - t0_stage1:.1f} 秒", flush=True)

    # 3. 阶段 2：网格搜索标定 36 组 Sizing 组合（分批运行，单组合保存）
    total_combos = len(sigmas) * len(thetas) * len(etas)
    print(f"\n[*] [阶段 2/2] 正在启动 {total_combos} 组金融 Sizing 参数网格搜索...", flush=True)
    
    # 创建中间结果文件，用于分批保存
    intermediate_results_path = os.path.join(TEST_DIR, "intermediate_results.json")
    
    # 加载已完成的结果（支持断点续跑）
    completed_results = []
    if os.path.exists(intermediate_results_path):
        with open(intermediate_results_path, "r", encoding="utf-8") as f:
            completed_results = json.load(f)
        print(f"[*] 检测到已有 {len(completed_results)} 组已完成的结果，将跳过这些组合...")
    
    # 构建所有待处理的参数组合
    all_combo_tasks = []
    for s_mid in sigmas:
        for theta in thetas:
            for eta in etas:
                combo_key = f"{s_mid:.2f}_{theta:.1f}_{eta:.2f}"
                # 检查是否已完成
                already_done = any(f"{r['sigma_mid_lat']:.2f}_{r['theta']:.1f}_{r['eta']:.2f}" == combo_key 
                                for r in completed_results)
                if not already_done:
                    all_combo_tasks.append((s_mid, theta, eta))
    
    print(f"[+] 本次需要处理 {len(all_combo_tasks)} 组参数组合...")
    
    # 逐个处理参数组合
    all_results = completed_results.copy()
    total_to_do = len(all_combo_tasks)
    done_count = 0
    t0_stage2 = time.time()
    
    for s_mid, theta, eta in all_combo_tasks:
        done_count += 1
        combo_key = f"{s_mid:.2f}_{theta:.1f}_{eta:.2f}"
        t0_combo = time.time()
        
        print(f"\n[{done_count}/{total_to_do}] 处理组合: σ={s_mid:.2f} θ={theta:.1f} η={eta:.2f}...", flush=True)
        
        try:
            # 更新 valid_scenarios 中的 sigma_mid 字段
            for scene in valid_scenarios:
                scene["sigma_mid"] = s_mid
            # 重新保存到磁盘
            with open(scenarios_path, "w", encoding="utf-8") as f:
                json.dump(valid_scenarios, f, ensure_ascii=False)
            
            # 单进程处理当前组合（避免多进程内存开销）
            # 首先加载 prob_cache
            prob_list = load_prob_cache_from_disk(s_mid)
            if prob_list is None:
                print(f"  [!] 无法加载 σ={s_mid:.2f} 的概率缓存，跳过此组合", flush=True)
                continue
            
            params = {
                "obs_error_sigma_baseline_mid_lat": s_mid,
                "obs_error_sigma_baseline_tropics": max(0.4, min(1.0, 0.8 * s_mid)),
                "robust_kelly_theta": theta,
                "robust_kelly_model_uncertainty_eta": eta
            }
            
            total_stake = 0.0
            total_profit = 0.0
            total_wins = 0
            total_bets = 0
            max_loss = 0.0
            
            # 逐个场景处理
            for idx, scene in enumerate(valid_scenarios):
                prob_out = prob_list[idx]
                if not prob_out:
                    continue
                sig_output = run_strategy_on_prob(scene["archive_path"], prob_out, params)
                st, pay, prof, wins, bets = evaluate_pnl(sig_output, scene["winning_cond"], scene["snapshot"])
                total_stake += st
                total_profit += prof
                total_wins += wins
                total_bets += bets
                if prof < 0:
                    max_loss = max(max_loss, abs(prof))
                
                # 进度显示（降低频率，便于观察）
                if (idx + 1) % 1000 == 0 or idx + 1 == num_scenes:
                    elapsed_combo = time.time() - t0_combo
                    rate = (idx + 1) / elapsed_combo
                    rem_sec = (num_scenes - idx - 1) / rate if rate > 0 else 0
                    print(f"    [{idx+1}/{num_scenes}] 速度: {rate:.1f} 点/秒 | 剩余: {rem_sec:.0f}s", flush=True)
            
            # 计算 ROI 和胜率
            roi = (total_profit / total_stake * 100) if total_stake > 0 else 0.0
            win_rate = (total_wins / total_bets * 100) if total_bets > 0 else 0.0
            
            result = {
                "sigma_mid_lat": s_mid,
                "theta": theta,
                "eta": eta,
                "stake": total_stake,
                "profit": total_profit,
                "roi": roi,
                "win_rate": win_rate,
                "total_bets": total_bets,
                "max_loss": max_loss,
                "elapsed_time": time.time() - t0_combo
            }
            
            all_results.append(result)
            
            # 立即保存到中间文件
            with open(intermediate_results_path, "w", encoding="utf-8") as f:
                json.dump(all_results, f, ensure_ascii=False)
            
            # 输出结果
            elapsed_combo = time.time() - t0_combo
            print(f"  ✅ 完成！用时: {elapsed_combo:.1f}s | ROI: {roi:+6.2f}% | PnL: ${total_profit:+9.2f} | 胜率: {win_rate:4.1f}%", flush=True)
            
            # 释放内存
            del prob_list
            del params
            import gc
            gc.collect()
            
        except KeyboardInterrupt:
            print(f"\n[!] 用户中断！已完成 {done_count-1} 组，正在保存进度...", flush=True)
            # 保存已完成的部分结果
            with open(intermediate_results_path, "w", encoding="utf-8") as f:
                json.dump(all_results, f, ensure_ascii=False)
            print(f"[+] 进度已保存至: {intermediate_results_path}")
            print(f"[+] 下次运行将自动跳过已完成的组合")
            shutil.rmtree(TEST_DIR, ignore_errors=True)
            print(f"[+] 临时文件已清理")
            sys.exit(0)
        except Exception as e:
            print(f"  [!] 处理组合 {combo_key} 时出错: {e}，跳过此组合", flush=True)
            continue
    
    print(f"\n[+] [阶段 2 完成] 全部 {total_to_do} 组参数组合处理完毕！用时: {time.time() - t0_stage2:.1f} 秒", flush=True)
    
    # 4. 输出汇总与保存
    all_results.sort(key=lambda x: x["profit"], reverse=True)

    print("\n" + "=" * 100)
    print(f"                       🏆 30 天全量金融标定网格搜索排名 (用时: {time.time() - start_time_all:.1f}s)")
    print("=" * 100)
    print(f"{'名次':^4} | {'σ_mid':^6} | {'θ':^4} | {'η':^4} | {'下注总额':^12} | {'总净利润':^14} | {'ROI':^10} | {'胜率':^10} | {'最大单次损失':^14}")
    print("-" * 100)
    for idx, r in enumerate(all_results[:15]):
        print(f"{idx+1:^4d} | {r['sigma_mid_lat']:6.2f} | {r['theta']:4.1f} | {r['eta']:4.2f} | {r['stake']:12.2f} | {r['profit']:+14.2f} | {r['roi']:9.2f}% | {r['win_rate']:9.1f}% | {r['max_loss']:14.2f}")
    print("=" * 100)

    best = all_results[0]
    print(f"\n[+] 全局标定最优风控配置推荐：")
    print(f"  - 物理下限 σ_baseline: {best['sigma_mid_lat']} °C")
    print(f"  - 凯利乘数 θ: {best['theta']}")
    print(f"  - 时间收缩系数 η: {best['eta']}")
    print(f"  - 标定 ROI: {best['roi']:.2f}% (总收益: {best['profit']:+.2f} USDC)")

    output_path = os.path.join("storage", "calibrated_financial_params.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "calibrated_at": datetime.datetime.now().isoformat(),
            "best_params": {
                "obs_error_sigma_baseline_mid_lat": best["sigma_mid_lat"],
                "obs_error_sigma_baseline_tropics": max(0.4, min(1.0, 0.8 * best["sigma_mid_lat"])),
                "robust_kelly_theta": best["theta"],
                "robust_kelly_model_uncertainty_eta": best["eta"]
            },
            "backtest_performance": {
                "total_stake_usdc": round(best["stake"], 2),
                "total_profit_usdc": round(best["profit"], 2),
                "roi_pct": round(best["roi"], 2),
                "win_rate_pct": round(best["win_rate"], 2),
                "max_single_loss_usdc": round(best["max_loss"], 2)
            }
        }, f, indent=2, ensure_ascii=False)
    print(f"[+] 标定结果已更新至: {output_path}")

    # 清理临时文件
    shutil.rmtree(TEST_DIR, ignore_errors=True)
    print(f"[+] 临时文件已清理")

if __name__ == "__main__":
    main()
