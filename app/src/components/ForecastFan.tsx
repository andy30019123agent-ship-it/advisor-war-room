import { useRef, useState } from 'react'
import type { Forecast, ForecastBand } from '../types/contract'

// 預估走勢．機率扇形圖（契約 v1.2 forecast）。SVG 手繪，不裝圖表庫。
// 座標系：viewBox 固定像素，容器 width:100% 靠 viewBox 縮放，觸控/滑鼠座標
// 用 getBoundingClientRect() 換算回 viewBox 座標（見 handlePointerMove）。

const VB_W = 360
const VB_H = 200
const PAD_LEFT = 6
const PAD_RIGHT = 80
const PAD_TOP = 16
const PAD_BOTTOM = 26
const PLOT_W = VB_W - PAD_LEFT - PAD_RIGHT
const PLOT_H = VB_H - PAD_TOP - PAD_BOTTOM

const X_TICKS: Array<{ d: number; label: string }> = [
  { d: 0, label: '今天' },
  { d: 21, label: '1 個月' },
  { d: 42, label: '2 個月' },
  { d: 63, label: '3 個月' },
]

function fmt(n: number): string {
  return Math.round(n).toLocaleString()
}

export function ForecastFan({ forecast }: { forecast: Forecast | null | undefined }) {
  if (!forecast) {
    return (
      <div className="group">
        <div className="group-title">預估走勢（3 個月機率模擬）</div>
        <div className="plain-card forecast-empty">樣本不足，暫無走勢模擬</div>
      </div>
    )
  }
  return (
    <div className="group">
      <div className="group-title">預估走勢（3 個月機率模擬）</div>
      <div className="summary-card forecast-card">
        <ForecastChart forecast={forecast} />
      </div>
    </div>
  )
}

