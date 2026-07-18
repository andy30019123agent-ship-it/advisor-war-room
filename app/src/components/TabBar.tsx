import { IconToday, IconHoldings, IconStockSearch, IconTrack } from './icons'
import type { TabId } from '../App'

const TABS: { id: TabId; label: string; Icon: typeof IconToday }[] = [
  { id: 'today', label: '今日', Icon: IconToday },
  { id: 'holdings', label: '持股', Icon: IconHoldings },
  { id: 'search', label: '查股票', Icon: IconStockSearch },
  { id: 'track', label: '戰績', Icon: IconTrack },
]

export function TabBar({ active, onChange }: { active: TabId; onChange: (id: TabId) => void }) {
  return (
    <nav className="tabbar">
      {TABS.map(({ id, label, Icon }) => (
        <button
          key={id}
          type="button"
          className={`tab${active === id ? ' active' : ''}`}
          onClick={() => onChange(id)}
          aria-current={active === id ? 'page' : undefined}
        >
          <Icon />
          {label}
        </button>
      ))}
    </nav>
  )
}
