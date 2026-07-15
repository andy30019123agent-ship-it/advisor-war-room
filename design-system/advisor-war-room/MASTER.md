# Advisor War Room Design System

> **Neumorphism 柔白＋淡粉版，Andy 於 2026-07-15 核准（基於 `proposals/2026-07-15/neu-final.html`）**
>
> 本檔是本專案週報與個股報告的唯一設計權威，工程實作需 1:1 復刻。舊「Mineral Signal War Room（礦物訊號戰情室）」版已廢止，不得再沿用 acid lime、銅色、深墨總結卡或礦物紙語彙。

## Design Tokens

### Colors

| Token | Hex | 用途 |
|---|---:|---|
| `--bg` | `#F0F0F3` | 頁面背景、凹面容器底 |
| `--surface` | `#FBFBFE` | 主要浮凸卡片 |
| `--soft` | `#F6F6F9` | 次層背景、KPI、列表列底 |
| `--pressed` | `#E7E7EC` | 凹/選中/分隔性底色 |
| `--line` | `#D9D9E2` | 髮絲線、低權重分隔 |
| `--ink` | `#141823` | 最高層文字、標題、重要數字 |
| `--text` | `#262B38` | 主要內文 |
| `--muted` | `#566071` | 次要文字、meta、label |
| `--accent` | `#6554D9` | 少量資訊點綴，不作語意色 |
| `--accent-2` | `#7D4FC7` | 角色小標、次點綴 |
| `--accent-soft` | `#ECE9FF` | 輔助提示底 |
| `--pink` | `#E8B4C0` | 淡粉主點綴、focus ring、儀表進度 |
| `--pink-soft` | `#F7E8EC` | 淡粉柔底、icon 圓底、hover 底 |
| `--pink-pressed` | `#F2D8DE` | 淡粉凹/選中/標題底線 |
| `--pink-ink` | `#6D3040` | 粉底上的文字、粉色滑標 |
| `--pink-line` | `#DDB8C2` | 粉色分隔線與弱邊界 |
| `--up` | `#087A46` | 漲、正報酬、綠燈文字 |
| `--up-bg` | `#DFF4E9` | 漲/綠燈柔底 |
| `--down` | `#B82033` | 跌、負報酬、紅燈文字 |
| `--down-bg` | `#FDE4E8` | 跌/紅燈柔底 |
| `--warn` | `#A06900` | 警示、中性、黃燈文字 |
| `--warn-bg` | `#FFF0CC` | 警示/黃燈柔底 |

淡粉只能作為低飽和輔助層。`--pink-ink` on `--pink-soft` 對比約 8.25:1，`--pink-ink` on `--pink` 約 5.46:1，可用於小字；不得用亮粉、螢光粉或用粉色取代漲跌/紅綠燈語意。

### Typography

Google Fonts import：

```css
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+TC:wght@400;500;600;700;800&family=Nunito+Sans:wght@700;800;900&family=IBM+Plex+Mono:wght@500;600;700&display=swap');
```

| Role | Font stack | 用途 |
|---|---|---|
| `--sans` | `'IBM Plex Sans TC','PingFang TC',system-ui,sans-serif` | 中文內文、標籤、UI |
| `--display` | `'Nunito Sans','IBM Plex Sans TC',system-ui,sans-serif` | H1/H2、決策字級 |
| `--mono` | `'IBM Plex Mono','SF Mono',ui-monospace,Menlo,monospace` | 數字、日期、價位、百分比 |

字級階梯固定，不用 viewport fluid scale：

| Token | Size / Line-height | 用途 |
|---|---|---|
| `--fs-11` | `11px / 1.45` | 極少用輔助 |
| `--fs-12` | `12px / 1.45` | chip、meta、日期 |
| `--fs-14` | `14px / 1.65` | 補充來源、免責 |
| `--fs-16` | `16px / 1.68` | body |
| `--fs-18` | `18px / 1.35` | H3 |
| `--fs-20` | `20px / 1.28` | KPI 數值 |
| `--fs-24` | `24px / 1.25` | H2 |
| `--fs-34` | `34px / 1` | 信心度數字 |
| `--fs-38` | `38px / 1.08` | mobile H1 |
| `--fs-48` | `48px / 1` | mobile 決策 rating |
| `--fs-56` | `56px / 1` | desktop 決策 rating |
| `--fs-58` | `58px / 1.08` | desktop H1 |

數字一律加 `.num`：`font-family: var(--mono); font-variant-numeric: tabular-nums; font-weight: 700;`。

### Spacing

採 4/8 倍數。常用值：`4, 8, 10, 12, 14, 16, 18, 20, 28, 32, 44, 48, 56, 76, 96`。

- 頁面：mobile `16px` 左右；desktop `32px` 左右；最大寬 `1080px`。
- section 間距：`32px`。
- 卡片 padding：主要卡 `20px`，mobile 可 `18px`。
- grid gap：一般 `14px`，首屏決策 `18px`。
- 觸控目標：所有可點擊元素最小 `44px` 高。

