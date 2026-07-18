"""劇本機率自我校正管線測試（沿用 tests/test_track_record.py 的 fail-closed 測試寫法：
tempfile.TemporaryDirectory + 假 log 檔）。全部離線，不打真 FinMind。"""
import json
import os
import tempfile
import unittest
import warnings

from warroom.scenario_calibration import (
    append_scenario_log, backfill_scenario_log, compute_calibration,
    determine_realized, format_bucket, sync_scenario_log, _shrinkage_lambda,
)


# ---------- format_bucket ----------
class TestFormatBucket(unittest.TestCase):
    def test_known_colors(self):
        self.assertEqual(format_bucket("yellow", "red"), "yellow_x_red")
        self.assertEqual(format_bucket("green", "green"), "green_x_green")

    def test_unknown_falls_back_to_yellow(self):
        self.assertEqual(format_bucket(None, "red"), "yellow_x_red")
        self.assertEqual(format_bucket("na", None), "yellow_x_yellow")


# ---------- append/覆蓋 ----------
class TestAppendScenarioLog(unittest.TestCase):
    def test_append_new_entry(self):
        log = append_scenario_log([], "2330", "2026-07-18", "yellow_x_red",
                                  [{"id": "base", "prob_pct": 40}],
                                  {"defense": 90.0, "r1": 105.0, "close": 100.0})
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["stock_id"], "2330")
        self.assertEqual(log[0]["bucket"], "yellow_x_red")
        self.assertIsNone(log[0]["realized"])

    def test_same_date_stock_overwrites_not_duplicates(self):
        log = append_scenario_log([], "2330", "2026-07-18", "yellow_x_red",
                                  [{"id": "base", "prob_pct": 40}],
                                  {"defense": 90.0, "r1": 105.0, "close": 100.0})
        log = append_scenario_log(log, "2330", "2026-07-18", "green_x_green",
                                  [{"id": "base", "prob_pct": 50}],
                                  {"defense": 91.0, "r1": 106.0, "close": 101.0})
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["bucket"], "green_x_green")

    def test_different_date_appends_new_entry(self):
        log = append_scenario_log([], "2330", "2026-07-18", "yellow_x_red",
                                  [], {"defense": 90.0, "r1": 105.0, "close": 100.0})
        log = append_scenario_log(log, "2330", "2026-07-19", "yellow_x_red",
                                  [], {"defense": 90.0, "r1": 105.0, "close": 100.0})
        self.assertEqual(len(log), 2)

    def test_entry_records_model_version_and_raw_probs(self):
        # 修復 14：每筆 entry 記 model_version 與 raw_probs（供校正吃同版本／稽核回溯）。
        log = append_scenario_log([], "2330", "2026-07-18", "yellow_x_red",
                                  [{"id": "base", "prob_pct": 40}, {"id": "risk", "prob_pct": 50},
                                   {"id": "bull", "prob_pct": 10}],
                                  {"defense": 90.0, "r1": 105.0, "close": 100.0})
        self.assertEqual(log[0]["model_version"], "v1")
        self.assertEqual(log[0]["raw_probs"], {"base": 40, "risk": 50, "bull": 10})


# ---------- realized 三分支（時間序第一觸發） ----------
class TestDetermineRealized(unittest.TestCase):
    def test_no_trigger_stays_in_range_returns_base(self):
        closes = [95.0, 96.0, 94.0, 97.0]  # 全在 defense(90)~r1(105) 之間
        self.assertEqual(determine_realized(closes, defense=90.0, r1=105.0), "base")

    def test_defense_breach_returns_risk(self):
        closes = [95.0, 89.0, 88.0]  # 連 2 日（第 2、3 天）收破 90 → risk
        self.assertEqual(determine_realized(closes, defense=90.0, r1=105.0), "risk")

    def test_r1_breach_returns_bull(self):
        closes = [95.0, 106.0, 107.0]  # 連 2 日（第 2、3 天）收上 105 → bull
        self.assertEqual(determine_realized(closes, defense=90.0, r1=105.0), "bull")

    def test_single_close_breach_not_confirmed_stays_base(self):
        # 修復 3：單一收盤碰線不算（需連 2 日確認）。第 2 天破防守但第 3 天站回 → base。
        self.assertEqual(determine_realized([95.0, 88.0, 95.0], defense=90.0, r1=105.0), "base")
        self.assertEqual(determine_realized([95.0, 106.0, 95.0], defense=90.0, r1=105.0), "base")

    def test_first_trigger_wins_risk_before_later_bull(self):
        # 先連 2 日破防守（第 1、2 天），後面又反彈連 2 日站上 r1——先觸發的算，仍是 risk。
        closes = [88.0, 87.0, 110.0, 111.0]
        self.assertEqual(determine_realized(closes, defense=90.0, r1=105.0), "risk")

    def test_first_trigger_wins_bull_before_later_risk(self):
        # 先連 2 日站上壓力（第 1、2 天），後面才連 2 日破防守——先觸發的算，是 bull。
        closes = [110.0, 111.0, 88.0, 87.0]
        self.assertEqual(determine_realized(closes, defense=90.0, r1=105.0), "bull")

    def test_none_values_skipped_do_not_break_consecutive_run(self):
        # 缺值不打斷連續計數：破防守→缺值→再破防守 仍算連 2 日確認 → risk。
        self.assertEqual(determine_realized([88.0, None, 87.0], defense=90.0, r1=105.0), "risk")
        self.assertEqual(determine_realized([None, None, 95.0], defense=90.0, r1=105.0), "base")


