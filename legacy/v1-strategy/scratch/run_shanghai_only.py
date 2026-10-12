import os
import json
import time
import glob
import requests
import datetime
import argparse

# 1. 保存系统最原始的 glob.glob 函数，以及 scanner 的事件拉取函数
original_glob = glob.glob

# 从主程序导入各个核心流水线模块
from src.config import CONFIG, PROXIES, validate_contract, setup_logger
import src.scanner as scanner
from src.scanner import run_scanner, parse_station_icao_from_desc
from src.analyst import run_analyst, resolve_station_coordinates
from src.strategy import run_strategy
from src.executor import run_executor

logger = setup_logger("FilteredOrchestrator")

PROTOCOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocols")
ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage", "archive")

def fetch_real_clob_book(token_id):
    """
    通过 CLOB API 拉取实时的订单簿挂单深度
    """
    clob_url = CONFIG["network_gateway"].get("polymarket_clob_url", "https://clob.polymarket.com")
    url = f"{clob_url}/book?token_id={token_id}"
    try:
        response = requests.get(url, proxies=PROXIES, timeout=5)
        if response.status_code == 200:
            data = response.json()
            bids = data.get("bids", [])[:10]
            asks = data.get("asks", [])[:10]
            return {
                "bids": [[float(b["price"]), float(b["size"])] for b in bids],
                "asks": [[float(a["price"]), float(a["size"])] for a in asks]
            }
    except Exception as e:
        logger.warning(f"拉取实时 CLOB Book 失败 (Token: {token_id}): {e}")
    return {"bids": [], "asks": []}

