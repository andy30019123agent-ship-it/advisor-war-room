"""兩份投顧報告共用的渲染基元：MASTER token（唯一設計權威）+ 共用 CSS + 元件函式。
純函式、無網路、無副作用；HTML 以 f-string 組出，不經 str.format（故 CSS 用單括號）。"""
import html
from email.utils import parsedate_to_datetime


CSS = r"""<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+TC:wght@400;500;600;700;800&family=Nunito+Sans:wght@700;800;900&family=IBM+Plex+Mono:wght@500;600;700&display=swap');
:root{
  --bg:#f0f0f3;--surface:#fbfbfe;--soft:#f6f6f9;--pressed:#e7e7ec;--ink:#141823;--text:#262b38;--muted:#566071;--line:#d9d9e2;
  --accent:#6554d9;--accent-2:#7d4fc7;--accent-soft:#ece9ff;--pink:#e8b4c0;--pink-soft:#f7e8ec;--pink-pressed:#f2d8de;--pink-ink:#6d3040;--pink-line:#ddb8c2;--up:#087a46;--up-bg:#dff4e9;--down:#b82033;--down-bg:#fde4e8;--warn:#a06900;--warn-bg:#fff0cc;
  --shadow-extrude:10px 10px 22px #c9c9d0,-10px -10px 22px #ffffff;
  --shadow-soft:6px 6px 14px #d0d0d7,-6px -6px 14px #ffffff;
  --shadow-inset:inset 6px 6px 12px #c9c9d0,inset -6px -6px 12px #ffffff;
  --sans:'IBM Plex Sans TC','PingFang TC',system-ui,sans-serif;--display:'Nunito Sans','IBM Plex Sans TC',system-ui,sans-serif;--mono:'IBM Plex Mono','SF Mono',ui-monospace,Menlo,monospace;
}
*{box-sizing:border-box} html{background:var(--bg)} body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);font-size:16px;line-height:1.68;letter-spacing:0;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
svg{display:block;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}.icon{width:20px;height:20px;flex:none}.num{font-family:var(--mono);font-variant-numeric:tabular-nums;font-weight:700}.up{color:var(--up)}.down{color:var(--down)}.muted{color:var(--muted)}
.page{max-width:1080px;margin:0 auto;padding:18px 16px 80px}.topbar{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;min-height:48px;color:var(--muted);font-family:var(--mono);font-size:12px;font-weight:700}.brand{display:inline-flex;align-items:center;gap:8px;color:var(--ink)}
.hero{display:grid;gap:18px;padding:20px 0 10px}.eyebrow,.chip,.pill{display:inline-flex;align-items:center;gap:8px;min-height:32px;width:max-content;max-width:100%;padding:5px 11px;border-radius:999px;background:var(--soft);box-shadow:var(--shadow-soft);color:var(--accent);font-family:var(--mono);font-size:12px;font-weight:700}.chip{color:var(--text);box-shadow:none;background:var(--pressed)}.chip.up,.pill.up{color:var(--up)}.chip.down,.pill.down{color:var(--down)}
h1{margin:0;color:var(--ink);font-family:var(--display);font-size:38px;line-height:1.08;font-weight:900;text-wrap:balance}.lead{margin:0;max-width:70ch;color:var(--muted);line-height:1.75}.meta{display:flex;flex-wrap:wrap;gap:8px}
.card{background:var(--surface);border-radius:16px;box-shadow:var(--shadow-extrude);padding:20px}.flat{background:var(--soft);border-radius:12px;padding:14px}.decision{margin-top:18px}.decision .eyebrow{background:var(--pink-soft);color:var(--pink-ink);box-shadow:var(--shadow-soft)}.decision-grid{display:grid;gap:18px}.rating{display:inline-block;margin:10px 0 8px;padding-bottom:4px;color:var(--ink);font-family:var(--display);font-size:56px;line-height:1;font-weight:900;background:linear-gradient(transparent 70%,var(--pink-pressed) 70%)}.reason{margin:0;color:var(--text);line-height:1.75}.note{display:flex;gap:8px;align-items:flex-start;margin-top:12px;min-height:44px;padding:12px;border-radius:12px;background:var(--accent-soft);color:#28215f}.confidence{position:relative;display:grid;place-items:center;min-height:148px;border-radius:16px;background:linear-gradient(145deg,var(--bg),var(--pink-soft));box-shadow:var(--shadow-inset);text-align:center;overflow:hidden}.confidence::before{content:"";position:absolute;inset:16px;border-radius:50%;background:conic-gradient(from 225deg,var(--pink) 0 var(--p,72%),var(--pressed) var(--p,72%) 100%);filter:saturate(.82);opacity:.72}.confidence::after{content:"";position:absolute;inset:26px;border-radius:50%;background:var(--bg);box-shadow:var(--shadow-inset)}.confidence>div{position:relative;z-index:1}.confidence b{display:block;color:var(--ink);font-family:var(--mono);font-size:34px}.confidence span{display:block;color:var(--muted);font-family:var(--mono);font-size:12px;font-weight:700}.kpis{display:grid;gap:12px;margin-top:16px}.kpi{min-height:76px;padding:14px;border-radius:14px;background:var(--soft)}.kpi small{display:block;color:var(--muted);font-family:var(--mono);font-size:12px;font-weight:700}.kpi strong{display:block;margin-top:6px;color:var(--ink);font-size:20px;line-height:1.28}
.jump{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}.jump a{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:9px 12px;border-radius:999px;background:var(--surface);box-shadow:var(--shadow-soft);color:var(--text);text-decoration:none;font-family:var(--mono);font-size:12px;font-weight:700;transition:background-color .18s ease,color .18s ease,box-shadow .18s ease}.jump a:hover{background:var(--pink-soft);color:var(--pink-ink);box-shadow:3px 3px 9px #d8c8cd,-3px -3px 9px #ffffff}
section{margin-top:32px}.section-head{display:flex;align-items:center;gap:10px;margin-bottom:14px}.mark{display:grid;place-items:center;width:36px;height:36px;border-radius:50%;background:var(--pink-soft);box-shadow:var(--shadow-soft);color:var(--pink-ink)}h2{margin:0;color:var(--ink);font-family:var(--display);font-size:24px;line-height:1.25;font-weight:900;text-wrap:balance}h3{margin:0 0 8px;color:var(--ink);font-size:18px;line-height:1.35}.grid{display:grid;gap:14px}.time p,.conditions p,.voice p,.source{margin:0}.tags{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}.tag{display:inline-flex;align-items:center;min-height:32px;padding:5px 10px;border-radius:999px;background:var(--pressed);color:var(--text);font-family:var(--mono);font-size:12px;font-weight:700}
.band{position:relative;height:28px;border-radius:999px;background:linear-gradient(90deg,var(--down-bg) 0 30%,var(--warn-bg) 30% 64%,var(--up-bg) 64%);box-shadow:var(--shadow-inset)}.band i{position:absolute;left:45%;top:-10px;width:4px;height:48px;border-radius:99px;background:var(--pink-ink);box-shadow:0 0 0 6px var(--pink-soft)}.legend{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:12px;color:var(--muted);font-family:var(--mono);font-size:12px}.legend b{display:block;color:var(--ink);font-size:16px}.source{margin-top:12px;color:var(--muted);font-size:14px;line-height:1.65}
.rr{display:grid;gap:12px}.rr .flat small{display:block;color:var(--muted);font-family:var(--mono);font-weight:700}.rr strong{display:block;margin-top:4px;font-family:var(--mono);font-size:26px}.conditions ul{margin:0;padding-left:20px}.conditions li{margin:6px 0}.invalid{display:grid;gap:10px;margin-top:14px}.invalid div{min-height:44px;padding:12px;border-radius:12px;background:var(--soft)}.invalid b{color:var(--ink)}
.lights{display:grid;gap:14px}.light{display:grid;gap:10px}.light-head{display:flex;align-items:center;justify-content:space-between;gap:10px}.dot{width:12px;height:12px;border-radius:50%;display:inline-block}.dot.g{background:var(--up)}.dot.r{background:var(--down)}.dot.y{background:var(--warn)}.evidence{display:flex;flex-wrap:wrap;gap:8px}.evidence span{min-height:32px;padding:5px 10px;border-radius:999px;background:var(--pressed);font-family:var(--mono);font-size:12px;font-weight:700;color:var(--text)}
.quality{display:grid;gap:10px}.factor{display:grid;grid-template-columns:minmax(72px,1fr) 94px 32px;gap:8px;align-items:center}.bar{height:12px;border-radius:999px;background:var(--pressed);box-shadow:var(--shadow-inset);overflow:hidden}.bar i{display:block;height:100%;background:var(--up)}.score{text-align:right;color:var(--ink);font-family:var(--mono);font-weight:700}.inst{display:grid;gap:12px}.inst-item{display:grid;grid-template-columns:72px 1fr;gap:10px;align-items:center}.inst-item b{color:var(--ink)}.split-note{display:inline-flex;align-items:center;min-height:32px;margin-top:10px;padding:4px 10px;border-radius:999px;background:var(--warn-bg);color:var(--warn);font-family:var(--mono);font-size:12px;font-weight:700}
.voice h3{color:var(--accent-2)}details{border:0;border-radius:16px;background:var(--surface);box-shadow:var(--shadow-extrude);overflow:hidden}summary{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:56px;padding:13px 16px;cursor:pointer;list-style:none;color:var(--ink);font-weight:800}summary::-webkit-details-marker{display:none}summary:focus-visible,.jump a:focus-visible{outline:3px solid var(--pink);outline-offset:3px}.details-body{display:grid;gap:10px;padding:0 16px 16px}.news a,.event,.hit{display:grid;gap:4px;min-height:44px;padding:12px;border-radius:12px;background:var(--soft);color:var(--text);text-decoration:none}.date{color:var(--pink-ink);font-family:var(--mono);font-size:12px;font-weight:700}
.weekly{background:#f8f8ff}.weekly-row{display:grid;gap:12px}.weekly-row div{padding:14px;border-radius:12px;background:var(--soft)}footer{margin-top:32px}.disclaimer{padding:16px;border-radius:14px;background:var(--pressed);color:#303545;font-size:14px;line-height:1.65}
@media (min-width:760px){.page{padding:28px 32px 96px}.hero{grid-template-columns:1.1fr .9fr;align-items:end}h1{font-size:58px}.decision-grid{grid-template-columns:1.25fr 180px;align-items:stretch}.kpis,.grid.three,.rr,.lights,.inst,.weekly-row{grid-template-columns:repeat(3,minmax(0,1fr))}.grid.two,.team{grid-template-columns:repeat(2,minmax(0,1fr))}.invalid{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:420px){.page{padding-left:16px;padding-right:16px}.card{padding:18px}.rating{font-size:48px}h1{font-size:34px}.factor{grid-template-columns:1fr 86px 28px}.inst-item{grid-template-columns:1fr}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;transition-duration:.01ms!important}}
</style>"""

