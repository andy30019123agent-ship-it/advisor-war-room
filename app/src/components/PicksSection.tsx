import { useState } from 'react'
import type { Daily, Pick, PicksPools, PicksFlat, RosterChanges } from '../types/contract'
import type { JournalEntry } from '../lib/journal'
import { getLossStreak } from '../lib/journal'
import { applyCooldown } from '../lib/cooldown'
import { TrackButton } from './TrackButton'

// B 包・今日精選（契約 v1.6 daily.picks）：主動選股候選池，v1.6 起改分艙（今日可操作／
// 解禁後優先／長線研究），取代 v1.5 的平鋪 short/swing/long。tab-pill 切換＋每檔收合式操作卡。
// gate（禁新倉）觸發時頂部誠實橫幅、actionable 池給空狀態。
//
// 向後相容（部署切換期防炸，契約硬規則 3）：拿到 v1.5 平鋪結構（有 short/swing/long、
// 無 pools）時整段退回舊版三分組渲染，不強行套 v1.6 的池子語意。判斷方式＝執行期看
// `'pools' in picks`（型別是 PicksSchema = union(V16, V15)，zod 解析時哪個形狀能過就是哪個）。
// picks 整組缺席（更舊資料）就整區隱藏（同一條硬規則）。

type PoolTab = 'actionable' | 'on_deck' | 'research'
type LegacyTab = 'short' | 'swing' | 'long'

const POOL_LABEL: Record<PoolTab, string> = { actionable: '今日可操作', on_deck: '解禁後優先', research: '長線研究' }
const LEGACY_LABEL: Record<LegacyTab, string> = { short: '短線', swing: '波段', long: '長線' }

function formatPrice(n: number | null): string {
  return n == null ? '—' : n.toLocaleString()
}

// 精選卡的「試單參考金額」：契約目前只有 entry_zone（價格區間），Pick 沒有部位金額欄位
// （那是 stocks/<id>.json 的 primary_decision.position 才有的東西，picks 池子的標的當天
// 不一定跑過完整 analyze）。用 score 概略對應 primary_decision.position 慣用的級距語言
// （0/10/20/40/60 萬）估一個量級參考，純前端 UI 顯示用、非引擎資料——之後契約若補上真正
// 的建議金額欄位要改接那個，這裡先讓冷靜期規則（規格 4.）在精選卡也看得見。
function suggestedTier(score: number): number {
  if (score >= 80) return 200000
  if (score >= 65) return 150000
  return 100000
}

function rankMoveClass(mark: string | null | undefined): string {
  return mark === '↑' ? 'up' : mark === '↓' ? 'down' : 'flat'
}

function ChevronGlyph() {
  return (
    <svg className="chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 6L15 12L9 18" />
    </svg>
  )
}

