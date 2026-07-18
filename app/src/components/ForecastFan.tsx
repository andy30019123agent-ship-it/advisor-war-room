import { useRef, useState } from 'react'
import type { Forecast, ForecastBand, ForecastEventMarker, ForecastHorizonKey } from '../types/contract'

// 預估走勢．機率扇形圖 2.0（契約 v1.3 forecast）。SVG 手繪，不裝圖表庫。
// 座標系：viewBox 固定像素，容器 width:100% 靠 viewBox 縮放，觸控/滑鼠座標
// 用 getBoundingClientRect() 換算回 viewBox 座標（見 handlePointerMove）。
//
// 版面分兩區：左 40%＝history（實際走勢），右 60%＝選定 horizon 的機率扇形。
// 兩區共用同一個 yScale（涵蓋全部 3 個 horizon 的機率帶＋history，固定不隨切換改變），
// 讓「歷史左半固定不動」在切換 1/3/6 月時成立；只有右側扇形的 xScale 定義域（0..horizon.days）
// 與帶狀資料會換。

const VB_W = 360
const VB_H = 220
const PAD_LEFT = 6
const PAD_RIGHT = 64
const PAD_TOP = 18
const PAD_BOTTOM = 34
const PLOT_W = VB_W - PAD_LEFT - PAD_RIGHT
const PLOT_H = VB_H - PAD_TOP - PAD_BOTTOM
const HISTORY_FRAC = 0.4

const TODAY_X = PAD_LEFT + PLOT_W * HISTORY_FRAC
const HISTORY_X0 = PAD_LEFT
const FORECAST_X1 = PAD_LEFT + PLOT_W

const HORIZON_LABELS: Record<ForecastHorizonKey, string> = { m1: '1 個月', m3: '3 個月', m6: '6 個月' }
const HORIZON_ORDER: ForecastHorizonKey[] = ['m1', 'm3', 'm6']

function fmt(n: number): string {
  return Math.round(n).toLocaleString()
}

