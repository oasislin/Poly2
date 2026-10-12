import os
import sqlite3
import requests
import datetime
import json
import time
from src.config import CONFIG, PROXIES, setup_logger

logger = setup_logger("WeatherCache")

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage")
DB_PATH = os.path.join(DB_DIR, "weather_cache.db")

def init_db():
    """
    初始化 SQLite 数据库，创建缓存表
    """
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS weather_daily_cache (
        station_id TEXT,
        date TEXT,
        is_lowest INTEGER,
        mean_forecast_extreme REAL,
        obs_extreme REAL,
        is_complete INTEGER DEFAULT 0,
        PRIMARY KEY (station_id, date, is_lowest)
    );
    """)
    # 动态检查并添加 is_complete 列以支持向后兼容
    try:
        cursor.execute("SELECT is_complete FROM weather_daily_cache LIMIT 1")
    except sqlite3.OperationalError:
        try:
            cursor.execute("ALTER TABLE weather_daily_cache ADD COLUMN is_complete INTEGER DEFAULT 0")
            conn.commit()
        except Exception as e:
            logger.warning(f"添加 is_complete 列失败: {e}")
            
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS open_meteo_api_cache (
        url TEXT,
        params TEXT,
        response_json TEXT,
        updated_at INTEGER,
        PRIMARY KEY (url, params)
    );
    """)
    conn.commit()
    conn.close()


def get_cached_stats(station_id: str, dates: list, is_lowest: bool, include_completion: bool = False) -> dict:
    """
    批量查询给定气象站和日期的缓存统计值。
    include_completion=True 时返回 {date: (mean_forecast_extreme, obs_extreme, is_complete)}
    否则返回 {date: (mean_forecast_extreme, obs_extreme)}
    """
    init_db()
    station_id = station_id.upper().strip()
    is_lowest_int = 1 if is_lowest else 0
    if not dates:
        return {}

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 构造 IN 子句查询
    placeholders = ",".join(["?"] * len(dates))
    select_fields = "date, mean_forecast_extreme, obs_extreme, is_complete" if include_completion else "date, mean_forecast_extreme, obs_extreme"
    query = f"""
    SELECT {select_fields} 
    FROM weather_daily_cache 
    WHERE station_id = ? AND is_lowest = ? AND date IN ({placeholders})
    """
    params = [station_id, is_lowest_int] + list(dates)
    
    results = {}
    try:
        cursor.execute(query, params)
        for row in cursor.fetchall():
            if include_completion:
                date_str, mean_forecast, obs, is_comp = row
                results[date_str] = (mean_forecast, obs, is_comp)
            else:
                date_str, mean_forecast, obs = row
                results[date_str] = (mean_forecast, obs)
    except Exception as e:
        logger.error(f"读取 SQLite 缓存异常 (Station: {station_id}): {e}")
    finally:
        conn.close()
        
    return results


def save_cached_stats(station_id: str, date: str, is_lowest: bool, mean_forecast_extreme: float, obs_extreme: float, is_complete: int = 0):
    """
    将单日统计值存入或覆盖缓存数据库
    """
    init_db()
    station_id = station_id.upper().strip()
    is_lowest_int = 1 if is_lowest else 0
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    query = """
    INSERT OR REPLACE INTO weather_daily_cache (station_id, date, is_lowest, mean_forecast_extreme, obs_extreme, is_complete)
    VALUES (?, ?, ?, ?, ?, ?)
    """
    try:
        cursor.execute(query, (station_id, date, is_lowest_int, mean_forecast_extreme, obs_extreme, is_complete))
        conn.commit()
    except Exception as e:
        logger.error(f"写入 SQLite 缓存异常 (Station: {station_id}, Date: {date}): {e}")
    finally:
        conn.close()

def get_country_code_by_icao(icao: str) -> str:
    icao = icao.upper().strip()
    prefix_2 = icao[:2]
    prefix_1 = icao[0]
    
    prefix_map = {
        "EG": "GB", "LF": "FR", "ED": "DE", "LI": "IT", "LE": "ES",
        "EP": "PL", "EH": "NL", "EF": "FI", "RK": "KR", "RJ": "JP",
        "VH": "HK", "WS": "SG", "RC": "TW", "NZ": "NZ", "FA": "ZA",
        "OE": "SA", "OP": "PK", "VI": "IN", "SA": "AR", "SB": "BR",
        "MP": "PA", "MM": "MX", "CY": "CA", "UU": "RU", "LT": "TR",
        "LL": "IL",
        # China prefixes
        "ZS": "CN", "ZB": "CN", "ZG": "CN", "ZU": "CN", "ZH": "CN", "ZL": "CN", "ZP": "CN",
    }
    
    if prefix_2 in prefix_map:
        return prefix_map[prefix_2]
    
    if prefix_1 == "K":
        return "US"
    if prefix_1 == "C":
        return "CA"
        
    return "US"

