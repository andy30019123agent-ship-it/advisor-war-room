// 帳本 v2（規格 docs/superpowers/specs/2026-07-23-portfolio-ledger-and-personal-advice-design.md §3）
//
// 為什麼是「事件帳本」而不是直接存一張持股表：交易是不可變的事實，持股是重播事實得到的
// 投影。使用者回頭修改／刪除一筆舊交易時，全量重播必然算對；反向加減必然有邊界情況
// （舊做法就是死在這裡——記一筆買賣完全不會動到持股表，兩份資料各說各話）。
//
// 舊 key（advisor-war-room:holdings / :journal）遷移後原封不動保留，不刪不改，是唯一的還原來源。

export const LEDGER_KEY = 'advisor-war-room:ledger:v2'
export const LEDGER_SCHEMA_VERSION = 2

// long＝長期持有（0050/2330 這種），不吃停損與減碼規則；swing＝波段，照防守價操作。
export type PositionTag = 'long' | 'swing'

// Andy 2026-07-23 指定的長期部位；遷移時預設標記，之後使用者可自己改。
export const DEFAULT_LONG_TERM_IDS = ['0050', '2330']

export interface OpeningPosition {
  stock_id: string
  name: string
  shares: number
  cost_price: number
}

export interface TradeEvent {
  id: string
  type: 'trade'
  date: string // YYYY-MM-DD 成交日
  created_at: string // ISO，同日多筆時排序決勝
  stock_id: string
  name: string
  side: 'buy' | 'sell'
  price: number
  qty: number // 股
  fee: number // 手續費：系統依公式自動算後寫入（存下來才可稽核，UI 不要求使用者輸入）
  tax: number // 證交稅：只有賣出才有
  followed_advice: boolean
  note?: string
  /**
   * 遷移進來的舊日誌。**一律不計入庫存與現金**，只供連敗保護與週覆盤。
   * 為什麼不能只靠 `date < opening.date` 判斷：遷移當天若舊日誌也有當天的買賣，
   * 舊 holdings 已經包含它的結果，日期比較不會排除它 → 同一筆被算兩次
   * （股數變兩倍、現金再扣一次）。未來日期的舊日誌同理。旗標才分得清「這是既有
   * 部位的來源」還是「遷移後真的又交易了一筆」。
   */
  legacy?: true
}

// 使用者直接改「現金餘額」時記下差額。不覆寫 opening.cash——覆寫會破壞「全量重播必然
// 正確」的性質（重播到一半的中間狀態會用到錯的期初值）。
export interface CashAdjustEvent {
  id: string
  type: 'cash_adjust'
  date: string
  created_at: string
  delta: number
  note?: string
}

export type LedgerEvent = TradeEvent | CashAdjustEvent

export interface LedgerSettings {
  fee_discount: number // 券商折扣，預設 0.6（六折）
  fee_min: number // 單筆最低手續費，預設 20 元
}

export interface Ledger {
  schema_version: 2
  opening: {
    date: string // 遷移日。早於這天的交易只供覆盤，不計入庫存（見 portfolio.ts）
    cash: number
    positions: OpeningPosition[]
  }
  events: LedgerEvent[]
  tags: Record<string, PositionTag>
  settings: LedgerSettings
}

export const DEFAULT_SETTINGS: LedgerSettings = { fee_discount: 0.6, fee_min: 20 }

