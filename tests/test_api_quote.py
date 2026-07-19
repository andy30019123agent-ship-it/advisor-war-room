"""GET /api/quote 測試（契約 v1.7「新 API：GET /api/quote」節）。mock 掉 urlopen，
不打真 MIS；is_trading_window 用 patch 控制盤中/盤外分支，不依賴跑測試當下的實際時間。"""
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from api import quote


def _mis_response(items):
    """組一個假 MIS json 回應（urlopen().read() 要回 bytes）。"""
    body = json.dumps({"msgArray": items}).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def _item(sid, z="100.0000", y="98.0000", t="10:32:05"):
    return {"c": sid, "z": z, "y": y, "t": t}


class TestParseQuote(unittest.TestCase):
    def test_normal_item(self):
        out = quote._parse_quote(_item("2330", z="2295.0000", y="2290.0000", t="10:32:05"))
        self.assertEqual(out["price"], 2295.0)
        self.assertAlmostEqual(out["change_pct"], round((2295 / 2290 - 1) * 100, 2))
        self.assertEqual(out["at"], "10:32")
        self.assertFalse(out["stale"])

    def test_invalid_z_is_stale_null(self):
        out = quote._parse_quote(_item("2330", z="-"))
        self.assertIsNone(out["price"])
        self.assertIsNone(out["change_pct"])
        self.assertTrue(out["stale"])

    def test_missing_z_is_stale_null(self):
        out = quote._parse_quote({"c": "2330", "y": "98.0"})
        self.assertIsNone(out["price"])
        self.assertTrue(out["stale"])

    def test_invalid_y_gives_null_change_pct_but_price_present(self):
        out = quote._parse_quote(_item("2330", z="100.0", y="-"))
        self.assertEqual(out["price"], 100.0)
        self.assertIsNone(out["change_pct"])
        self.assertFalse(out["stale"])


