"""單一主結論引擎 primary_decision（規格 §3.1~3.5）。

修三個病根：
1. 結論打架 → 六層優先序（§3.2）產出「唯一」action；summary/rating/timeframes 一律派生。
2. 全空手 → 部位級距由 action + 信心 + R/R 決定（Andy 0/10/20/40/60 萬檔），不再一刀切。
3. 估值悲觀 → valuation_warning（base 偏離現價 >30%）不得直接觸發減碼；減碼只從硬風控（層 2）來。

全部純規則、可揭露；LLM 不介入產數字（§3.5 narration 去人工化＝依 reason_codes 套模板）。
"""
from typing import Dict, List, Optional

from warroom.decision_engine import composite_score

# action ↔ 各派生欄位（禁止各自重算，全部由 action 決定）
ACTION_TO_DELTA = {"加碼": "increase", "續抱": "hold", "試單": "small_entry",
                   "觀望": "wait", "減碼": "reduce", "出場": "exit"}
ACTION_TO_RATING = {"加碼": "買進", "續抱": "續抱", "試單": "試單",
                    "觀望": "觀望", "減碼": "減碼", "出場": "減碼"}
ACTION_TO_STANCE = {"加碼": "偏多", "續抱": "中性偏多", "試單": "中性偏多",
                    "觀望": "中性", "減碼": "中性偏空", "出場": "偏空"}
# legacy summary.direction 只有 偏多/中性/偏空 三檔，直接由 action 派生（不再獨立合成）
ACTION_TO_DIRECTION = {"加碼": "偏多", "續抱": "中性", "試單": "中性",
                       "觀望": "中性", "減碼": "偏空", "出場": "偏空"}

_BAND_CODE = {"便宜": "valuation_cheap", "合理": "valuation_fair",
              "偏貴": "valuation_expensive", "很貴": "valuation_very_expensive"}

# reason_code → 人話片段（理由模板「因為 A，所以 B；但 C 是風險」用）
_REASON_PHRASE = {
    "trend_ok": "趨勢仍在（站上均線）",
    "trend_mixed": "均線轉弱／糾結，僅守長期均線",
    "trend_weak": "技術轉弱（跌破均線）",
    "fundamental_ok": "基本面沒惡化",
    "fundamental_weak": "基本面轉弱",
    "fundamental_broken": "營收基本面失效",
    "chips_ok": "法人籌碼偏多",
    "chips_weak": "法人籌碼偏弱",
    "chips_broken": "法人連日賣超、籌碼失效",
    "defense_broken": "已跌破防守位",
    "valuation_cheap": "估值便宜",
    "valuation_fair": "估值合理",
    "valuation_expensive": "估值偏貴",
    "valuation_very_expensive": "估值很貴",
    "valuation_warning": "估值模型可能低估（僅參考）",
    "rr_insufficient": "報酬風險比不足",
    "data_insufficient": "資料不足",
    # ETF／特殊標的通常沒有月營收、估值等基本面資料源，f=="na" 是常態而非異常，
    # 用專屬措辭跟「三燈都缺」的 data_insufficient 區分，讀起來才不像系統壞掉（見 build_primary_and_context 呼叫端）。
    "fundamental_data_missing": "基本面資料不足（ETF/特殊標的），僅以技術與籌碼判讀",
    "market_bull": "大盤偏多",
    "market_bear": "大盤偏空",
}

_ACTION_PHRASE = {"加碼": "可加碼", "續抱": "續抱不動", "試單": "小量試單",
                  "觀望": "先觀望不進場", "減碼": "先降波段部位", "出場": "波段出場"}


def _light_codes(f: str, t: str, c: str) -> List[str]:
    """技術燈 amber＝均線糾結／部分跌破，不是「站上均線」，不得映成 trend_ok
    （回歸：2330 收盤跌破 MA20/MA60、僅守 MA120 時 readable_reason 誤寫「趨勢仍在」）。"""
    out = []
    out.append("trend_ok" if t == "green" else "trend_weak" if t == "red" else "trend_mixed")
    out.append("fundamental_ok" if f in ("green", "amber") else "fundamental_weak")
    out.append("chips_ok" if c == "green" else "chips_weak" if c in ("amber", "red") else "chips_ok")
    return out


_CEILING_ORDER = {"none": 0, "small": 1, "standard": 2, "add": 3}
# 估值天花板（§3.3/§3.4）：偏貴封在 standard（不得加碼）；很貴封在 none（不得加碼／不得新進場）。
_VALUATION_CEILING = {"偏貴": "standard", "很貴": "none"}


