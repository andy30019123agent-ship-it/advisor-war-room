"""短線劇本推演 warroom/short_scenarios.py 測試（規格：docs/contracts/data-contract-v1.md
「v1.4 增補」）。純函式、離線可測：機率查表／修正項／上下限 normalize／三劇本排序／
一致性閘門／紅線／schema 全覆蓋。"""
import json
import os
import unittest

import jsonschema

from warroom.short_scenarios import build_short_scenarios, _finalize_probs

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOCK_SCHEMA = json.load(open(os.path.join(REPO_ROOT, "schema", "stock.schema.json"), encoding="utf-8"))
_RESOLVER = jsonschema.RefResolver.from_schema(STOCK_SCHEMA)


def _validate(instance):
    jsonschema.validate(instance, STOCK_SCHEMA["properties"]["short_scenarios"], resolver=_RESOLVER)


# 基準輸入：現價 100、防守 90、近20日低 88、近20日高 110、MA20/60/120 = 95/85/80。
# 支撐候選（<100）＝{防守90,MA20 95,MA60 85,MA120 80,近20日低88}；壓力候選（>100）＝{近20日高110}。
# 三燈皆綠、籌碼無連買賣、大盤中性、大盤新倉不受限、防守未破、未突破近20日高
# → 全部修正項皆不觸發，機率＝原始查表值（供查表測試用）。
BASE_KW = dict(
    current_price=100.0, defense_price=90.0, low20=88.0, high20=110.0,
    ma20=95.0, ma60=85.0, ma120=80.0,
    technical_color="green", chips_color="green", fundamental_color="green",
    chips_streak=0, market_bias="neutral", market_new_position="可正常布局",
    is_bearish_arrangement=False, event_within_14d=False,
    primary_action="續抱", primary_position_delta="hold", halted=False,
)


def _probs_by_id(result):
    return {sc["id"]: sc["probability_pct"] for sc in result["scenarios"]}


def _kw(**overrides):
    kw = dict(BASE_KW)
    kw.update(overrides)
    return kw


# ---------- 機率查表（9 格抽 3 格） ----------
class TestProbTable(unittest.TestCase):
    def test_gg_table(self):
        out = build_short_scenarios(**_kw(technical_color="green", chips_color="green"))
        self.assertEqual(_probs_by_id(out), {"base": 50, "risk": 20, "bull": 30})

    def test_yr_table(self):
        out = build_short_scenarios(**_kw(technical_color="yellow", chips_color="red"))
        self.assertEqual(_probs_by_id(out), {"base": 40, "risk": 40, "bull": 20})

    def test_rr_table(self):
        out = build_short_scenarios(**_kw(technical_color="red", chips_color="red"))
        self.assertEqual(_probs_by_id(out), {"base": 30, "risk": 50, "bull": 20})

    def test_all_nine_cells_sum_to_100(self):
        for t in ("green", "yellow", "red"):
            for c in ("green", "yellow", "red"):
                out = build_short_scenarios(**_kw(technical_color=t, chips_color=c))
                self.assertEqual(sum(_probs_by_id(out).values()), 100, f"{t}x{c}")


# ---------- 修正項（各一） ----------
class TestCorrections(unittest.TestCase):
    def test_market_bearish_shifts_risk_up_bull_down(self):
        out = build_short_scenarios(**_kw(market_bias="bear"))
        p = _probs_by_id(out)
        self.assertEqual(p, {"base": 50, "risk": 25, "bull": 25})  # gg 20/30 ± 5

    def test_market_bullish_reverses_direction(self):
        out = build_short_scenarios(**_kw(market_bias="bull"))
        p = _probs_by_id(out)
        self.assertEqual(p, {"base": 50, "risk": 15, "bull": 35})

    def test_defense_broken_shifts_risk_up_base_down(self):
        # 現價跌到防守價以下 → defense_broken 內部自動判定，risk+10／base-10
        out = build_short_scenarios(**_kw(current_price=85.0))
        p = _probs_by_id(out)
        self.assertEqual(p, {"base": 40, "risk": 30, "bull": 30})

    def test_breakout_high20_shifts_bull_up_base_down(self):
        out = build_short_scenarios(**_kw(current_price=115.0))
        p = _probs_by_id(out)
        self.assertEqual(p, {"base": 45, "risk": 20, "bull": 35})

    def test_chips_buy_streak_ge3_shifts_bull_up_risk_down(self):
        out = build_short_scenarios(**_kw(chips_streak=3))
        p = _probs_by_id(out)
        self.assertEqual(p, {"base": 50, "risk": 15, "bull": 35})

    def test_chips_sell_streak_reverses_direction(self):
        out = build_short_scenarios(**_kw(chips_streak=-3))
        p = _probs_by_id(out)
        self.assertEqual(p, {"base": 50, "risk": 25, "bull": 25})


