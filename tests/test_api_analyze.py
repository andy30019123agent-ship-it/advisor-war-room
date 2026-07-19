"""GET /api/analyze 限流測試（2026-07-18 大檢查 🔴1：舊版完全沒有限流，換代號連續打
可以無限次觸發最壞情境 8~9 個 FinMind dataset 查詢，燒光額度／Vercel 執行時間）。

跟 api/track.py 同款 per-instance /tmp 計數設計：每 instance 每小時最多 30 次「冷查」
（快取沒命中、真的要打 FinMind 的查詢），快取命中不計數。這裡 mock 掉
_setup_lite_env／_read_cache／_rate_limit_ok，只驗證限流閘門本身的計數邏輯與
run_analyze／handler 的接線是否正確，不打真 FinMind。"""
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from api import analyze


# ---------- /tmp 限流計數邏輯（單元測，隔離用 tmp 檔避免污染其他測試） ----------
class TestRateLimit(unittest.TestCase):
    def test_allows_up_to_max_then_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            import os
            path = os.path.join(d, "rate_limit.json")
            for _ in range(analyze._RATE_LIMIT_MAX_PER_HOUR):
                self.assertTrue(analyze._rate_limit_ok(path))
            # 第 31 次超過每小時上限 → False
            self.assertFalse(analyze._rate_limit_ok(path))

    def test_missing_file_starts_fresh(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "does_not_exist.json")
            self.assertTrue(analyze._rate_limit_ok(path))


# ---------- run_analyze 接線：冷查才過限流閘門，快取命中不計數 ----------
class TestRunAnalyzeRateLimitWiring(unittest.TestCase):
    @patch("api.analyze._setup_lite_env")
    @patch("api.analyze._rate_limit_ok", return_value=False)
    @patch("api.analyze._read_cache", return_value=None)
    def test_cold_query_blocked_when_quota_exhausted(self, mock_read_cache, mock_rate, mock_setup):
        # 快取沒命中 + 限流額度用完 → 拋 _RateLimited，不該往下碰 FinMind（_setup_lite_env 不呼叫）
        with self.assertRaises(analyze._RateLimited):
            analyze.run_analyze("2603")
        mock_rate.assert_called_once()
        mock_setup.assert_not_called()

    @patch("api.analyze._rate_limit_ok")
    @patch("api.analyze._read_cache")
    def test_cache_hit_does_not_consume_rate_limit(self, mock_read_cache, mock_rate):
        # 快取命中：直接回快取內容，完全不碰限流閘門（同代號當天重複查不該扣額度）
        cached_payload = {"stock_id": "2603", "cached": True}
        mock_read_cache.return_value = cached_payload
        result = analyze.run_analyze("2603")
        self.assertEqual(result, cached_payload)
        mock_rate.assert_not_called()


# ---------- handler 層：429 狀態碼與回應文案 ----------
class TestHandlerRateLimited(unittest.TestCase):
    def _make_handler(self, query: str):
        h = analyze.handler.__new__(analyze.handler)
        h.path = f"/api/analyze?{query}"
        h.wfile = MagicMock()
        h.send_response = MagicMock()
        h.send_header = MagicMock()
        h.end_headers = MagicMock()
        return h

    def _sent_json(self, h):
        written = b"".join(c.args[0] for c in h.wfile.write.call_args_list)
        return json.loads(written.decode("utf-8"))

    @patch("api.analyze.run_analyze")
    def test_rate_limited_returns_429_with_chinese_message(self, mock_run):
        mock_run.side_effect = analyze._RateLimited()
        h = self._make_handler("stock=2603")
        h.do_GET()
        h.send_response.assert_called_once_with(429)
        self.assertEqual(self._sent_json(h), {"error": "查詢太頻繁，請稍後再試"})


class TestExposureGateFailClosed(unittest.TestCase):
    """實戰走查 🔴 任務 2：即時查詢的曝險閘門讀不到 daily.json 時要 fail-closed 回「禁止新增
    部位」，不能回 None（不受限）——否則 read 一出差錯就吐「試單 10 萬」違反禁新倉。"""
    def test_returns_banned_when_daily_json_unreadable(self):
        import os
        with patch("api.analyze._ROOT", "/no/such/dir"):
            self.assertEqual(analyze._lite_exposure_new_position(), "禁止新增部位")

    def test_reads_real_new_position_when_available(self):
        # 正常路徑：讀得到已部署 daily.json → 回其 exposure_guidance.new_position（三態之一）
        val = analyze._lite_exposure_new_position()
        self.assertIn(val, ("禁止新增部位", "僅限試單", "可正常布局"))


if __name__ == "__main__":
    unittest.main()
