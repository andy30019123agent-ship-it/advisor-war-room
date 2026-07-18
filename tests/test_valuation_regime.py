"""估值 regime 校準 + sanity warning + band 測試（規格 §3.3）。假資料、不打 API。"""
import unittest

from warroom.valuation import (
    valuation_band, sanity_warning, regime_percentiles, select_regime,
    quality_base_bump, fair_value_per_path, compute_valuation,
)


class TestValuationRegime(unittest.TestCase):
    def test_band_language(self):
        self.assertEqual(valuation_band(0.20), "便宜")
        self.assertEqual(valuation_band(0.50), "合理")
        self.assertEqual(valuation_band(0.80), "偏貴")
        self.assertEqual(valuation_band(0.97), "很貴")
        self.assertIsNone(valuation_band(None))   # 契約 v1：資料不足給 null，不回中文字串

    def test_sanity_warning_threshold(self):
        # Base 偏離現價 >30% → 警語；<30% → None
        self.assertIsNotNone(sanity_warning(1500.0, 2440.0))   # 38% 偏離
        self.assertIsNone(sanity_warning(2300.0, 2440.0))      # 6% 偏離
        self.assertIsNone(sanity_warning(None, 2440.0))

    def test_regime_prefers_recent_window(self):
        # 早年低 PER（10）一大段 + 近 3 年高 PER（30）→ full 分位被拖低、3y 較高
        series = [10.0] * 2000 + [30.0] * 756
        regimes = regime_percentiles(series)
        self.assertIn("3y", regimes)
        label, pcts = select_regime(regimes)
        self.assertEqual(label, "3y")
        self.assertGreater(pcts["p50"], 25.0)                  # 近 3 年 regime ≈ 30
        # 完整週期的 p50 會被早年低基期壓到 10 附近
        self.assertLess(regimes["full"]["p50"], 20.0)

    def test_quality_bump_raises_base(self):
        self.assertEqual(quality_base_bump(None), 0.0)
        self.assertGreater(quality_base_bump(0.32), 0.0)       # 高 ROE → 上修
        pcts = {"p10": 20.0, "p25": 25.0, "p50": 30.0, "p75": 40.0}
        plain = fair_value_per_path(100.0, pcts, "amber", base_bump=0.0)
        bumped = fair_value_per_path(100.0, pcts, "amber", base_bump=quality_base_bump(0.32))
        self.assertGreater(bumped["base"], plain["base"])      # 品質股 Base 更高
        self.assertLessEqual(bumped["base"], bumped["bull"])   # 仍不超過 Bull

    def test_compute_valuation_emits_band_regime_warning(self):
        # 近 3 年高 PER，早年低 → 反推 EPS、Base 應被 regime 拉高；欄位齊備
        inp = {
            "price": 1000.0, "industry_category": "半導體業", "market_light": "amber",
            "fs_df": None, "rev_df": None,
            "per_series": [8.0] * 2000 + [40.0] * 756, "per_current": 40.0,
            "pbr_series": [], "pbr_current": None, "roe": 0.30,
        }
        out = compute_valuation(inp)
        self.assertEqual(out["regime"], "3y")
        self.assertIn(out["band"], ("便宜", "合理", "偏貴", "很貴"))
        self.assertIsNotNone(out["fair_value"])
        # eps_ttm = 1000/40 = 25；regime=3y p50≈40 → base 遠高於用早年低分位（≈8）算的結果
        self.assertGreater(out["fair_value"]["base"], 25 * 20)

    def test_current_percentile_uses_selected_regime_not_full_series(self):
        # 回歸 bug #6（regime 混算）：current_percentile／band 要用 select_regime() 選定的
        # 同一段子序列，不可 fair value 用 3y、分位卻用完整週期。早年 2000 筆低 PER(10)
        # + 近 3 年 756 筆 20~40 均勻分布；current=30 在 3y regime 內約中段（合理），
        # 若誤用完整週期，早年全部 <30 會把分位推去接近 1.0（很貴），兩者結論明顯不同。
        early = [10.0] * 2000
        recent = [20.0 + (i % 21) for i in range(756)]  # 20..40 均勻循環
        inp = {
            "price": 900.0, "industry_category": "半導體業", "market_light": "amber",
            "fs_df": None, "rev_df": None,
            "per_series": early + recent, "per_current": 30.0,
            "pbr_series": [], "pbr_current": None, "roe": None,
        }
        out = compute_valuation(inp)
        self.assertEqual(out["regime"], "3y")
        self.assertGreater(out["current_percentile"], 0.35)
        self.assertLess(out["current_percentile"], 0.65)
        self.assertEqual(out["band"], "合理")

    def test_compute_valuation_warns_when_base_far_from_price(self):
        # 全程低 PER + 高價 → Base 遠低於現價 → warning 觸發、且是字串
        inp = {
            "price": 3000.0, "industry_category": "半導體業", "market_light": "amber",
            "fs_df": None, "rev_df": None,
            "per_series": [float(x) for x in range(5, 15)] * 100, "per_current": 60.0,
            "pbr_series": [], "pbr_current": None, "roe": None,
        }
        out = compute_valuation(inp)
        self.assertIsNotNone(out["warning"])
        self.assertIn("偏離", out["warning"])


if __name__ == "__main__":
    unittest.main()
