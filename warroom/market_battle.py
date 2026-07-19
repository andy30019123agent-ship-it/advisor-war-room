"""首頁大盤作戰區引擎（規格：docs/contracts/data-contract-v1.md「v1.8 增補」）。

daily.json 的 market_battle（整組可 null）：TAIEX 60 交易日 K 線＋關鍵位＋大盤版短線劇本
（複用 warroom/short_scenarios.py 的查表／修正／normalize／劇本排序機制，不複製貼上）＋
外資流向／領先族群／美股隔夜＋GBM 一個月區間。

純函式、不打網路：所有輸入（TAIEX 日線 df／全市場外資買賣超 df／領先族群清單／US 指數
變化）皆由呼叫端（warroom/build_snapshots.py 的 fetch_market_inputs()）抓好傳入，網路呼叫
集中在該處（同 short_scenarios.py／forecast.py 的既有設計原則）。

大盤劇本與個股 short_scenarios 的映射關係（v1.8 契約「生成規則」）：
- 技術燈：TAIEX 站上 MA20>MA60>MA120（多頭排列）→ green；跌破月季線（現價<MA20 且
  MA20<MA60）→ red；其餘 yellow。跟 analyze_tw.technical() 判多空排列同一組規則。
- 籌碼燈：外資連買≥3 日 green／連賣≥3 日 red／其餘 yellow（外資連買賣天數見
  build_foreign_streak，資料源＝FinMind taiwan_stock_institutional_investors_total 全市場
  合計，單位元→ /1e8 轉億元）。
- 機率查表／修正項／clip-normalize-整數化／劇本排序＋編號／invalidation 跨劇本引用解析，
  全部直接 import short_scenarios 的內部函式重用（_prob_lookup／_apply_corrections／
  _finalize_probs／_dedupe_by_spacing／_resolve_invalidation_refs／_fmt／_round_px／
  _ORDINAL／HORIZON／PROB_NOTE／DISCLAIMER），不重寫一份查表。個股版的機率校正覆蓋
  （data/prob_calibration.json）不套用在大盤——該檔只累積個股 bucket 的 realized 頻率，
  跟大盤是不同母體，故本模組固定用內建 _PROB_TABLE（呼叫 _prob_lookup 而非
  _resolve_probs，略過校正讀檔）。
- 修正項輸入來源改用大盤自身訊號（因為「大盤」不能再拿另一個大盤傾向來修正自己，形成套
  套邏輯）：
    market_bias  → 契約明定「改用 VIX 單日 ±8% 與美股 SOX 方向」（見 _vix_sox_bias）。
    defense_broken → TAIEX 沒有個股式的「防守價」，改用 MA60（季線）當作與技術紅燈規則
      對齊的關鍵防線（現價跌破季線）。
    breakout_high20 → 個股版比對近20日高；大盤 key_levels 用的是近60日高（契約明定關鍵位
      ＝近20日低＋MA20/60/120＋近60日高，跟個股的20/20不同window），故此處比對近60日高，
      沿用同一個「突破近端高點」修正語意。
    chips_streak → 外資連買賣訊號本身（買=正、賣=負），跟個股版語意完全相同，直接重用。
- 三劇本模板（base 守住支撐／risk 跌破季線／bull 站上壓力）為大盤量身重寫文案（個股模板
  講「防守價」，大盤沒有這個詞），但沿用同樣的資料形狀（id/title/trigger/price_path/
  price_path_text/narrative/invalidation/action）與 invalidation 佔位符機制。
- action 用曝險語言（維持防禦／降曝險／可回補試單）取代個股的持股/部位語言；bull 劇本受
  exposure_guidance.new_position 閘門收斂（禁止新增部位時不得出現「可回補試單」字樣）。
- 關鍵位間距去重沿用 short_scenarios._dedupe_by_spacing，但門檻改 1.5%（契約 JSON 範例
  註解＝「間距 ≥1.5%」，KEY_LEVEL_MIN_SPACING_PCT）。
- forecast_range_m1 直接呼叫 warroom/forecast.py 的 build_forecast()（同一顆 GBM 引擎，
  drift=0 同規則），取 horizons.m1.prob_range_70；TAIEX 序列 <120 根（MIN_BARS）該函式自己
  回 None，這裡跟著回 None，不編數字。
"""
import json
from typing import Dict, List, Optional, Tuple

import pandas as pd

