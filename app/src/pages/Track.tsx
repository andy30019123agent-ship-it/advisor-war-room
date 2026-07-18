import { useQueries, useQuery } from '@tanstack/react-query'
import { fetchDaily, fetchStockDetail, SchemaMismatchError } from '../lib/api'
import { FreshnessBadge } from '../components/FreshnessBadge'
import type { TrackEntry } from '../types/contract'

const MILESTONES = [5, 20, 60] as const

interface AggregatedEntry extends TrackEntry {
  stockId: string
  stockName: string
}

function daysSince(dateStr: string): number {
  const then = new Date(dateStr + 'T00:00:00+08:00').getTime()
  const now = Date.now()
  return Math.max(0, Math.floor((now - then) / (24 * 60 * 60 * 1000)))
}

export function Track() {
  // 戰績頁＝聚合追蹤清單裡每一檔的 track 歷史（來源：daily.json 的 tracked[]，逐檔讀 stocks/<id>.json）。
  const dailyQuery = useQuery({ queryKey: ['daily'], queryFn: fetchDaily })
  const trackedIds = dailyQuery.data?.tracked.map((t) => t.id) ?? []

  const detailQueries = useQueries({
    queries: trackedIds.map((id) => ({
      queryKey: ['stock', id],
      queryFn: () => fetchStockDetail(id),
      enabled: trackedIds.length > 0,
    })),
  })

  const detailsLoading = trackedIds.length > 0 && detailQueries.some((q) => q.isLoading)
  const isLoading = dailyQuery.isLoading || detailsLoading

  const entries: AggregatedEntry[] = []
  detailQueries.forEach((q, i) => {
    if (q.isError) {
      // 單檔抓失敗（404／schema 不合）就跳過，不讓整頁掛掉。
      console.warn(`Track: 抓取 ${trackedIds[i]} 失敗，跳過`, q.error)
      return
    }
    if (!q.data) return
    const detail = q.data
    detail.track.forEach((t) => {
      entries.push({ ...t, stockId: detail.profile.id, stockName: detail.profile.name })
    })
  })
  entries.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0))

  return (
    <div className="screen">
      <header className="page-header">
        <div className="top-row">
          {dailyQuery.data ? (
            <FreshnessBadge dataDate={dailyQuery.data.meta.data_date} generatedAt={dailyQuery.data.meta.generated_at} />
          ) : (
            <span />
          )}
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

      {!isLoading && dailyQuery.isError && (
        <div className="error-banner">
          {dailyQuery.error instanceof SchemaMismatchError ? '請更新 App' : '資料讀取失敗，請稍後再試'}
        </div>
      )}

      {!isLoading && !dailyQuery.isError && entries.length === 0 && (
        <div className="empty-state">
          <div className="title">還沒有追蹤紀錄</div>
          <div className="desc">追蹤清單裡的股票有新建議時，會顯示在這裡。</div>
        </div>
      )}

      {!isLoading && !dailyQuery.isError && entries.length > 0 && (
        <>
          <div className="group-title">全部追蹤（{trackedIds.length} 檔）</div>
          <div className="group">
            <div className="list-card">
              {entries.map((t, i) => {
                const elapsed = t.status === 'pending' ? daysSince(t.date) : null
                return (
                  <div className="track-row" key={`${t.stockId}-${t.date}-${i}`}>
                    <div className="track-top">
                      <span className="track-date mono">{t.date}</span>
                      <span className="pill">{t.action}</span>
                    </div>
                    <div style={{ fontSize: 16, color: 'var(--text-soft)' }}>
                      {t.stockName} <span className="mono">{t.stockId}</span> · 建議當時價{' '}
                      <span className="mono">{t.price_at_rec.toLocaleString()}</span>
                    </div>
                    {t.status === 'pending' ? (
                      <>
                        <div style={{ fontSize: 13, color: 'var(--text-soft)', marginTop: 6 }}>
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
