import { useRef, useState } from 'react'

// K 線疊層圖（契約 v1.7 stocks/<id>.json.ohlc 節；v1.8 daily.json.market_battle.ohlc
// 複用同一元件畫 TAIEX）：SVG 手繪 60 根日 K＋作戰地圖疊層（防守價／進場錨／劇本關鍵價位）
// ＋MA20/60。插在查股票頁「決策卡之後、短線推演之前」／首頁「大盤作戰區」內。
//
// 疊層線一律從既有欄位取，不新增資料（契約規則：「K 線疊層線＝defense_price/entry 錨/
// 劇本價位，前端從既有欄位取，不新增」）——呼叫端把 primary_decision.defense_price／
// entry_condition.price／short_scenarios.key_levels 抽出來傳進來。
//
// MA20 用這 60 根 K 自己回算（真實 20 日移動平均，資料足夠）；MA60 因為契約只給
// 「現值」一個數字（price.ma60），60 根 K 不夠回推完整 60 日移動平均線，改畫一條水平
// 參考線，不假裝有完整趨勢曲線。
//
// 無 volume 參數化（v1.8）：market_battle.ohlc[].v 可為 null（大盤無成交量資料）——
// 型別放寬成 number|null，量圖區偵測到全部 v 為 null 時不畫量柱，價格區直接吃滿原本
// 量圖的高度（不留空白），hover tooltip 的「量」行也跟著省略。

// 型別故意不從 contract.ts 的 OhlcCandle import：個股 ohlc（v 必為 number）與大盤
// market_battle.ohlc（v 可為 null）結構性相容於這裡放寬後的型別，呼叫端各自傳各自的型別
// 即可（structural typing），元件本身只認「有沒有 volume 資料」不認來源。
type CandleBar = { d: string; o: number; h: number; l: number; c: number; v: number | null }

const VB_W = 360
const VB_H = 220
const PAD_LEFT = 4
const PAD_RIGHT = 72
const PAD_TOP = 14
const GAP = 6
const VOL_H = 42
const PRICE_H_WITH_VOL = 146
const PRICE_H_NO_VOL = PRICE_H_WITH_VOL + GAP + VOL_H
const PLOT_W = VB_W - PAD_LEFT - PAD_RIGHT

// 沿用全站綠漲紅跌（跟台股慣例紅漲相反，App 內一致性用；圖角落一次性小註提醒）。
const GREEN = '#197542'
const RED = '#C13328'
const LABEL_MIN_GAP = 14

function fmt(n: number): string {
  return n.toLocaleString(undefined, { maximumFractionDigits: 1 })
}

type OverlayLine = { key: string; value: number; color: string; label: string }

