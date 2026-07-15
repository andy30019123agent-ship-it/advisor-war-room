"""T5：缺資料降級 + 純訊號抽取函式測試（純函式，不打真 API）。"""
import unittest

import pandas as pd

from warroom.analyze_tw import (
    technical, rev_signals_from_df, chip_signals_from_df,
)


def price_df(n):
    rows = []
    for i in range(n):
        c = 100.0 + (i % 5)
        rows.append({"date": f"2026-{(i // 28) % 12 + 1:02d}-{(i % 28) + 1:02d}",
                     "close": c, "max": c + 1, "min": c - 1, "Trading_Volume": 1000})
    return pd.DataFrame(rows)


class TestDegrade(unittest.TestCase):
    def test_technical_ma120_insufficient(self):
        # 只有 30 根 → MA120 應標「樣本不足」、不因此進空頭
        light, ev = technical(price_df(30))
        self.assertEqual(ev["MA120"], "樣本不足")

    def test_technical_full_sample(self):
        light, ev = technical(price_df(150))
        self.assertIsInstance(ev["MA120"], (int, float))

    def test_rev_signals(self):
        # 去年每月 100、今年前 4 月 90（YoY 負），且低於 6 月均
        months = [(2025, m, 100) for m in range(1, 13)] + \
                 [(2026, m, 90) for m in range(1, 5)]
        rev = pd.DataFrame([{"date": f"{y}-{m:02d}-01", "revenue": r,
                             "revenue_year": y, "revenue_month": m}
                            for (y, m, r) in months])
        sig = rev_signals_from_df(rev)
        self.assertTrue(sig["yoy_negative"])

    def test_chip_signals_sell_streak(self):
        # 連 3 日淨賣（buy<sell）
        rows = []
        for d in ("2026-07-10", "2026-07-11", "2026-07-14"):
            rows.append({"date": d, "buy": 100, "sell": 5000, "name": "Foreign_Investor"})
        chip = pd.DataFrame(rows)
        sig = chip_signals_from_df(chip)
        self.assertTrue(sig["sell_streak_ge3"])

    def test_signals_empty_safe(self):
        # 空表不 crash，回 False
        self.assertEqual(rev_signals_from_df(None)["yoy_negative"], False)
        self.assertEqual(chip_signals_from_df(pd.DataFrame())["sell_streak_ge3"], False)

    def test_chip_signals_ratio_gt_15pct_true(self):
        # 連 3 日各淨賣 1000 股：日均淨賣超 1000／vol20=5000 → 20% > 15% → True
        rows = []
        for d in ("2026-07-10", "2026-07-11", "2026-07-14"):
            rows.append({"date": d, "buy": 0, "sell": 1000, "name": "Foreign_Investor"})
        chip = pd.DataFrame(rows)
        sig = chip_signals_from_df(chip, vol20=5000)
        self.assertTrue(sig["sell_streak_ge3"])
        self.assertTrue(sig["ratio_gt_15pct"])

    def test_chip_signals_ratio_le_15pct_false(self):
        # 同樣連 3 日各淨賣 1000 股，但 vol20=10000 → 日均淨賣超佔比 10% < 15% → False
        rows = []
        for d in ("2026-07-10", "2026-07-11", "2026-07-14"):
            rows.append({"date": d, "buy": 0, "sell": 1000, "name": "Foreign_Investor"})
        chip = pd.DataFrame(rows)
        sig = chip_signals_from_df(chip, vol20=10000)
        self.assertTrue(sig["sell_streak_ge3"])
        self.assertFalse(sig["ratio_gt_15pct"])

    def test_chip_signals_vol20_missing_false(self):
        # 連 3 日同向賣，但 vol20 缺（None）→ 資料缺不誤報，ratio 維持 False
        rows = []
        for d in ("2026-07-10", "2026-07-11", "2026-07-14"):
            rows.append({"date": d, "buy": 0, "sell": 1000, "name": "Foreign_Investor"})
        chip = pd.DataFrame(rows)
        sig = chip_signals_from_df(chip, vol20=None)
        self.assertTrue(sig["sell_streak_ge3"])
        self.assertFalse(sig["ratio_gt_15pct"])


if __name__ == "__main__":
    unittest.main()
