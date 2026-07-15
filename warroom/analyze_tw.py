"""Phase 1a — 台股個股「規則式紅綠燈」引擎（無 LLM，純數據＋固定規則）。
每個維度回傳 (燈號, 證據)：燈號 = green/amber/red，證據 = 說得出依據的數字。
投顧紀律：燈由規則算、門檻寫死、缺資料降級；LLM 之後只負責解讀與反駁，不改燈。
"""
import pandas as pd
from warroom.news import fetch_news
from warroom.finmind_cache import get_loader, cached_fetch
from warroom.profile import load_profile
from warroom.valuation import compute_valuation
from warroom.decision_engine import (
    atr14, atr_percent_median, build_decision,
)
from warroom.chips_v2 import chips_breakdown
from warroom.fundamentals import compute_fundamentals

LIGHT_SCORE = {"green": 1, "amber": 0, "red": -1, "na": 0}
LIGHT_ZH = {"green": "🟢偏多", "amber": "🟡中性", "red": "🔴偏空", "na": "⚪資料缺"}

_INFO_CACHE = None


def stock_name(stock_id):
    """台股中文名（FinMind 個股資訊，快取一次）。"""
    global _INFO_CACHE
    try:
        if _INFO_CACHE is None:
            _INFO_CACHE = get_loader().taiwan_stock_info()
        row = _INFO_CACHE[_INFO_CACHE["stock_id"] == stock_id]
        return row.iloc[0]["stock_name"] if len(row) else stock_id
    except Exception:
        return stock_id


def stock_industry(stock_id):
    """個股產業別（去重取第一筆；判斷金融/循環股走 PBR 路徑用）。"""
    global _INFO_CACHE
    try:
        if _INFO_CACHE is None:
            _INFO_CACHE = get_loader().taiwan_stock_info()
        row = _INFO_CACHE[_INFO_CACHE["stock_id"] == stock_id].drop_duplicates("stock_id")
        return row.iloc[0]["industry_category"] if len(row) else None
    except Exception:
        return None


# ---------- 抓資料 ----------
def fetch(stock_id):
    """抓個股所需各資料源。任一源失敗回 None（該維度後續標「資料缺」）。"""
    out = {}
    sources = [
        ("price", "taiwan_stock_daily", dict(stock_id=stock_id, start_date="2024-01-01")),
        ("rev", "taiwan_stock_month_revenue", dict(stock_id=stock_id, start_date="2023-01-01")),
        ("val", "taiwan_stock_per_pbr", dict(stock_id=stock_id, start_date="2021-01-01")),
        ("chip", "taiwan_stock_institutional_investors", dict(stock_id=stock_id, start_date="2026-04-01")),
        ("fs", "taiwan_stock_financial_statement", dict(stock_id=stock_id, start_date="2024-01-01")),
        ("bs", "taiwan_stock_balance_sheet", dict(stock_id=stock_id, start_date="2024-01-01")),
        ("cf", "taiwan_stock_cash_flows_statement", dict(stock_id=stock_id, start_date="2024-01-01")),
    ]
    for key, method, kw in sources:
        try:
            df = cached_fetch(method, **kw)
            out[key] = df if (df is not None and len(df) > 0) else None
        except Exception:
            out[key] = None
    return out


# ---------- 技術面 ----------
def rsi(series, n=14):
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-9)
    out = 100 - 100 / (1 + rs)
    out[(gain == 0) & (loss == 0)] = 50  # 完全平盤 → 中性，避免被誤判超賣
    return out


def prior_n_high_low(df, hi_c, lo_c, n=20):
    """前 n 個「完整」交易日的高低點（不含當日，shift(1) 後再 tail(n)）。
    用於突破/停損參考：避免當日本身即創高時，「破近20日高」永遠不成立、也避免 lookahead。
    df 需已依 date 排序。回 (low_n, high_n)，資料不足時可能為 NaN。
    """
    hi = pd.to_numeric(df[hi_c], errors="coerce").shift(1).tail(n)
    lo = pd.to_numeric(df[lo_c], errors="coerce").shift(1).tail(n)
    hi_max, lo_min = hi.max(), lo.min()
    return (float(lo_min) if pd.notna(lo_min) else None,
            float(hi_max) if pd.notna(hi_max) else None)


