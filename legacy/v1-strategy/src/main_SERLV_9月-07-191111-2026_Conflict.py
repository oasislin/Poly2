import os
import time
import argparse
from src.config import CONFIG, setup_logger
from src.scanner import run_scanner
from src.analyst import run_analyst
from src.strategy import run_strategy
from src.executor import run_executor
from src.archiver import run_archiver

logger = setup_logger("Orchestrator")

def run_pipeline():
    """
    顺序运行套利交易流水线
    """
    logger.info("==================== 开始套利交易流水线 ====================", extra={"market_id": "SYSTEM"})
    
    start_time = time.time()
    try:
        # 1. 扫描盘口
        run_scanner()
        
        # 2. 气象胜率分析
        run_analyst()
        
        # 3. 期望值过滤与资金测算
        run_strategy()
        
        # 4. 执行下单与历史结清
        run_executor()
        
        # 5. 数据归档（持久化本轮原始数据快照供未来回测）
        run_archiver()
        
        elapsed = time.time() - start_time
        logger.info(f"==================== 流水线运行成功！耗时: {elapsed:.2f}秒 ====================", extra={"market_id": "SYSTEM"})
        
    except Exception as e:
        logger.critical(f"==================== 流水线异常中断！异常: {str(e)} ====================", extra={"market_id": "SYSTEM"})

def get_sleep_interval() -> int:
    """
    扫描 protocols/market_snapshot_*.json，计算所有活跃合约距离结算参考点的最小剩余小时数。
    若存在任一合约距离结算参考点在 3 小时以内，返回 15 分钟 (900秒)；
    否则返回 1 小时 (3600秒)。
    """
    import glob
    import json
    import datetime
    import pytz
    
    protocols_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocols")
    snapshot_files = glob.glob(os.path.join(protocols_dir, "market_snapshot_*.json"))
    
    if not snapshot_files:
        logger.info("未发现活跃合约，保持默认 1 小时轮询降频...", extra={"market_id": "SYSTEM"})
        return 3600
        
    min_hours = 999.0
    active_count = 0
    for fpath in snapshot_files:
        try:
            # 仅考虑最近 1 小时内更新过的活跃合约快照，排除历史残留文件
            if time.time() - os.path.getmtime(fpath) > 3600:
                continue
            active_count += 1
            with open(fpath, "r", encoding="utf-8") as f:
                snap = json.load(f)
            market_id = snap["market_id"]
            station_info = snap.get("station_info", {})
            timezone_str = station_info.get("timezone", "UTC")
            target_date_str = snap.get("target_date")
            
            is_lowest = "lowest" in market_id.lower()
            ref_hour = 5 if is_lowest else 15
            
            tz = pytz.timezone(timezone_str)
            now_station = datetime.datetime.now(tz)
            
            ref_dt = datetime.datetime.strptime(f"{target_date_str} {ref_hour:02d}:00:00", "%Y-%m-%d %H:%M:%S")
            ref_dt = tz.localize(ref_dt)
            
            delta_seconds = (ref_dt - now_station).total_seconds()
            hours = delta_seconds / 3600.0
            
            # 仅关心未来即将结算的合约，已过期的合约不参与最小剩余小时数计算（避免因已过结算点但未关闭的活跃合约导致持续处于高频轮询）
            if hours > 0:
                min_hours = min(min_hours, hours)
        except Exception as e:
            logger.warning(f"解析 {os.path.basename(fpath)} 估算轮询间隔失败: {e}", extra={"market_id": "SYSTEM"})
            
    if active_count == 0:
        logger.info("未发现最近 1 小时内有更新的活跃合约，保持默认 1 小时轮询降频...", extra={"market_id": "SYSTEM"})
        return 3600

    if min_hours <= 3.0:
        logger.info(f"最近合约距离结算仅 {min_hours:.2f} 小时 (<= 3h)，启用高频轮询模式 (间隔 15 分钟)", extra={"market_id": "SYSTEM"})
        return 900
    else:
        logger.info(f"最近合约距离结算仍有 {min_hours:.2f} 小时 (> 3h)，启用常规节电降频模式 (间隔 1 小时)", extra={"market_id": "SYSTEM"})
        return 3600

def main():
    parser = argparse.ArgumentParser(description="Polymarket 天气套利自动化量化交易系统")
    parser.add_argument("--once", action="store_true", help="单次执行流水线并退出 (适用于测试或 Cron 调度)")
    args = parser.parse_args()

    logger.info("系统初始化完成。运行模式: " + CONFIG["trading_mode"].upper(), extra={"market_id": "SYSTEM"})

    if args.once:
        run_pipeline()
    else:
        logger.info("启动常驻守护进程模式 (自适应动态频次)...", extra={"market_id": "SYSTEM"})
        while True:
            run_pipeline()
            sleep_sec = get_sleep_interval()
            logger.info(f"进入冷却，等待下一次循环 (休眠 {sleep_sec // 60} 分钟)...", extra={"market_id": "SYSTEM"})
            time.sleep(sleep_sec)

if __name__ == "__main__":
    main()
