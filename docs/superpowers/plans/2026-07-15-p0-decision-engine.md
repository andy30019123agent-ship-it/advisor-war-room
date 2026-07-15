# P0 決策引擎 Implementation Plan

> **REQUIRED SUB-SKILL**：執行本計畫請用 `superpowers:executing-plans`（逐 Task 依序做、每 Task 完成後 review checkpoint）。若在同一 session 內連續執行，改用 `superpowers:subagent-driven-development`。每個 Task 內部一律走 `superpowers:test-driven-development`（先寫失敗測試 → 跑到紅 → 最小實作 → 跑到綠 → commit）。

## Goal

把 `advisor-war-room` 的個股引擎從「只有方向性紅綠燈」升級成「可執行的專業投資建議」：每檔個股輸出合理價值區間（Bear/Base/Bull）、風險報酬比（R/R）、進出場與停損參考、部位**金額**（含零股標註）、可計算的信心 0-100、三時間框架觀點與三層失效條件。所有數字皆由固定規則計算、可揭露輸入來源，正確性是命門（影響真金白銀的決策）。

**本計畫只做 P0 引擎層，不含 HTML 渲染**（渲染等 UI 設計稿定案後另出計畫）。本計畫產出的 `decision` JSON 區塊是「之後渲染計畫」的介面契約，schema 已在下方 §介面契約 明確定義。

## Architecture

資料流（本計畫新增/修改的部分以 ★ 標記）：

```
update.py（orchestrator）
 ├─ finmind_cache.py ★（get_loader + 同日快取；供下游取代裸 DataLoader()）
 ├─ analyze_tw.py ★（三維燈；改造成「任一資料源缺→標資料缺+data_flags，不整檔 fail」）
 ├─ valuation.py ★（合理價值區間 Bear/Base/Bull，純規則）
 ├─ decision_engine.py ★（rating 五檔＋三框架＋R/R＋停損＋部位金額＋信心 0-100）
 │      輸入 = analyze 結果 + valuation + 大盤燈 + investor_profile
 │      輸出 = data/<id>.json 的 "decision" 區塊
 └─ profile.py ★（讀 data/investor_profile.json）
build_weekly.py / report_stock.py：入口加 consistency.py ★ 檢查（數字差>1% 或日期落後→非零 exit）
```

原則：新模組全走「純規則＋可揭露輸入」，LLM（Claude narration）只解讀與反駁，不產數字。

## Tech Stack

- Python 3.9.6（`./.venv/bin/python`），FinMind 2.0.4，pandas 2.0.4。
- 測試：stdlib `unittest`，純函式進出、pandas 假資料 fixture，**不打真 API**。
- 執行位置：一律 repo 根目錄 `/Users/andyc/Desktop/agent/advisor-war-room`。

## Global Constraints

1. **Python 3.9 相容**：型別註記用 `typing.Optional/List/Dict`，**不可**用 `X | None`、`match/case`、`list[int]` 這類 3.10+ 語法。
2. **只用既有依賴**：`requests`/`pandas`/`FinMind`/`yfinance`。不新增第三方套件（NumPy 隨 pandas 已在，但盡量用 pandas/stdlib）。
3. **風格與 `warroom/analyze_tw.py` 一致**：module docstring 說明用途、繁中註解、小純函式、缺資料降級不 crash。
4. **所有新數字必須可揭露輸入**：valuation 要輸出所用 EPS/倍數/分位；decision 要輸出 R/R 的分子分母、停損依據、部位檔位理由、信心四項拆分。
5. **繁體中文註解與輸出字串**；識別字（函式/變數名）用英文。
6. **金額單位一律新台幣元**（整數），不是「張」也不是「萬」。

---

## 介面契約：`data/<id>.json` 的 `decision` 區塊 schema

Task C 產出、併入既有 `data/<id>.json`（與 `fundamental`/`technical`/`chips`/`summary` 同層）。渲染計畫依此契約讀值：

```jsonc
"decision": {
  "rating": "續抱",                       // ∈ {買進,試單,續抱,觀望,減碼}
  "fair_value": {"bear": 2050.0, "base": 2380.0, "bull": 2720.0} , // 或 null（估值資料不足）
  "valuation": {                          // 估值揭露（來自 valuation.py）
    "path": "per",                        // "per" 或 "pbr"
    "eps_ttm": 62.5, "eps_source": "financial_statement", // 或 "per_backout"
    "eps_forward": 78.1, "growth_used": 0.25,             // growth 已 clamp(-0.2,+0.4)
    "multiples": {"bear": 25.0, "base": 30.0, "bull": 35.0},
    "current_multiple": 32.8, "current_percentile": 0.96,
    "disclosure": "TTM EPS 62.5（財報）、成長 g=+25.0%…"
  },
  "risk_reward": 1.8,                      // 或 null
  "stop": {"price": 2226.0, "pct": -0.08, "basis": "關鍵均線",
           "clamped": true, "note": "參考防守位，接回自行判斷"},
  "entry": {"pullback": "回測型：…", "breakout": "突破型：…"},
  "position": {"tier": "試單", "amount": 100000, "odd_lot": true,
               "shares": 41, "reason": "R/R 1.5-2 且信心 50-65",
               "core_note": "此為核心持股…不影響定期定額核心部位"}, // 非核心股 core_note=""
  "confidence": {"total": 58, "completeness": 30, "consistency": 15,
                 "rr": 8, "regime": 5},
  "time_frames": {
    "short": {"label": "短線 1-4 週", "stance": "中性", "basis": "…", "ref_price": "…"},
    "swing": {"label": "波段 1-3 月（主）", "stance": "中性偏多", "basis": "…", "ref_price": "…"},
    "mid":   {"label": "中期 3-12 月", "stance": "偏多", "basis": "…", "ref_price": "…"}
  },
  "invalidation": {"price": "…", "fundamental": "…", "chips": "…", "any_triggered": false},
  "as_of_price": 2420.0,
  "disclaimer": "本區塊為規則引擎輸出之決策輔助，非投資建議…"
}
```

---

## Task 執行順序（依相依性排定）

A → F → B → C → D → E。（A profile 為底層資料；F 的 `get_loader` 供 B/D 的抓取包裝使用；B/C 為純函式；D 用到 F 的快取；E 收尾。）

以下 Task 依此順序編號 T1–T6，括號標註對應規格計畫群。

---

## T1（群 A）投資人參數落檔 + 讀取工具

### Files
- **Create**：`data/investor_profile.json`
- **Create**：`warroom/profile.py`
- **Create**：`tests/__init__.py`（空檔，讓 `python -m unittest tests.xxx` 可載入）
- **Test**：`tests/test_profile.py`

### Interfaces
- Produces：
  - `load_profile(path: str = "data/investor_profile.json") -> Dict` — 讀 JSON 回 dict。
  - `is_core_holding(profile: Dict, stock_id: str) -> bool`
  - `position_tiers(profile: Dict) -> List[Dict]` — 回 `[{"name":str,"amount":int}, ...]`
- Consumes：無。

### Step 1：寫失敗測試

先建空的 `tests/__init__.py`：

```bash
mkdir -p tests && : > tests/__init__.py
```

`tests/test_profile.py`：

```python
"""T1：investor_profile 落檔與讀取工具測試。"""
import json
import os
import unittest

from warroom.profile import load_profile, is_core_holding, position_tiers


class TestProfile(unittest.TestCase):
    def test_profile_file_exists_and_parses(self):
        prof = load_profile()
        self.assertIn("time_frames", prof)
        self.assertIn("stop_loss_range", prof)
        self.assertIn("position_tiers", prof)
        self.assertIn("core_holdings", prof)

    def test_time_frames_three_horizons(self):
        prof = load_profile()
        tf = prof["time_frames"]
        self.assertEqual(set(tf.keys()), {"short", "swing", "mid"})
        # 波段為主 rating
        self.assertTrue(tf["swing"]["is_primary"])
        self.assertFalse(tf["short"].get("is_primary", False))

    def test_stop_loss_range(self):
        prof = load_profile()
        r = prof["stop_loss_range"]
        # 可忍回撤 -8% ~ -15%
        self.assertAlmostEqual(r["max_pct"], -0.08)
        self.assertAlmostEqual(r["min_pct"], -0.15)

    def test_position_tiers_amounts(self):
        prof = load_profile()
        amounts = [t["amount"] for t in position_tiers(prof)]
        self.assertEqual(amounts, [0, 100000, 200000, 400000, 600000])
        names = [t["name"] for t in position_tiers(prof)]
        self.assertEqual(names, ["空手", "試單", "標準", "加碼", "極高信心"])

    def test_core_holdings(self):
        prof = load_profile()
        self.assertEqual(prof["core_holdings"], ["2330", "0050"])
        self.assertTrue(is_core_holding(prof, "2330"))
        self.assertFalse(is_core_holding(prof, "2454"))

    def test_load_profile_custom_path(self):
        # 自訂路徑亦可讀
        prof = load_profile("data/investor_profile.json")
        self.assertIsInstance(prof, dict)


if __name__ == "__main__":
    unittest.main()
```

### Step 2：跑測試，預期 FAIL

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && ./.venv/bin/python -m unittest tests.test_profile -v
```

預期輸出（模組尚未建立）：
```
ModuleNotFoundError: No module named 'warroom.profile'
```

### Step 3：最小實作

`data/investor_profile.json`：

```json
{
  "_source": "Andy 問卷 2026-07-15 + 補充；規格 docs/superpowers/specs/2026-07-15-precision-upgrade-design.md §1",
  "time_frames": {
    "short": {"label": "短線 1-4 週", "horizon": "1-4 週", "is_primary": false},
    "swing": {"label": "波段 1-3 月", "horizon": "1-3 月", "is_primary": true},
    "mid":   {"label": "中期 3-12 月", "horizon": "3-12 月", "is_primary": false}
  },
  "stop_loss_range": {"min_pct": -0.15, "max_pct": -0.08},
  "position_tiers": [
    {"name": "空手",     "amount": 0},
    {"name": "試單",     "amount": 100000},
    {"name": "標準",     "amount": 200000},
    {"name": "加碼",     "amount": 400000},
    {"name": "極高信心", "amount": 600000}
  ],
  "core_holdings": ["2330", "0050"]
}
```

`warroom/profile.py`：

```python
"""投資人參數（Andy 問卷 2026-07-15，存 data/investor_profile.json）的讀取工具。
規格 §1：三時間框架、停損 -8%~-15%、部位金額檔位 0/10萬/20萬/40萬/60萬、
核心持股 2330/0050。本模組只負責讀，不含任何運算規則。
"""
import json
from typing import Dict, List

DEFAULT_PROFILE_PATH = "data/investor_profile.json"


