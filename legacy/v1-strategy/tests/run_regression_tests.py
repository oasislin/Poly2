import os
import sys
import json
import datetime
import unittest
from unittest.mock import patch
import numpy as np
import pytz

# 将 src 目录加入 python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analyst import analyze_single_market
from src.strategy import calculate_single_strategy
from src.config import CONFIG

class TestWeatherArbitrageRegression(unittest.TestCase):

    def setUp(self):
        # 建立一个临时 protocols 文件夹，防止污染实盘数据
        self.test_protocols_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_protocols")
        os.makedirs(self.test_protocols_dir, exist_ok=True)
        
        # 备份并修改 src.analyst 的 PROTOCOLS_DIR
        import src.analyst
        import src.strategy
        self.old_analyst_protocols_dir = src.analyst.PROTOCOLS_DIR
        self.old_strategy_protocols_dir = src.strategy.PROTOCOLS_DIR
        src.analyst.PROTOCOLS_DIR = self.test_protocols_dir
        src.strategy.PROTOCOLS_DIR = self.test_protocols_dir

    def tearDown(self):
        # 恢复原 protocols 路径
        import src.analyst
        import src.strategy
        src.analyst.PROTOCOLS_DIR = self.old_analyst_protocols_dir
        src.strategy.PROTOCOLS_DIR = self.old_strategy_protocols_dir
        
        # 清理临时文件
        if os.path.exists(self.test_protocols_dir):
            for f in os.listdir(self.test_protocols_dir):
                try:
                    os.remove(os.path.join(self.test_protocols_dir, f))
                except Exception:
                    pass
            try:
                os.rmdir(self.test_protocols_dir)
            except Exception:
                pass

    @patch("src.weather_cache.get_api_cache")
    @patch("src.weather_cache.fetch_wunderground_hourly_observed_today")
    @patch("src.strategy.get_current_holdings")
    def test_scenario_a_munich_defense(self, mock_get_positions, mock_fetch_obs, mock_get_cache):
        """场景 A：慕尼黑 7月19日 远期防守测试。确保模型在远期大噪声下不会对极低价长尾档位投机（投注为 0）。"""
        archive_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "storage", "archive", "20260719_132644_highest-temperature-in-munich-on-july-19-2026.json"
        )
        self.assertTrue(os.path.exists(archive_path), f"找不到慕尼黑历史存档文件: {archive_path}")
        
        with open(archive_path, "r", encoding="utf-8") as f:
            archive_data = json.load(f)
            
        # 从存档中提取 mock 数据
        raw_forecast = archive_data["raw_data"]["raw_forecast"]
        raw_observed = archive_data["raw_data"].get("raw_observed")
        market_snapshot = archive_data["raw_data"]["market_snapshot"]
        
        # 写入临时市场快照文件
        temp_snap_path = os.path.join(self.test_protocols_dir, "market_snapshot_highest-temperature-in-munich-on-july-19-2026.json")
        with open(temp_snap_path, "w", encoding="utf-8") as f_snap:
            json.dump(market_snapshot, f_snap, indent=2, ensure_ascii=False)
            
        # 设置 Mock 返回
        mock_get_cache.return_value = raw_forecast
        mock_get_positions.return_value = {"YES": {}, "NO": {}}
        
        # 如果 raw_observed 是单个数值，包装成时序观测列表
        if isinstance(raw_observed, (int, float)):
            mock_fetch_obs.return_value = [
                {"local_time": "2026-07-19 12:00:00", "temp": float(raw_observed), "hour": 12}
            ]
        else:
            mock_fetch_obs.return_value = raw_observed
        
        # Mock 当前时间为 2026-07-19 13:26:44 (带时区 Europe/Berlin)
        tz = pytz.timezone("Europe/Berlin")
        mock_now = tz.localize(datetime.datetime(2026, 7, 19, 13, 26, 44))
        
        class MockDateTime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return mock_now
                
        # 替换 src.analyst 中的 datetime.datetime
        with patch("src.analyst.datetime.datetime", MockDateTime):
            # 1. 运行分析模块生成概率契约
            prob_filename = analyze_single_market(temp_snap_path)
            self.assertIsNotNone(prob_filename, "分析模块生成概率契约失败")
            prob_path = os.path.join(self.test_protocols_dir, prob_filename)
            self.assertTrue(os.path.exists(prob_path), f"未找到生成的概率契约文件: {prob_path}")
            
            # 2. 运行策略模块生成投注信号
            sig_filename = calculate_single_strategy(temp_snap_path, prob_path)
            self.assertIsNotNone(sig_filename, "策略模块生成下注信号失败")
            sig_path = os.path.join(self.test_protocols_dir, sig_filename)
            self.assertTrue(os.path.exists(sig_path), f"未找到生成的投注信号文件: {sig_path}")
            
            # 3. 校验边界约束断言：极低价的 <=19 和 20 档位下注金额必须为 0
            with open(sig_path, "r", encoding="utf-8") as f_sig:
                sig_data = json.load(f_sig)
                
            signals = sig_data.get("execution_signals", [])
            for sig in signals:
                cond = sig.get("condition")
                stake = sig.get("recommended_stake_usdc", 0.0)
                if cond in ["<=19", "20"]:
                    self.assertEqual(stake, 0.0, f"违反防守防线：远期大不确定性下对极低概率档位 {cond} 进行了投机下注，金额: {stake} USDC")
                
        print("🟢 场景 A (慕尼黑远期防守测试) 通关：成功阻断低价投机。")

    @patch("src.weather_cache.get_api_cache")
    @patch("src.weather_cache.fetch_wunderground_hourly_observed_today")
    @patch("src.strategy.get_current_holdings")
    def test_scenario_b_madrid_convergence(self, mock_get_positions, mock_fetch_obs, mock_get_cache):
        """场景 B：马德里 7月21日 临场收敛测试。确保临近结算标准差平滑收缩后，胜率收敛并触发核心档位下注。"""
        archive_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "storage", "archive", "20260721_125347_highest-temperature-in-madrid-on-july-21-2026.json"
        )
        self.assertTrue(os.path.exists(archive_path), f"找不到马德里历史存档文件: {archive_path}")
        
        with open(archive_path, "r", encoding="utf-8") as f:
            archive_data = json.load(f)
            
        # 从存档中提取 mock 数据
        raw_forecast = archive_data["raw_data"]["raw_forecast"]
        raw_observed = archive_data["raw_data"].get("raw_observed")
        market_snapshot = archive_data["raw_data"]["market_snapshot"]
        
        # 写入临时市场快照文件
        temp_snap_path = os.path.join(self.test_protocols_dir, "market_snapshot_highest-temperature-in-madrid-on-july-21-2026.json")
        with open(temp_snap_path, "w", encoding="utf-8") as f_snap:
            json.dump(market_snapshot, f_snap, indent=2, ensure_ascii=False)
            
        # 设置 Mock 返回
        mock_get_cache.return_value = raw_forecast
        mock_get_positions.return_value = {"YES": {}, "NO": {}}
        
        # 如果 raw_observed 是单个数值，包装成时序观测列表
        if isinstance(raw_observed, (int, float)):
            mock_fetch_obs.return_value = [
                {"local_time": "2026-07-21 12:00:00", "temp": float(raw_observed), "hour": 12}
            ]
        else:
            mock_fetch_obs.return_value = raw_observed
        
        # Mock 当前时间为 2026-07-21 12:53:47 (带时区 Europe/Madrid)
        tz = pytz.timezone("Europe/Madrid")
        mock_now = tz.localize(datetime.datetime(2026, 7, 21, 12, 53, 47))
        
        class MockDateTime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return mock_now
                
        # 替换 src.analyst 中的 datetime.datetime
        with patch("src.analyst.datetime.datetime", MockDateTime):
            # 1. 运行分析模块生成概率契约
            prob_filename = analyze_single_market(temp_snap_path)
            self.assertIsNotNone(prob_filename, "分析模块生成概率契约失败")
            prob_path = os.path.join(self.test_protocols_dir, prob_filename)
            self.assertTrue(os.path.exists(prob_path), f"未找到生成的概率契约文件: {prob_path}")
            
            # 2. 校验概率收敛断言：37°C 胜率必须 >= 55%
            with open(prob_path, "r", encoding="utf-8") as f_prob:
                prob_data = json.load(f_prob)
                
            prob_dist = prob_data.get("probability_distribution", [])
            prob_37 = 0.0
            for item in prob_dist:
                if item.get("condition") == "37":
                    prob_37 = item.get("calculated_prob", 0.0)
                    break
                    
            print(f"📊 临场收敛校验：37°C 计算得到的胜率为 {prob_37*100:.2f}% (老算法静态 Clamp 强行吹散至 16.4%)")
            self.assertGreaterEqual(prob_37, 0.55, f"违反临场收敛防线：临近结算期标准差未能有效收缩，37°C 胜率仅为 {prob_37*100:.2f}% (要求 >= 55%)")
            
            # 3. 运行策略模块生成下注信号并校验必须有 BUY_YES 推荐
            sig_filename = calculate_single_strategy(temp_snap_path, prob_path)
            self.assertIsNotNone(sig_filename, "策略模块生成下注信号失败")
            sig_path = os.path.join(self.test_protocols_dir, sig_filename)
            
            with open(sig_path, "r", encoding="utf-8") as f_sig:
                sig_data = json.load(f_sig)
                
            signals = sig_data.get("execution_signals", [])
            found_buy = False
            buy_stake = 0.0
            for sig in signals:
                if sig.get("condition") in ["36", "37", "38"] and sig.get("recommended_stake_usdc", 0.0) > 0:
                    found_buy = True
                    buy_stake = sig.get("recommended_stake_usdc", 0.0)
                    break
                    
            self.assertTrue(found_buy, "违反临场收敛防线：未对核心区间 (37 或 38) 生成下注信号")
            self.assertGreater(buy_stake, 0.0, f"违反临场收敛防线：核心区间推荐下注金额为 0.00 USDC")
            print(f"🟢 场景 B (马德里临场收敛测试) 通关：胜率成功收敛至 {prob_37*100:.2f}% 并生成 {buy_stake:.2f} USDC 买入信号。")

if __name__ == "__main__":
    unittest.main()
