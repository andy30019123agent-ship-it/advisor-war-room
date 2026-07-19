import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchDaily, fetchStockDetail, NotFoundError, SchemaMismatchError } from '../lib/api'
import { loadHoldings } from '../lib/holdings'
import { formatShares, SHARES_PER_LOT } from '../lib/shares'
import { fmtPct, pctClass } from '../lib/format'
import { loadRecentSearches, addRecentSearch, type RecentSearch } from '../lib/recentSearches'
import { loadJournal, getLossStreak, type JournalEntry } from '../lib/journal'
import { applyCooldown } from '../lib/cooldown'
import { IconSearch } from '../components/icons'
import { ForecastFan } from '../components/ForecastFan'
import { ShortScenarios } from '../components/ShortScenarios'
import { GlossaryCard } from '../components/GlossaryCard'
import { PicksSection } from '../components/PicksSection'
import { TrackButton } from '../components/TrackButton'
import { JournalEntryFormModal } from '../components/JournalEntryFormModal'
import { CandleChart } from '../components/CandleChart'
import { MidLongReads } from '../components/MidLongReads'
import { LiveQuoteBadge } from '../components/LiveQuoteBadge'
import { loadWatchlist } from '../lib/watchlist'
import { useQuotes, isLiveQuote, isIntradayDefenseBreach } from '../lib/quotes'
import type { Daily, StockDetail } from '../types/contract'

