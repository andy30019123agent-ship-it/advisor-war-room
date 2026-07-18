"""主結論引擎 primary_decision 測試（規格 §3.1~3.5）：六層優先序每層 ≥1 case、
部位分層、核心保護、legacy 派生與一致性把關。純函式、不打網路。"""
import unittest

from warroom.primary_decision import (
    decide_action, build_primary_and_context, derive_summary, apply_derivations,
    ACTION_TO_RATING, ACTION_TO_DIRECTION,
)
from warroom.consistency import check_primary_consistency

PROFILE = {
    "position_tiers": [
        {"name": "空手", "amount": 0}, {"name": "試單", "amount": 100000},
        {"name": "標準", "amount": 200000}, {"name": "加碼", "amount": 400000},
        {"name": "極高信心", "amount": 600000},
    ],
    "core_holdings": ["2330", "0050"],
}

VAL_OK = {"band": "合理", "warning": None, "current_percentile": 0.5,
          "fair_value": {"bear": 90.0, "base": 120.0, "bull": 150.0}, "regime": "3y"}


def _decide(**kw):
    base = dict(lights=["green", "green", "green"], valuation=VAL_OK, rr=2.5,
                defense_broken=False, fundamental_broken=False, chips_broken=False,
                market_light="amber", confidence=70, is_core_holding=False, holding=None)
    base.update(kw)
    return decide_action(**base)


