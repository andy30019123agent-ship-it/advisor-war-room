"""單一主結論引擎 primary_decision（規格 §3.1~3.5）。

修三個病根：
1. 結論打架 → 六層優先序（§3.2）產出「唯一」action；summary/rating/timeframes 一律派生。
2. 全空手 → 部位級距由 action + 信心 + R/R 決定（Andy 0/10/20/40/60 萬檔），不再一刀切。
3. 估值悲觀 → valuation_warning（base 偏離現價 >30%）不得直接觸發減碼；減碼只從硬風控（層 2）來。

全部純規則、可揭露；LLM 不介入產數字（§3.5 narration 去人工化＝依 reason_codes 套模板）。
"""
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from warroom.decision_engine import composite_score

# 燈號 → 分數（跟 decision_engine._L 同一套），供短線 stance 技術＋籌碼合成用。
_LIGHT_SCORE = {"green": 1, "amber": 0, "red": -1, "na": 0}


def _short_stance(technical_light: str, chips_light: str) -> str:
    """短線 stance＝0.6×技術＋0.4×籌碼（沿用 decision_engine.time_frames 的 short_s 權重），
    門檻與該檔 stance() 一致（>0.2 偏多／<-0.2 偏空／其餘中性），落在契約五檔 enum 內。"""
    s = 0.6 * _LIGHT_SCORE.get(technical_light, 0) + 0.4 * _LIGHT_SCORE.get(chips_light, 0)
    return "偏多" if s > 0.2 else "偏空" if s < -0.2 else "中性"


def next_reeval_date(from_date: str, days: int = 7) -> str:
    """複評日＝from_date + days 曆日，再「下一交易日對齊」：落在週六 → +2（→週一）、
    週日 → +1（→週一）。簡化版不接國定假日行事曆（僅避開週末），屬近似值。
    from_date 格式錯誤時原樣回傳 from_date（不編日期）。"""
    try:
        d = datetime.strptime(from_date[:10], "%Y-%m-%d").date() + timedelta(days=days)
    except (ValueError, TypeError):
        return from_date
    if d.weekday() == 5:      # 週六
        d += timedelta(days=2)
    elif d.weekday() == 6:    # 週日
        d += timedelta(days=1)
    return d.strftime("%Y-%m-%d")

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


def _fmt_price(x):
    """人話文案用：四捨五入到整數＋千分位（契約文案本身即用 '2,107' 這種寫法）。"""
    try:
        return f"{round(float(x)):,}"
    except (TypeError, ValueError):
        return "—"


def _find_fact(facts, *keys):
    """回第一條同時含所有 keys 的 fact 字串，找不到回空字串（不編）。"""
    for s in facts or []:
        if all(k in s for k in keys):
            return s
    return ""


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


# ---------- v1.1：雙版建議 advice ＋ 防守價說明 defense_explain ----------
def _executable_anchors(price, tech_facts, defense_price):
    """回可執行（距現價 ≤15%）的價位錨清單，每項 {label, price, side}。
    來源：防守價＋MA20/MA60/MA120（沿用 _safe_entry_condition 的錨點與 15% 規則）。"""
    out = []
    if _anchor_executable(defense_price, price):
        out.append({"label": "防守價", "price": defense_price,
                    "side": "below" if defense_price < price else "above"})
    for label in ("MA20", "MA60", "MA120"):
        v = _parse_tech_anchor(tech_facts, label)
        if v is not None and _anchor_executable(v, price):
            out.append({"label": label, "price": v,
                        "side": "below" if v < price else "above"})
    return out


