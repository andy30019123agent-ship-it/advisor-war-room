# 2026-07-15 戰情室升級會議紀錄（Claude × Codex）

> 背景：Andy 抱怨報告「太粗糙」，要「網頁上看到最精準正確的投資建議、建立專業投資團隊」。
> Claude 派 Explore subagent 與 Codex（gpt-5.5, reasoning=high, 讀了 repo＋上網對標）各自獨立診斷後交叉比對，結論一致。
> 狀態：已發 Discord 問 Andy 路線（P0 先行／一次到位／自選）＋ 7 題投資人問卷，**等回覆中**。

## 診斷（雙方一致的缺口）
1. 結論只有方向（偏多/觀望/5 種文字＋-1~1 加權分），無目標價、上下檔、R/R、持有週期、失效條件（report_stock.py 只渲染 action_dir/conf/score/stop）。
2. 無合理價值區間：只有 PER 現值＋歷史分位，答不出「多少才合理」。
3. 無個股部位建議：週報只有整體曝險區間（如 30-45%）。
4. 基本面僅月營收 YoY＋PER 分位＋殖利率；無 EPS/毛利/營益/ROE/FCF/負債/同業比較。
5. 籌碼僅三大法人合計淨額＋連續天數；未拆外資/投信/自營、無佔均量比、無融資券。
6. 新聞只有標題清單，情緒/事件分類未做（2330.json 明寫待補）。
7. 無戰績回測，信心度（高/中/低）憑感覺。
8. 大盤燈只看加權/SOX/VIX 三點；類股是人工 mapping 無台股量化強度。
9. **品質 bug（兩邊獨立證實）**：narration 手寫數字與引擎輸出不同步（narration: 連賣3天/收2440/RSI55/多頭排列 vs 2330.json: 連賣4天/收2420/RSI53/均線糾結）。已向 Andy 承認。

## 升級藍圖（Codex 提案、Claude 審過，全部免費資料源）
### P0（1-2 天，立即見效）
- `decision_engine.py`：rating（買進/試單/續抱/觀望/減碼）＋時間框架＋失效條件。
- 合理價值區間 v1（相對估值）：Forward EPS = TTM EPS × clamp(近3/6/12月營收YoY加權, -20%, +40%)；Bear/Base/Bull = Forward EPS × 個股 3-5 年 PER 25/50/75 分位（大盤紅燈時 PE 上限下修一檔；金融/循環股改 PBR/ROE）。報告必揭露所用 EPS 與倍數。
- 風報比表：stop = max(ATR14×2 下緣, 關鍵均線/近20低)；target = base fair value 或壓力位；R/R < 1.5 不給買進。
- 部位單位化：0 / 0.5 / 1 / 2 單位（依 R/R、信心、市場 regime、波動；單位金額由 Andy 問卷定）。
- 信心度規則化 0-100：資料完整度30%＋三燈一致性30%＋R/R20%＋市場regime20%。
- 敘事一致性檢查：build 前比對 narration 關鍵數字 vs 引擎 JSON，差異>1% 或日期落後就 fail。
### P1（各 1-3 天）
- 籌碼拆解 v2（FinMind 分法人＋佔20日均量＋分歧標記）。
- 基本面品質分數（FinMind 財報三表，6 因子各 0-2 分）。
- 台股類股量化輪動（5/20/60 日等權動能＋量能＋相對加權）。
- 事件日曆/催化劑（法說/除息/營收公布/FOMC/CPI）。
- 戰績牆＋權重校準（recommendation_log.json，5/20/60 日自動回填，月調權重）。
### P2
- 美股個股引擎（yfinance＋SEC EDGAR companyfacts）；新聞事件規則分類器。

### 進出場專業寫法（定案原則）
- 條件式建議，不寫「必買」：「若 A/B/C 成立可配置 X 單位；D 失效降至 Y」。
- 回測型進場＝支撐±0.5ATR＋隔日收盤站回；突破型＝收盤破近20日高＋量>1.3×20日均量。
- 停損三層：價格（entry-2×ATR14 或關鍵均線/前低）、基本面（營收YoY轉負且連2月低於6月均）、籌碼（法人連3日同向賣且佔均量>15%）。

## Claude 審查備註（動工前要驗）
- FinMind 免費版能否穩定取得財報 EPS/三表 → 先做 Phase0 式資料驗證再寫引擎。
- FinMind 免費額度吃緊 → 申請免費 token。
- 部位/停損輸出必須保留「決策輔助非投資建議」免責與條件式語氣。

## 等 Andy 的輸入
- 路線：1️⃣ P0 先行（推薦）／2️⃣ P0+P1 一次到位／3️⃣ 自選模組。
- 問卷 7 題：操作週期、可忍回撤、建議直接度、單檔上限%、投資範圍、資金級距、首屏優先。
- 回覆後：依 brainstorming 流程寫正式 design spec（docs/superpowers/specs/）→ writing-plans → 開工。

## 原始材料
- Codex 完整輸出：scratchpad `codex_warroom_round1.log`（session 目錄，會消失；精華已收進本檔）。
- Codex 引用對標來源：FINRA Rule 2241（rating 需估值方法＋風險揭露＋時間框架）、Investopedia target price、arXiv 2407.18327。
