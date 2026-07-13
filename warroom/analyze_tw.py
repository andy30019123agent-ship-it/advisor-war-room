"""Phase 1a — 台股個股「規則式紅綠燈」引擎（無 LLM，純數據＋固定規則）。
每個維度回傳 (燈號, 證據)：燈號 = green/amber/red，證據 = 說得出依據的數字。
投顧紀律：燈由規則算、門檻寫死、缺資料降級；LLM 之後只負責解讀與反駁，不改燈。
"""
from FinMind.data import DataLoader
import pandas as pd
from warroom.news import fetch_news

LIGHT_SCORE = {"green": 1, "amber": 0, "red": -1}
LIGHT_ZH = {"green": "🟢偏多", "amber": "🟡中性", "red": "🔴偏空", "na": "⚪資料缺"}

_INFO_CACHE = None


def stock_name(stock_id):
    """台股中文名（FinMind 個股資訊，快取一次）。"""
    global _INFO_CACHE
    try:
        if _INFO_CACHE is None:
            _INFO_CACHE = DataLoader().taiwan_stock_info()
        row = _INFO_CACHE[_INFO_CACHE["stock_id"] == stock_id]
        return row.iloc[0]["stock_name"] if len(row) else stock_id
    except Exception:
        return stock_id


# ---------- 抓資料 ----------
def fetch(stock_id):
    dl = DataLoader()
    return {
        "price": dl.taiwan_stock_daily(stock_id=stock_id, start_date="2025-01-01"),
        "rev": dl.taiwan_stock_month_revenue(stock_id=stock_id, start_date="2023-01-01"),
        "val": dl.taiwan_stock_per_pbr(stock_id=stock_id, start_date="2024-01-01"),
        "chip": dl.taiwan_stock_institutional_investors(stock_id=stock_id, start_date="2026-04-01"),
    }


# ---------- 技術面 ----------
def rsi(series, n=14):
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-9)
    out = 100 - 100 / (1 + rs)
    out[(gain == 0) & (loss == 0)] = 50  # 完全平盤 → 中性，避免被誤判超賣
    return out


def technical(price):
    df = price.sort_values("date").reset_index(drop=True)
    c = df["close"]
    ma = {n: c.rolling(n).mean().iloc[-1] for n in (5, 20, 60, 120)}
    last = c.iloc[-1]
    r = rsi(c).iloc[-1]
    vol = df["Trading_Volume"]
    vol_ratio = vol.iloc[-1] / vol.tail(20).mean()

    bull = last > ma[20] > ma[60] > ma[120]
    bear = last < ma[20] and ma[20] < ma[60]
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

    return light, {
        "收盤": round(last, 1), "MA20": round(ma[20], 1), "MA60": round(ma[60], 1),
        "MA120": round(ma[120], 1), "RSI14": round(r, 0),
        "量能": f"{vol_ratio:.1f}×20日均量",
        "排列": "多頭排列" if bull else "空頭排列" if bear else "均線糾結",
        "備註": "；".join(note) or "—",
    }


# ---------- 基本面 ----------
def fundamental(rev, val):
    r = rev.sort_values(["revenue_year", "revenue_month"]).reset_index(drop=True)
    r["ym"] = r["revenue_year"] * 100 + r["revenue_month"]
    latest = r.iloc[-1]
    # YoY：同月比去年
    prev_year = r[(r["revenue_year"] == latest["revenue_year"] - 1) &
                  (r["revenue_month"] == latest["revenue_month"])]
    yoy = None
    if len(prev_year):
        yoy = (latest["revenue"] / prev_year.iloc[0]["revenue"] - 1) * 100
    # 近 3 月平均 YoY（趨勢）
    yoys = []
    for _, row in r.tail(3).iterrows():
        py = r[(r["revenue_year"] == row["revenue_year"] - 1) & (r["revenue_month"] == row["revenue_month"])]
        if len(py):
            yoys.append((row["revenue"] / py.iloc[0]["revenue"] - 1) * 100)
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
        "營收YoY": f"{yoy:+.1f}%" if yoy is not None else "—",
        "近3月平均YoY": f"{avg_yoy:+.1f}%" if avg_yoy is not None else "—",
        "PER": round(per_last, 1) if per_last is not None else "—",
        "PER歷史分位": f"{per_pctile*100:.0f}%" if per_pctile is not None else "—",
        "殖利率": f"{div_yield}%" if div_yield is not None else "—",
    }


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
    f_light, f_ev = fundamental(d["rev"], d["val"])
    t_light, t_ev = technical(d["price"])
    c_light, c_ev = chips(d["chip"])
    combo = synthesize(f_light, t_light, c_light)
    news = fetch_news(name, None, 6) if with_news else []
    return {
        "stock_id": stock_id,
        "name": name,
        "fundamental": {"light": f_light, "ev": f_ev},
        "technical": {"light": t_light, "ev": t_ev},
        "chips": {"light": c_light, "ev": c_ev},
        "news": news,
        "summary": combo,
    }


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
