# 帳本制持倉 ＋ 個人化操作建議（設計）

> 2026-07-23．Andy 拍板：帳本制 ＋ 記現金；同日**主動縮減範圍**（原話：「我覺得你們想太複雜，我單純只要對於我的庫存與買入賣出請你們給我建議」）
> 長期部位：0050、2330
> 前置：Claude 診斷 → Codex 交叉分析（兩輪）→ Claude 審核採納 → Andy 砍規模
> 影響範圍：**純前端**（`app/`）。引擎 JSON 契約不變。

## 1. 問題

Andy 原話：「連動感有點糟，例如我新增購入股數卻沒跑到我的持股中；應該要我填入後持續幫我彙整目前持倉，並給我操作建議，這個操作建議應該要按照目前價位與水位去調整；目前用起來像是有功能但建議不夠精確也不夠客製化。」

根因是兩件事：

### 1.1 兩套資料各自為政

`advisor-war-room:holdings`（手填持股）與 `advisor-war-room:journal`（交易日誌）是兩個互不相通的 localStorage key。`JournalEntryFormModal` 存檔後只 `setJournal`，從不碰 holdings。

| 現象 | 位置 |
|---|---|
| 記買單持股不增、記賣單不減、賣光了卡片還在 | `Holdings.tsx:455-462` onSaved 只更新 journal |
| 加碼不算加權平均成本 | `holdings.ts:28` `saveHolding()` 同代號整筆覆寫 |
| 「編輯股數」語意是「改成總共幾股」而非「這次買幾股」 | `Holdings.tsx:557` |
| 同一檔兩套成本並存（未實現用手填 `costPrice`、已實現用 FIFO） | `Holdings.tsx:162` vs `journal.ts:122` |
| 先手動建持股、再記賣單 → 賣單成孤兒，不算損益也不進連敗判定 | `journal.ts:94` 只認 journal 買單 |
| 曝險/現金水位只跟 holdings 走，日誌買賣不影響 | `Holdings.tsx:203` |
| 現金水位是 `100 − 曝險` 的推估，不是真現金 | `Holdings.tsx:216` |
| localStorage 無跨頁反應性（只在 mount 讀一次） | `Holdings.tsx:38,45` |

### 1.2 建議沒有「你」

每檔顯示的 `advice.holder.action_text` 與 `plan` 是引擎給「一般持有者」的通用文案，不看使用者的成本、損益、佔比、曝險、現金。附帶兩個更嚴重的：

- **風控算對了卻沒接到輸出端**：`getStreakAlert()` 已正確算出「3 連敗 → 暫停新倉」，但只餵給 `StreakAlertBanner`，下方卡片照樣顯示加碼建議 → 同一畫面可同時出現「暫停新倉」與「加碼 10 萬」。`max_equity_pct`／`min_cash_pct`／`new_position` 同樣只警告，不影響每檔建議。
- **盤中價變了建議不重算**：市值損益會更新，`actionText`/`plan`/`defensePrice` 仍來自快照。

引擎已提供足夠的結構化欄位可運算（皆已核對存在於 `app/src/types/contract.ts`）：`position.tier_amount:359`、`position_delta:352`、`entry_condition.price:364`、`defense_price`、`exposure_guidance.max_equity_pct/min_cash_pct/new_position:168-169`。**運算一律只讀結構化欄位，禁止解析 `plan.trigger/act` 的中文字串。**

## 2. 目標與非目標

**目標**
1. 記一筆買賣 → 持股、股數、加權成本、已實現損益、現金、曝險自動連動。
2. 現金自動加減（含手續費與證交稅，系統自動算，使用者不必輸入）。
3. 每檔輸出一句可執行的個人化指令（含數量與價位），可展開「為什麼」。
4. 0050／2330 標為長期，不被停損／減碼規則叫去砍。
5. `app/` 建立測試基礎設施（目前 0 個前端測試）。

