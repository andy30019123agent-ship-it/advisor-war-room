"""warroom/picks.py 測試（全離線，注入假 fetch_fn/analyze_fn）：
評分公式抽驗、閘門三態、名額上限、同股不重複、核心排除、候選池 fallback、entry_zone 錨點。"""
import json
import os
import unittest

import jsonschema
import pandas as pd

from warroom import picks

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY_SCHEMA = json.load(open(os.path.join(REPO_ROOT, "schema", "daily.schema.json"),
                              encoding="utf-8"))
PICK_DEF = DAILY_SCHEMA["definitions"]["pick"]


def _base_metrics(sid="9999", **over):
    m = {"id": sid, "name": sid, "close": 100.0, "ma20": 98.0, "ma60": 95.0,
         "ma120": 90.0, "ret20": 0.0, "ret60": 0.0, "high20": 105.0, "low20": 92.0,
         "vol_ratio": 1.0, "support": 98.0, "recent_high": 120.0, "revenue_yoy": None,
         "avg3_yoy": None, "per": None, "per_pctile": None, "pbr_pctile": None,
         "div_yield": None, "chip_turn_buy": False, "chip_buy_streak_ge3": False,
         "dist_high20_pct": 5.0, "earnings_within7": False, "risk_flags": []}
    m.update(over)
    return m


def _daily_df(prices, vols=None):
    n = len(prices)
    vols = vols or [1000] * n
    dates = pd.date_range("2024-01-01", periods=n).strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "close": prices, "max": [p * 1.01 for p in prices],
                         "min": [p * 0.99 for p in prices], "Trading_Volume": vols})


# ---------- 評分公式抽驗 ----------
class TestScoringFormulas(unittest.TestCase):
    def test_short_full_stack(self):
        # 動能滿(+30) + 站回MA20(+20) + 帶量突破(+25) + 法人轉買(+25) = 100
        m = _base_metrics(close=106.0, ma20=98.0, ret20=15.0, high20=105.0,
                          vol_ratio=1.5, chip_turn_buy=True, dist_high20_pct=None)
        self.assertEqual(picks.score_short(m), 100.0)

    def test_short_event_and_chase_penalty(self):
        # 動能 6% → 15；站回MA20 +20；距高 1% 追高 -10；事件7天內 -15 = 10
        m = _base_metrics(close=104.0, ma20=98.0, ret20=6.0, high20=105.0,
                          vol_ratio=1.0, dist_high20_pct=1.0, earnings_within7=True)
        self.assertEqual(picks.score_short(m), 10.0)

    def test_short_no_breakout_without_volume(self):
        m = _base_metrics(close=106.0, ma20=98.0, ret20=0.0, high20=105.0,
                          vol_ratio=1.1, dist_high20_pct=None)  # 突破但量不足
        self.assertEqual(picks.score_short(m), 20.0)  # 只有站回MA20

    def test_swing_full_stack(self):
        # 結構30 + RS60滿20 + 法人連買15 + R/R>=1.8 給20 + 營收正15 = 100
        m = _base_metrics(close=100.0, ma20=98.0, ma60=95.0, ma120=90.0, ret60=25.0,
                          chip_buy_streak_ge3=True, support=95.0, recent_high=130.0,
                          revenue_yoy=5.0)
        self.assertEqual(picks.score_swing(m), 100.0)

    def test_swing_rr_below_threshold_scaled(self):
        # 只測 R/R 分項：結構全關、其它關；close100 support98→defense≈94.08,
        # target105 → rr=(105-100)/(100-94.08)=0.845 <1 → 0 分
        m = _base_metrics(close=100.0, ma20=101.0, ma60=102.0, ma120=103.0, ret60=0.0,
                          support=98.0, recent_high=105.0, revenue_yoy=-1.0)
        self.assertEqual(picks.score_swing(m), 0.0)

    def test_long_value_stock(self):
        # 營收正15 + 近3月均正15 + avg3幅度10%→+5 + PER 30%分位→+8 + 殖利率3%→+10 = 53
        m = _base_metrics(revenue_yoy=8.0, avg3_yoy=10.0, per_pctile=0.30, div_yield=3.0)
        self.assertEqual(picks.score_long(m), 53.0)

    def test_long_risk_flag_penalty(self):
        base = picks.score_long(_base_metrics(revenue_yoy=8.0, avg3_yoy=8.0))
        flagged = picks.score_long(_base_metrics(revenue_yoy=8.0, avg3_yoy=8.0,
                                                 risk_flags=["高波動", "財報疑慮"]))
        self.assertEqual(base - flagged, 20.0)  # 兩個 flag 各 -10

    def test_confidence_mapping(self):
        self.assertEqual(picks.confidence_from_score(78), 65)  # 契約範例
        self.assertEqual(picks.confidence_from_score(100), 80)  # clamp 上限
        self.assertEqual(picks.confidence_from_score(0), 10)


