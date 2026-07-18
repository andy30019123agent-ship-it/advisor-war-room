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
