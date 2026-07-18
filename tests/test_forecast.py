"""T：機率扇形圖預估走勢 warroom/forecast.py 測試（規格見 docs/contracts/
data-contract-v1.md「v1.2 增補」）。純函式＋合成 price DataFrame，離線可測。"""
import json
import os
import unittest

import numpy as np
import pandas as pd

from warroom.forecast import build_forecast, MIN_BARS

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOCK_SCHEMA_PATH = os.path.join(REPO_ROOT, "schema", "stock.schema.json")


def make_price(n=260, base=100.0, seed=42):
    """合成日線：帶隨機報酬的價格序列（不是純直線，才有真實波動度可算）。
    date 用連續遞增字串（ISO 可字典序排序），貼近實際 price_df 的日期欄位。"""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0, 0.015, size=n)
    closes = base * np.exp(np.cumsum(rets))
    dates = pd.bdate_range("2024-01-01", periods=n).strftime("%Y-%m-%d")
    rows = [{"date": d, "close": float(c), "Trading_Volume": 1000 + i}
            for i, (d, c) in enumerate(zip(dates, closes))]
    return pd.DataFrame(rows)


VALUATION = {"fair_value": {"bear": 90.0, "base": 110.0, "bull": 130.0}}


class TestBuildForecast(unittest.TestCase):
    def test_insufficient_sample_returns_none(self):
        df = make_price(n=MIN_BARS - 1)
        out = build_forecast(df, VALUATION, "2026-07-18", "9999")
        self.assertIsNone(out)

    def test_none_price_df_returns_none(self):
        self.assertIsNone(build_forecast(None, VALUATION, "2026-07-18", "9999"))

    def test_determinism_same_seed_same_output(self):
        df = make_price()
        out1 = build_forecast(df, VALUATION, "2026-07-18", "2330")
        out2 = build_forecast(df, VALUATION, "2026-07-18", "2330")
        self.assertEqual(out1, out2)

    def test_different_data_date_changes_seed_and_output(self):
        df = make_price()
        out1 = build_forecast(df, VALUATION, "2026-07-18", "2330")
        out2 = build_forecast(df, VALUATION, "2026-07-19", "2330")
        self.assertNotEqual(out1["bands"], out2["bands"])

    def test_different_stock_id_changes_output(self):
        df = make_price()
        out1 = build_forecast(df, VALUATION, "2026-07-18", "2330")
        out2 = build_forecast(df, VALUATION, "2026-07-18", "2454")
        self.assertNotEqual(out1["bands"], out2["bands"])

    def test_bands_monotonic_within_each_day(self):
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        for row in out["bands"]:
            self.assertLessEqual(row["p10"], row["p25"])
            self.assertLessEqual(row["p25"], row["p50"])
            self.assertLessEqual(row["p50"], row["p75"])
            self.assertLessEqual(row["p75"], row["p90"])

    def test_d0_all_equal_current_price(self):
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        d0 = out["bands"][0]
        self.assertEqual(d0["d"], 0)
        last_close = round(float(df.sort_values("date")["close"].iloc[-1]), 2)
        for k in ("p10", "p25", "p50", "p75", "p90"):
            self.assertEqual(d0[k], last_close)

    def test_bands_cover_0_to_63_every_3_days(self):
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        days = [row["d"] for row in out["bands"]]
        self.assertEqual(days, list(range(0, 64, 3)))
        self.assertEqual(days[-1], 63)

    def test_vol_annualized_reasonable_range(self):
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        self.assertGreater(out["vol_annualized"], 0)
        self.assertLess(out["vol_annualized"], 2)

    def test_scenarios_reuse_valuation_fair_value_not_recomputed(self):
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        self.assertEqual(out["scenarios"], {"bear": 90.0, "base": 110.0, "bull": 130.0})

    def test_scenarios_null_when_valuation_missing(self):
        df = make_price()
        out = build_forecast(df, None, "2026-07-18", "2330")
        self.assertEqual(out["scenarios"], {"bear": None, "base": None, "bull": None})

    def test_prob_range_70_is_p15_p85_of_horizon(self):
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        lo, hi = out["prob_range_70"]
        self.assertLess(lo, hi)
        horizon = out["bands"][-1]
        # p15~p85 必落在該日 p10~p90 之內（更窄的機率帶）
        self.assertGreaterEqual(lo, horizon["p10"])
        self.assertLessEqual(hi, horizon["p90"])

    def test_method_and_shape_fields(self):
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        self.assertEqual(out["method"], "monte_carlo_gbm")
        self.assertEqual(out["horizon_days"], 63)
        self.assertEqual(out["n_paths"], 2000)
        self.assertEqual(out["as_of"], "2026-07-18")
        self.assertIn("突發事件", out["disclaimer"])

    def test_forecast_matches_schema(self):
        with open(STOCK_SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
        import jsonschema
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        # 對照 schema 內 forecast 子結構（非整份 stock.schema.json，這裡只驗 forecast 分支）
        forecast_schema = schema["properties"]["forecast"]
        jsonschema.validate(out, forecast_schema)
        jsonschema.validate(None, forecast_schema)  # 樣本不足時的 null 也要合法


if __name__ == "__main__":
    unittest.main()
