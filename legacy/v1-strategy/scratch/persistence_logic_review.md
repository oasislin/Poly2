# Polymarket 天气套利系统：本地数据持久化与存储逻辑审核手册

本手册汇集整理了系统当前所有涉及**本地数据库 (SQLite)** 以及 **JSON 归档文件**的持久化逻辑、数据库 Schema 设计以及核心读写函数实现，以便于对存储层架构进行独立审核。

---

## 1. 存储架构概览

系统在本地运行两个独立的 SQLite 数据库，并包含一个归档 JSON 目录：

1. **天气缓存数据库** (`storage/weather_cache.db`)
   - **目的**：缓存气象站的历史预报均值与 Wunderground 真实观测极值。
   - **作用**：加速 Moving Window 纠偏计算（避免重复请求 API 触发限频），同时为物理结算提供直接依据。
2. **交易账本数据库** (`storage/arbitrage.db`)
   - **目的**：记录程序的所有模拟/实盘交易订单、状态以及最终实现的 PnL 盈亏账本。
   - **作用**：防止同一盘口重复买入（幂等性保护），支持异步物理对账结算。
3. **历史数据归档库** (`storage/archive/`)
   - **目的**：以 `YYYYMMDD_HHMMSS_{market_slug}.json` 的格式，完整打包备份每一轮的盘口快照、Open-Meteo 原始预报、Wunderground 当日实况、CLOB 订单簿深度与模型计算出的胜率分布。

---

## 2. 数据库设计 (Schema)

### 2.1 天气缓存表 `cached_stats`
* **表结构**：
  ```sql
  CREATE TABLE IF NOT EXISTS cached_stats (
      station_id TEXT NOT NULL,
      date TEXT NOT NULL,
      is_lowest INTEGER NOT NULL,          -- 1 代表最低温，0 代表最高温
      forecast_extreme REAL NOT NULL,      -- 集合预报在纠偏样本天的预测极值均值
      observed_extreme REAL NOT NULL,      -- Wunderground 在该日发生的真实观测极值
      PRIMARY KEY (station_id, date, is_lowest)
  );
  ```

### 2.2 交易明细账本表 `trades`
* **表结构**：
  ```sql
  CREATE TABLE IF NOT EXISTS trades (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      timestamp INTEGER NOT NULL,
      market_id TEXT NOT NULL,
      range_id TEXT NOT NULL,
      condition TEXT NOT NULL,
      trade_type TEXT NOT NULL,            -- 'YES' 或 'NO'
      ask_price REAL NOT NULL,
      stake_usdc REAL NOT NULL,
      status TEXT DEFAULT 'PENDING',       -- 'PENDING', 'WON', 'LOST', 'REFUNDED'
      realized_pnl REAL DEFAULT 0.0,
      settlement_date TEXT NOT NULL        -- 结算日期格式 'YYYY-MM-DD'
  );
  ```

---

## 3. 天气缓存读写逻辑实现 (`src/weather_cache.py`)

以下是负责与天气 SQLite 缓存交互的三个核心底层函数：

```python
import os
import sqlite3
import logging

logger = logging.getLogger("WeatherCache")

STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage")
WEATHER_DB_PATH = os.path.join(STORAGE_DIR, "weather_cache.db")

def init_db():
    """初始化天气缓存数据库及表结构"""
    os.makedirs(STORAGE_DIR, exist_ok=True)
    conn = sqlite3.connect(WEATHER_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cached_stats (
            station_id TEXT NOT NULL,
            date TEXT NOT NULL,
            is_lowest INTEGER NOT NULL,
            forecast_extreme REAL NOT NULL,
            observed_extreme REAL NOT NULL,
            PRIMARY KEY (station_id, date, is_lowest)
        )
    """)
    conn.commit()
    conn.close()

def get_cached_stats(station_id, dates, is_lowest):
    """
    批量获取指定日期范围的天气缓存
    :return: dict -> { date_str: (forecast_extreme, observed_extreme) }
    """
    init_db()
    if not dates:
        return {}
        
    conn = sqlite3.connect(WEATHER_DB_PATH)
    cursor = conn.cursor()
    
    placeholders = ",".join(["?"] * len(dates))
    query = f"""
        SELECT date, forecast_extreme, observed_extreme 
        FROM cached_stats 
        WHERE station_id = ? AND is_lowest = ? AND date IN ({placeholders})
    """
    
    lowest_int = 1 if is_lowest else 0
    params = [station_id, lowest_int] + list(dates)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return {row[0]: (row[1], row[2]) for row in rows}

def save_cached_stats(station_id, date_str, is_lowest, forecast_extreme, observed_extreme):
    """保存或更新单条天气指标缓存"""
    init_db()
    conn = sqlite3.connect(WEATHER_DB_PATH)
    cursor = conn.cursor()
    lowest_int = 1 if is_lowest else 0
    
    cursor.execute("""
        INSERT OR REPLACE INTO cached_stats 
        (station_id, date, is_lowest, forecast_extreme, observed_extreme)
        VALUES (?, ?, ?, ?, ?)
    """, (station_id, date_str, lowest_int, float(forecast_extreme), float(observed_extreme)))
    
    conn.commit()
    conn.close()
```

---

## 4. 交易账本读写逻辑实现 (`src/executor.py`)

以下是交易官模块中用于维护 SQLite 交易账本与执行防重校验的核心函数：

