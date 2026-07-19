# 資料契約 v1.1（前端 ⇄ 引擎共同介面，2026-07-18；v1.1 新增欄位見文末「v1.1 增補」）

> 權威文件。引擎產出與前端讀取都以本檔為準；欄位要改必須先改這裡再改兩端。
> 形式化 schema 放 `schema/*.json`（由引擎端依本檔生成並加測試）；前端用 Zod 對齊。

## 檔案佈局（引擎每日產出，靜態託管）

```
public/data/daily.json          今日戰術台（首頁）
public/data/stocks/<id>.json    單股完整分析（追蹤清單每檔一份；即時查詢 API 回同構）
```

## 共通 meta（兩種檔案都有）

```jsonc
"meta": {
  "schema_version": 1,
  "data_date": "2026-07-18",        // 行情資料日（台北時區）
  "generated_at": "2026-07-18T14:30:00+08:00",
  "sources": ["FinMind", "yfinance"] // 本份資料實際用到的來源
}
```

## daily.json

```jsonc
{
  "meta": { ... },
  "market": {
    "status": "偏空防禦",            // 偏多進攻｜中性｜偏空防禦（三檔，引擎規則產生）
    "risk_temp": 8,                  // 1-10
    "conclusion": "今天不加碼，守好停損位。",  // 一句話，≤20 字
    "taiex": { "close": 45632, "change_pct": -1.2 },
    "us": [ { "id": "SPX", "name": "S&P 500", "change_pct": -0.8 } ]  // SPX/NDX/SOX/VIX
  },
  "core_holdings": [                 // 核心持股指引（永遠顯示、與波段訊號分離）
    { "id": "2330", "name": "台積電", "action": "核心續扣", "note": "波段不加碼" },
    { "id": "0050", "name": "元大台灣50", "action": "定期定額照常", "note": "不受本週訊號影響" }
  ],
  "tracked": [                       // 追蹤清單縮影（有完整 stocks/<id>.json 的檔）
    {
      "id": "2330", "name": "台積電",
      "close": 2440, "change_pct": -0.4,
      "decision": {                  // = stocks/<id>.json 的 primary_decision 縮影，禁止另算
        "action": "續抱",           // 加碼｜續抱｜試單｜觀望｜減碼｜出場
        "readable_reason": "趨勢仍在且基本面未壞；但估值偏貴，未突破前不加碼。",
        "defense_price": 2245
      }
    }
  ],
  "watch": [                         // 觀察清單（尚無完整報告，只有等待條件）
    { "id": "2454", "name": "聯發科", "wait_condition": "等站回 MA20" }
  ],
  "alerts_snapshot": [               // 提醒管線讀這裡，不重算
    { "id": "2330", "name": "台積電", "type": "defense", "price": 2245, "direction": "below" }
    // type: defense（跌破防守）｜entry（突破進場）；direction: below｜above
  ]
}
```

## stocks/<id>.json

