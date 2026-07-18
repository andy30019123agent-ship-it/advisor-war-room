import { useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { fetchDaily, fetchStockDetail } from '../lib/api'
import { loadHoldings, saveHolding, deleteHolding, type Holding } from '../lib/holdings'
import { FreshnessBadge } from '../components/FreshnessBadge'
import { IconEmptyBriefcase, IconPlus, IconTrash, IconClose } from '../components/icons'

// 自加持股若不在追蹤清單（daily.tracked）裡，daily.json 沒有它的現價/決策，
// 改即時打 fetchStockDetail（fallback /api/analyze 現算）補上。staleTime 拉到
// 「當日」等級，同一天內切分頁/重渲染不重打 API，只有隔天或手動重整才會再抓。
const STALE_TIME_TODAY = 12 * 60 * 60 * 1000

export function Holdings() {
  const [holdings, setHoldings] = useState<Holding[]>(() => loadHoldings())
  const [editing, setEditing] = useState<Holding | null>(null)
  const [showForm, setShowForm] = useState(false)

  const { data: daily } = useQuery({ queryKey: ['daily'], queryFn: fetchDaily })

  const trackedIds = new Set((daily?.tracked ?? []).map((t) => t.id))
  // enabled 只在 daily 已載入且確定「不在追蹤清單」時才打 API，避免每次 render 都打、
  // 也避免 daily 還沒回來時誤判成「不在清單」而提前打了不必要的請求。
  const liveDetailQueries = useQueries({
    queries: holdings.map((h) => ({
      queryKey: ['stock', h.id],
      queryFn: () => fetchStockDetail(h.id),
      enabled: !!daily && !trackedIds.has(h.id),
      staleTime: STALE_TIME_TODAY,
      retry: 1,
    })),
  })
  const liveById = new Map(holdings.map((h, i) => [h.id, liveDetailQueries[i]]))

  function openNew() {
    setEditing({ id: '', name: '', shares: 0, costPrice: 0 })
    setShowForm(true)
  }

  function openEdit(h: Holding) {
    setEditing(h)
    setShowForm(true)
  }

  function handleSave(h: Holding) {
    const next = saveHolding(h)
    setHoldings(next)
    setShowForm(false)
    setEditing(null)
  }

  function handleDelete(id: string) {
    const next = deleteHolding(id)
    setHoldings(next)
  }

  return (
    <div className="screen">
      <header className="page-header">
        <div className="top-row">
          {daily ? <FreshnessBadge dataDate={daily.meta.data_date} generatedAt={daily.meta.generated_at} /> : <span />}
        </div>
        <div className="large-title">持股</div>
      </header>

      {holdings.length === 0 ? (
        <div className="empty-state">
          <IconEmptyBriefcase />
          <div className="title">還沒有持股紀錄</div>
          <div className="desc">
            新增第一筆持股，追蹤損益和每檔的最新建議。
          </div>
          <div className="group" style={{ width: '100%', padding: '8px 0 0' }}>
            <button type="button" className="btn-primary" onClick={openNew}>
              <IconPlus /> 新增持股
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="search-wrap">
            <button type="button" className="btn-primary" onClick={openNew}>
              <IconPlus /> 新增持股
            </button>
          </div>
          <div className="group-title">我的持股</div>
          <div className="group">
            <div className="list-card">
              {holdings.map((h) => {
                const tracked = daily?.tracked.find((t) => t.id === h.id)
                // 不在追蹤清單 → 用 fetchStockDetail（fallback /api/analyze）現算的結果補現價/決策。
                const live = !tracked ? liveById.get(h.id) : undefined
                const liveDetail = live?.data

                const currentPrice = tracked?.close ?? liveDetail?.price.close ?? null
                const pnlPct =
                  currentPrice != null && h.costPrice > 0
                    ? ((currentPrice - h.costPrice) / h.costPrice) * 100
                    : null
                const pnlClass = pnlPct == null ? 'flat' : pnlPct > 0 ? 'up' : pnlPct < 0 ? 'down' : 'flat'

                const action = tracked?.decision.action ?? liveDetail?.primary_decision.action
                const defensePrice = tracked?.decision.defense_price ?? liveDetail?.primary_decision.defense_price ?? null
                const isLiveLoading = !!live?.isLoading
                const isLiveError = !!live?.isError

                return (
                  <button type="button" className="list-row" key={h.id} onClick={() => openEdit(h)} style={{ width: '100%', textAlign: 'left', background: 'none', border: 'none' }}>
                    <div className="row-top">
                      <div className="row-name">
                        <span className="name">{h.name || h.id}</span>
                        <span className="code mono">{h.id}</span>
                      </div>
                      {isLiveLoading ? (
                        <span className="skeleton skeleton-line" style={{ width: 48, height: 19, marginBottom: 0 }} />
                      ) : (
                        <div className={`row-price mono ${pnlClass === 'up' ? 'up' : pnlClass === 'down' ? 'down' : ''}`}>
                          {currentPrice != null ? currentPrice.toLocaleString() : '—'}
                        </div>
                      )}
                    </div>
                    <div className="row-tags">
                      <span className="pill neutral">
                        {h.shares.toLocaleString()} 股 ／ 成本 {h.costPrice.toLocaleString()}
                      </span>
                      {!isLiveLoading && (
                        <span className={`pnl ${pnlClass}`}>
                          {pnlPct != null ? `${pnlPct > 0 ? '+' : ''}${pnlPct.toFixed(1)}%` : '—'}
                        </span>
                      )}
                    </div>
                    {isLiveLoading && (
                      <div className="row-tags" style={{ marginTop: 8 }}>
                        <span className="skeleton skeleton-line" style={{ width: 96, height: 22, marginBottom: 0 }} />
                      </div>
                    )}
                    {isLiveError && (
                      <div className="row-tags" style={{ marginTop: 8 }}>
                        <span className="pill neutral">暫時抓不到分析（稍後自動重試）</span>
                      </div>
                    )}
                    {!isLiveLoading && !isLiveError && action && (
                      <div className="row-tags" style={{ marginTop: 8 }}>
                        <span className="pill">{action}</span>
                        {defensePrice != null && (
                          <span className="pill stop">防守價 {defensePrice.toLocaleString()}</span>
                        )}
                      </div>
                    )}
                  </button>
                )
              })}
            </div>
          </div>
        </>
      )}

      {showForm && editing && (
        <HoldingForm
          initial={editing}
          isNew={holdings.every((h) => h.id !== editing.id) || editing.id === ''}
          onCancel={() => {
            setShowForm(false)
            setEditing(null)
          }}
          onSave={handleSave}
          onDelete={holdings.some((h) => h.id === editing.id) ? () => handleDelete(editing.id) : undefined}
        />
      )}
    </div>
  )
}

function HoldingForm({
  initial,
  isNew,
  onCancel,
  onSave,
  onDelete,
}: {
  initial: Holding
  isNew: boolean
  onCancel: () => void
  onSave: (h: Holding) => void
  onDelete?: () => void
}) {
  const [id, setId] = useState(initial.id)
  const [name, setName] = useState(initial.name)
  const [shares, setShares] = useState(initial.shares ? String(initial.shares) : '')
  const [costPrice, setCostPrice] = useState(initial.costPrice ? String(initial.costPrice) : '')

  const canSave = id.trim().length > 0 && Number(shares) > 0 && Number(costPrice) > 0

  function submit() {
    if (!canSave) return
    onSave({
      id: id.trim(),
      name: name.trim() || id.trim(),
      shares: Number(shares),
      costPrice: Number(costPrice),
    })
  }

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span className="title">{isNew ? '新增持股' : '編輯持股'}</span>
          <button type="button" className="icon-btn" onClick={onCancel} aria-label="關閉">
            <IconClose />
          </button>
        </div>

        <div className="field">
          <label htmlFor="hf-id">股票代號</label>
          <input id="hf-id" value={id} onChange={(e) => setId(e.target.value)} placeholder="例如 2330" disabled={!isNew} />
        </div>
        <div className="field">
          <label htmlFor="hf-name">名稱</label>
          <input id="hf-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="例如 台積電" />
        </div>
        <div className="field">
          <label htmlFor="hf-shares">股數</label>
          <input id="hf-shares" type="number" inputMode="numeric" value={shares} onChange={(e) => setShares(e.target.value)} placeholder="1000" />
        </div>
        <div className="field">
          <label htmlFor="hf-cost">成本價</label>
          <input id="hf-cost" type="number" inputMode="decimal" value={costPrice} onChange={(e) => setCostPrice(e.target.value)} placeholder="2400" />
        </div>

        <button type="button" className="btn-primary" onClick={submit} disabled={!canSave} style={{ opacity: canSave ? 1 : 0.5 }}>
          儲存
        </button>

        {onDelete && (
          <div style={{ display: 'flex', justifyContent: 'center', marginTop: 12 }}>
            <button type="button" className="btn-danger-text" onClick={onDelete}>
              <IconTrash /> 刪除這筆持股
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