**非目標（Andy 明確砍掉或本次不做）**
- 遷移對帳畫面 —— 直接拿現有持股當起點。
- 入出金事件流 UI —— 只留一個可直接編輯的「現金餘額」。
- 同一檔拆核心／波段兩個 sleeve —— 改成整檔標記。
- 分階段交付 —— 一次做完再交付。
- 除權息／股票分割自動調整、券商匯入、美股、多幣別。
- 引擎側任何改動。

## 3. 資料模型 v2：事件帳本

### 3.1 為什麼是事件帳本

交易是不可變的事實，持股是重播事實得到的投影。關鍵理由不是優雅，而是：**編輯／刪除歷史交易時，全量重播必然正確，反向加減必然有邊界情況**。

### 3.2 儲存

新 key：`advisor-war-room:ledger:v2`。**舊 key `:holdings` 與 `:journal` 原封不動保留**（不刪不改），作為還原來源。

```ts
interface Ledger {
  schema_version: 2
  opening: {
    date: string              // YYYY-MM-DD＝遷移日；此日之前的交易只供覆盤，不計入庫存
    cash: number              // 現金餘額起點
    positions: OpeningPosition[]
  }
  events: LedgerEvent[]
  tags: Record<string, PositionTag>   // stock_id → 'long' | 'swing'，預設 swing
  settings: { fee_discount: number; fee_min: number }
}

type PositionTag = 'long' | 'swing'   // long＝長期持有，不吃停損/減碼；swing＝波段

interface OpeningPosition { stock_id: string; name: string; shares: number; cost_price: number }

type LedgerEvent = TradeEvent | CashAdjustEvent

interface TradeEvent {
  id: string; type: 'trade'
  date: string; created_at: string
  stock_id: string; name: string
  side: 'buy' | 'sell'
  price: number; qty: number
  fee: number; tax: number          // 系統自動算後寫入（存下來才可稽核），UI 不要求輸入
  followed_advice: boolean; note?: string
}

interface CashAdjustEvent {
  id: string; type: 'cash_adjust'
  date: string; created_at: string
  delta: number                     // 使用者直接改現金餘額時記下差額，保持重播可還原
  note?: string
}
```

現金餘額在 UI 上是一個可直接編輯的數字；改動落地成 `cash_adjust` 事件而非覆寫 `opening.cash`，這樣「全量重播必然正確」的性質不被破壞。

### 3.3 費稅公式（台股，系統自動）

```
手續費 fee = max(fee_min, round(price × qty × 0.001425 × fee_discount))   // 買賣各一次
證交稅 tax = round(price × qty × taxRate)                                  // 只有賣出
  taxRate = 一般股票 0.003；ETF（代號以 00 開頭）0.001

買進現金流出 = price × qty + fee
賣出現金流入 = price × qty − fee − tax
```

`fee_discount` 預設 0.6、`fee_min` 預設 20，設定頁可改。手續費計入持有成本，證交稅計入賣出減項。實作前再核當期官方稅率一次，不憑記憶寫死。

## 4. 投影引擎

單一純函式，無副作用：

```ts
derivePortfolio(ledger: Ledger, quotes: QuoteMap): Portfolio
```

```ts
interface Portfolio {
  positions: Position[]
  cash: number                 // opening.cash + Σ賣出淨收 − Σ買進總支出 + Σcash_adjust.delta
  totalMarketValue: number
  unrealizedPnl: number | null // 缺報價的部位整筆排除，並回報 missingPriceIds
  realizedPnl: number
  totalAssets: number          // cash + totalMarketValue
  exposurePct: number | null   // totalMarketValue / totalAssets
  cashPct: number | null
  missingPriceIds: string[]
  issues: ReconciliationIssue[]
}

interface Position {
  stock_id: string; name: string; tag: PositionTag
  shares: number
  avgCost: number              // 剩餘未平倉 lots 的加權平均（含手續費）
  openLots: Lot[]
  realizedPnl: number
  marketValue: number | null
  unrealizedPnl: number | null
  weightPct: number | null     // 佔總資產
}
```

規則：

