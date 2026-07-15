"""Task A：籌碼拆解 v2 測試（假法人資料 fixture，不打真 API）。"""
import unittest

import pandas as pd

from warroom.chips_v2 import chips_breakdown


def make_chip(rows):
    """rows: list of (date, name, buy, sell)。單位=股。"""
    return pd.DataFrame([{"date": d, "stock_id": "1111", "name": n,
                          "buy": b, "sell": s} for (d, n, b, s) in rows])


class TestChipsV2(unittest.TestCase):
    def test_group_aggregation(self):
        # 同一天：外資 = Foreign_Investor + Foreign_Dealer_Self
        df = make_chip([
            ("2026-07-14", "Foreign_Investor", 100, 50),      # 外資淨 +50
            ("2026-07-14", "Foreign_Dealer_Self", 10, 5),     # 外資淨 +5 → 外資合計 +55
            ("2026-07-14", "Investment_Trust", 30, 10),       # 投信 +20
            ("2026-07-14", "Dealer_self", 5, 8),              # 自營 -3
            ("2026-07-14", "Dealer_Hedging", 2, 1),           # 自營 +1 → 自營合計 -2
        ])
        out = chips_breakdown(df, vol20=1000.0)
        g = out["groups"]
        self.assertEqual(g["外資"]["net_latest"], 55)
        self.assertEqual(g["投信"]["net_latest"], 20)
        self.assertEqual(g["自營"]["net_latest"], -2)
        self.assertEqual(g["外資"]["dir"], "買")
        self.assertEqual(g["自營"]["dir"], "賣")
        self.assertEqual(out["as_of"], "2026-07-14")

    def test_ratio_20d_vol(self):
        df = make_chip([("2026-07-14", "Foreign_Investor", 500, 0)])  # 淨 +500 股
        out = chips_breakdown(df, vol20=1000.0)
        self.assertAlmostEqual(out["groups"]["外資"]["ratio_20d_vol"], 0.5)
        # vol20 缺 → ratio None，不誤報
        out2 = chips_breakdown(df, vol20=None)
        self.assertIsNone(out2["groups"]["外資"]["ratio_20d_vol"])

    def test_streak_counts_consecutive_same_dir(self):
        # 外資連 3 天賣（淨負），第 4 天（最舊）買 → streak=3
        df = make_chip([
            ("2026-07-09", "Foreign_Investor", 100, 10),   # +90 買
            ("2026-07-10", "Foreign_Investor", 10, 100),   # -90 賣
            ("2026-07-11", "Foreign_Investor", 10, 100),   # -90 賣
            ("2026-07-14", "Foreign_Investor", 10, 100),   # -90 賣（最新）
        ])
        out = chips_breakdown(df, vol20=1000.0)
        self.assertEqual(out["groups"]["外資"]["dir"], "賣")
        self.assertEqual(out["groups"]["外資"]["streak"], 3)

    def test_net_5d(self):
        df = make_chip([(f"2026-07-{d:02d}", "Investment_Trust", 10, 0)
                        for d in (7, 8, 9, 10, 11, 14)])  # 6 天各 +10
        out = chips_breakdown(df, vol20=1000.0)
        self.assertEqual(out["groups"]["投信"]["net_5d"], 50)  # 只算最近 5 天

    def test_divergence_foreign_sell_trust_buy(self):
        df = make_chip([
            ("2026-07-14", "Foreign_Investor", 0, 100),    # 外資賣
            ("2026-07-14", "Investment_Trust", 100, 0),    # 投信買
        ])
        out = chips_breakdown(df, vol20=1000.0)
        self.assertTrue(out["divergence"])
        self.assertIn("外資賣", out["divergence_note"])

    def test_no_divergence_same_dir(self):
        df = make_chip([
            ("2026-07-14", "Foreign_Investor", 100, 0),    # 外資買
            ("2026-07-14", "Investment_Trust", 100, 0),    # 投信買
        ])
        out = chips_breakdown(df, vol20=1000.0)
        self.assertFalse(out["divergence"])
        self.assertEqual(out["divergence_note"], "")

    def test_empty_df_safe(self):
        out = chips_breakdown(pd.DataFrame(), vol20=1000.0)
        self.assertFalse(out["divergence"])
        self.assertEqual(out["groups"]["外資"]["net_latest"], 0)
        self.assertIsNone(out["as_of"])


if __name__ == "__main__":
    unittest.main()
