"""T3：合理價值區間 valuation.py 測試（假資料 fixture，不打真 API）。"""
import unittest

import pandas as pd

from warroom.valuation import (
    is_pbr_industry, ttm_eps_from_statement, weighted_revenue_yoy,
    forward_eps, multiple_percentiles, current_percentile,
    fair_value_per_path, fair_value_pbr_path, compute_valuation,
)


def make_fs(eps_by_quarter):
    """eps_by_quarter: list of (date, 單季EPS)。回長格式綜合損益表 DataFrame。"""
    rows = []
    for d, v in eps_by_quarter:
        rows.append({"date": d, "stock_id": "1111", "type": "EPS",
                     "value": v, "origin_name": "基本每股盈餘"})
        # 混入雜訊 type，測試要能過濾
        rows.append({"date": d, "stock_id": "1111", "type": "Revenue",
                     "value": 999.0, "origin_name": "營業收入"})
    return pd.DataFrame(rows)


def make_rev(months):
    """months: list of (year, month, revenue)。"""
    return pd.DataFrame([{"date": f"{y}-{m:02d}-01", "stock_id": "1111",
                          "revenue": r, "revenue_year": y, "revenue_month": m}
                         for (y, m, r) in months])


class TestValuation(unittest.TestCase):
    def test_is_pbr_industry(self):
        self.assertTrue(is_pbr_industry("金融保險"))
        self.assertTrue(is_pbr_industry("航運業"))
        self.assertFalse(is_pbr_industry("半導體業"))
        self.assertFalse(is_pbr_industry(None))

    def test_ttm_eps_sum_last4(self):
        # FinMind EPS 為單季值（2026-07-15 真 API 實測證實）：直接加總最近 4 季
        # 單季：25Q1=3,25Q2=4,25Q3=5,25Q4=8,26Q1=4 → 近4季（25Q2..26Q1）= 4+5+8+4 = 21
        fs = make_fs([("2025-03-31", 3), ("2025-06-30", 4), ("2025-09-30", 5),
                      ("2025-12-31", 8), ("2026-03-31", 4)])
        self.assertAlmostEqual(ttm_eps_from_statement(fs), 21.0)

    def test_ttm_eps_insufficient(self):
        fs = make_fs([("2026-03-31", 4)])  # 只有 1 季 → None
        self.assertIsNone(ttm_eps_from_statement(fs))
        self.assertIsNone(ttm_eps_from_statement(None))

    def test_weighted_revenue_yoy(self):
        # 造 24 個月，去年每月 100、今年每月 130 → 各窗口 YoY 皆 +30%
        months = [(2025, m, 100) for m in range(1, 13)] + \
                 [(2026, m, 130) for m in range(1, 13)]
        g = weighted_revenue_yoy(make_rev(months))
        self.assertAlmostEqual(g, 0.30, places=3)

    def test_forward_eps_clamps(self):
        self.assertAlmostEqual(forward_eps(100.0, 0.25), 125.0)
        self.assertAlmostEqual(forward_eps(100.0, 0.90), 140.0)   # clamp 上限 +40%
        self.assertAlmostEqual(forward_eps(100.0, -0.50), 80.0)   # clamp 下限 -20%
        self.assertAlmostEqual(forward_eps(100.0, None), 100.0)   # 無成長 → g=0

    def test_multiple_percentiles(self):
        pcts = multiple_percentiles(list(range(10, 30)))  # 10..29
        self.assertIsNotNone(pcts)
        self.assertLess(pcts["p25"], pcts["p50"])
        self.assertLess(pcts["p50"], pcts["p75"])
        self.assertIsNone(multiple_percentiles([10, 11, 12]))  # 樣本<8 → None

    def test_current_percentile(self):
        self.assertAlmostEqual(current_percentile([10, 20, 30, 40], 35), 0.75)
        self.assertIsNone(current_percentile([], 10))

    def test_fair_value_per_path_red_market_downgrades(self):
        pcts = {"p10": 20.0, "p25": 25.0, "p50": 30.0, "p75": 35.0}
        normal = fair_value_per_path(100.0, pcts, "amber")
        red = fair_value_per_path(100.0, pcts, "red")
        self.assertEqual(normal["base"], 3000.0)  # 100×30
        self.assertEqual(red["base"], 2500.0)      # 下修一檔 → 100×25
        self.assertLess(red["bull"], normal["bull"])

    def test_fair_value_pbr_path(self):
        pcts = {"p10": 0.8, "p25": 1.0, "p50": 1.5, "p75": 2.0}
        fv = fair_value_pbr_path(150.0, 1.5, pcts, roe=0.20, market_light="amber")
        # BVPS = 150/1.5 = 100；ROE>15% → base 用 (p50+p75)/2=1.75
        self.assertAlmostEqual(fv["bvps"], 100.0)
        self.assertAlmostEqual(fv["base"], 175.0)

    def test_compute_valuation_per_path(self):
        fs = make_fs([("2025-03-31", 3), ("2025-06-30", 4), ("2025-09-30", 5),
                      ("2025-12-31", 8), ("2026-03-31", 4)])  # TTM=21（最近4季 4+5+8+4）
        inp = {
            "price": 700.0, "industry_category": "半導體業", "market_light": "amber",
            "fs_df": fs, "rev_df": make_rev([(2025, m, 100) for m in range(1, 13)] +
                                            [(2026, m, 130) for m in range(1, 13)]),
            "per_series": [float(x) for x in range(10, 30)], "per_current": 25.0,
            "pbr_series": [], "pbr_current": None, "roe": None,
        }
        out = compute_valuation(inp)
        self.assertEqual(out["path"], "per")
        self.assertEqual(out["eps_ttm"], 21.0)
        self.assertEqual(out["eps_source"], "financial_statement")
        self.assertIsNotNone(out["fair_value"])
        self.assertEqual(out["confidence_penalty"], 0)

    def test_compute_valuation_backout_fallback(self):
        # 無財報 → 用 現價/PER 反推、降信心
        inp = {
            "price": 500.0, "industry_category": "半導體業", "market_light": "amber",
            "fs_df": None, "rev_df": None,
            "per_series": [float(x) for x in range(10, 30)], "per_current": 20.0,
            "pbr_series": [], "pbr_current": None, "roe": None,
        }
        out = compute_valuation(inp)
        self.assertEqual(out["eps_source"], "per_backout")
        self.assertAlmostEqual(out["eps_ttm"], 25.0)  # 500/20
        self.assertGreater(out["confidence_penalty"], 0)

    def test_compute_valuation_negative_eps_no_per_valuation(self):
        # 虧損股（TTM EPS<0）：不得走 PER 相對估值，fair_value=None，disclosure 註明虧損
        fs = make_fs([("2025-03-31", -2), ("2025-06-30", -3), ("2025-09-30", -1),
                      ("2025-12-31", -4), ("2026-03-31", -2)])  # 近4季皆虧損 → TTM<0
        inp = {
            "price": 30.0, "industry_category": "半導體業", "market_light": "amber",
            "fs_df": fs, "rev_df": make_rev([(2025, m, 100) for m in range(1, 13)] +
                                            [(2026, m, 340) for m in range(1, 13)]),  # 若誤用會有極端g
            "per_series": [float(x) for x in range(10, 30)], "per_current": None,
            "pbr_series": [], "pbr_current": None, "roe": None,
        }
        out = compute_valuation(inp)
        self.assertIsNone(out["fair_value"])
        self.assertIsNone(out["eps_ttm"])  # 走既有估值不足路徑，不回傳負 EPS
        self.assertIn("虧損", out["disclosure"])
        self.assertGreater(out["confidence_penalty"], 0)

    def test_compute_valuation_zero_eps_no_per_valuation(self):
        # 零盈餘（TTM EPS==0）同樣不適用相對估值
        fs = make_fs([("2025-03-31", 0), ("2025-06-30", 0), ("2025-09-30", 0),
                      ("2025-12-31", 0), ("2026-03-31", 0)])
        inp = {
            "price": 30.0, "industry_category": "半導體業", "market_light": "amber",
            "fs_df": fs, "rev_df": None,
            "per_series": [float(x) for x in range(10, 30)], "per_current": None,
            "pbr_series": [], "pbr_current": None, "roe": None,
        }
        out = compute_valuation(inp)
        self.assertIsNone(out["fair_value"])
        self.assertIn("虧損", out["disclosure"])

    def test_disclosure_shows_clamped_growth_not_raw(self):
        # 8299 型案例：加權YoY遠超 +40% 上限 → disclosure 要顯示封頂後 g，並附註原始值
        fs = make_fs([("2025-03-31", 3), ("2025-06-30", 4), ("2025-09-30", 5),
                      ("2025-12-31", 8), ("2026-03-31", 4)])  # TTM=21
        months = [(2025, m, 100) for m in range(1, 13)] + \
                 [(2026, m, 340) for m in range(1, 13)]  # 今年營收暴增 → 加權YoY遠 >40%
        inp = {
            "price": 700.0, "industry_category": "半導體業", "market_light": "amber",
            "fs_df": fs, "rev_df": make_rev(months),
            "per_series": [float(x) for x in range(10, 30)], "per_current": 25.0,
            "pbr_series": [], "pbr_current": None, "roe": None,
        }
        out = compute_valuation(inp)
        self.assertAlmostEqual(out["growth_used"], 0.40)  # 已封頂 +40%
        self.assertIn("+40.0%", out["disclosure"])
        self.assertIn("已封頂", out["disclosure"])
        # 原始加權YoY遠高於 40%，也要附註出現在 disclosure
        self.assertNotIn("g=+240", out["disclosure"])  # 不能把原始值當成 g= 顯示

    def test_compute_valuation_pbr_path(self):
        inp = {
            "price": 60.0, "industry_category": "金融保險", "market_light": "amber",
            "fs_df": None, "rev_df": None, "per_series": [], "per_current": None,
            "pbr_series": [0.8 + 0.02 * i for i in range(20)], "pbr_current": 1.0,
            "roe": 0.12,
        }
        out = compute_valuation(inp)
        self.assertEqual(out["path"], "pbr")
        self.assertIsNotNone(out["fair_value"])


if __name__ == "__main__":
    unittest.main()
