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


def theme_rows(themes):
    st = {"成案": ("on", "成案"), "觀察": ("watch", "觀察")}
    rows = ""
    for t in themes:
        cls, zh = st.get(t["status"], ("watch", "觀察"))
        heat = f'{t["heat"]:+.0%}' if t.get("heat") is not None else "—"
        mom = f'{t["mom"]:+.1f}%' if t.get("mom") is not None else "—"
        rows += f'''<div class="theme">
          <div class="heat"><div class="z">{heat}</div><div class="zl">熱度趨勢</div></div>
          <div style="flex:1;min-width:0">
            <div class="tn">{esc(t['name'])}<span class="status {cls}">{zh}</span></div>
            <div class="tmeta">領頭 {esc(t['lead'])} {mom} · 台股：{esc(t['tw'])} · 首見 {esc(t.get('first_seen',''))}</div>
            <div class="tnote">{esc(t['reason'])}</div>
          </div></div>'''
    return rows


def stock_card(sid, data, one_liner):
    s = data["summary"]
    lights = [data["fundamental"]["light"], data["technical"]["light"], data["chips"]["light"]]
    dircode = "g" if s["score"] > 0.3 else "r" if s["score"] < -0.3 else "y"
    dots = "".join(f'<span class="tl {LIGHT[l][0]}"></span>' for l in lights)
    evs = ""
    for key, zh in [("fundamental", "基本面"), ("technical", "技術面"), ("chips", "消息/籌碼")]:
        b = data[key]
        evs += f'<div class="mini"><span class="tl {LIGHT[b["light"]][0]}"></span>{zh} {LIGHT[b["light"]][1]}</div>'
    return f'''<details class="stk">
      <summary>
        <div><span class="name">{esc(data['name'])}</span><span class="tick">{esc(sid)}</span>
          <div class="sublight">{dots}</div></div>
        <span class="verdict" style="color:{DIRW[dircode]};background:var(--{'up' if dircode=='g' else 'down' if dircode=='r' else 'neu'}-bg)">{esc(s['direction'])}</span>
      </summary>
      <div class="stkbody">
        <div class="lights">{evs}</div>
        <p class="reason">{esc(one_liner)}</p>
        <div class="meta2">加權分 {s['score']} · 信心 {esc(s['confidence'])}</div>
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
    events = "".join(f'<div class="ev"><div class="d">{esc(e["d"])}</div><div class="et"><b>{esc(e["t"])}</b><div class="mm">{esc(e["m"])}</div></div></div>' for e in n["events"])
    gen = datetime.now(TPE).strftime("%Y-%m-%d %H:%M")

    return TEMPLATE.format(
        period=esc(n["period"]), asof=esc(n["asof"]), gen=esc(gen),
        chief=esc(n["chief"]), direction=esc(n["direction"]), exposure=esc(n["exposure"]),
        conf=esc(n["confidence"]), risk=n["risk_temp"], risk_pct=n["risk_temp"] * 10,
        mkt_emo=emo, mkt_zh=zh, mkt_code=code,
        grid=index_grid(m["items"]) , foreign=foreign, market_say=esc(n["market"]),
        sectors=sector_rows(sec), sector_say=esc(n["sector"]),
        stocks=stock_cards, themes=theme_rows(themes), theme_say=esc(n.get("theme", "")), events=events,
    )


TEMPLATE = r"""<title>戰情週報 {period} · 專屬投顧戰情室</title>
<style>
:root{{--base:#E7EAF5;--ink:#383B58;--ink2:#5A5E80;--muted:#7E82A2;--faint:#A2A6C2;
--sh-d:#C6CBDE;--sh-l:#FFFFFF;--line:#D5D9EA;--pink:#F3A6D0;--purple:#B197E8;
--grad:linear-gradient(135deg,#F3A6D0,#B197E8);--up:#2AA588;--up-bg:#D6EEE6;
--down:#E36088;--down-bg:#F7DEE7;--warn:#D2982F;--warn-bg:#F3E8D2;--neu:#5E6288;--neu-bg:#E0E3F1;
--mono:ui-monospace,"SF Mono",Menlo,monospace;--sans:system-ui,-apple-system,"PingFang TC","Noto Sans TC",sans-serif;}}
*{{box-sizing:border-box}}
body{{margin:0;color:var(--ink);font-family:var(--sans);font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased;
background:linear-gradient(165deg,#E4E9F7,#E9E5F3 48%,#F1E6EE);background-attachment:fixed;min-height:100vh}}
.wrap{{max-width:780px;margin:0 auto;padding:24px 16px 70px}}
.num,.v,.chg,.schg{{font-family:var(--mono);font-variant-numeric:tabular-nums}}
.up{{color:var(--up)}}.down{{color:var(--down)}}.muted{{color:var(--muted)}}
.real{{display:inline-flex;align-items:center;gap:7px;font-size:12px;color:#1e7d63;background:var(--up-bg);border-radius:999px;padding:5px 12px;font-weight:600}}
.real::before{{content:"";width:7px;height:7px;border-radius:50%;background:var(--up)}}
.eyebrow{{font-size:12px;letter-spacing:.2em;text-transform:uppercase;font-weight:700;background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent;margin-top:14px}}
h1{{font-size:29px;margin:8px 0 4px;font-weight:700;letter-spacing:-.01em}}
.meta{{color:var(--muted);font-size:13px;font-family:var(--mono)}}
.card{{background:var(--base);border-radius:22px;padding:22px;margin-top:16px;box-shadow:7px 7px 16px var(--sh-d),-7px -7px 16px var(--sh-l)}}
.chieftag{{font-size:12px;letter-spacing:.1em;text-transform:uppercase;font-weight:700;background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}}
.dir{{font-size:23px;font-weight:800;margin:9px 0 0}}
.chief{{font-size:14.5px;margin:12px 0 0}}
.kpis{{display:flex;flex-wrap:wrap;gap:11px;margin-top:15px}}
.kpi{{flex:1;min-width:110px;background:var(--base);border-radius:14px;padding:11px 14px;box-shadow:inset 4px 4px 9px var(--sh-d),inset -4px -4px 9px var(--sh-l)}}
.kpi .t{{font-size:11px;color:var(--muted)}}.kpi .b{{font-size:15px;margin-top:3px;font-weight:700}}
.meterwrap{{margin-top:15px;background:var(--base);border-radius:14px;padding:12px 15px;box-shadow:inset 4px 4px 9px var(--sh-d),inset -4px -4px 9px var(--sh-l)}}
.meter{{height:9px;border-radius:99px;position:relative;background:linear-gradient(90deg,var(--up),var(--warn),var(--down))}}
.meter i{{position:absolute;top:-4px;width:5px;height:17px;background:#fff;border-radius:3px;box-shadow:0 1px 5px rgba(80,60,110,.5)}}
details{{background:var(--base);border-radius:22px;margin-top:16px;overflow:hidden;box-shadow:7px 7px 16px var(--sh-d),-7px -7px 16px var(--sh-l)}}
summary{{list-style:none;cursor:pointer;padding:17px 20px;display:flex;align-items:center;gap:12px;user-select:none}}
summary::-webkit-details-marker{{display:none}}
.layerno{{font-family:var(--mono);font-size:13px;font-weight:700;width:34px;height:34px;flex:none;border-radius:11px;display:grid;place-items:center;color:var(--purple);box-shadow:inset 3px 3px 6px var(--sh-d),inset -3px -3px 6px var(--sh-l)}}
summary h2{{font-size:18px;margin:0;font-weight:650}}
summary .lgt{{margin-left:auto;font-size:13px;font-weight:700}}
.chev{{width:20px;height:20px;flex:none;color:var(--muted);transition:transform .25s}}
details[open] .chev{{transform:rotate(180deg)}}
.inner{{padding:2px 20px 20px}}
.grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:11px;margin-top:4px}}
.cell{{background:var(--base);border-radius:14px;padding:12px 14px;box-shadow:5px 5px 11px var(--sh-d),-5px -5px 11px var(--sh-l)}}
.cell .lab{{font-size:12px;color:var(--muted);display:flex;align-items:center;gap:7px}}
.cell .v{{font-size:17px;margin-top:4px;font-weight:600}}
.cell .chg{{font-size:12px;margin-top:1px}}
.tl{{width:9px;height:9px;border-radius:50%;flex:none;display:inline-block}}
.tl.g{{background:var(--up)}}.tl.y{{background:var(--warn)}}.tl.r{{background:var(--down)}}
.say{{border-radius:15px;padding:14px 16px;margin-top:14px;background:linear-gradient(135deg,rgba(243,166,208,.10),rgba(177,151,232,.10))}}
.say .who{{font-size:11px;font-weight:700;color:var(--purple);display:block;margin-bottom:5px;letter-spacing:.05em}}
.say p{{margin:0;font-size:14px}}
.srow{{background:var(--base);border-radius:14px;margin-top:10px;overflow:hidden;box-shadow:5px 5px 11px var(--sh-d),-5px -5px 11px var(--sh-l)}}
.srow>summary{{padding:12px 15px;gap:10px}}
.srow .sname{{font-weight:600;font-size:14px}}.srow .etf{{font-family:var(--mono);color:var(--faint);font-size:11.5px}}
.srow .schg{{margin-left:auto;font-size:13.5px}}
.srow .sdetail{{padding:0 15px 13px;font-size:12.5px;color:var(--ink2);display:flex;flex-wrap:wrap;gap:6px 16px}}
.srow .sdetail b{{color:var(--ink);font-family:var(--mono)}}
.tag{{font-size:11.5px;border-radius:8px;padding:3px 10px;font-weight:700}}
.tag.att{{color:#1e7d63;background:var(--up-bg)}}.tag.hold{{color:#a8792a;background:var(--warn-bg)}}.tag.avoid{{color:#bd4a6c;background:var(--down-bg)}}
.stk{{border-radius:16px;margin-top:12px}}
.stk>summary{{padding:15px 16px;gap:11px;align-items:flex-start}}
.stk .name{{font-size:16px;font-weight:700}}.stk .tick{{font-family:var(--mono);color:var(--muted);font-size:13px;margin-left:6px}}
.stk .sublight{{display:flex;gap:6px;margin-top:8px}}
.verdict{{margin-left:auto;flex:none;font-size:12.5px;font-weight:700;border-radius:10px;padding:6px 12px}}
.stkbody{{padding:0 16px 16px}}
.lights{{display:flex;gap:14px;flex-wrap:wrap;margin:2px 0 11px}}
.mini{{display:flex;align-items:center;gap:7px;font-size:12.5px;color:var(--ink2)}}
.reason{{font-size:14px;margin:0 0 8px}}.meta2{{font-size:12px;color:var(--faint);font-family:var(--mono)}}
.theme{{display:flex;gap:13px;padding:13px 0;border-bottom:1px solid var(--line)}}.theme:last-child{{border-bottom:0}}
.theme .heat{{flex:none;width:60px;text-align:center;border-radius:13px;padding:9px 0;box-shadow:inset 3px 3px 6px var(--sh-d),inset -3px -3px 6px var(--sh-l)}}
.theme .heat .z{{font-family:var(--mono);font-size:15px;font-weight:700}}.theme .heat .zl{{font-size:9.5px;color:var(--faint);margin-top:2px}}
.theme .tn{{font-size:15px;font-weight:650;display:flex;align-items:center;gap:9px;flex-wrap:wrap}}
.theme .tmeta{{font-size:11.5px;color:var(--muted);margin-top:4px;font-family:var(--mono)}}
.theme .tnote{{font-size:13px;color:var(--ink2);margin-top:5px}}
.status{{font-size:11px;font-weight:700;border-radius:8px;padding:2px 9px}}
.status.on{{color:#1e7d63;background:var(--up-bg)}}.status.watch{{color:#a8792a;background:var(--warn-bg)}}
.ev{{display:flex;gap:13px;padding:12px 0;border-bottom:1px solid var(--line)}}.ev:last-child{{border-bottom:0}}
.ev .d{{flex:none;font-family:var(--mono);width:52px;font-size:12.5px;font-weight:700;background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}}
.ev .et{{font-size:14px}}.ev .et b{{color:var(--ink)}}.ev .mm{{color:var(--muted);font-size:12.5px;margin-top:3px;line-height:1.5}}
footer{{margin-top:26px;color:var(--faint);font-size:12.5px}}
.discl{{background:var(--base);border-radius:16px;padding:15px 17px;margin-top:12px;font-size:12.5px;color:var(--ink2);line-height:1.65;box-shadow:inset 4px 4px 9px var(--sh-d),inset -4px -4px 9px var(--sh-l)}}
@media(max-width:520px){{h1{{font-size:24px}}.kpi{{min-width:calc(50% - 6px)}}}}
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
      <div class="kpi"><div class="t">大盤環境</div><div class="b">{mkt_emo} {mkt_zh}</div></div>
      <div class="kpi"><div class="t">信心度</div><div class="b">{conf}</div></div>
    </div>
    <div class="meterwrap">
      <div style="font-size:11px;color:var(--muted);display:flex;justify-content:space-between;margin-bottom:8px"><span>風險溫度</span><span class="num">{risk} / 10</span></div>
      <div class="meter"><i style="left:{risk_pct}%"></i></div>
    </div>
  </div>

  <details open>
    <summary><span class="layerno">01</span><h2>大盤 · 環境溫度</h2><span class="lgt">{mkt_emo}</span>
      <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 9l6 6 6-6"/></svg></summary>
    <div class="inner">{grid}{foreign}
      <div class="say"><span class="who">團隊觀點 · 大盤</span><p>{market_say}</p></div>
    </div>
  </details>

  <details open>
    <summary><span class="layerno">02</span><h2>類股 · 資金往哪流</h2><span class="lgt" style="font-size:12px;color:var(--faint);font-family:var(--mono)">美股領先→台股</span>
      <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 9l6 6 6-6"/></svg></summary>
    <div class="inner">
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
