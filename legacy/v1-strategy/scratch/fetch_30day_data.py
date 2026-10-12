"""
30 天历史数据批量拉取脚本
========================
拉取 2026-06-20 ~ 2026-07-19 共 30 天的数据，三大数据源：
  1. Polymarket Gamma API - 事件、子市场、token_id
  2. Polymarket CLOB API - 价格历史 K 线
  3. Open-Meteo Ensemble API - 30 集合成员逐小时温度预报
  4. Wunderground Historical API - 逐小时实况观测

数据存储至 storage/backfill_30day/{station_id}/{date}.json
每个文件包含完整的三类数据，格式兼容现有标定脚本。
"""

import os
import sys
import json
import time
import datetime
import sqlite3
import requests
import pytz
from concurrent.futures import ThreadPoolExecutor, as_completed

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.config import CONFIG, load_cities_config

# ============================================================
# 配置
# ============================================================
START_DATE = "2026-06-20"
END_DATE = "2026-07-19"
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "storage", "backfill_30day")
PROGRESS_FILE = os.path.join(OUTPUT_DIR, "_progress.json")

GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
WUNDERGROUND_API_KEY = "e1f10a1e78da46f5b10a1e78da96f525"
PROXIES = CONFIG.get("network_gateway", {}).get("proxies")

# Polymarket 站点名 -> 城市关键词映射（用于匹配 Gamma 事件标题）
STATION_CITY_KEYWORDS = {
    "RKSI": "seoul", "KNYC": "new york", "EGLL": "london", "RJTT": "tokyo",
    "VHHH": "hong kong", "ZBAA": "beijing", "ZGGG": "guangzhou", "ZHHH": "wuhan",
    "ZSQD": "qingdao", "RCTP": "taipei", "RCSS": "taipei", "EHAM": "amsterdam",
    "LFPG": "paris", "LFPO": "paris", "EDDM": "munich", "LEMD": "madrid",
    "LIMC": "milan", "EPWA": "warsaw", "EFHK": "helsinki", "FACT": "cape town",
    "SAEZ": "buenos aires", "SBGR": "sao paulo", "MPTO": "panama", "MMMX": "mexico city",
    "CYYZ": "toronto", "NZWN": "wellington", "WSSS": "singapore", "WMKK": "kuala lumpur",
    "RPLL": "manila", "OPKC": "karachi", "KLAX": "los angeles", "KSFO": "san francisco",
    "UUEE": "moscow", "LTFM": "istanbul", "LTAC": "ankara", "LLBG": "tel aviv",
    "ATLA": "atlanta", "HOUS": "houston", "CHIC": "chicago", "AUST": "austin",
    "DENV": "denver", "AURO": "denver", "MIAI": "miami", "MIAM": "miami",
    "SEAT": "seattle", "DALL": "dallas", "ZSJN": "jinan", "ZHCC": "zhengzhou",
    "ZSPD": "shanghai", "ZUCK": "chongqing", "ZUUU": "chengdu", "ZGSZ": "shenzhen",
    "RKPK": "busan", "EGLC": "london", "LFPB": "paris", "VILK": "lucknow",
    "OEJN": "jeddah", "MPMG": "panama",
}

# Wunderground 站点映射
WUNDERGROUND_MAPPING = {
    "DALL": "KDAL", "MIAM": "KMIA", "MIAI": "KMIA", "ATLA": "KATL",
    "HOUS": "KHOU", "CHIC": "KORD", "AUST": "KAUS", "DENV": "KDEN",
    "AURO": "KDEN", "SEAT": "KSEA",
    "LTFM": "LTBA",
}

# ICAO -> 国家代码
def get_country_code(icao):
    prefix_map = {
        "EG": "GB", "LF": "FR", "ED": "DE", "LI": "IT", "LE": "ES",
        "EP": "PL", "EH": "NL", "EF": "FI", "RK": "KR", "RJ": "JP",
        "VH": "HK", "WS": "SG", "RC": "TW", "NZ": "NZ", "FA": "ZA",
        "OE": "SA", "OP": "PK", "VI": "IN", "SA": "AR", "SB": "BR",
        "MP": "PA", "MM": "MX", "CY": "CA", "UU": "RU", "LT": "TR",
        "LL": "IL", "ZS": "CN", "ZB": "CN", "ZG": "CN", "ZU": "CN",
        "ZH": "CN", "ZL": "CN", "ZP": "CN",
        "RP": "PH", "WM": "MY",
    }
    p2 = icao[:2]
    if p2 in prefix_map:
        return prefix_map[p2]
    if icao[0] == "K":
        return "US"
    if icao[0] == "C":
        return "CA"
    return "US"

