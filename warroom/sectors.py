"""類股層：跨市場輪動（美股領先 → 台股供應鏈）。
用 yfinance 抓美股族群 ETF 的 5 日/20 日動能排名（免費、不吃 FinMind 額度），
再對到人工維護的『美股族群 → 台股供應鏈』對應表。lead-lag 只用美股已收盤資料。
"""
import yfinance as yf

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
    m5 = (c.iloc[-1] / c.iloc[-6] - 1) * 100 if len(c) > 6 else None
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


if __name__ == "__main__":
    for r in fetch_sectors():
        print(f"  #{r['rank']} [{r['tier']}] {r['group']} ({r['etf']}): 5日 {r['m5']}% / 20日 {r['m20']}%  → {r['tw']}")
