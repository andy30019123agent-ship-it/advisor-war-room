"""warroom/picks.py 測試（全離線，注入假 fetch_fn/analyze_fn）。
涵蓋：評分 v2（品質/成長、估值殖利率上限 40%、金融 PBR、技術紅燈、warning cap）、
分艙 pools（actionable/on_deck/research 名額）、輪動席與降權、新面孔（tenure/rank_move/
roster_changes）、執行鏈路（picks entry alerts source）、族群對應、閘門三態、候選池 fallback。"""
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
PICKS_SCHEMA = {"$ref": "#/properties/picks", **DAILY_SCHEMA}


def _base_metrics(sid="9999", **over):
    m = {"id": sid, "name": sid, "close": 100.0, "ma20": 98.0, "ma60": 95.0,
         "ma120": 90.0, "ret20": 0.0, "ret60": 0.0, "high20": 105.0, "low20": 92.0,
         "vol_ratio": 1.0, "support": 98.0, "recent_high": 120.0, "revenue_yoy": None,
         "avg3_yoy": None, "avg12_yoy": None, "per": None, "per_pctile": None,
         "pbr_pctile": None, "div_yield": None, "chip_turn_buy": False,
         "chip_buy_streak_ge3": False, "dist_high20_pct": 5.0, "earnings_within7": False,
         "risk_flags": [], "sector": None, "sector_tier": None, "is_financial": False,
         "roe": None, "margin_improving": False, "quality_pct": None,
         "valuation_warning": False}
    m.update(over)
    return m


def _daily_df(prices, vols=None):
    n = len(prices)
    vols = vols or [1000] * n
    dates = pd.date_range("2024-01-01", periods=n).strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "close": prices, "max": [p * 1.01 for p in prices],
                         "min": [p * 0.99 for p in prices], "Trading_Volume": vols})


def _scored(sid, s, sw, l, **over):
    return {"metrics": _base_metrics(sid, **over), "short": s, "swing": sw, "long": l}


# ---------- 短線/波段評分（v1.5 沿用）----------
class TestShortSwing(unittest.TestCase):
    def test_short_full_stack(self):
        m = _base_metrics(close=106.0, ma20=98.0, ret20=15.0, high20=105.0,
                          vol_ratio=1.5, chip_turn_buy=True, dist_high20_pct=None)
        self.assertEqual(picks.score_short(m), 100.0)

    def test_short_event_and_chase_penalty(self):
        m = _base_metrics(close=104.0, ma20=98.0, ret20=6.0, high20=105.0,
                          vol_ratio=1.0, dist_high20_pct=1.0, earnings_within7=True)
        self.assertEqual(picks.score_short(m), 10.0)

    def test_swing_full_stack(self):
        m = _base_metrics(close=100.0, ma20=98.0, ma60=95.0, ma120=90.0, ret60=25.0,
                          chip_buy_streak_ge3=True, support=95.0, recent_high=130.0,
                          revenue_yoy=5.0)
        self.assertEqual(picks.score_swing(m), 100.0)


