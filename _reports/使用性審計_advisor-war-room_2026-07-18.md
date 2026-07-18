# 投顧戰情室（advisor-war-room）使用性審計

日期：2026-07-18｜審計人：fresh-context 產品審計 agent｜方法：唯讀分析（不改程式）

背景：07-15 剛完成 2.0（決策引擎＋渲染層，155 測試綠），但 Andy 回饋「目前能用的地方真的不多」「請重新設計邏輯」。本審計目的：找出「功能都做了、卻覺得不能用」的根因。

---

## a. 內容新鮮度

**結論：網站目前呈現的是 07-15 盤後的資料，到今天 07-18 為止三天沒有任何更新，且沒有任何自動化機制會讓它自己更新。**

證據：
- `git log --format="%ad %s" --date=short` 全部 30 筆提交日期都是 `2026-07-15`，07-16～07-18 沒有任何 commit。
- `reports/weekly.html`、`reports/2330.html` 檔案 mtime 都是 07-15 15:07/15:08（`ls -la reports/`）。
- `crontab -l` 無任何 war-room 相關排程；專案內找不到 `.github/workflows/`、任何 `*.yml`（`find . -iname "*.yml"` 無結果、`.github` 目錄不存在）。
- `warroom/update.py` 第 6 行 docstring 明講流程：「跑完這支 → **Claude** 讀下方 DIGEST 寫 `data/weekly_narration.json` 的團隊觀點 → `python -m warroom.build_weekly`」——更新鏈中段是人工／LLM 介入步驟，非可排程腳本。
- `warroom/report_stock.py` 第 392 行 `_load(f"data/{stock_id}.narration.json")`：沒有這份手寫檔就沒辦法出報告（見 c、e 節細節）。

Andy 平常（沒有 Claude 在場）打開網站，看到的必然是上次 Claude 在場時產出的舊資料，且無從得知資料已經過期多久——報告內雖標「as_of」日期，但入口頁 `index.html` 本身沒有任何「上次更新」或「資料新鮮度」提示。

## b. 覆蓋範圍

**結論：引擎其實跑過 6 檔，但實際「能看」的個股報告只有 1 檔（2330），週報也只帶到 2 檔（2330、2454）的評論；查其他股票在網站上完全沒有入口。**

證據：
- `data/` 目錄下有 6 檔個股引擎輸出：`2330.json 2454.json 2882.json 2892.json 3661.json 8299.json`（`ls -la data/`）。
- 但 `data/*.narration.json` 只有 `2330.narration.json` 一份——其餘 5 檔沒有人工／Claude 寫過團隊觀點，因此永遠無法通過 `report_stock.py` 的 narration 讀取步驟。
- `reports/` 目錄下實際存在的個股 HTML 只有 `2330.html` 一份（`ls -la reports/`），其餘 5 檔即使有引擎數據也從未產出報告頁。
- `data/weekly_narration.json` 的 `"stocks"` 欄位只有 `["2330", "2454"]` 兩把 key（`python3 -c "..."` 讀出），代表週報裡也只評論了 2 檔。
- `index.html` 第 36-37 行硬編正好 2 張卡片：`reports/weekly.html`、`reports/2330.html`——沒有任何「個股清單」或「查詢」入口。

Andy 想查一檔沒涵蓋的股票（例如手上其他持股）時，網站上什麼都做不到：沒有搜尋框、沒有股票清單頁、也沒有「請求分析」的按鈕，唯一辦法是回頭找 Claude 在終端機跑 CLI。

## c. 更新流程摩擦

**結論：出一期新報告需要至少 4 個步驟，其中「幫每檔股票手寫 6 角色投顧觀點」與「發布」兩步驟必須由 Claude／人工完成，Andy 自己一人（沒有 Claude 在場）無法完成整條鏈。**

證據（`README.md` 第 19-37 行「操作：更新戰情室怎麼跑」）：
1. `python -m warroom.update`（可自動化，純 Python，抓資料＋跑引擎＋印摘要）。
2. **「Claude 讀上面摘要 → 更新 `data/weekly_narration.json` 的團隊觀點（6 角色/大盤/類股/主題）」**——README 原文即標示這是 Claude 的步驟，非程式化流程；`report_stock.py` 個股版同樣要求 Claude 寫 `data/<id>.narration.json`（README 第 35 行：「Claude 寫 `data/2330.narration.json`（6 角色，依真數字）」）。
3. `build_weekly.py` / `report_stock.py` 組報告——但這一步內建 `warroom/consistency.py` 的 `assert_consistent()`：narration 裡的數字跟引擎 JSON 差 >1%、或敘事日期早於引擎最新資料日，就會 `sys.exit(1)` 直接讓 build 失敗（`consistency.py` docstring：「禁止舊敘事上線」）。這代表手寫敘事若有任何疏漏，整條發布鏈會卡住，需要人工排錯。
4. README 第 29 行：「截圖(500 寬)驗證 → publish Artifact → 發 Andy」——發布動作本身依賴 Claude 的 Artifact 工具，不是純腳本。

Andy 一個人（沒有 Claude 在場）能做的只有步驟 1（抓資料印摘要），完全卡在步驟 2（沒人幫他寫投顧觀點文字，也沒人幫他過一致性檢查跟發布）。這是「三天沒更新」（a 節）背後的直接機制原因。

## d. 互動能力

**結論：網站是純靜態閱讀頁，零查詢／零輸入能力，跟「AI 投顧團隊、隨時問」的定位落差很大。**