def technical(price):
    df = price.sort_values("date").reset_index(drop=True)
    c = df["close"]
    n_rows = len(c)
    # 最少筆數門檻：不足者標「樣本不足」，不進燈號判斷（規格 §4 backlog ②）
    ma = {n: (c.rolling(n).mean().iloc[-1] if n_rows >= n else None) for n in (5, 20, 60, 120)}
    last = c.iloc[-1]
    r = rsi(c).iloc[-1]
    vol = df["Trading_Volume"]
    vol_ratio = vol.iloc[-1] / vol.tail(20).mean()

    bull = (None not in (ma[20], ma[60], ma[120])) and last > ma[20] > ma[60] > ma[120]
    bear = (ma[20] is not None and ma[60] is not None) and last < ma[20] and ma[20] < ma[60]
    light = "green" if bull else "red" if bear else "amber"
    # 過熱保護：多頭但 RSI 過熱 → 降一級到中性（提醒別追高）
    note = []
    if r > 80:
        note.append(f"RSI {r:.0f} 過熱")
        if light == "green":
            light = "amber"
    elif r < 20:
        note.append(f"RSI {r:.0f} 超賣")
    if vol_ratio > 1.5:
        note.append(f"爆量 {vol_ratio:.1f}×均量")

    # 技術位（純規則參考，非買賣建議）：從均線＋近期高低點挑最靠近的支撐/壓力
    hi_c = "max" if "max" in df.columns else "high" if "high" in df.columns else "close"
    lo_c = "min" if "min" in df.columns else "low" if "low" in df.columns else "close"
    low20_prior, high20_prior = prior_n_high_low(df, hi_c, lo_c, 20)
    cand = {k: v for k, v in {
        "MA20": ma[20], "MA60": ma[60], "MA120": ma[120],
        "近20日高": high20_prior, "近60日高": df[hi_c].tail(60).max(),
        "近20日低": low20_prior}.items() if v is not None}

    def _px(v):
        return f"{v:,.0f}" if v >= 100 else f"{v:.1f}"

    sup = sorted([(v, k) for k, v in cand.items() if v < last], reverse=True)   # 收盤下方＝支撐（近→遠）
    res = sorted([(v, k) for k, v in cand.items() if v > last])                 # 收盤上方＝壓力（近→遠）
    buy_ref = " · ".join(f"{k} {_px(v)}" for v, k in sup[:2]) or "無明顯支撐（探底中）"
    res_ref = " · ".join(f"{k} {_px(v)}" for v, k in res[:2]) or "無明顯壓力（波段創高）"

    def _ma(v):
        return round(v, 1) if v is not None else "樣本不足"

    return light, {
        "收盤": round(last, 1), "MA20": _ma(ma[20]), "MA60": _ma(ma[60]),
        "MA120": _ma(ma[120]), "RSI14": round(r, 0),
        "量能": f"{vol_ratio:.1f}×20日均量",
        "排列": "多頭排列" if bull else "空頭排列" if bear else "均線糾結",
        "買入參考區": buy_ref,
        "壓力參考位": res_ref,
        "備註": "；".join(note) or "—",
    }


# ---------- 基本面 ----------
def fundamental(rev, val):
    r = rev.sort_values(["revenue_year", "revenue_month"]).reset_index(drop=True)
    r["ym"] = r["revenue_year"] * 100 + r["revenue_month"]
    latest = r.iloc[-1]
    # YoY：同月比去年。去年同月營收（分母）<=0 視為無效基期 → yoy 回 None，不產生 inf
    prev_year = r[(r["revenue_year"] == latest["revenue_year"] - 1) &
                  (r["revenue_month"] == latest["revenue_month"])]
    yoy = None
    yoy_base_invalid = False
    if len(prev_year):
        base = prev_year.iloc[0]["revenue"]
        if base and base > 0:
            yoy = (latest["revenue"] / base - 1) * 100
        else:
            yoy_base_invalid = True
    # 近 3 月平均 YoY（趨勢）；同樣排除基期<=0 的月份
    yoys = []
    for _, row in r.tail(3).iterrows():
        py = r[(r["revenue_year"] == row["revenue_year"] - 1) & (r["revenue_month"] == row["revenue_month"])]
        if len(py):
            py_base = py.iloc[0]["revenue"]
            if py_base and py_base > 0:
                yoys.append((row["revenue"] / py_base - 1) * 100)
    avg_yoy = sum(yoys) / len(yoys) if yoys else None

    v = val.sort_values("date").reset_index(drop=True)
    per_num = pd.to_numeric(v["PER"], errors="coerce")
    per_series = per_num[per_num > 0].dropna()  # 排除負/零 PER，避免污染分位
    per_last = per_series.iloc[-1] if len(per_series) else None
    per_pctile = (per_series < per_last).mean() if per_last is not None else None
    div_yield = v["dividend_yield"].iloc[-1] if len(v) else None

    light = "amber"
    if yoy is not None:
        if yoy > 0 and (avg_yoy or 0) > 0 and (per_pctile is None or per_pctile < 0.85):
            light = "green"
        elif yoy < 0 and (avg_yoy or 0) < 0:
            light = "red"

    return light, {
        "最新營收月": f"{int(latest['revenue_year'])}/{int(latest['revenue_month'])}",
        "營收YoY": f"{yoy:+.1f}%" if yoy is not None else ("去年同月基期無效" if yoy_base_invalid else "—"),
        "近3月平均YoY": f"{avg_yoy:+.1f}%" if avg_yoy is not None else "—",
        "PER": round(per_last, 1) if per_last is not None else "—",
        "PER歷史分位": f"{per_pctile*100:.0f}%" if per_pctile is not None else "—",
        "殖利率": f"{div_yield}%" if div_yield is not None else "—",
    }, {"revenue_yoy_base_invalid": yoy_base_invalid}


