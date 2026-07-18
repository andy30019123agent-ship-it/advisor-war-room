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
from warroom.primary_decision import build_primary_and_context, apply_derivations
from warroom.chips_v2 import chips_breakdown
from warroom.fundamentals import compute_fundamentals
from warroom.events import (build_ex_div_map, has_upcoming_event,
                            event_risk_downgrade, build_event_calendar)
from datetime import datetime, timezone, timedelta
import email.utils as _eut
import json as _json
import os as _os

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


def stock_exists(stock_id):
    """代號是否存在於 FinMind 全市場清單。回 True/False；查不了（額度用完／網路問題）
    回 None——呼叫方不該把「查不了」當成「不存在」，那是兩件事（見 api/analyze.py 用法）。"""
    global _INFO_CACHE
    try:
        if _INFO_CACHE is None:
            _INFO_CACHE = get_loader().taiwan_stock_info()
        return bool((_INFO_CACHE["stock_id"] == stock_id).any())
    except Exception:
        return None


class FinMindUnavailable(Exception):
    """FinMind 全域不可用（額度用完/429/402 等）往上冒泡的訊號——跟一般單一 dataset
    抓不到（缺資料，標 None 走既有降級）分開。api/analyze.py 接到這個會回 503
    「FinMind 額度用完，請稍後再試」；批次排程（warroom/update.py 的 analyze() 呼叫）
    本來就用 try/except Exception 包整支，會照舊 warn＋跳過該檔，不影響其餘股票。"""


def _is_finmind_unavailable(exc: Exception) -> bool:
    """辨識「全域不可用」型錯誤：serverless lite loader 丟的 FinMindRateLimited
    （HTTP 402/429/連線失敗，見 api/_lib/finmind_lite.py；用類別名字串比對，不 import
    api 套件，維持 warroom 不依賴 api 的分層），以及正式 FinMind SDK 丟的通用 Exception
    （'Final response status: 402/429...' 或訊息含 limit/login 等額度字樣）。
    只有這裡認得出的訊號才冒泡，其餘（單一 dataset 沒資料、格式錯誤等）仍走原本的
    單一維度降級（out[key]=None），不影響批次排程既有行為。"""
    if type(exc).__name__ == "FinMindRateLimited":
        return True
    msg = str(exc).lower()
    if any(s in msg for s in ("status: 402", "status: 429", "http 402", "http 429")):
        return True
    return any(kw in msg for kw in ("rate limit", "login", "額度", "quota"))


# ---------- 抓資料 ----------
def fetch(stock_id):
    """抓個股所需各資料源。任一源失敗回 None（該維度後續標「資料缺」）；
    但辨識出「FinMind 全域不可用」（額度用完/429/402）時改丟 FinMindUnavailable
    往上冒泡，不再默默吞成 None——不然查詢額度用完時，即時查詢會靜默降級成一筆
    看起來正常的「資料缺、觀望」，使用者跟系統都以為是正常結果（2026-07-18 聯測 #2）。"""
    out = {}
    sources = [
        ("price", "taiwan_stock_daily", dict(stock_id=stock_id, start_date="2024-01-01")),
        ("rev", "taiwan_stock_month_revenue", dict(stock_id=stock_id, start_date="2023-01-01")),
        ("val", "taiwan_stock_per_pbr", dict(stock_id=stock_id, start_date="2021-01-01")),
        ("chip", "taiwan_stock_institutional_investors", dict(stock_id=stock_id, start_date="2026-04-01")),
        ("div", "taiwan_stock_dividend", dict(stock_id=stock_id, start_date="2025-01-01")),
        ("fs", "taiwan_stock_financial_statement", dict(stock_id=stock_id, start_date="2024-01-01")),
        ("bs", "taiwan_stock_balance_sheet", dict(stock_id=stock_id, start_date="2024-01-01")),
        ("cf", "taiwan_stock_cash_flows_statement", dict(stock_id=stock_id, start_date="2024-01-01")),
    ]
    for key, method, kw in sources:
        try:
            df = cached_fetch(method, **kw)
            out[key] = df if (df is not None and len(df) > 0) else None
        except Exception as e:
            if _is_finmind_unavailable(e):
                raise FinMindUnavailable(str(e)) from e
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

    # 落一筆戰績牆建議（規格 §3.3）。P1 fix #4：搬進 analyze() 尾端，讓 update.py 的批次
    # 入口（直接呼叫 analyze()，不經 __main__）也會落 log；缺資料/寫檔失敗降級不 crash。
    try:
        from warroom.track_record import log_recommendation
        _today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        # 建議日＝行情資料日（price_at_rec 是那天的收盤），週末補跑才不會標成無交易的日期
        log_recommendation(res, res.get("as_of_date") or _today)
    except Exception:
        pass
    return res


