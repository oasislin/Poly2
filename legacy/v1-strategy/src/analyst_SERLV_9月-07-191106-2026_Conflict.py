import os
import json
import time
import requests
import datetime
import glob
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.config import CONFIG, PROXIES, validate_contract, setup_logger, load_custom_station_mappings, add_pending_station
from src.bias_corrector import get_bias_corrector
import src.weather_cache as weather_cache

logger = setup_logger("Analyst")

PROTOCOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocols")
STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage")
CACHE_PATH = os.path.join(STORAGE_DIR, "station_cache.json")

FALLBACK_STATION_MAP = {
    "RKSI": {"lat": 37.469, "lon": 126.451, "city": "Incheon", "timezone": "Asia/Seoul"},
    "KNYC": {"lat": 40.782, "lon": -73.965, "city": "New York", "timezone": "America/New_York"},
    "EGLL": {"lat": 51.470, "lon": -0.454, "city": "London", "timezone": "Europe/London"},
    "RJTT": {"lat": 35.552, "lon": 139.780, "city": "Tokyo", "timezone": "Asia/Tokyo"},
    "VHHH": {"lat": 22.308, "lon": 113.918, "city": "Hong Kong", "timezone": "Asia/Hong_Kong"},
    "ZSSS": {"lat": 31.198, "lon": 121.336, "city": "Shanghai", "timezone": "Asia/Shanghai"},
    
    # 解决 Polymarket 对赌协议描述中写错的非标准 ICAO 代码 ( typos )
    "ATLA": {"lat": 33.640, "lon": -84.428, "city": "Atlanta", "timezone": "America/New_York"},
    "HOUS": {"lat": 29.645, "lon": -95.279, "city": "Houston", "timezone": "America/Chicago"},
    "CHIC": {"lat": 41.974, "lon": -87.907, "city": "Chicago", "timezone": "America/Chicago"},
    "AUST": {"lat": 30.194, "lon": -97.670, "city": "Austin", "timezone": "America/Chicago"},
    "DENV": {"lat": 39.856, "lon": -104.673, "city": "Denver", "timezone": "America/Denver"},
    "AURO": {"lat": 39.856, "lon": -104.673, "city": "Denver", "timezone": "America/Denver"},
    "MIAI": {"lat": 25.793, "lon": -80.290, "city": "Miami", "timezone": "America/New_York"},
    "MIAM": {"lat": 25.793, "lon": -80.290, "city": "Miami", "timezone": "America/New_York"},
    "SEAT": {"lat": 47.448, "lon": -122.309, "city": "Seattle", "timezone": "America/Los_Angeles"},
    "DALL": {"lat": 32.899, "lon": -97.040, "city": "Dallas", "timezone": "America/Chicago"}
}

