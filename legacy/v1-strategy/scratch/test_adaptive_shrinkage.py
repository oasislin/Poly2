import json
import os
import numpy as np
import datetime
import pytz
from src.strategy import calculate_single_strategy
from src.config import CONFIG

def test_adaptive_shrinkage():
    print("========== 开始测试时间自适应非线性收缩 (Time-Adaptive Sigmoid Shrinkage) ==========")
    
    protocols_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocols")
    
    # 模拟一个 snapshot
    snapshot_path = os.path.join(protocols_dir, "market_snapshot_test_shrinkage.json")
    prob_path = os.path.join(protocols_dir, "weather_probability_test_shrinkage.json")
    
    # 设定基准快照：目标日期为明天
    # 计算当前时间到明天下午 15:00 的小时数
    tz = pytz.timezone("Asia/Shanghai")
    now_station = datetime.datetime.now(tz)
    
    # 场景 1: 远期状态 (> 24小时前)
    # 我们将 target_date 设为 3 天后，这样 hours_to_maturity 肯定 > 24，q_0 锁定在 0.05
    target_date_far = (now_station + datetime.timedelta(days=3)).strftime("%Y-%m-%d")
    
    snapshot_data_far = {
        "protocol_version": CONFIG["version"],
        "timestamp": int(now_station.timestamp()),
        "market_id": "highest-temperature-in-test-on-june-30-2026",
        "station_info": {
            "station_id": "TEST",
            "city": "test",
            "timezone": "Asia/Shanghai"
        },
        "target_date": target_date_far,
        "resolution_precision": "INT_CELSIUS",
        "ranges": [
            {"range_id": "r1", "condition": "25", "ask_price": 0.025, "yes_ask": 0.025, "no_ask": 0.975, "yes_token_id": "1", "no_token_id": "2"},
            {"range_id": "r2", "condition": "26", "ask_price": 0.975, "yes_ask": 0.975, "no_ask": 0.025, "yes_token_id": "3", "no_token_id": "4"}
        ]
    }
    
    prob_data = {
        "protocol_version": CONFIG["version"],
        "timestamp": int(now_station.timestamp()),
        "market_id": "highest-temperature-in-test-on-june-30-2026",
        "target_date": target_date_far,
        "total_effective_members": 40,
        "_simulated_sigma": 0.6,
        "probability_distribution": [
            {"condition": "25", "calculated_prob": 0.16, "standard_error": 0.01},
            {"condition": "26", "calculated_prob": 0.84, "standard_error": 0.01}
        ]
    }
    
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(snapshot_data_far, f)
    with open(prob_path, "w", encoding="utf-8") as f:
        json.dump(prob_data, f)
        
    print("\n--- 1. 远期测算 (预期大折价收缩，无 BUY 信号) ---")
    sig_file1 = calculate_single_strategy(snapshot_path, prob_path)
    with open(os.path.join(protocols_dir, sig_file1), "r", encoding="utf-8") as f:
        sigs_far = json.load(f)
        
    actions_far = [s["action"] for s in sigs_far["execution_signals"]]
    print(f"远期交易决策列表: {actions_far}")
    # 期望没有 BUY_YES
    assert "BUY_YES" not in actions_far, "远期未成功收缩限制低价合约投机！"
    
    # 场景 2: 临近结算状态 (< 3小时)
    # 我们将 target_date 设为今天，且结算在 1 小时内发生，小时数 < 3h，q_0 线性收拢在 0.01
    # 为保证结算时间在当前 1 小时内，我们将结算参考点计算设为当前时间往前或刚刚过
    target_date_near = now_station.strftime("%Y-%m-%d")
    
    snapshot_data_near = snapshot_data_far.copy()
    snapshot_data_near["target_date"] = target_date_near
    # 我们需要构造一个 market_id
    snapshot_data_near["market_id"] = f"highest-temperature-in-test-on-{target_date_near}"
    prob_data_near = prob_data.copy()
    prob_data_near["target_date"] = target_date_near
    prob_data_near["market_id"] = f"highest-temperature-in-test-on-{target_date_near}"
    
    # 我们设定 ref_hour 让剩余小时数处于 0 ~ 2 小时之间
    # 刚才 strategy 里面 ref_hour = 15 (若是最低温则是 5)
    # 为了在测试中动态对齐，我们在测试脚本里暂时把 market_id 修改为 lowest 以对齐清晨结算
    # 或者直接把当前时间设为参考结算小时
    current_hour = now_station.hour
    is_lowest = False
    if current_hour < 12:
        is_lowest = True
        ref_h = 5
    else:
        ref_h = 15
        
    # 如果当前时间与 ref_h 的差值在 3 小时以内或已经过期，则进入临近状态
    # 为确保测试百分百走入临近区，我们可以在 snapshot 里把时区调到刚刚好结算的城市，
    # 或者直接修改 snapshot 目标日期。
    # 这里直接让 target_date 设为今天且 is_lowest 配合
    # 我们用 lowest 配合 ref_hour = 5。若现在是 21 点，那距离 27 日清晨 5点 还有 8 小时。
    # 我们只需要构造一个 target_date_near，让 ref_dt - now_station <= 3 小时即可。
    # 当前是 21:51。那么设置结算参考点为 22:00 (1小时后) 即可！
    # 我们的 strategy 是通过 `market_id` 判定 `is_lowest`。
    # 我们让 lowest (ref_hour = 5)， target_date 设为明天 (27号)。
    # 现在 21:50，距离明天 5 点是 7.1 小时。
    # 为了制造 < 3 小时，我们可以利用 lowest，把 target_date 设为今天 (26号)，
    # 今天 5 点结算，现在是 21点，已经过期（剩余时间是负数，负数在 get_bias/main 里按 0 小时处理，代表已结算/决战期）
    # 负数在 strategy 里的 hours_to_maturity 会算为负数，cap_ratio 取 below_3h = 1.00，q_0 也会取 min_hours=0 即 0.01!
    snapshot_data_near["market_id"] = f"lowest-temperature-in-test-on-{target_date_near}"
    prob_data_near["market_id"] = f"lowest-temperature-in-test-on-{target_date_near}"
    
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(snapshot_data_near, f)
    with open(prob_path, "w", encoding="utf-8") as f:
        json.dump(prob_data_near, f)
        
    print("\n--- 2. 临近测算 (预期小折价，信任度高，生成 BUY 信号) ---")
    sig_file2 = calculate_single_strategy(snapshot_path, prob_path)
    with open(os.path.join(protocols_dir, sig_file2), "r", encoding="utf-8") as f:
        sigs_near = json.load(f)
        
    actions_near = [s["action"] for s in sigs_near["execution_signals"]]
    print(f"临近交易决策列表: {actions_near}")
    assert "BUY_YES" in actions_near, "临近结算未能恢复对低价高概率合约的信任！"
    
    # 清理
    for p in [snapshot_path, prob_path, os.path.join(protocols_dir, sig_file1), os.path.join(protocols_dir, sig_file2)]:
        if os.path.exists(p):
            os.remove(p)
            
    print("\n[Test] 时间自适应非线性平滑收缩测试 100% 通过！")

if __name__ == "__main__":
    test_adaptive_shrinkage()
