# 投顧戰情室 Advisor War Room

> Andy 的**專屬個股投顧戰略團隊**。台美股一起看，由大到小（大盤→類股→個股→主題→事件），
> 每個判斷都有數據依據＋團隊解讀＋反方壓力測試。**決策輔助，非投資建議、非保證獲利。**
> 狀態：MVP（Phase 0–3）完成、真實資料可跑（2026-07-14）。本檔＝操作手冊。

---

## 1. 這是什麼

一支 6 角色 AI 投顧團隊：基本面分析師、技術分析師、消息面分析師、風控長、魔鬼代言人、投資長（綜合）。
- **紅綠燈由「數據＋固定規則」算**（技術面均線/RSI/量、基本面營收 YoY/PER 分位、籌碼三大法人），
  AI（Claude）只負責**解讀與反駁**，不憑感覺喊買賣——避免玄學。
- 兩種產出：
  1. **單檔深度報告**：說「研究 XXXX（股號）」→ 一份完整投顧報告。
  2. **一週兩次戰情週報**：大盤→類股→個股→主題雷達→事件，一份 top-down 報告。
- 白底柔和 neumorphism 風、可點擊開合。

## 2. 操作：「更新戰情室」怎麼跑

```bash
cd ~/Desktop/agent/advisor-war-room
# ① 抓資料 + 跑引擎 + 掃主題 + 大盤/類股 → 印數據摘要
./.venv/bin/python -m warroom.update            # 個股用選股器機會清單；含主題
#   （可選）./.venv/bin/python -m warroom.update --stocks 2330,2454,3661 --no-themes
# ② Claude 讀上面摘要 → 更新 data/weekly_narration.json 的團隊觀點（6 角色/大盤/類股/主題）
# ③ 組報告
./.venv/bin/python -m warroom.build_weekly       # → reports/weekly.html
# ④ 截圖(500 寬)驗證 → publish Artifact → 發 Andy
```

單檔報告：
```bash
./.venv/bin/python -m warroom.analyze_tw 2330    # → data/2330.json
# Claude 寫 data/2330.narration.json（6 角色，依真數字）
./.venv/bin/python -m warroom.report_stock 2330  # → reports/2330.html
```

## 3. 模組地圖（warroom/）
| 檔 | 作用 | 資料源 |
|---|---|---|
| `analyze_tw.py` | 台股個股三維規則引擎（燈＋證據＋新聞） | FinMind(價/量/月營收/PER/三大法人) |
| `news.py` | 新聞（台股優先 Google News RSS 中文，GDELT 備援） | Google News RSS / GDELT |
| `report_stock.py` | 單檔報告產生器（data json＋narration json→HTML） | — |
| `market.py` | 大盤層（台美指數/SOX/VIX/10Y/DXY/台幣/外資） | FinMind + yfinance |
| `sectors.py` | 類股層＝美股族群動能排名→台股供應鏈對應表 | yfinance |
| `themes.py` | 主題雷達（GDELT 熱度＋領頭股確認才成案；thesis log） | GDELT + yfinance |
| `build_weekly.py` | 週報組裝（market+sectors+個股+主題+事件→HTML） | 上述 + data/*.json |
| `update.py` | 一鍵更新 orchestrator（串全部、印數據摘要給 Claude） | — |

資料契約：個股層讀選股器 `../tw-stock-screener/dist/data/opportunities.json`（整併既有工具）。
產出：`data/*.json`（引擎輸出＋我寫的 narration）、`reports/*.html`。

## 4. 設計紀律（每份報告都遵守）
- 燈由規則算、LLM 只解讀＋反駁；三面矛盾**誠實觀望**不硬給方向。
- 跨市場輪動只用「昨晚美股已收盤」資料推今日台股。
- 主題「熱度上升＋個股確認」雙訊號才成案；純新聞爆量只進觀察；每主題記首見日防事後諸葛。
- 數據標來源與抓取時間；抓不到即註記缺漏、**絕不編造**。
- 每份帶免責：投資決策輔助，非投資建議、非保證獲利，風險自負。

## 5. 環境
- venv：`.venv/`（Python 3.9.6 + requests/pandas/yfinance/FinMind）。
- 雷：FinMind 免費版有用量上限（超量 402、亂打恐 IP 暫封）→ 大量跑考慮申請免費 token；
  GDELT 會 429（themes.py 已內建退避重試，故較慢、建議背景跑）；TWSE `/v1/fund/T86` 已掛（改 FinMind）。
- 詳細驗證：`phase0/RESULTS.md`。

## 6. 待辦 / 下一步
- Phase 4 戰績牆：判斷落地存檔，回算 5/20/60 天命中率、校正權重。
- 美股個股引擎（目前個股層以台股為主；美股在大盤/類股層已含）。
- 類股層補台股量化強度（目前 US→TW 為 mapping 表）。
- 主題雷達擴候選、接 arXiv。
- git init（`.venv/`、`data/` 要 gitignore）。