def _facts_list(ev):
    """把某燈的證據 dict 濃縮成幾條事實字串（供 context.lights / 角色觀點）。"""
    out = []
    for k, v in (ev or {}).items():
        if k in ("備註", "排列", "買入參考區", "壓力參考位") or v in (None, "—", ""):
            continue
        out.append(f"{k} {v}")
    return out[:4]


def _parse_news_date(raw):
    """news.py 兩個來源日期格式不同：GDELT seendate＝YYYYMMDDTHHMMSSZ；
    Google RSS pubDate＝RFC822（Thu, 16 Jul 2026 04:00:00 GMT）。統一轉 ISO；解析不出給 None
    （契約規則：缺資料給 null，不得編字串、不得讓整檔 build 失敗）。"""
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
    except (ValueError, TypeError):
        pass
    try:
        dt = _eut.parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except (ValueError, TypeError, IndexError, OverflowError):
        return None


def _normalize_news(items):
    """news.py 回傳 {title,url,date,src} → 契約 evidence.news 的 {title,source,url,published_at}
    （規格：evidence.news 欄位正規化）。只動 evidence 輸出，legacy res["news"]（report_stock.py
    等舊渲染仍讀 src/date）維持原格式不變。"""
    out = []
    for a in (items or []):
        out.append({
            "title": a.get("title") or "",
            "source": a.get("src") or a.get("source") or None,
            "url": a.get("url") or None,
            "published_at": _parse_news_date(a.get("date") or a.get("published_at")),
        })
    return out


def _attach_primary(res, dec, valuation, price, market_light, rev_sig, chip_sig,
                    defense_price, high20):
    """建 primary_decision + context + evidence，並把 legacy summary/rating/timeframes
    改為由 primary 派生（規格 §3.1，杜絕結論打架）。缺資料時安全降級不 crash。"""
    stock_id = res["stock_id"]
    profile = load_profile()
    lights = [res["fundamental"]["light"], res["technical"]["light"], res["chips"]["light"]]
    lights_facts = {
        "fundamental": _facts_list(res["fundamental"]["ev"]),
        "technical": _facts_list(res["technical"]["ev"]),
        "chips": _facts_list(res["chips"]["ev"]),
    }
    fundamental_broken = bool(rev_sig.get("yoy_negative") and rev_sig.get("below_6m_2months"))
    chips_broken = bool(chip_sig.get("sell_streak_ge3") and chip_sig.get("ratio_gt_15pct"))
    defense_broken = "已觸發" in (dec.get("invalidation", {}) or {}).get("price", "")
    is_core = stock_id in profile.get("core_holdings", [])
    reeval = (datetime.now(timezone(timedelta(hours=8))) + timedelta(days=7)).strftime("%Y-%m-%d")
    entry_cond = ({"price": round(high20, 1), "condition": "帶量突破近20日高、法人回補"}
                  if high20 is not None else None)

    primary, context, roles = build_primary_and_context(
        price=price or 0, lights=lights, lights_facts=lights_facts, valuation=valuation,
        rr=dec.get("risk_reward"), defense_price=defense_price,
        defense_broken=defense_broken, fundamental_broken=fundamental_broken,
        chips_broken=chips_broken, market_light=market_light,
        confidence=(dec.get("confidence") or {}).get("total", 0), profile=profile,
        is_core_holding=is_core, reeval_date=reeval, entry_condition=entry_cond)

    res["primary_decision"] = primary
    res["context"] = context
    res["evidence"] = {"roles": roles, "news": _normalize_news(res.get("news", [])), "events": []}
    res["decision"] = dec
    apply_derivations(res, primary, context)


