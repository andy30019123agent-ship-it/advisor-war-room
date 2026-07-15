"""單檔投顧報告產生器：讀 data/<id>.json（引擎數據）＋ data/<id>.narration.json（Claude 團隊觀點）
→ 產 reports/<id>.html（Neumorphism 柔白＋淡粉版）。這是真實資料報告，非示意。

渲染是純函式：render_stock_html(d, n, stats, events) 只吃 dict/list、回字串，
無網路、無 assert，可離線測試。build() 負責讀檔＋一致性 assert＋落檔的既有流程。
"""
import json
import os
import sys

from warroom import render_common as rc
from warroom import track_record

_FACTOR_ORDER = (
    ("revenue", "營收"), ("eps", "EPS"), ("gross_margin", "毛利率"),
    ("operating_margin", "營益率"), ("roe", "ROE"), ("fcf", "現金流"), ("debt", "負債"),
)
_GROUP_ORDER = ("外資", "投信", "自營")
_DEFAULT_HORIZON_DAYS = 14  # events.json 目前 horizon_days=14；純函式介面未傳入該值，此為揭露的假設


def _n1(x):
    """價格類數字統一 1 位小數、不加千分位（合理價值區間需與敘事逐字比對，逗號會拆散數字）。"""
    if x is None:
        return "—"
    return "{:.1f}".format(x)


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _stance_cls(stance):
    if "多" in stance:
        return "up"
    if "空" in stance:
        return "down"
    return "muted"


def _split_label(s):
    """「價格：收盤…（未觸發）」→ (「價格」, 「收盤…（未觸發）」)，字串已含中文冒號。"""
    if "：" in s:
        label, rest = s.split("：", 1)
        return label, rest
    return "", s


def _hero(d, n, sid):
    as_of_price = d.get("decision", {}).get("as_of_price")
    asof = n.get("as_of", "—")
    chips = [f'<span class="chip">現價 <span class="num">{_n1(as_of_price)}</span></span>']
    chips.append(f'<span class="chip">資料時間 <span class="num">{rc.esc(asof)}</span></span>')
    chips.append('<span class="chip">綠漲紅跌</span>')
    return (
        '<div class="topbar"><span class="brand">' + rc.icon("i-chart")
        + 'Advisor War Room</span><span>真實資料 · FinMind × TWSE × Google News · '
        + rc.esc(asof) + '</span></div>'
        '<header class="hero"><div><h1>' + rc.esc(d.get("name", "")) + " "
        + rc.esc(sid) + '<br>戰術決策報告</h1></div>'
        '<div class="meta">' + "".join(chips) + "</div></header>"
    )


def _decision_card(dec, n):
    rating = dec.get("rating", "—")
    chief = n.get("roles", {}).get("chief", "")
    pos = dec.get("position", {}) or {}
    conf = dec.get("confidence", {}) or {}
    stop = dec.get("stop", {}) or {}

    note_html = ""
    core_note = pos.get("core_note") or ""
    if core_note:
        note_html = ('<div class="note">' + rc.icon("i-shield")
                     + "<span>" + rc.esc(core_note) + "</span></div>")

    amount = pos.get("amount", 0) or 0
    tier = pos.get("tier", "空手")
    if amount == 0:
        pos_strong = "空手｜0 元"
    else:
        pos_strong = f"{rc.esc(tier)}｜{amount:,} 元"
    lots = pos.get("lots", 0) or 0
    odd_shares = pos.get("odd_shares", 0) or 0
    pos_small = f"{lots} 張" + (f" + {odd_shares} 股" if odd_shares > 0 else "")

    stop_small = f"{rc.esc(stop.get('basis', '—'))}／{rc.esc(stop.get('note', ''))}"

    return (
        '<section class="card decision" aria-labelledby="decision-title">'
        '<div class="decision-grid"><div>'
        '<span class="eyebrow">決策卡 · 首屏優先</span>'
        f'<h2 id="decision-title" class="rating">{rc.esc(rating)}</h2>'
        f'<p class="reason">核心理由：{rc.esc(chief)}</p>'
        f'{note_html}</div>'
        f'{rc.confidence_gauge(conf.get("total", 0))}</div>'
        '<div class="kpis">'
        f'<div class="kpi"><small>部位金額建議</small><strong>{pos_strong}</strong><small>{pos_small}</small></div>'
        f'<div class="kpi"><small>操作分級</small><strong>{rc.esc(rating)}</strong><small>買進、試單、續抱、觀望、減碼</small></div>'
        f'<div class="kpi"><small>防守線</small><strong class="num">{_n1(stop.get("price"))}</strong><small>{stop_small}</small></div>'
        '</div></section>'
    )