SVG_DEFS = r"""<svg width="0" height="0" aria-hidden="true">
<symbol id="i-chart" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M4 19V5"/><path d="M4 19h16"/><path d="m7 15 4-5 3 3 5-7"/></symbol>
<symbol id="i-shield" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 3 20 7v6c0 5-3.5 7.5-8 8-4.5-.5-8-3-8-8V7l8-4Z"/><path d="m9 12 2 2 4-5"/></symbol>
<symbol id="i-check" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M20 6 9 17l-5-5"/></symbol>
<symbol id="i-calendar" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M7 3v4"/><path d="M17 3v4"/><path d="M4 8h16"/><rect x="4" y="5" width="16" height="16" rx="2"/></symbol>
<symbol id="i-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="m6 9 6 6 6-6"/></symbol>
</svg>"""


def esc(s):
    """HTML 轉義。"""
    return html.escape(str(s))


def num(x):
    """數字 span（mono + tabular-nums）。"""
    return '<span class="num">' + esc(x) + '</span>'


def icon(symbol_id, cls="icon"):
    """內聯 SVG icon 使用 href。"""
    return '<svg class="' + cls + '"><use href="#' + esc(symbol_id) + '"/></svg>'


def head(title, viewport=True):
    """頁面 head 區（viewport + title + CSS + SVG_DEFS）。"""
    vp = '<meta name="viewport" content="width=device-width, initial-scale=1">' if viewport else ""
    return vp + "<title>" + esc(title) + "</title>\n" + CSS + "\n" + SVG_DEFS


