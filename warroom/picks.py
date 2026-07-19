"""B 包・主動選股引擎（候選池 → 三準則評分 → 風控閘門 → 操作卡）。

設計原則（Codex 顧問版）：候選池→三準則評分→風控閘門→操作卡；誠實不明牌。
契約：docs/contracts/data-contract-v1.md v1.5 的 `daily.picks`（schema/daily.schema.json 的 pick / picks 定義）。

流程分兩層（與 build_snapshots 同款「純函式 vs main() 打網路」）：
- 打網路的組裝（fetch opportunities、FinMind 抓輕量資料、跑被選檔 analyze）集中在 generate_picks()。
- 評分／閘門／選檔／操作卡全是純函式，吃 metrics dict，方便測試構造資料抽驗公式。

額度紀律（規格）：整批候選 ≤35 檔、每檔輕量評分 ≤3 個 dataset（日線／月營收／PER），
全走 finmind_cache.cached_fetch 同日快取。tracked 個股與被選檔的 analyze() 已用相同參數抓過，
scoring 這裡命中快取＝0 次新呼叫。被選新股才另跑完整 analyze()（上限 6 檔）產 stocks/<id>.json。

============================ 三準則評分公式（寫死、可揭露）============================

每個框架分數 0-100，加法累計後 clamp [0,100]。metrics 缺值時該項給 0（不編數字）。

短線 short_score（動能 + 量 + 籌碼轉向）：
  + 20 日動能：clamp(ret20, 0, 12) / 12 * 30      （ret20＝近 20 交易日報酬%；RS20）
  + 站回 MA20（close > ma20）：              +20
  + 帶量突破 20 日高（close ≥ high20 且 vol_ratio > 1.3）：+25
  + 法人近 3 日轉買（chip_turn_buy）：       +25
  - 追高扣分（距 20 日高 < 2% 且尚未突破）： -10
  - 事件 7 天內（earnings_within7）：        -15
  → 取分 ≥70、最高 1 檔。

波段 swing_score（均線結構 + RS + 法人連續 + R/R≥1.8 + 營收）：
  + 均線結構：close>ma20 +10、ma20>ma60 +10、ma60>ma120 +10（多頭排列最高 30）
  + 60 日 RS：clamp(ret60, 0, 20) / 20 * 20     （ret60＝近 60 交易日報酬%）
  + 法人連續同向買（chip_buy_streak_ge3）：  +15
  + R/R：rr≥1.8 → +20；1.8>rr≥1.0 → 線性 (rr-1)/0.8*20；rr<1 → 0
  + 營收 YoY 為正（revenue_yoy>0）：          +15
  → 取分 ≥65、前 3 檔。

長線 long_score（營收動能 + 估值分位 + 殖利率 + 風險扣分；不含 EPS/ROE——本引擎未抓財報三表，
  勿與 warroom/valuation.py 的估值模型或 warroom/fundamentals.py 的財報品質分混為一談）：
  + 營收 YoY 為正：             +15
  + 近 3 月均 YoY 為正：        +15；且 avg3_yoy 幅度 clamp(avg3,0,20)/20*10 額外最高 +10
  + PER 歷史分位 <50%：clamp(0.5-per_pctile,0,0.5)/0.5*20（越低越加分，最高 +20）
  + PBR 歷史分位 <50%：clamp(0.5-pbr_pctile,0,0.5)/0.5*10（最高 +10）
  + 殖利率：≥4% +15、≥2.5% +10、>0 +5
  - 每個 risk_flag：           -10
  → 取分 ≥60、前 5 檔。

confidence（信心度）＝ round(score*0.7 + 10)，clamp [0, 80]
  （對照契約範例：score 78 → confidence 65）。

選檔去重：一檔只出現在它「有達標的框架中分數最高」那一個（同股不跨框架重複）。
核心持股（profile.core_holdings，如 2330/0050）永不進 picks（已持有）。

風控閘門（gate＝daily.exposure_guidance.new_position）：
  禁止新增部位 → short/swing 清空；long 仍列但操作卡改「等大盤解禁再佈局」語言。
  僅限試單     → 三框架照列，每檔 action_summary 註明「試單上限 10 萬」。
  可正常布局   → 正常。
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Dict, List, Optional, Tuple

import pandas as pd

OPPORTUNITIES_URL = ("https://andy30019123agent-ship-it.github.io/"
                     "tw-stock-screener/data/opportunities.json")
UNIVERSE_PATH = "data/universe.json"
LOCAL_OPPORTUNITIES_PATH = "data/opportunities.json"  # 線上掛掉時的中間 fallback（可有可無）
POOL_CAP = 35  # 整批候選上限（額度紀律）
MAX_NEW_ANALYZE = 6  # 被選新股跑完整 analyze 上限

# analyze_tw.fetch 的抓取參數（刻意對齊，讓輕量評分命中同一份同日快取＝0 次新呼叫）
_DAILY_KW = dict(stock_id=None, start_date="2024-01-01")
_REV_KW = dict(stock_id=None, start_date="2023-01-01")
_VAL_KW = dict(stock_id=None, start_date="2021-01-01")

_CHIP_BUY_KEYWORDS = ("投信連買", "外資連買", "投信買超", "外資買超",
                      "連買", "買超", "千張大戶↑", "大戶↑")


# ======================= 候選池 =======================
def load_universe(path: str = UNIVERSE_PATH) -> List[Dict]:
    """讀人工維護的 universe 種子清單（id+name）。缺檔/壞檔 → 回 []（不炸）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return list(json.load(f).get("stocks") or [])
    except Exception:
        return []