```python
import os
import sqlite3
import time
import logging

logger = logging.getLogger("Executor")

STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage")
DB_PATH = os.path.join(STORAGE_DIR, "arbitrage.db")

def init_db():
    """初始化交易账本数据库及表结构"""
    os.makedirs(STORAGE_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            market_id TEXT NOT NULL,
            range_id TEXT NOT NULL,
            condition TEXT NOT NULL,
            trade_type TEXT NOT NULL,
            ask_price REAL NOT NULL,
            stake_usdc REAL NOT NULL,
            status TEXT DEFAULT 'PENDING',
            realized_pnl REAL DEFAULT 0.0,
            settlement_date TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def has_active_position(market_id, range_id, trade_type):
    """
    防重校验：检查该市场该档位是否已有同方向的未结算（PENDING）或已成交仓位
    防止在极短的轮询时间内发生重复下单
    """
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT id FROM trades WHERE market_id = ? AND range_id = ? AND trade_type = ? AND status = 'PENDING'",
        (market_id, range_id, trade_type)
    )
    row = cursor.fetchone()
    conn.close()
    return row is not None

def record_trade(market_id, range_id, condition, trade_type, ask_price, stake_usdc, settlement_date):
    """向本地账本写入一笔新成交的交易（状态默认为 PENDING）"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO trades (timestamp, market_id, range_id, condition, trade_type, ask_price, stake_usdc, settlement_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (int(time.time()), market_id, range_id, condition, trade_type, float(ask_price), float(stake_usdc), settlement_date))
    
    conn.commit()
    conn.close()
    logger.info(f"成功向数据库持久化交易：{market_id} | {range_id} | {trade_type} | {stake_usdc} USDC")
```

---

## 5. 归档序列化逻辑实现 (`src/archiver.py`)

系统每轮运行结束后，自动提取各环节产生的 JSON 协议文件，整合并持久化到归档目录下。以下是核心组装与去重保存流程：

```python
import os
import glob
import json
import time
import datetime
from src.config import CONFIG, setup_logger, validate_contract

logger = setup_logger("Archiver")

PROTOCOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "protocols")
STORAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "storage")
ARCHIVE_DIR = os.path.join(STORAGE_DIR, "archive")

def run_archiver():
    """
    数据归档模块：将当前轮次活跃市场的快照、预报、订单簿及 Wunderground 实况打包序列化。
    """
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    snapshot_files = glob.glob(os.path.join(PROTOCOLS_DIR, "market_snapshot_*.json"))
    
    for snap_path in snapshot_files:
        filename = os.path.basename(snap_path)
        slug = filename.replace("market_snapshot_", "").replace(".json", "")
        
        prob_path = os.path.join(PROTOCOLS_DIR, f"weather_probability_{slug}.json")
        sig_path = os.path.join(PROTOCOLS_DIR, f"arbitrage_signals_{slug}.json")

        if not os.path.exists(prob_path) or not os.path.exists(sig_path):
            continue

        try:
            with open(snap_path, "r", encoding="utf-8") as f:
                snapshot = json.load(f)
            with open(prob_path, "r", encoding="utf-8") as f:
                probability = json.load(f)
            with open(sig_path, "r", encoding="utf-8") as f:
                signals = json.load(f)

            # 提取已由天气分析器（Analyst）及策略引擎（Strategy）嵌入的底层原始数据
            raw_forecast = probability.get("_raw_open_meteo_response", {})
            raw_observed = probability.get("_raw_wunderground_observed", None) # Wunderground 决战实况数据
            clob_books = signals.get("_raw_clob_books", {})

            # 按照强约束契约 Schema 组装归档对象
            archive_data = {
                "protocol_version": CONFIG["version"],
                "timestamp": snapshot.get("timestamp", int(time.time())),
                "market_id": slug,
                "target_date": snapshot["target_date"],
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
                    "raw_forecast": raw_forecast,
                    "market_snapshot": snapshot,
                    "raw_observed": raw_observed  # 持久化为历史回测打底的 Wunderground 真实观测数据
                },
                "calculated_results": {
                    "probability_distribution": probability.get("probability_distribution", [])
                }
            }

            # 执行 JSON Schema 契约校验，确保格式安全
            validate_contract(archive_data, "backtest_archive")

            # 去重：同市场且同时间戳的归档文件跳过写入
            target_timestamp = archive_data["timestamp"]
            existing = glob.glob(os.path.join(ARCHIVE_DIR, f"*_{slug}.json"))
            is_duplicate = False
            for old_path in existing:
                try:
                    with open(old_path, "r", encoding="utf-8") as f_old:
                        if json.load(f_old).get("timestamp") == target_timestamp:
                            is_duplicate = True
                            break
                except Exception:
                    pass

            if is_duplicate:
                continue

            # 按时间戳与 Slug 命名并写入本地 JSON 归档文件
            dt_str = datetime.datetime.fromtimestamp(target_timestamp).strftime("%Y%m%d_%H%M%S")
            archive_name = f"{dt_str}_{slug}.json"
            archive_path = os.path.join(ARCHIVE_DIR, archive_name)

            with open(archive_path, "w", encoding="utf-8") as f_out:
                json.dump(archive_data, f_out, indent=2, ensure_ascii=False)
                
            logger.info(f"成功归档历史数据：{archive_name}")

        except Exception as e:
            logger.error(f"处理市场 {slug} 归档失败: {e}")
```
