"""build_snapshots.py 測試：離線（不打網路），用 repo 內既有 data/*.json 與合成 fixture
驗 schema 通過、alerts 提取正確、舊格式 graceful degrade。"""
import json
import os
import tempfile
import unittest

import jsonschema

import pandas as pd

from warroom.build_snapshots import (
    build_all, build_alerts_for_stock, build_context, build_core_holdings,
    build_daily, build_evidence, build_forecast_accuracy, build_market_block,
    build_stock_detail, build_track, build_track_stats, build_tracked_entry,
    backfill_forecast_log, backfill_recommendation_log, confirmed_trade_date,
    _max_as_of_date, _load_forecast_log, compute_conclusion, compute_market_status,
    compute_risk_temp, discover_stock_files, is_new_format, load_stock_results,
    update_forecast_log,
    build_today_command, build_today_headline, build_today_action, build_today_todos,
    build_delta, build_exposure_guidance,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY_SCHEMA = json.load(open(os.path.join(REPO_ROOT, "schema", "daily.schema.json"), encoding="utf-8"))
STOCK_SCHEMA = json.load(open(os.path.join(REPO_ROOT, "schema", "stock.schema.json"), encoding="utf-8"))

FAKE_META = {"schema_version": 1, "data_date": "2026-07-18",
             "generated_at": "2026-07-18T14:30:00+08:00", "sources": ["FinMind", "yfinance"]}

FAKE_PROFILE = {
    "core_holdings": ["9999", "0050"],
    "position_tiers": [
        {"name": "空手", "amount": 0}, {"name": "試單", "amount": 100000},
        {"name": "標準", "amount": 200000}, {"name": "加碼", "amount": 400000},
        {"name": "極高信心", "amount": 600000},
    ],
}


def make_fake_res(action="續抱", entry_condition=None, is_core_note=True):
    primary = {
        "action": action, "stance": "中性偏多", "position_delta": "hold",
        "confidence": 62, "decided_by_layer": 4,
        "reason_codes": ["trend_ok", "valuation_expensive"],
        "readable_reason": "因為趨勢仍在，所以續抱不動；但估值偏貴是風險。",
        "risk_note": "跌破 90 防守位就先降波段部位。",
        "position": {"tier": "標準", "tier_amount": 200000, "lots": 1, "odd_shares": 500},
        "defense_price": 90.0,
        "entry_condition": entry_condition,
        "reeval_date": "2026-07-25",
    }
    if is_core_note:
        primary["core_note"] = "此為波段層判斷，不影響定期定額核心部位。"
    return {
        "stock_id": "9999", "name": "測試股",
        "technical": {"ev": {"MA20": 100.5, "MA60": 95.0, "收盤": 101.0}},
        "decision": {"as_of_price": 101.0},
        "primary_decision": primary,
        "context": {
            "timeframes": {
                "short": {"label": "短線 1-4 週", "stance": "中性", "basis": "技術中性＋籌碼偏空"},
                "swing": {"label": "波段 1-3 月（主）", "stance": "中性偏多", "basis": primary["readable_reason"]},
                "mid": {"label": "中期 3-12 月", "stance": "中性", "basis": "基本面中性＋估值偏貴"},
            },
            "lights": {
                "fundamental": {"color": "yellow", "facts": ["營收 YoY +5%"]},
                "technical": {"color": "green", "facts": ["站上均線"]},
                "chips": {"color": None, "facts": []},
            },
            "valuation": {"band": "偏貴", "base": 95.0, "bull": 120.0, "bear": 80.0,
                          "regime": "3y", "warning": None},
            "rr": 1.8,
        },
        "evidence": {
            "roles": [{"role": "技術面分析師", "support": ["站上均線"], "oppose": [], "verify": ["觀察"]}],
            "news": [
                {"title": "測試新聞A", "src": "測試來源", "url": "https://example.com/a",
                 "date": "Wed, 16 Jul 2026 09:00:00 GMT"},
                {"title": "測試新聞B", "source": "已有 source 欄位", "url": "https://example.com/b",
                 "published_at": "2026-07-15T08:00:00+08:00"},
            ],
            "events": [{"date": "2026-07-16", "label": "法說會", "impact_note": "上修展望"}],
        },
    }


# ---------- 大盤三檔規則 ----------
class TestMarketStatusRules(unittest.TestCase):
    def test_bearish_status(self):
        status = compute_market_status(-1.5, -1.3, 12.0, -150)
        self.assertEqual(status, "偏空防禦")
        self.assertEqual(compute_risk_temp(status, -1.5, 12.0), 8)

    def test_bullish_status(self):
        status = compute_market_status(1.5, 1.2, -10.0, 150)
        self.assertEqual(status, "偏多進攻")
        self.assertEqual(compute_risk_temp(status, 1.5, -10.0), 2)

    def test_neutral_status(self):
        status = compute_market_status(0.2, -0.3, 1.0, 10)
        self.assertEqual(status, "中性")
        self.assertEqual(compute_risk_temp(status, 0.2, 1.0), 5)

    def test_missing_signals_default_neutral(self):
        # 全部訊號缺（None）→ 不得編方向，回中性
        self.assertEqual(compute_market_status(None, None, None, None), "中性")

    def test_risk_temp_bounded_1_to_10(self):
        for status in ("偏空防禦", "中性", "偏多進攻"):
            t = compute_risk_temp(status, -5.0, 20.0)
            self.assertGreaterEqual(t, 1)
            self.assertLessEqual(t, 10)

    def test_conclusion_short_and_covers_all_status(self):
        for status in ("偏多進攻", "中性", "偏空防禦"):
            c = compute_conclusion(status)
            self.assertTrue(0 < len(c) <= 20, f"{status} 結論過長：{c!r}（{len(c)} 字）")

    def test_build_market_block_shape(self):
        inputs = {
            "taiex": {"close": 42671.3, "change_pct": -6.47},
            "us": [{"id": "SPX", "name": "S&P 500", "change_pct": -1.0},
                   {"id": "NDX", "name": "Nasdaq 100", "change_pct": -1.5},
                   {"id": "SOX", "name": "費城半導體", "change_pct": -1.6},
                   {"id": "VIX", "name": "VIX", "change_pct": 12.0}],
            "foreign_net_yi": -300,
        }
        block = build_market_block(inputs)
        self.assertEqual(block["status"], "偏空防禦")
        self.assertEqual(block["taiex"]["close"], 42671.3)
        self.assertIsInstance(block["risk_temp"], int)
        self.assertTrue(block["conclusion"])


# ---------- 個股 data/<id>.json 發現與 graceful degrade ----------
class TestDiscoverAndDegrade(unittest.TestCase):
    def test_discover_stock_files_only_numeric_stems(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "2330.json"), "w").write("{}")
            open(os.path.join(d, "investor_profile.json"), "w").write("{}")
            open(os.path.join(d, "2330.narration.json"), "w").write("{}")
            open(os.path.join(d, "recommendation_log.json"), "w").write("[]")
            found = discover_stock_files(d)
            self.assertEqual(set(found), {"2330"})

    def test_is_new_format(self):
        self.assertTrue(is_new_format(make_fake_res()))
        self.assertFalse(is_new_format({"stock_id": "8888", "name": "舊股"}))
        self.assertFalse(is_new_format(None))

    def test_load_stock_results_skips_old_format_without_crashing(self):
        with tempfile.TemporaryDirectory() as d:
            new_path = os.path.join(d, "9999.json")
            old_path = os.path.join(d, "8888.json")
            bad_path = os.path.join(d, "7777.json")
            json.dump(make_fake_res(), open(new_path, "w", encoding="utf-8"))
            json.dump({"stock_id": "8888", "name": "舊股", "decision": {}}, open(old_path, "w", encoding="utf-8"))
            open(bad_path, "w", encoding="utf-8").write("{not valid json")

            files = discover_stock_files(d)
            self.assertEqual(set(files), {"9999", "8888", "7777"})
            results, skipped = load_stock_results(files)

            self.assertEqual(set(results), {"9999"})
            skipped_ids = {sid for sid, _ in skipped}
            self.assertEqual(skipped_ids, {"8888", "7777"})
            # 缺欄位與讀檔失敗要給不同、可辨識的理由
            reasons = dict(skipped)
            self.assertIn("舊格式", reasons["8888"])
            self.assertIn("讀檔失敗", reasons["7777"])


