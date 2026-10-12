import os
import json
import time
import datetime
import argparse
import requests
import pytz
import glob
import numpy as np
from src.config import CONFIG, PROXIES, validate_contract, setup_logger, load_custom_station_mappings
from src.analyst import resolve_station_coordinates, check_condition

logger = setup_logger("BacktestLoader")

PROTOCOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocols")

# 复制自 scanner.py 以保持时区映射一致
TIMEZONE_MAP = {
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

def parse_weather_condition(question_text):
    """
    解析问题文本以提取温度条件。
    """
    # 提取数字
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

import re

def parse_station_icao_from_desc(description_text):
    match = re.search(r"daily/[a-z\-]+/([a-z\-]+)/([A-Z]{4})", description_text, re.IGNORECASE)
    if match:
        return match.group(2).upper()
    return None

def fetch_historical_markets(target_date):
    """
    拉取已关闭 Polymarket 天气合约（通过 end_date_min 和 end_date_max 精准限制时间范围以绕过 offset 分页限制）
    """
    gamma_url = CONFIG["network_gateway"].get("polymarket_gamma_url", "https://gamma-api.polymarket.com")
    matching_events = []
    
    logger.info(f"正在从 Polymarket 检索结算日为 {target_date} 的已关闭天气事件...", extra={"market_id": "BACKTEST"})
    
    try:
        target_dt = datetime.datetime.strptime(target_date, "%Y-%m-%d")
        min_dt = target_dt - datetime.timedelta(days=1)
        max_dt = target_dt + datetime.timedelta(days=1)
        end_date_min = min_dt.strftime("%Y-%m-%dT00:00:00Z")
        end_date_max = max_dt.strftime("%Y-%m-%dT23:59:59Z")
    except Exception as e:
        logger.error(f"解析目标日期错误: {e}", extra={"market_id": "BACKTEST"})
        return []
        
    url = f"{gamma_url}/events?closed=true&tag_id=84&end_date_min={end_date_min}&end_date_max={end_date_max}&limit=100"
    
    try:
        response = requests.get(url, proxies=PROXIES, timeout=10)
        if response.status_code != 200:
            logger.error(f"请求 Gamma 历史事件失败, 状态码: {response.status_code}", extra={"market_id": "BACKTEST"})
            return []
        
        events = response.json()
        if not events:
            return []
        
        for e in events:
            title = e.get("title", "")
            desc = e.get("description", "")
            if "temperature" in title.lower() or "temp" in title.lower():
                icao = parse_station_icao_from_desc(desc)
                if icao:
                    event_date = e.get("eventDate", "")
                    if not event_date:
                        date_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", title)
                        if date_match:
                            event_date = date_match.group(0)
                    if event_date == target_date:
                        matching_events.append((e, icao))
    except Exception as e:
        logger.error(f"请求 Gamma 异常: {str(e)}", extra={"market_id": "BACKTEST"})
        
    logger.info(f"成功找到 {len(matching_events)} 个符合条件的已关闭天气事件。", extra={"market_id": "BACKTEST"})
    return matching_events

def fetch_historical_price(token_id, target_timestamp):
    """
    调用 CLOB /prices-history 获取 token 在决策时间点附近的成交价
    """
    clob_url = CONFIG["network_gateway"].get("polymarket_clob_url", "https://clob.polymarket.com")
    # 检索决策时间前后 12 小时的 1 小时级别 K 线
    start_ts = target_timestamp - 43200
    end_ts = target_timestamp + 43200
    url = f"{clob_url}/prices-history?market={token_id}&startTs={start_ts}&endTs={end_ts}&fidelity=60"
    
    try:
        response = requests.get(url, proxies=PROXIES, timeout=10)
        if response.status_code == 200:
            data = response.json()
            history = data.get("history", [])
            if history:
                # 寻找最接近决策时间戳的烛线
                closest = min(history, key=lambda x: abs(x["t"] - target_timestamp))
                return float(closest["p"])
    except Exception as e:
        logger.warning(f"拉取 token {token_id} 历史价格失败，尝试降级。错误: {e}", extra={"market_id": "BACKTEST"})
    
    return None

def fetch_historical_forecast(lat, lon, target_date, timezone):
    """
    调用 Open-Meteo Historical Forecast API，拉取对应站点的 ICON 预报数据
    """
    url = "https://historical-forecast-api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": target_date,
        "end_date": target_date,
        "hourly": "temperature_2m",
        "models": "icon_seamless",
        "timezone": timezone
    }
    
    # 礼貌延迟，防止 429
    time.sleep(0.5)
    
    try:
        response = requests.get(url, params=params, proxies=PROXIES, timeout=15)
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Open-Meteo 历史接口返回非200状态码: {response.status_code}", extra={"market_id": "BACKTEST"})
    except Exception as e:
        logger.error(f"请求 Open-Meteo 历史预报异常: {str(e)}", extra={"market_id": "BACKTEST"})
    return None