# ---------- 消息/籌碼面（籌碼部分先做；新聞情緒待 LLM 層）----------
def chips(chip):
    df = chip.copy()
    df["buy"] = pd.to_numeric(df["buy"], errors="coerce").fillna(0)
    df["sell"] = pd.to_numeric(df["sell"], errors="coerce").fillna(0)
    df["net"] = df["buy"] - df["sell"]
    daily = df.groupby("date")["net"].sum().sort_index()
    last5 = daily.tail(5)
    net5 = last5.sum()
    # 方向以「最新一天」為準，連續天數從最新日同號往回數
    buy_dir = daily.iloc[-1] > 0
    streak = 0
    for v in reversed(daily.tolist()):
        if v != 0 and (v > 0) == buy_dir:
            streak += 1
        else:
            break
    light = ("green" if buy_dir and streak >= 3 and net5 > 0
             else "red" if (not buy_dir) and streak >= 3 and net5 < 0 else "amber")
    return light, {
        "近5日法人淨額(張)": f"{net5/1000:,.0f}",
        "連續方向天數": f"{'買' if buy_dir else '賣'} {streak} 天",
        "最新日": daily.index[-1],
        "備註": "新聞情緒分類待 LLM 團隊層補上",
    }


def rev_signals_from_df(rev_df):
    """失效條件-基本面：最新月營收 YoY 轉負，且最近連 2 月低於近 6 月均。空表安全回 False。"""
    out = {"yoy_negative": False, "below_6m_2months": False}
    if rev_df is None or len(rev_df) == 0:
        return out
    r = rev_df.copy()
    r["revenue"] = pd.to_numeric(r["revenue"], errors="coerce")
    r = r.dropna(subset=["revenue"])
    r["ym"] = r["revenue_year"].astype(int) * 100 + r["revenue_month"].astype(int)
    r = r.sort_values("ym").reset_index(drop=True)
    if len(r) < 8:
        return out
    lookup = {int(row["ym"]): float(row["revenue"]) for _, row in r.iterrows()}
    last = r.iloc[-1]
    py_ym = (int(last["revenue_year"]) - 1) * 100 + int(last["revenue_month"])
    base = lookup.get(py_ym)
    if base and base != 0:
        out["yoy_negative"] = (float(last["revenue"]) / base - 1) < 0
    avg6 = r["revenue"].tail(6).mean()
    out["below_6m_2months"] = bool((r["revenue"].tail(2) < avg6).all())
    return out