from warroom.chips_v2 import _streak
from warroom.forecast import build_forecast
from warroom.short_scenarios import (
    DISCLAIMER,
    HORIZON,
    PROB_NOTE,
    _ORDINAL,
    _apply_corrections,
    _dedupe_by_spacing,
    _finalize_probs,
    _fmt,
    _nearest_or_fallback,
    _prob_lookup,
    _resolve_invalidation_refs,
    _round_px,
)

MIN_OHLC_BARS = 20
DISPLAY_OHLC_BARS = 60
LOW_WINDOW = 20
HIGH_WINDOW = 60
KEY_LEVEL_MIN_SPACING_PCT = 0.015
FOREIGN_STREAK_WINDOW = 10
VIX_EXTREME_PCT = 8.0

TW_SECTORS_PATH = "data/tw_sectors.json"
LEADING_SECTORS_TOP_N = 2

_MSG_INSUFFICIENT = "TAIEX 關鍵位資料不足，暫無法推演大盤劇本。"


# ---------- TAIEX K 線／均線／關鍵位 ----------
def build_taiex_ohlc(df, n: int = DISPLAY_OHLC_BARS) -> Optional[List[Dict]]:
    """近 n（預設 60）交易日 TAIEX 日 K。欄位對映同 analyze_tw.build_ohlc
    （open/max/min/close），但 v（成交量）契約明定給 null（大盤指數無單一成交量意義）。
    有效根數 <MIN_OHLC_BARS 整組回 None；20~59 根照實際根數給，只有 ≥60 根才截斷取最後 60。
    """
    if df is None or len(df) == 0:
        return None
    d = df.sort_values("date").reset_index(drop=True)
    o_c = "open" if "open" in d.columns else None
    h_c = "max" if "max" in d.columns else "high" if "high" in d.columns else None
    l_c = "min" if "min" in d.columns else "low" if "low" in d.columns else None
    c_c = "close" if "close" in d.columns else None
    if not all((o_c, h_c, l_c, c_c)):
        return None
    out = []
    for _, row in d.tail(n).iterrows():
        o = pd.to_numeric(row[o_c], errors="coerce")
        h = pd.to_numeric(row[h_c], errors="coerce")
        l = pd.to_numeric(row[l_c], errors="coerce")
        c = pd.to_numeric(row[c_c], errors="coerce")
        if any(pd.isna(x) for x in (o, h, l, c)):
            continue
        out.append({
            "d": str(row["date"])[:10],
            "o": round(float(o), 1), "h": round(float(h), 1),
            "l": round(float(l), 1), "c": round(float(c), 1),
            "v": None,
        })
    return out if len(out) >= MIN_OHLC_BARS else None


def _market_levels(df) -> Dict:
    """現價／MA20/60/120／近20日低（不含當日）／近60日高（不含當日）。任一均線樣本不足
    給 None（graceful，不強制整組開天窗——只有 key_levels/scenarios 用到的欄位缺才降級）。"""
    d = df.sort_values("date").reset_index(drop=True)
    close = pd.to_numeric(d["close"], errors="coerce")
    n = len(close)

    def _ma(window: int) -> Optional[float]:
        if n < window:
            return None
        v = close.rolling(window).mean().iloc[-1]
        return float(v) if pd.notna(v) else None

    hi_c = "max" if "max" in d.columns else "high" if "high" in d.columns else "close"
    lo_c = "min" if "min" in d.columns else "low" if "low" in d.columns else "close"

    def _prior_extreme(col: str, window: int, how: str) -> Optional[float]:
        s = pd.to_numeric(d[col], errors="coerce").shift(1).tail(window)
        v = s.min() if how == "min" else s.max()
        return float(v) if pd.notna(v) else None

    price = float(close.iloc[-1]) if n and pd.notna(close.iloc[-1]) else None
    return {
        "price": price, "ma20": _ma(20), "ma60": _ma(60), "ma120": _ma(120),
        "low20": _prior_extreme(lo_c, LOW_WINDOW, "min"),
        "high60": _prior_extreme(hi_c, HIGH_WINDOW, "max"),
    }


def _labeled_levels(ma20, ma60, ma120, low20, high60) -> List[Tuple[str, float]]:
    pairs = [("MA20", ma20), ("MA60", ma60), ("MA120", ma120),
             ("近20日低", low20), ("近60日高", high60)]
    return [(label, float(v)) for label, v in pairs if v is not None]


