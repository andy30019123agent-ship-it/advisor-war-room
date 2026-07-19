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

// ---------- v1.4 增補（docs/contracts/data-contract-v1.md「v1.4 增補」節）----------
// short_scenarios：短線（1-4 週）三劇本推演，取代扇形圖當查股票頁主角。
// 整組可為 null／status=insufficient_data（後者只給一句話 message）。
// 移到檔案前段（v1.8 增補）：daily.json 的 market_battle.scenarios 與個股 short_scenarios
// 同構複用這組 schema，必須先定義在 DailySchema 之前（JS 模組是依序求值，DailySchema
// 物件字面量組裝當下就要引用到已存在的 const）。

export const ShortScenarioActionSchema = z.object({
  stance: z.string(),
  text: z.string(),
})

export const ShortScenarioSchema = z.object({
  id: z.enum(['base', 'risk', 'bull']),
  title: z.string(),
  probability_pct: z.number(),
  trigger: z.string(),
  price_path: z.array(z.number()),
  price_path_text: z.string(),
  narrative: z.string(),
  invalidation: z.string(),
  action: ShortScenarioActionSchema,
})

export const ShortScenariosOkSchema = z.object({
  status: z.literal('ok'),
  horizon: z.string(),
  key_levels: z.object({
    supports: z.array(z.number()),
    resistances: z.array(z.number()),
  }),
  scenarios: z.array(ShortScenarioSchema),
  prob_note: z.string(),
  disclaimer: z.string(),
})

export const ShortScenariosInsufficientSchema = z.object({
  status: z.literal('insufficient_data'),
  message: z.string(),
})

export const ShortScenariosSchema = z.discriminatedUnion('status', [
  ShortScenariosOkSchema,
  ShortScenariosInsufficientSchema,
])

export type ShortScenario = z.infer<typeof ShortScenarioSchema>
export type ShortScenarios = z.infer<typeof ShortScenariosSchema>

// ---------- v1.8 增補（docs/contracts/data-contract-v1.md「v1.8 增補」節）----------
// market_battle：首頁大盤作戰區（TAIEX K 線＋大盤三劇本＋資金流向＋1 個月機率區間）。
// 整組可為 null（引擎尚未產出／舊 daily.json，v1.7 前相容，前端整區隱藏）。
// ohlc[].v 可為 null（大盤無成交量資料時，CandleChart 需支援「無 volume」情境）。

export const MarketBattleOhlcCandleSchema = z.object({
  d: z.string(),
  o: z.number(),
  h: z.number(),
  l: z.number(),
  c: z.number(),
  v: z.number().nullable(),
})

export type MarketBattleOhlcCandle = z.infer<typeof MarketBattleOhlcCandleSchema>

export const MarketBattleFlowSchema = z.object({
  foreign_streak: z
    .object({
      direction: z.enum(['buy', 'sell']),
      days: z.number(),
      latest_yi: z.number(),
    })
    .nullable(),
  leading_sectors: z.array(z.string()),
  us_overnight: z.array(z.object({ id: z.string(), change_pct: z.number().nullable() })),
})

export type MarketBattleFlow = z.infer<typeof MarketBattleFlowSchema>

export const MarketBattleSchema = z.object({
  ohlc: z.array(MarketBattleOhlcCandleSchema).nullable(),
  key_levels: z.object({
    supports: z.array(z.number()),
    resistances: z.array(z.number()),
  }),
  scenarios: ShortScenariosSchema.nullable(),
  flow: MarketBattleFlowSchema,
  forecast_range_m1: z.tuple([z.number(), z.number()]).nullable(),
})

export type MarketBattle = z.infer<typeof MarketBattleSchema>

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

// ---------- v1.1 增補（docs/contracts/data-contract-v1.md「v1.1 增補」節）----------
// schema_version 仍為 1；全部新欄位 optional/nullable，缺席不炸（向後相容 v1 fixture）。

export const ExposureGuidanceSchema = z.object({
  risk_temp: z.number(),
  max_equity_pct: z.number(),
  min_cash_pct: z.number(),
  new_position: z.enum(['禁止新增部位', '僅限試單', '可正常布局']),
  note: z.string(),
})