- FIFO 佇列以 `stock_id` 為 key。期初部位＝日期為 `opening.date`、排在所有事件之前的一筆 lot。
- `date < opening.date` 的交易事件**不計入庫存**（避免與期初部位重複計算），但仍供連敗保護與週覆盤使用。
- 事件依 `date` 升冪、同日用 `created_at` 決勝（沿用 `journal.ts:60` `sortKey` 語意）。
- 編輯／刪除一律「改事件後全量重播」，不做增量回沖。
- 股數歸零 → position 自動消失。
- **異常不丟棄、列為 issue**：賣超庫存、負現金、重複 id、缺欄位、負數，交由 UI 顯示。
- **曝險分母改用真實總資產**（現金＋市值），不再用手填的 `total_capital`。後者退化為「目標資金規模」，僅用於集中度紅線與級距對照，UI 標明口徑。

跨頁反應性：ledger 收斂到一個 React context ＋ `storage` 事件監聽，取代各頁 `useState(() => load...())` 各讀各的。

## 5. 個人化決策層

```ts
personalInstruction(input: {
  engine: PrimaryDecision
  position: Position | null
  quote: Quote | null
  portfolio: Portfolio
  guidance: ExposureGuidance
  streak: StreakAlert
  allocation: number          // 組合層分配給這檔的減碼額度（見 5.3）
}): Instruction

interface Instruction {
  instruction: string
  action: 'sell' | 'hold' | 'buy' | 'wait'
  qty: number
  price: number | null
  ruleId: string
  reasons: string[]
  inputsUsed: Record<string, number | string>
  degraded: boolean
}
```

### 5.1 硬規則

**個人化層只能收緊，不能放寬引擎風控。** 引擎說 `exit`/`reduce` 時，前端不得因使用者虧損很多而改成攤平；引擎說加碼時，前端可以因曝險或冷靜期改成少買／不買。

### 5.2 優先序

| 序 | 規則 | 觸發 | 輸出 |
|---|---|---|---|
| 0 | 資料完整性閘門 | 缺即時價／報價過期／股數成本無效／缺結構化價位 | `degraded: true`，只給參考與防守價，**不產生可執行數量**。禁止拿成本價冒充現價算單。 |
| 1 | 組合風控 | 曝險 > `min(max_equity_pct, 100 − min_cash_pct)`／現金低於最低水位／單檔 > 40% | 賣出，數量由 5.3 統一分配 |
| 1b | 禁新倉閘門 | `new_position === '禁止新增部位'`／連敗 red | **不觸發賣出**，把後續加碼壓成 0 股 |
| 2 | 停損（**只作用於 `tag === 'swing'`**） | 現價跌破 `max(defense_price, avgCost × 0.92)` → 賣一半；跌破 `avgCost × 0.88` 或 `position_delta === 'exit'` → 全出 | 賣出 |
| 3 | 減碼（**只作用於 swing**） | `position_delta ∈ {reduce, exit}`／市值 > `position.tier_amount` | `ceil((市值 − tier_amount) / 現價)`；若部位已低於級距 → **不盲賣**，降級為守價 |
| 4 | 加碼／試單 | `position_delta ∈ {increase, small_entry}` 且 未破防守價 且 `new_position ≠ 禁止` 且 非 red 且 現價未顯著高於 `entry_condition.price` | `budget = min(級距缺口, 曝險餘裕, 現金 − 最低現金, 集中度餘裕)`；`僅限試單` 壓到總資產 10%；amber 連敗數量減半 |
| 5 | 續抱 | 以上皆非 | 也要量化：「續抱 800 股，收盤跌破 90 元賣 400 股」 |

`tag === 'long'`（0050／2330）只走 0、1、4、5：不停損、不減碼，但仍受組合風控與加碼閘門約束，且組合減碼分配時排在最後。

### 5.3 組合層減碼分配

超額曝險先由 `allocatePortfolioRisk()` 統一分配，**不能讓每張卡各自算全部超額**（否則重複減碼、砍過頭）。排序：引擎 `exit`/`reduce` → 波段部位 → 超集中部位 → confidence 較低 → 長期部位最後。

### 5.4 文案範例

