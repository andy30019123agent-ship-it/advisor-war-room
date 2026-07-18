import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TabBar } from './components/TabBar'
import { Today } from './pages/Today'
import { Holdings } from './pages/Holdings'
import { StockSearch } from './pages/StockSearch'
import { Track } from './pages/Track'
import { NotFoundError, SchemaMismatchError } from './lib/api'

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
  const [tab, setTab] = useState<TabId>('today')

  return (
    <QueryClientProvider client={queryClient}>
      {tab === 'today' && <Today onNavigate={setTab} />}
      {tab === 'holdings' && <Holdings />}
      {tab === 'search' && <StockSearch />}
      {tab === 'track' && <Track />}
      <TabBar active={tab} onChange={setTab} />
    </QueryClientProvider>
  )
}

export default App
