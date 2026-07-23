// 持倉投影（規格 §4）：把帳本事件重播成「現在的持股、成本、現金、曝險」。
// 純函式、無副作用、不碰 localStorage——所以可以完整單元測試，也是整個帳本制的核心。

import {
  getTag,
  tradeCashFlow,
  type Ledger,
  type LedgerEvent,
  type PositionTag,
  type TradeEvent,
} from './ledger'

export interface Lot {
  date: string
  price: number // 每股成本（已含買進手續費攤分）
  remaining: number
}

export interface Position {
  stock_id: string
  name: string
  tag: PositionTag
  shares: number
  avgCost: number // 剩餘未平倉 lots 的加權平均成本
  openLots: Lot[]
  realizedPnl: number
  marketValue: number | null
  unrealizedPnl: number | null
  weightPct: number | null // 佔總資產
}

export type IssueKind = 'oversell' | 'negative_cash' | 'duplicate_id' | 'bad_data'

export interface ReconciliationIssue {
  kind: IssueKind
  stock_id?: string
  message: string
}

export interface Portfolio {
  positions: Position[]
  cash: number
  totalMarketValue: number
  totalAssets: number
  unrealizedPnl: number | null
  realizedPnl: number
  exposurePct: number | null
  cashPct: number | null
  missingPriceIds: string[]
  issues: ReconciliationIssue[]
}

export type QuoteMap = Record<string, number | null | undefined>

// 排序：date 升冪，同日用 created_at 決勝。沿用 journal.ts 既有語意，確保「連續停損」
// 判定跟畫面顯示的時間順序一致，不受使用者輸入順序或陣列順序影響。
function sortKey(e: LedgerEvent): string {
  return `${e.date}T${e.created_at}`
}

export function sortEvents<T extends LedgerEvent>(events: T[]): T[] {
  return [...events].sort((a, b) => (sortKey(a) < sortKey(b) ? -1 : sortKey(a) > sortKey(b) ? 1 : 0))
}

function isValidTrade(e: TradeEvent): boolean {
  return (
    !!e.stock_id &&
    (e.side === 'buy' || e.side === 'sell') &&
    Number.isFinite(e.price) &&
    Number.isFinite(e.qty) &&
    e.price > 0 &&
    e.qty > 0
  )
}

