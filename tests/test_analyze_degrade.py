"""T5：缺資料降級 + 純訊號抽取函式測試（純函式，不打真 API）。"""
import unittest

import pandas as pd

from warroom.analyze_tw import (
    technical, rev_signals_from_df, chip_signals_from_df, fundamental, prior_n_high_low,
    _normalize_news, _parse_news_date,
)


def make_val(n=10):
    return pd.DataFrame([{"date": f"2026-{(i % 12) + 1:02d}-01", "PER": 15.0,
                         "dividend_yield": 3.0} for i in range(n)])


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

    def test_fundamental_yoy_none_when_prior_year_base_zero(self):
        # 去年同月營收為 0（無效基期）→ YoY 回 None，不得產生 inf
        months = [(2025, m, 0 if m == 6 else 100) for m in range(1, 13)] + [(2026, 6, 150)]
        rev = pd.DataFrame([{"date": f"{y}-{m:02d}-01", "revenue": r,
                             "revenue_year": y, "revenue_month": m}
                            for (y, m, r) in months])
        light, ev, flags = fundamental(rev, make_val())
        self.assertEqual(ev["營收YoY"], "去年同月基期無效")
        self.assertTrue(flags["revenue_yoy_base_invalid"])

    def test_fundamental_yoy_none_when_prior_year_base_negative(self):
        # 去年同月營收為負（財報異常值）→ 同樣視為無效基期，不得產生負值或 inf
        months = [(2025, m, -50 if m == 6 else 100) for m in range(1, 13)] + [(2026, 6, 150)]
        rev = pd.DataFrame([{"date": f"{y}-{m:02d}-01", "revenue": r,
                             "revenue_year": y, "revenue_month": m}
                            for (y, m, r) in months])
        light, ev, flags = fundamental(rev, make_val())
        self.assertEqual(ev["營收YoY"], "去年同月基期無效")
        self.assertTrue(flags["revenue_yoy_base_invalid"])

    def test_fundamental_yoy_normal_when_base_valid(self):
        months = [(2025, m, 100) for m in range(1, 13)] + [(2026, m, 130) for m in range(1, 7)]
        rev = pd.DataFrame([{"date": f"{y}-{m:02d}-01", "revenue": r,
                             "revenue_year": y, "revenue_month": m}
                            for (y, m, r) in months])
        light, ev, flags = fundamental(rev, make_val())
        self.assertEqual(ev["營收YoY"], "+30.0%")
        self.assertFalse(flags["revenue_yoy_base_invalid"])

    def test_prior_n_high_low_excludes_today(self):
        # 前 20 天平盤 100，最後一天（今日）飆高到 200 → 前20完整交易日的高低不應含今日
        rows = []
        for i in range(21):
            c = 200.0 if i == 20 else 100.0
            rows.append({"date": f"2026-01-{i+1:02d}", "max": c, "min": c})
        df = pd.DataFrame(rows)
        low, high = prior_n_high_low(df, "max", "min", 20)
        self.assertEqual(high, 100.0)  # 不含今日的 200
        self.assertEqual(low, 100.0)

    def test_prior_n_high_low_insufficient_data(self):
        df = pd.DataFrame([{"date": "2026-01-01", "max": 100.0, "min": 90.0}])
        low, high = prior_n_high_low(df, "max", "min", 20)
        self.assertIsNone(low)
        self.assertIsNone(high)

    def test_chip_signals_vol20_missing_false(self):
        # 連 3 日同向賣，但 vol20 缺（None）→ 資料缺不誤報，ratio 維持 False
        rows = []
        for d in ("2026-07-10", "2026-07-11", "2026-07-14"):
            rows.append({"date": d, "buy": 0, "sell": 1000, "name": "Foreign_Investor"})
        chip = pd.DataFrame(rows)
        sig = chip_signals_from_df(chip, vol20=None)
        self.assertTrue(sig["sell_streak_ge3"])
        self.assertFalse(sig["ratio_gt_15pct"])


class TestNewsNormalization(unittest.TestCase):
    """规格條 8：evidence.news 要正規化成契約 {title, source, url, published_at}（ISO 日期）。"""

    def test_normalize_gdelt_shape(self):
        raw = [{"title": "台積電法說會展望佳", "url": "https://x.example/a",
               "date": "20260716T083000Z", "src": "example.com"}]
        out = _normalize_news(raw)
        self.assertEqual(out, [{"title": "台積電法說會展望佳", "source": "example.com",
                                "url": "https://x.example/a",
                                "published_at": "2026-07-16T08:30:00+00:00"}])

    def test_normalize_google_rss_shape(self):
        raw = [{"title": "外資調升目標價", "url": "https://x.example/b",
               "date": "Thu, 16 Jul 2026 04:00:00 GMT", "src": "Google News"}]
        out = _normalize_news(raw)
        self.assertEqual(out[0]["source"], "Google News")
        self.assertEqual(out[0]["published_at"], "2026-07-16T04:00:00+00:00")

    def test_normalize_unparseable_date_gives_null_not_string(self):
        raw = [{"title": "某新聞", "url": "u", "date": "不是日期", "src": "s"}]
        out = _normalize_news(raw)
        self.assertIsNone(out[0]["published_at"])

    def test_normalize_empty_safe(self):
        self.assertEqual(_normalize_news([]), [])
        self.assertEqual(_normalize_news(None), [])

    def test_parse_news_date_none_on_empty(self):
        self.assertIsNone(_parse_news_date(None))
        self.assertIsNone(_parse_news_date(""))


if __name__ == "__main__":
    unittest.main()
