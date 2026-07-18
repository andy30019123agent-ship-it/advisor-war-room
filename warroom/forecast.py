"""機率扇形圖預估走勢 2.0（規格：docs/contracts/data-contract-v1.md「v1.2 增補」＋
「v1.3 增補」）。

GBM（幾何布朗運動）蒙地卡羅：drift=0（不假裝知道方向）、vol＝EWMA(λ=0.94，近 250 根
日 K 對數報酬)、n=2000 條路徑；一次模擬跑 126 個交易日，切三段 horizon（m1=21／
m3=63／m6=126），各自每 3 個交易日取樣一點（含 d=0）＋各自 prob_range_70（該
horizon 終點的 p15~p85）。week_range_70 另外抓 d=5（第 5 個交易日）的 p15~p85，
供週報連動用。history 是過去 63 個交易日的實際收盤（非模擬），同樣每 3 日取樣＋d=0，
供前端畫「已發生走勢」銜接扇形圖起點。

seed 由 stock_id＋data_date 的穩定 hash 決定（同日重跑結果一致；不用內建 hash()——它
跨行程不穩，見 https://docs.python.org/3/reference/datamodel.html#object.__hash__ 的
PYTHONHASHSEED 說明）。價格樣本 <120 根日 K → 整組回 None（契約硬規則：缺資料給
null，不編數字）。scenarios 直接引用 valuation 的 fair_value（bear/base/bull，錨在
m3，維持 v1.2 語意），不另算。

event_markers：取該股 evidence.events（呼叫端傳入，analyze 時機視 res["evidence"]
是否已組好）＋鄰專案 tw-earnings-calendar/data/latest.json（存在才讀，不存在跳過不
編）合併去重，只留 horizon 內（0≤d≤126）的事件；日期換算交易日 d 用「曆日×5/7 四捨
五入」的粗略近似（不是精確的台股交易日曆，註明近似）。

accuracy：本函式只回一個「樣本累積中」的預設值（此函式看不到 data/forecast_log.json
的歷史紀錄）；實際回填後的準確度統計由 warroom/build_snapshots.py 的 forecast_log
管線算好後覆蓋這個欄位（見該檔 build_forecast_accuracy()）。
"""
import hashlib
import json
import os
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

MIN_BARS = 120
EWMA_LAMBDA = 0.94
EWMA_WINDOW = 250
N_PATHS = 2000
HORIZONS = {"m1": 21, "m3": 63, "m6": 126}  # 交易日；契約 v1.3 三段 horizon，插入順序＝輸出順序
MAX_HORIZON_DAYS = max(HORIZONS.values())
WEEK_DAYS = 5
HISTORY_DAYS = 63
SAMPLE_STEP_DAYS = 3
TRADING_DAYS_PER_YEAR = 252
CAL_TO_TRADING_RATIO = 5 / 7  # 曆日→交易日粗略近似（不含國定假日調整）

# 未來事件來源②：法說會行事曆（姊妹專案；不存在則跳過，不編）。與 build_snapshots.py /
# analyze_tw.py 用同一相對路徑常數，三處保持一致。
EARNINGS_CALENDAR = "../tw-earnings-calendar/data/latest.json"

DISCLAIMER = "統計推算（零漂移歷史波動隨機模擬），非方向預測；突發事件不在模型內。"
_ACCURACY_NOTE = "樣本累積中：每天記錄預估區間，5 日後開始回填驗證"