export function StockSearch() {
  const [queryId, setQueryId] = useState<string | null>(null)
  const [inputValue, setInputValue] = useState('')
  // 最近查過（速修 4.）：查到新的一筆就記下來，chips 顯示在搜尋框下方可點重查。
  const [recentSearches, setRecentSearches] = useState<RecentSearch[]>(() => loadRecentSearches())
  // C 包・冷靜期落地（契約 v1.6 執行鏈路節）：載入 journal 算連敗 streak，決策卡部位金額
  // 據此減半／暫停顯示；「記一筆」存檔後要重算，所以用 state 存、onSaved 時更新。
  const [journal, setJournal] = useState<JournalEntry[]>(() => loadJournal())

  // daily.json 反正各分頁都會載、有共用快取；先知道追蹤清單再決定要不要試靜態檔，
  // 省一次注定 404 的請求（聯測 2026-07-18 #3/#8）。
  const { data: daily } = useQuery({ queryKey: ['daily'], queryFn: fetchDaily })
  // daily 還沒回來時給 undefined（不是空 Set！）：fetchStockDetail 收到 undefined 會退回
  // 舊行為（先試靜態檔、404 才 fallback），避免把「還不知道」誤判成「確定不在追蹤清單」。
  const trackedIds = daily
    ? new Set([...daily.tracked.map((t) => t.id), ...daily.watch.map((w) => w.id)])
    : undefined

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['stock', queryId],
    queryFn: () => fetchStockDetail(queryId!, trackedIds),
    enabled: queryId !== null,
  })

  // 查成功才算「查過」，記進最近查過清單（查無、查失敗都不記）。
  useEffect(() => {
    if (data) {
      setRecentSearches(addRecentSearch(data.profile.id, data.profile.name))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  function submit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = inputValue.trim()
    if (!trimmed) return
    setQueryId(trimmed)
  }

  function searchAgain(id: string) {
    setInputValue(id)
    setQueryId(id)
    window.scrollTo({ top: 0 })
  }

  return (
    <main className="screen">
      <header className="page-header">
        <div className="large-title">查股票</div>
      </header>

      <form className="search-wrap" onSubmit={submit}>
        <div className="search-bar">
          <IconSearch />
          <input
            id="stock-search-input"
            name="stock-search"
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

      {recentSearches.length > 0 && (
        <div className="recent-chips-wrap">
          <div className="recent-chips">
            {recentSearches.map((r) => (
              <button type="button" key={r.id} className="chip" onClick={() => searchAgain(r.id)}>
                {r.name || r.id} <span className="mono">{r.id}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <PicksSection daily={daily} collapsed={queryId !== null} onSelectStock={searchAgain} journal={journal} />

      {queryId === null && (
        <>
          <div className="empty-state">
            <IconSearch size={40} />
            <div className="title">輸入代號開始分析</div>
            <div className="desc">會給你一句話結論、防守價，和完整的證據拆解。</div>
          </div>
          <div className="group">
            <div className="list-card">
              <GlossaryCard />
            </div>
          </div>
        </>
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

      {data && <StockDetailView detail={data} daily={daily} journal={journal} onJournalChange={setJournal} />}
    </main>
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

// 負 R/R 白話（速修 3.）：散戶看不懂「R/R -10.39」在講什麼（07-19 深度使用報告點名），
// 依數值分級給白話一句話。R/R < 0 代表連最好情況能賺的都比可能賠的少，比 0~0.5 更嚴重，
// 用詞要更重（不宜追價 vs 先觀望較穩）。
function rrWarnText(rr: number): string | null {
  if (rr < 0) return '⚠ 上檔空間已用盡，不宜追價'
  if (rr < 0.5) return '⚠ 上檔空間有限，划不來，先觀望較穩'
  return null
}

// 持有／空手雙版建議（契約 v1.1 primary_decision.advice）：預設依 localStorage 持股清單
// 判斷使用者是否持有這檔，自動選對應分頁；沒有 advice 欄位（舊資料／schema 尚未補上）
// 就退回原本的 readable_reason 單版文案。
function AdviceSection({ detail }: { detail: StockDetail }) {
  const { profile, primary_decision: pd } = detail
  const isHolder = loadHoldings().some((h) => h.id === profile.id)
  const [variant, setVariant] = useState<'holder' | 'nonholder'>(isHolder ? 'holder' : 'nonholder')

  if (!pd.advice) {
    return <div className="decision-reason">{pd.readable_reason}</div>
  }

  const active = pd.advice[variant]

  return (
    <>
      <div className="segment-control">
        <button type="button" className={variant === 'holder' ? 'active' : ''} onClick={() => setVariant('holder')}>
          我有持股
        </button>
        <button type="button" className={variant === 'nonholder' ? 'active' : ''} onClick={() => setVariant('nonholder')}>
          我還沒買
        </button>
      </div>
      <div className="decision-reason">{active.action_text}</div>
      {active.plan.length > 0 && (
        <div className="plan-list" style={{ padding: '0 16px 14px' }}>
          {active.plan.map((p, i) => (
            <div className="plan-step" key={i}>
              <span className="plan-trigger">{p.trigger}</span>
              <span className="plan-act">→ {p.act}</span>
            </div>
          ))}
        </div>
      )}
    </>
  )
}

// 術語 tooltip：點了才展開一句白話解釋，用原生 <details> 免額外狀態管理。
function TermTooltip({ label, explain }: { label: string; explain: string }) {
  return (
    <details className="term-tooltip">
      <summary>
        {label} <span className="info-dot">ⓘ</span>
      </summary>
      <p>{explain}</p>
    </details>
  )
}

// 決策卡內的一列 k/v，可點開看白話解釋（防守價、R/R 都用這個）。
function TermRow({ label, value, explain, valueClass }: { label: string; value: string; explain: string; valueClass?: string }) {
  return (
    <details className="term-row">
      <summary className="decision-meta-row">
        <span className="k">
          {label} <span className="info-dot">ⓘ</span>
        </span>
        <span className={`v ${valueClass ?? ''}`}>{value}</span>
      </summary>
      <p className="term-explain">{explain}</p>
    </details>
  )
}

function StockDetailView({
  detail,
  daily,
  journal,
  onJournalChange,
}: {
  detail: StockDetail
  daily: Daily | undefined
  journal: JournalEntry[]
  onJournalChange: (entries: JournalEntry[]) => void
}) {
  const { profile, price, primary_decision: pd, context, evidence } = detail
  // 禁新倉時不對空手者秀部位金額（實戰走查任務 4）：大盤禁新倉＋使用者沒持有這檔＝這時秀
  // 「20 萬部位」會誘導在該空手時進場，改顯示「—（禁新倉）」。資料保留，只在顯示層處理；
  // 持有者仍看得到自己既有部位大小，不受影響。
  const gateBanned = daily?.exposure_guidance?.new_position === '禁止新增部位'
  const isHolder = loadHoldings().some((h) => h.id === profile.id)
  const suppressPosition = gateBanned && !isHolder

  // 盤中現價即時化（契約 v1.7 App 行為節）：對「持股∪監控∪當前查詢股」刷新，這裡查詢股
  // 就是 profile.id。stale=false 才覆蓋顯示；分析結論（primary_decision 等）不因盤中價
  // 重算——只換上面這一格數字＋徽章。
  const quoteIds = Array.from(new Set([...loadHoldings().map((h) => h.id), ...loadWatchlist(), profile.id]))
  const { data: quotes } = useQuotes(quoteIds)
  const quote = quotes?.[profile.id]
  const live = isLiveQuote(quote)
  const displayClose = live ? quote.price : price.close
  const displayChangePct = live ? quote.change_pct : price.change_pct

  // C 包・冷靜期落地（契約 v1.6 執行鏈路節）：連續停損 streak≥2 部位金額減半＋「冷靜期」
  // amber badge；≥3 用「暫停新倉」red badge 取代金額。只在真的有部位金額可顯示時才套用
  // （suppressPosition／空手時本來就沒有金額，套冷靜期沒有意義）。
  const streak = getLossStreak(journal)
  const cooldown =
    !suppressPosition && pd.position.tier_amount > 0 ? applyCooldown(pd.position.tier_amount, streak) : null

  // 誠實揭露（大檢查2 Y1）：盤中即時價已跌破防守價，但防守價本身的失效判定以收盤為準——
  // 兩個基準同框時要明講，不要讓使用者把「盤中暫破」誤讀成「劇本已經判定跌破」。
  const intradayBreach = isIntradayDefenseBreach(live, displayClose, pd.defense_price)

  const [journalSeed, setJournalSeed] = useState<{ stock_id: string; name: string; price?: number } | null>(null)

  return (
    <>
      <TrackButton stockId={profile.id} daily={daily} />

      <div className="group">
        <div className="decision-card">
          <div style={{ padding: '18px 16px 0', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <span style={{ fontSize: 17, fontWeight: 700 }}>
              {profile.name} <span className="code mono" style={{ fontSize: 13, color: 'var(--text-soft)' }}>{profile.id}</span>
            </span>
            <span className="row-price-block">
              {live && <LiveQuoteBadge at={quote.at} />}
              <span className={`row-price mono ${pctClass(displayChangePct)}`}>{formatNumber(displayClose)}</span>
              <span className={`row-change mono ${pctClass(displayChangePct)}`}>今日 {fmtPct(displayChangePct)}</span>
            </span>
          </div>
          <div className="decision-action">{pd.action}</div>

          <AdviceSection detail={detail} />

          <div style={{ padding: '0 16px 14px' }}>
            <button
              type="button"
              className="journal-entry-btn"
              onClick={() => setJournalSeed({ stock_id: profile.id, name: profile.name, price: price.close ?? undefined })}
            >
              記一筆
            </button>
          </div>

          <div className="hairline" />
          <div className="decision-meta-row">
            <span className="k">部位</span>
            <span className="v" style={{ display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'flex-end' }}>
              {suppressPosition
                ? '—（禁新倉）'
                : pd.position.tier_amount > 0
                  ? cooldown && cooldown.level === 'red'
                    ? '暫停新倉'
                    : cooldown && cooldown.level === 'amber'
                      ? `${(cooldown.amount! / 10000).toFixed(0)} 萬（冷靜期減半）`
                      : `${(pd.position.tier_amount / 10000).toFixed(0)} 萬（${formatShares(pd.position.lots * SHARES_PER_LOT + pd.position.odd_shares)}）`
                  : '空手'}
              {cooldown?.badgeText && (
                <span className={`badge ${cooldown.level === 'red' ? 'block' : 'amber'}`}>{cooldown.badgeText}</span>
              )}
            </span>
          </div>

          {pd.defense_explain ? (
            <TermRow
              label="防守價"
              value={formatNumber(pd.defense_price)}
              explain={pd.defense_explain}
              valueClass="risk"
            />
          ) : (
            <div className="decision-meta-row">
              <span className="k">防守價</span>
              <span className="v risk">{formatNumber(pd.defense_price)}</span>
            </div>
          )}
          {intradayBreach && (
            <p className="quote-breach-hint quote-breach-hint-block">盤中已觸及防守，以收盤確認為準</p>
          )}

          {context.rr != null && (
            <>
              <TermRow
                label="R/R"
                value={context.rr.toFixed(2)}
                explain="R/R（風險報酬比）＝預期能賺的空間 ÷ 可能賠的空間。例如 2 代表預期獲利大約是可能虧損的 2 倍，數字越高通常代表這筆進場越划算。"
              />
              {rrWarnText(context.rr) && <p className="rr-warn">{rrWarnText(context.rr)}</p>}
            </>
          )}

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

      <CandleChart
        ohlc={detail.ohlc}
        ma60={price.ma60}
        defensePrice={pd.defense_price}
        entryPrice={pd.entry_condition?.price ?? null}
        keyLevels={
          detail.short_scenarios?.status === 'ok' && detail.short_scenarios.key_levels
            ? [...detail.short_scenarios.key_levels.supports, ...detail.short_scenarios.key_levels.resistances]
            : []
        }
      />

      <ShortScenarios data={detail.short_scenarios} close={price.close} />

      <MidLongReads data={detail.mid_long_reads} />

      <ForecastFan forecast={detail.forecast} />

      <div className="group-title">證據拆解</div>
      <div className="group">
        <div className="list-card">
          <details className="disclosure">
            <summary>
              三燈號
              <ChevronGlyph />
            </summary>
            <div className="disclosure-body">
              <TermTooltip
                label="三燈號是什麼？"
                explain="紅黃綠三色分別評基本面、技術面、籌碼面目前的狀態：綠燈偏多、黃燈中性、紅燈偏空。三個燈一起看，才知道是三方一致還是彼此打架。"
              />
              <TermTooltip
                label="PER 分位是什麼？"
                explain="PER 分位＝目前本益比（股價 ÷ 每股盈餘）落在過去一段期間所有本益比中的百分位。分位越高代表現在股價相對歷史更貴，越低代表相對便宜。"
              />
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
                  {context.valuation.regime && (
                    <TermTooltip
                      label="regime（分位區間）是什麼？"
                      explain="regime 是這次估值參考的歷史區間長度，例如 3y＝近 3 年、5y＝近 5 年。區間越長，算出來的『合理價』越平滑，但也可能跟不上公司最近的變化。"
                    />
                  )}
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
              {evidence.news.map((n) => {
                const isSafeUrl = /^https?:\/\//i.test(n.url)
                return (
                  <p key={n.url}>
                    {isSafeUrl ? (
                      <a
                        href={n.url}
                        target="_blank"
                        rel="noreferrer"
                        style={{ color: 'var(--text)', textDecoration: 'underline' }}
                      >
                        {n.title}
                      </a>
                    ) : (
                      <span>{n.title}</span>
                    )}{' '}
                    — {n.source}
                  </p>
                )
              })}
            </div>
          </details>
        </div>
      </div>

      {journalSeed && (
        <JournalEntryFormModal
          seed={journalSeed}
          onClose={() => setJournalSeed(null)}
          onSaved={onJournalChange}
          onDeleted={onJournalChange}
        />
      )}
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
