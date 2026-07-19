// C 包・交易日誌新增／編輯表單（規格 1.）：從持股頁「記一筆」（預填該股）或「交易日誌」
// 全列表的新增／編輯入口開啟。輸入防呆同持股表單（代號格式、股數/成交價需為正數）。

import { useState } from 'react'
import { IconClose, IconTrash } from './icons'
import {
  genJournalId,
  saveJournalEntry,
  deleteJournalEntry,
  type JournalEntry,
  type JournalSide,
} from '../lib/journal'

const STOCK_ID_RE = /^\d{4,6}$/

function todayTaipei(): string {
  const d = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Taipei' }))
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function JournalEntryFormModal({
  seed,
  onClose,
  onSaved,
  onDeleted,
}: {
  // 編輯現有紀錄傳完整 JournalEntry；持股頁「記一筆」快速預填傳 { stock_id, name }；
  // 全新空白紀錄傳 null。
  seed: JournalEntry | { stock_id: string; name: string } | null
  onClose: () => void
  onSaved: (entries: JournalEntry[]) => void
  onDeleted?: (entries: JournalEntry[]) => void
}) {
  const isEditing = !!(seed && 'id' in seed)
  const existing = isEditing ? (seed as JournalEntry) : null

  const [date, setDate] = useState(existing?.date ?? todayTaipei())
  const [stockId, setStockId] = useState(seed?.stock_id ?? '')
  const [name, setName] = useState(seed?.name ?? '')
  const [side, setSide] = useState<JournalSide>(existing?.side ?? 'buy')
  const [price, setPrice] = useState(existing ? String(existing.price) : '')
  const [qty, setQty] = useState(existing ? String(existing.qty) : '')
  const [followedAdvice, setFollowedAdvice] = useState(existing?.followed_advice ?? true)
  const [note, setNote] = useState(existing?.note ?? '')

  const trimmedId = stockId.trim()
  const priceNum = Number(price)
  const qtyNum = Number(qty)
  const canSave =
    !!date && STOCK_ID_RE.test(trimmedId) && Number.isFinite(priceNum) && priceNum > 0 && Number.isFinite(qtyNum) && qtyNum > 0

  function submit() {
    if (!canSave) return
    const entry: JournalEntry = {
      id: existing?.id ?? genJournalId(),
      date,
      stock_id: trimmedId,
      name: name.trim() || trimmedId,
      side,
      price: priceNum,
      qty: qtyNum,
      followed_advice: followedAdvice,
      note: note.trim() || undefined,
      created_at: existing?.created_at ?? new Date().toISOString(),
    }
    const next = saveJournalEntry(entry)
    onSaved(next)
    onClose()
  }

  function handleDelete() {
    if (!existing) return
    if (!window.confirm(`確定要刪除這筆「${existing.name || existing.stock_id}」交易紀錄嗎？此操作無法復原。`)) return
    const next = deleteJournalEntry(existing.id)
    onDeleted?.(next)
    onClose()
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span className="title">{isEditing ? '編輯交易紀錄' : '記一筆交易'}</span>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="關閉">
            <IconClose />
          </button>
        </div>

        <div className="field">
          <label htmlFor="jf-date">成交日</label>
          <input id="jf-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="jf-id">股票代號</label>
          <input
            id="jf-id"
            value={stockId}
            onChange={(e) => setStockId(e.target.value)}
            placeholder="例如 2330"
            disabled={isEditing}
          />
        </div>
        <div className="field">
          <label htmlFor="jf-name">名稱</label>
          <input id="jf-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="例如 台積電" />
        </div>
        <div className="field">
          <span className="field-label-text">買賣別</span>
          <div className="unit-toggle">
            <button type="button" className={side === 'buy' ? 'active' : ''} onClick={() => setSide('buy')}>
              買進
            </button>
            <button type="button" className={side === 'sell' ? 'active' : ''} onClick={() => setSide('sell')}>
              賣出
            </button>
          </div>
        </div>
        <div className="field">
          <label htmlFor="jf-price">成交價</label>
          <input id="jf-price" type="number" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="2400" />
        </div>
        <div className="field">
          <label htmlFor="jf-qty">股數</label>
          <input id="jf-qty" type="number" inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value)} placeholder="1000" />
        </div>
        <div className="field">
          <span className="field-label-text">是否照建議操作</span>
          <div className="unit-toggle">
            <button type="button" className={followedAdvice ? 'active' : ''} onClick={() => setFollowedAdvice(true)}>
              有照建議
            </button>
            <button type="button" className={!followedAdvice ? 'active' : ''} onClick={() => setFollowedAdvice(false)}>
              沒照建議
            </button>
          </div>
        </div>
        <div className="field">
          <label htmlFor="jf-note">備註（選填）</label>
          <input id="jf-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="例如：跌破防守價停損" />
        </div>

        <button type="button" className="btn-primary" onClick={submit} disabled={!canSave} style={{ opacity: canSave ? 1 : 0.5 }}>
          儲存
        </button>

        {isEditing && (
          <div style={{ display: 'flex', justifyContent: 'center', marginTop: 12 }}>
            <button type="button" className="btn-danger-text" onClick={handleDelete}>
              <IconTrash /> 刪除這筆紀錄
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