def section_head(symbol_id, title):
    """區塊小標（粉色 icon 圓點 + h2）。"""
    return ('<div class="section-head"><span class="mark">' + icon(symbol_id)
            + '</span><h2>' + esc(title) + '</h2></div>')


_LIGHT = {"green": ("g", "綠燈"), "amber": ("y", "黃燈"), "red": ("r", "紅燈")}


def traffic(light):
    """紅綠燈：回傳 (dot_cls, zh_label)。"""
    return _LIGHT.get(light, ("y", "黃燈"))


def confidence_gauge(total):
    """信心儀表（凹面 + conic 進度 + 中心圓）。"""
    t = int(round(total or 0))
    return ('<div class="confidence" style="--p:' + str(t) + '%"><div><b>' + str(t)
            + '</b><span>信心度 / 100</span></div></div>')


def disclaimer(*paragraphs):
    """免責 footer（支援混合 HTML 與純文字段落）。"""
    body = "".join("<p>" + esc(p) + "</p>" if not p.startswith("<") else p for p in paragraphs)
    return '<footer><div class="disclaimer">' + body + "</div></footer>"


def fmt_pct(x, signed=True):
    """百分比格式（帶正負號或去）。"""
    if x is None:
        return "—"
    return ("{:+.1f}%" if signed else "{:.1f}%").format(x * 100)


def zhang(net_shares):
    """股數轉張數字串（如 -12416209→"-12,416 張"）。"""
    if net_shares is None:
        return "—"
    return "{:+,} 張".format(int(round(net_shares / 1000)))


def rfc_to_mmdd(date_str):
    """RFC2822 日期轉 MM/DD（如 "Mon, 06 Jul 2026…"→"07/06"）。"""
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.strftime("%m/%d")
    except Exception:
        return ""
