import unittest
import numpy as np
import os
import sys

# 将 src 目录加入 python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.strategy import simulate_slippage, solve_kelly_yes_no
from src.analyst import check_condition

class TestBettingOptimizer(unittest.TestCase):
    
    def test_condition_checker(self):
        """测试温度区间条件解析逻辑"""
        self.assertTrue(check_condition(25, "22-25"))
        self.assertTrue(check_condition(22, "22-25"))
        self.assertFalse(check_condition(21, "22-25"))
        self.assertFalse(check_condition(26, "22-25"))
        
        self.assertTrue(check_condition(21, "<22"))
        self.assertFalse(check_condition(22, "<22"))
        
        self.assertTrue(check_condition(26, ">=26"))
        self.assertTrue(check_condition(27, ">=26"))
        self.assertFalse(check_condition(25, ">=26"))

    def test_simulate_slippage_with_custom_asks(self):
        """测试带自定义挂单的订单簿滑点模拟"""
        asks = [[0.50, 100.0], [0.55, 200.0]]
        
        # 1. 投入额在首档内，不应有滑点
        avg_p_1, spent_1, shares_1 = simulate_slippage(asks, 10.0)
        self.assertEqual(avg_p_1, 0.50)
        self.assertAlmostEqual(spent_1, 10.0)
        self.assertAlmostEqual(shares_1, 20.0)
        
        # 2. 投入额跨越首档，产生滑点且均价上升
        avg_p_2, spent_2, shares_2 = simulate_slippage(asks, 100.0)
        self.assertGreater(avg_p_2, 0.50)
        self.assertLess(avg_p_2, 0.55)
        self.assertAlmostEqual(spent_2, 100.0)
        self.assertGreater(shares_2, 0.0)

    def test_simulate_slippage_with_fallback(self):
        """测试空挂单簿时降级为内置深度模拟"""
        # fallback_price = 0.60
        avg_p, spent, shares = simulate_slippage([], 10.0, fallback_price=0.60)
        self.assertEqual(avg_p, 0.60)
        self.assertAlmostEqual(spent, 10.0)
        self.assertAlmostEqual(shares, 10.0 / 0.60)

    def test_solve_kelly_yes_no_no_edge(self):
        """测试在没有正期望（No Edge）时，Kelly 求解器应返回 0 投入"""
        probs = np.array([0.2, 0.5, 0.3])
        # 有效成本高于真实胜率，期望全部为负
        q_eff_yes = np.array([0.25, 0.55, 0.35])
        q_eff_no = np.array([0.85, 0.55, 0.75])
        
        C_total = 10000.0
        C_loc = 500.0
        K_u = 0.50
        
        x_yes, x_no = solve_kelly_yes_no(probs, q_eff_yes, q_eff_no, C_total, C_loc, K_u)
        # 应无任何买入
        np.testing.assert_array_almost_equal(x_yes, np.zeros(3))
        np.testing.assert_array_almost_equal(x_no, np.zeros(3))

    def test_solve_kelly_yes_no_with_edge(self):
        """测试在有正期望时，Kelly 求解器应分配资金且不超过约束硬顶"""
        probs = np.array([0.1, 0.8, 0.1])
        # YES 中间档位有巨大期望优势 (prob=0.8, cost=0.4)
        q_eff_yes = np.array([0.2, 0.4, 0.2])
        q_eff_no = np.array([0.95, 0.95, 0.95])
        
        C_total = 10000.0
        C_loc = 500.0
        K_u = 0.50  # 限制总下注 <= 250 USDC
        
        x_yes, x_no = solve_kelly_yes_no(probs, q_eff_yes, q_eff_no, C_total, C_loc, K_u)
        
        # 中间档位 YES 应该有显著的资金分配
        self.assertGreater(x_yes[1], 0.0)
        # 资金分配总额不能超过限制硬顶 (C_loc * K_u = 250.0)
        self.assertLessEqual(np.sum(x_yes) + np.sum(x_no), C_loc * K_u + 1e-6)
        
        # 劣势档位不应分配资金
        self.assertAlmostEqual(x_yes[0], 0.0, places=4)
        self.assertAlmostEqual(x_yes[2], 0.0, places=4)

    def test_monte_carlo_math_simulation(self):
        """测试模拟气温高斯噪声采样与取整逻辑的正确性"""
        raw_temps = [23.4, 23.8, 24.2]
        sigma = 0.6
        mc_samples = 500
        
        # 模拟生成噪声样本并执行向下取整
        np.random.seed(42)
        settled = []
        for tj in raw_temps:
            noise = np.random.normal(0, sigma, mc_samples)
            sim = tj + noise
            for val in sim:
                settled.append(int(np.floor(val)))
                
        total_sims = len(settled)
        self.assertEqual(total_sims, len(raw_temps) * mc_samples)
        
        # 验证所有模拟出来的结算值都在预期温度区间内
        for val in settled:
            self.assertIsInstance(val, int)
            self.assertTrue(18 <= val <= 30)

    def test_phase_3_observed_constraint(self):
        """测试 Phase III 决战实况气温约束对模拟概率的物理订正"""
        # 预报温度均较低
        raw_temps = [22.1, 22.5, 23.0]
        sigma = 0.5
        mc_samples = 100
        
        # 假设今日实况已经录得 24.5°C (最高温)
        obs_temp = 24.5
        
        np.random.seed(42)
        settled_with_obs = []
        
        for tj in raw_temps:
            noise = np.random.normal(0, sigma, mc_samples)
            sim_temps = tj + noise
            # 注入 Observed Max constraint
            sim_temps = np.maximum(sim_temps, obs_temp)
            for t_val in sim_temps:
                settled_with_obs.append(int(np.floor(t_val)))
                
        # 由于实况已经达到 24.5°C，向下取整后结算温度必须至少是 24°C！
        for val in settled_with_obs:
            self.assertGreaterEqual(val, 24)
            
if __name__ == "__main__":
    unittest.main()
