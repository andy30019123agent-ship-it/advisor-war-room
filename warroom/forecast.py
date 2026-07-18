"""機率扇形圖預估走勢（規格：docs/contracts/data-contract-v1.md「v1.2 增補」）。

GBM（幾何布朗運動）蒙地卡羅：drift=0（不假裝知道方向）、vol＝EWMA(λ=0.94，近 250 根
日 K 對數報酬)、n=2000 條路徑、63 個交易日、每 3 個交易日取樣一點（含 d=0 與 d=63）。
seed 由 stock_id＋data_date 的穩定 hash 決定（同日重跑結果一致；不用內建 hash()——它
跨行程不穩，見 https://docs.python.org/3/reference/datamodel.html#object.__hash__ 的
PYTHONHASHSEED 說明）。價格樣本 <120 根日 K → 整組回 None（契約硬規則：缺資料給
null，不編數字）。scenarios 直接引用 valuation 的 fair_value（bear/base/bull），不另算。
"""
import hashlib
from typing import Dict, Optional

import numpy as np
import pandas as pd

MIN_BARS = 120
EWMA_LAMBDA = 0.94
EWMA_WINDOW = 250
N_PATHS = 2000
HORIZON_DAYS = 63
SAMPLE_STEP_DAYS = 3
TRADING_DAYS_PER_YEAR = 252

DISCLAIMER = "統計推算（歷史波動隨機模擬），非方向預測；突發事件不在模型內。"


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


def build_forecast(price_df, valuation: Optional[Dict], data_date: str,
                    stock_id: str) -> Optional[Dict]:
    """price_df 需含 date/close 欄位（未排序也可，內部會排序）。valuation 為
    warroom.valuation.compute_valuation() 的輸出（讀其 fair_value.bear/base/bull）。
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
    z = rng.standard_normal((N_PATHS, HORIZON_DAYS))
    # drift=0 的 GBM：日對數報酬 ~ N(-0.5·σ²，σ²)（-0.5σ² 是 GBM 本身的凸性修正項，
    # 不是額外假設方向；純粹讓 log-price 隨機漫步而不偏多偏空）。向量化一次算完，不逐條迴圈。
    daily_log_ret = -0.5 * daily_vol ** 2 + daily_vol * z
    cum_log_ret = np.cumsum(daily_log_ret, axis=1)
    paths = s0 * np.exp(cum_log_ret)  # shape (N_PATHS, HORIZON_DAYS)，欄 i＝第 i+1 個交易日

    def _round(x) -> float:
        return round(float(x), 2)

    bands = [{"d": 0, "p10": _round(s0), "p25": _round(s0), "p50": _round(s0),
              "p75": _round(s0), "p90": _round(s0)}]
    for d in range(SAMPLE_STEP_DAYS, HORIZON_DAYS + 1, SAMPLE_STEP_DAYS):
        prices_d = paths[:, d - 1]
        p10, p25, p50, p75, p90 = np.percentile(prices_d, [10, 25, 50, 75, 90])
        bands.append({"d": d, "p10": _round(p10), "p25": _round(p25), "p50": _round(p50),
                      "p75": _round(p75), "p90": _round(p90)})

    horizon_prices = paths[:, HORIZON_DAYS - 1]
    p15, p85 = np.percentile(horizon_prices, [15, 85])

    fair = (valuation or {}).get("fair_value") or {}
    scenarios = {"bear": fair.get("bear"), "base": fair.get("base"), "bull": fair.get("bull")}

    return {
        "method": "monte_carlo_gbm",
        "horizon_days": HORIZON_DAYS,
        "n_paths": N_PATHS,
        "vol_annualized": round(vol_annualized, 4),
        "as_of": data_date,
        "bands": bands,
        "scenarios": scenarios,
        "prob_range_70": [_round(p15), _round(p85)],
        "disclaimer": DISCLAIMER,
    }
