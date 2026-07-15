"""P1 終審修復 #4：批次入口（update.py 直接呼叫 analyze()，不經 __main__）也要落
recommendation_log，且不能因此重複落。用 mock 隔絕真 API（fetch/stock_name/
stock_industry/market），只驗證 log_recommendation 被呼叫一次。
"""
import unittest
from unittest.mock import patch

import warroom.analyze_tw as analyze_tw


class TestAnalyzeLogsRecommendation(unittest.TestCase):
    def test_analyze_calls_log_recommendation_exactly_once(self):
        # 模擬「所有資料源皆缺」的降級路徑（analyze_tw 對此已有既定的缺資料降級行為），
        # 重點只驗證：直接呼叫 analyze()（update.py 的用法）就會落一筆 log，且只落一次。
        with patch.object(analyze_tw, "fetch", return_value={}), \
             patch.object(analyze_tw, "stock_name", return_value="測試股"), \
             patch.object(analyze_tw, "stock_industry", return_value=None), \
             patch("warroom.market.fetch_market", return_value={"light": "amber"}), \
             patch("warroom.track_record.log_recommendation") as mock_log:
            res = analyze_tw.analyze("9999", with_news=False)

        mock_log.assert_called_once()
        called_res, called_today = mock_log.call_args[0]
        self.assertEqual(called_res["stock_id"], "9999")
        self.assertIsInstance(called_today, str)
        self.assertEqual(res["stock_id"], "9999")

    def test_analyze_logging_failure_does_not_crash(self):
        # log_recommendation 若拋例外（例如寫檔失敗），analyze() 仍要正常回傳結果，不 crash。
        with patch.object(analyze_tw, "fetch", return_value={}), \
             patch.object(analyze_tw, "stock_name", return_value="測試股"), \
             patch.object(analyze_tw, "stock_industry", return_value=None), \
             patch("warroom.market.fetch_market", return_value={"light": "amber"}), \
             patch("warroom.track_record.log_recommendation", side_effect=RuntimeError("boom")):
            res = analyze_tw.analyze("9999", with_news=False)
        self.assertEqual(res["stock_id"], "9999")


if __name__ == "__main__":
    unittest.main()
