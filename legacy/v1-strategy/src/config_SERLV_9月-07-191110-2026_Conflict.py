import os
import yaml
import logging
from logging.handlers import RotatingFileHandler
import jsonschema
from jsonschema import validate

# 默认路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "config.yaml")
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
LOG_PATH = os.path.join(STORAGE_DIR, "bot.log")

# 加载 .env 环境变量
def load_env():
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

load_env()

# 加载 config.yaml 并组合环境变量
if not os.path.exists(CONFIG_PATH):
    # 退而求其次，寻找 example
    CONFIG_PATH = os.path.join(BASE_DIR, "config", "config.yaml.example")

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

# 合并环境变量配置
CONFIG["private_key"] = os.environ.get("POLYMARKET_PRIVATE_KEY", "0x0000000000000000000000000000000000000000000000000000000000000000")
CONFIG["http_proxy"] = os.environ.get("LAN_HTTP_PROXY", None)
CONFIG["https_proxy"] = os.environ.get("LAN_HTTPS_PROXY", None)

# 设置代理字典
PROXIES = None
if CONFIG["http_proxy"] or CONFIG["https_proxy"]:
    PROXIES = {
        "http": CONFIG["http_proxy"],
        "https": CONFIG["https_proxy"] or CONFIG["http_proxy"]
    }

# ----------------- 结构化滚动日志系统 -----------------
class CustomFormatter(logging.Formatter):
    """
    格式: [时间戳] [模块名称] [日志级别] [全局事务ID/市场ID] | [核心事件与上下文数据]
    """
    def format(self, record):
        timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        module_name = record.name
        level = record.levelname
        # 提取额外参数 (用于全局事务ID/市场ID)，默认填充 '-'
        market_id = getattr(record, "market_id", "-")
        message = record.getMessage()
        return f"[{timestamp}] [{module_name}] [{level}] [{market_id}] | {message}"

def setup_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # 避免重复绑定 handler
    if logger.hasHandlers():
        return logger

    # 控制台 Handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(CustomFormatter())
    logger.addHandler(ch)

    # 滚动文件 Handler (最大 10MB, 最多保留 3 个历史备份，总物理上限 <= 40MB)
    os.makedirs(STORAGE_DIR, exist_ok=True)
    fh = RotatingFileHandler(LOG_PATH, maxBytes=10*1024*1024, backupCount=3, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(CustomFormatter())
    logger.addHandler(fh)

    return logger

# ----------------- 数据契约 (JSON Schema) 定义 -----------------
SCHEMAS = {
    "market_snapshot": {
        "type": "object",
        "required": ["protocol_version", "timestamp", "market_id", "station_info", "target_date", "resolution_precision", "ranges"],
        "properties": {
            "protocol_version": { "type": "string" },
            "timestamp": { "type": "integer" },
            "market_id": { "type": "string" },
            "station_info": {
                "type": "object",
                "required": ["station_id", "city", "timezone"],
                "properties": {
                    "station_id": { "type": "string" },
                    "city": { "type": "string" },
                    "timezone": { "type": "string" }
                }
            },
            "target_date": { "type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$" },
            "resolution_precision": { "type": "string", "enum": ["INT_CELSIUS", "FLOAT_CELSIUS", "INT_FAHRENHEIT"] },
            "status": { "type": "string", "enum": ["active", "inactive"] },
            "ranges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["range_id", "condition", "ask_price"],
                    "properties": {
                        "range_id": { "type": "string" },
                        "condition": { "type": "string" },
                        "ask_price": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
                        "yes_ask": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
                        "no_ask": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
                        "yes_token_id": { "type": "string" },
                        "no_token_id": { "type": "string" }
                    }
                }
            }
        }
    },
    
    "weather_probability": {
        "type": "object",
        "required": ["protocol_version", "timestamp", "market_id", "target_date", "total_effective_members", "probability_distribution"],
        "properties": {
            "protocol_version": { "type": "string" },
            "timestamp": { "type": "integer" },
            "market_id": { "type": "string" },
            "target_date": { "type": "string" },
            "total_effective_members": { "type": "integer", "minimum": 1 },
            "probability_distribution": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["condition", "calculated_prob"],
                    "properties": {
                        "condition": { "type": "string" },
                        "calculated_prob": { "type": "number", "minimum": 0.0, "maximum": 1.0 }
                    }
                }
            }
        }
    },

    "arbitrage_signals": {
        "type": "object",
        "required": ["protocol_version", "timestamp", "execution_signals"],
        "properties": {
            "protocol_version": { "type": "string" },
            "timestamp": { "type": "integer" },
            "execution_signals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["market_id", "range_id", "condition", "market_ask", "real_prob", "expected_value", "action", "recommended_stake_usdc"],
                    "properties": {
                        "market_id": { "type": "string" },
                        "range_id": { "type": "string" },
                        "condition": { "type": "string" },
                        "market_ask": { "type": "number" },
                        "real_prob": { "type": "number" },
                        "expected_value": { "type": "number" },
                        "action": { "type": "string", "enum": ["BUY_YES", "BUY_NO", "HOLD_SATISFIED", "HOLD_INACTIVE", "IGNORE_NO_EDGE", "IGNORE_LOW_EDGE"] },
                        "recommended_stake_usdc": { "type": "number", "minimum": 0.0 }
                    }
                }
            }
        }
    },

    "backtest_archive": {
        "type": "object",
        "required": ["protocol_version", "timestamp", "market_id", "target_date", "algorithm_metadata", "raw_data", "calculated_results"],
        "properties": {
            "protocol_version": { "type": "string" },
            "timestamp": { "type": "integer" },
            "market_id": { "type": "string" },
            "target_date": { "type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$" },
            "algorithm_metadata": {
                "type": "object",
                "required": ["algorithm_name", "algorithm_version", "parameters"],
                "properties": {
                    "algorithm_name": { "type": "string" },
                    "algorithm_version": { "type": "string" },
                    "parameters": { "type": "object" }
                }
            },
            "raw_data": {
                "type": "object",
                "required": ["clob_books", "raw_forecast", "market_snapshot"],
                "properties": {
                    "clob_books": {
                        "type": "object",
                        "description": "按 Token ID 记录的每个档位实时的订单簿买卖深度"
                    },
                    "raw_forecast": {
                        "type": "object",
                        "description": "抓取的原始天气预报数据（Open-Meteo 返回 of JSON 结构）"
                    },
                    "market_snapshot": {
                        "type": "object",
                        "description": "Scanner 阶段抓取的 Polymarket 盘口快照"
                    },
                    "raw_observed": {
                        "type": ["object", "number", "null"],
                        "description": "抓取的 Wunderground 原始实况极值或当前已发生数据"
                    }
                }
            },
            "calculated_results": {
                "type": "object",
                "required": ["probability_distribution"],
                "properties": {
                    "probability_distribution": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["condition", "calculated_prob"],
                            "properties": {
                                "condition": { "type": "string" },
                                "calculated_prob": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
                                "standard_error": { "type": "number" }
                            }
                        }
                    }
                }
            }
        }
    }
}