# ---------- 操作卡 / entry_zone ----------
class TestOperationCard(unittest.TestCase):
    def test_entry_zone_anchor_within_10pct(self):
        for close in (66.8, 305.0, 1850.0):
            m = _base_metrics(close=close, support=close * 1.04, ma20=close * 1.04)
            low, high = picks._entry_zone(m)
            self.assertGreaterEqual(low, round(close * 0.90, 1) - 0.05)
            self.assertLessEqual(high, round(close * 1.02, 1) + 0.05)
            self.assertLessEqual(low, high)

    def test_card_has_exactly_three_reasons_and_passes_schema(self):
        m = _base_metrics(close=305.0, revenue_yoy=8.0, avg3_yoy=7.0, per_pctile=0.35,
                          div_yield=3.0, pbr_pctile=0.3)
        card = picks.build_pick_card(m, "long", 78, "僅限試單")
        self.assertEqual(len(card["reasons"]), 3)
        jsonschema.validate(card, PICK_DEF)

    def test_reasons_padded_to_three_when_sparse(self):
        m = _base_metrics(close=50.0)  # 幾乎沒有正向理由
        card = picks.build_pick_card(m, "long", 60, "可正常布局")
        self.assertEqual(len(card["reasons"]), 3)

    def test_trial_note_only_when_trial_gate(self):
        m = _base_metrics(close=100.0)
        trial = picks.build_pick_card(m, "swing", 70, "僅限試單")
        normal = picks.build_pick_card(m, "swing", 70, "可正常布局")
        self.assertIn("試單上限 10 萬", trial["action_summary"])
        self.assertNotIn("試單上限", normal["action_summary"])


# ---------- 選檔 / 名額上限 / 同股不重複 ----------
class TestSelection(unittest.TestCase):
    def _scored(self, sid, s, sw, l):
        return {"metrics": _base_metrics(sid), "short": s, "swing": sw, "long": l}

    def test_limits_per_framework(self):
        scored = [self._scored(f"L{i}", 0, 0, 90 - i) for i in range(8)]
        scored += [self._scored(f"W{i}", 0, 90 - i, 0) for i in range(6)]
        scored += [self._scored(f"S{i}", 90 - i, 0, 0) for i in range(3)]
        buckets = picks.select_frameworks(scored)
        self.assertLessEqual(len(buckets["short"]), 1)
        self.assertLessEqual(len(buckets["swing"]), 3)
        self.assertLessEqual(len(buckets["long"]), 5)

    def test_stock_only_in_highest_framework(self):
        # 同一檔三框架都達標，最高分是 swing → 只出現在 swing
        scored = [self._scored("AAA", 72, 90, 61)]
        buckets = picks.select_frameworks(scored)
        ids = {fw: [m["id"] for m, _ in buckets[fw]] for fw in buckets}
        self.assertEqual(ids["swing"], ["AAA"])
        self.assertNotIn("AAA", ids["short"])
        self.assertNotIn("AAA", ids["long"])

    def test_below_all_thresholds_dropped(self):
        buckets = picks.select_frameworks([self._scored("BBB", 69, 64, 59)])
        self.assertEqual(buckets["short"] + buckets["swing"] + buckets["long"], [])

    def test_falls_to_lower_qualifying_framework(self):
        # short 分最高但 <70 未達標；swing 66 達標 → 落到 swing
        buckets = picks.select_frameworks([self._scored("CCC", 68, 66, 55)])
        ids = [m["id"] for m, _ in buckets["swing"]]
        self.assertEqual(ids, ["CCC"])


