"""一週兩次 top-down 戰情週報產生器：大盤→類股→個股→事件。
即時抓 market/sectors，讀個股引擎 JSON ＋ 我手寫的 weekly_narration.json → 產 reports/weekly.html。
Neumorphism 柔白＋淡粉版（MASTER.md 為唯一設計權威）。真實資料，非示意。

渲染是純函式：render_weekly_html(ctx) 只吃 dict、回字串，
無網路、無 assert，可離線測試。build() 負責抓網路資料＋一致性 assert＋落檔的既有流程。
"""
import json
import os
from datetime import datetime, timezone, timedelta

from warroom import render_common as rc
from warroom.market import fetch_market
from warroom.sectors import fetch_sectors, fetch_tw_sectors

TPE = timezone(timedelta(hours=8))
LIGHT = {"green": ("g", "偏多"), "amber": ("y", "中性"), "red": ("r", "偏空")}
RATING_CLS = {"買進": "up", "試單": "up", "續抱": "up", "觀望": "muted", "減碼": "down"}
TIER_ZH = {"lead": ("領先", "up"), "mid": ("中性", "muted"), "lag": ("落後", "down")}
PUR_CLS = {"純": "hi", "中": "mid", "分散": "lo"}


def chg_cls(wk):
    """漲用 up、跌用 down、平用 muted（綠漲紅跌固定，不得翻轉）。"""
    return "up" if (wk or 0) > 0 else "down" if (wk or 0) < 0 else "muted"


def _pct(x, digits=1):
    return f'{x:+.{digits}f}%' if x is not None else "—"


def _n1(x):
    if x is None:
        return "—"
    return "{:.1f}".format(x)


def _pill(container_cls, cls, label):
    """粉白 neu 底 + 內層語意色文字（container 本身不承載色彩，避免 CSS 特異度覆蓋問題）。"""
    return f'<span class="{container_cls}"><span class="{cls}">{rc.esc(label)}</span></span>'


def index_grid(items):
    """大盤層格線（加權/櫃買）：沿用 render_common 的 .kpi 卡片元件。"""
    cells = ""
    for i in items:
        wk = i.get("wk")
        cells += (
            '<div class="kpi"><small><span class="dot ' + rc.esc(i.get("dot", "y"))
            + '"></span> ' + rc.esc(i["name"]) + '</small>'
            '<strong class="num">' + rc.esc(i["value"]) + '</strong>'
            '<small class="' + chg_cls(wk) + '">' + _pct(wk) + ' · 週</small></div>'
        )
    return '<div class="kpis">' + cells + '</div>'


def market_strip(items):
    """類股區頂端的『台美大盤現況』小摘要（複用大盤層已抓的指數）。"""
    chips = ""
    for i in items:
        wk = i.get("wk")
        chips += (
            '<span class="tag"><span class="dot ' + rc.esc(i.get("dot", "y")) + '"></span> '
            + rc.esc(i["name"]) + ' <span class="' + chg_cls(wk) + ' num">' + _pct(wk) + '</span></span>'
        )
    return '<div class="tags">' + chips + '</div>'


def sector_rows(sectors):
    """美股族群動能排名（可展開對應台股供應鏈）。"""
    rows = ""
    for r in sectors:
        zh, cls = TIER_ZH.get(r.get("tier"), ("中性", "muted"))
        m5, m20 = _pct(r.get("m5")), _pct(r.get("m20"))
        rows += (
            '<details><summary><span>' + rc.esc(r["group"])
            + ' <span class="muted num">' + rc.esc(r["etf"]) + '</span></span>'
            + _pill("tag", cls, zh) + rc.icon("i-chevron") + '</summary>'
            '<div class="details-body">'
            f'<span>近5日 <b class="num {chg_cls(r.get("m5"))}">{m5}</b></span>'
            f'<span>近20日 <b class="num {chg_cls(r.get("m20"))}">{m20}</b></span>'
            f'<span>美股代表 <b>{rc.esc(r["us_names"])}</b></span>'
            f'<span>→ 台股對應：{rc.esc(r["tw"])}</span>'
            '</div></details>'
        )
    return rows


