import numpy as np
from src.strategy import solve_kelly_yes_no

def test_yes_no_kelly():
    print("========== 开始测试双向 YES/NO 凸优化凯利求解器 ==========")
    
    # 模拟上海 27 日最高温的估算概率 (11个区间)
    # 索引 6 对应 27°C 档位，胜率为 11.72% (即 YES 概率 11.7%，NO 概率 88.3%)
    probs = np.array([0.0, 0.0, 0.0005, 0.0057, 0.0208, 0.0428, 0.1172, 0.2933, 0.3432, 0.1457, 0.0307])
    
    # 模拟 YES 有效单价 (包含手续费折算)
    # 27°C (索引 6) YES 价格设为很高，29°C (索引 8), 9, 10 也设为很高（无优势）
    q_eff_yes = np.ones(11)
    
    # 模拟 NO 有效单价
    # 27°C (索引 6) NO 卖价 0.62，费率折算后 q_eff_no = 0.62 * (1 + 0.0125*(1-0.62)) = 0.6229
    # 其他档位无流动性，默认有效单价 1.0 (不买入)
    q_eff_no = np.ones(11)
    q_eff_no[6] = 0.6229  # 27°C 的 NO 有效价
    
    C_total = 10000.0
    C_loc = 500.0  # 单盘上限
    K_u = 0.50     # HIGH 置信等级，最大允许使用 250.0 USDC
    
    # 运行凸优化求解器
    x_yes, x_no = solve_kelly_yes_no(probs, q_eff_yes, q_eff_no, C_total, C_loc, K_u)
    
    print("\n--- 凸优化求解结果 ---")
    for i in range(11):
        if x_yes[i] > 0.1 or x_no[i] > 0.1:
            print(f"档位索引 {i:2d} | 真实 YES 概率: {probs[i]*100:4.1f}% | YES 目标投入: {x_yes[i]:6.2f} USDC | NO 目标投入: {x_no[i]:6.2f} USDC")
            
    # 校验断言
    # 1. 27°C (索引 6) 的 NO 应该被大量推荐买入 (因为期望优势 Edge = 88.3% - 62.3% = +26.0% 极其明显)
    assert x_no[6] > 10.0, f"27°C NO 应该被买入，但只分配了 {x_no[6]} USDC"
    # 3. 总投入绝对不能超出资金上限 250 USDC
    total_spent = np.sum(x_yes) + np.sum(x_no)
    assert total_spent <= 250.01, f"总下注超出本金约束！当前总额: {total_spent} USDC"
    
    print(f"\n[Test] 校验全部通过！总投入: {total_spent:.2f} USDC。成功生成 BUY_NO 决策分配。")

if __name__ == "__main__":
    test_yes_no_kelly()