def get_wunderground_station(station_id):
    return WUNDERGROUND_MAPPING.get(station_id.upper(), station_id.upper())

# ============================================================
# 日期工具
# ============================================================
def date_range(start, end):
    d1 = datetime.datetime.strptime(start, "%Y-%m-%d")
    d2 = datetime.datetime.strptime(end, "%Y-%m-%d")
    dates = []
    while d1 <= d2:
        dates.append(d1.strftime("%Y-%m-%d"))
        d1 += datetime.timedelta(days=1)
    return dates

ALL_DATES = date_range(START_DATE, END_DATE)

# ============================================================
# 数据源 1: Polymarket Gamma - 拉取事件和子市场
# ============================================================
def fetch_polymarket_events(target_date):
    """拉取某一天的所有已关闭温度事件"""
    end_date_min = f"{target_date}T00:00:00Z"
    end_date_max = f"{target_date}T23:59:59Z"
    url = f"{GAMMA_URL}/events?closed=true&tag_id=84&end_date_min={end_date_min}&end_date_max={end_date_max}&limit=200"
    try:
        resp = requests.get(url, proxies=PROXIES, timeout=15)
        if resp.status_code == 200:
            events = resp.json()
            return [e for e in events if "temperature" in e.get("title", "").lower()]
    except Exception as e:
        print(f"  [!] Gamma API 错误 ({target_date}): {e}")
    return []

def match_event_to_station(event, stations_config):
    """将 Gamma 事件匹配到站点 ID（只在传入的 stations_config 范围内匹配）"""
    title = event.get("title", "").lower()
    desc = event.get("description", "")
    
    # 优先从 description 解析 ICAO
    import re
    match = re.search(r"daily/[a-z\-]+/([a-z\-]+)/([A-Z]{4})", desc, re.IGNORECASE)
    if match:
        icao = match.group(2).upper()
        for station_id in stations_config:
            if station_id.upper() == icao:
                return station_id
            if get_wunderground_station(station_id) == icao:
                return station_id
    
    # 通过城市关键词匹配（只检查传入的 station_id）
    for station_id in stations_config:
        keyword = STATION_CITY_KEYWORDS.get(station_id, "")
        if keyword and keyword in title:
            return station_id
    
    return None

# ============================================================
# 数据源 2: Polymarket CLOB - 拉取价格历史
# ============================================================
def fetch_token_price_history(token_id, target_timestamp):
    """拉取 token 在目标时间附近的价格历史"""
    start_ts = target_timestamp - 43200  # 前 12 小时
    end_ts = target_timestamp + 43200    # 后 12 小时
    url = f"{CLOB_URL}/prices-history?market={token_id}&startTs={start_ts}&endTs={end_ts}&fidelity=60"
    try:
        resp = requests.get(url, proxies=PROXIES, timeout=15)
        if resp.status_code == 200:
            history = resp.json().get("history", [])
            if history:
                closest = min(history, key=lambda x: abs(x["t"] - target_timestamp))
                return float(closest["p"]), history
    except Exception:
        pass
    return None, None

# ============================================================
# 数据源 3: Open-Meteo Ensemble - 30 集合成员预报
# ============================================================
def fetch_ensemble_forecast(lat, lon, target_date, timezone_str):
    """拉取某天的 30 集合成员逐小时温度预报"""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": target_date,
        "end_date": target_date,
        "hourly": "temperature_2m",
        "timezone": timezone_str,
    }
    try:
        resp = requests.get(ENSEMBLE_URL, params=params, proxies=PROXIES, timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"  [!] Ensemble API 错误 ({target_date}, lat={lat}): {e}")
    return None

