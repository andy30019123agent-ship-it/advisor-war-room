"""T：機率扇形圖預估走勢 2.0 warroom/forecast.py 測試（規格見 docs/contracts/
data-contract-v1.md「v1.2 增補」＋「v1.3 增補」）。純函式＋合成 price DataFrame，離線可測。"""
import json
import os
import tempfile
import unittest

import numpy as np
import pandas as pd

from warroom.forecast import HORIZONS, MIN_BARS, WEEK_DAYS, build_forecast

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


class TestBuildForecastBasics(unittest.TestCase):
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
        self.assertNotEqual(out1["horizons"]["m3"]["bands"], out2["horizons"]["m3"]["bands"])

    def test_different_stock_id_changes_output(self):
        df = make_price()
        out1 = build_forecast(df, VALUATION, "2026-07-18", "2330")
        out2 = build_forecast(df, VALUATION, "2026-07-18", "2454")
        self.assertNotEqual(out1["horizons"]["m3"]["bands"], out2["horizons"]["m3"]["bands"])

    def test_method_and_shape_fields(self):
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        self.assertEqual(out["method"], "monte_carlo_gbm")
        self.assertEqual(out["n_paths"], 2000)
        self.assertEqual(out["as_of"], "2026-07-18")
        self.assertIn("突發事件", out["disclaimer"])

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

    def test_scenarios_null_when_valuation_has_warning(self):
        # 修復 8／R1：valuation.warning 非 null（Base 偏離現價過大、可能低估）時，
        # forecast.scenarios 不得裸奔悲觀估值，一律回 null（bear/base/bull 全 None）。
        df = make_price()
        val = {"fair_value": {"bear": 90.0, "base": 110.0, "bull": 130.0},
               "warning": "Base 1297.9 與現價偏離 61%，可能低估，不作為減碼依據"}
        out = build_forecast(df, val, "2026-07-18", "2330")
        self.assertEqual(out["scenarios"], {"bear": None, "base": None, "bull": None})

    def test_disclaimer_mentions_zero_drift(self):
        # 修復 16：disclaimer 標明「零漂移」波動模擬（與週報「下週 70% 區間」短註同語意）。
        out = build_forecast(make_price(), VALUATION, "2026-07-18", "2330")
        self.assertIn("零漂移", out["disclaimer"])


# ---------- horizons：m1/m3/m6 三段結構 ----------
class TestHorizons(unittest.TestCase):
    def test_horizons_have_correct_days(self):
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        self.assertEqual(set(out["horizons"]), {"m1", "m3", "m6"})
        self.assertEqual(out["horizons"]["m1"]["days"], 21)
        self.assertEqual(out["horizons"]["m3"]["days"], 63)
        self.assertEqual(out["horizons"]["m6"]["days"], 126)

    def test_bands_cover_0_to_days_every_3_days(self):
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        for key, days in HORIZONS.items():
            band_days = [row["d"] for row in out["horizons"][key]["bands"]]
            self.assertEqual(band_days, list(range(0, days + 1, 3)), key)
            self.assertEqual(band_days[-1], days)

    def test_d0_all_equal_current_price_for_each_horizon(self):
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        last_close = round(float(df.sort_values("date")["close"].iloc[-1]), 2)
        for key in HORIZONS:
            d0 = out["horizons"][key]["bands"][0]
            self.assertEqual(d0["d"], 0)
            for k in ("p10", "p25", "p50", "p75", "p90"):
                self.assertEqual(d0[k], last_close, key)

    def test_bands_monotonic_within_each_day_for_each_horizon(self):
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        for key in HORIZONS:
            for row in out["horizons"][key]["bands"]:
                self.assertLessEqual(row["p10"], row["p25"], key)
                self.assertLessEqual(row["p25"], row["p50"], key)
                self.assertLessEqual(row["p50"], row["p75"], key)
                self.assertLessEqual(row["p75"], row["p90"], key)

    def test_prob_range_70_is_p15_p85_of_horizon_endpoint(self):
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        for key in HORIZONS:
            lo, hi = out["horizons"][key]["prob_range_70"]
            self.assertLess(lo, hi, key)
            endpoint = out["horizons"][key]["bands"][-1]
            self.assertGreaterEqual(lo, endpoint["p10"], key)
            self.assertLessEqual(hi, endpoint["p90"], key)

    def test_prob_range_70_widens_across_horizons_m1_lt_m3_lt_m6(self):
        """GBM 變異數隨天數增加，同一次模擬下 m1<m3<m6 的 70% 區間寬度應遞增
        （多 horizon 單調性；n=2000 條路徑降噪，這個關係應穩定成立）。"""
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        widths = {k: out["horizons"][k]["prob_range_70"][1] - out["horizons"][k]["prob_range_70"][0]
                 for k in HORIZONS}
        self.assertLess(widths["m1"], widths["m3"])
        self.assertLess(widths["m3"], widths["m6"])


