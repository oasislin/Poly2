import unittest
from unittest.mock import patch, MagicMock
import os
import json
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.backtest_loader import parse_station_icao_from_desc, parse_weather_condition, fetch_historical_price, run_backtest_load
from src.config import validate_contract

class TestBacktestLoader(unittest.TestCase):
    
    def setUp(self):
        self.test_protocols_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_protocols")
        os.makedirs(self.test_protocols_dir, exist_ok=True)
        import src.backtest_loader
        self.old_protocols_dir = src.backtest_loader.PROTOCOLS_DIR
        src.backtest_loader.PROTOCOLS_DIR = self.test_protocols_dir

    def tearDown(self):
        import src.backtest_loader
        src.backtest_loader.PROTOCOLS_DIR = self.old_protocols_dir
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

    def test_icao_extraction(self):
        """测试从 Wunderground URL 提取 ICAO 站号"""
        desc_1 = "This market resolves to the daily temperature at https://www.wunderground.com/history/daily/kr/incheon/RKSI/date/2026-6-20"
        desc_2 = "https://www.wunderground.com/history/daily/us/new-york/KNYC"
        self.assertEqual(parse_station_icao_from_desc(desc_1), "RKSI")
        self.assertEqual(parse_station_icao_from_desc(desc_2), "KNYC")
        self.assertIsNone(parse_station_icao_from_desc("No ICAO link here"))

    @patch("src.backtest_loader.requests.get")
    def test_fetch_historical_price_success(self, mock_get):
        """测试成功拉取到历史价格的情形"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_ok = True
        mock_response.json.return_value = {
            "history": [
                {"t": 1718000000, "p": 0.45},
                {"t": 1718040000, "p": 0.52},
                {"t": 1718080000, "p": 0.60}
            ]
        }
        mock_get.return_value = mock_response
        
        # 目标查找时间为 1718043000，最接近的烛线应为 1718040000 -> 0.52
        price = fetch_historical_price("token_123", 1718043000)
        self.assertEqual(price, 0.52)

    @patch("src.backtest_loader.requests.get")
    def test_fetch_historical_price_failure(self, mock_get):
        """测试历史价格拉取异常时返回 None 以便执行降级"""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response
        
        price = fetch_historical_price("token_123", 1718043000)
        self.assertIsNone(price)

    @patch("src.backtest_loader.fetch_historical_forecast")
    @patch("src.backtest_loader.fetch_historical_price")
    @patch("src.backtest_loader.fetch_historical_markets")
    def test_run_backtest_load_contract(self, mock_fetch_markets, mock_fetch_price, mock_fetch_forecast):
        """测试加载器主逻辑以及契约文件的生成与强校验"""
        # Mock Gamma 事件结构
        mock_fetch_markets.return_value = [
            ({
                "title": "Highest temperature in Incheon on 2026-06-20",
                "description": "https://www.wunderground.com/history/daily/kr/incheon/RKSI",
                "slug": "highest-temp-incheon-2026-06-20",
                "eventDate": "2026-06-20",
                "markets": [
                    {
                        "question": "Will the highest temperature in Incheon be 22°C or below on June 20, 2026?",
                        "clobTokenIds": '["11111"]',
                        "outcomePrices": '["0.10", "0.90"]'
                    },
                    {
                        "question": "Will the highest temperature in Incheon be between 23°C to 25°C on June 20, 2026?",
                        "clobTokenIds": '["22222"]',
                        "outcomePrices": '["0.65", "0.35"]'
                    },
                    {
                        "question": "Will the highest temperature in Incheon be 26°C or above on June 20, 2026?",
                        "clobTokenIds": '["33333"]',
                        "outcomePrices": '["0.25", "0.75"]'
                    }
                ]
            }, "RKSI")
        ]
        
        # Mock 历史价格拉取（有的成功，有的失败触发降级）
        mock_fetch_price.side_effect = lambda token_id, ts: {
            "11111": 0.15,
            "22222": None, # 触发降级
            "33333": 0.20
        }.get(token_id)
        
        # Mock Open-Meteo 历史预报返回的 40 个成员
        dummy_hourly = {
            "time": ["2026-06-20T00:00", "2026-06-20T06:00", "2026-06-20T12:00", "2026-06-20T18:00"],
            "temperature_2m": [20.0, 24.0, 25.0, 21.0] # max = 25.0
        }
        for i in range(1, 40):
            # 成员 1-39 预报最高温在 23-25 度区间
            dummy_hourly[f"temperature_2m_member{i:02d}"] = [19.0, 23.5, 24.5, 20.0] # max = 24.5
            
        mock_fetch_forecast.return_value = {
            "hourly": dummy_hourly
        }
        
        # 运行加载器
        target_date = "2026-06-20"
        run_backtest_load(target_date)
        
        # 验证 protocols 文件夹下正确生成了快照和概率文件，且文件契约验证通过
        import src.backtest_loader
        protocols_dir = src.backtest_loader.PROTOCOLS_DIR
        snapshot_file = os.path.join(protocols_dir, "market_snapshot_highest-temp-incheon-2026-06-20.json")
        probability_file = os.path.join(protocols_dir, "weather_probability_highest-temp-incheon-2026-06-20.json")
        
        self.assertTrue(os.path.exists(snapshot_file))
        self.assertTrue(os.path.exists(probability_file))
        
        # 读取并验证快照契约
        with open(snapshot_file, "r", encoding="utf-8") as f:
            snapshot_data = json.load(f)
        self.assertTrue(validate_contract(snapshot_data, "market_snapshot"))
        self.assertEqual(snapshot_data["ranges"][0]["ask_price"], 0.15)
        # 验证第二档成功执行了兜底降级（outcomePrices[0] = 0.65）
        self.assertEqual(snapshot_data["ranges"][1]["ask_price"], 0.65)
        
        # 读取并验证概率契约
        with open(probability_file, "r", encoding="utf-8") as f:
            prob_data = json.load(f)
        self.assertTrue(validate_contract(prob_data, "weather_probability"))
        
        # 清理生成的临时回测文件以保持 workspace 干净
        os.remove(snapshot_file)
        os.remove(probability_file)

if __name__ == "__main__":
    unittest.main()
