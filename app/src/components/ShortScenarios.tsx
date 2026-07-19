import type { ShortScenarios as ShortScenariosData } from '../types/contract'
import { ScenarioCardList } from './ScenarioCards'

// 短線推演（1-4 週）三劇本卡（契約 v1.4 short_scenarios）。取代扇形圖當查股票頁主角——
// 扇形圖降級成收合區塊，見 ForecastFan.tsx。卡片渲染本體抽到 ScenarioCards.tsx（首頁
// 大盤作戰區 MarketBattle.tsx 複用同一份，契約 v1.8：「大盤劇本＝複用 short_scenarios
// 引擎」，schema 同構）。

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

  return (
    <div className="group">
      <div className="group-title">短線推演（1-4 週）</div>
      <ScenarioCardList scenarios={data.scenarios} close={close} probNote={data.prob_note} disclaimer={data.disclaimer} />
    </div>
  )
}
