import { DailySchema, StockDetailSchema, type Daily, type StockDetail } from '../types/contract'

// 所有資料存取集中在這支檔案，日後接真的 /api/* 只需要改這裡的實作。

export class SchemaMismatchError extends Error {
  constructor(context: string) {
    super(`schema mismatch: ${context}`)
    this.name = 'SchemaMismatchError'
  }
}

async function fetchJson(path: string): Promise<unknown> {
  const res = await fetch(path)
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

// 查股票：目前查任何代號都回 2330 fixture；之後接真 API 只要換掉這裡的 path。
export async function fetchStockDetail(_id: string): Promise<StockDetail> {
  const raw = await fetchJson(`/data/stocks/2330.json`)
  const parsed = StockDetailSchema.safeParse(raw)
  if (!parsed.success) {
    throw new SchemaMismatchError('stocks/2330.json')
  }
  return parsed.data
}
