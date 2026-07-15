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
