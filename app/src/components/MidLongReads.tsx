import type { MidLongRead, MidLongReads as MidLongReadsData } from '../types/contract'

// 中長線方向判讀卡（契約 v1.7 stocks/<id>.json.mid_long_reads 節）：取代「長線機率區間」
// 在查股票頁的主位——bias 派生自 primary_decision 的 timeframes stance（引擎端保證，前端
// 不另算），path_text/flip_condition 給操作語意，basis chips 給依據。整組可為 null／個別
// 欄位缺席就隱藏（契約硬規則 3，graceful degrade）。

function biasClass(bias: string): string {
  if (bias === '偏多' || bias === '中性偏多') return 'up'
  if (bias === '偏空' || bias === '中性偏空') return 'down'
  return 'flat'
}

function ReadCard({ label, read }: { label: string; read: MidLongRead }) {
  return (
    <div className="summary-card midlong-card">
      <div className="midlong-top">
        <span className="midlong-label">{label}</span>
        <span className={`badge midlong-bias ${biasClass(read.bias)}`}>{read.bias}</span>
      </div>
      {read.path_text && <p className="midlong-path">{read.path_text}</p>}
      {read.flip_condition && (
        <div className="midlong-flip">
          <span className="midlong-flip-label">翻多條件</span>
          <span>{read.flip_condition}</span>
        </div>
      )}
      {read.basis.length > 0 && (
        <div className="midlong-basis">
          {read.basis.map((b, i) => (
            <span className="chip-static" key={i}>
              {b}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export function MidLongReads({ data }: { data: MidLongReadsData | null | undefined }) {
  if (!data) return null

  return (
    <div className="group">
      <div className="group-title">中長線判讀</div>
      <div className="midlong-list">
        <ReadCard label="波段 1-3 月" read={data.swing} />
        <ReadCard label="中期 3-12 月" read={data.mid} />
      </div>
    </div>
  )
}