export const DailyEventSchema = z.object({
  date: z.string(),
  id: z.string(),
  name: z.string(),
  type: z.string(),
  label: z.string(),
})

export const TrackStatsByTimeframeEntrySchema = z.object({
  n: z.number(),
  hit_rate: z.number().nullable(),
})

export const TrackStatsSchema = z.object({
  n: z.number(),
  closed: z.number(),
  hit_rate_5d: z.number().nullable(),
  hit_rate_20d: z.number().nullable(),
  hit_rate_60d: z.number().nullable(),
  note: z.string(),
  // C 包・戰績分層（v1.5 增補）：short/swing/long 各自 n 與 hit_rate，樣本 <5 時引擎給
  // hit_rate=null。整組 optional：舊 daily.json（引擎尚未補上這欄位）時前端不顯示分層列
  // （契約硬規則 3，graceful degrade）。
  by_timeframe: z
    .object({
      short: TrackStatsByTimeframeEntrySchema,
      swing: TrackStatsByTimeframeEntrySchema,
      long: TrackStatsByTimeframeEntrySchema,
    })
    .optional(),
})

// ---------- v1.5 增補（docs/contracts/data-contract-v1.md「v1.5 增補」節）----------
// today_command／delta：D 包・今日指令中心，首頁新主角；全部 optional/nullable，
// 缺欄位時前端退回舊版摘要卡（graceful degrade，契約硬規則 3）。

export const TodayCommandTodoSchema = z.object({
  text: z.string(),
  stock_id: z.string().nullable().optional(),
  kind: z.string().optional(),
})

export const TodayCommandActionSchema = z.object({
  text: z.string(),
  stock_id: z.string().nullable().optional(),
})

export const TodayCommandSchema = z.object({
  headline: z.string(),
  action: TodayCommandActionSchema.nullable(),
  todos: z.array(TodayCommandTodoSchema),
})

export const DeltaSchema = z.object({
  since: z.string().nullable(),
  items: z.array(z.string()),
})

export type TodayCommandTodo = z.infer<typeof TodayCommandTodoSchema>
export type TodayCommandAction = z.infer<typeof TodayCommandActionSchema>
export type TodayCommand = z.infer<typeof TodayCommandSchema>
export type Delta = z.infer<typeof DeltaSchema>

// B 包・今日精選（docs/contracts/data-contract-v1.md「v1.5 增補」節 daily.picks）：
// 主動選股候選池，經三準則評分＋風控閘門後產出，禁新倉時 short/swing 給空陣列＋note。
// 整組 optional/nullable：舊資料（引擎尚未補上這欄位）時前端整區隱藏（契約硬規則 3）。

export const PickSchema = z.object({
  id: z.string(),
  name: z.string(),
  close: z.number().nullable(),
  score: z.number(),
  confidence: z.number().min(0).max(100),
  action_summary: z.string(),
  entry_zone: z.tuple([z.number(), z.number()]).nullable(),
  defense_price: z.number().nullable(),
  invalidation: z.string(),
  reasons: z.array(z.string()),
  // ---------- v1.6 增補（docs/contracts/data-contract-v1.md「v1.6 增補」節）----------
  // 全部 optional/nullable：v1.5 舊 fixture（引擎尚未升級）沒有這些欄位也能過 schema，
  // Pick 型別本身向後相容，只有下面的容器結構（pools vs 平鋪 short/swing/long）分兩種。
  sector: z.string().nullable().optional(),
  tenure_days: z.number().nullable().optional(),
  rank_move: z.enum(['↑', '↓', '−']).nullable().optional(),
  status_note: z.string().nullable().optional(),
  horizon: z.enum(['short', 'swing', 'long']).nullable().optional(),
})

export type Pick = z.infer<typeof PickSchema>

// v1.6 分艙容器（daily.picks.pools）：今日可操作／解禁後優先／長線研究三分組。
export const RosterChangesSchema = z.object({
  new: z.array(z.string()),
  dropped: z.array(z.string()),
  stay_note: z.string().nullable(),
})

export const PicksPoolsContainerSchema = z.object({
  actionable: z.array(PickSchema),
  on_deck: z.array(PickSchema),
  research: z.array(PickSchema),
})

