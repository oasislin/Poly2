import unittest
import numpy as np
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.strategy import check_hedge_opportunity


def _make_ranges(n=5):
    ranges = []
    for i in range(n):
        cond = f"{75 + i}-{76 + i}"
        ranges.append({
            "range_id": f"range_{i}",
            "condition": cond,
            "yes_token_id": f"yes_token_{i}",
            "no_token_id": f"no_token_{i}",
        })
    return ranges


def _make_deep_book(price, depth=1000.0):
    return [
        [price, depth],
        [price + 0.01, depth],
        [price + 0.02, depth],
    ]


def _make_shallow_book(best_price, total_value=100.0):
    return [
        [best_price, total_value / best_price * 0.2],
        [best_price + 0.03, total_value / (best_price + 0.03) * 0.3],
        [best_price + 0.07, total_value / (best_price + 0.07) * 0.5],
    ]


def _build_clob_books(ranges, yes_book_fn=None, no_book_fn=None):
    clob_books = {}
    for i, r in enumerate(ranges):
        if yes_book_fn:
            clob_books[r["yes_token_id"]] = {"asks": yes_book_fn(i), "bids": []}
        if no_book_fn:
            clob_books[r["no_token_id"]] = {"asks": no_book_fn(i), "bids": []}
    return clob_books