def _nonholder_entry(price, tech_facts, entry_condition, anchors):
    """空手者的進場錨：優先「站回最近上方均線」，退而求其次回測下方均線，
    再退回 primary 的 entry_condition（已被 _safe_entry_condition 收斂到 ≤15%）。"""
    ma_aboves = sorted([a for a in anchors if a["side"] == "above" and a["label"].startswith("MA")],
                       key=lambda a: a["price"])
    if ma_aboves:
        a = ma_aboves[0]
        return {"price": a["price"],
                "trigger": f"站回 {a['label']} {_fmt_price(a['price'])} 且法人連 2 日買超"}
    ma_belows = sorted([a for a in anchors if a["side"] == "below" and a["label"].startswith("MA")],
                       key=lambda a: a["price"], reverse=True)
    if ma_belows:
        a = ma_belows[0]
        return {"price": a["price"],
                "trigger": f"回測 {a['label']} {_fmt_price(a['price'])} 附近止穩、法人止賣"}
    ec = _safe_entry_condition(entry_condition, price, tech_facts)
    if ec and ec.get("price") is not None:
        return {"price": ec["price"],
                "trigger": f"{ec.get('condition', '進場條件')}（約 {_fmt_price(ec['price'])}）"}
    return None


# holder action_text 的固定起手詞（動詞方向由 action 決定，一致性測試把關）
_HOLDER_TEXT = {
    "加碼": "維持持股、可分批加碼",
    "續抱": "續抱不動",
    "試單": "續抱不動",
    "觀望": "續抱觀望、暫不加碼",
    "減碼": "分批減碼",
    "出場": "波段出場、反彈不追",
}
_ACTION_DIR = {"加碼": "up", "續抱": "hold", "試單": "hold",
               "觀望": "hold", "減碼": "down", "出場": "down"}


def _text_direction(action_text):
    """由 holder action_text 起手段判動詞方向（一致性測試用；與 _ACTION_DIR 對齊）。"""
    head = re.split(r"[，；：。]", action_text or "")[0]
    if "減碼" in head or "出場" in head or "出清" in head:
        return "down"
    if "加碼" in head and "不加碼" not in head and "暫不" not in head:
        return "up"
    return "hold"


def _fmt_wan(amount) -> Optional[str]:
    """金額（元）→『X 萬』人話字串；缺值或非正數回 None（呼叫端降級成不帶總上限的文案）。"""
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    return f"{amount / 10000:.0f} 萬"


