import { describe, expect, it } from 'vitest'
import { buildLedgerFrom } from './ledgerMigration'
import { derivePortfolio } from './portfolio'
import type { Holding } from './holdings'
import type { JournalEntry } from './journal'

const holdings: Holding[] = [
  { id: '2330', name: '台積電', shares: 1000, costPrice: 900 },
  { id: '2454', name: '聯發科', shares: 2000, costPrice: 1200 },
]

const journal: JournalEntry[] = [
  {
    id: 'j1',
    date: '2026-06-01',
    stock_id: '2330',
    name: '台積電',
    side: 'buy',
    price: 900,
    qty: 1000,
    followed_advice: true,
    created_at: '2026-06-01T01:00:00.000Z',
  },
]

describe('遷移', () => {
  it('舊持股變期初部位、舊日誌只供覆盤，庫存不重複計算', () => {
    const l = buildLedgerFrom(holdings, journal, '2026-07-23')
    const p = derivePortfolio(l)
    expect(p.positions.find((x) => x.stock_id === '2330')?.shares).toBe(1000) // 不是 2000
    expect(l.events).toHaveLength(1) // 歷史仍完整保留給連敗保護／週覆盤
  })

  it('遷移日之後才記的交易正常計入庫存', () => {
    const l = buildLedgerFrom(holdings, journal, '2026-07-23')
    l.events.push({
      id: 'j2',
      type: 'trade',
      date: '2026-07-24',
      created_at: '2026-07-24T01:00:00.000Z',
      stock_id: '2330',
      name: '台積電',
      side: 'buy',
      price: 1000,
      qty: 1000,
      fee: 0,
      tax: 0,
      followed_advice: true,
    })
    expect(derivePortfolio(l).positions.find((x) => x.stock_id === '2330')?.shares).toBe(2000)
  })

  it('0050／2330 預設標長期，其他標波段', () => {
    const l = buildLedgerFrom(holdings, [], '2026-07-23')
    expect(l.tags['2330']).toBe('long')
    expect(l.tags['0050']).toBe('long')
    expect(l.tags['2454']).toBeUndefined() // 取值時預設 swing
    expect(derivePortfolio(l).positions.find((x) => x.stock_id === '2454')?.tag).toBe('swing')
  })

  it('期初現金為 0（不猜金額），由使用者自己填', () => {
    expect(buildLedgerFrom(holdings, [], '2026-07-23').opening.cash).toBe(0)
  })

  it('股數為 0 或缺代號的舊持股不會帶進來', () => {
    const l = buildLedgerFrom(
      [...holdings, { id: '', name: '壞資料', shares: 100, costPrice: 10 }, { id: '3008', name: '大立光', shares: 0, costPrice: 2000 }],
      [],
      '2026-07-23'
    )
    expect(l.opening.positions).toHaveLength(2)
  })

  it('舊日誌沒記費稅，遷移時依公式回填', () => {
    const l = buildLedgerFrom([], journal, '2026-07-23')
    expect(l.events[0].type === 'trade' && l.events[0].fee).toBeGreaterThan(0)
  })

  it('兩份舊資料都空 → 建出乾淨的空帳本', () => {
    const l = buildLedgerFrom([], [], '2026-07-23')
    expect(derivePortfolio(l).positions).toHaveLength(0)
    expect(derivePortfolio(l).issues).toHaveLength(0)
  })
})
