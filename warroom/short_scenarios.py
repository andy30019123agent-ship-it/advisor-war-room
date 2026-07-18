"""短線劇本推演引擎（規格：docs/contracts/data-contract-v1.md「v1.4 增補」）。

三劇本（base 守住支撐／risk 跌破防守／bull 站上壓力）由「技術燈×籌碼燈」查表機率＋
大盤/防守/突破/籌碼修正項算出，再 clip 10~65% → normalize 100% → 整數化（差額補在
bull，即固定 base/risk/bull 順序的末位，不受最終依機率排序影響）。輸出陣列本身依
probability_pct 降冪排序，並依排序後名次套「劇本一/二/三」（跟 base/risk/bull 的 id
脫鉤——例：risk 機率最高時它會是「劇本一」）。

純函式、不打網路、不讀檔：所有輸入（現價／防守價／均線／近20日高低／三燈顏色／籌碼連買
賣天數／大盤傾向／大盤新倉閘門／空頭排列旗標／事件旗標／主結論 action）皆由呼叫端
（warroom/analyze_tw.py）算好傳入，方便離線測試每個查表格/修正項/紅線。

紅線（缺資料一律回 status=insufficient_data＋一句話，不編數字）：
- 停牌
- 現價／防守價／近20日高／近20日低 任一缺（或現價非正）
- 技術燈／籌碼燈／基本面燈 三者中有 2 個以上未知（None/na）
  （只 1 個未知時，若剛好是查表要用的技術/籌碼燈，退回中性 yellow 繼續算，
  graceful degrade，不因單一維度缺資料就整組開天窗）。
"""
from typing import Dict, List, Optional, Tuple

HORIZON = "1-4 週"

PROB_NOTE = "機率為規則估計（依三燈/籌碼/大盤查表），不是統計勝率，更不是保證。"
DISCLAIMER = "劇本＝條件推演；價位到了不代表會停，跟著失效條件走。"

_MSG_HALTED = "個股停牌中，暫無法推演短線劇本。"
_MSG_MISSING_LEVELS = "現價／近20日高低／防守價缺，暫無法推演短線劇本。"
_MSG_LIGHTS_UNKNOWN = "三燈資料不足，暫無法推演短線劇本。"

_ORDINAL = ["一", "二", "三"]

# 機率查表（技術燈×籌碼燈 → (base, risk, bull) 百分比）；key = 技術燈首字母＋籌碼燈首字母
# （g=green／y=yellow／r=red），插入順序即契約列出的順序。
_PROB_TABLE = {
    "gg": (50, 20, 30), "gy": (50, 25, 25), "gr": (45, 35, 20),
    "yg": (45, 25, 30), "yy": (50, 30, 20), "yr": (40, 40, 20),
    "rg": (40, 35, 25), "ry": (35, 45, 20), "rr": (30, 50, 20),
}
_COLOR_KEY = {"green": "g", "yellow": "y", "red": "r"}

_PROB_MIN, _PROB_MAX = 10, 65

# 關鍵位間距規則：候選彼此（依「離錨點近到遠」排序後，跟『前一個已收下的候選』比）要
# 差 ≥2%，太近就跳過看下一個——但第一個候選（離現價/防守價最近的那個，即 R1／
# 最近支撐）一律收下，不因為離錨點太近就跳過（那就是使用者要看的最近關鍵位，問題只在
# 「下一個」候選是不是跟它幾乎重疊，例如 MA60 2,324 與近20日低 2,325 只差 0.04%）。
_MIN_LEVEL_SPACING_PCT = 0.02

# 「近20日低」出現在壓力側（值＞現價，代表股價已跌破自己的近20日低、該低點反過來變成
# 上檔關卡）／「近20日高」出現在支撐側（值＜現價，代表股價已突破自己的近20日高、該高點
# 反過來變成下檔承接）時，原名稱會誤導（低點被當壓力講、高點被當支撐講），改用中性措辭。
_RESISTANCE_LABEL_OVERRIDE = {"近20日低": "前波低點"}
_SUPPORT_LABEL_OVERRIDE = {"近20日高": "前波高點"}

