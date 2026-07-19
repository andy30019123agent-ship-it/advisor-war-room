import { useQuery } from '@tanstack/react-query'
import { fetchDaily, SchemaMismatchError } from '../lib/api'
import { loadHoldings } from '../lib/holdings'
import { FreshnessBadge } from '../components/FreshnessBadge'
import { IconSearch, IconChevron, IconPlus } from '../components/icons'
import type { TabId } from '../App'
import type { Daily, TrackedStock } from '../types/contract'

type AlertSnapshot = Daily['alerts_snapshot'][number]

function marketStatusClass(status: string): string {
  if (status === '偏多進攻') return 'bullish'
  if (status === '中性') return 'neutral'
  return '' // 偏空防禦 uses default amber
}

function fmtIndex(n: number | null): string {
  return n == null ? '—' : n.toLocaleString(undefined, { maximumFractionDigits: 0 })
}

function fmtPct(n: number | null): string {
  return n == null ? '—' : `${n > 0 ? '+' : ''}${n.toFixed(1)}%`
}

function pctClass(n: number | null): string {
  if (n == null) return ''
  return n > 0 ? 'up' : n < 0 ? 'down' : ''
}

// 距觸發／防守價的緊張度：>8% 綠（安全）、3-8% 黃（留意）、<3% 紅（緊迫）。D 包規格。
function tensionClass(distPct: number | null): 'green' | 'yellow' | 'red' | null {
  if (distPct == null) return null
  const abs = Math.abs(distPct)
  if (abs < 3) return 'red'
  if (abs <= 8) return 'yellow'
  return 'green'
}

// 加權／S&P/費半 一行快照（大盤條，8.1）：null 一律顯示 —，不編數字。
function MarketSnapshot({ market }: { market: Daily['market'] }) {
  const spx = market.us.find((u) => u.id === 'SPX')
  const sox = market.us.find((u) => u.id === '費半') ?? market.us.find((u) => u.id === 'SOX')
  return (
    <div className="market-snapshot">
      <span>
        加權 <span className={`mono ${pctClass(market.taiex.change_pct)}`}>{fmtIndex(market.taiex.close)}</span>（
        <span className={`mono ${pctClass(market.taiex.change_pct)}`}>{fmtPct(market.taiex.change_pct)}</span>）
      </span>
      <span className="sep">｜</span>
      <span>
        S&P <span className={`mono ${pctClass(spx?.change_pct ?? null)}`}>{fmtPct(spx?.change_pct ?? null)}</span>
      </span>
      <span className="sep">｜</span>
      <span>
        費半 <span className={`mono ${pctClass(sox?.change_pct ?? null)}`}>{fmtPct(sox?.change_pct ?? null)}</span>
      </span>
    </div>
  )
}

function exposureBadgeClass(newPosition: string): string {
  if (newPosition === '禁止新增部位') return 'block'
  if (newPosition === '僅限試單') return 'amber'
  return 'ok'
}

