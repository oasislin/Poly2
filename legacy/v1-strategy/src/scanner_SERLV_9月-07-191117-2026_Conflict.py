import os
import json
import time
import datetime
import re
import requests
import glob
from src.config import CONFIG, PROXIES, validate_contract, setup_logger, load_custom_station_mappings, add_pending_station, load_cities_config, save_cities_config

logger = setup_logger("Scanner")

PROTOCOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocols")

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

def parse_station_icao_from_desc(description_text):
    """
    从 Wunderground URL 中提取气象站 ICAO 代码
    """
    match = re.search(r"daily/[a-z\-]+/([a-z\-]+)/([A-Z]{4})", description_text, re.IGNORECASE)
    if match:
        return match.group(2).upper()
    return None

def fetch_all_active_weather_events():
    """
    分页获取所有活跃的的天气类 Event
    """
    gamma_url = CONFIG["network_gateway"].get("polymarket_gamma_url", "https://gamma-api.polymarket.com")
    all_events = []
    offset = 0
    limit = 100
    
    logger.info("向 Polymarket 拉取全部活跃天气事件列表...", extra={"market_id": "SCANNER"})
    
    while True:
        url = f"{gamma_url}/events?active=true&closed=false&tag_id=84&limit={limit}&offset={offset}"
        retries = 3
        backoff = 2.0
        success = False
        for attempt in range(retries):
            try:
                response = requests.get(url, proxies=PROXIES, timeout=10)
                if response.status_code != 200:
                    logger.error(f"请求 events 失败, 状态码: {response.status_code}", extra={"market_id": "SCANNER"})
                    break
                
                events = response.json()
                success = True
                break
            except Exception as e:
                if attempt == retries - 1:
                    logger.error(f"请求 events 异常 (已达最大重试次数): {str(e)}", extra={"market_id": "SCANNER"})
                else:
                    logger.warning(f"请求 events 异常，正在进行第 {attempt+1} 次重试... 错误: {str(e)}", extra={"market_id": "SCANNER"})
                    time.sleep(backoff * (attempt + 1))
        
        if not success:
            break
            
        if not events:
            break
        
        all_events.extend(events)
        if len(events) < limit:
            break
        offset += limit
            
    logger.info(f"总计获取到 {len(all_events)} 个活跃天气/环境类事件。", extra={"market_id": "SCANNER"})
    return all_events