# ---------- backfill（eligibility + fail-safe） ----------
class TestBackfillScenarioLog(unittest.TestCase):
    def _entry(self, date="2026-06-01", realized=None):
        return {"date": date, "stock_id": "2330", "bucket": "yellow_x_red",
               "scenarios": [], "realized": realized,
               "levels": {"defense": 90.0, "r1": 105.0, "close": 100.0}}

    def test_not_yet_eligible_before_28_calendar_days_skipped(self):
        log = [self._entry(date="2026-07-01")]
        calls = []

        def lookup(sid, date):
            calls.append((sid, date))
            return [95.0]

        backfill_scenario_log(log, price_lookup=lookup, today="2026-07-18")  # 只差 17 天
        self.assertEqual(calls, [])
        self.assertIsNone(log[0]["realized"])

    def test_eligible_after_28_days_backfills_realized(self):
        log = [self._entry(date="2026-06-01")]
        out = backfill_scenario_log(log, price_lookup=lambda sid, date: [88.0, 87.0],
                                    today="2026-07-18")  # 47 天後，連 2 日跌破防守
        self.assertEqual(out[0]["realized"], "risk")

    def test_backfill_dict_lookup_records_ex_div_adjusted(self):
        # 修復 4：預設 lookup 回 {"closes", "ex_div_adjusted"}，backfill 應記錄該旗標。
        log = [self._entry(date="2026-06-01")]
        out = backfill_scenario_log(
            log, price_lookup=lambda sid, date: {"closes": [88.0, 87.0], "ex_div_adjusted": True},
            today="2026-07-18")
        self.assertEqual(out[0]["realized"], "risk")
        self.assertTrue(out[0]["ex_div_adjusted"])

    def test_lookup_returns_none_leaves_pending_for_next_run(self):
        log = [self._entry(date="2026-06-01")]
        out = backfill_scenario_log(log, price_lookup=lambda sid, date: None,
                                    today="2026-07-18")
        self.assertIsNone(out[0]["realized"])

    def test_already_realized_not_recomputed(self):
        log = [self._entry(date="2026-06-01", realized="base")]
        calls = []

        def lookup(sid, date):
            calls.append(1)
            return [200.0]

        backfill_scenario_log(log, price_lookup=lookup, today="2026-07-18")
        self.assertEqual(calls, [])  # 已回填過，不該再呼叫

    def test_lookup_exception_does_not_crash_whole_batch(self):
        log = [self._entry(date="2026-06-01")]

        def boom(sid, date):
            raise RuntimeError("網路掛了")

        out = backfill_scenario_log(log, price_lookup=boom, today="2026-07-18")
        self.assertIsNone(out[0]["realized"])


# ---------- 收縮混合 λ ----------
class TestShrinkageLambda(unittest.TestCase):
    def test_lambda_at_n20_is_half(self):
        self.assertAlmostEqual(_shrinkage_lambda(20), 0.5)

    def test_lambda_approaches_one_as_n_grows(self):
        self.assertGreater(_shrinkage_lambda(1000), 0.9)

    def test_lambda_at_zero_samples_is_zero(self):
        self.assertEqual(_shrinkage_lambda(0), 0.0)