def fetch_raw_weather_forecast(icao):
    """
    获取站点的 Open-Meteo 实时原始预报 JSON
    """
    try:
        lat, lon = resolve_station_coordinates(icao)
        timezone_map = {
            "ZSSS": "Asia/Shanghai",
            "ZBAA": "Asia/Shanghai",
            "ZGGG": "Asia/Shanghai",
            "ZHHH": "Asia/Shanghai",
            "ZSQD": "Asia/Shanghai",
            "RCTP": "Asia/Taipei",
            "RCSS": "Asia/Taipei",
        }
        timezone = timezone_map.get(icao, "UTC")
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m",
            "models": "icon_seamless",
            "timezone": timezone
        }
        response = requests.get(url, params=params, proxies=PROXIES, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.warning(f"获取气象站 {icao} 原始天气预报失败: {e}")
    return {}

def archive_all_data():
    """
    抓取当前活跃事件的数据归档。由于现在运行前已经做了过滤，为了不丢失其他城市数据，
    归档模块单独使用最底层的全量拉取。
    """
    logger.info("============== 开始全量数据归档 (Backtest Archive) ==============")
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    
    # 临时解开 scanner 补丁以获取全量事件
    original_fetch = getattr(scanner, "original_fetch_events", scanner.fetch_all_active_weather_events)
    try:
        events = original_fetch()
    except Exception as e:
        logger.error(f"拉取 Gamma 事件异常: {e}")
        return

    for e in events:
        title = e.get("title", "")
        desc = e.get("description", "")
        if "temperature" not in title.lower() and "temp" not in title.lower():
            continue
            
        icao = parse_station_icao_from_desc(desc)
        if not icao:
            continue
            
        slug = e["slug"]
        target_date = e.get("eventDate", "")
        if not target_date:
            target_date = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
            
        logger.info(f"归档处理事件: {slug}")
        
        # 1. 抓取 CLOB 实时的订单簿挂单深度
        clob_books = {}
        markets = e.get("markets", [])
        for m in markets:
            clob_tokens_str = m.get("clobTokenIds", "[]")
            if isinstance(clob_tokens_str, str):
                try:
                    clob_tokens = json.loads(clob_tokens_str)
                except Exception:
                    clob_tokens = []
            else:
                clob_tokens = clob_tokens_str
                
            if clob_tokens and len(clob_tokens) > 0:
                yes_token_id = clob_tokens[0]
                clob_books[yes_token_id] = fetch_real_clob_book(yes_token_id)
                
        # 2. 抓取原始预报
        raw_forecast = fetch_raw_weather_forecast(icao)
        
        # 3. 读取计算出来的胜率估算结果 (从 protocols 读取)
        prob_file = os.path.join(PROTOCOLS_DIR, f"weather_probability_{slug}.json")
        calculated_results = {"probability_distribution": []}
        if os.path.exists(prob_file):
            try:
                with open(prob_file, "r", encoding="utf-8") as f_prob:
                    prob_data = json.load(f_prob)
                    calculated_results["probability_distribution"] = prob_data.get("probability_distribution", [])
            except Exception as ex:
                logger.warning(f"读取已计算的概率契约失败: {ex}")
                
        # 4. 组装 backtest_archive 数据
        archive_data = {
            "protocol_version": CONFIG["version"],
            "timestamp": int(time.time()),
            "market_id": slug,
            "target_date": target_date,
            "algorithm_metadata": {
                "algorithm_name": "Monte_Carlo_Temperature_Sampler",
                "algorithm_version": "v3.2",
                "parameters": {
                    "obs_error_sigma_0": CONFIG.get("risk_control_lock", {}).get("obs_error_sigma_0", 0.6),
                    "lead_time_decay_beta": CONFIG.get("risk_control_lock", {}).get("lead_time_decay_beta", 0.15),
                    "mc_samples_per_member": CONFIG.get("risk_control_lock", {}).get("mc_samples_per_member", 100)
                }
            },
            "raw_data": {
                "clob_books": clob_books,
                "raw_forecast": raw_forecast
            },
            "calculated_results": calculated_results
        }
        
        # 5. 契约校验并保存
        try:
            validate_contract(archive_data, "backtest_archive")
            timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_filename = f"{timestamp_str}_{slug}.json"
            archive_path = os.path.join(ARCHIVE_DIR, archive_filename)
            with open(archive_path, "w", encoding="utf-8") as f_arc:
                json.dump(archive_data, f_arc, indent=2, ensure_ascii=False)
            logger.info(f"成功保存全量归档数据: {archive_filename}")
        except Exception as err:
            logger.error(f"归档契约校验失败: {err}")

def setup_glob_monkey_patch(target_filter_str):
    """
    动态拦截全局 glob。
    """
    if not target_filter_str:
        return

    filter_lower = target_filter_str.lower()
    logger.info(f"开启 Glob 内存过滤拦截，专注目标: {target_filter_str}")

    def filtered_glob(pathname, *args, **kwargs):
        files = original_glob(pathname, *args, **kwargs)
        if "market_snapshot_" in pathname or "weather_probability_" in pathname or "arbitrage_signals_" in pathname:
            filtered = [
                f for f in files 
                if filter_lower in os.path.basename(f).lower() or ("zsss" in os.path.basename(f).lower() and filter_lower == "shanghai")
            ]
            return filtered
        return files

    glob.glob = filtered_glob

def setup_scanner_monkey_patch(target_filter_str):
    """
    动态拦截 scanner 接口拉取事件。
    在最源头过滤掉不需要的城市，使 scanner 和 analyst 仅需发起 1 个城市的网络请求，极大加快运行速度！
    """
    if not target_filter_str:
        return

    filter_lower = target_filter_str.lower()
    logger.info(f"开启 Scanner 内存过滤拦截，源头限制目标: {target_filter_str}")

    original_fetch = scanner.fetch_all_active_weather_events
    # 保存备份
    scanner.original_fetch_events = original_fetch

    def filtered_fetch():
        events = original_fetch()
        filtered = [
            e for e in events 
            if filter_lower in e.get("slug", "").lower() or ("zsss" in e.get("description", "").lower() and filter_lower == "shanghai")
        ]
        logger.info(f"[Scanner 拦截] 原始活跃事件 {len(events)} 个，过滤后仅保留 {len(filtered)} 个关于 {target_filter_str} 的事件。")
        return filtered

    scanner.fetch_all_active_weather_events = filtered_fetch

def restore_monkey_patches():
    """
    还原所有补丁
    """
    glob.glob = original_glob
    if hasattr(scanner, "original_fetch_events"):
        scanner.fetch_all_active_weather_events = scanner.original_fetch_events
    logger.info("所有内存过滤拦截补丁已卸载，系统环境复位。")

def run_filtered_pipeline(city_filter, enable_archive=False):
    logger.info(f"==================== 启动专注归档流水线 | 专注目标: {city_filter or '全量'} ====================")
    start_time = time.time()
    try:
        # 1. 开启最源头的扫描器内存拦截 (只保留上海相关的事件列表)
        if city_filter:
            setup_scanner_monkey_patch(city_filter)
            setup_glob_monkey_patch(city_filter)
        
        # 2. 运行市场扫描器 (此时仅对上海进行扫描，1秒完成)
        run_scanner()
        
        # 3. 运行胜率分析器 (此时仅对上海进行气象拉取与自适应纠偏，几秒完成)
        run_analyst()
        
        # 4. 如果需要全量归档，离线执行 (平时手动只跑上海以节省时间，可以关掉 archive 以获得极致速度)
        if enable_archive:
            archive_all_data()
        
        # 5. 运行策略测算 (只看见并处理指定城市的协议)
        run_strategy()
        
        # 6. 动态屏蔽历史待结单气象轮询以实现秒级响应
        import src.executor as executor
        executor.check_and_settle_past_trades = lambda: logger.info("[Orchestrator 拦截] 已禁用历史积压仓位气象结算轮询。")
        
        # 执行下单模块 (只处理指定城市的下单)
        run_executor()
        
        # 7. 还原所有补丁
        restore_monkey_patches()
        
        elapsed = time.time() - start_time
        logger.info(f"==================== 运行成功！总耗时: {elapsed:.2f}秒 ====================")
    except Exception as e:
        logger.critical(f"==================== 运行异常中断！: {e} ====================")
        # 兜底恢复
        restore_monkey_patches()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Polymarket 天气套利专注交易与全量归档外挂")
    parser.add_argument("--city", type=str, default="shanghai", help="专注过滤的城市名称或标的关键字 (默认: shanghai)")
    parser.add_argument("--archive", action="store_true", help="是否在本次手动执行中进行全量归档备份（默认不开启以获得秒级响应速度）")
    parser.add_argument("--loop", action="store_true", help="是否以常驻守护进程模式循环运行")
    args = parser.parse_args()
    
    if args.loop:
        from src.main import get_sleep_interval
        logger.info(f"启动专注守护进程模式 | 专注目标: {args.city}")
        while True:
            run_filtered_pipeline(args.city, args.archive)
            sleep_sec = get_sleep_interval()
            logger.info(f"进入冷却，等待下一次循环 (休眠 {sleep_sec // 60} 分钟)...")
            time.sleep(sleep_sec)
    else:
        run_filtered_pipeline(args.city, args.archive)