# ---------- tracked / alerts 提取 ----------
class TestTrackedAndAlerts(unittest.TestCase):
    def test_tracked_entry_derives_from_primary_decision(self):
        res = make_fake_res()
        entry = build_tracked_entry("9999", res)
        self.assertEqual(entry["decision"]["action"], "續抱")
        self.assertEqual(entry["decision"]["defense_price"], 90.0)
        self.assertEqual(entry["close"], 101.0)
        self.assertIsNone(entry["change_pct"])  # 已知缺口：見模組說明

    def test_alerts_defense_only_when_no_entry_condition(self):
        res = make_fake_res(entry_condition=None)
        alerts = build_alerts_for_stock("9999", "測試股", res["primary_decision"])
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0], {"id": "9999", "name": "測試股", "type": "defense",
                                     "price": 90.0, "direction": "below", "source": "tracked"})

    def test_alerts_include_entry_when_present(self):
        res = make_fake_res(action="觀望",
                            entry_condition={"price": 110.0, "condition": "站回月線"})
        alerts = build_alerts_for_stock("9999", "測試股", res["primary_decision"])
        types = {a["type"] for a in alerts}
        self.assertEqual(types, {"defense", "entry"})
        entry_alert = next(a for a in alerts if a["type"] == "entry")
        self.assertEqual(entry_alert["price"], 110.0)
        self.assertEqual(entry_alert["direction"], "above")

    def test_core_holdings_tracked_vs_untracked(self):
        results = {"9999": make_fake_res()}
        holdings = build_core_holdings(FAKE_PROFILE, results)
        by_id = {h["id"]: h for h in holdings}
        self.assertEqual(by_id["9999"]["action"], "核心續扣")
        self.assertEqual(by_id["9999"]["note"], "波段不加碼")
        self.assertEqual(by_id["0050"]["name"], "元大台灣50")
        self.assertEqual(by_id["0050"]["action"], "定期定額照常")


# ---------- context / evidence 轉換 ----------
class TestContextEvidence(unittest.TestCase):
    def test_context_color_passthrough_and_null_for_na(self):
        ctx = make_fake_res()["context"]
        out = build_context(ctx)
        self.assertEqual(out["lights"]["fundamental"]["color"], "yellow")
        self.assertEqual(out["lights"]["technical"]["color"], "green")
        self.assertIsNone(out["lights"]["chips"]["color"])  # na → null，不得編色

    def test_evidence_news_maps_src_and_parses_date(self):
        ev = make_fake_res()["evidence"]
        out = build_evidence(ev)
        a, b = out["news"]
        self.assertEqual(a["source"], "測試來源")          # src → source
        self.assertTrue(a["published_at"])                 # RFC822 轉出非空字串
        self.assertNotEqual(a["published_at"], "Wed, 16 Jul 2026 09:00:00 GMT")
        self.assertEqual(b["source"], "已有 source 欄位")   # 已是 source 欄位時原樣用
        self.assertEqual(b["published_at"], "2026-07-15T08:00:00+08:00")


