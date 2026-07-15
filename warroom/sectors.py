"""類股層：跨市場輪動（美股領先 → 台股供應鏈）。
用 yfinance 抓美股族群 ETF 的 5 日/20 日動能排名（免費、不吃 FinMind 額度），
再對到人工維護的『美股族群 → 台股供應鏈』對應表。lead-lag 只用美股已收盤資料。
"""
import yfinance as yf
import pandas as pd
from typing import Dict, List, Optional

# 美股族群代理 ETF（動能來源）
US_GROUPS = [
    ("AI 晶片 / 半導體", "SMH"),
    ("半導體設備", "SOXX"),
    ("軟體 / 雲", "IGV"),
    ("科技大盤", "XLK"),
    ("金融", "XLF"),
    ("能源", "XLE"),
    ("國防航太", "ITA"),
]

# 美股族群 → 台股供應鏈對應表（人工維護，先建核心鏈；每項可再擴）
MAPPING = {
    "AI 晶片 / 半導體": {"tw": "台積電 · 先進封裝(世芯/日月光) · 散熱(奇鋐) · PCB/ABF(欣興)",
                        "us_names": "NVDA · AVGO · AMD"},
    "半導體設備": {"tw": "設備廠(家登/辛耘) · 台積電資本支出受惠鏈", "us_names": "AMAT · LRCX · KLAC"},
    "軟體 / 雲": {"tw": "台股直接對應少，觀察雲端伺服器代工", "us_names": "MSFT · CRM · ORCL"},
    "科技大盤": {"tw": "電子權值整體", "us_names": "AAPL · MSFT"},
    "金融": {"tw": "台股金控", "us_names": "JPM · BAC"},
    "能源": {"tw": "台股對應少", "us_names": "XOM · CVX"},
    "國防航太": {"tw": "軍工(漢翔/雷虎)", "us_names": "LMT · RTX"},
}


def _mom(ticker):
    h = yf.Ticker(ticker).history(period="1mo")
    c = h["Close"]
    m5 = (c.iloc[-1] / c.iloc[-6] - 1) * 100 if len(c) >= 6 else None
    m20 = (c.iloc[-1] / c.iloc[0] - 1) * 100 if len(c) > 1 else None
    return round(m5, 2) if m5 is not None else None, round(m20, 2) if m20 is not None else None


def fetch_sectors():
    rows = []
    for name, etf in US_GROUPS:
        try:
            m5, m20 = _mom(etf)
            rows.append({"group": name, "etf": etf, "m5": m5, "m20": m20,
                         "tw": MAPPING[name]["tw"], "us_names": MAPPING[name]["us_names"]})
        except Exception as e:
            rows.append({"group": name, "etf": etf, "m5": None, "m20": None,
                         "tw": MAPPING[name]["tw"], "us_names": MAPPING[name]["us_names"], "err": str(e)[:40]})
    # 依 5 日動能排名
    ranked = sorted([r for r in rows if r["m5"] is not None], key=lambda r: r["m5"], reverse=True)
    for i, r in enumerate(ranked):
        r["rank"] = i + 1
        r["tier"] = "lead" if r["m5"] > 1 else "lag" if r["m5"] < -1 else "mid"
    return ranked


# ==================== 台股類股量化輪動（Task C）====================
# 族群 → 台股代表個股（人工維護；沿用 US→TW 對應概念的 TW 側，先建核心鏈）。

from warroom.finmind_cache import cached_fetch

TW_GROUPS = {
    "AI/半導體": ["2330", "2454", "3661"],       # 台積電/聯發科/世芯
    "封裝測試": ["3711", "6239"],                # 日月光投控/力成
    "散熱": ["3017", "3324"],                    # 奇鋐/雙鴻
    "PCB/載板": ["3037", "6269"],                # 欣興/台郡
    "金融": ["2882", "2891", "2886"],            # 國泰金/中信金/兆豐金
    "軍工航太": ["2634", "8033"],                # 漢翔/雷虎
    "半導體設備": ["3680", "3131"],              # 家登/弘塑
}


def _ret(closes, lookback: int) -> Optional[float]:
    """近 lookback 交易日報酬（%）：需 lookback+1 筆。"""
    if closes is None or len(closes) < lookback + 1:
        return None
    return round((float(closes.iloc[-1]) / float(closes.iloc[-1 - lookback]) - 1) * 100, 4)


