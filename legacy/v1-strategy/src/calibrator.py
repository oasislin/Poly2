import os
import sys
import json
import sqlite3
import datetime
import numpy as np

# 独立于交易逻辑的参数标定与联合优化程序

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

DB_PATH = os.path.join(BASE_DIR, "storage", "weather_cache.db")
CITIES_CONFIG_PATH = os.path.join(BASE_DIR, "config", "cities.json")
OUTPUT_PARAMS_PATH = os.path.join(BASE_DIR, "storage", "calibrated_params.json")

def load_cities():
    if os.path.exists(CITIES_CONFIG_PATH):
        try:
            with open(CITIES_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"警告: 加载 cities.json 失败: {e}")
    return {}

def main():
    print("=" * 80)
    print("               📈 Polymarket 天气套利策略：参数标定与联合优化程序")
    print("=" * 80)
    
    if not os.path.exists(DB_PATH):
        print(f"错误: 未找到 SQLite 天气数据库: {DB_PATH}")
        print("请先运行 python -m src.backfill 或流水线填充缓存数据。")
        return
        
    cities = load_cities()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. 检查数据概况
    try:
        cursor.execute("SELECT count(*) FROM weather_daily_cache")
        total_records = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM weather_daily_cache WHERE obs_extreme IS NOT NULL")
        labeled_records = cursor.fetchone()[0]
        print(f"[*] 数据库总记录数: {total_records}，其中含有实况观测的有效样本数: {labeled_records}")
    except Exception as e:
        print(f"错误: 读取 weather_daily_cache 表结构异常: {e}")
        conn.close()
        return

    # 2. 读取全部有效数据
    query = """
    SELECT station_id, date, is_lowest, mean_forecast_extreme, obs_extreme 
    FROM weather_daily_cache 
    WHERE obs_extreme IS NOT NULL AND mean_forecast_extreme IS NOT NULL
    ORDER BY station_id, date ASC
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()
    
    if len(rows) < 10:
        print("[-] 样本数据过少，无法进行有统计学意义的参数标定。请运行 python -m src.backfill --days 30 积累数据。")
        return

    # 组织数据结构
    # data[station_id][is_lowest] = [(date, forecast, observed)]
    data = {}
    for row in rows:
        st_id, dt_str, is_lowest, f_val, o_val = row
        st_id = st_id.upper()
        if st_id not in data:
            data[st_id] = {0: [], 1: []} # 0 for highest, 1 for lowest
        data[st_id][is_lowest].append((dt_str, f_val, o_val))

    # 3. 物理层标定：自适应纠偏窗口 bias_window_days 的网格搜索
    print("\n[1] 正在通过滚动模拟寻找最佳自适应纠偏窗口 'bias_window_days' (网格搜索区间: 3-7天)...")
    window_options = list(range(3, 8))
    window_mae = {w: [] for w in window_options}
    window_rmse = {w: [] for w in window_options}
    
    valid_series_count = 0
    
    for st_id, sub in data.items():
        for is_lowest in [0, 1]:
            series = sub[is_lowest]
            if len(series) < 6:
                continue
            valid_series_count += 1
            
            for w in window_options:
                errors = []
                for idx in range(w, len(series)):
                    past_residuals = [series[i][2] - series[i][1] for i in range(idx - w, idx)]
                    avg_bias = np.mean(past_residuals)
                    
                    curr_forecast = series[idx][1]
                    curr_observed = series[idx][2]
                    corrected_forecast = curr_forecast + avg_bias
                    
                    err = curr_observed - corrected_forecast
                    errors.append(err)
                
                if errors:
                    mae = np.mean(np.abs(errors))
                    rmse = np.sqrt(np.mean(np.array(errors) ** 2))
                    window_mae[w].append(mae)
                    window_rmse[w].append(rmse)
                    
    print(f"[*] 参与窗口评估的有效气象站时间序列数量: {valid_series_count}")
    
    optimal_window = 7
    min_overall_mae = float('inf')
    
    print("-" * 60)
    print(f"{'窗口大小 (天)':^15} | {'平均绝对误差 (MAE)':^20} | {'均方根误差 (RMSE)':^20}")
    print("-" * 60)
    for w in window_options:
        if window_mae[w]:
            avg_mae = np.mean(window_mae[w])
            avg_rmse = np.mean(window_rmse[w])
            print(f"{w:^15d} | {avg_mae:^20.4f} | {avg_rmse:^20.4f}")
            if avg_mae < min_overall_mae:
                min_overall_mae = avg_mae
                optimal_window = w
        else:
            print(f"{w:^15d} | {'数据不足':^20} | {'数据不足':^20}")
    print("-" * 60)
    print(f"[+] 推荐全局最优纠偏窗口 (bias_window_days): {optimal_window} 天 (此时 MAE 达到最小值: {min_overall_mae:.4f}°C)")

    # 4. 静态预报噪声基准标定（按气候区）
    print("\n[2] 正在标定静态兜底噪声基准标定值 (20th Percentile Rule)...")
    raw_errors = []
    zone_errors = {"mid_lat": [], "tropics": []}
    rolling_sigmas_by_zone = {"mid_lat": [], "tropics": []}
    
    for st_id, sub in data.items():
        st_info = cities.get(st_id, {})
        climate_zone = st_info.get("climate_zone", "mid_lat")
        if climate_zone not in rolling_sigmas_by_zone:
            climate_zone = "mid_lat"
            
        for is_lowest in [0, 1]:
            series = sub[is_lowest]
            residuals = [s[2] - s[1] for s in series]
            raw_errors.extend(residuals)
            zone_errors[climate_zone].extend(residuals)
            
            if len(series) >= optimal_window + 2:
                for idx in range(optimal_window, len(series)):
                    past_residuals = [series[i][2] - series[i][1] for i in range(idx - optimal_window, idx)]
                    r_std = np.std(past_residuals, ddof=1) if len(past_residuals) > 1 else 0.5
                    rolling_sigmas_by_zone[climate_zone].append(r_std)

    obs_error_sigma_0 = np.std(raw_errors, ddof=1) if len(raw_errors) > 1 else 0.6
    
    print("-" * 80)
    print(f"{'气候分区':^12} | {'样本量':^8} | {'均值 Bias':^12} | {'标准差 Std':^12} | {'建议基准下限 (20th Pctl)':^25}")
    print("-" * 80)
    
    calibrated_baselines = {}
    for zone in ["mid_lat", "tropics"]:
        errors = zone_errors[zone]
        rolling_sigmas = rolling_sigmas_by_zone[zone]
        
        if len(errors) > 1:
            mean_bias = np.mean(errors)
            std_dev = np.std(errors, ddof=1)
            suggested_baseline = np.percentile(rolling_sigmas, 20) if len(rolling_sigmas) > 5 else (std_dev * 0.7)
            suggested_baseline = max(0.4, min(1.5, suggested_baseline))
            calibrated_baselines[zone] = suggested_baseline
            print(f"{zone:^12} | {len(errors):^8d} | {mean_bias:^+12.4f} | {std_dev:^12.4f} | {suggested_baseline:^25.4f}°C")
        else:
            print(f"{zone:^12} | {'无数据':^8} | {'-':^12} | {'-':^12} | {'-':^25}")
            calibrated_baselines[zone] = 1.0 if zone == "mid_lat" else 0.8
    print("-" * 80)

    # 5. 提示用户可通过 scratch/calibrate_sigma_brier.py 运行完整 Brier Score 重放测试
    print("\n[3] 物理 Brier Score 重放诊断与金融 Sizing 寻优指引:")
    print("  - 若需对历史 Snapshot 快照执行极精细的多 Candidate σ Brier Score 重放评估，")
    print("    请直接运行: python scratch/calibrate_sigma_brier.py")

    # 6. 写入 calibrated_params.json
    output_params = {
        "calibrated_at": datetime.now().isoformat() if 'datetime' in locals() and hasattr(datetime, 'now') else datetime.datetime.now().isoformat(),
        "total_samples": len(rows),
        "bias_window_days": int(optimal_window),
        "obs_error_sigma_0": round(float(obs_error_sigma_0), 4),
        "obs_error_sigma_baseline_mid_lat": round(float(calibrated_baselines.get("mid_lat", 1.2)), 4),
        "obs_error_sigma_baseline_tropics": round(float(calibrated_baselines.get("tropics", 0.8)), 4),
        "robust_kelly_theta": 1.5,
        "uncertainty_eta": 0.15
    }
    
    with open(OUTPUT_PARAMS_PATH, "w", encoding="utf-8") as f:
        json.dump(output_params, f, indent=2, ensure_ascii=False)
        
    print(f"\n[+] 标定成功！标定结果已更新至: {OUTPUT_PARAMS_PATH}")
    print("=" * 80)

if __name__ == "__main__":
    main()