# ---------- track（recommendation_log.json）----------
class TestBuildTrack(unittest.TestCase):
    def test_track_skips_missing_price_and_maps_status(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "recommendation_log.json")
            log = [
                {"date": "2026-07-15", "stock_id": "9999", "price": 101.0, "rating": "續抱",
                 "outcome": {"r5": None, "r20": None, "r60": None, "hit": None}},
                {"date": "2026-07-10", "stock_id": "9999", "price": 99.0, "rating": "試單",
                 "outcome": {"r5": 0.02, "r20": 0.05, "r60": None, "hit": "target"}},
                {"date": "2026-07-05", "stock_id": "9999", "price": None, "rating": "觀望",
                 "outcome": {"r5": None, "r20": None, "r60": None, "hit": None}},
                {"date": "2026-07-14", "stock_id": "0000", "price": 50.0, "rating": "續抱",
                 "outcome": {"r5": None, "r20": None, "r60": None, "hit": None}},
            ]
            json.dump(log, open(log_path, "w", encoding="utf-8"))
            track = build_track("9999", log_path=log_path)
            self.assertEqual(len(track), 2)   # price=None 的一筆被跳過
            self.assertEqual(track[0]["date"], "2026-07-15")  # 依日期新到舊排序
            self.assertEqual(track[0]["status"], "pending")
            self.assertEqual(track[1]["status"], "done")

    def test_track_missing_log_file_returns_empty(self):
        self.assertEqual(build_track("9999", log_path="/no/such/path.json"), [])


# ---------- 端到端：合成資料整批組裝 + schema 驗證 ----------
class TestBuildAllSynthetic(unittest.TestCase):
    def _build(self, results):
        market_block = build_market_block({
            "taiex": {"close": 45000.0, "change_pct": -1.5},
            "us": [{"id": "SPX", "name": "S&P 500", "change_pct": -1.0},
                   {"id": "NDX", "name": "Nasdaq 100", "change_pct": -1.2},
                   {"id": "SOX", "name": "費城半導體", "change_pct": -1.8},
                   {"id": "VIX", "name": "VIX", "change_pct": 9.0}],
            "foreign_net_yi": -200,
        })
        daily = build_daily(FAKE_PROFILE, results, FAKE_META, market_block)
        stock_details = {sid: build_stock_detail(sid, res, FAKE_PROFILE, FAKE_META)
                         for sid, res in results.items()}
        return daily, stock_details

    def test_synthetic_daily_and_stock_pass_schema(self):
        results = {"9999": make_fake_res()}
        daily, stock_details = self._build(results)
        jsonschema.validate(daily, DAILY_SCHEMA)
        jsonschema.validate(stock_details["9999"], STOCK_SCHEMA)
        self.assertEqual(daily["tracked"][0]["id"], "9999")
        self.assertTrue(daily["market"]["conclusion"])

    def test_synthetic_watch_stock_without_full_report_is_omitted_not_fabricated(self):
        # 沒有完整報告的股票不應出現在 tracked（目前無 watchlist 資料源，watch 保守回空陣列）
        daily, _ = self._build({"9999": make_fake_res()})
        self.assertEqual(daily["watch"], [])
        ids = {t["id"] for t in daily["tracked"]}
        self.assertNotIn("8888", ids)


# ---------- 端到端：repo 內既有資料（離線，market_inputs 用固定 dict）----------
class TestBuildAllRealData(unittest.TestCase):
    """用 repo 內既有 data/*.json 跑，不打網路（market_inputs 固定注入）。"""

    OFFLINE_MARKET_INPUTS = {
        "taiex": {"close": 45000.0, "change_pct": -0.8},
        "us": [{"id": "SPX", "name": "S&P 500", "change_pct": -0.5},
               {"id": "NDX", "name": "Nasdaq 100", "change_pct": -0.6},
               {"id": "SOX", "name": "費城半導體", "change_pct": -0.9},
               {"id": "VIX", "name": "VIX", "change_pct": 3.0}],
        "foreign_net_yi": -50,
    }

    @classmethod
    def setUpClass(cls):
        cls.daily, cls.stock_details, cls.skipped = build_all(
            data_dir=os.path.join(REPO_ROOT, "data"),
            market_inputs=cls.OFFLINE_MARKET_INPUTS)

    def test_daily_passes_schema(self):
        jsonschema.validate(self.daily, DAILY_SCHEMA)

    def test_every_built_stock_detail_passes_schema(self):
        self.assertGreater(len(self.stock_details), 0,
                            "repo 內至少要有一檔新格式 data/<id>.json（本次驗收前應已跑過 "
                            "python3 -m warroom.analyze_tw 2330）")
        for sid, detail in self.stock_details.items():
            jsonschema.validate(detail, STOCK_SCHEMA)

    def test_old_format_stocks_are_skipped_not_crashed(self):
        # 不論這次 repo 內有幾檔舊格式，degrade 都不該讓整批 build 掛掉（此處已成功跑到這行）
        for sid, reason in self.skipped:
            self.assertIsInstance(sid, str)
            self.assertTrue(reason)

    def test_market_conclusion_nonempty(self):
        self.assertTrue(self.daily["market"]["conclusion"])
        self.assertLessEqual(len(self.daily["market"]["conclusion"]), 20)


# ---------- 修復 1：戰績回填接進管線 ----------
class TestBackfillRecommendationLog(unittest.TestCase):
    def _pending_entry(self, date="2026-06-01"):
        return {"date": date, "stock_id": "2330", "name": "台積電", "price": 100.0,
                "rating": "買進", "fair_base": 120.0, "stop": 90.0, "rr": 2.0,
                "outcome": {"r5": None, "r20": None, "r60": None, "hit": None,
                            "hit_days": None, "max_drawdown": None}}

    def test_backfill_fills_outcome_and_closed_reflects(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "recommendation_log.json")
            json.dump([self._pending_entry()], open(p, "w", encoding="utf-8"))

            def price_lookup(sid):
                rows = [{"date": f"2026-06-{2+i:02d}", "close": 100.0 + i,
                         "max": 101.0 + i, "min": 99.0 + i} for i in range(10)]
                return pd.DataFrame(rows)

            out = backfill_recommendation_log(p, price_lookup=price_lookup, div_lookup=None)
            self.assertIsNotNone(out[0]["outcome"]["r5"])   # r5 已回填
            # build_track_stats 的 closed 隨回填後的 log 更新（原本永遠 0）
            stats = build_track_stats(log_path=p)
            self.assertEqual(stats["closed"], 1)

    def test_backfill_corrupt_log_fail_closed_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "recommendation_log.json")
            broken = "{壞掉的 json,,,"
            with open(p, "w", encoding="utf-8") as f:
                f.write(broken)
            import warnings
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                out = backfill_recommendation_log(p, price_lookup=lambda sid: None)
            self.assertIsNone(out)
            self.assertTrue(any("recommendation_log" in str(w.message) for w in caught))
            self.assertEqual(open(p, encoding="utf-8").read(), broken)  # 原檔沒被覆寫


