import { describe, expect, it } from 'vitest'
import { derivePortfolio } from './portfolio'
import { calcFee, calcTax, emptyLedger, tradeCashFlow, type Ledger, type TradeEvent } from './ledger'

function trade(over: Partial<TradeEvent> & Pick<TradeEvent, 'stock_id' | 'side' | 'price' | 'qty' | 'date'>): TradeEvent {
  return {
    id: over.id ?? `t_${over.date}_${over.stock_id}_${over.side}_${over.qty}`,
    type: 'trade',
    created_at: over.created_at ?? `${over.date}T09:00:00.000Z`,
    name: over.name ?? over.stock_id,
    fee: over.fee ?? calcFee(over.price, over.qty),
    tax: over.tax ?? calcTax(over.stock_id, over.side, over.price, over.qty),
    followed_advice: over.followed_advice ?? true,
    ...over,
  } as TradeEvent
}

function ledgerWith(events: TradeEvent[], over: Partial<Ledger> = {}): Ledger {
  const base = emptyLedger('2026-01-01')
  return { ...base, ...over, events, opening: { ...base.opening, ...(over.opening ?? {}) } }
}

describe('費稅公式', () => {
  it('手續費＝成交金額 × 0.1425% × 折扣，未達門檻收最低 20 元', () => {
    expect(calcFee(500, 1000)).toBe(Math.round(500 * 1000 * 0.001425 * 0.6)) // 428
    expect(calcFee(10, 100)).toBe(20) // 1,000 元成交 → 算出來不到 20，收最低
  })

  it('證交稅只有賣出收；ETF 0.1%、一般股 0.3%', () => {
    expect(calcTax('2330', 'buy', 1000, 1000)).toBe(0)
    expect(calcTax('2330', 'sell', 1000, 1000)).toBe(3000)
    expect(calcTax('0050', 'sell', 1000, 1000)).toBe(1000)
  })

  it('現金流：買進要多扣手續費，賣出要再扣稅', () => {
    const buy = trade({ stock_id: '2330', side: 'buy', price: 1000, qty: 1000, date: '2026-02-02' })
    const sell = trade({ stock_id: '2330', side: 'sell', price: 1000, qty: 1000, date: '2026-02-03' })
    expect(tradeCashFlow(buy)).toBe(-(1_000_000 + buy.fee))
    expect(tradeCashFlow(sell)).toBe(1_000_000 - sell.fee - sell.tax)
  })
})

