import json
import os
import numpy as np
from src.strategy import calculate_single_strategy, fetch_real_clob_book
from src.config import CONFIG

def test_live_clob_strategy():
    print("========== 开始测试实时 CLOB 数据接口与策略集成 ==========")
    
    # 1. 验证单一 Token 的 CLOB 挂单薄拉取
    # 使用上海最高温 6月27日 盘口的一个已知 Token 进行拉取测试
    protocols_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocols")
    snap_file = os.path.join(protocols_dir, "market_snapshot_highest-temperature-in-shanghai-on-june-27-2026.json")
    prob_file = os.path.join(protocols_dir, "weather_probability_highest-temperature-in-shanghai-on-june-27-2026.json")
    
    if not os.path.exists(snap_file) or not os.path.exists(prob_file):
        print(f"❌ 找不到测试快照文件 {snap_file}，请确保扫描已运行过。")
        return
        
    with open(snap_file, "r", encoding="utf-8") as f:
        snap_data = json.load(f)
        
    print("\n--- 1. 接口连通性测试 (Fetch Real CLOB Book) ---")
    test_token = None
    for r in snap_data["ranges"]:
        if r.get("yes_token_id"):
            test_token = r["yes_token_id"]
            print(f"找到待测试的 YES Token: {test_token} (区间: {r['condition']})")
            break
            
    if test_token:
        book = fetch_real_clob_book(test_token)
        print(f"拉取结果: 買价深度={len(book['bids'])}档 | 賣价深度={len(book['asks'])}档")
        if book["asks"]:
            print(f"最佳 Ask 价格: {book['asks'][0][0]} | 挂单量: {book['asks'][0][1]}")
        else:
            print("警告: 实时挂单簿 asks 为空（可能该档位目前无卖单）")
    else:
        print("未在快照中找到任何活跃的 Token ID！")

    print("\n--- 2. 策略引擎集成测试 (Strategy Engine with Live CLOB) ---")
    sig_file = calculate_single_strategy(snap_file, prob_file)
    
    sig_path = os.path.join(protocols_dir, sig_file)
    with open(sig_path, "r", encoding="utf-8") as f:
        sigs = json.load(f)
        
    print(f"策略生成信号成功！文件: {sig_file}")
    print("各档位实时 Ask 价格与成交决策汇总:")
    for s in sigs["execution_signals"]:
        print(
            f"档位: {s['condition']:<6} | "
            f"实时 Ask: {s['market_ask']:.4f} | "
            f"真实概率: {s['real_prob']:.4f} | "
            f"EV: {s['expected_value']:.4f} | "
            f"决策: {s['action']:<10} | "
            f"推荐投注: {s['recommended_stake_usdc']:.2f} USDC"
        )
        
    print("\n[Test] 实时 CLOB 接口与策略集成测试完成！")

if __name__ == "__main__":
    test_live_clob_strategy()
