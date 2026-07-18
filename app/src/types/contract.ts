import { z } from 'zod'

// 資料契約 v1（docs/contracts/data-contract-v1.md）對應的 Zod schema。
// 前端 fetch 回來的 json 一律先過這層驗證；驗不過顯示「請更新 App」而非白屏。

export const MetaSchema = z.object({
  schema_version: z.literal(1),
  data_date: z.string(),
  generated_at: z.string(),
  sources: z.array(z.string()),
})

// 六檔決策動作／五檔多空傾向：兩端共用同一組詞彙，前端 UI 文案（顏色、標籤）也是照這個 enum 分類。
export const ActionSchema = z.enum(['加碼', '續抱', '試單', '觀望', '減碼', '出場'])
export const StanceSchema = z.enum(['偏多', '中性偏多', '中性', '中性偏空', '偏空'])

// ---------- daily.json ----------

export const UsIndexSchema = z.object({
  id: z.string(),
  name: z.string(),
  change_pct: z.number().nullable(),
})

export const MarketSchema = z.object({
  status: z.enum(['偏多進攻', '中性', '偏空防禦']),
  risk_temp: z.number().min(1).max(10),
  conclusion: z.string(),
  taiex: z.object({ close: z.number().nullable(), change_pct: z.number().nullable() }),
  us: z.array(UsIndexSchema),
})

export const CoreHoldingSchema = z.object({
  id: z.string(),
  name: z.string(),
  action: z.string(),
  note: z.string(),
})

export const TrackedDecisionSchema = z.object({
  action: ActionSchema,
  readable_reason: z.string(),
  defense_price: z.number().nullable(),
})

export const TrackedStockSchema = z.object({
  id: z.string(),
  name: z.string(),
  close: z.number().nullable(),
  change_pct: z.number().nullable(),
  decision: TrackedDecisionSchema,
})

export const WatchItemSchema = z.object({
  id: z.string(),
  name: z.string(),
  wait_condition: z.string(),
})

export const AlertSnapshotSchema = z.object({
  id: z.string(),
  name: z.string(),
  type: z.enum(['defense', 'entry']),
  price: z.number(),
  direction: z.enum(['below', 'above']),
})

export const DailySchema = z.object({
  meta: MetaSchema,
  market: MarketSchema,
  core_holdings: z.array(CoreHoldingSchema),
  tracked: z.array(TrackedStockSchema),
  watch: z.array(WatchItemSchema),
  alerts_snapshot: z.array(AlertSnapshotSchema),
})

export type Daily = z.infer<typeof DailySchema>
export type TrackedStock = z.infer<typeof TrackedStockSchema>
export type WatchItem = z.infer<typeof WatchItemSchema>

// ---------- stocks/<id>.json ----------

export const PrimaryDecisionSchema = z.object({
  action: ActionSchema,
  stance: StanceSchema,
  position_delta: z.enum(['increase', 'hold', 'small_entry', 'wait', 'reduce', 'exit']),
  confidence: z.number().min(0).max(100),
  decided_by_layer: z.number(),
  reason_codes: z.array(z.string()),
  readable_reason: z.string(),
  risk_note: z.string(),
  position: z.object({
    tier_amount: z.number(),
    lots: z.number(),
    odd_shares: z.number(),
  }),
  defense_price: z.number().nullable(),
  entry_condition: z
    .object({ price: z.number(), condition: z.string() })
    .nullable(),
  reeval_date: z.string(),
  core_note: z.string().optional(),
})

export const TimeframeSchema = z.object({
  label: z.string(),
  stance: StanceSchema,
  basis: z.string(),
})

export const LightSchema = z.object({
  color: z.enum(['green', 'yellow', 'red']).nullable(),
  facts: z.array(z.string()),
})

export const ValuationSchema = z.object({
  band: z.enum(['便宜', '合理', '偏貴', '很貴']).nullable(),
  base: z.number().nullable(),
  bull: z.number().nullable(),
  bear: z.number().nullable(),
  regime: z.string().nullable(),
  warning: z.string().nullable(),
})

export const ContextSchema = z.object({
  timeframes: z.object({
    short: TimeframeSchema,
    swing: TimeframeSchema,
    mid: TimeframeSchema,
  }),
  lights: z.object({
    fundamental: LightSchema,
    technical: LightSchema,
    chips: LightSchema,
  }),
  valuation: ValuationSchema,
  rr: z.number().nullable(),
})

export const RoleSchema = z.object({
  role: z.string(),
  support: z.array(z.string()),
  oppose: z.array(z.string()),
  verify: z.array(z.string()),
})

export const NewsSchema = z.object({
  title: z.string(),
  source: z.string(),
  url: z.string(),
  published_at: z.string(),
})

export const EventSchema = z.object({
  date: z.string(),
  label: z.string(),
  impact_note: z.string(),
})

export const EvidenceSchema = z.object({
  roles: z.array(RoleSchema),
  news: z.array(NewsSchema),
  events: z.array(EventSchema),
})

export const TrackEntrySchema = z.object({
  date: z.string(),
  action: ActionSchema,
  price_at_rec: z.number(),
  outcome: z.object({
    r5: z.number().nullable(),
    r20: z.number().nullable(),
    r60: z.number().nullable(),
  }),
  status: z.enum(['pending', 'done']),
})

export const StockDetailSchema = z.object({
  meta: MetaSchema,
  profile: z.object({
    id: z.string(),
    name: z.string(),
    market: z.string(),
    is_core_holding: z.boolean(),
  }),
  price: z.object({
    close: z.number().nullable(),
    change_pct: z.number().nullable(),
    ma20: z.number().nullable(),
    ma60: z.number().nullable(),
  }),
  primary_decision: PrimaryDecisionSchema,
  context: ContextSchema,
  evidence: EvidenceSchema,
  track: z.array(TrackEntrySchema),
})

export type StockDetail = z.infer<typeof StockDetailSchema>
export type TrackEntry = z.infer<typeof TrackEntrySchema>