def _jump_nav():
    items = (
        ("#frames", "時間框架"), ("#value", "價值區間"), ("#entry", "進場失效"),
        ("#signals", "紅綠燈"), ("#quality", "財報品質"), ("#inst", "法人分拆"),
        ("#team", "角色觀點"),
    )
    return '<nav class="jump" aria-label="快速導覽">' + "".join(
        f'<a href="{href}">{rc.esc(label)}</a>' for href, label in items) + "</nav>"


def _time_frames(tf):
    cards = []
    for key in ("short", "swing", "mid"):
        f = tf.get(key, {}) or {}
        label, basis, ref = f.get("label", "—"), f.get("basis", ""), f.get("ref_price", "")
        stance = f.get("stance", "")
        cards.append(
            f'<article class="card time"><h3>{rc.esc(label)}</h3><p>{rc.esc(basis)}</p>'
            '<div class="tags">'
            f'<span class="tag {_stance_cls(stance)}">{rc.esc(stance)}</span>'
            f'<span class="tag">{rc.esc(ref)}</span>'
            '</div></article>'
        )
    return ('<section id="frames">' + rc.section_head("i-chart", "三時間框架")
           + '<div class="grid three">' + "".join(cards) + "</div></section>")


def _value_section(dec):
    fv = dec.get("fair_value", {}) or {}
    val = dec.get("valuation", {}) or {}
    bear, base, bull = fv.get("bear"), fv.get("base"), fv.get("bull")
    as_of_price = dec.get("as_of_price")
    if bear is not None and bull is not None and bull != bear and as_of_price is not None:
        p = _clamp((as_of_price - bear) / (bull - bear) * 100, 2, 98)
    else:
        p = 50
    path = val.get("path", "per")
    method = (
        "方法：純歷史 PBR 分位回歸推估合理倍數（Bear/Base/Bull＝25/50/75 分位）；"
        "高本益比成長股的 Bull 情境偏樂觀，僅供區間參考、非目標價。"
        if path == "pbr" else
        "方法：純歷史 PER 分位回歸推估合理倍數（Bear/Base/Bull＝25/50/75 分位）；"
        "高本益比成長股的 Bull 情境偏樂觀，僅供區間參考、非目標價。"
    )
    pbr_line = ""
    if path == "pbr":
        bvps, roe = val.get("bvps"), val.get("roe")
        pbr_line = (f'<p class="source">每股淨值 <span class="num">{_n1(bvps)}</span>、'
                    f'ROE {rc.fmt_pct(roe, False)}</p>')
    return (
        '<section id="value">' + rc.section_head("i-chart", "合理價值區間")
        + '<div class="card">'
        f'<div class="band" aria-label="Bear Base Bull valuation band"><i style="left:{p:.1f}%"></i></div>'
        '<div class="legend">'
        f'<span>Bear <b class="num">{_n1(bear)}</b></span>'
        f'<span>Base <b class="num">{_n1(base)}</b></span>'
        f'<span>Bull <b class="num">{_n1(bull)}</b></span>'
        '</div>'
        f'<p class="source">{rc.esc(val.get("disclosure", ""))}</p>'
        f'{pbr_line}'
        f'<p class="source">{method}</p>'
        '</div></section>'
    )


def _rr_section(dec):
    as_of_price = dec.get("as_of_price")
    bull = (dec.get("fair_value") or {}).get("bull")
    stop_price = (dec.get("stop") or {}).get("price")
    up_pct = (bull - as_of_price) / as_of_price if (bull is not None and as_of_price) else None
    down_pct = (stop_price - as_of_price) / as_of_price if (stop_price is not None and as_of_price) else None
    rr = dec.get("risk_reward")
    rr_disp = "—" if rr is None else "{:g}".format(rr)
    return (
        '<section>' + rc.section_head("i-shield", "風險報酬比")
        + '<div class="rr">'
        f'<div class="flat"><small>上檔至 Bull</small><strong class="up">{rc.fmt_pct(up_pct)}</strong></div>'
        f'<div class="flat"><small>下檔至停損</small><strong class="down">{rc.fmt_pct(down_pct)}</strong></div>'
        f'<div class="flat"><small>R/R</small><strong class="num">{rr_disp}</strong></div>'
        '</div><p class="muted">R/R&lt;1.5 不建議追價</p></section>'
    )


