# 投顧戰情室 App 版重建 — 設計 spec（2026-07-18）

## 0. 背景與目標

07-15 上線的 2.0（靜態 HTML 報告）被 Andy 驗收打槍：「目前能用的地方真的不多」「操作上 UI/UX 也很差」，並要求重新設計邏輯。三路獨立診斷（設計審計＋使用性審計＋Codex，報告在 `_reports/*_2026-07-18.md`）結論一致，四大病根：

1. **報告是死的**：更新鏈綁死「Claude 在場手寫 narration」＋零排程，07-15 後三天沒更新。
2. **建議是鎖住的**：同頁結論打架（2330 同時「觀望／減碼／中性」）；部位規則一刀切全變「空手」；估值過悲觀（2330 Base 1,736 vs 市價 2,440）。
3. **網站是孤島**：三頁零互連、45% 文字 <16px、零互動能力，與「隨時問的投顧團隊」定位落差巨大。
4. **沒有戰績**：recommendation_log 4 筆 outcome 全 null，信任迴路未閉合。

**成功標準**：Andy 不需要 Claude 在場，任何一天打開 App 都看到當日資料；輸入任一台股代號幾秒得到完整分析；每份分析只有一個主結論＋人話理由；防守價跌破自動收到 Telegram；戰績頁看得到過去建議的追蹤進度。

## 1. Andy 已拍板的決策（2026-07-18，Discord）

| 決策 | 選擇 |
|---|---|
| 產品形態 | 路線 3：互動 App（PWA），砍掉靜態報告站形態 |
| 到價提醒 | Telegram 通知（現有 bot） |
| 持股/成本儲存 | 手機 localStorage，免登入 |
| 查股即時性 | 即時現查（serverless API） |
| 視覺方向 | C「iOS 原生感・清透」（權威＝`design-system/advisor-war-room/MASTER.md`，含 Andy 核准章） |
| 部位級距（沿用 07-15 拍板，Codex 建議的 2-5 萬級距不採用） | 0／10 萬／20 萬（標準）／40 萬／60 萬（高信心） |
| 核心持股 | 台積電＋0050 定期定額為核心，建議須註明不影響核心部位 |

## 2. 架構（Codex 提案＋Claude 統籌修正後定案）

```
┌─ 每日排程（GitHub Actions，盤後）
│    跑 warroom Python 引擎 → 產 public/data/*.json → commit push → Vercel 自動部署
├─ 即時查詢（Vercel Python serverless）
│    /api/analyze?stock=XXXX → cache-first → miss 才打 FinMind → 回 JSON
├─ 到價提醒（GitHub Actions，盤中每 15 分）
│    讀最新 snapshot 的防守價/觸發價 → 比對即時價 → 命中發 Telegram
└─ 前端（React + TS + Vite + PWA，Vercel 託管）
     四主畫面：今日／持股／查股票／戰績；TanStack Query 拉資料；持股存 localStorage
```

- **Python 引擎保留不改寫 TS**（155 測試是資產）；角色從「產 HTML」改為「產 JSON contract」。
- 資料契約：`public/data/daily.json`（今日戰術台）、`public/data/stocks/{id}.json`（單股）、`public/data/market.json`；`schema/*.json` 定義結構，Python 端跑 schema 測試，前端 Zod 驗證——防契約漂移。
- **FinMind 額度保護**：token 只在 server env；排程優先、cache-first、TTL（價格 5-15 分／籌碼盤後／營收財報每日）、quota ledger 記當日呼叫數，接近上限只回快照並標示資料時間，不偷偷冒充即時。
- **提醒 v1 範圍**：只監控引擎追蹤清單（daily snapshot 內個股）的防守價/觸發價；使用者自訂到價提醒因 localStorage 無法同步 server，列 v2（需輕量同步機制時再議）。
- 舊 `reports/*.html` 靜態站保留唯讀存檔，入口 index.html 改導向新 App。

## 3. 決策引擎重設計（本案核心，修「結論打架＋全空手＋估值悲觀」）

### 3.1 單一主結論 `primary_decision`
- 欄位：`action`（加碼/續抱/試單/觀望/減碼/出場）、`stance`（偏多~偏空五檔）、`position_delta`、`reason_codes[]`（結構化）、`readable_reason`（一句人話）。
- **summary、rating、時間框架文案全部從 primary_decision 派生，禁止各自重算**；CI 加一致性測試抓矛盾。
- 短線/波段/中期可不同調，但只作背景解釋，主卡永遠只顯示一個操作結論。