def resolve_station_coordinates(station_id):
    station_id = station_id.upper().strip()
    
    try:
        from src.config import load_cities_config
        cities = load_cities_config()
        if station_id in cities:
            info = cities[station_id]
            if info.get("lat") and info.get("lon"):
                return float(info["lat"]), float(info["lon"])
    except Exception:
        pass
        
    # 优先匹配用户自定义的手动映射配置
    custom_mappings = load_custom_station_mappings()
    if station_id in custom_mappings:
        info = custom_mappings[station_id]
        if "lat" in info and "lon" in info:
            return info["lat"], info["lon"]

    cache = {}
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                cache = json.load(f)
            if station_id in cache:
                return cache[station_id]["lat"], cache[station_id]["lon"]
        except Exception:
            pass
            
    awc_url = CONFIG["network_gateway"].get("aviation_weather_url", "https://aviationweather.gov/api/data/stationinfo")
    url = f"{awc_url}?ids={station_id}&format=json"
    
    try:
        headers = {"User-Agent": "WeatherArbitrageBot/1.0.0 (huhuh@gemini.antigravity)"}
        response = requests.get(url, headers=headers, proxies=PROXIES, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            station_info = None
            if isinstance(data, list) and len(data) > 0:
                station_info = data[0]
            elif isinstance(data, dict):
                station_info = data
                
            if station_info and "lat" in station_info and "lon" in station_info:
                lat = float(station_info["lat"])
                lon = float(station_info["lon"])
                
                # 读取最新并写入缓存
                try:
                    if os.path.exists(CACHE_PATH):
                        with open(CACHE_PATH, "r", encoding="utf-8") as f:
                            cache = json.load(f)
                except Exception:
                    cache = {}
                cache[station_id] = {"lat": lat, "lon": lon, "updated_at": int(time.time())}
                os.makedirs(STORAGE_DIR, exist_ok=True)
                with open(CACHE_PATH, "w", encoding="utf-8") as f:
                    json.dump(cache, f, indent=2)
                    
                return lat, lon
    except Exception:
        pass

    if station_id in FALLBACK_STATION_MAP:
        info = FALLBACK_STATION_MAP[station_id]
        return info["lat"], info["lon"]

    # 解析失败，抛出错误前计入人工干预列表
    add_pending_station(station_id, "", "missing_coordinates", "无法通过民航天气网解析该气象站坐标，且系统无兜底映射")
    raise ValueError(f"无法解析气象站 {station_id} 的地理坐标，且无预置兜底！")

def check_condition(temp, condition_str):
    condition_str = condition_str.strip().replace(" ", "")
    try:
        if condition_str.startswith("<="):
            limit = float(condition_str[2:])
            return temp <= limit
        elif condition_str.startswith(">="):
            limit = float(condition_str[2:])
            return temp >= limit
        elif condition_str.startswith("<"):
            limit = float(condition_str[1:])
            return temp < limit
        elif condition_str.startswith(">"):
            limit = float(condition_str[1:])
            return temp > limit
        elif "-" in condition_str:
            parts = condition_str.split("-")
            low = float(parts[0])
            high = float(parts[1])
            return low <= temp <= high
        else:
            return temp == float(condition_str)
    except Exception as e:
        logger.error(f"解析气温条件错误: {condition_str}, 详情: {str(e)}", extra={"market_id": "ANALYST"})
    return False

def analyze_single_market(snapshot_path):
    with open(snapshot_path, "r", encoding="utf-8") as f:
        snapshot = json.load(f)
        
    try:
        validate_contract(snapshot, "market_snapshot")
    except Exception as e:
        logger.error(f"快照文件 {snapshot_path} 校验失败，跳过分析！错误: {str(e)}", extra={"market_id": "ANALYST"})
        return None

    market_id = snapshot["market_id"]
    status = snapshot.get("status", "active")
    if status != "active":
        logger.info(f"跳过 inactive/时间过滤 的快照分析: {market_id}", extra={"market_id": market_id})
        return None
        
    station_id = snapshot["station_info"]["station_id"]
    target_date = snapshot["target_date"]
    timezone = snapshot["station_info"]["timezone"]
    precision = snapshot["resolution_precision"]
    ranges = snapshot["ranges"]

    # 1. 获取坐标
    try:
        lat, lon = resolve_station_coordinates(station_id)
    except Exception as e:
        logger.error(f"气象站 {station_id} 经纬度解析失败，跳过该城市分析！错误: {str(e)}", extra={"market_id": market_id})
        return None

    # 2. 调用 Open-Meteo Ensemble
    open_meteo_url = CONFIG["network_gateway"].get("open_meteo_url", "https://ensemble-api.open-meteo.com/v1/ensemble")
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m",
        "models": "icon_seamless",
        "timezone": timezone
    }
    
    import random
    max_retries = 5
    # 优先读取本地 API 缓存 (缓存有效期 30 分钟)
    forecast_data = weather_cache.get_api_cache(open_meteo_url, params)
    
    if not forecast_data:
        # 礼貌性延迟，降低请求速率，彻底规避 429 限频
        time.sleep(0.5)
        
        for attempt in range(max_retries):
            try:
                # 随机小抖动
                time.sleep(random.uniform(0.1, 0.3) * attempt)
                response = requests.get(open_meteo_url, params=params, proxies=PROXIES, timeout=15)
                if response.status_code == 429:
                    logger.warning(f"触发 Open-Meteo 频控 (429)，开始第 {attempt+1} 次重试...", extra={"market_id": market_id})
                    time.sleep(1.5 * (attempt + 1))
                    continue
                if response.status_code == 400:
                    err_text = response.text
                    if "Invalid timezone" in err_text:
                        add_pending_station(station_id, snapshot["station_info"]["city"], "invalid_timezone", f"Open-Meteo 接口不支持当前配置时区 ({timezone})。建议人工核实并变更为受支持的代表城市时区（如 Europe/Berlin 等）。")
                    else:
                        add_pending_station(station_id, snapshot["station_info"]["city"], "invalid_params", f"Open-Meteo 接口请求参数有误: {err_text}")
                    raise RuntimeError(f"Open-Meteo 返回 HTTP 400 错误: {err_text}")
                if response.status_code != 200:
                    raise RuntimeError(f"Open-Meteo API 返回非200状态码: {response.status_code}")
                forecast_data = response.json()
                weather_cache.save_api_cache(open_meteo_url, params, forecast_data)
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"请求气象 API 异常，跳过该城市分析！错误: {str(e)}", extra={"market_id": market_id})
                    return None
                time.sleep(1.0 * (attempt + 1))
            
    if not forecast_data:
        return None

    hourly = forecast_data.get("hourly", {})
    times = hourly.get("time", [])
    
    target_indices = [idx for idx, t_str in enumerate(times) if t_str.startswith(target_date)]
    if not target_indices:
        logger.error(f"未在预报中找到日期 {target_date}，跳过分析！", extra={"market_id": market_id})
        return None

    is_lowest = "lowest" in market_id.lower()
    
    import numpy as np
    import pytz
    
    # 动态解析时区并计算当前时间
    try:
        tz = pytz.timezone(timezone)
        station_now = datetime.datetime.now(tz)
    except Exception:
        station_now = datetime.datetime.now(datetime.timezone.utc)
    station_today_str = station_now.strftime("%Y-%m-%d")
    
    # 计算提前天数（Lead Days）以实现时效衰减
    try:
        target_dt = datetime.datetime.strptime(target_date, "%Y-%m-%d").date()
        station_dt = station_now.date()
        lead_days = max(0, (target_dt - station_dt).days)
    except Exception:
        lead_days = 0

    risk_config = CONFIG.get("risk_control_lock", {})
    obs_error_sigma_0 = risk_config.get("obs_error_sigma_0", 0.6)
    lead_time_decay_beta = risk_config.get("lead_time_decay_beta", 0.15)
    mc_samples_per_member = risk_config.get("mc_samples_per_member", 100)
    
    # 动态获取纠偏器并计算偏置纠正量与滚动残差标准差
    bias = 0.0
    rolling_sigma = None
    bias_corrector_class = risk_config.get("bias_corrector_class", "MovingWindowBiasCorrector")
    bias_window_days = risk_config.get("bias_window_days", 7)
    
    try:
        corrector = get_bias_corrector(bias_corrector_class)
        bias, rolling_sigma = corrector.get_bias(
            station_id=station_id,
            lat=lat,
            lon=lon,
            timezone=timezone,
            target_date=target_date,
            is_lowest=is_lowest,
            window_days=bias_window_days
        )
    except Exception as ex:
        logger.warning(f"自适应纠偏与标准差计算失败, 降级为默认。错误: {ex}", extra={"market_id": market_id})
        
    # 如果获取到了滚动标准差，使用其作为基准不确定性；否则使用静态配置 obs_error_sigma_0 作为兜底
    if rolling_sigma is not None:
        sigma = rolling_sigma * (1.0 + lead_time_decay_beta * lead_days)
        logger.info(f"时效衰减计算 (滚动自适应): 提前天数={lead_days}, 滚动基准偏差={rolling_sigma:.3f}°C, 噪声标准差 σ={sigma:.3f}°C", extra={"market_id": market_id})
    else:
        sigma = obs_error_sigma_0 * (1.0 + lead_time_decay_beta * lead_days)
        logger.info(f"时效衰减计算 (静态兜底): 提前天数={lead_days}, 兜底基准偏差={obs_error_sigma_0:.3f}°C, 噪声标准差 σ={sigma:.3f}°C", extra={"market_id": market_id})
        
    logger.info(f"偏置修正计算: 注入偏移量 Bias={bias:+.3f}°C", extra={"market_id": market_id})

    # Phase III 决战窗口：提取今日已发生的实况极值进行单向约束 (优先使用 Wunderground)
    obs_temp_so_far = None
    if target_date == station_today_str:
        obs_temp_so_far = weather_cache.fetch_wunderground_observed_today(station_id, is_lowest, timezone)
        if obs_temp_so_far is not None:
            logger.info(f"【Phase III 决战窗口】[Wunderground] 今日已发生气温极端值 (Observed So Far): {obs_temp_so_far:.2f}°C", extra={"market_id": market_id})
        else:
            logger.warning(f"【Phase III 决战窗口】从 Wunderground 获取实况极值失败，降级使用 Open-Meteo 历史预报估算今日实况...", extra={"market_id": market_id})
            past_indices = []
            station_now_str = station_now.strftime("%Y-%m-%dT%H:%M")
            for idx in target_indices:
                t_str = times[idx]
                if t_str <= station_now_str:
                    past_indices.append(idx)
            if past_indices:
                control_temps = hourly.get("temperature_2m", [])
                past_temps = [control_temps[idx] for idx in past_indices if control_temps[idx] is not None]
                if past_temps:
                    obs_temp_so_far = min(past_temps) if is_lowest else max(past_temps)
                    logger.info(f"【Phase III 降级估算】今日已发生气温极端值 (Observed So Far): {obs_temp_so_far:.2f}°C", extra={"market_id": market_id})

    member_keys = ["temperature_2m"] + [f"temperature_2m_member{i:02d}" for i in range(1, 40)]
    raw_forecast_temps = []
    
    for m_key in member_keys:
        if m_key not in hourly:
            continue
        m_temps = hourly[m_key]
        day_temps = [m_temps[idx] for idx in target_indices if m_temps[idx] is not None]
        if day_temps:
            target_val = min(day_temps) if is_lowest else max(day_temps)
            raw_forecast_temps.append(target_val)
            
    total_effective = len(raw_forecast_temps)
    if total_effective == 0:
        logger.error("无有效温度预报数据，跳过分析！", extra={"market_id": market_id})
        return None

    # 运行蒙特卡洛噪声重采样
    np.random.seed(42)  # 固定种子以保证计算可复现
    simulated_settled_temps = []
    
    for tj in raw_forecast_temps:
        noise = np.random.normal(0, sigma, mc_samples_per_member)
        sim_temps = tj + noise + bias
        
        # 注入 Phase III 实况极值约束
        if obs_temp_so_far is not None:
            if is_lowest:
                sim_temps = np.minimum(sim_temps, obs_temp_so_far)
            else:
                sim_temps = np.maximum(sim_temps, obs_temp_so_far)
                
        # 按照结算精度对模拟值向下取整 (Floor)
        for t_val in sim_temps:
            if precision == "INT_FAHRENHEIT":
                t_f = t_val * 9.0 / 5.0 + 32.0
                t_settle = int(np.floor(t_f))
            elif precision == "INT_CELSIUS":
                t_settle = int(np.floor(t_val))
            else:
                t_settle = t_val
            simulated_settled_temps.append(t_settle)

    total_simulations = len(simulated_settled_temps)
    
    # 模拟胜率与概率估计的标准差
    probability_distribution = []
    for r in ranges:
        cond = r["condition"]
        matching_count = sum(1 for temp in simulated_settled_temps if check_condition(temp, cond))
        prob = matching_count / total_simulations
        std_err = np.sqrt(prob * (1.0 - prob) / total_simulations)
        
        probability_distribution.append({
            "condition": cond,
            "calculated_prob": round(prob, 4),
            "standard_error": round(float(std_err), 6)
        })

    # 为看板/调试提供经过单位转换的基准预报（保持兼容性）
    calibrated_raw_temps = []
    for t_val in raw_forecast_temps:
        if precision == "INT_FAHRENHEIT":
            calibrated_raw_temps.append(round(t_val * 9 / 5 + 32))
        elif precision == "INT_CELSIUS":
            calibrated_raw_temps.append(round(t_val))
        else:
            calibrated_raw_temps.append(t_val)

    prob_data = {
        "protocol_version": CONFIG["version"],
        "timestamp": int(time.time()),
        "market_id": market_id,
        "target_date": target_date,
        "total_effective_members": total_effective,
        "probability_distribution": probability_distribution,
        "_raw_member_temps": calibrated_raw_temps,
        "_simulated_sigma": round(float(sigma), 4),
        "_raw_open_meteo_response": forecast_data,
        "_raw_wunderground_observed": obs_temp_so_far
    }

    try:
        validate_contract(prob_data, "weather_probability")
        prob_path = os.path.join(PROTOCOLS_DIR, f"weather_probability_{market_id}.json")
        with open(prob_path, "w", encoding="utf-8") as f:
            json.dump(prob_data, f, indent=2, ensure_ascii=False)
        logger.info(f"分析完成，契约已写入 {prob_path}", extra={"market_id": market_id})
        return f"weather_probability_{market_id}.json"
    except Exception as e:
        logger.error(f"胜率契约校验失败！错误: {str(e)}", extra={"market_id": market_id})
        return None