def _supports(levels: List[Tuple[str, float]], price: float) -> List[Tuple[str, float]]:
    below = [(l, v) for l, v in levels if v < price]
    below.sort(key=lambda x: x[1], reverse=True)  # 離現價最近的在前
    return _dedupe_by_spacing(below, KEY_LEVEL_MIN_SPACING_PCT)


def _resistances(levels: List[Tuple[str, float]], price: float) -> List[Tuple[str, float]]:
    above = [(l, v) for l, v in levels if v > price]
    above.sort(key=lambda x: x[1])  # 離現價最近的在前
    return _dedupe_by_spacing(above, KEY_LEVEL_MIN_SPACING_PCT)


def _key_levels_block(supports: List[Tuple[str, float]],
                      resistances: List[Tuple[str, float]]) -> Dict:
    return {
        "supports": [_round_px(v) for _, v in supports[:3]],
        "resistances": [_round_px(v) for _, v in resistances[:3]],
    }


def _technical_color(price: Optional[float], ma20: Optional[float],
                     ma60: Optional[float], ma120: Optional[float]) -> str:
    """多頭排列 green／跌破月季線 red／其餘 yellow。green 沿用 analyze_tw.technical 的多頭
    排列判斷（price>MA20>MA60>MA120）；red 採契約字面義「跌破月季線」＝現價同時跌破
    MA20 與 MA60（不要求 MA20<MA60 的排列順序）——不能照搬 analyze_tw.technical 的 bear
    判斷（該判斷額外要求 ma20<ma60，代表「均線已死叉排列」的個股空頭排列語意，比「跌破
    月季線」嚴格）。實測驗證：2026-07-19 TAIEX 42,671 同時跌破 MA20 45,850.9／MA60
    43,525.1，但兩條均線本身還沒死叉（MA20 仍 > MA60，急跌剛發生、均線來不及反應）；若
    沿用 analyze_tw 的排列判斷會誤判成 yellow，跟「大盤才剛重摔穿所有均線」的實況不符，
    故 red 只看「現價是否雙雙跌破」。"""
    if price is None:
        return "yellow"
    bull = (None not in (ma20, ma60, ma120)) and price > ma20 > ma60 > ma120
    red = (ma20 is not None and ma60 is not None) and price < ma20 and price < ma60
    return "green" if bull else "red" if red else "yellow"


def _vix_sox_bias(vix_chg: Optional[float], sox_chg: Optional[float]) -> str:
    """大盤自身的「大盤傾向」修正項（契約：改用 VIX 單日 ±8% 與美股 SOX 方向）：
    VIX 單日跳動 ≥8% 視為恐慌極端優先判斷；沒有極端 VIX 訊號時退而看 SOX 前一夜方向。"""
    if vix_chg is not None and vix_chg >= VIX_EXTREME_PCT:
        return "bear"
    if vix_chg is not None and vix_chg <= -VIX_EXTREME_PCT:
        return "bull"
    if sox_chg is not None and sox_chg > 0:
        return "bull"
    if sox_chg is not None and sox_chg < 0:
        return "bear"
    return "neutral"


# ---------- flow：外資連買賣／領先族群／美股隔夜 ----------
def build_foreign_streak(foreign_df, window: int = FOREIGN_STREAK_WINDOW) -> Optional[Dict]:
    """全市場外資買賣超（FinMind taiwan_stock_institutional_investors_total，單位元）近
    window 個交易日：方向連續天數＋最新一日億元。streak 演算法重用 chips_v2._streak（同一套
    「從最新日往回數連續同向天數」規則，只是這裡餵的是全市場外資淨額而非單股單一法人組）。
    最新日淨額剛好 0（無方向）時 direction 落 "buy"、streak 天數為 0（同 _streak 的 0 邊界
    行為，非真正有方向的連續——契約沒有定義第三種 "flat" 方向列舉，這裡不新增）。
    無資料（df 缺／無 Foreign 列）→ None（graceful）。"""
    if foreign_df is None or len(foreign_df) == 0 or "name" not in foreign_df.columns:
        return None
    f = foreign_df[foreign_df["name"].str.contains("Foreign", case=False, na=False)]
    if len(f) == 0:
        return None
    f = f.copy()
    f["buy"] = pd.to_numeric(f["buy"], errors="coerce").fillna(0)
    f["sell"] = pd.to_numeric(f["sell"], errors="coerce").fillna(0)
    f["net_yi"] = (f["buy"] - f["sell"]) / 1e8
    daily = f.groupby("date")["net_yi"].sum().sort_index()
    nets = [float(x) for x in daily.tolist()][-window:]
    if not nets:
        return None
    direction = "sell" if nets[-1] < 0 else "buy"
    days = _streak(nets)
    return {"direction": direction, "days": days, "latest_yi": round(nets[-1], 1)}


