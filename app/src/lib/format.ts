// 共用格式化：今日漲跌 %（change_pct）顯示與上下色。Holdings／StockSearch 共用，
// 避免各自重寫一份（Today.tsx 已有自己的 fmtPct/pctClass，這裡刻意不去動它，
// 只給「非首頁」頁面用，降低跟另一個 agent 正在改的 Today.tsx 衝突的機會）。

export function fmtPct(n: number | null | undefined): string {
  if (n == null) return '—'
  return `${n > 0 ? '+' : ''}${n.toFixed(1)}%`
}

export function pctClass(n: number | null | undefined): string {
  if (n == null) return ''
  return n > 0 ? 'up' : n < 0 ? 'down' : ''
}