def build_advice(*, action, reason_codes, price, defense_price, tech_facts,
                 entry_condition, is_core_holding, valuation=None, tier_amount=None,
                 market_new_position=None):
    """雙版建議：holder（已持有）＋nonholder（空手），各含 action_text＋plan 階梯。
    plan 每條 trigger 含具體價位/條件、act 含比例或金額；價位錨一律 ≤15%（見 _executable_anchors）。
    文案由 action + reason_codes + 價位錨生成，與 action 同向（一致性測試把關）。

    tier_amount＝該股 position 級距金額（元，見 _position／Andy 0/10/20/40/60 萬檔位）：
    action=="加碼" 時代表這次加碼的『總上限』，不是一次全押；plan 金額改講「第一段 20 萬
    （總上限 X 萬）」，避免使用者誤讀成分批階梯之外還能再加碼到 20 萬（回歸：舊文案固定寫
    死「加碼 20 萬」，跟該股實際核准到 40／60 萬的級距脫鉤）。試單／回補金額不受級距影響，
    維持固定 10 萬起（Andy 試單檔位就是 10 萬，不需要另外接級距）。

    market_new_position＝當下 exposure_guidance.new_position（見 build_exposure_guidance，
    daily.json 的大盤層級規則）。同時收斂 nonholder（空手進場）與 holder 的「加碼／回補」
    ——後兩者也是「新增部位」，禁新倉時不該叫持有者加碼（大檢查・邏輯組 Y5，跟 bull 劇本
    同源）；holder 的既有防守/減碼紀律不受影響，只有「新增」動作過閘門：
    - "禁止新增部位"：不管個股 action 算出什麼，空手一律不建議進場，plan／文案改講
      「暫不進場（大盤禁新倉）」，不得出現任何試單／買進金額（回歸：個股層級沒看大盤，
      大盤都喊禁新倉了，某些股票的 nonholder 建議還在講「試單 10 萬」，兩層互相矛盾）。
    - "僅限試單"：空手若原本因為 action=="加碼" 會看到 20/40/60 萬階梯，收斂回 10 萬
      試單額度，其餘 action（本來就是 10 萬起）不受影響。"""
    codes = reason_codes or []
    # 提前算 market_banned（原本只在下面主路徑算），核心持股提前 return 分支也要用（見下）。
    market_banned = market_new_position == "禁止新增部位"
    # 核心持股且引擎沒有真正資料可判讀（ETF/特殊標的常態缺基本面，primary_code 落在
    # fundamental_data_missing／data_insufficient——見 decide_action 層 1）：不套波段防守
    # 模板（0050 這類標的沒有波段層可言，跌破某條均線算出的「防守價」對定期定額投資人
    # 沒有意義）。2330 這類核心持股有完整波段層（f_light 非 na）不受影響，維持雙軌不變
    # （契約 v1.5 App 行為段：核心持股顯示核心語言，不套波段防守模板）。
    if is_core_holding and any(c in codes for c in
                               ("fundamental_data_missing", "data_insufficient")):
        core_text = "核心持股：定期定額照常，僅基本面長期失效才調整。"
        holder = {"action_text": core_text, "plan": []}
        entry = _nonholder_entry(price, tech_facts, entry_condition,
                                 _executable_anchors(price, tech_facts, defense_price))
        if market_banned:
            # 核心持股的空手版本（定期定額分批布局）同樣是「新增部位」，大盤禁新倉時要
            # 跟一般 nonholder 閘門同源收斂（大檢查・核心分支漏閘門）：不得出現任何分批
            # 布局／定期定額的「進場」語言，清掉佈局 act，改講暫不進場。
            if entry:
                banned_text = f"暫不進場（大盤禁新倉），{entry['trigger']}後再評估。"
                nonholder = {"action_text": banned_text,
                            "plan": [{"trigger": entry["trigger"], "act": banned_text[:-1]}]}
            else:
                nonholder = {"action_text": "暫不進場（大盤禁新倉），資料亦不足，維持觀望。",
                            "plan": []}
        elif entry:
            nonholder = {"action_text": f"核心持股：可等{entry['trigger']}分批布局，不追高。",
                        "plan": [{"trigger": entry["trigger"], "act": "分批布局，定期定額為主"}]}
        else:
            nonholder = {"action_text": "核心持股：資料不足，維持既定定期定額計畫。", "plan": []}
        return {"holder": holder, "nonholder": nonholder}

    anchors = _executable_anchors(price, tech_facts, defense_price)
    defense_exec = _anchor_executable(defense_price, price)
    core_txt = "（核心不動）" if is_core_holding else ""
    core_act = "，核心不動" if is_core_holding else ""
    add_cap = _fmt_wan(tier_amount) if action == "加碼" else None
    # holder 的「加碼／回補」也是「新增部位」，同樣要過大盤 new_position 閘門（大檢查・
    # 邏輯組 Y5）：禁新倉 → 不加碼/不回補、維持既有；僅限試單 → 縮到 10 萬。與劇本層
    # bull action、nonholder 版同一個大盤閘門同源，不再只擋 nonholder。
    # （market_banned 已在函式頂端算過，核心持股提前 return 分支也共用同一個值。）
    trial_only = market_new_position == "僅限試單"

    # ---- holder ----
    hplan = []
    if defense_exec:
        if action == "出場":
            hplan.append({"trigger": f"反彈至均線或跌破 {_fmt_price(defense_price)}（防守價）",
                          "act": f"波段部位分批出清{core_act}"})
        else:
            hplan.append({"trigger": f"收盤跌破 {_fmt_price(defense_price)}（防守價）",
                          "act": f"賣出波段部位的 1/2{core_act}"})
            lowers = sorted([a for a in anchors if a["side"] == "below" and a["price"] < defense_price],
                            key=lambda a: a["price"], reverse=True)
            if lowers:
                a = lowers[0]
                hplan.append({"trigger": f"收盤再跌破 {_fmt_price(a['price'])}（{a['label']}）",
                              "act": f"波段部位全部出場{core_act}"})
    if action in ("加碼", "續抱", "試單", "觀望"):
        ma_aboves = sorted([a for a in anchors if a["side"] == "above" and a["label"].startswith("MA")],
                           key=lambda a: a["price"])
        if ma_aboves:
            a = ma_aboves[0]
            if market_banned:
                # 禁新倉：加碼/回補都是新增部位，一律不加、維持既有（跟 bull 劇本同語意）。
                verb = "加碼" if action == "加碼" else "回補"
                add_act = f"大盤禁新倉，不{verb}、維持既有部位"
            elif action == "加碼":
                if trial_only:
                    add_act = "大盤僅限試單，加碼縮到 10 萬"
                else:
                    add_act = f"第一段可加碼 20 萬（總上限 {add_cap}）" if add_cap else "可加碼 20 萬"
            else:
                add_act = "可回補 10 萬"
            hplan.append({"trigger": f"站回 {a['label']} {_fmt_price(a['price'])} 且法人連 2 日買超",
                          "act": f"{add_act}{core_act}"})

    if defense_exec:
        if action == "出場":
            htail = f"，跌破 {_fmt_price(defense_price)} 前分批出清"
        elif action == "減碼":
            htail = f"，跌破 {_fmt_price(defense_price)} 收盤前完成減碼"
        else:
            htail = f"，跌破 {_fmt_price(defense_price)} 收盤再降一半波段部位"
    else:
        htail = ""
    holder_text = f"{_HOLDER_TEXT.get(action, action)}{htail}{core_txt}。"

    # ---- nonholder ----（market_banned/trial_only 於函式頂端已定義，holder/nonholder 共用）
    entry = _nonholder_entry(price, tech_facts, entry_condition, anchors)
    nplan = []
    if entry:
        if market_banned:
            nplan.append({"trigger": entry["trigger"],
                          "act": f"暫不進場（大盤禁新倉），{entry['trigger']}後再評估"})
        elif action in ("減碼", "出場"):
            nplan.append({"trigger": entry["trigger"], "act": "確認止穩後再考慮試單 10 萬"})
        elif action == "加碼" and not trial_only:
            act = f"分批布局，第一段 20 萬（總上限 {add_cap}）" if add_cap else "分批布局 20 萬"
            nplan.append({"trigger": entry["trigger"], "act": act})
        else:
            nplan.append({"trigger": entry["trigger"], "act": "試單 10 萬"})

    if entry is None:
        nonholder_text = "資料不足，暫不列進場條件，先觀望。"
    elif market_banned:
        nonholder_text = f"暫不進場（大盤禁新倉），{entry['trigger']}後再評估。"
    elif action in ("減碼", "出場"):
        nonholder_text = f"空手續抱觀望，法人止賣、{entry['trigger']}前不接刀。"
    elif action == "觀望":
        nonholder_text = f"先不進場，等{entry['trigger']}。"
    else:
        if action == "加碼" and not trial_only:
            amt = f"第一段 20 萬（總上限 {add_cap}）" if add_cap else "20 萬"
        else:
            amt = "10 萬"
        nonholder_text = f"空手可等{entry['trigger']}再試單 {amt}，不追高。"

    return {
        "holder": {"action_text": holder_text, "plan": hplan},
        "nonholder": {"action_text": nonholder_text, "plan": nplan},
    }


