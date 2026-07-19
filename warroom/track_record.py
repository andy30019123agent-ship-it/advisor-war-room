"""戰績牆（規格 §3.3）：每次 analyze 落一筆建議 → recommendation_log.json；
5/20/60 交易日回填報酬、先到 target 或 stop、最大回撤；統計命中率／平均 R。
權重校準只落「建議」不自動套用（規格：每月一次、規則化、不手調 = 不即時改權重）。
純規則、缺資料降級不 crash。金額/報酬皆可揭露輸入。

P1 終審修復重點：
- backfill_one：hit 終局規則改為「60 交易日到期或命中 target/stop 才終局」
  （hit ∈ target/stop/expired），未到期且未命中維持 None（pending），可持續補齊（fix #1）。
- log 檔壞掉時 fail-closed，不覆寫成只剩新 entry；寫入用 temp 檔 + os.replace 原子替換（fix #2）。
- 回填收盤價支援除權息還原（events.build_ex_div_map 同語意），避免除息跳空誤觸 stop
  或扭曲 r20/r60（fix #3）。
"""
import json
import os
import warnings
from datetime import datetime, timezone, timedelta
from typing import Callable, Dict, List, Optional

import pandas as pd

_TPE = timezone(timedelta(hours=8))
DEFAULT_LOG = "data/recommendation_log.json"
_EMPTY_OUTCOME = {"r5": None, "r20": None, "r60": None,
                  "hit": None, "hit_days": None, "max_drawdown": None,
                  "ex_div_adjusted": False}
_HIT_WINDOW_DAYS = 60  # 到期交易日數：超過仍未命中 target/stop → 終局為 expired


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
        # 建議當時的主時間框架（見 data/investor_profile.json time_frames.swing.is_primary）。
        # log 目前沒有真正的 per-timeframe 建議來源（B 包主動選股 short/swing/long 分類尚
        # 未接上這支 log），固定標「swing」；舊 entries 缺此欄位時 build_track_stats 的
        # 分層統計一律視同 swing（規格 v1.5：track_stats 分層）。
        "timeframe": "swing",
        "factors": {
            "fund_light": res.get("fundamental", {}).get("light"),
            "tech_light": res.get("technical", {}).get("light"),
            "chip_light": res.get("chips", {}).get("light"),
            "per_percentile": val.get("current_percentile"),
        },
        "outcome": dict(_EMPTY_OUTCOME),
    }


