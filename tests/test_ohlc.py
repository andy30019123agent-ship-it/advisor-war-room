"""K 線疊層 warroom/analyze_tw.build_ohlc 測試（規格：docs/contracts/data-contract-v1.md
「v1.7 增補」）。純函式＋合成 price DataFrame（open/max/min/close/Trading_Volume，同
FinMind taiwan_stock_daily 欄名），離線可測。"""
import json
import os
import unittest

import jsonschema
import pandas as pd

from warroom.analyze_tw import build_ohlc

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOCK_SCHEMA = json.load(open(os.path.join(REPO_ROOT, "schema", "stock.schema.json"), encoding="utf-8"))


def _validate(instance):
    jsonschema.validate(instance, STOCK_SCHEMA["properties"]["ohlc"])


def make_price(n, base=100.0):
    """合成日線：o/h/l/c 皆由 base 位移出，v 遞增，date 連續遞增字串。"""
    dates = pd.bdate_range("2024-01-01", periods=n).strftime("%Y-%m-%d")
    rows = []
    for i, d in enumerate(dates):
        c = base + i * 0.5
        rows.append({"date": d, "open": c - 1, "max": c + 2, "min": c - 2,
                     "close": c, "Trading_Volume": 1000 + i * 10})
    return pd.DataFrame(rows)


class TestBuildOhlcBasics(unittest.TestCase):
    def test_60_rows_gives_last_60(self):
        df = make_price(100)
        out = build_ohlc(df)
        self.assertEqual(len(out), 60)
        # 取最後 60 根，日期應是原始序列的尾段
        full_dates = df.sort_values("date")["date"].tolist()
        self.assertEqual([r["d"] for r in out], full_dates[-60:])

    def test_fields_and_rounding(self):
        df = make_price(60)
        out = build_ohlc(df)
        row = out[-1]
        self.assertEqual(set(row.keys()), {"d", "o", "h", "l", "c", "v"})
        self.assertIsInstance(row["v"], int)
        self.assertIsInstance(row["o"], float)
        self.assertIsInstance(row["d"], str)

    def test_insufficient_data_below_20_returns_none(self):
        df = make_price(19)
        self.assertIsNone(build_ohlc(df))

    def test_exactly_20_rows_returns_actual_count(self):
        df = make_price(20)
        out = build_ohlc(df)
        self.assertEqual(len(out), 20)

    def test_between_20_and_60_returns_actual_count_not_padded(self):
        df = make_price(35)
        out = build_ohlc(df)
        self.assertEqual(len(out), 35)  # 不硬湊 60，照實際根數給

    def test_none_price_df_returns_none(self):
        self.assertIsNone(build_ohlc(None))

    def test_empty_price_df_returns_none(self):
        self.assertIsNone(build_ohlc(pd.DataFrame()))

    def test_missing_ohlc_columns_returns_none(self):
        df = pd.DataFrame({"date": ["2026-07-01", "2026-07-02"], "close": [100.0, 101.0]})
        self.assertIsNone(build_ohlc(df))

    def test_unsorted_input_still_orders_by_date(self):
        df = make_price(25).sample(frac=1, random_state=1).reset_index(drop=True)
        out = build_ohlc(df)
        ds = [r["d"] for r in out]
        self.assertEqual(ds, sorted(ds))

    def test_nan_row_is_skipped_not_crashed(self):
        df = make_price(25)
        df.loc[df.index[-1], "close"] = float("nan")
        out = build_ohlc(df)
        # 最後一根缺值被跳過，仍回傳其餘有效根（24 根，未低於 20 門檻）
        self.assertEqual(len(out), 24)

    def test_schema_valid_for_ok_case(self):
        out = build_ohlc(make_price(60))
        _validate(out)

    def test_schema_valid_for_none_case(self):
        _validate(None)


if __name__ == "__main__":
    unittest.main()
