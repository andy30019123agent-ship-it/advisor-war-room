// 個人化決策層（規格 §5）：把引擎給「一般持有者」的通用建議，換算成「以你的成本、你的
// 股數、你的曝險水位」為前提的一句可執行指令。
//
// 兩條不可違反的原則：
// 1. **只能收緊，不能放寬引擎風控。** 引擎說 exit/reduce 時，這裡不准因為使用者虧很多就改成
//    攤平；引擎說加碼時，這裡可以因曝險或冷靜期改成少買／不買。
// 2. **只讀結構化欄位運算**（position.tier_amount / position_delta / entry_condition.price /
//    defense_price / exposure_guidance），禁止解析 advice.plan 的中文字串來抓數字——那是
//    自由文字，拿正規表示式去撈必然在某天悄悄撈錯。

import { DEFAULT_SETTINGS, calcFee, type LedgerSettings } from './ledger.ts'
import type { StreakAlert } from './journal'
import type { Portfolio, Position } from './portfolio'
import type { ExposureGuidance, PrimaryDecision } from '../types/contract'

export type InstructionAction = 'sell' | 'hold' | 'buy' | 'wait'

export interface Instruction {
  instruction: string
  action: InstructionAction
  qty: number
  price: number | null
  ruleId: string
  reasons: string[]
  inputsUsed: Record<string, number | string>
  degraded: boolean
}

export interface AdviceInput {
  engine: PrimaryDecision | null | undefined
  position: Position | null
  price: number | null
  priceIsLive: boolean
  priceDate?: string | null
  portfolio: Portfolio
  guidance: ExposureGuidance | null | undefined
  streak: StreakAlert
  /** 組合層分配給這檔的減碼金額（元），由 allocatePortfolioRisk 統一計算 */
  allocation: number
  /** 目標資金規模（使用者設定），只用於集中度紅線與級距對照 */
  totalCapital: number
  /** 手續費設定，算加碼股數時要預留費用 */
  feeSettings?: LedgerSettings
}

// 單檔集中度紅線：單檔市值超過總資產這個比例就要求減碼（沿用既有 Holdings 頁的 40%）。
export const CONCENTRATION_LIMIT_PCT = 40
// 個人停損：成本 −8% 賣一半、−12% 全出。跟引擎防守價取「較高者」——兩道防線誰先到就先動。
const PERSONAL_STOP_RATIO = 0.92
const PERSONAL_DEEP_STOP_RATIO = 0.88
// 追價保護：現價高於引擎進場錨點超過這個比例就不追。
const CHASE_LIMIT_PCT = 5

// 台股撮合最小跳動單位。算出來的限價要落在合法檔位，不然是張不可能成交的單。
export function tickSize(price: number): number {
  if (price < 10) return 0.01
  if (price < 50) return 0.05
  if (price < 100) return 0.1
  if (price < 500) return 0.5
  if (price < 1000) return 1
  return 5
}

export function roundToTick(price: number): number {
  const t = tickSize(price)
  return Math.round(Math.round(price / t) * t * 100) / 100
}

function fmt(n: number): string {
  return Math.round(n).toLocaleString()
}

/**
 * 組合層減碼分配（規格 §5.3）。
 *
 * 為什麼要有這一層：曝險超標是「整個組合」的事。若讓每張持股卡各自算「要賣掉全部超額」，
 * 三檔各賣一份就砍掉三倍，使用者照做會直接砍過頭。所以超額只算一次，再依優先序分配到個股。
 *
 * 回傳 stock_id → 應減碼金額（元）。
 */