class TestSixLayers(unittest.TestCase):
    # ---- 層 1：資料品質 ----
    def test_layer1_data_insufficient_never_buys(self):
        act, layer, codes, _ = _decide(lights=["na", "na", "na"], holding=False)
        self.assertEqual((act, layer), ("觀望", 1))
        act_h, _, _, _ = _decide(lights=["na", "na", "na"], holding=True)
        self.assertEqual(act_h, "續抱")            # 有持股 → 續抱，不是買進
        self.assertNotIn(act_h, ("加碼", "試單"))

    # ---- 層 2：硬風控 ----
    def test_layer2_hardrisk_holder_reduces_flat_waits(self):
        act_h, layer, codes, _ = _decide(chips_broken=True, holding=True, is_core_holding=False)
        self.assertEqual((act_h, layer), ("減碼", 2))
        act_f, _, _, _ = _decide(chips_broken=True, holding=False, is_core_holding=False)
        self.assertEqual(act_f, "觀望")            # 空手無部位可減 → 觀望（不與減碼並存）
        act_exit, _, _, _ = _decide(fundamental_broken=True, holding=True, is_core_holding=False)
        self.assertEqual(act_exit, "出場")

    def test_layer2_core_holding_protected(self):
        # 核心持股籌碼失效 → 不減核心，回續抱（§3.4）
        act, layer, codes, _ = _decide(chips_broken=True, is_core_holding=True, holding=True)
        self.assertEqual(act, "續抱")
        self.assertNotEqual(layer, 2)
        self.assertIn("chips_broken", codes)       # 風險仍記錄

    def test_core_holding_hard_risk_still_caps_action_no_add(self):
        # 核心持股「不砍核心部位」不等於「硬風控失效」：defense_broken/chips_broken 時
        # 波段層 action 上限仍是續抱，不得被 _normal_zone 判成加碼/試單（回歸 bug #1）。
        act, layer, codes, code0 = _decide(
            chips_broken=True, is_core_holding=True, holding=True,
            confidence=90, rr=3.5)   # 若無天花板，正常區會判「加碼」
        self.assertEqual(act, "續抱")
        self.assertNotIn(act, ("加碼", "試單"))
        self.assertIn("chips_broken", codes)
        self.assertIn("chips_weak" if "chips_weak" in codes else "chips_broken", codes)

        act2, layer2, codes2, _ = _decide(
            defense_broken=True, is_core_holding=True, holding=True,
            confidence=95, rr=4.0)
        self.assertEqual(act2, "續抱")
        self.assertNotIn(act2, ("加碼", "試單"))
        self.assertIn("defense_broken", codes2)

    # ---- 層 3：持股狀態決定用詞 ----
    def test_layer3_vocabulary_split(self):
        # 空手偏多 → 試單（不會是續抱）；有持股中性 → 續抱（不會是觀望）
        act_flat, _, _, _ = _decide(holding=False, rr=2.5)
        self.assertEqual(act_flat, "試單")
        act_hold, _, _, _ = _decide(lights=["amber", "amber", "amber"], holding=True, rr=2.5)
        self.assertEqual(act_hold, "續抱")

    # ---- 層 4：R/R 天花板 ----
    def test_layer4_rr_gates_entry_and_add(self):
        # 空手 + 三燈綠但 R/R<1.5 → 觀望（不新增）
        act, layer, _, _ = _decide(holding=False, rr=1.0)
        self.assertEqual(act, "觀望")
        # 有持股 + 強多 + R/R>3 + 高信心 → 加碼
        act2, layer2, _, _ = _decide(holding=True, rr=3.5, confidence=90, valuation=VAL_OK)
        self.assertEqual((act2, layer2), ("加碼", 4))

    # ---- 層 5：三燈/大盤只影響信心，不覆蓋硬規則 ----
    def test_layer5_weak_lights_do_not_force_reduce(self):
        # 有持股、三燈轉弱、但無硬風控觸發 → 續抱（減碼只從層 2 來）
        act, layer, _, _ = _decide(lights=["red", "amber", "amber"], holding=True,
                                   chips_broken=False, fundamental_broken=False,
                                   defense_broken=False)
        self.assertEqual(act, "續抱")
        self.assertNotEqual(act, "減碼")

    # ---- 層 6：估值過熱限制加碼、warning 不觸發減碼 ----
    def test_layer6_overheat_limits_add_not_reduce(self):
        hot = {"band": "很貴", "warning": "模型 Base 1700 與現價 2440 偏離 30%…",
               "current_percentile": 0.97,
               "fair_value": {"bear": 1400.0, "base": 1700.0, "bull": 2400.0}, "regime": "3y"}
        act, layer, codes, _ = _decide(valuation=hot, rr=3.5, confidence=90, holding=True)
        self.assertEqual(act, "續抱")              # 過熱＋warning → 不加碼
        self.assertNotEqual(act, "減碼")           # warning 不得直接觸發減碼
        self.assertIn("valuation_warning", codes)

    def test_layer6_very_expensive_no_warning_still_no_add(self):
        # 回歸 bug #2（估值無天花板）：很貴＋全綠燈＋高 R/R，即使沒有 warning 字串，
        # 仍不得判「加碼」；空手則不得判「試單」，只能觀望。
        very_hot = {"band": "很貴", "warning": None, "current_percentile": 0.97,
                    "fair_value": {"bear": 1400.0, "base": 1700.0, "bull": 2400.0}, "regime": "3y"}
        act_hold, _, _, _ = _decide(valuation=very_hot, rr=5.0, confidence=95, holding=True)
        self.assertEqual(act_hold, "續抱")
        self.assertNotEqual(act_hold, "加碼")
        act_flat, _, _, _ = _decide(valuation=very_hot, rr=5.0, confidence=95, holding=False)
        self.assertEqual(act_flat, "觀望")
        self.assertNotEqual(act_flat, "試單")

    def test_layer6_expensive_caps_add_but_allows_hold(self):
        # 偏貴：上限續抱（不得加碼），但仍可續抱（非強制觀望/減碼）。
        pricey = {"band": "偏貴", "warning": None, "current_percentile": 0.80,
                  "fair_value": {"bear": 90.0, "base": 120.0, "bull": 150.0}, "regime": "3y"}
        act, _, _, _ = _decide(valuation=pricey, rr=5.0, confidence=95, holding=True)
        self.assertEqual(act, "續抱")
        self.assertNotEqual(act, "加碼")


