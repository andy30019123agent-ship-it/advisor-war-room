// 帳本的單一 React 入口。舊做法是每頁各自 useState(() => loadXxx())，同一份資料在不同頁
// 各讀各的、寫入後別頁不會更新（跨頁改完回來看還是舊值）。這裡集中管理，並監聽 storage
// 事件讓多個分頁／PWA 視窗同步。

import { useCallback, useEffect, useState } from 'react'
import {
  LEDGER_KEY,
  genEventId,
  loadLedger,
  saveLedger,
  todayTaipei,
  type Ledger,
  type PositionTag,
} from './ledger'
import { ensureLedger } from './ledgerMigration'

export function useLedger() {
  const [ledger, setLedgerState] = useState<Ledger>(() => ensureLedger())

  // 其他分頁寫入 localStorage 時同步過來。storage 事件只在「別的分頁」觸發，
  // 本分頁自己的寫入靠下面的 setLedger 直接更新 state。
  useEffect(() => {
    function onStorage(e: StorageEvent) {
      if (e.key !== LEDGER_KEY) return
      const next = loadLedger()
      if (next) setLedgerState(next)
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const setLedger = useCallback((next: Ledger) => {
    saveLedger(next)
    setLedgerState(next)
  }, [])

  /** 從外部（例如交易日誌 modal 寫完帳本後）重讀，讓畫面立刻反映新的持倉。 */
  const refresh = useCallback(() => {
    const next = loadLedger()
    if (next) setLedgerState(next)
  }, [])

  const setCash = useCallback(
    (target: number) => {
      const current = loadLedger()
      if (!current) return
      // 使用者直接改「現金餘額」時記成一筆調整事件，而不是覆寫 opening.cash——覆寫會讓
      // 歷史重播用到錯的期初值，中間狀態就全錯了。
      const derivedNow = currentCash(current)
      const delta = target - derivedNow
      if (Math.abs(delta) < 0.5) return
      setLedger({
        ...current,
        events: [
          ...current.events,
          {
            id: genEventId('c'),
            type: 'cash_adjust',
            date: todayTaipei(),
            created_at: new Date().toISOString(),
            delta,
            note: '手動調整現金餘額',
          },
        ],
      })
    },
    [setLedger]
  )

  const setTag = useCallback(
    (stockId: string, tag: PositionTag) => {
      const current = loadLedger()
      if (!current) return
      setLedger({ ...current, tags: { ...current.tags, [stockId]: tag } })
    },
    [setLedger]
  )

  return { ledger, setLedger, setCash, setTag, refresh }
}

// 只算現金，不需要整份投影（setCash 要拿它算差額）。與 derivePortfolio 的現金公式一致。
function currentCash(ledger: Ledger): number {
  let cash = Number(ledger.opening.cash) || 0
  for (const e of ledger.events) {
    if (e.type === 'cash_adjust') {
      if (Number.isFinite(e.delta)) cash += e.delta
      continue
    }
    if (e.date < ledger.opening.date) continue
    const gross = e.price * e.qty
    cash += e.side === 'buy' ? -(gross + e.fee) : gross - e.fee - e.tax
  }
  return cash
}