export function allocatePortfolioRisk(
  portfolio: Portfolio,
  guidance: ExposureGuidance | null | undefined,
  engineByStock: Record<string, PrimaryDecision | null | undefined> = {}
): Record<string, number> {
  const result: Record<string, number> = {}
  const { totalAssets, totalMarketValue } = portfolio
  if (!(totalAssets > 0)) return result

  // 有效曝險上限：最大持股比例與「100 − 最低現金比例」取嚴的那個。
  const allowedPct =
    guidance != null ? Math.min(guidance.max_equity_pct, 100 - guidance.min_cash_pct) : 100
  const allowedValue = (totalAssets * allowedPct) / 100
  let remaining = Math.max(0, totalMarketValue - allowedValue)

  // 分配優先序：引擎叫出場/減碼的先砍 → 波段部位 → 超集中 → 引擎信心低的 → 長期部位最後。
  const ranked = [...portfolio.positions].sort((a, b) => rank(a) - rank(b))
  function rank(p: Position): number {
    const e = engineByStock[p.stock_id]
    const delta = e?.position_delta
    if (delta === 'exit') return 0
    if (delta === 'reduce') return 1
    if (p.tag === 'swing') return 2 + (100 - (e?.confidence ?? 50)) / 1000
    return 5 // long：最後才動
  }

  for (const p of ranked) {
    const value = p.marketValue ?? p.avgCost * p.shares
    // 單檔集中度超額：這筆不受組合超額額度限制，是獨立的紅線。
    const concentrationExcess = Math.max(0, value - (totalAssets * CONCENTRATION_LIMIT_PCT) / 100)
    const fromPortfolio = remaining > 0 ? Math.min(remaining, value) : 0
    const take = Math.max(concentrationExcess, fromPortfolio)
    if (take > 0) {
      result[p.stock_id] = take
      remaining -= fromPortfolio
    }
  }
  return result
}

function degradedInstruction(input: AdviceInput, reason: string): Instruction {
  const defense = input.engine?.defense_price
  return {
    instruction: `暫不下單；${reason}，取得有效報價後再計算股數。${defense != null ? `引擎防守價為 ${defense} 元。` : ''}`,
    action: 'wait',
    qty: 0,
    price: null,
    ruleId: 'DATA_GATE',
    reasons: [reason],
    inputsUsed: { defense_price: defense ?? '—' },
    degraded: true,
  }
}

/**
 * 單檔個人化指令。規則由高到低優先，第一個命中的就是答案；被跳過的較低優先規則會寫進
 * reasons，讓「為什麼」展開時看得到是被誰覆寫的。
 */