def _entry_section(dec):
    entry = dec.get("entry", {}) or {}
    inv = dec.get("invalidation", {}) or {}
    triggered = inv.get("any_triggered", False)
    pill = '<span class="pill down">已觸發失效</span>' if triggered else ""
    invalid_cards = []
    for key in ("price", "fundamental", "chips"):
        label, rest = _split_label(inv.get(key, "") or "")
        invalid_cards.append(f'<div><b>{rc.esc(label)}：</b>{rc.esc(rest)}</div>')
    # entry.pullback/breakout 字串本身已含「回測型：／突破型：」前綴，h3 已標題化，
    # 顯示時去重複前綴避免「回測型／回測型：…」疊字。
    _, pullback_rest = _split_label(entry.get("pullback", "") or "")
    _, breakout_rest = _split_label(entry.get("breakout", "") or "")
    return (
        f'<section id="entry">{rc.section_head("i-check", "進場條件與失效")}{pill}'
        '<div class="grid two conditions">'
        f'<div class="card"><h3>回測型</h3><p>{rc.esc(pullback_rest)}</p></div>'
        f'<div class="card"><h3>突破型</h3><p>{rc.esc(breakout_rest)}</p></div>'
        '</div>'
        f'<div class="invalid">{"".join(invalid_cards)}</div>'
        '</section>'
    )


def _signals_section(d):
    order = (("technical", "技術"), ("fundamental", "基本面"), ("chips", "籌碼"))
    cards = []
    for key, label in order:
        block = d.get(key, {}) or {}
        cls, zh = rc.traffic(block.get("light"))
        evidence = "".join(
            f'<span>{rc.esc(k)} {rc.esc(v)}</span>' for k, v in (block.get("ev") or {}).items())
        cards.append(
            '<article class="card light"><div class="light-head">'
            f'<h3>{rc.esc(label)}</h3><span><span class="dot {cls}"></span> {rc.esc(zh)}</span>'
            f'</div><div class="evidence">{evidence}</div></article>'
        )
    return ('<section id="signals">' + rc.section_head("i-chart", "三維紅綠燈")
           + '<div class="lights">' + "".join(cards) + "</div></section>")


def _quality_section(fq):
    factors = fq.get("factors", {}) or {}
    rows = []
    for key, label in _FACTOR_ORDER:
        f = factors.get(key, {}) or {}
        applicable = f.get("applicable", True)
        score = f.get("score", 0) or 0
        width = 0 if not applicable else round(score / 2 * 100)
        score_disp = "不適用" if not applicable else str(score)
        rows.append(
            f'<div class="factor"><span>{rc.esc(label)}</span>'
            f'<span class="bar"><i style="width:{width}%"></i></span>'
            f'<span class="score">{rc.esc(score_disp)}</span></div>'
        )
    total, mx = fq.get("total", 0), fq.get("max", 0)
    return (
        '<section id="quality">' + rc.section_head("i-check", "財報品質分數")
        + '<div class="card quality">' + "".join(rows)
        + f'<p class="source">總分 <span class="num">{total} / {mx}</span>；{rc.esc(fq.get("note", ""))}</p>'
        + '</div></section>'
    )


def _inst_section(breakdown):
    groups = breakdown.get("groups", {}) or {}
    cards = []
    for name in _GROUP_ORDER:
        g = groups.get(name, {}) or {}
        direction = g.get("dir", "—")
        cls = "up" if direction == "買" else "down"
        ratio = g.get("ratio_20d_vol")
        ratio_txt = f" · 佔均量 {rc.fmt_pct(ratio, False)}" if ratio is not None else ""
        cards.append(
            f'<div class="card inst-item"><b>{rc.esc(name)}</b>'
            f'<span><span class="{cls} num">{rc.zhang(g.get("net_latest"))}</span><br>'
            f'<small>連{rc.esc(direction)} {g.get("streak", "—")} 日{ratio_txt}</small></span></div>'
        )
    note = ""
    if breakdown.get("divergence"):
        note = f'<span class="split-note">{rc.esc(breakdown.get("divergence_note", ""))}</span>'
    return (
        '<section id="inst">' + rc.section_head("i-chart", "法人分拆")
        + '<div class="inst">' + "".join(cards) + "</div>" + note + "</section>"
    )


def _team_section(roles):
    order = (
        ("fundamental", "基本面分析師"), ("technical", "技術分析師"), ("news", "消息分析師"),
        ("risk", "風控長"), ("devil", "魔鬼代言人"), ("chief", "投資長"),
    )
    cards = "".join(
        f'<article class="card voice"><h3>{rc.esc(label)}</h3><p>{rc.esc(roles.get(key, ""))}</p></article>'
        for key, label in order
    )
    return ('<section id="team">' + rc.section_head("i-check", "六角色觀點")
           + '<div class="grid two team">' + cards + "</div></section>")