def tw_sector_rows(tw_sec):
    """台股類股輪動真實強度區（data/tw_sectors.json）：依 score／rank 排序展示。"""
    if not tw_sec:
        return '<p class="muted">（台股類股輪動本次無資料）</p>'
    rows = ""
    for r in sorted(tw_sec, key=lambda x: x.get("rank") if x.get("rank") is not None else 999):
        zh, cls = TIER_ZH.get(r.get("tier"), ("中性", "muted"))
        m5, m20 = _pct(r.get("m5")), _pct(r.get("m20"))
        vol = r.get("vol_expansion")
        vol_txt = f'{vol:.2f}x' if vol is not None else "—"
        rs = r.get("rs_vs_twii")
        rs_txt = f'{rs:+.1f}' if rs is not None else "—"
        rows += (
            '<details><summary><span>' + rc.esc(r["group"]) + '</span>'
            + _pill("tag", cls, zh) + rc.icon("i-chevron") + '</summary>'
            '<div class="details-body">'
            f'<span>近5日 <b class="num {chg_cls(r.get("m5"))}">{m5}</b></span>'
            f'<span>近20日 <b class="num {chg_cls(r.get("m20"))}">{m20}</b></span>'
            f'<span>量能 <b class="num">{vol_txt}</b></span>'
            f'<span>RS 強度 <b class="num">{rs_txt}</b></span>'
            '</div></details>'
        )
    return rows


def _theme_stock_list(stocks):
    rows = ""
    for s in stocks:
        pur = PUR_CLS.get(s.get("purity", ""), "mid")
        pure = '<span class="tag"><span class="up">最純</span></span>' if s.get("purest") else ""
        rows += (
            '<div class="flat"><span class="num muted">' + rc.esc(s.get("id", "—")) + '</span> '
            + rc.esc(s.get("name", "")) + f' <span class="tag"><span class="{pur}">'
            + rc.esc(s.get("purity", "—")) + '</span></span>' + pure
            + f'<p class="source">{rc.esc(s.get("note", ""))}</p></div>'
        )
    return rows


def theme_rows(themes, theme_stocks=None):
    """主題雷達：熱度×領頭股動能×台股個股確認才『成案』。"""
    theme_stocks = theme_stocks or {}
    st = {"成案": "up", "觀察": "muted"}
    rows = ""
    for t in themes:
        cls = st.get(t["status"], "muted")
        heat = f'{t["heat"]:+.0%}' if t.get("heat") is not None else "—"
        mom = f'{t["mom"]:+.1f}%' if t.get("mom") is not None else "—"
        stocks = theme_stocks.get(t["name"])
        head = f'<h3>{rc.esc(t["name"])}</h3>' + _pill("tag", cls, t["status"])
        meta = (
            f'<p class="source">熱度 <span class="num">{heat}</span> · 領頭 {rc.esc(t["lead"])} {mom} · '
            f'首見 {rc.esc(t.get("first_seen", ""))}</p>'
            f'<p class="reason">{rc.esc(t["reason"])}</p>'
        )
        if stocks:
            rows += (
                '<details><summary><span class="light-head">' + head + '</span>'
                + rc.icon("i-chevron") + '</summary>'
                '<div class="details-body">' + meta + _theme_stock_list(stocks) + '</div></details>'
            )
        else:
            rows += '<div class="card"><div class="light-head">' + head + '</div>' + meta + '</div>'
    return rows