def run_scanner():
    """
    运行市场扫描仪：尝试从 Polymarket 抓取并解析所有活跃天气盘口。
    """
    logger.info("启动 Polymarket 多城市天气市场扫描...", extra={"market_id": "SCANNER"})
    
    os.makedirs(PROTOCOLS_DIR, exist_ok=True)
    
    # 记录本轮更新的文件名
    active_files = []
    
    try:
        events = fetch_all_active_weather_events()
        weather_events = []
        cities_config = load_cities_config()
        config_changed = False
        
        for e in events:
            title = e.get("title", "")
            description = e.get("description", "")
            # 过滤出温度相关的事件
            if "temperature" in title.lower() or "temp" in title.lower():
                icao = parse_station_icao_from_desc(description)
                if not icao:
                    # 针对非 Wunderground 结算页面（如香港天文台 HKO 或 NWS 等）的备用硬编码映射
                    title_lower = title.lower()
                    if "hong kong" in title_lower:
                        icao = "VHHH"
                    elif "new york" in title_lower or "nyc" in title_lower:
                        icao = "KNYC"
                    elif "los angeles" in title_lower:
                        icao = "KLAX"
                    elif "san francisco" in title_lower:
                        icao = "KSFO"
                    elif "moscow" in title_lower:
                        icao = "UUEE"
                    elif "istanbul" in title_lower:
                        icao = "LTFM"
                    elif "ankara" in title_lower:
                        icao = "LTAC"
                    elif "tel aviv" in title_lower:
                        icao = "LLBG"
                if icao:
                    icao = icao.upper().strip()
                    # 动态注册没有配置过的新城市，防止由于没有静态配置而漏掉
                    if icao not in cities_config:
                        cities_config[icao] = {
                            "city": title.replace("Highest temperature in ", "").replace("Lowest temperature in ", "").split(" on ")[0].strip(),
                            "lat": 0.0,
                            "lon": 0.0,
                            "timezone": "UTC",
                            "is_tracked": True,
                            "is_tradable": False
                        }
                        config_changed = True
                        
                    if cities_config[icao].get("is_tracked", True):
                        weather_events.append((e, icao))
                    else:
                        logger.info(f"过滤跳过配置为不追踪的城市: {e.get('slug')} ({icao})", extra={"market_id": "SCANNER"})
                        
        if config_changed:
            save_cities_config(cities_config)
            logger.info("已将扫描到的新气象城市增量写入 cities.json 配置中（默认不投注）", extra={"market_id": "SCANNER"})
            
        if not weather_events:
            logger.warning("未在 Polymarket 发现任何活跃的天气对赌合约。", extra={"market_id": "SCANNER"})
            # 清理 protocols 下本轮没有更新的陈旧 market_snapshot_*.json 文件
            all_snapshot_files = glob.glob(os.path.join(PROTOCOLS_DIR, "market_snapshot_*.json"))
            for fpath in all_snapshot_files:
                try:
                    os.remove(fpath)
                    logger.info(f"清理陈旧的历史快照协议文件: {os.path.basename(fpath)}", extra={"market_id": "SCANNER"})
                except Exception as e:
                    logger.warning(f"清理陈旧协议 {os.path.basename(fpath)} 失败: {str(e)}", extra={"market_id": "SCANNER"})
            return
            
        logger.info(f"筛选到包含有效气象站的温度事件共 {len(weather_events)} 个。", extra={"market_id": "SCANNER"})
        
        timezone_map = {
            "RKSI": "Asia/Seoul",
            "KNYC": "America/New_York",
            "EGLL": "Europe/London",
            "RJTT": "Asia/Tokyo",
            "VHHH": "Asia/Hong_Kong",
            "ZSSS": "Asia/Shanghai",
            "ZBAA": "Asia/Shanghai",   # 北京
            "ZGGG": "Asia/Shanghai",   # 广州
            "ZHHH": "Asia/Shanghai",   # 武汉
            "ZSQD": "Asia/Shanghai",   # 青岛
            "RCTP": "Asia/Taipei",     # 台北
            "RCSS": "Asia/Taipei",     # 台北
            "EHAM": "Europe/Amsterdam", # 阿姆斯坦丹
            "LFPG": "Europe/Paris",     # 巴黎
            "LFPO": "Europe/Paris",     # 巴黎
            "EDDM": "Europe/Berlin",    # 慕尼黑 (Open-Meteo 不支持 Europe/Munich，故映射为 Europe/Berlin)
            "LEMD": "Europe/Madrid",    # 马德里
            "LIMC": "Europe/Rome",      # 米兰
            "EPWA": "Europe/Warsaw",    # 华沙
            "EFHK": "Europe/Helsinki",  # 赫尔辛基
            "FACT": "Africa/Johannesburg", # 开普敦
            "SAEZ": "America/Argentina/Buenos_Aires", # 布宜诺斯艾利斯
            "SBGR": "America/Sao_Paulo", # 圣保罗
            "MPTO": "America/Panama",    # 巴拿马
            "MMMX": "America/Mexico_City", # 墨西哥城
            "CYYZ": "America/Toronto",    # 多伦多
            "NZWN": "Pacific/Auckland",   # 惠领顿
            "WSSS": "Asia/Singapore",     # 新加坡
            "WMKK": "Asia/Kuala_Lumpur",  # 吉隆坡
            "RPLL": "Asia/Manila",        # 马尼拉
            "OPKC": "Asia/Karachi",       # 卡拉奇
            
            # 新增支持的非 Wunderground 城市时区
            "KLAX": "America/Los_Angeles",
            "KSFO": "America/Los_Angeles",
            "UUEE": "Europe/Moscow",
            "LTFM": "Europe/Istanbul",
            "LTAC": "Europe/Istanbul",
            "LLBG": "Asia/Jerusalem",
            
            # 解决 Polymarket 对赌协议描述中写错的非标准 ICAO 代码的时区映射 ( typos )
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
        
        # 合并用户自定义时区映射
        custom_mappings = load_custom_station_mappings()
        for s_id, m in custom_mappings.items():
            if "timezone" in m:
                timezone_map[s_id.upper()] = m["timezone"]
        
        for event, icao in weather_events:
            icao = icao.upper().strip()
            slug = event["slug"]
            target_date = event.get("eventDate", "")
            if not target_date:
                target_date = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
            
            # 解决时区对齐问题：转换至气象站当地时间进行精细化过滤
            timezone_str = "UTC"
            if icao in cities_config and "timezone" in cities_config[icao]:
                timezone_str = cities_config[icao]["timezone"]
            elif icao in timezone_map:
                timezone_str = timezone_map[icao]
            else:
                city = event.get("title", "").replace("Highest temperature in ", "").replace("Lowest temperature in ", "").split(" on ")[0].strip()
                add_pending_station(icao, city, "missing_timezone", f"气象站时区映射缺失。系统默认 fallback 至 UTC。")
                
            try:
                import pytz
                tz = pytz.timezone(timezone_str)
                station_now = datetime.datetime.now(tz)
            except Exception:
                # 备用 UTC
                import datetime as dt
                station_now = datetime.datetime.now(dt.timezone.utc)
                
            station_today_str = station_now.strftime("%Y-%m-%d")
            
            status = "active"
            
            if target_date < station_today_str:
                logger.info(f"标记历史已结算事件为 inactive: {slug} (日期: {target_date}, 站时: {station_today_str})", extra={"market_id": "SCANNER"})
                status = "inactive"
            elif target_date == station_today_str:
                # 判断是最高温还是最低温合约
                title_lower = event.get("title", "").lower()
                is_lowest = "lowest" in title_lower
                
                if is_lowest:
                    # 最低温出现在夜间 (当天20:00以后至次日清晨08:00以前，跨天连续滚动)
                    # 如果在白天的 08:00 - 20:00 之间，判定为非活性期，过滤以防模型滞后于早上已发生的低温
                    if 8 <= station_now.hour < 20:
                        logger.info(f"当天最低温事件处于白昼非活性期，标记为 inactive: {slug} (站时: {station_now.strftime('%Y-%m-%d %H:%M')})", extra={"market_id": "SCANNER"})
                        status = "inactive"
                    else:
                        logger.info(f"当天最低温事件处于夜间/清晨活性期，保留监控: {slug} (站时: {station_now.strftime('%Y-%m-%d %H:%M')})", extra={"market_id": "SCANNER"})
                else:
                    # 最高温合约一般在午后 (13:00-15:00) 见顶，过 13:00 判定已过峰值期
                    if station_now.hour >= 13:
                        logger.info(f"当天最高温事件已过峰值确定期，标记为 inactive: {slug} (站时: {station_now.strftime('%Y-%m-%d %H:%M')})", extra={"market_id": "SCANNER"})
                        status = "inactive"
                    else:
                        logger.info(f"当天最高温事件仍未到峰值确定期，保留监控: {slug} (站时: {station_now.strftime('%Y-%m-%d %H:%M')})", extra={"market_id": "SCANNER"})
                
            markets = event.get("markets", [])
            if not markets:
                continue
                
            ranges = []
            
            # 【重要修复】单位统一：根据各个子市场问题中是否包含 "°F" 来决定精度
            is_fahrenheit = False
            for m in markets:
                if "°f" in m["question"].lower() or " f " in m["question"].lower():
                    is_fahrenheit = True
                    break
            
            precision = "INT_FAHRENHEIT" if is_fahrenheit else "INT_CELSIUS"
            timezone = timezone_map.get(icao, "UTC")
            
            for idx, m in enumerate(markets):
                condition = parse_weather_condition(m["question"])
                if condition:
                    prices = m.get("outcomePrices", ["1.0", "1.0"])
                    if isinstance(prices, str):
                        try:
                            prices = json.loads(prices)
                        except Exception:
                            prices = ["1.0", "1.0"]
                    yes_price = float(prices[0]) if prices and len(prices) > 0 else 1.0
                    no_price = float(prices[1]) if prices and len(prices) > 1 else 1.0
                    
                    clob_tokens_str = m.get("clobTokenIds", "[]")
                    if isinstance(clob_tokens_str, str):
                        try:
                            clob_tokens = json.loads(clob_tokens_str)
                        except Exception:
                            clob_tokens = []
                    else:
                        clob_tokens = clob_tokens_str
                    
                    yes_token = clob_tokens[0] if len(clob_tokens) > 0 else ""
                    no_token = clob_tokens[1] if len(clob_tokens) > 1 else ""
                    
                    ranges.append({
                        "range_id": f"r{idx+1}",
                        "condition": condition,
                        "ask_price": yes_price,
                        "yes_ask": yes_price,
                        "no_ask": no_price,
                        "yes_token_id": yes_token,
                        "no_token_id": no_token
                    })
            
            # 构建单城市快照
            snapshot_data = {
                "protocol_version": CONFIG["version"],
                "timestamp": int(time.time()),
                "market_id": slug,
                "station_info": {
                    "station_id": icao,
                    "city": event.get("title", "").replace("Highest temperature in ", "").replace("Lowest temperature in ", "").split(" on ")[0].strip(),
                    "timezone": timezone
                },
                "target_date": target_date,
                "resolution_precision": precision,
                "status": status,
                "ranges": ranges
            }
            
            # 强校验契约
            try:
                validate_contract(snapshot_data, "market_snapshot")
                
                # 持久化为带有 slug 后缀的协议文件
                filename = f"market_snapshot_{slug}.json"
                file_path = os.path.join(PROTOCOLS_DIR, filename)
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(snapshot_data, f, indent=2, ensure_ascii=False)
                    
                active_files.append(filename)
                logger.info(f"市场快照契约已成功持久化至 {file_path}", extra={"market_id": slug})
                
            except Exception as e:
                logger.error(f"事件 {slug} 快照契约校验失败，跳过写入！错误: {str(e)}", extra={"market_id": slug})
                
        # 清理 protocols 下本轮没有更新的陈旧 market_snapshot_*.json 文件，防止下游读取过期合约
        all_snapshot_files = glob.glob(os.path.join(PROTOCOLS_DIR, "market_snapshot_*.json"))
        for fpath in all_snapshot_files:
            fname = os.path.basename(fpath)
            if fname not in active_files:
                try:
                    os.remove(fpath)
                    logger.info(f"清理陈旧的历史快照协议文件: {fname}", extra={"market_id": "SCANNER"})
                except Exception as e:
                    logger.warning(f"清理陈旧协议 {fname} 失败: {str(e)}", extra={"market_id": "SCANNER"})
                    
        # 兼容性清理原先无后缀的单个 market_snapshot.json
        legacy_snapshot = os.path.join(PROTOCOLS_DIR, "market_snapshot.json")
        if os.path.exists(legacy_snapshot):
            os.remove(legacy_snapshot)
            
    except Exception as e:
        logger.error(f"扫描 Polymarket 失败: {str(e)}", extra={"market_id": "SCANNER"})
        raise e

if __name__ == "__main__":
    run_scanner()
