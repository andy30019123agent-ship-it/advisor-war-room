// 資料新鮮度徽章：綠點＋「MM-DD HH:MM 已更新」；過期（>1 天）改 amber 並寫「資料為 X 天前」。

function formatMMDDHHMM(iso: string): string {
  const d = new Date(iso)
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${mi}`
}

export function FreshnessBadge({ generatedAt }: { generatedAt: string }) {
  const generated = new Date(generatedAt)
  const ageMs = Date.now() - generated.getTime()
  const ageDays = Math.floor(ageMs / (24 * 60 * 60 * 1000))
  const stale = ageDays >= 1

  return (
    <div className={`freshness${stale ? ' stale' : ''}`}>
      <span className="dot" />
      {stale ? `資料為 ${ageDays} 天前` : `${formatMMDDHHMM(generatedAt)} 已更新`}
    </div>
  )
}