def load_leading_sectors(path: str = TW_SECTORS_PATH,
                         top_n: int = LEADING_SECTORS_TOP_N) -> List[str]:
    """data/tw_sectors.json 領先族群 top N（依 rank 由小到大）。缺檔/壞檔一律回空陣列
    （契約：「無資料空陣列」），不編族群名。"""
    try:
        with open(path, encoding="utf-8") as f:
            groups = json.load(f)
        ranked = sorted((g for g in (groups or []) if g.get("group")),
                        key=lambda g: g.get("rank", 1 << 30))
        return [g["group"] for g in ranked[:top_n]]
    except Exception:
        return []


def build_us_overnight(us: Optional[List[Dict]]) -> List[Dict]:
    """從 build_snapshots 已抓好的 us 陣列（market.taiex 同一份）取 SPX/SOX（契約
    flow.us_overnight 只列這兩檔）。缺該 id → 不列入（不編數字）。"""
    by_id = {u.get("id"): u.get("change_pct") for u in (us or [])}
    return [{"id": id_, "change_pct": by_id.get(id_)} for id_ in ("SPX", "SOX") if id_ in by_id]


# ---------- 大盤版三劇本（模板重寫，機制重用） ----------
def _base_scenario(price, support, resistance, is_bearish_arrangement) -> Dict:
    s_label, s_val = support
    r_label, r_val = resistance
    if is_bearish_arrangement:
        narrative = (f"大盤空頭排列尚未扭轉，指數在{s_label}與{r_label}之間震盪尋底，"
                    f"反彈至壓力後仍拉回，等外資止賣訊號再說。")
    else:
        narrative = (f"指數在{s_label}與{r_label}之間找方向，"
                    f"等外資動向與均線結構進一步確認再調整曝險。")
    return {
        "id": "base",
        "title_suffix": f"守住{s_label}",
        "trigger": f"收盤守住 {_fmt(s_val)}（{s_label}）",
        "price_path": [_round_px(price), _round_px(s_val), _round_px(r_val)],
        "price_path_text": (f"{_fmt(price)} → 回測 {_fmt(s_val)}（{s_label}）→ "
                            f"反彈 {_fmt(r_val)}（{r_label}）震盪"),
        "narrative": narrative,
        "invalidation": f"收盤跌破 {_fmt(s_val)} 本劇本失效，切換{{REF:risk}}。",
        "action": {"stance": "hold", "text": "維持防禦，不因單一劇本加減碼"},
    }


def _risk_scenario(price, pivot, next_support) -> Dict:
    p_label, p_val = pivot
    n_label, n_val = next_support
    broken = price < p_val
    if broken:
        trigger = f"已跌破{p_label} {_fmt(p_val)}，觀察能否止穩"
        price_path = [_round_px(p_val), _round_px(price), _round_px(n_val)]
        price_path_text = (f"已跌破 {_fmt(p_val)}（{p_label}）→ 現價 {_fmt(price)} → "
                           f"續探 {_fmt(n_val)}（{n_label}），守穩才反彈")
        title_suffix = f"跌破{p_label}，觀察止穩"
    else:
        trigger = f"收盤跌破 {_fmt(p_val)}（{p_label}）"
        price_path = [_round_px(price), _round_px(p_val), _round_px(n_val)]
        price_path_text = (f"{_fmt(price)} → 跌破 {_fmt(p_val)}（{p_label}）→ "
                           f"下探 {_fmt(n_val)}（{n_label}），守穩才反彈")
        title_suffix = f"跌破{p_label}，下探支撐"
    narrative = "跌破季線代表大盤結構轉弱，先降曝險保守以對，等止穩訊號再評估回補。"
    return {
        "id": "risk",
        "title_suffix": title_suffix,
        "trigger": trigger,
        "price_path": price_path,
        "price_path_text": price_path_text,
        "narrative": narrative,
        "invalidation": f"站回 {_fmt(p_val)}（{p_label}）本劇本失效，切換{{REF:base}}。",
        "action": {"stance": "reduce", "text": "降曝險，控制股票總部位比重"},
    }


