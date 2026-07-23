# 帳本制持倉 ＋ 個人化操作建議（設計）

> 2026-07-23．Andy 拍板：做法 1（帳本制）＋ 真的記現金
> 前置討論：Claude 診斷 → Codex 交叉分析（兩輪）→ Claude 審核採納
> 影響範圍：**純前端**（`app/`）。引擎 JSON 契約不變，只在資料契約補「App 行為」一節。

## 1. 問題

Andy 原話：「連動感有點糟，例如我新增購入股數卻沒跑到我的持股中；應該要我填入後持續幫我彙整目前持倉，並給我操作建議，這個操作建議應該要按照目前價位與水位去調整；目前用起來像是有功能但建議不夠精確也不夠客製化。」

根因是兩件事，不是一件：

### 1.1 兩套資料各自為政

`advisor-war-room:holdings`（手填持股）與 `advisor-war-room:journal`（交易日誌）是兩個互不相通的 localStorage key。`JournalEntryFormModal` 存檔後只 `setJournal`，從不碰 holdings。

實測會發生（逐條對照程式碼確認）：

| 現象 | 位置 |
|---|---|
| 記買單持股不增、記賣單不減、賣光了卡片還在 | `Holdings.tsx:455-462` onSaved 只更新 journal |
| 加碼不算加權平均成本 | `holdings.ts:28` `saveHolding()` 同代號整筆覆寫 |
| 「編輯股數」語意是「改成總共幾股」而非「這次買幾股」 | `Holdings.tsx:557` `handleSharesInput` |
| 同一檔兩套成本並存（未實現用手填 `costPrice`、已實現用 FIFO） | `Holdings.tsx:162` vs `journal.ts:122` |
| 先手動建持股、再記賣單 → 賣單成孤兒，不算損益也不進連敗判定 | `journal.ts:94` `computeFifoMatches()` 只認 journal 買單 |
| 曝險/現金水位只跟 holdings 走，日誌買賣不影響 | `Holdings.tsx:203` |
| 現金水位是 `100 - 曝險` 的推估，不是真現金 | `Holdings.tsx:216` |
| localStorage 無跨頁反應性（只在 mount 讀一次） | `Holdings.tsx:38,45` |

### 1.2 建議沒有「你」

每檔顯示的 `primary_decision.advice.holder.action_text` 與 `plan` 是引擎給「一般持有者」的通用文案，不看使用者的成本價、未實現損益、單檔佔比、總曝險、現金水位。附帶兩個更嚴重的：

- **風控算對了卻沒接到輸出端**：`getStreakAlert()` 已正確算出「3 連敗 → 暫停新倉」，但只餵給 `StreakAlertBanner` 顯示，下方卡片照樣顯示加碼建議 → 同一畫面可同時出現「暫停新倉」與「加碼 10 萬」。`max_equity_pct`、`min_cash_pct`、`new_position` 同樣只產生警告，不影響每檔建議。
- **盤中價變了建議不重算**：`currentPrice` 會用即時報價更新市值損益，但 `actionText`/`plan`/`defensePrice` 仍直接來自快照。

引擎其實已提供足夠的結構化欄位可運算（皆已核對存在於 `app/src/types/contract.ts`）：`position.tier_amount:359`、`position_delta:352`、`entry_condition.price:364`、`defense_price`、`exposure_guidance.max_equity_pct/min_cash_pct/new_position:168-169`。**運算一律只讀這些結構化欄位，禁止解析 `plan.trigger/act` 的中文字串。**

## 2. 目標與非目標

**目標**
1. 記一筆買賣 → 持股、股數、加權成本、已實現損益、現金餘額、曝險全部自動連動。
2. 現金是真的帳本：期初現金 ＋ 買賣現金流 ＋ 手續費 ＋ 證交稅 ＋ 入出金。
3. 每檔輸出一句可執行的個人化指令（含數量與價位），並可展開「為什麼」看用了哪些數字、被哪條規則覆寫。
4. 遷移不得靜默改動既有資料，逐檔對帳讓使用者確認。
5. `app/` 建立測試基礎設施（目前 0 個前端測試，34 個測試全在 Python 引擎）。

**非目標（本次不做）**
- 除權息、股票分割自動調整（保留事件型別位置，v2.1 再做）。
- 券商 API 對接、自動匯入對帳單。
- 多幣別、美股（backlog 另案）。
- 引擎側任何改動。

## 3. 資料模型 v2：事件帳本

### 3.1 為什麼是事件帳本

交易是不可變的事實，持股是重播事實得到的投影。關鍵理由不是優雅，而是：**編輯／刪除歷史交易時，全量重播必然正確，反向加減必然有邊界情況**。雙寫方案（做法 2）若要正確處理回溯編輯，最後仍須從日誌全量重算 holdings——那時 holdings 已經只是投影的快取，等於繞一圈回到這裡還多欠一筆技術債。