def fetch_opportunities(url: str = OPPORTUNITIES_URL,
                        local_path: str = LOCAL_OPPORTUNITIES_PATH,
                        timeout: int = 20) -> Tuple[List[Dict], str]:
    """抓線上 opportunities.json。fallback 鏈：線上 → 本地檔 → 空。
    回 (picks_list, source_tag)；source_tag ∈ {"online", "local", "none"}。"""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        picks = data.get("picks")
        if isinstance(picks, list):
            return picks, "online"
    except Exception:
        pass
    try:
        with open(local_path, encoding="utf-8") as f:
            picks = json.load(f).get("picks")
        if isinstance(picks, list):
            return picks, "local"
    except Exception:
        pass
    return [], "none"


def build_candidate_pool(opportunities: List[Dict], universe: List[Dict],
                         tracked_ids: List[str], core_ids: List[str],
                         cap: int = POOL_CAP) -> List[Dict]:
    """合併去重成候選池。優先序：opportunities（最新訊號）> tracked > universe，
    去重後截到 cap。核心持股（已持有）直接排除。
    回 [{"id","name","opp": <opportunity dict or None>}...]。"""
    core = set(core_ids)
    seen, pool = set(), []

    def _add(sid: str, name: str, opp: Optional[Dict]):
        if not sid or sid in seen or sid in core or len(pool) >= cap:
            return
        seen.add(sid)
        pool.append({"id": sid, "name": name or sid, "opp": opp})

    for o in opportunities:
        _add(str(o.get("id") or ""), o.get("name") or "", o)
    for sid in tracked_ids:
        _add(str(sid), "", None)
    for u in universe:
        _add(str(u.get("id") or ""), u.get("name") or "", None)
    return pool


# ======================= 指標抽取（輕量、純函式）=======================
def _num(x) -> Optional[float]:
    try:
        v = float(x)
        return v if v == v else None  # NaN → None
    except (TypeError, ValueError):
        return None


def metrics_from_daily(df: "pd.DataFrame") -> Dict:
    """從日線 DataFrame 算技術指標（純函式）。缺欄/樣本不足 → 對應項給 None。"""
    out = {"close": None, "ma5": None, "ma20": None, "ma60": None, "ma120": None,
           "ret20": None, "ret60": None, "high20": None, "low20": None,
           "vol_ratio": None}
    if df is None or len(df) == 0 or "close" not in df.columns:
        return out
    d = df.sort_values("date").reset_index(drop=True)
    c = pd.to_numeric(d["close"], errors="coerce").dropna()
    if len(c) == 0:
        return out
    n = len(c)
    out["close"] = float(c.iloc[-1])
    for m in (5, 20, 60, 120):
        out[f"ma{m}"] = float(c.rolling(m).mean().iloc[-1]) if n >= m else None
    if n >= 21:
        out["ret20"] = (float(c.iloc[-1]) / float(c.iloc[-21]) - 1) * 100
    if n >= 61:
        out["ret60"] = (float(c.iloc[-1]) / float(c.iloc[-61]) - 1) * 100
    hi_c = "max" if "max" in d.columns else "high" if "high" in d.columns else "close"
    lo_c = "min" if "min" in d.columns else "low" if "low" in d.columns else "close"
    hi = pd.to_numeric(d[hi_c], errors="coerce").shift(1).tail(20)
    lo = pd.to_numeric(d[lo_c], errors="coerce").shift(1).tail(20)
    out["high20"] = float(hi.max()) if pd.notna(hi.max()) else None
    out["low20"] = float(lo.min()) if pd.notna(lo.min()) else None
    if "Trading_Volume" in d.columns:
        v = pd.to_numeric(d["Trading_Volume"], errors="coerce")
        v20 = v.tail(20).mean()
        if pd.notna(v20) and v20 > 0 and pd.notna(v.iloc[-1]):
            out["vol_ratio"] = float(v.iloc[-1]) / float(v20)
    return out