def _bull_action(market_new_position: Optional[str]) -> Tuple[str, str]:
    """bull 劇本受 exposure_guidance.new_position 閘門收斂（規格：禁新倉時不得出現
    「可回補試單」）。跟 short_scenarios._bull_action 同語意，這裡換成曝險語言。"""
    if market_new_position == "禁止新增部位":
        return "wait", "不追價，僅觀察"
    if market_new_position == "僅限試單":
        return "small_entry", "可回補試單，不重壓"
    return "small_entry", "可回補試單，留意量能是否延續"


def _bull_scenario(price, res1, res2, market_new_position) -> Dict:
    r1_label, r1_val = res1
    stance, text = _bull_action(market_new_position)
    narrative = (f"站上{r1_label}且外資買盤延續，才是轉強訊號。"
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
        "trigger": f"收盤站上 {_fmt(r1_val)}（{r1_label}）且外資連 2 日買超",
        "price_path": price_path,
        "price_path_text": price_path_text,
        "narrative": narrative,
        "invalidation": f"站上 {_fmt(r1_val)} 後量縮不過，本劇本失效，切換{{REF:top_non_bull}}。",
        "action": {"stance": stance, "text": text},
    }


def build_market_scenarios(
    *,
    current_price: Optional[float],
    low20: Optional[float],
    high60: Optional[float],
    ma20: Optional[float],
    ma60: Optional[float],
    ma120: Optional[float],
    technical_color: str,
    chips_color: str,
    chips_streak: int,
    vix_chg: Optional[float],
    sox_chg: Optional[float],
    market_new_position: Optional[str],
    is_bearish_arrangement: bool = False,
) -> Dict:
    """大盤版 short_scenarios（契約：「與個股 short_scenarios 同構：
    status/horizon/scenarios[3]/prob_note/disclaimer」，key_levels 不在此塊重複——已在
    market_battle 頂層算好一份單一事實源，見 build_market_battle）。"""
    if current_price is None or current_price <= 0 or low20 is None or high60 is None:
        return {"status": "insufficient_data", "message": _MSG_INSUFFICIENT}

    price = float(current_price)
    levels = _labeled_levels(ma20, ma60, ma120, low20, high60)
    supports = _supports(levels, price)
    resistances = _resistances(levels, price)
    # 候選可能真的是空的（例如指數連創 60 日新高，近端沒有任何歷史值高於現價）——跟
    # short_scenarios.build_short_scenarios 同款寬容：不因候選是空的就整組開天窗，退合成值
    # （現價 ±5%，同 short_scenarios._nearest_or_fallback 的既有 fallback 慣例）。
    support = _nearest_or_fallback(supports, "近期支撐", _round_px(price * 0.95))
    resistance = _nearest_or_fallback(resistances, "近期壓力", _round_px(price * 1.05))

    # risk 劇本的關鍵防線：優先用 MA60（季線，跟技術紅燈規則同一條線）；缺季線資料才退回
    # 最近支撐（見模組頂端「defense_broken」說明）。
    pivot = ("MA60", float(ma60)) if ma60 is not None else support
    below_pivot = [(l, v) for l, v in levels if v < pivot[1]]
    below_pivot.sort(key=lambda x: x[1], reverse=True)
    below_pivot = _dedupe_by_spacing(below_pivot, KEY_LEVEL_MIN_SPACING_PCT)
    next_support = below_pivot[0] if below_pivot else ("次一支撐", _round_px(pivot[1] * 0.98))

    # bull R1／R2：R1＝最近壓力（一律收下，含 fallback 合成值）；R2 沒有第二候選就不硬湊
    # （同 short_scenarios 的既有 2 段 price_path 處理）。
    res1 = resistances[0] if resistances else resistance
    res2 = resistances[1] if len(resistances) >= 2 else None

    base_p, risk_p, bull_p = _prob_lookup(technical_color, chips_color)
    market_bias = _vix_sox_bias(vix_chg, sox_chg)
    defense_broken = price < pivot[1]
    breakout_high60 = price > high60
    base_p, risk_p, bull_p = _apply_corrections(
        base_p, risk_p, bull_p, market_bias=market_bias, defense_broken=defense_broken,
        breakout_high20=breakout_high60, chips_streak=chips_streak)
    base_pct, risk_pct, bull_pct = _finalize_probs(base_p, risk_p, bull_p)

    scenarios = [
        {**_base_scenario(price, support, resistance, is_bearish_arrangement),
         "probability_pct": base_pct},
        {**_risk_scenario(price, pivot, next_support), "probability_pct": risk_pct},
        {**_bull_scenario(price, res1, res2, market_new_position), "probability_pct": bull_pct},
    ]
    scenarios.sort(key=lambda s: s["probability_pct"], reverse=True)
    for i, sc in enumerate(scenarios):
        sc["title"] = f"劇本{_ORDINAL[i]}・{sc.pop('title_suffix')}"
    _resolve_invalidation_refs(scenarios)

    return {
        "status": "ok",
        "horizon": HORIZON,
        "scenarios": scenarios,
        "prob_note": PROB_NOTE,
        "disclaimer": DISCLAIMER,
    }


