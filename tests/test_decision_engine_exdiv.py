"""Task D：decision_engine 除權息調整測試（不動 P0 既有 test_decision_engine.py）。"""
import unittest

import pandas as pd

from warroom.decision_engine import atr14, invalidation


def flat_price(n=20, close=100.0, hi=1.0, lo=1.0):
    """平盤 n 天：high=close+hi, low=close-lo。回 DataFrame。"""
    return pd.DataFrame({"date": [f"2026-06-{i+1:02d}" for i in range(n)],
                         "max": [close + hi] * n, "min": [close - lo] * n,
                         "close": [close] * n})


class TestExDivAdjust(unittest.TestCase):
    def test_atr_suppresses_ex_div_gap(self):
        # 19 天平盤 100，第 20 天除息跳空到 96（配息 4）
        df = flat_price(19)
        df = pd.concat([df, pd.DataFrame([{"date": "2026-06-20", "max": 97.0,
                        "min": 95.0, "close": 96.0}])], ignore_index=True)
        naive = atr14(df)                                   # 未調整：跳空灌大 TR
        adj = atr14(df, ex_div_map={"2026-06-20": 4.0})     # 調整：還原前收，抑制跳空
        self.assertIsNotNone(naive)
        self.assertIsNotNone(adj)
        self.assertLess(adj, naive)                         # 調整後 ATR 明顯較小

    def test_atr_default_unchanged(self):
        # ex_div_map=None → 與 P0 行為一致（不改既有結果）
        df = flat_price(20)
        self.assertEqual(atr14(df), atr14(df, ex_div_map=None))

    def test_invalidation_price_layer_normal(self):
        # 一般日：收盤 96 跌破防守位 97 → 觸發
        inv = invalidation(97.0, {"yoy_negative": False, "below_6m_2months": False},
                           {"sell_streak_ge3": False, "ratio_gt_15pct": False},
                           price=96.0, ex_dividend_today=False, ex_div_amt=0.0)
        self.assertIn("已觸發", inv["price"])
        self.assertTrue(inv["any_triggered"])

    def test_invalidation_price_suppressed_on_ex_div(self):
        # 除息日：收盤 96、配息 4 → 還原 100 >= 防守位 97 → 不觸發
        inv = invalidation(97.0, {"yoy_negative": False, "below_6m_2months": False},
                           {"sell_streak_ge3": False, "ratio_gt_15pct": False},
                           price=96.0, ex_dividend_today=True, ex_div_amt=4.0)
        self.assertIn("除息", inv["price"])
        self.assertFalse(inv["any_triggered"])


if __name__ == "__main__":
    unittest.main()