def _stable_seed(stock_id: str, data_date: str) -> int:
    """穩定 seed：hashlib（跨行程/跨進程一致），不用內建 hash()。"""
    digest = hashlib.sha256(f"{stock_id}{data_date}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _ewma_daily_vol(log_returns: np.ndarray, lam: float = EWMA_LAMBDA) -> Optional[float]:
    """RiskMetrics 式 EWMA：var_t = λ·var_{t-1} + (1-λ)·r_t²，回最新一期日波動度。"""
    if len(log_returns) == 0:
        return None
    var = float(log_returns[0]) ** 2
    for r in log_returns[1:]:
        var = lam * var + (1 - lam) * float(r) ** 2
    if not np.isfinite(var) or var <= 0:
        return None
    return float(np.sqrt(var))


def _round(x) -> float:
    return round(float(x), 2)


def _bands_for_horizon(paths: np.ndarray, s0: float, days: int) -> List[Dict]:
    """單一 horizon 的 bands：d=0（現價）起、每 3 個交易日一點，含端點 d=days
    （HORIZONS 三個值皆為 3 的倍數，range 自然含端點，不需另外特判）。"""
    bands = [{"d": 0, "p10": _round(s0), "p25": _round(s0), "p50": _round(s0),
              "p75": _round(s0), "p90": _round(s0)}]
    for d in range(SAMPLE_STEP_DAYS, days + 1, SAMPLE_STEP_DAYS):
        prices_d = paths[:, d - 1]
        p10, p25, p50, p75, p90 = np.percentile(prices_d, [10, 25, 50, 75, 90])
        bands.append({"d": d, "p10": _round(p10), "p25": _round(p25), "p50": _round(p50),
                      "p75": _round(p75), "p90": _round(p90)})
    return bands


def _build_history(closes: np.ndarray) -> List[Dict]:
    """過去 63 個交易日實際收盤，每 3 日取樣＋d=0（即現價）。MIN_BARS=120 已保證
    closes 長度足夠回溯 63 天，idx<0 的防禦分支理論上不會走到。"""
    n = len(closes)
    history = []
    for d in range(-HISTORY_DAYS, 1, SAMPLE_STEP_DAYS):
        idx = n - 1 + d
        if idx < 0:
            continue
        history.append({"d": d, "close": _round(closes[idx])})
    return history


def _event_d(event_date: str, data_date: str) -> Optional[int]:
    """事件日期換算成距 data_date 的交易日數（曆日×5/7 四捨五入，近似值）。"""
    try:
        d0 = datetime.strptime(data_date[:10], "%Y-%m-%d")
        d1 = datetime.strptime(str(event_date)[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    return round((d1 - d0).days * CAL_TO_TRADING_RATIO)


def _build_event_markers(stock_id: str, data_date: str, events: Optional[List[Dict]],
                         calendar_path: Optional[str], max_days: int) -> List[Dict]:
    """合併①呼叫端傳入的 evidence.events、②法說會行事曆（只取該股），
    只留 0≤d≤max_days 的事件，去重＋依 d 排序。任一來源缺席都不編，graceful。"""
    seen = set()
    out = []

    def _add(date_str: str, label: str):
        if not date_str:
            return
        d = _event_d(date_str, data_date)
        if d is None or d < 0 or d > max_days:
            return
        date_iso = str(date_str)[:10]
        key = (date_iso, label)
        if key in seen:
            return
        seen.add(key)
        out.append({"d": d, "date": date_iso, "label": label})

    for ev in events or []:
        _add(ev.get("date"), ev.get("label") or ev.get("type") or "事件")

    if calendar_path and os.path.exists(calendar_path):
        try:
            with open(calendar_path, encoding="utf-8") as f:
                cal = json.load(f)
            for ev in cal.get("events") or []:
                if str(ev.get("id") or "") != str(stock_id):
                    continue
                _add(ev.get("date"), ev.get("type") or "事件")
        except Exception:
            pass

    out.sort(key=lambda e: (e["d"], e["label"]))
    return out


def build_forecast(price_df, valuation: Optional[Dict], data_date: str, stock_id: str,
                   events: Optional[List[Dict]] = None,
                   calendar_path: str = EARNINGS_CALENDAR) -> Optional[Dict]:
    """price_df 需含 date/close 欄位（未排序也可，內部會排序）。valuation 為
    warroom.valuation.compute_valuation() 的輸出（讀其 fair_value.bear/base/bull）。
    events 為該股 evidence.events（可為 None/[]，缺席時只靠法說會行事曆）。
    樣本不足、波動度算不出、現價非正 → 回 None（graceful，呼叫端不炸）。
    """
    if price_df is None or len(price_df) == 0 or not data_date or not stock_id:
        return None

    df = price_df.sort_values("date").reset_index(drop=True)
    closes = pd.to_numeric(df["close"], errors="coerce").dropna().to_numpy()
    if len(closes) < MIN_BARS:
        return None

    s0 = float(closes[-1])
    if s0 <= 0:
        return None

    log_returns = np.diff(np.log(closes))
    log_returns = log_returns[np.isfinite(log_returns)]
    log_returns = log_returns[-EWMA_WINDOW:]
    daily_vol = _ewma_daily_vol(log_returns)
    if daily_vol is None:
        return None
    vol_annualized = daily_vol * np.sqrt(TRADING_DAYS_PER_YEAR)

    seed = _stable_seed(stock_id, data_date)
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((N_PATHS, MAX_HORIZON_DAYS))
    # drift=0 的 GBM：日對數報酬 ~ N(-0.5·σ²，σ²)（-0.5σ² 是 GBM 本身的凸性修正項，
    # 不是額外假設方向；純粹讓 log-price 隨機漫步而不偏多偏空）。向量化一次算完，不逐條迴圈。
    daily_log_ret = -0.5 * daily_vol ** 2 + daily_vol * z
    cum_log_ret = np.cumsum(daily_log_ret, axis=1)
    paths = s0 * np.exp(cum_log_ret)  # shape (N_PATHS, MAX_HORIZON_DAYS)，欄 i＝第 i+1 個交易日

    horizons = {}
    for key, days in HORIZONS.items():
        bands = _bands_for_horizon(paths, s0, days)
        p15, p85 = np.percentile(paths[:, days - 1], [15, 85])
        horizons[key] = {"days": days, "bands": bands, "prob_range_70": [_round(p15), _round(p85)]}

    w15, w85 = np.percentile(paths[:, WEEK_DAYS - 1], [15, 85])

    # scenarios 直接引用 valuation 三情境（錨在 m3，維持 v1.2 語意），但估值有 warning
    # （Base 偏離現價過大、可能低估，不作為減碼依據）時，這裡不得把同一個悲觀原始值裸奔
    # 端到前端——primary_decision 已用同一個護欄壓抑減碼，forecast.scenarios 也一律回 null
    # （bear/base/bull 全 None，維持契約物件形狀，前端據此不畫線）。見大檢查・邏輯組 R1。
    fair = (valuation or {}).get("fair_value") or {}
    if (valuation or {}).get("warning"):
        scenarios = {"bear": None, "base": None, "bull": None}
    else:
        scenarios = {"bear": fair.get("bear"), "base": fair.get("base"), "bull": fair.get("bull")}

    event_markers = _build_event_markers(stock_id, data_date, events, calendar_path, MAX_HORIZON_DAYS)

    return {
        "method": "monte_carlo_gbm",
        "n_paths": N_PATHS,
        "vol_annualized": round(vol_annualized, 4),
        "as_of": data_date,
        "history": _build_history(closes),
        "horizons": horizons,
        "week_range_70": [_round(w15), _round(w85)],
        "scenarios": scenarios,
        "event_markers": event_markers,
        # 樣本統計還沒到（本函式看不到 forecast_log），先給預設值；
        # build_snapshots.build_forecast_accuracy() 會用真實回填結果覆蓋這欄。
        "accuracy": {"n_evaluated": 0, "hit_rate_70": None, "note": _ACCURACY_NOTE},
        "disclaimer": DISCLAIMER,
    }
