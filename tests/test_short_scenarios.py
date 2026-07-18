"""短線劇本推演 warroom/short_scenarios.py 測試（規格：docs/contracts/data-contract-v1.md
「v1.4 增補」）。純函式、離線可測：機率查表／修正項／上下限 normalize／三劇本排序／
一致性閘門／紅線／schema 全覆蓋。"""
import json
import os
import re
import unittest

import jsonschema

from warroom.short_scenarios import (
    build_short_scenarios, _finalize_probs, PROB_NOTE, _PROB_TABLE,
    apply_market_new_position_gate,
)

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


# ---------- invalidation 跨劇本引用：排序重編號後不得指向自己 ----------
class TestInvalidationCrossReference(unittest.TestCase):
    """根因：舊版在生成當下就寫死「切換劇本一/二」，但 scenarios 最後依機率重新排序、
    id 對應的「劇本X」編號會變，導致 base/risk 互相失效條件指到自己（prod 實測：risk
    排到劇本一時，它自己的失效文字卻寫「切換劇本一」）。"""

    @staticmethod
    def _ordinal_of(sc):
        return sc["title"].split("・")[0]

    def _target_ordinal(self, sc):
        m = re.search(r"切換(劇本[一二三])", sc["invalidation"])
        self.assertIsNotNone(m, sc["invalidation"])
        return m.group(1)

    def test_risk_ranked_first_invalidation_points_to_base_not_itself(self):
        # rr 查表：risk(50) > base(30) > bull(20) → risk 排到劇本一（複現 prod 回報的排序）。
        out = build_short_scenarios(**_kw(technical_color="red", chips_color="red"))
        by_id = {sc["id"]: sc for sc in out["scenarios"]}
        risk, base = by_id["risk"], by_id["base"]
        self.assertEqual(self._ordinal_of(risk), "劇本一")
        self.assertEqual(self._ordinal_of(base), "劇本二")
        self.assertNotEqual(self._target_ordinal(risk), self._ordinal_of(risk))
        self.assertEqual(self._target_ordinal(risk), self._ordinal_of(base))
        self.assertNotEqual(self._target_ordinal(base), self._ordinal_of(base))
        self.assertEqual(self._target_ordinal(base), self._ordinal_of(risk))

    def test_bull_invalidation_points_to_top_non_bull_when_base_leads(self):
        out = build_short_scenarios(**_kw(technical_color="green", chips_color="green",
                                          market_bias="bull", chips_streak=3))
        by_id = {sc["id"]: sc for sc in out["scenarios"]}
        bull = by_id["bull"]
        self.assertNotEqual(self._target_ordinal(bull), self._ordinal_of(bull))
        self.assertEqual(self._target_ordinal(bull), self._ordinal_of(by_id["base"]))

    def test_bull_invalidation_points_to_top_non_bull_when_risk_leads(self):
        out = build_short_scenarios(**_kw(technical_color="red", chips_color="red"))
        by_id = {sc["id"]: sc for sc in out["scenarios"]}
        bull = by_id["bull"]
        self.assertNotEqual(self._target_ordinal(bull), self._ordinal_of(bull))
        self.assertEqual(self._target_ordinal(bull), self._ordinal_of(by_id["risk"]))

    def test_never_self_references_across_all_probability_orderings(self):
        # 任意機率排序組合（9 格查表 × 3 種大盤傾向）：每個劇本的 invalidation 引用一律
        # 不指向自己，且引用到的編號正確對應該指向的劇本 id。
        for t in ("green", "yellow", "red"):
            for c in ("green", "yellow", "red"):
                for bias in ("neutral", "bull", "bear"):
                    out = build_short_scenarios(**_kw(technical_color=t, chips_color=c,
                                                       market_bias=bias))
                    by_id = {sc["id"]: sc for sc in out["scenarios"]}
                    for sc in out["scenarios"]:
                        target = self._target_ordinal(sc)
                        own = self._ordinal_of(sc)
                        self.assertNotEqual(target, own,
                                            f"{t}x{c}x{bias}: {sc['id']} 指向自己：{sc['invalidation']}")
                    self.assertEqual(self._target_ordinal(by_id["base"]),
                                     self._ordinal_of(by_id["risk"]))
                    self.assertEqual(self._target_ordinal(by_id["risk"]),
                                     self._ordinal_of(by_id["base"]))
                    _RANK = {"劇本一": 0, "劇本二": 1, "劇本三": 2}
                    top_non_bull = min((by_id["base"], by_id["risk"]),
                                       key=lambda s: _RANK[self._ordinal_of(s)])
                    self.assertEqual(self._target_ordinal(by_id["bull"]),
                                     self._ordinal_of(top_non_bull))


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


