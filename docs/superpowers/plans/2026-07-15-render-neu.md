# 報告渲染層改版 Implementation Plan（Neumorphism 柔白＋淡粉；個股報告＋週報全面套新設計＋呈現 P1 全新內容）

> **REQUIRED SUB-SKILL**：執行本計畫用 `superpowers:executing-plans`（逐 Task 依序做、每 Task 完成後 review checkpoint）。同一 session 連續執行改用 `superpowers:subagent-driven-development`。每個 Task 內部一律走 `superpowers:test-driven-development`（先寫失敗測試 → 跑到紅 → 最小實作 → 跑到綠 → commit）。
>
> 前置：P0 決策引擎＋P1 五模組已完工合併（HEAD `2994b30`，106 測試綠）。本計畫**只動渲染層**（把引擎已產出的 JSON 區塊畫成新版面），除 Task 1 一個 additive 白名單補洞外，不動任何引擎計算邏輯與既有欄位語意。
>
> **唯一設計權威**：`design-system/advisor-war-room/MASTER.md`（Andy 2026-07-15 核准）。**1:1 復刻參考**：`design-system/advisor-war-room/proposals/2026-07-15/neu-final.html`（下稱 `neu-final.html`）。凡本計畫寫「照抄 neu-final.html 第 X-Y 行」＝原樣貼入該檔對應行，不得改 token 值、不得自創 hex。

## Goal

把 `advisor-war-room` 的**個股報告**（`warroom/report_stock.py`）與**週報**（`warroom/build_weekly.py`）的 HTML 從舊「Mineral Signal 礦物訊號（acid lime＋銅色＋深墨卡）」版，全面改成 Neumorphism 柔白＋淡粉版，並把 P1 引擎已算好、但舊版面沒呈現的全部新內容畫出來：

- **決策卡首屏**：rating、部位金額（含張數 lots＋零股 odd_shares）、信心儀表、核心持股註記、免責。
- **三時間框架**（`decision.time_frames`）、**估值區間條**（Bear/Base/Bull＋現價滑標＋揭露＋方法說明）、**風報比**、**進場條件與三層失效**、**三維紅綠燈**、**財報品質分**（7 因子條）、**法人分拆**（外資/投信/自營＋分歧）、**六角色觀點**、**新聞**、**事件日曆**（`events.json`）、**戰績牆**（`recommendation_log.json` 統計，樣本不足顯示「累積中」）。
- **週報**：首屏（大盤溫度／建議曝險／個股決策卡縮影）＋既有五層套新設計＋台股類股輪動真實強度區（`tw_sectors.json`）＋事件區。

## Architecture

資料流（★＝本計畫新增/修改）：

```
warroom/decision_engine.py  ★Task1：build_decision() valuation 白名單補 roe/bvps（additive，唯一引擎改動）
warroom/render_common.py    ★Task2【新】：MASTER token 常數 + 共用 CSS/SVG + 共用元件函式（兩報告共用）
warroom/report_stock.py     ★Task3：全面改版，讀 data/<id>.json(decision/chips.breakdown/fundamentals_quality)
                                     + data/<id>.narration.json + events.json + recommendation_log.json
warroom/build_weekly.py     ★Task4：全面改版，首屏 hero + 個股決策卡縮影 + 台股類股輪動(tw_sectors.json) + 事件
tests/test_render_common.py ★Task2
tests/test_report_stock.py  ★Task3
tests/test_build_weekly.py  ★Task4
tests/test_render_e2e.py    ★Task5：端到端，真 data/*.json 重產兩份 HTML，斷言關鍵 id/class/值
```

原則：**渲染是純函式**。把「組 HTML」與「抓網路/落檔/一致性 assert」分離——組 HTML 的函式（`render_stock_html(d, n, ...)`、`render_weekly_html(...)`）只吃 dict、回字串，可離線測試；`build()`/`__main__` 保留既有的網路抓取與 `assert_consistent` 閘門，語意不變。

## Tech Stack

- Python 3.9.6（`./.venv/bin/python`）。標準庫 `json/html/os/sys/datetime/email.utils`。**不新增任何第三方依賴**（不用 jinja、不用 css 前處理器）。
- 測試：stdlib `unittest`，斷言「產出 HTML 字串含指定 id/class 與關鍵值」，**不打真 API**、用現有 `data/*.json`。
- 執行位置：一律 repo 根目錄 `/Users/andyc/Desktop/agent/advisor-war-room`。

## Global Constraints（每個 Task 都要守）

1. **Python 3.9 相容**：`typing.Optional/List/Dict`，不可用 `X | None`、`list[str]`、`match/case`。
2. **零新依賴**：只用 stdlib。
3. **MASTER.md token 是唯一顏色/字級來源**：產出 HTML 的 `:root{}` 值必須逐一等於 MASTER §Design Tokens。**HTML 內不得出現 MASTER 沒有的裸 hex**（例外：neumorphism shadow 內的 `#c9c9d0/#ffffff/#d0d0d7/#d8c8cd` 與免責 `#303545`、決策 note `#28215f`——這些在 MASTER §Shadows／§免責／neu-final.html 已列，屬允許集；除此之外不得新增 hex）。
4. **繁體中文**輸出字串與註解；識別字用英文。
5. **中英數字之間半形空格**：字面文案（如 `FY26 EPS 70`、`07/15 台積電`、`R/R 3.3`）一律留半形空格；數字用 `.num`（mono＋tabular-nums）。
6. **綠漲紅跌固定**：`.up` 綠 `.down` 紅，不得翻轉；漲跌/紅綠燈語意色不得被粉色取代或稀釋。
7. **emoji 不當結構 icon**：紅綠燈、區塊小標一律用 inline SVG（`neu-final.html` 的 `<symbol>` 組）或 `.dot`/`.tl` 圓點；舊版 `LIGHT` 的 emoji 只可保留在「不是結構 icon」處，最好整批移除。
8. **`<details>` 展開**：新聞/事件/戰績用 `<details>`，`summary` 最小高 56px，保留 `:focus-visible`（`3px solid var(--pink)`）。
9. **手機優先 390**：`<meta name="viewport" content="width=device-width, initial-scale=1">` 必附；390px 寬全程單欄、不得橫捲；可點擊目標 >= 44px。
10. **免責必附**：兩報告 footer 都要 `.disclaimer`，寫明「投資決策輔助、非投資建議、非保證獲利」；個股報告另附 `decision.disclaimer`。
11. **Additive／不動引擎**：除 Task 1 白名單，不改任何 `warroom/*.py` 的計算；106 個既有測試每個 Task 收尾都要全綠（`./.venv/bin/python -m unittest discover -s tests -v` 末尾 `OK`）。
12. **不憑記憶**：所有欄位名以 `data/*.json` 實際檔為準（本計畫 §資料契約 已抄實檔）。