# ---------- 校正表 ----------
def _log_with_realized(bucket, realized_counts):
    """realized_counts: {"base": n1, "risk": n2, "bull": n3}。每筆給「不同 stock_id」，
    確保修復 5 的（stock_id, bucket）30 天去重不會把它們折成 1 筆（每檔各只出現一次，
    天然是獨立樣本）。日期任意（去重只在同一 stock 內生效）。"""
    log = []
    i = 0
    for realized, n in realized_counts.items():
        for _ in range(n):
            i += 1
            log.append({"date": "2026-01-01", "stock_id": f"S{i:04d}", "bucket": bucket,
                       "model_version": "v1", "scenarios": [],
                       "levels": {"defense": 90.0, "r1": 105.0, "close": 100.0},
                       "realized": realized})
    return log


class TestComputeCalibration(unittest.TestCase):
    def test_below_min_samples_produces_no_entry(self):
        log = _log_with_realized("yellow_x_red", {"base": 10, "risk": 5, "bull": 4})  # n=19
        calibration = compute_calibration(log)
        self.assertNotIn("yellow_x_red", calibration)

    def test_meets_min_samples_produces_adjusted_entry(self):
        log = _log_with_realized("yellow_x_red", {"base": 8, "risk": 8, "bull": 4})  # n=20
        calibration = compute_calibration(log)
        self.assertIn("yellow_x_red", calibration)
        entry = calibration["yellow_x_red"]
        self.assertEqual(entry["n"], 20)
        self.assertIn("adjusted", entry)
        self.assertEqual(set(entry["adjusted"]), {"base", "risk", "bull"})
        self.assertEqual(sum(entry["adjusted"].values()), 100)
        self.assertAlmostEqual(entry["observed"]["risk"], 0.4)

    def test_pending_realized_none_not_counted(self):
        log = _log_with_realized("yellow_x_red", {"base": 8, "risk": 8, "bull": 4})
        log.append({"date": "2026-03-01", "stock_id": "2330", "bucket": "yellow_x_red",
                   "scenarios": [], "levels": {}, "realized": None})  # pending，不計
        calibration = compute_calibration(log)
        self.assertEqual(calibration["yellow_x_red"]["n"], 20)

    def test_deviation_from_rule_table_capped_at_15_points(self):
        # yellow_x_red 規則表值＝(40,40,20)（見 short_scenarios._PROB_TABLE["yr"]）。
        # 100% 都實現 risk（極端觀察值）在 n 很大時 λ→1，觀察頻率單獨會把 risk 衝到
        # ~100%，但 ±15 上限應把它夾在 40+15=55 附近（clamp/normalize 前）。
        log = _log_with_realized("yellow_x_red", {"risk": 200})
        calibration = compute_calibration(log)
        entry = calibration["yellow_x_red"]
        # clamp 前混合值被限制在規則值 ±15，clamp/normalize 後 risk 不會逼近 100。
        self.assertLess(entry["adjusted"]["risk"], 65)  # 仍受最終 10-65% clamp 節制
        self.assertGreater(entry["adjusted"]["risk"], 40)  # 但確實比規則表值 40 高

    def test_final_probs_sum_to_100_and_within_10_65_clamp(self):
        log = _log_with_realized("green_x_green", {"base": 1, "risk": 1, "bull": 18})
        calibration = compute_calibration(log)
        entry = calibration["green_x_green"]
        self.assertEqual(sum(entry["adjusted"].values()), 100)
        for v in entry["adjusted"].values():
            self.assertGreaterEqual(v, 10)
            self.assertLessEqual(v, 65)

    def test_unknown_bucket_format_ignored(self):
        log = [{"date": "2026-01-01", "stock_id": "2330", "bucket": "not_a_real_bucket",
               "scenarios": [], "levels": {}, "realized": "base"}] * 25
        calibration = compute_calibration(log)
        self.assertEqual(calibration, {})

    def test_same_stock_consecutive_days_deduped_to_one_sample(self):
        # 修復 5：同一 (stock_id, bucket) 30 天內只計 1 筆（連日快照自相關）。25 筆同股連日
        # → 去重成 1 筆 → 遠低於 20，不產生校正條目（防連日快照灌爆 n）。
        log = [{"date": f"2026-01-{d:02d}", "stock_id": "2330", "bucket": "yellow_x_red",
                "model_version": "v1", "scenarios": [],
                "levels": {"defense": 90.0, "r1": 105.0, "close": 100.0}, "realized": "risk"}
               for d in range(1, 26)]
        calibration = compute_calibration(log)
        self.assertNotIn("yellow_x_red", calibration)

    def test_same_stock_spaced_over_30_days_counts_separately(self):
        # 同股但每筆間隔 40 天（>30）→ 各自獨立計入（去重只擋 30 天內的連日快照）。
        from datetime import date, timedelta
        base = date(2026, 1, 1)
        dates = [(base + timedelta(days=40 * i)).strftime("%Y-%m-%d") for i in range(20)]
        log = [{"date": d, "stock_id": "2330", "bucket": "yellow_x_red", "model_version": "v1",
                "scenarios": [], "levels": {"defense": 90.0, "r1": 105.0, "close": 100.0},
                "realized": "risk"} for d in dates]
        calibration = compute_calibration(log)
        self.assertIn("yellow_x_red", calibration)
        self.assertEqual(calibration["yellow_x_red"]["n"], 20)

    def test_final_adjusted_stays_within_15pp_of_rule_table(self):
        # 修復 6：clamp 與 normalize 迭代後，最終每個機率仍在規則表 ±15pp 內（normalize
        # 不得把值推出邊界）。yr 規則＝(40,40,20)，極端全 risk 觀察值也不得讓 risk 超過 55。
        log = _log_with_realized("yellow_x_red", {"risk": 300})
        adj = compute_calibration(log)["yellow_x_red"]["adjusted"]
        rule = {"base": 40, "risk": 40, "bull": 20}
        for k, rv in rule.items():
            self.assertLessEqual(adj[k], rv + 15, f"{k} 超出規則 +15pp")
            self.assertGreaterEqual(adj[k], rv - 15, f"{k} 低於規則 -15pp")
        self.assertEqual(sum(adj.values()), 100)

    def test_only_matching_model_version_counted(self):
        # 修復 14：校正只吃同 model_version 的樣本；不同版本（v2）不計入。
        log = _log_with_realized("yellow_x_red", {"base": 8, "risk": 8, "bull": 4})  # 20 筆 v1
        for e in log[:15]:
            e["model_version"] = "v2"  # 15 筆改成別版本 → 只剩 5 筆 v1 < 20
        calibration = compute_calibration(log)
        self.assertNotIn("yellow_x_red", calibration)


