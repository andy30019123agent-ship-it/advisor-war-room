import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchStockDetail, NotFoundError, SchemaMismatchError } from '../lib/api'
import { IconSearch } from '../components/icons'
import type { StockDetail } from '../types/contract'

export function StockSearch() {
  const [queryId, setQueryId] = useState<string | null>(null)
  const [inputValue, setInputValue] = useState('')

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['stock', queryId],
    queryFn: () => fetchStockDetail(queryId!),
    enabled: queryId !== null,
  })

  function submit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = inputValue.trim()
    if (!trimmed) return
    setQueryId(trimmed)
  }

  return (
    <div className="screen">
      <header className="page-header">
        <div className="large-title">查股票</div>
      </header>

      <form className="search-wrap" onSubmit={submit}>
        <div className="search-bar">
          <IconSearch />
          <input
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="輸入台股代號，例如 2330"
            inputMode="numeric"
            aria-label="輸入台股代號"
          />
        </div>
        <div style={{ paddingTop: 8 }}>
          <button type="submit" className="btn-primary" disabled={!inputValue.trim()} style={{ opacity: inputValue.trim() ? 1 : 0.5 }}>
            分析
          </button>
        </div>
      </form>

      {queryId === null && (
        <div className="empty-state">
          <IconSearch size={40} />
          <div className="title">輸入代號開始分析</div>
          <div className="desc">會給你一句話結論、防守價，和完整的證據拆解。</div>
        </div>
      )}

      {queryId !== null && isLoading && <LoadingSkeleton />}

      {queryId !== null && isError && error instanceof NotFoundError && (
        <div className="empty-state">
          <IconSearch size={40} />
          <div className="title">查無這檔股票，確認代號再試一次</div>
        </div>
      )}

      {queryId !== null && isError && !(error instanceof NotFoundError) && (
        <div className="error-banner">
          {error instanceof SchemaMismatchError ? '請更新 App' : '分析失敗，稍後再試'}
        </div>
      )}

      {data && <StockDetailView detail={data} />}
    </div>
  )
}

function LoadingSkeleton() {
  return (
    <div className="group">
      <div className="summary-card summary-inner">
        <div className="skeleton skeleton-line" style={{ width: '50%', height: 22 }} />
        <div className="skeleton skeleton-line" style={{ width: '95%' }} />
        <div className="skeleton skeleton-line" style={{ width: '80%' }} />
        <div className="skeleton skeleton-line" style={{ width: '60%' }} />
      </div>
      <div className="group-title" style={{ opacity: 0.5 }}>分析中</div>
    </div>
  )
}

function formatNumber(n: number | null): string {
  return n == null ? '—' : n.toLocaleString()
}

function StockDetailView({ detail }: { detail: StockDetail }) {
  const { profile, price, primary_decision: pd, context, evidence } = detail

  return (
    <>
      <div className="group">
        <div className="decision-card">
          <div style={{ padding: '18px 16px 0', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <span style={{ fontSize: 17, fontWeight: 700 }}>
              {profile.name} <span className="code mono" style={{ fontSize: 13, color: 'var(--text-soft)' }}>{profile.id}</span>
            </span>
            <span className={`row-price mono ${price.change_pct != null && price.change_pct < 0 ? 'down' : price.change_pct != null && price.change_pct > 0 ? 'up' : ''}`}>
              {formatNumber(price.close)}
            </span>
          </div>
          <div className="decision-action">{pd.action}</div>
          <div className="decision-reason">{pd.readable_reason}</div>
          <div className="hairline" />
          <div className="decision-meta-row">
            <span className="k">部位</span>
            <span className="v">
              {pd.position.tier_amount > 0
                ? `${(pd.position.tier_amount / 10000).toFixed(0)} 萬（${pd.position.lots} 張 ${pd.position.odd_shares} 股）`
                : '空手'}
            </span>
          </div>
          <div className="decision-meta-row">
            <span className="k">防守價</span>
            <span className="v risk">{formatNumber(pd.defense_price)}</span>
          </div>
          <div className="decision-meta-row">
            <span className="k">風險提示</span>
            <span className="v risk">{pd.risk_note}</span>
          </div>
          {pd.core_note && (
            <div className="decision-meta-row">
              <span className="k">核心備註</span>
              <span className="v">{pd.core_note}</span>
            </div>
          )}
        </div>
      </div>

      <div className="group-title">證據拆解</div>
      <div className="group">
        <div className="list-card">
          <details className="disclosure">
            <summary>
              三燈號
              <ChevronGlyph />
            </summary>
            <div className="disclosure-body">
              <LightRow label="基本面" light={context.lights.fundamental} />
              <LightRow label="技術面" light={context.lights.technical} />
              <LightRow label="籌碼面" light={context.lights.chips} />
            </div>
          </details>

          <details className="disclosure">
            <summary>
              估值
              <ChevronGlyph />
            </summary>
            <div className="disclosure-body">
              {context.valuation.band == null ? (
                <p>估值資料不足</p>
              ) : (
                <>
                  <p>目前落在「{context.valuation.band}」區間。</p>
                  <p>
                    base {formatNumber(context.valuation.base)} ／ bull {formatNumber(context.valuation.bull)} ／ bear{' '}
                    {formatNumber(context.valuation.bear)}
                    {context.valuation.regime ? `（${context.valuation.regime} 分位）` : ''}
                  </p>
                  {context.valuation.warning && <p>{context.valuation.warning}</p>}
                </>
              )}
            </div>
          </details>

          <details className="disclosure">
            <summary>
              時間框架
              <ChevronGlyph />
            </summary>
            <div className="disclosure-body">
              <p><strong>{context.timeframes.short.label}</strong>：{context.timeframes.short.stance}—{context.timeframes.short.basis}</p>
              <p><strong>{context.timeframes.swing.label}</strong>：{context.timeframes.swing.stance}—{context.timeframes.swing.basis}</p>
              <p><strong>{context.timeframes.mid.label}</strong>：{context.timeframes.mid.stance}—{context.timeframes.mid.basis}</p>
            </div>
          </details>

          <details className="disclosure">
            <summary>
              角色觀點
              <ChevronGlyph />
            </summary>
            <div className="disclosure-body">
              {evidence.roles.map((r) => (
                <div key={r.role} style={{ marginBottom: 12 }}>
                  <p><strong>{r.role}</strong></p>
                  {r.support.map((s, i) => <p key={`s${i}`}>＋ {s}</p>)}
                  {r.oppose.map((s, i) => <p key={`o${i}`}>－ {s}</p>)}
                </div>
              ))}
            </div>
          </details>

          <details className="disclosure">
            <summary>
              新聞
              <ChevronGlyph />
            </summary>
            <div className="disclosure-body">
              {evidence.news.map((n) => (
                <p key={n.url}>
                  <a href={n.url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>
                    {n.title}
                  </a>{' '}
                  — {n.source}
                </p>
              ))}
            </div>
          </details>
        </div>
      </div>
    </>
  )
}

function LightRow({ label, light }: { label: string; light: { color: 'green' | 'yellow' | 'red' | null; facts: string[] } }) {
  return (
    <div className="light-row">
      <span className={`light-dot ${light.color ?? 'na'}`} />
      <div>
        <strong>{label}</strong>
        {light.color == null ? <p>無資料</p> : light.facts.map((f, i) => <p key={i}>{f}</p>)}
      </div>
    </div>
  )
}

function ChevronGlyph() {
  return (
    <svg className="chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 6L15 12L9 18" />
    </svg>
  )
}
