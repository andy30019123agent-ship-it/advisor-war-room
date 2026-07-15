"""戰績牆（規格 §3.3）：每次 analyze 落一筆建議 → recommendation_log.json；
5/20/60 交易日回填報酬、先到 target 或 stop、最大回撤；統計命中率／平均 R。
權重校準只落「建議」不自動套用（規格：每月一次、規則化、不手調 = 不即時改權重）。
純規則、缺資料降級不 crash。金額/報酬皆可揭露輸入。
"""
import json
import os
from datetime import datetime, timezone, timedelta
from typing import Callable, Dict, List, Optional

import pandas as pd

_TPE = timezone(timedelta(hours=8))
DEFAULT_LOG = "data/recommendation_log.json"
_EMPTY_OUTCOME = {"r5": None, "r20": None, "r60": None,
                  "hit": None, "hit_days": None, "max_drawdown": None}


def entry_from_res(res: Dict, today: str) -> Dict:
    """由 analyze 結果組一筆 log entry（見計畫 §介面契約 5）。缺欄以 None 帶過。"""
    dec = res.get("decision", {}) or {}
    fv = dec.get("fair_value") or {}
    stop = dec.get("stop") or {}
    conf = dec.get("confidence") or {}
    val = dec.get("valuation") or {}
    return {
        "logged_at": datetime.now(_TPE).isoformat(timespec="seconds"),
        "date": today, "stock_id": res.get("stock_id"), "name": res.get("name"),
        "price": dec.get("as_of_price"), "rating": dec.get("rating"),
        "fair_base": fv.get("base"), "stop": stop.get("price"),
        "rr": dec.get("risk_reward"), "confidence": conf.get("total"),
        "factors": {
            "fund_light": res.get("fundamental", {}).get("light"),
            "tech_light": res.get("technical", {}).get("light"),
            "chip_light": res.get("chips", {}).get("light"),
            "per_percentile": val.get("current_percentile"),
        },
        "outcome": dict(_EMPTY_OUTCOME),
    }


def _load(path: str) -> List[Dict]:
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def log_recommendation(res: Dict, today: str, path: str = DEFAULT_LOG) -> Dict:
    """落一筆建議。同一 (date, stock_id) 覆蓋（避免同日多次跑重複堆疊）。回該 entry。"""
    entry = entry_from_res(res, today)
    log = _load(path)
    log = [e for e in log if not (e.get("date") == entry["date"]
                                  and e.get("stock_id") == entry["stock_id"])]
    log.append(entry)
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return entry


def backfill_one(entry: Dict, future_df) -> Dict:
    """給該股『建議日之後』的日線（欄 date/close，選配 max/min），回 outcome。
    先到 target(fair_base) 或 stop 為準（同日觸及優先算 stop，保守）。"""
    out = dict(_EMPTY_OUTCOME)
    entry_price = entry.get("price")
    if entry_price in (None, 0) or future_df is None or len(future_df) == 0:
        return out
    df = future_df.sort_values("date").reset_index(drop=True)
    close = pd.to_numeric(df["close"], errors="coerce")
    high = pd.to_numeric(df["max"], errors="coerce") if "max" in df.columns else close
    low = pd.to_numeric(df["min"], errors="coerce") if "min" in df.columns else close

    for k, key in ((5, "r5"), (20, "r20"), (60, "r60")):
        if len(close) >= k and pd.notna(close.iloc[k - 1]):
            out[key] = round(float(close.iloc[k - 1]) / entry_price - 1, 4)

    stop, target = entry.get("stop"), entry.get("fair_base")
    worst = 0.0
    hit, hit_days = None, None
    for i in range(len(df)):
        lo_i, hi_i = low.iloc[i], high.iloc[i]
        if pd.notna(lo_i):
            worst = min(worst, float(lo_i) / entry_price - 1)
        if stop is not None and pd.notna(lo_i) and float(lo_i) <= stop:
            hit, hit_days = "stop", i + 1
            break
        if target is not None and pd.notna(hi_i) and float(hi_i) >= target:
            hit, hit_days = "target", i + 1
            break
    if hit is None and len(df) >= 5:
        hit = "none"
    out["hit"], out["hit_days"] = hit, hit_days
    out["max_drawdown"] = round(worst, 4)
    return out


