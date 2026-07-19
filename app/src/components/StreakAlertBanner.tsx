// C 包・連敗保護（規格 3.）：連續 2 筆賣出且虧損顯示 amber 警示、連續 3 筆（含以上）顯示
// red 警示。Holdings 與 Track 頁頂部共用同一顆元件，判定邏輯在 lib/journal.ts（可測）。

import { getStreakAlert, type JournalEntry } from '../lib/journal'

export function StreakAlertBanner({ entries }: { entries: JournalEntry[] }) {
  const alert = getStreakAlert(entries)
  if (alert.level === 'none') return null
  return <div className={`streak-alert ${alert.level}`}>{alert.message}</div>
}
