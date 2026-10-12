"""
σ_mid Brier Score 标定脚本
==============================
设计文档: docs/brier_score_calibration_design.md

目标：用历史已结算市场的实测气温作为真值标签，评估不同 σ_mid 参数下
     Analyst 概率预测的准确性（Brier Score），找到最优的 σ_mid 值。

关键特性：
  - 不依赖我们是否下注，不依赖交易盈亏，只需要"存档快照 + 实测气温"
  - rolling_sigma 无前瞻偏差（窗口由 target_date 决定，与重放时刻无关）
  - 两层聚合：先按市场取均值，再跨市场取均值，避免多存档市场主导结果
  - 自动输出先决条件诊断：rolling_sigma 分布、提前量分布

运行方式：
  cd /Users/ericlin/SynologyDrive/Project/Polymarket天气套利
  /opt/miniconda3/bin/python3 scratch/calibrate_sigma_brier.py
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
import numpy as np
from unittest.mock import patch
from collections import defaultdict

# ─── 路径设置 ────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analyst import analyze_single_market, check_condition
from src.config import CONFIG
import src.analyst as analyst_module

DB_PATH        = os.path.join(PROJECT_ROOT, "storage/arbitrage.db")
CACHE_DB_PATH  = os.path.join(PROJECT_ROOT, "storage/weather_cache.db")
ARCHIVE_DIR    = os.path.join(PROJECT_ROOT, "storage/archive")
TEMP_DIR       = os.path.join(PROJECT_ROOT, "scratch/brier_temp")

# ─── 标定参数 ────────────────────────────────────────────────────────────────
SIGMA_CANDIDATES = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5, 2.0]

LEAD_TIME_BUCKETS = [
    (0,   24,  "0-24h"),
    (24,  48,  "24-48h"),
    (48,  72,  "48-72h"),
    (72,  9999,"72h+"),
]

# ─── 抑制日志 ────────────────────────────────────────────────────────────────
for _ln in ["src.analyst", "src.strategy", "src.bias_corrector",
            "src.weather_cache", "urllib3", "BiasCorrector", "Analyst"]:
    logging.getLogger(_ln).setLevel(logging.CRITICAL)
logging.basicConfig(level=logging.CRITICAL)


# ════════════════════════════════════════════════════════════════════════════
# 第一步：加载有效市场样本
# ════════════════════════════════════════════════════════════════════════════

def load_obs_extreme_map():
    conn = sqlite3.connect(CACHE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT station_id, date, is_lowest, obs_extreme "
        "FROM weather_daily_cache WHERE obs_extreme IS NOT NULL"
    )
    result = {(r[0].upper(), r[1], r[2]): r[3] for r in cursor.fetchall()}
    conn.close()
    return result


def load_trades_market_info():
    """从 storage/archive 中的快照构建 30 天全量已结算市场索引"""
    archives_by_m = load_archive_files_by_market()
    result = {}
    for market_id, paths in archives_by_m.items():
        if not paths:
            continue
        # 从快照读取 station_id 和 settlement_date
        for p in paths:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
                snap = d.get("raw_data", {}).get("market_snapshot", {})
                st_id = snap.get("station_info", {}).get("station_id", "").upper()
                s_date = snap.get("target_date")
                if st_id and s_date:
                    is_lowest = 1 if "lowest" in market_id.lower() else 0
                    result[market_id] = {
                        "station_id": st_id,
                        "settlement_date": s_date,
                        "is_lowest": is_lowest,
                    }
                    break
            except Exception:
                continue
    return result


def load_archive_files_by_market():
    result = defaultdict(list)
    for path in glob.glob(os.path.join(ARCHIVE_DIR, "*.json")):
        bn = os.path.basename(path)
        parts = bn.split("_", 2)
        if len(parts) == 3:
            market_id = parts[2].replace(".json", "")
            result[market_id].append(path)
    return result


def get_archive_timestamp(archive_path):
    bn = os.path.basename(archive_path)
    parts = bn.split("_", 2)
    try:
        return datetime.datetime.strptime(parts[0] + "_" + parts[1], "%Y%m%d_%H%M%S")
    except Exception:
        return None


def get_settlement_ref_time(target_date, timezone_str):
    try:
        tz = pytz.timezone(timezone_str)
        local_ref = tz.localize(
            datetime.datetime.strptime(target_date + " 23:00:00", "%Y-%m-%d %H:%M:%S")
        )
        return local_ref.astimezone(pytz.utc)
    except Exception:
        return None


def compute_hours_to_maturity(archive_path, target_date, timezone_str):
    archive_dt = get_archive_timestamp(archive_path)
    if not archive_dt:
        return None
    archive_utc = pytz.utc.localize(archive_dt)
    ref_utc = get_settlement_ref_time(target_date, timezone_str)
    if not ref_utc:
        return None
    return (ref_utc - archive_utc).total_seconds() / 3600.0


def get_winner_condition(obs_temp_celsius, ranges, market_id):
    """用实测气温匹配胜出区间。
    通过 ranges 数值范围自动推断是否为华氏度市场。
    """
    is_fahrenheit = False
    if ranges:
        try:
            sample_vals = []
            for r in ranges[:3]:
                cond = r.get("condition", "")
                if "-" in cond:
                    sample_vals.append(float(cond.split("-")[0]))
                elif cond.startswith(">=") or cond.startswith("<="):
                    sample_vals.append(float(cond[2:]))
            if sample_vals and np.mean(sample_vals) > 40:
                is_fahrenheit = True
        except Exception:
            pass

    temp_for_check = obs_temp_celsius * 9/5 + 32 if is_fahrenheit else obs_temp_celsius

    for r in ranges:
        cond = r.get("condition", "")
        if check_condition(temp_for_check, cond):
            return cond
    return None


def build_valid_scenarios():
    print("[*] 正在加载数据索引...", flush=True)
    obs_map       = load_obs_extreme_map()
    market_info   = load_trades_market_info()
    archives_by_m = load_archive_files_by_market()

    print(f"    weather_daily_cache 实测气温条目: {len(obs_map)}")
    print(f"    trades 表 distinct market 数: {len(market_info)}")
    print(f"    archive 目录 distinct market 数: {len(archives_by_m)}")

    scenarios = []
    skipped = {"no_obs": 0, "no_archive": 0, "no_winner": 0, "same_day": 0, "future": 0, "bad_data": 0}

    for market_id, info in market_info.items():
        station_id      = info["station_id"]
        settlement_date = info["settlement_date"]
        is_lowest       = info["is_lowest"]

        obs_key = (station_id, settlement_date, is_lowest)
        if obs_key not in obs_map:
            skipped["no_obs"] += 1
            continue
        obs_temp = obs_map[obs_key]

        if market_id not in archives_by_m:
            skipped["no_archive"] += 1
            continue
        archive_paths = archives_by_m[market_id]

        # 从最早的存档里读取 ranges 和 timezone
        timezone_str = None
        ranges = None
        for ap in sorted(archive_paths):
            try:
                with open(ap, "r", encoding="utf-8") as f:
                    d = json.load(f)
                snap = d.get("raw_data", {}).get("market_snapshot", {})
                tz_in_snap = snap.get("station_info", {}).get("timezone")
                r_in_snap  = snap.get("ranges", [])
                if tz_in_snap and r_in_snap:
                    timezone_str = tz_in_snap
                    ranges = r_in_snap
                    break
            except Exception:
                continue

        if not timezone_str or not ranges:
            skipped["bad_data"] += 1
            continue

        winner_cond = get_winner_condition(obs_temp, ranges, market_id)
        if not winner_cond:
            skipped["no_winner"] += 1
            continue

        for ap in sorted(archive_paths):
            hours = compute_hours_to_maturity(ap, settlement_date, timezone_str)
            if hours is None or hours <= 0:
                skipped["future"] += 1
                continue
            # 方案 A：过滤掉 <=24h 的同日存档，避免触发 CHSM 安全降级机制
            if hours <= 24:
                skipped["same_day"] += 1
                continue
            scenarios.append({
                "market_id":         market_id,
                "station_id":        station_id,
                "settlement_date":   settlement_date,
                "is_lowest":         is_lowest,
                "obs_temp":          obs_temp,
                "winner_cond":       winner_cond,
                "archive_path":      ap,
                "hours_to_maturity": hours,
                "timezone_str":      timezone_str,
                "ranges":            ranges,
            })

    n_markets = len(set(s["market_id"] for s in scenarios))
    print(f"\n[+] 场景构建完成！有效场景: {len(scenarios)} 个 (来自 {n_markets} 个市场)")
    for k, v in skipped.items():
        print(f"    丢弃-{k}: {v}")
    return scenarios


# ════════════════════════════════════════════════════════════════════════════
# 第二步：先决条件诊断
# ════════════════════════════════════════════════════════════════════════════

def diagnose_prerequisites(scenarios):
    print("\n" + "="*70)
    print("  📊 先决条件诊断")
    print("="*70)

    hours_list = [s["hours_to_maturity"] for s in scenarios]
    print(f"\n【提前量分布】(共 {len(hours_list)} 个快照)")
    for lo, hi, label in LEAD_TIME_BUCKETS:
        cnt = sum(1 for h in hours_list if lo < h <= hi)
        pct = cnt / len(hours_list) * 100 if hours_list else 0
        bar = "█" * int(pct / 2)
        print(f"  {label:9s}: {cnt:4d} 个 ({pct:5.1f}%) {bar}")

    markets = defaultdict(int)
    for s in scenarios:
        markets[s["market_id"]] += 1
    counts = sorted(markets.values(), reverse=True)
    print(f"\n【每市场快照数】(共 {len(markets)} 个市场)")
    print(f"  最多: {counts[0]}  中位数: {counts[len(counts)//2]}  最少: {counts[-1]}")

    all_range_counts = [len(s["ranges"]) for s in scenarios if s["ranges"]]
    avg_n = np.mean(all_range_counts) if all_range_counts else 15
    uniform_bs = 1.0 - 1.0 / avg_n
    print(f"\n【均匀分布基准】平均区间数 N={avg_n:.1f}，均匀 BS ≈ {uniform_bs:.4f}")
    print("="*70)
    return uniform_bs


# ════════════════════════════════════════════════════════════════════════════
# 第三步（前置）：一次性预热 BiasCorrector 历史数据缓存
# ════════════════════════════════════════════════════════════════════════════

def prefetch_bias_cache(scenarios):
    """
    在主标定循环开始前，一次性为所有 (station_id, target_date, is_lowest) 组合
    触发 BiasCorrector，把所有缺失的历史气象数据（Open-Meteo + Wunderground）
    批量写入 weather_daily_cache。

    执行完毕后，主循环中的所有 Analyst 调用均可完全离线运行（全部命中缓存）。
    """
    from src.analyst import resolve_station_coordinates
    from src.bias_corrector import get_bias_corrector

    # 收集所有唯一的 (station_id, target_date, is_lowest) 组合
    unique_combos = {}
    for s in scenarios:
        key = (s["station_id"], s["settlement_date"], s["is_lowest"])
        if key not in unique_combos:
            unique_combos[key] = s["timezone_str"]

    print(f"\n" + "="*70)
    print(f"  🌐 [数据预热] 一次性拉取 BiasCorrector 所需历史气象数据")
    print(f"  目标: {len(unique_combos)} 个唯一 (站点, 结算日, 最高/低) 组合")
    print(f"  完成后主标定循环将完全离线运行")
    print("="*70)

    corrector = get_bias_corrector(
        CONFIG.get("risk_control_lock", {}).get("bias_corrector_class", "MovingWindowBiasCorrector")
    )
    window_days = CONFIG.get("risk_control_lock", {}).get("bias_window_days", 7)

    done = 0
    fetched = 0
    errors = 0

    for (station_id, target_date, is_lowest), timezone_str in unique_combos.items():
        done += 1
        try:
            lat, lon = resolve_station_coordinates(station_id)
            bias, rolling_std = corrector.get_bias(
                station_id=station_id,
                lat=lat,
                lon=lon,
                timezone=timezone_str,
                target_date=target_date,
                is_lowest=bool(is_lowest),
                window_days=window_days,
            )
            fetched += 1
            print(f"  [{done:3d}/{len(unique_combos)}] {station_id} {target_date} "
                  f"({'最低' if is_lowest else '最高'}) "
                  f"→ bias={bias:+.3f}°C, rolling_σ={rolling_std:.3f}°C" if rolling_std is not None
                  else f"  [{done:3d}/{len(unique_combos)}] {station_id} {target_date} "
                  f"({'最低' if is_lowest else '最高'}) → bias={bias:+.3f}°C, rolling_σ=None",
                  flush=True)
        except Exception as e:
            errors += 1
            print(f"  [{done:3d}/{len(unique_combos)}] ⚠️  {station_id} {target_date} 失败: {e}", flush=True)

    print(f"\n[+] 数据预热完成！成功: {fetched}，失败: {errors}")
    print(f"    后续所有 Analyst 调用将从本地缓存读取，无需联网。")
    print("="*70)


# ════════════════════════════════════════════════════════════════════════════
# 第三步：运行 Analyst
# ════════════════════════════════════════════════════════════════════════════

def run_analyst_on_archive(archive_path, s_mid, timezone_str):
    os.makedirs(TEMP_DIR, exist_ok=True)

    try:
        with open(archive_path, "r", encoding="utf-8") as f:
            archive_data = json.load(f)
    except Exception:
        return None

    raw_forecast    = archive_data.get("raw_data", {}).get("raw_forecast")
    raw_observed    = archive_data.get("raw_data", {}).get("raw_observed")
    market_snapshot = archive_data.get("raw_data", {}).get("market_snapshot")

    if not raw_forecast or not market_snapshot:
        return None

    market_id = market_snapshot.get("market_id", "")
    temp_snap_path = os.path.join(TEMP_DIR, f"market_snapshot_{market_id}.json")
    try:
        with open(temp_snap_path, "w", encoding="utf-8") as f:
            json.dump(market_snapshot, f, ensure_ascii=False)
    except Exception:
        return None

    archive_dt_utc = get_archive_timestamp(archive_path)
    if not archive_dt_utc:
        return None
    try:
        tz = pytz.timezone(timezone_str)
        mock_dt = pytz.utc.localize(archive_dt_utc).astimezone(tz)
    except Exception:
        mock_dt = pytz.utc.localize(archive_dt_utc)

    class MockDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                return mock_dt.astimezone(tz)
            return mock_dt

    old_risk_config = dict(CONFIG.get("risk_control_lock", {}))
    CONFIG["risk_control_lock"] = dict(old_risk_config)
    CONFIG["risk_control_lock"]["obs_error_sigma_baseline_mid_lat"] = s_mid
    CONFIG["risk_control_lock"]["obs_error_sigma_baseline_tropics"] = max(0.4, min(1.0, 0.8 * s_mid))

    old_protocols_dir = analyst_module.PROTOCOLS_DIR
    analyst_module.PROTOCOLS_DIR = TEMP_DIR

    if isinstance(raw_observed, (int, float)):
        obs_list = [{"local_time": "2026-01-01 12:00:00", "temp": float(raw_observed), "hour": 12}]
    elif isinstance(raw_observed, list):
        obs_list = raw_observed
    else:
        obs_list = []

    try:
        with patch("src.weather_cache.get_api_cache", return_value=raw_forecast), \
             patch("src.weather_cache.fetch_wunderground_hourly_observed_today", return_value=obs_list), \
             patch("src.analyst.datetime.datetime", MockDateTime):
            with patch("builtins.print"):
                prob_filename = analyze_single_market(temp_snap_path)

        if not prob_filename:
            return None

        prob_path = os.path.join(TEMP_DIR, prob_filename)
        if not os.path.exists(prob_path):
            return None

        with open(prob_path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:
        return None
    finally:
        CONFIG["risk_control_lock"] = old_risk_config
        analyst_module.PROTOCOLS_DIR = old_protocols_dir


# ════════════════════════════════════════════════════════════════════════════
# 第四步：Brier Score 计算
# ════════════════════════════════════════════════════════════════════════════

def compute_brier_score(prob_output, winner_cond):
    if not prob_output:
        return None

    # Analyst 输出契约中使用 probability_distribution 键，项中使用 calculated_prob
    prob_ranges = prob_output.get("probability_distribution", [])
    if not prob_ranges:
        prob_ranges = prob_output.get("ranges", [])
    if not prob_ranges:
        return None

    prob_map = {}
    for r in prob_ranges:
        cond = r.get("condition", "")
        prob = r.get("calculated_prob", r.get("probability", 0.0))
        if cond:
            prob_map[cond] = float(prob)

    if not prob_map:
        return None

    total_prob = sum(prob_map.values())
    if total_prob <= 0:
        return None
    prob_map = {k: v / total_prob for k, v in prob_map.items()}

    bs = sum((p - (1.0 if c == winner_cond else 0.0)) ** 2 for c, p in prob_map.items())

    # 若 winner_cond 不在 prob_map 里，补加惩罚项
    if winner_cond not in prob_map:
        bs += 1.0

    return bs


# ════════════════════════════════════════════════════════════════════════════
# 第五步：主标定流程
# ════════════════════════════════════════════════════════════════════════════

def _worker_run_analyst(args):
    ap, s_mid, tz_str = args
    prob_out = run_analyst_on_archive(ap, s_mid, tz_str)
    return ap, s_mid, prob_out

def run_brier_calibration(scenarios):
    from concurrent.futures import ProcessPoolExecutor, as_completed

    print("\n" + "="*70)
    print("  🔬 [阶段 1/2] 构建概率分布缓存 (多核 CPU 并行计算化)")
    print("="*70)

    unique_archives = {}
    for s in scenarios:
        ap = s["archive_path"]
        if ap not in unique_archives:
            unique_archives[ap] = s["timezone_str"]

    prob_cache = {s_mid: {} for s_mid in SIGMA_CANDIDATES}
    
    # 构造全量并发任务列表
    tasks = []
    for s_mid in SIGMA_CANDIDATES:
        for ap, tz_str in unique_archives.items():
            tasks.append((ap, s_mid, tz_str))

    total_tasks = len(tasks)
    cpu_count = max(1, os.cpu_count() - 1)
    print(f"[*] 启动 {cpu_count} 个 CPU 进程池并行加速，总任务数: {total_tasks}...")

    done = 0
    with ProcessPoolExecutor(max_workers=cpu_count) as executor:
        futures = [executor.submit(_worker_run_analyst, t) for t in tasks]
        for future in as_completed(futures):
            done += 1
            try:
                ap, s_mid, prob_out = future.result()
                prob_cache[s_mid][ap] = prob_out
            except Exception:
                pass
            if done % 1000 == 0 or done == total_tasks:
                print(f"  [进度] 多核计算已完成: {done}/{total_tasks} ({done/total_tasks*100:.1f}%)", flush=True)

    shutil.rmtree(TEMP_DIR, ignore_errors=True)

    print("\n" + "="*70)
    print("  📐 [阶段 2/2] 计算 Brier Score")
    print("="*70)

    results = {}
    for s_mid in SIGMA_CANDIDATES:
        bs_per_market = defaultdict(lambda: defaultdict(list))

        for scene in scenarios:
            ap     = scene["archive_path"]
            mid    = scene["market_id"]
            winner = scene["winner_cond"]
            hours  = scene["hours_to_maturity"]

            bs = compute_brier_score(prob_cache[s_mid].get(ap), winner)
            if bs is None:
                continue

            bucket = LEAD_TIME_BUCKETS[-1][2]
            for lo, hi, label in LEAD_TIME_BUCKETS:
                if lo < hours <= hi:
                    bucket = label
                    break

            bs_per_market[mid]["all"].append(bs)
            bs_per_market[mid][bucket].append(bs)

        # 两层聚合
        market_means = [np.mean(d["all"]) for d in bs_per_market.values() if d["all"]]
        bucket_means = defaultdict(list)
        for d in bs_per_market.values():
            for bkt, vals in d.items():
                if bkt != "all" and vals:
                    bucket_means[bkt].append(np.mean(vals))

        results[s_mid] = {
            "bs_avg":    np.mean(market_means) if market_means else None,
            "bs_by_lead": {bkt: np.mean(vals) for bkt, vals in bucket_means.items()},
            "n_markets": len(market_means),
            "n_valid":   sum(len(d["all"]) for d in bs_per_market.values()),
        }

    return results


# ════════════════════════════════════════════════════════════════════════════
# 第六步：输出报告
# ════════════════════════════════════════════════════════════════════════════

def print_results(results, uniform_bs):
    print("\n" + "="*70)
    print("  📋 Brier Score 标定结果")
    print("="*70)
    print(f"\n  均匀分布基准 BS ≈ {uniform_bs:.4f}")
    print()

    sorted_r = sorted(
        [(s, r) for s, r in results.items() if r["bs_avg"] is not None],
        key=lambda x: x[1]["bs_avg"]
    )

    best_sigma = sorted_r[0][0] if sorted_r else None

    print(f"  {'σ_mid':>6} | {'全局 BS':>10} | {'Δ vs均匀':>10} | {'有效快照':>8} | {'市场数':>6}")
    print(f"  {'─'*6}-+-{'─'*10}-+-{'─'*10}-+-{'─'*8}-+-{'─'*6}")
    for sigma, r in sorted_r:
        bs    = r["bs_avg"]
        delta = bs - uniform_bs
        flag  = " ★" if sigma == best_sigma else ""
        print(f"  {sigma:>6.2f} | {bs:>10.4f} | {delta:>+10.4f} | "
              f"{r['n_valid']:>8} | {r['n_markets']:>6}{flag}")

    # 提前量分层
    buckets = [lb for _, _, lb in LEAD_TIME_BUCKETS]
    print(f"\n  【按提前量分层】")
    print(f"  {'σ_mid':>6} | " + " | ".join(f"{b:>9}" for b in buckets))
    print(f"  {'─'*6}-+-" + "-+-".join("─"*9 for _ in buckets))
    for sigma, r in sorted_r:
        row = f"  {sigma:>6.2f} | "
        row += " | ".join(
            f"{r['bs_by_lead'].get(b, float('nan')):>9.4f}" for b in buckets
        )
        print(row)

    # 有效性判断
    print(f"\n  【有效性判断】")
    if len(sorted_r) >= 2:
        best_bs  = sorted_r[0][1]["bs_avg"]
        worst_bs = max(r["bs_avg"] for _, r in sorted_r)
        spread   = worst_bs - best_bs
        gap      = uniform_bs - best_bs

        print(f"  最优 σ_mid = {best_sigma:.2f}°C | BS = {best_bs:.4f}")
        print(f"  BS 极差（最优 vs 最差）: {spread:.4f}")
        print(f"  最优 BS 低于均匀基准: {gap:.4f}")

        if gap < 0.05:
            print("  ⚠️  模型预测力不显著（差距 < 0.05），σ_mid 可能未起保底作用。")
        elif spread < 0.01:
            print("  ⚠️  各 σ 候选值 BS 极差 < 0.01，σ_mid 对结果几乎无影响。")
        else:
            print("  ✅  Brier Score 有效区分了不同 σ_mid，标定结果可信。")

    print("="*70)
    return best_sigma


def main():
    print("="*70)
    print("  🎯 σ_mid Brier Score 标定")
    print("  设计文档: docs/brier_score_calibration_design.md")
    print("="*70)

    scenarios = build_valid_scenarios()
    if len(scenarios) < 10:
        print("[-] 有效场景不足 10 个，终止。")
        return

    uniform_bs = diagnose_prerequisites(scenarios)

    n_archives = len(set(s["archive_path"] for s in scenarios))
    print(f"\n[*] 将运行 {len(SIGMA_CANDIDATES)} × {n_archives} = "
          f"{len(SIGMA_CANDIDATES)*n_archives} 次 Analyst 调用")
    print(f"    σ 候选值: {SIGMA_CANDIDATES}")
    print("\n按 Enter 继续，Ctrl+C 取消...")
    try:
        input()
    except KeyboardInterrupt:
        print("\n已取消。")
        return

    # 数据预热：一次性拉取所有历史气象数据，后续全程离线
    prefetch_bias_cache(scenarios)

    results = run_brier_calibration(scenarios)
    best_sigma = print_results(results, uniform_bs)

    if best_sigma is not None:
        current = CONFIG.get("risk_control_lock", {}).get("obs_error_sigma_baseline_mid_lat", "N/A")
        print(f"\n  当前配置: σ_mid = {current}")
        print(f"  标定推荐: σ_mid = {best_sigma:.2f}°C")


if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    main()
