# Design System Master File — advisor-war-room

> **定案設計：Mineral Signal War Room（礦物訊號戰情室）**
> **Andy 於 2026-07-14 核准**（方向由 Codex gpt-5.5 設計、Claude 實作＋審查）。
> 此後這份是週報／個股報告色・字・版的唯一權威。之前那版自動生成的「暗色 OLED dashboard」建議稿**從未採用、已作廢**。

**Category:** Financial Advisory Report（週報 + 個股報告）
**CSS 位置：** 樣式 inline 在產生器裡 —
- 週報：`warroom/build_weekly.py` 的 `TEMPLATE` `<style>`
- 個股：`warroom/report_stock.py` 的 `TEMPLATE` `<style>`
（兩檔共用同一套 token 與視覺語言；改設計改這兩處的 `<style>`。因走 `str.format`，`<style>` 內大括號要**雙寫** `{{ }}`。）

---

## 設計概念
像一份放在「霧面礦物紙」上的高階戰情簡報。低噪音背景、清楚層級、線條分隔取代方框陰影、少量高彩訊號色做記憶點。專業可信但不像制式金融 dashboard。

## 色彩（實際使用中的權威值）
| Role | Hex | 用途 |
|------|-----|------|
| paper（底） | `#EFF2EA` | 頁面背景（霧綠礦物白） |
| surface / surface2 | `#FBFDF7` / `#F5F8F0` | 卡片、格子底 |
| ink / ink2 | `#151713` / `#30362C` | 主標題數字 / 內文 |
| muted / faint | `#65705F` / `#899480` | 標籤 / meta |
| rule / rule-dk | `#D8E0D1` / `#AEB9A5` | 髮絲線分隔 |
| accent（深墨卡） | `#1A1D14` | 投資長總結卡背景（深黑質感錨點） |
| **acid（訊號萊姆）** | **`#C7F04A`** | 招牌點綴：章節編號、頂部訊號帶、狀態點 |
| ox / ox2（銅） | `#A85C3A` / `#6E3D2B` | 次點綴、hover、日期 |
| up / down | `#167A54` / `#B64238` | **漲=綠 / 跌=紅（美股慣例，維持未翻轉）** |
| warn | `#9A6818` | 中性/警示 |

## 字體
- **Space Grotesk**（`--disp`）：數字、英文、標題、結構感。
- **IBM Plex Sans TC**（`--text`）：中文內文，乾淨不制式。
- Google Fonts `@import`（放 `<style>` 最前）。

## 關鍵版式
- 頂部 8px 訊號色帶（acid→copper→ink，`body::before`）。
- 投資長總結 = 深墨卡 + 頂部 acid→copper 光帶，白字，是視覺錨點。
- 章節：acid 方塊編號 + Space Grotesk 標題 + 髮絲線。
- 團隊觀點：淺底框 + 銅色小標籤。
- 卡片圓角 8px、線條為主、陰影克制。
- 內容容器 max-width 800–860 置中。

## 硬規則（違反＝不可交付）
- **每份 HTML 開頭必有** `<meta name="viewport" content="width=device-width, initial-scale=1">`（缺了手機會縮成 980px、字超細；2026-07-14 三版都曾漏，已修）。
- 不用 emoji 當 icon（紅綠燈用 `.tl` CSS 圓點 `.tl.g/.tl.y/.tl.r`）。
- 不用無意義漸層文字（`background-clip:text`）。
- 深墨卡上的文字一律用淺色（`#DDE6D5`/`#AEBBA5`/`#FBFDF7`），別用 `--muted`。
- 漲跌色語意固定：`.up`綠 / `.down`紅 / `.muted`持平——**要翻成台股慣例（紅漲綠跌）須 Andy 另外拍板**。
- 響應式斷點 `@media(max-width:700px)`；`prefers-reduced-motion` 要處理。
- 對比 ≥4.5:1；可見 focus。