class TestHedgeLogic(unittest.TestCase):

    def test_no_holdings_no_hedge(self):
        ranges = _make_ranges(3)
        holdings = {"YES": {}, "NO": {}}
        clob_books = _build_clob_books(
            ranges,
            yes_book_fn=lambda i: _make_deep_book(0.25),
            no_book_fn=lambda i: _make_deep_book(0.75),
        )
        no_prices = np.array([0.75, 0.75, 0.75])
        yes_prices = np.array([0.25, 0.25, 0.25])
        q_eff_yes = np.array([0.25, 0.25, 0.25])

        is_hedge, x_yes, x_no = check_hedge_opportunity(
            ranges, holdings, clob_books, no_prices, yes_prices, q_eff_yes,
            taker_base_fee=0.0125, min_dutch_book_margin=0.02
        )

        self.assertFalse(is_hedge)
        np.testing.assert_array_equal(x_yes, np.zeros(3))
        np.testing.assert_array_equal(x_no, np.zeros(3))

    def test_deep_book_no_slippage_should_hedge_no(self):
        ranges = _make_ranges(3)
        holdings = {
            "YES": {"range_1": {"avg_price": 0.20, "shares": 100.0}},
            "NO": {},
        }
        clob_books = _build_clob_books(
            ranges,
            yes_book_fn=lambda i: _make_deep_book(0.90),
            no_book_fn=lambda i: _make_deep_book(0.75),
        )
        no_prices = np.array([0.75, 0.75, 0.75])
        yes_prices = np.array([0.90, 0.90, 0.90])
        q_eff_yes = np.array([0.90, 0.90, 0.90])

        is_hedge, x_yes, x_no = check_hedge_opportunity(
            ranges, holdings, clob_books, no_prices, yes_prices, q_eff_yes,
            taker_base_fee=0.0125, min_dutch_book_margin=0.02
        )

        self.assertTrue(is_hedge)
        self.assertGreater(x_no[1], 0.0)
        self.assertAlmostEqual(x_yes[0], 0.0)
        self.assertAlmostEqual(x_yes[2], 0.0)

    def test_shallow_book_high_slippage_no_hedge(self):
        ranges = _make_ranges(3)
        holdings = {
            "YES": {"range_1": {"avg_price": 0.20, "shares": 500.0}},
            "NO": {},
        }
        clob_books = _build_clob_books(
            ranges,
            yes_book_fn=lambda i: _make_deep_book(0.90),
            no_book_fn=lambda i: _make_shallow_book(0.75, 200.0),
        )
        no_prices = np.array([0.75, 0.75, 0.75])
        yes_prices = np.array([0.90, 0.90, 0.90])
        q_eff_yes = np.array([0.90, 0.90, 0.90])

        is_hedge, x_yes, x_no = check_hedge_opportunity(
            ranges, holdings, clob_books, no_prices, yes_prices, q_eff_yes,
            taker_base_fee=0.0125, min_dutch_book_margin=0.02
        )

        self.assertFalse(is_hedge)
        np.testing.assert_array_equal(x_yes, np.zeros(3))
        np.testing.assert_array_equal(x_no, np.zeros(3))

    def test_seattle_july_20_scenario_no_hedge(self):
        ranges = [
            {"range_id": "range_78", "condition": "78-79",
             "yes_token_id": "yes_78", "no_token_id": "no_78"},
            {"range_id": "range_80", "condition": "80-81",
             "yes_token_id": "yes_80", "no_token_id": "no_80"},
            {"range_id": "range_82", "condition": "82-83",
             "yes_token_id": "yes_82", "no_token_id": "no_82"},
        ]
        holdings = {
            "YES": {"range_80": {"avg_price": 0.2190, "shares": 286.20}},
            "NO": {},
        }
        shallow_no_asks = [
            [0.7501, 30.0],
            [0.7800, 50.0],
            [0.8200, 100.0],
            [0.8500, 200.0],
        ]
        clob_books = {
            "yes_78": {"asks": [[0.85, 500]], "bids": []},
            "yes_80": {"asks": [[0.22, 500]], "bids": []},
            "yes_82": {"asks": [[0.90, 500]], "bids": []},
            "no_78": {"asks": [[0.85, 500]], "bids": []},
            "no_80": {"asks": shallow_no_asks, "bids": []},
            "no_82": {"asks": [[0.90, 500]], "bids": []},
        }
        no_prices = np.array([0.85, 0.7501, 0.90])
        yes_prices = np.array([0.85, 0.22, 0.90])
        q_eff_yes = np.array([0.85, 0.22, 0.90])

        is_hedge, x_yes, x_no = check_hedge_opportunity(
            ranges, holdings, clob_books, no_prices, yes_prices, q_eff_yes,
            taker_base_fee=0.0125, min_dutch_book_margin=0.02
        )

        self.assertFalse(is_hedge, "NO滑点大且其他YES贵，应完全放弃对冲")
        np.testing.assert_array_equal(x_yes, np.zeros(3))
        np.testing.assert_array_equal(x_no, np.zeros(3))

    def test_seattle_july_20_deep_book_should_hedge(self):
        ranges = [
            {"range_id": "range_80", "condition": "80-81",
             "yes_token_id": "yes_80", "no_token_id": "no_80"},
        ]
        holdings = {
            "YES": {"range_80": {"avg_price": 0.2190, "shares": 286.20}},
            "NO": {},
        }
        deep_no_asks = [
            [0.7501, 1000.0],
            [0.7510, 1000.0],
        ]
        clob_books = {
            "yes_80": {"asks": [[0.22, 1000]], "bids": []},
            "no_80": {"asks": deep_no_asks, "bids": []},
        }
        no_prices = np.array([0.7501])
        yes_prices = np.array([0.22])
        q_eff_yes = np.array([0.22])

        is_hedge, x_yes, x_no = check_hedge_opportunity(
            ranges, holdings, clob_books, no_prices, yes_prices, q_eff_yes,
            taker_base_fee=0.0125, min_dutch_book_margin=0.02
        )

        self.assertTrue(is_hedge, "深盘口无滑点时应触发 NO 对冲")
        self.assertGreater(x_no[0], 0.0)
        expected_budget = 286.20 * 0.7501
        self.assertAlmostEqual(x_no[0], expected_budget * 1.005, delta=expected_budget * 0.02)

    def test_hedge_target_amount_matches_shares(self):
        ranges = [
            {"range_id": "r0", "condition": "70-71",
             "yes_token_id": "yes0", "no_token_id": "no0"},
        ]
        shares = 100.0
        holdings = {
            "YES": {"r0": {"avg_price": 0.30, "shares": shares}},
            "NO": {},
        }
        clob_books = {
            "yes0": {"asks": [[0.40, 200.0]], "bids": []},
            "no0": {"asks": [[0.60, 200.0]], "bids": []},
        }
        no_prices = np.array([0.60])
        yes_prices = np.array([0.40])
        q_eff_yes = np.array([0.40])

        is_hedge, x_yes, x_no = check_hedge_opportunity(
            ranges, holdings, clob_books, no_prices, yes_prices, q_eff_yes,
            taker_base_fee=0.0125, min_dutch_book_margin=0.02
        )

        self.assertTrue(is_hedge)
        no_q_eff = 0.60 * (1.0 + 0.0125 * (1.0 - 0.60))
        expected_target = shares * no_q_eff
        self.assertAlmostEqual(x_no[0], expected_target, places=2)

    def test_empty_clob_book_uses_fallback(self):
        ranges = [
            {"range_id": "r0", "condition": "70-71",
             "yes_token_id": "yes0", "no_token_id": "no0"},
        ]
        holdings = {
            "YES": {"r0": {"avg_price": 0.20, "shares": 50.0}},
            "NO": {},
        }
        clob_books = {
            "yes0": {"asks": [], "bids": []},
            "no0": {"asks": [], "bids": []},
        }
        no_prices = np.array([0.60])
        yes_prices = np.array([0.40])
        q_eff_yes = np.array([0.40])

        is_hedge, x_yes, x_no = check_hedge_opportunity(
            ranges, holdings, clob_books, no_prices, yes_prices, q_eff_yes,
            taker_base_fee=0.0125, min_dutch_book_margin=0.02
        )

        self.assertTrue(is_hedge)
        self.assertGreater(x_no[0], 0.0)

    def test_yes_cost_too_high_no_hedge(self):
        ranges = [
            {"range_id": "r0", "condition": "70-71",
             "yes_token_id": "yes0", "no_token_id": "no0"},
        ]
        holdings = {
            "YES": {"r0": {"avg_price": 0.50, "shares": 100.0}},
            "NO": {},
        }
        clob_books = {
            "yes0": {"asks": [[0.45, 1000.0]], "bids": []},
            "no0": {"asks": [[0.55, 1000.0]], "bids": []},
        }
        no_prices = np.array([0.55])
        yes_prices = np.array([0.45])
        q_eff_yes = np.array([0.45])

        is_hedge, x_yes, x_no = check_hedge_opportunity(
            ranges, holdings, clob_books, no_prices, yes_prices, q_eff_yes,
            taker_base_fee=0.0125, min_dutch_book_margin=0.02
        )

        self.assertFalse(is_hedge)

    def test_multi_yes_combination_hedge_deep_book(self):
        ranges = [
            {"range_id": "r0", "condition": "70-71",
             "yes_token_id": "yes0", "no_token_id": "no0"},
            {"range_id": "r1", "condition": "71-72",
             "yes_token_id": "yes1", "no_token_id": "no1"},
            {"range_id": "r2", "condition": "72-73",
             "yes_token_id": "yes2", "no_token_id": "no2"},
            {"range_id": "r3", "condition": "73-74",
             "yes_token_id": "yes3", "no_token_id": "no3"},
            {"range_id": "r4", "condition": "74-75",
             "yes_token_id": "yes4", "no_token_id": "no4"},
        ]
        holdings = {
            "YES": {"r0": {"avg_price": 0.10, "shares": 100.0}},
            "NO": {},
        }
        clob_books = _build_clob_books(
            ranges,
            yes_book_fn=lambda i: _make_deep_book([0.05, 0.15, 0.20, 0.15, 0.05][i]),
            no_book_fn=lambda i: _make_deep_book(0.95),
        )
        no_prices = np.array([0.95, 0.95, 0.95, 0.95, 0.95])
        yes_prices = np.array([0.05, 0.15, 0.20, 0.15, 0.05])
        q_eff_yes = np.array([0.05, 0.15, 0.20, 0.15, 0.05])

        is_hedge, x_yes, x_no = check_hedge_opportunity(
            ranges, holdings, clob_books, no_prices, yes_prices, q_eff_yes,
            taker_base_fee=0.0125, min_dutch_book_margin=0.02
        )

        self.assertTrue(is_hedge)
        self.assertEqual(x_no[0], 0.0)
        self.assertGreater(x_yes[1], 0.0)
        self.assertGreater(x_yes[2], 0.0)
        self.assertGreater(x_yes[3], 0.0)
        self.assertGreater(x_yes[4], 0.0)


if __name__ == "__main__":
    unittest.main()