### Radius

| Token | Value | 用途 |
|---|---:|---|
| `--r-sm` | `12px` | flat 區、列表列、提示 |
| `--r-md` | `14px` | KPI、免責 |
| `--r-lg` | `16px` | 主卡、details、信心儀表 |
| `--r-pill` | `999px` | chip、tag、jump nav |
| `--r-circle` | `50%` | icon mark、燈號點 |

### Neumorphism Shadows

浮凸與凹面是此版的核心材質。只能用在容器，不用在文字、長段落或小字。

| Token | CSS value | 用途 |
|---|---|---|
| `--shadow-extrude` | `10px 10px 22px #C9C9D0, -10px -10px 22px #FFFFFF` | 主卡凸起 |
| `--shadow-soft` | `6px 6px 14px #D0D0D7, -6px -6px 14px #FFFFFF` | chip、icon、導覽 |
| `--shadow-inset` | `inset 6px 6px 12px #C9C9D0, inset -6px -6px 12px #FFFFFF` | 信心儀表、價值區間、progress track |
| `--shadow-hover-pink` | `3px 3px 9px #D8C8CD, -3px -3px 9px #FFFFFF` | 淡粉 hover 狀態 |

可用元件態：

- 凸：`background: var(--surface); box-shadow: var(--shadow-extrude);`
- 輕凸：`background: var(--surface); box-shadow: var(--shadow-soft);`
- 凹：`background: var(--bg); box-shadow: var(--shadow-inset);`
- 平：`background: var(--soft); box-shadow: none;`
- 淡粉選中/hover：`background: var(--pink-soft); color: var(--pink-ink); box-shadow: var(--shadow-hover-pink);`

## Component Specs

### 決策卡

結構：主 `section.card.decision`，內含淡粉決策徽章、`h2.rating`、核心理由、提示 note、右側信心儀表、下方三個 KPI。desktop 使用 `1.25fr 180px`，mobile 單欄。

Tokens：`--surface`、`--shadow-extrude`、`--pink-soft`、`--pink-ink`、`--pink-pressed`、`--accent-soft`、`--ink`。

禁忌：不要把整張卡染粉；不要讓 rating 用粉色文字；不要把 note 改成紅/綠語意色。

### 信心儀表

結構：`div.confidence` 使用凹面底，內層 `::before` 為淡粉 conic 進度，`::after` 壓出中間圓，內容放分數與 label。

Tokens：`--bg`、`--pink-soft`、`--pink`、`--pressed`、`--shadow-inset`、`--ink`、`--muted`。

禁忌：不要用飽和紅綠做信心進度；信心度不是漲跌語意。分數須使用 mono，label 不可低於 12px。

### 三時間框架列

結構：三張 `article.card.time`，各有 H3、描述、tags；desktop 三欄，mobile 單欄。

Tokens：`--surface`、`--shadow-extrude`、`--pressed`、`--ink`、`--text`、`--muted`。

禁忌：不要用粉色標示短/中/長線方向；方向仍由文字與 up/down 語意色處理。

### 估值區間條

結構：`div.band` 橫向分成 Bear/Base/Bull，使用 `--down-bg`、`--warn-bg`、`--up-bg`；現價滑標 `band i` 使用粉色指針；下方三欄 legend。

Tokens：`--shadow-inset`、`--down-bg`、`--warn-bg`、`--up-bg`、`--pink-ink`、`--pink-soft`、`--ink`、`--muted`。

禁忌：Bear/Base/Bull 三段不可改成粉色漸層；粉色只標「目前位置」，不表示好壞。

### 風報比區

結構：三個 `.flat` 指標：上檔、下檔、R/R。上檔數字 `.up`，下檔 `.down`，R/R `.num`。

Tokens：`--soft`、`--up`、`--down`、`--ink`、`--muted`。

禁忌：不可用粉色或紫色表示報酬方向；正負報酬只能綠漲紅跌。

### 紅綠燈徽章

結構：每張 light card 有標題、燈號圓點 `.dot.g/.dot.y/.dot.r` 與 evidence chips。

Tokens：`--up`、`--down`、`--warn`、`--pressed`、`--surface`、`--shadow-extrude`。

禁忌：紅綠燈不可用 emoji；不可讓粉色介入燈號；文字需明確寫「綠燈/黃燈/紅燈」。

### 財報品質分數條

結構：每個 `.factor` 為 label、凹面 `.bar`、右側 score。bar fill 目前用 `--up` 表示品質通過度。

Tokens：`--pressed`、`--shadow-inset`、`--up`、`--ink`。

禁忌：bar track 不要用外框加陰影的 ghost-card 模式；分數不可只靠顏色判讀。

### 法人分拆列

結構：三張 `.inst-item`，左側法人名稱，右側張數與補充。買超 `.up`，賣超 `.down`，分歧說明用警示 pill。

Tokens：`--surface`、`--shadow-extrude`、`--up`、`--down`、`--warn-bg`、`--warn`。