export function Today({
  onNavigate,
  onNavigateStock,
}: {
  onNavigate: (tab: TabId) => void
  onNavigateStock: (id: string) => void
}) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['daily'],
    queryFn: fetchDaily,
  })

  if (isLoading) {
    return (
      <main className="screen">
        <header className="page-header">
          <div className="large-title">投顧戰情室</div>
        </header>
        <div className="group">
          <div className="summary-card summary-inner">
            <div className="skeleton skeleton-line" style={{ width: '40%' }} />
            <div className="skeleton skeleton-line" style={{ width: '90%', height: 24 }} />
            <div className="skeleton skeleton-line" style={{ width: '70%' }} />
          </div>
        </div>
      </main>
    )
  }

  if (isError) {
    const message = error instanceof SchemaMismatchError ? '請更新 App' : '資料讀取失敗，請稍後再試'
    return (
      <main className="screen">
        <header className="page-header">
          <div className="large-title">投顧戰情室</div>
        </header>
        <div className="error-banner">{message}</div>
      </main>
    )
  }

  if (!data) return null

  const { meta, market, core_holdings, watch, alerts_snapshot, events, exposure_guidance, today_command, delta, tracked } = data
  const holdings = loadHoldings()

  return (
    <main className="screen">
      <header className="page-header">
        <div className="top-row">
          <FreshnessBadge dataDate={meta.data_date} generatedAt={meta.generated_at} />
        </div>
        <div className="large-title">投顧戰情室</div>
      </header>

      <div className="search-wrap">
        <button type="button" className="search-bar" onClick={() => onNavigate('search')}>
          <IconSearch />
          <span>輸入台股代號，立刻分析</span>
        </button>
      </div>

      {today_command ? (
        <TodayCommandCard
          command={today_command}
          market={market}
          exposureGuidance={exposure_guidance ?? null}
          onNavigateStock={onNavigateStock}
        />
      ) : (
        <LegacyCommandCard market={market} exposureGuidance={exposure_guidance ?? null} />
      )}

      {delta && delta.items.length > 0 && (
        <>
          <div className="group-title">昨→今變化</div>
          <div className="group">
            <div className="list-card delta-card">
              {delta.items.slice(0, 5).map((item, i) => (
                <div className="delta-row" key={i}>
                  {renderDeltaItem(item)}
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      <div className="group-title">我的持股</div>
      {core_holdings.length > 0 && (
        <div className="core-holdings-note">
          核心：{core_holdings.map((h) => `${h.name} ${h.action}`).join('、')}
        </div>
      )}
      {holdings.length === 0 ? (
        <div className="group">
          <button type="button" className="holdings-cta" onClick={() => onNavigate('holdings')}>
            <IconPlus /> 還沒有持股紀錄，點此前往持股頁新增
          </button>
        </div>
      ) : (
        <div className="group">
          <div className="list-card">
            {holdings.map((h) => {
              const t = tracked.find((x) => x.id === h.id)
              const currentPrice = t?.close ?? null
              const changePct = t?.change_pct ?? null
              const defensePrice = t?.decision.defense_price ?? null
              const distPct =
                currentPrice != null && defensePrice != null && currentPrice !== 0
                  ? ((currentPrice - defensePrice) / currentPrice) * 100
                  : null
              const tension = tensionClass(distPct)
              return (
                <div className="list-row" key={h.id}>
                  <button
                    type="button"
                    className="row-button-reset"
                    onClick={() => onNavigateStock(h.id)}
                  >
                    <div className="row-top">
                      <div className="row-name">
                        {tension && <span className={`tension-dot ${tension}`} />}
                        <span className="name">{h.name || h.id}</span>
                        <span className="code mono">{h.id}</span>
                      </div>
                      <div className={`row-price mono ${pctClass(changePct)}`}>
                        {currentPrice != null ? currentPrice.toLocaleString() : '—'}
                      </div>
                    </div>
                    <div className="row-tags">
                      <span className={`pill ${pctClass(changePct)}`}>{fmtPct(changePct)}</span>
                      {distPct != null ? (
                        <span className="pill neutral">距防守 {distPct.toFixed(1)}%</span>
                      ) : (
                        <span className="pill neutral">非追蹤清單，暫無防守價</span>
                      )}
                    </div>
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {alerts_snapshot.length > 0 && (
        <MonitoringSection alerts={alerts_snapshot} tracked={tracked} onNavigateStock={onNavigateStock} />
      )}

      {!!events && events.length > 0 && (
        <>
          <div className="group-title">未來 14 天事件</div>
          <div className="group">
            <div className="list-card">
              {events.map((e, i) => (
                <div className="list-row" key={`${e.id}-${e.date}-${i}`}>
                  <div className="row-top">
                    <div className="row-name">
                      <span className="name">{e.name}</span>
                      <span className="code mono">{e.id}</span>
                    </div>
                    <span className="track-date mono">{e.date}</span>
                  </div>
                  <div className="row-tags">
                    <span className="pill neutral">{e.label}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {watch.length > 0 && (
        <>
          <div className="group-title">觀察清單</div>
          <div className="group">
            <div className="list-card">
              {watch.map((w) => (
                <button type="button" className="watch-row" key={w.id} onClick={() => onNavigate('search')}>
                  <div className="watch-left">
                    <span className="name">{w.name}</span>
                    <span className="code mono">{w.id}</span>
                  </div>
                  <div className="watch-right">
                    {w.wait_condition}
                    <IconChevron />
                  </div>
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </main>
  )
}

// D 包・今日指令中心：首頁新主角。headline 大字＋action 顯著動作行＋todos 0-3 條，
// 市場快照與風險溫度／曝險說明降級成卡底小字。
function TodayCommandCard({
  command,
  market,
  exposureGuidance,
  onNavigateStock,
}: {
  command: NonNullable<Daily['today_command']>
  market: Daily['market']
  exposureGuidance: Daily['exposure_guidance']
  onNavigateStock: (id: string) => void
}) {
  const { action, todos } = command
  return (
    <div className="group">
      <div className="command-card">
        <div className="command-headline">{command.headline}</div>

        {action &&
          (action.stock_id ? (
            <button type="button" className="command-action" onClick={() => onNavigateStock(action.stock_id!)}>
              <span>{action.text}</span>
              <IconChevron />
            </button>
          ) : (
            <div className="command-action-static">{action.text}</div>
          ))}

        {todos.length > 0 && (
          <div className="command-todos">
            {todos.slice(0, 3).map((t, i) =>
              t.stock_id ? (
                <button
                  type="button"
                  className="command-todo row-button-reset"
                  key={i}
                  onClick={() => onNavigateStock(t.stock_id!)}
                >
                  <span>{t.text}</span>
                  <IconChevron />
                </button>
              ) : (
                <div className="command-todo" key={i}>
                  <span>{t.text}</span>
                </div>
              )
            )}
          </div>
        )}

        <div className="hairline" />
        <div className="command-footer">
          <MarketSnapshot market={market} />
          <div className="command-risk-row">
            <span className="risk-mini mono">風險 {market.risk_temp}/10</span>
            {exposureGuidance && <span className="exposure-mini">{exposureGuidance.note}</span>}
          </div>
        </div>
      </div>
    </div>
  )
}

// 舊版摘要卡（today_command 缺席時的 graceful degrade，契約硬規則 3）：保留 v1.1 版面。
function LegacyCommandCard({
  market,
  exposureGuidance,
}: {
  market: Daily['market']
  exposureGuidance: Daily['exposure_guidance']
}) {
  return (
    <div className="group">
      <div className="summary-card">
        <div className="summary-inner">
          <div className="summary-top">
            <div className={`market-status ${marketStatusClass(market.status)}`}>
              <IconTrendGlyph />
              {market.status}
            </div>
            <div className="risk-meter">
              <span className="label">風險溫度</span>
              <span className="value mono">
                {market.risk_temp}
                <small>/10</small>
              </span>
            </div>
          </div>
          <MarketSnapshot market={market} />
        </div>
        <div className="hairline" />
        <div className="conclusion">{renderConclusion(market.conclusion)}</div>
        {exposureGuidance && (
          <>
            <div className="hairline" />
            <div className="exposure-row">
              <p className="exposure-note">{exposureGuidance.note}</p>
              <span className={`badge ${exposureBadgeClass(exposureGuidance.new_position)}`}>
                {exposureGuidance.new_position}
              </span>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// 監控中（升級）：同一股票多個警示合併成一張卡，取距觸發最近者驅動緊張度色點；
// 整卡可點→直達查股票該股。
function MonitoringSection({
  alerts,
  tracked,
  onNavigateStock,
}: {
  alerts: AlertSnapshot[]
  tracked: TrackedStock[]
  onNavigateStock: (id: string) => void
}) {
  const grouped: { id: string; name: string; alerts: AlertSnapshot[] }[] = []
  for (const a of alerts) {
    const existing = grouped.find((g) => g.id === a.id)
    if (existing) existing.alerts.push(a)
    else grouped.push({ id: a.id, name: a.name, alerts: [a] })
  }

  return (
    <>
      <div className="group-title">監控中</div>
      <div className="group">
        <div className="list-card">
          {grouped.map((g) => {
            const t = tracked.find((x) => x.id === g.id)
            const currentPrice = t?.close ?? null
            const distances = g.alerts
              .map((a) => (currentPrice != null && currentPrice !== 0 ? Math.abs((currentPrice - a.price) / currentPrice) * 100 : null))
              .filter((d): d is number => d != null)
            const minDist = distances.length > 0 ? Math.min(...distances) : null
            const tension = tensionClass(minDist)
            return (
              <div className="list-row" key={g.id}>
                <button type="button" className="row-button-reset" onClick={() => onNavigateStock(g.id)}>
                  <div className="row-top">
                    <div className="row-name">
                      {tension && <span className={`tension-dot ${tension}`} />}
                      <span className="name">{g.name}</span>
                      <span className="code mono">{g.id}</span>
                    </div>
                    {minDist != null && <span className="monitor-distance mono">距觸發 {minDist.toFixed(1)}%</span>}
                  </div>
                  <div className="row-tags">
                    {g.alerts.map((a, i) => (
                      <span className={`pill ${a.type === 'defense' ? 'stop' : 'up'}`} key={i}>
                        {a.type === 'defense' ? '防守' : '進場'} {a.price.toLocaleString()}{' '}
                        {a.direction === 'below' ? '↓' : '↑'}
                      </span>
                    ))}
                  </div>
                </button>
              </div>
            )
          })}
        </div>
      </div>
    </>
  )
}

// 昨→今變化的一行：有「舊→新」箭頭就拆成三段上色，沒有就整句原色顯示。
function renderDeltaItem(text: string) {
  const idx = text.indexOf('→')
  if (idx === -1) return text
  return (
    <>
      <span className="delta-old">{text.slice(0, idx)}</span>
      <span className="delta-arrow">→</span>
      <span className="delta-new">{text.slice(idx + 1)}</span>
    </>
  )
}

function renderConclusion(text: string) {
  // 「不加碼」等關鍵字用 accent 標色（貼近 mockup），找不到就整句原色。
  const keyword = text.match(/不加碼|加碼|減碼|出場|觀望|續抱/)?.[0]
  if (!keyword) return text
  const idx = text.indexOf(keyword)
  return (
    <>
      {text.slice(0, idx)}
      <span className="accent">{keyword}</span>
      {text.slice(idx + keyword.length)}
    </>
  )
}

function IconTrendGlyph() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 18L10 10L14 14L20 6" />
      <path d="M15 6H20V11" />
    </svg>
  )
}
