import { useState } from 'react'
import type { Daily, Pick } from '../types/contract'

// B 包・今日精選（契約 v1.5 daily.picks）：主動選股候選池，三分組（短線/波段/長線）
// tab-pill 切換＋每檔收合式操作卡。gate（禁新倉）觸發時頂部誠實橫幅、短線/波段給空狀態。
// picks 整組缺席（舊資料）就整區隱藏（契約硬規則 3 graceful degrade）。

type Tab = 'short' | 'swing' | 'long'

const TAB_LABEL: Record<Tab, string> = { short: '短線', swing: '波段', long: '長線' }

function formatPrice(n: number | null): string {
  return n == null ? '—' : n.toLocaleString()
}

function ChevronGlyph() {
  return (
    <svg className="chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 6L15 12L9 18" />
    </svg>
  )
}

function PickCard({ pick, onSelectStock }: { pick: Pick; onSelectStock: (id: string) => void }) {
  return (
    <details className="pick-card">
      <summary>
        <div className="pick-summary-content">
          <div className="pick-row-top">
            <span className="pick-name">
              {pick.name}
              <span className="pick-code mono">{pick.id}</span>
            </span>
            <span className="pick-close mono">{formatPrice(pick.close)}</span>
          </div>
          <div className="pick-row-bottom">
            <span className="pick-conf">
              <span className="pick-conf-bar-track">
                <span className="pick-conf-bar-fill" style={{ width: `${pick.confidence}%` }} />
              </span>
              <span className="pick-conf-num mono">{pick.confidence}</span>
            </span>
            <span className="pick-summary">{pick.action_summary}</span>
          </div>
        </div>
        <ChevronGlyph />
      </summary>
      <div className="pick-body">
        {pick.entry_zone && (
          <div className="pick-entry-zone">
            分批佈局區 {formatPrice(pick.entry_zone[0])}-{formatPrice(pick.entry_zone[1])}
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
        <div className="pick-reasons">
          {pick.reasons.map((r, i) => (
            <p key={i}>{i + 1}. {r}</p>
          ))}
        </div>
        <button type="button" className="pick-detail-btn" onClick={() => onSelectStock(pick.id)}>
          看完整分析 →
        </button>
      </div>
    </details>
  )
}

export function PicksSection({ daily, collapsed, onSelectStock }: {
  daily: Daily | undefined
  collapsed: boolean
  onSelectStock: (id: string) => void
}) {
  const picks = daily?.picks
  const gateOn = !!picks && picks.gate !== '可正常布局'
  const counts: Record<Tab, number> = {
    short: picks?.short.length ?? 0,
    swing: picks?.swing.length ?? 0,
    long: picks?.long.length ?? 0,
  }
  const defaultTab: Tab = counts.short > 0 ? 'short' : counts.swing > 0 ? 'swing' : 'long'
  const [tab, setTab] = useState<Tab>(defaultTab)
  const [forceExpand, setForceExpand] = useState(false)

  if (!picks) return null

  if (collapsed && !forceExpand) {
    return (
      <div className="group">
        <button type="button" className="picks-collapsed-entry" onClick={() => setForceExpand(true)}>
          <span>
            今日精選
            <span className="picks-collapsed-sub">
              {' '}短 {counts.short}／波 {counts.swing}／長 {counts.long}{gateOn ? '・禁新倉' : ''}
            </span>
          </span>
          <ChevronGlyph />
        </button>
      </div>
    )
  }

  const list = picks[tab]

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

        {gateOn && <div className="picks-gate-banner">{picks.note}</div>}

        <div className="picks-tabs">
          {(['short', 'swing', 'long'] as Tab[]).map((t) => (
            <button
              type="button"
              key={t}
              className={`picks-tab ${tab === t ? 'active' : ''}`}
              onClick={() => setTab(t)}
            >
              {TAB_LABEL[t]}
              <span className="n">（{counts[t]}）</span>
            </button>
          ))}
        </div>

        {list.length === 0 ? (
          <div className="picks-empty">
            {gateOn && (tab === 'short' || tab === 'swing') ? '今日無新倉' : '今日無標的'}
          </div>
        ) : (
          <div className="picks-list">
            {list.map((p) => (
              <PickCard key={p.id} pick={p} onSelectStock={onSelectStock} />
            ))}
          </div>
        )}

        <div className="picks-disclaimer">精選＝規則篩選的研究候選，非投資指示；買賣前照劇本與防守紀律。</div>
      </div>
    </div>
  )
}