def load_profile(path: str = DEFAULT_PROFILE_PATH) -> Dict:
    """讀投資人參數 JSON。找不到檔或格式錯會直接拋例外（讓上層明確失敗，不吞錯）。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def is_core_holding(profile: Dict, stock_id: str) -> bool:
    """是否為核心持股（定期定額續買，加減碼建議不影響核心部位）。"""
    return stock_id in profile.get("core_holdings", [])


def position_tiers(profile: Dict) -> List[Dict]:
    """部位金額檔位清單：[{"name":..., "amount":...}, ...]。"""
    return profile.get("position_tiers", [])
```

### Step 4：跑測試，預期 PASS

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && ./.venv/bin/python -m unittest tests.test_profile -v
```
預期：`Ran 6 tests ... OK`。

### Step 5：git commit

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && \
git add data/investor_profile.json warroom/profile.py tests/__init__.py tests/test_profile.py && \
git commit -m "T1: investor_profile 落檔 + profile.py 讀取工具

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## T2（群 F）FinMind 呼叫快取 + FINMIND_TOKEN

### Files
- **Create**：`warroom/finmind_cache.py`
- **Modify**：`.gitignore`（加 `data/cache/`）
- **Test**：`tests/test_finmind_cache.py`

### Interfaces
- Produces：
  - `get_loader() -> DataLoader` — 單例；若環境有 `FINMIND_TOKEN` 則 `login_by_token`，失敗或無 token 照舊免登入。
  - `cached_fetch(method_name: str, loader=None, cache_dir: str = "data/cache", **kwargs) -> pandas.DataFrame` — 呼叫 `loader.<method_name>(**kwargs)`，同日相同參數不重抓（快取到 `data/cache/<YYYY-MM-DD>/<md5>.pkl`）。`loader=None` 時用 `get_loader()`。
- Consumes：`FinMind.data.DataLoader`。

### Step 1：寫失敗測試

`tests/test_finmind_cache.py`：

```python
"""T2：FinMind 同日快取 + token 支援測試（用假 loader，不打真 API）。"""
import os
import shutil
import tempfile
import unittest

import pandas as pd

from warroom.finmind_cache import cached_fetch


class FakeLoader:
    """假 DataLoader：記錄呼叫次數，回固定 DataFrame。"""

    def __init__(self):
        self.calls = 0

    def taiwan_stock_daily(self, stock_id, start_date):
        self.calls += 1
        return pd.DataFrame({"date": ["2026-07-14"], "stock_id": [stock_id],
                             "close": [100.0]})


class TestFinmindCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_first_call_hits_loader(self):
        fake = FakeLoader()
        df = cached_fetch("taiwan_stock_daily", loader=fake, cache_dir=self.tmp,
                          stock_id="2330", start_date="2025-01-01")
        self.assertEqual(fake.calls, 1)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["stock_id"], "2330")

    def test_second_same_day_call_uses_cache(self):
        fake = FakeLoader()
        kw = dict(stock_id="2330", start_date="2025-01-01")
        cached_fetch("taiwan_stock_daily", loader=fake, cache_dir=self.tmp, **kw)
        cached_fetch("taiwan_stock_daily", loader=fake, cache_dir=self.tmp, **kw)
        # 第二次應命中快取，不再呼叫 loader
        self.assertEqual(fake.calls, 1)

    def test_different_params_not_shared(self):
        fake = FakeLoader()
        cached_fetch("taiwan_stock_daily", loader=fake, cache_dir=self.tmp,
                     stock_id="2330", start_date="2025-01-01")
        cached_fetch("taiwan_stock_daily", loader=fake, cache_dir=self.tmp,
                     stock_id="2454", start_date="2025-01-01")
        # 不同參數各抓一次
        self.assertEqual(fake.calls, 2)


if __name__ == "__main__":
    unittest.main()
```

### Step 2：跑測試，預期 FAIL

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && ./.venv/bin/python -m unittest tests.test_finmind_cache -v
```
預期：`ModuleNotFoundError: No module named 'warroom.finmind_cache'`。

### Step 3：最小實作

`warroom/finmind_cache.py`：

```python
"""FinMind 呼叫層：單例 DataLoader（可選 FINMIND_TOKEN）＋同日檔案快取。
規格 §4：申請免費 token 走環境變數 FINMIND_TOKEN（無 token 照舊跑）；
日線/財報同日不重抓（data/cache/<日期>/，隔日自然失效）。
下游模組請改用 get_loader() / cached_fetch() 取代裸 DataLoader()。
"""
import hashlib
import os
import pickle
from datetime import datetime, timezone, timedelta
from typing import Optional

from FinMind.data import DataLoader

_TPE = timezone(timedelta(hours=8))
_LOADER = None  # 單例


def get_loader() -> DataLoader:
    """回傳單例 DataLoader。若環境有 FINMIND_TOKEN 就登入（額度 300→600/hr）；
    token 失效或不存在時退回免登入模式，不讓程式中斷。"""
    global _LOADER
    if _LOADER is None:
        dl = DataLoader()
        token = os.environ.get("FINMIND_TOKEN")
        if token:
            try:
                dl.login_by_token(api_token=token)
            except Exception:
                pass  # token 失效 → 免登入照跑
        _LOADER = dl
    return _LOADER


def _today() -> str:
    return datetime.now(_TPE).strftime("%Y-%m-%d")


def _cache_key(method_name: str, kwargs: dict) -> str:
    raw = method_name + "|" + "&".join(f"{k}={kwargs[k]}" for k in sorted(kwargs))
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def cached_fetch(method_name: str, loader: Optional[object] = None,
                 cache_dir: str = "data/cache", **kwargs):
    """呼叫 loader.<method_name>(**kwargs)，同日相同參數命中快取。
    - loader=None → 用 get_loader()（正式執行）。測試可傳假 loader。
    - 快取讀寫任何失敗都不影響主流程（能抓到資料最重要）。
    """
    if loader is None:
        loader = get_loader()
    key = _cache_key(method_name, kwargs)
    day_dir = os.path.join(cache_dir, _today())
    path = os.path.join(day_dir, key + ".pkl")
    if os.path.exists(path):
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass  # 快取壞掉 → 重抓
    df = getattr(loader, method_name)(**kwargs)
    try:
        os.makedirs(day_dir, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(df, f)
    except Exception:
        pass  # 寫快取失敗不影響回傳
    return df
```

`.gitignore` 追加一行（在檔尾）：

```
data/cache/
```

### Step 4：跑測試，預期 PASS

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && ./.venv/bin/python -m unittest tests.test_finmind_cache -v
```
預期：`Ran 3 tests ... OK`。

### Step 5：git commit

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && \
git add warroom/finmind_cache.py tests/test_finmind_cache.py .gitignore && \
git commit -m "T2: FinMind 同日快取 + FINMIND_TOKEN 支援

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## T3（群 B）合理價值區間 valuation.py

### Files
- **Create**：`warroom/valuation.py`
- **Test**：`tests/test_valuation.py`

### Interfaces
- Produces（純函式，供測試逐一驗證）：
  - `is_pbr_industry(industry_category: Optional[str]) -> bool`
  - `ttm_eps_from_statement(fs_df) -> Optional[float]` — 長格式綜合損益表（欄 `date/type/value`）→ TTM EPS（FinMind 的 EPS 為**單季值**，直接加總最近 4 季；2026-07-15 已用真 API 實測證實，見下方驗證紀錄）。
  - `weighted_revenue_yoy(rev_df) -> Optional[float]` — 近 3/6/12 月營收 YoY 加權（0.5/0.3/0.2），回小數。
  - `forward_eps(ttm_eps: float, weighted_yoy: Optional[float]) -> float` — `ttm×(1+clamp(g,-0.2,0.4))`。
  - `multiple_percentiles(series: List[float]) -> Optional[Dict]` — 回 `{"p10","p25","p50","p75"}`；樣本 <8 回 None。
  - `current_percentile(series: List[float], current: Optional[float]) -> Optional[float]`
  - `fair_value_per_path(fwd_eps: float, per_pcts: Dict, market_light: str) -> Dict`
  - `fair_value_pbr_path(price: float, pbr_current: float, pbr_pcts: Dict, roe: Optional[float], market_light: str) -> Optional[Dict]`
  - `compute_valuation(inp: Dict) -> Dict` — 統一入口，輸出契約見 §介面契約的 `valuation` 欄位 + `fair_value`/`confidence_penalty`。
- Consumes：Task C 用 `compute_valuation` 的輸出；`inp` 由抓取層（沿用 T2 `cached_fetch`）組。

`compute_valuation` 的 `inp` dict 欄位：`price(float)`、`industry_category(str)`、`market_light("green"/"amber"/"red")`、`fs_df(綜合損益表 long DataFrame 或 None)`、`rev_df(月營收 DataFrame 或 None)`、`per_series(List[float])`、`per_current(Optional[float])`、`pbr_series(List[float])`、`pbr_current(Optional[float])`、`roe(Optional[float] 小數)`。

### Step 1：寫失敗測試

`tests/test_valuation.py`：

```python
"""T3：合理價值區間 valuation.py 測試（假資料 fixture，不打真 API）。"""
import unittest

import pandas as pd

from warroom.valuation import (
    is_pbr_industry, ttm_eps_from_statement, weighted_revenue_yoy,
    forward_eps, multiple_percentiles, current_percentile,
    fair_value_per_path, fair_value_pbr_path, compute_valuation,
)


def make_fs(eps_by_quarter):
    """eps_by_quarter: list of (date, 單季EPS)。回長格式綜合損益表 DataFrame。"""
    rows = []
    for d, v in eps_by_quarter:
        rows.append({"date": d, "stock_id": "1111", "type": "EPS",
                     "value": v, "origin_name": "基本每股盈餘"})
        # 混入雜訊 type，測試要能過濾
        rows.append({"date": d, "stock_id": "1111", "type": "Revenue",
                     "value": 999.0, "origin_name": "營業收入"})
    return pd.DataFrame(rows)


def make_rev(months):
    """months: list of (year, month, revenue)。"""
    return pd.DataFrame([{"date": f"{y}-{m:02d}-01", "stock_id": "1111",
                          "revenue": r, "revenue_year": y, "revenue_month": m}
                         for (y, m, r) in months])


class TestValuation(unittest.TestCase):
    def test_is_pbr_industry(self):
        self.assertTrue(is_pbr_industry("金融保險"))
        self.assertTrue(is_pbr_industry("航運業"))
        self.assertFalse(is_pbr_industry("半導體業"))
        self.assertFalse(is_pbr_industry(None))

    def test_ttm_eps_sum_last4(self):
        # FinMind EPS 為單季值（2026-07-15 真 API 實測證實）：直接加總最近 4 季
        # 單季：25Q1=3,25Q2=4,25Q3=5,25Q4=8,26Q1=4 → 近4季（25Q2..26Q1）= 4+5+8+4 = 21
        fs = make_fs([("2025-03-31", 3), ("2025-06-30", 4), ("2025-09-30", 5),
                      ("2025-12-31", 8), ("2026-03-31", 4)])
        self.assertAlmostEqual(ttm_eps_from_statement(fs), 21.0)

    def test_ttm_eps_insufficient(self):
        fs = make_fs([("2026-03-31", 4)])  # 只有 1 季 → None
        self.assertIsNone(ttm_eps_from_statement(fs))
        self.assertIsNone(ttm_eps_from_statement(None))

    def test_weighted_revenue_yoy(self):
        # 造 24 個月，去年每月 100、今年每月 130 → 各窗口 YoY 皆 +30%
        months = [(2025, m, 100) for m in range(1, 13)] + \
                 [(2026, m, 130) for m in range(1, 13)]
        g = weighted_revenue_yoy(make_rev(months))
        self.assertAlmostEqual(g, 0.30, places=3)

    def test_forward_eps_clamps(self):
        self.assertAlmostEqual(forward_eps(100.0, 0.25), 125.0)
        self.assertAlmostEqual(forward_eps(100.0, 0.90), 140.0)   # clamp 上限 +40%
        self.assertAlmostEqual(forward_eps(100.0, -0.50), 80.0)   # clamp 下限 -20%
        self.assertAlmostEqual(forward_eps(100.0, None), 100.0)   # 無成長 → g=0

    def test_multiple_percentiles(self):
        pcts = multiple_percentiles(list(range(10, 30)))  # 10..29
        self.assertIsNotNone(pcts)
        self.assertLess(pcts["p25"], pcts["p50"])
        self.assertLess(pcts["p50"], pcts["p75"])
        self.assertIsNone(multiple_percentiles([10, 11, 12]))  # 樣本<8 → None

    def test_current_percentile(self):
        self.assertAlmostEqual(current_percentile([10, 20, 30, 40], 35), 0.75)
        self.assertIsNone(current_percentile([], 10))

    def test_fair_value_per_path_red_market_downgrades(self):
        pcts = {"p10": 20.0, "p25": 25.0, "p50": 30.0, "p75": 35.0}
        normal = fair_value_per_path(100.0, pcts, "amber")
        red = fair_value_per_path(100.0, pcts, "red")
        self.assertEqual(normal["base"], 3000.0)  # 100×30
        self.assertEqual(red["base"], 2500.0)      # 下修一檔 → 100×25
        self.assertLess(red["bull"], normal["bull"])

    def test_fair_value_pbr_path(self):
        pcts = {"p10": 0.8, "p25": 1.0, "p50": 1.5, "p75": 2.0}
        fv = fair_value_pbr_path(150.0, 1.5, pcts, roe=0.20, market_light="amber")
        # BVPS = 150/1.5 = 100；ROE>15% → base 用 (p50+p75)/2=1.75
        self.assertAlmostEqual(fv["bvps"], 100.0)
        self.assertAlmostEqual(fv["base"], 175.0)

    def test_compute_valuation_per_path(self):
        # 單季制 fixture（2026-07-15 實測定案；實作時已同步修正）
        fs = make_fs([("2025-03-31", 3), ("2025-06-30", 4), ("2025-09-30", 5),
                      ("2025-12-31", 8), ("2026-03-31", 4)])  # TTM=21
        inp = {
            "price": 700.0, "industry_category": "半導體業", "market_light": "amber",
            "fs_df": fs, "rev_df": make_rev([(2025, m, 100) for m in range(1, 13)] +
                                            [(2026, m, 130) for m in range(1, 13)]),
            "per_series": [float(x) for x in range(10, 30)], "per_current": 25.0,
            "pbr_series": [], "pbr_current": None, "roe": None,
        }
        out = compute_valuation(inp)
        self.assertEqual(out["path"], "per")
        self.assertEqual(out["eps_ttm"], 21.0)
        self.assertEqual(out["eps_source"], "financial_statement")
        self.assertIsNotNone(out["fair_value"])
        self.assertEqual(out["confidence_penalty"], 0)

    def test_compute_valuation_backout_fallback(self):
        # 無財報 → 用 現價/PER 反推、降信心
        inp = {
            "price": 500.0, "industry_category": "半導體業", "market_light": "amber",
            "fs_df": None, "rev_df": None,
            "per_series": [float(x) for x in range(10, 30)], "per_current": 20.0,
            "pbr_series": [], "pbr_current": None, "roe": None,
        }
        out = compute_valuation(inp)
        self.assertEqual(out["eps_source"], "per_backout")
        self.assertAlmostEqual(out["eps_ttm"], 25.0)  # 500/20
        self.assertGreater(out["confidence_penalty"], 0)

    def test_compute_valuation_pbr_path(self):
        inp = {
            "price": 60.0, "industry_category": "金融保險", "market_light": "amber",
            "fs_df": None, "rev_df": None, "per_series": [], "per_current": None,
            "pbr_series": [0.8 + 0.02 * i for i in range(20)], "pbr_current": 1.0,
            "roe": 0.12,
        }
        out = compute_valuation(inp)
        self.assertEqual(out["path"], "pbr")
        self.assertIsNotNone(out["fair_value"])


if __name__ == "__main__":
    unittest.main()
```

### Step 2：跑測試，預期 FAIL

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && ./.venv/bin/python -m unittest tests.test_valuation -v
```
預期：`ModuleNotFoundError: No module named 'warroom.valuation'`。

### Step 3：最小實作

> **✅ 已驗證（2026-07-15，主對話真 API 實測）**：FinMind 的 EPS 為**單季值**——2330 的 2024 四季 8.70/9.56/12.55/14.45 加總 ≈45.25＝全年 EPS；近 4 季合計 74.39 換算 PER≈32.5 與市場現值 32.8 吻合。本模組已改為「直接加總最近 4 季」。以下抽驗指令保留供日後複驗：
> ```bash
> cd /Users/andyc/Desktop/agent/advisor-war-room && ./.venv/bin/python -c "
> from FinMind.data import DataLoader
> import pandas as pd
> df = DataLoader().taiwan_stock_financial_statement(stock_id='2330', start_date='2024-01-01')
> e = df[df['type']=='EPS'][['date','value']].sort_values('date')
> print(e.to_string())
> print('若 Q2 值≈Q1×2、Q4≈全年 → 累計制（本模組正確）；若各季獨立小值 → 需改為直接加總近4季')"
> ```
> （歷史註記：原計畫假設累計制，2026-07-15 實測推翻，已全數改為單季直加。）

`warroom/valuation.py`：

```python
"""合理價值區間（Bear/Base/Bull）— 純規則、可揭露輸入（規格 §3.1）。
PER 路徑：TTM EPS 優先財報，取不到用 現價/PER 反推並降信心；
  Forward EPS = TTM × (1+clamp(加權YoY, -20%, +40%))；
  Bear/Base/Bull = Forward EPS × 個股 PER 25/50/75 分位；大盤紅燈時倍數下修一檔。