export const PicksV16Schema = z.object({
  generated_from: z.string(),
  gate: z.string(),
  note: z.string(),
  pools: PicksPoolsContainerSchema,
  roster_changes: RosterChangesSchema.optional().nullable(),
})

// v1.5 舊平鋪容器（部署切換期相容用；引擎已宣告 v1.6 起不再輸出，但前端保留 fallback
// 防炸——見 PicksSection.tsx 的向後相容渲染）。
export const PicksV15Schema = z.object({
  generated_from: z.string(),
  gate: z.string(),
  note: z.string(),
  short: z.array(PickSchema),
  swing: z.array(PickSchema),
  long: z.array(PickSchema),
})

// union：先試 v1.6（有 pools 才會過），解不過再退回 v1.5 平鋪；兩種形狀在執行期用
// `'pools' in picks` 分辨（見 PicksSection.tsx）。
export const PicksSchema = z.union([PicksV16Schema, PicksV15Schema])

export type PicksPools = z.infer<typeof PicksV16Schema>
export type PicksFlat = z.infer<typeof PicksV15Schema>
export type RosterChanges = z.infer<typeof RosterChangesSchema>
export type Picks = z.infer<typeof PicksSchema>

export const DailySchema = z.object({
  meta: MetaSchema,
  market: MarketSchema,
  core_holdings: z.array(CoreHoldingSchema),
  tracked: z.array(TrackedStockSchema),
  watch: z.array(WatchItemSchema),
  alerts_snapshot: z.array(AlertSnapshotSchema),
  exposure_guidance: ExposureGuidanceSchema.optional().nullable(),
  events: z.array(DailyEventSchema).optional(),
  track_stats: TrackStatsSchema.optional().nullable(),
  today_command: TodayCommandSchema.optional().nullable(),
  delta: DeltaSchema.optional().nullable(),
  picks: PicksSchema.optional().nullable(),
  // v1.8：大盤作戰區。.catch(null)：形狀對不上時退化成 null，不拖垮整份 daily.json 解析
  // （契約硬規則 3，graceful degrade；同 forecast/short_scenarios 的相容防呆手法）。
  market_battle: MarketBattleSchema.optional().nullable().catch(null),
})

export type Daily = z.infer<typeof DailySchema>
export type TrackedStock = z.infer<typeof TrackedStockSchema>
export type WatchItem = z.infer<typeof WatchItemSchema>
export type ExposureGuidance = z.infer<typeof ExposureGuidanceSchema>
export type DailyEvent = z.infer<typeof DailyEventSchema>
export type TrackStats = z.infer<typeof TrackStatsSchema>
export type TrackStatsByTimeframeEntry = z.infer<typeof TrackStatsByTimeframeEntrySchema>
export type TrackTimeframeKey = 'short' | 'swing' | 'long'

// ---------- stocks/<id>.json ----------

export const AdvicePlanStepSchema = z.object({
  trigger: z.string(),
  act: z.string(),
})

export const AdviceVariantSchema = z.object({
  action_text: z.string(),
  plan: z.array(AdvicePlanStepSchema),
})

export const AdviceSchema = z.object({
  holder: AdviceVariantSchema,
  nonholder: AdviceVariantSchema,
})

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
  advice: AdviceSchema.optional().nullable(),
  defense_explain: z.string().optional().nullable(),
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

// ---------- v1.3 增補（docs/contracts/data-contract-v1.md「v1.3 增補」節）----------
// forecast：多 horizon（1/3/6 月）機率模擬走勢 + 歷史 + 事件標記 + 準確度回測。
// 整組可為 null（樣本 <120 根日 K，樣本不足時前端顯示 degrade 卡）。
//
// 相容防呆：舊 v1.2 結構（有 bands、無 horizons）不符合這裡的必要欄位，
// StockDetailSchema 用 .catch(null) 接住解析失敗，整組退化成 null，
// 不會讓整份 stocks/<id>.json 判定「請更新 App」（見 StockDetailSchema 的 forecast 欄位）。

export const ForecastBandSchema = z.object({
  d: z.number(),
  p10: z.number(),
  p25: z.number(),
  p50: z.number(),
  p75: z.number(),
  p90: z.number(),
})

