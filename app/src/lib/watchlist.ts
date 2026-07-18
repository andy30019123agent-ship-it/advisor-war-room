// 「加入監控」localStorage 紀錄（契約 v1.1 POST /api/track 節）：
// 呼叫成功後把代號記進這裡，畫面立即顯示「監控中」，不用等隔天 daily.tracked 才出現。

const STORAGE_KEY = 'advisor-war-room:watchlist'

export function loadWatchlist(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((x) => typeof x === 'string') : []
  } catch {
    return []
  }
}

export function addToWatchlist(id: string): string[] {
  const current = loadWatchlist()
  if (current.includes(id)) return current
  const next = [...current, id]
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  } catch {
    // 忽略儲存失敗；本次 render 仍用記憶體內的 next 顯示「監控中」。
  }
  return next
}