describe('derivePortfolio 庫存與成本', () => {
  it('記一筆買進，持股就出現（舊系統的核心缺陷）', () => {
    const p = derivePortfolio(ledgerWith([trade({ stock_id: '2454', side: 'buy', price: 100, qty: 1000, date: '2026-02-01' })]))
    expect(p.positions).toHaveLength(1)
    expect(p.positions[0].shares).toBe(1000)
  })

  it('加碼後成本是加權平均，不是被最後一筆覆寫', () => {
    const p = derivePortfolio(
      ledgerWith([
        trade({ stock_id: '2454', side: 'buy', price: 100, qty: 1000, date: '2026-02-01', fee: 0 }),
        trade({ stock_id: '2454', side: 'buy', price: 200, qty: 1000, date: '2026-02-05', fee: 0 }),
      ])
    )
    expect(p.positions[0].shares).toBe(2000)
    expect(p.positions[0].avgCost).toBe(150)
  })

  it('買進手續費攤進每股成本', () => {
    const p = derivePortfolio(ledgerWith([trade({ stock_id: '2454', side: 'buy', price: 100, qty: 1000, date: '2026-02-01', fee: 100 })]))
    expect(p.positions[0].avgCost).toBeCloseTo(100.1, 6)
  })

  it('賣出減少股數；FIFO 先吃最舊的批次', () => {
    const p = derivePortfolio(
      ledgerWith([
        trade({ stock_id: '2454', side: 'buy', price: 100, qty: 1000, date: '2026-02-01', fee: 0 }),
        trade({ stock_id: '2454', side: 'buy', price: 200, qty: 1000, date: '2026-02-05', fee: 0 }),
        trade({ stock_id: '2454', side: 'sell', price: 300, qty: 1000, date: '2026-02-10', fee: 0, tax: 0 }),
      ])
    )
    expect(p.positions[0].shares).toBe(1000)
    expect(p.positions[0].avgCost).toBe(200) // 100 元那批被吃掉了，剩 200 元那批
    expect(p.positions[0].realizedPnl).toBe(200_000) // (300-100) × 1000
  })

  it('賣出的手續費與證交稅計入已實現損益', () => {
    const p = derivePortfolio(
      ledgerWith([
        trade({ stock_id: '2454', side: 'buy', price: 100, qty: 1000, date: '2026-02-01', fee: 0 }),
        trade({ stock_id: '2454', side: 'sell', price: 110, qty: 1000, date: '2026-02-10', fee: 94, tax: 330 }),
      ])
    )
    expect(p.realizedPnl).toBe(10_000 - 94 - 330)
  })

  it('清倉後持股卡片消失，但已實現損益留在總計', () => {
    const p = derivePortfolio(
      ledgerWith([
        trade({ stock_id: '2454', side: 'buy', price: 100, qty: 1000, date: '2026-02-01', fee: 0 }),
        trade({ stock_id: '2454', side: 'sell', price: 150, qty: 1000, date: '2026-02-10', fee: 0, tax: 0 }),
      ])
    )
    expect(p.positions).toHaveLength(0)
    expect(p.realizedPnl).toBe(50_000)
  })

  it('賣超庫存列為 issue，不靜默吞掉', () => {
    const p = derivePortfolio(
      ledgerWith([
        trade({ stock_id: '2454', side: 'buy', price: 100, qty: 1000, date: '2026-02-01' }),
        trade({ stock_id: '2454', side: 'sell', price: 150, qty: 3000, date: '2026-02-10' }),
      ])
    )
    expect(p.issues.some((i) => i.kind === 'oversell')).toBe(true)
  })

  it('補記一筆更早的交易後全量重播，結果跟一開始就按順序記一樣', () => {
    const a = trade({ stock_id: '2454', side: 'buy', price: 200, qty: 1000, date: '2026-02-05', fee: 0 })
    const b = trade({ stock_id: '2454', side: 'buy', price: 100, qty: 1000, date: '2026-02-01', fee: 0 })
    expect(derivePortfolio(ledgerWith([a, b])).positions[0].avgCost).toBe(
      derivePortfolio(ledgerWith([b, a])).positions[0].avgCost
    )
  })

  it('同一天多筆用 created_at 決勝，先買才賣得掉', () => {
    const p = derivePortfolio(
      ledgerWith([
        trade({ stock_id: '2454', side: 'sell', price: 150, qty: 1000, date: '2026-02-01', created_at: '2026-02-01T10:00:00Z', fee: 0, tax: 0 }),
        trade({ stock_id: '2454', side: 'buy', price: 100, qty: 1000, date: '2026-02-01', created_at: '2026-02-01T09:00:00Z', fee: 0 }),
      ])
    )
    expect(p.issues.some((i) => i.kind === 'oversell')).toBe(false)
    expect(p.realizedPnl).toBe(50_000)
  })

  it('重複 id 只算一次', () => {
    const dup = trade({ stock_id: '2454', side: 'buy', price: 100, qty: 1000, date: '2026-02-01', id: 'same' })
    expect(derivePortfolio(ledgerWith([dup, { ...dup }])).positions[0].shares).toBe(1000)
  })
})

