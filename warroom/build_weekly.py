"""一週兩次 top-down 戰情週報產生器：大盤→類股→個股→事件。
即時抓 market/sectors，讀個股引擎 JSON ＋ 我手寫的 weekly_narration.json → 產 reports/weekly.html。
白底柔和 neumorphism、可點擊開合。真實資料。
"""
import json, os, html
from datetime import datetime, timezone, timedelta
from warroom.market import fetch_market
from warroom.sectors import fetch_sectors

TPE = timezone(timedelta(hours=8))
LIGHT = {"green": ("g", "🟢", "偏多"), "amber": ("y", "🟡", "中性"), "red": ("r", "🔴", "偏空")}
DIRW = {"g": "var(--up)", "y": "var(--warn)", "r": "var(--down)"}


def esc(s): return html.escape(str(s))


def chg_cls(wk): return "up" if (wk or 0) > 0 else "down" if (wk or 0) < 0 else "muted"


def index_grid(items):
    cells = ""
    for i in items:
        wk = i["wk"]
        chg = f'{wk:+.1f}%' if wk is not None else "—"
        cells += f'''<div class="cell"><div class="lab"><span class="tl {i['dot']}"></span>{esc(i['name'])}</div>
          <div class="v">{esc(i['value'])}</div><div class="chg {chg_cls(wk)}">{chg} · 週</div></div>'''
    return f'<div class="grid">{cells}</div>'


def market_strip(items):
    """類股區頂端的『台美大盤現況』小摘要（複用大盤層已抓的指數）。"""
    chips = ""
    for i in items:
        wk = i.get("wk")
        pct = f'{wk:+.1f}%' if wk is not None else "—"
        chips += (f'<span class="mchip"><span class="tl {i["dot"]}"></span>'
                  f'<b>{esc(i["name"])}</b><span class="{chg_cls(wk)}">{pct}</span></span>')
    return (f'<div class="mktstrip"><div class="mstitle">台美大盤現況 · 週變化</div>'
            f'<div class="mchips">{chips}</div></div>')


def sector_rows(sectors):
    tierzh = {"lead": ("領先", "att"), "mid": ("中性", "hold"), "lag": ("落後", "avoid")}
    rows = ""
    for r in sectors:
        zh, cls = tierzh[r["tier"]]
        m5 = f'{r["m5"]:+.1f}%' if r["m5"] is not None else "—"
        m20 = f'{r["m20"]:+.1f}%' if r.get("m20") is not None else "—"
        rows += f'''<details class="srow"><summary>
            <span class="sname">{esc(r['group'])} <span class="etf">{esc(r['etf'])}</span></span>
            <span class="schg {chg_cls(r['m5'])}">{m5}</span><span class="tag {cls}">{zh}</span></summary>
          <div class="sdetail"><span>近5日 <b>{m5}</b></span><span>近20日 <b>{m20}</b></span>
            <span>美股代表 <b>{esc(r['us_names'])}</b></span><span style="flex-basis:100%">→ 台股對應：{esc(r['tw'])}</span></div></details>'''
    return rows


PUR_CLS = {"純": "hi", "中": "mid", "分散": "lo"}


def _theme_stock_list(stocks):
    rows = ""
    for s in stocks:
        pur = PUR_CLS.get(s.get("purity", ""), "mid")
        pure = '<span class="puresttag">最純</span>' if s.get("purest") else ""
        rows += (f'<div class="thstk{" pure" if s.get("purest") else ""}">'
                 f'<span class="thid">{esc(s.get("id","—"))}</span>'
                 f'<span class="thname">{esc(s.get("name",""))}</span>'
                 f'<span class="pur {pur}">{esc(s.get("purity","—"))}</span>{pure}'
                 f'<span class="thnote">{esc(s.get("note",""))}</span></div>')
    return rows