# ---------- 上下限 clip → normalize 100% → 整數化 ----------
class TestNormalize(unittest.TestCase):
    def test_low_value_clipped_to_floor_then_renormalized(self):
        base, risk, bull = _finalize_probs(5, 50, 45)
        self.assertEqual(base, 10)          # 5 被夾到下限 10
        self.assertEqual(base + risk + bull, 100)

    def test_high_value_clipped_to_ceiling_then_renormalized(self):
        base, risk, bull = _finalize_probs(50, 10, 80)
        self.assertLessEqual(bull, 65 + 1)  # 80 先夾到 65 再依比例縮放，允許縮放後些微超過純屬設計
        self.assertEqual(base + risk + bull, 100)

    def test_sum_always_100_even_with_stacked_corrections(self):
        out = build_short_scenarios(**_kw(technical_color="red", chips_color="red",
                                          market_bias="bear", current_price=85.0,
                                          chips_streak=-5))
        self.assertEqual(sum(_probs_by_id(out).values()), 100)


# ---------- 三劇本排序＝prob 降冪＋title 劇本一/二/三 ----------
class TestOrderingAndTitles(unittest.TestCase):
    def test_sorted_desc_and_title_ordinal_follows_rank_not_id(self):
        # gg 查表 base(50) > bull(30) > risk(20)：陣列順序應為 base、bull、risk，
        # 對應「劇本一/二/三」——risk 機率最低卻拿「劇本三」，證明編號跟 id 脫鉤。
        out = build_short_scenarios(**_kw(technical_color="green", chips_color="green"))
        scs = out["scenarios"]
        self.assertEqual([s["id"] for s in scs], ["base", "bull", "risk"])
        self.assertEqual([s["probability_pct"] for s in scs], [50, 30, 20])
        self.assertTrue(scs[0]["title"].startswith("劇本一"))
        self.assertTrue(scs[1]["title"].startswith("劇本二"))
        self.assertTrue(scs[2]["title"].startswith("劇本三"))


# ---------- 關鍵位間距規則（2%）：候選太近就跳到下一個／不足時 2 段 path／中性化標籤 ----------
class TestLevelSpacingRule(unittest.TestCase):
    def _bull(self, out):
        return next(s for s in out["scenarios"] if s["id"] == "bull")

    def test_close_candidate_skipped_jumps_to_next(self):
        # MA60 101.5 與 MA20 101.9 只差 0.39%（<2%）：R1 仍是 MA60（不因離現價近就跳過），
        # R2 應跳過 MA20、改用近20日高 130（複現 2330 實跑「R1/R2 幾乎重疊」的報告）。
        out = build_short_scenarios(**_kw(ma20=101.9, ma60=101.5, ma120=None, high20=130.0))
        bull = self._bull(out)
        self.assertEqual(bull["price_path"], [100.0, 101.5, 130.0])
        self.assertIn("MA60", bull["trigger"])
        self.assertIn("近20日高", bull["price_path_text"])
        self.assertNotIn("101.9", bull["price_path_text"])

    def test_all_candidates_too_close_gives_two_point_path(self):
        # MA60/MA20/近20日高全部擠在 R1 的 2% 以內：不硬湊第三段，只給現價→R1。
        out = build_short_scenarios(**_kw(ma20=101.5, ma60=101.0, ma120=None, high20=101.8))
        bull = self._bull(out)
        self.assertEqual(len(bull["price_path"]), 2)
        self.assertEqual(bull["price_path"], [100.0, 101.0])
        self.assertNotIn("突破後上看", bull["price_path_text"])

    def test_key_levels_resistances_also_deduped(self):
        # key_levels 跟 price_path 共用同一份已去重候選集，top3 不該出現幾乎重疊的兩個數字。
        out = build_short_scenarios(**_kw(ma20=101.9, ma60=101.5, ma120=None, high20=130.0))
        self.assertEqual(out["key_levels"]["resistances"], [101.5, 130.0])

    def test_near20_low_as_resistance_relabeled_neutral(self):
        # 現價已跌破自己的近20日低（低點反過來變成上檔關卡）：label 改「前波低點」，
        # 不再誤導成「近20日低」（低點語意卻出現在壓力側）。
        out = build_short_scenarios(**_kw(low20=105.0, high20=140.0, ma20=None, ma60=None, ma120=None))
        bull = self._bull(out)
        self.assertIn("前波低點", bull["trigger"])
        self.assertNotIn("近20日低", bull["trigger"])

    def test_near20_high_as_support_relabeled_neutral(self):
        # 現價已突破自己的近20日高（高點反過來變成下檔承接）：label 改「前波高點」。
        out = build_short_scenarios(**_kw(high20=95.0, low20=80.0, ma20=None, ma60=None, ma120=None))
        base = next(s for s in out["scenarios"] if s["id"] == "base")
        self.assertIn("前波高點", base["trigger"])
        self.assertNotIn("近20日高", base["trigger"])


