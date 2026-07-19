"""首頁大盤作戰區 warroom/market_battle.py 測試（規格：docs/contracts/data-contract-v1.md
「v1.8 增補」）。純函式＋合成 TAIEX/外資 DataFrame，離線可測：技術/籌碼燈映射、關鍵位
間距去重與 ≤3 上限、大盤劇本機率查表重用、bull 曝險語言 gate 一致性、外資連買賣天數／
單位換算、GBM 一個月區間、graceful null 全覆蓋。"""
import json
import os
import unittest

import jsonschema
import numpy as np
import pandas as pd

from warroom.forecast import MIN_BARS as FORECAST_MIN_BARS
from warroom.market_battle import (
    KEY_LEVEL_MIN_SPACING_PCT,
    MIN_OHLC_BARS,
    _key_levels_block,
    _labeled_levels,
    _resistances,
    _supports,
    _technical_color,
    _vix_sox_bias,
    build_foreign_streak,
    build_forecast_range_m1,
    build_market_battle,
    build_market_scenarios,
    build_taiex_ohlc,
    build_us_overnight,
    load_leading_sectors,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY_SCHEMA = json.load(open(os.path.join(REPO_ROOT, "schema", "daily.schema.json"), encoding="utf-8"))
_RESOLVER = jsonschema.RefResolver.from_schema(DAILY_SCHEMA)


def _validate_battle(instance):
    jsonschema.validate(instance, DAILY_SCHEMA["properties"]["market_battle"], resolver=_RESOLVER)


def make_taiex_df(closes, start="2024-01-01"):
    """合成 TAIEX 日線：欄位對映 FinMind taiwan_stock_daily（open/max/min/close）。
    high/low 用 close ±0.2% 合成，不影響 MA/近端高低點的結構性測試（只需要 close 精確
    可控）。"""
    n = len(closes)
    dates = pd.bdate_range(start, periods=n).strftime("%Y-%m-%d")
    rows = [{"date": d, "open": c, "max": c * 1.002, "min": c * 0.998, "close": c}
            for d, c in zip(dates, closes)]
    return pd.DataFrame(rows)


def make_random_taiex_df(n=260, base=20000.0, seed=7):
    rng = np.random.default_rng(seed)
    rets = rng.normal(0, 0.008, size=n)
    closes = base * np.exp(np.cumsum(rets))
    dates = pd.bdate_range("2024-01-01", periods=n).strftime("%Y-%m-%d")
    rows = [{"date": d, "open": float(c) * 0.999, "max": float(c) * 1.004,
             "min": float(c) * 0.996, "close": float(c)}
            for d, c in zip(dates, closes)]
    return pd.DataFrame(rows)


def make_foreign_df(nets_yi, start="2026-07-01"):
    """合成全市場外資買賣超（單位元）：nets_yi 為每日淨額（億元），buy/sell 兩欄合成出
    對應淨額，覆蓋單位換算（/1e8）測試。"""
    n = len(nets_yi)
    dates = pd.bdate_range(start, periods=n).strftime("%Y-%m-%d")
    rows = []
    for d, net in zip(dates, nets_yi):
        net_yuan = net * 1e8
        if net_yuan >= 0:
            buy, sell = net_yuan, 0.0
        else:
            buy, sell = 0.0, -net_yuan
        rows.append({"date": d, "name": "Foreign_Investor", "buy": buy, "sell": sell})
    return pd.DataFrame(rows)


# ---------- 技術燈映射 ----------
class TestTechnicalColor(unittest.TestCase):
    def test_bull_alignment_green(self):
        self.assertEqual(_technical_color(110, 105, 100, 95), "green")

    def test_broken_monthly_quarterly_red(self):
        self.assertEqual(_technical_color(90, 95, 100, 105), "red")

    def test_choppy_yellow(self):
        self.assertEqual(_technical_color(100, 101, 99, 102), "yellow")

    def test_missing_price_defaults_yellow(self):
        self.assertEqual(_technical_color(None, 105, 100, 95), "yellow")

    def test_missing_ma_defaults_yellow_not_crash(self):
        self.assertEqual(_technical_color(100, None, None, None), "yellow")

    def test_price_below_both_lines_is_red_even_if_ma20_above_ma60(self):
        # 迴歸測試（2026-07-19 實跑觀察）：急跌剛發生時均線常來不及死叉（MA20 仍 > MA60），
        # 但現價已經同時跌破兩條線——這仍該判 red（「跌破月季線」看的是現價，不是均線
        # 彼此的排列順序），不能照搬個股版 analyze_tw.technical() 的死叉排列判斷。
        self.assertEqual(_technical_color(42671.0, 45850.9, 43525.1, 38480.0), "red")


# ---------- 大盤傾向修正項（VIX/SOX） ----------
class TestVixSoxBias(unittest.TestCase):
    def test_vix_extreme_up_is_bear(self):
        self.assertEqual(_vix_sox_bias(8.5, 2.0), "bear")

    def test_vix_extreme_down_is_bull(self):
        self.assertEqual(_vix_sox_bias(-9.0, -2.0), "bull")

    def test_sox_direction_fallback_when_vix_normal(self):
        self.assertEqual(_vix_sox_bias(1.0, -1.5), "bear")
        self.assertEqual(_vix_sox_bias(1.0, 1.5), "bull")

    def test_all_missing_neutral(self):
        self.assertEqual(_vix_sox_bias(None, None), "neutral")


# ---------- 外資連買賣：方向／天數／單位換算 ----------
class TestForeignStreak(unittest.TestCase):
    def test_buy_streak_direction_and_days(self):
        out = build_foreign_streak(make_foreign_df([10, 20, 15, 5, 30]))
        self.assertEqual(out["direction"], "buy")
        self.assertEqual(out["days"], 5)

    def test_sell_streak_direction_and_days(self):
        out = build_foreign_streak(make_foreign_df([10, -5, -8, -3, -12, -20, -1]))
        self.assertEqual(out["direction"], "sell")
        self.assertEqual(out["days"], 6)

    def test_latest_yi_unit_conversion_元_to_億元(self):
        out = build_foreign_streak(make_foreign_df([12.3, -519.0]))
        self.assertEqual(out["latest_yi"], -519.0)

    def test_streak_breaks_on_sign_change(self):
        out = build_foreign_streak(make_foreign_df([-5, -5, 8]))
        self.assertEqual(out["direction"], "buy")
        self.assertEqual(out["days"], 1)

    def test_streak_fills_window_marks_days_capped(self):
        # 20 天資料、window=15（FOREIGN_STREAK_WINDOW）全部同向買超 → streak 吃滿整個
        # window，代表連續天數可能更早開始只是被截斷看不到，需標 days_capped（2026-07-19
        # 修復：window 10→15＋此旗標，讓前端能顯示「15+ 日」而非誤植精確值）。
        out = build_foreign_streak(make_foreign_df([10] * 20))
        self.assertEqual(out["days"], 15)
        self.assertTrue(out.get("days_capped"))

    def test_streak_within_window_not_capped(self):
        # streak 天數 < 可用天數（3 天同向後翻轉）→ 不該有 days_capped 這個鍵。
        out = build_foreign_streak(make_foreign_df([-8, -5, 5, 5, 5]))
        self.assertEqual(out["days"], 3)
        self.assertNotIn("days_capped", out)

    def test_no_foreign_rows_returns_none(self):
        df = pd.DataFrame([{"date": "2026-07-01", "name": "Investment_Trust",
                             "buy": 100.0, "sell": 0.0}])
        self.assertIsNone(build_foreign_streak(df))

    def test_none_or_empty_df_returns_none(self):
        self.assertIsNone(build_foreign_streak(None))
        self.assertIsNone(build_foreign_streak(pd.DataFrame()))


# ---------- 關鍵位間距去重（≥1.5%）與 ≤3 上限 ----------
class TestKeyLevelsDedupe(unittest.TestCase):
    def test_levels_within_1_5_pct_collapse_to_nearest(self):
        # 98.5 與 98.0 相距 0.51%（< 1.5%），應只留離現價(100)較近的 98.5。
        levels = [("MA20", 98.5), ("近20日低", 98.0)]
        out = _supports(levels, 100.0)
        self.assertEqual(out, [("MA20", 98.5)])

    def test_levels_beyond_1_5_pct_both_kept(self):
        # 98.5 與 96.0 相距 2.6%（>= 1.5%），兩個都該留。
        levels = [("MA20", 98.5), ("MA60", 96.0)]
        out = _supports(levels, 100.0)
        self.assertEqual([v for _, v in out], [98.5, 96.0])

    def test_resistances_capped_at_3(self):
        levels = [("MA20", 102.0), ("MA60", 105.0), ("MA120", 108.0),
                  ("近60日高", 111.0)]  # 彼此間距皆 ~2.8~3%，都不會被去重
        resistances = _resistances(levels, 100.0)
        block = _key_levels_block([], resistances)
        self.assertEqual(len(block["resistances"]), 3)
        self.assertEqual(block["resistances"], [102.0, 105.0, 108.0])


# ---------- 大盤劇本：機率查表重用＋一致性 ----------
BATTLE_KW = dict(
    current_price=100.0, low20=90.0, high60=110.0,
    ma20=98.0, ma60=95.0, ma120=92.0,
    technical_color="green", chips_color="green", chips_streak=0,
    vix_chg=1.0, sox_chg=0.5, market_new_position="可正常布局",
    is_bearish_arrangement=False,
)


def _battle_kw(**overrides):
    kw = dict(BATTLE_KW)
    kw.update(overrides)
    return kw


class TestScenarioProbTableReuse(unittest.TestCase):
    def test_gg_matches_short_scenarios_prob_table(self):
        # 技術綠×籌碼綠、且本測試的修正項輸入皆不觸發（vix/sox 中性、未破 MA60、未破
        # 60 日高、chips_streak=0），機率應等於 short_scenarios._PROB_TABLE["gg"]=(50,20,30)。
        out = build_market_scenarios(**_battle_kw(vix_chg=None, sox_chg=None))
        probs = {sc["id"]: sc["probability_pct"] for sc in out["scenarios"]}
        self.assertEqual(probs, {"base": 50, "risk": 20, "bull": 30})

    def test_probabilities_sum_to_100(self):
        for t in ("green", "yellow", "red"):
            for c in ("green", "yellow", "red"):
                out = build_market_scenarios(**_battle_kw(technical_color=t, chips_color=c))
                total = sum(sc["probability_pct"] for sc in out["scenarios"])
                self.assertEqual(total, 100, f"{t}x{c}")

    def test_scenarios_ordered_by_probability_descending(self):
        out = build_market_scenarios(**_battle_kw(technical_color="red", chips_color="red"))
        probs = [sc["probability_pct"] for sc in out["scenarios"]]
        self.assertEqual(probs, sorted(probs, reverse=True))


class TestGateConsistency(unittest.TestCase):
    def _bull(self, out):
        return next(sc for sc in out["scenarios"] if sc["id"] == "bull")

    def test_forbidden_new_position_excludes_add_back_wording(self):
        out = build_market_scenarios(**_battle_kw(market_new_position="禁止新增部位"))
        bull = self._bull(out)
        self.assertNotIn("回補試單", bull["action"]["text"])
        self.assertEqual(bull["action"]["stance"], "wait")

    def test_normal_deployment_allows_add_back_wording(self):
        out = build_market_scenarios(**_battle_kw(market_new_position="可正常布局"))
        bull = self._bull(out)
        self.assertIn("可回補試單", bull["action"]["text"])

    def test_trial_only_allows_add_back_wording_small_sized(self):
        out = build_market_scenarios(**_battle_kw(market_new_position="僅限試單"))
        bull = self._bull(out)
        self.assertIn("可回補試單", bull["action"]["text"])
        self.assertEqual(bull["action"]["stance"], "small_entry")

    def test_action_text_uses_exposure_language_not_position_language(self):
        out = build_market_scenarios(**_battle_kw())
        base = next(sc for sc in out["scenarios"] if sc["id"] == "base")
        risk = next(sc for sc in out["scenarios"] if sc["id"] == "risk")
        self.assertIn("維持防禦", base["action"]["text"])
        self.assertIn("降曝險", risk["action"]["text"])
        # 不該出現個股式持股/部位語言（例如「續抱」「試單10萬」等字樣不會被這裡產生）。
        for sc in out["scenarios"]:
            self.assertNotIn("續抱", sc["action"]["text"])


# ---------- 紅線：insufficient_data ----------
class TestScenarioRedLines(unittest.TestCase):
    def test_missing_current_price_insufficient(self):
        out = build_market_scenarios(**_battle_kw(current_price=None))
        self.assertEqual(out["status"], "insufficient_data")
        self.assertIn("message", out)

    def test_missing_low20_insufficient(self):
        out = build_market_scenarios(**_battle_kw(low20=None))
        self.assertEqual(out["status"], "insufficient_data")

    def test_missing_high60_insufficient(self):
        out = build_market_scenarios(**_battle_kw(high60=None))
        self.assertEqual(out["status"], "insufficient_data")

    def test_zero_or_negative_price_insufficient(self):
        out = build_market_scenarios(**_battle_kw(current_price=0))
        self.assertEqual(out["status"], "insufficient_data")

    def test_empty_resistance_candidates_falls_back_not_insufficient(self):
        # 指數連創 60 日新高：所有 MA／近60日高皆低於現價，resistances 天生是空的。
        # 應該退合成壓力值（現價+5%）繼續產出劇本，而不是整組回 insufficient_data
        # （見 build_market_scenarios 對 short_scenarios._nearest_or_fallback 的沿用）。
        out = build_market_scenarios(**_battle_kw(
            current_price=200.0, low20=180.0, high60=195.0,
            ma20=190.0, ma60=185.0, ma120=180.0))
        self.assertEqual(out["status"], "ok")
        bull = next(sc for sc in out["scenarios"] if sc["id"] == "bull")
        self.assertIn("近期壓力", bull["trigger"])


# ---------- leading_sectors / us_overnight ----------
class TestFlowHelpers(unittest.TestCase):
    def test_load_leading_sectors_top2_by_rank(self):
        out = load_leading_sectors(path=os.path.join(REPO_ROOT, "data", "tw_sectors.json"))
        self.assertEqual(out, ["軍工航太", "封裝測試"])

    def test_load_leading_sectors_missing_file_returns_empty(self):
        self.assertEqual(load_leading_sectors(path="/no/such/file.json"), [])

    def test_us_overnight_filters_spx_sox_only(self):
        us = [{"id": "SPX", "name": "S&P 500", "change_pct": -1.0},
              {"id": "NDX", "name": "Nasdaq 100", "change_pct": -1.2},
              {"id": "SOX", "name": "費城半導體", "change_pct": -1.6},
              {"id": "VIX", "name": "VIX", "change_pct": 9.0}]
        out = build_us_overnight(us)
        self.assertEqual(out, [{"id": "SPX", "change_pct": -1.0}, {"id": "SOX", "change_pct": -1.6}])

    def test_us_overnight_empty_when_none(self):
        self.assertEqual(build_us_overnight(None), [])


# ---------- forecast_range_m1（GBM 重用 forecast.py） ----------
class TestForecastRangeM1(unittest.TestCase):
    def test_sufficient_bars_returns_ordered_range(self):
        df = make_random_taiex_df(n=FORECAST_MIN_BARS + 40)
        rng = build_forecast_range_m1(df, "2026-07-18")
        self.assertIsNotNone(rng)
        self.assertEqual(len(rng), 2)
        self.assertLess(rng[0], rng[1])

    def test_insufficient_bars_returns_none(self):
        df = make_random_taiex_df(n=FORECAST_MIN_BARS - 1)
        self.assertIsNone(build_forecast_range_m1(df, "2026-07-18"))

    def test_none_df_or_date_returns_none(self):
        self.assertIsNone(build_forecast_range_m1(None, "2026-07-18"))
        df = make_random_taiex_df(n=FORECAST_MIN_BARS + 10)
        self.assertIsNone(build_forecast_range_m1(df, None))

    def test_deterministic_same_seed_same_date(self):
        df = make_random_taiex_df(n=FORECAST_MIN_BARS + 40)
        r1 = build_forecast_range_m1(df, "2026-07-18")
        r2 = build_forecast_range_m1(df, "2026-07-18")
        self.assertEqual(r1, r2)


# ---------- ohlc：v 一律 null ----------
class TestTaiexOhlc(unittest.TestCase):
    def test_v_field_is_null(self):
        df = make_random_taiex_df(n=80)
        ohlc = build_taiex_ohlc(df)
        self.assertIsNotNone(ohlc)
        self.assertTrue(all(bar["v"] is None for bar in ohlc))

    def test_trims_to_60_bars(self):
        df = make_random_taiex_df(n=200)
        ohlc = build_taiex_ohlc(df)
        self.assertEqual(len(ohlc), 60)

    def test_below_min_bars_returns_none(self):
        df = make_random_taiex_df(n=MIN_OHLC_BARS - 1)
        self.assertIsNone(build_taiex_ohlc(df))


# ---------- graceful null：整組 market_battle ----------
class TestBuildMarketBattleGracefulNull(unittest.TestCase):
    def test_none_df_returns_none(self):
        self.assertIsNone(build_market_battle(taiex_df=None))

    def test_too_few_rows_returns_none(self):
        df = make_random_taiex_df(n=MIN_OHLC_BARS - 1)
        self.assertIsNone(build_market_battle(taiex_df=df))

    def test_missing_ohlc_columns_returns_none(self):
        df = pd.DataFrame([{"date": "2026-07-01", "close": 20000.0}] * 30)
        self.assertIsNone(build_market_battle(taiex_df=df))


# ---------- 端到端：schema 驗證 ----------
class TestBuildMarketBattleEndToEnd(unittest.TestCase):
    def test_full_block_passes_schema(self):
        df = make_random_taiex_df(n=FORECAST_MIN_BARS + 60)
        foreign_df = make_foreign_df([5, 8, 12, -3, 20, 15, 9, 22, 18, 30])
        out = build_market_battle(
            taiex_df=df, foreign_df=foreign_df,
            leading_sectors=["軍工航太", "封裝測試"],
            us=[{"id": "SPX", "change_pct": -0.5}, {"id": "SOX", "change_pct": -1.1}],
            data_date="2026-07-18", market_new_position="可正常布局",
            vix_chg=3.0, sox_chg=-1.1,
        )
        self.assertIsNotNone(out)
        _validate_battle(out)
        self.assertEqual(out["flow"]["leading_sectors"], ["軍工航太", "封裝測試"])
        self.assertLessEqual(len(out["ohlc"]), 60)

    def test_null_market_battle_passes_schema(self):
        _validate_battle(None)


if __name__ == "__main__":
    unittest.main()
