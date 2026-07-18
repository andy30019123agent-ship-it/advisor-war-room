// 資料新鮮度徽章：以 meta.data_date（行情資料日，非腳本執行日）判斷新鮮度。
// data_date 距今天（Asia/Taipei）≤1 個日曆日 → 綠點＋「MM-DD HH:MM 已更新」；
// >1 天（例如週末／假日還沒有新交易日資料）→ 中性樣式「資料：MM-DD 收盤」，
// 不假裝「今天已更新」。

function formatMMDDHHMM(iso: string): string {
  const d = new Date(iso)
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${mi}`
}

function formatMMDD(dateStr: string): string {
  const [, mm, dd] = dateStr.split('-')
  return `${mm}-${dd}`
}

// data_date（YYYY-MM-DD，台股交易日）距離「今天」（Asia/Taipei 日曆日）的天數。
function calendarDaysAgo(dateStr: string): number {
  const todayStr = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Taipei' })
  const dataMs = new Date(`${dateStr}T00:00:00+08:00`).getTime()
  const todayMs = new Date(`${todayStr}T00:00:00+08:00`).getTime()
  return Math.round((todayMs - dataMs) / (24 * 60 * 60 * 1000))
}

export function FreshnessBadge({ dataDate, generatedAt }: { dataDate: string; generatedAt: string }) {
  const daysAgo = calendarDaysAgo(dataDate)

  if (daysAgo > 1) {
    return (
      <div className="freshness neutral">
        <span className="dot" />
        資料：{formatMMDD(dataDate)} 收盤
      </div>
    )
  }

  if (daysAgo === 1) {
    // 行情是前一交易日（例如週六看週五盤）：綠燈但明講收盤日，不假裝是今天的行情
    return (
      <div className="freshness">
        <span className="dot" />
        {formatMMDD(dataDate)} 收盤（今日更新）
      </div>
    )
  }

  return (
    <div className="freshness">
      <span className="dot" />
      {formatMMDDHHMM(generatedAt)} 已更新
    </div>
  )
}
