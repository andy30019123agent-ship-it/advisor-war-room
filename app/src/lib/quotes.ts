import { useQuery } from '@tanstack/react-query'

// 盤中現價即時化（契約 v1.7「新 API：GET /api/quote」節）：serverless 代理 TWSE MIS 即時
// 報價。App 開啟／切前景（visibilitychange）時對「持股∪監控∪當前查詢股」刷新，
// 用 TanStack Query 的預設 refetchOnWindowFocus（focus manager 內建監聽 visibilitychange
// ＋focus，App.tsx 的 QueryClient 已設 staleTime 60s 全域預設）自然達成，這裡不用另外接
// 事件監聽器。

export interface QuoteEntry {
  price: number | null
  change_pct: number | null
  at: string | null // "HH:MM"
  stale: boolean // true＝非交易時段／查無，前端 fallback 用快照收盤價
}

export type QuotesMap = Record<string, QuoteEntry>

// 契約上限：12 檔/次。
const MAX_IDS_PER_CALL = 12

// 本機測試 /api/quote 不存在（Python serverless 平行開發中，engine 尚未落地）：fetch 一定
// 404／連線失敗，這是已知、暫時的開發期現象，不是真的錯誤——graceful catch 沿用快照收盤價，
// 只警告一次（不洗版 console，v1.7 規格豁免零紅字規則，見任務回報）。
let warnedOnce = false

function warnOnce(e: unknown) {
  if (warnedOnce) return
  warnedOnce = true
  console.warn('[quotes] /api/quote 目前抓不到（開發環境常見；正式站接上 quote API 後會消失），沿用快照收盤價', e)
}

export async function fetchQuotes(ids: readonly string[]): Promise<QuotesMap> {
  const unique = Array.from(new Set(ids)).filter(Boolean)
  if (unique.length === 0) return {}
  const capped = unique.slice(0, MAX_IDS_PER_CALL)
  try {
    const res = await fetch(`/api/quote?ids=${capped.map(encodeURIComponent).join(',')}`)
    if (!res.ok) throw new Error(`quote api failed (${res.status})`)
    const json = (await res.json()) as unknown
    if (!json || typeof json !== 'object') return {}
    return json as QuotesMap
  } catch (e) {
    warnOnce(e)
    return {}
  }
}

// ids 陣列每次 render 參考位址都不同（呼叫端常常現算），先正規化成排序去重的字串當
// queryKey，避免同一組代號因為陣列 identity 不同而被判定成「新的 query」重複打 API。
export function useQuotes(ids: readonly string[]) {
  const key = Array.from(new Set(ids))
    .filter(Boolean)
    .sort()
    .join(',')
  return useQuery({
    queryKey: ['quotes', key],
    queryFn: () => fetchQuotes(key ? key.split(',') : []),
    enabled: key.length > 0,
  })
}

// 判斷某檔的即時報價是否「可用且非盤外」：可用才覆蓋快照顯示。
export function isLiveQuote(q: QuoteEntry | undefined): q is QuoteEntry & { price: number; at: string } {
  return !!q && q.stale === false && q.price != null && q.at != null
}

// 誠實揭露（大檢查2 Y1）：畫面上「距防守 %」用盤中即時價算，但劇本／決策卡的失效判定
// 一律以「收盤」為準（primary_decision／短線劇本都寫死「收盤跌破防守價才失效」）。
// 盤中即時價已經跌破防守、但收盤還沒收確認時，兩個基準會同框出現矛盾訊號——即時價讀起來
// 像「已經破防守」，但劇本卡仍在講「還沒破」。這裡只負責判斷是否要秀出那句誠實提示，
// 不改變任何判定邏輯本身。
export function isIntradayDefenseBreach(
  live: boolean,
  currentPrice: number | null,
  defensePrice: number | null,
): boolean {
  return live && currentPrice != null && defensePrice != null && currentPrice < defensePrice
}