```jsonc
{
  "meta": { ... },
  "profile": { "id": "2330", "name": "台積電", "market": "TWSE", "is_core_holding": true },
  "price": { "close": 2440, "change_pct": -0.4, "ma20": 2429.5, "ma60": 2350.0 },

  "primary_decision": {              // ★ 全檔唯一結論源，所有文案由此派生
    "action": "續抱",
    "stance": "中性偏多",           // 偏多｜中性偏多｜中性｜中性偏空｜偏空
    "position_delta": "hold",        // increase|hold|small_entry|wait|reduce|exit
    "confidence": 62,                // 0-100
    "decided_by_layer": 4,           // 六層優先序中最終拍板的層（1資料 2硬風控 3持股 4R/R 5三燈 6估值）
    "reason_codes": ["trend_ok", "valuation_expensive", "chips_weak"],
    "readable_reason": "因為趨勢仍在且基本面未壞，所以不急著賣；但估值已偏貴，未突破前不加碼。",
    "risk_note": "跌破 2,245 防守位就先降波段部位。",
    "position": { "tier_amount": 200000, "lots": 0, "odd_shares": 82 },  // 級距 0/10/20/40/60 萬
    "defense_price": 2245,
    "entry_condition": null,         // 空手時給：{"price": 2480, "condition": "站回 MA20 且法人連 2 日買超"}
    "reeval_date": "2026-07-25",
    "core_note": "此為波段層判斷，不影響定期定額核心部位。"  // 僅 is_core_holding=true 時有
  },

  "context": {                       // 背景解釋層（不得與 primary_decision 打架；一致性測試把關）
    "timeframes": {
      "short": { "label": "短線 1-4 週", "stance": "中性", "basis": "技術偏多＋籌碼偏空" },
      "swing": { "label": "波段 1-3 月（主）", "stance": "中性偏多", "basis": "..." },
      "mid":   { "label": "中期 3-12 月", "stance": "中性", "basis": "..." }
    },
    "lights": {                    // color 只允許 green｜yellow｜red｜null（缺資料）；引擎內部的 amber/na 必須先正規化
      "fundamental": { "color": "yellow", "facts": ["營收 YoY +67.9%", "PER 32.8 落在近3年 82% 分位"] },
      "technical":   { "color": "green",  "facts": ["站上 MA20/60，多頭排列"] },
      "chips":       { "color": "red",    "facts": ["外資連 3 日賣超 1.6 萬張"] }
    },
    "valuation": {
      "band": "偏貴",               // 便宜｜合理｜偏貴｜很貴｜null（資料不足時整組欄位給 null，前端顯示「估值資料不足」）
      "base": 2150, "bull": 2600, "bear": 1900,   // 可為 null
      "regime": "3y",               // 用了哪個 regime 分位；可為 null
      "warning": null               // Base 偏離現價 >25-35% 時給說明字串
    },
    "rr": 1.8
  },

  "evidence": {
    "roles": [                       // 六角色改決策工具格式（引擎依 reason_codes 模板生成）
      { "role": "技術面分析師", "support": ["..."], "oppose": ["..."], "verify": ["..."] }
    ],
    "news": [ { "title": "...", "source": "...", "url": "...", "published_at": "..." } ],
    "events": [ { "date": "2026-07-16", "label": "法說會", "impact_note": "..." } ]
  },

  "track": [                         // 本檔歷史建議（戰績頁用；pending 也要給）
    { "date": "2026-07-15", "action": "減碼", "price_at_rec": 2453,
      "outcome": { "r5": null, "r20": null, "r60": null }, "status": "pending" }
  ]
}
```

## 硬規則

1. `daily.tracked[].decision`、`context.timeframes`、六角色文案——凡是會被人讀到的結論，一律派生自該股 `primary_decision`，禁止各自重算；CI 一致性測試把「打架」當 fail。
2. 數字一律數值型（不含千分位字串）；日期 ISO 格式；金額單位＝元。
3. 缺資料：欄位給 `null` ＋ 在 `meta.sources` 反映，不得編數字、不得讓整檔 build 失敗（graceful degrade）。
4. 前端遇到 `schema_version` 不認識時顯示「請更新 App」而非白屏。

---

## v1.1 增補（2026-07-18 晚，Andy 拍板三包全做）

> schema_version 仍為 1（只增不改既有欄位，向後相容；前端 zod 新欄位一律 optional/nullable）。

### stocks/<id>.json 的 primary_decision 新增

```jsonc
"advice": {                        // 持有/空手雙版建議（取代單一 readable_reason 的呈現主角；readable_reason 保留）
  "holder": {                      // 已持有這檔的人看這版
    "action_text": "續抱不動，跌破 2,107 收盤再降一半波段部位。",
    "plan": [                      // 分批計畫階梯（可執行、有價位、有數量語意）
      { "trigger": "收盤跌破 2,107（防守價）", "act": "賣出波段部位的 1/2" },
      { "trigger": "收盤跌破 1,950（MA120）", "act": "波段部位全部出場，核心不動" },
      { "trigger": "站回 MA20 2,428 且法人連 2 日買超", "act": "可回補 10 萬" }
    ]
  },
  "nonholder": {                   // 空手的人看這版
    "action_text": "先不進場，等站回 MA60 且法人回補。",
    "plan": [ { "trigger": "站回 MA60 3,809 且法人連 2 日買超", "act": "試單 10 萬" } ]
  }
},
"defense_explain": "防守價 2,107＝近 20 日低點與 -8%~-15% 停損帶取較近者；跌破代表波段結構破壞。"
```

