# Phase 1 資料集驗證結果（FinMind）

> 執行 2026-07-15 09:30–09:32（台北）
> 腳本：`phase0/test_p1data.py`（主測，16 次呼叫）＋ 3 次補測（type 欄位詳查）＋ 1 次法人類別詳查
> **總呼叫數：20 次**（預算 40 次內），全程無 token（免費未註冊模式），呼叫間 sleep 1 秒，**零錯誤、零 402/429**。
> 環境：`./.venv/bin/python`（3.9.6）+ FinMind 2.0.4 + pandas 2.0.4。

## 結論總覽
地基可蓋樓，但財報系列（1/2/3）都是「長格式」，實作前必讀下面的欄位語意，否則會踩雷（尤其金融股 schema 不同、`_per` 重複列、多個相似 type 名）。

---

## 1. TaiwanStockFinancialStatements（綜合損益表）
- **可得性**：✅ 三檔（2330／2882／8299）都成功。
- **呼叫方式**：`dl.taiwan_stock_financial_statement(stock_id=..., start_date="2024-01-01")`
- **資料格式**：**長格式**（每列一個科目），欄位＝`date, stock_id, type, value, origin_name`。要拿 EPS/營收/毛利/營業利益必須先 `pivot(index='date', columns='type', values='value')`。
- **關鍵科目確認可用**（2330 實測 type 清單節錄）：
  - `Revenue`＝營業收入 ✅
  - `GrossProfit`＝營業毛利（毛損） ✅
  - `OperatingIncome`＝營業利益（損失） ✅
  - `EPS`＝基本每股盈餘 ✅（只有這一種 EPS，沒看到稀釋 EPS 的獨立 type）
  - `CostOfGoodsSold`＝營業成本、`OperatingExpenses`＝營業費用、`PreTaxIncome`＝稅前淨利、`IncomeAfterTaxes`＝本期淨利
- **樣本**（2330 最新一列）：`{'date': '2026-03-31', 'type': 'IncomeFromContinuingOperations', 'value': 572801304000.0}`
- **最新資料日期**：2026-03-31（即 2026 Q1，7/15 當下最新可得季報，符合台股財報公告時程）
- **雷點（重要）**：
  1. **金融股 schema 完全不同**：2882（國泰金）的 type 集合出現 `NetChangeInProvisionsForInsuranceLiabilities`（保險負債準備淨變動）等保險業專屬科目，2330 沒有這些欄位。**不能假設所有股票的財報欄位一致**，寫程式時要用 `type` 名稱去抓值、抓不到要能容錯（NaN），不要假設固定欄位順序/數量（2330＝153 筆、2882＝151 筆、8299＝153 筆，筆數不同）。
  2. 長格式需要 pivot，且同一 `type` 在不同季度都有一列，要先篩 `date` 最新一筆再 pivot，否則會拿到歷史堆疊。

## 2. TaiwanStockBalanceSheet（資產負債表）
- **可得性**：✅ 2330、8299 都成功。
- **呼叫方式**：`dl.taiwan_stock_balance_sheet(stock_id=..., start_date="2024-01-01")`
- **關鍵科目確認可用**：`TotalAssets`＝資產總額 ✅、`Liabilities`＝負債總額 ✅、`Equity`＝權益總額 ✅、`TotalLiabilitiesEquity`＝負債及權益總計 ✅
- **最新資料日期**：2026-03-31
- **雷點**：
  1. **每個科目都有兩個 type**：原始值＋`_per`（佔總資產百分比，如 `TotalAssets_per`）。抓資料時要精準比對 type 字串，不能用 `str.contains` 模糊比對，否則會混進百分比欄位。
  2. 2330 有 909 筆、8299 有 791 筆（科目數不同，8299 少約 118 個科目）——同樣是「不同公司科目集合不同」的雷，跟 #1 一致。

## 3. TaiwanStockCashFlowsStatement（現金流量表）
- **可得性**：✅ 2330、2882 都成功。
- **呼叫方式**：`dl.taiwan_stock_cash_flows_statement(stock_id=..., start_date="2024-01-01")`
- **關鍵科目**：`CashFlowsFromOperatingActivities`＝營業活動之淨現金流入（流出）✅、`CashProvidedByInvestingActivities`＝投資活動之淨現金流入（流出）✅
- **最新資料日期**：2026-03-31
- **雷點**：**同一概念出現兩個相似 type**——`CashFlowsFromOperatingActivities` 和 `NetCashInflowFromOperatingActivities` 都跟營業現金流有關，容易選錯欄位；寫程式前要用 `origin_name` 中文名再核對一次語意，不要只憑英文 type 名猜。

