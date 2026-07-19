// 「最近查過」localStorage 紀錄（查股票頁 5.）：記最近查過的 5 檔（代號＋名稱），
// 搜尋框下方顯示 chips 可點重查，熟練使用者不用每天重打代號。

export interface RecentSearch {
  id: string
  name: string
}

const STORAGE_KEY = 'advisor-war-room:recent_searches'
const MAX_RECENT = 5

export function loadRecentSearches(): RecentSearch[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (x): x is RecentSearch => x && typeof x.id === 'string' && typeof x.name === 'string'
    )
  } catch {
    return []
  }
}

// 查到新的一筆就搬到最前面（同代號去重），最多留 5 筆。
export function addRecentSearch(id: string, name: string): RecentSearch[] {
  const current = loadRecentSearches().filter((r) => r.id !== id)
  const next = [{ id, name }, ...current].slice(0, MAX_RECENT)
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  } catch {
    // localStorage 不可用：靜默放棄持久化，本次 render 仍用記憶體內的 next 顯示。
  }
  return next
}