def theme_rows(themes, theme_stocks=None):
    theme_stocks = theme_stocks or {}
    st = {"成案": ("on", "成案"), "觀察": ("watch", "觀察")}
    rows = ""
    for t in themes:
        cls, zh = st.get(t["status"], ("watch", "觀察"))
        heat = f'{t["heat"]:+.0%}' if t.get("heat") is not None else "—"
        mom = f'{t["mom"]:+.1f}%' if t.get("mom") is not None else "—"
        stocks = theme_stocks.get(t["name"])
        head = f'''<div class="heat"><div class="z">{heat}</div><div class="zl">熱度趨勢</div></div>
          <div style="flex:1;min-width:0">
            <div class="tn">{esc(t['name'])}<span class="status {cls}">{zh}</span>{'<span class="thexp">個股 ▾</span>' if stocks else ''}</div>
            <div class="tmeta">領頭 {esc(t['lead'])} {mom} · 首見 {esc(t.get('first_seen',''))}</div>
            <div class="tnote">{esc(t['reason'])}</div>
          </div>'''
        if stocks:
            rows += f'''<details class="theme"><summary class="thsum">{head}</summary>
              <div class="thstocks">{_theme_stock_list(stocks)}</div></details>'''
        else:
            rows += f'<div class="theme">{head}</div>'
    return rows


def stock_card(sid, data, one_liner):
    s = data["summary"]
    lights = [data["fundamental"]["light"], data["technical"]["light"], data["chips"]["light"]]
    dircode = "g" if s["score"] > 0.3 else "r" if s["score"] < -0.3 else "y"
    dots = "".join(f'<span class="tl {LIGHT[l][0]}"></span>' for l in lights)
    evs = ""
    for key, zh in [("fundamental", "基本面"), ("technical", "技術面"), ("chips", "消息/籌碼")]:
        b = data[key]
        evs += f'<div class="mini"><span class="tl {LIGHT[b["light"]][0]}"></span>{zh} {LIGHT[b["light"]][2]}</div>'
    tev = data.get("technical", {}).get("ev", {})
    buy, res = tev.get("買入參考區"), tev.get("壓力參考位")
    lvls = ""
    if buy or res:
        lvls = (f'<div class="lvls">'
                f'<span class="lvl"><i>買入參考區</i>{esc(buy or "—")}</span>'
                f'<span class="lvl"><i>壓力參考位</i>{esc(res or "—")}</span></div>')
    return f'''<details class="stk">
      <summary>
        <div><span class="name">{esc(data['name'])}</span><span class="tick">{esc(sid)}</span>
          <div class="sublight">{dots}</div></div>
        <span class="verdict" style="color:{DIRW[dircode]};background:var(--{'up' if dircode=='g' else 'down' if dircode=='r' else 'neu'}-bg)">{esc(s['direction'])}</span>
      </summary>
      <div class="stkbody">
        <div class="lights">{evs}</div>
        {lvls}
        <p class="reason">{esc(one_liner)}</p>
        <div class="meta2">加權分 {s['score']} · 信心 {esc(s['confidence'])} · 技術位為規則參考非買賣建議</div>
      </div></details>'''


def build():
    m = fetch_market()
    sec = fetch_sectors()
    n = json.load(open("data/weekly_narration.json", encoding="utf-8"))
    stocks = {}
    for sid in n["stocks"]:
        p = f"data/{sid}.json"
        if os.path.exists(p):
            stocks[sid] = json.load(open(p, encoding="utf-8"))

    code, emo, zh = LIGHT[m["light"]]
    foreign = ""
    if m.get("foreign"):
        net = m["foreign"]["net_yi"]
        fdot = "g" if net > 0 else "r" if net < 0 else "y"
        fcls = "up" if net > 0 else "down" if net < 0 else "muted"
        foreign = f'<div class="cell"><div class="lab"><span class="tl {fdot}"></span>外資買賣超</div><div class="v">{net:+,.0f} 億</div><div class="chg {fcls}">{esc(m["foreign"]["date"])}</div></div>'

    stock_cards = "".join(stock_card(sid, stocks[sid], n["stocks"][sid]) for sid in stocks if sid in stocks)
    themes = json.load(open("data/themes.json", encoding="utf-8")) if os.path.exists("data/themes.json") else []
    theme_stocks = json.load(open("data/theme_stocks.json", encoding="utf-8")) if os.path.exists("data/theme_stocks.json") else {}
    events = "".join(f'<div class="ev"><div class="d">{esc(e["d"])}</div><div class="et"><b>{esc(e["t"])}</b><div class="mm">{esc(e["m"])}</div></div></div>' for e in n["events"])
    gen = datetime.now(TPE).strftime("%Y-%m-%d %H:%M")

    return TEMPLATE.format(
        period=esc(n["period"]), asof=esc(n["asof"]), gen=esc(gen),
        chief=esc(n["chief"]), direction=esc(n["direction"]), exposure=esc(n["exposure"]),
        conf=esc(n["confidence"]), risk=n["risk_temp"], risk_pct=n["risk_temp"] * 10,
        mkt_emo=emo, mkt_zh=zh, mkt_code=code,
        grid=index_grid(m["items"]) , foreign=foreign, market_say=esc(n["market"]),
        mktstrip=market_strip(m["items"]),
        sectors=sector_rows(sec), sector_say=esc(n["sector"]),
        stocks=stock_cards, themes=theme_rows(themes, theme_stocks), theme_say=esc(n.get("theme", "")), events=events,
    )