_STANCE_TEXT = {
    "increase": "維持加碼步調，依計畫分批進場",
    "hold": "維持續抱，不追價也不減碼",
    "small_entry": "維持小量試單，不重壓",
    "wait": "維持觀望，不進場",
    "reduce": "先減碼、控制部位",
    "exit": "維持出場紀律，反彈不追",
}


def _insufficient(message: str) -> Dict:
    return {"status": "insufficient_data", "message": message}


def _fmt(x) -> str:
    """人話文案用：四捨五入到整數＋千分位（沿用 primary_decision._fmt_price 同款寫法）。"""
    try:
        return f"{round(float(x)):,}"
    except (TypeError, ValueError):
        return "—"


def _round_px(x) -> float:
    return round(float(x), 1)


def _labeled_levels(defense_price, ma20, ma60, ma120, low20, high20
                    ) -> List[Tuple[str, float]]:
    pairs = [("防守價", defense_price), ("MA20", ma20), ("MA60", ma60),
             ("MA120", ma120), ("近20日低", low20), ("近20日高", high20)]
    return [(label, float(v)) for label, v in pairs if v is not None]


def _dedupe_by_spacing(items_sorted: List[Tuple[str, float]],
                       min_pct: float = _MIN_LEVEL_SPACING_PCT) -> List[Tuple[str, float]]:
    """items_sorted＝已依離錨點近到遠排序的候選。第一個必收；之後每個候選要跟『上一個
    已收下的候選』差 ≥min_pct 才收，太近就跳過看下一個（見上方常數說明）。"""
    out: List[Tuple[str, float]] = []
    for label, val in items_sorted:
        if not out or abs(val - out[-1][1]) / abs(out[-1][1]) >= min_pct:
            out.append((label, val))
    return out


def _supports(levels: List[Tuple[str, float]], price: float) -> List[Tuple[str, float]]:
    below = [(_SUPPORT_LABEL_OVERRIDE.get(l, l), v) for l, v in levels if v < price]
    below.sort(key=lambda x: x[1], reverse=True)  # 離現價最近的在前
    return _dedupe_by_spacing(below)


def _resistances(levels: List[Tuple[str, float]], price: float,
                 entry_anchor: Optional[float]) -> List[Tuple[str, float]]:
    above = [(_RESISTANCE_LABEL_OVERRIDE.get(l, l), v) for l, v in levels if v > price]
    if entry_anchor is not None and entry_anchor > price and \
       all(abs(entry_anchor - v) > 1e-9 for _, v in above):
        above.append(("進場錨", float(entry_anchor)))
    above.sort(key=lambda x: x[1])  # 離現價最近的在前
    return _dedupe_by_spacing(above)


def _key_levels(supports: List[Tuple[str, float]], resistances: List[Tuple[str, float]]) -> Dict:
    return {
        "supports": [_round_px(v) for _, v in supports[:3]],
        "resistances": [_round_px(v) for _, v in resistances[:3]],
    }


def _nearest_or_fallback(levels: List[Tuple[str, float]], fallback_label: str,
                         fallback_value: float) -> Tuple[str, float]:
    return levels[0] if levels else (fallback_label, fallback_value)


def _prob_lookup(technical_color: Optional[str], chips_color: Optional[str]
                 ) -> Tuple[float, float, float]:
    key = _COLOR_KEY.get(technical_color, "y") + _COLOR_KEY.get(chips_color, "y")
    return _PROB_TABLE[key]


def _apply_corrections(base, risk, bull, *, market_bias, defense_broken,
                       breakout_high20, chips_streak) -> Tuple[float, float, float]:
    if market_bias == "bear":
        risk += 5; bull -= 5
    elif market_bias == "bull":
        risk -= 5; bull += 5
    if defense_broken:
        risk += 10; base -= 10
    if breakout_high20:
        bull += 5; base -= 5
    if chips_streak >= 3:
        bull += 5; risk -= 5
    elif chips_streak <= -3:
        bull -= 5; risk += 5
    return base, risk, bull


def _finalize_probs(base, risk, bull) -> Tuple[int, int, int]:
    """clip 10~65% → normalize 總和 100% → 整數化，差額補在末位（bull，固定
    base/risk/bull 順序，跟依機率排序後的顯示順序無關）。"""
    clipped = [max(_PROB_MIN, min(_PROB_MAX, v)) for v in (base, risk, bull)]
    total = sum(clipped)
    scaled = clipped if total == 100 else [v * 100.0 / total for v in clipped]
    ints = [round(v) for v in scaled]
    diff = 100 - sum(ints)
    ints[-1] += diff
    return tuple(ints)  # type: ignore[return-value]