---

## 資料契約（2026-07-15 讀實檔確認，寫程式前必讀）

### `data/<id>.json`（引擎）
- `stock_id, name`
- `fundamental/technical/chips`：各 `{light: "green"|"amber"|"red", ev: {...}}`。
- `chips.breakdown`（P1 Task A）：`{as_of, groups:{外資/投信/自營:{net_latest(股,int), net_5d(股), streak(int), dir:"買"|"賣", ratio_20d_vol(float|null)}}, divergence(bool), divergence_note(str)}`。**net 單位＝股；顯示張＝net/1000。**
- `news`：list `{title, url, date(RFC2822 如 "Mon, 06 Jul 2026 07:00:00 GMT"), src}`。
- `summary`：`{score(float), direction(str), confidence(str "中"), conflict(bool)}`。
- `fundamentals_quality`（P1 Task B）：`{total(int), max(14), pct, streak_bonus, roe_value, factors:{revenue/eps/gross_margin/operating_margin/roe/fcf/debt:{score(0-2), applicable(bool), value(str)}}, note}`。
- `decision`（P0/P1）：
  - `rating`（"買進"/"試單"/"續抱"/"觀望"/"減碼"）
  - `fair_value:{bear,base,bull}`
  - `valuation:{path:"per"|"pbr", eps_ttm, eps_source, eps_forward, growth_used, multiples:{bear,base,bull}, current_multiple, current_percentile, disclosure}` **← Task 1 後另有 `roe, bvps`**
  - `risk_reward(float)`
  - `stop:{price, pct, basis, clamped, note}`
  - `entry:{pullback(str), breakout(str)}`
  - `position:{tier(如"空手"), amount(元,int), odd_lot(bool), shares, lots, odd_shares, reason, core_note(可能為空字串)}`
  - `confidence:{total(0-100), completeness, consistency, rr, regime, valuation_penalty}`
  - `time_frames:{short/swing/mid:{label, stance, basis, ref_price}}`
  - `invalidation:{price(str), fundamental(str), chips(str), any_triggered(bool)}` — 每個字串尾含「（未觸發）/（已觸發）」
  - `as_of_price(float)`, `note(可能 null)`, `disclaimer(str)`

### `data/<id>.narration.json`（Claude 團隊觀點）
`{as_of(str), roles:{fundamental, technical, news, risk, devil, chief}, action:{direction, stop, confidence}}`。**六角色＝**基本面(`fundamental`)、技術(`technical`)、消息(`news`)、風控長(`risk`)、魔鬼代言人(`devil`)、投資長(`chief`)。個股決策卡「核心理由」用 `roles["chief"]`。

### `data/events.json`（全市場事件）
`{generated, horizon_days, events:[{date, days_ahead(int), type(如"法說會"/"FOMC"), stock_id(str|null), name, detail, source, confidence("confirmed"/"scheduled")}], degraded:[str]}`。**個股報告只取 `stock_id==sid` 或 `stock_id is None`（總經）；** 週報事件區優先用 `weekly_narration.events`（手寫 d/t/m），另可附 `events.json` 的近端法說。

### `data/recommendation_log.json`（戰績）＋ `warroom/track_record.py`
list of `{date, stock_id, name, price, rating, fair_base, stop, rr, confidence, factors, outcome:{r5,r20,r60,hit,hit_days,max_drawdown}}`。用 `track_record.compute_stats(log)` → `{resolved, hit_rate, avg_r, avg_r20, total_logged}`。**目前所有 outcome 皆 null → resolved=0、hit_rate=None → 顯示「資料累積中」。**

### `data/tw_sectors.json`（台股類股輪動，P1 Task C）
list of `{group, stock_ids:[...], m5, m20, m60(可能 null), vol_expansion, rs_vs_twii, score, rank, tier:"lead"|"mid"|"lag"}`。

### `data/weekly_narration.json`（週報敘事）
`{period, asof, direction, exposure, confidence, risk_temp(int 0-10), chief, market, sector, theme, stocks:{sid:一句話}, events:[{d,t,m}]}`。週報個股卡縮影：`stocks` 的 key（sid）→ 讀 `data/<sid>.json` 的 `decision`。

---

## ⚠️ 兩個已驗證的資料落差（實測，Task 5 必處理，先讀）

1. **個股報告一致性閘門會擋 2330**：`report_stock.build()` 進入即 `assert_consistent(check_stock_consistency(d, n))`。`data/2330.narration.json` 的 `as_of="2026-07-13"` 早於引擎 `chips.ev.最新日="2026-07-14"` → **目前 CLI 直接 `sys.exit(1)`**（實測輸出：`[日期落後] 敘事 as_of (2026,7,13) 早於引擎最新資料日 (2026,7,14)`）。**這是資料新鮮度閘門，不是渲染 bug。** 對策見 Task 3（把 HTML 組裝抽成純函式 `render_stock_html(d,n,...)`，測試與 Task 5 斷言走純函式、繞過閘門）＋ Task 5（CLI 全流程另需把 2330 narration `as_of` 更新到 `2026-07-14` 才會過閘門——此為資料維運步驟，非渲染責任，Task 5 只在報告裡標註，不代改敘事內容）。
2. **只有 2330 有 `.narration.json`**：個股報告需要 narration，故端到端個股報告唯一可測標的＝ **2330**。週報**不需**個股 narration（用 `weekly_narration.stocks` 的一句話），2330/2454 引擎 JSON 皆在，週報可完整重產（惟 `build()` 會 `fetch_market()/fetch_sectors()` 打網路——Task 4 把畫面組裝抽成純函式離線測，`build()` 網路部分不變）。

---

## Task 1 — decision_engine valuation 白名單補 `roe`/`bvps`（additive，附測試）

### Files
- **Modify**：`warroom/decision_engine.py`（`build_decision()` 回傳的 `valuation` 白名單）
- **Test**：`tests/test_decision_engine.py`（新增一個測試方法）

