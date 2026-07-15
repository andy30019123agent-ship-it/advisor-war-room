"""Task E：戰績牆測試（假 res / 日線 fixture，不打真 API）。"""
import json
import os
import tempfile
import unittest
import warnings

import pandas as pd

from warroom.track_record import (
    entry_from_res, log_recommendation, backfill_one, backfill_outcomes,
    compute_stats, calibrate_weights,
)


def make_res(sid="2330", price=100.0, base=120.0, stop=90.0, rating="買進",
             rr=3.0, conf=85, per_pctile=0.5, lights=("green", "green", "green")):
    return {
        "stock_id": sid, "name": "測試股",
        "fundamental": {"light": lights[0]}, "technical": {"light": lights[1]},
        "chips": {"light": lights[2]},
        "decision": {
            "rating": rating, "as_of_price": price, "risk_reward": rr,
            "fair_value": {"base": base}, "stop": {"price": stop},
            "confidence": {"total": conf},
            "valuation": {"current_percentile": per_pctile},
        },
    }


def future(dates_closes, hi=None, lo=None):
    """dates_closes: list of (date, close)。hi/lo 可選同長度。"""
    rows = []
    for i, (d, c) in enumerate(dates_closes):
        rows.append({"date": d, "close": c,
                     "max": (hi[i] if hi else c), "min": (lo[i] if lo else c)})
    return pd.DataFrame(rows)