export function personalInstruction(input: AdviceInput): Instruction {
  const { engine, position, price, portfolio, guidance, streak, allocation, totalCapital } = input
  const feeSettings = input.feeSettings ?? DEFAULT_SETTINGS

  // ── 0. 資料完整性閘門 ──────────────────────────────────────────
  // 缺現價就不產生可執行數量。禁止拿成本價冒充現價算單——那會生出一張永遠不會成交、
  // 或以錯誤價位成交的委託。
  if (!engine) return degradedInstruction(input, '目前拿不到這檔的引擎分析')
  if (price == null || !Number.isFinite(price) || price <= 0) {
    return degradedInstruction(input, '目前缺即時價')
  }

  const limitPrice = roundToTick(price)
  const shares = position?.shares ?? 0
  const value = shares * price
  const isLong = position?.tag === 'long'
  const priceNote = input.priceIsLive ? '' : `（依 ${input.priceDate ?? '最近'} 收盤價估算）`

  const base = {
    price: limitPrice,
    degraded: false,
    inputsUsed: {
      現價: limitPrice,
      持有股數: shares,
      平均成本: position ? Math.round(position.avgCost * 100) / 100 : '—',
      總曝險: portfolio.exposurePct != null ? `${portfolio.exposurePct.toFixed(1)}%` : '—',
      現金: Math.round(portfolio.cash),
      引擎方向: engine.position_delta,
      引擎防守價: engine.defense_price ?? '—',
      建議級距: engine.position.tier_amount,
    } as Record<string, number | string>,
  }

  // ── 1. 組合風控：曝險/集中度超標 ────────────────────────────────
  if (allocation > 0 && shares > 0) {
    const sellQty = Math.min(shares, Math.ceil(allocation / price))
    const afterPct =
      portfolio.totalAssets > 0
        ? ((portfolio.totalMarketValue - sellQty * price) / portfolio.totalAssets) * 100
        : null
    const overWeight = position?.weightPct != null && position.weightPct > CONCENTRATION_LIMIT_PCT
    return {
      ...base,
      instruction:
        `現價 ${limitPrice} 元，${overWeight ? `這檔佔總資產 ${position?.weightPct?.toFixed(1)}%，超過 ${CONCENTRATION_LIMIT_PCT}% 集中風險` : `總曝險 ${portfolio.exposurePct?.toFixed(1)}% 高於上限`}；` +
        `限價 ${limitPrice} 元賣出 ${fmt(sellQty)} 股${afterPct != null ? `，完成後組合曝險約降至 ${afterPct.toFixed(1)}%` : ''}。${priceNote}`,
      action: 'sell',
      qty: sellQty,
      ruleId: overWeight ? 'CONCENTRATION' : 'PORTFOLIO_OVEREXPOSURE',
      reasons: [
        `組合層分配給這檔的減碼金額 ${fmt(allocation)} 元`,
        isLong ? '長期部位排在減碼順序最後，仍被分配到代表其他部位已不夠減' : '波段部位優先減碼',
      ],
    }
  }

  // ── 2a. 引擎明確出場：**長期部位也要照做** ─────────────────────
  // 「只能收緊不能放寬」是雙向的：長期標記可以豁免我自己訂的成本停損線（那是我加的），
  // 但不能把引擎的 exit 改成續抱（那是引擎的風控）。否則只要把一檔標成長期，就等於
  // 關掉它的出場訊號——那是最危險的放寬。
  if (shares > 0 && position && engine.position_delta === 'exit') {
    return {
      ...base,
      instruction: `引擎已轉為出場；限價 ${limitPrice} 元賣出全部 ${fmt(shares)} 股。${isLong ? '（此為引擎風控，長期部位一樣適用）' : ''}${priceNote}`,
      action: 'sell',
      qty: shares,
      ruleId: 'ENGINE_EXIT',
      reasons: ['引擎 position_delta = exit，個人化層不得放寬引擎風控'],
    }
  }

  // ── 2b. 個人停損（只作用於波段部位）───────────────────────────
  // 長期部位（0050／2330）不吃這裡的成本停損——對定期定額部位喊「跌破防守價賣一半」是誤導。
  if (shares > 0 && position && !isLong) {
    const personalStop = position.avgCost * PERSONAL_STOP_RATIO
    const deepStop = position.avgCost * PERSONAL_DEEP_STOP_RATIO
    const effectiveStop = Math.max(engine.defense_price ?? 0, personalStop)
    if (price < deepStop) {
      return {
        ...base,
        instruction: `現價 ${limitPrice} 元低於成本停損線 ${Math.round(deepStop)} 元；限價 ${limitPrice} 元賣出全部 ${fmt(shares)} 股。${priceNote}`,
        action: 'sell',
        qty: shares,
        ruleId: 'DEEP_STOP',
        reasons: [`成本 ${Math.round(position.avgCost)} 元，深度停損線 ${Math.round(deepStop)} 元`],
      }
    }
    if (effectiveStop > 0 && price < effectiveStop) {
      const sellQty = Math.max(1, Math.floor(shares / 2))
      return {
        ...base,
        instruction: `成本 ${Math.round(position.avgCost)} 元、有效防守價 ${Math.round(effectiveStop)} 元，現價 ${limitPrice} 元已跌破；限價 ${limitPrice} 元賣出 ${fmt(sellQty)} 股（半數）。${priceNote}`,
        action: 'sell',
        qty: sellQty,
        ruleId: 'STOP_LOSS',
        reasons: [
          `有效防守價＝引擎防守價 ${engine.defense_price ?? '—'} 與成本 −8%（${Math.round(personalStop)}）取高`,
        ],
      }
    }
  }

  // ── 3. 減碼（只作用於波段部位）────────────────────────────────
  if (shares > 0 && !isLong && (engine.position_delta === 'reduce' || value > engine.position.tier_amount)) {
    const target = engine.position.tier_amount
    if (value > target) {
      const sellQty = Math.min(shares, Math.ceil((value - target) / price))
      return {
        ...base,
        instruction: `現價 ${limitPrice} 元，持股市值 ${fmt(value)} 元高於引擎建議級距 ${fmt(target)} 元；限價 ${limitPrice} 元賣出 ${fmt(sellQty)} 股，保留 ${fmt(shares - sellQty)} 股。${priceNote}`,
        action: 'sell',
        qty: sellQty,
        ruleId: 'ENGINE_REDUCE',
        reasons: [`引擎方向 ${engine.position_delta}，目標部位 ${fmt(target)} 元`],
      }
    }
    // 部位已經低於級距：不為了「減碼」兩個字繼續盲賣，降級為守價。
    const defense = engine.defense_price
    return {
      ...base,
      instruction: `目前 ${fmt(shares)} 股市值 ${fmt(value)} 元，已低於建議級距 ${fmt(target)} 元；先續抱、不再減碼${defense != null ? `，收盤跌破 ${defense} 元再賣出 ${fmt(Math.floor(shares / 2))} 股` : ''}。${priceNote}`,
      action: 'hold',
      qty: 0,
      ruleId: 'REDUCE_BUT_UNDER_TIER',
      reasons: ['引擎叫減碼，但實際部位已低於目標級距，盲賣只會讓部位更偏離'],
    }
  }

  // ── 4. 加碼／試單 ────────────────────────────────────────────
  if (engine.position_delta === 'increase' || engine.position_delta === 'small_entry') {
    const blockers: string[] = []
    if (guidance?.new_position === '禁止新增部位') blockers.push('引擎風控：禁止新增部位')
    // 有持股缺報價時，總市值是用成本估的——成本可能遠低於現價，曝險就被低估，
    // 依它算出的「曝險餘裕」會放行不該發生的加碼。寧可不買，也不要用不確定的水位下單。
    if (portfolio.missingPriceIds.length > 0) {
      blockers.push(`有 ${portfolio.missingPriceIds.length} 檔持股缺報價，目前曝險不確定`)
    }
    if (streak.level === 'red') blockers.push(`連續 ${streak.streak} 筆停損，冷靜期暫停新倉`)
    if (engine.defense_price != null && price < engine.defense_price) blockers.push('現價已跌破引擎防守價')
    const anchor = engine.entry_condition?.price ?? null
    if (anchor != null && price > anchor * (1 + CHASE_LIMIT_PCT / 100)) {
      blockers.push(`現價高於進場錨點 ${anchor} 元逾 ${CHASE_LIMIT_PCT}%`)
    }

    if (blockers.length > 0) {
      return {
        ...base,
        instruction: `今日不加碼（${blockers[0]}）；${shares > 0 ? `續抱現有 ${fmt(shares)} 股` : '維持空手'}。${priceNote}`,
        action: shares > 0 ? 'hold' : 'wait',
        qty: 0,
        ruleId: streak.level === 'red' ? 'STREAK_RED_BLOCK' : 'ADD_BLOCKED',
        reasons: blockers,
      }
    }

    const minCash = guidance != null ? (portfolio.totalAssets * guidance.min_cash_pct) / 100 : 0
    const allowedPct =
      guidance != null ? Math.min(guidance.max_equity_pct, 100 - guidance.min_cash_pct) : 100
    const budgets = [
      engine.position.tier_amount - value, // 距目標級距的缺口
      (portfolio.totalAssets * allowedPct) / 100 - portfolio.totalMarketValue, // 曝險餘裕
      portfolio.cash - minCash, // 可動用現金
      (portfolio.totalAssets * CONCENTRATION_LIMIT_PCT) / 100 - value, // 集中度餘裕
    ]
    let budget = Math.min(...budgets)
    if (guidance?.new_position === '僅限試單') budget = Math.min(budget, totalCapital * 0.1)

    // 預算要先扣掉手續費才換算股數。直接 floor(budget / price) 會把全部預算用光買股票，
    // 手續費就從「最低現金水位」那一格挖出去——完成後現金低於下限、曝險高於上限，
    // 等於這條規則自己違反了它剛剛檢查過的限制。小額單受最低 20 元影響更明顯。
    let buyQty = 0
    if (budget > 0) {
      const rough = Math.floor(budget / limitPrice)
      const fee = rough > 0 ? calcFee(limitPrice, rough, feeSettings) : 0
      buyQty = Math.max(0, Math.floor((budget - fee) / limitPrice))
    }
    const halved = streak.level === 'amber' && buyQty > 0
    if (halved) buyQty = Math.floor(buyQty / 2)

    if (buyQty <= 0) {
      const tightest = ['距目標級距已滿', '曝險已無餘裕', '可動用現金不足', '單檔集中度已滿'][
        budgets.indexOf(Math.min(...budgets))
      ]
      return {
        ...base,
        instruction: `引擎建議加碼，但你的水位不允許（${tightest}）；${shares > 0 ? `續抱現有 ${fmt(shares)} 股` : '維持空手'}。${priceNote}`,
        action: shares > 0 ? 'hold' : 'wait',
        qty: 0,
        ruleId: 'ADD_NO_BUDGET',
        reasons: [tightest, `可用預算 ${fmt(Math.max(0, budget))} 元`],
      }
    }

    return {
      ...base,
      instruction:
        (halved ? `連續 ${streak.streak} 筆停損，加碼數量減半：` : '') +
        `限價 ${limitPrice} 元買進 ${fmt(buyQty)} 股，加碼後總曝險約 ${(((portfolio.totalMarketValue + buyQty * limitPrice) / portfolio.totalAssets) * 100).toFixed(1)}%。${priceNote}`,
      action: 'buy',
      qty: buyQty,
      ruleId: halved ? 'ADD_HALVED_BY_STREAK' : 'ENGINE_ADD',
      reasons: [
        `預算取四者最小：級距缺口 / 曝險餘裕 / 可動用現金 / 集中度餘裕 → ${fmt(budget)} 元`,
        ...(guidance?.new_position === '僅限試單' ? ['引擎僅允許試單，已壓到總資金 10% 以內'] : []),
      ],
    }
  }

  // ── 5. 續抱／觀望：也要換算成你的股數，不能只丟一句抽象建議 ──────
  if (shares > 0) {
    const defense = engine.defense_price
    return {
      ...base,
      instruction:
        `續抱現有 ${fmt(shares)} 股，不加碼${defense != null && !isLong ? `；收盤跌破 ${defense} 元時賣出 ${fmt(Math.floor(shares / 2))} 股` : ''}。` +
        (isLong ? '（長期部位，不因短線跌破防守價賣出）' : '') +
        priceNote,
      action: 'hold',
      qty: 0,
      ruleId: isLong ? 'LONG_TERM_HOLD' : 'HOLD',
      reasons: [`引擎方向 ${engine.position_delta}`],
    }
  }

  return {
    ...base,
    instruction: `維持空手，等引擎給出進場條件${engine.entry_condition ? `（目前錨點 ${engine.entry_condition.price} 元：${engine.entry_condition.condition}）` : ''}。${priceNote}`,
    action: 'wait',
    qty: 0,
    ruleId: 'WAIT',
    reasons: [`引擎方向 ${engine.position_delta}`],
  }
}