規則：plan 每條 trigger 必含具體價位或條件、act 必含具體動作與數量語意（比例或金額）；價位錨距現價 ≤15%（沿用 entry 錨點規則）。文案由 reason_codes＋數據模板生成，禁止與 action 打架（一致性測試涵蓋）。

### daily.json 新增

```jsonc
"exposure_guidance": {             // 風險溫度 → 白話曝險規則（規則表寫死在引擎，可揭露）
  "risk_temp": 9,
  "max_equity_pct": 40,            // 建議股票總曝險上限 %
  "min_cash_pct": 60,
  "new_position": "禁止新增部位",  // 禁止新增部位｜僅限試單｜可正常布局（三檔）
  "note": "風險溫度 9/10：市場劇烈波動，現金至少留六成，今天不開新倉。"
},
"events": [                        // 未來 14 天事件（法說/除息/月營收公布），來源：tw-earnings-calendar latest.json＋股利資料
  { "date": "2026-07-22", "id": "2330", "name": "台積電", "type": "earnings", "label": "法說會" }
],
"track_stats": {                   // 戰績統計（樣本不足時 rate 給 null，n 照實）
  "n": 6, "closed": 0,
  "hit_rate_5d": null, "hit_rate_20d": null, "hit_rate_60d": null,
  "note": "樣本累積中，5 日結果最快 07-24 開始回填"
}
```

### 新 API：POST /api/track

`{"stock": "2603"}` → 透過 GitHub contents API 把代號加進 `data/tracked_stocks.json`（Vercel env `GH_PAT`），201 回 `{"ok":true,"pending":"次一交易日 14:30 起納入每日更新與防守價監控"}`。上限 20 檔（超過回 409）；重複回 200 idempotent；代號格式驗證同 /api/analyze。加入後 App 前端立即把該股放進 localStorage watchlist 顯示「監控生效中（明日起）」。

### 前端本地新設定（localStorage，不進契約檔案）

`total_capital`（預設 1,000,000）：持股頁可改；組合總覽卡用它算曝險 %／現金水位，與 exposure_guidance 比對超標提示。

---

## v1.2 增補（2026-07-18 夜，Andy 拍板：機率扇形圖預估走勢）

### stocks/<id>.json 新增 `forecast`（整組可為 null＝樣本不足）

```jsonc
"forecast": {
  "method": "monte_carlo_gbm",     // 幾何布朗運動蒙地卡羅；drift=0（不假裝知道方向），vol=歷史波動（EWMA 250d）
  "horizon_days": 63,              // 約 3 個月
  "n_paths": 2000,
  "vol_annualized": 0.42,
  "as_of": "2026-07-17",
  "bands": [                       // 每 3 個交易日取樣一點，含 d=0（現價）與 d=63
    { "d": 0, "p10": 2290, "p25": 2290, "p50": 2290, "p75": 2290, "p90": 2290 },
    { "d": 63, "p10": 1980, "p25": 2140, "p50": 2295, "p75": 2460, "p90": 2650 }
  ],
  "scenarios": { "bear": 1900, "base": 2150, "bull": 2600 },  // 3 個月估值錨（context.valuation 派生；null 可）
  "prob_range_70": [2050, 2600],   // horizon 的 p15~p85（「3 個月後 70% 機率落在此區間」）
  "disclaimer": "統計推算（歷史波動隨機模擬），非方向預測；突發事件不在模型內。"
}
```