export const ForecastScenariosSchema = z.object({
  bear: z.number().nullable(),
  base: z.number().nullable(),
  bull: z.number().nullable(),
})

export const ForecastHistoryPointSchema = z.object({
  d: z.number(),
  close: z.number(),
})

export const ForecastHorizonSchema = z.object({
  days: z.number(),
  bands: z.array(ForecastBandSchema),
  prob_range_70: z.tuple([z.number(), z.number()]),
})

export const ForecastEventMarkerSchema = z.object({
  d: z.number(),
  date: z.string(),
  label: z.string(),
})

export const ForecastAccuracySchema = z.object({
  n_evaluated: z.number(),
  hit_rate_70: z.number().nullable(),
  note: z.string(),
})

export const ForecastSchema = z.object({
  method: z.string(),
  n_paths: z.number(),
  vol_annualized: z.number(),
  as_of: z.string(),
  history: z.array(ForecastHistoryPointSchema),
  horizons: z.object({
    m1: ForecastHorizonSchema,
    m3: ForecastHorizonSchema,
    m6: ForecastHorizonSchema,
  }),
  week_range_70: z.tuple([z.number(), z.number()]),
  scenarios: ForecastScenariosSchema,
  event_markers: z.array(ForecastEventMarkerSchema),
  accuracy: ForecastAccuracySchema,
  disclaimer: z.string(),
})

export type ForecastBand = z.infer<typeof ForecastBandSchema>
export type ForecastHistoryPoint = z.infer<typeof ForecastHistoryPointSchema>
export type ForecastHorizon = z.infer<typeof ForecastHorizonSchema>
export type ForecastEventMarker = z.infer<typeof ForecastEventMarkerSchema>
export type ForecastAccuracy = z.infer<typeof ForecastAccuracySchema>
export type Forecast = z.infer<typeof ForecastSchema>
export type ForecastHorizonKey = 'm1' | 'm3' | 'm6'

// ---------- v1.4 增補（docs/contracts/data-contract-v1.md「v1.4 增補」節）----------
// short_scenarios：短線（1-4 週）三劇本推演，取代扇形圖當查股票頁主角。schema 定義已移到
// 檔案前段（見上方「v1.4 增補」區塊，v1.8 market_battle.scenarios 複用同一組 schema）。

// ---------- v1.7 增補（docs/contracts/data-contract-v1.md「v1.7 增補」節）----------
// ohlc：過去 60 交易日日 K（K 線疊層圖用）；mid_long_reads：中長線方向判讀（波段/中期）。
// 兩者整組可為 null（缺資料／樣本不足），前端 graceful degrade（契約硬規則 3）。

export const OhlcCandleSchema = z.object({
  d: z.string(),
  o: z.number(),
  h: z.number(),
  l: z.number(),
  c: z.number(),
  v: z.number(),
})

export type OhlcCandle = z.infer<typeof OhlcCandleSchema>

export const MidLongReadSchema = z.object({
  bias: StanceSchema,
  path_text: z.string(),
  flip_condition: z.string(),
  basis: z.array(z.string()),
})

export type MidLongRead = z.infer<typeof MidLongReadSchema>

export const MidLongReadsSchema = z.object({
  swing: MidLongReadSchema,
  mid: MidLongReadSchema,
})

export type MidLongReads = z.infer<typeof MidLongReadsSchema>

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
  // .catch(null)：舊 v1.2 fixture（有 bands、無 horizons）解析失敗時退化成 null，
  // 不拖垮整份 StockDetailSchema（見上方相容防呆註解）。
  forecast: ForecastSchema.nullable().optional().catch(null),
  // 同樣 .catch(null)：引擎還沒補上這欄位、或格式對不上時退化成 null，不拖垮整份解析。
  short_scenarios: ShortScenariosSchema.nullable().optional().catch(null),
  // v1.7：ohlc 缺資料整組 null（K 線疊層圖顯示「K 線資料準備中」小卡）。
  ohlc: z.array(OhlcCandleSchema).nullable().optional().catch(null),
  mid_long_reads: MidLongReadsSchema.nullable().optional().catch(null),
})

export type StockDetail = z.infer<typeof StockDetailSchema>
export type TrackEntry = z.infer<typeof TrackEntrySchema>