# ---------- 修復 7：forecast_log fail-closed ----------
class TestForecastLogFailClosed(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(_load_forecast_log("/no/such/forecast_log.json"), [])

    def test_corrupt_file_raises_not_silently_empty(self):
        # 修復 7／Y2：壞檔不得回 []（否則 main() 會無條件覆寫、清空歷史），改往上拋讓
        # main() fail-closed（警告＋跳過寫入）。
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "forecast_log.json")
            with open(p, "w", encoding="utf-8") as f:
                f.write("{壞掉的 json,,,")
            with self.assertRaises(Exception):
                _load_forecast_log(p)


# ---------- 修復 13：data_date fallback ----------
class TestDataDateFallback(unittest.TestCase):
    def test_max_as_of_date(self):
        results = {"a": {"as_of_date": "2026-07-16"}, "b": {"as_of_date": "2026-07-17"},
                   "c": {}}  # 缺 as_of_date 的忽略
        self.assertEqual(_max_as_of_date(results), "2026-07-17")
        self.assertIsNone(_max_as_of_date({}))

    def test_confirmed_trade_date_prefers_market(self):
        self.assertEqual(confirmed_trade_date({"trade_date": "2026-07-18"}), "2026-07-18")

    def test_confirmed_trade_date_none_when_no_market_and_no_data(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(confirmed_trade_date({}, data_dir=d))

    def test_build_all_meta_falls_back_to_as_of_when_no_trade_date(self):
        # market_inputs 無 trade_date → meta.data_date 退所有個股 as_of 最大值，非「今天」。
        market_inputs = dict(TestBuildAllRealData.OFFLINE_MARKET_INPUTS)
        market_inputs.pop("trade_date", None)
        daily, _, _ = build_all(data_dir=os.path.join(REPO_ROOT, "data"),
                                market_inputs=market_inputs)
        results, _ = load_stock_results(discover_stock_files(os.path.join(REPO_ROOT, "data")))
        self.assertEqual(daily["meta"]["data_date"], _max_as_of_date(results))


# ---------- v1.8 大盤作戰區：build_all 掛載 ----------
class TestMarketBattleMount(unittest.TestCase):
    """market_battle 由 build_all() 事後掛到 daily（不進 build_daily 簽章，跟 delta/picks
    同款掛法，見 warroom/build_snapshots.py build_all 內註解）。"""

    def _taiex_df(self, n=200, base=20000.0, seed=3):
        import numpy as np
        rng = np.random.default_rng(seed)
        rets = rng.normal(0, 0.008, size=n)
        closes = base * np.exp(np.cumsum(rets))
        dates = pd.bdate_range("2024-01-01", periods=n).strftime("%Y-%m-%d")
        return pd.DataFrame([
            {"date": d, "open": float(c) * 0.999, "max": float(c) * 1.004,
             "min": float(c) * 0.996, "close": float(c)}
            for d, c in zip(dates, closes)
        ])

    def test_absent_market_battle_inputs_degrades_to_null(self):
        # 沿用既有（本測試檔既有的）OFFLINE_MARKET_INPUTS fixture，本來就不帶
        # market_battle 子欄位（舊格式/抓取全失敗的寫照）——daily.market_battle 該是
        # None，且整份 daily 仍照舊通過 schema（回歸保護：新增欄位不能破壞舊呼叫端）。
        daily, _, _ = build_all(data_dir=os.path.join(REPO_ROOT, "data"),
                                market_inputs=TestBuildAllRealData.OFFLINE_MARKET_INPUTS)
        self.assertIsNone(daily["market_battle"])
        jsonschema.validate(daily, DAILY_SCHEMA)

    def test_wired_market_battle_populates_and_passes_schema(self):
        market_inputs = dict(TestBuildAllRealData.OFFLINE_MARKET_INPUTS)
        market_inputs["market_battle"] = {
            "taiex_df": self._taiex_df(),
            "foreign_df": None,
            "leading_sectors": ["軍工航太", "封裝測試"],
        }
        daily, _, _ = build_all(data_dir=os.path.join(REPO_ROOT, "data"),
                                market_inputs=market_inputs)
        jsonschema.validate(daily, DAILY_SCHEMA)
        battle = daily["market_battle"]
        self.assertIsNotNone(battle)
        self.assertEqual(battle["flow"]["leading_sectors"], ["軍工航太", "封裝測試"])

    def test_bull_action_gate_matches_daily_exposure_guidance(self):
        # 風險溫度 9（禁止新增部位）情境：market_battle 劇本的 bull action 不得出現
        # 「回補試單」（大檢查・邏輯組同款 gate 一致性，見契約 v1.8「action 用曝險語言…
        # 需與 exposure_guidance.new_position 一致」）。
        bearish_inputs = {
            "taiex": {"close": 20000.0, "change_pct": -2.5},
            "us": [{"id": "SPX", "name": "S&P 500", "change_pct": -2.0},
                   {"id": "NDX", "name": "Nasdaq 100", "change_pct": -2.2},
                   {"id": "SOX", "name": "費城半導體", "change_pct": -2.5},
                   {"id": "VIX", "name": "VIX", "change_pct": 12.0}],
            "foreign_net_yi": -300, "trade_date": "2026-07-18",
            "market_battle": {"taiex_df": self._taiex_df(), "foreign_df": None,
                              "leading_sectors": []},
        }
        daily, _, _ = build_all(data_dir=os.path.join(REPO_ROOT, "data"),
                                market_inputs=bearish_inputs)
        self.assertEqual(daily["exposure_guidance"]["new_position"], "禁止新增部位")
        battle = daily["market_battle"]
        self.assertIsNotNone(battle)
        scenarios = battle["scenarios"]
        if scenarios.get("status") == "ok":
            bull = next(sc for sc in scenarios["scenarios"] if sc["id"] == "bull")
            self.assertNotIn("回補試單", bull["action"]["text"])


# ---------- schema 檔本身要是合法 draft-07 ----------
class TestSchemasAreValidDraft7(unittest.TestCase):
    def test_schemas_check_out(self):
        jsonschema.Draft7Validator.check_schema(DAILY_SCHEMA)
        jsonschema.Draft7Validator.check_schema(STOCK_SCHEMA)


# ---------- v1.3 forecast_log 準確度管線 ----------
FAKE_FORECAST = {
    "week_range_70": [95.0, 105.0],
    "horizons": {
        "m1": {"days": 21, "prob_range_70": [90.0, 110.0]},
        "m3": {"days": 63, "prob_range_70": [80.0, 120.0]},
        "m6": {"days": 126, "prob_range_70": [70.0, 130.0]},
    },
}


class TestUpdateForecastLog(unittest.TestCase):
    def test_append_new_entry(self):
        log = update_forecast_log([], "9999", FAKE_FORECAST, "2026-07-18")
        self.assertEqual(len(log), 1)
        e = log[0]
        self.assertEqual(e["date"], "2026-07-18")
        self.assertEqual(e["stock_id"], "9999")
        self.assertEqual(e["week"], [95.0, 105.0])
        self.assertEqual(e["m1"], [90.0, 110.0])
        self.assertEqual(e["m3"], [80.0, 120.0])
        self.assertIsNone(e["week_hit"])
        self.assertIsNone(e["m1_hit"])
        self.assertIsNone(e["m3_hit"])

    def test_same_date_and_stock_overwrites_not_duplicates(self):
        log = update_forecast_log([], "9999", FAKE_FORECAST, "2026-07-18")
        newer = {**FAKE_FORECAST, "week_range_70": [96.0, 106.0]}
        log = update_forecast_log(log, "9999", newer, "2026-07-18")
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["week"], [96.0, 106.0])

    def test_different_date_appends_new_entry(self):
        log = update_forecast_log([], "9999", FAKE_FORECAST, "2026-07-18")
        log = update_forecast_log(log, "9999", FAKE_FORECAST, "2026-07-19")
        self.assertEqual(len(log), 2)

    def test_none_forecast_skipped(self):
        log = update_forecast_log([], "9999", None, "2026-07-18")
        self.assertEqual(log, [])

    def test_forecast_missing_horizon_range_skipped(self):
        broken = {"week_range_70": [95.0, 105.0], "horizons": {}}
        log = update_forecast_log([], "9999", broken, "2026-07-18")
        self.assertEqual(log, [])