// 短線三劇本卡（ShortScenarios）取代這裡當查股票頁主角，扇形圖降級成預設收合的
// 長線輔助區塊——用原生 <details> 免額外狀態管理，跟其他證據拆解區塊一致。
export function ForecastFan({ forecast }: { forecast: Forecast | null | undefined }) {
  return (
    <div className="group">
      <div className="list-card">
        <details className="disclosure">
          <summary>
            長線機率區間（1/3/6 個月模擬）
            <ChevronGlyph />
          </summary>
          <div className="disclosure-body forecast-disclosure-body">
            {!forecast ? (
              <div className="forecast-empty">資料更新中，暫無走勢模擬</div>
            ) : (
              <ForecastChart forecast={forecast} />
            )}
          </div>
        </details>
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

type HistoryHover = { kind: 'history'; d: number; close: number }
type ForecastHover = { kind: 'forecast'; band: ForecastBand }
type Hover = HistoryHover | ForecastHover

function ForecastChart({ forecast }: { forecast: Forecast }) {
  const { history, horizons, scenarios, event_markers: events, accuracy, disclaimer } = forecast
  const containerRef = useRef<HTMLDivElement>(null)
  const [horizonKey, setHorizonKey] = useState<ForecastHorizonKey>('m3')
  const [hover, setHover] = useState<Hover | null>(null)
  const [activeEvent, setActiveEvent] = useState<ForecastEventMarker | null>(null)

  const horizon = horizons[horizonKey]
  const probRange = horizon.prob_range_70

  const minHistD = history.length > 0 ? history[0].d : 0
  const todayClose = history.length > 0 ? history[history.length - 1].close : horizon.bands[0]?.p50 ?? 0

  // y 軸範圍：涵蓋 history 全部收盤 + 三個 horizon 的機率帶 + 情境錨點，固定不隨切換改變。
  const allPrices: number[] = history.map((h) => h.close)
  for (const key of HORIZON_ORDER) {
    for (const b of horizons[key].bands) allPrices.push(b.p10, b.p90)
  }
  if (scenarios.bear != null) allPrices.push(scenarios.bear)
  if (scenarios.base != null) allPrices.push(scenarios.base)
  if (scenarios.bull != null) allPrices.push(scenarios.bull)
  const rawMin = Math.min(...allPrices)
  const rawMax = Math.max(...allPrices)
  const range = rawMax - rawMin || rawMax * 0.1 || 1
  const yMin = rawMin - range * 0.04
  const yMax = rawMax + range * 0.04

  function yScale(price: number): number {
    return PAD_TOP + (1 - (price - yMin) / (yMax - yMin)) * PLOT_H
  }
  function xScaleHistory(d: number): number {
    if (minHistD === 0) return TODAY_X
    return HISTORY_X0 + ((d - minHistD) / (0 - minHistD)) * (TODAY_X - HISTORY_X0)
  }
  function xScaleForecast(d: number): number {
    return TODAY_X + (d / horizon.days) * (FORECAST_X1 - TODAY_X)
  }

  const historyPts = history.map((h) => `${xScaleHistory(h.d)},${yScale(h.close)}`).join(' ')

  const topOuter = horizon.bands.map((b) => `${xScaleForecast(b.d)},${yScale(b.p90)}`)
  const botOuter = [...horizon.bands].reverse().map((b) => `${xScaleForecast(b.d)},${yScale(b.p10)}`)
  const outerPath = `M${topOuter.join(' L')} L${botOuter.join(' L')} Z`

  const topInner = horizon.bands.map((b) => `${xScaleForecast(b.d)},${yScale(b.p75)}`)
  const botInner = [...horizon.bands].reverse().map((b) => `${xScaleForecast(b.d)},${yScale(b.p25)}`)
  const innerPath = `M${topInner.join(' L')} L${botInner.join(' L')} Z`

  const medianPts = horizon.bands.map((b) => `${xScaleForecast(b.d)},${yScale(b.p50)}`).join(' ')

  const todayY = yScale(todayClose)

  // 情境錨（3 個月估值錨，per 契約「scenarios 直接引用 valuation 三情境不得另算」）：
  // 畫成貫穿整個繪圖區的水平參考虛線，不隨 horizon 切換改變位置，避免不同 horizon
  // 下對 d=63 畫斜線產生誤導的斜率。
  const scenarioLines: Array<{ key: 'bull' | 'base' | 'bear'; value: number; color: string; label: string }> = []
  if (scenarios.bull != null) scenarioLines.push({ key: 'bull', value: scenarios.bull, color: 'var(--green)', label: '樂觀' })
  if (scenarios.base != null) scenarioLines.push({ key: 'base', value: scenarios.base, color: 'var(--text-soft)', label: '中性' })
  if (scenarios.bear != null) scenarioLines.push({ key: 'bear', value: scenarios.bear, color: 'var(--red)', label: '保守' })

  const visibleEvents = events.filter((e) => e.d >= 0 && e.d <= horizon.days)

  function nearestBand(d: number): ForecastBand {
    let best = horizon.bands[0]
    let bestDist = Infinity
    for (const b of horizon.bands) {
      const dist = Math.abs(b.d - d)
      if (dist < bestDist) {
        bestDist = dist
        best = b
      }
    }
    return best
  }

  function nearestHistory(d: number): { d: number; close: number } {
    let best = history[0]
    let bestDist = Infinity
    for (const h of history) {
      const dist = Math.abs(h.d - d)
      if (dist < bestDist) {
        bestDist = dist
        best = h
      }
    }
    return best
  }

  function updateFromClientX(clientX: number) {
    const el = containerRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const ratio = VB_W / rect.width
    const localX = (clientX - rect.left) * ratio

    if (localX < TODAY_X) {
      const d = Math.min(0, Math.max(minHistD, minHistD + ((localX - HISTORY_X0) / (TODAY_X - HISTORY_X0)) * (0 - minHistD)))
      const h = nearestHistory(d)
      setHover({ kind: 'history', d: h.d, close: h.close })
    } else {
      const d = Math.min(horizon.days, Math.max(0, ((localX - TODAY_X) / (FORECAST_X1 - TODAY_X)) * horizon.days))
      setHover({ kind: 'forecast', band: nearestBand(d) })
    }
    setActiveEvent(null)
  }

  function handlePointerMove(e: React.PointerEvent<SVGRectElement>) {
    updateFromClientX(e.clientX)
  }
  function handlePointerLeave() {
    setHover(null)
  }
  function handleBackgroundClick() {
    setActiveEvent(null)
  }

  const hoverX = hover ? (hover.kind === 'history' ? xScaleHistory(hover.d) : xScaleForecast(hover.band.d)) : null

  let tooltipStyle: React.CSSProperties | null = null
  if (hoverX != null) {
    const xPct = (hoverX / VB_W) * 100
    const flip = xPct > 62
    tooltipStyle = {
      left: `${xPct}%`,
      transform: flip ? 'translateX(-100%)' : 'translateX(0)',
      marginLeft: flip ? -8 : 8,
    }
  }

  let eventTooltipStyle: React.CSSProperties | null = null
  if (activeEvent) {
    const xPct = (xScaleForecast(activeEvent.d) / VB_W) * 100
    const flip = xPct > 62
    eventTooltipStyle = {
      left: `${xPct}%`,
      transform: flip ? 'translateX(-100%)' : 'translateX(0)',
      marginLeft: flip ? -8 : 8,
    }
  }

  const accuracyText =
    accuracy.hit_rate_70 != null
      ? `過去 ${accuracy.n_evaluated} 次預估，實際落點命中 ${Math.round(accuracy.hit_rate_70 * 100)}%`
      : accuracy.note

  return (
    <div className="forecast-body">
      <div className="segment-control forecast-segment">
        {HORIZON_ORDER.map((key) => (
          <button
            key={key}
            type="button"
            className={key === horizonKey ? 'active' : ''}
            onClick={() => {
              setHorizonKey(key)
              setHover(null)
              setActiveEvent(null)
            }}
          >
            {HORIZON_LABELS[key]}
          </button>
        ))}
      </div>

      <div className="forecast-headline mono">
        {HORIZON_LABELS[horizonKey]}後約 70% 機率落在 {fmt(probRange[0])} ～ {fmt(probRange[1])}
      </div>

      <div className="forecast-chart-wrap" ref={containerRef}>
        <svg
          className="forecast-svg"
          viewBox={`0 0 ${VB_W} ${VB_H}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={`預估走勢圖，左側為過去走勢，右側為 ${HORIZON_LABELS[horizonKey]}機率扇形，${HORIZON_LABELS[horizonKey]}後 70% 機率落在 ${fmt(probRange[0])} 到 ${fmt(probRange[1])} 之間`}
        >
          {scenarioLines.map((s) => {
            const y = yScale(s.value)
            return (
              <g key={s.key}>
                <line x1={HISTORY_X0} y1={y} x2={FORECAST_X1} y2={y} stroke={s.color} strokeWidth="1.5" strokeDasharray="3 3" opacity={0.8} />
                <text x={FORECAST_X1 + 4} y={y} dy="0.32em" fontSize="10.5" fill="var(--text-soft)" className="mono">
                  {s.label} {fmt(s.value)}
                </text>
              </g>
            )
          })}

          {/* 歷史實線（左 40%，固定不隨 horizon 切換改變） */}
          <polyline points={historyPts} fill="none" stroke="var(--text)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />

          {/* 預估扇形（右 60%），用 key 讓切換 horizon 時整組重新掛載觸發 fade 過場 */}
          <g key={horizonKey} className="forecast-fan-anim">
            <path d={outerPath} fill="rgba(74, 85, 199, 0.12)" />
            <path d={innerPath} fill="rgba(74, 85, 199, 0.24)" />
            <polyline points={medianPts} fill="none" stroke="var(--text-soft)" strokeWidth="2" strokeDasharray="4 4" />
          </g>

          {/* 今天：交接處 8px 圓點＋垂直 hairline */}
          <line x1={TODAY_X} y1={PAD_TOP} x2={TODAY_X} y2={VB_H - PAD_BOTTOM} stroke="var(--hairline)" strokeWidth="1" />
          <circle cx={TODAY_X} cy={todayY} r="4" fill="var(--accent)" stroke="var(--card)" strokeWidth="2" />
          <text x={TODAY_X} y={PAD_TOP - 6} fontSize="11" fill="var(--text-soft)" textAnchor="middle" className="mono">
            今天 {fmt(todayClose)}
          </text>

          {/* crosshair（雙區：history 顯示當日收盤，預估區顯示區間） */}
          {hoverX != null && (
            <line x1={hoverX} y1={PAD_TOP} x2={hoverX} y2={VB_H - PAD_BOTTOM} stroke="var(--text-soft)" strokeWidth="1" strokeDasharray="2 2" />
          )}

          {/* 觸控/滑鼠偵測層：全寬全高，命中目標比任何 mark 都大。放在事件標記「之前」
              （DOM 順序＝疊放順序），讓事件標記蓋在最上層才點得到，否則會被這層蓋住。 */}
          <rect
            x={0}
            y={0}
            width={VB_W}
            height={VB_H}
            fill="transparent"
            onPointerMove={handlePointerMove}
            onPointerDown={(e) => {
              handlePointerMove(e)
              handleBackgroundClick()
            }}
            onPointerLeave={handlePointerLeave}
          />

          {/* 事件標記：只顯示落在目前 horizon 內的事件。疊在偵測層之上才收得到點擊。 */}
          {visibleEvents.map((ev) => {
            const x = xScaleForecast(ev.d)
            const tipY = VB_H - PAD_BOTTOM
            return (
              <g
                key={`${ev.d}-${ev.label}`}
                className="forecast-event"
                onPointerDown={(e) => {
                  e.stopPropagation()
                  setActiveEvent(activeEvent?.d === ev.d && activeEvent?.label === ev.label ? null : ev)
                }}
              >
                <polygon points={`${x - 4},${tipY + 10} ${x + 4},${tipY + 10} ${x},${tipY + 2}`} fill="var(--accent)" />
                <rect x={x - 10} y={tipY - 8} width="20" height="20" fill="transparent" />
                <text x={x} y={tipY + 22} fontSize="9.5" fill="var(--text-soft)" textAnchor="middle">
                  {ev.label}
                </text>
              </g>
            )
          })}
        </svg>

        {hover && tooltipStyle && (
          <div className="forecast-tooltip mono" style={tooltipStyle}>
            {hover.kind === 'history' ? (
              <>
                <div className="forecast-tooltip-title">第 {hover.d} 個交易日</div>
                <div>收盤 {fmt(hover.close)}</div>
              </>
            ) : (
              <>
                <div className="forecast-tooltip-title">第 {hover.band.d} 個交易日</div>
                <div>中位數 {fmt(hover.band.p50)}</div>
                <div className="forecast-tooltip-range">
                  {fmt(hover.band.p10)} ～ {fmt(hover.band.p90)}
                </div>
              </>
            )}
          </div>
        )}

        {activeEvent && eventTooltipStyle && (
          <div className="forecast-tooltip mono" style={eventTooltipStyle}>
            <div className="forecast-tooltip-title">{activeEvent.label}</div>
            <div>{activeEvent.date}</div>
          </div>
        )}
      </div>

      <div className="forecast-legend">
        {/* p10-p90＝80% 機率區間，p25-p75＝50% 機率區間（跟 headline 的 70% 是不同統計量，
            headline 用 p15~p85，此處帶狀圖只畫 10/25/75/90 分位，標籤要如實反映涵蓋率）。 */}
        <span className="forecast-legend-item">
          <span className="forecast-swatch" style={{ background: 'rgba(74, 85, 199, 0.12)' }} />
          80% 機率區間
        </span>
        <span className="forecast-legend-item">
          <span className="forecast-swatch" style={{ background: 'rgba(74, 85, 199, 0.24)' }} />
          50% 機率區間
        </span>
        <span className="forecast-legend-item">
          <span className="forecast-swatch-line" style={{ background: 'var(--text-soft)' }} />
          中位數
        </span>
        {scenarioLines.map((s) => (
          <span className="forecast-legend-item" key={s.key}>
            <span className="forecast-swatch-line" style={{ background: s.color }} />
            {s.label}情境
          </span>
        ))}
      </div>

      <div className="forecast-accuracy">模型驗證：{accuracyText}</div>
      <div className="forecast-disclaimer">{disclaimer}</div>
    </div>
  )
}