def _load(path: str) -> List[Dict]:
    """讀既有 log。檔案不存在 → []（正常初始狀態）。
    P1 fix #2：檔案存在但 JSON 壞掉 → 往上拋例外，讓呼叫端 fail-closed（不得吞掉後
    當作空清單，否則後續寫入會把壞檔覆寫成只剩這次新 entry，等於毀損既有戰績紀錄）。"""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def log_recommendation(res: Dict, today: str, path: str = DEFAULT_LOG) -> Dict:
    """落一筆建議。同一 (date, stock_id) 覆蓋（避免同日多次跑重複堆疊）。回該 entry。
    P1 fix #2：讀檔失敗（JSON 壞掉）時 fail-closed——跳過本次寫入並警告，不覆寫原檔；
    寫入改「寫 temp 檔 + os.replace 原子替換」，避免寫到一半或同時讀取看到半檔。"""
    entry = entry_from_res(res, today)
    try:
        log = _load(path)
    except Exception as ex:
        warnings.warn(
            f"recommendation_log 讀取失敗（{path}）：{type(ex).__name__} {ex}；"
            "本次跳過寫入，避免覆寫毀損既有紀錄（fail-closed）")
        return entry
    log = [e for e in log if not (e.get("date") == entry["date"]
                                  and e.get("stock_id") == entry["stock_id"])]
    log.append(entry)
    try:
        dirname = os.path.dirname(path) or "."
        os.makedirs(dirname, exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        pass
    return entry


def backfill_one(entry: Dict, future_df, ex_div_map: Optional[Dict] = None) -> Dict:
    """給該股『建議日之後』的日線（欄 date/close，選配 max/min），回 outcome。
    先到 target(fair_base) 或 stop 為準（同日觸及優先算 stop，保守）。

    終局規則（P1 fix #1）：60 交易日到期或命中 target/stop 才終局
    （hit ∈ target/stop/expired）；未到期（可用資料 <60 個交易日）且未命中 → 維持 None
    （pending），r5/r20/r60 到哪天補到哪天，之後可持續補齊，不會被提早鎖死。

    除權息還原（P1 fix #3）：ex_div_map={除息日: 每股配息}（見 events.build_ex_div_map），
    比對日還原＝該日 close/high/low 皆加回「當日起累計」的配息（與 decision_engine 的
    單日除息抑制同語意，只是延伸成整段回填窗口的累計版），避免除息機械跳空誤觸 stop
    或使 r20/r60 失真。ex_div_map=None（拿不到配息資料）→ 照舊不調整，
    outcome 附註 ex_div_adjusted=False；傳入 dict（含空 dict）→ 視為已嘗試調整，
    outcome 附註 ex_div_adjusted=True。
    """
    out = dict(_EMPTY_OUTCOME)
    entry_price = entry.get("price")
    if entry_price in (None, 0) or future_df is None or len(future_df) == 0:
        return out
    df = future_df.sort_values("date").reset_index(drop=True)
    close_raw = pd.to_numeric(df["close"], errors="coerce")
    high_raw = pd.to_numeric(df["max"], errors="coerce") if "max" in df.columns else close_raw
    low_raw = pd.to_numeric(df["min"], errors="coerce") if "min" in df.columns else close_raw

    ex_div_adjusted = ex_div_map is not None
    out["ex_div_adjusted"] = ex_div_adjusted
    if ex_div_adjusted and ex_div_map:
        div_per_day = df["date"].astype(str).map(lambda d: float(ex_div_map.get(d, 0.0)))
        cum_div = div_per_day.cumsum()
    else:
        cum_div = pd.Series([0.0] * len(df))
    close = close_raw + cum_div
    high = high_raw + cum_div
    low = low_raw + cum_div

    for k, key in ((5, "r5"), (20, "r20"), (60, "r60")):
        if len(close) >= k and pd.notna(close.iloc[k - 1]):
            out[key] = round(float(close.iloc[k - 1]) / entry_price - 1, 4)

    stop, target = entry.get("stop"), entry.get("fair_base")
    worst = 0.0
    hit, hit_days = None, None
    window = min(len(df), _HIT_WINDOW_DAYS)
    for i in range(window):
        lo_i, hi_i = low.iloc[i], high.iloc[i]
        if pd.notna(lo_i):
            worst = min(worst, float(lo_i) / entry_price - 1)
        if stop is not None and pd.notna(lo_i) and float(lo_i) <= stop:
            hit, hit_days = "stop", i + 1
            break
        if target is not None and pd.notna(hi_i) and float(hi_i) >= target:
            hit, hit_days = "target", i + 1
            break
    if hit is None and window >= _HIT_WINDOW_DAYS:
        hit = "expired"   # 60 個交易日到期仍未命中 target/stop → 終局但非命中
    out["hit"], out["hit_days"] = hit, hit_days
    out["max_drawdown"] = round(worst, 4)
    return out


def backfill_outcomes(log: List[Dict], price_lookup: Callable,
                      div_lookup: Optional[Callable] = None, min_days: int = 5) -> List[Dict]:
    """就地回填每筆 outcome。price_lookup(stock_id)->該股完整日線；取建議日之後的列。
    只跳過已終局（hit ∈ target/stop/expired）的筆；pending（hit=None）會持續重試，
    直到 60 交易日到期或命中為止（P1 fix #1）。
    div_lookup(stock_id)->該股股利 DataFrame（供 events.build_ex_div_map 用）；
    不給或該股拿不到配息資料 → 照舊不調整（P1 fix #3）。"""
    for e in log:
        if e.get("outcome", {}).get("hit") not in (None,):
            continue  # 已終局（target/stop/expired）→ 跳過；None（pending）才重試
        try:
            full = price_lookup(e["stock_id"])
            if full is None or len(full) == 0:
                continue
            f = full.sort_values("date")
            future_df = f[f["date"].astype(str) > str(e["date"])]
            if len(future_df) < min_days:
                continue
            ex_div_map = None
            if div_lookup is not None:
                try:
                    from warroom.events import build_ex_div_map
                    div_df = div_lookup(e["stock_id"])
                    ex_div_map = build_ex_div_map(div_df) if div_df is not None else None
                except Exception:
                    ex_div_map = None
            e["outcome"] = backfill_one(e, future_df, ex_div_map=ex_div_map)
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
    """命中率（target/resolved）、平均 R、平均 20 日報酬、樣本數。未回填（pending）者不計。
    P1 fix #1：resolved（終局樣本）改為 hit ∈ (target, stop, expired) 皆計入分母——
    舊版只認 target/stop，讓「60 天到期都沒中」的案例（原 "none"）整批消失於統計外，
    等於系統性剔除不利樣本、虛灌命中率。expired 不算命中（不進分子），
    但確實計入分母，才是誠實的命中率。"""
    resolved = [e for e in log if e.get("outcome", {}).get("hit") in ("target", "stop", "expired")]
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
