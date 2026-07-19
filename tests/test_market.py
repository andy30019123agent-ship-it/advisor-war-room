"""warroom/market.py 測試：外資合計端點改走 cached_fetch（2026-07-19 維運修復），不再繞過
直接呼叫 DataLoader 方法。用假 cached_fetch／DataLoader／yfinance 全離線跑，不打真網路。"""
import unittest
from unittest.mock import patch

import pandas as pd

from warroom import market


class TestFetchMarketInstitutionalCache(unittest.TestCase):
    def _fake_cached_fetch(self, method, loader=None, **kw):
        self.calls.append(method)
        if method == "taiwan_stock_daily":
            return pd.DataFrame({"date": ["2026-07-17", "2026-07-18"],
                                 "close": [100.0, 101.0]})
        if method == "taiwan_stock_institutional_investors_total":
            return pd.DataFrame({"date": ["2026-07-18"], "name": ["Foreign_Investor"],
                                 "buy": [1e9], "sell": [2e8]})
        return pd.DataFrame()

    def test_institutional_endpoint_routes_through_cached_fetch(self):
        """2026-07-19 修復重現條件：原本這行直接呼叫 dl.taiwan_stock_institutional_
        investors_total(...)，繞過同檔其他呼叫都用的 cached_fetch，導致 fetch_market()
        在管線裡被呼叫兩次時，這個端點（唯一實測出現過 5 分鐘延遲的端點）也被真的打兩次。
        改走 cached_fetch 後，方法名必須出現在 cached_fetch 的呼叫紀錄裡，而不是繞過去
        直接命中 loader 物件本身的方法。"""
        self.calls = []
        with patch("warroom.market.DataLoader", return_value=object()), \
             patch("warroom.finmind_cache.cached_fetch", side_effect=self._fake_cached_fetch), \
             patch("warroom.market.yf.Ticker", side_effect=RuntimeError("no net in test")):
            result = market.fetch_market()

        self.assertIn("taiwan_stock_institutional_investors_total", self.calls)
        self.assertIsNotNone(result["foreign"])
        self.assertEqual(result["foreign"]["net_yi"], 8.0)  # (1e9 - 2e8) / 1e8

    def test_second_call_same_day_hits_cache_not_loader_again(self):
        """呼叫兩次 fetch_market()（同管線內 warroom.update 與 build_snapshots 各一次的
        情境）：走真正的 cached_fetch（不再整支被 mock），第二次應該命中同日快取，
        不再重打外資合計這個慢端點——直接用 warroom.finmind_cache.cached_fetch 的同日快取
        機制（tests/test_finmind_cache.py 已驗證過快取本身正確），這裡只驗證 market.py
        真的把呼叫送進了這套快取，而不是繞過它。"""
        institutional_hits = []

        class FakeLoader:
            def taiwan_stock_daily(self, **kw):
                return pd.DataFrame({"date": ["2026-07-17", "2026-07-18"],
                                     "close": [100.0, 101.0]})

            def taiwan_stock_institutional_investors_total(self, **kw):
                institutional_hits.append(1)
                return pd.DataFrame({"date": ["2026-07-18"], "name": ["Foreign_Investor"],
                                     "buy": [1e9], "sell": [2e8]})

        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        try:
            fake = FakeLoader()
            from warroom import finmind_cache as fc
            original_cached_fetch = fc.cached_fetch  # 綁定原始函式，避免被 patch 後自呼叫遞迴

            def _cached_fetch_with_tmp_dir(method, loader=None, **kw):
                return original_cached_fetch(method, loader=loader, cache_dir=tmp, **kw)

            with patch("warroom.market.DataLoader", return_value=fake), \
                 patch("warroom.market.yf.Ticker", side_effect=RuntimeError("no net in test")), \
                 patch("warroom.finmind_cache.cached_fetch",
                       side_effect=_cached_fetch_with_tmp_dir):
                market.fetch_market()
                market.fetch_market()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        self.assertEqual(len(institutional_hits), 1)  # 第二次命中快取，沒有再打一次


if __name__ == "__main__":
    unittest.main()