function PickCard({
  pick,
  gateOn,
  onSelectStock,
  daily,
  journal,
}: {
  pick: Pick
  gateOn: boolean
  onSelectStock: (id: string) => void
  daily: Daily | undefined
  journal: JournalEntry[]
}) {
  const streak = getLossStreak(journal)
  const cooldown = applyCooldown(suggestedTier(pick.score), streak)
  const showBadgeRow = !!pick.status_note || (pick.tenure_days != null && pick.tenure_days >= 3)

  return (
    <details className="pick-card">
      <summary>
        <div className="pick-summary-content">
          <div className="pick-row-top">
            <span className="pick-name">
              {pick.name}
              <span className="pick-code mono">{pick.id}</span>
              {pick.sector && <span className="pick-sector">{pick.sector}</span>}
              {pick.rank_move && <span className={`pick-rank ${rankMoveClass(pick.rank_move)}`}>{pick.rank_move}</span>}
            </span>
            <span className="pick-close mono">{formatPrice(pick.close)}</span>
          </div>
          {showBadgeRow && (
            <div className="pick-badge-row">
              {pick.status_note && <span className="badge amber">{pick.status_note}</span>}
              {pick.tenure_days != null && pick.tenure_days >= 3 && (
                <span className="pick-tenure">留任 {pick.tenure_days} 日</span>
              )}
            </div>
          )}
          <div className="pick-row-bottom">
            {/* 顯示評分（規則排序用的 score，非 confidence）＋「評分」小字 label——收合卡的
               裸數字沒 label 讓人看不懂（實戰走查任務 5）。排序即依此 score，數字大＝排前面。 */}
            <span className="pick-conf">
              <span className="pick-conf-bar-track">
                <span className="pick-conf-bar-fill" style={{ width: `${Math.min(pick.score, 100)}%` }} />
              </span>
              <span className="pick-conf-num mono">{Math.round(pick.score)}</span>
              <span className="pick-conf-label">評分</span>
            </span>
            <span className="pick-summary">{pick.action_summary}</span>
          </div>
        </div>
        <ChevronGlyph />
      </summary>
      <div className="pick-body">
        {pick.entry_zone && (
          <div className="pick-entry-zone">
            {/* 禁新倉時（gateOn）這區間不是「可以進場佈局」，是「等解禁前先盯著看」——
               收合 summary 已經誠實講「等解禁」，展開後的區間 label 不能還喊「佈局」，
               不然使用者會覺得矛盾（大檢查・picks 卡矛盾）。 */}
            {gateOn ? '觀察區 ' : '分批佈局區 '}
            {formatPrice(pick.entry_zone[0])}-{formatPrice(pick.entry_zone[1])}
          </div>
        )}
        <div className="pick-meta-row">
          <span className="k">防守價</span>
          <span className="v">{formatPrice(pick.defense_price)}</span>
        </div>
        <div className="pick-meta-row">
          <span className="k">失效條件</span>
          <span className="v">{pick.invalidation}</span>
        </div>
        <div className="pick-position-row">
          <span className="k">試單參考</span>
          <span className="v">
            {cooldown.level === 'red' ? '暫停新倉' : `${(cooldown.amount! / 10000).toFixed(0)} 萬`}
            {cooldown.badgeText && (
              <span className={`badge ${cooldown.level === 'red' ? 'block' : 'amber'}`} style={{ marginLeft: 6 }}>
                {cooldown.badgeText}
              </span>
            )}
          </span>
        </div>
        <div className="pick-reasons">
          {pick.reasons.map((r, i) => (
            <p key={i}>{i + 1}. {r}</p>
          ))}
        </div>
        <div className="pick-track-row">
          <TrackButton stockId={pick.id} daily={daily} variant="inline" />
        </div>
        <button type="button" className="pick-detail-btn" onClick={() => onSelectStock(pick.id)}>
          看完整分析 →
        </button>
      </div>
    </details>
  )
}

function RosterChangesBanner({ rc }: { rc: RosterChanges | null | undefined }) {
  if (!rc) return null
  const hasNew = rc.new.length > 0
  const hasDropped = rc.dropped.length > 0
  if (!hasNew && !hasDropped) return null
  const parts: string[] = []
  if (hasNew) parts.push(`新進 ${rc.new.join('、')}`)
  if (hasDropped) parts.push(`移出 ${rc.dropped.join('、')}`)
  return (
    <div className="roster-changes-banner">
      今日調整：{parts.join('・')}
      {rc.stay_note && <span className="stay-note">{rc.stay_note}</span>}
    </div>
  )
}