def resolve_station_timezone(station_id: str) -> str:
    station_id = station_id.upper().strip()
    try:
        from src.config import load_cities_config
        cities = load_cities_config()
        if station_id in cities and "timezone" in cities[station_id]:
            return cities[station_id]["timezone"]
    except Exception:
        pass

    # Check custom mappings

    # Check fallback map
    fallback_timezones = {
        "RKSI": "Asia/Seoul", "KNYC": "America/New_York", "EGLL": "Europe/London",
        "RJTT": "Asia/Tokyo", "VHHH": "Asia/Hong_Kong", "ZSSS": "Asia/Shanghai",
        "ATLA": "America/New_York", "HOUS": "America/Chicago", "CHIC": "America/Chicago",
        "AUST": "America/Chicago", "DENV": "America/Denver", "AURO": "America/Denver",
        "MIAI": "America/New_York", "MIAM": "America/New_York", "SEAT": "America/Los_Angeles",
        "DALL": "America/Chicago", "ZSPD": "Asia/Shanghai",
        "KLAX": "America/Los_Angeles", "KSFO": "America/Los_Angeles",
        "UUEE": "Europe/Moscow", "LTFM": "Europe/Istanbul",
        "LTAC": "Europe/Istanbul", "LLBG": "Asia/Jerusalem"
    }
    if station_id in fallback_timezones:
        return fallback_timezones[station_id]
        
    # Default to UTC
    return "UTC"

def map_polymarket_station_to_wunderground(station_id: str) -> str:
    station_mapping = {
        "DALL": "KDAL", # Dallas Love Field
        "MIAM": "KMIA", # Miami International Airport
        "MIAI": "KMIA",
        "ATLA": "KATL", # Atlanta Hartsfield-Jackson
        "HOUS": "KHOU", # Houston Hobby Airport
        "CHIC": "KORD", # Chicago O'Hare
        "AUST": "KAUS", # Austin-Bergstrom
        "DENV": "KDEN", # Denver
        "AURO": "KDEN", # Denver
        "SEAT": "KSEA", # Seattle-Tacoma
    }
    return station_mapping.get(station_id.upper().strip(), station_id.upper().strip())

