import { useState } from 'react'
import { postTrack } from '../lib/api'
import { loadWatchlist, addToWatchlist } from '../lib/watchlist'
import type { Daily } from '../types/contract'

// 加入監控（契約 v1.1 POST /api/track；v1.6 執行鏈路節：精選卡「＋監控」複用查股頁同一套
// 邏輯）：已在 daily.tracked（正式追蹤清單）或本機 watchlist（剛加入、次一交易日才會併進
// daily.tracked）都算「監控中」，不可再點。查股頁與精選卡共用這顆元件，只差外層排版——
// variant='block' 是查股頁原本整條 .group 版型；variant='inline' 是精選卡內縮的行內小按鈕。
export function TrackButton({
  stockId,
  daily,
  variant = 'block',
}: {
  stockId: string
  daily: Daily | undefined
  variant?: 'block' | 'inline'
}) {
  const [watchlist, setWatchlist] = useState<string[]>(() => loadWatchlist())
  const [status, setStatus] = useState<'idle' | 'loading' | 'added' | 'already' | 'full' | 'error'>('idle')
  const [errorMsg, setErrorMsg] = useState('')

  const alreadyMonitored = (daily?.tracked.some((t) => t.id === stockId) ?? false) || watchlist.includes(stockId)

  async function handleClick() {
    setStatus('loading')
    const result = await postTrack(stockId)
    if (result.kind === 'added' || result.kind === 'already') {
      setWatchlist(addToWatchlist(stockId))
      setStatus(result.kind)
    } else if (result.kind === 'full') {
      setStatus('full')
    } else {
      setErrorMsg(result.message)
      setStatus('error')
    }
  }

  const isMonitored = alreadyMonitored || status === 'added' || status === 'already'
  const msgText = status === 'added' ? '✓ 已加入監控（明日 14:30 起生效）' : '監控中'

  if (variant === 'inline') {
    if (isMonitored) {
      return <span className="pick-track-msg success">{msgText}</span>
    }
    return (
      <span className="pick-track-inline">
        {status === 'full' && <span className="pick-track-msg warn">監控清單已滿</span>}
        {status === 'error' && <span className="pick-track-msg warn">{errorMsg}</span>}
        <button
          type="button"
          className="pick-track-btn"
          onClick={handleClick}
          disabled={status === 'loading'}
        >
          {status === 'loading' ? '加入中…' : '＋ 監控'}
        </button>
      </span>
    )
  }

  if (isMonitored) {
    return (
      <div className="group">
        <div className="track-msg success">{msgText}</div>
      </div>
    )
  }

  return (
    <div className="group">
      {status === 'full' && <div className="track-msg warn">監控清單已滿（20 檔）</div>}
      {status === 'error' && <div className="track-msg warn">{errorMsg}</div>}
      <button
        type="button"
        className="btn-secondary"
        style={{ width: '100%' }}
        onClick={handleClick}
        disabled={status === 'loading'}
      >
        {status === 'loading' ? '加入中…' : '＋ 加入監控'}
      </button>
    </div>
  )
}