def metrics_from_revenue(df: "pd.DataFrame") -> Dict:
    """從月營收 DataFrame 算 YoY 與近 3 月均 YoY（同 analyze_tw.fundamental 口徑）。"""
    out = {"revenue_yoy": None, "avg3_yoy": None}
    if df is None or len(df) == 0:
        return out
    r = df.copy()
    r["revenue"] = pd.to_numeric(r["revenue"], errors="coerce")
    r = r.dropna(subset=["revenue"])
    if len(r) == 0:
        return out
    r["y"] = r["revenue_year"].astype(int)
    r["m"] = r["revenue_month"].astype(int)
    r = r.sort_values(["y", "m"]).reset_index(drop=True)
    lookup = {(row["y"], row["m"]): float(row["revenue"]) for _, row in r.iterrows()}

    def _yoy(y, m, rev):
        base = lookup.get((y - 1, m))
        return (rev / base - 1) * 100 if base and base > 0 else None

    last = r.iloc[-1]
    out["revenue_yoy"] = _yoy(int(last["y"]), int(last["m"]), float(last["revenue"]))
    yoys = [v for _, row in r.tail(3).iterrows()
            for v in [_yoy(int(row["y"]), int(row["m"]), float(row["revenue"]))] if v is not None]
    out["avg3_yoy"] = sum(yoys) / len(yoys) if yoys else None
    return out


def metrics_from_valuation(df: "pd.DataFrame") -> Dict:
    """從 per_pbr DataFrame 算 PER/PBR 歷史分位與殖利率（分位＝當前值在歷史序列的百分位）。"""
    out = {"per": None, "per_pctile": None, "pbr_pctile": None, "div_yield": None}
    if df is None or len(df) == 0:
        return out
    v = df.sort_values("date").reset_index(drop=True)
    per = pd.to_numeric(v.get("PER"), errors="coerce")
    per = per[per > 0].dropna()
    if len(per):
        out["per"] = float(per.iloc[-1])
        out["per_pctile"] = float((per < per.iloc[-1]).mean())
    pbr = pd.to_numeric(v.get("PBR"), errors="coerce")
    pbr = pbr[pbr > 0].dropna()
    if len(pbr):
        out["pbr_pctile"] = float((pbr < pbr.iloc[-1]).mean())
    if "dividend_yield" in v.columns:
        out["div_yield"] = _num(v["dividend_yield"].iloc[-1])
    return out


def _chip_from_opp_reasons(opp: Optional[Dict]) -> bool:
    """從 opportunities.reasons 的文字關鍵詞判法人是否轉買（免抓籌碼 dataset）。"""
    if not opp:
        return False
    reasons = " ".join(str(x) for x in (opp.get("reasons") or []))
    return any(k in reasons for k in _CHIP_BUY_KEYWORDS)