class TestRunQuoteDuringTradingWindow(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        patcher_cache = patch.object(quote, "_CACHE_DIR", self._tmpdir.name)
        patcher_cache.start()
        self.addCleanup(patcher_cache.stop)
        patcher_rl = patch.object(quote, "_RATE_LIMIT_PATH", self._tmpdir.name + "/rl.json")
        patcher_rl.start()
        self.addCleanup(patcher_rl.stop)
        patcher_tw = patch("warroom.alerts.is_trading_window", return_value=True)
        patcher_tw.start()
        self.addCleanup(patcher_tw.stop)

    @patch("api.quote.urlopen")
    def test_normal_single_market_query(self, mock_urlopen):
        mock_urlopen.return_value = _mis_response([_item("2330", z="2295.0000", y="2290.0000")])
        result = quote.run_quote(["2330"])
        self.assertFalse(result["2330"]["stale"])
        self.assertEqual(result["2330"]["price"], 2295.0)
        mock_urlopen.assert_called_once()  # 全部 tse 命中，不該再打 otc

    @patch("api.quote.urlopen")
    def test_mixed_otc_supplement_query(self, mock_urlopen):
        # 第一次（tse）只查到 2330；5347 查無資料（MIS 對查無代號回 c 為空字串的
        # placeholder），第二次（otc）補查到 5347。
        tse_resp = _mis_response([_item("2330", z="2295.0000", y="2290.0000"), {"c": "", "z": "-"}])
        otc_resp = _mis_response([_item("5347", z="169.0000", y="187.5000")])
        mock_urlopen.side_effect = [tse_resp, otc_resp]

        result = quote.run_quote(["2330", "5347"])
        self.assertEqual(mock_urlopen.call_count, 2)
        self.assertFalse(result["2330"]["stale"])
        self.assertFalse(result["5347"]["stale"])
        self.assertEqual(result["5347"]["price"], 169.0)
        # 第二次呼叫（otc 補查）ex_ch 只該帶查無資料的 5347，不重查已命中的 2330
        second_call_url = mock_urlopen.call_args_list[1].args[0].full_url
        self.assertIn("otc_5347.tw", second_call_url)
        self.assertNotIn("2330", second_call_url)

    @patch("api.quote.urlopen")
    def test_z_invalid_in_response_returns_stale_null(self, mock_urlopen):
        tse_resp = _mis_response([_item("2330", z="-")])
        otc_resp = _mis_response([{"c": "", "z": "-"}])
        mock_urlopen.side_effect = [tse_resp, otc_resp]
        result = quote.run_quote(["2330"])
        self.assertIsNone(result["2330"]["price"])
        self.assertTrue(result["2330"]["stale"])

    @patch("api.quote.urlopen")
    def test_cache_hit_skips_upstream_call(self, mock_urlopen):
        mock_urlopen.return_value = _mis_response([_item("2330", z="2295.0000", y="2290.0000")])
        first = quote.run_quote(["2330"])
        mock_urlopen.reset_mock()
        second = quote.run_quote(["2330"])
        mock_urlopen.assert_not_called()
        self.assertEqual(first, second)

    @patch("api.quote.urlopen")
    def test_rate_limited_when_quota_exhausted(self, mock_urlopen):
        with patch.object(quote, "_rate_limit_ok", return_value=False):
            with self.assertRaises(quote._RateLimited):
                quote.run_quote(["2330"])
        mock_urlopen.assert_not_called()


class TestRunQuoteOutsideTradingWindow(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        patcher_cache = patch.object(quote, "_CACHE_DIR", self._tmpdir.name)
        patcher_cache.start()
        self.addCleanup(patcher_cache.stop)

    @patch("api.quote.urlopen")
    def test_returns_stale_without_calling_upstream(self, mock_urlopen):
        with patch("warroom.alerts.is_trading_window", return_value=False):
            result = quote.run_quote(["2330", "2454"])
        mock_urlopen.assert_not_called()
        for sid in ("2330", "2454"):
            self.assertIsNone(result[sid]["price"])
            self.assertTrue(result[sid]["stale"])


class TestHandler(unittest.TestCase):
    def _make_handler(self, query: str):
        h = quote.handler.__new__(quote.handler)
        h.path = f"/api/quote?{query}"
        h.wfile = MagicMock()
        h.send_response = MagicMock()
        h.send_header = MagicMock()
        h.end_headers = MagicMock()
        return h

    def _sent_json(self, h):
        written = b"".join(c.args[0] for c in h.wfile.write.call_args_list)
        return json.loads(written.decode("utf-8"))

    def test_too_many_ids_returns_400(self):
        ids = ",".join(str(2330 + i) for i in range(13))  # 13 檔，超過上限 12
        h = self._make_handler(f"ids={ids}")
        h.do_GET()
        h.send_response.assert_called_once_with(400)
        self.assertEqual(self._sent_json(h), {"error": "too_many_ids"})

    def test_invalid_id_format_returns_400(self):
        h = self._make_handler("ids=2330,abc")
        h.do_GET()
        h.send_response.assert_called_once_with(400)
        self.assertEqual(self._sent_json(h), {"error": "invalid_ids"})

    def test_empty_ids_returns_400(self):
        h = self._make_handler("ids=")
        h.do_GET()
        h.send_response.assert_called_once_with(400)

    @patch("api.quote.run_quote")
    def test_rate_limited_returns_429(self, mock_run):
        mock_run.side_effect = quote._RateLimited()
        h = self._make_handler("ids=2330")
        h.do_GET()
        h.send_response.assert_called_once_with(429)
        self.assertEqual(self._sent_json(h), {"error": "查詢太頻繁，請稍後再試"})

    @patch("api.quote.run_quote")
    def test_happy_path_returns_200(self, mock_run):
        mock_run.return_value = {"2330": {"price": 2295.0, "change_pct": 0.2, "at": "10:32", "stale": False}}
        h = self._make_handler("ids=2330")
        h.do_GET()
        h.send_response.assert_called_once_with(200)
        self.assertEqual(self._sent_json(h)["2330"]["price"], 2295.0)

    @patch("api.quote.run_quote")
    def test_unexpected_exception_returns_503(self, mock_run):
        mock_run.side_effect = RuntimeError("boom")
        h = self._make_handler("ids=2330")
        h.do_GET()
        h.send_response.assert_called_once_with(503)


if __name__ == "__main__":
    unittest.main()