_STOP_BASIS_PHRASE = {
    "ATR": "近期波動下緣（2×ATR）",
    "關鍵均線": "關鍵均線支撐",
    "近20日低": "近 20 日低點",
    "區間下限": "-8%～-15% 停損區間下限",
}


def build_defense_explain(defense_price, stop_info):
    """一句話說明防守價怎麼來（如實描述 decision_engine.stop_reference 用的錨，不編）。"""
    if defense_price is None:
        return "尚無有效防守價（資料不足），暫以個人停損紀律為準。"
    basis = (stop_info or {}).get("basis")
    clamped = (stop_info or {}).get("clamped")
    phrase = _STOP_BASIS_PHRASE.get(basis, "技術支撐")
    fmt = _fmt_price(defense_price)
    if clamped:
        return (f"防守價 {fmt}＝{phrase}與 -8%～-15% 停損帶取較近者"
                f"（原始錨落在停損帶外、已收斂至邊界）；跌破代表波段結構破壞。")
    return (f"防守價 {fmt}＝{phrase}，落在 -8%～-15% 停損帶內；"
            f"跌破代表波段結構破壞。")


# ---------- v1.7：中長線方向判讀 mid_long_reads ----------
_BIAS_LEAN = {"偏多": "up", "中性偏多": "up", "中性": "neutral",
             "中性偏空": "down", "偏空": "down"}

