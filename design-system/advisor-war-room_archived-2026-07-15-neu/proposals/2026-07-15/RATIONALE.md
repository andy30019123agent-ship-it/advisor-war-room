# 投顧戰情室新版報告視覺提案

> 限制說明：`impeccable` 初始化流程要求在專案根目錄建立 `PRODUCT.md`，但本任務明確要求不得動指定目錄外檔案，因此本次只在本目錄產出 mockup 與 rationale。

## Direction 1｜編輯級投資備忘錄

一句定位：把個股報告做成一份可慢讀、可信任、層級清楚的投資備忘錄。

主色與輔色：
- Ink `#151713`
- Porcelain `#F7F7F4`
- Surface `#FFFFFF`
- Deep Teal `#223A34`
- Cinnabar `#8F3D2E`
- Up Green `#147A4C`
- Down Red `#B33D32`

字體配對：`Noto Serif TC` 標題，`Noto Sans TC` 內文，`IBM Plex Mono` 數字。

為什麼適合：Andy 主要用手機讀長報告，這個方向用明確首屏決策、報紙式標題、較長行高和分段留白降低數據疲勞；適合週報與深度報告共用同一套「先結論、後證據」節奏。

現實世界參考：`The Economist` 的資料型長文節奏，以及 `Financial Times` 的投資敘事層級，但避開商務金融常見金黑套版。

## Direction 2｜終端儀表風

一句定位：像個人交易戰情台，讓重要訊號、條件與風控一眼可掃。

主色與輔色：
- Charcoal `#111411`
- Panel `#191D19`
- Panel Raised `#20261F`
- Rule `#394138`
- Signal Gold `#D2B15B`
- Cool Teal `#88B8AD`
- Up Green `#4EC17D`
- Down Red `#FF756B`

字體配對：`IBM Plex Sans TC` 介面與內文，`IBM Plex Mono` 數字與代碼式標籤。

為什麼適合：數據密度最高，適合把「條件、分數、觸發、失效」做成操作面板；深色降低夜間手機閱讀刺眼感，但用高對比文字維持可讀性。

現實世界參考：`Bloomberg Terminal` 的任務密度與 `Linear` 的克制產品語彙；保留儀表感但去掉傳統金融的沉重商務味。

## Direction 3｜柔和人文閱讀

一句定位：把投資判斷做成一份有照護感的手機閱讀報告。

主色與輔色：
- Mist `#EEF3F1`
- Paper `#FBFCFA`
- Soft Panel `#F4F7F4`
- Deep Teal `#245E55`
- Plum `#5A3D62`
- Rose `#A94848`
- Up Green `#16805A`
- Down Red `#B4413A`

字體配對：`Noto Serif TC` 標題，`IBM Plex Sans TC` 內文，`IBM Plex Mono` 數字。

為什麼適合：Andy 要美感與舒服，這個方向降低工具感，用柔和色層、較短區塊與展開式追蹤資訊，讓非工程師也能安心閱讀數據密集內容。

現實世界參考：`Apple Health` 的照護感與 `Monocle` 的溫和編排，但轉成投資報告需要的明確訊號與風控結構。

## 共通設計決策

- 手機優先：390px 寬以單欄與可換行晶片為主，不使用需要橫向捲動的表格。
- 首屏優先：每個方向都先呈現 rating、部位金額、信心度、核心理由與定期定額註記。
- 綠漲紅跌：沿用本專案定案的國際慣例，不做台股紅綠反轉。
- 圖示一致：全部使用 inline SVG，統一 stroke 寬與線端樣式，不用 emoji 作為結構 icon。
- 資料揭露：估值區間顯示 Bear / Base / Bull、現價落點、EPS 與倍數假設；所有數據均標示為示意。

## Neumorphism 定案方向

### neu-a｜白底經典 Neumorphism

色票：
- Background `#F0F0F3`
- Surface `#FBFBFE`
- Soft `#F6F6F9`
- Pressed `#E7E7EC`
- Ink `#141823`
- Text `#262B38`
- Muted `#566071`
- Accent Purple `#6554D9`
- Accent Violet `#7D4FC7`
- Up Green `#087A46`
- Down Red `#B82033`
- Warning `#A06900`

字體配對：`Nunito Sans` 作為圓潤標題，`IBM Plex Sans TC` 作為繁中介面與內文，`IBM Plex Mono` 作為數字與代碼標籤。

陰影 token：
- Extrude `10px 10px 22px #C9C9D0, -10px -10px 22px #FFFFFF`
- Soft control `6px 6px 14px #D0D0D7, -6px -6px 14px #FFFFFF`
- Inset `inset 6px 6px 12px #C9C9D0, inset -6px -6px 12px #FFFFFF`

差異定位：最貼近 Andy 指定的柔白經典 neumorphism，乾淨、明亮、偏產品預設。

### neu-b｜霧藍灰柔色 Neumorphism

色票：
- Background `#E7EDF1`
- Surface `#F5F9FB`
- Soft `#EDF3F6`
- Pressed `#DBE5EB`
- Ink `#12202A`
- Text `#253340`
- Muted `#516575`
- Accent Blue `#315F8F`
- Accent Violet `#6C4BB3`
- Up Green `#087A46`
- Down Red `#B51E32`
- Warning `#986400`

字體配對：`Nunito Sans` 作為圓潤標題，`IBM Plex Sans TC` 作為繁中介面與內文，`IBM Plex Mono` 作為數字與代碼標籤。

陰影 token：
- Extrude `10px 10px 22px #C3CDD4, -10px -10px 22px #FFFFFF`
- Soft control `6px 6px 14px #C8D2D9, -6px -6px 14px #FFFFFF`
- Inset `inset 6px 6px 12px #C1CBD2, inset -6px -6px 12px #FFFFFF`

差異定位：用霧藍灰建立更有識別度的柔色底，閱讀較安定但仍保留清楚訊號。