### Interfaces
現況（`warroom/decision_engine.py` 約 308-310 行）：
```python
"valuation": {k: valuation.get(k) for k in
              ("path", "eps_ttm", "eps_source", "eps_forward", "growth_used",
               "multiples", "current_multiple", "current_percentile", "disclosure")},
```
`warroom/valuation.py` 的 PBR 路徑（金融/循環股）與 PER 路徑都已在回傳 dict 帶 `bvps`/`roe`（PER 路徑為 `None`，PBR 路徑為實值，實測 2892 disclosure 有 `每股淨值 20.71 / ROE=+9.4%` 但結構化鍵被白名單濾掉）。本 Task 只把這兩鍵加進白名單 tuple，讓下游報告能結構化讀 PBR 路徑的每股淨值與 ROE。

### Step 1：寫失敗測試
在 `tests/test_decision_engine.py` 加：
```python
def test_valuation_whitelist_passes_roe_and_bvps(self):
    """PBR 路徑的 roe/bvps 需被 build_decision 保留（additive 白名單）。"""
    valuation = {
        "path": "pbr", "eps_ttm": None, "eps_source": None, "eps_forward": None,
        "growth_used": None, "multiples": {"bear": 1.42, "base": 1.48, "bull": 1.53},
        "current_multiple": 1.62, "current_percentile": 0.95,
        "disclosure": "金融/循環股 PBR 路徑…", "bvps": 20.71, "roe": 0.094,
        "fair_value": {"bear": 29.4, "base": 30.6, "bull": 31.7},
    }
    out = build_decision(
        price=33.5, lights=["green", "green", "amber"], per_percentile=0.95,
        market_light="amber", valuation=valuation, data_flags={"fundamental": True},
        chips_breakdown=None, ma20=32.0,
    )
    self.assertIn("bvps", out["valuation"])
    self.assertIn("roe", out["valuation"])
    self.assertEqual(out["valuation"]["bvps"], 20.71)
    self.assertAlmostEqual(out["valuation"]["roe"], 0.094)
    # PER 路徑（roe/bvps 為 None）仍保留鍵、值為 None，不 KeyError
```
> 執行前先讀 `build_decision` 的真實簽名（`grep -n "def build_decision" warroom/decision_engine.py` 及其參數預設），依實際必填參數補齊呼叫；上方參數名以現碼為準微調，**不可臆造**。跑到紅（`KeyError`/`assertIn` 失敗）。

### Step 2-3：最小實作 → 跑綠
把白名單 tuple 尾端加 `"bvps", "roe"`：
```python
"valuation": {k: valuation.get(k) for k in
              ("path", "eps_ttm", "eps_source", "eps_forward", "growth_used",
               "multiples", "current_multiple", "current_percentile", "disclosure",
               "bvps", "roe")},
```
`valuation.get` 對缺鍵回 `None`，PER 路徑安全。

### Step 4：全量回歸
`./.venv/bin/python -m unittest discover -s tests -v` → 末尾 `OK`。並重跑 `warroom/analyze_tw.py` 對 2892（PBR 股）確認 `data/2892.json` 的 `decision.valuation` 出現 `roe/bvps` 結構化值（**若不便跑真 API，改用既有測試證明即可，不強制重抓**）。

### Step 5：commit
`git commit -m "Task1(render): decision valuation 白名單補 roe/bvps（additive）"`

---

## Task 2 — `warroom/render_common.py`（設計 token 常數＋共用元件函式）

### Files
- **Create**：`warroom/render_common.py`
- **Test**：`tests/test_render_common.py`

### Interfaces（本檔對外提供，兩報告共用，避免重複 CSS）
```python
esc(s) -> str
num(x) -> str                         # <span class="num">…</span>
CSS -> str                            # 完整 <style>…</style>（含 @import + :root token + 元件 + 響應式）
SVG_DEFS -> str                       # inline <symbol> 組（i-chart/i-shield/i-check/i-calendar/i-chevron）
head(title, viewport=True) -> str     # <meta viewport>+<title>+CSS+SVG_DEFS
icon(symbol_id, cls="icon") -> str    # <svg class=…><use href="#id"/></svg>
section_head(symbol_id, title) -> str # .section-head（.mark 粉底 icon + h2）
traffic(light) -> (dot_cls, zh)       # green→("g","綠燈") amber→("y","黃燈") red→("r","紅燈")
confidence_gauge(total) -> str        # 信心儀表（凹面+粉色 conic，讀 total/100）
disclaimer(*paragraphs) -> str        # footer .disclaimer
fmt_pct(x, signed=True) -> str        # 0.679→"+67.9%"，None→"—"
zhang(net_shares) -> str              # 股→張字串，如 -12416209→"-12,416 張"
rfc_to_mmdd(date_str) -> str          # "Mon, 06 Jul 2026…"→"07/06"；解析失敗回 ""
```

### 常數內容
**`CSS`**（`render_common.py` 內以 `r"""..."""` 常數）＝以下拼成，**一律正常單括號（本檔不經過 `str.format`，故不需雙寫 `{{}}`）**：

1. 開頭：
```css
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+TC:wght@400;500;600;700;800&family=Nunito+Sans:wght@700;800;900&family=IBM+Plex+Mono:wght@500;600;700&display=swap');
```
2. `:root{...}`：**照抄 `neu-final.html` 第 10-16 行**（token 值逐一等於 MASTER §Colors/§Typography/§Shadows；含 `--pink-line/--pink-ink` 等，全帶）。
3. 元件與響應式：**照抄 `neu-final.html` 第 17-32 行**（`*`/`body`/`.icon`/`.num`/`.up`/`.down`/`.page`/`.topbar`/`.hero`/`h1`/`.card`/`.decision`/`.rating`/`.confidence`/`.kpi`/`.jump`/`.section-head`/`.mark`/`h2`/`.grid`/`.band`/`.rr`/`.conditions`/`.invalid`/`.lights`/`.dot`/`.quality`/`.factor`/`.bar`/`.inst`/`.voice`/`details`/`summary`/`.news`/`.event`/`.hit`/`.date`/`.weekly`/`.disclaimer` 及 `@media(min-width:760px)`/`@media(max-width:420px)` 全段）。
4. **唯一對 mockup CSS 的必要參數化**：把 `.confidence::before` 的 `conic-gradient(from 225deg,var(--pink) 0 72%,var(--pressed) 72% 100%)` 改成用自訂屬性 `conic-gradient(from 225deg,var(--pink) 0 var(--p,72%),var(--pressed) var(--p,72%) 100%)`，讓信心分數可由 `.confidence` 的 inline `style="--p:{total}%"` 驅動（其餘 CSS 不改）。
5. `prefers-reduced-motion`：`neu-final.html` 未含，補一段（MASTER §Interaction 要求）：
```css
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;transition-duration:.01ms!important}}
</style>
```

