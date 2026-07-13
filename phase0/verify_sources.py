"""Phase 0 — 資料源技術驗證
逐一實際打每個資料源，印出 PASS/FAIL＋樣本＋新鮮度。不寫架構，只證明水管通不通。
"""
import json, sys, urllib.request, traceback
from datetime import datetime, timezone, timedelta

TPE = timezone(timedelta(hours=8))
def now_tpe(): return datetime.now(TPE).strftime("%Y-%m-%d %H:%M")

results = []
def rec(name, ok, detail):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

def get_json(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "advisor-war-room/phase0 (research; contact andy)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

# 1) TWSE 官方 OpenAPI — 台股日成交（零依賴）
try:
    d = get_json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL")
    tsmc = next((x for x in d if x.get("Code") == "2330"), None)
    rec("TWSE 台股日成交", bool(tsmc),
        f"{len(d)} 檔；台積電2330 收盤 {tsmc['ClosingPrice'] if tsmc else '?'}（資料日 {tsmc['Date'] if tsmc else '?'} 民國年）")
except Exception as e:
    rec("TWSE 台股日成交", False, f"{type(e).__name__}: {e}")

# 2) TWSE 三大法人買賣超（籌碼面）
try:
    d = get_json("https://openapi.twse.com.tw/v1/fund/T86")
    rec("TWSE 三大法人T86", isinstance(d, list) and len(d) > 0,
        f"{len(d)} 筆；欄位樣本 {list(d[0].keys())[:4] if d else '無'}")
except Exception as e:
    rec("TWSE 三大法人T86", False, f"{type(e).__name__}: {e}")

# 3) FinMind — 台股月營收（基本面）
try:
    from FinMind.data import DataLoader
    dl = DataLoader()
    df = dl.taiwan_stock_month_revenue(stock_id="2330", start_date="2025-01-01")
    ok = df is not None and len(df) > 0
    last = df.iloc[-1].to_dict() if ok else {}
    rec("FinMind 月營收", ok,
        f"{len(df)} 筆；最新 {last.get('revenue_month','?')}/{last.get('revenue_year','?')} 營收 {last.get('revenue','?')}")
except Exception as e:
    rec("FinMind 月營收", False, f"{type(e).__name__}: {str(e)[:120]}")

# 4) FinMind — 台股 K 線（技術面）
try:
    from FinMind.data import DataLoader
    dl = DataLoader()
    df = dl.taiwan_stock_daily(stock_id="2330", start_date="2026-06-01")
    ok = df is not None and len(df) > 0
    rec("FinMind 台股K線", ok,
        f"{len(df)} 根；最新 {df.iloc[-1]['date'] if ok else '?'} 收 {df.iloc[-1]['close'] if ok else '?'}")
except Exception as e:
    rec("FinMind 台股K線", False, f"{type(e).__name__}: {str(e)[:120]}")

# 5) yfinance — 美股價量
try:
    import yfinance as yf
    h = yf.Ticker("AVGO").history(period="5d")
    ok = h is not None and len(h) > 0
    rec("yfinance 美股價量", ok,
        f"AVGO {len(h)} 根；最新收 {round(float(h['Close'].iloc[-1]),2) if ok else '?'}")
except Exception as e:
    rec("yfinance 美股價量", False, f"{type(e).__name__}: {str(e)[:120]}")

# 6) SEC EDGAR — 美股官方財報 (companyconcept, NVDA CIK 1045810)
try:
    d = get_json("https://data.sec.gov/api/xbrl/companyconcept/CIK0001045810/us-gaap/Revenues.json")
    units = d.get("units", {}).get("USD", [])
    rec("SEC EDGAR 財報", len(units) > 0,
        f"NVDA Revenues {len(units)} 期；最新 {units[-1].get('end','?')} = {units[-1].get('val','?')}" if units else "無 USD 單位")
except Exception as e:
    rec("SEC EDGAR 財報", False, f"{type(e).__name__}: {str(e)[:120]}")

# 7) GDELT — 新聞（消息面/主題）
try:
    d = get_json("https://api.gdeltproject.org/api/v2/doc/doc?query=TSMC&mode=artlist&maxrecords=5&format=json&sort=datedesc")
    arts = d.get("articles", [])
    rec("GDELT 新聞", len(arts) > 0,
        f"TSMC {len(arts)} 篇；最新「{arts[0].get('title','?')[:40]}」" if arts else "無文章")
except Exception as e:
    rec("GDELT 新聞", False, f"{type(e).__name__}: {str(e)[:120]}")

print("\n" + "="*60)
p = sum(1 for _, ok, _ in results if ok)
print(f"Phase 0 資料驗證 @ {now_tpe()} (台北)：{p}/{len(results)} 通過")
for name, ok, _ in results:
    print(f"  {'✅' if ok else '❌'} {name}")
