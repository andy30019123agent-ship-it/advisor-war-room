import { DailySchema, StockDetailSchema, type Daily, type StockDetail } from '../types/contract'

// 所有資料存取集中在這支檔案，日後接真的 /api/* 只需要改這裡的實作。

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

// 查股票：依 id 讀 /data/stocks/<id>.json；目前僅涵蓋追蹤清單（fixture 有的檔），
// 之後接真 API 只要換掉這裡的 path，NotFoundError／SchemaMismatchError 的處理邏輯不用動。
export async function fetchStockDetail(id: string): Promise<StockDetail> {
  let raw: unknown
  try {
    raw = await fetchJson(`/data/stocks/${id}.json`)
  } catch (e) {
    if (e instanceof NotFoundError) {
      throw new NotFoundError(id)
    }
    throw e
  }
  const parsed = StockDetailSchema.safeParse(raw)
  if (!parsed.success) {
    throw new SchemaMismatchError(`stocks/${id}.json`)
  }
  return parsed.data
}