- 風控：「現價 500 元，總曝險 70% 高於上限 60%；限價 500 元賣出 200 股，完成後曝險約降至 60%。」
- 停損：「成本 100 元、引擎防守價 94 元，現價 93 元已跌破；限價 93 元賣出 500 股。」
- 減碼但已低於級距：「目前 1,000 股市值 10 萬，已低於建議級距 20 萬；先續抱，收盤跌破 92 元再賣 500 股。」
- 加碼受連敗壓制：「連續 2 筆停損，原可加碼 1,000 股降為 500 股；限價 100 元買進 500 股。」
- 追價保護：「現價 108 元已高於進場錨點 100 元 8%；今日不追價，等回到 100 元附近再重新計算。」
- 長期部位：「0050 為長期部位，續抱 2,000 股，定期定額照常，不因短線跌破防守價賣出。」
- 降級：「暫不下單；目前缺即時價，取得有效報價後再計算股數。引擎防守價為 94 元。」

### 5.5 明列的陷阱

- 連敗保護必須**真的覆寫數量**（red → 0 股、amber → 減半），不能只貼橫幅。
- 長期部位不得被停損／減碼規則叫去砍。
- 沒有即時價就降級，快照收盤價可顯示參考但須標明「依 YYYY-MM-DD 收盤價估算」。
- 所有輸出保留 `ruleId` 與算式，UI 提供「為什麼」展開被哪條較高優先規則覆寫。

## 6. 遷移（自動，無使用者流程）

首次載入偵測無 `ledger:v2` 時自動建立：

- `opening.date` = 遷移當日；`opening.positions` = 既有 `holdings` 全部。
- `opening.cash` = 0，並在持股頁提示「請設定現金餘額」（不猜金額）。
- `tags`：`0050`、`2330` 預設 `long`，其餘 `swing`。
- 既有 `journal` 全部轉為 `TradeEvent`（`fee`/`tax` 依公式回填），日期早於 `opening.date` 者不計入庫存、僅供連敗與週覆盤 —— 這正是「不重複計算」的保證。
- 舊 key 不刪；遷移冪等（已存在 `ledger:v2` 就不再執行）。

## 7. UI 變更

- **持股頁**：改讀投影；總覽卡新增「現金餘額」（可直接編輯）與「總資產」；曝險改真實口徑並標註；每檔顯示個人化指令 ＋「為什麼」展開；每檔可切換「長期／波段」標記。
- **記一筆 modal**：不新增輸入欄位（費稅自動算）；三個呼叫點 `StockSearch.tsx:498`、`Holdings.tsx:456`、`JournalListModal.tsx:79` 改寫入 ledger。
- **移除**手動「新增/編輯持股」的股數覆寫語意 —— 改為「這次買/賣幾股」，避免既有的誤解。
- `StreakAlertBanner` 保留，下方指令由 5.2 保證與它一致。

## 8. 測試

`app/` 導入 Vitest。必須覆蓋：

- `derivePortfolio`：買／賣／加碼加權成本／清倉移除／賣超 orphan／回溯插入舊交易後重播／事件排序決勝／`date < opening.date` 不計入庫存。
- 費稅：一般股 vs ETF、最低手續費 20 元、折扣。
- 現金：期初＋買賣＋`cash_adjust`；負現金列 issue。
- `personalInstruction`：每條規則各一組、優先序覆寫（風控壓過加碼、red 壓成 0 股、amber 減半）、降級路徑、`long` 不被砍。
- `allocatePortfolioRisk`：多檔超額不重複減碼、加總等於所需減碼額。
- 遷移：四種情境 ＋ 重複執行冪等 ＋ 損壞資料。

**交付前實跑 prod 驗證**，不接受只有 fixture 自測（歷來雷點：前端自造 fixture 自我印證）。

## 9. 契約

引擎 JSON 不變。於 `docs/contracts/data-contract-v1.md` 補「v1.9 增補（App 行為）」一節，記錄 ledger v2 schema、費稅公式、個人化決策層優先序，作為前端權威來源。