**`SVG_DEFS`**：照抄 `neu-final.html` 第 36-42 行（`<svg width="0" height="0" aria-hidden="true">…5 個 <symbol>…</svg>`）。

### 元件函式（完整 Python，無佔位）
```python
"""兩份投顧報告共用的渲染基元：MASTER token（唯一設計權威）+ 共用 CSS + 元件函式。
純函式、無網路、無副作用；HTML 以 f-string 組出，不經 str.format（故 CSS 用單括號）。"""
import html
from email.utils import parsedate_to_datetime

# CSS / SVG_DEFS 常數見上（略）

def esc(s):
    return html.escape(str(s))

def num(x):
    return '<span class="num">' + esc(x) + '</span>'

def icon(symbol_id, cls="icon"):
    return '<svg class="' + cls + '"><use href="#' + esc(symbol_id) + '"/></svg>'

def head(title, viewport=True):
    vp = '<meta name="viewport" content="width=device-width, initial-scale=1">' if viewport else ""
    return vp + "<title>" + esc(title) + "</title>\n" + CSS + "\n" + SVG_DEFS

def section_head(symbol_id, title):
    return ('<div class="section-head"><span class="mark">' + icon(symbol_id)
            + '</span><h2>' + esc(title) + '</h2></div>')

_LIGHT = {"green": ("g", "綠燈"), "amber": ("y", "黃燈"), "red": ("r", "紅燈")}

def traffic(light):
    return _LIGHT.get(light, ("y", "黃燈"))

def confidence_gauge(total):
    t = int(round(total or 0))
    return ('<div class="confidence" style="--p:' + str(t) + '%"><div><b>' + str(t)
            + '</b><span>信心度 / 100</span></div></div>')

def disclaimer(*paragraphs):
    body = "".join("<p>" + esc(p) + "</p>" if not p.startswith("<") else p for p in paragraphs)
    return '<footer><div class="disclaimer">' + body + "</div></footer>"

def fmt_pct(x, signed=True):
    if x is None:
        return "—"
    return ("{:+.1f}%" if signed else "{:.1f}%").format(x * 100)

def zhang(net_shares):
    if net_shares is None:
        return "—"
    return "{:+,} 張".format(int(round(net_shares / 1000)))

def rfc_to_mmdd(date_str):
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.strftime("%m/%d")
    except Exception:
        return ""
```
> `disclaimer` 的段落若已是 `<p>`/HTML 片段（如免責含 `<b>`）直接放行；純文字才包 `<p>`。實作時可視需要簡化為固定兩段。

### Step 1：寫失敗測試 `tests/test_render_common.py`
```python
"""Task 2：共用渲染基元測試（純字串，不打網路）。"""
import unittest
from warroom import render_common as rc


class TestRenderCommon(unittest.TestCase):
    def test_css_has_master_tokens_not_naked_hex(self):
        css = rc.CSS
        for tok in ("--bg:#f0f0f3", "--surface:#fbfbfe", "--pink:#e8b4c0",
                    "--up:#087a46", "--down:#b82033", "--pink-ink:#6d3040"):
            self.assertIn(tok, css.replace(" ", ""))
        # 不得出現舊礦物版 acid lime / 銅色
        for banned in ("#C7F04A", "#c7f04a", "#A85C3A", "acid"):
            self.assertNotIn(banned, css)

    def test_head_has_viewport_and_fonts(self):
        h = rc.head("測試 標題")
        self.assertIn('name="viewport"', h)
        self.assertIn("width=device-width", h)
        self.assertIn("fonts.googleapis.com", h)
        self.assertIn("<title>測試 標題</title>", h)

    def test_confidence_gauge_reads_total(self):
        g = rc.confidence_gauge(58)
        self.assertIn("--p:58%", g)
        self.assertIn(">58<", g)

    def test_traffic_no_emoji(self):
        self.assertEqual(rc.traffic("red"), ("r", "紅燈"))
        self.assertEqual(rc.traffic("green"), ("g", "綠燈"))

    def test_zhang_and_pct(self):
        self.assertEqual(rc.zhang(-12416209), "-12,416 張")
        self.assertEqual(rc.zhang(1841069), "+1,841 張")
        self.assertEqual(rc.fmt_pct(0.679), "+67.9%")
        self.assertEqual(rc.fmt_pct(None), "—")

    def test_rfc_to_mmdd(self):
        self.assertEqual(rc.rfc_to_mmdd("Mon, 06 Jul 2026 07:00:00 GMT"), "07/06")
        self.assertEqual(rc.rfc_to_mmdd("garbage"), "")

    def test_svg_defs_no_emoji_icons(self):
        self.assertIn('id="i-chart"', rc.SVG_DEFS)
        self.assertIn('id="i-chevron"', rc.SVG_DEFS)
```
跑到紅（module 不存在）。

### Step 2-3：實作 `render_common.py`（CSS/SVG 照抄 + 上方函式）→ 跑綠。
### Step 4：全量回歸 `OK`。
### Step 5：`git commit -m "Task2(render): render_common 共用 token/CSS/元件（neu 柔白粉）"`

---

## Task 3 — `report_stock.py` 全面改版（個股報告，1:1 復刻 neu-final.html）

### Files
- **Modify**：`warroom/report_stock.py`（整個 TEMPLATE 與組裝改寫；保留 `build()` 的 `assert_consistent` 閘門與 `__main__`）
- **Test**：`tests/test_report_stock.py`

### Interfaces
把「組 HTML」抽成純函式，`build()` 只負責讀檔＋一致性 assert＋呼叫純函式：
```python
def render_stock_html(d, n, stats=None, events=None) -> str
    # d=data/<id>.json, n=narration, stats=track_record.compute_stats(log)（可 None），
    # events=events.json 過濾後 list（可 None）。純字串，無網路、無 assert。

def build(stock_id) -> str
    # 讀 data/<id>.json + narration + recommendation_log + events.json；
    # assert_consistent(check_stock_consistency(d,n), f"個股報告 {stock_id}")；
    # stats=compute_stats(_load_log())；events=[e for e in ev if e["stock_id"] in (sid, None)]；
    # return render_stock_html(d, n, stats, events)
```