### 3.2 儲存

新 key：`advisor-war-room:ledger:v2`。**舊 key `:holdings` 與 `:journal` 原封不動保留**（不刪、不改），作為遷移失敗時的還原來源。

```ts
interface Ledger {
  schema_version: 2
  opening: {
    date: string          // YYYY-MM-DD，遷移切點；此日之前的交易只供覆盤，不影響庫存
    cash: number          // 期初現金（使用者填，不猜）
    positions: OpeningPosition[]
  }
  events: LedgerEvent[]
  settings: LedgerSettings
}

interface OpeningPosition {
  stock_id: string
  name: string
  sleeve: Sleeve          // 'core' | 'swing'
  shares: number
  cost_price: number      // 每股成本
}

type Sleeve = 'core' | 'swing'   // 核心＝定期定額長抱；波段＝吃防守價/減碼規則

type LedgerEvent = TradeEvent | CashEvent

interface TradeEvent {
  id: string
  type: 'trade'
  date: string            // 成交日
  created_at: string      // ISO，同日排序決勝
  stock_id: string
  name: string
  side: 'buy' | 'sell'
  sleeve: Sleeve
  price: number
  qty: number             // 股
  fee: number             // 手續費，預設自動算、可覆寫
  tax: number             // 證交稅，賣出才有，預設自動算、可覆寫
  followed_advice: boolean
  note?: string
}

interface CashEvent {
  id: string
  type: 'cash'
  date: string
  created_at: string
  direction: 'in' | 'out' // 入金／出金
  amount: number
  note?: string
}

interface LedgerSettings {
  total_capital: number   // 沿用既有 advisor-war-room:total_capital 的值
  fee_discount: number    // 券商折扣，預設 0.6（六折）
  fee_min: number         // 單筆最低手續費，預設 20
}
```

`sleeve` 是**每筆交易**的屬性而非每檔股票的屬性——同一檔 2330 可以同時有核心 1000 股與波段 500 股，兩個 sleeve 各自維護 FIFO 佇列。這解掉現行 `isPureCore`（靠「在核心清單且不在追蹤清單」推斷）無法處理「同一檔一半長抱一半波段」的缺口。

### 3.3 費稅公式（台股）

```
手續費 fee = max(fee_min, round(price × qty × 0.001425 × fee_discount))   // 買賣各收一次
證交稅 tax = round(price × qty × taxRate)                                  // 只有賣出收
  taxRate = 一般股票 0.003；ETF（代號以 00 開頭）0.001

買進現金流出 = price × qty + fee
賣出現金流入 = price × qty − fee − tax
```

`fee_discount` 預設 0.6，設定頁可改；每筆交易的 fee/tax 自動帶入後**允許使用者覆寫**（券商實際收費有零頭差異，不強迫對齊公式）。

**成本口徑**：加碼後顯示「剩餘未平倉部位的加權平均成本」，與券商 App 對得起來。手續費計入成本、證交稅計入賣出減項。

## 4. 投影引擎

單一純函式，無副作用，可完整單元測試：

```ts
derivePortfolio(ledger: Ledger, quotes: QuoteMap, now: Date): Portfolio
```

輸出：

```ts
interface Portfolio {
  positions: Position[]        // 每檔每 sleeve 一筆
  cash: number                 // 期初現金 + Σ賣出淨收 − Σ買進總支出 + 入金 − 出金
  totalMarketValue: number
  totalCost: number
  unrealizedPnl: number | null // 缺報價的部位整筆排除，並回報 missingPriceIds
  realizedPnl: number
  exposurePct: number | null   // 市值 / (現金 + 市值)；不再用 total_capital 硬除
  cashPct: number | null
  missingPriceIds: string[]
  issues: ReconciliationIssue[]
}

interface Position {
  stock_id: string
  name: string
  sleeve: Sleeve
  shares: number
  avgCost: number              // 剩餘未平倉 lots 的加權平均
  openLots: Lot[]
  realizedPnl: number
  marketValue: number | null
  unrealizedPnl: number | null
  weightPct: number | null     // 佔總資產
}
```

規則：

- FIFO 佇列以 `(stock_id, sleeve)` 為 key，期初部位當作日期為 `opening.date`、排在所有事件之前的一筆 lot。
- 事件依 `date` 升冪、同日用 `created_at` 決勝（沿用 `journal.ts:60` `sortKey` 的既有語意）。
- 任何編輯／刪除都是「改事件後全量重播」，不做增量回沖。
- 股數歸零 → 該 position 自動消失（不留空卡片）。
- **異常不丟棄、列為 issue**：賣超庫存（orphan）、負現金、重複 id、缺欄位、負數，全部進 `issues` 由 UI 顯示，不靜默吞掉。
- **曝險分母改用「現金 + 持股市值」**（真實總資產），不再用 `total_capital` 這個手填值。`total_capital` 退化為「目標資金規模」，僅用於集中度紅線與級距對照，並在 UI 標明差異。