def _rr_ceiling(rr: Optional[float], warning: Optional[str], band: Optional[str] = None) -> str:
    """R/R 天花板（§3.2 層 4）：<1.5 不新增｜1.5-2 最多試單｜>2 標準｜>3 才可加碼。
    有 valuation_warning 時 base 不可信 → rr 不可信 → 不放到可加碼（保守封在 standard）。
    valuation band=偏貴/很貴 另外封頂（§3.3 估值天花板），兩者取更嚴格者。"""
    if rr is None:
        base = "standard"          # 缺 R/R：允許續抱/標準，但不加碼
    elif rr < 1.5:
        base = "none"
    elif rr < 2:
        base = "small"
    elif rr <= 3 or warning:
        base = "standard"
    else:
        base = "add"
    cap = _VALUATION_CEILING.get(band)
    if cap is not None and _CEILING_ORDER[base] > _CEILING_ORDER[cap]:
        return cap
    return base


def _direction_bucket(lights: List[str], per_pct, market_light) -> str:
    """由三燈＋估值分位＋大盤合成方向（§3.2 層 5-6 只影響信心與傾向，不覆蓋硬規則）。"""
    score = composite_score(lights[0], lights[1], lights[2], per_pct, market_light)
    has_red = "red" in lights
    if score >= 0.4 and not has_red:
        return "strong_bull"
    if score >= 0.15 and not has_red:
        return "bull"
    if score <= -0.15:
        return "weak"
    return "neutral"


def _normal_zone(lights, per_pct, market_light, rr, warning, holding, confidence, band=None):
    """層 3-6：非硬風控區。持股→續抱/加碼；空手→試單/觀望。杜絕『觀望＋減碼』並存。
    band=偏貴/很貴 時 ceiling 已被 _rr_ceiling 封頂，天然擋掉加碼／很貴時也擋掉新進場（§3.3）。"""
    bucket = _direction_bucket(lights, per_pct, market_light)
    ceiling = _rr_ceiling(rr, warning, band)
    if holding:
        if bucket == "strong_bull" and ceiling == "add" and confidence > 75:
            return "加碼", 4, "rr_ok"
        return "續抱", (6 if bucket in ("neutral", "weak") else 5), "trend_ok"
    # 空手觀點
    if bucket in ("bull", "strong_bull") and ceiling in ("small", "standard", "add"):
        return "試單", 4, "rr_ok"
    return "觀望", (5 if bucket != "neutral" else 4), "rr_insufficient" if ceiling == "none" else "chips_weak"


def decide_action(*, lights, valuation, rr, defense_broken, fundamental_broken,
                  chips_broken, market_light, confidence, is_core_holding,
                  holding=None):
    """六層優先序（§3.2），回 (action, layer, reason_codes, primary_code)。"""
    f, t, c = lights
    present = [x for x in lights if x in ("green", "amber", "red")]
    band = (valuation or {}).get("band")
    warning = (valuation or {}).get("warning")
    per_pct = (valuation or {}).get("current_percentile")

    if holding is None:
        holding = bool(is_core_holding)   # 引擎只確知核心持股；其餘採空手觀點

    codes = _light_codes(f, t, c)
    if band in _BAND_CODE:
        codes.append(_BAND_CODE[band])
    if warning:
        codes.append("valuation_warning")
    codes.append("market_bull" if market_light == "green"
                 else "market_bear" if market_light == "red" else None)
    codes = [x for x in codes if x]

    hard = []
    if defense_broken:
        hard.append("defense_broken")
    if fundamental_broken:
        hard.append("fundamental_broken")
    if chips_broken:
        hard.append("chips_broken")

    # 層 1：資料品質 — 不足只能觀望/續抱，不得建議買進
    if len(present) < 2 or f == "na":
        action = "續抱" if holding else "觀望"
        # ETF/特殊標的常態性缺基本面（f=="na"）但技術/籌碼仍有 ≥2 筆可判讀，跟「三燈幾乎全缺」
        # 的一般資料不足分開措辭，避免讀起來像系統出錯（見 6：0050 查詢 stance 契約修復）。
        primary_code = "fundamental_data_missing" if (f == "na" and len(present) >= 2) else "data_insufficient"
        codes = _dedup([primary_code] + codes)
        return action, 1, codes, primary_code

    # 核心持股（§3.4）：僅基本面長期失效才動核心，其他硬訊號記為風險但不改方向
    core_protected = is_core_holding and not fundamental_broken

    # 層 2：硬風控 — 跌破防守/基本面失效/籌碼失效 → 減碼/出場優先
    if hard and not core_protected:
        codes = _dedup(hard + codes)
        if holding:
            action = "出場" if fundamental_broken else "減碼"
        else:
            action = "觀望"        # 空手者無部位可減 → 觀望（不與減碼並存）
        return action, 2, codes, hard[0]

    # 層 3-6：正常區
    action, layer, primary = _normal_zone(lights, per_pct, market_light, rr,
                                          warning, holding, confidence, band)
    if hard:
        codes = _dedup(hard + codes)
        # 核心被保護（例如 defense_broken/chips_broken 但基本面未失效）：不砍核心部位，
        # 但波段層仍受硬風控天花板約束 → action 上限續抱（持股）／觀望（空手），不得加碼/試單。
        if action in ("加碼", "試單"):
            action = "續抱" if holding else "觀望"
            layer = 2
            primary = hard[0]
    return action, layer, _dedup(codes), primary