### 版面（依 MASTER §個股報告 與 neu-final.html 第 43-157 行逐段對應；每段的 data 來源已標）

`render_stock_html` 依序 `"".join` 下列片段，最後用 `render_common.head(title)` 包在最前：

1. **Topbar + Hero**（照 neu-final 第 44-57 行結構）
   - `.topbar`：`<span class="brand">i-chart Advisor War Room</span>` + 右側 `真實資料 · FinMind × TWSE × Google News · {n["as_of"]}`。
   - `<h1>{name} {sid}<br>戰術決策報告</h1>`（`--display`）。
   - `.meta` chips：`現價 {as_of_price}`、`資料時間 {as_of}`、`綠漲紅跌`。（無日漲跌資料則不放該 chip，不得編造。）

2. **決策卡首屏**（`section.card.decision`，照 neu-final 第 59-74 行）
   - `.eyebrow`（粉底）`決策卡 · 首屏優先`。
   - `<h2 class="rating">{decision.rating}</h2>`（粉色底線由 CSS 的 `.rating` linear-gradient 提供，**文字本身不染粉**）。
   - `.reason`：`核心理由：{esc(n["roles"]["chief"])}`。
   - `.note`（僅當 `position.core_note` 非空）：`icon(i-shield)` + `core_note`。
   - `confidence_gauge(decision.confidence.total)`。
   - `.kpis`（三格）：
     - 部位金額建議：`<strong>` = `{tier}｜{amount:,} 元`（amount==0 → `空手｜0 元`）；`<small>` = `{lots} 張` + （`odd_shares>0` 時 ` + {odd_shares} 股`）。
     - 操作分級：`<strong>{rating}</strong>`；`<small>買進、試單、續抱、觀望、減碼</small>`。
     - 防守線：`<strong class="num">{stop.price}</strong>`；`<small>{stop.basis}／{stop.note}</small>`（如 `ATR／參考防守位，接回自行判斷`）。

3. **快速導覽 `nav.jump`**：錨點 `#frames #value #entry #signals #quality #inst #team`（照 neu-final 第 76 行，加 quality/inst 錨）。

4. **三時間框架 `#frames`**（`.grid.three`，照 neu-final 第 78-85 行）
   - 對 `decision.time_frames` 的 `short/swing/mid` 各出一張 `article.card.time`：`<h3>{label}</h3>`，`<p>{basis}</p>`，`.tags` 放 `stance`（用 up/down/muted 依 stance 含「多」→up、「空」→down、否則 muted）＋ `ref_price`（如 `參考 MA20 2426.2` 拆成 tag）。

5. **合理價值區間 `#value`**（照 neu-final 第 87-94 行）
   - `.band`：三段固定視覺（`down-bg`/`warn-bg`/`up-bg` 等分三段代表 Bear/Base/Bull 區）＋現價滑標 `<i style="left:{p}%">`，`p = clamp((as_of_price - bear)/(bull - bear)*100, 2, 98)`。
   - `.legend` 三欄：`Bear {bear}` / `Base {base}` / `Bull {bull}`（`.num`）。
   - `.source`（估值揭露）：直接放 `decision.valuation.disclosure`；**PBR 路徑（path=="pbr"）另補一行**用結構化 `bvps`/`roe`（Task 1 提供）：`每股淨值 {bvps}、ROE {fmt_pct(roe,False)}`。
   - **方法說明（MASTER/進度要求必附）**：追加一句 `方法：純歷史 PER 分位回歸推估合理倍數（Bear/Base/Bull＝25/50/75 分位）；高本益比成長股的 Bull 情境偏樂觀，僅供區間參考、非目標價。`（PBR 股改寫成「歷史 PBR 分位」）。

6. **風險報酬比**（`.rr`，照 neu-final 第 96-103 行）
   - 上檔至 Bull：`.up`，值 `fmt_pct((bull - as_of_price)/as_of_price)`。
   - 下檔至停損：`.down`，值 `fmt_pct((stop.price - as_of_price)/as_of_price)`（即 `stop.pct` 亦可，取一致）。
   - R/R：`.num`，值 `decision.risk_reward`（保留原值，可為負，如 -1.08；**不得改寫成假樂觀**）；下方小字 `R/R<1.5 不建議追價`（風險語境，MASTER §戰績牆/風控）。

7. **進場條件與失效 `#entry`**（`.grid.two.conditions` + `.invalid`，照 neu-final 第 105-112 行）
   - 兩張 card：回測型＝`decision.entry.pullback`；突破型＝`decision.entry.breakout`（各為一段字串，放 `<p>` 或拆句成 `<li>`；字串已含數字，維持半形空格）。
   - `.invalid` 三格：`decision.invalidation.price/fundamental/chips`（字串已含「（未觸發）/（已觸發）」）；`any_triggered` 為真時該區 `.section-head` 旁加一個 `.pill.down 已觸發失效` 提示。

8. **三維紅綠燈 `#signals`**（`.lights`，照 neu-final 第 114-121 行）
   - 三張 `article.card.light`：技術/基本面/籌碼，各讀 `d["technical"/"fundamental"/"chips"]["light"]` → `traffic()` 給 `.dot` 與「X燈」文字；`.evidence` chips 逐一放該區塊 `ev` 的 key/value（如 技術：`收盤 2420`、`MA60 2305.5`、`RSI 53`；籌碼：`近5日法人淨額 -24,085`、`連續方向 賣 4 天`）。**不得用 emoji。**

9. **財報品質分數 `#quality`**（`.card.quality`，照 neu-final 第 123-129 行）
   - 對 `fundamentals_quality.factors` 的 7 個 key 依固定順序 `revenue/eps/gross_margin/operating_margin/roe/fcf/debt`，label 對映 `營收/EPS/毛利率/營益率/ROE/現金流/負債`；每列 `.factor`：label、`.bar`（`<i style="width:{score/2*100}%">`；`applicable=False` → width:0 且 score 顯示「不適用」）、`.score` = `score`。
   - `.source`：`總分 {total} / {max}`（`.num`）＋ `fundamentals_quality.note`。

