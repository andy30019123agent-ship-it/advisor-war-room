# Phase 0 · 資料源技術驗證結果

> 執行 2026-07-13 17:55（台北）· `./.venv/bin/python phase0/verify_sources.py`（+ `_2.py` 補測）
> 結論：**需要的每個維度都有免費、實測可用的來源，地基穩，可進 Phase 1。**

## 環境
- Python 3.9.6（系統版，無 brew/新版）；venv 在 `.venv/`。
- 已裝：requests、pandas、yfinance、FinMind（3.9 相容 OK）。
- LibreSSL 的 urllib3 warning 無害。

## 各來源實測（抓到今日真實資料）
| 維度 | 來源 | 狀態 | 實測樣本 |
|---|---|---|---|
| 台股股價 | TWSE OpenAPI `STOCK_DAY_ALL`（零依賴 urllib） | ✅ | 台積電2330 收 2415（民國115/07/09）；1369 檔 |
| 台股股價/K線 | FinMind `taiwan_stock_daily` | ✅ | 2330 最新 2026-07-13 收 2440 |
| 台股基本面 | FinMind `taiwan_stock_month_revenue` | ✅ | 2330 最新 6/2026 營收 442,679,969,000 |
| 台股籌碼 | FinMind `taiwan_stock_institutional_investors` | ✅ | 2330 最新 2026-07-13；欄位 date/buy/sell/name |
| 美股股價 | yfinance `Ticker.history` | ✅ | AVGO 最新收 399.97 |
| 美股官方財報 | SEC EDGAR `companyconcept`（需 User-Agent） | ✅ | NVDA Revenues 276 期，最新 2026-04-26 = 81.6B |
| 新聞/主題 | GDELT `doc` API | ✅（偶 429） | semiconductor 5 篇；需退避重試 |

## 踩到的雷與對策（都不擋路）
1. **TWSE OpenAPI `/v1/fund/T86`（三大法人）已掛**：回 HTML 錯誤頁非 JSON → 台股籌碼一律走 **FinMind 三大法人**（已驗證）。
2. **GDELT 會 429 限流**：首跑 429、重試就過 → fetcher 要內建退避重試；備援 **Google News RSS**（記得 `urllib.parse.quote` 中文 query，否則 UnicodeEncodeError）。
3. **FinMind 免費版有用量上限**（超量 402、亂打恐 IP 暫封，見 Codex 查證）：一週兩次量不大應夠；要更保險去申請免費 token 提額（待 Andy 決定）。
4. **Python 3.9 偏舊**：目前全 OK；若日後套件需 3.10+ 再請 Andy 裝新版。

## 資料源定案（給 Phase 1 用）
- 台股：**FinMind 為主**（價/量/月營收/財報/籌碼）＋ **TWSE OpenAPI 交叉驗證價格**。
- 美股：**yfinance**（價量）＋ **SEC EDGAR**（官方財報）。
- 新聞/主題：**GDELT**（退避重試）＋ **Google News RSS**（備援）。
- 總經（Phase 3 再接）：FRED（需免費 API key）。
