import { describe, expect, it } from 'vitest'
import { allocatePortfolioRisk, personalInstruction, roundToTick, type AdviceInput } from './personalAdvice'
import type { Portfolio, Position } from './portfolio'
import type { StreakAlert } from './journal'
import type { ExposureGuidance, PrimaryDecision } from '../types/contract'

function pos(over: Partial<Position> = {}): Position {
  const shares = over.shares ?? 1000
  const avgCost = over.avgCost ?? 100
  return {
    stock_id: '2454',
    name: '聯發科',
    tag: 'swing',
    shares,
    avgCost,
    openLots: [{ date: '2026-02-01', price: avgCost, remaining: shares }],
    realizedPnl: 0,
    marketValue: shares * avgCost,
    unrealizedPnl: 0,
    weightPct: 10,
    ...over,
  }
}

function portfolio(over: Partial<Portfolio> = {}): Portfolio {
  return {
    positions: [],
    cash: 500_000,
    totalMarketValue: 500_000,
    totalAssets: 1_000_000,
    unrealizedPnl: 0,
    realizedPnl: 0,
    exposurePct: 50,
    cashPct: 50,
    missingPriceIds: [],
    issues: [],
    ...over,
  }
}

function engine(over: Partial<PrimaryDecision> = {}): PrimaryDecision {
  return {
    action: '持有',
    stance: '中性',
    position_delta: 'hold',
    confidence: 60,
    decided_by_layer: 3,
    reason_codes: [],
    readable_reason: '',
    risk_note: '',
    position: { tier_amount: 200_000, lots: 2, odd_shares: 0 },
    defense_price: 90,
    entry_condition: null,
    reeval_date: '2026-03-01',
    ...over,
  } as PrimaryDecision
}

const guidance: ExposureGuidance = {
  risk_temp: 50,
  max_equity_pct: 60,
  min_cash_pct: 20,
  new_position: '可正常布局',
  note: '',
}

const noStreak: StreakAlert = { level: 'none', streak: 0, message: '' }

function input(over: Partial<AdviceInput> = {}): AdviceInput {
  return {
    engine: engine(),
    position: pos(),
    price: 100,
    priceIsLive: true,
    portfolio: portfolio(),
    guidance,
    streak: noStreak,
    allocation: 0,
    totalCapital: 1_000_000,
    ...over,
  }
}

describe('台股檔位', () => {
  it('限價落在合法跳動單位', () => {
    expect(roundToTick(93.33)).toBe(93.3 + 0) // 50~100 → 0.1
    expect(roundToTick(1003)).toBe(1005) // >=1000 → 5
    expect(roundToTick(123.4)).toBe(123.5) // 100~500 → 0.5
  })
})

describe('0. 資料完整性閘門', () => {
  it('缺即時價時不產生可執行數量', () => {
    const r = personalInstruction(input({ price: null }))
    expect(r.degraded).toBe(true)
    expect(r.qty).toBe(0)
    expect(r.action).toBe('wait')
    expect(r.instruction).toContain('暫不下單')
  })

  it('缺引擎分析時同樣降級，不亂編數量', () => {
    expect(personalInstruction(input({ engine: null })).degraded).toBe(true)
  })
})

describe('1. 組合風控優先於一切建議', () => {
  it('曝險超標時要求賣出，數量由組合層分配額換算', () => {
    const r = personalInstruction(input({ allocation: 100_000, engine: engine({ position_delta: 'increase' }) }))
    expect(r.action).toBe('sell')
    expect(r.qty).toBe(1000) // 100,000 / 100
    expect(r.ruleId).toBe('PORTFOLIO_OVEREXPOSURE')
  })

  it('風控壓過引擎的加碼建議（只能收緊不能放寬）', () => {
    const r = personalInstruction(input({ allocation: 50_000, engine: engine({ position_delta: 'increase' }) }))
    expect(r.action).not.toBe('buy')
  })

  it('賣出數量不會超過實際持股', () => {
    const r = personalInstruction(input({ allocation: 999_999_999 }))
    expect(r.qty).toBe(1000)
  })
})

