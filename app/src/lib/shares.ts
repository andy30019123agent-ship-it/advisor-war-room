// 股數／張數換算與顯示（1 張 = 1000 股，台股慣例）。

export const SHARES_PER_LOT = 1000

export function formatShares(shares: number): string {
  if (!Number.isFinite(shares) || shares <= 0) return '0 股'
  if (shares < SHARES_PER_LOT) return `${shares.toLocaleString()} 股`
  const lots = Math.floor(shares / SHARES_PER_LOT)
  const odd = shares % SHARES_PER_LOT
  return odd > 0 ? `${lots} 張 ${odd} 股` : `${lots} 張`
}