export function CandleChart({
  ohlc,
  ma60,
  defensePrice,
  entryPrice,
  keyLevels,
  title = 'K 線走勢',
}: {
  ohlc: CandleBar[] | null | undefined
  ma60: number | null
  defensePrice: number | null
  entryPrice: number | null
  keyLevels: number[]
  title?: string
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)

  if (!ohlc || ohlc.length === 0) {
    return (
      <div className="group">
        <div className="group-title">{title}</div>
        <div className="plain-card candle-empty">K 線資料準備中</div>
      </div>
    )
  }

  const n = ohlc.length
  const slot = PLOT_W / n
  const bodyW = Math.max(1.4, slot * 0.62)

  function xCenter(i: number): number {
    return PAD_LEFT + slot * (i + 0.5)
  }

  // 無 volume 情境（v1.8 market_battle.ohlc）：全部 v 為 null 時量圖區收掉，價格區
  // 吃滿高度；量柱渲染與 hover tooltip 的「量」行都跟著隱藏。
  const hasVolume = ohlc.some((c) => c.v != null)
  const PRICE_H = hasVolume ? PRICE_H_WITH_VOL : PRICE_H_NO_VOL
  const PRICE_Y0 = PAD_TOP
  const PRICE_Y1 = PAD_TOP + PRICE_H
  const VOL_Y0 = PRICE_Y1 + GAP
  const VOL_Y1 = VOL_Y0 + VOL_H

  const highs = ohlc.map((c) => c.h)
  const lows = ohlc.map((c) => c.l)
  const vols = ohlc.map((c) => c.v ?? 0)

  const ma20Series: Array<{ i: number; v: number }> = []
  for (let i = 19; i < n; i++) {
    let sum = 0
    for (let k = i - 19; k <= i; k++) sum += ohlc[k].c
    ma20Series.push({ i, v: sum / 20 })
  }

  const allPriceValues = [...highs, ...lows]
  if (defensePrice != null) allPriceValues.push(defensePrice)
  if (entryPrice != null) allPriceValues.push(entryPrice)
  for (const k of keyLevels) allPriceValues.push(k)
  if (ma60 != null) allPriceValues.push(ma60)
  for (const p of ma20Series) allPriceValues.push(p.v)

  const rawMin = Math.min(...allPriceValues)
  const rawMax = Math.max(...allPriceValues)
  const range = rawMax - rawMin || rawMax * 0.05 || 1
  const yMin = rawMin - range * 0.06
  const yMax = rawMax + range * 0.06

  function yScale(price: number): number {
    return PRICE_Y0 + (1 - (price - yMin) / (yMax - yMin)) * PRICE_H
  }

  const vMax = Math.max(...vols, 1)
  function volScale(v: number): number {
    return (v / vMax) * VOL_H
  }

  const overlays: OverlayLine[] = []
  if (defensePrice != null) overlays.push({ key: 'defense', value: defensePrice, color: RED, label: `防守 ${fmt(defensePrice)}` })
  if (entryPrice != null) overlays.push({ key: 'entry', value: entryPrice, color: GREEN, label: `進場參考 ${fmt(entryPrice)}` })
  keyLevels.forEach((v, i) => {
    // 跟防守/進場價太接近（<0.3%）就不重複畫，避免同個價位疊兩條線兩個標籤。
    const dupe = overlays.some((o) => Math.abs(o.value - v) / v < 0.003)
    if (!dupe) overlays.push({ key: `level-${i}`, value: v, color: 'var(--text-soft)', label: fmt(v) })
  })

  // 標籤防疊：依 y 由上到下排序，相鄰間距 <14px 就往下推開；再反向修一次避免最後幾個
  // 被推出繪圖區時，回頭又跟前面的擠在一起。
  const sorted = [...overlays].sort((a, b) => yScale(a.value) - yScale(b.value))
  const labelY: Record<string, number> = {}
  let prevY = -Infinity
  for (const o of sorted) {
    let y = yScale(o.value)
    if (y - prevY < LABEL_MIN_GAP) y = prevY + LABEL_MIN_GAP
    labelY[o.key] = y
    prevY = y
  }
  let nextY = Infinity
  for (let i = sorted.length - 1; i >= 0; i--) {
    const o = sorted[i]
    let y = labelY[o.key]
    if (nextY - y < LABEL_MIN_GAP) y = nextY - LABEL_MIN_GAP
    labelY[o.key] = y
    nextY = y
  }

  function updateFromClientX(clientX: number) {
    const el = containerRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const ratio = VB_W / rect.width
    const localX = (clientX - rect.left) * ratio
    const idx = Math.min(n - 1, Math.max(0, Math.floor((localX - PAD_LEFT) / slot)))
    setHoverIdx(idx)
  }

  const hovered = hoverIdx != null ? ohlc[hoverIdx] : null
  const lastClose = ohlc[n - 1].c

  let tooltipStyle: React.CSSProperties | null = null
  if (hoverIdx != null) {
    const xPct = (xCenter(hoverIdx) / VB_W) * 100
    const flip = xPct > 62
    tooltipStyle = { left: `${xPct}%`, transform: flip ? 'translateX(-100%)' : 'translateX(0)', marginLeft: flip ? -8 : 8 }
  }

  return (
    <div className="group">
      <div className="group-title">{title}</div>
      <div className="list-card candle-card">
        <div className="candle-note">綠漲紅跌</div>
        <div className="candle-chart-wrap" ref={containerRef}>
          <svg
            className="candle-svg"
            viewBox={`0 0 ${VB_W} ${VB_H}`}
            preserveAspectRatio="none"
            role="img"
            aria-label={`過去 ${n} 個交易日 K 線圖，含防守價與關鍵價位標示，按住可查看單日開高低收`}
          >
            {overlays.map((o) => {
              const y = yScale(o.value)
              return (
                <g key={o.key}>
                  <line x1={PAD_LEFT} y1={y} x2={PAD_LEFT + PLOT_W} y2={y} stroke={o.color} strokeWidth="1" strokeDasharray="3 3" opacity={0.85} />
                  <text x={PAD_LEFT + PLOT_W + 4} y={labelY[o.key]} dy="0.32em" fontSize="10" fill={o.color} className="mono">
                    {o.label}
                  </text>
                </g>
              )
            })}

            {ma60 != null && (
              <line
                x1={PAD_LEFT}
                y1={yScale(ma60)}
                x2={PAD_LEFT + PLOT_W}
                y2={yScale(ma60)}
                stroke="var(--text-soft)"
                strokeWidth="2"
                strokeDasharray="5 3"
                opacity={0.7}
              />
            )}

            {ma20Series.length >= 2 && (
              <polyline
                points={ma20Series.map((p) => `${xCenter(p.i)},${yScale(p.v)}`).join(' ')}
                fill="none"
                stroke="var(--accent)"
                strokeWidth="2"
                strokeOpacity="0.6"
                strokeLinejoin="round"
              />
            )}

            {ohlc.map((c, i) => {
              const up = c.c >= c.o
              const color = up ? GREEN : RED
              const x = xCenter(i)
              const yO = yScale(c.o)
              const yC = yScale(c.c)
              const bodyTop = Math.min(yO, yC)
              const bodyH = Math.max(1, Math.abs(yC - yO))
              return (
                <g key={c.d}>
                  <line x1={x} y1={yScale(c.h)} x2={x} y2={yScale(c.l)} stroke={color} strokeWidth="1" />
                  <rect x={x - bodyW / 2} y={bodyTop} width={bodyW} height={bodyH} fill={color} />
                </g>
              )
            })}

            <circle cx={PAD_LEFT + PLOT_W} cy={yScale(lastClose)} r="3.5" fill="var(--accent)" stroke="var(--card)" strokeWidth="1.5" />

            {hasVolume &&
              ohlc.map((c, i) => {
                const up = c.c >= c.o
                const color = up ? GREEN : RED
                const x = xCenter(i)
                const h = volScale(c.v ?? 0)
                return <rect key={`v-${c.d}`} x={x - bodyW / 2} y={VOL_Y1 - h} width={bodyW} height={h} fill={color} opacity={0.3} />
              })}

            {hoverIdx != null && (
              <line
                x1={xCenter(hoverIdx)}
                y1={PRICE_Y0}
                x2={xCenter(hoverIdx)}
                y2={hasVolume ? VOL_Y1 : PRICE_Y1}
                stroke="var(--text-soft)"
                strokeWidth="1"
                strokeDasharray="2 2"
              />
            )}

            {/* 觸控/滑鼠偵測層：全寬全高，放最上層才收得到 pointer 事件；按住（touchmove
                只在接觸中才觸發）即滿足「按住顯示 tooltip」，放開／移出即清除。 */}
            <rect
              x={0}
              y={0}
              width={VB_W}
              height={VB_H}
              fill="transparent"
              onPointerMove={(e) => updateFromClientX(e.clientX)}
              onPointerDown={(e) => updateFromClientX(e.clientX)}
              onPointerLeave={() => setHoverIdx(null)}
            />
          </svg>

          {hovered && tooltipStyle && (
            <div className="candle-tooltip mono" style={tooltipStyle}>
              <div className="candle-tooltip-title">{hovered.d}</div>
              <div>
                開 {fmt(hovered.o)} ／ 高 {fmt(hovered.h)}
              </div>
              <div>
                低 {fmt(hovered.l)} ／ 收 {fmt(hovered.c)}
              </div>
              {hovered.v != null && <div>量 {hovered.v.toLocaleString()}</div>}
            </div>
          )}
        </div>

        <div className="forecast-legend candle-legend">
          <span className="forecast-legend-item">
            <span className="forecast-swatch-line" style={{ background: 'var(--accent)', opacity: 0.6 }} />
            MA20
          </span>
          <span className="forecast-legend-item">
            <span className="forecast-swatch-line" style={{ background: 'var(--text-soft)' }} />
            MA60
          </span>
        </div>
      </div>
    </div>
  )
}