def _decide(stock_id, d, res, flags):
    """組估值 + 決策區塊。任何一步缺資料都降級，不讓整檔 fail。"""
    try:
        from warroom.market import fetch_market
        market_light = fetch_market().get("light", "amber")
    except Exception:
        market_light = "amber"

    price_df = d.get("price")
    if price_df is None or len(price_df) == 0:
        dec = {"rating": "觀望", "fair_value": None, "risk_reward": None,
               "position": {"tier": "空手", "amount": 0, "odd_lot": False, "shares": 0,
                            "reason": "日線資料缺，無法計算", "core_note": ""},
               "confidence": {"total": 0, "completeness": 0, "consistency": 0,
                              "rr": 0, "regime": 0},
               "invalidation": {}, "stop": {"price": None},
               "note": "日線資料缺，決策降級", "as_of_price": None,
               "disclaimer": "資料不足，僅供參考。"}
        _attach_primary(res, dec, None, None, market_light,
                        {"yoy_negative": False, "below_6m_2months": False},
                        {"sell_streak_ge3": False, "ratio_gt_15pct": False}, None, None)
        return dec

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

    ex_div_map = build_ex_div_map(d.get("div"))
    latest_date = str(pdf["date"].iloc[-1])
    res["as_of_date"] = latest_date[:10]   # 行情資料日（最後一根日 K 的日期），戰績 log 與 API meta 用
    ex_today = latest_date in ex_div_map
    ex_amt = float(ex_div_map.get(latest_date, 0.0))
    atr = atr14(pdf, ex_div_map=ex_div_map)
    atr_med = atr_percent_median(pdf)
    atr_pct = (atr / price) if (atr is not None and price) else None
    per_pctile = valuation.get("current_percentile")

    rev_sig = rev_signals_from_df(d.get("rev"))
    chip_sig = chip_signals_from_df(d.get("chip"), vol20=avg_vol20)
    dec = build_decision(
        price=price, lights=lights, per_percentile=per_pctile, market_light=market_light,
        valuation=valuation, atr=atr, key_ma=ma20, low20=low20, high20=high20,
        ma20=ma20, avg_vol20=avg_vol20, atr_pct=atr_pct, atr_median_pct=atr_med,
        data_flags=flags, rev_signals=rev_sig, chip_signals=chip_sig,
        profile=load_profile(), stock_id=stock_id,
        ex_dividend_today=ex_today, ex_div_amt=ex_amt)

    # 事件前高估值＋籌碼弱 → 自動降級（規格 §3.3）。has_ev 先預設 False：下方 try 若在
    # has_upcoming_event 算出來前就例外，短線劇本推演（見尾端 short_scenarios 掛載）仍要
    # 讀得到這個變數，不能讓它因為這裡的 try/except 吞例外而變成未定義。
    has_ev = False
    try:
        earnings_json = None
        ep = "../tw-earnings-calendar/data/latest.json"
        if _os.path.exists(ep):
            earnings_json = _json.load(open(ep, encoding="utf-8"))
        today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        has_ev = has_upcoming_event(stock_id, d.get("div"), earnings_json,
                                     {stock_id: res["name"]}, today, 14)
        new_rating, ev_note = event_risk_downgrade(
            dec["rating"], has_ev, per_pctile, res["chips"]["light"])
        if ev_note:
            dec["rating"] = new_rating
            dec["event_downgrade"] = ev_note   # additive：渲染可顯示降級理由
    except Exception:
        pass

    # 主結論引擎（§3.1~3.5）：產 primary_decision + context + evidence，並把 legacy 欄位改為派生
    _attach_primary(res, dec, valuation, price, market_light, rev_sig, chip_sig,
                    dec["stop"]["price"], high20)

    # 機率扇形圖預估走勢（規格 v1.2/v1.3）：樣本不足/算不出時 build_forecast 內部已回
    # None，這裡再包一層 try 是防禦性的（例如 pdf 欄位格式異常），失敗一律 None，不讓
    # 整檔 build 失敗。放在 _attach_primary 之後，才能把 res["evidence"]["events"]
    # 一併餵給 event_markers（見 warroom/forecast.py build_forecast 的 events 參數）。
    try:
        from warroom.forecast import build_forecast
        evidence_events = (res.get("evidence") or {}).get("events")
        res["forecast"] = build_forecast(pdf, valuation, res["as_of_date"], stock_id,
                                         events=evidence_events)
    except Exception:
        res["forecast"] = None

    # 短線劇本推演（規格 v1.4）：defense_price/action 一律讀 primary_decision（唯一結論
    # 源，剛由上面 _attach_primary 寫入，不重算）；MA/近20日高低沿用本函式已算好的
    # low20/high20/ma20/t_ev；籌碼連買賣天數借用 chips_v2 分組拆解裡「外資」這組已算好
    # 的 streak/dir（法人籌碼指標一般以外資為主要觀察對象）。市場閘門（大盤偏多/空傾向、
    # 新倉閘門）在 analyze 階段還沒有 build_snapshots 才算得出的真 exposure_guidance，
    # 用 market_light 當代理，門檻精神對齊 build_exposure_guidance（綠→可正常布局／
    # 黃→僅限試單／紅→禁止新增部位），build_snapshots 端只需透傳，不再另算一次
    # （見該檔 build_stock_detail 的 short_scenarios 透傳）。任何例外都降級成 None，不
    # 讓整檔 build 失敗。
    try:
        from warroom.short_scenarios import build_short_scenarios
        _SC_COLOR = {"green": "green", "amber": "yellow", "red": "red"}
        primary = res["primary_decision"]
        foreign = ((res.get("chips") or {}).get("breakdown") or {}).get("groups", {}).get("外資", {})
        f_streak = foreign.get("streak", 0) or 0
        f_dir = foreign.get("dir", "平")
        chips_streak_signed = f_streak if f_dir == "買" else (-f_streak if f_dir == "賣" else 0)
        market_bias = ("bull" if market_light == "green"
                       else "bear" if market_light == "red" else "neutral")
        market_new_position_proxy = ("可正常布局" if market_light == "green"
                                     else "禁止新增部位" if market_light == "red"
                                     else "僅限試單")
        res["short_scenarios"] = build_short_scenarios(
            current_price=price,
            defense_price=primary.get("defense_price"),
            low20=low20, high20=high20,
            ma20=ma20, ma60=_num(t_ev.get("MA60")), ma120=_num(t_ev.get("MA120")),
            entry_anchor=(primary.get("entry_condition") or {}).get("price"),
            technical_color=_SC_COLOR.get(res["technical"]["light"]),
            chips_color=_SC_COLOR.get(res["chips"]["light"]),
            fundamental_color=_SC_COLOR.get(res["fundamental"]["light"]),
            chips_streak=chips_streak_signed,
            market_bias=market_bias,
            market_new_position=market_new_position_proxy,
            is_bearish_arrangement=(t_ev.get("排列") == "空頭排列"),
            event_within_14d=bool(has_ev),
            primary_action=primary.get("action"),
            primary_position_delta=primary.get("position_delta", "hold"),
        )
    except Exception:
        res["short_scenarios"] = None
    return dec


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

    try:
        from warroom.finmind_cache import cached_fetch as _cf
        ep = "../tw-earnings-calendar/data/latest.json"
        ej = _json.load(open(ep, encoding="utf-8")) if _os.path.exists(ep) else None
        try:
            _div = _cf("taiwan_stock_dividend", stock_id=sid, start_date="2025-01-01")
        except Exception:
            _div = None
        today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        # 單檔版事件日曆：本股除息 + 本股月營收 + 全域法說/FOMC/CPI（週報可另做全市場版）
        cal = build_event_calendar(ej, {sid: (res["name"], _div)}, {sid: res["name"]}, today, 14)
        with open("data/events.json", "w", encoding="utf-8") as f:
            _json.dump(cal, f, ensure_ascii=False, indent=2)
        print("→ 已寫 data/events.json")
    except Exception as _e:
        print(f"（events.json 落檔略過：{_e}）")

    # P1 fix #4：recommendation_log 落檔已搬進 analyze() 尾端統一處理（見上方 analyze()
    # 呼叫時已落過一筆），這裡不再重複落，避免兩個入口各落一次。
    print("→ recommendation_log 已於 analyze() 內落檔（見上方）")