10. **法人分拆 `#inst`**（`.inst` 三卡 + `.split-note`，照 neu-final 第 131-139 行）
    - `chips.breakdown.groups` 外資/投信/自營各一張 `.card.inst-item`：`<b>{名稱}</b>`；右側 `zhang(net_latest)` 套 `.up`（dir=="買"）/`.down`（dir=="賣"）；`<small>連{dir} {streak} 日 · 佔均量 {fmt_pct(ratio_20d_vol,False)}</small>`（ratio None → 略「佔均量」）。
    - `divergence` 為真 → `.split-note`（warn pill）放 `divergence_note`。

11. **六角色觀點 `#team`**（`.grid.two.team` 六卡，照 neu-final 第 141-151 行）
    - 依序 基本面分析師(`roles.fundamental`)、技術分析師(`roles.technical`)、消息分析師(`roles.news`)、風控長(`roles.risk`)、魔鬼代言人(`roles.devil`)、投資長(`roles.chief`)；`h3` 用 `--accent-2`（CSS `.voice h3` 已定），`<p>` 放內文。

12. **新聞 / 事件日曆 / 戰績牆**（`section.grid` 內三個 `<details>`，照 neu-final 第 153-157 行）
    - **新聞**（`<details open>`）：`d["news"][:6]` 每則 `<a href={url} target=_blank rel=noopener><span class="date">{rfc_to_mmdd(date)}</span><b>{title}</b><span class="muted">{src}</span></a>`；空 → `<p class="muted">（本次未取得新聞）</p>`。
    - **事件日曆**（`<details open>`）：`events`（已過濾 `stock_id in (sid, None)`）每筆 `.event`：`<span class="date">{date}（+{days_ahead} 天）</span><b>{name} · {detail}</b><span>{type}／{confidence}｜來源 {source}</span>`；空 → `（未來 {horizon_days} 天無登錄事件）`。
    - **戰績牆**（`<details>`，預設收合）：讀 `stats`；`resolved>=5 且 hit_rate 非 None` → 兩格 `.hit`：`近 {resolved} 次已結案命中率 {fmt_pct(hit_rate,False)}`、`平均 R {avg_r}`；否則單格 `資料累積中（已登錄 {total_logged} 筆、已結案 {resolved} 筆；達 5 筆結案後顯示命中率）`。**不得用綠色強化必勝、不得暗示保證。**

13. **免責 footer**：`render_common.disclaimer(...)`，第一段 = 舊版方法說明（紅綠燈由數據＋固定規則計算…含 `<b>本報告為投資決策輔助，非投資建議、非保證獲利…</b>`），第二段 = `decision.disclaimer`。

> 移除舊 `LIGHT` emoji dict、`dim_card`、舊 `TEMPLATE`。所有片段用 f-string，**不使用 `str.format`**（避免 CSS/內容大括號 KeyError）。

### Step 1：寫失敗測試 `tests/test_report_stock.py`
```python
"""Task 3：個股報告渲染（真 data/2330.json，純函式繞過一致性閘門）。"""
import json
import unittest
from warroom.report_stock import render_stock_html
from warroom.track_record import compute_stats


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


class TestReportStock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = load("data/2330.json")
        cls.n = load("data/2330.narration.json")
        cls.stats = compute_stats(load("data/recommendation_log.json"))
        ev = load("data/events.json")["events"]
        cls.events = [e for e in ev if e["stock_id"] in ("2330", None)]
        cls.htm = render_stock_html(cls.d, cls.n, cls.stats, cls.events)

    def test_no_str_format_crash_and_viewport(self):
        self.assertIn('name="viewport"', self.htm)
        self.assertIn("width=device-width", self.htm)

    def test_decision_first_screen(self):
        self.assertIn('class="rating"', self.htm)
        self.assertIn("減碼", self.htm)                    # decision.rating
        self.assertIn("--p:58%", self.htm)                 # confidence.total
        self.assertIn("空手", self.htm)                    # position.tier

    def test_sections_present(self):
        for anchor in ('id="frames"', 'id="value"', 'id="entry"',
                       'id="signals"', 'id="quality"', 'id="inst"', 'id="team"'):
            self.assertIn(anchor, self.htm)

    def test_value_band_and_method_note(self):
        self.assertIn('class="band"', self.htm)
        self.assertIn("2480.4", self.htm)                  # fair_value.base（legend）
        self.assertIn("方法", self.htm)                    # 估值方法說明必附
        self.assertIn("PER", self.htm.upper())

    def test_quality_seven_factors(self):
        for zh in ("營收", "EPS", "毛利率", "營益率", "ROE", "現金流", "負債"):
            self.assertIn(zh, self.htm)
        self.assertIn("14 / 14".replace(" ", ""), self.htm.replace(" ", ""))  # total/max

    def test_institution_split(self):
        self.assertIn("外資", self.htm)
        self.assertIn("-12,416 張", self.htm)              # zhang(net_latest)
        self.assertIn("外資賣", self.htm)                  # divergence_note

    def test_six_roles(self):
        for role in ("基本面分析師", "技術分析師", "消息分析師",
                     "風控長", "魔鬼代言人", "投資長"):
            self.assertIn(role, self.htm)

    def test_track_record_accumulating(self):
        self.assertIn("累積中", self.htm)                  # 目前 outcome 全 null

    def test_disclaimer_and_no_emoji_lights(self):
        self.assertIn("非投資建議", self.htm)
        for emo in ("🟢", "🟡", "🔴"):
            self.assertNotIn(emo, self.htm)                # 紅綠燈不得用 emoji
        self.assertIn("紅燈", self.htm)                    # 文字寫明燈號
```
跑到紅。

### Step 2-3：改寫 `report_stock.py` → 跑綠（`render_stock_html` 對 2330 全數斷言通過）。
### Step 4：全量回歸 `OK`（106+新測全綠）。
### Step 5：`git commit -m "Task3(render): 個股報告改 neu 柔白粉、呈現 P1 全模組"`

---

## Task 4 — `build_weekly.py` 全面改版（週報）

### Files
- **Modify**：`warroom/build_weekly.py`（TEMPLATE 與組裝改寫；`build()` 的 `fetch_market/fetch_sectors` 與 `assert_consistent` 閘門與落檔行為不變）
- **Test**：`tests/test_build_weekly.py`

