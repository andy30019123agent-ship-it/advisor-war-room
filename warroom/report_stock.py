"""單檔投顧報告產生器：讀 data/<id>.json（引擎數據）＋ data/<id>.narration.json（Claude 團隊觀點）
→ 產 reports/<id>.html（白底柔和 neumorphism 風）。這是真實資料報告，非示意。
"""
import json, sys, os, html
from datetime import datetime, timezone, timedelta

TPE = timezone(timedelta(hours=8))
LIGHT = {"green": ("g", "🟢", "偏多"), "amber": ("y", "🟡", "中性"), "red": ("r", "🔴", "偏空")}


def esc(s): return html.escape(str(s))


def ev_chips(ev):
    return "".join(f'<span class="d">{esc(k)} <b>{esc(v)}</b></span>' for k, v in ev.items())


def dim_card(no, title, block, narration):
    code, emo, zh = LIGHT.get(block["light"], ("y", "🟡", "中性"))
    return f"""
    <div class="dim">
      <div class="dimhead"><span class="tl {code}"></span><h3>{title}</h3><span class="lgt {code}"><span class="tl {code}"></span>{zh}</span></div>
      <div class="evrow">{ev_chips(block['ev'])}</div>
      <div class="say"><span class="who">{no}</span><p>{esc(narration)}</p></div>
    </div>"""


def build(stock_id):
    with open(f"data/{stock_id}.json", encoding="utf-8") as f:
        d = json.load(f)
    with open(f"data/{stock_id}.narration.json", encoding="utf-8") as f:
        n = json.load(f)
    r = n["roles"]
    s = d["summary"]
    act = n["action"]
    gen_time = datetime.now(TPE).strftime("%Y-%m-%d %H:%M")

    news_html = "".join(
        f'<a class="news" href="{esc(a.get("url","#"))}" target="_blank" rel="noopener">'
        f'<span class="nt">{esc(a.get("title",""))}</span><span class="ns">{esc(a.get("src",""))}</span></a>'
        for a in d.get("news", [])[:6]) or '<p class="muted">（本次未取得新聞）</p>'

    dims = (
        dim_card("基本面分析師", "基本面", d["fundamental"], r["fundamental"]) +
        dim_card("技術分析師", "技術面", d["technical"], r["technical"]) +
        dim_card("消息／籌碼分析師", "消息 · 籌碼", d["chips"], r["news"])
    )

    return TEMPLATE.format(
        name=esc(d["name"]), sid=esc(stock_id), asof=esc(n["as_of"]), gen=esc(gen_time),
        direction=esc(s["direction"]), conf=esc(act["confidence"]), score=esc(s["score"]),
        chief=esc(r["chief"]), action_dir=esc(act["direction"]), action_stop=esc(act["stop"]),
        risk=esc(r["risk"]), devil=esc(r["devil"]), dims=dims, news=news_html,
    )


