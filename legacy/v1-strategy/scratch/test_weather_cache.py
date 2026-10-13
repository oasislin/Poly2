import os
import sqlite3
import datetime
from src.bias_corrector import MovingWindowBiasCorrector
from src.weather_cache import DB_PATH

def test_caching():
    print("========== 开始测试天气纠偏本地缓存与增量拉取 ==========")
    
    # 1. 清理已有的测试数据，以保证干净的冷启动测试
    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM weather_daily_cache WHERE station_id = 'ZSSS'")
            conn.commit()
            conn.close()
            print("[Test] 已清空 ZSSS 气象站在缓存库中的历史记录。")
        except Exception as e:
            print(f"[Test] 清空历史记录失败: {e}")

    corrector = MovingWindowBiasCorrector()
    
    # ZSSS 坐标
    lat, lon = 31.198, 121.336
    timezone = "Asia/Shanghai"
    target_date = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"[Test] 目标日期: {target_date} (气象站: ZSSS)")
    
    # 2. 第一次执行：应发生 Cache Miss，发起网络请求
    print("\n--- 第一次执行 (冷启动，预期 Cache Miss 并拉取 API) ---")
    start_time = datetime.datetime.now()
    bias1, std_dev1 = corrector.get_bias(
        station_id="ZSSS", 
        lat=lat, 
        lon=lon, 
        timezone=timezone, 
        target_date=target_date, 
        is_lowest=False, 
        window_days=7
    )
    elapsed1 = (datetime.datetime.now() - start_time).total_seconds()
    print(f"[Test] 结果: Bias = {bias1:+.3f}°C | StdDev = {std_dev1} | 耗时: {elapsed1:.2f}秒")
    
    # 3. 第二次执行：应发生 Cache Hit，完全从 SQLite 读取，耗时应在 0.1秒以内
    print("\n--- 第二次执行 (热启动，预期 100% 缓存命中) ---")
    start_time = datetime.datetime.now()
    bias2, std_dev2 = corrector.get_bias(
        station_id="ZSSS", 
        lat=lat, 
        lon=lon, 
        timezone=timezone, 
        target_date=target_date, 
        is_lowest=False, 
        window_days=7
    )
    elapsed2 = (datetime.datetime.now() - start_time).total_seconds()
    print(f"[Test] 结果: Bias = {bias2:+.3f}°C | StdDev = {std_dev2} | 耗时: {elapsed2:.4f}秒")
    
    # 断言校验
    assert abs(bias1 - bias2) < 1e-5, f"两次计算的 Bias 值不一致！{bias1} vs {bias2}"
    assert elapsed2 < 0.1, f"缓存读取过慢，耗时: {elapsed2}秒"
    print("\n[Test] 校验成功！自适应纠偏缓存命中性能达到要求。")

if __name__ == "__main__":
    test_caching()
