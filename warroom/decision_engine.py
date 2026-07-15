"""決策引擎：rating 五檔＋三時間框架＋進出場/停損＋R/R＋部位金額＋信心 0-100（規格 §3.2）。
全部純規則、可揭露輸入；LLM 不介入產數字。輸出併入 data/<id>.json 的 "decision" 區塊。
"""
from typing import Dict, List, Optional

import pandas as pd

RATINGS = ("買進", "試單", "續抱", "觀望", "減碼")
_L = {"green": 1, "amber": 0, "red": -1, "na": 0}
_ZH = {"green": "偏多", "amber": "中性", "red": "偏空", "na": "缺"}


# ---------- 波動度 ----------
def atr14(price_df, n: int = 14, ex_div_map: Optional[Dict] = None) -> Optional[float]:
    """ATR14（Wilder EWMA）。需 max/min/close 欄；資料 <n+1 列或缺欄 → None。
    ex_div_map={除息日: 每股配息}：在除息日用「配息還原後前收」算 TR，抑制除權息跳空
    對 ATR 的污染（規格 §3.2.1）。ex_div_map=None → 與 P0 行為一致。"""
    if price_df is None or len(price_df) < n + 1:
        return None
    df = price_df.sort_values("date").reset_index(drop=True)
    for col in ("max", "min", "close"):
        if col not in df.columns:
            return None
    high = pd.to_numeric(df["max"], errors="coerce")
    low = pd.to_numeric(df["min"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")
    prev = close.shift(1)
    if ex_div_map:
        # 除息日的「前收」下修當日配息額 → 移除機械式跳空（僅影響該日 TR）
        adj = df["date"].astype(str).map(lambda x: float(ex_div_map.get(x, 0.0)))
        prev = prev - adj.values
    tr = pd.concat([(high - low).abs(), (high - prev).abs(), (low - prev).abs()],
                   axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    return round(float(atr), 2) if pd.notna(atr) else None


def atr_percent_median(price_df, window: int = 240) -> Optional[float]:
    """近 1 年日振幅/收盤 的中位（波動 proxy，用來判斷「波動低於自身中位」）。"""
    if price_df is None or len(price_df) < 20:
        return None
    df = price_df.sort_values("date").reset_index(drop=True).tail(window)
    for col in ("max", "min", "close"):
        if col not in df.columns:
            return None
    high = pd.to_numeric(df["max"], errors="coerce")
    low = pd.to_numeric(df["min"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce").replace(0, pd.NA)
    rng = (high - low) / close
    m = rng.median()
    return round(float(m), 4) if pd.notna(m) else None


# ---------- rating 合成 ----------
def light_consistency_score(lights: List[str]) -> int:
    """三燈一致性 0-30：全同非中性 30；兩同非中性 22；一非中性 18；全中性 15；綠紅衝突 0。"""
    valid = [l for l in lights if l in ("green", "amber", "red")]
    if not valid:
        return 0
    if "green" in valid and "red" in valid:
        return 0
    if len(set(valid)) == 1 and valid[0] != "amber":
        return 30
    non_amber = [l for l in valid if l != "amber"]
    if non_amber:
        return 22 if len(non_amber) == 2 else 18
    return 15


def composite_score(f_light, t_light, c_light, per_percentile, market_light) -> float:
    """三燈加權（基本 0.4/技術 0.3/籌碼 0.3）＋估值分位調整＋大盤調整。"""
    base = 0.4 * _L[f_light] + 0.3 * _L[t_light] + 0.3 * _L[c_light]
    val_adj = 0.0
    if per_percentile is not None:
        if per_percentile > 0.85:
            val_adj = -0.2
        elif per_percentile < 0.35:
            val_adj = 0.1
    mkt_adj = 0.1 if market_light == "green" else -0.2 if market_light == "red" else 0.0
    return round(base + val_adj + mkt_adj, 3)


def rating(f_light, t_light, c_light, per_percentile, market_light, rr) -> str:
    """五檔 rating。R/R<1.5 一律不給「買進」（會退成續抱）。綠紅衝突 → 觀望。"""
    lights = [f_light, t_light, c_light]
    if "green" in lights and "red" in lights:
        return "觀望"
    score = composite_score(f_light, t_light, c_light, per_percentile, market_light)
    can_buy = rr is not None and rr >= 1.5
    if score >= 0.5 and can_buy:
        return "買進"
    if score >= 0.2 and can_buy:
        return "試單"
    if score <= -0.4:
        return "減碼"
    if score <= -0.15:
        return "觀望"
    return "續抱"


# ---------- 停損 / R/R ----------
def stop_reference(price, atr, key_ma, low20, min_pct=-0.15, max_pct=-0.08) -> Dict:
    """停損參考 = max(entry-2×ATR, 關鍵均線, 近20日低)，夾在現價 -8%~-15%。
    max_pct=-0.08（最淺）、min_pct=-0.15（最深）。"""
    cands = []
    if atr is not None:
        cands.append(("ATR", price - 2 * atr))
    if key_ma is not None:
        cands.append(("關鍵均線", key_ma))
    if low20 is not None:
        cands.append(("近20日低", low20))
    below = [(name, v) for name, v in cands if v is not None and v < price]
    if below:
        basis, raw = max(below, key=lambda x: x[1])  # 最靠近現價下方的防守
    else:
        basis, raw = "區間下限", price * (1 + max_pct)
    lo = price * (1 + min_pct)
    hi = price * (1 + max_pct)
    stop = min(max(raw, lo), hi)
    clamped = not (lo <= raw <= hi)
    return {"price": round(stop, 1), "pct": round(stop / price - 1, 4), "basis": basis,
            "clamped": clamped, "note": "參考防守位，接回自行判斷"}


def risk_reward(base_fair, price, stop_price) -> Optional[float]:
    """R/R = (base 合理價 − 現價) ÷ (現價 − 停損)。分母<=0 或缺值 → None。"""
    if base_fair is None or stop_price is None:
        return None
    downside = price - stop_price
    if downside <= 0:
        return None
    return round((base_fair - price) / downside, 2)


# ---------- 信心 0-100 ----------
def confidence_score(data_flags: Dict, lights, rr, market_light, valuation_penalty: int = 0) -> Dict:
    """完整度 30 + 一致性 30 + R/R 20 + regime 20，再扣估值缺失的 confidence_penalty。"""
    present = sum(1 for k in ("fundamental", "technical", "chips", "eps_statement")
                  if data_flags.get(k))
    completeness = round(30 * present / 4)
    consistency = light_consistency_score(lights)
    if rr is None:
        rr_score = 0
    elif rr >= 3:
        rr_score = 20
    elif rr >= 2.5:
        rr_score = 16
    elif rr >= 2:
        rr_score = 12
    elif rr >= 1.5:
        rr_score = 8
    else:
        rr_score = 0
    regime = 20 if market_light == "green" else 10 if market_light == "amber" else 0
    raw = completeness + consistency + rr_score + regime
    total = max(0, min(100, raw - (valuation_penalty or 0)))
    return {"total": total, "completeness": completeness, "consistency": consistency,
            "rr": rr_score, "regime": regime, "valuation_penalty": valuation_penalty or 0}


# ---------- 部位金額 ----------
def position_sizing(rr, confidence, lights, market_light, atr_pct, atr_median_pct,
                    data_incomplete, profile, price, stock_id) -> Dict:
    """金額制部位（規格 §3.2）。ladder 由高到低取第一個達標檔位（門檻皆為最低要求，較高檔位更嚴）。"""
    tiers = {t["name"]: t["amount"] for t in profile["position_tiers"]}
    conflict = ("green" in lights and "red" in lights)
    three_aligned = (len([l for l in lights if l in ("green", "amber", "red")]) == 3
                     and len(set(lights)) == 1 and lights[0] != "amber")
    low_vol = (atr_pct is not None and atr_median_pct is not None and atr_pct < atr_median_pct)
    if rr is None or rr < 1.5 or data_incomplete or conflict or market_light == "red":
        name, reason = "空手", "R/R<1.5／資料不足／訊號分歧／大盤紅燈 其一（保守）"
    elif rr > 3 and confidence > 80 and three_aligned and low_vol:
        name, reason = "極高信心", "R/R>3 且信心>80 且三燈一致且波動低於自身中位"
    elif rr > 2.5 and confidence > 75:
        name, reason = "加碼", "R/R>2.5 且信心>75"
    elif rr > 2 and confidence >= 65:
        name, reason = "標準", "R/R>2 且信心≥65 且大盤非紅燈"
    elif rr >= 1.5 and confidence >= 50:
        name, reason = "試單", "R/R 1.5-2 且信心 50-65"
    else:
        name, reason = "空手", "未達任一部位檔位門檻（保守）"
    amount = tiers[name]
    shares = int(amount // price) if amount > 0 and price > 0 else 0
    lots = shares // 1000       # 整張數
    odd_shares = shares % 1000  # 零股數
    odd_lot = odd_shares != 0   # 建議股數是否含零股
    core_note = ""
    if stock_id in profile.get("core_holdings", []):
        core_note = "此為核心持股，本建議僅供波段加減碼層判斷，不影響定期定額核心部位"
    return {"tier": name, "amount": amount, "odd_lot": odd_lot, "shares": shares,
            "lots": lots, "odd_shares": odd_shares,
            "reason": reason, "core_note": core_note}


# ---------- 進場條件 ----------
def entry_conditions(price, atr, low20, high20, ma20, avg_vol20) -> Dict:
    """回測型（支撐±0.5×ATR＋隔日收盤站回）／突破型（破近20日高＋量>1.3×20日均量）。"""
    pullback = "資料不足，暫不列回測型進場"
    if atr is not None and (ma20 is not None or low20 is not None):
        support = ma20 if ma20 is not None else low20
        band = 0.5 * atr
        pullback = (f"回測型：回檔至支撐 {support:.1f}±{band:.1f}（0.5×ATR）、"
                    f"隔日收盤站回不破再進")
    breakout = "資料不足，暫不列突破型進場"
    if high20 is not None and avg_vol20 is not None:
        breakout = (f"突破型：收盤帶量突破近20日高 {high20:.1f}、"
                    f"且量>1.3×20日均量（約 {1.3 * avg_vol20:,.0f}）")
    return {"pullback": pullback, "breakout": breakout}


# ---------- 三時間框架 ----------
def _rating_stance(r):
    return {"買進": "偏多", "試單": "偏多", "續抱": "中性偏多",
            "觀望": "中性", "減碼": "偏空"}.get(r, "中性")


def time_frames(lights, rating_main, fair_value, tech_ev, valuation) -> Dict:
    """短線（技術+籌碼）／波段（主 rating）／中期（基本面+估值）。"""
    f_light, t_light, c_light = lights

    def stance(s):
        return "偏多" if s > 0.2 else "偏空" if s < -0.2 else "中性"

    short_s = 0.6 * _L[t_light] + 0.4 * _L[c_light]
    pctile = valuation.get("current_percentile")
    val_bias = 0 if pctile is None else (-1 if pctile > 0.75 else 1)
    mid_s = 0.6 * _L[f_light] + 0.4 * val_bias
    ma20 = tech_ev.get("MA20")
    base = fair_value.get("base") if fair_value else None
    bull = fair_value.get("bull") if fair_value else None
    return {
        "short": {"label": "短線 1-4 週", "stance": stance(short_s),
                  "basis": f"技術{_ZH[t_light]}＋籌碼{_ZH[c_light]}為主",
                  "ref_price": (f"參考 MA20 {ma20}" if ma20 is not None else "—")},
        "swing": {"label": "波段 1-3 月（主）", "stance": _rating_stance(rating_main),
                  "basis": f"綜合三燈與估值：{rating_main}",
                  "ref_price": (f"合理價 Base {base}" if base is not None else "—")},
        "mid": {"label": "中期 3-12 月", "stance": stance(mid_s),
                "basis": f"基本面{_ZH[f_light]}＋估值分位",
                "ref_price": (f"樂觀目標 Bull {bull}" if bull is not None else "—")},
    }


# ---------- 失效條件三層 ----------
def invalidation(stop_price, rev_signals, chip_signals,
                 price=None, ex_dividend_today=False, ex_div_amt=0.0) -> Dict:
    """價格（防守位）／基本面（營收 YoY 轉負且連 2 月低於 6 月均）／籌碼（法人連3日同向賣且佔20日均量>15%）。
    價格層：price 給定時判斷是否跌破防守位；除息日用配息還原後收盤比對，機械式跳空不觸發
    （規格 §3.2.1）。price=None → 不納入 any_triggered（維持 P0 行為）。"""
    fund_hit = bool(rev_signals.get("yoy_negative") and rev_signals.get("below_6m_2months"))
    chip_hit = bool(chip_signals.get("sell_streak_ge3") and chip_signals.get("ratio_gt_15pct"))

    price_hit = False
    if price is not None and stop_price is not None:
        cmp_close = price + ex_div_amt if ex_dividend_today else price  # 除息日還原配息
        price_hit = cmp_close < stop_price
    if price is None:
        price_text = f"價格：跌破參考防守位 {stop_price} 且未快速收回"
    elif ex_dividend_today:
        price_text = ("價格：除息日，已用配息還原後收盤比對防守位 "
                      f"{stop_price}（機械式跳空不計失效）"
                      + ("（仍跌破，已觸發）" if price_hit else "（未觸發）"))
    else:
        price_text = (f"價格：收盤 {price} vs 防守位 {stop_price}"
                      + ("（已觸發）" if price_hit else "（未觸發）"))

    return {
        "price": price_text,
        "fundamental": "基本面：最新營收 YoY 轉負且連 2 月低於 6 月均"
                       + ("（已觸發）" if fund_hit else "（未觸發）"),
        "chips": "籌碼：法人連 3 日同向賣且賣超佔 20 日均量>15%"
                 + ("（已觸發）" if chip_hit else "（未觸發）"),
        "any_triggered": fund_hit or chip_hit or price_hit,
    }


# ---------- 組裝 ----------
def build_decision(price, lights, per_percentile, market_light, valuation,
                   atr, key_ma, low20, high20, ma20, avg_vol20,
                   atr_pct, atr_median_pct, data_flags, rev_signals, chip_signals,
                   profile, stock_id, ex_dividend_today=False, ex_div_amt=0.0) -> Dict:
    """把所有純片段組裝成 data/<id>.json 的 "decision" 區塊（見計畫 §介面契約）。"""
    fv = valuation.get("fair_value")
    base_fair = fv.get("base") if fv else None
    stop = stop_reference(price, atr, key_ma, low20)
    rr = risk_reward(base_fair, price, stop["price"])
    conf = confidence_score(data_flags, lights, rr, market_light,
                            valuation_penalty=valuation.get("confidence_penalty", 0))
    rate = rating(lights[0], lights[1], lights[2], per_percentile, market_light, rr)
    note = None
    if fv is None:
        # 估值不足（fair_value=None）：rating 上限為觀望，除非綜合分數已差到 <=-0.3 仍給減碼
        score = composite_score(lights[0], lights[1], lights[2], per_percentile, market_light)
        rate = "減碼" if score <= -0.3 else "觀望"
        note = "估值不足，僅供燈號參考"
    data_incomplete = sum(1 for k in ("fundamental", "technical", "chips")
                          if data_flags.get(k)) < 3
    pos = position_sizing(rr, conf["total"], lights, market_light, atr_pct, atr_median_pct,
                          data_incomplete, profile, price, stock_id)
    entries = entry_conditions(price, atr, low20, high20, ma20, avg_vol20)
    frames = time_frames(lights, rate, fv or {}, {"MA20": ma20}, valuation)
    inval = invalidation(stop["price"], rev_signals, chip_signals,
                         price=price, ex_dividend_today=ex_dividend_today,
                         ex_div_amt=ex_div_amt)
    return {
        "rating": rate,
        "fair_value": fv,
        "valuation": {k: valuation.get(k) for k in
                      ("path", "eps_ttm", "eps_source", "eps_forward", "growth_used",
                       "multiples", "current_multiple", "current_percentile", "disclosure")},
        "risk_reward": rr,
        "stop": stop,
        "entry": entries,
        "position": pos,
        "confidence": conf,
        "time_frames": frames,
        "invalidation": inval,
        "as_of_price": round(price, 1),
        "note": note,
        "disclaimer": "本區塊為規則引擎輸出之決策輔助，非投資建議；"
                      "數字依固定規則計算，最終決策與風險由使用者承擔。",
    }
