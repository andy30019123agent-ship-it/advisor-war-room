"""財報品質分數（規格 §3.3）＋ ROE（規格 §3.2.1 終審移交第 1 項）。
7 因子各 0-2 分：營收/EPS/毛利率/營益率/ROE/營業現金流(OCF，key 名沿用 fcf 相容既有介面，
未扣資本支出、非真正自由現金流)/負債；連續改善另加減分（streak_bonus）。
資料源：FinMind 綜合損益表 / 資產負債表 / 現金流量表 / 月營收（皆長格式）。
純規則、缺科目降級：金融股缺毛利/營益 → 該因子標「不適用」不扣分（max 只計可用因子）。
資料事實（2026-07-15 真 API 實測）：
- EPS/Revenue/GrossProfit/OperatingIncome 為單季值 → TTM＝近 4 季直加。
- 淨利科目：一般股 IncomeAfterTaxes、金融股 IncomeAfterTax（無 s）→ 容錯清單依序試。
- 現金流量表為年度累計制 → FCF 只做「同季 YoY」比較（同季累計基礎可比），不做 TTM 加總。
- 資產負債表每科目有 _per 重複列 → 必須精準等值比對 type。
"""
from typing import Dict, List, Optional, Tuple

import pandas as pd

_QUARTER_BY_MONTH = {3: 1, 6: 2, 9: 3, 12: 4}
# 淨利科目容錯清單（一般股→金融股→保底）
NET_INCOME_TYPES = ["IncomeAfterTaxes", "IncomeAfterTax",
                    "TotalConsolidatedProfitForThePeriod"]
# 金融/循環業：負債比不可比，債務因子標不適用
_NO_DEBT_INDUSTRIES = {"金融保險", "銀行業", "保險業", "證券業"}


def _qkey(date_str: str) -> Optional[Tuple[int, int]]:
    """date 字串轉 (year, quarter)。"""
    try:
        y, m = int(date_str[:4]), int(date_str[5:7])
    except (ValueError, IndexError):
        return None
    q = _QUARTER_BY_MONTH.get(m)
    return (y, q) if q else None


def _series(fs_df, type_name: str) -> Dict[Tuple[int, int], float]:
    """長格式某 type 的單季值序列 {(year, quarter): value}（精準等值比對 type）。"""
    if fs_df is None or len(fs_df) == 0 or "type" not in fs_df.columns:
        return {}
    sub = fs_df[fs_df["type"] == type_name].copy()
    if len(sub) == 0:
        return {}
    sub["value"] = pd.to_numeric(sub["value"], errors="coerce")
    out = {}
    for _, r in sub.dropna(subset=["value"]).iterrows():
        k = _qkey(str(r["date"]))
        if k:
            out[k] = float(r["value"])
    return out


def _first_series(fs_df, type_names: List[str]) -> Tuple[Dict, Optional[str]]:
    """容錯清單：依序試型別，回傳第一個找到的序列 + 型別名。"""
    for t in type_names:
        s = _series(fs_df, t)
        if s:
            return s, t
    return {}, None


def _ttm(series: Dict, keys: List, offset: int = 0) -> Optional[float]:
    """近 4 季加總，offset=0 為最新 TTM、offset=4 為前一年 TTM。keys 需已升冪。
    P1 fix #7：要求所選 4 季在時間序列上「連續」（無缺季），若中間缺一季即回 None
    （上層標樣本不足），避免用不連續的 4 筆湊 TTM 膨脹指標（如 ROE 進而灌水 PBR 估值）。
    跨年份時（例如 Q4→隔年Q1）正確處理。"""
    end = len(keys) - offset
    if end < 4:
        return None
    window = keys[end - 4:end]
    for i in range(1, 4):
        y0, q0 = window[i - 1]
        y1, q1 = window[i]
        expected = (y0, q0 + 1) if q0 < 4 else (y0 + 1, 1)
        if (y1, q1) != expected:
            return None
    return sum(series[k] for k in window)


def compute_roe(fs_df, bs_df) -> Optional[float]:
    """ROE = TTM 淨利 ÷ 最新權益（小數）。缺任一 → None。"""
    ni_series, _ = _first_series(fs_df, NET_INCOME_TYPES)
    if not ni_series:
        return None
    keys = sorted(ni_series.keys())
    ttm_ni = _ttm(ni_series, keys, 0)
    if ttm_ni is None:
        return None
    eq_series = _series(bs_df, "Equity")
    if not eq_series:
        return None
    equity = eq_series[sorted(eq_series.keys())[-1]]  # 最新一季權益
    if not equity or equity == 0:
        return None
    return round(ttm_ni / equity, 4)


def _factor(score, applicable, value) -> Dict:
    """因子回傳格式。"""
    return {"score": score, "applicable": applicable, "value": value}


