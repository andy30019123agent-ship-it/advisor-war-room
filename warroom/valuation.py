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


def valuation_band(percentile: Optional[float]) -> str:
    """對外估值文案改區間語言（規格 §3.3）：便宜/合理/偏貴/很貴。"""
    if percentile is None:
        return "資料不足"
    if percentile < 0.35:
        return "便宜"
    if percentile < 0.65:
        return "合理"
    if percentile < 0.85:
        return "偏貴"
    return "很貴"


def sanity_warning(base: Optional[float], price: Optional[float],
                   threshold: float = 0.30) -> Optional[str]:
    """估值 sanity check（規格 §3.3）：Base 偏離現價 > threshold → 回警語字串。
    警語只標示「模型可能低估近期估值 regime」，呼叫端不得用它直接觸發減碼。"""
    if base is None or not price:
        return None
    dev = abs(base - price) / price
    if dev > threshold:
        return (f"模型 Base {base} 與現價 {price} 偏離 {dev * 100:.0f}%，"
                "可能低估近期估值 regime；僅供參考，不作為減碼依據")
    return None


# 近 3 年 / 近 5 年 / 完整週期的近似交易日數（regime 分組用；日 PER 序列已 date 升冪）
_REGIME_WINDOWS = (("3y", 756), ("5y", 1260), ("full", None))


def regime_percentiles(series: List[float]) -> Dict[str, Dict]:
    """分 regime（近3年/近5年/完整）各算一組分位；樣本<8 的窗口略過（規格 §3.3）。"""
    out = {}
    for label, n in _REGIME_WINDOWS:
        sub = series[-n:] if n else series
        pcts = multiple_percentiles(sub)
        if pcts:
            out[label] = pcts
    return out


def select_regime(regimes: Dict[str, Dict]):
    """優先近 3 年（反映當前估值環境，避免早年低基期把分位拖低）；不足退 5y→full。"""
    for label in ("3y", "5y", "full"):
        if label in regimes:
            return label, regimes[label]
    return None, None


def quality_base_bump(roe: Optional[float]) -> float:
    """品質股（高 ROE）Base multiple 上修半檔到一檔（規格 §3.3），回 p50→p75 間的比例。
    roe>=20% → 上修約一檔（0.66）；roe>=12% → 半檔（0.33）；其餘不上修。"""
    if roe is None:
        return 0.0
    if roe >= 0.20:
        return 0.66
    if roe >= 0.12:
        return 0.33
    return 0.0


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


def fair_value_per_path(fwd_eps: float, per_pcts: Dict, market_light: str,
                        base_bump: float = 0.0) -> Dict:
    """PER 路徑：Bear/Base/Bull = Forward EPS × 分位倍數。
    base_bump（0~0.8）＝品質股把 Base multiple 由 p50 往 p75 上修的比例，預設 0＝不上修。"""
    lo, mid, hi = _trio(per_pcts, market_light)
    base_mult = mid + max(0.0, min(0.8, base_bump)) * (hi - mid)
    return {
        "bear": round(fwd_eps * lo, 1),
        "base": round(fwd_eps * base_mult, 1),
        "bull": round(fwd_eps * hi, 1),
        "multiples": {"bear": round(lo, 2), "base": round(base_mult, 2), "bull": round(hi, 2)},
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
        "band": "資料不足", "regime": None, "warning": None,
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
            "band": valuation_band(current_percentile(pbr_series, pbr_cur)),
            "regime": "full", "warning": sanity_warning(fv["base"], price),
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
    if eps_ttm <= 0:
        # 虧損/零盈餘股：相對估值（PER）無意義，不得硬套（會算出負且倒序的 Bear/Base/Bull）
        return _insufficient("per", 30, "虧損/零盈餘，不適用相對估值（PER）")
    per_series = inp.get("per_series") or []
    # regime 分組（規格 §3.3）：優先近 3 年分位，避開早年低估值週期把 Base 拖太低
    regimes = regime_percentiles(per_series)
    regime_label, per_pcts = select_regime(regimes)
    if per_pcts is None:
        return _insufficient("per", 25, "PER 歷史樣本不足，無法給估值區間")
    g = weighted_revenue_yoy(inp.get("rev_df"))
    fwd = forward_eps(eps_ttm, g)
    if fwd <= 0:
        return _insufficient("per", 30, "虧損/零盈餘，不適用相對估值（PER）")
    base_bump = quality_base_bump(inp.get("roe"))
    fv = fair_value_per_path(fwd, per_pcts, market_light, base_bump=base_bump)
    band = valuation_band(current_percentile(per_series, per_cur))
    warning = sanity_warning(fv["base"], price)
    src_zh = "財報 TTM" if eps_source == "financial_statement" else "現價/PER 反推（降信心）"
    g_used = max(-0.20, min(0.40, g)) if g is not None else 0.0
    if g is not None and abs(g_used - g) > 1e-9:
        growth_note = f"成長 g={_pct(g_used)}（原始 {_pct(g)} 已封頂）"
    else:
        growth_note = f"成長 g={_pct(g_used)}（clamp -20%~+40%）"
    bump_note = ("；品質股 Base 上修" if base_bump > 0 else "")
    disclosure = (
        f"TTM EPS {eps_ttm}（{src_zh}）、{growth_note}、"
        f"Forward EPS {fwd}；PER 25/50/75={per_pcts['p25']}/{per_pcts['p50']}/{per_pcts['p75']}"
        f"（regime={regime_label}，現值 {per_cur}，分位 {_pct(current_percentile(per_series, per_cur))}）"
        + bump_note
        + ("；大盤紅燈倍數下修一檔" if market_light == "red" else ""))
    return {
        "path": "per", "eps_ttm": eps_ttm, "eps_source": eps_source, "eps_forward": fwd,
        "growth_used": g_used,
        "fair_value": {"bear": fv["bear"], "base": fv["base"], "bull": fv["bull"]},
        "multiples": fv["multiples"], "current_multiple": per_cur,
        "current_percentile": current_percentile(per_series, per_cur),
        "bvps": None, "roe": None,
        "confidence_penalty": penalty, "disclosure": disclosure,
        "band": band, "regime": regime_label, "warning": warning,
    }
