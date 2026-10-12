import os
import sys
import json
import time
import shutil
import sqlite3
import zipfile
import argparse
import glob
from datetime import datetime

# 将当前文件所在目录的父目录加入 sys.path 以便于引入 src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import CONFIG, setup_logger

logger = setup_logger("DatasetExporter")

PROTOCOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocols")
STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage")
ARCHIVE_DIR = os.path.join(STORAGE_DIR, "archive")
EXPORTS_DIR = os.path.join(STORAGE_DIR, "exports")

REQUEST_PROTO_PATH = os.path.join(PROTOCOLS_DIR, "export_request.json")
RESPONSE_PROTO_PATH = os.path.join(PROTOCOLS_DIR, "export_response.json")


def copy_table_dynamically(conn_src, conn_dst, table_name, date_column, start_date, end_date):
    """
    自适应表结构复制：
    1. 动态读取源数据库表的字段和类型 (PRAGMA table_info)
    2. 在目标库中自动创建相同结构的表
    3. 动态拼接 SQL 进行按日期范围筛选的数据复制
    """
    cursor_src = conn_src.cursor()
    cursor_dst = conn_dst.cursor()
    
    # 1. 动态获取源表结构
    cursor_src.execute(f"PRAGMA table_info({table_name})")
    columns_info = cursor_src.fetchall()
    if not columns_info:
        logger.warning(f"源表中未找到表 {table_name}")
        return 0
        
    # columns_info 格式: (cid, name, type, notnull, dflt_value, pk)
    col_names = [col[1] for col in columns_info]
    
    # 2. 构建创建表的 SQL
    col_defs = []
    pks = []
    for col in columns_info:
        col_def = f"{col[1]} {col[2]}"
        if col[5] > 0:  # PRIMARY KEY
            pks.append(col[1])
        col_defs.append(col_def)
        
    if pks:
        col_defs.append(f"PRIMARY KEY ({', '.join(pks)})")
        
    create_sql = f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join(col_defs)})"
    cursor_dst.execute(create_sql)
    
    # 3. 动态筛选并复制数据
    placeholders = ", ".join(["?"] * len(col_names))
    insert_sql = f"INSERT OR REPLACE INTO {table_name} ({', '.join(col_names)}) VALUES ({placeholders})"
    
    # 查询
    select_sql = f"SELECT {', '.join(col_names)} FROM {table_name} WHERE {date_column} >= ? AND {date_column} <= ?"
    cursor_src.execute(select_sql, (start_date, end_date))
    rows = cursor_src.fetchall()
    
    if rows:
        cursor_dst.executemany(insert_sql, rows)
        conn_dst.commit()
        
    return len(rows)