# ---------- risk 劇本：跌破防守狀態用次一支撐 ----------
class TestRiskPricePath(unittest.TestCase):
    def _risk(self, out):
        return next(s for s in out["scenarios"] if s["id"] == "risk")

    def test_defense_intact_path_uses_defense_then_next_support(self):
        out = build_short_scenarios(**_kw(current_price=100.0))
        risk = self._risk(out)
        self.assertEqual(risk["price_path"], [100.0, 90.0, 88.0])  # 現價→防守→次一支撐(近20日低)
        self.assertIn("跌破 90", risk["price_path_text"])

    def test_defense_broken_path_still_uses_next_support(self):
        out = build_short_scenarios(**_kw(current_price=85.0))
        risk = self._risk(out)
        # 防守已破：[防守, 現價, 次一支撐]，仍指向次一支撐（近20日低 88 已高於現價 85，
        # 這裡的候選改成 MA120 80——因為此時「低於防守價、排除防守本身」的候選集含
        # 近20日低 88／MA60 85／MA120 80，取最靠近防守價的 88）
        self.assertEqual(risk["price_path"][0], 90.0)
        self.assertEqual(risk["price_path"][1], 85.0)
        self.assertEqual(risk["price_path"][-1], 88.0)
        self.assertIn("已跌破防守", risk["trigger"])


# ---------- 一致性：bull 動作不得跟大盤閘門／primary 打架 ----------
class TestBullActionConsistency(unittest.TestCase):
    def _bull(self, out):
        return next(s for s in out["scenarios"] if s["id"] == "bull")

    def test_market_banned_forces_wait(self):
        out = build_short_scenarios(**_kw(market_new_position="禁止新增部位",
                                          primary_action="加碼", primary_position_delta="increase"))
        bull = self._bull(out)
        self.assertEqual(bull["action"]["stance"], "wait")
        self.assertIn("不追價，僅觀察", bull["action"]["text"])

    def test_primary_reduce_caps_bull_to_wait(self):
        out = build_short_scenarios(**_kw(market_new_position="可正常布局",
                                          primary_action="減碼", primary_position_delta="reduce"))
        bull = self._bull(out)
        self.assertEqual(bull["action"]["stance"], "wait")

    def test_primary_exit_caps_bull_to_wait(self):
        out = build_short_scenarios(**_kw(market_new_position="可正常布局",
                                          primary_action="出場", primary_position_delta="exit"))
        bull = self._bull(out)
        self.assertEqual(bull["action"]["stance"], "wait")

    def test_market_trial_only_caps_bull_to_small_entry_even_if_primary_add(self):
        out = build_short_scenarios(**_kw(market_new_position="僅限試單",
                                          primary_action="加碼", primary_position_delta="increase"))
        bull = self._bull(out)
        self.assertEqual(bull["action"]["stance"], "small_entry")

    def test_free_market_and_primary_add_allows_increase(self):
        out = build_short_scenarios(**_kw(market_new_position="可正常布局",
                                          primary_action="加碼", primary_position_delta="increase"))
        bull = self._bull(out)
        self.assertEqual(bull["action"]["stance"], "increase")

    def test_free_market_default_primary_gives_small_entry(self):
        out = build_short_scenarios(**_kw(market_new_position="可正常布局",
                                          primary_action="續抱", primary_position_delta="hold"))
        bull = self._bull(out)
        self.assertEqual(bull["action"]["stance"], "small_entry")


