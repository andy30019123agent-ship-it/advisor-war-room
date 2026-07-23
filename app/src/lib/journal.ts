// 交易日誌（C 包・勝率行為閉環，契約 v1.5「App 行為」節）：使用者自行記錄的買賣紀錄。
// 用途是把「模型的建議對不對」跟「使用者有沒有照建議操作」拆開看——覆盤時才分得清是模型錯
// 還是自己手癢，同時用連續停損偵測擋散戶加碼攤平／報復性交易的自毀行為。
//
// 2026-07-23 起「儲存」改接帳本 v2（ledger.ts）：日誌不再是獨立的一份資料，而是帳本裡
// TradeEvent 的另一種視角。這正是「記一筆買賣持股卻沒動」的根治點——只要還有兩份各自
// 儲存的資料，就一定會有一天對不上。下面的純邏輯（FIFO 配對、連敗、週覆盤）完全沒動。
// 舊 key advisor-war-room:journal 保留不刪，由 ledgerMigration 一次性讀進帳本。

// 這裡刻意寫出 .ts 副檔名：scripts/test-journal.mjs 用 Node 的 TS type-stripping 直接跑
// 這支檔案，而 type-stripping 不解析無副檔名的相對匯入（tsconfig 已開
// allowImportingTsExtensions，Vite 與 tsc 都吃得下）。改成無副檔名會讓那支腳本壞掉。
import { loadLedger, makeTrade, saveLedger, type Ledger, type TradeEvent } from './ledger.ts'

export type JournalSide = 'buy' | 'sell'

export interface JournalEntry {
  id: string
  date: string // YYYY-MM-DD，使用者輸入的成交日
  stock_id: string
  name: string
  side: JournalSide
  price: number
  qty: number
  followed_advice: boolean
  note?: string
  created_at: string // ISO 時間戳，新增當下產生，同一天多筆時用來排時間序
}

/** 舊 key。只有 ledgerMigration 會讀它做一次性遷移；一般流程不再讀寫。 */
export const LEGACY_JOURNAL_KEY = 'advisor-war-room:journal'