def export_dataset(start_date=None, end_date=None, output_format="zip", output_name=None):
    """
    核心导出逻辑：
    1. 筛选特定日期范围内的 weather_cache.db 记录
    2. 筛选特定日期范围内的 arbitrage.db (交易账本) 记录
    3. 筛选特定日期范围内的 JSON 归档文件
    4. 将它们整体打包导出一个 zip/tar 或文件夹作为回测/测试库
    """
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    
    # 默认设置日期范围为近 30 天
    if not start_date:
        start_date = "1970-01-01"
    if not end_date:
        end_date = "2099-12-31"
        
    logger.info(f"开始执行数据集打包导出。时间范围: {start_date} 至 {end_date}，格式: {output_format}")
    
    # 创建临时工作目录
    temp_export_dir = os.path.join(EXPORTS_DIR, f"temp_export_{int(time.time())}")
    os.makedirs(temp_export_dir, exist_ok=True)
    
    weather_db_src = os.path.join(STORAGE_DIR, "weather_cache.db")
    arbitrage_db_src = os.path.join(STORAGE_DIR, "arbitrage.db")
    
    stats = {
        "weather_cache_records": 0,
        "trade_records": 0,
        "archive_files_count": 0
    }
    
    # 1. 过滤并复制 weather_cache 数据
    temp_weather_db = os.path.join(temp_export_dir, "weather_cache.db")
    if os.path.exists(weather_db_src):
        try:
            conn_src = sqlite3.connect(weather_db_src)
            conn_dst = sqlite3.connect(temp_weather_db)
            
            copied = copy_table_dynamically(
                conn_src, conn_dst,
                table_name="weather_daily_cache",
                date_column="date",
                start_date=start_date,
                end_date=end_date
            )
            
            stats["weather_cache_records"] = copied
            conn_src.close()
            conn_dst.close()
            logger.info(f"成功导出天气缓存记录: {copied} 条 (自适应 Schema)")
        except Exception as e:
            logger.error(f"处理天气缓存导出失败: {e}")
            shutil.rmtree(temp_export_dir, ignore_errors=True)
            return False, f"Weather cache export error: {e}", None
    else:
        logger.warning("未找到源天气缓存数据库，略过。")

    # 2. 过滤并复制交易账本数据
    temp_arbitrage_db = os.path.join(temp_export_dir, "arbitrage.db")
    if os.path.exists(arbitrage_db_src):
        try:
            conn_src = sqlite3.connect(arbitrage_db_src)
            conn_dst = sqlite3.connect(temp_arbitrage_db)
            
            copied = copy_table_dynamically(
                conn_src, conn_dst,
                table_name="trades",
                date_column="settlement_date",
                start_date=start_date,
                end_date=end_date
            )
            
            stats["trade_records"] = copied
            conn_src.close()
            conn_dst.close()
            logger.info(f"成功导出交易账本记录: {copied} 条 (自适应 Schema)")
        except Exception as e:
            logger.error(f"处理交易账本导出失败: {e}")
            shutil.rmtree(temp_export_dir, ignore_errors=True)
            return False, f"Arbitrage ledger export error: {e}", None
    else:
        logger.warning("未找到源交易账本数据库，略过。")

    # 3. 过滤并复制归档的 JSON 协议快照
    temp_archive_dir = os.path.join(temp_export_dir, "archive")
    os.makedirs(temp_archive_dir, exist_ok=True)
    
    archive_files = glob.glob(os.path.join(ARCHIVE_DIR, "*.json"))
    exported_archives_count = 0
    
    # 格式化日期以便做字符串比较匹配 YYYYMMDD
    start_date_clean = start_date.replace("-", "")
    end_date_clean = end_date.replace("-", "")
    
    for file_path in archive_files:
        filename = os.path.basename(file_path)
        # 归档文件名格式通常为 20260717_123456_slug.json
        if len(filename) >= 8 and filename[:8].isdigit():
            file_date = filename[:8]
            if not (start_date_clean <= file_date <= end_date_clean):
                continue
        else:
            # 如果文件名不符合规范，读取内部 metadata 校验
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                target_date = data.get("target_date", "")
                if not (start_date <= target_date <= end_date):
                    continue
            except Exception:
                continue
                
        shutil.copy2(file_path, os.path.join(temp_archive_dir, filename))
        exported_archives_count += 1
        
    stats["archive_files_count"] = exported_archives_count
    logger.info(f"成功导出归档快照文件: {exported_archives_count} 个")

    # 4. 打包文件
    if not output_name:
        output_name = f"backtest_dataset_{start_date.replace('-', '')}_{end_date.replace('-', '')}"
        
    if output_format == "zip":
        zip_file_path = os.path.join(EXPORTS_DIR, f"{output_name}.zip")
        try:
            with zipfile.ZipFile(zip_file_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(temp_export_dir):
                    for file in files:
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, temp_export_dir)
                        zipf.write(full_path, rel_path)
            shutil.rmtree(temp_export_dir, ignore_errors=True)
            logger.info(f"数据集已成功打包至: {zip_file_path}")
            return True, None, {
                "file_path": zip_file_path,
                "stats": stats
            }
        except Exception as e:
            logger.error(f"打包 ZIP 失败: {e}")
            shutil.rmtree(temp_export_dir, ignore_errors=True)
            return False, f"Zip packaging error: {e}", None
    else:
        # 直接保留为文件夹形式
        final_folder_path = os.path.join(EXPORTS_DIR, output_name)
        if os.path.exists(final_folder_path):
            shutil.rmtree(final_folder_path)
        shutil.move(temp_export_dir, final_folder_path)
        logger.info(f"数据集已生成到目录: {final_folder_path}")
        return True, None, {
            "file_path": final_folder_path,
            "stats": stats
        }


