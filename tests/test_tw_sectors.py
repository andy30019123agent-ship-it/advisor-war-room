"""Task C：台股類股量化輪動測試（假日線 fixture，不打真 API）。"""
import unittest

import pandas as pd

from warroom.sectors import stock_momentum, tw_group_metrics, _tier_for


def make_price(closes, vols=None):
    n = len(closes)
    vols = vols or [1000.0] * n
    # 用真實遞增日期（不循環進位），避免 sort_values("date") 打亂與生成順序不一致的舊 bug。
    dates = pd.date_range("2026-01-01", periods=n, freq="D").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "close": closes, "Trading_Volume": vols})


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

    def test_stock_momentum_order_independent(self):
        # 防回歸：把正確 fixture 的列順序打亂餵入，結果須與排序版完全相同
        # （證明 stock_momentum 內部靠 sort_values("date") 自行還原順序，不依賴輸入順序）。
        closes = [100.0 + i for i in range(70)]
        price = make_price(closes)
        shuffled = price.sample(frac=1, random_state=42).reset_index(drop=True)
        self.assertFalse(shuffled["date"].tolist() == price["date"].tolist())  # 確認真的打亂了
        m_sorted = stock_momentum(price)
        m_shuffled = stock_momentum(shuffled)
        self.assertEqual(m_sorted, m_shuffled)

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
        self.assertEqual(g["coverage"], 0)

    # ---------- P1 終審修復 #10：缺窗口重新歸一化，不當 0 計分 ----------
    def test_tw_group_metrics_coverage_and_renormalized_weight(self):
        # 只有 25 天資料：m5/m20 可算，m60 需 61 筆 → None
        up = make_price([100.0 + i * 1.0 for i in range(25)])
        twii = make_price([100.0 + i * 0.2 for i in range(25)])
        g = tw_group_metrics("短資料族群", [up], twii)
        self.assertIsNone(g["m60"])
        self.assertIsNotNone(g["m20"])
        self.assertEqual(g["coverage"], 2)   # m5、m20 可用；m60 不可用
        # 不得把 m60 當 0：score 應為「可用窗口」重新歸一化後的加權平均 + rs 加成
        expected_base = (0.4 * g["m5"] + 0.35 * g["m20"]) / 0.75
        expected_score = round(expected_base + 0.3 * (g["rs_vs_twii"] or 0), 2)
        self.assertAlmostEqual(g["score"], expected_score, places=2)

    def test_tier_for_lead_requires_m20(self):
        self.assertEqual(_tier_for(5.0, 10.0), "lead")
        self.assertEqual(_tier_for(5.0, None), "mid")    # m20 缺 → 不得列 lead，但仍可列 mid
        self.assertEqual(_tier_for(-5.0, None), "lag")
        self.assertEqual(_tier_for(None, 10.0), "na")


if __name__ == "__main__":
    unittest.main()