def _dedup(seq):
    seen, out = set(), []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _position(action, confidence, rr, profile, price, is_core_holding):
    """部位級距（§3.4）：由 action + 信心 + R/R 決定 Andy 檔位（0/10/20/40/60 萬）。"""
    tiers = {t["name"]: t["amount"] for t in profile["position_tiers"]}
    if action in ("觀望", "出場"):
        tier = "空手"
    elif action == "減碼":
        tier = "試單"              # 降一檔（保留小部位）
    elif action == "試單":
        tier = "標準" if (rr is not None and rr >= 2) else "試單"
    elif action == "續抱":
        tier = "標準"
    elif action == "加碼":
        if confidence > 80 and rr is not None and rr > 3:
            tier = "極高信心"
        else:
            tier = "加碼"
    else:
        tier = "空手"
    amount = tiers.get(tier, 0)
    shares = int(amount // price) if amount > 0 and price and price > 0 else 0
    return {"tier": tier, "tier_amount": amount, "lots": shares // 1000,
            "odd_shares": shares % 1000}


def _readable_reason(action, layer, codes, is_core_holding):
    """理由模板『因為 A，所以 B；但 C 是風險』（§3.4）。A=主因、B=動作、C=首要風險。"""
    risk_codes = ("defense_broken", "fundamental_broken", "chips_broken",
                  "valuation_very_expensive", "valuation_expensive", "rr_insufficient",
                  "trend_mixed")
    positive_first = ["trend_ok", "fundamental_ok", "chips_ok", "valuation_cheap",
                      "valuation_fair"]
    # A：層 1/2 用命中碼；正常區用最強的正面理由
    if layer <= 2:
        a_code = codes[0]
    else:
        a_code = next((x for x in positive_first if x in codes), codes[0])
    a = _REASON_PHRASE.get(a_code, a_code)
    b = _ACTION_PHRASE.get(action, action)
    c_code = next((x for x in codes if x in risk_codes and x != a_code), None)
    reason = f"因為{a}，所以{b}"
    if c_code:
        reason += f"；但{_REASON_PHRASE.get(c_code, c_code)}是風險"
    reason += "。"
    if is_core_holding:
        reason += "（此為波段層判斷，不影響定期定額核心部位）"
    return reason


def _risk_note(codes, defense_price, tier_amount=None):
    """tier_amount==0＝空手／觀望：不得對空手者下達「降波段部位」指令
    （回歸：risk_note 曾對沒有部位的人講『先降波段部位』，措辭改成條件句）。"""
    parts = []
    is_flat = tier_amount == 0
    if "defense_broken" in codes:
        parts.append(f"已跌破防守位 {defense_price}")
    elif defense_price is not None:
        if is_flat:
            parts.append(f"若已持有，跌破 {defense_price} 先降波段部位；空手則等進場條件")
        else:
            parts.append(f"跌破 {defense_price} 防守位就先降波段部位")
    if "chips_broken" in codes:
        parts.append("法人持續賣超需留意")
    if "fundamental_broken" in codes:
        parts.append("營收基本面已失效，優先降風險")
    return "；".join(parts) or "維持既定防守紀律。"


def _facts_of(lights_facts, key):
    v = (lights_facts or {}).get(key)
    return list(v) if v else []


_MAX_ENTRY_DISTANCE = 0.15   # entry 錨點距現價 >15% 視為不可執行（規格回歸 #3）


def _parse_tech_anchor(tech_facts, label):
    """從 context.lights.technical.facts（如 'MA20 2428.2'）解析均線數值；
    缺資料／格式不符（如「樣本不足」）一律回 None，不編數字。"""
    prefix = label + " "
    for s in tech_facts or []:
        if s.startswith(prefix):
            try:
                return float(s[len(prefix):].replace(",", ""))
            except ValueError:
                return None
    return None


def _anchor_executable(anchor_price, price, max_pct=_MAX_ENTRY_DISTANCE):
    return (anchor_price is not None and price and price > 0
            and abs(anchor_price / price - 1) <= max_pct)


def _safe_entry_condition(entry_condition, price, tech_facts):
    """entry_condition 突破價距現價 >15% 視為不可執行（回歸：2454 現價 3370 給「突破
    4785」＝要求 +42% 才進場），改用較近可執行錨點：優先 MA20，太遠退 MA60，
    兩者都太遠則退回現價 +5% 觀察區間（仍在 15% 門檻內）。距現價本就 ≤15% 時原樣不動。"""
    if not entry_condition or price is None or price <= 0:
        return entry_condition
    if _anchor_executable(entry_condition.get("price"), price):
        return entry_condition
    ma20 = _parse_tech_anchor(tech_facts, "MA20")
    if ma20 is not None and ma20 >= price and _anchor_executable(ma20, price):
        return {"price": round(ma20, 1), "condition": "站回 MA20 且法人連 2 日買超"}
    ma60 = _parse_tech_anchor(tech_facts, "MA60")
    if ma60 is not None and ma60 >= price and _anchor_executable(ma60, price):
        return {"price": round(ma60, 1), "condition": "站回 MA60 且法人連 2 日買超"}
    fallback = round(price * 1.05, 1)
    return {"price": fallback,
            "condition": "現價附近整理走穩、法人止賣（原突破價過遠，已改近端觀察區間）"}


# 契約 v1：context.lights.color 只允許 green/yellow/red/null；引擎內部 amber/na 要在輸出前正規化。
_LIGHT_COLOR_OUT = {"green": "green", "amber": "yellow", "red": "red"}


def _normalize_light_color(x):
    return _LIGHT_COLOR_OUT.get(x)   # na／缺資料／其他 → None


def generate_roles(codes, lights_facts, action):
    """§3.5：角色觀點改引擎決定式生成，格式＝支持/反對/要驗證三欄，不再依賴手寫 narration。"""
    roles = []
    tech_f = _facts_of(lights_facts, "technical")
    fund_f = _facts_of(lights_facts, "fundamental")
    chip_f = _facts_of(lights_facts, "chips")
    roles.append({
        "role": "技術面分析師",
        "support": tech_f if "trend_ok" in codes else [],
        "oppose": tech_f if "trend_weak" in codes else [],
        "verify": ["觀察是否守住均線與防守位"],
    })
    roles.append({
        "role": "基本面分析師",
        "support": fund_f if "fundamental_ok" in codes else [],
        "oppose": fund_f if ("fundamental_weak" in codes or "fundamental_broken" in codes) else [],
        "verify": ["追蹤下月營收 YoY 是否維持"],
    })
    roles.append({
        "role": "籌碼分析師",
        "support": chip_f if "chips_ok" in codes else [],
        "oppose": chip_f if ("chips_weak" in codes or "chips_broken" in codes) else [],
        "verify": ["確認外資／投信是否轉買"],
    })
    val_codes = [c for c in codes if c.startswith("valuation")]
    roles.append({
        "role": "風控／估值",
        "support": ["估值便宜提供安全邊際"] if "valuation_cheap" in codes else [],
        "oppose": [_REASON_PHRASE[c] for c in val_codes
                   if c in ("valuation_expensive", "valuation_very_expensive")],
        "verify": ["估值模型有 warning 時以區間語言為準"] if "valuation_warning" in codes
                  else ["確認 R/R 是否站上 2 倍再加碼"],
    })
    return roles


def build_primary_and_context(*, price, lights, lights_facts, valuation, rr,
                              defense_price, defense_broken, fundamental_broken,
                              chips_broken, market_light, confidence, profile,
                              is_core_holding, reeval_date=None, entry_condition=None,
                              holding=None):
    """組出 data/<id>.json 的 primary_decision + context 兩區塊（資料契約 v1）。"""
    action, layer, codes, primary_code = decide_action(
        lights=lights, valuation=valuation, rr=rr, defense_broken=defense_broken,
        fundamental_broken=fundamental_broken, chips_broken=chips_broken,
        market_light=market_light, confidence=confidence,
        is_core_holding=is_core_holding, holding=holding)

    stance = ACTION_TO_STANCE[action]
    pos = _position(action, confidence, rr, profile, price, is_core_holding)
    fair = (valuation or {}).get("fair_value") or {}

    primary = {
        "action": action,
        "stance": stance,
        "position_delta": ACTION_TO_DELTA[action],
        "confidence": confidence,
        "decided_by_layer": layer,
        "reason_codes": codes,
        "readable_reason": _readable_reason(action, layer, codes, is_core_holding),
        "risk_note": _risk_note(codes, defense_price, pos.get("tier_amount")),
        "position": pos,
        "defense_price": defense_price,
        "entry_condition": (_safe_entry_condition(entry_condition, price,
                                                  _facts_of(lights_facts, "technical"))
                           if action in ("試單", "觀望") else None),
        "reeval_date": reeval_date,
    }
    if is_core_holding:
        primary["core_note"] = "此為波段層判斷，不影響定期定額核心部位。"

    f, t, c = lights
    _zh = {"green": "偏多", "amber": "中性", "red": "偏空", "na": "缺"}
    # stance 是契約五檔 enum（StanceSchema），"缺"不在裡面——na 燈只能在 basis 說明文字裡講
    # 「資料缺」，stance 欄位一律安全退回中性，否則 ETF 等常態缺基本面的標的會讓前端 zod 整頁炸掉
    # （見 6：0050 查詢「請更新 App」bug，contract.ts TimeframeSchema.stance）。
    _stance_zh = {"green": "偏多", "amber": "中性", "red": "偏空", "na": "中性"}
    context = {
        "timeframes": {
            "short": {"label": "短線 1-4 週",
                      "stance": _stance_zh.get(t, "中性"),
                      "basis": f"技術{_zh.get(t)}＋籌碼{_zh.get(c)}"},
            "swing": {"label": "波段 1-3 月（主）",
                      "stance": stance,                # ★ 主框架＝primary，禁止另算
                      "basis": primary["readable_reason"]},
            "mid": {"label": "中期 3-12 月",
                    "stance": _stance_zh.get(f, "中性"),
                    "basis": f"基本面{_zh.get(f)}＋估值{(valuation or {}).get('band') or '—'}"},
        },
        "lights": {
            "fundamental": {"color": _normalize_light_color(f), "facts": _facts_of(lights_facts, "fundamental")},
            "technical": {"color": _normalize_light_color(t), "facts": _facts_of(lights_facts, "technical")},
            "chips": {"color": _normalize_light_color(c), "facts": _facts_of(lights_facts, "chips")},
        },
        "valuation": {
            "band": (valuation or {}).get("band"),
            "base": fair.get("base"), "bull": fair.get("bull"), "bear": fair.get("bear"),
            "regime": (valuation or {}).get("regime"),
            "warning": (valuation or {}).get("warning"),
        },
        "rr": rr,
    }

    roles = generate_roles(codes, lights_facts, action)
    return primary, context, roles


# ---------- 派生 legacy 欄位（§3.1：summary/rating/timeframes 一律派生，禁止各自重算）----------
def derive_summary(primary: Dict) -> Dict:
    direction = ACTION_TO_DIRECTION[primary["action"]]
    conf_zh = "高" if primary["confidence"] >= 70 else "中" if primary["confidence"] >= 45 else "低"
    return {"direction": direction, "confidence": conf_zh, "conflict": False,
            "derived_from": "primary_decision"}


def apply_derivations(res: Dict, primary: Dict, context: Dict) -> None:
    """把 legacy summary / decision.rating / decision.time_frames 全改為由 primary 派生，
    防舊渲染壞掉、並讓一致性測試不再抓到打架（§3.1）。"""
    res["summary"] = {**res.get("summary", {}), **derive_summary(primary)}
    dec = res.get("decision")
    if isinstance(dec, dict):
        dec["rating"] = ACTION_TO_RATING[primary["action"]]
        dec.pop("event_downgrade", None)   # 舊事件降級路徑不再覆蓋主結論
        tf = dec.get("time_frames")
        if isinstance(tf, dict) and "swing" in tf:
            tf["swing"]["stance"] = context["timeframes"]["swing"]["stance"]
            tf["swing"]["basis"] = f"主結論：{primary['action']}"
        # legacy decision.position 同步主結論部位，避免舊渲染顯示與 primary_decision 矛盾的金額
        ppos = primary.get("position")
        pos = dec.get("position")
        if isinstance(pos, dict) and isinstance(ppos, dict):
            pos["tier"] = ppos.get("tier")
            pos["amount"] = ppos.get("tier_amount")
            pos["lots"] = ppos.get("lots")
            pos["odd_shares"] = ppos.get("odd_shares")
            lots, odd = ppos.get("lots") or 0, ppos.get("odd_shares") or 0
            pos["shares"] = lots * 1000 + odd
            pos["odd_lot"] = odd != 0
