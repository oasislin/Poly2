import unittest
import numpy as np
import os
import sys

# 将 src 目录加入 python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.strategy import solve_kelly_yes_no, project_worst_case_probabilities

class TestRobustKelly(unittest.TestCase):
    
    def test_project_worst_case_probabilities(self):
        """测试贪心最坏概率投影算法"""
        # 3档结局
        p_L = np.array([0.1, 0.2, 0.3])
        p_U = np.array([0.3, 0.4, 0.5])
        
        # 情况 1: 财富 W 相同，最坏概率应退化为某种和为 1.0 的分配
        W_equal = np.array([10.0, 10.0, 10.0])
        p_worst_eq = project_worst_case_probabilities(W_equal, p_L, p_U)
        self.assertAlmostEqual(np.sum(p_worst_eq), 1.0)
        
        # 情况 2: 第一档财富最差，第二档中等，第三档最好
        # 算法应尽可能多地将概率分配给财富最差的结局（index 0），其次是 index 1，最后是 index 2
        W = np.array([2.0, 5.0, 10.0])
        p_worst = project_worst_case_probabilities(W, p_L, p_U)
        self.assertAlmostEqual(np.sum(p_worst), 1.0)
        
        # 初始 sum(p_L) = 0.6. 剩余 R = 0.4.
        # 最坏情况下，应该先把最差结局 (index 0) 升到上限 p_U[0] = 0.3.
        # 这需要 0.3 - 0.1 = 0.2 额度. 剩余 R = 0.2.
        # 然后把第二差结局 (index 1) 升到上限 p_U[1] = 0.4.
        # 这需要 0.4 - 0.2 = 0.2 额度. 剩余 R = 0.0.
        # 最终概率分配应为 [0.3, 0.4, 0.3].
        np.testing.assert_array_almost_equal(p_worst, np.array([0.3, 0.4, 0.3]))
        
        # 情况 3: 第三档财富最差，第一档最好
        W_rev = np.array([10.0, 5.0, 2.0])
        p_worst_rev = project_worst_case_probabilities(W_rev, p_L, p_U)
        # 应优先提升 index 2: p_L[2] = 0.3, 提升至上限 p_U[2] = 0.5 (消耗 0.2, R 剩 0.2)
        # 其次提升 index 1: p_L[1] = 0.2, 提升至上限 p_U[1] = 0.4 (消耗 0.2, R 剩 0.0)
        # 最终概率分配应为 [0.1, 0.4, 0.5]
        np.testing.assert_array_almost_equal(p_worst_rev, np.array([0.1, 0.4, 0.5]))

    def test_solve_robust_kelly_reduces_stake(self):
        """测试 Robust Kelly (theta > 0) 在存在不确定性时，比标准凯利减少或归零投注仓位"""
        # 3档结局，中间档位有 10% 的正 Edge（prob=0.5, price=0.4）
        probs = np.array([0.25, 0.5, 0.25])
        q_eff_yes = np.array([0.9, 0.4, 0.9])
        q_eff_no = np.array([0.9, 0.9, 0.9])
        
        C_total = 10000.0
        C_loc = 500.0
        K_u = 0.50
        
        # 1. 标准凯利 (theta = 0)
        x_yes_std, x_no_std = solve_kelly_yes_no(
            probs, q_eff_yes, q_eff_no, C_total, C_loc, K_u,
            std_errors=None, theta=0.0
        )
        self.assertGreater(x_yes_std[1], 10.0, "标准凯利应该对中间档位有显著的 YES 下注")
        
        # 2. 稳健凯利，设置较大标准差 (比如 0.15) 和安全乘数 (theta = 1.0)
        # 中间档位的概率区间大约为 [0.5 - 0.15, 0.5 + 0.15] = [0.35, 0.65]
        # 在最坏情况下其真实胜率可能只有 0.35，这低于有效成本 0.4，因此最坏情况下 Edge 为负，投注额应被极大地缩水或判定为 0
        std_errors = np.array([0.05, 0.15, 0.05])
        x_yes_robust, x_no_robust = solve_kelly_yes_no(
            probs, q_eff_yes, q_eff_no, C_total, C_loc, K_u,
            std_errors=std_errors, theta=1.0
        )
        
        self.assertLess(x_yes_robust[1], x_yes_std[1], "Robust Kelly 应该显著降低不确定档位的下注")
        self.assertAlmostEqual(x_yes_robust[1], 0.0, places=4, msg="对于负的最坏期望，下注应降为 0")

if __name__ == "__main__":
    unittest.main()