def chip_signals_from_df(chip_df, vol20=None):
    """失效條件-籌碼：法人連 3 日同向賣，且賣超佔 20 日均量>15%。
    vol20＝20 日均量（股）；缺（None/0/NaN）視為資料缺，ratio 維持 False 不誤報。
    空表安全回 False。
    """
    out = {"sell_streak_ge3": False, "ratio_gt_15pct": False}
    if chip_df is None or len(chip_df) == 0:
        return out
    df = chip_df.copy()
    df["buy"] = pd.to_numeric(df["buy"], errors="coerce").fillna(0)
    df["sell"] = pd.to_numeric(df["sell"], errors="coerce").fillna(0)
    df["net"] = df["buy"] - df["sell"]
    daily = df.groupby("date")["net"].sum().sort_index()
    if len(daily) == 0:
        return out
    streak = 0
    for v in reversed(daily.tolist()):
        if v < 0:
            streak += 1
        else:
            break
    out["sell_streak_ge3"] = streak >= 3

    # 佔 20 日均量比例：僅當連賣 ≥3 天且 vol20 有效（>0）才計算，避免資料缺誤報
    if out["sell_streak_ge3"] and vol20 is not None and pd.notna(vol20) and vol20 > 0:
        last3_net_sum = daily.tail(3).sum()  # 最近 3 個交易日日淨額合計（賣超為負）
        avg_daily_sell = abs(last3_net_sum) / 3
        ratio = avg_daily_sell / vol20
        out["ratio_gt_15pct"] = ratio > 0.15
    return out


# ---------- 綜合 ----------
def synthesize(f_light, t_light, c_light):
    W = {"fund": 0.4, "tech": 0.3, "chip": 0.3}
    score = (LIGHT_SCORE[f_light]*W["fund"] + LIGHT_SCORE[t_light]*W["tech"] + LIGHT_SCORE[c_light]*W["chip"])
    lights = [f_light, t_light, c_light]
    conflict = ("green" in lights and "red" in lights)
    if conflict:
        direction, conf = "訊號分歧・建議觀望", "低"
    elif score > 0.3:
        direction, conf = "偏多", "高" if lights.count("green") == 3 else "中"
    elif score < -0.3:
        direction, conf = "偏空", "高" if lights.count("red") == 3 else "中"
    else:
        direction, conf = "中性", "中"
    return {"score": round(score, 2), "direction": direction, "confidence": conf, "conflict": conflict}


def analyze(stock_id, with_news=True):
    d = fetch(stock_id)
    name = stock_name(stock_id)
    flags = {}

    if d.get("rev") is not None and d.get("val") is not None:
        f_light, f_ev, f_flags = fundamental(d["rev"], d["val"]); flags["fundamental"] = True
        flags.update(f_flags)
    else:
        f_light, f_ev = "na", {"備註": "營收/估值資料缺"}; flags["fundamental"] = False

    if d.get("price") is not None:
        t_light, t_ev = technical(d["price"]); flags["technical"] = True
    else:
        t_light, t_ev = "na", {"備註": "日線資料缺"}; flags["technical"] = False

    if d.get("chip") is not None:
        c_light, c_ev = chips(d["chip"]); flags["chips"] = True
    else:
        c_light, c_ev = "na", {"備註": "法人資料缺"}; flags["chips"] = False

    # 籌碼 v2 分組拆解（additive；vol20 用日線近 20 日均量，單位=股）
    vol20_shares = None
    if d.get("price") is not None and "Trading_Volume" in d["price"].columns:
        _pv = pd.to_numeric(d["price"].sort_values("date")["Trading_Volume"],
                            errors="coerce").tail(20)
        if len(_pv) and pd.notna(_pv.mean()):
            vol20_shares = float(_pv.mean())
    chip_breakdown = chips_breakdown(d.get("chip"), vol20=vol20_shares)

    # 財報品質分數（additive）＋ ROE（供 valuation）
    fundamentals_quality = compute_fundamentals({
        "fs_df": d.get("fs"), "bs_df": d.get("bs"), "cf_df": d.get("cf"),
        "rev_df": d.get("rev"), "industry_category": stock_industry(stock_id),
    })

    combo = synthesize(f_light, t_light, c_light)
    news = fetch_news(name, None, 6) if with_news else []
    res = {
        "stock_id": stock_id, "name": name,
        "fundamental": {"light": f_light, "ev": f_ev},
        "technical": {"light": t_light, "ev": t_ev},
        "chips": {"light": c_light, "ev": c_ev, "breakdown": chip_breakdown},
        "news": news, "summary": combo, "data_flags": flags,
        "fundamentals_quality": fundamentals_quality,
    }
    res["decision"] = _decide(stock_id, d, res, flags)
    return res