_FALLBACK_SUPPORT_PCT = 0.95
_FALLBACK_RESIST_PCT = 1.05

_NO_PRICE_PATH_TEXT = "資料不足，暫無法判讀走勢路徑。"
_NO_PRICE_FLIP_TEXT = "資料不足，暫無法判斷翻轉條件。"


def _mid_long_anchors(price, tech_facts, defense_price, entry_condition):
    """既有關鍵位（防守價/MA20/60/120/entry 錨），沿用 _executable_anchors 的 ≤15% 規則；
    entry 錨（未與既有錨重疊時）併入，供 path_text/flip_condition 的目標價取用。"""
    anchors = _executable_anchors(price, tech_facts, defense_price)
    ec = entry_condition or {}
    ep = ec.get("price")
    if ep is not None and _anchor_executable(ep, price) and \
       all(abs(ep - a["price"]) > 1e-9 for a in anchors):
        anchors.append({"label": "進場錨", "price": float(ep),
                        "side": "below" if ep < price else "above"})
    return anchors


def _nearest_or_fallback_price(anchors, side, fallback_label, price, fallback_pct):
    cands = sorted([a for a in anchors if a["side"] == side],
                   key=lambda a: a["price"], reverse=(side == "below"))
    if cands:
        return cands[0]["label"], cands[0]["price"]
    return fallback_label, round(price * fallback_pct, 1)


def _direction_read(bias, price, tech_facts, defense_price, entry_condition):
    """依 stance 方向與現價位置，從既有關鍵位組 path_text/flip_condition（沿用劇本層
    ≤15% 錨點規則，見 _mid_long_anchors）。price 缺（None/非正）→ 安全降級成一句話，
    不編數字。偏空→「可能先回測 X，守住才…」；偏多→「回測 Y 不破後挑戰 Z」；
    中性→區間震盪語言。flip_condition 一律指向相反方向的下一個 stance。"""
    if price is None or price <= 0:
        return _NO_PRICE_PATH_TEXT, _NO_PRICE_FLIP_TEXT

    lean = _BIAS_LEAN.get(bias, "neutral")
    anchors = _mid_long_anchors(price, tech_facts, defense_price, entry_condition)
    s_label, s_val = _nearest_or_fallback_price(anchors, "below", "近期支撐",
                                                price, _FALLBACK_SUPPORT_PCT)
    r_label, r_val = _nearest_or_fallback_price(anchors, "above", "近期壓力",
                                                price, _FALLBACK_RESIST_PCT)

    if lean == "down":
        path_text = f"可能先回測 {s_label} {_fmt_price(s_val)}，不破且法人止賣才有反轉條件"
        flip_condition = f"站回 {r_label} {_fmt_price(r_val)} 且連 2 日買超 → 轉中性偏多"
    elif lean == "up":
        path_text = f"回測 {s_label} {_fmt_price(s_val)} 不破後，可挑戰 {r_label} {_fmt_price(r_val)}"
        flip_condition = f"跌破 {s_label} {_fmt_price(s_val)} 且連 2 日賣超 → 轉中性偏空"
    else:
        path_text = (f"多在 {s_label} {_fmt_price(s_val)} 與 {r_label} {_fmt_price(r_val)} "
                    f"間震盪，等三燈或大盤訊號轉向再判斷")
        flip_condition = f"站回 {r_label} {_fmt_price(r_val)} 且連 2 日買超 → 轉中性偏多"
    return path_text, flip_condition