禁忌：法人買賣不可用粉色；投信/外資/自營欄寬在 390px 下要單欄避免橫捲。

### 六角色觀點卡

結構：六張 `.card.voice`，H3 使用 `--accent-2`，內文保持 `--text`。desktop 兩欄，mobile 單欄。

Tokens：`--surface`、`--shadow-extrude`、`--accent-2`、`--text`。

禁忌：不要為六角色各自發明顏色；不要使用 emoji 頭像；角色卡不做 nested card。

### 新聞/事件列

結構：`details` 群組，`summary` 最小高 56px，內容列 `.news a/.event` 使用平底 soft。日期 `.date` 使用 `--pink-ink` 作淡粉系統的小型記憶點。

Tokens：`--surface`、`--shadow-extrude`、`--soft`、`--pink-ink`、`--ink`、`--text`。

禁忌：可收合區不可拿掉 focus-visible；新聞列不可整列變粉，避免像警示。

### 戰績牆

結構：放在 `details`，內容為兩欄 `.hit`，呈現命中率、回撤等歷史績效校正資訊。

Tokens：`--soft`、`--ink`、`--text`、`--mono`。

禁忌：不得呈現為保證績效；不得用綠色強化「必勝」感。

### 免責 Footer

結構：頁尾 `.disclaimer`，平面 pressed 底，14px 文字，清楚聲明示意資料與非投資建議。

Tokens：`--pressed`、`#303545`、`--r-md`。

禁忌：免責不得縮到難讀；不得用 `--muted` 造成對比不足；不得放進浮凸主卡削弱層級。

## Pink Accent Placement

本版已核准的粉色落點限 5 類：

1. 決策卡徽章與 rating 底線：`--pink-soft`、`--pink-pressed`。
2. 信心儀表進度與柔底：`--pink`、`--pink-soft`。
3. 區塊小標 icon 圓底：`--pink-soft`、`--pink-ink`。
4. 快速導覽 hover/focus/選中態：`--pink-soft`、`--pink-ink`、`--shadow-hover-pink`。
5. 估值區間現價滑標與新聞日期：`--pink-ink`、`--pink-soft`。

新增粉色落點需先刪減既有落點，維持 3-5 個；寧少勿多。

## Hard Rules

### Neumorphism 三大雷

1. 文字對比不可犧牲：body 與小字對比需 >= 4.5:1；大字需 >= 3:1。不可把淺灰字放在粉底或凹面上。
2. 浮凸只給容器：卡片、chip、icon、凹面 track 可以用 shadow；文字、數字、長段落不可加 neumorphic shadow。
3. 語意色要跳：`--up`、`--down`、`--warn` 必須比柔白底清楚，且不得被粉色取代或稀釋。

### Interaction / Accessibility

- 手機 390px 寬不得橫向捲動。
- 可點擊目標高度 >= 44px。
- `:focus-visible` 必須清楚，使用 `3px solid var(--pink)`，`outline-offset: 3px`。
- hover/active 只做輕微材質變化，轉場 150-200ms。
- 不做頁面載入大動效；若加 motion，必須有 `prefers-reduced-motion`。

### Content / Finance

- 不用 emoji 當 icon；使用 inline SVG 或 icon font。
- 中英數字之間保留半形空格：例如 `FY26 EPS 70`、`07/15 台積電`。
- 漲跌固定：綠漲紅跌。`.up` 綠、`.down` 紅，不得翻轉。
- 報告不可暗示保證獲利；戰績牆與 R/R 需保留風險語境。

## Page Skeletons

### 週報首屏

目的：讓使用者在第一屏判斷本週曝險與大盤溫度，再進入個股清單。

版面：

1. Topbar：產品名、資料時間、資料性質。
2. Hero：本週市場一句話、資料日期、總體狀態 chips。
3. 首屏主卡：大盤溫度/信心儀表、建議曝險區間、三個最重要風險。
4. 個股決策卡縮影：每檔顯示代號、決策、信心、觸發價/防守線。
5. 本週事件與風險：可收合 details，避免首屏過長。

規格：desktop 可兩欄（主卡 + 個股縮影），mobile 單欄；首屏不放長篇新聞，避免稀釋決策。

### 個股報告

目的：先回答「要不要動」，再提供估值、條件、證據與風控。

版面：

1. Topbar + Hero meta：股票名稱、代號、現價、資料時間。
2. 決策卡：rating、核心理由、信心儀表、KPI（部位、操作分級、防守線）。
3. 快速導覽：時間框架、價值區間、進場失效、紅綠燈、角色觀點。
4. 三時間框架列。
5. 合理價值區間與風報比。
6. 進場條件與失效條件。
7. 三維紅綠燈、財報品質、法人分拆。
8. 六角色觀點。
9. 新聞列表、事件日曆、戰績牆。
10. 免責 footer。

規格：決策卡必須在首屏；任何補充資料不得排在決策前。desktop 1080px max width；390px mobile 全程單欄且不橫捲。
