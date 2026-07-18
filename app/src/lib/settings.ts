// 前端本地設定（localStorage，不進資料契約檔案）：總資金。
// docs/contracts/data-contract-v1.md v1.1「前端本地新設定」節：total_capital 預設 1,000,000，持股頁可改。

const STORAGE_KEY = 'advisor-war-room:total_capital'
export const DEFAULT_TOTAL_CAPITAL = 1_000_000

export function loadTotalCapital(): number {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_TOTAL_CAPITAL
    const n = Number(raw)
    return Number.isFinite(n) && n > 0 ? n : DEFAULT_TOTAL_CAPITAL
  } catch {
    return DEFAULT_TOTAL_CAPITAL
  }
}

export function saveTotalCapital(n: number): void {
  try {
    localStorage.setItem(STORAGE_KEY, String(n))
  } catch {
    // localStorage 不可用（隱私模式等）：靜默放棄，畫面仍照 state 顯示本次輸入值。
  }
}
