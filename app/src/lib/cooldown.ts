// 冷靜期落地（契約 v1.6「執行鏈路」節）：journal 連續停損（getLossStreak）≥2 時，下單建議
// 顯示的金額要減半＋標「冷靜期」（amber）；≥3 時金額整個被「暫停新倉」取代（red）。
// 純函式（輸入原始建議金額與 streak，回傳畫面該顯示什麼），可測；StockSearch 的部位欄
// （真實 primary_decision.position.tier_amount）與精選卡（前端依 score 估的建議試單量）
// 共用同一份判斷，不各自重寫一次規則。

export type CooldownLevel = 'none' | 'amber' | 'red'

export interface CooldownDisplay {
  level: CooldownLevel
  amount: number | null // 元；red 時為 null（顯示改用 badgeText「暫停新倉」取代金額）
  badgeText: string | null // none 時 null；amber「冷靜期」；red「暫停新倉」
}

export function applyCooldown(amount: number, streak: number): CooldownDisplay {
  if (streak >= 3) {
    return { level: 'red', amount: null, badgeText: '暫停新倉' }
  }
  if (streak >= 2) {
    return { level: 'amber', amount: Math.round(amount / 2), badgeText: '冷靜期' }
  }
  return { level: 'none', amount, badgeText: null }
}