# ---------- sync_scenario_log fail-closed ----------
class TestSyncScenarioLogFailClosed(unittest.TestCase):
    def test_corrupt_log_file_skips_write_and_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "scenario_log.json")
            broken = "{not valid json,,, 這是壞掉的檔案"
            with open(p, "w", encoding="utf-8") as f:
                f.write(broken)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result = sync_scenario_log({}, "2026-07-18", log_path=p)
            self.assertIsNone(result)
            self.assertTrue(any("scenario_log" in str(w.message) for w in caught))
            with open(p, encoding="utf-8") as f:
                content = f.read()
            self.assertEqual(content, broken)  # 原檔原封不動，沒被覆寫

    def test_missing_log_file_is_normal_empty_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "scenario_log.json")
            result = sync_scenario_log({}, "2026-07-18", log_path=p,
                                       price_lookup=lambda sid, date: None)
            self.assertEqual(result, [])
            self.assertTrue(os.path.exists(p))

    def test_stock_detail_appended_with_correct_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "scenario_log.json")
            detail = {
                "primary_decision": {"defense_price": 90.0},
                "price": {"close": 100.0},
                "context": {"lights": {"technical": {"color": "yellow"},
                                       "chips": {"color": "red"}}},
                "short_scenarios": {
                    "status": "ok",
                    "key_levels": {"resistances": [105.0, 110.0]},
                    "scenarios": [{"id": "base", "probability_pct": 40},
                                 {"id": "risk", "probability_pct": 40},
                                 {"id": "bull", "probability_pct": 20}],
                },
            }
            result = sync_scenario_log({"2330": detail}, "2026-07-18", log_path=p,
                                       price_lookup=lambda sid, date: None)
            self.assertEqual(len(result), 1)
            e = result[0]
            self.assertEqual(e["stock_id"], "2330")
            self.assertEqual(e["bucket"], "yellow_x_red")
            self.assertEqual(e["levels"], {"defense": 90.0, "r1": 105.0, "close": 100.0})
            self.assertEqual(e["scenarios"],
                             [{"id": "base", "prob_pct": 40}, {"id": "risk", "prob_pct": 40},
                              {"id": "bull", "prob_pct": 20}])

    def test_insufficient_data_stock_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "scenario_log.json")
            detail = {"short_scenarios": {"status": "insufficient_data", "message": "x"}}
            result = sync_scenario_log({"2330": detail}, "2026-07-18", log_path=p,
                                       price_lookup=lambda sid, date: None)
            self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