跨頁反應性：ledger 統一收斂到一個 React context + `storage` 事件監聽，取代目前各頁 `useState(() => load...())` 各讀各的。

## 5. 個人化決策層

```ts
personalInstruction(input: {
  engine: PrimaryDecision          // 引擎建議（結構化欄位）
  position: Position | null        // 這檔這個 sleeve 的持倉
  quote: Quote | null              // 即時價
  portfolio: Portfolio             // 曝險、現金
  guidance: ExposureGuidance       // max_equity_pct / min_cash_pct / new_position
  streak: StreakAlert              // 連敗狀態
  allocation: number               // 組合層分配給這檔的減碼額度（見 5.2）
}): Instruction

interface Instruction {
  instruction: string              // 給人看的一句話
  action: 'sell' | 'hold' | 'buy' | 'wait'
  qty: number
  price: number | null
  ruleId: string                   // 例：PORTFOLIO_OVEREXPOSURE
  reasons: string[]
  inputsUsed: Record<string, number | string>   // 「為什麼」展開用
  degraded: boolean
}
```

### 5.1 硬規則

**個人化層只能收緊，不能放寬引擎的風控。** 引擎說 `exit`/`reduce` 時，前端不得因使用者虧損很多而改成攤平；引擎說加碼時，前端可以因曝險或冷靜期改成少買／不買。

### 5.2 優先序

| 序 | 規則 | 觸發 | 輸出 |
|---|---|---|---|
| 0 | 資料完整性閘門 | 缺即時價／報價過期／股數成本無效／缺結構化價位 | `degraded: true`，只給參考與防守價，**不產生可執行數量**。禁止拿成本價冒充現價算單。 |
| 1 | 組合風控 | 曝險 > `min(max_equity_pct, 100 − min_cash_pct)`／現金低於最低水位／單檔 > 40% | 賣出，數量由 5.3 統一分配 |
| 1b | 禁新倉閘門 | `new_position === '禁止新增部位'`／連敗 red | **不觸發賣出**，只把後續加碼數量壓成 0 股（既有部位仍照 2、3 處理停損與減碼） |
| 2 | 停損（**只砍 swing，不動 core**） | 現價跌破 `max(defense_price, avgCost × 0.92)` → 賣一半；跌破 `avgCost × 0.88` 或 `position_delta === 'exit'` → 波段全出 | 賣出 |
| 3 | 減碼 | `position_delta ∈ {reduce, exit}`／實際市值 > `position.tier_amount` | `ceil((市值 − tier_amount) / 現價)`；若實際部位已低於級距 → **不盲賣**，降級為守價 |
| 4 | 加碼／試單 | `position_delta ∈ {increase, small_entry}` 且 未破防守價 且 `new_position ≠ 禁止` 且 非 red 冷靜期 且 現價未顯著高於 `entry_condition.price` | `budget = min(級距缺口, 曝險餘裕, 現金 − 最低現金, 集中度餘裕)`；`僅限試單` 再壓到總資金 10%；amber 連敗數量減半 |
| 5 | 續抱 | 以上皆非 | 也要量化：「續抱 800 股，收盤跌破 90 元賣 400 股」 |

### 5.3 組合層減碼分配

超額曝險必須先由組合層 `allocatePortfolioRisk()` 統一分配，**不能讓每張卡各自算全部超額**（否則重複減碼、加總砍過頭）。分配排序：

1. 引擎標記 `exit`/`reduce` 的
2. 非核心波段部位
3. 超集中部位
4. 引擎 confidence 較低的
5. 核心部位（最後才動）

### 5.4 文案範例

- 風控：「現價 500 元，總曝險 70% 高於上限 60%；限價 500 元賣出 200 股，完成後曝險約降至 60%。」
- 停損：「成本 100 元、引擎防守價 94 元，現價 93 元已跌破；限價 93 元賣出波段 500 股，核心 1,000 股不動。」
- 減碼但已低於級距：「目前 1,000 股市值 10 萬，已低於建議級距 20 萬；先續抱，不再減碼，收盤跌破 92 元再賣 500 股。」
- 加碼受連敗壓制：「連續 2 筆停損，原可加碼 1,000 股降為 500 股；限價 100 元買進 500 股。」
- 追價保護：「現價 108 元已高於進場錨點 100 元 8%；今日不追價，等回到 100 元附近再重新計算。」
- 降級：「暫不下單；目前缺即時價，取得有效報價後再計算股數。引擎防守價為 94 元。」