def stock_momentum(price_df) -> Dict:
    """單檔日線 → 5/20/60 日動能（%）＋近 5 日/近 60 日均量（股）。不足筆數該項 None。"""
    out = {"r5": None, "r20": None, "r60": None, "vol5": None, "vol60": None}
    if price_df is None or len(price_df) == 0 or "close" not in price_df.columns:
        return out
    df = price_df.reset_index(drop=True)
    c = pd.to_numeric(df["close"], errors="coerce").dropna()
    out["r5"], out["r20"], out["r60"] = _ret(c, 5), _ret(c, 20), _ret(c, 60)
    if "Trading_Volume" in df.columns:
        v = pd.to_numeric(df["Trading_Volume"], errors="coerce").dropna()
        if len(v) >= 5:
            out["vol5"] = round(float(v.tail(5).mean()), 1)
        if len(v) >= 60:
            out["vol60"] = round(float(v.tail(60).mean()), 1)
    return out


def _avg(vals: List[Optional[float]]) -> Optional[float]:
    xs = [v for v in vals if v is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def tw_group_metrics(group_name: str, stock_dfs: List, twii_df) -> Dict:
    """族群等權彙整（見計畫 §介面契約 3，不含 rank/tier）。
    score = 0.4×m5 + 0.35×m20 + 0.25×m60 + rs 加成（相對加權指數）。"""
    moms = [stock_momentum(df) for df in stock_dfs]
    m5 = _avg([m["r5"] for m in moms])
    m20 = _avg([m["r20"] for m in moms])
    m60 = _avg([m["r60"] for m in moms])
    vol5 = _avg([m["vol5"] for m in moms])
    vol60 = _avg([m["vol60"] for m in moms])
    vol_expansion = round(vol5 / vol60, 2) if (vol5 and vol60 and vol60 > 0) else None

    rs = None
    if twii_df is not None and m20 is not None:
        twii_m20 = _ret(pd.to_numeric(twii_df.sort_values("date")["close"],
                                      errors="coerce").dropna(), 20)
        if twii_m20 is not None:
            rs = round(m20 - twii_m20, 2)

    score = None
    if any(v is not None for v in (m5, m20, m60)):
        score = round(0.4 * (m5 or 0) + 0.35 * (m20 or 0) + 0.25 * (m60 or 0)
                      + 0.3 * (rs or 0), 2)

    return {"group": group_name, "stock_ids": [], "m5": m5, "m20": m20, "m60": m60,
            "vol_expansion": vol_expansion, "rs_vs_twii": rs, "score": score}


def fetch_tw_sectors() -> List[Dict]:
    """抓 TW_GROUPS 各檔日線 + 加權指數，回排名後的台股類股輪動清單。"""
    try:
        twii = cached_fetch("taiwan_stock_daily", stock_id="TAIEX", start_date="2026-01-01")
    except Exception:
        twii = None
    rows = []
    for name, ids in TW_GROUPS.items():
        dfs = []
        for sid in ids:
            try:
                df = cached_fetch("taiwan_stock_daily", stock_id=sid, start_date="2026-01-01")
                if df is not None and len(df) > 0:
                    dfs.append(df)
            except Exception:
                continue
        g = tw_group_metrics(name, dfs, twii)
        g["stock_ids"] = ids
        rows.append(g)
    ranked = sorted([r for r in rows if r["score"] is not None],
                    key=lambda r: r["score"], reverse=True)
    for i, r in enumerate(ranked):
        r["rank"] = i + 1
        r["tier"] = "lead" if r["score"] > 3 else "lag" if r["score"] < -3 else "mid"
    # score 缺者附在後面（rank/tier 標記為缺）
    for r in rows:
        if r["score"] is None:
            r["rank"], r["tier"] = None, "na"
            ranked.append(r)
    return ranked


if __name__ == "__main__":
    for r in fetch_sectors():
        print(f"  #{r['rank']} [{r['tier']}] {r['group']} ({r['etf']}): 5日 {r['m5']}% / 20日 {r['m20']}%  → {r['tw']}")
