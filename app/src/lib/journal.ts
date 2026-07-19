// 交易日誌（C 包・勝率行為閉環，契約 v1.5「App 行為」節）：使用者自行記錄的買賣紀錄，
// 全存 localStorage（不進資料契約檔案）。用途是把「模型的建議對不對」跟「使用者有沒有
// 照建議操作」拆開看——覆盤時才分得清是模型錯還是自己手癢，同時用連續停損偵測擋散戶
// 加碼攤平／報復性交易的自毀行為。

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

const STORAGE_KEY = 'advisor-war-room:journal'

export function loadJournal(): JournalEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
  } catch {
    return []
  }
}

function persist(entries: JournalEntry[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(entries))
}

export function genJournalId(): string {
  return `j_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

export function saveJournalEntry(entry: JournalEntry): JournalEntry[] {
  const current = loadJournal()
  const idx = current.findIndex((e) => e.id === entry.id)
  const next = idx >= 0 ? [...current] : [...current, entry]
  if (idx >= 0) next[idx] = entry
  persist(next)
  return next
}

export function deleteJournalEntry(id: string): JournalEntry[] {
  const next = loadJournal().filter((e) => e.id !== id)
  persist(next)
  return next
}

// 排序 key：date 優先，同天用 created_at 決勝，確保「連續停損」判定跟畫面顯示的
// 時間順序一致，不受使用者輸入順序或 localStorage 陣列順序影響。
function sortKey(e: JournalEntry): string {
  return `${e.date}T${e.created_at}`
}

export function sortedByTime(entries: JournalEntry[]): JournalEntry[] {
  return [...entries].sort((a, b) => (sortKey(a) < sortKey(b) ? -1 : sortKey(a) > sortKey(b) ? 1 : 0))
}

// 幫一筆賣出配對「對應買進」：同代號、成交時間在這筆賣出（含同天但 created_at 較早）
// 之前，取時間上最近的一筆買進。這是簡化配對（不是嚴格 FIFO 庫存追蹤），找不到就回
// null，代表這筆賣出的損益無法判斷（例如日誌只補記了賣出、沒有補買進成本）。
export function findMatchingBuy(allEntries: JournalEntry[], sell: JournalEntry): JournalEntry | null {
  const buys = sortedByTime(allEntries.filter((e) => e.stock_id === sell.stock_id && e.side === 'buy'))
  const before = buys.filter((b) => sortKey(b) <= sortKey(sell))
  return before.length > 0 ? before[before.length - 1] : null
}

export interface SellWithPnl {
  sell: JournalEntry
  buy: JournalEntry | null
  isLoss: boolean | null // null＝配不到對應買進，無法判斷盈虧
  pnlAmt: number | null
}

// allEntries：拿來配對買進的完整母體（可以包含週期範圍外的買進）。
// sellsSubset：要計算的賣出子集，預設＝allEntries 裡全部的賣出。
export function pairSells(allEntries: JournalEntry[], sellsSubset?: JournalEntry[]): SellWithPnl[] {
  const sells = sortedByTime(sellsSubset ?? allEntries.filter((e) => e.side === 'sell'))
  return sells.map((sell) => {
    const buy = findMatchingBuy(allEntries, sell)
    if (!buy) return { sell, buy: null, isLoss: null, pnlAmt: null }
    return { sell, buy, isLoss: sell.price < buy.price, pnlAmt: (sell.price - buy.price) * sell.qty }
  })
}

// ---------- 連敗保護 ----------

// 連續停損筆數：從時間序最新的賣出往回數，遇到「配對得到買進且虧損」的賣出就繼續數；
// 配不到對應買進（isLoss=null）視為中斷——資料不全時無法確認虧損，保守起見不算進連
// 敗，但也不能假裝沒事繼續往前數，直接中斷計數。
export function getLossStreak(entries: JournalEntry[]): number {
  const sells = pairSells(entries) // 已經是時間升冪
  let streak = 0
  for (let i = sells.length - 1; i >= 0; i--) {
    if (sells[i].isLoss === true) streak++
    else break
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