## 4. TaiwanStockInstitutionalInvestorsBuySell（三大法人買賣超）
- **可得性**：✅ 三檔（2330／2882／8299）都成功，近 14 天各 45 筆。
- **呼叫方式**：`dl.taiwan_stock_institutional_investors(stock_id=..., start_date=...)`
- **欄位**：`date, stock_id, buy, sell, name`（**沒有** Foreign_Investor/Investment_Trust/Dealer 分欄，是用 `name` 欄位分列，要自己 pivot 成寬表）
- **法人類別（5 種，2330 實測確認）**：`Foreign_Investor`（外資）、`Foreign_Dealer_Self`（外資自營）、`Investment_Trust`（投信）、`Dealer_self`（自營商自行）、`Dealer_Hedging`（自營商避險）
- **單位**：**股**（不是張、不是元）——驗證依據：2330 近 10 交易日 Foreign_Investor 買超總量 1.56 億股，除以約 10 個交易日約每日 1500 萬股，與台積電日均量級相符，若是「張」單位會是 1560 億股顯然不合理，若是「元」單位也對不上收盤價量級。
- **最新資料日期**：2026-07-14
- **雷點**：`dtype` 是 `int64`（買超/賣超都是整數股數），無小數；三檔資料筆數一致（都 45 筆＝14 天窗口內的交易日數×5 類別），覆蓋度沒問題。

## 5. TaiwanStockPER（本益比/淨值比/殖利率）
- **可得性**：✅ 2330（2021-01-01 至今）、8299（近期）都成功。
- **呼叫方式**：`dl.taiwan_stock_per_pbr(stock_id=..., start_date=...)`（注意：FinMind 的 Python method 名稱是 `taiwan_stock_per_pbr`，不是 `taiwan_stock_per`）
- **欄位**：`date, stock_id, dividend_yield, PER, PBR` ✅ 三者齊全
- **速度**：2330 抓 2021-01-01 至今（**1341 筆，約 5.5 年**）僅耗時 **1.09 秒**，不會卡、也沒被擋——抓 3–5 年歷史沒有速度或額度疑慮。
- **最新資料日期**：2026-07-14
- **雷點**：無明顯雷，資料乾淨。

## 6. TaiwanStockInfo（股票基本資料／產業別）
- **可得性**：✅ 一次呼叫拿全市場（4277 筆，含個股與部分指數列）。
- **欄位**：`industry_category, stock_id, stock_name, type, date`
- **驗證結果**：
  - 2330＝`半導體業`（type=twse）
  - 2882＝`金融保險`（type=twse）
  - 8299＝`半導體業`（type=tpex，上櫃）
- **雷點**：
  1. **2330 出現兩筆重複資料**，`industry_category` 分別是「半導體業」和「電子工業」——同一支股票在這個資料集裡不保證唯一，寫程式判斷金融/景氣循環股時要先 `drop_duplicates` 或取第一筆，否則邏輯可能被第二筆覆蓋出錯。
  2. 全市場清單也混入指數列（如 `TradingConsumersGoods` 貿易百貨類指數，`date='None'` 字串而非空值），過濾時要小心 `stock_id` 是否為真實 4 碼股票代號。
  3. 上櫃（8299）欄位跟上市（2330/2882）格式一致，沒有缺漏，可放心用同一套邏輯處理上市櫃。

## 7. TaiwanStockDividend ／ TaiwanStockDividendResult（除權息）
- **可得性**：✅ 2330 兩個資料集都成功（各 10 筆，2024-01-01 至今）。
- **`taiwan_stock_dividend`（公告面）欄位較完整**：含 `AnnouncementDate`（董事會宣布日）、`CashExDividendTradingDate`（除息交易日）、`CashDividendPaymentDate`（發放日）、`CashEarningsDistribution`（每股配息）等。
- **`taiwan_stock_dividend_result`（除權息結果）欄位**：`before_price, after_price, stock_and_cache_dividend, stock_or_cache_dividend, max_price/min_price/open_price/reference_price`——這是除權息當天的**已發生**結果，不是預告。
- **最新資料**：2330 最新一筆 `AnnouncementDate=2026-05-27`（宣布）、`CashExDividendTradingDate=2026-06-11`（除息，已過）、`CashDividendPaymentDate=2026-07-09`（發放，已過，測試當下 7/15 已完成）。
- **雷點（待驗證，本次測試無法百分百確認）**：本次測試窗口內 2330 最新一筆除息日已經過去（6/11），**沒有測到「已公告但尚未除息」的未來事件**，因為 2330 是季配息、下一次公告時間點還沒到。無法從這次測試 100% 確認「未來除息日」是否會提前出現在 `taiwan_stock_dividend`（理論上應該會——公告面資料集本來就是拿 AnnouncementDate 之後、除息前就能查到——但需要抓一支最近剛公告、還沒除息的股票才能實測驗證）。**這點列入待決策/待補測，不確定就不硬說有。**

