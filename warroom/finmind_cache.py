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