### Interfaces
把畫面組裝抽成純函式，離線可測：
```python
def render_weekly_html(ctx) -> str
    # ctx = {"n": weekly_narration, "market": m, "us_sectors": sec, "tw_sectors": tw_sec,
    #        "stocks": {sid: data/<sid>.json}, "events_json": events.json(可 None)}
    # 純字串。build() 抓完網路資料後組 ctx 再呼叫它。

def stock_mini_card(sid, data, one_liner) -> str   # 首屏個股決策卡縮影
def tw_sector_rows(tw_sec) -> str                  # 台股類股輪動真實強度
```

### 版面（MASTER §週報首屏 + neu-final.html 第 159-162 行「週報首屏概念」放大成完整週報）

`render_weekly_html` 依序：`head("戰情週報 {period}")` +

1. **Topbar + Hero**：`.topbar` 品牌 + `真實資料 · … · 資料日 {asof}`；`<h1>戰情週報 {period}</h1>`；`.meta`。

2. **首屏主卡 `section.card`（決策首屏）**（融合 neu-final 決策卡 + 第 159-161 行 weekly-row）
   - `.eyebrow`（粉底）`本週研判 · 首屏優先`。
   - `<h2 class="rating">{n["direction"]}</h2>`。
   - `.reason` = `n["chief"]`。
   - `confidence_gauge`：以 `risk_temp` 轉信心不直觀，**改放「大盤溫度」儀表**——用同一 `.confidence` 元件，`--p:{risk_temp*10}%`，中央顯示 `{risk_temp}/10` label「風險溫度」（label 改字即可，不改結構）。
   - `.kpis` 三格：建議股票曝險 `{n["exposure"]}`；大盤環境 `.dot`＋`{market light 中文}`；本週信心 `{n["confidence"]}`。

3. **個股決策卡縮影**（`section`，`.grid`）：對 `n["stocks"]` 每個 sid，若 `data/<sid>.json` 存在 → `stock_mini_card`：顯示 `代號 名稱`、`decision.rating`（用 verdict pill，rating→顏色：買進/試單/續抱→up、觀望→muted、減碼→down）、`信心 {decision.confidence.total}`、`防守 {decision.stop.price}`、`觸發 {decision.entry.breakout 內的價}`（直接放 breakout 字串亦可）、末行放 `n["stocks"][sid]` 一句話。**縮影只讀引擎，不需個股 narration。**

4. **五層 `<details>`（既有結構套新設計）**：沿用現有 01-05 五層（大盤／類股／個股／主題／事件），但外框改用 `render_common` 的 `details`（neu 凸卡）＋ `.section-head`/`.mark` 粉底 icon 風格；01 大盤格線 `index_grid`、02 類股沿用 `sector_rows`（美股）＋ **新增台股輪動**（見 5）、03 個股沿用 `stock_card`（可展開細節）、04 主題 `theme_rows`、05 事件。**保留既有函式，只換 class 與外層樣式對齊 MASTER**（up/down/warn/dot 沿用；移除 `--acid/--ox` 礦物色）。

5. **台股類股輪動真實強度區**（放進 02 類股層，美股族群下方）：`tw_sector_rows(tw_sec)` 讀 `data/tw_sectors.json`——每列 `.srow`/或 `.factor` 條：`{group}`、`近5日 {m5}`、`近20日 {m20}`、`量能 {vol_expansion}x`、`RS {rs_vs_twii}`、`tier`→tag（lead→領先/att、mid→中性/hold、lag→落後/avoid）；強度用 `score` 排序（已含 rank）。`tw_sec` 為空 → 顯示「（台股類股輪動本次無資料）」。

6. **事件區（05）**：優先 `n["events"]`（d/t/m 手寫）逐筆 `.event`；若傳入 `events_json`，附一小塊「未來 7 天法說」＝ `events_json["events"]` 中 `days_ahead<=7 且 type=="法說會"` 前若干筆。

7. **免責 footer**：`render_common.disclaimer(...)`（沿用舊週報免責文字 + `<b>非投資建議…</b>`）。

> `render_weekly_html` 全用 f-string，不用 `str.format`。`build()` 保留：`fetch_market()/fetch_sectors()/fetch_tw_sectors()`、`assert_consistent(check_weekly_consistency(stocks,n))`、把 `tw_sec` 落 `data/tw_sectors.json` 的既有行為。

### Step 1：寫失敗測試 `tests/test_build_weekly.py`（離線，組假 ctx + 真 tw_sectors/個股 JSON）
```python
"""Task 4：週報渲染（離線純函式；market/us_sectors 用小假 dict，tw_sectors/個股用真檔）。"""
import json
import unittest
from warroom.build_weekly import render_weekly_html


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


class TestBuildWeekly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        n = load("data/weekly_narration.json")
        tw = load("data/tw_sectors.json")
        stocks = {sid: load("data/%s.json" % sid) for sid in n["stocks"]
                  if __import__("os").path.exists("data/%s.json" % sid)}
        market = {"light": "red", "items": [
            {"name": "加權", "value": "44,738", "wk": -3.9, "dot": "r"},
            {"name": "櫃買", "value": "407", "wk": -7.4, "dot": "r"}],
            "foreign": {"net_yi": -519, "date": "2026-07-14"}}
        us_sec = [{"tier": "lead", "group": "能源", "etf": "XLE", "m5": 6.8,
                   "m20": 3.1, "us_names": "XOM", "tw": "—"}]
        cls.ctx = {"n": n, "market": market, "us_sectors": us_sec,
                   "tw_sectors": tw, "stocks": stocks, "events_json": load("data/events.json")}
        cls.htm = render_weekly_html(cls.ctx)

    def test_viewport_and_title(self):
        self.assertIn('name="viewport"', self.htm)
        self.assertIn("戰情週報", self.htm)

    def test_first_screen(self):
        self.assertIn('class="rating"', self.htm)
        self.assertIn(load("data/weekly_narration.json")["exposure"], self.htm)
        self.assertIn("--p:80%", self.htm)                 # risk_temp 8 → 80%

    def test_stock_mini_cards(self):
        self.assertIn("2330", self.htm)
        self.assertIn("2454", self.htm)
        self.assertIn("減碼", self.htm)                    # 2330/2454 decision.rating

    def test_tw_sector_rotation(self):
        for g in ("軍工航太", "封裝測試", "散熱"):
            self.assertIn(g, self.htm)
        self.assertIn("領先", self.htm)                    # tier lead
        self.assertIn("落後", self.htm)                    # tier lag

    def test_no_mineral_palette(self):
        for banned in ("#C7F04A", "#A85C3A", "--acid", "--ox"):
            self.assertNotIn(banned, self.htm)

    def test_disclaimer(self):
        self.assertIn("非投資建議", self.htm)
```
> `market`/`us_sectors` 的假 dict 欄位需對齊 `fetch_market`/`fetch_sectors` 真實回傳鍵——實作前先 `grep` 兩函式的 return 結構校準欄位名，避免 KeyError（本測試欄位以現碼 `index_grid`/`sector_rows`/`market_strip` 用到的鍵為準）。跑到紅。