class TestBackfillForecastLog(unittest.TestCase):
    # entry 日 2026-07-18 起 94 天＝2026-10-20，超過三個 horizon 的日期門檻（週19 這裡指
    # week/m1/m3 分別 7/30/89 曆日），供「已到期」情境測試用；門檻本身另有專屬測試。
    _ELIGIBLE_TODAY = "2026-10-20"

    def test_close_within_range_marks_hit_true(self):
        log = [{"date": "2026-07-18", "stock_id": "9999", "week": [95.0, 105.0],
               "m1": [90.0, 110.0], "m3": [80.0, 120.0],
               "week_hit": None, "m1_hit": None, "m3_hit": None}]
        lookup = lambda sid, date, n_days: 100.0  # 落在三個區間內
        out = backfill_forecast_log(log, price_lookup=lookup, today=self._ELIGIBLE_TODAY)
        self.assertTrue(out[0]["week_hit"])
        self.assertTrue(out[0]["m1_hit"])
        self.assertTrue(out[0]["m3_hit"])

    def test_close_outside_range_marks_hit_false(self):
        log = [{"date": "2026-07-18", "stock_id": "9999", "week": [95.0, 105.0],
               "m1": [90.0, 110.0], "m3": [80.0, 120.0],
               "week_hit": None, "m1_hit": None, "m3_hit": None}]
        lookup = lambda sid, date, n_days: 200.0  # 三個區間都落外
        out = backfill_forecast_log(log, price_lookup=lookup, today=self._ELIGIBLE_TODAY)
        self.assertFalse(out[0]["week_hit"])
        self.assertFalse(out[0]["m1_hit"])
        self.assertFalse(out[0]["m3_hit"])

    def test_range_boundary_inclusive_counts_as_hit(self):
        log = [{"date": "2026-07-18", "stock_id": "9999", "week": [95.0, 105.0],
               "m1": [90.0, 110.0], "m3": [80.0, 120.0],
               "week_hit": None, "m1_hit": None, "m3_hit": None}]
        lookup = lambda sid, date, n_days: 105.0  # week 上界，含端點
        out = backfill_forecast_log(log, price_lookup=lookup, today=self._ELIGIBLE_TODAY)
        self.assertTrue(out[0]["week_hit"])

    def test_lookup_returns_none_leaves_pending_for_next_run(self):
        log = [{"date": "2026-07-18", "stock_id": "9999", "week": [95.0, 105.0],
               "m1": [90.0, 110.0], "m3": [80.0, 120.0],
               "week_hit": None, "m1_hit": None, "m3_hit": None}]
        lookup = lambda sid, date, n_days: None  # 還沒到期／抓不到
        out = backfill_forecast_log(log, price_lookup=lookup, today=self._ELIGIBLE_TODAY)
        self.assertIsNone(out[0]["week_hit"])
        self.assertIsNone(out[0]["m1_hit"])
        self.assertIsNone(out[0]["m3_hit"])

    def test_already_filled_hit_not_recomputed(self):
        log = [{"date": "2026-07-18", "stock_id": "9999", "week": [95.0, 105.0],
               "m1": [90.0, 110.0], "m3": [80.0, 120.0],
               "week_hit": True, "m1_hit": None, "m3_hit": None}]
        calls = []

        def lookup(sid, date, n_days):
            calls.append(n_days)
            return 100.0

        backfill_forecast_log(log, price_lookup=lookup, today=self._ELIGIBLE_TODAY)
        self.assertNotIn(5, calls)  # week（5 交易日）已回填過，不該再呼叫

    def test_lookup_exception_does_not_crash_whole_batch(self):
        log = [{"date": "2026-07-18", "stock_id": "9999", "week": [95.0, 105.0],
               "m1": [90.0, 110.0], "m3": [80.0, 120.0],
               "week_hit": None, "m1_hit": None, "m3_hit": None}]

        def boom(sid, date, n_days):
            raise RuntimeError("網路掛了")

        out = backfill_forecast_log(log, price_lookup=boom, today=self._ELIGIBLE_TODAY)  # 不炸
        self.assertIsNone(out[0]["week_hit"])

    # ---- 日期門檻（比照 scenario_log 的 _eligible_for_backfill）----
    def test_not_yet_eligible_skips_api_call(self):
        """進場才 1 天，三個 horizon 都還沒到門檻（week 需 7 曆日）→ 完全不打 price_lookup，
        省掉注定落空的呼叫（2026-07-19 維運檢查抓到的白打問題）。"""
        log = [{"date": "2026-07-18", "stock_id": "9999", "week": [95.0, 105.0],
               "m1": [90.0, 110.0], "m3": [80.0, 120.0],
               "week_hit": None, "m1_hit": None, "m3_hit": None}]
        calls = []

        def lookup(sid, date, n_days):
            calls.append(n_days)
            return 100.0

        out = backfill_forecast_log(log, price_lookup=lookup, today="2026-07-19")
        self.assertEqual(calls, [])
        self.assertIsNone(out[0]["week_hit"])
        self.assertIsNone(out[0]["m1_hit"])
        self.assertIsNone(out[0]["m3_hit"])

    def test_week_eligible_before_m1_and_m3(self):
        """week 門檻 7 天先到，m1（30 天）／m3（89 天）還沒到 → 只打 week 那次呼叫。"""
        log = [{"date": "2026-07-01", "stock_id": "9999", "week": [95.0, 105.0],
               "m1": [90.0, 110.0], "m3": [80.0, 120.0],
               "week_hit": None, "m1_hit": None, "m3_hit": None}]
        calls = []

        def lookup(sid, date, n_days):
            calls.append(n_days)
            return 100.0

        out = backfill_forecast_log(log, price_lookup=lookup, today="2026-07-10")  # 差 9 天
        self.assertEqual(calls, [5])  # 只有 week（5 交易日）達門檻
        self.assertTrue(out[0]["week_hit"])
        self.assertIsNone(out[0]["m1_hit"])
        self.assertIsNone(out[0]["m3_hit"])