# ============================================================
# 数据源 4: Wunderground - 逐小时实况
# ============================================================
def fetch_wunderground_hourly(station_id, target_date, timezone_str):
    """拉取某站点某天的逐小时实况观测"""
    api_station = get_wunderground_station(station_id)
    country = get_country_code(api_station)
    date_str = target_date.replace("-", "")
    url = f"https://api.weather.com/v1/location/{api_station}:9:{country}/observations/historical.json"
    params = {
        "apiKey": WUNDERGROUND_API_KEY,
        "units": "m",
        "startDate": date_str,
        "endDate": date_str,
    }
    try:
        resp = requests.get(url, params=params, proxies=PROXIES, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            observations = data.get("observations", [])
            tz = pytz.timezone(timezone_str)
            results = []
            for obs in observations:
                valid_time = obs.get("valid_time_gmt")
                temp = obs.get("temp")
                if valid_time is not None and temp is not None:
                    dt_local = datetime.datetime.fromtimestamp(valid_time, tz)
                    date_str_local = dt_local.strftime("%Y-%m-%d")
                    if date_str_local == target_date:
                        results.append({
                            "local_time": dt_local.strftime("%Y-%m-%d %H:%M:%S"),
                            "temp": float(temp),
                            "hour": dt_local.hour,
                        })
            return results
    except Exception as e:
        print(f"  [!] Wunderground API 错误 ({station_id}, {target_date}): {e}")
    return []

# ============================================================
# 进度管理
# ============================================================
def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_progress(progress):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, ensure_ascii=False)

# ============================================================
# 主流程：拉取单个 (station, date) 的所有数据
# ============================================================
def fetch_single_station_date(station_id, station_info, target_date, events_by_date):
    """拉取单个站点单天的完整数据"""
    output_path = os.path.join(OUTPUT_DIR, station_id, f"{target_date}.json")
    
    # 已存在则跳过
    if os.path.exists(output_path):
        return "skip", output_path
    
    lat = station_info["lat"]
    lon = station_info["lon"]
    tz_str = station_info["timezone"]
    
    # 1. 拉取 Open-Meteo 集合预报
    forecast = fetch_ensemble_forecast(lat, lon, target_date, tz_str)
    time.sleep(0.3)  # 礼貌延迟
    
    # 2. 拉取 Wunderground 逐小时实况
    hourly_obs = fetch_wunderground_hourly(station_id, target_date, tz_str)
    time.sleep(0.2)
    
    # 3. 匹配 Polymarket 事件（从预匹配的映射中直接取）
    station_events = events_by_date.get(target_date, {})
    matched_event = station_events.get(station_id)
    
    market_snapshot = None
    clob_books = {}
    price_history = {}
    
    if matched_event:
        slug = matched_event.get("slug", "")
        title = matched_event.get("title", "")
        markets = matched_event.get("markets", [])
        
        # 决策时间戳：T-1 日 10:00 UTC
        target_dt = datetime.datetime.strptime(target_date, "%Y-%m-%d")
        decision_dt = target_dt - datetime.timedelta(days=1)
        decision_dt = decision_dt.replace(hour=10, minute=0, second=0, tzinfo=datetime.timezone.utc)
        target_timestamp = int(decision_dt.timestamp())
        
        ranges = []
        for m in markets:
            cond_str = m.get("groupItemTitle", "") or m.get("question", "")
            clob_tokens = m.get("clobTokenIds", [])
            if isinstance(clob_tokens, str):
                try:
                    import json as _json
                    clob_tokens = _json.loads(clob_tokens)
                except:
                    clob_tokens = []
            
            token_id = clob_tokens[0] if clob_tokens and len(clob_tokens) > 0 else ""
            no_token_id = clob_tokens[1] if clob_tokens and len(clob_tokens) > 1 else ""
            
            # 拉取价格历史
            price_val = 0.50
            if token_id:
                price, hist = fetch_token_price_history(token_id, target_timestamp)
                if price is not None:
                    price_val = price
                    price_history[token_id] = hist
                time.sleep(0.15)
            
            ranges.append({
                "range_id": f"r{len(ranges)+1}",
                "condition": cond_str,
                "ask_price": price_val,
                "yes_ask": price_val,
                "no_ask": round(1.0 - price_val, 4),
                "yes_token_id": token_id,
                "no_token_id": no_token_id,
            })
            
            if token_id:
                clob_books[token_id] = {
                    "bids": [{"price": str(max(0.01, round(price_val - 0.02, 2))), "size": "100"}],
                    "asks": [{"price": str(min(0.99, round(price_val + 0.02, 2))), "size": "100"}],
                }
        
        market_snapshot = {
            "market_id": slug,
            "title": title,
            "target_date": target_date,
            "station_info": {
                "station_id": station_id,
                "latitude": lat,
                "longitude": lon,
                "timezone": tz_str,
            },
            "timestamp": target_timestamp,
            "ranges": ranges,
        }
    
    # 组装输出
    output_data = {
        "station_id": station_id,
        "target_date": target_date,
        "fetched_at": datetime.datetime.now().isoformat(),
        "raw_forecast": forecast,
        "raw_observed_hourly": hourly_obs,
        "market_snapshot": market_snapshot,
        "clob_books": clob_books,
        "price_history": price_history,
    }
    
    # 保存
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False)
    
    status = "ok" if (forecast and hourly_obs and market_snapshot) else "partial"
    return status, output_path