# swing basis：由 reason_codes 挑最多 3 條（trend/valuation/chips 各挑一，優先序見下），
# 刻意不收 fundamental_* ——那是 mid basis 的主場（估值＋營收），避免兩邊講同一件事。
_SWING_BASIS_ORDER = [
    "trend_weak", "trend_ok", "trend_mixed",
    "valuation_very_expensive", "valuation_expensive", "valuation_fair", "valuation_cheap",
    "chips_broken", "chips_weak", "chips_ok",
]
_SWING_BASIS_PHRASE = {
    "trend_ok": "月線結構偏多", "trend_mixed": "均線糾結、結構未定", "trend_weak": "月線結構空方",
    "valuation_cheap": "估值便宜", "valuation_fair": "估值合理",
    "valuation_expensive": "估值偏貴", "valuation_very_expensive": "估值很貴",
    "chips_ok": "外資籌碼偏多", "chips_weak": "外資籌碼偏弱", "chips_broken": "外資連賣",
}


def _swing_basis(reason_codes) -> List[str]:
    codes = reason_codes or []
    seen_kind, out = set(), []
    for code in _SWING_BASIS_ORDER:
        if code not in codes:
            continue
        kind = code.split("_")[0]
        if kind in seen_kind:
            continue
        seen_kind.add(kind)
        out.append(_SWING_BASIS_PHRASE[code])
        if len(out) == 3:
            break
    _fallbacks = ["資料有限，依現有燈號研判", "建議搭配三燈與大盤訊號綜合判斷"]
    while len(out) < 2:
        out.append(_fallbacks[len(out) % len(_fallbacks)])
    return out


def _mid_basis(valuation, rev_yoy, rev_avg3_yoy, rev_avg12_yoy, industry, ma_structure) -> List[str]:
    """mid basis：估值 band（含 PER 分位可用時）＋營收 YoY/加速度（近3月均−近12月均）＋
    產業別或月線結構，恰 3 條、含數字更好（缺資料一律講「資料不足」，不編）。"""
    val = valuation or {}
    band = val.get("band")
    per_pctile = val.get("current_percentile")
    if band:
        val_text = (f"估值{band}（PER 分位 {per_pctile*100:.0f}%）" if per_pctile is not None
                   else f"估值{band}")
    else:
        val_text = "估值資料不足"

    if rev_yoy is not None:
        if rev_avg3_yoy is not None and rev_avg12_yoy is not None:
            accel = rev_avg3_yoy - rev_avg12_yoy
            trend = "動能轉強" if accel > 0 else "動能放緩" if accel < 0 else "動能持平"
            rev_text = f"營收 YoY {rev_yoy:+.1f}%，近3月{trend}（加速度 {accel:+.1f}pp）"
        else:
            rev_text = f"營收 YoY {rev_yoy:+.1f}%"
    else:
        rev_text = "營收資料不足"

    if industry:
        structure_text = f"產業別：{industry}"
    elif ma_structure:
        structure_text = f"月線結構{ma_structure}"
    else:
        structure_text = "產業與月線結構資料不足"

    return [val_text, rev_text, structure_text]


def build_mid_long_reads(*, price, tech_facts, defense_price, entry_condition,
                         timeframes, valuation, reason_codes,
                         rev_yoy=None, rev_avg3_yoy=None, rev_avg12_yoy=None,
                         industry=None, ma_structure=None) -> Dict:
    """契約 v1.7 mid_long_reads：波段（swing）＋中期（mid）方向判讀。bias 直接引用
    timeframes 對應 stance（禁另算——見契約規則：『bias 派生自 primary_decision 的
    timeframes stance』），path_text/flip_condition 依 stance 方向與現價位置，從既有
    關鍵位（defense/MA 系列/entry 錨，≤15% 規則，見 _mid_long_anchors）組模板；swing
    basis 引 reason_codes 短語（技術/估值/籌碼），mid basis 用估值 band＋營收趨勢
    （YoY/加速度）＋產業或月線結構（2-3 條含數字）。純規則、不打網路；缺資料一律安全
    降級成一句話或『資料不足』，不編數字，整組不回 None（跟 forecast/short_scenarios
    不同——bias 永遠拿得到，contract 沒有標示這欄可整組 null）。"""
    tf = timeframes or {}
    swing_stance = (tf.get("swing") or {}).get("stance") or "中性"
    mid_stance = (tf.get("mid") or {}).get("stance") or "中性"

    swing_path, swing_flip = _direction_read(swing_stance, price, tech_facts,
                                             defense_price, entry_condition)
    mid_path, mid_flip = _direction_read(mid_stance, price, tech_facts,
                                         defense_price, entry_condition)

    return {
        "swing": {
            "bias": swing_stance,
            "path_text": swing_path,
            "flip_condition": swing_flip,
            "basis": _swing_basis(reason_codes),
        },
        "mid": {
            "bias": mid_stance,
            "path_text": mid_path,
            "flip_condition": mid_flip,
            "basis": _mid_basis(valuation, rev_yoy, rev_avg3_yoy, rev_avg12_yoy,
                                industry, ma_structure),
        },
    }