class TestBuildForecastAccuracy(unittest.TestCase):
    def _log_with_hits(self, stock_id, hits):
        """hits: bool 或 None 的 list，每個攤成一筆只含一個 _hit 欄位的 entry
        （方便控制樣本數，不受同一筆三個 horizon 綁在一起影響）。"""
        log = []
        for i, h in enumerate(hits):
            log.append({"date": f"2026-07-{i+1:02d}", "stock_id": stock_id,
                        "week": [1, 2], "m1": None, "m3": None,
                        "week_hit": h, "m1_hit": None, "m3_hit": None})
        return log

    def test_below_min_samples_gives_null_rate(self):
        log = self._log_with_hits("9999", [True, False, True])  # 3 筆 < 10
        out = build_forecast_accuracy("9999", log)
        self.assertEqual(out["n_evaluated"], 3)
        self.assertIsNone(out["hit_rate_70"])
        self.assertTrue(out["note"])

    def test_at_least_min_samples_computes_rate(self):
        hits = [True] * 7 + [False] * 3  # 10 筆，7 命中
        log = self._log_with_hits("9999", hits)
        out = build_forecast_accuracy("9999", log)
        self.assertEqual(out["n_evaluated"], 10)
        self.assertEqual(out["hit_rate_70"], 0.7)

    def test_pending_none_entries_not_counted(self):
        hits = [True] * 9 + [None] * 5  # 只有 9 筆已回填，None 不算樣本
        log = self._log_with_hits("9999", hits)
        out = build_forecast_accuracy("9999", log)
        self.assertEqual(out["n_evaluated"], 9)
        self.assertIsNone(out["hit_rate_70"])

    def test_other_stock_entries_excluded(self):
        log = self._log_with_hits("9999", [True] * 10) + self._log_with_hits("8888", [False] * 10)
        out = build_forecast_accuracy("9999", log)
        self.assertEqual(out["n_evaluated"], 10)
        self.assertEqual(out["hit_rate_70"], 1.0)


# ---------- v1.5 today_command ----------
def _tc_res(name, close, defense, action="續抱", reeval_date=None, codes=None):
    return {"name": name, "decision": {"as_of_price": close},
            "primary_decision": {"defense_price": defense, "action": action,
                                 "reeval_date": reeval_date, "reason_codes": codes or []}}


class TestTodayHeadline(unittest.TestCase):
    def test_headline_per_new_position_and_within_25_chars(self):
        for new_pos in ("禁止新增部位", "僅限試單", "可正常布局"):
            eg = {"risk_temp": 8, "new_position": new_pos}
            h = build_today_headline(eg)
            self.assertLessEqual(len(h), 25, f"{new_pos} 標題過長：{h!r}（{len(h)} 字）")
            self.assertIn("8/10", h)

    def test_headline_unknown_new_position_degrades_safely(self):
        h = build_today_headline({"risk_temp": 5, "new_position": "未知值"})
        self.assertTrue(h)
        self.assertLessEqual(len(h), 25)


