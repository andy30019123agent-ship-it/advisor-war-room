"""Task 3：個股報告渲染（真 data/2330.json，純函式繞過一致性閘門）。"""
import json
import unittest
from warroom.report_stock import render_stock_html
from warroom.track_record import compute_stats


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


class TestReportStock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = load("data/2330.json")
        cls.n = load("data/2330.narration.json")
        cls.stats = compute_stats(load("data/recommendation_log.json"))
        ev = load("data/events.json")["events"]
        cls.events = [e for e in ev if e["stock_id"] in ("2330", None)]
        cls.htm = render_stock_html(cls.d, cls.n, cls.stats, cls.events)

    def test_no_str_format_crash_and_viewport(self):
        self.assertIn('name="viewport"', self.htm)
        self.assertIn("width=device-width", self.htm)

    def test_decision_first_screen(self):
        # 動態對照 data 檔（data/*.json 會隨每次更新戰情室刷新，不可寫死快照值）
        dec = self.d["decision"]
        self.assertIn('class="rating"', self.htm)
        self.assertIn(dec["rating"], self.htm)
        self.assertIn(f'--p:{dec["confidence"]["total"]}%', self.htm)
        self.assertIn(dec["position"]["tier"], self.htm)

    def test_sections_present(self):
        for anchor in ('id="frames"', 'id="value"', 'id="entry"',
                       'id="signals"', 'id="quality"', 'id="inst"', 'id="team"'):
            self.assertIn(anchor, self.htm)

    def test_value_band_and_method_note(self):
        self.assertIn('class="band"', self.htm)
        fv = self.d["decision"].get("fair_value")
        if fv and fv.get("base") is not None:
            self.assertIn(str(fv["base"]), self.htm)       # fair_value.base（legend，動態）
        self.assertIn("方法", self.htm)                    # 估值方法說明必附
        self.assertIn("PER", self.htm.upper())

    def test_quality_seven_factors(self):
        for zh in ("營收", "EPS", "毛利率", "營益率", "ROE", "現金流", "負債"):
            self.assertIn(zh, self.htm)
        fq = self.d.get("fundamentals_quality", {})
        want = f'{fq.get("total")}/{fq.get("max")}'
        self.assertIn(want, self.htm.replace(" ", ""))     # total/max（動態）

    def test_institution_split(self):
        self.assertIn("外資", self.htm)
        groups = self.d["chips"]["breakdown"]["groups"]
        net = groups["外資"]["net_latest"]
        self.assertIn(f'{net/1000:+,.0f} 張', self.htm)    # zhang(net_latest)，動態
        div_note = self.d["chips"]["breakdown"].get("divergence_note")
        if div_note:
            self.assertIn(div_note, self.htm)

    def test_six_roles(self):
        for role in ("基本面分析師", "技術分析師", "消息分析師",
                     "風控長", "魔鬼代言人", "投資長"):
            self.assertIn(role, self.htm)

    def test_track_record_accumulating(self):
        self.assertIn("累積中", self.htm)                  # 目前 outcome 全 null

    def test_disclaimer_and_no_emoji_lights(self):
        self.assertIn("非投資建議", self.htm)
        for emo in ("🟢", "🟡", "🔴"):
            self.assertNotIn(emo, self.htm)                # 紅綠燈不得用 emoji
        self.assertIn("紅燈", self.htm)                    # 文字寫明燈號
