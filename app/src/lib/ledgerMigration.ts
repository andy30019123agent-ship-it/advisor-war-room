// 舊資料 → 帳本 v2 遷移（規格 §6）。自動、無使用者流程、冪等。
//
// 關鍵不變量：**舊持股當期初部位，舊日誌只供覆盤。**
// 既有的 holdings 已經是「所有歷史買賣的結果」，若再把舊 journal 的買賣重播一次計入庫存，
// 同一批股票會被算兩次。所以 opening.date 設在遷移當日，早於它的交易事件在 derivePortfolio
// 裡不計入庫存與現金——但事件仍完整保留，連敗保護與週覆盤照樣讀得到歷史。
// 這就是為什麼砍掉「逐檔對帳畫面」也不會算錯。

import { loadHoldings, type Holding } from './holdings'
import { loadLegacyJournal, type JournalEntry } from './journal'
import {
  DEFAULT_LONG_TERM_IDS,
  DEFAULT_SETTINGS,
  calcFee,
  calcTax,
  emptyLedger,
  loadLedger,
  saveLedger,
  todayTaipei,
  type Ledger,
  type PositionTag,
  type TradeEvent,
} from './ledger'

export function journalToTrade(e: JournalEntry): TradeEvent {
  return {
    id: e.id,
    type: 'trade',
    date: e.date,
    created_at: e.created_at,
    stock_id: e.stock_id,
    name: e.name,
    side: e.side,
    price: e.price,
    qty: e.qty,
    // 舊日誌沒記費稅，依公式回填，讓歷史損益口徑跟新交易一致。
    fee: calcFee(e.price, e.qty, DEFAULT_SETTINGS),
    tax: calcTax(e.stock_id, e.side, e.price, e.qty),
    followed_advice: e.followed_advice,
    note: e.note,
    // 舊日誌一律標 legacy：期初部位已經是它們的結果，再計入庫存就是重複計算。
    legacy: true,
  }
}

export function buildLedgerFrom(
  holdings: Holding[],
  journal: JournalEntry[],
  date: string = todayTaipei()
): Ledger {
  const ledger = emptyLedger(date)
  ledger.opening.positions = holdings
    .filter((h) => h?.id && h.shares > 0)
    .map((h) => ({ stock_id: h.id, name: h.name || h.id, shares: h.shares, cost_price: h.costPrice }))
  ledger.events = journal.map(journalToTrade)

  // 長期標記：Andy 指定的 0050／2330，加上任何已在持股中的同代號。其餘一律 swing。
  const tags: Record<string, PositionTag> = {}
  for (const id of DEFAULT_LONG_TERM_IDS) tags[id] = 'long'
  ledger.tags = tags
  return ledger
}

/**
 * 首次載入時呼叫。已有 ledger:v2 就原樣回傳（冪等，不會二次遷移）。
 * 舊 key 一律不刪不改——出事時那是唯一的還原來源。
 */
export function ensureLedger(): Ledger {
  const existing = loadLedger()
  if (existing) return existing
  const ledger = buildLedgerFrom(loadHoldings(), loadLegacyJournal())
  saveLedger(ledger)
  return ledger
}