# ---------- 長線評分 v2 ----------
class TestScoreLongV2(unittest.TestCase):
    def test_value_stock_baseline(self):
        # 營收正15 + 近3月均10%→15+6 + PER 30%分位→10 + 殖利率3%→10（估值殖利率合計 20≤40）= 56
        m = _base_metrics(revenue_yoy=8.0, avg3_yoy=10.0, per_pctile=0.30, div_yield=3.0)
        self.assertEqual(picks.score_long(m), 56.0)

    def test_growth_stock_reaches_research(self):
        # 研華型：高營收成長＋加速，估值偏貴（分位85%、未達warning）殖利率低 → 品質面撐到 ≥60
        m = _base_metrics(revenue_yoy=73.0, avg3_yoy=45.0, avg12_yoy=25.0,
                          per_pctile=0.85, div_yield=0.5)
        s = picks.score_long(m)
        self.assertGreaterEqual(s, 60.0)  # 成長股能進 research（修正 v1.5 價值偏誤）

    def test_valuation_yield_weight_capped_at_40(self):
        # 極端便宜＋高殖利率：PER0%→25、PBR0%→5、殖利率4%→15 合計 45，但硬上限 40
        cheap = _base_metrics(per_pctile=0.0, pbr_pctile=0.0, div_yield=5.0)
        no_val = _base_metrics()
        self.assertEqual(round(picks.score_long(cheap) - picks.score_long(no_val), 1), 40.0)

    def test_financial_uses_pbr_not_per(self):
        # 金融股：便宜 PER 不該給分（不可比），只看 PBR。非金融同分位則吃 PER credit。
        fin = _base_metrics(is_financial=True, sector="金融",
                            per_pctile=0.05, pbr_pctile=0.80)
        nonfin = _base_metrics(is_financial=False, per_pctile=0.05, pbr_pctile=0.80)
        self.assertEqual(picks.score_long(fin), 0.0)        # PBR 貴、PER 被忽略
        self.assertGreater(picks.score_long(nonfin), 0.0)   # 非金融吃便宜 PER

    def test_valuation_warning_caps_at_70(self):
        # 高成長高品質但 valuation_warning=True（估值不可信）→ 最終 cap 70
        m = _base_metrics(revenue_yoy=73.0, avg3_yoy=45.0, avg12_yoy=10.0,
                          div_yield=4.0, roe=0.30, margin_improving=True,
                          valuation_warning=True)
        self.assertLessEqual(picks.score_long(m), 70.0)
        # 同標的無 warning → 分數突破 70（證明 cap 真的來自 warning）
        m2 = _base_metrics(revenue_yoy=73.0, avg3_yoy=45.0, avg12_yoy=10.0,
                           div_yield=4.0, roe=0.30, margin_improving=True,
                           valuation_warning=False)
        self.assertGreater(picks.score_long(m2), 70.0)

    def test_valuation_warning_proxy_from_extreme_percentile(self):
        # assemble_metrics 代理：估值分位極端偏高（≥0.9）→ valuation_warning=True
        cand = {"id": "9999", "name": "X", "opp": {}}
        m = picks.assemble_metrics(
            cand, {"close": 100.0, "ma20": 98.0}, {},
            {"per": None, "per_pctile": 0.95, "pbr_pctile": None, "div_yield": None},
            tracked_res=None, sector_info={"sector": "光學", "tier": "mid"})
        self.assertTrue(m["valuation_warning"])

    def test_technical_red_deducts(self):
        below = _base_metrics(close=90.0, ma20=95.0, ma60=100.0, ma120=110.0,
                              revenue_yoy=8.0, avg3_yoy=8.0)
        above = _base_metrics(close=120.0, ma20=95.0, ma60=100.0, ma120=110.0,
                              revenue_yoy=8.0, avg3_yoy=8.0)
        self.assertEqual(round(picks.score_long(above) - picks.score_long(below), 1), 15.0)

    def test_below_ma120_only_deducts_8(self):
        # 價低於 MA120 但站上 MA20/60（和泰車型長期趨勢未收復）→ -8（非紅燈 -15）
        below120 = _base_metrics(close=486.0, ma20=477.0, ma60=476.0, ma120=498.0,
                                 revenue_yoy=8.0, avg3_yoy=8.0)
        above = _base_metrics(close=520.0, ma20=477.0, ma60=476.0, ma120=498.0,
                              revenue_yoy=8.0, avg3_yoy=8.0)
        self.assertEqual(round(picks.score_long(above) - picks.score_long(below120), 1), 8.0)

    def test_base_deviation_warning_from_tracked(self):
        # decision.valuation：Base 公允價（15.66×41.96≈657）偏離現價 486 達 35% → warning
        tracked_res = {"decision": {"as_of_price": 486.0,
                                    "valuation": {"multiples": {"base": 15.66},
                                                  "eps_forward": 41.96}}}
        cand = {"id": "2207", "name": "和泰車", "opp": {}}
        m = picks.assemble_metrics(cand, {"close": 486.0, "ma20": 477.0}, {},
                                   {"per": None, "per_pctile": 0.09, "pbr_pctile": None,
                                    "div_yield": None},
                                   tracked_res=tracked_res,
                                   sector_info={"sector": "汽車", "tier": "mid"})
        self.assertTrue(m["valuation_warning"])

    def test_revenue_acceleration_bonus(self):
        accel = _base_metrics(revenue_yoy=20.0, avg3_yoy=30.0, avg12_yoy=10.0)  # 加速 +20
        flat = _base_metrics(revenue_yoy=20.0, avg3_yoy=30.0, avg12_yoy=30.0)   # 無加速
        self.assertGreater(picks.score_long(accel), picks.score_long(flat))

    def test_roe_margin_only_when_data(self):
        with_fund = _base_metrics(revenue_yoy=8.0, roe=0.30, margin_improving=True)
        without = _base_metrics(revenue_yoy=8.0)
        self.assertEqual(round(picks.score_long(with_fund) - picks.score_long(without), 1),
                         10.0)  # ROE≥15% +6、毛利改善 +4

    def test_confidence_mapping(self):
        self.assertEqual(picks.confidence_from_score(78), 65)
        self.assertEqual(picks.confidence_from_score(100), 80)


