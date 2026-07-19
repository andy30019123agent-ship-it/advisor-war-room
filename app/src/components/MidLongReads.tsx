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

// flip_condition 引擎端保證「一律指向相反方向的下一個 stance」（primary_decision.py
// _direction_read docstring）：bias 偏多 → flip_condition 描述怎麼翻空；bias 偏空／中性
// → flip_condition 描述怎麼翻多。label 之前寫死「翻多條件」，偏多股會出現「翻多條件：
// 跌破…轉偏空」的語意反話（大檢查2 R1）。改依 bias 動態算 label，跟 flip_condition 內容
// 的實際方向對齊。
function flipLabel(bias: string): string {
  if (bias.includes('偏多')) return '翻空條件'
  if (bias.includes('偏空')) return '翻多條件'
  return '翻向條件'
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
          <span className="midlong-flip-label">{flipLabel(read.bias)}</span>
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