def validate_contract(data, schema_name):
    """
    遵循“契约优先原则（Contract-First）”，验证输入输出 JSON 格式
    """
    if schema_name not in SCHEMAS:
        raise ValueError(f"Unknown schema name: {schema_name}")
    try:
        validate(instance=data, schema=SCHEMAS[schema_name])
        return True
    except jsonschema.exceptions.ValidationError as e:
        # 抛出清晰的契约校验错误
        raise jsonschema.exceptions.ValidationError(
            f"数据契约 [{schema_name}] 校验失败！具体错误: {e.message} @ 路径: {list(e.absolute_path)}"
        ) from e

# ----------------- 人工干预配置管理 -----------------
CUSTOM_MAPPINGS_PATH = os.path.join(STORAGE_DIR, "custom_station_mappings.json")
PENDING_STATIONS_PATH = os.path.join(STORAGE_DIR, "pending_stations.json")

def load_custom_station_mappings():
    """
    加载用户通过仪表盘手动配置的气象站映射（包含时区、经纬度兜底等）
    """
    if os.path.exists(CUSTOM_MAPPINGS_PATH):
        try:
            import json
            with open(CUSTOM_MAPPINGS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_custom_station_mapping(station_id, timezone, lat, lon):
    """
    保存/新增自定义气象站映射
    """
    mappings = load_custom_station_mappings()
    mappings[station_id.upper().strip()] = {
        "timezone": timezone.strip(),
        "lat": float(lat),
        "lon": float(lon)
    }
    import json
    os.makedirs(STORAGE_DIR, exist_ok=True)
    with open(CUSTOM_MAPPINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(mappings, f, indent=2, ensure_ascii=False)
    
    # 自动清除 pending 中的该站记录
    clear_pending_station(station_id)

def add_pending_station(station_id, city, error_type, details):
    """
    将待校正的气象站加入到 pending_stations.json 列表中
    """
    import time
    station_id = station_id.upper().strip()
    pending = {}
    if os.path.exists(PENDING_STATIONS_PATH):
        try:
            import json
            with open(PENDING_STATIONS_PATH, "r", encoding="utf-8") as f:
                pending = json.load(f)
        except Exception:
            pass
    
    pending[station_id] = {
        "station_id": station_id,
        "city": city,
        "error_type": error_type,
        "details": details,
        "timestamp": int(time.time())
    }
    
    import json
    os.makedirs(STORAGE_DIR, exist_ok=True)
    with open(PENDING_STATIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(pending, f, indent=2, ensure_ascii=False)

def clear_pending_station(station_id):
    """
    从待校正列表中移除某个气象站
    """
    station_id = station_id.upper().strip()
    if not os.path.exists(PENDING_STATIONS_PATH):
        return
    try:
        import json
        with open(PENDING_STATIONS_PATH, "r", encoding="utf-8") as f:
            pending = json.load(f)
        if station_id in pending:
            del pending[station_id]
            with open(PENDING_STATIONS_PATH, "w", encoding="utf-8") as f:
                json.dump(pending, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

CITIES_CONFIG_PATH = os.path.join(BASE_DIR, "config", "cities.json")

def load_cities_config() -> dict:
    """
    加载所有气象城市站点的配置数据
    """
    if os.path.exists(CITIES_CONFIG_PATH):
        try:
            import json
            with open(CITIES_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_cities_config(config_dict: dict):
    """
    保存气象城市站点的配置数据到 cities.json
    """
    import json
    os.makedirs(os.path.dirname(CITIES_CONFIG_PATH), exist_ok=True)
    with open(CITIES_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config_dict, f, indent=2, ensure_ascii=False)