def _resolve_invalidation_refs(scenarios: List[Dict]) -> None:
    """就地把每個 scenario['invalidation'] 裡的佔位符（{REF:base}／{REF:risk}／
    {REF:top_non_bull}）換成排序定稿後的最終「劇本X」編號。scenarios 須已完成機率
    排序＋title 賦值（ordinal 直接從 title 的『劇本X』反推，不另外重算一次排序邏輯，
    避免跟主排序分岔）。

    修根因用：舊版在生成當下就寫死「切換劇本一/二」，但陣列最後會依機率重新排序、
    「劇本X」編號因此可能落到別的 id 上，導致 base/risk 互相失效條件指到自己
    （prod 實測：risk 排到劇本一時，它自己的失效文字卻寫「切換劇本一」）。
    - base 失效 → 一律指向 risk 的最終編號；risk 失效 → 一律指向 base 的最終編號
      （兩者 id 不同，天然不會自我指涉）。
    - bull 失效 → 指向排序後機率最高的那個非 bull 劇本（base 或 risk，看誰排前面）；
      bull 不可能是自己的 non_bull，天然不會自我指涉。
    """
    ordinal = {sc["id"]: sc["title"].split("・")[0] for sc in scenarios}  # 例："劇本一"
    top_non_bull = next((sc for sc in scenarios if sc["id"] != "bull"), None)
    refs = {
        "{REF:base}": ordinal.get("base", ""),
        "{REF:risk}": ordinal.get("risk", ""),
        "{REF:top_non_bull}": (top_non_bull["title"].split("・")[0] if top_non_bull else ""),
    }
    for sc in scenarios:
        text = sc["invalidation"]
        for token, replacement in refs.items():
            text = text.replace(token, replacement)
        sc["invalidation"] = text


def _base_scenario(price, support, resistance, is_bearish_arrangement,
                   position_delta) -> Dict:
    s_label, s_val = support
    r_label, r_val = resistance
    if is_bearish_arrangement:
        narrative = (f"空頭排列尚未扭轉，股價在{s_label}與{r_label}之間打底，"
                    f"反彈至壓力後仍震盪，等訊號轉強再說。")
    else:
        narrative = (f"股價在{s_label}與{r_label}之間找方向，"
                    f"等法人與均線訊號進一步確認再加減碼。")
    return {
        "id": "base",
        "title_suffix": f"守住{s_label}",
        "trigger": f"收盤守住 {_fmt(s_val)}（{s_label}）",
        "price_path": [_round_px(price), _round_px(s_val), _round_px(r_val)],
        "price_path_text": (f"{_fmt(price)} → 回測 {_fmt(s_val)}（{s_label}）→ "
                            f"反彈 {_fmt(r_val)}（{r_label}）震盪"),
        "narrative": narrative,
        # 佔位符，排序定稿、每個 id 的最終「劇本X」編號都確定後才由 _resolve_invalidation_refs
        # 統一替換（見該函式說明；不能在這裡寫死編號，scenarios 最後會依機率重排序）。
        "invalidation": f"收盤跌破 {_fmt(s_val)} 本劇本失效，切換{{REF:risk}}。",
        "action": {"stance": position_delta,
                  "text": _STANCE_TEXT.get(position_delta, "維持既有部位")},
    }


