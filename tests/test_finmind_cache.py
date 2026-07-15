"""T2：FinMind 同日快取 + token 支援測試（用假 loader，不打真 API）。"""
import os
import shutil
import tempfile
import unittest

import pandas as pd

from warroom.finmind_cache import cached_fetch


class FakeLoader:
    """假 DataLoader：記錄呼叫次數，回固定 DataFrame。"""

    def __init__(self):
        self.calls = 0

    def taiwan_stock_daily(self, stock_id, start_date):
        self.calls += 1
        return pd.DataFrame({"date": ["2026-07-14"], "stock_id": [stock_id],
                             "close": [100.0]})


class TestFinmindCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_first_call_hits_loader(self):
        fake = FakeLoader()
        df = cached_fetch("taiwan_stock_daily", loader=fake, cache_dir=self.tmp,
                          stock_id="2330", start_date="2025-01-01")
        self.assertEqual(fake.calls, 1)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["stock_id"], "2330")

    def test_second_same_day_call_uses_cache(self):
        fake = FakeLoader()
        kw = dict(stock_id="2330", start_date="2025-01-01")
        cached_fetch("taiwan_stock_daily", loader=fake, cache_dir=self.tmp, **kw)
        cached_fetch("taiwan_stock_daily", loader=fake, cache_dir=self.tmp, **kw)
        # 第二次應命中快取，不再呼叫 loader
        self.assertEqual(fake.calls, 1)

    def test_different_params_not_shared(self):
        fake = FakeLoader()
        cached_fetch("taiwan_stock_daily", loader=fake, cache_dir=self.tmp,
                     stock_id="2330", start_date="2025-01-01")
        cached_fetch("taiwan_stock_daily", loader=fake, cache_dir=self.tmp,
                     stock_id="2454", start_date="2025-01-01")
        # 不同參數各抓一次
        self.assertEqual(fake.calls, 2)


if __name__ == "__main__":
    unittest.main()
