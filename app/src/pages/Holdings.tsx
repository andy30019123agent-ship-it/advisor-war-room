import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchDaily } from '../lib/api'
import { loadHoldings, saveHolding, deleteHolding, type Holding } from '../lib/holdings'
import { FreshnessBadge } from '../components/FreshnessBadge'
import { IconEmptyBriefcase, IconPlus, IconTrash, IconClose } from '../components/icons'

export function Holdings() {
  const [holdings, setHoldings] = useState<Holding[]>(() => loadHoldings())
  const [editing, setEditing] = useState<Holding | null>(null)
  const [showForm, setShowForm] = useState(false)

  const { data: daily } = useQuery({ queryKey: ['daily'], queryFn: fetchDaily })

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
          {daily ? <FreshnessBadge generatedAt={daily.meta.generated_at} /> : <span />}
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
                const currentPrice = tracked?.close ?? null
                const pnlPct =
                  currentPrice != null && h.costPrice > 0
                    ? ((currentPrice - h.costPrice) / h.costPrice) * 100
                    : null
                const pnlClass = pnlPct == null ? 'flat' : pnlPct > 0 ? 'up' : pnlPct < 0 ? 'down' : 'flat'

                return (
                  <button type="button" className="list-row" key={h.id} onClick={() => openEdit(h)} style={{ width: '100%', textAlign: 'left', background: 'none', border: 'none' }}>
                    <div className="row-top">
                      <div className="row-name">
                        <span className="name">{h.name || h.id}</span>
                        <span className="code mono">{h.id}</span>
                      </div>
                      <div className={`row-price mono ${pnlClass === 'up' ? 'up' : pnlClass === 'down' ? 'down' : ''}`}>
                        {currentPrice != null ? currentPrice.toLocaleString() : '—'}
                      </div>
                    </div>
                    <div className="row-tags">
                      <span className="pill neutral">
                        {h.shares.toLocaleString()} 股 ／ 成本 {h.costPrice.toLocaleString()}
                      </span>
                      <span className={`pnl ${pnlClass}`}>
                        {pnlPct != null ? `${pnlPct > 0 ? '+' : ''}${pnlPct.toFixed(1)}%` : '—'}
                      </span>
                    </div>
                    {tracked && (
                      <div className="row-tags" style={{ marginTop: 8 }}>
                        <span className="pill">{tracked.decision.action}</span>
                        {tracked.decision.defense_price != null && (
                          <span className="pill stop">防守價 {tracked.decision.defense_price.toLocaleString()}</span>
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