### 3.2 六層優先序（由上而下，先命中先決定）
1. 資料品質：資料不足 → 只能觀望/續抱，不得建議買進。
2. 硬風控：跌破防守位、基本面失效、籌碼失效 → 減碼/出場優先。
3. 持股狀態：空手給「試單/觀望」、有持股給「續抱/減碼/加碼」——杜絕「觀望但又減碼」。
4. R/R：<1.5 不新增；1.5–2 最多試單；>2 標準部位；>3 才可加碼。
5. 三燈與大盤：只影響信心與理由，不覆蓋 1–4。
6. 估值：過熱限制加碼、不強迫清倉；便宜也不無視風控。

### 3.3 估值校準
- regime 分組（近 3 年／近 5 年／完整週期分開算 PER 分位），高 ROE/毛利/成長的品質股 Base multiple 上修半檔到一檔。
- sanity check：Base 與現價差 >25–35% → 輸出 `valuation_warning`（模型可能低估 regime），不得直接餵進減碼結論。
- 對外文案改區間語言：便宜／合理／偏貴／很貴。

### 3.4 部位分層
- 核心持股（2330、0050 定期定額）：只因基本面長期失效才動，其他訊號一律標註「不影響核心部位」。
- 波段部位：照六層優先序＋Andy 級距（0/10/20/40/60 萬）。
- 理由模板：「因為 A，所以 B；但 C 是風險」。

### 3.5 Narration 去人工化
角色觀點改為引擎決定式生成（依 reason_codes 套人話模板），格式改「支持／反對／要驗證」三欄位，不再依賴 Claude 手寫 narration.json。Claude 僅在人工出刊時可選擇性潤稿，非必經步驟。

## 4. 前端資訊架構（四 tab）

1. **今日**：新鮮度徽章＋搜尋列（唯一主 CTA）＋今日總結卡（市場狀態/風險溫度/一句話結論）＋我的持股卡＋觀察清單（可行動/等條件分組）。3 秒內回答「今天該做什麼」。
2. **持股**：localStorage 持股與成本管理（新增/編輯）；每檔顯示 primary_decision＋防守價＋損益。
3. **查股票**：輸入代號 → 呼叫 /api/analyze → 完整單股分析（主結論卡置頂，證據收 tabs：三燈/估值/籌碼/新聞/角色觀點）。
4. **戰績**：所有歷史建議含 pending 狀態、5/20/60 日追蹤進度，不等結案才顯示。

視覺一律照 MASTER.md 方向 C token；錯誤/離線態：顯示最近快照＋資料時間，絕不留白屏。

## 5. 測試與驗收

- 引擎：既有 155 測試保持綠；新增 primary_decision 一致性測試、schema 測試、六層優先序單元測試。
- 前端：build 通過＋三尺寸（375/768/1280）實測不跑版。
- 交付前三層驗收：機器審（web-design-guidelines＋Lighthouse）→ fresh-context 對抗審 → Andy 手機實測點頭才算完成。

## 6. 分工（Andy 指定 Claude×Codex 合作）

- **Codex**：decision_engine 重構、估值校準、JSON contract 化、schema、測試補強（workspace-write、明令禁動字體/build script 的既有雷條款）。
- **Claude（主對話＋subagents）**：架構統籌、spec/PRD、前端 UI 實作與視覺、人話文案模板、每次 Codex 產出的審查、與 Andy 溝通。
- 工作流：Claude 鎖 spec → Codex 做引擎層 → Claude 驗收＋做前端 → 交叉 review → 部署。

## 7. 里程碑

1. M1 引擎重設計＋JSON contract（含測試）
2. M2 App 骨架＋今日/持股兩 tab（讀 snapshot）
3. M3 每日排程＋查股票 tab（即時 API）
4. M4 Telegram 提醒＋戰績 tab
5. M5 部署＋三層驗收＋交付 Andy

每個里程碑完成即回報 Discord；M2 起提供可玩連結。

## 8. 明確不做（v1）

多用戶/登入/雲端同步、使用者自訂到價提醒、美股個股引擎（仍是下一波優先，但不混進本案）、盤中即時全清單刷新（首頁只讀每日 snapshot）。

## 9. Backlog（Codex 07-18 審查提出、判定不擋 v1）

1. 引擎 layer 3 的持股狀態只認核心持股；使用者 localStorage 實際持股應能覆寫（前端對已持有的非核心股把「試單/觀望」語意換成持有視角，或 API 帶持股參數）。
2. 舊靜態報告 report_stock.py 仍強制讀手寫 narration.json；若要保留舊站活著，應 fallback 用 primary_decision.readable_reason＋evidence.roles 自動生成（目前舊站定位＝唯讀存檔，故延後）。
