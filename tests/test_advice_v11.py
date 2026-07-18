"""v1.1 增補欄位測試：advice 雙版建議＋plan 階梯、defense_explain、exposure_guidance、
events、track_stats、六角色人話化。每欄位 ≥2 case（正常＋degrade），含一致性與 15% 錨點驗證。
純函式、離線（不打網路）。"""
import json
import os
import tempfile
import unittest

import jsonschema

from warroom.primary_decision import (
    build_advice, build_defense_explain, generate_roles,
    _executable_anchors, _text_direction, _ACTION_DIR, _MAX_ENTRY_DISTANCE,
)
from warroom.build_snapshots import (
    build_exposure_guidance, build_events, build_track_stats, build_all,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY_SCHEMA = json.load(open(os.path.join(REPO_ROOT, "schema", "daily.schema.json"), encoding="utf-8"))
STOCK_SCHEMA = json.load(open(os.path.join(REPO_ROOT, "schema", "stock.schema.json"), encoding="utf-8"))

# 2330 現況錨點：現價 2290、防守 2106.8、MA20 2428.2 / MA60 2323.8 / MA120 2094.3
TECH_2330 = ["收盤 2290.0", "MA20 2428.2", "MA60 2323.8", "MA120 2094.3"]
# 2454 現況：現價 3370、MA20 4063.2（+20.6%，>15% 應被排除）、MA60 3809.4（+13%，可用）
TECH_2454 = ["收盤 3370.0", "MA20 4063.2", "MA60 3809.4", "MA120 2754.1"]


# ---------- advice 雙版建議 ----------
class TestAdvice(unittest.TestCase):
    def test_holder_plan_normal_has_prices_and_ratios(self):
        adv = build_advice(action="續抱", reason_codes=["chips_broken", "trend_mixed"],
                           price=2290.0, defense_price=2106.8, tech_facts=TECH_2330,
                           entry_condition=None, is_core_holding=True)
        plan = adv["holder"]["plan"]
        self.assertGreaterEqual(len(plan), 2)
        # 每條 trigger 含具體價位、每條 act 含比例或金額語意
        self.assertTrue(any("2,107" in p["trigger"] for p in plan))
        self.assertTrue(any("1/2" in p["act"] or "全部出場" in p["act"] for p in plan))
        # 核心持股：holder act 一律註明核心不動
        self.assertTrue(all("核心不動" in p["act"] for p in plan))
        self.assertIn("核心不動", adv["holder"]["action_text"])

    def test_nonholder_entry_uses_nearest_executable_ma(self):
        adv = build_advice(action="觀望", reason_codes=["trend_mixed", "chips_weak"],
                           price=3370.0, defense_price=2875.8, tech_facts=TECH_2454,
                           entry_condition={"price": 3809.4, "condition": "站回 MA60 且法人連 2 日買超"},
                           is_core_holding=False)
        non = adv["nonholder"]
        self.assertIn("站回 MA60 3,809", non["action_text"])
        self.assertEqual(len(non["plan"]), 1)
        self.assertIn("試單 10 萬", non["plan"][0]["act"])

    def test_degrade_no_anchors_still_returns_both_versions(self):
        # 防守價太遠（>15%）、無 MA facts → 無可用錨點，但仍給雙版且不炸
        adv = build_advice(action="觀望", reason_codes=["data_insufficient"],
                           price=100.0, defense_price=50.0, tech_facts=["收盤 100.0"],
                           entry_condition=None, is_core_holding=False)
        self.assertIn("holder", adv)
        self.assertIn("nonholder", adv)
        self.assertEqual(adv["holder"]["plan"], [])  # 無可執行錨點 → 空 plan，不編價位

    def test_plan_anchors_within_15pct(self):
        # 15% 錨點紀律：>15% 的 MA20 4063 不得出現在任何 plan trigger，MA60 3809 可用
        adv = build_advice(action="續抱", reason_codes=["trend_mixed"],
                           price=3370.0, defense_price=2875.8, tech_facts=TECH_2454,
                           entry_condition=None, is_core_holding=False)
        all_triggers = " ".join(p["trigger"] for p in
                                adv["holder"]["plan"] + adv["nonholder"]["plan"])
        self.assertNotIn("4,063", all_triggers)
        # _executable_anchors 只回 ≤15% 的錨
        anchors = _executable_anchors(3370.0, TECH_2454, 2875.8)
        for a in anchors:
            self.assertLessEqual(abs(a["price"] / 3370.0 - 1), _MAX_ENTRY_DISTANCE + 1e-9)
        labels = {a["label"] for a in anchors}
        self.assertIn("MA60", labels)
        self.assertNotIn("MA20", labels)  # 4063 距現價 20.6% 被排除

    def test_holder_action_text_direction_matches_action(self):
        # 一致性：holder action_text 動詞方向與 action 同向（6 種 action 全覆蓋）
        for action in ("加碼", "續抱", "試單", "觀望", "減碼", "出場"):
            adv = build_advice(action=action, reason_codes=["trend_ok"],
                               price=2290.0, defense_price=2106.8, tech_facts=TECH_2330,
                               entry_condition=None, is_core_holding=False)
            self.assertEqual(_text_direction(adv["holder"]["action_text"]),
                             _ACTION_DIR[action], f"{action} 方向打架")


# ---------- defense_explain ----------
class TestDefenseExplain(unittest.TestCase):
    def test_atr_clamped_describes_real_anchor(self):
        # 如實描述 stop_reference：basis=ATR、clamped=True
        s = build_defense_explain(2106.8, {"basis": "ATR", "clamped": True})
        self.assertIn("2,107", s)
        self.assertIn("2×ATR", s)
        self.assertIn("停損帶", s)
        self.assertIn("跌破", s)

    def test_ma_not_clamped(self):
        s = build_defense_explain(2875.8, {"basis": "近20日低", "clamped": False})
        self.assertIn("近 20 日低點", s)
        self.assertIn("停損帶內", s)

    def test_degrade_no_defense_price(self):
        s = build_defense_explain(None, None)
        self.assertIn("資料不足", s)


# ---------- exposure_guidance ----------
class TestExposureGuidance(unittest.TestCase):
    def test_rule_table_tiers(self):
        cases = {1: (80, "可正常布局"), 3: (80, "可正常布局"),
                 4: (60, "僅限試單"), 6: (60, "僅限試單"),
                 7: (50, "僅限試單"), 8: (50, "僅限試單"),
                 9: (40, "禁止新增部位"), 10: (40, "禁止新增部位")}
        for rt, (mx, npos) in cases.items():
            g = build_exposure_guidance(rt)
            self.assertEqual(g["max_equity_pct"], mx)
            self.assertEqual(g["min_cash_pct"], 100 - mx)
            self.assertEqual(g["new_position"], npos)
            self.assertIn(str(rt), g["note"])

    def test_high_risk_note_matches_contract(self):
        g = build_exposure_guidance(9)
        self.assertIn("現金至少留六成", g["note"])
        self.assertIn("不開新倉", g["note"])


# ---------- events ----------
def _fake_results():
    return {
        "2330": {"name": "台積電", "evidence": {"events": []}},
        "2454": {"name": "聯發科",
                 "evidence": {"events": [{"date": "2026-07-20", "label": "除息", "impact_note": ""}]}},
    }


class TestEvents(unittest.TestCase):
    def test_calendar_and_per_stock_within_window(self):
        with tempfile.TemporaryDirectory() as d:
            cal = os.path.join(d, "latest.json")
            json.dump({"events": [
                {"id": "2330", "name": "台積電", "date": "2026-07-22", "type": "法說會"},
                {"id": "2330", "name": "台積電", "date": "2026-07-10", "type": "法說會"},  # 過去，濾掉
                {"id": "9999", "name": "非追蹤", "date": "2026-07-22", "type": "法說會"},  # 非追蹤，濾掉
            ]}, open(cal, "w"))
            evs = build_events(_fake_results(), today="2026-07-18", calendar_path=cal)
        dates = [(e["id"], e["date"], e["type"]) for e in evs]
        self.assertIn(("2330", "2026-07-22", "earnings"), dates)   # 來源①法說
        self.assertIn(("2454", "2026-07-20", "ex_dividend"), dates)  # 來源②除息
        self.assertNotIn("9999", [e["id"] for e in evs])  # 非追蹤股不列
        self.assertFalse(any(e["date"] == "2026-07-10" for e in evs))  # 過去事件不列
        self.assertEqual(dates, sorted(dates, key=lambda x: (x[1], x[0])))  # 依日期排序

    def test_degrade_no_calendar_no_events(self):
        evs = build_events(_fake_results(), today="2026-08-01",
                           calendar_path="/nonexistent/latest.json")
        self.assertEqual(evs, [])  # 抓不到就空，不編


# ---------- track_stats ----------
def _log_entry(date, r5=None, r20=None, r60=None):
    return {"date": date, "stock_id": "2330", "rating": "續抱", "price": 100.0,
            "outcome": {"r5": r5, "r20": r20, "r60": r60}}


class TestTrackStats(unittest.TestCase):
    def test_small_sample_rate_null_and_refill_date(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            json.dump([_log_entry("2026-07-15"), _log_entry("2026-07-17")], open(p, "w"))
            st = build_track_stats(p)
        self.assertEqual(st["n"], 2)
        self.assertEqual(st["closed"], 0)
        self.assertIsNone(st["hit_rate_5d"])
        self.assertIn("2026-07-22", st["note"])  # 最早 pending 2026-07-15 +7 曆日

    def test_closed_sample_computes_hit_rate(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            entries = [_log_entry(f"2026-06-{10+i:02d}", r5=(3.0 if i < 4 else -1.0),
                                  r20=2.0, r60=-1.0) for i in range(5)]
            json.dump(entries, open(p, "w"))
            st = build_track_stats(p)
        self.assertEqual(st["n"], 5)
        self.assertEqual(st["closed"], 5)
        self.assertEqual(st["hit_rate_5d"], 0.8)   # 4/5 為正
        self.assertEqual(st["hit_rate_20d"], 1.0)  # 5/5 為正
        self.assertEqual(st["hit_rate_60d"], 0.0)  # 0/5 為正
        self.assertIn("已結算", st["note"])

    def test_degrade_missing_log(self):
        st = build_track_stats("/nonexistent/log.json")
        self.assertEqual(st["n"], 0)
        self.assertIsNone(st["hit_rate_5d"])


# ---------- 六角色人話化 ----------
class TestRoles(unittest.TestCase):
    LF = {"fundamental": ["營收YoY +67.9%", "PER 30.8"],
          "technical": ["MA20 2428.2", "MA60 2323.8"],
          "chips": ["近5日法人淨額(張) -55,026", "連續方向天數 賣 7 天"]}

    def test_six_roles_with_full_sentences(self):
        roles = generate_roles(["trend_mixed", "fundamental_ok", "chips_broken",
                                "valuation_very_expensive"], self.LF, "續抱")
        names = [r["role"] for r in roles]
        for expected in ("技術面分析師", "基本面分析師", "籌碼面分析師",
                         "風控長", "魔鬼代言人", "投資長"):
            self.assertIn(expected, names)
        # 每角色三欄齊全、句子帶標點（非純數字複讀）
        for r in roles:
            self.assertTrue(r["verify"])
            for line in r["support"] + r["oppose"] + r["verify"]:
                self.assertGreater(len(line), 8)

    def test_devil_opposes_bullish_action(self):
        roles = generate_roles(["trend_ok", "fundamental_ok", "chips_broken",
                                "valuation_very_expensive"], self.LF, "續抱")
        devil = next(r for r in roles if r["role"] == "魔鬼代言人")
        txt = " ".join(devil["support"])
        self.assertTrue("出貨" in txt or "尾聲" in txt)  # 對偏多 action 提最強空方反例

    def test_devil_opposes_defensive_action(self):
        roles = generate_roles(["trend_weak", "fundamental_ok", "chips_weak"],
                               self.LF, "出場")
        devil = next(r for r in roles if r["role"] == "魔鬼代言人")
        txt = " ".join(devil["support"])
        self.assertTrue("阿呆谷" in txt or "反彈" in txt or "錯過" in txt)  # 反向唱多

    def test_roles_vary_by_codes(self):
        # 不同 codes 組合 → 文案不同（非每檔股票長一樣）
        r1 = generate_roles(["trend_ok", "fundamental_ok", "chips_ok"], self.LF, "加碼")
        r2 = generate_roles(["trend_weak", "fundamental_broken", "chips_broken"], self.LF, "出場")
        self.assertNotEqual(json.dumps(r1, ensure_ascii=False),
                            json.dumps(r2, ensure_ascii=False))


# ---------- 整合：build_all 過 schema（含新欄位）----------
class TestBuildAllSchema(unittest.TestCase):
    FAKE_MARKET = {
        "taiex": {"close": 22000.0, "change_pct": -1.5},
        "us": [{"id": "SOX", "name": "費城半導體", "change_pct": -2.0},
               {"id": "VIX", "name": "VIX", "change_pct": 12.0}],
        "foreign_net_yi": -200, "trade_date": "2026-07-18",
    }

    def test_daily_and_stocks_pass_schema_with_new_fields(self):
        daily, stocks, _ = build_all(market_inputs=self.FAKE_MARKET)
        jsonschema.validate(daily, DAILY_SCHEMA)
        self.assertIn("exposure_guidance", daily)
        self.assertIn("events", daily)
        self.assertIn("track_stats", daily)
        for sid, detail in stocks.items():
            jsonschema.validate(detail, STOCK_SCHEMA)
            self.assertIn("advice", detail["primary_decision"])
            self.assertIn("defense_explain", detail["primary_decision"])
            self.assertEqual(len(detail["evidence"]["roles"]), 6)


if __name__ == "__main__":
    unittest.main()
