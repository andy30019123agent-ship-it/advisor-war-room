"""Task C：台股類股量化輪動測試（假日線 fixture，不打真 API）。"""
import unittest

import pandas as pd

from warroom.sectors import stock_momentum, tw_group_metrics


def make_price(closes, vols=None):
    n = len(closes)
    vols = vols or [1000.0] * n
    return pd.DataFrame({"date": [f"2026-05-{(i % 28) + 1:02d}" for i in range(n)],
                         "close": closes, "Trading_Volume": vols})


class TestTwSectors(unittest.TestCase):
    def test_stock_momentum_returns(self):
        # 70 天，從 100 每天 +1 → 最新 169
        closes = [100.0 + i for i in range(70)]
        m = stock_momentum(make_price(closes))
        # r5 = (169/164 - 1)*100
        self.assertAlmostEqual(m["r5"], (169 / 164 - 1) * 100, places=3)
        self.assertAlmostEqual(m["r20"], (169 / 149 - 1) * 100, places=3)
        self.assertAlmostEqual(m["r60"], (169 / 109 - 1) * 100, places=3)
        self.assertIsNotNone(m["vol5"])
        self.assertIsNotNone(m["vol60"])

    def test_stock_momentum_insufficient(self):
        m = stock_momentum(make_price([100.0, 101.0, 102.0]))
        self.assertIsNone(m["r60"])   # 不足 61 筆
        self.assertIsNone(m["r5"])    # r5 也不足（<6 筆）→ None

    def test_tw_group_metrics_equal_weight(self):
        # 兩檔：一檔 r20=+10%、一檔 r20=+20% → 等權 +15%
        up10 = make_price([100.0 + i * 0.5 for i in range(70)])   # 平緩上漲
        up20 = make_price([100.0 + i * 1.0 for i in range(70)])   # 較陡上漲
        twii = make_price([100.0 + i * 0.2 for i in range(70)])   # 大盤更緩
        g = tw_group_metrics("測試族群", [up10, up20], twii)
        self.assertIsNotNone(g["m20"])
        self.assertIsNotNone(g["rs_vs_twii"])
        self.assertGreater(g["rs_vs_twii"], 0)   # 族群強於大盤
        self.assertIsNotNone(g["score"])
        self.assertEqual(g["group"], "測試族群")

    def test_tw_group_metrics_all_missing_safe(self):
        g = tw_group_metrics("空族群", [], None)
        self.assertIsNone(g["m5"])
        self.assertIsNone(g["score"])   # 無資料 → score None（排名時濾掉）


if __name__ == "__main__":
    unittest.main()