def stock_card(sid, data, one_liner):
    """個股 · 本期名單（03 層，展開細節）：沿用 summary/紅綠燈點/理由。"""
    s = data["summary"]
    lights = [data["fundamental"]["light"], data["technical"]["light"], data["chips"]["light"]]
    dircode = "green" if s["score"] > 0.3 else "red" if s["score"] < -0.3 else "amber"
    verdict_cls = "up" if dircode == "green" else "down" if dircode == "red" else "muted"
    dots = "".join(f'<span class="dot {rc.traffic(l)[0]}"></span>' for l in lights)
    evs = ""
    for key, zh in [("fundamental", "基本面"), ("technical", "技術面"), ("chips", "消息/籌碼")]:
        b = data[key]
        cls, lzh = rc.traffic(b["light"])
        evs += f'<span><span class="dot {cls}"></span> {zh} {lzh}</span>'
    tev = data.get("technical", {}).get("ev", {})
    buy, res = tev.get("買入參考區"), tev.get("壓力參考位")
    lvls = ""
    if buy or res:
        lvls = (
            '<div class="tags">'
            f'<span class="tag">買入參考區 {rc.esc(buy or "—")}</span>'
            f'<span class="tag">壓力參考位 {rc.esc(res or "—")}</span></div>'
        )
    return (
        '<details><summary>'
        f'<span>{rc.esc(data["name"])} <span class="muted num">{rc.esc(sid)}</span> {dots}</span>'
        + _pill("chip", verdict_cls, s["direction"]) + rc.icon("i-chevron") + '</summary>'
        '<div class="details-body">'
        f'<div class="evidence">{evs}</div>{lvls}'
        f'<p class="reason">{rc.esc(one_liner)}</p>'
        f'<p class="source">加權分 {s["score"]} · 信心 {rc.esc(s["confidence"])} · 技術位為規則參考非買賣建議</p>'
        '</div></details>'
    )


def stock_mini_card(sid, data, one_liner):
    """首屏個股決策卡縮影：代號名稱、rating、信心、防守、觸發、一句話。只讀引擎，不需個股 narration。"""
    dec = data.get("decision", {}) or {}
    rating = dec.get("rating", "—")
    ccls = RATING_CLS.get(rating, "muted")
    conf = (dec.get("confidence") or {}).get("total", 0)
    stop_price = (dec.get("stop") or {}).get("price")
    breakout = (dec.get("entry") or {}).get("breakout", "") or ""
    return (
        '<article class="card">'
        '<div class="light-head">'
        f'<h3>{rc.esc(data.get("name", ""))} <span class="muted num">{rc.esc(sid)}</span></h3>'
        + _pill("chip", ccls, rating) +
        '</div>'
        '<div class="kpis">'
        f'<div class="kpi"><small>信心</small><strong class="num">{conf}</strong></div>'
        f'<div class="kpi"><small>防守</small><strong class="num">{_n1(stop_price)}</strong></div>'
        f'<div class="kpi"><small>觸發</small><strong>{rc.esc(breakout)}</strong></div>'
        '</div>'
        f'<p class="reason">{rc.esc(one_liner)}</p>'
        '</article>'
    )


def _events_body(n, events_json):
    """05 事件層：優先手寫 n["events"]，附 events.json 未來 7 天法說。"""
    rows = "".join(
        '<div class="event">'
        f'<span class="date">{rc.esc(e["d"])}</span>'
        f'<b>{rc.esc(e["t"])}</b><span class="muted">{rc.esc(e["m"])}</span>'
        '</div>'
        for e in n.get("events", [])
    )
    upcoming = ""
    if events_json:
        conf_events = [
            e for e in events_json.get("events", [])
            if (e.get("days_ahead") is not None and e.get("days_ahead") <= 7) and e.get("type") == "法說會"
        ]
        if conf_events:
            items = "".join(
                '<div class="event">'
                f'<span class="date">{rc.esc(e.get("date", ""))}（+{e.get("days_ahead", 0)} 天）</span>'
                f'<b>{rc.esc(e.get("name", ""))}</b><span class="muted">{rc.esc(e.get("detail", ""))}</span>'
                '</div>'
                for e in conf_events[:8]
            )
            upcoming = f'<p class="source">未來 7 天法說</p><div class="grid two">{items}</div>'
    return rows + upcoming


