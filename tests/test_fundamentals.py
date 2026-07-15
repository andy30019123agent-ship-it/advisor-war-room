"""Task B：財報品質分數 + ROE 測試（假三表 fixture，不打真 API）。"""
import unittest

import pandas as pd

from warroom.fundamentals import (
    compute_fundamentals, compute_roe, _ttm, _series, _eps_factor, _fcf_factor,
)


def make_fs(quarters):
    """quarters: list of dict {date, EPS, Revenue, GrossProfit, OperatingIncome, NetIncome}。
    缺的鍵不放列（模擬金融股缺科目）。NetIncome 用 type=IncomeAfterTaxes。"""
    rows = []
    type_map = {"EPS": "EPS", "Revenue": "Revenue", "GrossProfit": "GrossProfit",
                "OperatingIncome": "OperatingIncome", "NetIncome": "IncomeAfterTaxes",
                "NetIncomeBank": "IncomeAfterTax"}
    for q in quarters:
        for k, v in q.items():
            if k == "date":
                continue
            rows.append({"date": q["date"], "stock_id": "1111",
                         "type": type_map[k], "value": v, "origin_name": k})
    return pd.DataFrame(rows)


def make_bs(equity, liabilities, total_assets, date="2026-03-31"):
    rows = [
        {"date": date, "stock_id": "1111", "type": "Equity", "value": equity, "origin_name": "權益總額"},
        {"date": date, "stock_id": "1111", "type": "Equity_per", "value": 40.0, "origin_name": "權益%"},
        {"date": date, "stock_id": "1111", "type": "Liabilities", "value": liabilities, "origin_name": "負債總額"},
        {"date": date, "stock_id": "1111", "type": "TotalAssets", "value": total_assets, "origin_name": "資產總額"},
    ]
    return pd.DataFrame(rows)


def make_cf(op_by_quarter):
    """op_by_quarter: list of (date, 營業現金流)。"""
    return pd.DataFrame([{"date": d, "stock_id": "1111",
                          "type": "CashFlowsFromOperatingActivities",
                          "value": v, "origin_name": "營業活動之淨現金流入"}
                         for (d, v) in op_by_quarter])


def make_rev(months):
    return pd.DataFrame([{"date": f"{y}-{m:02d}-01", "stock_id": "1111",
                          "revenue": r, "revenue_year": y, "revenue_month": m}
                         for (y, m, r) in months])


# 8 季一般股：營收/EPS/毛利/營益逐季走高
Q8 = [
    {"date": "2024-03-31", "EPS": 8.0, "Revenue": 5000, "GrossProfit": 2500, "OperatingIncome": 2000, "NetIncome": 1800},
    {"date": "2024-06-30", "EPS": 9.0, "Revenue": 5200, "GrossProfit": 2650, "OperatingIncome": 2100, "NetIncome": 1900},
    {"date": "2024-09-30", "EPS": 10.0, "Revenue": 5500, "GrossProfit": 2850, "OperatingIncome": 2250, "NetIncome": 2050},
    {"date": "2024-12-31", "EPS": 11.0, "Revenue": 5800, "GrossProfit": 3050, "OperatingIncome": 2400, "NetIncome": 2200},
    {"date": "2025-03-31", "EPS": 12.0, "Revenue": 6100, "GrossProfit": 3250, "OperatingIncome": 2550, "NetIncome": 2350},
    {"date": "2025-06-30", "EPS": 13.0, "Revenue": 6400, "GrossProfit": 3450, "OperatingIncome": 2700, "NetIncome": 2500},
    {"date": "2025-09-30", "EPS": 14.0, "Revenue": 6700, "GrossProfit": 3650, "OperatingIncome": 2850, "NetIncome": 2650},
    {"date": "2025-12-31", "EPS": 15.0, "Revenue": 7000, "GrossProfit": 3850, "OperatingIncome": 3000, "NetIncome": 2800},
]