def run_backtest_load(target_date):
    """
    历史数据加载主流程
    """
    logger.info(f"============ 启动历史数据加载器: 目标日期 {target_date} ============", extra={"market_id": "BACKTEST"})
    
    # 解析决策时间戳 (T-1日 10:00:00 UTC)
    try:
        target_dt = datetime.datetime.strptime(target_date, "%Y-%m-%d")
        decision_dt = target_dt - datetime.timedelta(days=1)
        # 固定在决策日的 10:00 UTC 附近
        decision_dt = decision_dt.replace(hour=10, minute=0, second=0, tzinfo=datetime.timezone.utc)
        target_timestamp = int(decision_dt.timestamp())
    except Exception as e:
        logger.error(f"日期解析失败: {str(e)}", extra={"market_id": "BACKTEST"})
        return
        
    events = fetch_historical_markets(target_date)
    if not events:
        logger.warning(f"在 {target_date} 未找到任何已关闭的天气对赌事件，退出。", extra={"market_id": "BACKTEST"})
        return

    # 合并自定义时区映射
    custom_mappings = load_custom_station_mappings()
    timezone_map = dict(TIMEZONE_MAP)
    for s_id, m in custom_mappings.items():
        if "timezone" in m:
            timezone_map[s_id.upper()] = m["timezone"]

    os.makedirs(PROTOCOLS_DIR, exist_ok=True)
    
    # 记录本轮生成的文件，以便后续清理
    generated_snapshots = []
    generated_probabilities = []

    for event, icao in events:
        icao = icao.upper().strip()
        slug = event["slug"]
        markets = event.get("markets", [])
        if not markets:
            continue
            
        logger.info(f"正在处理事件: {slug} | 气象站: {icao}", extra={"market_id": slug})
        
        # 1. 确定经纬度和时区
        try:
            lat, lon = resolve_station_coordinates(icao)
        except Exception as e:
            logger.error(f"无法获取气象站 {icao} 坐标，跳过此事件。错误: {e}", extra={"market_id": slug})
            continue
            
        timezone_str = timezone_map.get(icao, "UTC")
        
        # 2. 区分最高温/最低温及精度单位
        is_lowest = "lowest" in slug.lower()
        is_fahrenheit = False
        for m in markets:
            if "°f" in m["question"].lower() or " f " in m["question"].lower():
                is_fahrenheit = True
                break
        precision = "INT_FAHRENHEIT" if is_fahrenheit else "INT_CELSIUS"

        # 3. 逐个拉取档位价格 (CLOB T-1 价格)
        ranges = []
        for idx, m in enumerate(markets):
            condition = parse_weather_condition(m["question"])
            if not condition:
                continue
                
            # 解析 Token ID
            clob_tokens_str = m.get("clobTokenIds", "[]")
            if isinstance(clob_tokens_str, str):
                try:
                    clob_tokens = json.loads(clob_tokens_str)
                except Exception:
                    clob_tokens = []
            else:
                clob_tokens = clob_tokens_str
                
            yes_price = None
            if clob_tokens and len(clob_tokens) > 0:
                yes_token_id = clob_tokens[0]
                # 拉取历史价格
                yes_price = fetch_historical_price(yes_token_id, target_timestamp)
                
            # 如果无法拉取历史价格，则进行兜底（优先使用合约最后结算价，否则默认 0.50）
            if yes_price is None:
                outcome_prices = m.get("outcomePrices", ["0.5", "0.5"])
                if isinstance(outcome_prices, str):
                    try:
                        outcome_prices = json.loads(outcome_prices)
                    except Exception:
                        outcome_prices = ["0.5", "0.5"]
                yes_price = float(outcome_prices[0]) if len(outcome_prices) > 0 else 0.50
                logger.warning(
                    f"档位 {condition} 价格采用降级兜底: {yes_price:.2f} USDC (Token: {clob_tokens[0] if clob_tokens else 'N/A'})", 
                    extra={"market_id": slug}
                )
                
            ranges.append({
                "range_id": f"r{idx+1}",
                "condition": condition,
                "ask_price": yes_price
            })

        # 4. 构建并保存市场快照契约
        snapshot_data = {
            "protocol_version": CONFIG["version"],
            "timestamp": int(time.time()),
            "market_id": slug,
            "station_info": {
                "station_id": icao,
                "city": event.get("title", "").replace("Highest temperature in ", "").replace("Lowest temperature in ", "").split(" on ")[0].strip(),
                "timezone": timezone_str
            },
            "target_date": target_date,
            "resolution_precision": precision,
            "ranges": ranges
        }

        try:
            validate_contract(snapshot_data, "market_snapshot")
            snapshot_filename = f"market_snapshot_{slug}.json"
            snapshot_path = os.path.join(PROTOCOLS_DIR, snapshot_filename)
            with open(snapshot_path, "w", encoding="utf-8") as f:
                json.dump(snapshot_data, f, indent=2, ensure_ascii=False)
            generated_snapshots.append(snapshot_filename)
        except Exception as e:
            logger.error(f"历史快照契约校验失败，跳过。错误: {e}", extra={"market_id": slug})
            continue

        # 5. 调用 Open-Meteo 历史预报接口
        forecast_data = fetch_historical_forecast(lat, lon, target_date, timezone_str)
        if not forecast_data:
            logger.error(f"拉取历史预报失败，跳过事件: {slug}", extra={"market_id": slug})
            continue

        hourly = forecast_data.get("hourly", {})
        times = hourly.get("time", [])
        target_indices = [idx for idx, t_str in enumerate(times) if t_str.startswith(target_date)]
        if not target_indices:
            logger.error(f"在历史预报中未找到日期 {target_date}，跳过分析！", extra={"market_id": slug})
            continue

        # 6. 执行与主程序一致的蒙特卡洛模拟
        risk_config = CONFIG.get("risk_control_lock", {})
        obs_error_sigma_0 = risk_config.get("obs_error_sigma_0", 0.6)
        lead_time_decay_beta = risk_config.get("lead_time_decay_beta", 0.15)
        mc_samples_per_member = risk_config.get("mc_samples_per_member", 100)
        
        # 决策时间 T-1，所以提前天数 lead_days = 1
        lead_days = 1
        
        # 气候分区与基准不确定性下限
        climate_zone = "mid_lat"
        try:
            from src.config import load_cities_config
            cities = load_cities_config()
            if icao in cities:
                climate_zone = cities[icao].get("climate_zone", "mid_lat")
        except Exception as e:
            logger.warning(f"获取城市气候分区失败: {e}", extra={"market_id": slug})

        obs_error_sigma_baseline_mid_lat = risk_config.get("obs_error_sigma_baseline_mid_lat", 1.2)
        obs_error_sigma_baseline_tropics = risk_config.get("obs_error_sigma_baseline_tropics", 0.8)
        baseline_sigma = obs_error_sigma_baseline_tropics if climate_zone == "tropics" else obs_error_sigma_baseline_mid_lat

        # 计算距离结算的剩余小时数 (hours_to_maturity) 以进行基准方差时间衰减
        try:
            import pytz
            tz = pytz.timezone(timezone_str)
            decision_dt_local = datetime.datetime.fromtimestamp(target_timestamp, tz)
            ref_hour = 5 if is_lowest else 15
            ref_dt = datetime.datetime.strptime(f"{target_date} {ref_hour:02d}:00:00", "%Y-%m-%d %H:%M:%S")
            ref_dt = tz.localize(ref_dt)
            delta_seconds = (ref_dt - decision_dt_local).total_seconds()
            hours_to_maturity = delta_seconds / 3600.0
        except Exception:
            hours_to_maturity = 999.0

        sigma_fade_window_hours = risk_config.get("sigma_fade_window_hours", 12.0)
        sigma_absolute_min_celsius = risk_config.get("sigma_absolute_min_celsius", 0.2)

        if hours_to_maturity < sigma_fade_window_hours:
            decay_ratio = max(0.0, hours_to_maturity / sigma_fade_window_hours) if hours_to_maturity > 0 else 0.0
            baseline_sigma = sigma_absolute_min_celsius + (baseline_sigma - sigma_absolute_min_celsius) * decay_ratio

        base_sigma = max(obs_error_sigma_0, baseline_sigma)
        sigma = base_sigma * (1.0 + lead_time_decay_beta * lead_days)
        
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
            logger.error("无有效温度预报数据，跳过！", extra={"market_id": slug})
            continue

        np.random.seed(42)
        simulated_settled_temps = []
        for tj in raw_forecast_temps:
            noise = np.random.normal(0, sigma, mc_samples_per_member)
            sim_temps = tj + noise
            # 注意：T-1 日决策时，实况 observed 温度为 None
            for t_val in sim_temps:
                if precision == "INT_FAHRENHEIT":
                    t_f = t_val * 9.0 / 5.0 + 32.0
                    t_settle = int(np.floor(t_f))
                elif precision == "INT_CELSIUS":
                    t_settle = int(round(t_val))
                else:
                    t_settle = t_val
                simulated_settled_temps.append(t_settle)

        total_simulations = len(simulated_settled_temps)
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
            "market_id": slug,
            "target_date": target_date,
            "total_effective_members": total_effective,
            "probability_distribution": probability_distribution,
            "_raw_member_temps": calibrated_raw_temps,
            "_simulated_sigma": round(float(sigma), 4)
        }

        try:
            validate_contract(prob_data, "weather_probability")
            prob_filename = f"weather_probability_{slug}.json"
            prob_path = os.path.join(PROTOCOLS_DIR, prob_filename)
            with open(prob_path, "w", encoding="utf-8") as f:
                json.dump(prob_data, f, indent=2, ensure_ascii=False)
            generated_probabilities.append(prob_filename)
            logger.info(f"成功保存历史胜率契约: {prob_filename}", extra={"market_id": slug})
        except Exception as e:
            logger.error(f"历史胜率契约验证失败。错误: {e}", extra={"market_id": slug})
            continue

    # 清理 protocols 下其他陈旧的回测快照/胜率文件
    all_snapshots = glob.glob(os.path.join(PROTOCOLS_DIR, "market_snapshot_*.json"))
    for fpath in all_snapshots:
        fname = os.path.basename(fpath)
        if fname not in generated_snapshots:
            try:
                os.remove(fpath)
            except Exception:
                pass
                
    all_probs = glob.glob(os.path.join(PROTOCOLS_DIR, "weather_probability_*.json"))
    for fpath in all_probs:
        fname = os.path.basename(fpath)
        if fname not in generated_probabilities:
            try:
                os.remove(fpath)
            except Exception:
                pass

    logger.info(f"============ 历史数据加载完成。成功生成 {len(generated_snapshots)} 个城市的历史协议 ============", extra={"market_id": "BACKTEST"})

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="回测历史数据加载器")
    parser.add_argument("--date", type=str, required=True, help="目标历史结算日期 (格式 YYYY-MM-DD)")
    args = parser.parse_args()
    
    run_backtest_load(args.date)