class TestPositionLayering(unittest.TestCase):
    def _pos(self, action_kwargs):
        kw = dict(price=100.0, lights=["green", "green", "green"], lights_facts={},
                  valuation=VAL_OK, rr=2.5, defense_price=90.0, defense_broken=False,
                  fundamental_broken=False, chips_broken=False, market_light="amber",
                  confidence=70, profile=PROFILE, is_core_holding=False)
        kw.update(action_kwargs)
        primary, _, _ = build_primary_and_context(**kw)
        return primary

    def test_wait_is_flat(self):
        p = self._pos(dict(rr=1.0, holding=False))   # → 觀望
        self.assertEqual(p["action"], "觀望")
        self.assertEqual(p["position"]["tier_amount"], 0)

    def test_hold_is_standard_tier(self):
        p = self._pos(dict(lights=["amber", "amber", "amber"], holding=True, rr=2.5))
        self.assertEqual(p["action"], "續抱")
        self.assertEqual(p["position"]["tier_amount"], 200000)

    def test_add_uses_top_tier(self):
        p = self._pos(dict(holding=True, rr=3.5, confidence=90))
        self.assertEqual(p["action"], "加碼")
        self.assertEqual(p["position"]["tier_amount"], 600000)   # 極高信心檔

    def test_reduce_downtiers(self):
        primary, _, _ = build_primary_and_context(
            price=100.0, lights=["green", "green", "red"], lights_facts={},
            valuation=VAL_OK, rr=2.5, defense_price=90.0, defense_broken=False,
            fundamental_broken=False, chips_broken=True, market_light="amber",
            confidence=60, profile=PROFILE, is_core_holding=False, holding=True)
        self.assertEqual(primary["action"], "減碼")
        self.assertEqual(primary["position"]["tier_amount"], 100000)   # 降一檔

    def test_core_holding_note_and_not_flat(self):
        # 核心持股即便籌碼失效也維持波段標準部位＋核心不動註記（§3.4，杜絕全空手）
        primary, _, _ = build_primary_and_context(
            price=2440.0, lights=["amber", "green", "red"], lights_facts={},
            valuation=VAL_OK, rr=-3.0, defense_price=2245.0, defense_broken=False,
            fundamental_broken=False, chips_broken=True, market_light="red",
            confidence=40, profile=PROFILE, is_core_holding=True, holding=True)
        self.assertEqual(primary["action"], "續抱")
        self.assertIn("core_note", primary)
        self.assertGreater(primary["position"]["tier_amount"], 0)      # 不是空手


class TestDerivationConsistency(unittest.TestCase):
    def _res(self):
        primary, context, roles = build_primary_and_context(
            price=100.0, lights=["green", "amber", "red"], lights_facts={},
            valuation=VAL_OK, rr=2.0, defense_price=90.0, defense_broken=False,
            fundamental_broken=False, chips_broken=False, market_light="amber",
            confidence=65, profile=PROFILE, is_core_holding=False, holding=True)
        res = {"stock_id": "2454", "summary": {}, "primary_decision": primary,
               "context": context,
               "decision": {"rating": "觀望", "time_frames": {"swing": {"stance": "中性"}}}}
        apply_derivations(res, primary, context)
        return res, primary

    def test_derivations_are_consistent(self):
        res, primary = self._res()
        self.assertEqual(res["decision"]["rating"], ACTION_TO_RATING[primary["action"]])
        self.assertEqual(res["summary"]["direction"], ACTION_TO_DIRECTION[primary["action"]])
        self.assertEqual(res["decision"]["time_frames"]["swing"]["stance"], primary["stance"])
        self.assertEqual(check_primary_consistency(res), [])
        self.assertFalse(res["summary"]["conflict"])

    def test_consistency_catches_conflict(self):
        # 手動把 rating 改成與 action 矛盾（模擬舊「觀望＋減碼並存」）→ 必須 fail
        res, _ = self._res()
        res["decision"]["rating"] = "減碼"
        diffs = check_primary_consistency(res)
        self.assertTrue(any("打架" in d for d in diffs))

    def test_no_wait_and_reduce_coexist(self):
        # 有持股：不論輸入，action 唯一 → 派生 rating/summary 不可能同時是觀望與減碼
        res, primary = self._res()
        rating = res["decision"]["rating"]
        direction = res["summary"]["direction"]
        self.assertFalse(rating == "觀望" and "偏空" == direction)

    def test_legacy_position_synced_to_primary(self):
        # 回歸 bug #3：legacy decision.position 要映射自 primary["position"]，
        # 否則舊渲染會顯示跟 primary_decision 矛盾的金額/檔位。
        primary, context, roles = build_primary_and_context(
            price=2440.0, lights=["green", "green", "green"], lights_facts={},
            valuation=VAL_OK, rr=3.5, defense_price=2245.0, defense_broken=False,
            fundamental_broken=False, chips_broken=False, market_light="amber",
            confidence=90, profile=PROFILE, is_core_holding=False, holding=True)
        self.assertEqual(primary["action"], "加碼")
        res = {"stock_id": "2330", "summary": {}, "primary_decision": primary,
               "context": context,
               "decision": {"rating": "觀望",
                            "position": {"tier": "空手", "amount": 0, "odd_lot": False,
                                        "shares": 0, "reason": "舊值", "core_note": ""},
                            "time_frames": {"swing": {"stance": "中性"}}}}
        apply_derivations(res, primary, context)
        pos = res["decision"]["position"]
        self.assertEqual(pos["tier"], primary["position"]["tier"])
        self.assertEqual(pos["amount"], primary["position"]["tier_amount"])
        self.assertEqual(pos["lots"], primary["position"]["lots"])
        self.assertEqual(pos["odd_shares"], primary["position"]["odd_shares"])
        self.assertEqual(pos["shares"],
                         primary["position"]["lots"] * 1000 + primary["position"]["odd_shares"])


