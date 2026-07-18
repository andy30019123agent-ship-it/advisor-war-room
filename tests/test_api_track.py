"""POST /api/track 測試：mock urllib（不打真 GitHub API），涵蓋契約 v1.1
「新 API：POST /api/track」節結果——格式錯 404、代號不存在 404、代號查不了 503、
idempotent 200、新增 201、滿 20 檔 409、限流 429、Origin 不符 403、GitHub 失敗 503。

大部分測試預設代號「存在」（patch `_check_stock_exists` 回 True），聚焦驗證各自要測的
那段邏輯；代號存在性本身的行為由 TestRunTrackStockExistence 專門測。"""
import base64
import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError

from api import track


class _RunTrackTestCase(unittest.TestCase):
    """共用 setUp：預設代號「存在」、略過限流，讓各測試專注在自己要驗的那段邏輯
    （代號存在性本身由 TestRunTrackStockExistence 測；限流本身由 TestRateLimit 測）。"""

    def setUp(self):
        super().setUp()
        p_exists = patch("api.track._check_stock_exists", return_value=True)
        p_rate = patch("api.track._rate_limit_ok", return_value=True)
        p_exists.start()
        p_rate.start()
        self.addCleanup(p_exists.stop)
        self.addCleanup(p_rate.stop)


def _gh_get_response(stocks):
    """組出 GitHub contents API GET 回應該有的 payload（base64 內容 + sha）。"""
    content = json.dumps({"_comment": "x", "stocks": stocks}, ensure_ascii=False)
    return {
        "sha": "abc123sha",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }


class _FakeResp:
    """urlopen() 回傳物件的最小替身：context manager + .read()。"""

    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


class TestRunTrackFormatValidation(unittest.TestCase):
    def test_invalid_format_rejected_before_any_network_call(self):
        # 不合法代號連 GH_PAT 檢查都不該碰到——直接在 handler 層擋掉，
        # 這裡驗證 run_track 本身不是格式驗證點的邊界：由 handler 的 regex 負責。
        self.assertFalse(track._STOCK_ID_RE.match("abc"))
        self.assertFalse(track._STOCK_ID_RE.match("123"))
        self.assertFalse(track._STOCK_ID_RE.match("1234567"))
        self.assertTrue(track._STOCK_ID_RE.match("2603"))
        self.assertTrue(track._STOCK_ID_RE.match("123456"))


class TestRunTrackMissingToken(_RunTrackTestCase):
    @patch.dict("os.environ", {}, clear=True)
    def test_missing_gh_pat_raises_unavailable(self):
        with self.assertRaises(track._Unavailable):
            track.run_track("2603")