def _na(reason: str) -> Dict:
    """不適用因子。"""
    return _factor(None, False, reason)


def _score_growth(g: Optional[float]) -> int:
    """成長率 → 0-2：>10% 給 2、0~10% 給 1、<0 給 0。"""
    if g is None:
        return 0
    if g > 0.10:
        return 2
    if g >= 0:
        return 1
    return 0


def _latest_month_yoy(rev_df) -> Optional[float]:
    """月營收：最新月 YoY（小數）。缺基期 → None。"""
    if rev_df is None or len(rev_df) == 0:
        return None
    r = rev_df.copy()
    r["revenue"] = pd.to_numeric(r["revenue"], errors="coerce")
    r = r.dropna(subset=["revenue"])
    if len(r) == 0:
        return None
    r["ym"] = r["revenue_year"].astype(int) * 100 + r["revenue_month"].astype(int)
    r = r.sort_values("ym").reset_index(drop=True)
    lookup = {int(row["ym"]): float(row["revenue"]) for _, row in r.iterrows()}
    last = r.iloc[-1]
    py = (int(last["revenue_year"]) - 1) * 100 + int(last["revenue_month"])
    base = lookup.get(py)
    if base and base > 0:
        return float(last["revenue"]) / base - 1
    return None


def _margin_factor(num_series, rev_series, label: str) -> Dict:
    """毛利率/營益率因子：TTM 分子/TTM 營收，比前一年 TTM 改善→2、持平→1、惡化→0。"""
    if not num_series or not rev_series:
        return _na("科目不適用（無此科目）")
    nk, rk = sorted(num_series.keys()), sorted(rev_series.keys())
    num_now, num_prev = _ttm(num_series, nk, 0), _ttm(num_series, nk, 4)
    rev_now, rev_prev = _ttm(rev_series, rk, 0), _ttm(rev_series, rk, 4)
    if num_now is None or rev_now in (None, 0):
        return _na("樣本不足")
    m_now = num_now / rev_now
    if num_prev is None or rev_prev in (None, 0):
        # 只有現值：以水準粗評（>20% 給 2、>10% 給 1、else 0），標注無 YoY
        score = 2 if m_now > 0.20 else 1 if m_now > 0.10 else 0
        return _factor(score, True, f"{label} {m_now*100:.1f}%（無同期比較）")
    m_prev = num_prev / rev_prev
    if m_now > m_prev + 0.005:
        score = 2
    elif m_now >= m_prev - 0.005:
        score = 1
    else:
        score = 0
    return _factor(score, True, f"{label} {m_now*100:.1f}%（前 {m_prev*100:.1f}%）")


def _fcf_factor(cf_df) -> Dict:
    """營業現金流（OCF）因子：最新季 vs 去年同季（累計制→同季可比）。正且改善→2、正→1、負→0。
    P1 fix #8 誠實化：此因子只讀「營業活動之淨現金流」，未扣資本支出，並非真正的自由現金流
    （Free Cash Flow）。顯示名改「營業現金流」，避免掛 FCF 之名誤導；key 名維持 "fcf" 相容既有介面。"""
    op = _series(cf_df, "CashFlowsFromOperatingActivities")
    if not op:
        return _na("科目不適用（無營業現金流）")
    keys = sorted(op.keys())
    now = op[keys[-1]]
    prev = None
    prev_key = (keys[-1][0] - 1, keys[-1][1])  # 去年同季
    if prev_key in op:
        prev = op[prev_key]
    suffix = "（以 OCF 評分，未扣資本支出）"
    if now <= 0:
        return _factor(0, True, f"營業現金流 {now:,.0f}（負）{suffix}")
    if prev is not None and now > prev:
        return _factor(2, True, f"營業現金流 正、同季 YoY 增{suffix}")
    return _factor(1, True, f"營業現金流 正、同季 YoY 持平或略降{suffix}")


def _debt_factor(bs_df, industry_category) -> Dict:
    """負債比 = Liabilities/TotalAssets（最新季）。<0.4→2、0.4~0.6→1、>0.6→0。金融業不適用。"""
    if industry_category in _NO_DEBT_INDUSTRIES:
        return _na("金融業槓桿不可比，不評分")
    liab = _series(bs_df, "Liabilities")
    ta = _series(bs_df, "TotalAssets")
    if not liab or not ta:
        return _na("科目不適用（無負債/資產）")
    k = sorted(set(liab.keys()) & set(ta.keys()))
    if not k:
        return _na("樣本不足")
    latest = k[-1]
    denom = ta[latest]
    if not denom or denom == 0:
        return _na("資產為 0")
    ratio = liab[latest] / denom
    score = 2 if ratio < 0.4 else 1 if ratio <= 0.6 else 0
    return _factor(score, True, f"負債比 {ratio*100:.0f}%")


