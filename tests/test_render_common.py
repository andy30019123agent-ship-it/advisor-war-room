"""Task 2：共用渲染基元測試（純字串，不打網路）。"""
import unittest
from warroom import render_common as rc


class TestRenderCommon(unittest.TestCase):
    def test_css_has_master_tokens_not_naked_hex(self):
        css = rc.CSS
        for tok in ("--bg:#f0f0f3", "--surface:#fbfbfe", "--pink:#e8b4c0",
                    "--up:#087a46", "--down:#b82033", "--pink-ink:#6d3040"):
            self.assertIn(tok, css.replace(" ", ""))
        # 不得出現舊礦物版 acid lime / 銅色
        for banned in ("#C7F04A", "#c7f04a", "#A85C3A", "acid"):
            self.assertNotIn(banned, css)

    def test_head_has_viewport_and_fonts(self):
        h = rc.head("測試 標題")
        self.assertIn('name="viewport"', h)
        self.assertIn("width=device-width", h)
        self.assertIn("fonts.googleapis.com", h)
        self.assertIn("<title>測試 標題</title>", h)

    def test_confidence_gauge_reads_total(self):
        g = rc.confidence_gauge(58)
        self.assertIn("--p:58%", g)
        self.assertIn(">58<", g)

    def test_traffic_no_emoji(self):
        self.assertEqual(rc.traffic("red"), ("r", "紅燈"))
        self.assertEqual(rc.traffic("green"), ("g", "綠燈"))

    def test_zhang_and_pct(self):
        self.assertEqual(rc.zhang(-12416209), "-12,416 張")
        self.assertEqual(rc.zhang(1841069), "+1,841 張")
        self.assertEqual(rc.fmt_pct(0.679), "+67.9%")
        self.assertEqual(rc.fmt_pct(None), "—")

    def test_rfc_to_mmdd(self):
        self.assertEqual(rc.rfc_to_mmdd("Mon, 06 Jul 2026 07:00:00 GMT"), "07/06")
        self.assertEqual(rc.rfc_to_mmdd("garbage"), "")

    def test_svg_defs_no_emoji_icons(self):
        self.assertIn('id="i-chart"', rc.SVG_DEFS)
        self.assertIn('id="i-chevron"', rc.SVG_DEFS)

    def test_esc_html_entities(self):
        self.assertIn("&lt;", rc.esc("<tag>"))
        self.assertIn("&amp;", rc.esc("a & b"))

    def test_num_wraps_with_span(self):
        n = rc.num("2,420")
        self.assertIn('<span class="num">', n)
        self.assertIn("2,420", n)
        self.assertIn("</span>", n)

    def test_icon_uses_href_safely(self):
        i = rc.icon("i-chart")
        self.assertIn('href="#i-chart"', i)
        self.assertIn('class="icon"', i)

    def test_section_head_includes_title_and_icon(self):
        sh = rc.section_head("i-chart", "測試標題")
        self.assertIn("測試標題", sh)
        self.assertIn("i-chart", sh)
        self.assertIn('class="section-head"', sh)

    def test_disclaimer_handles_plain_and_html(self):
        d1 = rc.disclaimer("第一段", "第二段")
        self.assertIn("<p>第一段</p>", d1)
        self.assertIn("<p>第二段</p>", d1)
        self.assertIn('class="disclaimer"', d1)

    def test_disclaimer_inline_bold_not_escaped(self):
        # 迴歸：段落內嵌 <b> 要輸出成真標籤，不能被 esc 成 &lt;b&gt; 字面文字
        d = rc.disclaimer("前段<b>重點句</b>後段", "")
        self.assertIn("<b>重點句</b>", d)
        self.assertNotIn("&lt;b&gt;", d)
        self.assertNotIn("<p></p>", d)  # 空段落要略過


if __name__ == "__main__":
    unittest.main()
