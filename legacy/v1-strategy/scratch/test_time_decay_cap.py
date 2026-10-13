import json
import os
import numpy as np
import datetime
import pytz
from unittest.mock import patch
from src.strategy import calculate_single_strategy
from src.config import CONFIG
from src.main import get_sleep_interval

def test_time_decay_cap():
    print("========== 开始测试自适应分数凯利时间衰减 (Fractional Kelly Time-Decay v3.8) ==========")
    
    protocols_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocols")
    
    snapshot_path = os.path.join(protocols_dir, "market_snapshot_test_time.json")
    prob_path = os.path.join(protocols_dir, "weather_probability_test_time.json")
    
    snapshot_data = {
        "protocol_version": CONFIG["version"],
        "timestamp": 1719398400,
        "market_id": "highest-temperature-in-test-on-june-27-2026",
        "station_info": {
            "station_id": "TEST",
            "city": "test",
            "timezone": "Asia/Shanghai"
        },
        "target_date": "2026-06-27",
        "resolution_precision": "INT_CELSIUS",
        "ranges": [
            {"range_id": "r1", "condition": "< 25", "ask_price": 0.1, "yes_ask": 0.1, "no_ask": 0.9, "yes_token_id": "1", "no_token_id": "2"},
            {"range_id": "r2", "condition": "25 - 27", "ask_price": 0.8, "yes_ask": 0.8, "no_ask": 0.2, "yes_token_id": "3", "no_token_id": "4"},
            {"range_id": "r3", "condition": "> 27", "ask_price": 0.1, "yes_ask": 0.1, "no_ask": 0.9, "yes_token_id": "5", "no_token_id": "6"}
        ]
    }
    
    prob_data = {
        "protocol_version": CONFIG["version"],
        "timestamp": 1719398400,
        "market_id": "highest-temperature-in-test-on-june-27-2026",
        "target_date": "2026-06-27",
        "total_effective_members": 40,
        "_simulated_sigma": 0.6,
        "probability_distribution": [
            {"condition": "< 25", "calculated_prob": 0.05, "standard_error": 0.01},
            {"condition": "25 - 27", "calculated_prob": 0.90, "standard_error": 0.01},
            {"condition": "> 27", "calculated_prob": 0.05, "standard_error": 0.01}
        ]
    }
    
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(snapshot_data, f)
        
    with open(prob_path, "w", encoding="utf-8") as f:
        json.dump(prob_data, f)
        
    # 模拟在不同时间点运行，检查 K_u 和投注额
    # 结算参考时间为最高温 2026-06-27 15:00:00 Asia/Shanghai
    tz = pytz.timezone("Asia/Shanghai")
    ref_dt = tz.localize(datetime.datetime(2026, 6, 27, 15, 0, 0))
    
    test_cases = [
        # (时间对象, 距离结算的实际小时数)
        (ref_dt - datetime.timedelta(hours=48), 48.0),
        (ref_dt - datetime.timedelta(hours=24), 24.0),
        (ref_dt - datetime.timedelta(hours=12), 12.0),
        (ref_dt - datetime.timedelta(hours=3), 3.0),
        (ref_dt, 0.0)
    ]
    
    decay_lambda = CONFIG["risk_control_lock"].get("kelly_time_decay_lambda", 0.0578)
    min_fraction = CONFIG["risk_control_lock"].get("kelly_min_fraction", 0.20)
    C_loc = CONFIG["risk_control_lock"].get("allocated_capital", 10000.0) * CONFIG["risk_control_lock"].get("max_portfolio_exposure", 0.05)
    
    print(f"系统配置: λ={decay_lambda}, min_fraction={min_fraction}, C_loc={C_loc}")
    
    for mock_now, hours_to_mat in test_cases:
        # 计算理论衰减因子和 K_u
        expected_decay = min_fraction + (1.0 - min_fraction) * np.exp(-decay_lambda * hours_to_mat)
        # 胜率标准差极低（0.01 < 0.05），置信度为 HIGH，所以 K_u_base = 0.50
        expected_ku = 0.50 * expected_decay
        expected_max_exposure = C_loc * expected_ku
        
        print(f"\n--- 测试时间点: {mock_now.strftime('%Y-%m-%d %H:%M:%S')} (剩余 {hours_to_mat:.1f} 小时) ---")
        print(f"理论衰减因子: {expected_decay:.4f} | 预期 K_u: {expected_ku:.4f} | 最大理论下注上限: {expected_max_exposure:.2f} USDC")
        
        # 使用 mock 替换 datetime.datetime.now
        class MockDateTime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is not None:
                    return mock_now.astimezone(tz)
                return mock_now
                
        with patch('datetime.datetime', MockDateTime):
            sig_file = calculate_single_strategy(snapshot_path, prob_path)
            
        sig_file_path = os.path.join(protocols_dir, sig_file)
        with open(sig_file_path, "r", encoding="utf-8") as f:
            sigs = json.load(f)
            
        found_buy = False
        for s in sigs["execution_signals"]:
            stake = s["recommended_stake_usdc"]
            if stake > 0:
                print(f"生成信号: {s['action']} | 档位: {s['condition']} | 推荐投注: {stake} USDC")
                # 投注额不能超过理论优化上限 + 浮点数极小误差
                assert stake <= expected_max_exposure + 0.01, f"投注额超出最大理论限制! 实际: {stake}, 限制: {expected_max_exposure}"
                found_buy = True
        
        assert found_buy, "未生成任何买入信号！"
        
        # 移除信号文件
        if os.path.exists(sig_file_path):
            os.remove(sig_file_path)

    # 测试动态频次计算
    print("\n--- 场景 3: 测试动态频次轮询计算 ---")
    interval = get_sleep_interval()
    print(f"动态频次计算得出的休眠间隔: {interval // 60} 分钟")
    assert interval in [900, 3600], f"轮询时间段不合规: {interval}"
    
    # 清理测试数据
    for p in [snapshot_path, prob_path]:
        if os.path.exists(p):
            os.remove(p)

    print("\n[Test] 自适应分数凯利时间衰减测试 100% 通过！")

if __name__ == "__main__":
    test_time_decay_cap()