def _eps_factor(fs_df) -> Dict:
    """EPS 因子：TTM EPS vs 前一年 TTM EPS 成長。需 ≥8 季（且 _ttm 內建連續性檢查），否則不適用。
    P1 fix #9：前期 TTM EPS<0（虧損）時，舊寫法一律 g=None→0 分，讓「虧轉盈」跟「雙虧損擴大」
    拿一樣的最差分數，不合理。改為：虧轉盈→2 分；雙虧損但收斂（|now|<|prev|）→1 分；
    雙虧損擴大或持平→0 分。前期為正時維持原本的成長率評分（_score_growth）。"""
    eps = _series(fs_df, "EPS")
    if not eps:
        return _na("無 EPS 科目")
    keys = sorted(eps.keys())
    now, prev = _ttm(eps, keys, 0), _ttm(eps, keys, 4)
    if now is None or prev is None or prev == 0:
        return _na("EPS 樣本不足（需 8 季連續）")
    if prev < 0:
        if now > 0:
            return _factor(2, True, f"TTM EPS {now:.1f} vs 前 {prev:.1f}（由虧轉盈）")
        if now < 0 and abs(now) < abs(prev):
            return _factor(1, True, f"TTM EPS {now:.1f} vs 前 {prev:.1f}（虧損收斂）")
        return _factor(0, True, f"TTM EPS {now:.1f} vs 前 {prev:.1f}（虧損擴大或持平）")
    g = now / prev - 1
    return _factor(_score_growth(g), True, f"TTM EPS {now:.1f} vs 前 {prev:.1f}")


def _revenue_factor(rev_df) -> Dict:
    """營收因子：月營收最新月 YoY。"""
    yoy = _latest_month_yoy(rev_df)
    if yoy is None:
        return _na("月營收資料缺或基期無效")
    return _factor(_score_growth(yoy), True, f"最新月 YoY {yoy*100:+.1f}%")


def _roe_factor(roe: Optional[float]) -> Dict:
    """ROE 水準：>15%→2、8~15%→1、<8%→0。缺 → 不適用。"""
    if roe is None:
        return _na("無法計算 ROE（缺淨利或權益）")
    score = 2 if roe > 0.15 else 1 if roe >= 0.08 else 0
    return _factor(score, True, f"ROE {roe*100:.1f}%")


def _streak_bonus(fs_df) -> int:
    """連續改善加減分：TTM 營收近 3 期趨勢。連 2 期增 +1、連 3 期增 +2；反向對稱 -1/-2。"""
    rev = _series(fs_df, "Revenue")
    if not rev:
        return 0
    keys = sorted(rev.keys())
    ttms = [_ttm(rev, keys, off) for off in (2, 1, 0)]  # 舊 → 新
    if any(v is None for v in ttms):
        return 0
    if ttms[2] > ttms[1] > ttms[0]:
        return 2
    if ttms[2] > ttms[1]:
        return 1
    if ttms[2] < ttms[1] < ttms[0]:
        return -2
    if ttms[2] < ttms[1]:
        return -1
    return 0


def compute_fundamentals(inp: Dict) -> Dict:
    """財報品質分數（見計畫 §介面契約 2）。純規則、缺科目降級不扣分。"""
    fs_df = inp.get("fs_df")
    bs_df = inp.get("bs_df")
    cf_df = inp.get("cf_df")
    rev_df = inp.get("rev_df")
    industry = inp.get("industry_category")

    roe = compute_roe(fs_df, bs_df)
    rev_series = _series(fs_df, "Revenue")
    gp_series = _series(fs_df, "GrossProfit")
    oi_series = _series(fs_df, "OperatingIncome")

    factors = {
        "revenue": _revenue_factor(rev_df),
        "eps": _eps_factor(fs_df),
        "gross_margin": _margin_factor(gp_series, rev_series, "毛利率"),
        "operating_margin": _margin_factor(oi_series, rev_series, "營益率"),
        "roe": _roe_factor(roe),
        "fcf": _fcf_factor(cf_df),
        "debt": _debt_factor(bs_df, industry),
    }

    applicable = [f for f in factors.values() if f["applicable"]]
    max_score = 2 * len(applicable)
    raw = sum(f["score"] for f in applicable)
    bonus = _streak_bonus(fs_df)
    total = max(0, min(max_score, raw + bonus)) if max_score > 0 else 0
    pct = round(total / max_score, 3) if max_score > 0 else None

    return {
        "total": total, "max": max_score, "pct": pct,
        "streak_bonus": bonus, "roe_value": roe, "factors": factors,
        "note": "7 因子各 0-2 分；缺科目標不適用不扣分；連續改善另加減分",
    }
