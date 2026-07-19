import { useEffect, useRef } from 'react'

// D 包・deeplink（/?stock=2330 或首頁點擊直達查股票頁）：StockSearch.tsx 這次由另一個
// agent 平行在改、鐵則不可觸碰，所以沒辦法加一個 initialStockId prop 讓它自己吃。改用「模擬
// 使用者操作」橋接——等查股票頁的搜尋框（id="stock-search-input"，見 StockSearch.tsx）出現在
// DOM 後，用原生 input setter 寫代號＋dispatch input 事件（讓 React 的受控 state 跟著更新、
// submit 按鈕解除 disabled），下一輪再對 form 呼叫 requestSubmit() 觸發它既有的 submit()。
// 全程不改 StockSearch.tsx 一行程式碼；等雙邊工作合併、檔案解鎖後，可以換回正規的 prop。
// 台股代號格式＝4-6 碼數字（與 App.tsx 的 readDeepLinkStock 同一條規則）；這裡再守一次是
// defense-in-depth——stockId 不只可能來自已驗證過的 deeplink query param，將來也可能被其
// 他呼叫端（如未來的 prop 化 navigateToStock）傳進未經驗證的字串，不合法就不觸碰 DOM。
const STOCK_ID_RE = /^\d{4,6}$/

export function DeepLinkBridge({ stockId, onDone }: { stockId: string; onDone: () => void }) {
  const doneRef = useRef(false)

  useEffect(() => {
    if (!STOCK_ID_RE.test(stockId)) {
      onDone()
      return
    }
    doneRef.current = false
    let cancelled = false
    let attempts = 0
    let raf = 0

    function tick() {
      if (cancelled || doneRef.current) return
      attempts += 1
      const input = document.getElementById('stock-search-input') as HTMLInputElement | null
      const form = input?.closest('form') ?? null

      if (input && form) {
        const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set
        nativeSetter?.call(input, stockId)
        input.dispatchEvent(new Event('input', { bubbles: true }))

        // 等一輪 React re-render（inputValue state 更新、submit 按鈕解除 disabled）再送出，
        // 不然 requestSubmit 時表單讀到的還是舊的空值。
        raf = requestAnimationFrame(() => {
          if (cancelled) return
          form.requestSubmit()
          doneRef.current = true
          onDone()
        })
        return
      }

      // 查股票頁還沒掛載完成（tab 剛切過去那一瞬間）：最多重試 60 幀（約 1 秒）。
      if (attempts < 60) {
        raf = requestAnimationFrame(tick)
      }
    }

    raf = requestAnimationFrame(tick)

    return () => {
      cancelled = true
      cancelAnimationFrame(raf)
    }
  }, [stockId, onDone])

  return null
}