export function todayTaipei(now: Date = new Date()): string {
  const t = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Taipei' }))
  return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`
}

export function genEventId(prefix = 'e'): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

export function emptyLedger(date: string = todayTaipei()): Ledger {
  return {
    schema_version: LEDGER_SCHEMA_VERSION,
    opening: { date, cash: 0, positions: [] },
    events: [],
    tags: Object.fromEntries(DEFAULT_LONG_TERM_IDS.map((id) => [id, 'long' as PositionTag])),
    settings: { ...DEFAULT_SETTINGS },
  }
}

// ---------- 費稅（台股，系統自動算，使用者不必輸入）----------

const FEE_RATE = 0.001425
const TAX_RATE_STOCK = 0.003
const TAX_RATE_ETF = 0.001

// ETF 判定：台股 ETF 代號以 00 開頭（0050、0056、00878…）。這是給稅率用的粗篩，
// 不是完整的證券類型判斷——寧可保守用較高的一般股稅率，也不要把一般股算成 ETF 少收稅
// 而讓使用者以為自己賣出能拿回更多錢。
export function isEtf(stockId: string): boolean {
  return /^00/.test(stockId)
}

export function calcFee(price: number, qty: number, settings: LedgerSettings = DEFAULT_SETTINGS): number {
  const gross = price * qty
  if (!(gross > 0)) return 0
  return Math.max(settings.fee_min, Math.round(gross * FEE_RATE * settings.fee_discount))
}

export function calcTax(stockId: string, side: 'buy' | 'sell', price: number, qty: number): number {
  if (side !== 'sell') return 0 // 證交稅只有賣出才收
  const gross = price * qty
  if (!(gross > 0)) return 0
  return Math.round(gross * (isEtf(stockId) ? TAX_RATE_ETF : TAX_RATE_STOCK))
}

// 買進：現金流出 = 成交金額 + 手續費；賣出：現金流入 = 成交金額 − 手續費 − 證交稅。
export function tradeCashFlow(e: TradeEvent): number {
  const gross = e.price * e.qty
  return e.side === 'buy' ? -(gross + e.fee) : gross - e.fee - e.tax
}

export function makeTrade(
  input: Omit<TradeEvent, 'id' | 'type' | 'created_at' | 'fee' | 'tax'> & { fee?: number; tax?: number },
  settings: LedgerSettings = DEFAULT_SETTINGS,
  createdAt: string = new Date().toISOString()
): TradeEvent {
  return {
    id: genEventId('t'),
    type: 'trade',
    created_at: createdAt,
    ...input,
    fee: input.fee ?? calcFee(input.price, input.qty, settings),
    tax: input.tax ?? calcTax(input.stock_id, input.side, input.price, input.qty),
  }
}

// ---------- 儲存 ----------

export function loadLedger(): Ledger | null {
  try {
    const raw = localStorage.getItem(LEDGER_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || parsed.schema_version !== LEDGER_SCHEMA_VERSION) return null
    return normalizeLedger(parsed)
  } catch {
    return null
  }
}

export function saveLedger(ledger: Ledger): void {
  try {
    localStorage.setItem(LEDGER_KEY, JSON.stringify(ledger))
  } catch {
    // localStorage 不可用（隱私模式／配額滿）：靜默放棄，畫面仍照 state 顯示本次結果。
    // 這裡不能吞得無聲無息到使用者以為存好了——呼叫端負責提示，見 usePortfolio。
  }
}

// 舊資料／手動編輯過的 JSON 可能缺欄位。補完預設值而不是拒收，壞掉的部分交給
// derivePortfolio 列成 issue 顯示，不靜默丟資料。
export function normalizeLedger(raw: Partial<Ledger>): Ledger {
  const base = emptyLedger(raw.opening?.date ?? todayTaipei())
  return {
    schema_version: LEDGER_SCHEMA_VERSION,
    opening: {
      date: raw.opening?.date ?? base.opening.date,
      cash: Number(raw.opening?.cash) || 0,
      positions: Array.isArray(raw.opening?.positions) ? raw.opening.positions : [],
    },
    events: Array.isArray(raw.events) ? raw.events : [],
    tags: { ...base.tags, ...(raw.tags ?? {}) },
    settings: { ...DEFAULT_SETTINGS, ...(raw.settings ?? {}) },
  }
}

export function getTag(ledger: Ledger, stockId: string): PositionTag {
  return ledger.tags[stockId] ?? 'swing'
}