# ---------- week_range_70：d=5 的 p15~p85 ----------
class TestWeekRange(unittest.TestCase):
    def test_week_range_70_narrower_than_m1(self):
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        wlo, whi = out["week_range_70"]
        self.assertLess(wlo, whi)
        m1lo, m1hi = out["horizons"]["m1"]["prob_range_70"]
        # d=5 比 m1 的 d=21 短，變異數更小，區間應更窄（或至少不寬於）
        self.assertLessEqual(whi - wlo, m1hi - m1lo)

    def test_week_days_constant_is_5(self):
        self.assertEqual(WEEK_DAYS, 5)


# ---------- history：過去 63 交易日實際收盤，每 3 日取樣＋d=0 ----------
class TestHistory(unittest.TestCase):
    def test_history_length_and_step(self):
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        days = [row["d"] for row in out["history"]]
        self.assertEqual(days, list(range(-63, 1, 3)))

    def test_history_d0_equals_current_price(self):
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        last_close = round(float(df.sort_values("date")["close"].iloc[-1]), 2)
        self.assertEqual(out["history"][-1]["d"], 0)
        self.assertEqual(out["history"][-1]["close"], last_close)

    def test_history_uses_actual_closes_not_simulated(self):
        df = make_price()
        sorted_closes = df.sort_values("date")["close"].reset_index(drop=True)
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        n = len(sorted_closes)
        for row in out["history"]:
            idx = n - 1 + row["d"]
            self.assertEqual(row["close"], round(float(sorted_closes.iloc[idx]), 2))


# ---------- event_markers：evidence.events ＋ 法說會行事曆合併換算 d ----------
class TestEventMarkers(unittest.TestCase):
    def test_events_from_evidence_converted_to_trading_days(self):
        df = make_price()
        # 曆日 14 天 * 5/7 = 10（整數，四捨五入即精確值）
        events = [{"date": "2026-08-01", "label": "法說會"}]
        out = build_forecast(df, VALUATION, "2026-07-18", "2330", events=events, calendar_path=None)
        self.assertEqual(out["event_markers"], [{"d": 10, "date": "2026-08-01", "label": "法說會"}])

    def test_events_outside_horizon_excluded(self):
        df = make_price()
        # 曆日 200 天遠超 126 交易日 horizon（200*5/7≈143>126）
        events = [{"date": "2027-02-04", "label": "法說會"}]
        out = build_forecast(df, VALUATION, "2026-07-18", "2330", events=events, calendar_path=None)
        self.assertEqual(out["event_markers"], [])

    def test_events_before_as_of_excluded(self):
        df = make_price()
        events = [{"date": "2026-07-01", "label": "已過去的事件"}]
        out = build_forecast(df, VALUATION, "2026-07-18", "2330", events=events, calendar_path=None)
        self.assertEqual(out["event_markers"], [])

    def test_events_none_and_missing_calendar_file_gives_empty_list(self):
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330", events=None,
                             calendar_path="/no/such/calendar.json")
        self.assertEqual(out["event_markers"], [])

    def test_events_dedup_same_date_and_label(self):
        df = make_price()
        events = [{"date": "2026-08-01", "label": "法說會"}, {"date": "2026-08-01", "label": "法說會"}]
        out = build_forecast(df, VALUATION, "2026-07-18", "2330", events=events, calendar_path=None)
        self.assertEqual(len(out["event_markers"]), 1)

    def test_events_from_calendar_file_filtered_by_stock_id(self):
        with tempfile.TemporaryDirectory() as d:
            cal_path = os.path.join(d, "latest.json")
            with open(cal_path, "w", encoding="utf-8") as f:
                json.dump({"events": [
                    {"id": "2330", "date": "2026-08-05", "type": "法說會"},
                    {"id": "9999", "date": "2026-08-05", "type": "法說會"},
                ]}, f)
            df = make_price()
            out = build_forecast(df, VALUATION, "2026-07-18", "2330", events=None, calendar_path=cal_path)
            self.assertEqual(len(out["event_markers"]), 1)
            self.assertEqual(out["event_markers"][0]["label"], "法說會")

    def test_events_sorted_by_d(self):
        df = make_price()
        events = [{"date": "2026-08-15", "label": "B"}, {"date": "2026-08-01", "label": "A"}]
        out = build_forecast(df, VALUATION, "2026-07-18", "2330", events=events, calendar_path=None)
        self.assertEqual([e["label"] for e in out["event_markers"]], ["A", "B"])


# ---------- accuracy：build_forecast 本身只給預設值 ----------
class TestAccuracyDefault(unittest.TestCase):
    def test_accuracy_default_shape(self):
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        self.assertEqual(out["accuracy"]["n_evaluated"], 0)
        self.assertIsNone(out["accuracy"]["hit_rate_70"])
        self.assertTrue(out["accuracy"]["note"])


# ---------- schema ----------
class TestForecastMatchesSchema(unittest.TestCase):
    def test_forecast_matches_schema(self):
        with open(STOCK_SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
        import jsonschema
        df = make_price()
        out = build_forecast(df, VALUATION, "2026-07-18", "2330")
        resolver = jsonschema.RefResolver.from_schema(schema)
        forecast_schema = schema["properties"]["forecast"]
        jsonschema.validate(out, forecast_schema, resolver=resolver)
        jsonschema.validate(None, forecast_schema, resolver=resolver)  # 樣本不足時的 null 也要合法


if __name__ == "__main__":
    unittest.main()
