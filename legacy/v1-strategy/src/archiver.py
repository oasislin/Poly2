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
    数据归档流水线步骤：将当前轮次活跃市场的快照、预报及订单簿数据打包归档。
    """
    logger.info("启动数据归档器...", extra={"market_id": "ARCHIVER"})
    os.makedirs(ARCHIVE_DIR, exist_ok=True)

    snapshot_files = glob.glob(os.path.join(PROTOCOLS_DIR, "market_snapshot_*.json"))
    if not snapshot_files:
        logger.warning("没有发现活跃的市场快照，跳过本次归档。", extra={"market_id": "ARCHIVER"})
        return

    for snap_path in snapshot_files:
        filename = os.path.basename(snap_path)
        slug = filename.replace("market_snapshot_", "").replace(".json", "")
        
        prob_path = os.path.join(PROTOCOLS_DIR, f"weather_probability_{slug}.json")
        sig_path = os.path.join(PROTOCOLS_DIR, f"arbitrage_signals_{slug}.json")

        if not os.path.exists(prob_path) or not os.path.exists(sig_path):
            logger.warning(f"市场 {slug} 缺失胜率或信号契约文件，跳过归档。", extra={"market_id": slug})
            continue

        try:
            with open(snap_path, "r", encoding="utf-8") as f:
                snapshot = json.load(f)
            with open(prob_path, "r", encoding="utf-8") as f:
                probability = json.load(f)
            with open(sig_path, "r", encoding="utf-8") as f:
                signals = json.load(f)

            # 提取已嵌入的原始数据
            raw_forecast = probability.get("_raw_open_meteo_response", {})
            raw_observed = probability.get("_raw_wunderground_observed", None)
            raw_hourly_obs = probability.get("_raw_wunderground_hourly_obs", [])
            clob_books = signals.get("_raw_clob_books", {})

            # 组装归档结构
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
                    "raw_observed": raw_observed,
                    "raw_hourly_obs": raw_hourly_obs
                },
                "calculated_results": {
                    "probability_distribution": probability.get("probability_distribution", []),
                    "bias": probability.get("_bias", 0.0),
                    "rolling_sigma": probability.get("_rolling_sigma", None),
                    "daily_residuals": probability.get("_daily_residuals", []),
                    "simulated_sigma": probability.get("_simulated_sigma", None),
                    "ref_hour": probability.get("ref_hour", None),
                    "total_effective_members": probability.get("total_effective_members", 0),
                    "execution_signals": signals.get("execution_signals", []),
                    "strategy_metadata": signals.get("metadata", {})
                }
            }

            # 校验契约
            validate_contract(archive_data, "backtest_archive")

            # 去重：检查是否已有相同时间戳的归档文件
            target_timestamp = archive_data["timestamp"]
            # 通过匹配后缀查找
            existing = glob.glob(os.path.join(ARCHIVE_DIR, f"*_{slug}.json"))
            is_duplicate = False
            for old_path in existing:
                try:
                    with open(old_path, "r", encoding="utf-8") as f_old:
                        old_data = json.load(f_old)
                        if old_data.get("timestamp") == target_timestamp:
                            is_duplicate = True
                            break
                except Exception:
                    pass

            if is_duplicate:
                logger.debug(f"市场 {slug} 本轮数据未发生更新 (timestamp={target_timestamp})，跳过归档。", extra={"market_id": slug})
                continue

            # 保存归档
            dt_str = datetime.datetime.fromtimestamp(target_timestamp).strftime("%Y%m%d_%H%M%S")
            archive_name = f"{dt_str}_{slug}.json"
            archive_path = os.path.join(ARCHIVE_DIR, archive_name)

            with open(archive_path, "w", encoding="utf-8") as f_out:
                json.dump(archive_data, f_out, indent=2, ensure_ascii=False)

            logger.info(f"成功归档历史数据：{archive_name}", extra={"market_id": slug})

        except Exception as e:
            logger.error(f"处理市场 {slug} 归档失败: {e}", extra={"market_id": slug})

if __name__ == "__main__":
    run_archiver()