def assemble_metrics(cand: Dict, daily_m: Dict, rev_m: Dict, val_m: Dict,
                     tracked_res: Optional[Dict]) -> Dict:
    """把各來源指標合成單一 metrics dict。opportunities 有提供的欄位優先當錨點；
    籌碼訊號來自 tracked 既有 analyze 結果（綠燈＝連買）或 opportunities reasons 關鍵詞。"""
    opp = cand.get("opp") or {}
    close = daily_m.get("close") or _num(opp.get("close"))
    high20 = daily_m.get("high20") or _num(opp.get("recent_high20"))
    support = _num(opp.get("support_ma20")) or daily_m.get("ma20")
    ret20 = daily_m.get("ret20")
    if ret20 is None:
        ret20 = _num(opp.get("rs20"))
    revenue_yoy = rev_m.get("revenue_yoy")
    if revenue_yoy is None:
        revenue_yoy = _num(opp.get("revenue_yoy"))

    # 籌碼：tracked 既有分析綠燈＝連 3 日同向買；否則看 opportunities reasons 關鍵詞
    chip_buy_streak = False
    if tracked_res:
        chip_buy_streak = ((tracked_res.get("chips") or {}).get("light") == "green")
    chip_turn_buy = chip_buy_streak or _chip_from_opp_reasons(cand.get("opp"))

    dist_high20 = None
    if close and high20 and high20 > 0:
        dist_high20 = (high20 - close) / close * 100

    earnings = opp.get("earnings_date")
    return {
        "id": cand["id"], "name": cand.get("name") or cand["id"],
        "close": close, "ma20": daily_m.get("ma20"), "ma60": daily_m.get("ma60"),
        "ma120": daily_m.get("ma120"), "ret20": ret20, "ret60": daily_m.get("ret60"),
        "high20": high20, "low20": daily_m.get("low20"),
        "vol_ratio": daily_m.get("vol_ratio"),
        "support": support, "recent_high": high20,
        "revenue_yoy": revenue_yoy, "avg3_yoy": rev_m.get("avg3_yoy"),
        "per": val_m.get("per"), "per_pctile": val_m.get("per_pctile"),
        "pbr_pctile": val_m.get("pbr_pctile"), "div_yield": val_m.get("div_yield"),
        "chip_turn_buy": chip_turn_buy, "chip_buy_streak_ge3": chip_buy_streak,
        "dist_high20_pct": dist_high20,
        "earnings_within7": _earnings_within7(earnings),
        "risk_flags": list(opp.get("risk_flags") or []),
    }


def _earnings_within7(earnings_date, today: Optional[str] = None) -> bool:
    """事件（法說/財報）是否在 7 天內。缺日期 → False。"""
    if not earnings_date:
        return False
    from datetime import datetime, timezone, timedelta
    try:
        d = datetime.strptime(str(earnings_date)[:10], "%Y-%m-%d").date()
        t = (datetime.strptime(today[:10], "%Y-%m-%d").date() if today
             else datetime.now(timezone(timedelta(hours=8))).date())
    except (ValueError, TypeError):
        return False
    return 0 <= (d - t).days <= 7


# ======================= 三準則評分（純函式）=======================
def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _rr(m: Dict, defense: Optional[float]) -> Optional[float]:
    """R/R＝(目標-現價)/(現價-防守)。錨點缺或分母<=0 → None。"""
    close, target = m.get("close"), m.get("recent_high")
    if not (close and target and defense) or close <= defense or target <= close:
        return None
    return (target - close) / (close - defense)


def score_short(m: Dict) -> float:
    s = 0.0
    if m.get("ret20") is not None:
        s += _clamp(m["ret20"], 0, 12) / 12 * 30
    if m.get("close") and m.get("ma20") and m["close"] > m["ma20"]:
        s += 20
    if (m.get("close") and m.get("high20") and m.get("vol_ratio")
            and m["close"] >= m["high20"] and m["vol_ratio"] > 1.3):
        s += 25
    if m.get("chip_turn_buy"):
        s += 25
    d = m.get("dist_high20_pct")
    if d is not None and 0 < d < 2:  # 就在 20 日高下方 2% 內＝追高
        s -= 10
    if m.get("earnings_within7"):
        s -= 15
    return round(_clamp(s, 0, 100), 1)


def score_swing(m: Dict) -> float:
    s = 0.0
    c, ma20, ma60, ma120 = m.get("close"), m.get("ma20"), m.get("ma60"), m.get("ma120")
    if c and ma20 and c > ma20:
        s += 10
    if ma20 and ma60 and ma20 > ma60:
        s += 10
    if ma60 and ma120 and ma60 > ma120:
        s += 10
    if m.get("ret60") is not None:
        s += _clamp(m["ret60"], 0, 20) / 20 * 20
    if m.get("chip_buy_streak_ge3"):
        s += 15
    defense = _swing_defense(m)
    rr = _rr(m, defense)
    if rr is not None:
        s += 20 if rr >= 1.8 else _clamp((rr - 1.0) / 0.8, 0, 1) * 20
    if (m.get("revenue_yoy") or 0) > 0:
        s += 15
    return round(_clamp(s, 0, 100), 1)


def score_long(m: Dict) -> float:
    s = 0.0
    if (m.get("revenue_yoy") or 0) > 0:
        s += 15
    avg3 = m.get("avg3_yoy")
    if (avg3 or 0) > 0:
        s += 15 + _clamp(avg3, 0, 20) / 20 * 10
    pp = m.get("per_pctile")
    if pp is not None:
        s += _clamp(0.5 - pp, 0, 0.5) / 0.5 * 20
    pb = m.get("pbr_pctile")
    if pb is not None:
        s += _clamp(0.5 - pb, 0, 0.5) / 0.5 * 10
    dy = m.get("div_yield")
    if dy is not None:
        s += 15 if dy >= 4 else 10 if dy >= 2.5 else 5 if dy > 0 else 0
    s -= 10 * len(m.get("risk_flags") or [])
    return round(_clamp(s, 0, 100), 1)