export function loadLegacyJournal(): JournalEntry[] {
  try {
    const raw = localStorage.getItem(LEGACY_JOURNAL_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function tradeToJournalEntry(e: TradeEvent): JournalEntry {
  return {
    id: e.id,
    date: e.date,
    stock_id: e.stock_id,
    name: e.name,
    side: e.side,
    price: e.price,
    qty: e.qty,
    followed_advice: e.followed_advice,
    note: e.note,
    created_at: e.created_at,
  }
}

export function loadJournal(): JournalEntry[] {
  const ledger = loadLedger()
  return ledger ? journalFromLedger(ledger) : []
}

// 純函式版本：呼叫端已經有 ledger 時直接用這支，不要再讀一次 localStorage——
// 讀 localStorage 的版本對 React 來說是「沒有輸入的函式」，依賴關係看不出來，
// 帳本更新後畫面可能繼續用舊的連敗狀態。
export function journalFromLedger(ledger: Ledger): JournalEntry[] {
  const trades = ledger.events.filter((e): e is TradeEvent => e.type === 'trade').map(tradeToJournalEntry)

  // 期初部位要補一筆合成買單，否則賣掉遷移進來的持股時 FIFO 配不到成本 → 被判成孤兒單 →
  // 不算虧損 → 連敗保護整個失效（連停三檔期初持股，streak 仍是 0，red 冷靜期被繞過）。
  // 只有這裡（連敗／週覆盤）需要它；derivePortfolio 走的是 opening.positions 本身，
  // 不讀這份清單，所以不會重複計算。
  const opening: JournalEntry[] = ledger.opening.positions
    .filter((p) => p?.stock_id && p.shares > 0)
    .map((p) => ({
      id: `opening_${p.stock_id}`,
      date: ledger.opening.date,
      stock_id: p.stock_id,
      name: p.name || p.stock_id,
      side: 'buy' as JournalSide,
      price: p.cost_price,
      qty: p.shares,
      followed_advice: true,
      note: '期初部位（遷移建立）',
      created_at: '0000-01-01T00:00:00.000Z', // 排在所有事件之前，確保後續賣出配得到它
    }))

  return [...opening, ...trades]
}

export function genJournalId(): string {
  return `j_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

// 新增／編輯一筆交易＝寫進帳本。費稅由 makeTrade 依公式自動算（使用者不必輸入），
// 編輯既有紀錄時沿用原本的 id 與 created_at，讓時間序與 FIFO 配對維持穩定。
export function saveJournalEntry(entry: JournalEntry): JournalEntry[] {
  const ledger = loadLedger()
  if (!ledger) return []
  const trade = makeTrade(
    {
      date: entry.date,
      stock_id: entry.stock_id,
      name: entry.name,
      side: entry.side,
      price: entry.price,
      qty: entry.qty,
      followed_advice: entry.followed_advice,
      note: entry.note,
    },
    ledger.settings,
    entry.created_at
  )
  trade.id = entry.id
  const idx = ledger.events.findIndex((e) => e.id === entry.id)
  const events = [...ledger.events]
  if (idx >= 0) events[idx] = trade
  else events.push(trade)
  saveLedger({ ...ledger, events })
  return loadJournal()
}

export function deleteJournalEntry(id: string): JournalEntry[] {
  const ledger = loadLedger()
  if (!ledger) return []
  saveLedger({ ...ledger, events: ledger.events.filter((e) => e.id !== id) })
  return loadJournal()
}

// 排序 key：date 優先，同天用 created_at 決勝，確保「連續停損」判定跟畫面顯示的
// 時間順序一致，不受使用者輸入順序或 localStorage 陣列順序影響。
function sortKey(e: JournalEntry): string {
  return `${e.date}T${e.created_at}`
}

export function sortedByTime(entries: JournalEntry[]): JournalEntry[] {
  return [...entries].sort((a, b) => (sortKey(a) < sortKey(b) ? -1 : sortKey(a) > sortKey(b) ? 1 : 0))
}

// 單筆賣出配到的其中一筆買進批次（FIFO 消耗庫存的其中一段）。
export interface FifoMatchLot {
  buy: JournalEntry
  qty: number // 這筆賣出從這筆買進批次吃掉的股數
}

export interface SellWithPnl {
  sell: JournalEntry
  buy: JournalEntry | null // FIFO 配到的第一筆（最舊）買進；相容舊介面／畫面顯示用，完整明細見 matches
  matches: FifoMatchLot[] // 依 FIFO 順序配到的買進批次（可能跨多筆買進）
  matchedQty: number // 有配到成本的股數
  orphanQty: number // 賣超庫存、配不到成本的股數（不算損益、不進連敗判定）
  isLoss: boolean | null // matchedQty=0（整筆 orphan）時無法判斷 → null
  pnlAmt: number | null // 只計 matched 部位的損益；matchedQty=0 時 null
}

interface FifoLot {
  entry: JournalEntry
  remaining: number
}

// 全域 FIFO 模擬：依股票代號分組，依時間序逐筆處理買/賣——買進推入庫存佇列，賣出從佇列
// 最舊的批次開始依序吃（先進先出），可能一筆賣出跨吃好幾筆不同價位的買進。賣出數量超過
// 當下庫存的部分記為 orphan（配不到買進成本，例如日誌只補記了賣出、沒有補買進，或補記
// 順序有誤造成賣超）——orphan 部位不算損益、也不計入連敗判定。用 allEntries 的完整時間序
// 模擬（不只看 sellsSubset），確保子集之外的買賣也會正確消耗/佔用庫存。
function computeFifoMatches(allEntries: JournalEntry[]): Map<string, SellWithPnl> {
  const bySid = new Map<string, JournalEntry[]>()
  for (const e of sortedByTime(allEntries)) {
    const list = bySid.get(e.stock_id)
    if (list) list.push(e)
    else bySid.set(e.stock_id, [e])
  }

  const result = new Map<string, SellWithPnl>()
  for (const entries of bySid.values()) {
    const queue: FifoLot[] = []
    for (const e of entries) {
      if (e.side === 'buy') {
        queue.push({ entry: e, remaining: e.qty })
        continue
      }
      let need = e.qty
      const matches: FifoMatchLot[] = []
      while (need > 0 && queue.length > 0) {
        const lot = queue[0]
        const take = Math.min(need, lot.remaining)
        matches.push({ buy: lot.entry, qty: take })
        lot.remaining -= take
        need -= take
        if (lot.remaining <= 0) queue.shift()
      }
      const matchedQty = e.qty - need
      const orphanQty = need
      const pnlAmt = matchedQty > 0
        ? matches.reduce((sum, m) => sum + (e.price - m.buy.price) * m.qty, 0)
        : null
      result.set(e.id, {
        sell: e,
        buy: matches.length > 0 ? matches[0].buy : null,
        matches,
        matchedQty,
        orphanQty,
        isLoss: matchedQty > 0 ? (pnlAmt as number) < 0 : null,
        pnlAmt,
      })
    }
  }
  return result
}

// 幫一筆賣出配對「對應買進」：per-stock FIFO 消耗庫存下，這筆賣出吃到的第一筆（最舊）
// 買進批次。找不到（庫存已空、整筆 orphan）就回 null。
export function findMatchingBuy(allEntries: JournalEntry[], sell: JournalEntry): JournalEntry | null {
  return computeFifoMatches(allEntries).get(sell.id)?.buy ?? null
}

// allEntries：拿來模擬 FIFO 庫存的完整母體（含週期範圍外的買賣，確保消耗順序正確）。
// sellsSubset：要回傳結果的賣出子集，預設＝allEntries 裡全部的賣出。
export function pairSells(allEntries: JournalEntry[], sellsSubset?: JournalEntry[]): SellWithPnl[] {
  const sells = sortedByTime(sellsSubset ?? allEntries.filter((e) => e.side === 'sell'))
  const matches = computeFifoMatches(allEntries)
  return sells.map((sell) => matches.get(sell.id) ?? {
    sell, buy: null, matches: [], matchedQty: 0, orphanQty: sell.qty, isLoss: null, pnlAmt: null,
  })
}

// ---------- 連敗保護 ----------

// 連續停損筆數：從時間序最新的賣出往回數，遇到「FIFO 配對得到成本且虧損」的賣出就繼續數；
// 遇到「配得到成本但賺錢」（isLoss=false）才真的中斷——那才是連敗被打斷的證據。
// 孤兒賣單（isLoss=null，配不到成本，例如漏記買進、或同日補記賣單時買單還沒進 queue）
// 改成「跳過、繼續往前看」而不是中斷：孤兒單本身不代表使用者賺錢或停損保護該解除，
// 之前把 null 當中斷會讓使用者補記一筆漏配的賣單就把冷靜期保護整個歸零（大檢查2 Y5，
// 保守方向反了——寧可繼續數，不要誤放行冷靜期）。isLoss 已是 FIFO 損益的結果（見
// computeFifoMatches，內部依 sortedByTime＝date 優先、同日用 created_at 決勝排序），
// 這裡不用再處理配對細節。
export function getLossStreak(entries: JournalEntry[]): number {
  const sells = pairSells(entries) // 已經是時間升冪
  let streak = 0
  for (let i = sells.length - 1; i >= 0; i--) {
    const isLoss = sells[i].isLoss
    if (isLoss === true) streak++
    else if (isLoss === null) continue // 孤兒單：跳過，不中斷、不計數
    else break // isLoss === false：真的賺錢，連敗到此為止
  }
  return streak
}

export type StreakLevel = 'none' | 'amber' | 'red'

export interface StreakAlert {
  level: StreakLevel
  streak: number
  message: string
}

// 規格（C 包 3.）：連續 2 筆賣出且虧損 → amber「下一筆建議部位減半，冷靜期」；
// 連續 3 筆（含以上）→ red「建議暫停新倉 3 天，只處理既有持股」。
export function getStreakAlert(entries: JournalEntry[]): StreakAlert {
  const streak = getLossStreak(entries)
  if (streak >= 3) {
    return { level: 'red', streak, message: `連續 ${streak} 筆停損：建議暫停新倉 3 天，只處理既有持股` }
  }
  if (streak === 2) {
    return { level: 'amber', streak, message: '連續 2 筆停損：下一筆建議部位減半，冷靜期' }
  }
  return { level: 'none', streak, message: '' }
}

// ---------- 本週覆盤 ----------

export interface WeekRange {
  start: string // YYYY-MM-DD，週一
  end: string // YYYY-MM-DD，週日
  label: string // 顯示用「7/14 - 7/20」
}

// 週一為週首，用 Asia/Taipei 當地日期（跟 daily.json 的 date 字串同一套時區假設）。
export function getCurrentWeekRange(now: Date = new Date()): WeekRange {
  const taipei = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Taipei' }))
  const day = taipei.getDay() // 0=Sun..6=Sat
  const diffToMon = day === 0 ? -6 : 1 - day
  const monday = new Date(taipei)
  monday.setDate(taipei.getDate() + diffToMon)
  monday.setHours(0, 0, 0, 0)
  const sunday = new Date(monday)
  sunday.setDate(monday.getDate() + 6)
  const fmt = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  const label = `${monday.getMonth() + 1}/${monday.getDate()} - ${sunday.getMonth() + 1}/${sunday.getDate()}`
  return { start: fmt(monday), end: fmt(sunday), label }
}

export interface WeeklyReview {
  week: WeekRange
  count: number
  followedRatio: number | null // 0-1，count=0 時 null
  realizedPnl: number | null // 一筆都配不到對應買進時 null，畫面改顯示筆數就好（規格 2.）
  buyCount: number
  sellCount: number
  comment: string
}

export function getWeeklyReview(entries: JournalEntry[], now: Date = new Date()): WeeklyReview {
  const week = getCurrentWeekRange(now)
  const weekEntries = entries.filter((e) => e.date >= week.start && e.date <= week.end)
  const count = weekEntries.length
  const followedRatio = count > 0 ? weekEntries.filter((e) => e.followed_advice).length / count : null

  const weekSells = weekEntries.filter((e) => e.side === 'sell')
  const paired = pairSells(entries, weekSells) // 配對母體用完整日誌，買進可能在本週之前
  const computable = paired.filter((s) => s.pnlAmt != null)
  const realizedPnl = computable.length > 0 ? computable.reduce((sum, s) => sum + (s.pnlAmt as number), 0) : null

  const buyCount = weekEntries.filter((e) => e.side === 'buy').length
  const sellCount = weekSells.length

  let comment = ''
  if (count > 0) {
    if (followedRatio != null && followedRatio >= 0.8) comment = '紀律優秀'
    else if (followedRatio != null && followedRatio < 0.5) comment = '多數操作偏離建議——是建議不好用，還是手癢？'
    else comment = '紀律普通，持續留意'
  }

  return { week, count, followedRatio, realizedPnl, buyCount, sellCount, comment }
}
