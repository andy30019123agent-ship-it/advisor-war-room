"""FinMind REST 直連（無 SDK）：serverless 專用的輕量 loader。

為什麼要有這支：真的 `FinMind` SDK（見 warroom/finmind_cache.py）會帶入
pyarrow/aiohttp/lxml/pyecharts/ipython/ta 等一堆用不到的重依賴（實測光 pyarrow
就 108MB），疊上 pandas/numpy 遠超 Vercel serverless 250MB 上限、也拖慢冷啟。
這支只用 stdlib（urllib + json）直接打 FinMind 公開 REST API v4，
回傳的 DataFrame 欄位跟真 SDK 完全一致（both 都是 `pd.DataFrame(resp["data"])`，
同一個 API、同一組欄位），所以 warroom/analyze_tw.py 等下游模組完全不用改。

用法：把單例塞進 warroom.finmind_cache._LOADER，get_loader() 就會直接回傳這支，
不會再去 import 真正的 FinMind SDK（見該檔 lazy-import 註解）。
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

import pandas as pd

_API_URL = "https://api.finmindtrade.com/api/v4/data"
_TIMEOUT = 8  # 秒／次；序列打 8~9 個 dataset，寧可個別快失敗，靠上層 partial degrade

# loader 方法名 → FinMind Dataset 名稱（照 FinMind.schema.data.Dataset 對照，
# 2026-07-18 讀 FinMind SDK 2.0.4 原始碼核對過）。
_DATASET = {
    "taiwan_stock_daily": "TaiwanStockPrice",
    "taiwan_stock_month_revenue": "TaiwanStockMonthRevenue",
    "taiwan_stock_per_pbr": "TaiwanStockPER",
    "taiwan_stock_institutional_investors": "TaiwanStockInstitutionalInvestorsBuySell",
    "taiwan_stock_dividend": "TaiwanStockDividend",
    "taiwan_stock_financial_statement": "TaiwanStockFinancialStatements",
    "taiwan_stock_balance_sheet": "TaiwanStockBalanceSheet",
    "taiwan_stock_cash_flows_statement": "TaiwanStockCashFlowsStatement",
    "taiwan_stock_info": "TaiwanStockInfo",
}


class FinMindRateLimited(Exception):
    """FinMind 額度用完／登入失效等「整體不可用」訊號，api/analyze.py 據此回 503。"""


class LiteLoader:
    """跟真 FinMind DataLoader 同名方法、同回傳格式的輕量替身。
    只實作 warroom/analyze_tw.py 實際用到的 9 個方法。"""

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.environ.get("FINMIND_TOKEN") or ""

    def _fetch(self, dataset: str, data_id: str = "", start_date: str = "",
              end_date: str = "") -> pd.DataFrame:
        params = {"dataset": dataset}
        if data_id:
            params["data_id"] = data_id
            params["stock_id"] = data_id  # v4 兩個參數名都吃，照 SDK 行為對齊
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if self.token:
            params["token"] = self.token
        url = f"{_API_URL}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "advisor-war-room/1.0 (personal research)",
        })
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                body = json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            # 402/429 常見於免 token 額度用完；訊息夾在 body 裡，能讀就讀
            try:
                body = json.loads(e.read().decode("utf-8", "replace"))
            except Exception:
                raise FinMindRateLimited(f"FinMind HTTP {e.code}") from e
            msg = str(body.get("msg") or body.get("detail") or body)
            raise FinMindRateLimited(f"FinMind HTTP {e.code}: {msg}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise FinMindRateLimited(f"FinMind 連線失敗: {e}") from e

        if "data" not in body:
            msg = str(body.get("msg") or body.get("detail") or body)
            if any(k in msg.lower() for k in ("limit", "token", "login")):
                raise FinMindRateLimited(f"FinMind API: {msg}")
            raise RuntimeError(f"FinMind API unexpected response: {msg}")
        return pd.DataFrame(body["data"])

    def taiwan_stock_daily(self, stock_id="", start_date="", end_date="", **_):
        return self._fetch(_DATASET["taiwan_stock_daily"], stock_id, start_date, end_date)

    def taiwan_stock_month_revenue(self, stock_id="", start_date="", end_date="", **_):
        return self._fetch(_DATASET["taiwan_stock_month_revenue"], stock_id, start_date, end_date)

    def taiwan_stock_per_pbr(self, stock_id="", start_date="", end_date="", **_):
        return self._fetch(_DATASET["taiwan_stock_per_pbr"], stock_id, start_date, end_date)

    def taiwan_stock_institutional_investors(self, stock_id="", start_date="", end_date="", **_):
        return self._fetch(_DATASET["taiwan_stock_institutional_investors"], stock_id, start_date, end_date)

    def taiwan_stock_dividend(self, stock_id="", start_date="", end_date="", **_):
        return self._fetch(_DATASET["taiwan_stock_dividend"], stock_id, start_date, end_date)

    def taiwan_stock_financial_statement(self, stock_id="", start_date="", end_date="", **_):
        return self._fetch(_DATASET["taiwan_stock_financial_statement"], stock_id, start_date, end_date)

    def taiwan_stock_balance_sheet(self, stock_id="", start_date="", end_date="", **_):
        return self._fetch(_DATASET["taiwan_stock_balance_sheet"], stock_id, start_date, end_date)

    def taiwan_stock_cash_flows_statement(self, stock_id="", start_date="", end_date="", **_):
        return self._fetch(_DATASET["taiwan_stock_cash_flows_statement"], stock_id, start_date, end_date)

    def taiwan_stock_info(self, timeout: int = None, **_):
        # 全市場清單（無 data_id），analyze_tw.stock_name/stock_industry 用 stock_id 篩選。
        return self._fetch(_DATASET["taiwan_stock_info"])
