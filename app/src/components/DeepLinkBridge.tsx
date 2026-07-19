import { useEffect, useRef } from 'react'

// D 包・deeplink（/?stock=2330 或首頁點擊直達查股票頁）：StockSearch.tsx 這次由另一個
// agent 平行在改、鐵則不可觸碰，所以沒辦法加一個 initialStockId prop 讓它自己吃。改用「模擬
// 使用者操作」橋接——等查股票頁的搜尋框（id="stock-search-input"，見 StockSearch.tsx）出現在
// DOM 後，用原生 input setter 寫代號＋dispatch input 事件（讓 React 的受控 state 跟著更新、
// submit 按鈕解除 disabled），下一輪再對 form 呼叫 requestSubmit() 觸發它既有的 submit()。
// 全程不改 StockSearch.tsx 一行程式碼；等雙邊工作合併、檔案解鎖後，可以換回正規的 prop。
export function DeepLinkBridge({ stockId, onDone }: { stockId: string; onDone: () => void }) {
  const doneRef = useRef(false)

  useEffect(() => {
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
