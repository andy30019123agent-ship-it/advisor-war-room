# Design System Master File — 投顧戰情室 App 版

> **✅ Andy 於 2026-07-18 核准：方向 C「iOS 原生感・清透」**（三方向 mockup 比稿勝出，參考稿 `proposals/2026-07-18/dir-C.html`）。
> 本檔是 App 版色/字/距唯一權威；任何頁面不得偏離。頁面級例外寫 `pages/<page>.md`。
> 舊版（07-15 Neumorphism 粉白，用於靜態報告站）已歸檔於 `../advisor-war-room_archived-2026-07-15-neu/`，不再適用。

---

**Project:** advisor-war-room（App 版重建）
**Approved:** 2026-07-18 by Andy
**氣質:** 像 Apple 內建股市 App 的專業原生感——清透、分組列表、大標題、hairline 分隔

---

## 色彩 Token（元件內禁裸 hex，一律引用變數）

| Token | Hex | 用途 |
|---|---|---|
| `--bg` | `#F2F2F7` | 頁面底（iOS systemGroupedBackground） |
| `--card` | `#FFFFFF` | 卡片／分組列表底 |
| `--hairline` | `#D8D8DE` | 分隔線（1px；列表內縮排 16px 起） |
| `--accent` | `#4A55C7` | 唯一強調色：主 CTA、選中 tab、關鍵字 |
| `--text` | `#1C1C1E` | 主文字 |
| `--text-soft` | `#6C6C70` | 次要文字 |
| `--text-faint` | `#9A9AA0` | 弱化文字，**只准用於 placeholder／純裝飾**（對白卡對比僅 2.8:1，不達 4.5:1，不可用於任何需要閱讀的文字，含群組標題／關鍵標籤） |
| `--green` | `#197542` | 漲／正面（新鮮度、上漲）——維持綠漲紅跌（2026-07-19 大檢查為對比 ≥4.5:1 加深，原 #1D8A4E） |
| `--red` | `#C13328` | 跌／風險（防守價、高風險溫度）（同上加深，原 #D6392C） |
| `--amber-bg` / `--amber-text` | `#FFF1DE` / `#975A0E` | 警示徽章（偏空防禦等市場狀態）（text 加深，原 #B26A11） |

規則：accent 一頁只點在一個主 CTA＋導覽選中態；漲跌語意色不得挪作裝飾。

## 字體

- 全站系統字：`-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang TC", "Helvetica Neue", sans-serif`（不載入 web font，原生感即來自系統字）
- 數字：`font-variant-numeric: tabular-nums`＋weight 600 起（等寬對齊）
- 層級：Large Title 32px/800 → 結論句 21px/700 → 卡片標題 17px/700 → 內文 16px/400 → 群組標題 13px/600 大寫字距 0.4px → 徽章 12.5–14.5px/600–700
- 內文 ≥16px、行高 ≥1.5

## 間距與形狀

- 間距 4/8 倍數；頁面左右 padding 16px；縱向節奏 8/12/16/20
- 卡片 radius 12；徽章 radius 8；搜尋列 radius 12、底 `rgba(118,118,128,0.12)`
- 觸控目標 ≥44×44；內容區 padding-bottom ≥ tab bar 高＋16px
- 陰影：原則上不用（清透感靠 hairline 與底色對比）；必要時僅極輕（≤ 0 2px 8px rgba(0,0,0,.04)）

## 元件慣例

- 底部 tab bar 固定 4 項：今日／持股／查股票／戰績；icon 一律 inline SVG 線條風（同 stroke 寬），選中 = `--accent`，未選 = `--text-faint`
- 分組列表：群組標題（13px 大寫弱化）＋白卡內多列，列間 hairline，列尾 chevron 表可點
- 資料新鮮度徽章固定在頁首：綠點＋「MM-DD HH:MM 已更新」；資料過期改 amber 並寫「資料為 X 天前」
- 一頁一個主 CTA（首頁＝搜尋列）；次要動作視覺降級
- 動畫 150–300ms、只動 transform/opacity、尊重 prefers-reduced-motion

## Anti-slop 禁令（違反＝不可交付）

emoji 當 icon／裸 hex／無來由漸層毛玻璃／三卡並排無主從／非 4/8 間距／內文 <16px／對比 <4.5:1／觸控 <44px／手機橫向捲動／>400ms 動畫／多主 CTA——全部封殺。

---
*（本檔 2026-07-18 由主對話依 Andy 核准的 dir-C mockup 重寫；ui-ux-pro-max 產生器的原始輸出已被本檔取代。）*
