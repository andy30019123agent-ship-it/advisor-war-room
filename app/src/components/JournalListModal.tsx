// C 包・交易日誌全列表（規格 1.）：持股頁頂部「交易日誌」入口開啟，新增／編輯／刪除都在
// 這裡（編輯/刪除共用 JournalEntryFormModal，刪除有二次確認）。

import { useState } from 'react'
import { IconClose, IconPlus, IconChevron } from './icons'
import { JournalEntryFormModal } from './JournalEntryFormModal'
import { sortedByTime, type JournalEntry } from '../lib/journal'

export function JournalListModal({
  entries,
  onClose,
  onChange,
}: {
  entries: JournalEntry[]
  onClose: () => void
  onChange: (entries: JournalEntry[]) => void
}) {
  const [editing, setEditing] = useState<JournalEntry | 'new' | null>(null)

  const sorted = [...sortedByTime(entries)].reverse() // 最新在上面

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span className="title">交易日誌</span>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="關閉">
            <IconClose />
          </button>
        </div>

        <div className="group" style={{ padding: '0 0 12px' }}>
          <button type="button" className="btn-primary" onClick={() => setEditing('new')}>
            <IconPlus /> 記一筆交易
          </button>
        </div>

        {sorted.length === 0 ? (
          <div className="empty-state" style={{ padding: '24px 0' }}>
            <div className="title">還沒有交易紀錄</div>
            <div className="desc">每筆買賣記下來，才能分清是模型錯還是自己沒照計畫。</div>
          </div>
        ) : (
          <div className="list-card">
            {sorted.map((e) => (
              <button
                key={e.id}
                type="button"
                className="list-row row-button-reset"
                style={{ width: '100%', textAlign: 'left' }}
                onClick={() => setEditing(e)}
              >
                <div className="row-top">
                  <div className="row-name">
                    <span className="name">{e.name || e.stock_id}</span>
                    <span className="code mono">{e.stock_id}</span>
                  </div>
                  <IconChevron />
                </div>
                <div className="row-tags">
                  <span className={`pill ${e.side === 'buy' ? 'up' : 'stop'}`}>{e.side === 'buy' ? '買進' : '賣出'}</span>
                  <span className="pill neutral">
                    {e.date} · {e.price.toLocaleString()} 元 × {e.qty.toLocaleString()} 股
                  </span>
                  <span className={`pill ${e.followed_advice ? 'neutral' : 'stop'}`}>
                    {e.followed_advice ? '有照建議' : '沒照建議'}
                  </span>
                </div>
                {e.note && (
                  <div style={{ fontSize: 13, color: 'var(--text-soft)', marginTop: 6 }}>{e.note}</div>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {editing && (
        <JournalEntryFormModal
          seed={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={onChange}
          onDeleted={onChange}
        />
      )}
    </div>
  )
}
