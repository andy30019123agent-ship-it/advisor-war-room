import { useEffect, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { fetchDaily, fetchStockDetail } from '../lib/api'
import { loadHoldings, saveHolding, deleteHolding, type Holding } from '../lib/holdings'
import { FreshnessBadge } from '../components/FreshnessBadge'
import { IconEmptyBriefcase, IconPlus, IconTrash, IconClose } from '../components/icons'
import type { Daily } from '../types/contract'

// 自加持股若不在追蹤清單（daily.tracked）裡，daily.json 沒有它的現價/決策，
// 改即時打 fetchStockDetail（fallback /api/analyze 現算）補上。staleTime 拉到
// 「當日」等級，同一天內切分頁/重渲染不重打 API，只有隔天或手動重整才會再抓。
const STALE_TIME_TODAY = 12 * 60 * 60 * 1000

// 非追蹤持股的即時分析：最多同時 2 個併發、總數最多 8 檔（超過排隊）。持股清單沒上限，
// 一次全打會同時炸出多支 /api/analyze 冷查（各自最久 20 幾秒），互搶時間又吃 FinMind 額度
// （聯測 2026-07-18 #3）。
const MAX_LIVE_CONCURRENT = 2
const MAX_LIVE_TOTAL = 8

export function Holdings() {
  const [holdings, setHoldings] = useState<Holding[]>(() => loadHoldings())
  const [editing, setEditing] = useState<Holding | null>(null)
  const [showForm, setShowForm] = useState(false)

  const { data: daily } = useQuery({ queryKey: ['daily'], queryFn: fetchDaily })

  const trackedIds = new Set((daily?.tracked ?? []).map((t) => t.id))
  const untrackedHoldings = holdings.filter((h) => !trackedIds.has(h.id))
  const liveEligible = untrackedHoldings.slice(0, MAX_LIVE_TOTAL)
  const queuedIds = new Set(untrackedHoldings.slice(MAX_LIVE_TOTAL).map((h) => h.id))

  // 併發池：settledIds 記錄「已經有結果（成功或失敗）」的持股。某檔一結算，佇列裡排在
  // 它後面、還沒開始跑的下一檔就補上這個併發名額——不是死板地固定跑前兩個，而是同時最多
  // 兩個在飛行中。
  const [settledIds, setSettledIds] = useState<Set<string>>(new Set())

  // enabled 只在 daily 已載入、確定「不在追蹤清單」、且併發池還有名額（或本來就已結算過）
  // 時才打 API，避免每次 render 都打、也避免 daily 還沒回來時誤判成「不在清單」而提前打了
  // 不必要的請求。
  const liveDetailQueries = useQueries({
    queries: liveEligible.map((h, i) => {
      const pendingAhead = liveEligible.slice(0, i).filter((h2) => !settledIds.has(h2.id)).length
      return {
        queryKey: ['stock', h.id],
        queryFn: () => fetchStockDetail(h.id, trackedIds),
        enabled: !!daily && (settledIds.has(h.id) || pendingAhead < MAX_LIVE_CONCURRENT),
        staleTime: STALE_TIME_TODAY,
        retry: 1,
      }
    }),
  })
  const liveById = new Map(liveEligible.map((h, i) => [h.id, liveDetailQueries[i]]))

  useEffect(() => {
    setSettledIds((prev) => {
      let next: Set<string> | null = null
      liveEligible.forEach((h, i) => {
        const q = liveDetailQueries[i]
        if (q && (q.isSuccess || q.isError) && !prev.has(h.id)) {
          if (!next) next = new Set(prev)
          next.add(h.id)
        }
      })
      return next ?? prev
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveDetailQueries])

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
    // 刪除後彈窗要跟著關：不關的話 editing 還指著剛刪的舊資料，isNew 判斷
    // （holdings.every(id 不在清單) ）會被算成 true，彈窗變身「新增持股」還殘留舊欄位值，
    // 使用者按儲存等於把剛刪的持股用同一個 id 加回來（07-18 聯測 bug #7）。
    setShowForm(false)
    setEditing(null)
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
                // 超過併發池總量上限（MAX_LIVE_TOTAL）的非追蹤持股：不進 useQueries、不打 API，
                // 只顯示「排隊中」。
                const isQueued = !tracked && queuedIds.has(h.id)
                // 不在追蹤清單 → 用 fetchStockDetail（fallback /api/analyze）現算的結果補現價/決策。
                const live = !tracked && !isQueued ? liveById.get(h.id) : undefined
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
                    {isQueued && (
                      <div className="row-tags" style={{ marginTop: 8 }}>
                        <span className="pill neutral">分析排隊中</span>
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
          daily={daily}
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

const STOCK_ID_RE = /^\d{4,6}$/
const NAME_LOOKUP_DEBOUNCE_MS = 500

function HoldingForm({
  initial,
  isNew,
  daily,
  onCancel,
  onSave,
  onDelete,
}: {
  initial: Holding
  isNew: boolean
  daily: Daily | undefined
  onCancel: () => void
  onSave: (h: Holding) => void
  onDelete?: () => void
}) {
  const [id, setId] = useState(initial.id)
  const [name, setName] = useState(initial.name)
  const [shares, setShares] = useState(initial.shares ? String(initial.shares) : '')
  const [costPrice, setCostPrice] = useState(initial.costPrice ? String(initial.costPrice) : '')
  // 使用者只要手動動過名稱欄位一次，就不再自動覆蓋（找不到就留手動輸入，聯測 07-18 #9）。
  const [nameEditedByUser, setNameEditedByUser] = useState(!isNew && initial.name.length > 0)

  const canSave = id.trim().length > 0 && Number(shares) > 0 && Number(costPrice) > 0
  const trimmedId = id.trim()

  // 代號輸入後先查 daily.json 的 tracked/watch（反正已載入，免打 API）帶名稱；查不到、格式又
  // 合法時，debounce 後打一次即時分析拿 profile.name 補上（找不到就留手動輸入）。
  useEffect(() => {
    if (!isNew || nameEditedByUser || !trimmedId) return
    const fromDaily =
      daily?.tracked.find((t) => t.id === trimmedId)?.name ??
      daily?.watch.find((w) => w.id === trimmedId)?.name
    if (fromDaily) setName(fromDaily)
  }, [trimmedId, daily, isNew, nameEditedByUser])

  const knownInDaily = !!(
    daily?.tracked.some((t) => t.id === trimmedId) || daily?.watch.some((w) => w.id === trimmedId)
  )
  const [debouncedId, setDebouncedId] = useState(trimmedId)
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedId(trimmedId), NAME_LOOKUP_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [trimmedId])

  const liveNameQuery = useQuery({
    // 沿用跟持股清單/查股票頁一樣的 queryKey（['stock', id]），同一代號若別處已查過就直接共用
    // 快取，不重打。
    queryKey: ['stock', debouncedId],
    // enabled 已排除 knownInDaily，這裡打的一定是不在追蹤清單裡的代號 → 傳空 Set 讓
    // fetchStockDetail 直接跳過注定 404 的靜態檔、走 /api/analyze。
    queryFn: () => fetchStockDetail(debouncedId, new Set<string>()),
    enabled: isNew && !nameEditedByUser && !knownInDaily && STOCK_ID_RE.test(debouncedId),
    staleTime: 5 * 60 * 1000,
    retry: 0,
  })
  useEffect(() => {
    if (liveNameQuery.data && !nameEditedByUser) {
      setName(liveNameQuery.data.profile.name)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveNameQuery.data])

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
          <input
            id="hf-name"
            value={name}
            onChange={(e) => {
              setName(e.target.value)
              setNameEditedByUser(true)
            }}
            placeholder={isNew && liveNameQuery.isLoading ? '查詢名稱中…' : '例如 台積電'}
          />
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