# ---------- forecast_range_m1 ----------
def build_forecast_range_m1(taiex_df, data_date: Optional[str]) -> Optional[List[float]]:
    """GBM 餵 TAIEX 收盤序列（重用 warroom/forecast.py 同一顆引擎，drift=0 同規則），取
    m1（21 交易日）的 p15~p85。序列 <120 根（forecast.MIN_BARS）該函式自己回 None，這裡
    跟著回 None，不編數字。valuation 傳 None（大盤無估值錨，scenarios 欄位本函式不使用）。"""
    if taiex_df is None or not data_date:
        return None
    fc = build_forecast(taiex_df, None, data_date, "TAIEX")
    if not fc:
        return None
    return fc["horizons"]["m1"]["prob_range_70"]


# ---------- 組裝入口 ----------
def build_market_battle(
    *,
    taiex_df=None,
    foreign_df=None,
    leading_sectors: Optional[List[str]] = None,
    us: Optional[List[Dict]] = None,
    data_date: Optional[str] = None,
    market_new_position: Optional[str] = None,
    vix_chg: Optional[float] = None,
    sox_chg: Optional[float] = None,
) -> Optional[Dict]:
    """組出契約 v1.8 market_battle 區塊。整組可 None（TAIEX 序列抓不到／根數不足）。
    純函式：taiex_df/foreign_df 皆由呼叫端（build_snapshots.fetch_market_inputs）打網路
    抓好傳入，這裡不打網路。"""
    ohlc = build_taiex_ohlc(taiex_df)
    if ohlc is None:
        return None

    lv = _market_levels(taiex_df)
    price = lv["price"]
    levels = _labeled_levels(lv["ma20"], lv["ma60"], lv["ma120"], lv["low20"], lv["high60"])
    supports = _supports(levels, price) if price is not None else []
    resistances = _resistances(levels, price) if price is not None else []
    key_levels = _key_levels_block(supports, resistances)

    technical_color = _technical_color(price, lv["ma20"], lv["ma60"], lv["ma120"])
    foreign = build_foreign_streak(foreign_df)
    if foreign:
        if foreign["direction"] == "buy" and foreign["days"] >= 3:
            chips_color = "green"
        elif foreign["direction"] == "sell" and foreign["days"] >= 3:
            chips_color = "red"
        else:
            chips_color = "yellow"
        chips_streak_signed = foreign["days"] if foreign["direction"] == "buy" else -foreign["days"]
    else:
        chips_color, chips_streak_signed = "yellow", 0

    scenarios = build_market_scenarios(
        current_price=price, low20=lv["low20"], high60=lv["high60"],
        ma20=lv["ma20"], ma60=lv["ma60"], ma120=lv["ma120"],
        technical_color=technical_color, chips_color=chips_color,
        chips_streak=chips_streak_signed, vix_chg=vix_chg, sox_chg=sox_chg,
        market_new_position=market_new_position,
        is_bearish_arrangement=(technical_color == "red"),
    )

    return {
        "ohlc": ohlc,
        "key_levels": key_levels,
        "scenarios": scenarios,
        "flow": {
            "foreign_streak": foreign,
            "leading_sectors": leading_sectors or [],
            "us_overnight": build_us_overnight(us),
        },
        "forecast_range_m1": build_forecast_range_m1(taiex_df, data_date),
    }
