"""T6：一致性檢查 consistency.py 測試。"""
import unittest

from warroom.consistency import (
    build_stock_anchors, check_numbers, check_stock_consistency,
    check_weekly_consistency,
)


def make_engine():
    return {
        "technical": {"ev": {"MA20": 2426.2, "MA60": 2305.5, "MA120": 2076.7,
                             "收盤": 2420.0}},
        "chips": {"ev": {"最新日": "2026-07-14"}},
        "decision": {"fair_value": {"bear": 2050.0, "base": 2380.0, "bull": 2720.0}},
    }


class TestConsistency(unittest.TestCase):
    def test_anchors_built(self):
        a = build_stock_anchors(make_engine())
        self.assertAlmostEqual(a["MA20"], 2426.2)
        self.assertAlmostEqual(a["Base"], 2380.0)

    def test_numbers_match_within_tolerance(self):
        # 敘事寫 MA20 2,426（與 2426.2 差 <1%）→ 無 diff
        diffs = check_numbers("收盤站上 MA20 2,426 保持多頭", build_stock_anchors(make_engine()))
        self.assertEqual(diffs, [])

    def test_numbers_mismatch_flagged(self):
        # 敘事寫錯 Base 2,900（與 2380 差 >1%）→ 有 diff
        diffs = check_numbers("合理價 Base 2,900 元", build_stock_anchors(make_engine()))
        self.assertTrue(any("Base" in d for d in diffs))

    def test_stock_consistency_date_lag(self):
        eng = make_engine()
        narration = {"as_of": "2026-07-10（台北）", "roles": {"chief": "維持觀望"}}
        diffs = check_stock_consistency(eng, narration)
        self.assertTrue(any("日期落後" in d for d in diffs))

    def test_stock_consistency_clean(self):
        eng = make_engine()
        narration = {"as_of": "2026-07-14（台北）",
                     "roles": {"technical": "收盤 2,420 站上 MA20 2,426"}}
        diffs = check_stock_consistency(eng, narration)
        self.assertEqual(diffs, [])

    def test_weekly_consistency(self):
        engines = {"2330": make_engine()}
        weekly = {"stocks": {"2330": "體質仍強，但合理價 Base 2,900 偏高"}}  # 錯 Base
        diffs = check_weekly_consistency(engines, weekly)
        self.assertTrue(any("2330" in d for d in diffs))


if __name__ == "__main__":
    unittest.main()