def _news_events_track(d, stats, events):
    news = d.get("news", []) or []
    news_html = "".join(
        f'<a href="{rc.esc(a.get("url", "#"))}" target="_blank" rel="noopener">'
        f'<span class="date">{rc.rfc_to_mmdd(a.get("date", ""))}</span>'
        f'<b>{rc.esc(a.get("title", ""))}</b><span class="muted">{rc.esc(a.get("src", ""))}</span></a>'
        for a in news[:6]
    ) or '<p class="muted">（本次未取得新聞）</p>'

    events = events or []
    events_html = "".join(
        '<div class="event">'
        f'<span class="date">{rc.esc(e.get("date", ""))}（+{e.get("days_ahead", 0)} 天）</span>'
        f'<b>{rc.esc(e.get("name", ""))} · {rc.esc(e.get("detail", ""))}</b>'
        f'<span>{rc.esc(e.get("type", ""))}／{rc.esc(e.get("confidence", ""))}｜來源 {rc.esc(e.get("source", ""))}</span>'
        '</div>'
        for e in events
    ) or f'<p class="muted">（未來 {_DEFAULT_HORIZON_DAYS} 天無登錄事件）</p>'

    stats = stats or {}
    resolved = stats.get("resolved", 0) or 0
    hit_rate = stats.get("hit_rate")
    if resolved >= 5 and hit_rate is not None:
        track_html = (
            f'<div class="hit"><b>近 {resolved} 次已結案命中率 {rc.fmt_pct(hit_rate, False)}</b></div>'
            f'<div class="hit"><b>平均 R {stats.get("avg_r", "—")}</b></div>'
        )
    else:
        total_logged = stats.get("total_logged", 0) or 0
        track_html = (
            '<div class="hit"><b>資料累積中'
            f'（已登錄 {total_logged} 筆、已結案 {resolved} 筆；達 5 筆結案後顯示命中率）</b></div>'
        )

    return (
        '<section class="grid">'
        f'<details open><summary>新聞列表 {rc.icon("i-chevron")}</summary>'
        f'<div class="details-body">{news_html}</div></details>'
        f'<details open><summary>事件日曆 {rc.icon("i-chevron")}</summary>'
        f'<div class="details-body grid two">{events_html}</div></details>'
        f'<details><summary>戰績牆 {rc.icon("i-chevron")}</summary>'
        f'<div class="details-body grid two">{track_html}</div></details>'
        '</section>'
    )


def render_stock_html(d, n, stats=None, events=None):
    """純函式：組個股報告 HTML。d=data/<id>.json，n=narration，
    stats=track_record.compute_stats(log)（可 None），events=events.json 過濾後 list（可 None）。"""
    sid = d.get("stock_id", "")
    dec = d.get("decision", {}) or {}
    fq = d.get("fundamentals_quality", {}) or {}
    chips_breakdown = d.get("chips", {}).get("breakdown", {}) or {}
    roles = n.get("roles", {}) or {}

    title = f'{d.get("name", "")} {sid} · 投顧戰情報告'
    body = (
        rc.head(title)
        + '<div class="page">'
        + _hero(d, n, sid)
        + _decision_card(dec, n)
        + _jump_nav()
        + _time_frames(dec.get("time_frames", {}) or {})
        + _value_section(dec)
        + _rr_section(dec)
        + _entry_section(dec)
        + _signals_section(d)
        + _quality_section(fq)
        + _inst_section(chips_breakdown)
        + _team_section(roles)
        + _news_events_track(d, stats, events)
        + rc.disclaimer(
            "紅綠燈由「數據＋固定規則」計算（技術面均線／RSI／量能、基本面營收 YoY／PER 分位、"
            "籌碼三大法人淨買），團隊觀點由分析師解讀與反駁，不憑感覺喊買賣。"
            "<b>本報告為投資決策輔助，非投資建議、非保證獲利，最終決策與風險由使用者承擔。</b>"
            "數據來源與抓取時間如上；抓不到即註記缺漏、絕不編造。",
            dec.get("disclaimer", ""),
        )
        + "</div>"
    )
    return body


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_log(path="data/recommendation_log.json"):
    if not os.path.exists(path):
        return []
    return _load(path)


def _load_events(sid, path="data/events.json"):
    if not os.path.exists(path):
        return []
    ev = _load(path).get("events", [])
    return [e for e in ev if e.get("stock_id") in (sid, None)]


def build(stock_id):
    d = _load(f"data/{stock_id}.json")
    n = _load(f"data/{stock_id}.narration.json")
    from warroom.consistency import check_stock_consistency, assert_consistent
    assert_consistent(check_stock_consistency(d, n), f"個股報告 {stock_id}")
    stats = track_record.compute_stats(_load_log())
    events = _load_events(stock_id)
    return render_stock_html(d, n, stats, events)


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else "2330"
    os.makedirs("reports", exist_ok=True)
    out = f"reports/{sid}.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(build(sid))
    print(f"→ 已產出 {out}")