def _risk_scenario(price, defense_price, next_support, position_delta) -> Dict:
    n_label, n_val = next_support
    defense_broken = price < defense_price
    if defense_broken:
        trigger = f"已跌破防守 {_fmt(defense_price)}，觀察能否止穩"
        price_path = [_round_px(defense_price), _round_px(price), _round_px(n_val)]
        price_path_text = (f"已跌破 {_fmt(defense_price)}（防守價）→ 現價 {_fmt(price)} → "
                           f"續探 {_fmt(n_val)}（{n_label}），守穩才反彈")
    else:
        trigger = f"收盤跌破 {_fmt(defense_price)}（防守價）"
        price_path = [_round_px(price), _round_px(defense_price), _round_px(n_val)]
        price_path_text = (f"{_fmt(price)} → 跌破 {_fmt(defense_price)}（防守價）→ "
                           f"下探 {_fmt(n_val)}（{n_label}），守穩才反彈")
    narrative = ("跌破防守位代表波段結構轉弱，先執行紀律不留戀。"
                "等止穩訊號出現再評估是否回補。")
    if position_delta == "exit":
        r_stance, r_text = "wait", "已無波段部位，觀望等止穩訊號"
    else:
        r_stance, r_text = "reduce", "跌破即先減碼／執行停損，嚴守紀律不凹單"
    return {
        "id": "risk",
        "title_suffix": "防守已破，觀察止穩" if defense_broken else "跌破防守，下探支撐",
        "trigger": trigger,
        "price_path": price_path,
        "price_path_text": price_path_text,
        "narrative": narrative,
        "invalidation": f"站回 {_fmt(defense_price)}（防守價）本劇本失效，切換{{REF:base}}。",
        "action": {"stance": r_stance, "text": r_text},
    }


def _bull_action(primary_action, primary_position_delta, market_new_position):
    """bull 動作受大盤新倉閘門與主結論一致性雙重收斂（規格：與 primary_decision 不得打架）。"""
    if market_new_position == "禁止新增部位":
        return "wait", "不追價，僅觀察"
    if primary_position_delta in ("reduce", "exit"):
        return "wait", "站上壓力先觀察，主結論仍偏保守，不因單一劇本翻多加碼"
    if market_new_position == "僅限試單":
        return "small_entry", "站上壓力可先小量試單，不重壓"
    if primary_action == "加碼":
        return "increase", "站上壓力且籌碼延續，可依計畫分批加碼"
    return "small_entry", "站上壓力且量能／籌碼配合，可小量試單"


def _bull_scenario(price, res1, res2, primary_action, primary_position_delta,
                   market_new_position) -> Dict:
    """res2 可為 None：R1 之後的候選全部跟 R1 差距 <2%（間距規則濾光）時，不硬湊第三段，
    price_path 只給兩段（現價→R1）。"""
    r1_label, r1_val = res1
    stance, text = _bull_action(primary_action, primary_position_delta, market_new_position)
    narrative = (f"站上{r1_label}且法人買盤延續，才是轉強訊號。"
                f"站不穩前仍以區間對待，不追高。")
    if res2 is not None:
        r2_label, r2_val = res2
        price_path = [_round_px(price), _round_px(r1_val), _round_px(r2_val)]
        price_path_text = (f"{_fmt(price)} → 挑戰 {_fmt(r1_val)}（{r1_label}）→ "
                           f"突破後上看 {_fmt(r2_val)}（{r2_label}）")
    else:
        price_path = [_round_px(price), _round_px(r1_val)]
        price_path_text = (f"{_fmt(price)} → 挑戰 {_fmt(r1_val)}（{r1_label}），"
                           f"站穩後再觀察下一關卡（近端無明確次一壓力）")
    return {
        "id": "bull",
        "title_suffix": f"站上{r1_label}",
        "trigger": f"收盤站上 {_fmt(r1_val)}（{r1_label}）且法人連 2 日買超",
        "price_path": price_path,
        "price_path_text": price_path_text,
        "narrative": narrative,
        # bull 失效時切去哪個劇本要看「排序後機率最高的非 bull 劇本」，排序前無法確定，
        # 用專屬佔位符（見 _resolve_invalidation_refs）。
        "invalidation": f"站上 {_fmt(r1_val)} 後量縮不過，本劇本失效，切換{{REF:top_non_bull}}。",
        "action": {"stance": stance, "text": text},
    }