class TestTodayAction(unittest.TestCase):
    def test_nearest_defense_stock_wins_tier1(self):
        # 甲距防守 8%（不在<5%門檻內）、乙距防守 2%（最急迫）
        results = {
            "甲": _tc_res("甲股", close=108.0, defense=100.0),
            "乙": _tc_res("乙股", close=102.0, defense=100.0),
        }
        action = build_today_action(results)
        self.assertIsNotNone(action)
        self.assertEqual(action["stock_id"], "乙")
        self.assertIn("乙股", action["text"])
        self.assertIn("跌破", action["text"])
        self.assertLessEqual(len(action["text"]), 25)

    def test_exit_action_uses_rebound_template_not_breakdown(self):
        results = {"丙": _tc_res("丙股", close=101.0, defense=100.0, action="出場")}
        action = build_today_action(results)
        self.assertIn("反彈", action["text"])
        self.assertNotIn("跌破", action["text"])

    def test_tier2_reduce_or_exit_when_no_stock_near_defense(self):
        results = {
            "甲": _tc_res("甲股", close=150.0, defense=100.0, action="續抱"),
            "乙": _tc_res("乙股", close=150.0, defense=100.0, action="減碼"),
        }
        action = build_today_action(results)
        self.assertEqual(action["stock_id"], "乙")
        self.assertIn("減碼", action["text"])

    def test_no_action_when_nothing_urgent(self):
        results = {"甲": _tc_res("甲股", close=150.0, defense=100.0, action="續抱")}
        self.assertIsNone(build_today_action(results))


class TestTodayTodos(unittest.TestCase):
    def test_defense_near_sorted_by_distance(self):
        results = {
            "甲": _tc_res("甲股", close=101.0, defense=100.0),   # ~0.99%
            "乙": _tc_res("乙股", close=102.5, defense=100.0),   # ~2.44%
        }
        todos = build_today_todos(results, events=[], next_trading_day=None)
        self.assertEqual(len(todos), 2)
        self.assertEqual(todos[0]["stock_id"], "甲")             # 距離最近排最前
        self.assertEqual(todos[0]["kind"], "defense_near")
        for t in todos:
            self.assertLessEqual(len(t["text"]), 25)

    def test_reeval_due_and_event_tomorrow_included(self):
        results = {"甲": _tc_res("甲股", close=150.0, defense=100.0, reeval_date="2026-07-20")}
        events = [{"date": "2026-07-20", "id": "乙", "name": "乙股", "label": "法說會"}]
        todos = build_today_todos(results, events=events, next_trading_day="2026-07-20")
        kinds = {t["kind"] for t in todos}
        self.assertEqual(kinds, {"reeval_due", "event_tomorrow"})

    def test_capped_at_3_items(self):
        results = {f"s{i}": _tc_res(f"股{i}", close=100.0 + i * 0.1, defense=100.0)
                  for i in range(5)}
        todos = build_today_todos(results, events=[], next_trading_day=None)
        self.assertLessEqual(len(todos), 3)

    def test_no_next_trading_day_only_defense_items(self):
        results = {"甲": _tc_res("甲股", close=101.0, defense=100.0, reeval_date="2026-07-20")}
        todos = build_today_todos(results, events=[{"date": "2026-07-20", "id": "甲",
                                                     "name": "甲股", "label": "法說會"}],
                                  next_trading_day=None)
        kinds = {t["kind"] for t in todos}
        self.assertEqual(kinds, {"defense_near"})   # reeval/event 都需要 next_trading_day


class TestBuildTodayCommand(unittest.TestCase):
    def test_shape_has_headline_action_todos(self):
        results = {"甲": _tc_res("甲股", close=150.0, defense=100.0)}
        eg = build_exposure_guidance(7)
        cmd = build_today_command(results, eg, events=[], data_date="2026-07-17")
        self.assertIn("headline", cmd)
        self.assertIn("action", cmd)
        self.assertIn("todos", cmd)
        self.assertIsInstance(cmd["todos"], list)

    def test_missing_data_date_gives_empty_todos_not_crash(self):
        results = {"甲": _tc_res("甲股", close=150.0, defense=100.0, reeval_date="2026-07-20")}
        eg = build_exposure_guidance(7)
        cmd = build_today_command(results, eg, events=[], data_date=None)
        self.assertEqual(cmd["todos"], [])


# ---------- v1.5 delta（昨→今變了什麼）----------
def _daily_fixture(data_date, tracked=None, risk_temp=5, status="中性", watch=None):
    return {
        "meta": {"data_date": data_date},
        "market": {"risk_temp": risk_temp, "status": status},
        "tracked": tracked or [],
        "watch": watch or [],
    }


class TestBuildDelta(unittest.TestCase):
    def test_no_prev_daily_returns_none(self):
        new = _daily_fixture("2026-07-18")
        self.assertIsNone(build_delta(None, new, {}))

    def test_same_data_date_is_idempotent_none(self):
        # 冪等：同日重跑不能把「自己」當昨天比較（見 build_delta docstring）
        prev = _daily_fixture("2026-07-18", tracked=[{"id": "2330", "name": "台積電",
                              "decision": {"action": "續抱"}}])
        new = _daily_fixture("2026-07-18", tracked=[{"id": "2330", "name": "台積電",
                             "decision": {"action": "減碼"}}])
        self.assertIsNone(build_delta(prev, new, {}))

    def test_tracked_action_change_with_reason_suffix(self):
        prev = _daily_fixture("2026-07-17", tracked=[
            {"id": "2330", "name": "台積電", "decision": {"action": "續抱"}}])
        new = _daily_fixture("2026-07-18", tracked=[
            {"id": "2330", "name": "台積電", "decision": {"action": "減碼"}}])
        results = {"2330": {"primary_decision": {"reason_codes": ["defense_broken"]}}}
        delta = build_delta(prev, new, results)
        self.assertEqual(delta["since"], "2026-07-17")
        self.assertTrue(any("續抱→減碼" in i and "跌破防守" in i for i in delta["items"]))

    def test_risk_temp_and_status_and_watchlist_changes(self):
        prev = _daily_fixture("2026-07-17", risk_temp=5, status="中性",
                              tracked=[{"id": "2330", "name": "台積電",
                                       "decision": {"action": "續抱"}}])
        new = _daily_fixture("2026-07-18", risk_temp=9, status="偏空防禦",
                             tracked=[{"id": "2330", "name": "台積電",
                                      "decision": {"action": "續抱"}},
                                      {"id": "2603", "name": "長榮",
                                       "decision": {"action": "續抱"}}])
        delta = build_delta(prev, new, {})
        joined = " ".join(delta["items"])
        self.assertIn("風險溫度 5→9", joined)
        self.assertIn("大盤狀態 中性→偏空防禦", joined)
        self.assertIn("新增監控：長榮", joined)

    def test_items_capped_at_5(self):
        prev_tracked = [{"id": f"s{i}", "name": f"股{i}", "decision": {"action": "續抱"}}
                        for i in range(6)]
        new_tracked = [{"id": f"s{i}", "name": f"股{i}", "decision": {"action": "減碼"}}
                      for i in range(6)]
        prev = _daily_fixture("2026-07-17", tracked=prev_tracked)
        new = _daily_fixture("2026-07-18", tracked=new_tracked)
        delta = build_delta(prev, new, {})
        self.assertLessEqual(len(delta["items"]), 5)

    def test_first_run_no_prev_file_gives_null_delta_via_build_all(self):
        # build_all 顯式傳 prev_daily=None（模擬缺前檔／首次跑）→ daily["delta"] 為 null
        daily, _, _ = build_all(
            data_dir=os.path.join(REPO_ROOT, "data"),
            market_inputs=TestBuildAllRealData.OFFLINE_MARKET_INPUTS,
            prev_daily=None)
        self.assertIsNone(daily["delta"])