規則：模擬 seed 由 stock_id＋data_date 決定（同日重跑結果一致、可測試）；價格樣本 <120 根日 K → 整組 null；scenarios 直接引用 valuation 三情境不得另算。前端 zod optional/nullable。

補充說明（大檢查・邏輯組修復 8／R1）：`valuation.warning` 非 null（Base 偏離現價過大、可能低估，不作為減碼依據）時，`forecast.scenarios` 一律回 `{bear:null, base:null, bull:null}`——不得把同一個被判定不可信的悲觀估值裸奔到前端（primary_decision 已用同一護欄壓抑減碼）。前端據此不畫該三條線。物件形狀維持不變（三鍵仍在，只是值為 null）。

補充說明（修復 16）：`forecast.disclaimer` 標明此為「零漂移」歷史波動隨機模擬（drift=0 的 GBM），與週報「下週 70% 區間（零漂移波動模擬）」短註同語意。

---

## v1.3 增補（2026-07-18 夜二，Andy 拍板：預估走勢 2.0 五項全做）

### `forecast` 結構升級（取代 v1.2 單一 horizon；前端同步改，zod 仍 optional/nullable）

```jsonc
"forecast": {
  "method": "monte_carlo_gbm", "n_paths": 2000, "vol_annualized": 0.40, "as_of": "2026-07-17",
  "history": [ { "d": -63, "close": 2453 }, ... , { "d": 0, "close": 2290 } ],  // 過去 63 交易日，每 3 日取樣＋必含 d=0
  "horizons": {                       // 同一次模擬跑到 126 日，切三段
    "m1": { "days": 21,  "bands": [ {"d":0,...}, ... ], "prob_range_70": [x, y] },
    "m3": { "days": 63,  "bands": [...], "prob_range_70": [x, y] },
    "m6": { "days": 126, "bands": [...], "prob_range_70": [x, y] }
  },
  "week_range_70": [x, y],            // d=5 的 p15~p85（週報連動用）
  "scenarios": { "bear": ..., "base": ..., "bull": ... },   // 錨在 m3（維持 v1.2 語意）
  "event_markers": [ { "d": 12, "date": "2026-08-05", "label": "法說會" } ],  // horizon 內已知事件（法說/除息；來源同 daily.events＋evidence.events），無=空陣列
  "accuracy": {                       // 預估準確度回測（forecast_log 統計；樣本 <10 給 null rate）
    "n_evaluated": 0, "hit_rate_70": null,
    "note": "樣本累積中：每天記錄預估區間，5 日後開始回填驗證"
  },
  "disclaimer": "…"
}
```

### 新增 `data/forecast_log.json`（引擎內部，非前端契約）

每日 build_snapshots 時對每檔追蹤股 append：{date, stock_id, week:[p15,p85], m1:[...], m3:[...]}；同 (date,stock_id) 覆蓋。到期驗證：date+5 交易日（week）／+21（m1）／+63（m3）後用實際收盤回填 hit true/false；accuracy.hit_rate_70 = 所有已回填 horizon 樣本的命中率。

### weekly_brief 連動

持股劇本每檔加一行「下週 70% 區間：X ～ Y」（讀 stocks/<id>.json 的 forecast.week_range_70；缺欄位跳過）。

---

## v1.4 增補（2026-07-18 夜三，Andy 給參考圖：短線劇本推演取代扇形當主角）

### stocks/<id>.json 新增 `short_scenarios`（整組可 null）