describe('2. 停損只作用於波段部位', () => {
  it('跌破有效防守價賣一半', () => {
    const r = personalInstruction(input({ price: 89, position: pos({ avgCost: 100 }) }))
    expect(r.action).toBe('sell')
    expect(r.qty).toBe(500)
    expect(r.ruleId).toBe('STOP_LOSS')
  })

  it('跌破成本 −12% 全部出場', () => {
    const r = personalInstruction(input({ price: 87, position: pos({ avgCost: 100 }) }))
    expect(r.qty).toBe(1000)
    expect(r.ruleId).toBe('DEEP_STOP')
  })

  it('長期部位（0050／2330）不會被叫去停損', () => {
    const r = personalInstruction(
      input({ price: 80, position: pos({ stock_id: '0050', name: '元大台灣50', tag: 'long', avgCost: 100 }) })
    )
    expect(r.action).not.toBe('sell')
    expect(r.ruleId).toBe('LONG_TERM_HOLD')
  })

  it('有效防守價＝引擎防守價與成本 −8% 取高', () => {
    // 成本 200 → 個人停損 184、深度停損 176，兩者都高於引擎防守價 90。
    // 現價 180：低於 184 觸發半數停損，但還沒到 176，不該全出。
    const r = personalInstruction(input({ price: 180, position: pos({ avgCost: 200 }), engine: engine({ defense_price: 90 }) }))
    expect(r.ruleId).toBe('STOP_LOSS')
    expect(r.qty).toBe(500)
    // 190 還在 184 之上，不該觸發
    expect(personalInstruction(input({ price: 190, position: pos({ avgCost: 200 }), engine: engine({ defense_price: 90 }) })).action).not.toBe('sell')
  })
})

describe('3. 減碼', () => {
  it('市值高於建議級距時賣掉超出的部分', () => {
    const r = personalInstruction(
      input({
        price: 100,
        position: pos({ shares: 3000, avgCost: 100 }),
        engine: engine({ position_delta: 'reduce', position: { tier_amount: 200_000, lots: 2, odd_shares: 0 } }),
      })
    )
    expect(r.action).toBe('sell')
    expect(r.qty).toBe(1000) // (300,000 − 200,000) / 100
  })

  it('部位已低於級距時不盲賣，降級為守價', () => {
    const r = personalInstruction(
      input({
        price: 100,
        position: pos({ shares: 1000, avgCost: 100 }),
        engine: engine({ position_delta: 'reduce', position: { tier_amount: 200_000, lots: 2, odd_shares: 0 } }),
      })
    )
    expect(r.action).toBe('hold')
    expect(r.qty).toBe(0)
    expect(r.ruleId).toBe('REDUCE_BUT_UNDER_TIER')
  })
})

describe('4. 加碼與連敗保護', () => {
  const addEngine = engine({ position_delta: 'increase', defense_price: 50 })

  it('正常情況下算得出可買股數', () => {
    const r = personalInstruction(input({ engine: addEngine, position: pos({ shares: 500 }) }))
    expect(r.action).toBe('buy')
    expect(r.qty).toBeGreaterThan(0)
  })

  it('連敗 red：加碼壓成 0 股，不是只貼橫幅', () => {
    const r = personalInstruction(
      input({ engine: addEngine, streak: { level: 'red', streak: 3, message: '' } })
    )
    expect(r.qty).toBe(0)
    expect(r.ruleId).toBe('STREAK_RED_BLOCK')
  })

  it('連敗 amber：數量真的減半', () => {
    const full = personalInstruction(input({ engine: addEngine, position: pos({ shares: 500 }) }))
    const half = personalInstruction(
      input({ engine: addEngine, position: pos({ shares: 500 }), streak: { level: 'amber', streak: 2, message: '' } })
    )
    expect(half.qty).toBe(Math.floor(full.qty / 2))
    expect(half.ruleId).toBe('ADD_HALVED_BY_STREAK')
  })

  it('引擎禁止新增部位時不加碼', () => {
    const r = personalInstruction(
      input({ engine: addEngine, guidance: { ...guidance, new_position: '禁止新增部位' } })
    )
    expect(r.qty).toBe(0)
  })

  it('現價高於進場錨點太多就不追價', () => {
    const r = personalInstruction(
      input({
        price: 108,
        engine: engine({ position_delta: 'increase', defense_price: 50, entry_condition: { price: 100, condition: '回測月線' } }),
      })
    )
    expect(r.action).not.toBe('buy')
    expect(r.reasons.join()).toContain('進場錨點')
  })

  it('現金不足以維持最低水位時不加碼', () => {
    const r = personalInstruction(
      input({ engine: addEngine, portfolio: portfolio({ cash: 0, totalMarketValue: 1_000_000, totalAssets: 1_000_000 }) })
    )
    expect(r.qty).toBe(0)
    expect(r.ruleId).toBe('ADD_NO_BUDGET')
  })
})