TEMPLATE = r"""<meta name="viewport" content="width=device-width, initial-scale=1">
<title>戰情週報 {period} · 專屬投顧戰情室</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+TC:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');

:root {{
  --paper:#EFF2EA; --paper2:#E4EADF; --surface:#FBFDF7; --surface2:#F5F8F0;
  --ink:#151713; --ink2:#30362C; --muted:#65705F; --faint:#647059;
  --rule:#D8E0D1; --rule-dk:#AEB9A5; --ox:#A85C3A; --ox2:#6E3D2B;
  --accent:#1A1D14; --acid:#C7F04A; --acid2:#E9FF9D;
  --up:#167A54; --up-bg:#E2F4EB; --down:#B64238; --down-bg:#F8E4E0;
  --warn:#8A5A14; --warn-bg:#F7EBCF; --neu:#5E6758; --neu-bg:#ECEFE6;
  --disp:'Space Grotesk','IBM Plex Sans TC','PingFang TC','Noto Sans TC',sans-serif;
  --text:'IBM Plex Sans TC','PingFang TC','Noto Sans TC',system-ui,sans-serif;
  --mono:'Space Grotesk','SF Mono',ui-monospace,Menlo,monospace;
}}
* {{ box-sizing:border-box; }}
html {{ background:var(--paper); }}
body {{
  margin:0; min-height:100vh; color:var(--ink2); font-family:var(--text);
  font-size:16px; line-height:1.68; letter-spacing:0; background:var(--paper);
  -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility;
}}
body::before {{
  content:""; position:fixed; inset:0 0 auto; height:8px; z-index:0; pointer-events:none;
  background:linear-gradient(90deg,var(--acid) 0 22%,var(--ox) 22% 34%,var(--accent) 34% 100%);
}}
.wrap {{ position:relative; z-index:1; max-width:860px; margin:0 auto; padding:48px 28px 92px; }}
.up {{ color:var(--up); }} .down {{ color:var(--down); }} .muted {{ color:var(--muted); }} .warn {{ color:var(--warn); }}

.smcap,.chieftag,.cell .lab,.kpi .t,.meterlab,.say .who,.meta2 {{
  font-family:var(--mono); font-size:11px; font-weight:700; letter-spacing:.08em; text-transform:uppercase;
}}
.real {{
  display:inline-flex; align-items:center; gap:9px; max-width:100%; color:var(--ink2);
  font-family:var(--mono); font-size:11px; font-weight:700; letter-spacing:.06em;
  padding:7px 10px; border:1px solid var(--rule-dk); border-radius:999px; background:rgba(251,253,247,.64);
}}
.real::before {{ content:""; width:7px; height:7px; border-radius:50%; background:var(--acid); box-shadow:0 0 0 3px rgba(199,240,74,.22); }}
.eyebrow {{ margin-top:26px; color:var(--ox2); font-family:var(--mono); font-size:12px; font-weight:700; letter-spacing:.05em; }}
h1 {{
  margin:10px 0 0; color:var(--ink); font-family:var(--disp); font-size:56px; line-height:.98;
  font-weight:700; letter-spacing:-.03em; text-wrap:balance;
}}
.meta {{ margin-top:16px; color:var(--muted); font-size:13px; font-family:var(--mono); letter-spacing:.02em; }}

.card {{
  position:relative; overflow:hidden; margin-top:30px; padding:28px; border-radius:8px;
  color:#EEF4E8; background:var(--accent); box-shadow:0 14px 34px rgba(21,23,19,.18);
}}
.card::before {{ content:""; position:absolute; inset:0 0 auto; height:5px; background:linear-gradient(90deg,var(--acid),var(--ox)); }}
.chieftag {{ color:var(--acid2); }}
.dir {{ margin:13px 0 0; color:#FBFDF7; font-family:var(--disp); font-size:34px; line-height:1.16; font-weight:700; letter-spacing:-.025em; text-wrap:balance; }}
.chief {{ max-width:70ch; margin:16px 0 0; color:#DDE6D5; font-size:16px; line-height:1.78; }}
.kpis {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin-top:24px; }}
.kpi {{ min-width:0; padding:14px; border-radius:8px; background:rgba(251,253,247,.08); }}
.kpi .t {{ color:#AEBBA5; }}
.kpi .b {{ display:flex; align-items:center; gap:8px; margin-top:7px; color:#FBFDF7; font-family:var(--disp); font-size:20px; font-weight:700; line-height:1.15; }}
.meterwrap {{ margin-top:20px; padding-top:4px; }}
.meterlab {{ display:flex; justify-content:space-between; margin-bottom:9px; color:#AEBBA5; }}
.num,.v,.chg,.schg {{ font-family:var(--mono); font-variant-numeric:tabular-nums; }}
.meterwrap .num,.meterlab .num {{ color:#FBFDF7; }}
.meter {{ position:relative; height:8px; border-radius:999px; background:linear-gradient(90deg,var(--up),var(--warn),var(--down)); }}
.meter i {{ position:absolute; top:-6px; width:4px; height:20px; border-radius:999px; background:#FBFDF7; box-shadow:0 0 0 2px rgba(21,23,19,.5); }}

details {{ border:0; }}
.wrap > details {{
  margin-top:18px; border:1px solid var(--rule); border-radius:8px; overflow:hidden; background:var(--surface);
}}
summary {{ list-style:none; cursor:pointer; user-select:none; transition:background .2s ease,color .2s ease; }}
summary::-webkit-details-marker {{ display:none; }}
summary:focus-visible {{ outline:3px solid color-mix(in srgb,var(--acid) 70%,transparent); outline-offset:3px; border-radius:8px; }}
.wrap > details > summary {{ display:flex; align-items:center; gap:14px; padding:18px 18px; }}
.wrap > details > summary:hover {{ background:var(--surface2); }}
.layerno {{
  display:grid; place-items:center; flex:none; width:42px; height:34px; border-radius:8px;
  color:var(--accent); background:var(--acid); font-family:var(--mono); font-size:16px; font-weight:700; line-height:1;
}}
summary h2 {{ min-width:0; margin:0; color:var(--ink); font-family:var(--disp); font-size:23px; line-height:1.18; font-weight:700; letter-spacing:-.02em; text-wrap:balance; }}
summary .lgt {{ margin-left:auto; display:inline-flex; align-items:center; gap:8px; color:var(--muted); font-family:var(--mono); font-size:12px; font-weight:700; white-space:nowrap; }}
.lgt .tl,.kpi .b .tl {{ width:9px; height:9px; }}
.chev {{ flex:none; width:20px; height:20px; color:var(--muted); transition:transform .22s cubic-bezier(.2,.8,.2,1), color .2s ease; }}
details[open] > summary .chev {{ transform:rotate(180deg); color:var(--ink); }}
.inner {{ padding:0 18px 22px; }}

.grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }}
.cell {{ min-width:0; padding:15px; border:1px solid var(--rule); border-radius:8px; background:var(--surface2); }}
.cell .lab {{ display:flex; align-items:center; gap:8px; color:var(--muted); line-height:1.35; }}
.cell .v {{ margin-top:8px; color:var(--ink); font-size:24px; font-weight:700; line-height:1.08; }}
.cell .chg {{ margin-top:6px; font-size:13px; font-weight:700; }}
.tl {{ display:inline-block; flex:none; width:8px; height:8px; border-radius:50%; }}
.tl.g {{ background:var(--up); box-shadow:0 0 0 3px rgba(22,122,84,.12); }}
.tl.y {{ background:var(--warn); box-shadow:0 0 0 3px rgba(154,104,24,.13); }}
.tl.r {{ background:var(--down); box-shadow:0 0 0 3px rgba(182,66,56,.12); }}

.say {{ margin-top:18px; padding:16px 17px; border:1px solid var(--rule-dk); border-radius:8px; background:#F7FAF1; }}
.say .who {{ display:block; margin-bottom:8px; color:var(--ox2); }}
.say p {{ margin:0; color:var(--ink); font-size:16px; line-height:1.78; text-wrap:pretty; }}

.srow,.stk {{ border-top:1px solid var(--rule); }}
.srow:first-of-type,.stk:first-of-type {{ margin-top:10px; }}
.srow > summary,.stk > summary {{ display:flex; align-items:center; gap:13px; padding:15px 2px; }}
.srow > summary:hover,.stk > summary:hover {{ background:linear-gradient(90deg,rgba(199,240,74,.10),transparent); }}
.srow .sname {{ min-width:0; color:var(--ink); font-size:16px; font-weight:700; }}
.srow .etf,.stk .tick {{ color:var(--faint); font-family:var(--mono); font-size:12px; font-weight:700; }}
.srow .schg {{ margin-left:auto; font-size:15px; font-weight:700; }}
.srow .sdetail {{ display:flex; flex-wrap:wrap; gap:7px 18px; padding:0 2px 16px; color:var(--muted); font-size:13px; line-height:1.6; }}
.srow .sdetail b {{ color:var(--ink); font-family:var(--mono); font-weight:700; }}
.tag,.status {{
  display:inline-flex; align-items:center; min-height:24px; padding:3px 9px; border-radius:999px;
  font-family:var(--mono); font-size:10px; font-weight:700; letter-spacing:.06em; text-transform:uppercase;
}}
.tag.att,.status.on {{ color:var(--up); background:var(--up-bg); }}
.tag.hold,.status.watch {{ color:var(--warn); background:var(--warn-bg); }}
.tag.avoid {{ color:var(--down); background:var(--down-bg); }}
.tag.watch {{ color:var(--neu); background:var(--neu-bg); }}

.stk .name {{ color:var(--ink); font-size:17px; font-weight:700; }}
.stk .tick {{ margin-left:8px; }}
.stk .sublight {{ display:flex; gap:7px; margin-top:9px; }}
.verdict {{
  margin-left:auto; flex:none; align-self:center; padding:5px 10px; border-radius:999px;
  border:1px solid color-mix(in srgb,currentColor 28%,transparent);
  font-family:var(--mono); font-size:11px; font-weight:700; letter-spacing:.06em; white-space:nowrap;
}}
.stkbody {{ padding:0 2px 17px; }}
.lights {{ display:flex; flex-wrap:wrap; gap:10px 16px; margin:1px 0 13px; }}
.mini {{ display:flex; align-items:center; gap:8px; color:var(--muted); font-size:13px; }}
.reason {{ margin:0 0 10px; color:var(--ink2); font-size:15px; line-height:1.75; text-wrap:pretty; }}
.meta2 {{ color:var(--faint); }}
.lvls {{ display:flex; flex-wrap:wrap; gap:9px; margin:2px 0 12px; }}
.lvl {{ display:inline-flex; flex-direction:column; gap:3px; padding:9px 13px; border:1px solid var(--rule); border-radius:8px; background:var(--surface2); font-family:var(--mono); font-size:13px; color:var(--ink); font-weight:600; }}
.lvl i {{ font-style:normal; font-size:10px; letter-spacing:.06em; text-transform:uppercase; color:var(--muted); font-weight:700; }}

.theme {{ display:flex; gap:16px; padding:18px 0; border-bottom:1px solid var(--rule); }}
.theme:last-child {{ border-bottom:0; }}
.theme .heat {{ flex:none; width:72px; padding:10px 8px; border-radius:8px; color:var(--accent); background:var(--acid); text-align:center; }}
.theme .heat .z {{ font-family:var(--mono); font-size:18px; font-weight:700; line-height:1; }}
.theme .heat .zl {{ margin-top:5px; font-family:var(--mono); color:#465023; font-size:10px; font-weight:700; letter-spacing:.03em; }}
.theme .tn {{ display:flex; align-items:center; flex-wrap:wrap; gap:9px; color:var(--ink); font-size:17px; font-weight:700; }}
.theme .tmeta {{ margin-top:6px; color:var(--muted); font-family:var(--mono); font-size:12px; line-height:1.55; }}
.theme .tnote {{ margin-top:8px; color:var(--ink2); font-size:14px; line-height:1.7; }}
details.theme {{ display:block; }}
.theme summary.thsum {{ display:flex; gap:16px; list-style:none; cursor:pointer; }}
.theme summary.thsum::-webkit-details-marker {{ display:none; }}
.theme summary.thsum:focus-visible {{ outline:2px solid var(--ox); outline-offset:3px; }}
.thexp {{ font-family:var(--mono); font-size:10px; font-weight:700; letter-spacing:.05em; color:var(--ox2); padding:2px 8px; border:1px solid var(--rule-dk); border-radius:999px; }}
details.theme[open] .thexp {{ color:var(--accent); background:var(--acid); border-color:var(--acid); }}
.thstocks {{ display:flex; flex-direction:column; gap:8px; padding:6px 0 16px 88px; }}
.thstk {{ display:flex; align-items:baseline; flex-wrap:wrap; gap:8px; padding:10px 13px; border:1px solid var(--rule); border-radius:8px; background:var(--surface2); }}
.thstk.pure {{ border-color:var(--acid); background:#F4FBE4; }}
.thid {{ font-family:var(--mono); font-size:12px; font-weight:700; color:var(--muted); }}
.thname {{ font-size:15px; font-weight:700; color:var(--ink); }}
.pur {{ font-family:var(--mono); font-size:10px; font-weight:700; letter-spacing:.05em; padding:2px 8px; border-radius:999px; }}
.pur.hi {{ color:var(--up); background:var(--up-bg); }}
.pur.mid {{ color:var(--warn); background:var(--warn-bg); }}
.pur.lo {{ color:var(--neu); background:var(--neu-bg); }}
.puresttag {{ font-family:var(--mono); font-size:10px; font-weight:700; color:var(--accent); background:var(--acid); padding:2px 8px; border-radius:999px; }}
.thnote {{ flex-basis:100%; color:var(--ink2); font-size:13px; line-height:1.55; }}
@media (max-width:700px) {{ .thstocks {{ padding-left:0; }} }}

.ev {{ display:flex; gap:16px; padding:16px 0; border-bottom:1px solid var(--rule); }}
.ev:last-child {{ border-bottom:0; }}
.ev .d {{ flex:none; width:70px; color:var(--ox2); font-family:var(--mono); font-size:13px; font-weight:700; line-height:1.45; }}
.ev .et {{ color:var(--ink2); font-size:15px; line-height:1.65; }}
.ev .et b {{ color:var(--ink); font-weight:700; }}
.ev .mm {{ margin-top:4px; color:var(--muted); font-size:13px; line-height:1.6; }}

.mktstrip {{ margin:2px 0 16px; padding:14px 15px; border:1px solid var(--rule); border-radius:8px; background:var(--surface2); }}
.mstitle {{ font-family:var(--mono); font-size:11px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color:var(--ox2); margin-bottom:11px; }}
.mchips {{ display:flex; flex-wrap:wrap; gap:9px 16px; }}
.mchip {{ display:inline-flex; align-items:center; gap:6px; font-size:13px; white-space:nowrap; }}
.mchip b {{ color:var(--ink2); font-weight:600; }}
.mchip .up,.mchip .down,.mchip .muted {{ font-family:var(--mono); font-weight:700; }}

footer {{ margin-top:24px; color:var(--muted); font-size:13px; }}
.discl {{ padding:16px 0 0; border-top:1px solid var(--rule-dk); color:var(--muted); font-size:13px; line-height:1.75; }}
.discl b {{ color:var(--ink); font-weight:700; }}

@media (max-width:700px) {{
  .wrap {{ padding:36px 18px 70px; }}
  h1 {{ font-size:42px; }}
  .card {{ padding:22px; }}
  .dir {{ font-size:28px; }}
  .kpis {{ grid-template-columns:1fr; }}
  .grid {{ grid-template-columns:1fr; }}
  .wrap > details > summary {{ flex-wrap:wrap; align-items:center; gap:11px; padding:16px 14px; }}
  .layerno {{ width:38px; height:32px; font-size:15px; }}
  summary h2 {{ flex:1; font-size:20px; }}
  summary .lgt {{ order:3; flex-basis:100%; margin-left:49px; white-space:normal; }}
  .inner {{ padding:0 14px 20px; }}
  .srow > summary,.stk > summary {{ flex-wrap:wrap; }}
  .srow .schg {{ margin-left:auto; }}
  .verdict {{ margin-left:0; }}
  .theme {{ gap:12px; }}
  .theme .heat {{ width:64px; }}
  .ev {{ gap:12px; }}
  .ev .d {{ width:58px; }}
}}

@media (prefers-reduced-motion:reduce) {{
  *,*::before,*::after {{ animation-duration:.01ms !important; animation-iteration-count:1 !important; transition-duration:.01ms !important; scroll-behavior:auto !important; }}
}}
</style>
<div class="wrap">
  <span class="real">真實資料 · FinMind × TWSE × yfinance × Google News</span>
  <div class="eyebrow">專屬投顧戰情室 · Advisor War Room</div>
  <h1>戰情週報 {period}</h1>
  <div class="meta">一週兩次 · 資料日 {asof} · 產出 {gen}（台北）</div>

  <div class="card">
    <div class="chieftag">投資長 · 本期總結</div>
    <div class="dir">{direction}</div>
    <p class="chief">{chief}</p>
    <div class="kpis">
      <div class="kpi"><div class="t">建議股票曝險</div><div class="b">{exposure}</div></div>
      <div class="kpi"><div class="t">大盤環境</div><div class="b"><span class="tl {mkt_code}"></span>{mkt_zh}</div></div>
      <div class="kpi"><div class="t">信心度</div><div class="b">{conf}</div></div>
    </div>
    <div class="meterwrap">
      <div style="font-size:11px;color:#AEBBA5;display:flex;justify-content:space-between;margin-bottom:8px"><span>風險溫度</span><span class="num">{risk} / 10</span></div>
      <div class="meter"><i style="left:{risk_pct}%"></i></div>
    </div>
  </div>

  <details open>
    <summary><span class="layerno">01</span><h2>大盤 · 環境溫度</h2><span class="lgt"><span class="tl {mkt_code}"></span></span>
      <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 9l6 6 6-6"/></svg></summary>
    <div class="inner">{grid}{foreign}
      <div class="say"><span class="who">團隊觀點 · 大盤</span><p>{market_say}</p></div>
    </div>
  </details>

  <details open>
    <summary><span class="layerno">02</span><h2>類股 · 資金往哪流</h2><span class="lgt" style="font-size:12px;color:var(--faint);font-family:var(--mono)">美股領先→台股</span>
      <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 9l6 6 6-6"/></svg></summary>
    <div class="inner">
      {mktstrip}
      <div style="font-size:11.5px;color:var(--faint);margin:4px 0 2px">美股族群動能排名（點列展開對應台股供應鏈）</div>
      {sectors}
      <div class="say"><span class="who">團隊觀點 · 類股輪動</span><p>{sector_say}</p></div>
    </div>
  </details>

  <details open>
    <summary><span class="layerno">03</span><h2>個股 · 本期名單</h2><span class="lgt" style="font-size:12px;color:var(--faint);font-family:var(--mono)">點卡展開</span>
      <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 9l6 6 6-6"/></svg></summary>
    <div class="inner">{stocks}
      <div style="font-size:11.5px;color:var(--faint);margin-top:12px">＊來源：選股器機會清單 opportunities.json，經團隊三維研判。說「研究 XXXX」可產完整單檔報告。</div>
    </div>
  </details>

  <details>
    <summary><span class="layerno">04</span><h2>主題雷達 · 看未來</h2><span class="lgt" style="font-size:12px;color:var(--faint);font-family:var(--mono)">熱度×確認</span>
      <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 9l6 6 6-6"/></svg></summary>
    <div class="inner">
      <div style="font-size:11.5px;color:var(--faint);margin:2px 0 4px">新技術／話題發掘 · 熱度上升＋個股確認才「成案」，只有噪音的僅進觀察</div>
      {themes}
      <div class="say"><span class="who">團隊觀點 · 主題</span><p>{theme_say}</p></div>
    </div>
  </details>

  <details>
    <summary><span class="layerno">05</span><h2>本期關鍵事件</h2>
      <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 9l6 6 6-6"/></svg></summary>
    <div class="inner">{events}</div>
  </details>

  <footer>
    <div class="discl">紅綠燈由「數據＋固定規則」計算，團隊觀點由分析師解讀與反駁，不憑感覺喊買賣。跨市場輪動只用「昨晚美股已收盤」資料。<b style="color:var(--ink)">本報告為投資決策輔助，非投資建議、非保證獲利，最終決策與風險由使用者承擔。</b>資料來源與時間如上；抓不到即註記缺漏、絕不編造。</div>
  </footer>
</div>
"""


if __name__ == "__main__":
    os.makedirs("reports", exist_ok=True)
    with open("reports/weekly.html", "w", encoding="utf-8") as f:
        f.write(build())
    print("→ 已產出 reports/weekly.html")