# ---------- 閘門三態 ----------
class TestGate(unittest.TestCase):
    def _scored(self):
        return [
            {"metrics": _base_metrics("S1"), "short": 80, "swing": 0, "long": 0},
            {"metrics": _base_metrics("W1"), "short": 0, "swing": 80, "long": 0},
            {"metrics": _base_metrics("L1"), "short": 0, "swing": 0, "long": 80},
        ]

    def test_gate_banned_clears_short_swing_keeps_long(self):
        block, _ = picks.build_picks_block(self._scored(), "禁止新增部位", "gen")
        self.assertEqual(block["short"], [])
        self.assertEqual(block["swing"], [])
        self.assertEqual(len(block["long"]), 1)
        self.assertIn("等大盤解禁", block["long"][0]["action_summary"])
        self.assertIn("禁新倉", block["note"])

    def test_gate_trial_all_frameworks_with_note(self):
        block, _ = picks.build_picks_block(self._scored(), "僅限試單", "gen")
        self.assertEqual(len(block["short"]), 1)
        self.assertEqual(len(block["swing"]), 1)
        self.assertEqual(len(block["long"]), 1)
        self.assertIn("試單上限 10 萬", block["short"][0]["action_summary"])

    def test_gate_normal(self):
        block, _ = picks.build_picks_block(self._scored(), "可正常布局", "gen")
        self.assertTrue(all(block[fw] for fw in ("short", "swing", "long")))
        self.assertNotIn("試單上限", block["long"][0]["action_summary"])

    def test_whitelist_excludes_uncklickable_new_ids(self):
        # max_new_ids 白名單只放 W1 → S1/L1（新股但不在白名單）被移除
        block, sel = picks.build_picks_block(self._scored(), "可正常布局", "gen",
                                             max_new_ids={"W1"})
        self.assertEqual(sel, ["W1"])
        self.assertEqual(block["short"], [])
        self.assertEqual(block["long"], [])


# ---------- 候選池 / 核心排除 / fallback ----------
class TestCandidatePool(unittest.TestCase):
    def test_core_holdings_excluded(self):
        pool = picks.build_candidate_pool(
            opportunities=[{"id": "2330", "name": "台積電"}],
            universe=[{"id": "0050", "name": "元大台灣50"}, {"id": "2317", "name": "鴻海"}],
            tracked_ids=["2330"], core_ids=["2330", "0050"])
        ids = [c["id"] for c in pool]
        self.assertNotIn("2330", ids)
        self.assertNotIn("0050", ids)
        self.assertIn("2317", ids)

    def test_dedup_and_priority_and_cap(self):
        opp = [{"id": "1101", "name": "台泥"}]
        uni = [{"id": str(1000 + i), "name": f"U{i}"} for i in range(50)]
        pool = picks.build_candidate_pool(opp, uni, tracked_ids=["1101", "2603"],
                                          core_ids=[], cap=5)
        ids = [c["id"] for c in pool]
        self.assertEqual(len(ids), 5)
        self.assertEqual(len(set(ids)), 5)  # 去重
        self.assertEqual(ids[0], "1101")    # opportunities 優先
        self.assertIn("2603", ids)          # tracked 次之

    def test_fetch_opportunities_fallback_to_local(self, ):
        # 線上必掛（無效 url）→ 落到本地檔
        local = os.path.join(REPO_ROOT, "tests", "_tmp_opp.json")
        json.dump({"picks": [{"id": "9527", "name": "測試"}]}, open(local, "w"))
        try:
            got, src = picks.fetch_opportunities(url="http://127.0.0.1:0/none",
                                                 local_path=local, timeout=1)
            self.assertEqual(src, "local")
            self.assertEqual(got[0]["id"], "9527")
        finally:
            os.remove(local)

    def test_fetch_opportunities_none_when_all_fail(self):
        got, src = picks.fetch_opportunities(url="http://127.0.0.1:0/none",
                                             local_path="/no/such/file.json", timeout=1)
        self.assertEqual((got, src), ([], "none"))