def process_protocol_request():
    """读取并处理 export_request.json 协议文件"""
    if not os.path.exists(REQUEST_PROTO_PATH):
        return
        
    try:
        with open(REQUEST_PROTO_PATH, "r", encoding="utf-8") as f:
            request_data = json.load(f)
            
        request_id = request_data.get("request_id", f"req_{int(time.time())}")
        start_date = request_data.get("start_date")
        end_date = request_data.get("end_date")
        output_format = request_data.get("output_format", "zip")
        output_name = request_data.get("output_name", f"export_{request_id}")
        
        logger.info(f"收到协议导出请求: ID={request_id}")
        
        success, err, result = export_dataset(
            start_date=start_date,
            end_date=end_date,
            output_format=output_format,
            output_name=output_name
        )
        
        # 写入响应协议
        response_data = {
            "protocol_version": request_data.get("protocol_version", "1.0"),
            "request_id": request_id,
            "timestamp": int(time.time()),
            "status": "SUCCESS" if success else "FAILED",
            "error_message": err,
            "output_file": result["file_path"] if success else None,
            "stats": result["stats"] if success else {}
        }
        
        with open(RESPONSE_PROTO_PATH, "w", encoding="utf-8") as f:
            json.dump(response_data, f, indent=2, ensure_ascii=False)
            
        logger.info(f"协议导出成功，响应已写入 {RESPONSE_PROTO_PATH}")
        
    except Exception as e:
        logger.error(f"处理请求协议异常: {e}")
        try:
            err_response = {
                "protocol_version": "1.0",
                "request_id": "unknown",
                "timestamp": int(time.time()),
                "status": "FAILED",
                "error_message": f"Fatal request processing error: {e}",
                "output_file": None,
                "stats": {}
            }
            with open(RESPONSE_PROTO_PATH, "w", encoding="utf-8") as f:
                json.dump(err_response, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
    finally:
        # 删除已处理完毕的请求协议文件，避免重复运行
        try:
            os.remove(REQUEST_PROTO_PATH)
        except Exception:
            pass


def start_watch_mode(interval=2.0):
    """守护进程轮询模式，监控协议目录"""
    logger.info(f"导出程序已启动监控模式，正在监视 {REQUEST_PROTO_PATH} ...")
    while True:
        if os.path.exists(REQUEST_PROTO_PATH):
            process_protocol_request()
        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="独立的量化回测数据集打包与导出工具")
    parser.add_argument("--watch", action="store_true", help="开启监控协议目录模式（Daemon 模式）")
    parser.add_argument("--start-date", type=str, help="开始日期 (格式 YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="结束日期 (格式 YYYY-MM-DD)")
    parser.add_argument("--format", type=str, default="zip", choices=["zip", "dir"], help="导出格式: zip 或 dir")
    parser.add_argument("--name", type=str, help="导出包名称")
    
    args = parser.parse_args()
    
    if args.watch:
        start_watch_mode()
    else:
        success, err, result = export_dataset(
            start_date=args.start_date,
            end_date=args.end_date,
            output_format=args.format,
            output_name=args.name
        )
        if success:
            print(f"Export Success! File: {result['file_path']}")
            print(f"Stats: {result['stats']}")
        else:
            print(f"Export Failed! Error: {err}")
            sys.exit(1)