def confidence_from_score(score: float) -> int:
    """信心度映射：round(score*0.7+10)，clamp [0,80]（契約範例 78→65）。"""
    return int(_clamp(round(score * 0.7 + 10), 0, 80))


# ======================= 操作卡（純函式）=======================
def _swing_defense(m: Dict) -> Optional[float]:
    sup = m.get("support") or m.get("ma20")
    close = m.get("close")
    if not (sup and close):
        return None
    return round(min(sup, close) * 0.96, 1)


def _entry_zone(m: Dict) -> Tuple[Optional[float], Optional[float]]:
    """買進帶：以支撐為錨的拉回區，兩端夾在現價 ±10% 內（規格：錨點距現價 ≤10%）。"""
    close, sup = m.get("close"), (m.get("support") or m.get("ma20"))
    if not close:
        return None, None
    anchor = min(sup, close) if sup else close * 0.97
    low = _clamp(anchor * 0.98, close * 0.90, close)
    high = _clamp(max(anchor, close * 0.99), close * 0.90, close * 1.02)
    if low > high:
        low, high = close * 0.95, close
    return round(low, 1), round(high, 1)


def build_pick_card(m: Dict, framework: str, score: float,
                    new_position: str) -> Dict:
    """組單檔操作卡（符合 schema pick 定義）。reasons 恰 3 條、每條含數字。"""
    close = m.get("close")
    low, high = _entry_zone(m)
    if framework == "long":
        defense = round((m.get("ma60") or (close * 0.90 if close else 0)) * 0.95, 1)
    else:
        defense = _swing_defense(m) or (round(close * 0.93, 1) if close else None)
    if defense and low and defense >= low:
        defense = round(low * (0.93 if framework == "long" else 0.96), 1)

    reasons = _build_reasons(m, framework, defense)[:3]
    while len(reasons) < 3:  # 保底補到 3 條（含數字），避免 reasons 不足 3
        reasons.append(f"現價 {close}（分數 {score:.0f}／100）" if close is not None
                       else f"綜合評分 {score:.0f}／100")

    banned = (new_position == "禁止新增部位")
    action = _action_summary(framework, low, high, defense, new_position, banned)
    invalidation = _invalidation(framework, defense)
    return {
        "id": m["id"], "name": m.get("name") or m["id"],
        "close": _num(close), "score": round(score, 1),
        "confidence": confidence_from_score(score),
        "action_summary": action,
        "entry_zone": [low if low is not None else 0.0,
                       high if high is not None else 0.0],
        "defense_price": _num(defense),
        "invalidation": invalidation,
        "reasons": reasons,
    }


# 失效條件的基本面語言（各框架固定），對外顯示與精選卡自算防守數字組合成一句話。
_INVALIDATION_FUND_COND = {"short": "動能轉弱、爆量收黑",
                           "swing": "營收 YoY 連 2 月轉負",
                           "long": "營收連 2 月轉負或估值回到高分位"}


def _invalidation(framework: str, defense: Optional[float]) -> str:
    fund_cond = _INVALIDATION_FUND_COND[framework]
    return f"跌破 {defense} 或{fund_cond}" if defense is not None else fund_cond


def _action_summary(framework, low, high, defense, new_position, banned) -> str:
    zone = f"{low}-{high}" if low is not None and high is not None else "—"
    if banned and framework == "long":
        return f"大盤禁新倉，觀察區 {zone}，等大盤解禁再佈局"
    verb = {"short": f"突破買進區 {zone}，跌破 {defense} 出場",
            "swing": f"拉回布局區 {zone}，跌破 {defense} 停損",
            "long": f"分批佈局區 {zone}，跌破 {defense} 停損"}[framework]
    if new_position == "僅限試單":
        verb += "（試單上限 10 萬）"
    return verb