def fetch_wunderground_daily_history(station_id: str) -> dict:
    """
    通过 TWC v1 observations/historical.json 接口拉取过去 30 天的高精度逐小时实况数据，
    按天统计出真实的观测极大值/极小值并写入本地缓存，返回 {date_str: {"max_temp": float, "min_temp": float}}
    """
    station_id = station_id.upper().strip()
    api_station_id = map_polymarket_station_to_wunderground(station_id)
    country = get_country_code_by_icao(api_station_id)
    timezone_str = resolve_station_timezone(station_id)
    
    url = f"https://api.weather.com/v1/location/{api_station_id}:9:{country}/observations/historical.json"
    
    import datetime, pytz
    # 必须使用站点当地时间，避免跨时区时 endDate 偏移导致漏拉或多拉一天数据
    try:
        tz = pytz.timezone(timezone_str)
        today = datetime.datetime.now(tz).date()
    except Exception:
        today = datetime.date.today()
    start_date_obj = today - datetime.timedelta(days=30)
    start_date_str = start_date_obj.strftime("%Y%m%d")
    end_date_str = today.strftime("%Y%m%d")
    
    params = {
        "apiKey": "e1f10a1e78da46f5b10a1e78da96f525",
        "units": "m",
        "startDate": start_date_str,
        "endDate": end_date_str
    }
    
    # 优先读取本地 API 缓存 (历史数据 12 小时内不重复拉取)
    cached_data = get_api_cache(url, params, expire_seconds=43200)
    if cached_data:
        return cached_data

    results = {}
    try:
        logger.info(f"正在从 Wunderground 拉取高精度历史观测曲线 (Station: {station_id}, API: {api_station_id}, Range: {start_date_str}-{end_date_str})")
        resp = requests.get(url, params=params, proxies=PROXIES, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            observations = data.get("observations", [])
            
            # 按站点当地时间分组统计每日温度极值
            import pytz
            try:
                tz = pytz.timezone(timezone_str)
            except Exception:
                tz = pytz.UTC
                
            daily_groups = {} # {date_str: []}
            for obs in observations:
                valid_time = obs.get("valid_time_gmt")
                temp = obs.get("temp")
                if valid_time is not None and temp is not None:
                    # 将 GMT 时间转换为站点本地时间
                    dt_local = datetime.datetime.fromtimestamp(valid_time, tz)
                    date_str = dt_local.strftime("%Y-%m-%d")
                    if date_str not in daily_groups:
                        daily_groups[date_str] = []
                    daily_groups[date_str].append(float(temp))
            
            # 汇总极值
            for date_str, temps in daily_groups.items():
                results[date_str] = {
                    "max_temp": max(temps),
                    "min_temp": min(temps)
                }
            
            save_api_cache(url, params, results)
        else:
            logger.warning(f"拉取 Wunderground 高精度历史曲线失败, HTTP 状态码: {resp.status_code}")
    except Exception as e:
        logger.error(f"拉取 Wunderground 高精度历史曲线异常 (Station: {station_id}): {e}")
        
    if not results:
        logger.warning(f"从 Wunderground 拉取 {station_id} 历史数据失败/被限流，已禁用 Open-Meteo 结算兜底。")
        
    return results

def fetch_openmeteo_daily_history(station_id: str) -> dict:
    """
    备用观测源：从 Open-Meteo Archive API 获取过去 30 天的历史实况
    """
    station_id = station_id.upper().strip()
    lat = None
    lon = None
    try:
        from src.config import load_cities_config
        cities = load_cities_config()
        if station_id in cities:
            lat = cities[station_id].get("lat")
            lon = cities[station_id].get("lon")
    except Exception:
        pass
        
    if lat is None or lon is None or (abs(lat) < 1e-5 and abs(lon) < 1e-5):
        try:
            from src.analyst import resolve_station_coordinates
            lat, lon = resolve_station_coordinates(station_id)
        except Exception:
            # 针对核心非 Wunderground 城市的硬编码经纬度防循环导入兜底
            coord_map = {
                "VHHH": (22.308, 113.918),
                "KNYC": (40.782, -73.965),
                "KLAX": (33.942, -118.408),
                "KSFO": (37.619, -122.375),
                "UUEE": (55.973, 37.415),
                "LTFM": (41.275, 28.752),
                "LTAC": (40.128, 32.995),
                "LLBG": (32.009, 34.885),
                "EGLL": (51.470, -0.454),
            }
            if station_id in coord_map:
                lat, lon = coord_map[station_id]
            else:
                return {}
            
    timezone_str = resolve_station_timezone(station_id)
    url = "https://archive-api.open-meteo.com/v1/archive"
    import datetime, pytz
    # 必须使用站点当地时间，避免跨时区时日期偏移
    try:
        tz = pytz.timezone(timezone_str)
        today = datetime.datetime.now(tz).date()
    except Exception:
        today = datetime.date.today()
    start_date = (today - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    end_date = (today - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "daily": "temperature_2m_max,temperature_2m_min",
        "timezone": timezone_str
    }
    
    results = {}
    try:
        logger.info(f"正在从 Open-Meteo Archive 接口拉取历史观测 (Station: {station_id}, Coordinates: {lat}, {lon})")
        resp = requests.get(url, params=params, proxies=PROXIES, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            daily = data.get("daily", {})
            times = daily.get("time", [])
            max_temps = daily.get("temperature_2m_max", [])
            min_temps = daily.get("temperature_2m_min", [])
            for i in range(len(times)):
                results[times[i]] = {
                    "max_temp": float(max_temps[i]) if max_temps[i] is not None else None,
                    "min_temp": float(min_temps[i]) if min_temps[i] is not None else None
                }
    except Exception as e:
        logger.error(f"从 Open-Meteo Archive 拉取历史曲线异常 (Station: {station_id}): {e}")
    return results


def fetch_wunderground_hourly_observed_today(station_id: str, timezone_str: str) -> list[dict]:
    """
    从 TWC v1 observations/historical.json 接口拉取今日的高精度历史观测值（含 METAR 特报），
    返回列表 [{"local_time": str, "temp": float, "hour": int}]
    """
    station_id = station_id.upper().strip()
    api_station_id = map_polymarket_station_to_wunderground(station_id)
    country = get_country_code_by_icao(api_station_id)
    
    # 获取当前站点的今日日期 (YYYYMMDD)
    import pytz
    try:
        tz = pytz.timezone(timezone_str)
        station_now = datetime.datetime.now(tz)
    except Exception:
        tz = pytz.UTC
        station_now = datetime.datetime.now(datetime.timezone.utc)
    today_str = station_now.strftime("%Y-%m-%d")
    today_str_short = station_now.strftime("%Y%m%d")
    
    url = f"https://api.weather.com/v1/location/{api_station_id}:9:{country}/observations/historical.json"
    params = {
        "apiKey": "e1f10a1e78da46f5b10a1e78da96f525",
        "units": "m",
        "startDate": today_str_short,
        "endDate": today_str_short
    }
    
    # 5分钟缓存，防止重复请求
    cached_data = get_api_cache(url, params, expire_seconds=300)
    
    if cached_data is None:
        try:
            logger.info(f"正在从 Wunderground 拉取今日高精度实况 (Station: {station_id}, API: {api_station_id})")
            resp = requests.get(url, params=params, proxies=PROXIES, timeout=15)
            if resp.status_code == 200:
                cached_data = resp.json()
                save_api_cache(url, params, cached_data)
            else:
                logger.warning(f"拉取 Wunderground 今日高精度实况失败, HTTP 状态码: {resp.status_code}")
        except Exception as e:
            logger.error(f"拉取 Wunderground 今日高精度实况异常 (Station: {station_id}, API: {api_station_id}): {e}")
            
    results = []
    if cached_data:
        observations = cached_data.get("observations", [])
        for obs in observations:
            valid_time = obs.get("valid_time_gmt")
            temp = obs.get("temp")
            if valid_time is not None and temp is not None:
                # 将 GMT 时间转换为站点本地时间
                dt_local = datetime.datetime.fromtimestamp(valid_time, tz)
                date_str = dt_local.strftime("%Y-%m-%d")
                if date_str == today_str:
                    results.append({
                        "local_time": dt_local.strftime("%Y-%m-%d %H:%M:%S"),
                        "temp": float(temp),
                        "hour": dt_local.hour
                    })
                    
    # 如果 v1 接口返回无数据，降级回退至 v3 小时级整点接口
    if not results:
        url_v3 = "https://api.weather.com/v3/wx/conditions/historical/hourly/1day"
        params_v3 = {
            "icaoCode": api_station_id,
            "units": "m",
            "language": "en-US",
            "format": "json",
            "apiKey": "e1f10a1e78da46f5b10a1e78da96f525"
        }
        cached_data_v3 = get_api_cache(url_v3, params_v3, expire_seconds=300)
        if cached_data_v3 is None:
            try:
                logger.info(f"v1接口无数据，尝试从 v3 接口拉取今日小时级实况 (Station: {station_id}, API: {api_station_id})")
                resp = requests.get(url_v3, params=params_v3, proxies=PROXIES, timeout=15)
                if resp.status_code == 200:
                    cached_data_v3 = resp.json()
                    save_api_cache(url_v3, params_v3, cached_data_v3)
            except Exception as e:
                logger.error(f"v3 接口拉取今日小时实况异常 (Station: {station_id}, API: {api_station_id}): {e}")
        
        if cached_data_v3:
            times = cached_data_v3.get("validTimeLocal", [])
            temps = cached_data_v3.get("temperature", [])
            for i in range(len(times)):
                if times[i].startswith(today_str) and temps[i] is not None:
                    try:
                        t_part = times[i][:19].replace("T", " ")
                        dt_local = datetime.datetime.strptime(t_part, "%Y-%m-%d %H:%M:%S")
                        results.append({
                            "local_time": dt_local.strftime("%Y-%m-%d %H:%M:%S"),
                            "temp": float(temps[i]),
                            "hour": dt_local.hour
                        })
                    except Exception:
                        pass
    return results


def fetch_wunderground_observed_today(station_id: str, is_lowest: bool, timezone_str: str) -> float:
    """
    拉取今日高精度实况温度（优先使用 v1 接口，含特报），并返回今日当前的最高或最低温度值 (Celsius)
    """
    hourly_obs = fetch_wunderground_hourly_observed_today(station_id, timezone_str)
    if hourly_obs:
        temps = [obs["temp"] for obs in hourly_obs]
        val = min(temps) if is_lowest else max(temps)
        today_str = hourly_obs[0]["local_time"][:10]
        logger.info(f"Wunderground 成功获取今日 ({today_str}) 高精度实况极值: {val:.2f}°C (lowest={is_lowest})")
        return float(val)
    return None

def get_api_cache(url: str, params: dict, expire_seconds: int = 1800) -> dict:
    """
    获取通用 API 的本地缓存。
    """
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    params_str = json.dumps(params, sort_keys=True)
    now = int(time.time())
    try:
        cursor.execute(
            "SELECT response_json, updated_at FROM open_meteo_api_cache WHERE url = ? AND params = ?",
            (url, params_str)
        )
        row = cursor.fetchone()
        if row:
            resp_json_str, updated_at = row
            if now - updated_at < expire_seconds:
                logger.info(f"API 缓存命中 (URL: {url})")
                return json.loads(resp_json_str)
    except Exception as e:
        logger.error(f"读取 API 缓存异常: {e}")
    finally:
        conn.close()
    return None

def save_api_cache(url: str, params: dict, response_json: dict):
    """
    保存通用 API 响应到本地缓存。
    """
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    params_str = json.dumps(params, sort_keys=True)
    resp_json_str = json.dumps(response_json)
    now = int(time.time())
    try:
        cursor.execute(
            "INSERT OR REPLACE INTO open_meteo_api_cache (url, params, response_json, updated_at) VALUES (?, ?, ?, ?)",
            (url, params_str, resp_json_str, now)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"写入 API 缓存异常: {e}")
    finally:
        conn.close()