# ---------- 機率校正覆蓋（data/prob_calibration.json，見 warroom/scenario_calibration.py） ----------
class TestCalibrationOverride(unittest.TestCase):
    def test_adjusted_values_replace_rule_table_when_present(self):
        calibration = {"green_x_green": {"adjusted": {"base": 45, "risk": 15, "bull": 40},
                                         "n": 37, "observed": {}, "updated_at": "2026-07-18"}}
        out = build_short_scenarios(**_kw(calibration=calibration))
        # BASE_KW 底下所有修正項皆中性（見模組頂端說明），adjusted 值應直接透傳。
        self.assertEqual(_probs_by_id(out), {"base": 45, "risk": 15, "bull": 40})

    def test_prob_note_mentions_sample_size_when_calibrated(self):
        calibration = {"green_x_green": {"adjusted": {"base": 45, "risk": 15, "bull": 40},
                                         "n": 37, "observed": {}, "updated_at": "2026-07-18"}}
        out = build_short_scenarios(**_kw(calibration=calibration))
        self.assertIn("歷史校正", out["prob_note"])
        self.assertIn("37", out["prob_note"])

    def test_no_matching_bucket_falls_back_to_rule_table(self):
        calibration = {"red_x_red": {"adjusted": {"base": 20, "risk": 60, "bull": 20},
                                     "n": 50, "observed": {}, "updated_at": "2026-07-18"}}
        out = build_short_scenarios(**_kw(calibration=calibration))  # 是 green_x_green，查無
        self.assertEqual(_probs_by_id(out), {"base": 50, "risk": 20, "bull": 30})
        self.assertNotIn("歷史校正", out["prob_note"])

    def test_empty_calibration_dict_falls_back_to_rule_table(self):
        out = build_short_scenarios(**_kw(calibration={}))
        self.assertEqual(_probs_by_id(out), {"base": 50, "risk": 20, "bull": 30})
        self.assertEqual(out["prob_note"], PROB_NOTE)

    def test_calibrated_result_still_passes_schema(self):
        calibration = {"green_x_green": {"adjusted": {"base": 45, "risk": 15, "bull": 40},
                                         "n": 37, "observed": {}, "updated_at": "2026-07-18"}}
        _validate(build_short_scenarios(**_kw(calibration=calibration)))


# ---------- 查表單調性（修復 15：鎖住規則表，防未來改壞） ----------
class TestProbTableMonotonicity(unittest.TestCase):
    def test_worse_technical_does_not_raise_bull_nor_lower_risk(self):
        # 固定籌碼燈，技術燈由 green→yellow→red 變差：bull 不得升、risk 不得降（單調）。
        for chips in ("g", "y", "r"):
            seq = [_PROB_TABLE[t + chips] for t in ("g", "y", "r")]  # 技術由好到壞
            bulls = [s[2] for s in seq]
            risks = [s[1] for s in seq]
            for a, b in zip(bulls, bulls[1:]):
                self.assertGreaterEqual(a, b, f"chips={chips}：技術變差 bull 反升 {bulls}")
            for a, b in zip(risks, risks[1:]):
                self.assertLessEqual(a, b, f"chips={chips}：技術變差 risk 反降 {risks}")

    def test_worse_chips_does_not_raise_bull_nor_lower_risk(self):
        # 固定技術燈，籌碼燈由 green→yellow→red 變差：bull 不得升、risk 不得降。
        for tech in ("g", "y", "r"):
            seq = [_PROB_TABLE[tech + c] for c in ("g", "y", "r")]
            bulls = [s[2] for s in seq]
            risks = [s[1] for s in seq]
            for a, b in zip(bulls, bulls[1:]):
                self.assertGreaterEqual(a, b, f"tech={tech}：籌碼變差 bull 反升 {bulls}")
            for a, b in zip(risks, risks[1:]):
                self.assertLessEqual(a, b, f"tech={tech}：籌碼變差 risk 反降 {risks}")


# ---------- 大盤新倉閘門統一同源（修復 10／Y7：build 階段重跑 bull 閘門） ----------
class TestApplyMarketNewPositionGate(unittest.TestCase):
    def _ok_scenarios(self, market_new_position):
        return build_short_scenarios(**_kw(market_new_position=market_new_position,
                                           primary_action="加碼", primary_position_delta="increase"))

    def _bull(self, ss):
        return next(sc for sc in ss["scenarios"] if sc["id"] == "bull")

    def test_gate_switches_bull_action_to_authoritative_new_position(self):
        # analyze 階段用「可正常布局」proxy 算出 bull=increase；build 階段權威閘門若是
        # 「禁止新增部位」，重跑後 bull action 應收斂成 wait/不追價（跟 advice 層同源）。
        ss = self._ok_scenarios("可正常布局")
        self.assertEqual(self._bull(ss)["action"]["stance"], "increase")
        gated = apply_market_new_position_gate(ss, market_new_position="禁止新增部位",
                                               primary_action="加碼",
                                               primary_position_delta="increase")
        self.assertEqual(self._bull(gated)["action"]["stance"], "wait")

    def test_gate_trial_only_caps_bull_to_small_entry(self):
        ss = self._ok_scenarios("可正常布局")
        gated = apply_market_new_position_gate(ss, market_new_position="僅限試單",
                                               primary_action="加碼",
                                               primary_position_delta="increase")
        self.assertEqual(self._bull(gated)["action"]["stance"], "small_entry")

    def test_gate_noop_on_insufficient_or_none(self):
        self.assertIsNone(apply_market_new_position_gate(
            None, market_new_position="禁止新增部位", primary_action="加碼"))
        insuff = {"status": "insufficient_data", "message": "x"}
        self.assertEqual(apply_market_new_position_gate(
            insuff, market_new_position="禁止新增部位", primary_action="加碼"), insuff)


if __name__ == "__main__":
    unittest.main()
