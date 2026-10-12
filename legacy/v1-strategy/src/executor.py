import os
import json
import time
import sqlite3
import datetime
import requests
import glob
from src.config import CONFIG, PROXIES, setup_logger
import src.weather_cache as weather_cache

logger = setup_logger("Executor")

STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage")
DB_PATH = os.path.join(STORAGE_DIR, "arbitrage.db")
PROTOCOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocols")

def init_db():
    os.makedirs(STORAGE_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            market_id TEXT NOT NULL,
            range_id TEXT NOT NULL,
            station_id TEXT NOT NULL,
            condition TEXT NOT NULL,
            stake_usdc REAL NOT NULL,
            ask_price REAL NOT NULL,
            expected_value REAL NOT NULL,
            real_prob REAL NOT NULL,
            status TEXT NOT NULL,
            settlement_date TEXT NOT NULL,
            tx_hash TEXT NOT NULL,
            realized_pnl REAL DEFAULT 0.0,
            trade_type TEXT DEFAULT 'YES'
        )
    """)
    # 增量更新 trade_type 字段
    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN trade_type TEXT DEFAULT 'YES'")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()
def is_signal_already_executed(market_id, range_id, settlement_date, trade_type='YES', signal_timestamp=0):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM trades WHERE market_id = ? AND range_id = ? AND settlement_date = ? AND trade_type = ? AND timestamp >= ?", 
        (market_id, range_id, settlement_date, trade_type, signal_timestamp)
    )
    row = cursor.fetchone()
    conn.close()
    return row is not None

def execute_buy_dry_run(market_id, range_id, station_id, condition, stake_usdc, ask_price, ev, real_prob, settlement_date, trade_type='YES'):
    timestamp = int(time.time())
    tx_hash = f"0xmock_{timestamp:x}{int(stake_usdc*100):x}"
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO trades (timestamp, market_id, range_id, station_id, condition, stake_usdc, ask_price, expected_value, real_prob, status, settlement_date, tx_hash, realized_pnl, trade_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (timestamp, market_id, range_id, station_id, condition, stake_usdc, ask_price, ev, real_prob, 'PENDING', settlement_date, tx_hash, 0.0, trade_type))
    conn.commit()
    conn.close()
    
    logger.info(
        f"【Dry-Run 下单成功】购买 {trade_type} 合约 | 市场: {market_id} | 区间: {condition} | "
        f"价格: {ask_price} | 投入: {stake_usdc} USDC | Mock哈希: {tx_hash}",
        extra={"market_id": market_id}
    )

def check_and_settle_past_trades():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 先拉取所有 PENDING 交易，后续按各交易对应的气象站当地时间逐个判断是否已过结算日
    # 支持选择 trade_type
    try:
        cursor.execute("SELECT id, market_id, station_id, condition, stake_usdc, ask_price, settlement_date, trade_type FROM trades WHERE status = 'PENDING'")
        pending_trades = cursor.fetchall()
    except sqlite3.OperationalError:
        cursor.execute("SELECT id, market_id, station_id, condition, stake_usdc, ask_price, settlement_date FROM trades WHERE status = 'PENDING'")
        pending_trades = [row + ('YES',) for row in cursor.fetchall()]

    if not pending_trades:
        conn.close()
        return

    logger.info(f"发现 {len(pending_trades)} 笔待结算的历史模拟仓位，启动自动气象结算...", extra={"market_id": "SETTLEMENT"})

    from src.analyst import resolve_station_coordinates, check_condition
    from src.weather_cache import resolve_station_timezone
    import pytz

    for trade_id, m_id, station_id, condition, stake_usdc, ask_price, settlement_date, trade_type in pending_trades:
        try:
            # 按气象站当地时间判断结算日是否已结束（跨时区安全）
            try:
                tz = pytz.timezone(resolve_station_timezone(station_id))
                station_today_str = datetime.datetime.now(tz).strftime("%Y-%m-%d")
            except Exception:
                station_today_str = datetime.date.today().strftime("%Y-%m-%d")
            if settlement_date >= station_today_str:
                continue

            # 优先使用 Polymarket Gamma API 的官方结算结果（最精准，避免因气象源差异导致结算错误）
            gamma_resolved = False
            winning_condition = None
            event_closed = False
            try:
                gamma_url = f"https://gamma-api.polymarket.com/events?slug={m_id}"
                res = requests.get(gamma_url, proxies=PROXIES, timeout=10)
                if res.status_code == 200:
                    events = res.json()
                    if events and isinstance(events, list):
                        event = events[0]
                        event_closed = event.get("closed", False)
                        if event_closed:
                            from src.scanner import parse_weather_condition
                            markets = event.get("markets", [])
                            for m in markets:
                                outcome_prices_str = m.get("outcomePrices")
                                if isinstance(outcome_prices_str, str):
                                    try:
                                        prices = json.loads(outcome_prices_str)
                                    except:
                                        prices = []
                                else:
                                    prices = outcome_prices_str
                                
                                if prices and len(prices) >= 2:
                                    # 如果 YES 合约结算价趋近 1 (或大于 0.99)，则该 market 条件为获胜档位
                                    if float(prices[0]) > 0.99:
                                        winning_condition = parse_weather_condition(m.get("question", ""))
                                        break
                            if winning_condition is not None:
                                gamma_resolved = True
            except Exception as ex:
                logger.warning(f"尝试从 Polymarket 接口拉取结算状态失败: {ex}", extra={"market_id": m_id})

            if gamma_resolved:
                is_yes_win = (condition == winning_condition)
                is_win = is_yes_win if trade_type.upper() == 'YES' else (not is_yes_win)
                status = 'WON' if is_win else 'LOST'
                
                if is_win:
                    pnl = round(stake_usdc * (1.0 / ask_price - 1.0), 2)
                else:
                    pnl = -stake_usdc
                    
                cursor.execute(
                    "UPDATE trades SET status = ?, realized_pnl = ? WHERE id = ?",
                    (status, pnl, trade_id)
                )
                logger.info(
                    f"【账本结算完成】交易ID: {trade_id} ({trade_type}) | 日期: {settlement_date} | "
                    f"结算来源: Polymarket官方 | 获胜档位: {winning_condition} | 结果: {status} | 净利润: {pnl} USDC",
                    extra={"market_id": m_id}
                )
                continue

            # 如果 Polymarket 官方还未正式关闭，则坚决保持 PENDING，不使用气象观测数据进行预测结算
            if not event_closed:
                logger.info(f"市场 {m_id} 在 Polymarket 上尚未正式关闭结算，保持 PENDING", extra={"market_id": m_id})
                continue

            # ----------------- 备用方案：Wunderground 官方气象实况结算 -----------------
            is_lowest = "lowest" in m_id.lower() or "lowest" in condition.lower()
            cached_res = weather_cache.get_cached_stats(station_id, [settlement_date], is_lowest)
            
            if settlement_date in cached_res:
                _, actual_obs = cached_res[settlement_date]
            else:
                # 缓存未命中，调用 Wunderground 接口拉取历史极值并更新缓存
                wu_data = weather_cache.fetch_wunderground_daily_history(station_id)
                day_wu = wu_data.get(settlement_date)
                if day_wu:
                    actual_obs = day_wu["min_temp"] if is_lowest else day_wu["max_temp"]
                    if actual_obs is not None:
                        # 结算只关注实况，我们把 forecast_extreme 设为与实况一致写入缓存
                        weather_cache.save_cached_stats(station_id, settlement_date, is_lowest, actual_obs, actual_obs, is_complete=1)
                else:
                    actual_obs = None
                    
            if actual_obs is None:
                logger.warning(f"无法从 Wunderground 获取 {station_id} 在 {settlement_date} 的历史实况，跳过本次结算", extra={"market_id": m_id})
                continue
                
            # 检测是否为华氏度合约 (美国站点或者 condition 数值大于 50)
            is_fahrenheit = False
            if weather_cache.get_country_code_by_icao(station_id) == "US":
                is_fahrenheit = True
            else:
                import re
                digits = [int(d) for d in re.findall(r"\d+", condition)]
                if digits and any(d > 50 for d in digits):
                    is_fahrenheit = True

            if is_fahrenheit:
                import math
                actual_calibrated_temp = int(math.floor(actual_obs * 9.0 / 5.0 + 32.0))
            else:
                actual_calibrated_temp = round(actual_obs)
            
            is_yes_win = check_condition(actual_calibrated_temp, condition)
            # 计算 YES/NO 是否胜出
            is_win = is_yes_win if trade_type.upper() == 'YES' else (not is_yes_win)
            
            status = 'WON' if is_win else 'LOST'
            if is_win:
                pnl = round(stake_usdc * (1.0 / ask_price - 1.0), 2)
            else:
                pnl = -stake_usdc
                
            cursor.execute(
                "UPDATE trades SET status = ?, realized_pnl = ? WHERE id = ?",
                (status, pnl, trade_id)
            )
            logger.info(
                f"【账本结算完成】交易ID: {trade_id} ({trade_type}) | 日期: {settlement_date} | 气象站: {station_id} | "
                f"结算来源: Wunderground气象计算 | 实际极值温: {actual_calibrated_temp}°C | 条件: {condition} | 结果: {status} | 净利润: {pnl} USDC",
                extra={"market_id": m_id}
            )
            
        except Exception as e:
            logger.error(f"结算交易ID {trade_id} 异常: {str(e)}", extra={"market_id": m_id})
            
    conn.commit()
    conn.close()

def execute_single_signal(sig_path):
    """
    处理单个城市的信号下达（YES/NO 双向支持）
    """
    filename = os.path.basename(sig_path)
    slug = filename.replace("arbitrage_signals_", "").replace(".json", "")
    snapshot_path = os.path.join(PROTOCOLS_DIR, f"market_snapshot_{slug}.json")
    
    if not os.path.exists(snapshot_path):
        logger.error(f"找不到信号对应的快照文件，跳过下单: {snapshot_path}", extra={"market_id": "EXECUTOR"})
        return

    try:
        with open(snapshot_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)
        with open(sig_path, "r", encoding="utf-8") as f:
            signals = json.load(f)
    except Exception as e:
        logger.error(f"读取下单信号或快照文件失败，跳过下单: {str(e)}", extra={"market_id": "EXECUTOR"})
        return

    market_id = snapshot["market_id"]
    station_id = snapshot["station_info"]["station_id"]
    settlement_date = snapshot["target_date"]
    
    # 增加过期信号拦截与自动清理：若信号对应的结算日期是气象站当地时间今天之前（历史合约），拒绝执行模拟下单并清理信号文件
    import datetime, pytz
    from src.weather_cache import resolve_station_timezone
    try:
        tz = pytz.timezone(resolve_station_timezone(station_id))
        today_str = datetime.datetime.now(tz).strftime("%Y-%m-%d")
    except Exception:
        today_str = datetime.date.today().strftime("%Y-%m-%d")
    if settlement_date < today_str:
        logger.warning(
            f"【交易拦截与清理】信号对应的结算日期 {settlement_date} 已经是站点今天 {today_str} 之前，拒绝执行历史信号下单并删除陈旧信号文件 {os.path.basename(sig_path)}。",
            extra={"market_id": market_id}
        )
        try:
            os.remove(sig_path)
        except Exception:
            pass
        return
        
    # 获取信号生成时间戳，作为去重参考点
    signal_timestamp = signals.get("timestamp", 0)
    
    execution_signals = signals.get("execution_signals", [])
    
    # 优先从 cities.json 统一配置文件中校验是否允许下注交易
    try:
        from src.config import load_cities_config
        cities_config = load_cities_config()
        station_id_upper = station_id.upper().strip()
        if station_id_upper in cities_config:
            if not cities_config[station_id_upper].get("is_tradable", True):
                logger.info(
                    f"【交易过滤拦截】根据 cities.json 配置，当前城市设定为只拉取数据、禁止投注交易。市场: {market_id} | 气象站: {station_id}",
                    extra={"market_id": market_id}
                )
                return
    except Exception as e:
        logger.warning(f"读取 cities.json 过滤校验失败: {e}，继续默认流程...")
        
    # 获取配置的允许交易城市白名单
    allowed_cities = CONFIG.get("risk_control_lock", {}).get("allowed_cities", None)
    if allowed_cities is not None:
        station_id_upper = station_id.upper().strip()
        allowed_cities_upper = [c.upper().strip() for c in allowed_cities]
        if station_id_upper not in allowed_cities_upper:
            logger.info(
                f"【交易过滤拦截】根据 allowed_cities 配置过滤非白名单城市。市场: {market_id} | 气象站: {station_id}",
                extra={"market_id": market_id}
            )
            return

    for sig in execution_signals:
        action = sig["action"]
        if action in ("BUY_YES", "BUY_NO"):
            range_id = sig["range_id"]
            condition = sig["condition"]
            stake_usdc = sig["recommended_stake_usdc"]
            ask_price = sig["market_ask"]
            ev = sig["expected_value"]
            real_prob = sig["real_prob"]
            trade_type = "YES" if action == "BUY_YES" else "NO"
            
            # 使用信号时间戳防止单次轮询内的重复成交，并允许后续轮询中因参数变动产生的新订单
            if is_signal_already_executed(market_id, range_id, settlement_date, trade_type, signal_timestamp):
                logger.warning(
                    f"【交易拦截】该交易信号在本轮运行中已执行过，跳过下单。类型: {trade_type} | 条件: {condition} | 日期: {settlement_date}",
                    extra={"market_id": market_id}
                )
                continue
                
            if stake_usdc <= 0:
                continue
                
            execute_buy_dry_run(
                market_id=market_id,
                range_id=range_id,
                station_id=station_id,
                condition=condition,
                stake_usdc=stake_usdc,
                ask_price=ask_price,
                ev=ev,
                real_prob=real_prob,
                settlement_date=settlement_date,
                trade_type=trade_type
            )

def run_executor():
    """
    遍历处理所有交易信号
    """
    logger.info("启动交易执行官...", extra={"market_id": "EXECUTOR"})
    init_db()
    
    # 自动对过期仓位跑结算
    check_and_settle_past_trades()
    
    sig_files = glob.glob(os.path.join(PROTOCOLS_DIR, "arbitrage_signals_*.json"))
    if not sig_files:
        logger.warning("未在 protocols/ 目录下发现任何活跃的 arbitrage_signals 协议文件，退出执行器。", extra={"market_id": "EXECUTOR"})
        return

    for sig_path in sig_files:
        execute_single_signal(sig_path)
            
    logger.info("交易执行流水线运行结束。", extra={"market_id": "EXECUTOR"})

if __name__ == "__main__":
    run_executor()