describe('遷移切點：早於 opening.date 的交易只供覆盤', () => {
  it('期初部位已含舊交易結果，舊交易不再計入庫存（不重複計算）', () => {
    const l = ledgerWith(
      [trade({ stock_id: '2330', side: 'buy', price: 900, qty: 1000, date: '2025-12-01' })],
      { opening: { date: '2026-01-01', cash: 500_000, positions: [{ stock_id: '2330', name: '台積電', shares: 1000, cost_price: 900 }] } }
    )
    const p = derivePortfolio(l)
    expect(p.positions[0].shares).toBe(1000) // 不是 2000
    expect(p.cash).toBe(500_000) // 舊交易也不重複扣現金
  })

  it('遷移日之後的交易正常計入', () => {
    const l = ledgerWith(
      [trade({ stock_id: '2330', side: 'buy', price: 900, qty: 1000, date: '2026-02-01', fee: 0 })],
      { opening: { date: '2026-01-01', cash: 1_000_000, positions: [{ stock_id: '2330', name: '台積電', shares: 1000, cost_price: 900 }] } }
    )
    const p = derivePortfolio(l)
    expect(p.positions[0].shares).toBe(2000)
    expect(p.cash).toBe(100_000)
  })
})

describe('現金與曝險', () => {
  it('現金＝期初＋賣出淨收−買進總支出＋手動調整', () => {
    const l = ledgerWith(
      [
        trade({ stock_id: '2454', side: 'buy', price: 100, qty: 1000, date: '2026-02-01', fee: 0 }),
        { id: 'c1', type: 'cash_adjust', date: '2026-02-02', created_at: '2026-02-02T00:00:00Z', delta: 50_000 } as never,
      ],
      { opening: { date: '2026-01-01', cash: 300_000, positions: [] } }
    )
    expect(derivePortfolio(l).cash).toBe(300_000 - 100_000 + 50_000)
  })

  it('負現金列為 issue', () => {
    const l = ledgerWith([trade({ stock_id: '2454', side: 'buy', price: 100, qty: 1000, date: '2026-02-01' })], {
      opening: { date: '2026-01-01', cash: 0, positions: [] },
    })
    expect(derivePortfolio(l).issues.some((i) => i.kind === 'negative_cash')).toBe(true)
  })

  it('曝險分母是真實總資產（現金＋市值），不是手填的總資金', () => {
    const l = ledgerWith([trade({ stock_id: '2454', side: 'buy', price: 100, qty: 1000, date: '2026-02-01', fee: 0 })], {
      opening: { date: '2026-01-01', cash: 400_000, positions: [] },
    })
    const p = derivePortfolio(l, { '2454': 100 })
    expect(p.cash).toBe(300_000)
    expect(p.totalMarketValue).toBe(100_000)
    expect(p.exposurePct).toBeCloseTo(25, 6)
    expect(p.cashPct).toBeCloseTo(75, 6)
  })

  it('缺報價的部位：未實現損益整筆排除並回報，但曝險用成本估（寧可高估不要低估）', () => {
    const l = ledgerWith([
      trade({ stock_id: '2454', side: 'buy', price: 100, qty: 1000, date: '2026-02-01', fee: 0 }),
      trade({ stock_id: '3008', side: 'buy', price: 500, qty: 1000, date: '2026-02-01', fee: 0 }),
    ])
    const p = derivePortfolio(l, { '2454': 120 })
    expect(p.missingPriceIds).toEqual(['3008'])
    expect(p.unrealizedPnl).toBe(20_000) // 只算 2454
    expect(p.totalMarketValue).toBe(120_000 + 500_000) // 3008 用成本估
  })
})

describe('長期／波段標記', () => {
  it('0050、2330 預設是長期，其他預設波段', () => {
    const l = ledgerWith([
      trade({ stock_id: '0050', side: 'buy', price: 200, qty: 1000, date: '2026-02-01' }),
      trade({ stock_id: '2454', side: 'buy', price: 100, qty: 1000, date: '2026-02-01' }),
    ])
    const p = derivePortfolio(l)
    expect(p.positions.find((x) => x.stock_id === '0050')?.tag).toBe('long')
    expect(p.positions.find((x) => x.stock_id === '2454')?.tag).toBe('swing')
  })
})