```jsonc
"short_scenarios": {
  "status": "ok",                    // ok｜insufficient_data（後者只給 message 一句話）
  "horizon": "1-4 週",
  "key_levels": { "supports": [2106.8, 2094.3], "resistances": [2324.0, 2428.2] },  // 由防守價/MA/近20日高低取、各最多 3 個
  "scenarios": [                     // 恰 3 個，依 prob 降冪＝劇本一/二/三
    {
      "id": "base",                  // base｜risk｜bull
      "title": "劇本一・守住防守價",
      "probability_pct": 50,
      "trigger": "收盤守住 2,107（防守價）",
      "price_path": [2290, 2107, 2324],
      "price_path_text": "2,290 → 回測 2,107 → 反彈 2,324（MA60）震盪",
      "narrative": "股災後在防守價與季線之間震盪打底，等法人止賣。",
      "invalidation": "收盤跌破 2,107 本劇本失效，切換劇本二。",
      "action": { "stance": "hold", "text": "維持續抱，不加碼（連動計畫階梯第 1 條）" }
    }
  ],
  "prob_note": "機率為規則估計（依三燈/籌碼/大盤查表），不是統計勝率，更不是保證。",
  "disclaimer": "劇本＝條件推演；價位到了不代表會停，跟著失效條件走。"
}
```

### 生成規則（引擎實作依據；Codex 07-18 設計＋主對話補模板）

- **關鍵位**：supports＝{防守價、MA20/60/120、近20日低}∩(<現價) 取最近 3 個；resistances＝同集合∩(>現價)＋近20日高＋entry 錨 取最近 3 個。
- **三劇本模板**：base＝守住最近支撐→「現價→回測最近支撐→反彈最近壓力震盪」；risk＝跌破防守→「防守→下探次一支撐→守住才反彈」＋invalidation 連動 advice 減碼條；bull＝站上最近壓力＋法人連 2 日買超→「現價→壓力1→壓力2」，action 受大盤 new_position 閘門（禁新倉時 stance=wait、文字改「不追價，僅觀察」）。狀態變形：空頭排列時 base 敘事用「反彈至壓力後仍震盪」；事件前 14 天內有 event_markers → narrative 前綴「事件前不押注：」。
- **機率查表**（技術燈×籌碼燈 → base/risk/bull）：gg 50/20/30、gy 50/25/25、gr 45/35/20、yg 45/25/30、yy 50/30/20、yr 40/40/20、rg 40/35/25、ry 35/45/20、rr 30/50/20；修正：大盤偏空 risk+5 bull-5（偏多反向）；跌破防守 risk+10 base-10；突破近20日高 bull+5 base-5；法人連買≥3 bull+5 risk-5（連賣反向）；上下限 10~65%、normalize 100%、整數化差額補末位。
- **紅線**：現價/近20日高低/防守價缺、停牌、三燈兩個以上 unknown → status=insufficient_data＋一句話；禁用「必漲/保證/高勝率」，價位序列一律接「↑/↓/震盪」中性動詞。
- 一致性：scenarios 的 action 不得與 primary_decision.action 打架（例如 primary=減碼時 bull 劇本 action 最多「觀察」）。
- **大盤新倉閘門統一同源**（大檢查・邏輯組修復 10／Y7）：bull 劇本的新倉閘門 build 階段以 `daily.exposure_guidance.new_position`（由 risk_temp 來，與 advice 層同源）為準——analyze 階段先用 market_light proxy 算一版，build_snapshots 透傳時重跑 bull 閘門對齊權威值，不再兩層各用不同訊號。

---

## 內部檔補充說明（非前端契約，引擎內部 log；大檢查・邏輯組修復）

