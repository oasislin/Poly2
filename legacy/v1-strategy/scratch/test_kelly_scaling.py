import json
import os
import numpy as np
from src.strategy import calculate_single_strategy
from src.config import CONFIG

def test_kelly_scaling():
    print("========== 开始测试物理噪声自适应资金缩水 (Dynamic Kelly Scaling) ==========")
    
    protocols_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocols")
    
    # 模拟一个 snapshot
    snapshot_path = os.path.join(protocols_dir, "market_snapshot_test_scaling.json")
    prob_path = os.path.join(protocols_dir, "weather_probability_test_scaling.json")
    
    snapshot_data = {
        "protocol_version": CONFIG["version"],
        "timestamp": 1719398400,
        "market_id": "test_scaling",
        "station_info": {
            "station_id": "TEST",
            "city": "test",
            "timezone": "UTC"
        },
        "target_date": "2026-06-27",
        "resolution_precision": "INT_CELSIUS",
        "ranges": [
            {"range_id": "r1", "condition": "< 25", "ask_price": 0.1, "yes_ask": 0.1, "no_ask": 0.9, "yes_token_id": "1", "no_token_id": "2"},
            {"range_id": "r2", "condition": "25 - 27", "ask_price": 0.8, "yes_ask": 0.8, "no_ask": 0.2, "yes_token_id": "3", "no_token_id": "4"},
            {"range_id": "r3", "condition": "> 27", "ask_price": 0.1, "yes_ask": 0.1, "no_ask": 0.9, "yes_token_id": "5", "no_token_id": "6"}
        ]
    }
    
    # 场景 1: 低噪声 (σ = 0.6)
    prob_data_low = {
        "protocol_version": CONFIG["version"],
        "timestamp": 1719398400,
        "market_id": "test_scaling",
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
        json.dump(prob_data_low, f)
        
    # 计算低噪声下的下注信号
    sig_file1 = calculate_single_strategy(snapshot_path, prob_path)
    with open(os.path.join(protocols_dir, sig_file1), "r", encoding="utf-8") as f:
        sigs_low = json.load(f)
        
    stake_low = sum(s["recommended_stake_usdc"] for s in sigs_low["execution_signals"])
    print(f"[Low Noise σ=0.6] 推荐下注总额: {stake_low} USDC")
    
    # 场景 2: 高噪声 (σ = 1.2)
    prob_data_high = prob_data_low.copy()
    prob_data_high["_simulated_sigma"] = 1.2
    
    with open(prob_path, "w", encoding="utf-8") as f:
        json.dump(prob_data_high, f)
        
    sig_file2 = calculate_single_strategy(snapshot_path, prob_path)
    with open(os.path.join(protocols_dir, sig_file2), "r", encoding="utf-8") as f:
        sigs_high = json.load(f)
        
    stake_high = sum(s["recommended_stake_usdc"] for s in sigs_high["execution_signals"])
    print(f"[High Noise σ=1.2] 推荐下注总额: {stake_high} USDC")
    
    # 验证高物理噪声下的下注额应明显低于低物理噪声
    assert stake_high < stake_low, f"缩水失败: {stake_high} vs {stake_low}"
    print(f"[Test] 物理不确定性自适应缩水比例: {stake_high / stake_low:.2%}")
    print("[Test] 资金缩水测试 100% 通过！")
    
    # 清理测试文件
    for p in [snapshot_path, prob_path, os.path.join(protocols_dir, sig_file1)]:
        if os.path.exists(p):
            os.remove(p)

if __name__ == "__main__":
    test_kelly_scaling()
