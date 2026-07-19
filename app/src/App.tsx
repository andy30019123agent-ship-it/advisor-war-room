import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TabBar } from './components/TabBar'
import { Today } from './pages/Today'
import { Holdings } from './pages/Holdings'
import { StockSearch } from './pages/StockSearch'
import { Track } from './pages/Track'
import { NotFoundError, SchemaMismatchError } from './lib/api'
import { DeepLinkBridge } from './components/DeepLinkBridge'

// D 包・deeplink（契約 v1.5「App 行為」節）：/?stock=2330 開啟即進查股票並載入該股，
// 讓 TG 警報訊息可以直達分析結果。只在初次載入讀一次 query param（不用 history/router，
// 這支 App 本來就沒有路由套件）。
// 台股代號格式＝4-6 碼數字；query param 是使用者可控輸入（URL 可被任意分享/竄改），
// 不驗證就直接塞進 DeepLinkBridge 模擬送出表單，格式不對的字串也會被當代號打進查詢——
// 不合法一律忽略（回 null，等同沒有 deeplink），DeepLinkBridge 也同樣守一次（大檢查）。
const STOCK_ID_RE = /^\d{4,6}$/

function readDeepLinkStock(): string | null {
  if (typeof window === 'undefined') return null
  const raw = new URLSearchParams(window.location.search).get('stock')
  return raw && STOCK_ID_RE.test(raw) ? raw : null
}

export type TabId = 'today' | 'holdings' | 'search' | 'track'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      // NotFoundError／SchemaMismatchError 是「重打也不會變」的確定性失敗（代號真的不存在、
      // 或後端資料契約不合），預設 retry 會白白把整個 fetchStockDetail（含即時 /api/analyze
      // 冷查，最久 20 幾秒）再打一次，浪費 FinMind 額度也讓查詢頁多等一輪。只有其餘（網路
      // 抖動、503 額度暫時用完等）才值得重試一次（聯測 2026-07-18 #4：非快取查詢打了兩輪）。
      retry: (failureCount, error) => {
        if (error instanceof NotFoundError || error instanceof SchemaMismatchError) return false
        return failureCount < 1
      },
    },
  },
})

function App() {
  const [tab, setTab] = useState<TabId>(() => (readDeepLinkStock() ? 'search' : 'today'))
  // 目前待橋接（或剛從 URL 讀到）的代號：交給 DeepLinkBridge 模擬送出查股票表單，
  // 送出後清空，避免同一個代號重複觸發。
  const [deepLinkStock, setDeepLinkStock] = useState<string | null>(() => readDeepLinkStock())

  // Today 首頁的指令卡／todos／持股／監控卡點擊，都走這條路徑直達查股票頁。
  function navigateToStock(id: string) {
    setDeepLinkStock(id)
    setTab('search')
  }

  return (
    <QueryClientProvider client={queryClient}>
      {tab === 'today' && <Today onNavigate={setTab} onNavigateStock={navigateToStock} />}
      {tab === 'holdings' && <Holdings />}
      {tab === 'search' && (
        <>
          <StockSearch />
          {deepLinkStock && <DeepLinkBridge stockId={deepLinkStock} onDone={() => setDeepLinkStock(null)} />}
        </>
      )}
      {tab === 'track' && <Track />}
      <TabBar active={tab} onChange={setTab} />
    </QueryClientProvider>
  )
}

export default App