# ---------- 操作卡 / entry_zone ----------
class TestOperationCard(unittest.TestCase):
    def test_entry_zone_anchor_within_10pct(self):
        for close in (66.8, 305.0, 1850.0):
            m = _base_metrics(close=close, support=close * 1.04, ma20=close * 1.04)
            low, high = picks._entry_zone(m)
            self.assertGreaterEqual(low, round(close * 0.90, 1) - 0.05)
            self.assertLessEqual(high, round(close * 1.02, 1) + 0.05)
            self.assertLessEqual(low, high)

    def test_card_has_new_fields_and_passes_schema(self):
        m = _base_metrics(close=305.0, revenue_yoy=8.0, avg3_yoy=7.0, per_pctile=0.35,
                          div_yield=3.0, pbr_pctile=0.3, sector="工業電腦")
        card = picks.build_pick_card(m, "long", 78, "僅限試單", tenure_days=3,
                                     rank_move="↑", status_note="等大盤解禁")
        self.assertEqual(len(card["reasons"]), 3)
        self.assertEqual(card["sector"], "工業電腦")
        self.assertEqual(card["tenure_days"], 3)
        self.assertEqual(card["rank_move"], "↑")
        self.assertEqual(card["status_note"], "等大盤解禁")
        jsonschema.validate(card, PICK_DEF)

    def test_trial_note_only_when_trial_gate(self):
        m = _base_metrics(close=100.0)
        trial = picks.build_pick_card(m, "swing", 70, "僅限試單")
        normal = picks.build_pick_card(m, "swing", 70, "可正常布局")
        self.assertIn("試單上限 10 萬", trial["action_summary"])
        self.assertNotIn("試單上限", normal["action_summary"])


# ---------- 選檔 / 名額 ----------
class TestSelection(unittest.TestCase):
    def test_limits_per_framework(self):
        scored = [_scored(f"L{i}", 0, 0, 90 - i) for i in range(8)]
        scored += [_scored(f"W{i}", 0, 90 - i, 0) for i in range(6)]
        scored += [_scored(f"S{i}", 90 - i, 0, 0) for i in range(3)]
        buckets = picks.select_frameworks(scored)
        self.assertLessEqual(len(buckets["short"]), 1)
        self.assertLessEqual(len(buckets["swing"]), 3)
        self.assertLessEqual(len(buckets["long"]), 5)

    def test_stock_only_in_highest_framework(self):
        buckets = picks.select_frameworks([_scored("AAA", 72, 90, 61)])
        ids = {fw: [m["id"] for m, _ in buckets[fw]] for fw in buckets}
        self.assertEqual(ids["swing"], ["AAA"])
        self.assertNotIn("AAA", ids["short"])
        self.assertNotIn("AAA", ids["long"])