- **`data/scenario_log.json`** 每筆新增 `model_version`（規則表版本，現行＝`"v1"`；規則表 `_PROB_TABLE` 改版時 bump）與 `raw_probs`（當天查表＋修正後的三劇本機率原值，供稽核回溯）。校正（`prob_calibration.json`）**只吃同 `model_version` 的樣本**（不同規則表算出的 realized 頻率不得混算；舊 entry 無此欄視為 v1）。realized 判定需「連續 2 個收盤」確認（連 2 日收破防守=risk、連 2 日收上 r1=bull，時間序先觸發者定案），並用除權息還原後收盤（`ex_div_adjusted` 記錄是否調整）。校正統計時同一 `(stock_id, bucket)` 30 天內只計 1 筆（去重防連日快照自相關灌爆 n）；混合值 clamp 與 normalize 迭代收斂，保證最終仍在規則表 ±15pp 內。
- **`data/forecast_log.json`** 讀壞檔改 fail-closed（警告＋跳過本次寫入、不覆寫歷史），與 recommendation_log／scenario_log 三支 log 行為一致。
- **`data/recommendation_log.json`** 的 `backfill_outcomes` 已接進 `build_snapshots.main()`（先回填再組 track_stats）；命中率口徑：看多建議報酬為正、防禦（減碼）建議報酬不為正即算命中，**觀望（無方向主張）一律排除**在統計之外。
- **交易資料日**：行情日缺時退所有個股 `as_of_date` 最大值；兩者皆無 → 跳過 forecast/scenario log 寫入（不記非交易日樣本）。複評日 `reeval_date`＝+7 曆日後「下一交易日對齊」（週六→+2、週日→+1；近似，不接國定假日行事曆）。

---

## v1.5 增補（2026-07-19，Andy 拍板 ABCD 四包全做）

### daily.json 新增

```jsonc
"today_command": {                  // D 包・今日指令中心（首頁主角，全部由引擎規則生成）
  "headline": "風險 9/10：今天不開新倉，只守防守價。",   // 一句話 ≤25 字
  "action": { "text": "若台積電收盤跌破 2,107，波段部位減半。", "stock_id": "2330" },  // 最多一個；無動作日給 null
  "todos": [                        // 0-3 條，急迫排序；來源：距防守 <3%、複評日到期、曝險超標、事件明日
    { "text": "聯發科距防守價只剩 2.1%，今天留意收盤", "stock_id": "2454", "kind": "defense_near" }
  ]
},
"delta": {                          // 昨→今變了什麼（與上一份 snapshot 比；首日/缺前檔給 null）
  "since": "2026-07-17",
  "items": ["台積電 續抱→減碼（跌破防守）", "風險溫度 7→9", "新增監控：長榮"]   // 只列有變的，≤5 條
},
"picks": {                          // B 包・主動選股（候選池→三準則評分→風控閘門）
  "generated_from": "tw-stock-screener opportunities + FinMind",
  "gate": "禁止新增部位",           // 引 exposure_guidance.new_position
  "note": "大盤禁新倉：短線/波段今日不推新倉，長線名單僅供研究等解禁。",  // gate 觸發時的誠實說明
  "short": [],                      // 禁新倉時空陣列
  "swing": [],
  "long": [                         // 每檔＝操作卡（欄位同 pick 結構）
    { "id": "2308", "name": "台達電", "close": 305.0, "score": 78, "confidence": 65,
      "action_summary": "分批佈局區 290-300，跌破 275 停損",
      "entry_zone": [290, 300], "defense_price": 275,
      "invalidation": "跌破 275 或營收連 2 月轉負",
      "reasons": ["營收 YoY 連 6 月正成長", "PER 落在 3 年 35% 分位", "外資連 5 日買超"] }
  ]
}
```

規則：short ≤1、swing ≤3、long ≤5；被選標的當日會跑完整 analyze（有 stocks/<id>.json 可點進去）；score/評分準則寫死可揭露（短線=動能+量+籌碼轉向；波段=均線結構+RS+法人連續+R/R≥1.8；長線=營收/獲利品質+估值分位+安全邊際）；文案全條件式禁明牌語言。

### stocks/<id>.json

`price.change_pct` 從 null 改為真值（引擎由日線倒數兩根計算）。

### App 行為（不進 JSON 契約）

- deeplink：`/?stock=2330` 開啟即進查股票並載入該股（TG 警報訊息附此連結）。
- 核心持股（is_core_holding）在持股頁顯示核心語言（「定期定額照常」），不套波段防守模板。
- C 包・交易日誌全存 localStorage（`journal` key：{date, stock_id, action, price, qty, followed_advice, note}）；連敗保護＝前端規則（journal 連續 2 筆停損 → 部位建議顯示減半＋警示；3 筆 → 建議只觀察）；週五覆盤卡與分層戰績由前端從 journal＋track 計算。
- track_stats 擴充（引擎）：per timeframe 分層（short/swing/long 各自 n 與 hit_rate，樣本 <5 null）。