## 8. TaiwanStockMonthRevenue（月營收）
- **可得性**：✅ 2330（18 筆，2025-01-01 至今）。
- **欄位**：`date, stock_id, country, revenue, revenue_month, revenue_year, create_time`
- **`date` 欄位語意（本次要查證的重點）**：**`date` 不是公告日，而是「營收所屬月份的次月 1 號」**。實測樣本：`revenue_month=6, revenue_year=2026` 對應 `date='2026-07-01'`（6 月營收，用 7/1 當索引日）。
- **`create_time`**：FinMind 自己爬取/寫入資料庫的時間戳，較接近真實公告時間但**不是官方公告日**本身（且舊資料的 `create_time` 可能是空字串，第一筆 2025-01 營收的 `create_time` 就是 `''`）。
- **雷點**：**做事件日曆／公告時程判斷時不能直接拿 `date` 欄位當公告日**——它只是「這筆營收屬於哪個月」的索引日，跟台股慣例（次月 10 日前公告）對不上，必須另外用官方公告時程規則（次月 10 日）或搭配 `create_time` 交叉驗證，不能只信 `date`。

---

## 額度與錯誤格式（文件查證 + 實測）
- **未註冊免費額度**：**300 次／小時**（來源：社群/文件二手查證，非 finmind.github.io 原文明載數字，見下方查證紀錄）
- **註冊免費 token 額度**：**600 次／小時**（2 倍）——申請方式：至 https://finmindtrade.com/analysis/#/account/user 登入註冊＋驗證信箱，登入後在使用者資訊頁面取得 API token，之後用 `DataLoader().login_by_token(token)` 或 HTTP header `Authorization: Bearer {token}` 帶入。
  - **查證方式**：WebFetch `https://finmind.github.io/login/`（申請流程原文確認）＋ WebSearch 綜合多來源（含 FinMind 官方 Facebook 社群貼文與 quickstart 頁），查證日期 2026-07-15。300/600 這組具體數字**沒有在 finmind.github.io 的頁面原文中直接抓到明載文字**，是 WebSearch 綜合多筆二手來源給出的一致結果（含官方社群貼文），**建議視為「高可信度但非一手文件截圖」，正式上限度前若要 100% 篤定建議 Andy 自己登入 https://finmind.github.io/api_usage_count/ 或 https://finmindtrade.com/analysis/#/account/user 的使用者頁面核對數字**。
- **402 超額錯誤（文件實查，本次測試未觸發）**：來源 https://finmind.github.io/api_usage_count/ ——超過額度時回傳 HTTP **402**，訊息文字為 `"Requests reach the upper limit."`（**文件值，本次 20 次呼叫未實測到**，因為遠低於 300/hr 門檻）。
- **429**：**查了 finmind.github.io 的 api_usage_count／login 頁面，沒找到 429 相關說明**——FinMind 額度超限走的是 402 不是 429，本次也沒實測到 429。這點不是「查不到就編」，是「確認 FinMind 用 402 當額度錯誤碼，429 在其文件裡沒出現」。

---

## 待決策（需要 Andy 決定，不自行假設）
1. **是否要申請免費 FinMind token**：本次 20 次呼叫全部零錯誤、免 token 也順暢，但主專案「今天稍後還要跑更新」＋未來 Phase 1 若要批次跑多檔（例如全market 掃描）會逼近 300/hr 上限。要不要現在去 https://finmindtrade.com/analysis/#/account/user 註冊拿 token（免費、只需驗證信箱），把上限從 300 提到 600？
2. **除權息「未來事件」是否可靠**：本次測試因 2330 剛好處在「已除息、下次未公告」的空窗期，沒能實測「已公告但未除息」的資料是否會提前出現在 `taiwan_stock_dividend`。若「法人分拆＋事件日曆」功能真的需要未來除權息日，建議之後找一支近期剛公告下一次配息、還沒除息的股票（例如金融股常見）補測一次，再往下蓋這塊功能。
