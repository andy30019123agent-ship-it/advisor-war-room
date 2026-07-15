"""Task 4：週報渲染（離線純函式；market/us_sectors 用小假 dict，tw_sectors/個股用真檔）。"""
import json
import unittest
from warroom.build_weekly import render_weekly_html


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


class TestBuildWeekly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        n = load("data/weekly_narration.json")
        tw = load("data/tw_sectors.json")
        stocks = {sid: load("data/%s.json" % sid) for sid in n["stocks"]
                  if __import__("os").path.exists("data/%s.json" % sid)}
        market = {"light": "red", "items": [
            {"name": "加權", "value": "44,738", "wk": -3.9, "dot": "r"},
            {"name": "櫃買", "value": "407", "wk": -7.4, "dot": "r"}],
            "foreign": {"net_yi": -519, "date": "2026-07-14"}}
        us_sec = [{"tier": "lead", "group": "能源", "etf": "XLE", "m5": 6.8,
                   "m20": 3.1, "us_names": "XOM", "tw": "—"}]
        cls.ctx = {"n": n, "market": market, "us_sectors": us_sec,
                   "tw_sectors": tw, "stocks": stocks, "events_json": load("data/events.json")}
        cls.htm = render_weekly_html(cls.ctx)

    def test_viewport_and_title(self):
        self.assertIn('name="viewport"', self.htm)
        self.assertIn("戰情週報", self.htm)

    def test_first_screen(self):
        self.assertIn('class="rating"', self.htm)
        n = load("data/weekly_narration.json")
        self.assertIn(n["exposure"], self.htm)
        self.assertIn(f'--p:{n["risk_temp"] * 10}%', self.htm)  # risk_temp 動態（資料檔會隨每期更新）

    def test_stock_mini_cards(self):
        self.assertIn("2330", self.htm)
        self.assertIn("2454", self.htm)
        self.assertIn("減碼", self.htm)                    # 2330/2454 decision.rating

    def test_tw_sector_rotation(self):
        for g in ("軍工航太", "封裝測試", "散熱"):
            self.assertIn(g, self.htm)
        self.assertIn("領先", self.htm)                    # tier lead
        self.assertIn("落後", self.htm)                    # tier lag

    def test_no_mineral_palette(self):
        for banned in ("#C7F04A", "#A85C3A", "--acid", "--ox"):
            self.assertNotIn(banned, self.htm)

    def test_disclaimer(self):
        self.assertIn("非投資建議", self.htm)