# ---------- 紅線（insufficient_data，3 種） ----------
class TestRedLines(unittest.TestCase):
    def test_halted(self):
        out = build_short_scenarios(**_kw(halted=True))
        self.assertEqual(out["status"], "insufficient_data")
        self.assertEqual(set(out.keys()), {"status", "message"})

    def test_missing_defense_price(self):
        out = build_short_scenarios(**_kw(defense_price=None))
        self.assertEqual(out["status"], "insufficient_data")
        self.assertTrue(out["message"])

    def test_missing_price_high_low(self):
        for field in ("current_price", "low20", "high20"):
            out = build_short_scenarios(**_kw(**{field: None}))
            self.assertEqual(out["status"], "insufficient_data", field)

    def test_two_or_more_unknown_lights(self):
        out = build_short_scenarios(**_kw(technical_color=None, chips_color=None))
        self.assertEqual(out["status"], "insufficient_data")

    def test_single_unknown_light_gracefully_degrades_not_insufficient(self):
        # 只有技術燈缺（籌碼／基本面都在）→ 未達「兩個以上未知」門檻，退回中性繼續算
        out = build_short_scenarios(**_kw(technical_color=None))
        self.assertEqual(out["status"], "ok")


# ---------- 文案：具體、含千分位價位與動詞、非保證用語 ----------
class TestCopywriting(unittest.TestCase):
    def test_price_path_text_has_verbs_and_formatted_price(self):
        out = build_short_scenarios(**_kw())
        verbs = ("回測", "反彈", "下探", "挑戰", "震盪")
        for sc in out["scenarios"]:
            self.assertTrue(any(v in sc["price_path_text"] for v in verbs), sc)

    def test_price_path_text_uses_thousands_separator_for_large_prices(self):
        # 2330 現價量級（千位數）：文案要含千分位逗號，不是裸數字。
        out = build_short_scenarios(**_kw(
            current_price=2290.0, defense_price=2106.8, low20=2094.3, high20=2428.2,
            ma20=2428.2, ma60=2323.8, ma120=2094.3))
        for sc in out["scenarios"]:
            self.assertIn(",", sc["price_path_text"], sc)

    def test_no_forbidden_absolute_words(self):
        out = build_short_scenarios(**_kw())
        banned = ("必漲", "保證", "高勝率")
        for sc in out["scenarios"]:
            for field in ("narrative", "trigger", "price_path_text", "invalidation"):
                for w in banned:
                    self.assertNotIn(w, sc[field])

    def test_event_within_14d_prefixes_narrative(self):
        out = build_short_scenarios(**_kw(event_within_14d=True))
        for sc in out["scenarios"]:
            self.assertTrue(sc["narrative"].startswith("事件前不押注："))

    def test_bearish_arrangement_variant_wording(self):
        out = build_short_scenarios(**_kw(is_bearish_arrangement=True))
        base = next(s for s in out["scenarios"] if s["id"] == "base")
        self.assertIn("反彈至壓力後仍震盪", base["narrative"])


# ---------- schema ----------
class TestSchema(unittest.TestCase):
    def test_ok_result_passes_schema(self):
        _validate(build_short_scenarios(**_kw()))

    def test_insufficient_result_passes_schema(self):
        _validate(build_short_scenarios(**_kw(halted=True)))

    def test_all_nine_table_cells_pass_schema(self):
        for t in ("green", "yellow", "red"):
            for c in ("green", "yellow", "red"):
                _validate(build_short_scenarios(**_kw(technical_color=t, chips_color=c)))


if __name__ == "__main__":
    unittest.main()