def _decide(stock_id, d, res, flags):
    """組估值 + 決策區塊。任何一步缺資料都降級，不讓整檔 fail。"""
    try:
        from warroom.market import fetch_market
        market_light = fetch_market().get("light", "amber")
    except Exception:
        market_light = "amber"

    price_df = d.get("price")
    if price_df is None or len(price_df) == 0:
        return {"rating": "觀望", "fair_value": None, "risk_reward": None,
                "position": {"tier": "空手", "amount": 0, "odd_lot": False, "shares": 0,
                             "reason": "日線資料缺，無法計算", "core_note": ""},
                "confidence": {"total": 0, "completeness": 0, "consistency": 0,
                               "rr": 0, "regime": 0},
                "note": "日線資料缺，決策降級", "as_of_price": None,
                "disclaimer": "資料不足，僅供參考。"}

    pdf = price_df.sort_values("date").reset_index(drop=True)
    price = float(pd.to_numeric(pdf["close"], errors="coerce").iloc[-1])

    # PER/PBR 序列
    per_series, per_current, pbr_series, pbr_current = [], None, [], None
    if d.get("val") is not None:
        v = d["val"].sort_values("date")
        per_series = [float(x) for x in pd.to_numeric(v["PER"], errors="coerce").dropna().tolist()]
        pbr_series = [float(x) for x in pd.to_numeric(v["PBR"], errors="coerce").dropna().tolist()]
        per_current = per_series[-1] if per_series else None
        pbr_current = pbr_series[-1] if pbr_series else None

    valuation = compute_valuation({
        "price": price, "industry_category": stock_industry(stock_id),
        "market_light": market_light, "fs_df": d.get("fs"), "rev_df": d.get("rev"),
        "per_series": per_series, "per_current": per_current,
        "pbr_series": pbr_series, "pbr_current": pbr_current,
        "roe": res.get("fundamentals_quality", {}).get("roe_value"),
    })
    flags["eps_statement"] = (valuation.get("eps_source") == "financial_statement")

    lights = [res["fundamental"]["light"], res["technical"]["light"], res["chips"]["light"]]
    t_ev = res["technical"]["ev"]

    def _num(x):
        return float(x) if isinstance(x, (int, float)) else None

    ma20 = _num(t_ev.get("MA20"))
    hi_c = "max" if "max" in pdf.columns else "close"
    lo_c = "min" if "min" in pdf.columns else "close"
    # 前20個完整交易日（不含當日）→ 突破/停損參考不會有 lookahead、也不會在創高日永遠不成立
    low20, high20 = prior_n_high_low(pdf, hi_c, lo_c, 20)
    avg_vol20 = float(pd.to_numeric(pdf["Trading_Volume"], errors="coerce").tail(20).mean()) \
        if "Trading_Volume" in pdf.columns else None
    atr = atr14(pdf)
    atr_med = atr_percent_median(pdf)
    atr_pct = (atr / price) if (atr is not None and price) else None
    per_pctile = valuation.get("current_percentile")

    return build_decision(
        price=price, lights=lights, per_percentile=per_pctile, market_light=market_light,
        valuation=valuation, atr=atr, key_ma=ma20, low20=low20, high20=high20,
        ma20=ma20, avg_vol20=avg_vol20, atr_pct=atr_pct, atr_median_pct=atr_med,
        data_flags=flags,
        rev_signals=rev_signals_from_df(d.get("rev")),
        chip_signals=chip_signals_from_df(d.get("chip"), vol20=avg_vol20),
        profile=load_profile(), stock_id=stock_id)


def pretty(res):
    print(f"\n{'='*54}\n  個股規則式研判：{res['stock_id']}\n{'='*54}")
    for key, zh in [("fundamental", "基本面"), ("technical", "技術面"), ("chips", "消息/籌碼")]:
        block = res[key]
        print(f"\n【{zh}】{LIGHT_ZH[block['light']]}")
        for k, v in block["ev"].items():
            print(f"    {k}: {v}")
    s = res["summary"]
    print(f"\n{'-'*54}\n  綜合方向：{s['direction']}（信心 {s['confidence']}，加權分 {s['score']}）")
    print(f"{'-'*54}")


if __name__ == "__main__":
    import sys, json, os
    sid = sys.argv[1] if len(sys.argv) > 1 else "2330"
    res = analyze(sid)
    pretty(res)
    if "news" in res and res["news"]:
        print("\n【近期新聞】")
        for a in res["news"][:5]:
            print(f"    · {a['title'][:56]}")
    os.makedirs("data", exist_ok=True)
    with open(f"data/{sid}.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n→ 已寫 data/{sid}.json")