def generate_roles(codes, lights_facts, action):
    """§3.5 升級：六角色（技術/基本/籌碼分析師、風控長、魔鬼代言人、投資長）依 reason_codes
    ＋facts 產「有立場的完整句子」——支持寫為何站這邊（含數字）、反對寫這角色擔心什麼、
    驗證寫接下來看什麼指標翻多/翻空。魔鬼代言人對 action 提最強反例。模板依 codes 組合變化。"""
    codes = codes or []
    tech_f = _facts_of(lights_facts, "technical")
    fund_f = _facts_of(lights_facts, "fundamental")
    chip_f = _facts_of(lights_facts, "chips")

    def has(*cs):
        return any(c in codes for c in cs)

    yoy = _find_fact(fund_f, "YoY") or "營收資料有限"
    per = _find_fact(fund_f, "PER")
    net = _find_fact(chip_f, "法人淨額") or _find_fact(chip_f, "法人")
    streak = _find_fact(chip_f, "連續")
    ma_line = "、".join([s for s in tech_f if s.startswith("MA")]) or "均線資料有限"
    val_band = next((_REASON_PHRASE[c] for c in codes
                     if c in ("valuation_expensive", "valuation_very_expensive")), "")
    act_phrase = _ACTION_PHRASE.get(action, action)

    # 技術面分析師
    if has("trend_ok"):
        t_sup = [f"價量結構站上均線（{ma_line}），波段趨勢仍偏多，回檔是找買點而非逃命。"]
        t_opp = ["若出現爆量長黑或跌破 MA20 收盤，多頭排列會鬆動，追高風險升高。"]
    elif has("trend_mixed"):
        t_sup = [f"均線糾結、僅守長天期均線（{ma_line}），尚未跌破結構，先給中性不偏空。"]
        t_opp = ["MA20 已走平下彎、上方均線壓力沉重，站不回去前反彈都可能是逃命波。"]
    else:
        t_sup = []
        t_opp = [f"已跌破短中期均線（{ma_line}），技術轉空，此時進場等於接下墜的刀。"]
    roles = [{"role": "技術面分析師", "support": t_sup, "oppose": t_opp,
              "verify": ["連 3 日站穩 MA20 並帶量突破前高 → 翻多；跌破 MA60 收盤 → 翻空。"]}]

    # 基本面分析師
    if has("fundamental_broken"):
        f_sup, f_opp = [], [f"營收基本面已失效（{yoy}），成長故事被打破，估值再低也不宜接。"]
    elif has("fundamental_weak"):
        f_sup = [f"基本面尚在但動能轉弱（{yoy}），撐得住但不宜押重。"]
        f_opp = ["成長率若連兩月下滑，估值下修空間會被放大。"]
    else:
        f_sup = [f"基本面沒惡化、成長仍在（{yoy}），是續抱與逢低的底氣。"]
        f_opp = [f"{per} 已不便宜，好公司不等於好價格，追高要留意估值。" if per
                 else "股價已反映不少成長，追高要留意估值。"]
    roles.append({"role": "基本面分析師", "support": f_sup, "oppose": f_opp,
                  "verify": ["追蹤下月營收 YoY 是否維持、法說會展望有無下修。"]})

    # 籌碼面分析師
    if has("chips_broken"):
        c_sup, c_opp = [], [f"法人連日站賣方（{net}；{streak}），主力籌碼鬆動，反彈量縮即是出貨。"]
    elif has("chips_weak"):
        c_sup, c_opp = [], [f"法人偏空、買盤縮手（{net}），沒有大戶點火前漲勢難延續。"]
    else:
        c_sup = [f"法人站買方（{net}），籌碼歸邊、下檔有承接。"]
        c_opp = ["一旦外資由買轉賣，短線籌碼面會立刻轉弱，須盯緊當日買賣超。"]
    roles.append({"role": "籌碼面分析師", "support": c_sup, "oppose": c_opp,
                  "verify": ["確認外資／投信是否由賣轉買、連續買超天數能否翻正。"]})

    # 風控長
    r_sup = [f"防守價明確、下檔可量化，{act_phrase}都在停損紀律內執行。"]
    r_opp = []
    if has("valuation_warning"):
        r_opp.append("估值模型有 warning、Base 不可信，R/R 不宜當加碼依據，只看價格結構與停損。")
    if has("rr_insufficient"):
        r_opp.append("報酬風險比不足 2 倍，賺賠不對稱，寧可等更好的點。")
    if val_band:
        r_opp.append(f"{val_band}，一旦情緒反轉，殺估值的速度會很快。")
    if not r_opp:
        r_opp = ["最大風險是紀律沒守住——跌破防守價卻凹單。"]
    roles.append({"role": "風控長", "support": r_sup, "oppose": r_opp,
                  "verify": ["盯 R/R 是否站上 2 倍、防守價是否被收盤跌破。"]})

    # 魔鬼代言人（對 action 唱反調）
    bullish = action in ("加碼", "續抱", "試單")
    if bullish:
        d_sup = [f"最強的反方：{val_band or '估值偏高'}、{net or '法人偏空'}，"
                 f"此時{act_phrase}等於在派對尾聲進場，利多恐是出貨掩護。"]
        d_opp = ["若法人續賣、股價跌破防守價，回頭看今天的樂觀就是套牢起點。"]
        d_ver = ["刻意找反例：跌破防守價證明我對、站回均線且法人回補證明我錯。"]
    else:
        d_sup = [f"反過來想：{yoy}、股價已修正一段，"
                 f"此時{act_phrase}可能砍在阿呆谷、錯過基本面反彈。"]
        d_opp = ["若營收維持成長、法人回補並站回均線，過度保守會兩頭空。"]
        d_ver = ["刻意找反例：續破底證明我錯、營收與籌碼同步轉強證明過度保守。"]
    roles.append({"role": "魔鬼代言人", "support": d_sup, "oppose": d_opp, "verify": d_ver})

    # 投資長（綜合拍板）
    pos_reason = "、".join([p for p in [
        "趨勢仍在" if has("trend_ok") else "",
        "基本面沒壞" if has("fundamental_ok") else "",
        "籌碼歸邊" if has("chips_ok") else "",
    ] if p]) or "多方理由有限"
    neg_reason = "、".join([p for p in [
        "籌碼失效" if has("chips_broken") else ("籌碼偏空" if has("chips_weak") else ""),
        val_band,
        "趨勢轉弱" if has("trend_weak", "trend_mixed") else "",
    ] if p]) or "空方風險有限"
    roles.append({"role": "投資長",
                  "support": [f"綜合三面與風控，本週定調：{act_phrase}。"
                              f"多方是{pos_reason}，空方是{neg_reason}。"],
                  "oppose": ["在防守價與站回訊號明朗前不擴大部位，避免用單一利多改變整體判斷。"],
                  "verify": ["下一決策點：防守價是否守住、法人是否回補、下月營收是否達標。"]})
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
    # 短線 stance＝技術＋籌碼合成（沿用 decision_engine.time_frames 的 0.6t＋0.4c 權重），
    # 與 basis 文字「技術X＋籌碼Y」一致，不再只看技術燈丟掉籌碼（大檢查・邏輯組 Y6：
    # 舊派生版 stance 只由 t 派生，2330 技術中性→標「中性」，但籌碼 red 連賣，標籤與依據
    # 自相矛盾）。合成分數對映與 mid/swing 一樣落在契約五檔 enum 內。
    context = {
        "timeframes": {
            "short": {"label": "短線 1-4 週",
                      "stance": _short_stance(t, c),
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