def _build_reasons(m: Dict, framework: str, defense) -> List[str]:
    out = []
    if framework == "short":
        if m.get("ret20") is not None:
            out.append(f"20 日動能 {m['ret20']:+.1f}%")
        if m.get("close") and m.get("ma20") and m["close"] > m["ma20"]:
            out.append(f"站回 MA20（{m['ma20']:.1f}）")
        if (m.get("close") and m.get("high20") and m.get("vol_ratio")
                and m["close"] >= m["high20"] and m["vol_ratio"] > 1.3):
            out.append(f"帶量突破 20 日高 {m['high20']:.1f}（量能 {m['vol_ratio']:.1f}×）")
        if m.get("chip_turn_buy"):
            out.append("法人近期轉買進（籌碼翻多）")
        if m.get("dist_high20_pct") is not None:
            out.append(f"距 20 日高 {m['dist_high20_pct']:.1f}%")
    elif framework == "swing":
        if m.get("ma20") and m.get("ma60") and m["ma20"] > m["ma60"]:
            out.append(f"均線多頭排列（MA20 {m['ma20']:.0f} > MA60 {m['ma60']:.0f}）")
        if m.get("ret60") is not None:
            out.append(f"60 日 RS {m['ret60']:+.1f}%")
        rr = _rr(m, defense)
        if rr is not None:
            out.append(f"R/R 約 {rr:.1f}（目標 {m['recent_high']:.0f}／防守 {defense}）")
        if (m.get("revenue_yoy") or 0) > 0:
            out.append(f"營收 YoY {m['revenue_yoy']:+.1f}%")
        if m.get("chip_buy_streak_ge3"):
            out.append("法人連續買超")
    else:  # long
        if m.get("revenue_yoy") is not None:
            avg = m.get("avg3_yoy")
            avg_s = f"，近 3 月均 {avg:+.1f}%" if avg is not None else ""
            out.append(f"營收 YoY {m['revenue_yoy']:+.1f}%{avg_s}")
        if m.get("per_pctile") is not None:
            out.append(f"PER 落在歷史 {m['per_pctile']*100:.0f}% 分位")
        if m.get("div_yield") is not None and m["div_yield"] > 0:
            out.append(f"殖利率 {m['div_yield']:.1f}%")
        if m.get("pbr_pctile") is not None:
            out.append(f"PBR 歷史 {m['pbr_pctile']*100:.0f}% 分位")
        if m.get("risk_flags"):
            out.append(f"風險旗標 {len(m['risk_flags'])} 項（已扣分）")
    return out


# ======================= 選檔 + 閘門（純函式）=======================
_THRESHOLDS = [("short", 70), ("swing", 65), ("long", 60)]
_LIMITS = {"short": 1, "swing": 3, "long": 5}


def select_frameworks(scored: List[Dict]) -> Dict[str, List[Dict]]:
    """每檔指派到「有達標框架中分數最高」的唯一框架，再各取前 N。
    scored 元素：{"metrics", "short","swing","long"}（後三個為分數）。
    回 {framework: [ (metrics, score) ... 已依分數降序、截 N ]}。"""
    buckets = {"short": [], "swing": [], "long": []}
    for it in scored:
        eligible = [(fw, it[fw]) for fw, thr in _THRESHOLDS if it[fw] >= thr]
        if not eligible:
            continue
        # 最高分框架；同分時依 short>swing>long 的順序（_THRESHOLDS 順序）優先
        order = {fw: i for i, (fw, _) in enumerate(_THRESHOLDS)}
        home_fw, home_score = max(eligible, key=lambda x: (x[1], -order[x[0]]))
        buckets[home_fw].append((it["metrics"], home_score))
    for fw in buckets:
        buckets[fw].sort(key=lambda x: x[1], reverse=True)
        buckets[fw] = buckets[fw][:_LIMITS[fw]]
    return buckets


def build_picks_block(scored: List[Dict], new_position: str,
                      generated_from: str, max_new_ids: Optional[List[str]] = None
                      ) -> Tuple[Dict, List[str]]:
    """組 daily.picks 區塊 + 回傳「需要跑完整 analyze 的被選 id 清單」。
    max_new_ids：允許的新股 id 白名單（可點入保證）；不在白名單的新股會被移出清單。
    這裡不打網路——白名單由呼叫端依 tracked/6 檔上限先算好傳入。"""
    buckets = select_frameworks(scored)
    banned = (new_position == "禁止新增部位")

    block = {"short": [], "swing": [], "long": []}
    selected_ids = []
    for fw in ("short", "swing", "long"):
        if banned and fw in ("short", "swing"):
            continue  # 禁新倉：短線/波段清空
        for metrics, score in buckets[fw]:
            sid = metrics["id"]
            if max_new_ids is not None and sid not in max_new_ids:
                continue  # 無法保證 stocks/<id>.json 存在 → 不列（可點入保證）
            block[fw].append(build_pick_card(metrics, fw, score, new_position))
            selected_ids.append(sid)

    note = _gate_note(new_position, bool(block["long"]))
    picks = {"generated_from": generated_from, "gate": new_position, "note": note,
             "short": block["short"], "swing": block["swing"], "long": block["long"]}
    return picks, selected_ids


