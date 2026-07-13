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
      <div class="dimhead"><span class="tl {code}"></span><h3>{title}</h3><span class="lgt {code}">{emo} {zh}</span></div>
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


TEMPLATE = """<title>{name} {sid} · 投顧戰情報告</title>
<style>
:root{{--base:#E7EAF5;--ink:#383B58;--ink2:#5A5E80;--muted:#7E82A2;--faint:#A2A6C2;
--sh-d:#C6CBDE;--sh-l:#FFFFFF;--line:#D5D9EA;--pink:#F3A6D0;--purple:#B197E8;
--grad:linear-gradient(135deg,#F3A6D0,#B197E8);--up:#2AA588;--up-bg:#D6EEE6;
--down:#E36088;--down-bg:#F7DEE7;--warn:#D2982F;--warn-bg:#F3E8D2;
--mono:ui-monospace,"SF Mono",Menlo,monospace;--sans:system-ui,-apple-system,"PingFang TC","Noto Sans TC",sans-serif;}}
*{{box-sizing:border-box}}
body{{margin:0;color:var(--ink);font-family:var(--sans);font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased;
background:linear-gradient(165deg,#E4E9F7,#E9E5F3 48%,#F1E6EE);background-attachment:fixed;min-height:100vh}}
.wrap{{max-width:760px;margin:0 auto;padding:26px 16px 70px}}
.real{{display:inline-flex;align-items:center;gap:7px;font-size:12px;color:#1e7d63;background:var(--up-bg);
border-radius:999px;padding:5px 12px;font-weight:600}}
.real::before{{content:"";width:7px;height:7px;border-radius:50%;background:var(--up)}}
header{{margin-top:16px}}
.tick{{font-family:var(--mono);color:var(--muted);font-size:15px;margin-left:8px}}
.mkt{{font-size:11px;border-radius:6px;padding:2px 8px;color:var(--purple);background:rgba(177,151,232,.16);
margin-left:8px;vertical-align:middle;font-weight:600}}
h1{{font-size:29px;margin:12px 0 6px;font-weight:700;letter-spacing:-.01em}}
.meta{{color:var(--muted);font-size:13px;font-family:var(--mono)}}
.card{{background:var(--base);border-radius:22px;padding:22px;margin-top:18px;
box-shadow:7px 7px 16px var(--sh-d),-7px -7px 16px var(--sh-l)}}
.chieftag{{font-size:12px;letter-spacing:.1em;text-transform:uppercase;font-weight:700;
background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}}
.dir{{font-size:24px;font-weight:800;margin:9px 0 4px;letter-spacing:-.01em}}
.chief{{font-size:15px;color:var(--ink);margin:12px 0 0}}
.kpis{{display:flex;flex-wrap:wrap;gap:11px;margin-top:16px}}
.kpi{{flex:1;min-width:120px;background:var(--base);border-radius:14px;padding:11px 14px;
box-shadow:inset 4px 4px 9px var(--sh-d),inset -4px -4px 9px var(--sh-l)}}
.kpi .t{{font-size:11px;color:var(--muted)}} .kpi .b{{font-size:15px;margin-top:3px;font-weight:700}}
.adv{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px}}
.advbox{{border-radius:15px;padding:14px 15px;background:var(--down-bg)}}
.advbox.risk{{background:var(--warn-bg)}}
.advbox .h{{font-size:11.5px;font-weight:700;letter-spacing:.04em;margin-bottom:6px}}
.advbox.risk .h{{color:#a8792a}} .advbox .h{{color:#bd4a6c}}
.advbox p{{margin:0;font-size:13px;color:var(--ink2);line-height:1.55}}
.sechead{{font-size:13px;letter-spacing:.14em;text-transform:uppercase;color:var(--faint);
font-weight:700;margin:30px 4px 4px}}
.dim{{background:var(--base);border-radius:20px;padding:18px;margin-top:14px;
box-shadow:6px 6px 14px var(--sh-d),-6px -6px 14px var(--sh-l)}}
.dimhead{{display:flex;align-items:center;gap:11px}}
.dimhead h3{{font-size:17px;margin:0;font-weight:650}}
.dimhead .lgt{{margin-left:auto;font-size:13px;font-weight:700}}
.lgt.g{{color:var(--up)}} .lgt.y{{color:var(--warn)}} .lgt.r{{color:var(--down)}}
.tl{{width:11px;height:11px;border-radius:50%;flex:none}}
.tl.g{{background:var(--up)}} .tl.y{{background:var(--warn)}} .tl.r{{background:var(--down)}}
.evrow{{display:flex;flex-wrap:wrap;gap:9px;margin:14px 0}}
.evrow .d{{background:var(--base);border-radius:11px;padding:8px 12px;font-size:12.5px;color:var(--muted);
box-shadow:inset 3px 3px 6px var(--sh-d),inset -3px -3px 6px var(--sh-l)}}
.evrow .d b{{color:var(--ink);font-family:var(--mono);font-weight:600;margin-left:2px}}
.say{{border-radius:14px;padding:13px 15px;background:linear-gradient(135deg,rgba(243,166,208,.10),rgba(177,151,232,.10))}}
.say .who{{font-size:11px;font-weight:700;color:var(--purple);display:block;margin-bottom:5px}}
.say p{{margin:0;font-size:14px;color:var(--ink)}}
.news{{display:flex;justify-content:space-between;gap:12px;align-items:baseline;text-decoration:none;
padding:12px 2px;border-bottom:1px solid var(--line);color:var(--ink)}}
.news:last-child{{border-bottom:0}}
.news .nt{{font-size:14px;line-height:1.45}} .news:hover .nt{{color:var(--purple)}}
.news .ns{{font-size:11.5px;color:var(--faint);font-family:var(--mono);white-space:nowrap;flex:none}}
.muted{{color:var(--muted);font-size:13px}}
footer{{margin-top:28px;color:var(--faint);font-size:12.5px}}
.discl{{background:var(--base);border-radius:16px;padding:15px 17px;margin-top:12px;font-size:12.5px;
color:var(--ink2);line-height:1.65;box-shadow:inset 4px 4px 9px var(--sh-d),inset -4px -4px 9px var(--sh-l)}}
@media(max-width:520px){{h1{{font-size:24px}}.adv{{grid-template-columns:1fr}}.kpi{{min-width:calc(50% - 6px)}}}}
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
  <div class="card" style="padding:8px 20px">{news}</div>

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
