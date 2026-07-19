"""中長線方向判讀 warroom/primary_decision.build_mid_long_reads 測試（規格：
docs/contracts/data-contract-v1.md「v1.7 增補」）。純函式，離線可測：bias 派生一致性、
path/flip 錨點 ≤15%、方向詞不與 bias 打架、mid basis 數字/資料不足降級、schema 全覆蓋。"""
import json
import os
import unittest

import jsonschema

from warroom.primary_decision import build_mid_long_reads

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOCK_SCHEMA = json.load(open(os.path.join(REPO_ROOT, "schema", "stock.schema.json"), encoding="utf-8"))
_RESOLVER = jsonschema.RefResolver.from_schema(STOCK_SCHEMA)


def _validate(instance):
    jsonschema.validate(instance, STOCK_SCHEMA["properties"]["mid_long_reads"], resolver=_RESOLVER)


TECH_FACTS = ["MA20 105.0", "MA60 95.0", "MA120 85.0", "收盤 100.0", "RSI14 45"]

TIMEFRAMES_BEARISH = {
    "short": {"label": "短線 1-4 週", "stance": "中性", "basis": "技術中性＋籌碼偏空"},
    "swing": {"label": "波段 1-3 月（主）", "stance": "中性偏空", "basis": "..."},
    "mid": {"label": "中期 3-12 月", "stance": "中性", "basis": "..."},
}
TIMEFRAMES_BULLISH = {
    "short": {"label": "短線 1-4 週", "stance": "偏多", "basis": "..."},
    "swing": {"label": "波段 1-3 月（主）", "stance": "偏多", "basis": "..."},
    "mid": {"label": "中期 3-12 月", "stance": "中性偏多", "basis": "..."},
}
TIMEFRAMES_NEUTRAL = {
    "short": {"label": "短線 1-4 週", "stance": "中性", "basis": "..."},
    "swing": {"label": "波段 1-3 月（主）", "stance": "中性", "basis": "..."},
    "mid": {"label": "中期 3-12 月", "stance": "中性", "basis": "..."},
}

VALUATION = {"band": "偏貴", "current_percentile": 0.82}


def _kw(**overrides):
    kw = dict(
        price=100.0, tech_facts=TECH_FACTS, defense_price=90.0, entry_condition=None,
        timeframes=TIMEFRAMES_BEARISH, valuation=VALUATION,
        reason_codes=["trend_weak", "valuation_expensive", "chips_broken"],
        rev_yoy=12.3, rev_avg3_yoy=15.0, rev_avg12_yoy=8.0,
        industry="半導體業", ma_structure="空頭排列",
    )
    kw.update(overrides)
    return kw


class TestBiasConsistency(unittest.TestCase):
    """bias 必等 timeframes 對應 stance（禁另算），一致性測試把關（大檢查・邏輯組要求）。"""

    def test_swing_bias_equals_timeframes_swing_stance(self):
        out = build_mid_long_reads(**_kw())
        self.assertEqual(out["swing"]["bias"], TIMEFRAMES_BEARISH["swing"]["stance"])

    def test_mid_bias_equals_timeframes_mid_stance(self):
        out = build_mid_long_reads(**_kw())
        self.assertEqual(out["mid"]["bias"], TIMEFRAMES_BEARISH["mid"]["stance"])

    def test_bullish_timeframes_bias_matches(self):
        out = build_mid_long_reads(**_kw(timeframes=TIMEFRAMES_BULLISH))
        self.assertEqual(out["swing"]["bias"], "偏多")
        self.assertEqual(out["mid"]["bias"], "中性偏多")

    def test_missing_timeframe_defaults_to_neutral_not_crash(self):
        out = build_mid_long_reads(**_kw(timeframes={}))
        self.assertEqual(out["swing"]["bias"], "中性")
        self.assertEqual(out["mid"]["bias"], "中性")


class TestAnchorDistanceRule(unittest.TestCase):
    """path_text/flip_condition 的價位錨點距現價 ≤15%（沿用 entry 錨點規則）。"""

    def _extract_prices(self, text):
        import re
        # 抓文字裡的價位數字：排除緊跟在字母後的數字（如「MA60」的 60 不是價位、是標籤
        # 一部分），只留大於 10 的獨立數字樣式。
        nums = re.findall(r"(?<![A-Za-z])[\d,]+\.?\d*", text)
        out = []
        for n in nums:
            v = float(n.replace(",", ""))
            if v > 10:
                out.append(v)
        return out

    def test_down_bias_anchor_within_15pct(self):
        out = build_mid_long_reads(**_kw(price=100.0, defense_price=90.0))
        for v in self._extract_prices(out["swing"]["path_text"]):
            self.assertLessEqual(abs(v / 100.0 - 1), 0.15)
        for v in self._extract_prices(out["swing"]["flip_condition"]):
            self.assertLessEqual(abs(v / 100.0 - 1), 0.15)

    def test_up_bias_anchor_within_15pct(self):
        out = build_mid_long_reads(**_kw(price=100.0, timeframes=TIMEFRAMES_BULLISH))
        for v in self._extract_prices(out["swing"]["path_text"]):
            self.assertLessEqual(abs(v / 100.0 - 1), 0.15)

    def test_far_anchor_falls_back_within_15pct(self):
        # MA120 遠在 85（-15%边界內尚可），故意把 tech_facts 全部推遠到超過 15%，
        # 應退回 fallback（現價 ±5%），仍在 15% 門檻內。
        far_facts = ["MA20 200.0", "MA60 210.0", "MA120 220.0"]
        out = build_mid_long_reads(**_kw(price=100.0, tech_facts=far_facts, defense_price=None))
        for v in self._extract_prices(out["swing"]["path_text"]):
            self.assertLessEqual(abs(v / 100.0 - 1), 0.15)


