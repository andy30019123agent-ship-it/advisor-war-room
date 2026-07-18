import { useEffect, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { fetchDaily, fetchStockDetail } from '../lib/api'
import { loadHoldings, saveHolding, deleteHolding, type Holding } from '../lib/holdings'
import { loadTotalCapital, saveTotalCapital } from '../lib/settings'
import { formatShares, SHARES_PER_LOT } from '../lib/shares'
import { FreshnessBadge } from '../components/FreshnessBadge'
import { IconEmptyBriefcase, IconPlus, IconTrash, IconClose, IconChevron } from '../components/icons'
import type { Daily, StockDetail } from '../types/contract'

// 自加持股若不在追蹤清單（daily.tracked）裡，daily.json 沒有它的現價/決策，
// 改即時打 fetchStockDetail（fallback /api/analyze 現算）補上。staleTime 拉到
// 「當日」等級，同一天內切分頁/重渲染不重打 API，只有隔天或手動重整才會再抓。
// 追蹤清單內的持股也一併走 fetchStockDetail（同一支函式會自動選走快速的靜態檔），
// 為的是拿到 primary_decision.advice（持有/空手雙版建議＋計畫階梯，v1.1）——daily.json
// 的 tracked[].decision 只有縮影，沒有 advice。
const STALE_TIME_TODAY = 12 * 60 * 60 * 1000

// 非追蹤持股的即時分析：最多同時 2 個併發、總數最多 8 檔（超過排隊）。追蹤清單內的持股
// 讀的是預算好的靜態檔（快、不耗 FinMind 額度），不受這個併發池限制。持股清單沒上限，
// 一次全打會同時炸出多支 /api/analyze 冷查（各自最久 20 幾秒），互搶時間又吃 FinMind 額度
// （聯測 2026-07-18 #3）。
const MAX_LIVE_CONCURRENT = 2
const MAX_LIVE_TOTAL = 8

export function Holdings() {
  const [holdings, setHoldings] = useState<Holding[]>(() => loadHoldings())
  const [editing, setEditing] = useState<Holding | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [totalCapital, setTotalCapital] = useState<number>(() => loadTotalCapital())

  const { data: daily } = useQuery({ queryKey: ['daily'], queryFn: fetchDaily })

  const trackedIds = new Set((daily?.tracked ?? []).map((t) => t.id))
  const untrackedHoldings = holdings.filter((h) => !trackedIds.has(h.id))
  const liveEligible = untrackedHoldings.slice(0, MAX_LIVE_TOTAL)
  const queuedIds = new Set(untrackedHoldings.slice(MAX_LIVE_TOTAL).map((h) => h.id))
  const liveEligibleIndex = new Map(liveEligible.map((h, i) => [h.id, i]))

  // 併發池：settledIds 記錄「已經有結果（成功或失敗）」的持股。某檔一結算，佇列裡排在
  // 它後面、還沒開始跑的下一檔就補上這個併發名額——不是死板地固定跑前兩個，而是同時最多
  // 兩個在飛行中。只算非追蹤持股（追蹤持股走靜態檔，不進池）。
  const [settledIds, setSettledIds] = useState<Set<string>>(new Set())

  const detailQueries = useQueries({
    queries: holdings.map((h) => {
      if (trackedIds.has(h.id)) {
        // 追蹤清單內：靜態檔，快，daily 一到就能打，不受併發池限制。
        return {
          queryKey: ['stock', h.id],
          queryFn: () => fetchStockDetail(h.id, trackedIds),
          enabled: !!daily,
          staleTime: STALE_TIME_TODAY,
          retry: 1,
        }
      }
      const idx = liveEligibleIndex.get(h.id)
      if (idx === undefined) {
        // 排隊中（超過 MAX_LIVE_TOTAL）：query 存在但 enabled 永遠 false，不打 API。
        return {
          queryKey: ['stock', h.id],
          queryFn: () => fetchStockDetail(h.id, trackedIds),
          enabled: false,
        }
      }
      const pendingAhead = liveEligible.slice(0, idx).filter((h2) => !settledIds.has(h2.id)).length
      return {
        queryKey: ['stock', h.id],
        queryFn: () => fetchStockDetail(h.id, trackedIds),
        enabled: !!daily && (settledIds.has(h.id) || pendingAhead < MAX_LIVE_CONCURRENT),
        staleTime: STALE_TIME_TODAY,
        retry: 1,
      }
    }),
  })
  const detailById = new Map(holdings.map((h, i) => [h.id, detailQueries[i]]))

  useEffect(() => {
    setSettledIds((prev) => {
      let next: Set<string> | null = null
      liveEligible.forEach((h) => {
        const q = detailById.get(h.id)
        if (q && (q.isSuccess || q.isError) && !prev.has(h.id)) {
          if (!next) next = new Set(prev)
          next.add(h.id)
        }
      })
      return next ?? prev
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detailQueries])

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

  function handleCapitalChange(n: number) {
    setTotalCapital(n)
    saveTotalCapital(n)
  }

  // 每檔持股彙整一次（現價／損益／建議文案／計畫階梯），組合總覽卡與清單共用同一份計算。
  const enriched = holdings.map((h) => {
    const tracked = daily?.tracked.find((t) => t.id === h.id)
    const isTracked = trackedIds.has(h.id)
    const isQueued = !isTracked && queuedIds.has(h.id)
    const live = !isQueued ? detailById.get(h.id) : undefined
    const detail = live?.data as StockDetail | undefined

    const currentPrice = tracked?.close ?? detail?.price.close ?? null
    const pnlPct =
      currentPrice != null && h.costPrice > 0 ? ((currentPrice - h.costPrice) / h.costPrice) * 100 : null

    const advice = detail?.primary_decision.advice
    const action = detail?.primary_decision.action ?? tracked?.decision.action
    const actionText = advice?.holder.action_text
    const plan = advice?.holder.plan ?? []
    const defensePrice = detail?.primary_decision.defense_price ?? tracked?.decision.defense_price ?? null

    // 用來算組合總覽：現價未知時退回成本價估市值，避免曝險被低估成 0（優於直接漏算）。
    const marketValue = (currentPrice ?? h.costPrice) * h.shares
    const costBasis = h.costPrice * h.shares

    return {
      holding: h,
      currentPrice,
      pnlPct,
      action,
      actionText,
      plan,
      defensePrice,
      marketValue,
      costBasis,
      isLiveLoading: !!live?.isLoading,
      isLiveError: !!live?.isError,
      isQueued,
    }
  })

  const totalMarketValue = enriched.reduce((sum, e) => sum + e.marketValue, 0)
  const totalCost = enriched.reduce((sum, e) => sum + e.costBasis, 0)
  const totalPnlAmt = totalMarketValue - totalCost
  const totalPnlPct = totalCost > 0 ? (totalPnlAmt / totalCost) * 100 : null
  const exposurePct = totalCapital > 0 ? (totalMarketValue / totalCapital) * 100 : null
  const cashPct = exposurePct != null ? Math.max(0, 100 - exposurePct) : null
  const maxEquityPct = daily?.exposure_guidance?.max_equity_pct ?? null
  const overExposed = maxEquityPct != null && exposurePct != null && exposurePct > maxEquityPct

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
          <div className="group">
            <div className={`summary-card${overExposed ? ' warn' : ''}`}>
              <div className="summary-inner">
                <div className="portfolio-grid">
                  <div className="stat">
                    <span className="stat-label">總市值</span>
                    <span className="stat-value mono">{Math.round(totalMarketValue).toLocaleString()}</span>
                  </div>
                  <div className="stat">
                    <span className="stat-label">總損益</span>
                    <span className={`stat-value mono ${totalPnlAmt > 0 ? 'up' : totalPnlAmt < 0 ? 'down' : ''}`}>
                      {totalPnlAmt > 0 ? '+' : ''}
                      {Math.round(totalPnlAmt).toLocaleString()}
                      {totalPnlPct != null && ` (${totalPnlPct > 0 ? '+' : ''}${totalPnlPct.toFixed(1)}%)`}
                    </span>
                  </div>
                  <div className="stat">
                    <span className="stat-label">股票曝險</span>
                    <span className="stat-value mono">{exposurePct != null ? `${exposurePct.toFixed(1)}%` : '—'}</span>
                  </div>
                  <div className="stat">
                    <span className="stat-label">現金水位</span>
                    <span className="stat-value mono">{cashPct != null ? `${cashPct.toFixed(1)}%` : '—'}</span>
                  </div>
                </div>
              </div>
              {overExposed && (
                <>
                  <div className="hairline" />
                  <div className="exposure-warn">超過建議上限 {maxEquityPct}%</div>
                </>
              )}
            </div>
          </div>

          <div className="group">
            <div className="list-card">
              <div className="capital-row">
                <span className="capital-label">總資金設定</span>
                <CapitalInput value={totalCapital} onChange={handleCapitalChange} />
              </div>
            </div>
          </div>

          <div className="search-wrap">
            <button type="button" className="btn-primary" onClick={openNew}>
              <IconPlus /> 新增持股
            </button>
          </div>
          <div className="group-title">我的持股</div>
          <div className="group">
            <div className="list-card">
              {enriched.map((e) => {
                const h = e.holding
                const pnlClass = e.pnlPct == null ? 'flat' : e.pnlPct > 0 ? 'up' : e.pnlPct < 0 ? 'down' : 'flat'
                return (
                  <div className="list-row" key={h.id}>
                    <button
                      type="button"
                      onClick={() => openEdit(h)}
                      style={{ width: '100%', textAlign: 'left', background: 'none', border: 'none', padding: 0 }}
                    >
                      <div className="row-top">
                        <div className="row-name">
                          <span className="name">{h.name || h.id}</span>
                          <span className="code mono">{h.id}</span>
                        </div>
                        {e.isLiveLoading ? (
                          <span className="skeleton skeleton-line" style={{ width: 48, height: 19, marginBottom: 0 }} />
                        ) : (
                          <div className={`row-price mono ${pnlClass === 'up' ? 'up' : pnlClass === 'down' ? 'down' : ''}`}>
                            {e.currentPrice != null ? e.currentPrice.toLocaleString() : '—'}
                          </div>
                        )}
                      </div>
                      <div className="row-tags">
                        <span className="pill neutral">
                          {formatShares(h.shares)} ／ 成本 {h.costPrice.toLocaleString()}
                        </span>
                        {!e.isLiveLoading && (
                          <span className={`pnl ${pnlClass}`}>
                            {e.pnlPct != null ? `${e.pnlPct > 0 ? '+' : ''}${e.pnlPct.toFixed(1)}%` : '—'}
                          </span>
                        )}
                      </div>
                      {e.isLiveLoading && (
                        <div className="row-tags" style={{ marginTop: 8 }}>
                          <span className="skeleton skeleton-line" style={{ width: 96, height: 22, marginBottom: 0 }} />
                        </div>
                      )}
                      {e.isLiveError && (
                        <div className="row-tags" style={{ marginTop: 8 }}>
                          <span className="pill neutral">暫時抓不到分析（稍後自動重試）</span>
                        </div>
                      )}
                      {e.isQueued && (
                        <div className="row-tags" style={{ marginTop: 8 }}>
                          <span className="pill neutral">分析排隊中</span>
                        </div>
                      )}
                      {!e.isLiveLoading && !e.isLiveError && (
                        <>
                          {e.actionText ? (
                            <p className="holding-advice-text">{e.actionText}</p>
                          ) : e.action ? (
                            <div className="row-tags" style={{ marginTop: 8 }}>
                              <span className="pill">{e.action}</span>
                            </div>
                          ) : null}
                          {e.defensePrice != null && (
                            <div className="row-tags" style={{ marginTop: 8 }}>
                              <span className="pill stop">防守價 {e.defensePrice.toLocaleString()}</span>
                            </div>
                          )}
                        </>
                      )}
                    </button>
                    {e.plan.length > 0 && (
                      <details className="plan-disclosure">
                        <summary>
                          查看計畫階梯
                          <IconChevron />
                        </summary>
                        <div className="plan-list">
                          {e.plan.map((p, i) => (
                            <div className="plan-step" key={i}>
                              <span className="plan-trigger">{p.trigger}</span>
                              <span className="plan-act">→ {p.act}</span>
                            </div>
                          ))}
                        </div>
                      </details>
                    )}
                  </div>
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

// 總資金：非編輯態顯示格式化金額（按鈕），點下去變數字輸入；blur／Enter 才存檔，
// 避免每個按鍵都寫 localStorage。
function CapitalInput({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(String(value))

  useEffect(() => {
    if (!editing) setDraft(String(value))
  }, [value, editing])

  function commit() {
    const n = Number(draft)
    if (Number.isFinite(n) && n > 0) onChange(n)
    setEditing(false)
  }

  if (editing) {
    return (
      <input
        id="total-capital"
        name="total-capital"
        className="capital-input"
        type="number"
        inputMode="numeric"
        value={draft}
        autoFocus
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit()
        }}
      />
    )
  }

  return (
    <button type="button" className="capital-value" onClick={() => setEditing(true)}>
      {value.toLocaleString()} 元
    </button>
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
  // shares 一律用「實際股數」當單一事實來源；unit 只決定輸入框顯示／解讀的單位。
  const [shares, setShares] = useState<number>(initial.shares || 0)
  const [unit, setUnit] = useState<'lot' | 'share'>(
    initial.shares > 0 && initial.shares % SHARES_PER_LOT !== 0 ? 'share' : 'lot'
  )
  const [costPrice, setCostPrice] = useState(initial.costPrice ? String(initial.costPrice) : '')
  // 使用者只要手動動過名稱欄位一次，就不再自動覆蓋（找不到就留手動輸入，聯測 07-18 #9）。
  const [nameEditedByUser, setNameEditedByUser] = useState(!isNew && initial.name.length > 0)

  const sharesDisplay = shares > 0 ? String(unit === 'lot' ? shares / SHARES_PER_LOT : shares) : ''

  function handleSharesInput(v: string) {
    if (v.trim() === '') {
      setShares(0)
      return
    }
    const n = Number(v)
    if (Number.isNaN(n)) return
    setShares(unit === 'lot' ? Math.round(n * SHARES_PER_LOT) : Math.round(n))
  }

  const canSave = id.trim().length > 0 && shares > 0 && Number(costPrice) > 0
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
      shares,
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
          <div className="shares-row">
            <input
              id="hf-shares"
              type="number"
              inputMode="decimal"
              value={sharesDisplay}
              onChange={(e) => handleSharesInput(e.target.value)}
              placeholder={unit === 'lot' ? '1' : '1000'}
              style={{ flex: 1 }}
            />
            <div className="unit-toggle">
              <button type="button" className={unit === 'lot' ? 'active' : ''} onClick={() => setUnit('lot')}>
                張
              </button>
              <button type="button" className={unit === 'share' ? 'active' : ''} onClick={() => setUnit('share')}>
                股
              </button>
            </div>
          </div>
          {shares > 0 && <div className="shares-hint">＝ {formatShares(shares)}</div>}
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