# ---------- 指標抽取 ----------
class TestMetrics(unittest.TestCase):
    def test_metrics_from_daily(self):
        m = picks.metrics_from_daily(_daily_df(list(range(1, 131))))
        self.assertEqual(m["close"], 130.0)
        self.assertIsNotNone(m["ma120"])
        self.assertGreater(m["ret20"], 0)

    def test_metrics_from_daily_short_series(self):
        m = picks.metrics_from_daily(_daily_df([10.0, 11.0, 12.0]))
        self.assertIsNone(m["ma120"])   # 樣本不足
        self.assertIsNone(m["ret20"])

    def test_metrics_from_revenue_yoy(self):
        rows = [{"revenue_year": 2025, "revenue_month": m, "revenue": 100} for m in range(1, 13)]
        rows += [{"revenue_year": 2026, "revenue_month": m, "revenue": 110} for m in range(1, 4)]
        m = picks.metrics_from_revenue(pd.DataFrame(rows))
        self.assertAlmostEqual(m["revenue_yoy"], 10.0, places=1)

    def test_metrics_from_valuation_percentile(self):
        df = pd.DataFrame({"date": pd.date_range("2021-01-01", periods=5).strftime("%Y-%m-%d"),
                           "PER": [20, 18, 16, 14, 12], "PBR": [3, 2.8, 2.6, 2.4, 2.2],
                           "dividend_yield": [2, 2, 2, 2, 4.0]})
        m = picks.metrics_from_valuation(df)
        self.assertEqual(m["per_pctile"], 0.0)  # 當前 12 為序列最低
        self.assertEqual(m["div_yield"], 4.0)


# ---------- generate_picks 端到端（離線注入）----------
class TestGeneratePicksOffline(unittest.TestCase):
    def _fetch_fn(self, method, stock_id=None, start_date=None, **kw):
        if method == "taiwan_stock_daily":
            # 上升趨勢，突破近高帶量
            prices = [80 + i * 0.4 for i in range(130)]
            vols = [1000] * 129 + [2000]
            return _daily_df(prices, vols)
        if method == "taiwan_stock_month_revenue":
            rows = [{"revenue_year": 2025, "revenue_month": m, "revenue": 100} for m in range(1, 13)]
            rows += [{"revenue_year": 2026, "revenue_month": m, "revenue": 115} for m in range(1, 4)]
            return pd.DataFrame(rows)
        if method == "taiwan_stock_per_pbr":
            return pd.DataFrame({"date": pd.date_range("2021-01-01", periods=5).strftime("%Y-%m-%d"),
                                 "PER": [30, 25, 20, 16, 12], "PBR": [3, 2.5, 2, 1.6, 1.2],
                                 "dividend_yield": [3, 3, 3, 3, 4.0]})
        return None

    def _analyze_fn(self, sid):
        return {"stock_id": sid, "name": sid, "chips": {"light": "amber"}}

    def test_end_to_end_normal_gate(self):
        eg = {"new_position": "可正常布局", "risk_temp": 3}
        block, results, stats = picks.generate_picks(
            eg, results={}, profile={"core_holdings": ["2330", "0050"]},
            fetch_fn=self._fetch_fn, analyze_fn=self._analyze_fn,
            opportunities=[{"id": "3034", "name": "聯詠", "reasons": ["外資連買"],
                            "support_ma20": 100.0, "recent_high20": 140.0,
                            "risk_flags": []}],
            universe=[{"id": "2308", "name": "台達電"}, {"id": "1101", "name": "台泥"}])
        # picks 區塊符合契約 + 至少有選出東西 + picks_results 是被選新股
        for fw in ("short", "swing", "long"):
            self.assertLessEqual(len(block[fw]), picks._LIMITS[fw])
        jsonschema.validate({**block}, {"$ref": "#/properties/picks",
                                        **DAILY_SCHEMA})
        self.assertTrue(set(results.keys()) <= {"3034", "2308", "1101"})
        self.assertLessEqual(len(results), picks.MAX_NEW_ANALYZE)
        self.assertGreater(stats["finmind_calls"], 0)
        self.assertEqual(stats["opp_source"], "injected")

    def test_end_to_end_banned_gate_only_long(self):
        eg = {"new_position": "禁止新增部位", "risk_temp": 9}
        block, results, stats = picks.generate_picks(
            eg, results={}, profile={"core_holdings": []},
            fetch_fn=self._fetch_fn, analyze_fn=self._analyze_fn,
            opportunities=[], universe=[{"id": "2308", "name": "台達電"}])
        self.assertEqual(block["short"], [])
        self.assertEqual(block["swing"], [])
        self.assertEqual(block["gate"], "禁止新增部位")

    def test_universe_only_when_no_opportunities(self):
        eg = {"new_position": "可正常布局", "risk_temp": 3}
        block, results, stats = picks.generate_picks(
            eg, results={}, profile={"core_holdings": []},
            fetch_fn=self._fetch_fn, analyze_fn=self._analyze_fn,
            opportunities=[], universe=[{"id": "2308", "name": "台達電"}])
        self.assertEqual(stats["pool_size"], 1)  # 僅 universe


if __name__ == "__main__":
    unittest.main()
