"""POST /api/track 測試：mock urllib（不打真 GitHub API），涵蓋契約 v1.1
「新 API：POST /api/track」節五種結果——格式錯 404、idempotent 200、新增 201、
滿 20 檔 409、GitHub 失敗 503。"""
import base64
import json
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError

from api import track


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


class TestRunTrackMissingToken(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
    def test_missing_gh_pat_raises_unavailable(self):
        with self.assertRaises(track._Unavailable):
            track.run_track("2603")


@patch.dict("os.environ", {"GH_PAT": "fake-token"})
class TestRunTrackIdempotent(unittest.TestCase):
    @patch("api.track.urlopen")
    def test_already_tracked_returns_ok_already(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResp(_gh_get_response(["2330", "2603"]))
        result = track.run_track("2603")
        self.assertEqual(result, {"ok": True, "already": True})
        # idempotent 命中：只該打一次 GET，不該再 PUT 回寫
        self.assertEqual(mock_urlopen.call_count, 1)


@patch.dict("os.environ", {"GH_PAT": "fake-token"})
class TestRunTrackAppend(unittest.TestCase):
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
class TestRunTrackListFull(unittest.TestCase):
    @patch("api.track.urlopen")
    def test_list_at_20_raises_list_full(self, mock_urlopen):
        stocks = [str(2000 + i) for i in range(20)]
        mock_urlopen.return_value = _FakeResp(_gh_get_response(stocks))
        with self.assertRaises(track._ListFull):
            track.run_track("2603")
        # 沒 append、沒 PUT
        self.assertEqual(mock_urlopen.call_count, 1)


@patch.dict("os.environ", {"GH_PAT": "fake-token"})
class TestRunTrackGithubFailure(unittest.TestCase):
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

    def _make_handler(self, body: bytes):
        h = track.handler.__new__(track.handler)
        h.rfile = MagicMock()
        h.rfile.read.return_value = body
        h.headers = {"Content-Length": str(len(body))}
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


if __name__ == "__main__":
    unittest.main()