---

## v1.6 增補（2026-07-19 下午，Andy 拍板：選股大腦 2.0＋執行鏈路閉環）

### daily.picks 結構升級（分艙；取代 v1.5 的 short/swing/long 平鋪——前端同步改，舊欄位不再輸出）

```jsonc
"picks": {
  "generated_from": "...", "gate": "禁止新增部位",
  "note": "...",
  "pools": {
    "actionable": [],               // 今日可操作（gate 允許時才有；卡片含完整操作資訊）
    "on_deck": [                    // 解禁後優先（強勢波段/短線候選，禁新倉時不消失、標「等解禁」）
      { ...pick, "horizon": "swing", "status_note": "等大盤解禁", ... }
    ],
    "research": [ ...pick ]         // 長線研究名單
  },
  "roster_changes": {               // 新面孔機制（與上一份 picks 比）
    "new": ["2317"], "dropped": ["1101"],
    "stay_note": "和泰車 連續 3 日留任（波段結構未變）"   // 連任 ≥3 日時給一句留任原因；無變化日 null
  }
}
```

pick 新增欄位：`tenure_days`（連續入榜天數）、`sector`（族群名，來自 tw_sectors 對應）、`rank_move`（↑↓−）。操作數字（defense/entry_zone/invalidation）一律引用該股 stocks json 的 primary_decision（v1.6 一致性原則，已由一致性修復落實）。

### 評分 v2（引擎規則，揭露於 picks.py docstring）

- 長線：估值＋殖利率合計權重上限 40%；新增品質因子（營收加速度=近3月YoY-近12月YoY、毛利率趨勢與 ROE 有資料才計、無資料不虛high）；金融股（產業=金融保險）估值改 PBR 分位路徑；技術紅燈（跌破全部均線）扣分；估值 warning 存在時 cap 分數 ≤70。
- 輪動席位：讀 data/tw_sectors.json 領先族群——on_deck 保留 1-2 席給領先族群最強分者；落後族群非深度價值（估值分位 <30%）降權 10%。
- 短線/波段評分沿用 v1.5。

### 執行鏈路（P1 包）

- **picks 進場監控**：picks 各池標的的 entry 錨點當日直接寫進 `alerts_snapshot`（type=entry、source="picks"），不必等加入 tracked——到價即 TG 提醒。alerts_snapshot entry 加 `source` 欄位（"tracked"|"picks"）。
- **前端**：精選卡「＋監控」按鈕（POST /api/track，同查股頁）；查股頁分析結果加「記一筆」按鈕（預填代號/名稱/現價 開 journal 表單）；連敗冷靜期作用於下單建議顯示——streak≥2 時 StockSearch/精選卡的部位/試單金額顯示減半並標「冷靜期」、≥3 顯示「暫停新倉」。

---

## v1.7 增補（2026-07-19 下午二，Andy 拍板：K 線疊層/中長線方向判讀/盤中現價）

### stocks/<id>.json 新增

```jsonc
"ohlc": [                           // 過去 60 交易日日 K（K 線圖用；缺資料 null 整組）
  { "d": "2026-07-17", "o": 2300, "h": 2320, "l": 2280, "c": 2290, "v": 45123 }
],
"mid_long_reads": {                 // 中長線方向判讀（取代「只會變寬的區間」的操作價值空缺）
  "swing": {                        // 波段 1-3 月
    "bias": "中性偏空",             // 五檔 stance 同 primary
    "path_text": "可能先回測 MA120 2,094，不破且法人止賣才有波段反轉條件",
    "flip_condition": "站回 MA60 2,324 且連 2 日買超 → 轉中性偏多",
    "basis": ["月線結構空方", "估值偏貴", "外資連賣"]   // 2-3 條含數字更好
  },
  "mid": { ... }                    // 中期 3-12 月（估值/基本面趨勢為主）
}
```

