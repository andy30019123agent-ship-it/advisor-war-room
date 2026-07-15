"""Task D：事件日曆測試（假 JSON / DataFrame fixture，不打真 API）。"""
import unittest

import pandas as pd

from warroom.events import (
    build_ex_div_map, parse_earnings, parse_dividends, revenue_publish_events,
    macro_events, build_event_calendar, has_upcoming_event, event_risk_downgrade,
)


def make_div(rows):
    """rows: list of (announce, cash_ex_date, cash_amt)。"""
    return pd.DataFrame([{"date": a or "", "stock_id": "2892",
                          "AnnouncementDate": a or "", "CashExDividendTradingDate": ex or "",
                          "CashEarningsDistribution": amt} for (a, ex, amt) in rows])


class TestEvents(unittest.TestCase):
    def test_build_ex_div_map(self):
        df = make_div([("2026-05-01", "2026-07-24", 1.0),
                       ("2025-05-01", "2025-07-20", 0.9)])
        m = build_ex_div_map(df)
        self.assertEqual(m["2026-07-24"], 1.0)
        self.assertEqual(m["2025-07-20"], 0.9)

    def test_build_ex_div_map_empty(self):
        self.assertEqual(build_ex_div_map(None), {})
        self.assertEqual(build_ex_div_map(pd.DataFrame()), {})

    def test_parse_earnings_window(self):
        j = {"events": [
            {"id": "2317", "name": "鴻海", "date": "2026-07-16", "type": "法說會"},
            {"id": "1234", "name": "遠古", "date": "2026-06-01", "type": "法說會"},  # 過去
            {"id": "9999", "name": "太遠", "date": "2026-09-01", "type": "法說會"},  # 窗外
        ]}
        evs = parse_earnings(j, today="2026-07-15", horizon_days=14)
        ids = [e["stock_id"] for e in evs]
        self.assertIn("2317", ids)
        self.assertNotIn("1234", ids)
        self.assertNotIn("9999", ids)
        self.assertEqual(evs[0]["type"], "法說會")
        self.assertEqual(evs[0]["days_ahead"], 1)

    def test_parse_earnings_none(self):
        self.assertEqual(parse_earnings(None, "2026-07-15", 14), [])

    def test_parse_dividends_only_announced_future(self):
        df = make_div([
            ("2026-06-01", "2026-07-24", 1.2),   # 已公告、未來 → 收
            ("", "2026-07-25", 2.0),             # 未公告 → 濾掉
            ("2026-01-01", "2026-06-11", 3.0),   # 已公告但已過 → 濾掉
        ])
        evs = parse_dividends(df, name="第一金", today="2026-07-15", horizon_days=14)
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["date"], "2026-07-24")
        self.assertEqual(evs[0]["type"], "除息")
        self.assertIn("1.2", evs[0]["detail"])
        self.assertEqual(evs[0]["confidence"], "scheduled")

    def test_revenue_publish_rule(self):
        # 7/15 之後最近的「10 號」是 8/10（本月 10 號已過）
        evs = revenue_publish_events({"2330": "台積電"}, today="2026-07-15", horizon_days=30)
        self.assertTrue(any(e["date"] == "2026-08-10" for e in evs))
        # 窗口太短 → 無
        evs2 = revenue_publish_events({"2330": "台積電"}, today="2026-07-15", horizon_days=5)
        self.assertEqual(evs2, [])

    def test_macro_events_window(self):
        evs = macro_events(today="2026-07-15", horizon_days=20)
        types = {e["type"] for e in evs}
        self.assertTrue({"FOMC"} & types or {"CPI"} & types)
        for e in evs:
            self.assertIsNone(e["stock_id"])

    def test_build_event_calendar_sorted(self):
        j = {"events": [{"id": "2317", "name": "鴻海", "date": "2026-07-16", "type": "法說會"}]}
        div = make_div([("2026-06-01", "2026-07-24", 1.2)])
        cal = build_event_calendar(j, {"2892": ("第一金", div)},
                                   {"2330": "台積電"}, today="2026-07-15", horizon_days=14)
        dates = [e["date"] for e in cal["events"]]
        self.assertEqual(dates, sorted(dates))       # 依日期排序
        self.assertIn("除息僅顯示已公告者（未來除息可靠性 P0 未 100% 實測）", cal["degraded"])

    def test_has_upcoming_event(self):
        div = make_div([("2026-06-01", "2026-07-20", 1.0)])
        self.assertTrue(has_upcoming_event("2892", div, None, {}, "2026-07-15", 14))
        self.assertFalse(has_upcoming_event("2892", None, None, {}, "2026-07-15", 14))

    def test_has_upcoming_event_revenue_branch(self):
        # 今天 7/7（<10 號），下一次月營收公布＝7/10（本月 10 日前公布規則），落在窗口內
        # 手算：t.day=7<10 → pub=2026-07-10；_in_window("2026-07-10","2026-07-07",14) 為真
        self.assertTrue(
            has_upcoming_event("2330", None, None, {"2330": "台積電"}, "2026-07-07", 14))
        # stock_map 沒有該股 → 月營收分支不觸發（回歸死碼修復前的錯誤：空 stock_map 永遠 False）
        self.assertFalse(
            has_upcoming_event("2330", None, None, {}, "2026-07-07", 14))

    def test_event_risk_downgrade(self):
        # 事件前 + 高估值 + 籌碼弱 → 降一級
        r, note = event_risk_downgrade("買進", True, 0.9, "red")
        self.assertEqual(r, "試單")
        self.assertIn("事件前", note)
        # 條件不足 → 不降
        r2, note2 = event_risk_downgrade("買進", True, 0.5, "green")
        self.assertEqual(r2, "買進")
        self.assertEqual(note2, "")


if __name__ == "__main__":
    unittest.main()