class TestTrackRecord(unittest.TestCase):
    def test_entry_fields(self):
        e = entry_from_res(make_res(), today="2026-07-15")
        self.assertEqual(e["stock_id"], "2330")
        self.assertEqual(e["price"], 100.0)
        self.assertEqual(e["fair_base"], 120.0)
        self.assertEqual(e["stop"], 90.0)
        self.assertEqual(e["rr"], 3.0)
        self.assertEqual(e["confidence"], 85)
        self.assertEqual(e["factors"]["fund_light"], "green")
        self.assertEqual(e["factors"]["per_percentile"], 0.5)
        self.assertIsNone(e["outcome"]["r20"])

    def test_log_appends_and_dedupes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "log.json")
            log_recommendation(make_res(), "2026-07-15", p)
            log_recommendation(make_res(), "2026-07-15", p)   # 同日同股 → 覆蓋
            log_recommendation(make_res("2454"), "2026-07-15", p)
            data = json.load(open(p, encoding="utf-8"))
            self.assertEqual(len(data), 2)   # 2330（去重後 1）+ 2454
            log_recommendation(make_res(), "2026-07-16", p)   # 不同日 → 新增
            data2 = json.load(open(p, encoding="utf-8"))
            self.assertEqual(len(data2), 3)

    def test_log_recommendation_atomic_write_no_leftover_tmp(self):
        # P1 fix #2：寫入用 temp 檔 + os.replace，成功後不應留下 .tmp 殘檔
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "log.json")
            log_recommendation(make_res(), "2026-07-15", p)
            self.assertTrue(os.path.exists(p))
            self.assertFalse(os.path.exists(p + ".tmp"))

    def test_log_recommendation_corrupt_file_fail_closed(self):
        # P1 fix #2：log 檔壞掉（JSON 解析失敗）時 fail-closed——
        # 不得把壞檔覆寫成只剩這次的新 entry（會毀損既有戰績歷史），且不應 crash。
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "log.json")
            broken = "{not valid json,,, 這是壞掉的檔案"
            with open(p, "w", encoding="utf-8") as f:
                f.write(broken)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                entry = log_recommendation(make_res(), "2026-07-15", p)
            self.assertIsInstance(entry, dict)               # 仍回傳這次的 entry，不 crash
            self.assertEqual(entry["stock_id"], "2330")
            self.assertTrue(any("recommendation_log" in str(w.message) for w in caught))
            with open(p, encoding="utf-8") as f:
                content = f.read()
            self.assertEqual(content, broken)                # 原檔原封不動，沒被覆寫

    def test_backfill_target_hit(self):
        e = entry_from_res(make_res(price=100.0, base=120.0, stop=90.0), "2026-07-15")
        # 之後價格走高，第 3 天 high 觸及 120（target）
        fdf = future([("2026-07-16", 105), ("2026-07-17", 110), ("2026-07-18", 118)],
                     hi=[106, 112, 121], lo=[104, 108, 116])
        out = backfill_one(e, fdf)
        self.assertEqual(out["hit"], "target")
        self.assertEqual(out["hit_days"], 3)

    def test_backfill_stop_hit(self):
        e = entry_from_res(make_res(price=100.0, base=120.0, stop=90.0), "2026-07-15")
        fdf = future([("2026-07-16", 95), ("2026-07-17", 89)],
                     hi=[97, 92], lo=[94, 88])   # 第 2 天 low 觸及 90
        out = backfill_one(e, fdf)
        self.assertEqual(out["hit"], "stop")
        self.assertEqual(out["hit_days"], 2)
        self.assertLess(out["max_drawdown"], 0)

    def test_backfill_returns_and_expired(self):
        # P1 fix #1：60 個交易日到期仍未命中 target/stop → 終局為 "expired"（非 "none"）
        e = entry_from_res(make_res(price=100.0, base=200.0, stop=10.0), "2026-07-15")
        closes = [("2026-07-%02d" % (16 + i), 100 + i) for i in range(60)]
        out = backfill_one(e, future(closes))
        self.assertAlmostEqual(out["r5"], (104 / 100 - 1), places=4)   # 第5天 close=104
        self.assertAlmostEqual(out["r20"], (119 / 100 - 1), places=4)
        self.assertEqual(out["hit"], "expired")   # 60 天內都沒碰 target(200)/stop(10) → 到期終局
        self.assertFalse(out["ex_div_adjusted"])  # 未傳 ex_div_map → 照舊不調整

    def test_backfill_pending_when_window_short_and_unresolved(self):
        # P1 fix #1 核心：資料只有 5 個交易日、未命中 → 應維持 pending（None），
        # 不得像舊版一樣提早終局為 "none"（那會讓之後 backfill_outcomes 永久跳過此筆）
        e = entry_from_res(make_res(price=100.0, base=200.0, stop=10.0), "2026-07-15")
        closes5 = [("2026-07-%02d" % (16 + i), 100 + i) for i in range(5)]
        out = backfill_one(e, future(closes5))
        self.assertIsNone(out["hit"])
        self.assertIsNone(out["hit_days"])

    def test_regression_day6_hit_not_skipped_after_pending(self):
        # 回歸測試（P1 fix #1 的具體 bug 場景）：
        # 第一次回填只有 5 天資料、未中 → 應維持 pending；
        # 第二次回填（模擬隔日再跑，資料多了第 6 天且觸及 target）→ 應能正確補上命中，
        # 不會因為第一次被誤判「none」終局而被 backfill_outcomes 永久跳過。
        e = entry_from_res(make_res(price=100.0, base=120.0, stop=90.0), "2026-07-15")
        log = [e]

        day5 = [("2026-07-%02d" % (16 + i), 100 + i) for i in range(5)]     # 100..104，未中
        day6 = day5 + [("2026-07-22", 130)]                                 # 第6天飆到 130，觸及 target(120)

        calls = {"n": 0}

        def price_lookup(sid):
            calls["n"] += 1
            rows = day5 if calls["n"] == 1 else day6
            return future(rows)

        backfill_outcomes(log, price_lookup, min_days=5)
        self.assertIsNone(log[0]["outcome"]["hit"])   # 第一次：pending，不是 "none"

        backfill_outcomes(log, price_lookup, min_days=5)
        self.assertEqual(log[0]["outcome"]["hit"], "target")   # 第二次：正確補上第 6 天命中
        self.assertEqual(log[0]["outcome"]["hit_days"], 6)

    def test_backfill_ex_div_adjustment_avoids_false_stop(self):
        # P1 fix #3：除息造成的機械跳空不應誤觸 stop。entry=100, stop=90。
        # 第 3 天除息 8 元，原始收盤/低點跳空至 90/89（未調整會誤觸 stop）；
        # 還原（加回當日起累計配息 8）後應為 98/97，未跌破 stop。
        e = entry_from_res(make_res(price=100.0, base=200.0, stop=90.0), "2026-07-15")
        fdf = future([("2026-07-16", 100), ("2026-07-17", 99), ("2026-07-20", 90)],
                     hi=[101, 100, 91], lo=[99, 98, 89])
        ex_div_map = {"2026-07-20": 8.0}
        out_adj = backfill_one(e, fdf, ex_div_map=ex_div_map)
        self.assertIsNone(out_adj["hit"])          # 還原後未觸及 stop
        self.assertTrue(out_adj["ex_div_adjusted"])
        out_naive = backfill_one(e, fdf)           # 不調整（ex_div_map=None）→ 誤觸 stop
        self.assertEqual(out_naive["hit"], "stop")
        self.assertFalse(out_naive["ex_div_adjusted"])

    def test_compute_stats(self):
        log = [
            {"outcome": {"hit": "target", "r20": 0.2}, "price": 100, "stop": 90,
             "fair_base": 120, "rr": 2.0},
            {"outcome": {"hit": "stop", "r20": -0.1}, "price": 100, "stop": 90,
             "fair_base": 120, "rr": 2.0},
            {"outcome": {"hit": None, "r20": None}, "price": 100, "stop": 90,
             "fair_base": 120, "rr": 2.0},   # 未回填（pending）→ 不計入
        ]
        s = compute_stats(log)
        self.assertEqual(s["resolved"], 2)
        self.assertAlmostEqual(s["hit_rate"], 0.5)
        self.assertAlmostEqual(s["avg_r"], 0.5)   # (+2R 命中target ... 見實作定義) 平均

    def test_compute_stats_expired_counts_in_resolved_not_as_hit(self):
        # P1 fix #1：expired（60 天到期未中）是終局樣本，應計入分母，但不算命中（分子）。
        # 舊版把這類樣本整批排除在統計外，會系統性虛灌 hit_rate。
        log = [
            {"outcome": {"hit": "target", "r20": 0.2}, "price": 100, "stop": 90,
             "fair_base": 120, "rr": 2.0},
            {"outcome": {"hit": "expired", "r20": 0.05}, "price": 100, "stop": 90,
             "fair_base": 120, "rr": 2.0},
        ]
        s = compute_stats(log)
        self.assertEqual(s["resolved"], 2)          # target + expired 都計入分母
        self.assertAlmostEqual(s["hit_rate"], 0.5)  # 1 target / 2 resolved

    def test_calibrate_weights_no_autoapply(self):
        log = [{"factors": {"fund_light": "green", "tech_light": "amber", "chip_light": "green"},
                "outcome": {"hit": "target", "r20": 0.2}}]
        c = calibrate_weights(log)
        self.assertFalse(c["applied"])
        self.assertIn("suggested", c)
        self.assertAlmostEqual(sum(c["suggested"].values()), 1.0, places=3)


if __name__ == "__main__":
    unittest.main()
