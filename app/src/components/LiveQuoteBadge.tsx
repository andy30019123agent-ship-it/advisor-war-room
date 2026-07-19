// 盤中現價徽章（契約 v1.7 App 行為節）：stale=false 時在現價旁顯示「盤中 HH:MM」＋綠點，
// 跟 FreshnessBadge 的收盤徽章區分開——這個代表「這個數字比今天收盤價更新」。
export function LiveQuoteBadge({ at }: { at: string }) {
  return (
    <span className="badge live">
      <span className="dot" />
      盤中 {at}
    </span>
  )
}