def backfill_outcomes(log: List[Dict], price_lookup: Callable, min_days: int = 5) -> List[Dict]:
    """就地回填每筆 outcome。price_lookup(stock_id)->該股完整日線；取建議日之後的列。"""
    for e in log:
        if e.get("outcome", {}).get("hit") not in (None,):
            continue  # 已回填過（hit 已定）→ 跳過
        try:
            full = price_lookup(e["stock_id"])
            if full is None or len(full) == 0:
                continue
            f = full.sort_values("date")
            future_df = f[f["date"].astype(str) > str(e["date"])]
            if len(future_df) < min_days:
                continue
            e["outcome"] = backfill_one(e, future_df)
        except Exception:
            continue
    return log


def _realized_r(e: Dict) -> Optional[float]:
    """已實現 R：命中 target = rr（賺 rr 倍風險）；命中 stop = -1R；none 用 r20/風險粗估。"""
    hit = e.get("outcome", {}).get("hit")
    price, stop, base = e.get("price"), e.get("stop"), e.get("fair_base")
    if hit == "stop":
        return -1.0
    if hit == "target":
        if price and stop is not None and (price - stop) > 0 and base is not None:
            return round((base - price) / (price - stop), 2)
        return e.get("rr")
    return None


def compute_stats(log: List[Dict]) -> Dict:
    """命中率（target/(target+stop)）、平均 R、平均 20 日報酬、樣本數。未回填者不計。"""
    resolved = [e for e in log if e.get("outcome", {}).get("hit") in ("target", "stop")]
    rs = [_realized_r(e) for e in resolved]
    rs = [r for r in rs if r is not None]
    r20s = [e["outcome"]["r20"] for e in log
            if e.get("outcome", {}).get("r20") is not None]
    n_target = sum(1 for e in resolved if e["outcome"]["hit"] == "target")
    return {
        "resolved": len(resolved),
        "hit_rate": round(n_target / len(resolved), 4) if resolved else None,
        "avg_r": round(sum(rs) / len(rs), 4) if rs else None,
        "avg_r20": round(sum(r20s) / len(r20s), 4) if r20s else None,
        "total_logged": len(log),
    }


def calibrate_weights(log: List[Dict]) -> Dict:
    """規則化權重『建議』：以各面向綠燈時的平均 R 當貢獻度，正規化成權重。
    **只回建議、不自動套用**（applied=False）；規格要求每月一次、人工/排程審核後才調。"""
    contrib = {"fund": [], "tech": [], "chip": []}
    key_map = {"fund": "fund_light", "tech": "tech_light", "chip": "chip_light"}
    for e in log:
        r = _realized_r(e)
        if r is None:
            continue
        for w, k in key_map.items():
            if e.get("factors", {}).get(k) == "green":
                contrib[w].append(r)
    avg = {w: (sum(v) / len(v)) if v else 0.0 for w, v in contrib.items()}
    positives = {w: max(0.0, a) for w, a in avg.items()}
    s = sum(positives.values())
    if s > 0:
        suggested = {w: round(p / s, 3) for w, p in positives.items()}
    else:
        suggested = {"fund": 0.4, "tech": 0.3, "chip": 0.3}  # 資料不足 → 沿用現行權重
    return {
        "applied": False,
        "suggested": suggested,
        "current": {"fund": 0.4, "tech": 0.3, "chip": 0.3},
        "basis": {w: round(a, 3) for w, a in avg.items()},
        "note": "規則化建議值，每月一次人工/排程審核後才調整，不自動套用",
    }