### Step 2-3：改寫 `build_weekly.py` → 跑綠。
### Step 4：全量回歸 `OK`。
### Step 5：`git commit -m "Task4(render): 週報改 neu、首屏決策+台股類股輪動真實強度"`

---

## Task 5 — 端到端驗證（真資料重產兩份報告 + 結構斷言）

### Files
- **Test**：`tests/test_render_e2e.py`
- **Produce**：`reports/2330.html`、`reports/weekly.html`（重產物，供主對話用 chrome-devtools 由 file:// 截圖驗收；本 Task 只負責產檔與基本斷言）

### 做法
1. **個股（2330）**：因一致性閘門會擋（見 §落差 1），本 Task 的自動斷言走 `render_stock_html`（純函式）產檔：
   ```python
   d = load("data/2330.json"); n = load("data/2330.narration.json")
   stats = compute_stats(load("data/recommendation_log.json"))
   ev = [e for e in load("data/events.json")["events"] if e["stock_id"] in ("2330", None)]
   html_out = render_stock_html(d, n, stats, ev)
   open("reports/2330.html", "w", encoding="utf-8").write(html_out)
   ```
   斷言：含 `id="frames"/id="value"/id="signals"/id="quality"/id="inst"/id="team"`、`class="rating"`、`name="viewport"`、`減碼`、`--p:58%`、無 `🟢🟡🔴`、無 `.format` 例外（函式正常回字串即證）。
2. **週報**：`build()` 需網路。若環境可連 FinMind/yfinance → 直接 `open("reports/weekly.html","w").write(build())`；**若無網路** → 用 Task 4 測試裡的 ctx 組法呼叫 `render_weekly_html(ctx)` 產 `reports/weekly.html`（真 tw_sectors/個股 JSON + 小假 market），斷言含 `戰情週報`、`軍工航太`、`name="viewport"`、無 `--acid`。二擇一皆可，測試用 try/except 網路降級。
3. **390 寬版面**：斷言兩份 HTML 皆含 `<meta name="viewport" content="width=device-width, initial-scale=1">`；CSS 含 `@media (max-width:420px)`（單欄）與 `.inst-item` 單欄規則（來自 render_common）。
4. **一致性閘門紀錄**：測試最後印一行提示（非失敗）：`如需 CLI 全流程（含 assert_consistent）產個股報告，需先把 data/2330.narration.json 的 as_of 更新到 >= 2026-07-14；本渲染計畫不代改敘事內容。`

### 斷言範例 `tests/test_render_e2e.py`
```python
"""Task 5：端到端重產兩份報告 + 關鍵區塊/viewport 斷言（不打真 API 亦可跑）。"""
import json
import os
import unittest
from warroom.report_stock import render_stock_html
from warroom.build_weekly import render_weekly_html
from warroom.track_record import compute_stats


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


class TestRenderE2E(unittest.TestCase):
    def test_stock_report_produced(self):
        d = load("data/2330.json"); n = load("data/2330.narration.json")
        stats = compute_stats(load("data/recommendation_log.json"))
        ev = [e for e in load("data/events.json")["events"]
              if e["stock_id"] in ("2330", None)]
        htm = render_stock_html(d, n, stats, ev)
        os.makedirs("reports", exist_ok=True)
        with open("reports/2330.html", "w", encoding="utf-8") as f:
            f.write(htm)
        for k in ('name="viewport"', 'width=device-width', 'class="rating"',
                  'id="frames"', 'id="value"', 'id="signals"', 'id="quality"',
                  'id="inst"', 'id="team"', "@media (max-width:420px)"):
            self.assertIn(k, htm)
        for emo in ("🟢", "🟡", "🔴"):
            self.assertNotIn(emo, htm)

    def test_weekly_report_produced(self):
        n = load("data/weekly_narration.json")
        tw = load("data/tw_sectors.json")
        stocks = {sid: load("data/%s.json" % sid) for sid in n["stocks"]
                  if os.path.exists("data/%s.json" % sid)}
        ctx = {"n": n, "market": {"light": "red", "items": [
                    {"name": "加權", "value": "44,738", "wk": -3.9, "dot": "r"}],
                    "foreign": {"net_yi": -519, "date": "2026-07-14"}},
               "us_sectors": [], "tw_sectors": tw, "stocks": stocks,
               "events_json": load("data/events.json")}
        htm = render_weekly_html(ctx)
        with open("reports/weekly.html", "w", encoding="utf-8") as f:
            f.write(htm)
        for k in ('name="viewport"', "戰情週報", "軍工航太", "@media (max-width:420px)"):
            self.assertIn(k, htm)
        self.assertNotIn("--acid", htm)
```

### Step 4：`./.venv/bin/python -m unittest discover -s tests -v` → `OK`；確認 `reports/2330.html`、`reports/weekly.html` 產出。**（截圖驗收由主對話用 chrome-devtools 於 390 寬跑，本計畫不含。）**
### Step 5：`git commit -m "Task5(render): 端到端重產兩報告+結構斷言（reports/2330,weekly.html）"`

---

## 完成後的驗收清單（主對話收尾用）
- [ ] 106 個既有測試 + 4 個新測試檔全綠。
- [ ] `reports/2330.html`、`reports/weekly.html` 已重產；主對話 chrome-devtools 390 寬截圖：決策卡首屏、估值區間條、財報品質條、法人分拆、事件日曆、戰績牆（累積中）、週報首屏＋台股輪動皆正確呈現。
- [ ] 無舊礦物版殘留（無 `--acid/--ox/#C7F04A/#A85C3A`）；無 emoji 當紅綠燈；粉色落點 <=5 類（MASTER §Pink Accent Placement）。
- [ ] 資料維運待辦（非本計畫）：`data/2330.narration.json` `as_of` 需更新到 >= 引擎最新資料日，CLI 全流程個股報告才會過一致性閘門。
