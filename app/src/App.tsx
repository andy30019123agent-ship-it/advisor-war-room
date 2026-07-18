import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TabBar } from './components/TabBar'
import { Today } from './pages/Today'
import { Holdings } from './pages/Holdings'
import { StockSearch } from './pages/StockSearch'
import { Track } from './pages/Track'

export type TabId = 'today' | 'holdings' | 'search' | 'track'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      retry: 1,
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