function ForecastChart({ forecast }: { forecast: Forecast }) {
  const { bands, scenarios, prob_range_70: probRange, disclaimer } = forecast
  const containerRef = useRef<HTMLDivElement>(null)
  const [hoverD, setHoverD] = useState<number | null>(null)

  const horizon = bands[bands.length - 1]?.d ?? 63

  const allPrices: number[] = []
  for (const b of bands) allPrices.push(b.p10, b.p90)
  if (scenarios.bear != null) allPrices.push(scenarios.bear)
  if (scenarios.base != null) allPrices.push(scenarios.base)
  if (scenarios.bull != null) allPrices.push(scenarios.bull)
  const rawMin = Math.min(...allPrices)
  const rawMax = Math.max(...allPrices)
  const range = rawMax - rawMin || rawMax * 0.1 || 1
  const yMin = rawMin - range * 0.04
  const yMax = rawMax + range * 0.04

  function xScale(d: number): number {
    return PAD_LEFT + (d / horizon) * PLOT_W
  }
  function yScale(price: number): number {
    return PAD_TOP + (1 - (price - yMin) / (yMax - yMin)) * PLOT_H
  }

  const topOuter = bands.map((b) => `${xScale(b.d)},${yScale(b.p90)}`)
  const botOuter = [...bands].reverse().map((b) => `${xScale(b.d)},${yScale(b.p10)}`)
  const outerPath = `M${topOuter.join(' L')} L${botOuter.join(' L')} Z`

  const topInner = bands.map((b) => `${xScale(b.d)},${yScale(b.p75)}`)
  const botInner = [...bands].reverse().map((b) => `${xScale(b.d)},${yScale(b.p25)}`)
  const innerPath = `M${topInner.join(' L')} L${botInner.join(' L')} Z`

  const medianPts = bands.map((b) => `${xScale(b.d)},${yScale(b.p50)}`).join(' ')

  const todayPrice = bands[0]?.p50 ?? 0
  const todayX = xScale(0)
  const todayY = yScale(todayPrice)

  const scenarioLines: Array<{ key: 'bull' | 'base' | 'bear'; value: number; color: string; label: string }> = []
  if (scenarios.bull != null) scenarioLines.push({ key: 'bull', value: scenarios.bull, color: 'var(--green)', label: '樂觀' })
  if (scenarios.base != null) scenarioLines.push({ key: 'base', value: scenarios.base, color: 'var(--text-soft)', label: '中性' })
  if (scenarios.bear != null) scenarioLines.push({ key: 'bear', value: scenarios.bear, color: 'var(--red)', label: '保守' })

  function nearestBand(d: number): ForecastBand {
    let best = bands[0]
    let bestDist = Infinity
    for (const b of bands) {
      const dist = Math.abs(b.d - d)
      if (dist < bestDist) {
        bestDist = dist
        best = b
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
    const d = Math.min(horizon, Math.max(0, ((localX - PAD_LEFT) / PLOT_W) * horizon))
    setHoverD(nearestBand(d).d)
  }

  function handlePointerMove(e: React.PointerEvent<SVGRectElement>) {
    updateFromClientX(e.clientX)
  }
  function handlePointerLeave() {
    setHoverD(null)
  }

  const hoverBand = hoverD != null ? bands.find((b) => b.d === hoverD) ?? null : null

  // tooltip 定位：以百分比換算容器座標，靠近右緣時改往左展開，避免出視窗。
  let tooltipStyle: React.CSSProperties | null = null
  if (hoverBand) {
    const xPct = (xScale(hoverBand.d) / VB_W) * 100
    const flip = xPct > 62
    tooltipStyle = {
      left: `${xPct}%`,
      transform: flip ? 'translateX(-100%)' : 'translateX(0)',
      marginLeft: flip ? -8 : 8,
    }
  }

  return (
    <div className="forecast-body">
      <div className="forecast-headline mono">
        3 個月後約 70% 機率落在 {fmt(probRange[0])} ～ {fmt(probRange[1])}
      </div>

      <div className="forecast-chart-wrap" ref={containerRef}>
        <svg
          className="forecast-svg"
          viewBox={`0 0 ${VB_W} ${VB_H}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={`預估走勢扇形圖，3 個月後 70% 機率落在 ${fmt(probRange[0])} 到 ${fmt(probRange[1])} 之間`}
        >
          <path d={outerPath} fill="rgba(74, 85, 199, 0.12)" />
          <path d={innerPath} fill="rgba(74, 85, 199, 0.24)" />
          <polyline points={medianPts} fill="none" stroke="var(--text-soft)" strokeWidth="2" strokeDasharray="4 4" />

          {scenarioLines.map((s) => {
            const x2 = xScale(horizon)
            const y2 = yScale(s.value)
            return (
              <g key={s.key}>
                <line x1={todayX} y1={todayY} x2={x2} y2={y2} stroke={s.color} strokeWidth="2" />
                <text x={x2 + 6} y={y2} dy="0.32em" fontSize="11" fill="var(--text-soft)" className="mono">
                  {s.label} {fmt(s.value)}
                </text>
              </g>
            )
          })}

          {/* 今天標記 */}
          <circle cx={todayX} cy={todayY} r="4" fill="var(--accent)" stroke="var(--card)" strokeWidth="2" />
          <text x={todayX} y={todayY - 10} fontSize="11" fill="var(--text-soft)" textAnchor="start" className="mono">
            今天 {fmt(todayPrice)}
          </text>

          {/* x 軸標籤 */}
          {X_TICKS.map((t) => {
            const anchor = t.d === 0 ? 'start' : t.d === horizon ? 'end' : 'middle'
            return (
              <text
                key={t.d}
                x={xScale(t.d)}
                y={VB_H - 6}
                fontSize="11"
                fill="var(--text-soft)"
                textAnchor={anchor}
              >
                {t.label}
              </text>
            )
          })}

          {/* crosshair */}
          {hoverBand && (
            <line
              x1={xScale(hoverBand.d)}
              y1={PAD_TOP}
              x2={xScale(hoverBand.d)}
              y2={VB_H - PAD_BOTTOM}
              stroke="var(--text-soft)"
              strokeWidth="1"
              strokeDasharray="2 2"
            />
          )}

          {/* 觸控/滑鼠偵測層：全寬全高，命中目標比任何 mark 都大 */}
          <rect
            x={0}
            y={0}
            width={VB_W}
            height={VB_H}
            fill="transparent"
            onPointerMove={handlePointerMove}
            onPointerDown={handlePointerMove}
            onPointerLeave={handlePointerLeave}
          />
        </svg>

        {hoverBand && tooltipStyle && (
          <div className="forecast-tooltip mono" style={tooltipStyle}>
            <div className="forecast-tooltip-title">第 {hoverBand.d} 個交易日</div>
            <div>中位數 {fmt(hoverBand.p50)}</div>
            <div className="forecast-tooltip-range">
              {fmt(hoverBand.p10)} ～ {fmt(hoverBand.p90)}
            </div>
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

      <div className="forecast-disclaimer">{disclaimer}</div>
    </div>
  )
}