describe('5. 續抱也要量化成你的股數', () => {
  it('續抱會講出實際股數與觸發價', () => {
    const r = personalInstruction(input({ engine: engine({ position_delta: 'hold' }) }))
    expect(r.instruction).toContain('1,000 股')
    expect(r.instruction).toContain('90')
  })

  it('空手時給觀望，不給數量', () => {
    const r = personalInstruction(input({ position: null, engine: engine({ position_delta: 'wait' }) }))
    expect(r.action).toBe('wait')
    expect(r.qty).toBe(0)
  })
})

describe('組合層減碼分配', () => {
  const a = pos({ stock_id: 'A', shares: 1000, avgCost: 300, marketValue: 300_000, weightPct: 30 })
  const b = pos({ stock_id: 'B', shares: 1000, avgCost: 300, marketValue: 300_000, weightPct: 30 })
  const p = portfolio({ positions: [a, b], cash: 200_000, totalMarketValue: 600_000, totalAssets: 800_000 })

  it('超額只分配一次，加總等於所需減碼額（不會每檔各砍一份）', () => {
    const alloc = allocatePortfolioRisk(p, guidance)
    const required = 600_000 - 800_000 * 0.6 // 上限 min(60, 100−20)=60% → 480,000
    const sum = Object.values(alloc).reduce((s, v) => s + v, 0)
    expect(sum).toBeCloseTo(required, 6)
  })

  it('引擎叫出場的先被分配', () => {
    const alloc = allocatePortfolioRisk(p, guidance, { B: engine({ position_delta: 'exit' }) })
    expect(alloc.B).toBeGreaterThan(0)
    expect(alloc.A ?? 0).toBe(0)
  })

  it('長期部位排最後', () => {
    const longA = { ...a, tag: 'long' as const }
    const alloc = allocatePortfolioRisk({ ...p, positions: [longA, b] }, guidance)
    expect(alloc.B).toBeGreaterThan(0)
    expect(alloc.A ?? 0).toBe(0)
  })

  it('沒超標就不叫人賣', () => {
    const safe = portfolio({ positions: [a], cash: 700_000, totalMarketValue: 300_000, totalAssets: 1_000_000 })
    expect(Object.keys(allocatePortfolioRisk(safe, guidance))).toHaveLength(0)
  })

  it('單檔集中度超過 40% 即使組合沒超標也要減碼', () => {
    const big = pos({ stock_id: 'C', shares: 1000, avgCost: 500, marketValue: 500_000, weightPct: 50 })
    const safe = portfolio({ positions: [big], cash: 500_000, totalMarketValue: 500_000, totalAssets: 1_000_000 })
    const alloc = allocatePortfolioRisk(safe, { ...guidance, max_equity_pct: 100, min_cash_pct: 0 })
    expect(alloc.C).toBeCloseTo(100_000, 6) // 50% − 40% = 10% × 100 萬
  })
})