class TestLightsColorNormalization(unittest.TestCase):
    def test_context_lights_only_allows_contract_colors(self):
        # 規格條 4：輸出前 amber→yellow、na/缺資料→null；只允許 green/yellow/red/null。
        primary, context, roles = build_primary_and_context(
            price=100.0, lights=["amber", "na", "red"], lights_facts={},
            valuation=VAL_OK, rr=2.0, defense_price=90.0, defense_broken=False,
            fundamental_broken=False, chips_broken=False, market_light="amber",
            confidence=50, profile=PROFILE, is_core_holding=False, holding=True)
        colors = {k: v["color"] for k, v in context["lights"].items()}
        self.assertEqual(colors["fundamental"], "yellow")   # amber → yellow
        self.assertIsNone(colors["technical"])              # na → null
        self.assertEqual(colors["chips"], "red")
        for c in colors.values():
            self.assertIn(c, ("green", "yellow", "red", None))


STANCE_ENUM = ("偏多", "中性偏多", "中性", "中性偏空", "偏空")


class TestStanceNeverLeaksNA(unittest.TestCase):
    """2026-07-18 聯測 #6：ETF／缺基本面標的（如 0050）查詢整頁顯示「請更新 App」。
    根因：context.timeframes.{short,mid}.stance 在對應燈號＝na 時吐出中文字串「缺」，
    不在前端 StanceSchema 五檔 enum 裡，Zod 驗證失敗。stance 欄位任何情況都只能是
    契約五檔之一——「缺」只准出現在 basis 說明文字，不准進 stance。"""

    def test_timeframe_stance_is_always_contract_enum_even_when_light_na(self):
        # technical＝na（模擬個股缺技術資料）＋fundamental＝na（模擬 ETF 缺財報）同時測。
        primary, context, roles = build_primary_and_context(
            price=100.0, lights=["na", "na", "green"], lights_facts={},
            valuation={"band": None, "warning": None, "current_percentile": None,
                      "fair_value": {}, "regime": None},
            rr=None, defense_price=None, defense_broken=False,
            fundamental_broken=False, chips_broken=False, market_light="amber",
            confidence=0, profile=PROFILE, is_core_holding=False, holding=False)
        for tf_key in ("short", "swing", "mid"):
            stance = context["timeframes"][tf_key]["stance"]
            self.assertIn(stance, STANCE_ENUM, f"{tf_key}.stance={stance!r} 不在契約 enum 裡")
        self.assertIn(primary["stance"], STANCE_ENUM)

    def test_etf_like_missing_fundamental_gets_observe_action_and_specific_reason(self):
        # f=="na" 但技術/籌碼仍有 ≥2 筆可判讀（ETF 常態）：action=觀望（非核心持股空手觀點）、
        # stance=中性、readable_reason 講清楚是 ETF/特殊標的缺基本面，不是系統壞掉。
        primary, context, roles = build_primary_and_context(
            price=100.0, lights=["na", "green", "amber"], lights_facts={},
            valuation={"band": None, "warning": None, "current_percentile": None,
                      "fair_value": {}, "regime": None},
            rr=2.0, defense_price=None, defense_broken=False,
            fundamental_broken=False, chips_broken=False, market_light="amber",
            confidence=50, profile=PROFILE, is_core_holding=False, holding=False)
        self.assertEqual(primary["action"], "觀望")
        self.assertEqual(primary["stance"], "中性")
        self.assertIn("ETF", primary["readable_reason"])


if __name__ == "__main__":
    unittest.main()
