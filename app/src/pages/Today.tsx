import { useQuery } from '@tanstack/react-query'
import { fetchDaily, SchemaMismatchError } from '../lib/api'
import { FreshnessBadge } from '../components/FreshnessBadge'
import { IconSearch, IconChevron } from '../components/icons'
import type { TabId } from '../App'

function marketStatusClass(status: string): string {
  if (status === '偏多進攻') return 'bullish'
  if (status === '中性') return 'neutral'
  return '' // 偏空防禦 uses default amber
}

export function Today({ onNavigate }: { onNavigate: (tab: TabId) => void }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['daily'],
    queryFn: fetchDaily,
  })

  if (isLoading) {
    return (
      <div className="screen">
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
      </div>
    )
  }

  if (isError) {
    const message = error instanceof SchemaMismatchError ? '請更新 App' : '資料讀取失敗，請稍後再試'
    return (
      <div className="screen">
        <header className="page-header">
          <div className="large-title">投顧戰情室</div>
        </header>
        <div className="error-banner">{message}</div>
      </div>
    )
  }

  if (!data) return null

  const { meta, market, core_holdings, watch } = data

  return (
    <div className="screen">
      <header className="page-header">
        <div className="top-row">
          <FreshnessBadge generatedAt={meta.generated_at} />
        </div>
        <div className="large-title">投顧戰情室</div>
      </header>

      <div className="search-wrap">
        <button type="button" className="search-bar" onClick={() => onNavigate('search')}>
          <IconSearch />
          <span>輸入台股代號，立刻分析</span>
        </button>
      </div>

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
          </div>
          <div className="hairline" />
          <div className="conclusion">{renderConclusion(market.conclusion)}</div>
        </div>
      </div>

      <div className="group-title">我的持股</div>
      <div className="group">
        <div className="list-card">
          {core_holdings.map((h) => (
            <div className="list-row" key={h.id}>
              <div className="row-top">
                <div className="row-name">
                  <span className="name">{h.name}</span>
                  <span className="code mono">{h.id}</span>
                </div>
              </div>
              <div className="row-tags">
                <span className="pill">{h.action}</span>
                <span className="pill neutral">{h.note}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

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
    </div>
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