證據：
- `grep -o "<script" reports/weekly.html | wc -l` → **0**；`grep -o "<input\|<form\|fetch(" reports/weekly.html` → 無結果。`reports/2330.html` 同樣沒有連回入口的內部連結（見 f 節）。
- 頁面唯一的「互動」是 CSS 原生 `<details>/<summary>` 折疊區塊（`render_common.py` 第 29 行 CSS：`details{...}summary{...}`），沒有任何 JS、沒有 API、沒有表單。
- `README.md` 第 11 行定位：「一支 6 角色 AI 投顧團隊……AI（Claude）只負責解讀與反駁」——語感上暗示「團隊隨時可問」，但落地產物是兩頁固定時間點的靜態 HTML，Andy 沒辦法在網站上輸入股票代號、問問題、或要求重新評估，任何互動都得繞回終端機找 Claude。

## e. 決策引擎輸出的可行動性

**結論：決策引擎本身輸出的欄位其實相當完整、可執行（這部分設計是對的），但因為 b/c 節的瓶頸，這個「聰明的大腦」只服務得到 1-2 檔股票，且「戰績牆」承諾的歷史命中率目前完全是空的。**

證據：
- `data/recommendation_log.json` 顯示引擎確實會輸出：`rating`（買進/試單/續抱/觀望/減碼）、`fair_base`（合理價）、`stop`（停損參考價）、`rr`（風報比）、`confidence`（信心分數）、`factors`（三燈+PER 分位）——例如 2330 那筆：`rating: 減碼, fair_base: 1736.5, stop: 2244.8, rr: -3.6, confidence: 30`。
- `data/investor_profile.json` 確認部位金額是具體新台幣金額分級（0／10萬／20萬／40萬／60萬）並標零股，對照 Andy 的實際下單動作是可行動的。
- 但**「戰績牆」功能（`track_record.py`，spec 第 3.3 節承諾的「報告顯示歷史命中率」）自 07-15 上線後從未實際跑過回填**：`data/recommendation_log.json` 裡全部 4 筆紀錄的 `outcome.r5/r20/r60/hit` 欄位都是 `null`（見檔案內容），因為沒有排程去跑 5/20/60 天回填（同 a 節「無自動化」根因）。
- 決策引擎的「可行動性」設計本身沒問題，問題是覆蓋率（b）與更新頻率（a/c）把它的價值鎖在極小範圍——Andy 手上如果有非 2330/2454 的持股，這套「該買哪檔、買多少、何時出場」的機制對他完全不可見。

## f. 資訊架構

**結論：入口頁本身乾淨，但只有「單向、去無回」的兩條路：從 index 進去 weekly 或 2330 報告後，兩份報告內部完全沒有連回首頁、也沒有互相連結，Andy 在手機上點進報告後無路可退、也看不到「還有其他報告」的線索。**

證據：
- `index.html`：`<title>` + 兩張卡片（`reports/weekly.html`、`reports/2330.html`）+ 免責聲明，共 41 行，資訊量精簡（第 32-39 行）。
- `grep -o 'href="[^"]*"' reports/weekly.html`：所有內部連結都是頁內錨點（`#i-chart` `#i-check` `#i-chevron`），**沒有任何連回 `index.html` 的連結**。
- `grep -o 'href="[^"]*"' reports/2330.html`：內部連結同樣只是頁內錨點（`#entry #frames #team` 等），外部連結全部指向 Google News RSS 文章，**沒有連回 index.html、也沒有連到 weekly.html**。
- 結果：Andy 用手機打開週報或個股報告後，唯一離開頁面的方式是瀏覽器「上一頁」或手動改網址；如果是別人轉傳報告連結給他（跳過 index），他甚至不知道還有首頁跟其他報告存在。

---

## 根因排序（按對「覺得不能用」的影響力，高到低）

1. **無自動更新機制、更新鏈中段綁死「必須有 Claude 手寫 narration」**——`update.py` 明文要求 Claude 讀摘要手寫 6 角色觀點，`report_stock.py` 沒有 narration.json 就無法產出報告，且沒有 cron／GitHub Actions／任何排程（`crontab -l` 空、找不到 `.github/workflows`）。這是最上游的根因：Andy 沒有主動來找 Claude，網站就永遠停在上次的日期（目前卡在 07-15，已 3 天沒動）。
2. **覆蓋率被手寫瓶頸鎖死在 1-2 檔，Andy 想查的股票十之八九不在裡面**——引擎跑了 6 檔（`data/*.json`），但手寫 narration 只完成 2330 一檔，週報也只帶 2330+2454，`index.html` 硬編死 2 張卡片、無清單無搜尋，其餘持股在網站上完全查不到。
3. **產品定位（隨時可問的 AI 投顧團隊）跟落地形態（零 JS 零輸入的靜態雙頁 HTML）之間有本質落差**——`reports/weekly.html` 掃描不到任何 `<script>`／`<input>`／`<form>`／`fetch(`，Andy 沒辦法在網站上做任何主動查詢，只能等 Claude 在場時手動觸發一輪新報告。
4. **導覽動線斷頭，靜態頁彼此不連通**——`index.html`、`weekly.html`、`2330.html` 三份文件之間沒有雙向連結，週報和個股報告只有頁內錨點跟外部新聞連結，Andy 手機點進報告後找不到路回首頁或看其他股票。
5. **（下游症狀）戰績牆從未實跑，決策引擎的「歷史命中率」目前是空集合**——`recommendation_log.json` 4 筆紀錄 `outcome` 全 `null`，這不是獨立問題，是根因 1（無排程）在「Phase 4 戰績牆」功能上的直接體現，但值得點名，因為它讓「精心設計的決策引擎」實際能展示的證據力目前是零。