export function PicksSection({ daily, collapsed, onSelectStock, journal }: {
  daily: Daily | undefined
  collapsed: boolean
  onSelectStock: (id: string) => void
  journal: JournalEntry[]
}) {
  const picks = daily?.picks
  const isPools = !!picks && 'pools' in picks
  const gateOn = !!picks && picks.gate !== '可正常布局'

  const tabKeys: string[] = isPools ? ['actionable', 'on_deck', 'research'] : ['short', 'swing', 'long']
  const labelOf = (t: string) => (isPools ? POOL_LABEL[t as PoolTab] : LEGACY_LABEL[t as LegacyTab])
  const countOf = (t: string) => (isPools ? listOf(t).length : listOf(t).length)
  function listOf(t: string): Pick[] {
    if (!picks) return []
    if (isPools) return (picks as PicksPools).pools[t as PoolTab]
    return (picks as PicksFlat)[t as LegacyTab]
  }

  // tab 卡死修復（大檢查）：daily 一開始是 undefined（counts 全 0）→ autoTab 落在最後一個 tab；
  // useState(defaultTab) 只吃「第一次 render」的值，之後 daily 非同步載入、counts 變了也
  // 不會重算，tab 就卡死。改成 derived：manualTab 為 null（使用者還沒手動點過任何 tab）時，
  // tab 每次 render 都跟著當下 counts 重算「第一個有資料的分組」；使用者一旦手動點過 tab
  // （selectTab），manualTab 落地，之後永遠尊重手動選擇、不再被 counts 變化蓋掉。
  const autoTab = tabKeys.find((t) => countOf(t) > 0) ?? tabKeys[tabKeys.length - 1]
  const [manualTab, setManualTab] = useState<string | null>(null)
  const tab = manualTab ?? autoTab
  const selectTab = (t: string) => setManualTab(t)
  const [forceExpand, setForceExpand] = useState(false)

  if (!picks) return null

  const collapsedSub = isPools
    ? `可操作 ${countOf('actionable')}／解禁 ${countOf('on_deck')}／研究 ${countOf('research')}${gateOn ? '・禁新倉' : ''}`
    : `短 ${countOf('short')}／波 ${countOf('swing')}／長 ${countOf('long')}${gateOn ? '・禁新倉' : ''}`

  if (collapsed && !forceExpand) {
    return (
      <div className="group">
        <button type="button" className="picks-collapsed-entry" onClick={() => setForceExpand(true)}>
          <span>
            今日精選
            <span className="picks-collapsed-sub"> {collapsedSub}</span>
          </span>
          <ChevronGlyph />
        </button>
      </div>
    )
  }

  const list = listOf(tab)
  const rosterChanges = isPools ? (picks as PicksPools).roster_changes : null

  return (
    <div className="group">
      <div className="group-title">今日精選</div>
      <div className="list-card" style={{ padding: 14 }}>
        {collapsed && (
          <button type="button" className="picks-collapsed-entry" style={{ marginBottom: 10 }} onClick={() => setForceExpand(false)}>
            <span>收起今日精選</span>
            <ChevronGlyph />
          </button>
        )}

        <RosterChangesBanner rc={rosterChanges} />

        {gateOn && <div className="picks-gate-banner">{picks.note}</div>}

        <div className="picks-tabs">
          {tabKeys.map((t) => (
            <button
              type="button"
              key={t}
              className={`picks-tab ${tab === t ? 'active' : ''}`}
              onClick={() => selectTab(t)}
            >
              {labelOf(t)}
              <span className="n">（{countOf(t)}）</span>
            </button>
          ))}
        </div>

        {list.length === 0 ? (
          <div className="picks-empty">
            {gateOn && (tab === 'short' || tab === 'swing' || tab === 'actionable') ? '今日無新倉' : '今日無標的'}
          </div>
        ) : (
          <div className="picks-list">
            {list.map((p) => (
              <PickCard key={p.id} pick={p} gateOn={gateOn} onSelectStock={onSelectStock} daily={daily} journal={journal} />
            ))}
          </div>
        )}

        <div className="picks-disclaimer">精選＝規則篩選的研究候選，非投資指示；買賣前照劇本與防守紀律。評分＝規則排序用，非勝率。試單參考金額為前端依評分估算的量級，非引擎資料。</div>
      </div>
    </div>
  )
}