# ---------- 輪動（降權 + on_deck 席位）----------
class TestRotation(unittest.TestCase):
    def test_lagging_non_deep_value_downweighted(self):
        lag = [_scored("LAG", 80, 80, 80, sector_tier="lag", per_pctile=0.60)]
        adj = picks.apply_rotation(lag)
        self.assertEqual(adj[0]["swing"], 72.0)   # 80 ×0.9
        self.assertTrue(adj[0]["metrics"].get("_rotation_downweighted"))

    def test_lagging_deep_value_not_downweighted(self):
        lag = [_scored("DV", 80, 80, 80, sector_tier="lag", per_pctile=0.20)]  # 深度價值
        adj = picks.apply_rotation(lag)
        self.assertEqual(adj[0]["swing"], 80)

    def test_leading_sector_reserved_ondeck_seat(self):
        # 領先族群強勢 swing 標的 → 保 on_deck 輪動席（gate 允許時）
        scored = [_scored("LEAD", 0, 90, 0, sector_tier="lead"),
                  _scored("MID", 0, 80, 0, sector_tier="mid")]
        block, _sel, _r = picks.build_pools_block(scored, "可正常布局", "gen")
        ondeck_ids = [c["id"] for c in block["pools"]["on_deck"]]
        actionable_ids = [c["id"] for c in block["pools"]["actionable"]]
        self.assertIn("LEAD", ondeck_ids)
        self.assertIn("MID", actionable_ids)
        self.assertIn("輪動席", block["pools"]["on_deck"][0]["status_note"])


# ---------- 分艙閘門 ----------
class TestPools(unittest.TestCase):
    def _scored3(self):
        return [_scored("S1", 80, 0, 0), _scored("W1", 0, 80, 0), _scored("L1", 0, 0, 80)]

    def test_gate_allows_tactical_in_actionable_long_in_research(self):
        block, _s, _r = picks.build_pools_block(self._scored3(), "可正常布局", "gen")
        act_ids = [c["id"] for c in block["pools"]["actionable"]]
        self.assertIn("S1", act_ids)
        self.assertIn("W1", act_ids)
        self.assertEqual([c["id"] for c in block["pools"]["research"]], ["L1"])

    def test_gate_banned_tactical_to_ondeck_with_status_note(self):
        block, _s, _r = picks.build_pools_block(self._scored3(), "禁止新增部位", "gen")
        self.assertEqual(block["pools"]["actionable"], [])
        ondeck = block["pools"]["on_deck"]
        self.assertEqual({c["id"] for c in ondeck}, {"S1", "W1"})
        self.assertIn("等大盤解禁", ondeck[0]["status_note"])
        self.assertEqual([c["id"] for c in block["pools"]["research"]], ["L1"])
        self.assertIn("禁新倉", block["note"])

    def test_actionable_plus_ondeck_capped_at_4(self):
        scored = [_scored(f"W{i}", 0, 90 - i, 0) for i in range(3)]
        scored += [_scored(f"S{i}", 88 - i, 0, 0) for i in range(2)]  # 5 個 tactical
        block, _s, _r = picks.build_pools_block(scored, "可正常布局", "gen")
        total = len(block["pools"]["actionable"]) + len(block["pools"]["on_deck"])
        self.assertLessEqual(total, 4)

    def test_research_capped_at_5(self):
        scored = [_scored(f"L{i}", 0, 0, 90 - i) for i in range(8)]
        block, _s, _r = picks.build_pools_block(scored, "可正常布局", "gen")
        self.assertLessEqual(len(block["pools"]["research"]), 5)

    def test_whitelist_excludes_unclickable_ids(self):
        block, sel, _r = picks.build_pools_block(self._scored3(), "可正常布局", "gen",
                                                 max_new_ids={"W1"})
        self.assertEqual(sel, ["W1"])
        self.assertEqual(block["pools"]["research"], [])

    def test_block_passes_schema(self):
        block, _s, _r = picks.build_pools_block(self._scored3(), "禁止新增部位", "gen")
        jsonschema.validate(block, PICKS_SCHEMA)