TEMPLATE = """<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} {sid} · 投顧戰情報告</title>
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
  font-size:16px; line-height:1.68; background:var(--paper);
  -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility;
}}
body::before {{
  content:""; position:fixed; inset:0 0 auto; height:8px; z-index:0; pointer-events:none;
  background:linear-gradient(90deg,var(--acid) 0 22%,var(--ox) 22% 34%,var(--accent) 34% 100%);
}}
.wrap {{ position:relative; z-index:1; max-width:820px; margin:0 auto; padding:48px 28px 92px; }}
.up {{ color:var(--up); }} .down {{ color:var(--down); }} .muted {{ color:var(--muted); font-size:13px; }}
.num {{ font-family:var(--mono); font-variant-numeric:tabular-nums; }}

.real {{
  display:inline-flex; align-items:center; gap:9px; max-width:100%; color:var(--ink2);
  font-family:var(--mono); font-size:11px; font-weight:700; letter-spacing:.06em;
  padding:7px 10px; border:1px solid var(--rule-dk); border-radius:999px; background:rgba(251,253,247,.64);
}}
.real::before {{ content:""; width:7px; height:7px; border-radius:50%; background:var(--acid); box-shadow:0 0 0 3px rgba(199,240,74,.22); }}
header {{ margin-top:22px; }}
h1 {{ margin:12px 0 0; color:var(--ink); font-family:var(--disp); font-size:44px; line-height:1.02; font-weight:700; letter-spacing:-.03em; text-wrap:balance; }}
.tick {{ margin-left:10px; color:var(--faint); font-family:var(--mono); font-size:17px; font-weight:700; }}
.mkt {{
  margin-left:10px; vertical-align:middle; display:inline-flex; align-items:center;
  padding:3px 9px; border:1px solid var(--rule-dk); border-radius:999px;
  color:var(--ox2); background:transparent; font-family:var(--mono); font-size:11px; font-weight:700; letter-spacing:.04em;
}}
.meta {{ margin-top:14px; color:var(--muted); font-family:var(--mono); font-size:13px; letter-spacing:.02em; }}

.card {{
  position:relative; overflow:hidden; margin-top:26px; padding:28px; border-radius:8px;
  color:#EEF4E8; background:var(--accent); box-shadow:0 14px 34px rgba(21,23,19,.18);
}}
.card::before {{ content:""; position:absolute; inset:0 0 auto; height:5px; background:linear-gradient(90deg,var(--acid),var(--ox)); }}
.newscard {{
  color:var(--ink2); background:var(--surface); border:1px solid var(--rule); box-shadow:none;
}}
.newscard::before {{ display:none; }}
.chieftag {{ color:var(--acid2); font-family:var(--mono); font-size:11px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }}
.dir {{ margin:13px 0 0; color:#FBFDF7; font-family:var(--disp); font-size:30px; line-height:1.16; font-weight:700; letter-spacing:-.025em; text-wrap:balance; }}
.chief {{ max-width:70ch; margin:15px 0 0; color:#DDE6D5; font-size:16px; line-height:1.78; }}
.kpis {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin-top:22px; }}
.kpi {{ min-width:0; padding:14px; border-radius:8px; background:rgba(251,253,247,.08); }}
.kpi .t {{ color:#AEBBA5; font-family:var(--mono); font-size:11px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; }}
.kpi .b {{ margin-top:7px; color:#FBFDF7; font-family:var(--disp); font-size:19px; font-weight:700; line-height:1.2; word-break:break-word; }}
.adv {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:16px; }}
.advbox {{ padding:15px 16px; border-radius:8px; background:rgba(251,253,247,.07); border:1px solid rgba(251,253,247,.14); }}
.advbox .h {{ margin-bottom:7px; font-family:var(--mono); font-size:11px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color:#E9FF9D; }}
.advbox.risk .h {{ color:#F3D28A; }}
.advbox p {{ margin:0; font-size:14px; color:#D6DFCF; line-height:1.62; }}

.sechead {{
  margin:38px 0 0; padding-bottom:12px; border-bottom:1px solid var(--rule-dk);
  color:var(--ink); font-family:var(--disp); font-size:15px; font-weight:700; letter-spacing:.02em;
  display:flex; align-items:center; gap:10px;
}}
.sechead::before {{ content:""; width:10px; height:10px; border-radius:2px; background:var(--acid); flex:none; }}

.dim {{ margin-top:14px; padding:20px; border:1px solid var(--rule); border-radius:8px; background:var(--surface); }}
.dimhead {{ display:flex; align-items:center; gap:11px; }}
.dimhead .tl {{ width:10px; height:10px; }}
.dimhead h3 {{ margin:0; color:var(--ink); font-family:var(--disp); font-size:18px; font-weight:700; letter-spacing:-.01em; }}
.dimhead .lgt {{ margin-left:auto; display:inline-flex; align-items:center; gap:7px; font-family:var(--mono); font-size:12px; font-weight:700; letter-spacing:.04em; }}
.lgt.g {{ color:var(--up); }} .lgt.y {{ color:var(--warn); }} .lgt.r {{ color:var(--down); }}
.tl {{ width:10px; height:10px; border-radius:50%; flex:none; display:inline-block; }}
.tl.g {{ background:var(--up); box-shadow:0 0 0 3px rgba(22,122,84,.12); }}
.tl.y {{ background:var(--warn); box-shadow:0 0 0 3px rgba(154,104,24,.13); }}
.tl.r {{ background:var(--down); box-shadow:0 0 0 3px rgba(182,66,56,.12); }}
.evrow {{ display:flex; flex-wrap:wrap; gap:8px; margin:15px 0; }}
.evrow .d {{ padding:7px 11px; border:1px solid var(--rule); border-radius:8px; background:var(--surface2); font-size:12.5px; color:var(--muted); }}
.evrow .d b {{ margin-left:4px; color:var(--ink); font-family:var(--mono); font-weight:700; }}
.say {{ margin-top:2px; padding:14px 15px; border-radius:8px; background:var(--surface2); border:1px solid var(--rule); }}
.say .who {{ display:block; margin-bottom:7px; color:var(--ox2); font-family:var(--mono); font-size:11px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; }}
.say p {{ margin:0; color:var(--ink); font-size:15px; line-height:1.72; text-wrap:pretty; }}

.news {{ display:flex; justify-content:space-between; gap:14px; align-items:baseline; text-decoration:none; padding:14px 2px; border-bottom:1px solid var(--rule); color:var(--ink); }}
.news:last-child {{ border-bottom:0; }}
.news .nt {{ font-size:15px; line-height:1.5; }}
.news:hover .nt {{ color:var(--ox); }}
.news .ns {{ flex:none; white-space:nowrap; color:var(--faint); font-family:var(--mono); font-size:12px; font-weight:700; }}

footer {{ margin-top:26px; }}
.discl {{ padding:16px 0 0; border-top:1px solid var(--rule-dk); color:var(--muted); font-size:13px; line-height:1.75; }}
.discl b {{ color:var(--ink); font-weight:700; }}

@media (max-width:700px) {{
  .wrap {{ padding:36px 18px 70px; }}
  h1 {{ font-size:34px; }}
  .card {{ padding:22px; }}
  .dir {{ font-size:25px; }}
  .kpis {{ grid-template-columns:1fr; }}
  .adv {{ grid-template-columns:1fr; }}
  .tick {{ display:inline-block; margin-left:0; margin-top:6px; }}
}}
@media (prefers-reduced-motion:reduce) {{
  *,*::before,*::after {{ animation-duration:.01ms !important; transition-duration:.01ms !important; }}
}}
</style>
<div class="wrap">
  <span class="real">真實資料 · FinMind × TWSE × Google News</span>
  <header>
    <h1>{name}<span class="tick">{sid}</span><span class="mkt">台股</span></h1>
    <div class="meta">投顧戰情報告 · 資料日 {asof} · 產出 {gen}（台北）</div>
  </header>

  <div class="card">
    <div class="chieftag">投資長 · 綜合研判</div>
    <div class="dir">{direction}</div>
    <p class="chief">{chief}</p>
    <div class="kpis">
      <div class="kpi"><div class="t">操作建議</div><div class="b">{action_dir}</div></div>
      <div class="kpi"><div class="t">信心度</div><div class="b">{conf}</div></div>
      <div class="kpi"><div class="t">加權分</div><div class="b">{score}</div></div>
    </div>
    <div class="kpi" style="margin-top:11px"><div class="t">防守 / 停損參考</div><div class="b" style="font-size:13.5px">{action_stop}</div></div>
    <div class="adv">
      <div class="advbox risk"><div class="h">⚠ 風控長</div><p>{risk}</p></div>
      <div class="advbox"><div class="h">◆ 魔鬼代言人</div><p>{devil}</p></div>
    </div>
  </div>

  <div class="sechead">三維度團隊研判</div>
  {dims}

  <div class="sechead">近期新聞</div>
  <div class="card newscard" style="padding:8px 20px">{news}</div>

  <footer>
    <div class="discl">紅綠燈由「數據＋固定規則」計算（技術面均線／RSI／量能、基本面營收 YoY／PER 分位、籌碼三大法人淨買），團隊觀點由分析師解讀與反駁，不憑感覺喊買賣。<b style="color:var(--ink)">本報告為投資決策輔助，非投資建議、非保證獲利，最終決策與風險由使用者承擔。</b>數據來源與抓取時間如上；抓不到即註記缺漏、絕不編造。</div>
  </footer>
</div>
"""


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else "2330"
    os.makedirs("reports", exist_ok=True)
    out = f"reports/{sid}.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(build(sid))
    print(f"→ 已產出 {out}")
