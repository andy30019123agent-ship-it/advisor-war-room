"""Task E：戰績牆測試（假 res / 日線 fixture，不打真 API）。"""
import json
import os
import tempfile
import unittest

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

    def test_backfill_returns_and_none(self):
        e = entry_from_res(make_res(price=100.0, base=200.0, stop=10.0), "2026-07-15")
        closes = [("2026-07-%02d" % (16 + i), 100 + i) for i in range(60)]
        out = backfill_one(e, future(closes))
        self.assertAlmostEqual(out["r5"], (104 / 100 - 1), places=4)   # 第5天 close=104
        self.assertAlmostEqual(out["r20"], (119 / 100 - 1), places=4)
        self.assertEqual(out["hit"], "none")   # 60 天內都沒碰 target(200)/stop(10)

    def test_compute_stats(self):
        log = [
            {"outcome": {"hit": "target", "r20": 0.2}, "price": 100, "stop": 90,
             "fair_base": 120, "rr": 2.0},
            {"outcome": {"hit": "stop", "r20": -0.1}, "price": 100, "stop": 90,
             "fair_base": 120, "rr": 2.0},
            {"outcome": {"hit": None, "r20": None}, "price": 100, "stop": 90,
             "fair_base": 120, "rr": 2.0},   # 未回填 → 不計入
        ]
        s = compute_stats(log)
        self.assertEqual(s["resolved"], 2)
        self.assertAlmostEqual(s["hit_rate"], 0.5)
        self.assertAlmostEqual(s["avg_r"], 0.5)   # (+2R 命中target ... 見實作定義) 平均

    def test_calibrate_weights_no_autoapply(self):
        log = [{"factors": {"fund_light": "green", "tech_light": "amber", "chip_light": "green"},
                "outcome": {"hit": "target", "r20": 0.2}}]
        c = calibrate_weights(log)
        self.assertFalse(c["applied"])
        self.assertIn("suggested", c)
        self.assertAlmostEqual(sum(c["suggested"].values()), 1.0, places=3)


if __name__ == "__main__":
    unittest.main()