def run_analyst():
    """
    使用 ThreadPoolExecutor 多线程并发拉取天气并分析 (大幅提高效率)
    """
    logger.info("启动多城市天气分析器 (并发模式)...", extra={"market_id": "ANALYST"})
    
    snapshot_files = glob.glob(os.path.join(PROTOCOLS_DIR, "market_snapshot_*.json"))
    if not snapshot_files:
        logger.warning("未在 protocols/ 目录下发现任何活跃的 market_snapshot 协议文件，退出分析。", extra={"market_id": "ANALYST"})
        return

    active_prob_files = []
    
    # 使用单线程顺序拉取数据（礼貌下发，完全杜绝 429 报错，计算部分为纯 CPU 操作已足够高效）
    with ThreadPoolExecutor(max_workers=1) as executor:
        futures = {executor.submit(analyze_single_market, fpath): fpath for fpath in snapshot_files}
        for fut in as_completed(futures):
            fpath = futures[fut]
            try:
                prob_file = fut.result()
                if prob_file:
                    active_prob_files.append(prob_file)
            except Exception as e:
                logger.error(f"分析文件 {os.path.basename(fpath)} 发生未捕获异常: {str(e)}", extra={"market_id": "ANALYST"})
            
    # 清理旧的概率协议文件
    all_prob_files = glob.glob(os.path.join(PROTOCOLS_DIR, "weather_probability_*.json"))
    for fpath in all_prob_files:
        fname = os.path.basename(fpath)
        if fname not in active_prob_files:
            try:
                os.remove(fpath)
            except Exception:
                pass
                
    legacy_prob = os.path.join(PROTOCOLS_DIR, "weather_probability.json")
    if os.path.exists(legacy_prob):
        os.remove(legacy_prob)

if __name__ == "__main__":
    run_analyst()