def render_weekly_html(ctx):
    """純函式：組週報 HTML。ctx = {"n","market","us_sectors","tw_sectors","stocks","events_json"}
    （另可選填 "themes"/"theme_stocks" 供 04 主題層，build() 會補上；ctx 未給時該層顯示空）。"""
    n = ctx["n"]
    m = ctx["market"]
    us_sec = ctx.get("us_sectors") or []
    tw_sec = ctx.get("tw_sectors") or []
    stocks = ctx.get("stocks") or {}
    events_json = ctx.get("events_json")
    themes = ctx.get("themes") or []
    theme_stocks = ctx.get("theme_stocks") or {}

    code, zh = LIGHT.get(m.get("light"), ("y", "中性"))
    risk = n.get("risk_temp", 0)
    risk_pct = risk * 10

    foreign_html = ""
    if m.get("foreign"):
        net = m["foreign"]["net_yi"]
        foreign_html = (
            '<div class="kpi"><small>外資買賣超</small>'
            f'<strong class="num {chg_cls(net)}">{net:+,.0f} 億</strong>'
            f'<small>{rc.esc(m["foreign"].get("date", ""))}</small></div>'
        )

    stock_sids = [sid for sid in n.get("stocks", {}) if sid in stocks]
    mini_cards = "".join(stock_mini_card(sid, stocks[sid], n["stocks"][sid]) for sid in stock_sids)
    stock_cards = "".join(stock_card(sid, stocks[sid], n["stocks"][sid]) for sid in stock_sids)

    gen = datetime.now(TPE).strftime("%Y-%m-%d %H:%M")

    return (
        rc.head(f'戰情週報 {n.get("period", "")} · 專屬投顧戰情室')
        + '<div class="page">'
        + '<div class="topbar"><span class="brand">' + rc.icon("i-chart") + 'Advisor War Room</span>'
        + '<span>真實資料 · FinMind × TWSE × yfinance × Google News · 資料日 '
        + rc.esc(n.get("asof", "")) + '</span></div>'
        + '<header class="hero"><div>'
        + f'<h1>戰情週報 {rc.esc(n.get("period", ""))}</h1>'
        + f'<p class="lead">一週兩次 · 產出 {rc.esc(gen)}（台北）</p>'
        + '</div></header>'

        # 首屏主卡：決策 + 大盤溫度儀表
        + '<section class="card decision weekly" aria-labelledby="weekly-title">'
        + '<div class="decision-grid"><div>'
        + '<span class="eyebrow">本週研判 · 首屏優先</span>'
        + f'<h2 id="weekly-title" class="rating">{rc.esc(n.get("direction", ""))}</h2>'
        + f'<p class="reason">{rc.esc(n.get("chief", ""))}</p>'
        + '</div>'
        + f'<div class="confidence" style="--p:{risk_pct}%"><div><b>{rc.esc(risk)}</b>'
        + '<span>風險溫度 / 10</span></div></div>'
        + '</div>'
        + '<div class="kpis">'
        + f'<div class="kpi"><small>建議股票曝險</small><strong>{rc.esc(n.get("exposure", ""))}</strong></div>'
        + f'<div class="kpi"><small>大盤環境</small><strong><span class="dot {code}"></span> {zh}</strong></div>'
        + f'<div class="kpi"><small>本週信心</small><strong>{rc.esc(n.get("confidence", ""))}</strong></div>'
        + '</div></section>'

        # 個股決策卡縮影
        + '<section id="mini-stocks">' + rc.section_head("i-check", "個股決策卡縮影")
        + '<div class="grid two">' + mini_cards + '</div></section>'

        # 01 大盤
        + '<details open><summary>01 · 大盤 · 環境溫度' + rc.icon("i-chevron") + '</summary>'
        + '<div class="details-body">' + index_grid(m.get("items", [])) + foreign_html
        + f'<p class="source">{rc.esc(n.get("market", ""))}</p>'
        + '</div></details>'

        # 02 類股（美股族群 + 台股類股輪動真實強度）
        + '<details open><summary>02 · 類股 · 資金往哪流' + rc.icon("i-chevron") + '</summary>'
        + '<div class="details-body">'
        + market_strip(m.get("items", []))
        + '<h3>美股族群動能排名（點列展開對應台股供應鏈）</h3>'
        + sector_rows(us_sec)
        + '<h3>台股類股輪動 · 真實強度</h3>'
        + tw_sector_rows(tw_sec)
        + f'<p class="source">{rc.esc(n.get("sector", ""))}</p>'
        + '</div></details>'

        # 03 個股名單
        + '<details open><summary>03 · 個股 · 本期名單' + rc.icon("i-chevron") + '</summary>'
        + '<div class="details-body">' + stock_cards
        + '<p class="source">＊來源：選股器機會清單，經團隊三維研判。說「研究 XXXX」可產完整單檔報告。</p>'
        + '</div></details>'

        # 04 主題雷達
        + '<details><summary>04 · 主題雷達 · 看未來' + rc.icon("i-chevron") + '</summary>'
        + '<div class="details-body">'
        + '<p class="source">新技術／話題發掘 · 熱度上升＋個股確認才「成案」，只有噪音的僅進觀察</p>'
        + theme_rows(themes, theme_stocks)
        + f'<p class="source">{rc.esc(n.get("theme", ""))}</p>'
        + '</div></details>'

        # 05 事件
        + '<details><summary>05 · 本期關鍵事件' + rc.icon("i-chevron") + '</summary>'
        + '<div class="details-body grid two">' + _events_body(n, events_json) + '</div></details>'

        + rc.disclaimer(
            "紅綠燈由「數據＋固定規則」計算，團隊觀點由分析師解讀與反駁，不憑感覺喊買賣。"
            "跨市場輪動只用「昨晚美股已收盤」資料。",
            "<b>本報告為投資決策輔助，非投資建議、非保證獲利，最終決策與風險由使用者承擔。</b>"
            "資料來源與時間如上；抓不到即註記缺漏、絕不編造。",
        )
        + "</div>"
    )