def build_short_scenarios(
    *,
    current_price: Optional[float],
    defense_price: Optional[float],
    low20: Optional[float],
    high20: Optional[float],
    ma20: Optional[float] = None,
    ma60: Optional[float] = None,
    ma120: Optional[float] = None,
    entry_anchor: Optional[float] = None,
    technical_color: Optional[str] = None,
    chips_color: Optional[str] = None,
    fundamental_color: Optional[str] = None,
    chips_streak: int = 0,
    market_bias: str = "neutral",
    market_new_position: Optional[str] = None,
    is_bearish_arrangement: bool = False,
    event_within_14d: bool = False,
    primary_action: Optional[str] = None,
    primary_position_delta: str = "hold",
    halted: bool = False,
) -> Dict:
    """組出契約 v1.4 short_scenarios 區塊。純函式，見模組頂端說明。"""
    if halted:
        return _insufficient(_MSG_HALTED)
    if any(v is None for v in (current_price, defense_price, low20, high20)):
        return _insufficient(_MSG_MISSING_LEVELS)
    if current_price <= 0:
        return _insufficient(_MSG_MISSING_LEVELS)

    unknown = sum(1 for c in (fundamental_color, technical_color, chips_color)
                 if c not in ("green", "yellow", "red"))
    if unknown >= 2:
        return _insufficient(_MSG_LIGHTS_UNKNOWN)

    price = float(current_price)
    defense_price = float(defense_price)
    low20 = float(low20)
    high20 = float(high20)

    levels = _labeled_levels(defense_price, ma20, ma60, ma120, low20, high20)
    supports = _supports(levels, price)
    resistances = _resistances(levels, price, entry_anchor)
    key_levels = _key_levels(supports, resistances)

    support = _nearest_or_fallback(supports, "近期支撐", _round_px(price * 0.95))
    resistance = _nearest_or_fallback(resistances, "近期壓力", _round_px(price * 1.05))

    below_defense = [(_SUPPORT_LABEL_OVERRIDE.get(l, l), v) for l, v in levels
                     if v < defense_price and l != "防守價"]
    below_defense.sort(key=lambda x: x[1], reverse=True)
    below_defense = _dedupe_by_spacing(below_defense)
    next_support = _nearest_or_fallback(below_defense, "次一支撐",
                                        _round_px(defense_price * 0.95))

    # bull R1／R2：R1＝最近壓力（一律收下，不因離現價太近而跳過）；R2＝resistances 已經
    # 依間距規則去重過，第二個候選跟 R1 保證 ≥2%——沒有第二個就是「候選都太近」，2 段
    # price_path 交給 _bull_scenario 處理，不合成假的第三段。
    res1 = resistances[0] if resistances else resistance
    res2 = resistances[1] if len(resistances) >= 2 else None

    # 機率：查表 → 修正項 → clip/normalize/整數化
    base_p, risk_p, bull_p = _prob_lookup(technical_color, chips_color)
    defense_broken = price < defense_price
    breakout_high20 = price > high20
    base_p, risk_p, bull_p = _apply_corrections(
        base_p, risk_p, bull_p, market_bias=market_bias, defense_broken=defense_broken,
        breakout_high20=breakout_high20, chips_streak=chips_streak)
    base_pct, risk_pct, bull_pct = _finalize_probs(base_p, risk_p, bull_p)

    scenarios = [
        {**_base_scenario(price, support, resistance, is_bearish_arrangement,
                          primary_position_delta), "probability_pct": base_pct},
        {**_risk_scenario(price, defense_price, next_support, primary_position_delta),
         "probability_pct": risk_pct},
        {**_bull_scenario(price, res1, res2, primary_action, primary_position_delta,
                          market_new_position), "probability_pct": bull_pct},
    ]

    # 依機率降冪排序（同分維持 base>risk>bull 的固定順序，sorted 穩定排序天然保證）；
    # 排序後名次套「劇本一/二/三」（跟 id 脫鉤——見模組頂端說明）。
    scenarios.sort(key=lambda s: s["probability_pct"], reverse=True)
    for i, sc in enumerate(scenarios):
        sc["title"] = f"劇本{_ORDINAL[i]}・{sc.pop('title_suffix')}"

    # 編號定稿後才解析 invalidation 的跨劇本引用（見該函式說明：修「引用指到自己」根因）。
    _resolve_invalidation_refs(scenarios)

    if event_within_14d:
        for sc in scenarios:
            sc["narrative"] = f"事件前不押注：{sc['narrative']}"

    return {
        "status": "ok",
        "horizon": HORIZON,
        "key_levels": key_levels,
        "scenarios": scenarios,
        "prob_note": PROB_NOTE,
        "disclaimer": DISCLAIMER,
    }
