// localStorage 持股管理：代號、名稱、股數、成本價。

export interface Holding {
  id: string // 代號，同時當 primary key
  name: string
  shares: number
  costPrice: number
}

const STORAGE_KEY = 'advisor-war-room:holdings'

export function loadHoldings(): Holding[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
  } catch {
    return []
  }
}

function persist(holdings: Holding[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(holdings))
}

export function saveHolding(holding: Holding): Holding[] {
  const current = loadHoldings()
  const idx = current.findIndex((h) => h.id === holding.id)
  const next = idx >= 0 ? [...current] : [...current, holding]
  if (idx >= 0) next[idx] = holding
  persist(next)
  return next
}

export function deleteHolding(id: string): Holding[] {
  const next = loadHoldings().filter((h) => h.id !== id)
  persist(next)
  return next
}