### 5.5 明列的陷阱

- 連敗保護必須**真的覆寫數量**（red → 新增 0 股、amber → 減半），不能只貼橫幅。
- 核心與波段一定要分倉，不能只用「是否在 `core_holdings`」判斷。
- 沒有即時價就降級，快照收盤價可顯示參考但須標明「依 YYYY-MM-DD 收盤價估算」。
- 所有輸出保留 `ruleId` 與算式，UI 提供「為什麼」展開被哪條較高優先規則覆寫。

## 6. 遷移

一次性，使用者確認才寫入，**不刪舊 key**。

| 既有資料 | 行為 |
|---|---|
| 只有 holdings | 轉為期初部位，`opening.date` = 遷移日 |
| 只有 journal | 全量推導 |
| 兩者都有 | **逐檔對帳表**：顯示「舊持股股數 / 日誌推導股數 / 差額」，讓使用者選（a）以目前 holdings 為期初快照、舊日誌僅供覆盤，或（b）以完整日誌重建 |
| 兩者都無 | 直接建空帳本，引導填期初現金 |

- 期初現金一律由使用者輸入，不給預設值、不從 `total_capital` 推算。
- 遷移前的 sleeve 一律預設 `swing`，並在對帳表提示「有哪幾檔是定期定額核心請改成核心」。
- 舊資料的缺欄位／負數／重複代號／賣超列為 reconciliation issue 顯示，不靜默丟棄。
- 寫入 `schema_version: 2`；未來版本以此判斷是否需再遷移。

## 7. UI 變更

- **持股頁**：改讀投影；總覽卡新增「現金餘額」與「可配置額度」；曝險分母改真實總資產並標註口徑；每檔顯示個人化指令 ＋「為什麼」展開。
- **記一筆 modal**：新增 `sleeve` 選擇（核心／波段）、手續費與證交稅（自動帶入可覆寫）；`app/src/pages/StockSearch.tsx:498`、`app/src/pages/Holdings.tsx:456`、`app/src/components/JournalListModal.tsx:79` 三個呼叫點同步。
- **新增入出金入口**（在交易日誌 modal 內，與「記一筆交易」並列）。
- **遷移對帳畫面**：一次性全螢幕流程。
- 既有 `StreakAlertBanner` 保留，但下方指令必須與它一致（由 5.2 保證，不再各說各話）。

## 8. 測試

`app/` 導入 Vitest（目前無任何前端測試）。必須覆蓋：

- `derivePortfolio`：買/賣/加碼加權成本/清倉移除/賣超 orphan/跨 sleeve 隔離/回溯插入舊交易後重播/事件排序決勝。
- 費稅：一般股 vs ETF 稅率、最低手續費 20 元、折扣、覆寫值優先。
- 現金：期初＋買賣＋入出金；負現金列 issue。
- `personalInstruction`：每條規則各一組、優先序覆寫（風控壓過加碼、red 壓成 0 股、amber 減半）、降級路徑、核心不被砍。
- `allocatePortfolioRisk`：多檔超額不重複減碼、加總等於所需減碼額。
- 遷移：四種情境 ＋ 重複執行冪等 ＋ 損壞資料。

**交付前實跑 prod 驗證**，不接受只有 fixture 自測（歷來雷點：前端自造 fixture 自我印證）。

## 9. 契約

引擎 JSON 不變。於 `docs/contracts/data-contract-v1.md` 補「v1.9 增補（App 行為）」一節，記錄 ledger v2 的 localStorage schema、費稅公式、個人化決策層優先序，作為前端權威來源。

## 10. 分階段交付

| 階段 | 內容 | 可交付價值 |
|---|---|---|
| P0 | Vitest 基礎設施 ＋ 帳本型別 ＋ `derivePortfolio` ＋ 測試 | 邏輯正確且有證據 |
| P1 | 現金帳本、費稅、入出金 | 現金與曝險變成真的 |
| P2 | 遷移流程 ＋ 對帳畫面 | 舊資料安全轉入 |
| P3 | 個人化決策層 ＋ UI 整合 | Andy 要的「客製化建議」 |
| P4 | prod 實測 ＋ Codex 交叉審 ＋ 契約 v1.9 落檔 | 交付 |

P0–P2 期間 App 行為不變（新舊並存、以舊為準），P3 切換為新資料源，降低中途中斷的風險。

## 11. 待確認（已送 Andy，未回則採預設）

1. 券商手續費折扣（預設 6 折 ＝ 0.0855%，單筆最低 20 元）
2. 期初現金金額（**必填，不猜**）
3. 哪些部位屬於定期定額核心（預設全部轉 `swing`，遷移對帳表可改）

證交稅率採一般股票 0.3%、ETF 0.1%（實作前再核當期官方稅率一次，不憑記憶寫死）。