# ---------- 新面孔（tenure / rank_move / roster_changes）----------
class TestRoster(unittest.TestCase):
    def test_tenure_and_rank_move_from_roster(self):
        roster = {"picks": {"W1": {"tenure_days": 2, "rank": 2, "pool": "actionable"}}}
        scored = [_scored("W1", 0, 90, 0), _scored("W2", 0, 80, 0)]
        block, _s, new_roster = picks.build_pools_block(scored, "可正常布局", "gen",
                                                        roster=roster)
        w1 = next(c for c in block["pools"]["actionable"] if c["id"] == "W1")
        w2 = next(c for c in block["pools"]["actionable"] if c["id"] == "W2")
        self.assertEqual(w1["tenure_days"], 3)     # 連任+1
        self.assertEqual(w1["rank_move"], "↑")     # 昨名次 2 → 今 1
        self.assertEqual(w2["tenure_days"], 1)     # 新進
        self.assertEqual(w2["rank_move"], "−")
        self.assertIn("W1", new_roster["picks"])

    def test_roster_changes_new_dropped_stay(self):
        roster = {"picks": {"OLD": {"tenure_days": 5, "rank": 1, "pool": "research"},
                            "STAY": {"tenure_days": 2, "rank": 1, "pool": "actionable"}}}
        scored = [_scored("STAY", 0, 90, 0), _scored("NEW", 0, 80, 0)]
        block, _s, _r = picks.build_pools_block(scored, "可正常布局", "gen", roster=roster)
        rc = block["roster_changes"]
        self.assertEqual(rc["new"], ["NEW"])
        self.assertEqual(rc["dropped"], ["OLD"])
        self.assertIn("STAY", rc["stay_note"])       # STAY 連任達 3 日
        self.assertIn("連續 3 日", rc["stay_note"])


# ---------- 執行鏈路：picks entry alerts ----------
class TestPicksEntryAlerts(unittest.TestCase):
    def test_entry_alert_source_picks(self):
        block = {"pools": {"actionable": [{"id": "2308", "name": "台達電"}],
                           "on_deck": [], "research": []}}
        details = {"2308": {"primary_decision": {"entry_condition": {"price": 320.0}}}}
        alerts = picks.picks_entry_alerts(block, details)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["source"], "picks")
        self.assertEqual(alerts[0]["type"], "entry")
        self.assertEqual(alerts[0]["price"], 320.0)

    def test_skip_tracked_ids_and_missing_entry(self):
        block = {"pools": {"actionable": [{"id": "2330", "name": "台積電"},
                                          {"id": "2308", "name": "台達電"}],
                           "on_deck": [], "research": []}}
        details = {"2330": {"primary_decision": {"entry_condition": {"price": 1000.0}}},
                   "2308": {"primary_decision": {"entry_condition": None}}}
        alerts = picks.picks_entry_alerts(block, details, skip_ids={"2330"})
        self.assertEqual(alerts, [])  # 2330 已 tracked 跳過、2308 無進場錨


