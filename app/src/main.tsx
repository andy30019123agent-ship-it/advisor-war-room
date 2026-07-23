import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { ensureLedger } from './lib/ledgerMigration'

// 開機第一件事就把帳本準備好（首次載入會從舊 holdings/journal 遷移一次，冪等）。
// 必須在 render 之前：查股頁的「記一筆」可能在持股頁還沒掛載過就被按下，那時若帳本
// 還不存在，寫入會靜默失敗、交易就丟了。
ensureLedger()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
