"""T1：investor_profile 落檔與讀取工具測試。"""
import json
import os
import unittest

from warroom.profile import load_profile, is_core_holding, position_tiers


class TestProfile(unittest.TestCase):
    def test_profile_file_exists_and_parses(self):
        prof = load_profile()
        self.assertIn("time_frames", prof)
        self.assertIn("stop_loss_range", prof)
        self.assertIn("position_tiers", prof)
        self.assertIn("core_holdings", prof)

    def test_time_frames_three_horizons(self):
        prof = load_profile()
        tf = prof["time_frames"]
        self.assertEqual(set(tf.keys()), {"short", "swing", "mid"})
        # 波段為主 rating
        self.assertTrue(tf["swing"]["is_primary"])
        self.assertFalse(tf["short"].get("is_primary", False))

    def test_stop_loss_range(self):
        prof = load_profile()
        r = prof["stop_loss_range"]
        # 可忍回撤 -8% ~ -15%
        self.assertAlmostEqual(r["max_pct"], -0.08)
        self.assertAlmostEqual(r["min_pct"], -0.15)

    def test_position_tiers_amounts(self):
        prof = load_profile()
        amounts = [t["amount"] for t in position_tiers(prof)]
        self.assertEqual(amounts, [0, 100000, 200000, 400000, 600000])
        names = [t["name"] for t in position_tiers(prof)]
        self.assertEqual(names, ["空手", "試單", "標準", "加碼", "極高信心"])

    def test_core_holdings(self):
        prof = load_profile()
        self.assertEqual(prof["core_holdings"], ["2330", "0050"])
        self.assertTrue(is_core_holding(prof, "2330"))
        self.assertFalse(is_core_holding(prof, "2454"))

    def test_load_profile_custom_path(self):
        # 自訂路徑亦可讀
        prof = load_profile("data/investor_profile.json")
        self.assertIsInstance(prof, dict)


if __name__ == "__main__":
    unittest.main()
