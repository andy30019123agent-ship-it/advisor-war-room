import type { MarketBattle as MarketBattleData, MarketBattleFlow } from '../types/contract'
import { CandleChart } from './CandleChart'
import { ScenarioCardList } from './ScenarioCards'
import { IconChevron } from './icons'
import { fmtPct, pctClass } from '../lib/format'

// 首頁「大盤作戰區」（契約 v1.8 daily.json.market_battle）。插在今日頁「指令卡之後、
// 我的持股之前」；預設收合成一行摘要，展開才看到 TAIEX K 線／大盤三劇本／資金流向／
// 1 個月機率區間——指令卡仍是首頁主角，這區不能把首頁塞爆。
//
// 用原生 <details>（同 ForecastFan.tsx 的收合手法，免額外狀態管理）；`.disclosure` 既有
// CSS 提供 200ms chevron 轉場，展開/收合本身是原生瞬時切換，兩者合計遠低於 300ms 驗收線。
//
// K 線／劇本卡都複用既有元件（CandleChart／ScenarioCardList），不重新刻一份——市場劇本
// 與個股 short_scenarios 同構（契約：「大盤劇本＝複用 short_scenarios 引擎」）。

function fmtPrice(n: number): string {
  return Math.round(n).toLocaleString()
}

function fmtYi(n: number): string {
  const rounded = Math.round(n)
  return `${rounded > 0 ? '+' : ''}${rounded.toLocaleString()} 億`
}

// 收合摘要：「大盤作戰區｜劇本一 50% ＋ 外資連賣 7 日」——取機率最高的劇本（標題「・」前
// 半段）＋外資連買賣天數，兩段用「＋」串起；缺哪段就跳過，兩段都沒有時只顯示區塊名稱。
function buildSummaryText(data: MarketBattleData): string {
  const parts: string[] = []
  if (data.scenarios && data.scenarios.status === 'ok' && data.scenarios.scenarios.length > 0) {
    const top = data.scenarios.scenarios.reduce((a, b) => (a.probability_pct >= b.probability_pct ? a : b))
    const shortTitle = top.title.split('・')[0]
    parts.push(`${shortTitle} ${top.probability_pct}%`)
  }
  if (data.flow.foreign_streak) {
    const { direction, days } = data.flow.foreign_streak
    parts.push(`外資連${direction === 'sell' ? '賣' : '買'} ${days} 日`)
  }
  return parts.length > 0 ? `大盤作戰區｜${parts.join(' ＋ ')}` : '大盤作戰區'
}

function FlowCard({ flow }: { flow: MarketBattleFlow }) {
  const { foreign_streak, leading_sectors, us_overnight } = flow
  const items: React.ReactNode[] = []

  if (foreign_streak) {
    items.push(
      <>
        外資連{foreign_streak.direction === 'sell' ? '賣' : '買'} {foreign_streak.days} 日（
        <span className={`mono ${foreign_streak.direction === 'sell' ? 'down' : 'up'}`}>{fmtYi(foreign_streak.latest_yi)}</span>）
      </>
    )
  }
  if (leading_sectors.length > 0) {
    items.push(<>資金流向：{leading_sectors.join('、')}</>)
  }
  if (us_overnight.length > 0) {
    items.push(
      <>
        美股隔夜{' '}
        {us_overnight.map((u, i) => (
          <span key={u.id}>
            {i > 0 && ' '}
            {u.id} <span className={`mono ${pctClass(u.change_pct)}`}>{fmtPct(u.change_pct)}</span>
          </span>
        ))}
      </>
    )
  }

  if (items.length === 0) return null

  return (
    <div className="group">
      <div className="list-card battle-flow-card">
        {items.map((item, i) => (
          <span className="battle-flow-item" key={i}>
            {i > 0 && <span className="battle-flow-sep">｜</span>}
            {item}
          </span>
        ))}
      </div>
    </div>
  )
}

export function MarketBattle({ data }: { data: MarketBattleData | null | undefined }) {
  // 整組缺席（引擎尚未產出／v1.7 前舊 daily.json）＝整區隱藏，不佔首頁版面（契約硬規則 3）。
  if (!data) return null

  const close = data.ohlc && data.ohlc.length > 0 ? data.ohlc[data.ohlc.length - 1].c : null
  const summaryText = buildSummaryText(data)
  const keyLevels = [...data.key_levels.supports, ...data.key_levels.resistances]

  return (
    <div className="group">
      <div className="list-card">
        <details className="disclosure market-battle-disclosure">
          <summary>
            <span className="market-battle-summary-text">{summaryText}</span>
            <IconChevron />
          </summary>
          <div className="disclosure-body market-battle-body">
            <CandleChart
              ohlc={data.ohlc}
              ma60={null}
              defensePrice={null}
              entryPrice={null}
              keyLevels={keyLevels}
              title="TAIEX 大盤 K 線"
            />

            {data.scenarios && data.scenarios.status === 'insufficient_data' && (
              <div className="group">
                <div className="group-title">大盤推演（1-4 週）</div>
                <div className="plain-card scenario-insufficient">{data.scenarios.message}</div>
              </div>
            )}
            {data.scenarios && data.scenarios.status === 'ok' && (
              <div className="group">
                <div className="group-title">大盤推演（1-4 週）</div>
                <ScenarioCardList
                  scenarios={data.scenarios.scenarios}
                  close={close}
                  probNote={data.scenarios.prob_note}
                  disclaimer={data.scenarios.disclaimer}
                />
              </div>
            )}

            <FlowCard flow={data.flow} />

            {data.forecast_range_m1 && (
              <div className="group">
                <div className="list-card battle-forecast-line mono">
                  未來 1 個月 70% 機率落在 {fmtPrice(data.forecast_range_m1[0])} ～ {fmtPrice(data.forecast_range_m1[1])}（零漂移模擬）
                </div>
              </div>
            )}
          </div>
        </details>
      </div>
    </div>
  )
}
