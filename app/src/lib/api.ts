import { DailySchema, StockDetailSchema, type Daily, type StockDetail } from '../types/contract'

// 所有資料存取集中在這支檔案，日後接真的 /api/* 只需要改這裡的實作。

// 台股代號格式：4~6 碼數字（含上櫃/興櫃常見碼數）。fetchStockDetail 用來擋路徑注入，
// 也用來判斷值是否值得打即時分析 API（見下方）。
const STOCK_ID_RE = /^\d{4,6}$/

export class SchemaMismatchError extends Error {
  constructor(context: string) {
    super(`schema mismatch: ${context}`)
    this.name = 'SchemaMismatchError'
  }
}

// 查無此股票（該代號沒有 stocks/<id>.json，例如不在追蹤清單裡）。
export class NotFoundError extends Error {
  constructor(id: string) {
    super(`stock not found: ${id}`)
    this.name = 'NotFoundError'
  }
}

async function fetchJson(path: string): Promise<unknown> {
  const res = await fetch(path)
  if (res.status === 404) {
    throw new NotFoundError(path)
  }
  if (!res.ok) {
    throw new Error(`fetch failed: ${path} (${res.status})`)
  }
  return res.json()
}

export async function fetchDaily(): Promise<Daily> {
  const raw = await fetchJson('/data/daily.json')
  const parsed = DailySchema.safeParse(raw)
  if (!parsed.success) {
    throw new SchemaMismatchError('daily.json')
  }
  return parsed.data
}

// 查股票：id 在 trackedIds 內才試 /data/stocks/<id>.json（追蹤清單預算好的靜態檔，快、
// 不耗查詢額度）；不在清單內（呼叫方沒傳 trackedIds，或傳了但查不到）就直接走
// /api/analyze 現算，不再白打一次注定 404 的靜態檔請求（省 console 噪音、請求數減半，
// 見聯測 2026-07-18 #3/#8）。trackedIds 未提供時退回舊行為（先試靜態檔、404 才 fallback），
// 給還沒接上 daily.json 的呼叫方相容。兩條路徑回同構契約 JSON，下游完全不用區分來源。
//
// id 格式先擋一輪 4~6 碼數字：不合法直接當「查無」，不讓使用者輸入（或殘留的持股代號）
// 原封不動接進 fetch 路徑當路徑片段（見聯測 2026-07-18 #4 路徑注入風險）。
export async function fetchStockDetail(id: string, trackedIds?: ReadonlySet<string> | readonly string[]): Promise<StockDetail> {
  if (!STOCK_ID_RE.test(id)) {
    throw new NotFoundError(id)
  }
  const tracked = trackedIds instanceof Set ? trackedIds : trackedIds ? new Set(trackedIds) : null
  let raw: unknown
  if (tracked && !tracked.has(id)) {
    raw = await fetchLiveStockDetail(id)
  } else {
    try {
      raw = await fetchJson(`/data/stocks/${encodeURIComponent(id)}.json`)
    } catch (e) {
      if (!(e instanceof NotFoundError)) {
        throw e
      }
      raw = await fetchLiveStockDetail(id)
    }
  }
  const parsed = StockDetailSchema.safeParse(raw)
  if (!parsed.success) {
    throw new SchemaMismatchError(`stocks/${id}.json`)
  }
  return parsed.data
}

async function fetchLiveStockDetail(id: string): Promise<unknown> {
  const res = await fetch(`/api/analyze?stock=${encodeURIComponent(id)}`)
  if (res.status === 404) {
    throw new NotFoundError(id)
  }
  if (!res.ok) {
    // 503（額度用完／抓不到資料）等：API 已回 { error: "人話說明" }，包成一般 Error
    // 讓現有的錯誤態接手顯示，不用另開一種 UI 狀態。
    let message = `即時查詢失敗（${res.status}）`
    try {
      const body = (await res.json()) as { error?: string }
      if (body?.error) message = body.error
    } catch {
      // 忽略非 JSON 錯誤內容，用預設訊息
    }
    throw new Error(message)
  }
  return res.json()
}
