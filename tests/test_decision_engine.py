"""T4：決策引擎 decision_engine.py 測試（純函式 + 假 price DataFrame）。"""
import unittest

import pandas as pd

from warroom.decision_engine import (
    atr14, atr_percent_median, light_consistency_score, composite_score,
    rating, stop_reference, risk_reward, confidence_score, position_sizing,
    entry_conditions, time_frames, invalidation, build_decision,
)

PROFILE = {
    "position_tiers": [
        {"name": "空手", "amount": 0}, {"name": "試單", "amount": 100000},
        {"name": "標準", "amount": 200000}, {"name": "加碼", "amount": 400000},
        {"name": "極高信心", "amount": 600000},
    ],
    "core_holdings": ["2330", "0050"],
}


def make_price(n=30, base=100.0):
    rows = []
    for i in range(n):
        c = base + i
        rows.append({"date": f"2026-06-{(i % 28) + 1:02d}", "max": c + 2,
                     "min": c - 2, "close": c, "Trading_Volume": 1000 + i})
    return pd.DataFrame(rows)


class TestDecisionEngine(unittest.TestCase):
    def test_atr14_needs_min_rows(self):
        self.assertIsNone(atr14(make_price(10)))  # <15 列
        self.assertIsNotNone(atr14(make_price(30)))

    def test_atr14_missing_cols(self):
        df = pd.DataFrame({"date": ["2026-06-01"] * 20, "close": [100.0] * 20})
        self.assertIsNone(atr14(df))

    def test_atr_percent_median(self):
        m = atr_percent_median(make_price(60))
        self.assertIsNotNone(m)
        self.assertGreater(m, 0)

    def test_light_consistency(self):
        self.assertEqual(light_consistency_score(["green", "green", "green"]), 30)
        self.assertEqual(light_consistency_score(["green", "green", "amber"]), 22)
        self.assertEqual(light_consistency_score(["green", "amber", "amber"]), 18)
        self.assertEqual(light_consistency_score(["amber", "amber", "amber"]), 15)
        self.assertEqual(light_consistency_score(["green", "red", "amber"]), 0)  # 衝突

    def test_composite_score_valuation_penalty(self):
        # 高估值分位（>0.85）壓低分數
        hi = composite_score("green", "green", "green", 0.96, "amber")
        lo = composite_score("green", "green", "green", 0.30, "amber")
        self.assertLess(hi, lo)

    def test_rating_no_buy_when_rr_low(self):
        # 三燈全綠但 R/R<1.5 → 不可買進
        r = rating("green", "green", "green", 0.30, "green", rr=1.0)
        self.assertNotEqual(r, "買進")
        r2 = rating("green", "green", "green", 0.30, "green", rr=3.0)
        self.assertEqual(r2, "買進")

    def test_rating_conflict_is_watch(self):
        self.assertEqual(rating("green", "red", "amber", 0.5, "amber", rr=3.0), "觀望")

    def test_stop_reference_clamped_to_range(self):
        # 關鍵均線離現價很近（-2%）→ 被夾到 -8%
        s = stop_reference(100.0, atr=1.0, key_ma=98.0, low20=97.0)
        self.assertLessEqual(s["pct"], -0.08 + 1e-9)
        self.assertGreaterEqual(s["pct"], -0.15 - 1e-9)
        self.assertTrue(s["clamped"])

    def test_stop_reference_deep_clamped(self):
        # ATR 很大導致停損 <-15% → 夾到 -15%
        s = stop_reference(100.0, atr=20.0, key_ma=50.0, low20=40.0)
        self.assertAlmostEqual(s["pct"], -0.15, places=4)

    def test_risk_reward(self):
        self.assertAlmostEqual(risk_reward(120.0, 100.0, 90.0), 2.0)  # (120-100)/(100-90)
        self.assertIsNone(risk_reward(120.0, 100.0, 100.0))  # 分母 0
        self.assertIsNone(risk_reward(None, 100.0, 90.0))

    def test_confidence_score_components(self):
        flags = {"fundamental": True, "technical": True, "chips": True, "eps_statement": True}
        c = confidence_score(flags, ["green", "green", "green"], rr=3.0, market_light="green")
        self.assertEqual(c["completeness"], 30)
        self.assertEqual(c["consistency"], 30)
        self.assertEqual(c["rr"], 20)
        self.assertEqual(c["regime"], 20)
        self.assertEqual(c["total"], 100)

    def test_confidence_penalized_when_data_missing(self):
        flags = {"fundamental": True, "technical": True, "chips": False, "eps_statement": False}
        c = confidence_score(flags, ["green", "amber", "na"], rr=None, market_light="red")
        self.assertLess(c["total"], 50)

    def test_position_sizing_ladder(self):
        # 極高信心：R/R>3、信心>80、三燈一致、低波動
        p = position_sizing(3.5, 90, ["green", "green", "green"], "green",
                            atr_pct=0.01, atr_median_pct=0.02, data_incomplete=False,
                            profile=PROFILE, price=100.0, stock_id="2454")
        self.assertEqual(p["amount"], 600000)
        # R/R<1.5 → 空手
        p0 = position_sizing(1.0, 90, ["green", "green", "green"], "green",
                             atr_pct=0.01, atr_median_pct=0.02, data_incomplete=False,
                             profile=PROFILE, price=100.0, stock_id="2454")
        self.assertEqual(p0["amount"], 0)
        # 大盤紅燈 → 空手
        pr = position_sizing(3.0, 85, ["green", "green", "amber"], "red",
                             atr_pct=0.01, atr_median_pct=0.02, data_incomplete=False,
                             profile=PROFILE, price=100.0, stock_id="2454")
        self.assertEqual(pr["amount"], 0)

    def test_position_odd_lot_and_core_note(self):
        # 股價 2420、試單 10 萬 → 一張要 242 萬 > 10 萬 → 零股
        p = position_sizing(1.8, 58, ["green", "amber", "amber"], "amber",
                            atr_pct=0.02, atr_median_pct=0.02, data_incomplete=False,
                            profile=PROFILE, price=2420.0, stock_id="2330")
        self.assertEqual(p["tier"], "試單")
        self.assertTrue(p["odd_lot"])
        self.assertIn("核心持股", p["core_note"])  # 2330 為核心

    def test_entry_conditions(self):
        e = entry_conditions(100.0, atr=2.0, low20=95.0, high20=110.0, ma20=98.0,
                             avg_vol20=1000.0)
        self.assertIn("回測型", e["pullback"])
        self.assertIn("突破型", e["breakout"])

    def test_time_frames_three(self):
        tf = time_frames(["green", "amber", "red"], "續抱",
                         {"base": 120.0, "bull": 140.0}, {"MA20": 98.0},
                         {"current_percentile": 0.9})
        self.assertEqual(set(tf.keys()), {"short", "swing", "mid"})
        self.assertIn("波段", tf["swing"]["label"])

    def test_invalidation_triggers(self):
        inv = invalidation(90.0,
                           {"yoy_negative": True, "below_6m_2months": True},
                           {"sell_streak_ge3": True, "ratio_gt_15pct": True})
        self.assertTrue(inv["any_triggered"])
        self.assertIn("已觸發", inv["fundamental"])

    def test_build_decision_integration(self):
        valuation = {
            "path": "per", "eps_ttm": 60.0, "eps_source": "financial_statement",
            "eps_forward": 75.0, "growth_used": 0.25,
            "fair_value": {"bear": 2050.0, "base": 2380.0, "bull": 2720.0},
            "multiples": {"bear": 25.0, "base": 30.0, "bull": 35.0},
            "current_multiple": 32.8, "current_percentile": 0.96,
            "disclosure": "…",
        }
        flags = {"fundamental": True, "technical": True, "chips": True, "eps_statement": True}
        dec = build_decision(
            price=2420.0, lights=["amber", "amber", "red"], per_percentile=0.96,
            market_light="red", valuation=valuation, atr=40.0, key_ma=2426.0,
            low20=2325.0, high20=2535.0, ma20=2426.0, avg_vol20=30000.0,
            atr_pct=0.017, atr_median_pct=0.02, data_flags=flags,
            rev_signals={"yoy_negative": False, "below_6m_2months": False},
            chip_signals={"sell_streak_ge3": True, "ratio_gt_15pct": False},
            profile=PROFILE, stock_id="2330")
        self.assertIn(dec["rating"], ["買進", "試單", "續抱", "觀望", "減碼"])
        self.assertIn("total", dec["confidence"])
        self.assertEqual(dec["fair_value"]["base"], 2380.0)
        self.assertIn("core_note", dec["position"])
        self.assertEqual(dec["as_of_price"], 2420.0)
        self.assertIn("disclaimer", dec)


if __name__ == "__main__":
    unittest.main()