PBR 路徑（金融/景氣循環股，用 industry_category 判斷）：PBR 分位 × 每股淨值，ROE 微調 base。
所有輸出都附 disclosure，揭露所用 EPS/倍數/分位。
"""
from typing import Dict, List, Optional

import pandas as pd

# 走 PBR 路徑的產業（金融保險與典型景氣循環）。用 FinMind industry_category 比對。
PBR_INDUSTRIES = {"金融保險", "銀行業", "保險業", "證券業",
                  "航運業", "鋼鐵工業", "水泥工業", "塑膠工業"}

# FinMind 綜合損益表 EPS 為「單季值」（2026-07-15 真 API 實測：2330 四季 8.70+9.56+12.55+14.45≈全年 45.25）。
_QUARTER_BY_MONTH = {3: 1, 6: 2, 9: 3, 12: 4}


def is_pbr_industry(industry_category: Optional[str]) -> bool:
    """金融/景氣循環股（改走 PBR×ROE 路徑，不硬套 PER）。"""
    if not industry_category:
        return False
    return industry_category in PBR_INDUSTRIES


def _quarter_key(date_str: str):
    """'2026-03-31' → (2026, 1)；非季底月份回 None。"""
    try:
        y, m = int(date_str[:4]), int(date_str[5:7])
    except (ValueError, IndexError):
        return None
    q = _QUARTER_BY_MONTH.get(m)
    return (y, q) if q else None


def ttm_eps_from_statement(fs_df) -> Optional[float]:
    """長格式綜合損益表 → TTM EPS。
    FinMind 的 EPS 為單季值（2026-07-15 實測證實），直接加總最近 4 個季度。
    抓不到 EPS 或不足 4 季 → None（讓上層改走 fallback）。
    """
    if fs_df is None or len(fs_df) == 0 or "type" not in fs_df.columns:
        return None
    eps = fs_df[fs_df["type"] == "EPS"].copy()
    if len(eps) == 0:
        return None
    eps["value"] = pd.to_numeric(eps["value"], errors="coerce")
    eps = eps.dropna(subset=["value"])
    single = {}  # (year, quarter) -> 單季 EPS（同季取最後出現）
    for _, r in eps.iterrows():
        qk = _quarter_key(str(r["date"]))
        if qk:
            single[qk] = float(r["value"])
    if len(single) < 4:
        return None
    keys = sorted(single.keys())  # (year, quarter) 升冪
    return round(sum(single[k] for k in keys[-4:]), 2)


def weighted_revenue_yoy(rev_df) -> Optional[float]:
    """近 3/6/12 月營收 YoY 加權（權重 0.5/0.3/0.2），回小數（0.30 = +30%）。
    任一窗口算不出就跳過、用可得窗口重新歸一化權重；全算不出 → None。"""
    if rev_df is None or len(rev_df) == 0:
        return None
    r = rev_df.copy()
    r["revenue"] = pd.to_numeric(r["revenue"], errors="coerce")
    r = r.dropna(subset=["revenue"])
    r["ym"] = r["revenue_year"].astype(int) * 100 + r["revenue_month"].astype(int)
    r = r.sort_values("ym").reset_index(drop=True)
    lookup = {int(row["ym"]): float(row["revenue"]) for _, row in r.iterrows()}

    def yoy_for(row):
        py_ym = (int(row["revenue_year"]) - 1) * 100 + int(row["revenue_month"])
        base = lookup.get(py_ym)
        if base and base != 0:
            return float(row["revenue"]) / base - 1
        return None

    def avg_last(n):
        vals = [yoy_for(row) for _, row in r.tail(n).iterrows()]
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None

    parts = []
    for w, n in ((0.5, 3), (0.3, 6), (0.2, 12)):
        v = avg_last(n)
        if v is not None:
            parts.append((w, v))
    if not parts:
        return None
    wsum = sum(w for w, _ in parts)
    return round(sum(w * v for w, v in parts) / wsum, 4)


def forward_eps(ttm_eps: float, weighted_yoy: Optional[float]) -> float:
    """Forward EPS = TTM × (1 + clamp(g, -20%, +40%))。g 為 None 時視為 0。"""
    g = weighted_yoy if weighted_yoy is not None else 0.0
    g = max(-0.20, min(0.40, g))
    return round(ttm_eps * (1 + g), 2)


def _percentile(sorted_vals: List[float], q: float) -> Optional[float]:
    """線性插值分位（0<=q<=1），sorted_vals 需已排序。"""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = q * (len(sorted_vals) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def multiple_percentiles(series: List[float]) -> Optional[Dict]:
    """PER/PBR 歷史分位 p10/p25/p50/p75。只取正值；樣本 <8 → None（樣本不足不硬給）。"""
    vals = sorted(v for v in series if v is not None and v > 0)
    if len(vals) < 8:
        return None
    return {
        "p10": round(_percentile(vals, 0.10), 2),
        "p25": round(_percentile(vals, 0.25), 2),
        "p50": round(_percentile(vals, 0.50), 2),
        "p75": round(_percentile(vals, 0.75), 2),
    }


def current_percentile(series: List[float], current: Optional[float]) -> Optional[float]:
    """現值落在歷史的分位（低於現值的比例）。"""
    vals = [v for v in series if v is not None and v > 0]
    if not vals or current is None:
        return None
    return round(sum(1 for v in vals if v < current) / len(vals), 2)


def _trio(pcts: Dict, market_light: str):
    """一般 p25/p50/p75；大盤紅燈 → 下修一檔 p10/p25/p50。"""
    if market_light == "red":
        return pcts["p10"], pcts["p25"], pcts["p50"]
    return pcts["p25"], pcts["p50"], pcts["p75"]


def fair_value_per_path(fwd_eps: float, per_pcts: Dict, market_light: str) -> Dict:
    """PER 路徑：Bear/Base/Bull = Forward EPS × 分位倍數。"""
    lo, mid, hi = _trio(per_pcts, market_light)
    return {
        "bear": round(fwd_eps * lo, 1),
        "base": round(fwd_eps * mid, 1),
        "bull": round(fwd_eps * hi, 1),
        "multiples": {"bear": round(lo, 2), "base": round(mid, 2), "bull": round(hi, 2)},
    }


def fair_value_pbr_path(price: float, pbr_current: float, pbr_pcts: Dict,
                        roe: Optional[float], market_light: str) -> Optional[Dict]:
    """PBR 路徑：每股淨值 = 現價/現值PBR；Bear/Base/Bull = BVPS × 分位PBR。
    ROE>15% base 上移半檔、<8% 下移半檔（品質溢/折價）。"""
    if not pbr_current or pbr_current <= 0:
        return None
    bvps = price / pbr_current
    lo, mid, hi = _trio(pbr_pcts, market_light)
    base_mult = mid
    if roe is not None:
        if roe > 0.15:
            base_mult = (mid + hi) / 2
        elif roe < 0.08:
            base_mult = (lo + mid) / 2
    return {
        "bear": round(bvps * lo, 1),
        "base": round(bvps * base_mult, 1),
        "bull": round(bvps * hi, 1),
        "multiples": {"bear": round(lo, 2), "base": round(base_mult, 2), "bull": round(hi, 2)},
        "bvps": round(bvps, 2),
        "roe": roe,
    }


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:+.1f}%"


def _insufficient(path: str, penalty: int, note: str) -> Dict:
    """估值資料不足時的統一回傳（fair_value=None，並回報信心扣分）。"""
    return {
        "path": path, "eps_ttm": None, "eps_source": None, "eps_forward": None,
        "growth_used": None, "fair_value": None, "multiples": None,
        "current_multiple": None, "current_percentile": None, "bvps": None, "roe": None,
        "confidence_penalty": penalty, "disclosure": note,
    }


def compute_valuation(inp: Dict) -> Dict:
    """統一入口。依 industry_category 選 PER 或 PBR 路徑，回估值區塊（見計畫 §介面契約）。"""
    price = inp["price"]
    market_light = inp.get("market_light", "amber")

    # ---- 金融/循環股：PBR 路徑 ----
    if is_pbr_industry(inp.get("industry_category")):
        pbr_series = inp.get("pbr_series") or []
        pbr_pcts = multiple_percentiles(pbr_series)
        pbr_cur = inp.get("pbr_current")
        if pbr_pcts is None or not pbr_cur:
            return _insufficient("pbr", 30, "PBR 樣本不足，無法給估值區間")
        fv = fair_value_pbr_path(price, pbr_cur, pbr_pcts, inp.get("roe"), market_light)
        disclosure = (
            f"金融/循環股 PBR 路徑：每股淨值 {fv['bvps']}、"
            f"PBR 25/50/75={pbr_pcts['p25']}/{pbr_pcts['p50']}/{pbr_pcts['p75']}"
            f"（現值 {pbr_cur}，分位 {_pct(current_percentile(pbr_series, pbr_cur))}）；"
            f"ROE={_pct(inp.get('roe'))}"
            + ("；大盤紅燈倍數下修一檔" if market_light == "red" else ""))
        return {
            "path": "pbr", "eps_ttm": None, "eps_source": None, "eps_forward": None,
            "growth_used": None,
            "fair_value": {"bear": fv["bear"], "base": fv["base"], "bull": fv["bull"]},
            "multiples": fv["multiples"], "current_multiple": pbr_cur,
            "current_percentile": current_percentile(pbr_series, pbr_cur),
            "bvps": fv["bvps"], "roe": inp.get("roe"),
            "confidence_penalty": 0, "disclosure": disclosure,
        }

    # ---- 一般股：PER 路徑 ----
    penalty = 0
    eps_ttm = ttm_eps_from_statement(inp.get("fs_df"))
    eps_source = "financial_statement"
    per_cur = inp.get("per_current")
    if eps_ttm is None:
        if per_cur and per_cur > 0:
            eps_ttm = round(price / per_cur, 2)
            eps_source = "per_backout"
            penalty += 15  # 無財報、用現價反推 → 降估值信心
        else:
            return _insufficient("per", 30, "無 EPS 亦無有效 PER，無法給估值區間")
    per_series = inp.get("per_series") or []
    per_pcts = multiple_percentiles(per_series)
    if per_pcts is None:
        return _insufficient("per", 25, "PER 歷史樣本不足，無法給估值區間")
    g = weighted_revenue_yoy(inp.get("rev_df"))
    fwd = forward_eps(eps_ttm, g)
    fv = fair_value_per_path(fwd, per_pcts, market_light)
    src_zh = "財報 TTM" if eps_source == "financial_statement" else "現價/PER 反推（降信心）"
    disclosure = (
        f"TTM EPS {eps_ttm}（{src_zh}）、成長 g={_pct(g)}（clamp -20%~+40%）、"
        f"Forward EPS {fwd}；PER 25/50/75={per_pcts['p25']}/{per_pcts['p50']}/{per_pcts['p75']}"
        f"（現值 {per_cur}，分位 {_pct(current_percentile(per_series, per_cur))}）"
        + ("；大盤紅燈倍數下修一檔" if market_light == "red" else ""))
    return {
        "path": "per", "eps_ttm": eps_ttm, "eps_source": eps_source, "eps_forward": fwd,
        "growth_used": max(-0.20, min(0.40, g)) if g is not None else 0.0,
        "fair_value": {"bear": fv["bear"], "base": fv["base"], "bull": fv["bull"]},
        "multiples": fv["multiples"], "current_multiple": per_cur,
        "current_percentile": current_percentile(per_series, per_cur),
        "bvps": None, "roe": None,
        "confidence_penalty": penalty, "disclosure": disclosure,
    }
```

### Step 4：跑測試，預期 PASS

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && ./.venv/bin/python -m unittest tests.test_valuation -v
```
預期：`Ran 12 tests ... OK`。

### Step 5：git commit

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && \
git add warroom/valuation.py tests/test_valuation.py && \
git commit -m "T3: valuation.py 合理價值區間（PER/PBR 雙路徑）

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## T4（群 C）決策引擎 decision_engine.py

### Files
- **Create**：`warroom/decision_engine.py`
- **Test**：`tests/test_decision_engine.py`

### Interfaces
- Produces（純函式）：
  - `atr14(price_df, n: int = 14) -> Optional[float]` — 需 `max/min/close` 欄。
  - `atr_percent_median(price_df, window: int = 240) -> Optional[float]` — 近 1 年日振幅/收盤 中位（波動 proxy）。
  - `light_consistency_score(lights: List[str]) -> int` — 三燈一致性 0-30。
  - `composite_score(f_light, t_light, c_light, per_percentile, market_light) -> float`
  - `rating(f_light, t_light, c_light, per_percentile, market_light, rr) -> str` — 回 {買進,試單,續抱,觀望,減碼}；`rr<1.5` 一律不給「買進」。
  - `stop_reference(price, atr, key_ma, low20, min_pct=-0.15, max_pct=-0.08) -> Dict`
  - `risk_reward(base_fair, price, stop_price) -> Optional[float]`
  - `confidence_score(data_flags: Dict, lights, rr, market_light) -> Dict`
  - `position_sizing(rr, confidence, lights, market_light, atr_pct, atr_median_pct, data_incomplete, profile, price, stock_id) -> Dict`
  - `entry_conditions(price, atr, low20, high20, ma20, avg_vol20) -> Dict`
  - `time_frames(lights, rating_main, fair_value, tech_ev, valuation) -> Dict`
  - `invalidation(stop_price, rev_signals, chip_signals) -> Dict`
  - `build_decision(...) -> Dict` — 組裝所有片段成 `decision` 區塊（見 §介面契約）。完整簽名見實作。
- Consumes：T3 `compute_valuation` 輸出（valuation dict）、T1 `load_profile`、analyze 的三燈與 `data_flags`（T5 產）、大盤燈（`warroom.market.fetch_market()["light"]`）。

### Step 1：寫失敗測試

`tests/test_decision_engine.py`：

```python
"""T4：決策引擎 decision_engine.py 測試（純函式 + 假 price DataFrame）。"""
import unittest

import pandas as pd

from warroom.decision_engine import (
    atr14, atr_percent_median, light_consistency_score, composite_score,
    rating, stop_reference, risk_reward, confidence_score, position_sizing,
    entry_conditions, time_frames, invalidation, build_decision,
)

PROFILE = {
    "position_tiers": [
        {"name": "空手", "amount": 0}, {"name": "試單", "amount": 100000},
        {"name": "標準", "amount": 200000}, {"name": "加碼", "amount": 400000},
        {"name": "極高信心", "amount": 600000},
    ],
    "core_holdings": ["2330", "0050"],
}


def make_price(n=30, base=100.0):
    rows = []
    for i in range(n):
        c = base + i
        rows.append({"date": f"2026-06-{(i % 28) + 1:02d}", "max": c + 2,
                     "min": c - 2, "close": c, "Trading_Volume": 1000 + i})
    return pd.DataFrame(rows)


class TestDecisionEngine(unittest.TestCase):
    def test_atr14_needs_min_rows(self):
        self.assertIsNone(atr14(make_price(10)))  # <15 列
        self.assertIsNotNone(atr14(make_price(30)))

    def test_atr14_missing_cols(self):
        df = pd.DataFrame({"date": ["2026-06-01"] * 20, "close": [100.0] * 20})
        self.assertIsNone(atr14(df))

    def test_atr_percent_median(self):
        m = atr_percent_median(make_price(60))
        self.assertIsNotNone(m)
        self.assertGreater(m, 0)

    def test_light_consistency(self):
        self.assertEqual(light_consistency_score(["green", "green", "green"]), 30)
        self.assertEqual(light_consistency_score(["green", "green", "amber"]), 22)
        self.assertEqual(light_consistency_score(["green", "amber", "amber"]), 18)
        self.assertEqual(light_consistency_score(["amber", "amber", "amber"]), 15)
        self.assertEqual(light_consistency_score(["green", "red", "amber"]), 0)  # 衝突

    def test_composite_score_valuation_penalty(self):
        # 高估值分位（>0.85）壓低分數
        hi = composite_score("green", "green", "green", 0.96, "amber")
        lo = composite_score("green", "green", "green", 0.30, "amber")
        self.assertLess(hi, lo)

    def test_rating_no_buy_when_rr_low(self):
        # 三燈全綠但 R/R<1.5 → 不可買進
        r = rating("green", "green", "green", 0.30, "green", rr=1.0)
        self.assertNotEqual(r, "買進")
        r2 = rating("green", "green", "green", 0.30, "green", rr=3.0)
        self.assertEqual(r2, "買進")

    def test_rating_conflict_is_watch(self):
        self.assertEqual(rating("green", "red", "amber", 0.5, "amber", rr=3.0), "觀望")

    def test_stop_reference_clamped_to_range(self):
        # 關鍵均線離現價很近（-2%）→ 被夾到 -8%
        s = stop_reference(100.0, atr=1.0, key_ma=98.0, low20=97.0)
        self.assertLessEqual(s["pct"], -0.08 + 1e-9)
        self.assertGreaterEqual(s["pct"], -0.15 - 1e-9)
        self.assertTrue(s["clamped"])

    def test_stop_reference_deep_clamped(self):
        # ATR 很大導致停損 <-15% → 夾到 -15%
        s = stop_reference(100.0, atr=20.0, key_ma=50.0, low20=40.0)
        self.assertAlmostEqual(s["pct"], -0.15, places=4)

    def test_risk_reward(self):
        self.assertAlmostEqual(risk_reward(120.0, 100.0, 90.0), 2.0)  # (120-100)/(100-90)
        self.assertIsNone(risk_reward(120.0, 100.0, 100.0))  # 分母 0
        self.assertIsNone(risk_reward(None, 100.0, 90.0))

    def test_confidence_score_components(self):
        flags = {"fundamental": True, "technical": True, "chips": True, "eps_statement": True}
        c = confidence_score(flags, ["green", "green", "green"], rr=3.0, market_light="green")
        self.assertEqual(c["completeness"], 30)
        self.assertEqual(c["consistency"], 30)
        self.assertEqual(c["rr"], 20)
        self.assertEqual(c["regime"], 20)
        self.assertEqual(c["total"], 100)

    def test_confidence_penalized_when_data_missing(self):
        flags = {"fundamental": True, "technical": True, "chips": False, "eps_statement": False}
        c = confidence_score(flags, ["green", "amber", "na"], rr=None, market_light="red")
        self.assertLess(c["total"], 50)

    def test_position_sizing_ladder(self):
        # 極高信心：R/R>3、信心>80、三燈一致、低波動
        p = position_sizing(3.5, 90, ["green", "green", "green"], "green",
                            atr_pct=0.01, atr_median_pct=0.02, data_incomplete=False,
                            profile=PROFILE, price=100.0, stock_id="2454")
        self.assertEqual(p["amount"], 600000)
        # R/R<1.5 → 空手
        p0 = position_sizing(1.0, 90, ["green", "green", "green"], "green",
                             atr_pct=0.01, atr_median_pct=0.02, data_incomplete=False,
                             profile=PROFILE, price=100.0, stock_id="2454")
        self.assertEqual(p0["amount"], 0)
        # 大盤紅燈 → 空手
        pr = position_sizing(3.0, 85, ["green", "green", "amber"], "red",
                             atr_pct=0.01, atr_median_pct=0.02, data_incomplete=False,
                             profile=PROFILE, price=100.0, stock_id="2454")
        self.assertEqual(pr["amount"], 0)

    def test_position_odd_lot_and_core_note(self):
        # 股價 2420、試單 10 萬 → 一張要 242 萬 > 10 萬 → 零股
        p = position_sizing(1.8, 58, ["green", "amber", "amber"], "amber",
                            atr_pct=0.02, atr_median_pct=0.02, data_incomplete=False,
                            profile=PROFILE, price=2420.0, stock_id="2330")
        self.assertEqual(p["tier"], "試單")
        self.assertTrue(p["odd_lot"])
        self.assertIn("核心持股", p["core_note"])  # 2330 為核心

    def test_entry_conditions(self):
        e = entry_conditions(100.0, atr=2.0, low20=95.0, high20=110.0, ma20=98.0,
                             avg_vol20=1000.0)
        self.assertIn("回測型", e["pullback"])
        self.assertIn("突破型", e["breakout"])

    def test_time_frames_three(self):
        tf = time_frames(["green", "amber", "red"], "續抱",
                         {"base": 120.0, "bull": 140.0}, {"MA20": 98.0},
                         {"current_percentile": 0.9})
        self.assertEqual(set(tf.keys()), {"short", "swing", "mid"})
        self.assertIn("波段", tf["swing"]["label"])

    def test_invalidation_triggers(self):
        inv = invalidation(90.0,
                           {"yoy_negative": True, "below_6m_2months": True},
                           {"sell_streak_ge3": True, "ratio_gt_15pct": True})
        self.assertTrue(inv["any_triggered"])
        self.assertIn("已觸發", inv["fundamental"])

    def test_build_decision_integration(self):
        valuation = {
            "path": "per", "eps_ttm": 60.0, "eps_source": "financial_statement",
            "eps_forward": 75.0, "growth_used": 0.25,
            "fair_value": {"bear": 2050.0, "base": 2380.0, "bull": 2720.0},
            "multiples": {"bear": 25.0, "base": 30.0, "bull": 35.0},
            "current_multiple": 32.8, "current_percentile": 0.96,
            "disclosure": "…",
        }
        flags = {"fundamental": True, "technical": True, "chips": True, "eps_statement": True}
        dec = build_decision(
            price=2420.0, lights=["amber", "amber", "red"], per_percentile=0.96,
            market_light="red", valuation=valuation, atr=40.0, key_ma=2426.0,
            low20=2325.0, high20=2535.0, ma20=2426.0, avg_vol20=30000.0,
            atr_pct=0.017, atr_median_pct=0.02, data_flags=flags,
            rev_signals={"yoy_negative": False, "below_6m_2months": False},
            chip_signals={"sell_streak_ge3": True, "ratio_gt_15pct": False},
            profile=PROFILE, stock_id="2330")
        self.assertIn(dec["rating"], ["買進", "試單", "續抱", "觀望", "減碼"])
        self.assertIn("total", dec["confidence"])
        self.assertEqual(dec["fair_value"]["base"], 2380.0)
        self.assertIn("core_note", dec["position"])
        self.assertEqual(dec["as_of_price"], 2420.0)
        self.assertIn("disclaimer", dec)


if __name__ == "__main__":
    unittest.main()
```

### Step 2：跑測試，預期 FAIL

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && ./.venv/bin/python -m unittest tests.test_decision_engine -v
```
預期：`ModuleNotFoundError: No module named 'warroom.decision_engine'`。

### Step 3：最小實作

`warroom/decision_engine.py`：

```python
"""決策引擎：rating 五檔＋三時間框架＋進出場/停損＋R/R＋部位金額＋信心 0-100（規格 §3.2）。
全部純規則、可揭露輸入；LLM 不介入產數字。輸出併入 data/<id>.json 的 "decision" 區塊。
"""
from typing import Dict, List, Optional

import pandas as pd

RATINGS = ("買進", "試單", "續抱", "觀望", "減碼")
_L = {"green": 1, "amber": 0, "red": -1, "na": 0}
_ZH = {"green": "偏多", "amber": "中性", "red": "偏空", "na": "缺"}


# ---------- 波動度 ----------
def atr14(price_df, n: int = 14) -> Optional[float]:
    """ATR14（Wilder EWMA）。需 max/min/close 欄；資料 <n+1 列或缺欄 → None。"""
    if price_df is None or len(price_df) < n + 1:
        return None
    df = price_df.sort_values("date").reset_index(drop=True)
    for col in ("max", "min", "close"):
        if col not in df.columns:
            return None
    high = pd.to_numeric(df["max"], errors="coerce")
    low = pd.to_numeric(df["min"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")
    prev = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev).abs(), (low - prev).abs()],
                   axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    return round(float(atr), 2) if pd.notna(atr) else None


def atr_percent_median(price_df, window: int = 240) -> Optional[float]:
    """近 1 年日振幅/收盤 的中位（波動 proxy，用來判斷「波動低於自身中位」）。"""
    if price_df is None or len(price_df) < 20:
        return None
    df = price_df.sort_values("date").reset_index(drop=True).tail(window)
    for col in ("max", "min", "close"):
        if col not in df.columns:
            return None
    high = pd.to_numeric(df["max"], errors="coerce")
    low = pd.to_numeric(df["min"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce").replace(0, pd.NA)
    rng = (high - low) / close
    m = rng.median()
    return round(float(m), 4) if pd.notna(m) else None


# ---------- rating 合成 ----------
def light_consistency_score(lights: List[str]) -> int:
    """三燈一致性 0-30：全同非中性 30；兩同非中性 22；一非中性 18；全中性 15；綠紅衝突 0。"""
    valid = [l for l in lights if l in ("green", "amber", "red")]
    if not valid:
        return 0
    if "green" in valid and "red" in valid:
        return 0
    if len(set(valid)) == 1 and valid[0] != "amber":
        return 30
    non_amber = [l for l in valid if l != "amber"]
    if non_amber:
        return 22 if len(non_amber) == 2 else 18
    return 15


def composite_score(f_light, t_light, c_light, per_percentile, market_light) -> float:
    """三燈加權（基本 0.4/技術 0.3/籌碼 0.3）＋估值分位調整＋大盤調整。"""
    base = 0.4 * _L[f_light] + 0.3 * _L[t_light] + 0.3 * _L[c_light]
    val_adj = 0.0
    if per_percentile is not None:
        if per_percentile > 0.85:
            val_adj = -0.2
        elif per_percentile < 0.35:
            val_adj = 0.1
    mkt_adj = 0.1 if market_light == "green" else -0.2 if market_light == "red" else 0.0
    return round(base + val_adj + mkt_adj, 3)


def rating(f_light, t_light, c_light, per_percentile, market_light, rr) -> str:
    """五檔 rating。R/R<1.5 一律不給「買進」（會退成續抱）。綠紅衝突 → 觀望。"""
    lights = [f_light, t_light, c_light]
    if "green" in lights and "red" in lights:
        return "觀望"
    score = composite_score(f_light, t_light, c_light, per_percentile, market_light)
    can_buy = rr is not None and rr >= 1.5
    if score >= 0.5 and can_buy:
        return "買進"
    if score >= 0.2 and can_buy:
        return "試單"
    if score <= -0.4:
        return "減碼"
    if score <= -0.15:
        return "觀望"
    return "續抱"


# ---------- 停損 / R/R ----------
def stop_reference(price, atr, key_ma, low20, min_pct=-0.15, max_pct=-0.08) -> Dict:
    """停損參考 = max(entry-2×ATR, 關鍵均線, 近20日低)，夾在現價 -8%~-15%。
    max_pct=-0.08（最淺）、min_pct=-0.15（最深）。"""
    cands = []
    if atr is not None:
        cands.append(("ATR", price - 2 * atr))
    if key_ma is not None:
        cands.append(("關鍵均線", key_ma))
    if low20 is not None:
        cands.append(("近20日低", low20))
    below = [(name, v) for name, v in cands if v is not None and v < price]
    if below:
        basis, raw = max(below, key=lambda x: x[1])  # 最靠近現價下方的防守
    else:
        basis, raw = "區間下限", price * (1 + max_pct)
    lo = price * (1 + min_pct)
    hi = price * (1 + max_pct)
    stop = min(max(raw, lo), hi)
    clamped = not (lo <= raw <= hi)
    return {"price": round(stop, 1), "pct": round(stop / price - 1, 4), "basis": basis,
            "clamped": clamped, "note": "參考防守位，接回自行判斷"}


def risk_reward(base_fair, price, stop_price) -> Optional[float]:
    """R/R = (base 合理價 − 現價) ÷ (現價 − 停損)。分母<=0 或缺值 → None。"""
    if base_fair is None or stop_price is None:
        return None
    downside = price - stop_price
    if downside <= 0:
        return None
    return round((base_fair - price) / downside, 2)


# ---------- 信心 0-100 ----------
def confidence_score(data_flags: Dict, lights, rr, market_light) -> Dict:
    """完整度 30 + 一致性 30 + R/R 20 + regime 20。"""
    present = sum(1 for k in ("fundamental", "technical", "chips", "eps_statement")
                  if data_flags.get(k))
    completeness = round(30 * present / 4)
    consistency = light_consistency_score(lights)
    if rr is None:
        rr_score = 0
    elif rr >= 3:
        rr_score = 20
    elif rr >= 2.5:
        rr_score = 16
    elif rr >= 2:
        rr_score = 12
    elif rr >= 1.5:
        rr_score = 8
    else:
        rr_score = 0
    regime = 20 if market_light == "green" else 10 if market_light == "amber" else 0
    total = max(0, min(100, completeness + consistency + rr_score + regime))
    return {"total": total, "completeness": completeness, "consistency": consistency,
            "rr": rr_score, "regime": regime}


# ---------- 部位金額 ----------
def position_sizing(rr, confidence, lights, market_light, atr_pct, atr_median_pct,
                    data_incomplete, profile, price, stock_id) -> Dict:
    """金額制部位（規格 §3.2）。ladder 由高到低取第一個達標檔位（門檻皆為最低要求，較高檔位更嚴）。"""
    tiers = {t["name"]: t["amount"] for t in profile["position_tiers"]}
    conflict = ("green" in lights and "red" in lights)
    three_aligned = (len([l for l in lights if l in ("green", "amber", "red")]) == 3
                     and len(set(lights)) == 1 and lights[0] != "amber")
    low_vol = (atr_pct is not None and atr_median_pct is not None and atr_pct < atr_median_pct)
    if rr is None or rr < 1.5 or data_incomplete or conflict or market_light == "red":
        name, reason = "空手", "R/R<1.5／資料不足／訊號分歧／大盤紅燈 其一（保守）"
    elif rr > 3 and confidence > 80 and three_aligned and low_vol:
        name, reason = "極高信心", "R/R>3 且信心>80 且三燈一致且波動低於自身中位"
    elif rr > 2.5 and confidence > 75:
        name, reason = "加碼", "R/R>2.5 且信心>75"
    elif rr > 2 and confidence >= 65:
        name, reason = "標準", "R/R>2 且信心≥65 且大盤非紅燈"
    elif rr >= 1.5 and confidence >= 50:
        name, reason = "試單", "R/R 1.5-2 且信心 50-65"
    else:
        name, reason = "空手", "未達任一部位檔位門檻（保守）"
    amount = tiers[name]
    odd_lot = amount > 0 and price * 1000 > amount
    shares = int(amount // price) if amount > 0 and price > 0 else 0
    core_note = ""
    if stock_id in profile.get("core_holdings", []):
        core_note = "此為核心持股，本建議僅供波段加減碼層判斷，不影響定期定額核心部位"
    return {"tier": name, "amount": amount, "odd_lot": odd_lot, "shares": shares,
            "reason": reason, "core_note": core_note}


# ---------- 進場條件 ----------
def entry_conditions(price, atr, low20, high20, ma20, avg_vol20) -> Dict:
    """回測型（支撐±0.5×ATR＋隔日收盤站回）／突破型（破近20日高＋量>1.3×20日均量）。"""
    pullback = "資料不足，暫不列回測型進場"
    if atr is not None and (ma20 is not None or low20 is not None):
        support = ma20 if ma20 is not None else low20
        band = 0.5 * atr
        pullback = (f"回測型：回檔至支撐 {support:.1f}±{band:.1f}（0.5×ATR）、"
                    f"隔日收盤站回不破再進")
    breakout = "資料不足，暫不列突破型進場"
    if high20 is not None and avg_vol20 is not None:
        breakout = (f"突破型：收盤帶量突破近20日高 {high20:.1f}、"
                    f"且量>1.3×20日均量（約 {1.3 * avg_vol20:,.0f}）")
    return {"pullback": pullback, "breakout": breakout}


# ---------- 三時間框架 ----------
def _rating_stance(r):
    return {"買進": "偏多", "試單": "偏多", "續抱": "中性偏多",
            "觀望": "中性", "減碼": "偏空"}.get(r, "中性")


def time_frames(lights, rating_main, fair_value, tech_ev, valuation) -> Dict:
    """短線（技術+籌碼）／波段（主 rating）／中期（基本面+估值）。"""
    f_light, t_light, c_light = lights

    def stance(s):
        return "偏多" if s > 0.2 else "偏空" if s < -0.2 else "中性"

    short_s = 0.6 * _L[t_light] + 0.4 * _L[c_light]
    pctile = valuation.get("current_percentile")
    val_bias = 0 if pctile is None else (-1 if pctile > 0.75 else 1)
    mid_s = 0.6 * _L[f_light] + 0.4 * val_bias
    ma20 = tech_ev.get("MA20")
    base = fair_value.get("base") if fair_value else None
    bull = fair_value.get("bull") if fair_value else None
    return {
        "short": {"label": "短線 1-4 週", "stance": stance(short_s),
                  "basis": f"技術{_ZH[t_light]}＋籌碼{_ZH[c_light]}為主",
                  "ref_price": (f"參考 MA20 {ma20}" if ma20 is not None else "—")},
        "swing": {"label": "波段 1-3 月（主）", "stance": _rating_stance(rating_main),
                  "basis": f"綜合三燈與估值：{rating_main}",
                  "ref_price": (f"合理價 Base {base}" if base is not None else "—")},
        "mid": {"label": "中期 3-12 月", "stance": stance(mid_s),
                "basis": f"基本面{_ZH[f_light]}＋估值分位",
                "ref_price": (f"樂觀目標 Bull {bull}" if bull is not None else "—")},
    }


# ---------- 失效條件三層 ----------
def invalidation(stop_price, rev_signals, chip_signals) -> Dict:
    """價格（防守位）／基本面（營收 YoY 轉負且連 2 月低於 6 月均）／籌碼（法人連3日同向賣且佔20日均量>15%）。"""
    fund_hit = bool(rev_signals.get("yoy_negative") and rev_signals.get("below_6m_2months"))
    chip_hit = bool(chip_signals.get("sell_streak_ge3") and chip_signals.get("ratio_gt_15pct"))
    return {
        "price": f"價格：跌破參考防守位 {stop_price} 且未快速收回",
        "fundamental": "基本面：最新營收 YoY 轉負且連 2 月低於 6 月均"
                       + ("（已觸發）" if fund_hit else "（未觸發）"),
        "chips": "籌碼：法人連 3 日同向賣且賣超佔 20 日均量>15%"
                 + ("（已觸發）" if chip_hit else "（未觸發）"),
        "any_triggered": fund_hit or chip_hit,
    }


# ---------- 組裝 ----------
def build_decision(price, lights, per_percentile, market_light, valuation,
                   atr, key_ma, low20, high20, ma20, avg_vol20,
                   atr_pct, atr_median_pct, data_flags, rev_signals, chip_signals,
                   profile, stock_id) -> Dict:
    """把所有純片段組裝成 data/<id>.json 的 "decision" 區塊（見計畫 §介面契約）。"""
    fv = valuation.get("fair_value")
    base_fair = fv.get("base") if fv else None
    stop = stop_reference(price, atr, key_ma, low20)
    rr = risk_reward(base_fair, price, stop["price"])
    conf = confidence_score(data_flags, lights, rr, market_light)
    rate = rating(lights[0], lights[1], lights[2], per_percentile, market_light, rr)
    data_incomplete = sum(1 for k in ("fundamental", "technical", "chips")
                          if data_flags.get(k)) < 3
    pos = position_sizing(rr, conf["total"], lights, market_light, atr_pct, atr_median_pct,
                          data_incomplete, profile, price, stock_id)
    entries = entry_conditions(price, atr, low20, high20, ma20, avg_vol20)
    frames = time_frames(lights, rate, fv or {}, {"MA20": ma20}, valuation)
    inval = invalidation(stop["price"], rev_signals, chip_signals)
    return {
        "rating": rate,
        "fair_value": fv,
        "valuation": {k: valuation.get(k) for k in
                      ("path", "eps_ttm", "eps_source", "eps_forward", "growth_used",
                       "multiples", "current_multiple", "current_percentile", "disclosure")},
        "risk_reward": rr,
        "stop": stop,
        "entry": entries,
        "position": pos,
        "confidence": conf,
        "time_frames": frames,
        "invalidation": inval,
        "as_of_price": round(price, 1),
        "disclaimer": "本區塊為規則引擎輸出之決策輔助，非投資建議；"
                      "數字依固定規則計算，最終決策與風險由使用者承擔。",
    }
```

### Step 4：跑測試，預期 PASS

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && ./.venv/bin/python -m unittest tests.test_decision_engine -v
```
預期：`Ran 18 tests ... OK`。

### Step 5：git commit

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && \
git add warroom/decision_engine.py tests/test_decision_engine.py && \
git commit -m "T4: decision_engine.py 決策合成（rating/R/R/停損/部位/信心/框架/失效）

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## T5（群 D）缺資料降級改造 analyze_tw.py + 併入 decision

### Files
- **Modify**：`warroom/analyze_tw.py`
- **Test**：`tests/test_analyze_degrade.py`

本 Task 改造 `analyze_tw.py`：(1) 任一資料源空表不再整檔失敗，改標「資料缺」＋輸出 `data_flags`；(2) MA120 需 ≥120 根否則標「樣本不足」不進燈號；(3) 抓取改用 T2 `cached_fetch`；(4) 併入 T3/T4，輸出 `decision` 區塊。抽出兩個純函式 `rev_signals_from_df` / `chip_signals_from_df` 供失效條件與測試使用。

### Interfaces
- Produces：
  - `analyze(stock_id, with_news=True) -> Dict` — 既有回傳新增 `"data_flags": Dict` 與 `"decision": Dict`（估值/大盤資料齊時；不齊時 `decision` 仍輸出但相關欄位為 None/降級）。
  - `rev_signals_from_df(rev_df) -> Dict` — 回 `{"yoy_negative": bool, "below_6m_2months": bool}`。
  - `chip_signals_from_df(chip_df) -> Dict` — 回 `{"sell_streak_ge3": bool, "ratio_gt_15pct": bool}`。
- Consumes：T1 `load_profile`、T2 `cached_fetch`/`get_loader`、T3 `compute_valuation`、T4 `build_decision`、`warroom.market.fetch_market`。

### Step 1：寫失敗測試

`tests/test_analyze_degrade.py`：

```python
"""T5：缺資料降級 + 純訊號抽取函式測試（純函式，不打真 API）。"""
import unittest

import pandas as pd

from warroom.analyze_tw import (
    technical, rev_signals_from_df, chip_signals_from_df,
)


def price_df(n):
    rows = []
    for i in range(n):
        c = 100.0 + (i % 5)
        rows.append({"date": f"2026-{(i // 28) % 12 + 1:02d}-{(i % 28) + 1:02d}",
                     "close": c, "max": c + 1, "min": c - 1, "Trading_Volume": 1000})
    return pd.DataFrame(rows)


class TestDegrade(unittest.TestCase):
    def test_technical_ma120_insufficient(self):
        # 只有 30 根 → MA120 應標「樣本不足」、不因此進空頭
        light, ev = technical(price_df(30))
        self.assertEqual(ev["MA120"], "樣本不足")

    def test_technical_full_sample(self):
        light, ev = technical(price_df(150))
        self.assertIsInstance(ev["MA120"], (int, float))

    def test_rev_signals(self):
        # 去年每月 100、今年前 4 月 90（YoY 負），且低於 6 月均
        months = [(2025, m, 100) for m in range(1, 13)] + \
                 [(2026, m, 90) for m in range(1, 5)]
        rev = pd.DataFrame([{"date": f"{y}-{m:02d}-01", "revenue": r,
                             "revenue_year": y, "revenue_month": m}
                            for (y, m, r) in months])
        sig = rev_signals_from_df(rev)
        self.assertTrue(sig["yoy_negative"])

    def test_chip_signals_sell_streak(self):
        # 連 3 日淨賣（buy<sell）
        rows = []
        for d in ("2026-07-10", "2026-07-11", "2026-07-14"):
            rows.append({"date": d, "buy": 100, "sell": 5000, "name": "Foreign_Investor"})
        chip = pd.DataFrame(rows)
        sig = chip_signals_from_df(chip)
        self.assertTrue(sig["sell_streak_ge3"])

    def test_signals_empty_safe(self):
        # 空表不 crash，回 False
        self.assertEqual(rev_signals_from_df(None)["yoy_negative"], False)
        self.assertEqual(chip_signals_from_df(pd.DataFrame())["sell_streak_ge3"], False)


if __name__ == "__main__":
    unittest.main()
```

### Step 2：跑測試，預期 FAIL

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && ./.venv/bin/python -m unittest tests.test_analyze_degrade -v
```
預期：`ImportError: cannot import name 'rev_signals_from_df' from 'warroom.analyze_tw'`（`technical` 已存在，但 `rev_signals_from_df`/`chip_signals_from_df` 尚未定義）。

### Step 3：最小實作（改 `warroom/analyze_tw.py`）

**(3a)** 更新檔首 import 與常數。將檔案最上方：

```python
from FinMind.data import DataLoader
import pandas as pd
from warroom.news import fetch_news

LIGHT_SCORE = {"green": 1, "amber": 0, "red": -1}
```

改為：

```python
import pandas as pd
from warroom.news import fetch_news
from warroom.finmind_cache import get_loader, cached_fetch
from warroom.profile import load_profile
from warroom.valuation import compute_valuation
from warroom.decision_engine import (
    atr14, atr_percent_median, build_decision,
)

LIGHT_SCORE = {"green": 1, "amber": 0, "red": -1, "na": 0}
```

**(3b)** `stock_name()` 內 `DataLoader().taiwan_stock_info()` 改為 `get_loader().taiwan_stock_info()`。同時新增取產業別的 helper（放在 `stock_name` 之後）：

```python
def stock_industry(stock_id):
    """個股產業別（去重取第一筆；判斷金融/循環股走 PBR 路徑用）。"""
    global _INFO_CACHE
    try:
        if _INFO_CACHE is None:
            _INFO_CACHE = get_loader().taiwan_stock_info()
        row = _INFO_CACHE[_INFO_CACHE["stock_id"] == stock_id].drop_duplicates("stock_id")
        return row.iloc[0]["industry_category"] if len(row) else None
    except Exception:
        return None
```

**(3c)** 把 `fetch()` 整個換成（改用快取、逐源容錯、多抓財報/PBR）：

```python
def fetch(stock_id):
    """抓個股所需各資料源。任一源失敗回 None（該維度後續標「資料缺」）。"""
    out = {}
    sources = [
        ("price", "taiwan_stock_daily", dict(stock_id=stock_id, start_date="2024-01-01")),
        ("rev", "taiwan_stock_month_revenue", dict(stock_id=stock_id, start_date="2023-01-01")),
        ("val", "taiwan_stock_per_pbr", dict(stock_id=stock_id, start_date="2021-01-01")),
        ("chip", "taiwan_stock_institutional_investors", dict(stock_id=stock_id, start_date="2026-04-01")),
        ("fs", "taiwan_stock_financial_statement", dict(stock_id=stock_id, start_date="2024-01-01")),
    ]
    for key, method, kw in sources:
        try:
            df = cached_fetch(method, **kw)
            out[key] = df if (df is not None and len(df) > 0) else None
        except Exception:
            out[key] = None
    return out
```

**(3d)** 改 `technical()` 的 MA 計算段，加最少筆數門檻。將原本：

```python
    df = price.sort_values("date").reset_index(drop=True)
    c = df["close"]
    ma = {n: c.rolling(n).mean().iloc[-1] for n in (5, 20, 60, 120)}
    last = c.iloc[-1]
```

改為：

```python
    df = price.sort_values("date").reset_index(drop=True)
    c = df["close"]
    n_rows = len(c)
    # 最少筆數門檻：不足者標「樣本不足」，不進燈號判斷（規格 §4 backlog ②）
    ma = {n: (c.rolling(n).mean().iloc[-1] if n_rows >= n else None) for n in (5, 20, 60, 120)}
    last = c.iloc[-1]
```

同一函式內，將多空排列判斷：

```python
    bull = last > ma[20] > ma[60] > ma[120]
    bear = last < ma[20] and ma[20] < ma[60]
```

改為（None 安全）：

```python
    bull = (None not in (ma[20], ma[60], ma[120])) and last > ma[20] > ma[60] > ma[120]
    bear = (ma[20] is not None and ma[60] is not None) and last < ma[20] and ma[20] < ma[60]
```

並將回傳 ev 內 MA 值改成 None→「樣本不足」（把原本四個 `round(ma[n],1)` 包一層）。將：

```python
    return light, {
        "收盤": round(last, 1), "MA20": round(ma[20], 1), "MA60": round(ma[60], 1),
        "MA120": round(ma[120], 1), "RSI14": round(r, 0),
```

改為：

```python
    def _ma(v):
        return round(v, 1) if v is not None else "樣本不足"

    return light, {
        "收盤": round(last, 1), "MA20": _ma(ma[20]), "MA60": _ma(ma[60]),
        "MA120": _ma(ma[120]), "RSI14": round(r, 0),
```

> 注意：`technical()` 內用到 `cand` 字典的 `MA20/MA60/MA120` 可能為 None。在建 `cand` 前補一行過濾，將：
> ```python
>     cand = {"MA20": ma[20], "MA60": ma[60], "MA120": ma[120],
>             "近20日高": df[hi_c].tail(20).max(), "近60日高": df[hi_c].tail(60).max(),
>             "近20日低": df[lo_c].tail(20).min()}
> ```
> 改為（None 的均線不放進候選）：
> ```python
>     cand = {k: v for k, v in {
>         "MA20": ma[20], "MA60": ma[60], "MA120": ma[120],
>         "近20日高": df[hi_c].tail(20).max(), "近60日高": df[hi_c].tail(60).max(),
>         "近20日低": df[lo_c].tail(20).min()}.items() if v is not None}
> ```

**(3e)** 新增兩個純訊號函式（放在 `chips()` 之後）：

```python
def rev_signals_from_df(rev_df):
    """失效條件-基本面：最新月營收 YoY 轉負，且最近連 2 月低於近 6 月均。空表安全回 False。"""
    out = {"yoy_negative": False, "below_6m_2months": False}
    if rev_df is None or len(rev_df) == 0:
        return out
    r = rev_df.copy()
    r["revenue"] = pd.to_numeric(r["revenue"], errors="coerce")
    r = r.dropna(subset=["revenue"])
    r["ym"] = r["revenue_year"].astype(int) * 100 + r["revenue_month"].astype(int)
    r = r.sort_values("ym").reset_index(drop=True)
    if len(r) < 8:
        return out
    lookup = {int(row["ym"]): float(row["revenue"]) for _, row in r.iterrows()}
    last = r.iloc[-1]
    py_ym = (int(last["revenue_year"]) - 1) * 100 + int(last["revenue_month"])
    base = lookup.get(py_ym)
    if base and base != 0:
        out["yoy_negative"] = (float(last["revenue"]) / base - 1) < 0
    avg6 = r["revenue"].tail(6).mean()
    out["below_6m_2months"] = bool((r["revenue"].tail(2) < avg6).all())
    return out


def chip_signals_from_df(chip_df):
    """失效條件-籌碼：法人連 3 日同向賣，且賣超佔 20 日均量>15%。空表安全回 False。"""
    out = {"sell_streak_ge3": False, "ratio_gt_15pct": False}
    if chip_df is None or len(chip_df) == 0:
        return out
    df = chip_df.copy()
    df["buy"] = pd.to_numeric(df["buy"], errors="coerce").fillna(0)
    df["sell"] = pd.to_numeric(df["sell"], errors="coerce").fillna(0)
    df["net"] = df["buy"] - df["sell"]
    daily = df.groupby("date")["net"].sum().sort_index()
    if len(daily) == 0:
        return out
    streak = 0
    for v in reversed(daily.tolist()):
        if v < 0:
            streak += 1
        else:
            break
    out["sell_streak_ge3"] = streak >= 3
    return out
```

**(3f)** 把 `analyze()` 整段換成（逐維度降級 + data_flags + 併入 decision）：

```python
def analyze(stock_id, with_news=True):
    d = fetch(stock_id)
    name = stock_name(stock_id)
    flags = {}

    if d.get("rev") is not None and d.get("val") is not None:
        f_light, f_ev = fundamental(d["rev"], d["val"]); flags["fundamental"] = True
    else:
        f_light, f_ev = "na", {"備註": "營收/估值資料缺"}; flags["fundamental"] = False

    if d.get("price") is not None:
        t_light, t_ev = technical(d["price"]); flags["technical"] = True
    else:
        t_light, t_ev = "na", {"備註": "日線資料缺"}; flags["technical"] = False

    if d.get("chip") is not None:
        c_light, c_ev = chips(d["chip"]); flags["chips"] = True
    else:
        c_light, c_ev = "na", {"備註": "法人資料缺"}; flags["chips"] = False

    combo = synthesize(f_light, t_light, c_light)
    news = fetch_news(name, None, 6) if with_news else []
    res = {
        "stock_id": stock_id, "name": name,
        "fundamental": {"light": f_light, "ev": f_ev},
        "technical": {"light": t_light, "ev": t_ev},
        "chips": {"light": c_light, "ev": c_ev},
        "news": news, "summary": combo, "data_flags": flags,
    }
    res["decision"] = _decide(stock_id, d, res, flags)
    return res


def _decide(stock_id, d, res, flags):
    """組估值 + 決策區塊。任何一步缺資料都降級，不讓整檔 fail。"""
    try:
        from warroom.market import fetch_market
        market_light = fetch_market().get("light", "amber")
    except Exception:
        market_light = "amber"

    price_df = d.get("price")
    if price_df is None or len(price_df) == 0:
        return {"rating": "觀望", "fair_value": None, "risk_reward": None,
                "position": {"tier": "空手", "amount": 0, "odd_lot": False, "shares": 0,
                             "reason": "日線資料缺，無法計算", "core_note": ""},
                "confidence": {"total": 0, "completeness": 0, "consistency": 0,
                               "rr": 0, "regime": 0},
                "note": "日線資料缺，決策降級", "as_of_price": None,
                "disclaimer": "資料不足，僅供參考。"}

    pdf = price_df.sort_values("date").reset_index(drop=True)
    price = float(pd.to_numeric(pdf["close"], errors="coerce").iloc[-1])

    # PER/PBR 序列
    per_series, per_current, pbr_series, pbr_current = [], None, [], None
    if d.get("val") is not None:
        v = d["val"].sort_values("date")
        per_series = [float(x) for x in pd.to_numeric(v["PER"], errors="coerce").dropna().tolist()]
        pbr_series = [float(x) for x in pd.to_numeric(v["PBR"], errors="coerce").dropna().tolist()]
        per_current = per_series[-1] if per_series else None
        pbr_current = pbr_series[-1] if pbr_series else None

    valuation = compute_valuation({
        "price": price, "industry_category": stock_industry(stock_id),
        "market_light": market_light, "fs_df": d.get("fs"), "rev_df": d.get("rev"),
        "per_series": per_series, "per_current": per_current,
        "pbr_series": pbr_series, "pbr_current": pbr_current, "roe": None,
    })
    flags["eps_statement"] = (valuation.get("eps_source") == "financial_statement")

    lights = [res["fundamental"]["light"], res["technical"]["light"], res["chips"]["light"]]
    t_ev = res["technical"]["ev"]

    def _num(x):
        return float(x) if isinstance(x, (int, float)) else None

    ma20 = _num(t_ev.get("MA20"))
    hi_c = "max" if "max" in pdf.columns else "close"
    lo_c = "min" if "min" in pdf.columns else "close"
    low20 = float(pd.to_numeric(pdf[lo_c], errors="coerce").tail(20).min())
    high20 = float(pd.to_numeric(pdf[hi_c], errors="coerce").tail(20).max())
    avg_vol20 = float(pd.to_numeric(pdf["Trading_Volume"], errors="coerce").tail(20).mean()) \
        if "Trading_Volume" in pdf.columns else None
    atr = atr14(pdf)
    atr_med = atr_percent_median(pdf)
    atr_pct = (atr / price) if (atr is not None and price) else None
    per_pctile = valuation.get("current_percentile")

    return build_decision(
        price=price, lights=lights, per_percentile=per_pctile, market_light=market_light,
        valuation=valuation, atr=atr, key_ma=ma20, low20=low20, high20=high20,
        ma20=ma20, avg_vol20=avg_vol20, atr_pct=atr_pct, atr_median_pct=atr_med,
        data_flags=flags,
        rev_signals=rev_signals_from_df(d.get("rev")),
        chip_signals=chip_signals_from_df(d.get("chip")),
        profile=load_profile(), stock_id=stock_id)
```

> `_L`/`LIGHT_ZH` 已含 `na`。`synthesize()` 無需改（`LIGHT_SCORE` 已補 `"na":0`，且綠紅衝突判斷不受 na 影響）。`pretty()` 讀 `LIGHT_ZH[block['light']]`，na 已在 `LIGHT_ZH`。

### Step 4：跑測試，預期 PASS

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && \
./.venv/bin/python -m unittest tests.test_analyze_degrade -v && \
./.venv/bin/python -c "import warroom.analyze_tw, warroom.decision_engine, warroom.valuation; print('imports OK')"
```
預期：`Ran 5 tests ... OK` 且印出 `imports OK`（確認整條 import 鏈無語法/循環錯誤）。

> 端到端真 API 抽驗（可選、需網路，非 CI）：`./.venv/bin/python -m warroom.analyze_tw 2330` 應寫出 `data/2330.json` 且含 `decision` 區塊、不 crash。這步驗證缺資料降級與併入 decision 在真實資料上成立。

### Step 5：git commit

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && \
git add warroom/analyze_tw.py tests/test_analyze_degrade.py && \
git commit -m "T5: analyze_tw 缺資料降級 + MA120 樣本門檻 + 併入 decision 區塊

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## T6（群 E）一致性檢查 consistency.py + 接進 build 入口

### Files
- **Create**：`warroom/consistency.py`
- **Modify**：`warroom/build_weekly.py`（`build()` 開頭加檢查）
- **Modify**：`warroom/report_stock.py`（`build()` 開頭加檢查）
- **Test**：`tests/test_consistency.py`

### Interfaces
- Produces：
  - `build_stock_anchors(engine: Dict) -> Dict[str, float]` — 從引擎 JSON 取可比對的錨點數字（MA20/MA60/MA120/收盤 + decision.fair_value 的 Bear/Base/Bull）。
  - `check_numbers(text: str, anchors: Dict[str, float], tol: float = 0.01) -> List[str]` — 敘事內關鍵字後方數字 vs 錨點，差>1% 記 diff。
  - `check_stock_consistency(engine: Dict, narration: Dict) -> List[str]`
  - `check_weekly_consistency(engine_by_id: Dict[str, Dict], weekly: Dict) -> List[str]`
  - `assert_consistent(diffs: List[str], context: str) -> None` — 有 diff 就印到 stderr 並 `sys.exit(1)`；無則印通過。
- Consumes：`build_weekly.build()`、`report_stock.build()` 呼叫上述函式。

### Step 1：寫失敗測試

`tests/test_consistency.py`：

```python
"""T6：一致性檢查 consistency.py 測試。"""
import unittest

from warroom.consistency import (
    build_stock_anchors, check_numbers, check_stock_consistency,
    check_weekly_consistency,
)


def make_engine():
    return {
        "technical": {"ev": {"MA20": 2426.2, "MA60": 2305.5, "MA120": 2076.7,
                             "收盤": 2420.0}},
        "chips": {"ev": {"最新日": "2026-07-14"}},
        "decision": {"fair_value": {"bear": 2050.0, "base": 2380.0, "bull": 2720.0}},
    }


class TestConsistency(unittest.TestCase):
    def test_anchors_built(self):
        a = build_stock_anchors(make_engine())
        self.assertAlmostEqual(a["MA20"], 2426.2)
        self.assertAlmostEqual(a["Base"], 2380.0)

    def test_numbers_match_within_tolerance(self):
        # 敘事寫 MA20 2,426（與 2426.2 差 <1%）→ 無 diff
        diffs = check_numbers("收盤站上 MA20 2,426 保持多頭", build_stock_anchors(make_engine()))
        self.assertEqual(diffs, [])

    def test_numbers_mismatch_flagged(self):
        # 敘事寫錯 Base 2,900（與 2380 差 >1%）→ 有 diff
        diffs = check_numbers("合理價 Base 2,900 元", build_stock_anchors(make_engine()))
        self.assertTrue(any("Base" in d for d in diffs))

    def test_stock_consistency_date_lag(self):
        eng = make_engine()
        narration = {"as_of": "2026-07-10（台北）", "roles": {"chief": "維持觀望"}}
        diffs = check_stock_consistency(eng, narration)
        self.assertTrue(any("日期落後" in d for d in diffs))

    def test_stock_consistency_clean(self):
        eng = make_engine()
        narration = {"as_of": "2026-07-14（台北）",
                     "roles": {"technical": "收盤 2,420 站上 MA20 2,426"}}
        diffs = check_stock_consistency(eng, narration)
        self.assertEqual(diffs, [])

    def test_weekly_consistency(self):
        engines = {"2330": make_engine()}
        weekly = {"stocks": {"2330": "體質仍強，但合理價 Base 2,900 偏高"}}  # 錯 Base
        diffs = check_weekly_consistency(engines, weekly)
        self.assertTrue(any("2330" in d for d in diffs))


if __name__ == "__main__":
    unittest.main()
```

### Step 2：跑測試，預期 FAIL

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && ./.venv/bin/python -m unittest tests.test_consistency -v
```
預期：`ModuleNotFoundError: No module named 'warroom.consistency'`。

### Step 3：最小實作

`warroom/consistency.py`：

```python
"""一致性檢查：narration（Claude 手寫敘事）數字/日期 vs 引擎 JSON（規格 §4）。
關鍵字後方數字差>1%、或敘事 as_of 日期早於引擎最新資料日 → 記 diff。
build 前呼叫 assert_consistent，有 diff 就中止（非零 exit）並印 diff，禁止舊敘事上線。
"""
import re
import sys
from typing import Dict, List, Optional

_NUM = re.compile(r"-?\d[\d,]*\.?\d*")
_DATE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")


def _to_float(tok: str) -> Optional[float]:
    try:
        return float(tok.replace(",", ""))
    except ValueError:
        return None


def _numbers_after(text: str, keyword: str, window: int = 12) -> List[float]:
    """關鍵字後方 window 字內的第一個數字（可能多處出現，逐一取）。"""
    out = []
    for m in re.finditer(re.escape(keyword), text):
        seg = text[m.end(): m.end() + window]
        nm = _NUM.search(seg)
        if nm:
            v = _to_float(nm.group())
            if v is not None:
                out.append(v)
    return out


def _parse_date(text: str):
    m = _DATE.search(text or "")
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def build_stock_anchors(engine: Dict) -> Dict[str, float]:
    """從引擎 JSON 取可比對的錨點數字。"""
    a = {}
    t = engine.get("technical", {}).get("ev", {})
    for k in ("MA20", "MA60", "MA120", "收盤"):
        if isinstance(t.get(k), (int, float)):
            a[k] = float(t[k])
    dec = engine.get("decision", {}) or {}
    fv = dec.get("fair_value")
    if fv:
        for k, label in (("bear", "Bear"), ("base", "Base"), ("bull", "Bull")):
            if isinstance(fv.get(k), (int, float)):
                a[label] = float(fv[k])
    return a


def check_numbers(text: str, anchors: Dict[str, float], tol: float = 0.01) -> List[str]:
    """關鍵字後方數字 vs 錨點，相對差>tol 記 diff。錨點在敘事沒出現則跳過（不強制提及）。"""
    diffs = []
    for kw, truth in anchors.items():
        if truth == 0:
            continue
        for got in _numbers_after(text, kw):
            if abs(got - truth) / abs(truth) > tol:
                diffs.append(f"[數字不符] 敘事「{kw} {got}」≠ 引擎 {truth}"
                             f"（差 {abs(got - truth) / abs(truth) * 100:.1f}%）")
    return diffs


def _iter_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_strings(v)


def _latest_engine_date(engine: Dict):
    c = engine.get("chips", {}).get("ev", {}).get("最新日")
    return _parse_date(str(c)) if c else None


def check_stock_consistency(engine: Dict, narration: Dict) -> List[str]:
    """單檔：數字錨點 + as_of 日期不得早於引擎最新資料日。"""
    diffs = []
    text = " ".join(_iter_strings(narration))
    diffs += check_numbers(text, build_stock_anchors(engine))
    nd = _parse_date(narration.get("as_of", ""))
    ed = _latest_engine_date(engine)
    if nd and ed and nd < ed:
        diffs.append(f"[日期落後] 敘事 as_of {nd} 早於引擎最新資料日 {ed}")
    return diffs


def check_weekly_consistency(engine_by_id: Dict[str, Dict], weekly: Dict) -> List[str]:
    """週報：每檔個股一句 vs 該檔引擎錨點。"""
    diffs = []
    for sid, text in (weekly.get("stocks", {}) or {}).items():
        eng = engine_by_id.get(sid)
        if not eng:
            continue
        diffs += [f"({sid}) " + d for d in check_numbers(str(text), build_stock_anchors(eng))]
    return diffs


def assert_consistent(diffs: List[str], context: str) -> None:
    """有 diff → 印 stderr 並 sys.exit(1)（build 中止）；無 → 印通過。"""
    if diffs:
        print(f"✗ 一致性檢查失敗（{context}）：", file=sys.stderr)
        for d in diffs:
            print("  - " + d, file=sys.stderr)
        sys.exit(1)
    print(f"✓ 一致性檢查通過（{context}）")
```

**接進 `warroom/report_stock.py`**：在 `build()` 讀完 `d` 與 `n` 之後、組 HTML 之前插入檢查。將：

```python
def build(stock_id):
    with open(f"data/{stock_id}.json", encoding="utf-8") as f:
        d = json.load(f)
    with open(f"data/{stock_id}.narration.json", encoding="utf-8") as f:
        n = json.load(f)
```

改為：

```python
def build(stock_id):
    with open(f"data/{stock_id}.json", encoding="utf-8") as f:
        d = json.load(f)
    with open(f"data/{stock_id}.narration.json", encoding="utf-8") as f:
        n = json.load(f)
    from warroom.consistency import check_stock_consistency, assert_consistent
    assert_consistent(check_stock_consistency(d, n), f"個股報告 {stock_id}")
```

**接進 `warroom/build_weekly.py`**：在 `build()` 內讀完 `stocks` 與 `n` 之後插入檢查。將：

```python
    stocks = {}
    for sid in n["stocks"]:
        p = f"data/{sid}.json"
        if os.path.exists(p):
            stocks[sid] = json.load(open(p, encoding="utf-8"))
```

改為（其後加兩行）：

```python
    stocks = {}
    for sid in n["stocks"]:
        p = f"data/{sid}.json"
        if os.path.exists(p):
            stocks[sid] = json.load(open(p, encoding="utf-8"))
    from warroom.consistency import check_weekly_consistency, assert_consistent
    assert_consistent(check_weekly_consistency(stocks, n), "週報")
```

### Step 4：跑測試，預期 PASS + 故意改壞驗證會 fail

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && ./.venv/bin/python -m unittest tests.test_consistency -v
```
預期：`Ran 6 tests ... OK`。

再用「故意改壞的 narration」驗證 build 真的會非零 exit（規格 §5 要求）：

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && ./.venv/bin/python -c "
import sys
from warroom.consistency import check_stock_consistency, assert_consistent
engine = {'technical': {'ev': {'MA20': 2426.2, '收盤': 2420.0}},
          'chips': {'ev': {'最新日': '2026-07-14'}},
          'decision': {'fair_value': {'bear': 2050.0, 'base': 2380.0, 'bull': 2720.0}}}
bad = {'as_of': '2026-07-14', 'roles': {'x': '合理價 Base 9,999 元'}}
try:
    assert_consistent(check_stock_consistency(engine, bad), 'demo')
    print('NG: 應該要 fail 卻通過'); sys.exit(2)
except SystemExit as e:
    print('OK: 故意改壞如預期非零 exit，code =', e.code)
"
```
預期：印出 `✗ 一致性檢查失敗` 的 diff，最後 `OK: 故意改壞如預期非零 exit，code = 1`。

### Step 5：git commit

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && \
git add warroom/consistency.py warroom/report_stock.py warroom/build_weekly.py tests/test_consistency.py && \
git commit -m "T6: consistency.py 敘事vs引擎一致性檢查 + 接進 build 入口

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## 全案收尾驗證（所有 Task 完成後）

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && ./.venv/bin/python -m unittest discover -s tests -v
```
預期全部通過（6 個測試檔）。再跑一次真 API 端到端（需網路）確認引擎在真實資料上輸出 `decision` 且不 crash：

```bash
cd /Users/andyc/Desktop/agent/advisor-war-room && \
for s in 2330 2454 2882 8299; do ./.venv/bin/python -m warroom.analyze_tw $s && \
  ./.venv/bin/python -c "import json;d=json.load(open('data/$s.json'));print('$s', d['decision']['rating'], d['decision']['position']['amount'], d['decision']['confidence']['total'])"; done
```
（2882 走 PBR 路徑、8299 上櫃/中小型走稀疏路徑，對應規格 §0 成功標準 5 的四檔實測。）

---

## 規格需求 → Task 對照（自我檢查）

| 規格條目 | 對應 Task |
|---|---|
| §0 成功標準 1（決策卡數字：rating/三框架/Bear-Base-Bull/R-R/部位金額含零股/信心 0-100） | T4（引擎產出）；渲染另計畫 |
| §0 標準 2（每個新數字可追溯 EPS/PER 分位/ATR） | T3 disclosure、T4 valuation 揭露＋stop.basis |
| §0 標準 3（narration 不一致 build fail） | T6 |
| §0 標準 4（FinMind 額度：token 或快取） | T2 |
| §0 標準 5（四檔實測含金融 PBR、中小稀疏） | 收尾驗證 + T3 PBR 路徑 + T5 降級 |
| §1 三時間框架 / 停損 -8~-15% / 部位金額檔位 / core_holdings | T1（落檔）＋ T4（用參數） |
| §3.1 TTM EPS 財報優先＋反推降信心 / Forward EPS clamp / Bear-Base-Bull PER 分位 / 紅燈下修 / 金融 PBR / 揭露 | T3 |
| §3.2 rating 五檔 / R/R<1.5 禁買 / 停損夾區間 / 進場兩型 / 部位金額含零股+核心註記 / 信心 30+30+20+20 / 三框架 / 失效三層 | T4 |
| §4 缺資料降級（空表不整檔 fail）/ MA120 樣本門檻 / FinMind token+快取 / 一致性 fail 中止 | T5（降級+門檻）、T2（token+快取）、T6（一致性） |

型別/函式名跨 Task 一致：`data_flags` dict（T5 產、T4 `confidence_score`/`build_decision` 用）；`valuation` dict（T3 產、T4 `build_decision` 用，欄位對齊 §介面契約）；`profile` dict（T1 產、T4 `position_sizing` 用 `position_tiers`/`core_holdings`）；`fair_value.base` 為 R/R 分子（T3→T4）。無 TBD/TODO/佔位符。