def build():
    m = fetch_market()
    sec = fetch_sectors()
    try:
        tw_sec = fetch_tw_sectors()
    except Exception:
        tw_sec = []
    n = json.load(open("data/weekly_narration.json", encoding="utf-8"))
    stocks = {}
    for sid in n["stocks"]:
        p = f"data/{sid}.json"
        if os.path.exists(p):
            stocks[sid] = json.load(open(p, encoding="utf-8"))
    from warroom.consistency import check_weekly_consistency, assert_consistent
    assert_consistent(check_weekly_consistency(stocks, n), "週報")

    try:
        with open("data/tw_sectors.json", "w", encoding="utf-8") as f:
            json.dump(tw_sec, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    themes = json.load(open("data/themes.json", encoding="utf-8")) if os.path.exists("data/themes.json") else []
    theme_stocks = (json.load(open("data/theme_stocks.json", encoding="utf-8"))
                     if os.path.exists("data/theme_stocks.json") else {})
    events_json = None
    if os.path.exists("data/events.json"):
        events_json = json.load(open("data/events.json", encoding="utf-8"))

    ctx = {
        "n": n, "market": m, "us_sectors": sec, "tw_sectors": tw_sec,
        "stocks": stocks, "events_json": events_json,
        "themes": themes, "theme_stocks": theme_stocks,
    }
    return render_weekly_html(ctx)


if __name__ == "__main__":
    os.makedirs("reports", exist_ok=True)
    # 先 build 完才開檔寫入：避免一致性閘門中途 exit 時把舊報告截成空檔
    html_out = build()
    with open("reports/weekly.html", "w", encoding="utf-8") as f:
        f.write(html_out)
    print("→ 已產出 reports/weekly.html")