# ======================= picks ↔ stocks 單一事實源對齊 =======================
def _authoritative_entry_zone(detail: Dict) -> Tuple[Optional[float], Optional[float]]:
    """從個股完整分析（stocks/<id>.json）的 primary_decision.advice「空手進場錨點」推回精選卡
    的觀察區——用 advice 那條同款 _nonholder_entry 邏輯（站回上方均線／回測下方均線／
    entry_condition），確保精選卡的進場區與完整分析的進場劇本同源、同一個數字。回 (low, high)
    ＝現價與錨點之間的觀察帶；資料不足回 (None, None)（呼叫端保留自算值）。"""
    from warroom.primary_decision import _nonholder_entry, _executable_anchors
    primary = detail.get("primary_decision") or {}
    price = _num((detail.get("price") or {}).get("close"))
    if price is None:
        return None, None
    defense = _num(primary.get("defense_price"))
    tech_facts = (((detail.get("context") or {}).get("lights") or {})
                  .get("technical") or {}).get("facts") or []
    entry = _nonholder_entry(price, tech_facts, primary.get("entry_condition"),
                             _executable_anchors(price, tech_facts, defense))
    if not entry or entry.get("price") is None:
        return None, None
    anchor = round(float(entry["price"]), 1)
    p = round(price, 1)
    return (min(anchor, p), max(anchor, p))


def align_picks_to_details(picks_block: Optional[Dict],
                           stock_details: Dict[str, Dict]) -> None:
    """單一事實源（實戰走查 🔴 任務 1）：精選操作卡「對外顯示」的 defense_price/entry_zone/
    invalidation/action_summary 一律改「直接取該股 stocks/<id>.json 的 primary_decision」，
    不再沿用 picks 自算的長線 MA 值——否則同一支股票精選卡防守 452.8、點進完整分析卻是
    447.1，同一天兩套數字打架最傷信任。picks 自算的 score/confidence 只用於評分排序，保留不動。
    就地修改 picks_block（picks 卡的 id 必在 stock_details 內：白名單＝tracked ∪ 被選新股）。"""
    if not picks_block:
        return
    gate = picks_block.get("gate")
    banned = (gate == "禁止新增部位")
    for fw in ("short", "swing", "long"):
        for card in picks_block.get(fw) or []:
            detail = stock_details.get(card.get("id"))
            if not detail:
                continue  # 理論上白名單保證存在；缺就保留自算值不炸
            primary = detail.get("primary_decision") or {}
            defense = _num(primary.get("defense_price"))
            if defense is None:
                continue  # 完整分析也沒有防守價（資料不足）→ 保留自算值
            low, high = _authoritative_entry_zone(detail)
            if low is None or high is None:  # 完整分析無可執行錨點 → 沿用自算觀察區
                low, high = card["entry_zone"][0], card["entry_zone"][1]
            card["defense_price"] = defense
            card["entry_zone"] = [low, high]
            card["action_summary"] = _action_summary(fw, low, high, defense, gate, banned)
            card["invalidation"] = _invalidation(fw, defense)


def _gate_note(new_position: str, has_long: bool) -> str:
    if new_position == "禁止新增部位":
        tail = "長線名單僅供研究、等解禁再佈局。" if has_long else "今日無符合門檻的長線名單。"
        return "大盤禁新倉：短線/波段今日不推新倉，" + tail
    if new_position == "僅限試單":
        return "大盤僅限試單：新倉每檔上限 10 萬、分批進場、嚴設防守價。"
    return "大盤穩定：可依紀律分批布局，仍以防守價控風險、不追高。"


def empty_picks(new_position: str = "僅限試單",
                generated_from: str = "tw-stock-screener opportunities + FinMind",
                note: Optional[str] = None) -> Dict:
    """給 build_all 純函式/離線模式的預設空區塊（仍符合契約）。"""
    return {"generated_from": generated_from, "gate": new_position,
            "note": note or "本次未生成主動選股（離線/純函式模式）。",
            "short": [], "swing": [], "long": []}


