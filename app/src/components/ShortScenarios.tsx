import type { ShortScenario, ShortScenarios as ShortScenariosData } from '../types/contract'

// 短線推演（1-4 週）三劇本卡（契約 v1.4 short_scenarios）。取代扇形圖當查股票頁主角——
// 扇形圖降級成收合區塊，見 ForecastFan.tsx。

const BULLISH_VERBS = ['反彈', '站上', '挑戰', '突破', '回升', '走升', '轉強', '守住']
const BEARISH_VERBS = ['下探', '跌破', '回測', '破底', '探底', '走弱', '轉弱']

type PathChip = {
  number: string
  verb: string | null
  sentiment: 'up' | 'down' | null
  rest: string
}

// 把 price_path_text（例："2,290 → 回測 2,107（防守價）→ 反彈 2,324（MA60）震盪"）
// 拆成一串 chip：每個 → 分隔的片段各自抽出數字、方向動詞（跟著語意色）、其餘備註文字。
function parsePricePathText(text: string): PathChip[] {
  return text
    .split('→')
    .map((raw) => raw.trim())
    .filter(Boolean)
    .map((seg) => {
      const numMatch = seg.match(/[\d,]+(\.\d+)?/)
      const number = numMatch ? numMatch[0] : seg
      let verb: string | null = null
      let sentiment: 'up' | 'down' | null = null
      for (const v of BULLISH_VERBS) {
        if (seg.includes(v)) {
          verb = v
          sentiment = 'up'
          break
        }
      }
      if (!verb) {
        for (const v of BEARISH_VERBS) {
          if (seg.includes(v)) {
            verb = v
            sentiment = 'down'
            break
          }
        }
      }
      let rest = seg
      if (numMatch) rest = rest.replace(numMatch[0], '')
      if (verb) rest = rest.replace(verb, '')
      return { number, verb, sentiment, rest: rest.trim() }
    })
}

function ScenarioPricePath({ text }: { text: string }) {
  const chips = parsePricePathText(text)
  return (
    <div className="scenario-path">
      {chips.map((chip, i) => (
        <span className="scenario-path-item" key={i}>
          {i > 0 && <span className="scenario-arrow">→</span>}
          {chip.verb && (
            <span className={`scenario-verb ${chip.sentiment === 'up' ? 'up' : chip.sentiment === 'down' ? 'down' : ''}`}>
              {chip.verb}
            </span>
          )}
          <span className="scenario-chip mono">{chip.number}</span>
          {chip.rest && <span className="scenario-chip-note">{chip.rest}</span>}
        </span>
      ))}
    </div>
  )
}

// 在 trigger 文字裡找到的第一個價位後面，插入該價位距現價的漲跌幅（例：
// 「收盤跌破 2,107（防守價）」→「收盤跌破 2,107（防守價，-8.0%）」）；沒有現價或抓不到
// 數字時原樣輸出，不硬湊。
function ScenarioTrigger({ trigger, close }: { trigger: string; close: number | null }) {
  const m = trigger.match(/[\d,]+(?:\.\d+)?/)
  if (!m || close == null || close <= 0) return <>{trigger}</>

  const priceStr = m[0]
  const price = Number(priceStr.replace(/,/g, ''))
  if (!Number.isFinite(price)) return <>{trigger}</>

  const pct = ((price - close) / close) * 100
  const pctText = `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`

  const idx = m.index ?? 0
  const before = trigger.slice(0, idx)
  const after = trigger.slice(idx + priceStr.length)
  const bracketMatch = after.match(/^（([^）]*)）/)

  if (bracketMatch) {
    const inner = bracketMatch[1]
    const rest = after.slice(bracketMatch[0].length)
    return (
      <>
        {before}
        {priceStr}（{inner}
        <span className="scenario-trigger-pct">，{pctText}</span>）{rest}
      </>
    )
  }

  return (
    <>
      {before}
      {priceStr}
      <span className="scenario-trigger-pct">（{pctText}）</span>
      {after}
    </>
  )
}

function ScenarioCard({ scenario, isPrimary, close }: { scenario: ShortScenario; isPrimary: boolean; close: number | null }) {
  return (
    <div className={`summary-card scenario-card ${isPrimary ? 'primary' : ''}`}>
      <div className="scenario-top">
        <span className="scenario-title">{scenario.title}</span>
        <span className="scenario-prob mono">{scenario.probability_pct}%</span>
      </div>
      <div className="scenario-prob-bar-track">
        <div className="scenario-prob-bar-fill" style={{ width: `${scenario.probability_pct}%` }} />
      </div>
      <div className="scenario-trigger">
        條件：<ScenarioTrigger trigger={scenario.trigger} close={close} />
      </div>
      <ScenarioPricePath text={scenario.price_path_text} />
      <div className="scenario-narrative">{scenario.narrative}</div>
      <div className="scenario-invalidation">失效：{scenario.invalidation}</div>
      <div className="scenario-action">{scenario.action.text}</div>
    </div>
  )
}

export function ShortScenarios({ data, close }: { data: ShortScenariosData | null | undefined; close: number | null }) {
  if (!data) return null

  if (data.status === 'insufficient_data') {
    return (
      <div className="group">
        <div className="group-title">短線推演（1-4 週）</div>
        <div className="plain-card scenario-insufficient">{data.message}</div>
      </div>
    )
  }

  const topProb = Math.max(...data.scenarios.map((s) => s.probability_pct))

  return (
    <div className="group">
      <div className="group-title">短線推演（1-4 週）</div>
      <div className="scenario-list">
        {data.scenarios.map((s) => (
          <ScenarioCard key={s.id} scenario={s} isPrimary={s.probability_pct === topProb} close={close} />
        ))}
      </div>
      <div className="scenario-note">{data.prob_note}</div>
      <div className="scenario-note">{data.disclaimer}</div>
    </div>
  )
}