class TestFundamentals(unittest.TestCase):
    def test_compute_roe(self):
        fs = make_fs(Q8)
        bs = make_bs(equity=40000, liabilities=20000, total_assets=60000)
        # TTM 淨利 = 2350+2500+2650+2800 = 10300；ROE = 10300/40000 = 0.2575
        roe = compute_roe(fs, bs)
        self.assertAlmostEqual(roe, 0.2575, places=4)

    def test_compute_roe_missing_equity(self):
        self.assertIsNone(compute_roe(make_fs(Q8), None))
        self.assertIsNone(compute_roe(None, make_bs(1, 1, 2)))

    def test_full_industrial_all_applicable(self):
        out = compute_fundamentals({
            "fs_df": make_fs(Q8),
            "bs_df": make_bs(equity=40000, liabilities=20000, total_assets=60000),
            "cf_df": make_cf([("2024-03-31", 1500), ("2024-06-30", 1600),
                              ("2025-03-31", 1700), ("2025-06-30", 1800)]),
            "rev_df": make_rev([(2025, m, 100) for m in range(1, 13)] +
                               [(2026, m, 130) for m in range(1, 13)]),
            "industry_category": "半導體業",
        })
        f = out["factors"]
        # 一般股 7 因子全可用
        self.assertTrue(all(f[k]["applicable"] for k in
                            ("revenue", "eps", "gross_margin", "operating_margin", "roe", "debt")))
        self.assertEqual(f["revenue"]["score"], 2)     # 月營收 YoY +30%
        self.assertEqual(f["eps"]["score"], 2)         # TTM EPS 54 vs 前 38 → +42%
        self.assertEqual(f["roe"]["score"], 2)         # ROE 25.75% > 15%
        self.assertEqual(f["debt"]["score"], 2)        # 負債比 20000/60000 = 0.33 < 0.4
        self.assertIsNotNone(out["roe_value"])
        self.assertGreater(out["max"], 0)
        self.assertLessEqual(out["total"], out["max"])

    def test_financial_stock_fallback(self):
        # 金融股：無 GrossProfit / OperatingIncome，用 IncomeAfterTax，債務不評分
        fin_q = [{"date": q["date"], "EPS": q["EPS"], "Revenue": q["Revenue"],
                  "NetIncomeBank": q["NetIncome"]} for q in Q8]
        out = compute_fundamentals({
            "fs_df": make_fs(fin_q),
            "bs_df": make_bs(equity=500000, liabilities=9000000, total_assets=9500000),
            "cf_df": None,
            "rev_df": None,
            "industry_category": "金融保險",
        })
        f = out["factors"]
        self.assertFalse(f["gross_margin"]["applicable"])   # 缺科目 → 不適用
        self.assertFalse(f["operating_margin"]["applicable"])
        self.assertFalse(f["debt"]["applicable"])           # 金融業槓桿不可比
        self.assertFalse(f["fcf"]["applicable"])            # cf_df None
        self.assertFalse(f["revenue"]["applicable"])        # rev_df None
        self.assertTrue(f["roe"]["applicable"])             # 用 IncomeAfterTax 算得 ROE
        self.assertIsNotNone(out["roe_value"])
        # max 只計可用因子（eps + roe = 2 因子 → max 4）
        self.assertEqual(out["max"], 4)

    def test_streak_bonus_rising(self):
        out = compute_fundamentals({
            "fs_df": make_fs(Q8), "bs_df": make_bs(40000, 20000, 60000),
            "cf_df": None, "rev_df": None, "industry_category": "半導體業",
        })
        # TTM 營收逐季走高 → streak_bonus 正
        self.assertGreater(out["streak_bonus"], 0)

    def test_empty_all_na(self):
        out = compute_fundamentals({"fs_df": None, "bs_df": None, "cf_df": None,
                                    "rev_df": None, "industry_category": None})
        self.assertEqual(out["max"], 0)
        self.assertIsNone(out["pct"])
        self.assertIsNone(out["roe_value"])
        self.assertFalse(any(v["applicable"] for v in out["factors"].values()))

    # ---------- P1 終審修復：#7 _ttm 連續性 ----------
    def test_ttm_none_on_quarter_gap(self):
        # 缺 2025Q2（EPS）→ keys 不連續，_ttm 應回 None，不得跳過缺季硬湊 4 筆
        q_missing = [q for q in Q8 if q["date"] != "2025-06-30"]
        fs = make_fs(q_missing)
        eps_series = _series(fs, "EPS")
        keys = sorted(eps_series.keys())
        self.assertIsNone(_ttm(eps_series, keys, 0))

    def test_eps_factor_na_on_quarter_gap(self):
        q_missing = [q for q in Q8 if q["date"] != "2025-06-30"]
        f = _eps_factor(make_fs(q_missing))
        self.assertFalse(f["applicable"])

    def test_compute_roe_none_on_quarter_gap(self):
        # 缺一季淨利 → TTM 不連續，ROE 不得硬湊出膨脹值（避免污染 PBR 估值）
        ni_missing = [q for q in Q8 if q["date"] != "2025-06-30"]
        fs = make_fs(ni_missing)
        bs = make_bs(equity=40000, liabilities=20000, total_assets=60000)
        self.assertIsNone(compute_roe(fs, bs))

    # ---------- P1 終審修復：#8 FCF 因子誠實化（OCF，未扣資本支出）----------
    def test_fcf_factor_display_name_and_caveat(self):
        f = _fcf_factor(make_cf([("2024-03-31", 1500), ("2024-06-30", 1600),
                                 ("2025-03-31", 1700), ("2025-06-30", 1800)]))
        self.assertTrue(f["applicable"])
        self.assertIn("營業現金流", f["value"])
        self.assertIn("OCF", f["value"])
        self.assertIn("未扣資本支出", f["value"])
        # key 名仍相容既有介面
        out = compute_fundamentals({
            "fs_df": None, "bs_df": None,
            "cf_df": make_cf([("2025-06-30", 100)]),
            "rev_df": None, "industry_category": None,
        })
        self.assertIn("fcf", out["factors"])

    # ---------- P1 終審修復：#9 虧轉盈評分 ----------
    def test_eps_factor_loss_to_profit_scores_high(self):
        rows = [
            {"date": "2024-03-31", "EPS": -3.0}, {"date": "2024-06-30", "EPS": -2.0},
            {"date": "2024-09-30", "EPS": -3.0}, {"date": "2024-12-31", "EPS": -2.0},
            {"date": "2025-03-31", "EPS": 1.0}, {"date": "2025-06-30", "EPS": 2.0},
            {"date": "2025-09-30", "EPS": 1.0}, {"date": "2025-12-31", "EPS": 2.0},
        ]
        f = _eps_factor(make_fs(rows))
        self.assertEqual(f["score"], 2)
        self.assertIn("由虧轉盈", f["value"])

    def test_eps_factor_loss_narrowing_scores_mid(self):
        rows = [
            {"date": "2024-03-31", "EPS": -5.0}, {"date": "2024-06-30", "EPS": -5.0},
            {"date": "2024-09-30", "EPS": -5.0}, {"date": "2024-12-31", "EPS": -5.0},
            {"date": "2025-03-31", "EPS": -3.0}, {"date": "2025-06-30", "EPS": -2.0},
            {"date": "2025-09-30", "EPS": -3.0}, {"date": "2025-12-31", "EPS": -2.0},
        ]
        f = _eps_factor(make_fs(rows))
        self.assertEqual(f["score"], 1)
        self.assertIn("虧損收斂", f["value"])

    def test_eps_factor_loss_widening_scores_zero(self):
        rows = [
            {"date": "2024-03-31", "EPS": -2.5}, {"date": "2024-06-30", "EPS": -2.5},
            {"date": "2024-09-30", "EPS": -2.5}, {"date": "2024-12-31", "EPS": -2.5},
            {"date": "2025-03-31", "EPS": -5.0}, {"date": "2025-06-30", "EPS": -5.0},
            {"date": "2025-09-30", "EPS": -5.0}, {"date": "2025-12-31", "EPS": -5.0},
        ]
        f = _eps_factor(make_fs(rows))
        self.assertEqual(f["score"], 0)
        self.assertIn("虧損擴大", f["value"])


if __name__ == "__main__":
    unittest.main()
