import { useQuery } from '@tanstack/react-query'
import { fetchStockDetail, SchemaMismatchError } from '../lib/api'
import { FreshnessBadge } from '../components/FreshnessBadge'

const MILESTONES = [5, 20, 60] as const

function daysSince(dateStr: string): number {
  const then = new Date(dateStr + 'T00:00:00+08:00').getTime()
  const now = Date.now()
  return Math.max(0, Math.floor((now - then) / (24 * 60 * 60 * 1000)))
}

export function Track() {
  // 戰績頁目前用 2330 fixture 的 track（追蹤清單每檔一份；v1 先示範單檔清單）。
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['stock', '2330'],
    queryFn: () => fetchStockDetail('2330'),
  })

  return (
    <div className="screen">
      <header className="page-header">
        <div className="top-row">
          {data ? <FreshnessBadge generatedAt={data.meta.generated_at} /> : <span />}
        </div>
        <div className="large-title">戰績</div>
      </header>

      {isLoading && (
        <div className="group">
          <div className="list-card" style={{ padding: 16 }}>
            <div className="skeleton skeleton-line" style={{ width: '80%' }} />
            <div className="skeleton skeleton-line" style={{ width: '60%' }} />
          </div>
        </div>
      )}

      {isError && (
        <div className="error-banner">
          {error instanceof SchemaMismatchError ? '請更新 App' : '資料讀取失敗，請稍後再試'}
        </div>
      )}

      {data && (
        <>
          <div className="group-title">{data.profile.name} {data.profile.id}</div>
          <div className="group">
            <div className="list-card">
              {data.track.map((t, i) => {
                const elapsed = t.status === 'pending' ? daysSince(t.date) : null
                return (
                  <div className="track-row" key={`${t.date}-${i}`}>
                    <div className="track-top">
                      <span className="track-date mono">{t.date}</span>
                      <span className="pill">{t.action}</span>
                    </div>
                    <div style={{ fontSize: 15, color: 'var(--text-soft)' }}>
                      建議當時價 <span className="mono">{t.price_at_rec.toLocaleString()}</span>
                    </div>
                    {t.status === 'pending' ? (
                      <>
                        <div style={{ fontSize: 13, color: 'var(--text-faint)', marginTop: 6 }}>
                          追蹤中 第 {elapsed} 天
                        </div>
                        <div className="progress-track">
                          {MILESTONES.map((m) => (
                            <span key={m} className={`progress-step${(elapsed ?? 0) >= m ? ' filled' : ''}`} />
                          ))}
                        </div>
                      </>
                    ) : (
                      <div className="row-tags" style={{ marginTop: 8 }}>
                        <span className="pill neutral">R5 {t.outcome.r5 ?? '—'}%</span>
                        <span className="pill neutral">R20 {t.outcome.r20 ?? '—'}%</span>
                        <span className="pill neutral">R60 {t.outcome.r60 ?? '—'}%</span>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