# ---------- 族群對應 ----------
class TestSectorMap(unittest.TestCase):
    def test_tier_from_tw_sectors(self):
        smap = picks.load_sector_map(picks.load_universe(
            os.path.join(REPO_ROOT, "data", "universe.json")),
            tw_sectors_path=os.path.join(REPO_ROOT, "data", "tw_sectors.json"))
        # 2634 在 tw_sectors「軍工航太」group（tier=lead），直接由 id 命中
        self.assertEqual(smap.get("2634", {}).get("tier"), "lead")
        # 金融族群名對應到 tw_sectors「金融」group（tier=mid）
        self.assertEqual(smap["2882"]["sector"], "金融")
        self.assertIn(smap["2882"]["tier"], ("mid", "lead", "lag"))

    def test_missing_tw_sectors_degrades(self):
        smap = picks.load_sector_map([{"id": "9999", "name": "X", "sector": "未知"}],
                                     tw_sectors_path="/no/such.json")
        self.assertEqual(smap["9999"]["tier"], None)


# ---------- 候選池 / fallback ----------
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

    def test_fetch_opportunities_fallback_to_local(self):
        local = os.path.join(REPO_ROOT, "tests", "_tmp_opp.json")
        json.dump({"picks": [{"id": "9527", "name": "測試"}]}, open(local, "w"))
        try:
            got, src = picks.fetch_opportunities(url="http://127.0.0.1:0/none",
                                                 local_path=local, timeout=1)
            self.assertEqual(src, "local")
            self.assertEqual(got[0]["id"], "9527")
        finally:
            os.remove(local)


# ---------- 指標抽取 ----------
class TestMetrics(unittest.TestCase):
    def test_metrics_from_revenue_yoy_and_avg12(self):
        rows = [{"revenue_year": 2024, "revenue_month": m, "revenue": 100} for m in range(1, 13)]
        rows += [{"revenue_year": 2025, "revenue_month": m, "revenue": 110} for m in range(1, 13)]
        rows += [{"revenue_year": 2026, "revenue_month": m, "revenue": 130} for m in range(1, 4)]
        m = picks.metrics_from_revenue(pd.DataFrame(rows))
        self.assertAlmostEqual(m["revenue_yoy"], 18.18, places=1)  # 130/110
        self.assertIsNotNone(m["avg12_yoy"])
        self.assertGreater(m["avg3_yoy"], m["avg12_yoy"])  # 近期加速

    def test_metrics_from_valuation_percentile(self):
        df = pd.DataFrame({"date": pd.date_range("2021-01-01", periods=5).strftime("%Y-%m-%d"),
                           "PER": [20, 18, 16, 14, 12], "PBR": [3, 2.8, 2.6, 2.4, 2.2],
                           "dividend_yield": [2, 2, 2, 2, 4.0]})
        m = picks.metrics_from_valuation(df)
        self.assertEqual(m["per_pctile"], 0.0)
        self.assertEqual(m["div_yield"], 4.0)


# ---------- generate_picks 端到端（離線注入）----------
class TestGeneratePicksOffline(unittest.TestCase):
    def _fetch_fn(self, method, stock_id=None, start_date=None, **kw):
        if method == "taiwan_stock_daily":
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
                            "support_ma20": 100.0, "recent_high20": 140.0, "risk_flags": []}],
            universe=[{"id": "2308", "name": "台達電"}, {"id": "1101", "name": "台泥"}])
        jsonschema.validate(block, PICKS_SCHEMA)
        pools = block["pools"]
        self.assertLessEqual(len(pools["actionable"]) + len(pools["on_deck"]), 4)
        self.assertLessEqual(len(pools["research"]), 5)
        self.assertIn("roster", stats)
        self.assertEqual(stats["opp_source"], "injected")

    def test_end_to_end_banned_gate(self):
        eg = {"new_position": "禁止新增部位", "risk_temp": 9}
        block, results, stats = picks.generate_picks(
            eg, results={}, profile={"core_holdings": []},
            fetch_fn=self._fetch_fn, analyze_fn=self._analyze_fn,
            opportunities=[], universe=[{"id": "2308", "name": "台達電"}])
        self.assertEqual(block["pools"]["actionable"], [])
        self.assertEqual(block["gate"], "禁止新增部位")
        jsonschema.validate(block, PICKS_SCHEMA)


if __name__ == "__main__":
    unittest.main()
