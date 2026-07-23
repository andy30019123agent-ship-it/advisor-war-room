import { useEffect, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { fetchDaily, fetchStockDetail } from '../lib/api'
import { loadTotalCapital, saveTotalCapital } from '../lib/settings'
import { formatShares } from '../lib/shares'
import { fmtPct, pctClass } from '../lib/format'
import { loadJournal, getStreakAlert, type JournalEntry } from '../lib/journal'
import { useQuotes, isLiveQuote } from '../lib/quotes'
import { useLedger } from '../lib/useLedger'
import { derivePortfolio, type QuoteMap } from '../lib/portfolio'
import { allocatePortfolioRisk, personalInstruction } from '../lib/personalAdvice'
import { FreshnessBadge } from '../components/FreshnessBadge'
import { LiveQuoteBadge } from '../components/LiveQuoteBadge'
import { StreakAlertBanner } from '../components/StreakAlertBanner'
import { JournalEntryFormModal } from '../components/JournalEntryFormModal'
import { JournalListModal } from '../components/JournalListModal'
import { IconEmptyBriefcase, IconPlus, IconChevron } from '../components/icons'
import type { PrimaryDecision, StockDetail } from '../types/contract'

// 自加持股若不在追蹤清單（daily.tracked）裡，daily.json 沒有它的現價/決策，改即時打
// fetchStockDetail（fallback /api/analyze 現算）補上。staleTime 拉到「當日」等級，同一天內
// 切分頁/重渲染不重打 API。追蹤清單內的持股也走 fetchStockDetail（同一支函式會自動選走
// 快速的靜態檔），為的是拿到完整 primary_decision——個人化建議要讀 tier_amount／
// position_delta／entry_condition，daily.json 的 tracked[].decision 只有縮影。
const STALE_TIME_TODAY = 12 * 60 * 60 * 1000

// 非追蹤持股的即時分析：最多同時 2 個併發、總數最多 8 檔（超過排隊）。一次全打會同時炸出
// 多支 /api/analyze 冷查（各自最久 20 幾秒），互搶時間又吃 FinMind 額度（聯測 2026-07-18 #3）。
const MAX_LIVE_CONCURRENT = 2
const MAX_LIVE_TOTAL = 8

export function Holdings() {
  const { ledger, setCash, setTag, refresh } = useLedger()
  const [totalCapital, setTotalCapital] = useState<number>(() => loadTotalCapital())
  const [journal, setJournal] = useState<JournalEntry[]>(() => loadJournal())
  const [quickJournalSeed, setQuickJournalSeed] = useState<{ stock_id: string; name: string } | null>(null)
  const [showJournalList, setShowJournalList] = useState(false)
  const [showNewTrade, setShowNewTrade] = useState(false)

  const { data: daily } = useQuery({ queryKey: ['daily'], queryFn: fetchDaily })

  // 先用「沒有報價」的投影拿到持股清單（要有清單才知道該查哪些報價），拿到報價後再算一次
  // 完整投影。兩次都是純函式，成本可忽略。
  const skeleton = derivePortfolio(ledger)
  const heldIds = skeleton.positions.map((p) => p.stock_id)

  const { data: quotes } = useQuotes(heldIds)

  const trackedIds = new Set((daily?.tracked ?? []).map((t) => t.id))
  const untracked = heldIds.filter((id) => !trackedIds.has(id))
  const liveEligible = untracked.slice(0, MAX_LIVE_TOTAL)
  const queuedIds = new Set(untracked.slice(MAX_LIVE_TOTAL))
  const liveEligibleIndex = new Map(liveEligible.map((id, i) => [id, i]))

  // 併發池：某檔一結算，佇列裡排在它後面、還沒開始跑的下一檔就補上這個併發名額。
  const [settledIds, setSettledIds] = useState<Set<string>>(new Set())

  const detailQueries = useQueries({
    queries: heldIds.map((id) => {
      if (trackedIds.has(id)) {
        return {
          queryKey: ['stock', id],
          queryFn: () => fetchStockDetail(id, trackedIds),
          enabled: !!daily,
          staleTime: STALE_TIME_TODAY,
          retry: 1,
        }
      }
      const idx = liveEligibleIndex.get(id)
      if (idx === undefined) {
        return { queryKey: ['stock', id], queryFn: () => fetchStockDetail(id, trackedIds), enabled: false }
      }
      const pendingAhead = liveEligible.slice(0, idx).filter((other) => !settledIds.has(other)).length
      return {
        queryKey: ['stock', id],
        queryFn: () => fetchStockDetail(id, trackedIds),
        enabled: !!daily && (settledIds.has(id) || pendingAhead < MAX_LIVE_CONCURRENT),
        staleTime: STALE_TIME_TODAY,
        retry: 1,
      }
    }),
  })
  const detailById = new Map(heldIds.map((id, i) => [id, detailQueries[i]]))

  useEffect(() => {
    setSettledIds((prev) => {
      let next: Set<string> | null = null
      liveEligible.forEach((id) => {
        const q = detailById.get(id)
        if (q && (q.isSuccess || q.isError) && !prev.has(id)) {
          if (!next) next = new Set(prev)
          next.add(id)
        }
      })
      return next ?? prev
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detailQueries])

  // 真正拿來算的報價：盤中即時價優先，退回 daily.tracked 收盤價，再退回即時分析的收盤價。
  const quoteMap: QuoteMap = {}
  const priceIsLive: Record<string, boolean> = {}
  for (const id of heldIds) {
    const q = quotes?.[id]
    const live = isLiveQuote(q)
    const detail = detailById.get(id)?.data as StockDetail | undefined
    const tracked = daily?.tracked.find((t) => t.id === id)
    quoteMap[id] = live ? q.price : (tracked?.close ?? detail?.price.close ?? null)
    priceIsLive[id] = live
  }

  const portfolio = derivePortfolio(ledger, quoteMap)
  const streak = getStreakAlert(journal)
  const guidance = daily?.exposure_guidance ?? null

  const engineByStock: Record<string, PrimaryDecision | null | undefined> = {}
  for (const id of heldIds) {
    engineByStock[id] = (detailById.get(id)?.data as StockDetail | undefined)?.primary_decision
  }
  // 超額曝險只算一次再分配到個股——不然每張卡各自算「賣掉全部超額」，照做會砍三倍。
  const allocation = allocatePortfolioRisk(portfolio, guidance, engineByStock)

  function handleJournalChanged(entries: JournalEntry[]) {
    setJournal(entries)
    refresh() // 交易寫進帳本後，持股/現金/曝險立刻重算——這就是 Andy 要的「連動」
  }

  function handleCapitalChange(n: number) {
    setTotalCapital(n)
    saveTotalCapital(n)
  }

  const cashUnset = ledger.opening.cash === 0 && !ledger.events.some((e) => e.type === 'cash_adjust')

  return (
    <main className="screen">
      <header className="page-header">
        <div className="top-row">
          {daily ? <FreshnessBadge dataDate={daily.meta.data_date} generatedAt={daily.meta.generated_at} /> : <span />}
        </div>
        <div className="large-title">持股</div>
      </header>

      <StreakAlertBanner entries={journal} />

      <div className="group" style={{ padding: '0 16px 8px', display: 'flex', justifyContent: 'flex-end' }}>
        <button type="button" className="journal-entry-btn" onClick={() => setShowJournalList(true)}>
          交易日誌
        </button>
      </div>

      {portfolio.positions.length === 0 ? (
        <div className="empty-state">
          <IconEmptyBriefcase />
          <div className="title">還沒有持股紀錄</div>
          <div className="desc">記一筆買進，持股、成本、現金和曝險就會自動算出來。</div>
          <div className="group" style={{ width: '100%', padding: '8px 0 0' }}>
            <button type="button" className="btn-primary" onClick={() => setShowNewTrade(true)}>
              <IconPlus /> 記一筆交易
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="group">
            <div className="summary-card">
              <div className="summary-inner">
                <div className="portfolio-grid">
                  <Stat label="總資產" value={fmtMoney(portfolio.totalAssets)} />
                  <Stat
                    label="未實現損益"
                    value={portfolio.unrealizedPnl == null ? '—' : signed(portfolio.unrealizedPnl)}
                    tone={tone(portfolio.unrealizedPnl)}
                    hint={portfolio.missingPriceIds.length > 0 ? '（部分持股缺報價未計入）' : undefined}
                  />
                  <Stat label="已實現損益" value={signed(portfolio.realizedPnl)} tone={tone(portfolio.realizedPnl)} />
                  <Stat label="持股市值" value={fmtMoney(portfolio.totalMarketValue)} />
                  <Stat
                    label="股票曝險"
                    value={portfolio.exposurePct != null ? `${portfolio.exposurePct.toFixed(1)}%` : '—'}
                  />
                  <Stat label="現金水位" value={portfolio.cashPct != null ? `${portfolio.cashPct.toFixed(1)}%` : '—'} />
                </div>
              </div>
              <div className="hairline" />
              <div className="capital-row">
                <span className="capital-label">現金餘額</span>
                <NumberInput value={Math.round(portfolio.cash)} onChange={setCash} suffix="元" />
              </div>
              {cashUnset && (
                <div className="exposure-warn">
                  還沒設定現金餘額——曝險與可加碼金額要有它才準，點上面的數字填入。
                </div>
              )}
              {portfolio.issues.map((issue, i) => (
                <div className="exposure-warn" key={i}>
                  {issue.message}
                </div>
              ))}
            </div>
          </div>

          <div className="group">
            <div className="list-card">
              <div className="capital-row">
                <span className="capital-label">目標資金規模</span>
                <NumberInput value={totalCapital} onChange={handleCapitalChange} suffix="元" />
              </div>
              <div style={{ padding: '0 16px 12px', fontSize: 11, color: 'var(--text-soft)' }}>
                曝險與現金水位已改用實際總資產（現金＋市值）計算；這個數字只用於試單上限對照。
              </div>
            </div>
          </div>

          <div className="search-wrap">
            <button type="button" className="btn-primary" onClick={() => setShowNewTrade(true)}>
              <IconPlus /> 記一筆交易
            </button>
          </div>

          <div className="group-title">我的持股</div>
          <div className="group">
            <div className="list-card">
              {portfolio.positions.map((p) => {
                const detailQuery = queuedIds.has(p.stock_id) ? undefined : detailById.get(p.stock_id)
                const detail = detailQuery?.data as StockDetail | undefined
                const price = quoteMap[p.stock_id]
                const pnlPct = price != null && p.avgCost > 0 ? ((price - p.avgCost) / p.avgCost) * 100 : null
                const pnlKlass = pnlPct == null ? 'flat' : pnlPct > 0 ? 'up' : pnlPct < 0 ? 'down' : 'flat'
                const quote = quotes?.[p.stock_id]
                const live = isLiveQuote(quote)
                const changePct = live
                  ? quote.change_pct
                  : (daily?.tracked.find((t) => t.id === p.stock_id)?.change_pct ?? detail?.price.change_pct ?? null)

                const advice = personalInstruction({
                  engine: detail?.primary_decision,
                  position: p,
                  price: price ?? null,
                  priceIsLive: priceIsLive[p.stock_id],
                  priceDate: daily?.meta.data_date,
                  portfolio,
                  guidance,
                  streak,
                  allocation: allocation[p.stock_id] ?? 0,
                  totalCapital,
                })

                return (
                  <div className="list-row" key={p.stock_id}>
                    <div className="row-top">
                      <div className="row-name">
                        <span className="name">{p.name}</span>
                        <span className={`badge${p.tag === 'long' ? ' core' : ''}`}>
                          {p.tag === 'long' ? '長期' : '波段'}
                        </span>
                        <span className="code mono">{p.stock_id}</span>
                      </div>
                      {detailQuery?.isLoading ? (
                        <span className="skeleton skeleton-line" style={{ width: 48, height: 19, marginBottom: 0 }} />
                      ) : (
                        <div className="row-price-block">
                          {live && <LiveQuoteBadge at={quote.at} />}
                          <div className={`row-price mono ${pnlKlass === 'up' ? 'up' : pnlKlass === 'down' ? 'down' : ''}`}>
                            {price != null ? price.toLocaleString() : '—'}
                          </div>
                          <span className={`row-change mono ${pctClass(changePct)}`}>今日 {fmtPct(changePct)}</span>
                        </div>
                      )}
                    </div>

                    <div className="row-tags">
                      <span className="pill neutral">
                        {formatShares(p.shares)} ／ 均價 {Math.round(p.avgCost * 100) / 100}
                      </span>
                      <span className={`pnl ${pnlKlass}`}>
                        {pnlPct != null ? `${pnlPct > 0 ? '+' : ''}${pnlPct.toFixed(1)}%` : '—'}
                      </span>
                      {p.weightPct != null && <span className="pill neutral">佔 {p.weightPct.toFixed(1)}%</span>}
                    </div>

                    {detailQuery?.isLoading ? (
                      <div className="row-tags" style={{ marginTop: 8 }}>
                        <span className="skeleton skeleton-line" style={{ width: 200, height: 22, marginBottom: 0 }} />
                      </div>
                    ) : (
                      <>
                        <p className="holding-advice-text">{advice.instruction}</p>
                        <details className="plan-disclosure">
                          <summary>
                            為什麼
                            <IconChevron />
                          </summary>
                          <div className="plan-list">
                            <div className="plan-step">
                              <span className="plan-trigger">規則</span>
                              <span className="plan-act">→ {advice.ruleId}</span>
                            </div>
                            {advice.reasons.map((r, i) => (
                              <div className="plan-step" key={`r${i}`}>
                                <span className="plan-trigger">依據</span>
                                <span className="plan-act">→ {r}</span>
                              </div>
                            ))}
                            {Object.entries(advice.inputsUsed).map(([k, v]) => (
                              <div className="plan-step" key={k}>
                                <span className="plan-trigger">{k}</span>
                                <span className="plan-act">→ {typeof v === 'number' ? v.toLocaleString() : v}</span>
                              </div>
                            ))}
                          </div>
                        </details>
                      </>
                    )}

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 }}>
                      <button
                        type="button"
                        className="journal-entry-btn"
                        onClick={() => setTag(p.stock_id, p.tag === 'long' ? 'swing' : 'long')}
                      >
                        改為{p.tag === 'long' ? '波段' : '長期'}
                      </button>
                      <button
                        type="button"
                        className="journal-entry-btn"
                        onClick={() => setQuickJournalSeed({ stock_id: p.stock_id, name: p.name })}
                      >
                        記一筆
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </>
      )}

      {(quickJournalSeed || showNewTrade) && (
        <JournalEntryFormModal
          seed={quickJournalSeed}
          onClose={() => {
            setQuickJournalSeed(null)
            setShowNewTrade(false)
          }}
          onSaved={handleJournalChanged}
          onDeleted={handleJournalChanged}
        />
      )}

      {showJournalList && (
        <JournalListModal entries={journal} onClose={() => setShowJournalList(false)} onChange={handleJournalChanged} />
      )}
    </main>
  )
}

function Stat({ label, value, tone, hint }: { label: string; value: string; tone?: string; hint?: string }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className={`stat-value mono ${tone ?? ''}`}>{value}</span>
      {hint && <span style={{ fontSize: 11, color: 'var(--text-soft)' }}>{hint}</span>}
    </div>
  )
}

function fmtMoney(n: number): string {
  return Math.round(n).toLocaleString()
}

function signed(n: number | null): string {
  if (n == null) return '—'
  return `${n > 0 ? '+' : ''}${Math.round(n).toLocaleString()}`
}

function tone(n: number | null): string {
  if (n == null || n === 0) return ''
  return n > 0 ? 'up' : 'down'
}

// 非編輯態顯示格式化金額（按鈕），點下去變數字輸入；blur／Enter 才提交，避免每個按鍵都寫檔。
function NumberInput({ value, onChange, suffix }: { value: number; onChange: (n: number) => void; suffix?: string }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(String(value))

  useEffect(() => {
    if (!editing) setDraft(String(value))
  }, [value, editing])

  function commit() {
    const n = Number(draft)
    if (!Number.isFinite(n) || n < 0) {
      setEditing(false)
      return
    }
    onChange(n)
    setEditing(false)
  }

  if (editing) {
    return (
      <input
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
      {value.toLocaleString()} {suffix}
    </button>
  )
}
