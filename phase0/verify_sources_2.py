"""Phase 0 補測：修兩個失敗項＋確認替代來源。"""
import json, time, urllib.request

def get_raw(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "advisor-war-room/phase0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()

# A) FinMind 三大法人（籌碼面主來源，替代 TWSE T86）
try:
    from FinMind.data import DataLoader
    dl = DataLoader()
    df = dl.taiwan_stock_institutional_investors(stock_id="2330", start_date="2026-06-20")
    ok = df is not None and len(df) > 0
    print(f"[{'PASS' if ok else 'FAIL'}] FinMind 三大法人: {len(df)} 筆；最新 {df.iloc[-1]['date'] if ok else '?'} 樣本欄位 {list(df.columns)[:5]}")
except Exception as e:
    print(f"[FAIL] FinMind 三大法人: {type(e).__name__}: {str(e)[:120]}")

# B) 診斷 TWSE T86（三大法人）到底回什麼
try:
    st, body = get_raw("https://openapi.twse.com.tw/v1/fund/T86")
    head = body[:160].decode("utf-8", "replace")
    print(f"[DIAG] TWSE T86: HTTP {st}, len={len(body)}, 前160字元: {head!r}")
except Exception as e:
    print(f"[DIAG] TWSE T86: {type(e).__name__}: {str(e)[:120]}")

# C) GDELT 加退避重試
gdelt_ok = False
for attempt in range(1, 4):
    try:
        st, body = get_raw("https://api.gdeltproject.org/api/v2/doc/doc?query=semiconductor&mode=artlist&maxrecords=5&format=json&sort=datedesc")
        d = json.loads(body)
        arts = d.get("articles", [])
        gdelt_ok = len(arts) > 0
        print(f"[{'PASS' if gdelt_ok else 'FAIL'}] GDELT（第{attempt}試）: {len(arts)} 篇；最新「{arts[0].get('title','?')[:40] if arts else '無'}」")
        break
    except Exception as e:
        print(f"  GDELT 第{attempt}試失敗: {type(e).__name__} {str(e)[:60]}；退避 {attempt*3}s")
        time.sleep(attempt * 3)

# D) Google News RSS（新聞備援，穩定免限流）
try:
    st, body = get_raw("https://news.google.com/rss/search?q=台積電&hl=zh-TW&gl=TW&ceid=TW:zh-TW")
    txt = body.decode("utf-8", "replace")
    n = txt.count("<item>")
    import re
    first = re.search(r"<item>.*?<title>(.*?)</title>", txt, re.S)
    print(f"[{'PASS' if n>0 else 'FAIL'}] Google News RSS: {n} 則；最新「{(first.group(1)[:44] if first else '?')}」")
except Exception as e:
    print(f"[FAIL] Google News RSS: {type(e).__name__}: {str(e)[:120]}")