# ======================= 打網路的組裝（generate_picks）=======================
def _fetch_light(sid: str, fetch_fn, counter: List[int]) -> Tuple[Dict, Dict, Dict]:
    """抓單檔輕量 3 dataset（日線/月營收/PER），回 (daily_m, rev_m, val_m)。
    fetch_fn(method, **kw)＝cached_fetch；每次呼叫 counter[0]+=1（含快取命中，供估算）。"""
    def _grab(method, kw):
        counter[0] += 1
        try:
            df = fetch_fn(method, **{**kw, "stock_id": sid})
            return df if (df is not None and len(df) > 0) else None
        except Exception:
            return None
    daily_df = _grab("taiwan_stock_daily", _DAILY_KW)
    rev_df = _grab("taiwan_stock_month_revenue", _REV_KW)
    val_df = _grab("taiwan_stock_per_pbr", _VAL_KW)
    return (metrics_from_daily(daily_df), metrics_from_revenue(rev_df),
            metrics_from_valuation(val_df))


def generate_picks(exposure_guidance: Dict, results: Dict[str, Dict],
                   profile: Dict, fetch_fn=None, analyze_fn=None,
                   opportunities: Optional[List[Dict]] = None,
                   universe: Optional[List[Dict]] = None) -> Tuple[Dict, Dict, Dict]:
    """打網路組 picks（放 build_snapshots.main()）。純函式部分全抽出，這裡只負責 IO。
    - fetch_fn：預設 finmind_cache.cached_fetch（可注入假 loader 測）。
    - analyze_fn：預設 analyze_tw.analyze（被選新股跑完整分析產 stocks/<id>.json）。
    回 (picks_block, picks_results, stats)：
      picks_results＝{sid: analyze_res}（僅新股，供 build_all 產 stock detail）；
      stats＝{finmind_calls, opp_source, pool_size, analyzed}。
    """
    if fetch_fn is None:
        from warroom.finmind_cache import cached_fetch as fetch_fn  # noqa
    if analyze_fn is None:
        from warroom.analyze_tw import analyze as analyze_fn  # noqa

    new_position = exposure_guidance.get("new_position", "僅限試單")
    core_ids = list(profile.get("core_holdings") or [])
    tracked_ids = list(results.keys())

    if opportunities is None:
        opportunities, opp_source = fetch_opportunities()
    else:
        opp_source = "injected"
    if universe is None:
        universe = load_universe()

    pool = build_candidate_pool(opportunities, universe, tracked_ids, core_ids)

    counter = [0]
    scored = []
    for cand in pool:
        sid = cand["id"]
        tracked_res = results.get(sid)
        daily_m, rev_m, val_m = _fetch_light(sid, fetch_fn, counter)
        m = assemble_metrics(cand, daily_m, rev_m, val_m, tracked_res)
        if m.get("close") is None:
            continue  # 現價缺＝資料不足，不評分（誠實不編）
        scored.append({"metrics": m, "short": score_short(m),
                       "swing": score_swing(m), "long": score_long(m)})

    # 先算選檔（不含可點入白名單），得出被選 id → 決定哪些新股要 analyze（上限 6）
    prelim = select_frameworks(scored)
    banned = (new_position == "禁止新增部位")
    ordered_new = []
    for fw in ("short", "swing", "long"):
        if banned and fw in ("short", "swing"):
            continue
        for metrics, _score in prelim[fw]:
            sid = metrics["id"]
            if sid not in results and sid not in ordered_new:
                ordered_new.append(sid)
    to_analyze = ordered_new[:MAX_NEW_ANALYZE]

    picks_results = {}
    analyze_calls = 0
    for sid in to_analyze:
        try:
            res = analyze_fn(sid)
            analyze_calls += 8  # analyze_tw.fetch 抓 8 個 dataset（估算）
            if res:
                picks_results[sid] = res
        except Exception:
            pass  # 單檔失敗不影響整批；該股不列（下方白名單過濾）

    # 白名單＝tracked（已有 detail）+ 這次成功 analyze 的新股
    allow_ids = set(results.keys()) | set(picks_results.keys())
    picks_block, _selected = build_picks_block(
        scored, new_position,
        generated_from="tw-stock-screener opportunities + FinMind",
        max_new_ids=allow_ids)

    stats = {"finmind_calls": counter[0] + analyze_calls,
             "scoring_calls": counter[0], "analyze_calls": analyze_calls,
             "opp_source": opp_source, "pool_size": len(pool),
             "analyzed": list(picks_results.keys())}
    return picks_block, picks_results, stats
