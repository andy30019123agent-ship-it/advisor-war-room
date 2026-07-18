# 資料契約 v1（前端 ⇄ 引擎共同介面，2026-07-18）

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
    "lights": {
      "fundamental": { "color": "yellow", "facts": ["營收 YoY +67.9%", "PER 32.8 落在近3年 82% 分位"] },
      "technical":   { "color": "green",  "facts": ["站上 MA20/60，多頭排列"] },
      "chips":       { "color": "red",    "facts": ["外資連 3 日賣超 1.6 萬張"] }
    },
    "valuation": {
      "band": "偏貴",               // 便宜｜合理｜偏貴｜很貴
      "base": 2150, "bull": 2600, "bear": 1900,
      "regime": "3y",               // 用了哪個 regime 分位
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