class TestPicksSingleSourceAlignment(unittest.TestCase):
    """實戰走查 🔴 任務 1：精選操作卡對外顯示的 defense_price/entry_zone/invalidation 必須
    「直接取該股 stocks/<id>.json 的 primary_decision」，不得用 picks 自算的長線 MA 值——
    否則精選卡防守 452.8、點進完整分析卻 447.1，同一天兩套數字打架。"""
    def test_pick_card_defense_equals_stock_detail_primary(self):
        from warroom import picks
        # 自算一張長線卡（防守＝MA60×0.95＝826.5，刻意與 2454 真正 primary_decision 不同源）
        m = {"id": "2454", "name": "聯發科", "close": 900.0, "ma20": 890.0, "ma60": 870.0,
             "ma120": 850.0, "support": 890.0, "recent_high": 1000.0, "revenue_yoy": 8.0,
             "avg3_yoy": 7.0, "per_pctile": 0.3, "pbr_pctile": 0.3, "div_yield": 3.0,
             "risk_flags": [], "ret20": None, "ret60": None, "high20": None, "low20": None,
             "vol_ratio": None, "chip_turn_buy": False, "chip_buy_streak_ge3": False,
             "dist_high20_pct": None, "earnings_within7": False}
        card = picks.build_pick_card(m, "long", 75.0, "禁止新增部位")
        self_calc_defense = card["defense_price"]
        self.assertEqual(self_calc_defense, 826.5)  # 對齊前＝自算長線值
        picks_input = {"generated_from": "t", "gate": "禁止新增部位", "note": "n",
                       "pools": {"actionable": [], "on_deck": [], "research": [card]},
                       "roster_changes": {"new": [], "dropped": [], "stay_note": None}}
        daily, details, _ = build_all(
            data_dir=os.path.join(REPO_ROOT, "data"),
            market_inputs=TestBuildAllRealData.OFFLINE_MARKET_INPUTS,
            picks_input=picks_input)
        self.assertIn("2454", details)
        expected = details["2454"]["primary_decision"]["defense_price"]
        self.assertIsNotNone(expected)
        aligned = daily["picks"]["pools"]["research"][0]
        # 核心驗收：picks 卡的防守價 == 對應 stocks json 的 defense_price（單一事實源）
        self.assertEqual(aligned["defense_price"], expected)
        self.assertNotEqual(aligned["defense_price"], self_calc_defense)  # 真的換過源
        # invalidation 帶對齊後的防守數字、entry_zone 兩端；action_summary 與 entry_zone 一致
        self.assertIn(str(expected), aligned["invalidation"])
        self.assertEqual(len(aligned["entry_zone"]), 2)
        jsonschema.validate(daily, DAILY_SCHEMA)


class TestStockDetailNewPositionGate(unittest.TestCase):
    """實戰走查 🔴 任務 2：build_stock_detail（即時查詢 api/analyze 走的同一支組裝）在大盤
    「禁止新增部位」時，空手建議一律「暫不進場」，不得吐「試單 10 萬」這種違反禁新倉、會叫人
    在該空手時進場的建議。api/analyze._lite_exposure_new_position 讀 daily.json 同一來源餵這個閘門。"""
    def _res(self, sid="2330"):
        with open(os.path.join(REPO_ROOT, "data", f"{sid}.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_banned_gate_blocks_trial_entry_in_advice(self):
        from warroom.profile import load_profile
        res = self._res("2330")
        profile = load_profile(os.path.join(REPO_ROOT, "data", "investor_profile.json"))
        banned = build_stock_detail("2330", res, profile, FAKE_META, "禁止新增部位")
        nh = banned["primary_decision"]["advice"]["nonholder"]
        self.assertIn("暫不進場", nh["action_text"])
        self.assertNotIn("試單 10 萬", nh["action_text"])
        for step in nh.get("plan") or []:
            self.assertNotIn("試單 10 萬", step.get("act", ""))

    def test_unrestricted_gate_allows_trial_entry(self):
        # 對照組：無大盤閘門（可正常布局）時，空手建議恢復可試單——證明上面的擋是閘門造成的
        from warroom.profile import load_profile
        res = self._res("2330")
        profile = load_profile(os.path.join(REPO_ROOT, "data", "investor_profile.json"))
        normal = build_stock_detail("2330", res, profile, FAKE_META, "可正常布局")
        nh = normal["primary_decision"]["advice"]["nonholder"]
        self.assertNotIn("暫不進場（大盤禁新倉）", nh["action_text"])


if __name__ == "__main__":
    unittest.main()