@patch.dict("os.environ", {"GH_PAT": "fake-token"})
class TestRunTrackIdempotent(_RunTrackTestCase):
    @patch("api.track.urlopen")
    def test_already_tracked_returns_ok_already(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResp(_gh_get_response(["2330", "2603"]))
        result = track.run_track("2603")
        self.assertEqual(result, {"ok": True, "already": True})
        # idempotent 命中：只該打一次 GET，不該再 PUT 回寫
        self.assertEqual(mock_urlopen.call_count, 1)


@patch.dict("os.environ", {"GH_PAT": "fake-token"})
class TestRunTrackAppend(_RunTrackTestCase):
    @patch("api.track.urlopen")
    def test_new_stock_appended_and_put_called(self, mock_urlopen):
        get_resp = _FakeResp(_gh_get_response(["2330"]))
        put_resp = _FakeResp({"content": {}})
        mock_urlopen.side_effect = [get_resp, put_resp]

        result = track.run_track("2603")

        self.assertEqual(
            result,
            {"ok": True, "pending": "次一交易日 14:30 起納入每日更新與防守價監控"},
        )
        self.assertEqual(mock_urlopen.call_count, 2)

        # 檢查 PUT 送出的 body：新代號有進 stocks、sha 有帶上、commit message 註明來源、token 沒外洩
        put_req = mock_urlopen.call_args_list[1][0][0]
        self.assertEqual(put_req.get_method(), "PUT")
        sent = json.loads(put_req.data.decode("utf-8"))
        self.assertEqual(sent["sha"], "abc123sha")
        self.assertIn("/api/track", sent["message"])
        decoded = json.loads(base64.b64decode(sent["content"]).decode("utf-8"))
        self.assertEqual(decoded["stocks"], ["2330", "2603"])
        self.assertNotIn("fake-token", json.dumps(sent))


@patch.dict("os.environ", {"GH_PAT": "fake-token"})
class TestRunTrackListFull(_RunTrackTestCase):
    @patch("api.track.urlopen")
    def test_list_at_20_raises_list_full(self, mock_urlopen):
        stocks = [str(2000 + i) for i in range(20)]
        mock_urlopen.return_value = _FakeResp(_gh_get_response(stocks))
        with self.assertRaises(track._ListFull):
            track.run_track("2603")
        # 沒 append、沒 PUT
        self.assertEqual(mock_urlopen.call_count, 1)


@patch.dict("os.environ", {"GH_PAT": "fake-token"})
class TestRunTrackGithubFailure(_RunTrackTestCase):
    @patch("api.track.urlopen")
    def test_get_http_error_raises_unavailable(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError("url", 500, "boom", {}, None)
        with self.assertRaises(track._Unavailable):
            track.run_track("2603")

    @patch("api.track.urlopen")
    def test_get_network_error_raises_unavailable(self, mock_urlopen):
        mock_urlopen.side_effect = URLError("network down")
        with self.assertRaises(track._Unavailable):
            track.run_track("2603")

    @patch("api.track.urlopen")
    def test_put_failure_raises_unavailable(self, mock_urlopen):
        get_resp = _FakeResp(_gh_get_response(["2330"]))
        mock_urlopen.side_effect = [get_resp, HTTPError("url", 409, "conflict", {}, None)]
        with self.assertRaises(track._Unavailable):
            track.run_track("2603")

    @patch("api.track.urlopen")
    def test_malformed_response_raises_unavailable(self, mock_urlopen):
        # sha 缺失／格式不對，不能讓後續 append/PUT 用到壞資料
        mock_urlopen.return_value = _FakeResp({"content": base64.b64encode(b"{}").decode()})
        with self.assertRaises(track._Unavailable):
            track.run_track("2603")


class TestHandlerStatusCodes(unittest.TestCase):
    """直接測 handler 的路由/狀態碼邏輯，繞開真的 socket，用 MagicMock 組 request。"""

    def _make_handler(self, body: bytes, headers=None):
        h = track.handler.__new__(track.handler)
        h.rfile = MagicMock()
        h.rfile.read.return_value = body
        h.headers = {"Content-Length": str(len(body)), **(headers or {})}
        h.wfile = MagicMock()
        h.send_response = MagicMock()
        h.send_header = MagicMock()
        h.end_headers = MagicMock()
        return h

    def _sent_json(self, h):
        written = b"".join(c.args[0] for c in h.wfile.write.call_args_list)
        return json.loads(written.decode("utf-8"))

    def test_invalid_format_returns_404(self):
        h = self._make_handler(json.dumps({"stock": "abc"}).encode("utf-8"))
        h.do_POST()
        h.send_response.assert_called_once_with(404)
        self.assertEqual(self._sent_json(h), {"error": "not_found"})

    def test_body_too_large_returns_404(self):
        big = json.dumps({"stock": "2" * 2000}).encode("utf-8")
        h = self._make_handler(big)
        h.do_POST()
        h.send_response.assert_called_once_with(404)

    @patch("api.track.run_track")
    def test_already_tracked_returns_200(self, mock_run):
        mock_run.return_value = {"ok": True, "already": True}
        h = self._make_handler(json.dumps({"stock": "2603"}).encode("utf-8"))
        h.do_POST()
        h.send_response.assert_called_once_with(200)

    @patch("api.track.run_track")
    def test_new_track_returns_201(self, mock_run):
        mock_run.return_value = {"ok": True, "pending": "..."}
        h = self._make_handler(json.dumps({"stock": "2603"}).encode("utf-8"))
        h.do_POST()
        h.send_response.assert_called_once_with(201)

    @patch("api.track.run_track")
    def test_list_full_returns_409(self, mock_run):
        mock_run.side_effect = track._ListFull()
        h = self._make_handler(json.dumps({"stock": "2603"}).encode("utf-8"))
        h.do_POST()
        h.send_response.assert_called_once_with(409)
        self.assertEqual(self._sent_json(h), {"error": "list_full"})

    @patch("api.track.run_track")
    def test_stock_not_found_returns_404(self, mock_run):
        # 代號查得到清單但確定不存在（stock_exists() 回 False）→ 404，不寫入
        mock_run.side_effect = track._NotFound("9999")
        h = self._make_handler(json.dumps({"stock": "9999"}).encode("utf-8"))
        h.do_POST()
        h.send_response.assert_called_once_with(404)
        self.assertEqual(self._sent_json(h), {"error": "not_found"})

    @patch("api.track.run_track")
    def test_rate_limited_returns_429(self, mock_run):
        mock_run.side_effect = track._RateLimited()
        h = self._make_handler(json.dumps({"stock": "2603"}).encode("utf-8"))
        h.do_POST()
        h.send_response.assert_called_once_with(429)
        self.assertEqual(self._sent_json(h), {"error": "rate_limited"})

    def test_mismatched_origin_returns_403_before_touching_run_track(self):
        with patch("api.track.run_track") as mock_run:
            h = self._make_handler(
                json.dumps({"stock": "2603"}).encode("utf-8"),
                headers={"Origin": "https://evil.example.com"},
            )
            h.do_POST()
            h.send_response.assert_called_once_with(403)
            self.assertEqual(self._sent_json(h), {"error": "forbidden"})
            mock_run.assert_not_called()

    @patch("api.track.run_track")
    def test_matching_origin_allowed(self, mock_run):
        mock_run.return_value = {"ok": True, "already": True}
        h = self._make_handler(
            json.dumps({"stock": "2603"}).encode("utf-8"),
            headers={"Origin": "https://advisor-war-room.vercel.app"},
        )
        h.do_POST()
        h.send_response.assert_called_once_with(200)

    @patch("api.track.run_track")
    def test_no_origin_header_allowed_curl_style(self, mock_run):
        # 沒有 Origin/Referer（curl／伺服器對呼叫）→ 放行，不是瀏覽器跨站請求
        mock_run.return_value = {"ok": True, "already": True}
        h = self._make_handler(json.dumps({"stock": "2603"}).encode("utf-8"))
        h.do_POST()
        h.send_response.assert_called_once_with(200)

    @patch("api.track.run_track")
    def test_unavailable_returns_503_without_leaking_token(self, mock_run):
        mock_run.side_effect = track._Unavailable("讀取失敗：帶有 fake-token 的內部訊息")
        h = self._make_handler(json.dumps({"stock": "2603"}).encode("utf-8"))
        h.do_POST()
        h.send_response.assert_called_once_with(503)
        body = self._sent_json(h)
        self.assertEqual(body, {"error": "暫時無法加入監控，請稍後再試"})
        self.assertNotIn("fake-token", json.dumps(body))

    def test_get_returns_405(self):
        h = track.handler.__new__(track.handler)
        h.wfile = MagicMock()
        h.send_response = MagicMock()
        h.send_header = MagicMock()
        h.end_headers = MagicMock()
        h.do_GET()
        h.send_response.assert_called_once_with(405)


# ---------- 代號存在性（run_track 直接測，不經 handler）----------
@patch.dict("os.environ", {"GH_PAT": "fake-token"})
@patch("api.track._rate_limit_ok", return_value=True)
class TestRunTrackStockExistence(unittest.TestCase):
    @patch("api.track._check_stock_exists", return_value=False)
    @patch("api.track.urlopen")
    def test_nonexistent_stock_raises_notfound_without_touching_github(
        self, mock_urlopen, mock_exists, mock_rate
    ):
        # stock_exists() 確定回 False → 直接 404，連 GitHub API 都不該碰
        with self.assertRaises(track._NotFound):
            track.run_track("9999")
        mock_urlopen.assert_not_called()

    @patch("api.track._check_stock_exists", return_value=None)
    @patch("api.track.urlopen")
    def test_unknown_existence_raises_unavailable_without_writing(
        self, mock_urlopen, mock_exists, mock_rate
    ):
        # 查不了（額度/網路問題，stock_exists() 回 None）→ 503，一樣不寫入
        with self.assertRaises(track._Unavailable):
            track.run_track("2603")
        mock_urlopen.assert_not_called()

    @patch("api.track._check_stock_exists", return_value=True)
    @patch("api.track.urlopen")
    def test_existing_stock_proceeds_to_github_lookup(self, mock_urlopen, mock_exists, mock_rate):
        mock_urlopen.return_value = _FakeResp(_gh_get_response(["2330", "2603"]))
        result = track.run_track("2603")
        self.assertEqual(result, {"ok": True, "already": True})


# ---------- Origin/Referer 檢查（單元測） ----------
class TestOriginAllowed(unittest.TestCase):
    def test_matching_origin_allowed(self):
        self.assertTrue(track._origin_allowed({"Origin": "https://advisor-war-room.vercel.app"}))

    def test_mismatched_origin_rejected(self):
        self.assertFalse(track._origin_allowed({"Origin": "https://evil.example.com"}))

    def test_no_origin_falls_back_to_referer(self):
        self.assertTrue(track._origin_allowed(
            {"Referer": "https://advisor-war-room.vercel.app/search"}))
        self.assertFalse(track._origin_allowed({"Referer": "https://evil.example.com/x"}))

    def test_no_origin_no_referer_allowed(self):
        # 非瀏覽器請求（curl／伺服器對呼叫）：單人工具不擋
        self.assertTrue(track._origin_allowed({}))


# ---------- /tmp 限流（單元測，隔離用 tmp 檔避免污染其他測試） ----------
class TestRateLimit(unittest.TestCase):
    def test_allows_up_to_max_then_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rate_limit.json")
            for _ in range(track._RATE_LIMIT_MAX_PER_HOUR):
                self.assertTrue(track._rate_limit_ok(path))
            # 第 11 次超過每小時上限 → False
            self.assertFalse(track._rate_limit_ok(path))

    def test_missing_file_starts_fresh(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "does_not_exist.json")
            self.assertTrue(track._rate_limit_ok(path))

    def test_run_track_raises_rate_limited_when_write_quota_exhausted(self):
        # 整合：run_track 一開頭就檢查限流（2026-07-18 大檢查 🟡3 起，閘門挪到最前面），
        # 額度用完該拋 _RateLimited，連 stock_exists()／GitHub GET 都不該碰到。
        with tempfile.TemporaryDirectory() as d, \
             patch.dict("os.environ", {"GH_PAT": "fake-token"}), \
             patch("api.track._check_stock_exists", return_value=True) as mock_exists, \
             patch("api.track._RATE_LIMIT_PATH", os.path.join(d, "rl.json")), \
             patch("api.track.urlopen") as mock_urlopen:
            # 先把限流額度打滿
            for _ in range(track._RATE_LIMIT_MAX_PER_HOUR):
                track._rate_limit_ok()
            mock_urlopen.return_value = _FakeResp(_gh_get_response(["2330"]))
            with self.assertRaises(track._RateLimited):
                track.run_track("2603")
            # 限流閘門在最前面：不該打到 stock_exists()，更不該打到 GitHub GET/PUT
            mock_exists.assert_not_called()
            mock_urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