export function derivePortfolio(ledger: Ledger, quotes: QuoteMap = {}): Portfolio {
  const issues: ReconciliationIssue[] = []
  const lotsById = new Map<string, Lot[]>()
  const nameById = new Map<string, string>()
  const realizedById = new Map<string, number>()

  // 期初部位：當成日期 = opening.date、排在所有事件之前的一筆 lot。
  for (const p of ledger.opening.positions) {
    if (!p?.stock_id || !(p.shares > 0)) {
      issues.push({ kind: 'bad_data', stock_id: p?.stock_id, message: `期初部位資料不完整，已略過：${p?.stock_id ?? '(無代號)'}` })
      continue
    }
    lotsById.set(p.stock_id, [{ date: ledger.opening.date, price: p.cost_price, remaining: p.shares }])
    nameById.set(p.stock_id, p.name || p.stock_id)
  }

  let cash = Number(ledger.opening.cash) || 0

  const seenIds = new Set<string>()
  for (const e of sortEvents(ledger.events)) {
    if (seenIds.has(e.id)) {
      issues.push({ kind: 'duplicate_id', message: `重複的事件 id ${e.id}，已略過重複的那筆` })
      continue
    }
    seenIds.add(e.id)

    if (e.type === 'cash_adjust') {
      if (Number.isFinite(e.delta)) cash += e.delta
      continue
    }

    if (!isValidTrade(e)) {
      issues.push({ kind: 'bad_data', stock_id: e.stock_id, message: `交易資料不完整，已略過：${e.date} ${e.stock_id}` })
      continue
    }

    // 遷移進來的舊交易只供覆盤（連敗保護、週覆盤），不計入庫存與現金——期初部位／期初
    // 現金已經包含了它們的結果，再算一次就是重複計算。這是「不做對帳畫面也不會算錯」的保證。
    // 用 legacy 旗標而非日期比較：遷移當天（或未來日期）的舊日誌用日期擋不掉。
    if (e.legacy || e.date < ledger.opening.date) {
      nameById.set(e.stock_id, e.name || nameById.get(e.stock_id) || e.stock_id)
      continue
    }

    nameById.set(e.stock_id, e.name || nameById.get(e.stock_id) || e.stock_id)

    const lots = lotsById.get(e.stock_id) ?? []
    if (e.side === 'buy') {
      cash += tradeCashFlow(e)
      // 手續費攤進每股成本，這樣 avgCost 跟券商 App 的成本才對得起來。
      lots.push({ date: e.date, price: (e.price * e.qty + e.fee) / e.qty, remaining: e.qty })
      lotsById.set(e.stock_id, lots)
      continue
    }

    // 賣出：FIFO 消耗最舊的批次。賣超庫存的部分記為 issue，不靜默吞掉。
    let need = e.qty
    let realized = 0
    while (need > 0 && lots.length > 0) {
      const lot = lots[0]
      const take = Math.min(need, lot.remaining)
      realized += (e.price - lot.price) * take
      lot.remaining -= take
      need -= take
      if (lot.remaining <= 0) lots.shift()
    }
    const matchedQty = e.qty - need

    // 賣超時只認「真的有庫存可賣」的那部分現金與費稅。全額入帳會憑空生出現金，
    // 那筆假現金會被加碼規則當成可動用資金，直接叫使用者拿不存在的錢去買股票——
    // 只顯示 issue 擋不住它。寧可少認，也不要讓錯誤的錢流進決策。
    const ratio = e.qty > 0 ? matchedQty / e.qty : 0
    const feeShare = e.fee * ratio
    const taxShare = e.tax * ratio
    cash += e.price * matchedQty - feeShare - taxShare

    // 賣出成本（手續費＋證交稅）計入已實現損益，才是真的口袋差額。
    realized -= feeShare + taxShare
    realizedById.set(e.stock_id, (realizedById.get(e.stock_id) ?? 0) + realized)
    lotsById.set(e.stock_id, lots)
    if (need > 0) {
      issues.push({
        kind: 'oversell',
        stock_id: e.stock_id,
        message: `${e.date} ${nameById.get(e.stock_id) ?? e.stock_id} 賣出 ${e.qty} 股，超過當時庫存 ${e.qty - need} 股——請補記買進紀錄`,
      })
    }
  }

  if (cash < 0) {
    issues.push({ kind: 'negative_cash', message: `現金餘額為負（${Math.round(cash).toLocaleString()} 元）——請確認期初現金或補記入金` })
  }

  const missingPriceIds: string[] = []
  const positions: Position[] = []
  for (const [stockId, lots] of lotsById) {
    const shares = lots.reduce((s, l) => s + l.remaining, 0)
    const realizedPnl = realizedById.get(stockId) ?? 0
    if (shares <= 0) continue // 清倉：卡片自動消失，不留空殼

    const costTotal = lots.reduce((s, l) => s + l.price * l.remaining, 0)
    const price = quotes[stockId]
    const hasPrice = typeof price === 'number' && Number.isFinite(price) && price > 0
    if (!hasPrice) missingPriceIds.push(stockId)

    positions.push({
      stock_id: stockId,
      name: nameById.get(stockId) ?? stockId,
      tag: getTag(ledger, stockId),
      shares,
      avgCost: costTotal / shares,
      openLots: lots,
      realizedPnl,
      marketValue: hasPrice ? price * shares : null,
      unrealizedPnl: hasPrice ? (price - costTotal / shares) * shares : null,
      weightPct: null, // 需要總資產，下面補
    })
  }

  // 已清倉但有已實現損益的標的：不進 positions（沒有卡片可顯示），但損益要進總計。
  let realizedPnl = 0
  for (const v of realizedById.values()) realizedPnl += v

  // 缺報價的部位用「成本」估市值：曝險寧可高估也不要低估成 0（低估會讓風控放行不該放行的加碼）。
  const totalMarketValue = positions.reduce(
    (s, p) => s + (p.marketValue ?? p.avgCost * p.shares),
    0
  )
  const totalAssets = cash + totalMarketValue

  // 未實現損益：只計「確定有現價」的部位。缺價的整筆排除並在 UI 標註——沿用成本價當現價
  // 等於默默假設它損益 0，會把總損益算錯又不吭聲。
  const priced = positions.filter((p) => p.unrealizedPnl != null)
  const unrealizedPnl = priced.length > 0 ? priced.reduce((s, p) => s + (p.unrealizedPnl as number), 0) : null

  for (const p of positions) {
    p.weightPct = totalAssets > 0 ? ((p.marketValue ?? p.avgCost * p.shares) / totalAssets) * 100 : null
  }

  return {
    positions: positions.sort((a, b) => (b.marketValue ?? 0) - (a.marketValue ?? 0)),
    cash,
    totalMarketValue,
    totalAssets,
    unrealizedPnl,
    realizedPnl,
    exposurePct: totalAssets > 0 ? (totalMarketValue / totalAssets) * 100 : null,
    cashPct: totalAssets > 0 ? (cash / totalAssets) * 100 : null,
    missingPriceIds,
    issues,
  }
}