# ============================================================
# 主函数
# ============================================================
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    cities = load_cities_config()
    stations = {k: v for k, v in cities.items() if v.get("is_tracked", False)}
    
    print("=" * 80)
    print(f"  30 天历史数据批量拉取 ({START_DATE} ~ {END_DATE})")
    print(f"  站点数: {len(stations)} | 天数: {len(ALL_DATES)} | 总任务: {len(stations) * len(ALL_DATES)}")
    print("=" * 80)
    
    # Step 1: 预拉取所有 Polymarket 事件（按天），并匹配到站点
    print("\n[1/3] 预拉取 Polymarket 事件并匹配站点...")
    events_by_date = {}  # date -> {station_id: event}
    for i, d in enumerate(ALL_DATES):
        events = fetch_polymarket_events(d)
        station_events = {}
        for e in events:
            # 用全部站点配置匹配
            matched_station = match_event_to_station(e, stations)
            if matched_station:
                station_events[matched_station] = e
        events_by_date[d] = station_events
        if (i+1) % 10 == 0 or i == len(ALL_DATES)-1:
            print(f"  [{i+1}/{len(ALL_DATES)}] {d}: {len(events)} 事件 -> {len(station_events)} 站点匹配")
        time.sleep(0.3)
    
    total_matched = sum(len(v) for v in events_by_date.values())
    print(f"  共匹配 {total_matched} 个 (站点, 事件) 对")
    
    # Step 2: 构建所有任务
    tasks = []
    for station_id, info in stations.items():
        for d in ALL_DATES:
            tasks.append((station_id, info, d))
    
    print(f"\n[2/3] 开始拉取 {len(tasks)} 个 (站点, 日期) 组合...")
    
    # Step 3: 多线程拉取（控制并发数避免限流）
    progress = load_progress()
    done = 0
    ok_count = 0
    partial_count = 0
    skip_count = 0
    fail_count = 0
    t0 = time.time()
    
    # 用线程池，并发数 5（平衡速度和限流）
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {}
        for station_id, info, d in tasks:
            # 检查是否已完成
            key = f"{station_id}_{d}"
            if key in progress and progress[key] == "ok":
                skip_count += 1
                done += 1
                continue
            
            future = executor.submit(
                fetch_single_station_date, station_id, info, d, events_by_date
            )
            futures[future] = (station_id, d)
        
        for future in as_completed(futures):
            station_id, d = futures[future]
            key = f"{station_id}_{d}"
            done += 1
            
            try:
                status, path = future.result()
                progress[key] = status
                if status == "ok":
                    ok_count += 1
                elif status == "partial":
                    partial_count += 1
                elif status == "skip":
                    skip_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                print(f"  [!] {station_id} {d} 出错: {e}")
                progress[key] = "fail"
                fail_count += 1
            
            # 每 100 个任务保存一次进度
            if done % 100 == 0:
                save_progress(progress)
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                rem = (len(tasks) - skip_count - done) / rate if rate > 0 else 0
                print(f"  [{done}/{len(tasks)}] OK:{ok_count} 部分:{partial_count} 跳过:{skip_count} 失败:{fail_count} | "
                      f"速度:{rate:.1f}/s | 剩余:{rem:.0f}s", flush=True)
    
    save_progress(progress)
    
    # 汇总
    print("\n" + "=" * 80)
    print(f"  拉取完成！用时: {time.time()-t0:.0f}s")
    print(f"  成功: {ok_count} | 部分: {partial_count} | 跳过: {skip_count} | 失败: {fail_count}")
    print("=" * 80)
    
    # 输出 partial 和 fail 的详情
    if partial_count > 0 or fail_count > 0:
        print("\n未完整的数据:")
        for key, status in progress.items():
            if status in ("partial", "fail"):
                print(f"  {status}: {key}")

if __name__ == "__main__":
    main()