class TestDirectionWordsDontConflictWithBias(unittest.TestCase):
    """模板方向詞不與 bias 打架：偏空/中性偏空的 path_text 不該出現「挑戰」「加碼」等偏多
    專屬字眼；偏多/中性偏多的 path_text 不該出現「減碼」「出場」等偏空專屬字眼。"""

    def test_bearish_path_text_has_no_bullish_words(self):
        out = build_mid_long_reads(**_kw(timeframes=TIMEFRAMES_BEARISH))
        for bad in ("挑戰", "加碼", "站上"):
            self.assertNotIn(bad, out["swing"]["path_text"])
            self.assertNotIn(bad, out["mid"]["path_text"])

    def test_bullish_path_text_has_no_bearish_words(self):
        out = build_mid_long_reads(**_kw(timeframes=TIMEFRAMES_BULLISH))
        for bad in ("減碼", "出場", "跌破"):
            self.assertNotIn(bad, out["swing"]["path_text"])
            self.assertNotIn(bad, out["mid"]["path_text"])

    def test_neutral_path_text_uses_range_language(self):
        out = build_mid_long_reads(**_kw(timeframes=TIMEFRAMES_NEUTRAL))
        self.assertIn("震盪", out["swing"]["path_text"])


class TestMidBasisNumbersAndDegrade(unittest.TestCase):
    def test_mid_basis_has_three_items_with_numbers(self):
        out = build_mid_long_reads(**_kw())
        basis = out["mid"]["basis"]
        self.assertEqual(len(basis), 3)
        joined = "".join(basis)
        self.assertIn("12.3", joined)   # rev_yoy
        self.assertIn("%", joined)

    def test_mid_basis_revenue_missing_says_insufficient(self):
        out = build_mid_long_reads(**_kw(rev_yoy=None, rev_avg3_yoy=None, rev_avg12_yoy=None))
        self.assertIn("營收資料不足", out["mid"]["basis"])

    def test_mid_basis_valuation_missing_says_insufficient(self):
        out = build_mid_long_reads(**_kw(valuation=None))
        self.assertIn("估值資料不足", out["mid"]["basis"])

    def test_mid_basis_falls_back_to_ma_structure_without_industry(self):
        out = build_mid_long_reads(**_kw(industry=None, ma_structure="多頭排列"))
        self.assertTrue(any("多頭排列" in b for b in out["mid"]["basis"]))


class TestSwingBasis(unittest.TestCase):
    def test_swing_basis_between_2_and_3_items(self):
        out = build_mid_long_reads(**_kw())
        self.assertGreaterEqual(len(out["swing"]["basis"]), 2)
        self.assertLessEqual(len(out["swing"]["basis"]), 3)

    def test_swing_basis_empty_codes_falls_back(self):
        out = build_mid_long_reads(**_kw(reason_codes=[]))
        self.assertGreaterEqual(len(out["swing"]["basis"]), 2)


class TestPriceMissingGracefulDegrade(unittest.TestCase):
    def test_price_none_returns_full_object_not_none(self):
        out = build_mid_long_reads(**_kw(price=None))
        self.assertIsNotNone(out)
        self.assertIn("資料不足", out["swing"]["path_text"])
        self.assertIn("資料不足", out["swing"]["flip_condition"])
        # bias 仍照 timeframes 給，不因價格缺就消失
        self.assertEqual(out["swing"]["bias"], "中性偏空")

    def test_price_zero_treated_as_missing(self):
        out = build_mid_long_reads(**_kw(price=0))
        self.assertIn("資料不足", out["swing"]["path_text"])


class TestSchema(unittest.TestCase):
    def test_bearish_case_passes_schema(self):
        _validate(build_mid_long_reads(**_kw()))

    def test_bullish_case_passes_schema(self):
        _validate(build_mid_long_reads(**_kw(timeframes=TIMEFRAMES_BULLISH)))

    def test_neutral_case_passes_schema(self):
        _validate(build_mid_long_reads(**_kw(timeframes=TIMEFRAMES_NEUTRAL)))

    def test_degraded_no_price_case_passes_schema(self):
        _validate(build_mid_long_reads(**_kw(price=None, valuation=None,
                                             rev_yoy=None, rev_avg3_yoy=None,
                                             rev_avg12_yoy=None, industry=None,
                                             ma_structure=None)))


if __name__ == "__main__":
    unittest.main()