規則：bias 派生自 primary_decision 的 timeframes stance（禁另算）；path_text/flip_condition 錨點沿用 ≤15%/已有關鍵位規則、與劇本語言一致；mid 的 basis 以估值 band＋營收趨勢＋產業結構為主。K 線疊層線＝defense_price/entry 錨/劇本價位（前端從既有欄位取，不新增）。

### 新 API：GET /api/quote?ids=2330,2454

serverless 代理 TWSE MIS 即時報價（純 stdlib；瀏覽器直打 MIS 有 CORS 擋所以走代理）。回 `{ "2330": {"price": 2295, "change_pct": 0.2, "at": "10:32", "stale": false} }`；上限 12 檔/次；per-instance 60 秒快取；非交易時段回 `{stale: true, price: null}`（前端 fallback 收盤價）。限流同 analyze 模式。

### App 行為

開啟/切前景時對「持股＋監控＋當前查詢股」抓 /api/quote 刷新現價與距防守 %；顯示「盤中 HH:MM」徽章與收盤價區別；盤外自動退回快照收盤（徽章維持「MM-DD 收盤」）。分析結論不因盤中價重算（收盤級決策設計不變）。K 線漲跌用色**沿用全站綠漲紅跌**（與台股看盤軟體紅漲相反——為 App 內一致性，圖上加一次性小註「綠漲紅跌」）。

---

## v1.8 增補（2026-07-19 傍晚，Andy 拍板：首頁大盤作戰區四件全做）

### daily.json 新增 `market_battle`（整組可 null）

```jsonc
"market_battle": {
  "ohlc": [ { "d": "2026-07-17", "o": ..., "h": ..., "l": ..., "c": 42671.3, "v": null } ],  // TAIEX 60 交易日（v 無資料給 null）
  "key_levels": { "supports": [41500, 40800], "resistances": [43800, 45600] },  // 近期低點/月線/季線挑 ≤3 個，間距 ≥1.5%
  "scenarios": { /* 與個股 short_scenarios 同構：status/horizon/scenarios[3]/prob_note/disclaimer */ },
  "flow": {
    "foreign_streak": { "direction": "sell", "days": 7, "latest_yi": -519.0 },  // 外資連 N 日、最新一日億元
    "leading_sectors": ["軍工航太", "封測"],       // tw_sectors 領先族群 top2；無資料空陣列
    "us_overnight": [ { "id": "SPX", "change_pct": -1.0 }, { "id": "SOX", "change_pct": -1.6 } ]
  },
  "forecast_range_m1": [40200, 45100]              // GBM on TAIEX，1 個月 70% 區間；樣本不足 null
}
```

### 生成規則

- 大盤劇本＝複用 short_scenarios 引擎，映射：技術燈=TAIEX vs MA20/60/120 結構（多頭排列 green／跌破月季線 red／其餘 yellow）；籌碼燈=外資連買賣（連買≥3 green／連賣≥3 red／else yellow）；「大盤 status」修正項改用 VIX 單日 ±8% 與美股 SOX 方向；關鍵位=近 20 日低、MA20/60/120、近 60 日高，沿用間距去重（大盤 ≥1.5%）與 ≤15% 錨點；核心持股/部位語言不適用——action 改「曝險語言」（維持防禦／可回補試單／降曝險）。
- flow.foreign_streak 由 FinMind institutional 近 10 日合計；leading_sectors 讀 data/tw_sectors.json 排名前 2。
- forecast_range_m1＝forecast.py GBM 引擎餵 TAIEX 序列（drift=0 同規則）取 m1 p15/p85。
- 前端「大盤作戰區」插在今日頁指令卡之後、我的持股之前：K 線（複用 CandleChart，疊 key_levels）＋劇本卡（複用 ShortScenarios 元件、機率條同語言）＋flow 一行卡＋區間一句話（附「零漂移模擬」註）。
