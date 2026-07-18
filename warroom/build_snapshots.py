"""快照產線：讀 data/<id>.json（引擎產物）＋大盤資料 → 組出 public/data/daily.json 與
public/data/stocks/<id>.json，嚴格照 docs/contracts/data-contract-v1.md（下稱「契約」）。

用法：
  python3 -m warroom.build_snapshots

設計原則：
- 網路呼叫（FinMind／yfinance）只集中在 fetch_market_inputs()；其餘全是純函式，
  離線可測（tests/test_build_snapshots.py 用 repo 內既有 data/*.json 跑，不打網路）。
- 個股 data/<id>.json 缺 primary_decision/context/evidence（舊格式）→ 該股跳過並在
  stderr 警告，不得讓整批 build 失敗（契約硬規則 3：graceful degrade）。
- 契約沒有資料源可產生的欄位一律給 null，不編數字（見模組尾端「已知缺口」說明）。
"""
import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Tuple

from warroom.finmind_cache import cached_fetch
from warroom.market import fetch_market
from warroom.primary_decision import build_advice, build_defense_explain, generate_roles
from warroom.profile import load_profile

_TPE = timezone(timedelta(hours=8))

DATA_DIR = "data"
OUT_DIR = "public/data"
STOCK_ID_RE = re.compile(r"^\d{4,6}$")
RECOMMENDATION_LOG = "data/recommendation_log.json"
# v1.3 forecast_log 準確度管線（引擎內部檔，非前端契約，見契約文末「v1.3 增補」）。
FORECAST_LOG = "data/forecast_log.json"
# 各 horizon 到期所需交易日數（week=forecast.week_range_70／m1／m3，對齊 forecast.horizons）。
FORECAST_HORIZON_TRADING_DAYS = {"week": 5, "m1": 21, "m3": 63}
FORECAST_ACCURACY_MIN_SAMPLES = 10
FORECAST_ACCURACY_NOTE_INSUFFICIENT = "樣本累積中：每天記錄預估區間，5 日後開始回填驗證"
# 未來事件來源①：法說會行事曆（姊妹專案；不存在則跳過，不編）。
EARNINGS_CALENDAR = "../tw-earnings-calendar/data/latest.json"
EVENTS_WINDOW_DAYS = 14
# 法說會行事曆／個股 events 的中文事件別 → 契約 events[].type
_EVENT_TYPE_MAP = {"法說會": "earnings", "除息": "ex_dividend", "除權息": "ex_dividend",
                   "除權": "ex_dividend", "月營收": "revenue", "營收": "revenue"}

# 契約 context.lights.color 只收 green/yellow/red/null。warroom/primary_decision.py
# 端已把 amber→yellow、na→null 正規化過（見該檔 _normalize_light_color），這裡只做
# 防禦性透传：遇到未預期的舊值仍保留一次 fallback 對照表，缺資料一律回 None，不編色。
_COLOR_MAP = {"green": "green", "yellow": "yellow", "amber": "yellow", "red": "red"}

# 核心持股中，非引擎覆蓋範圍（如 ETF）的已知名稱，供 core_holdings 區塊顯示用。
_KNOWN_UNTRACKED_NAMES = {"0050": "元大台灣50"}

_US_INDEXES = [
    ("SPX", "S&P 500", "^GSPC"),
    ("NDX", "Nasdaq 100", "^NDX"),
    ("SOX", "費城半導體", "^SOX"),
    ("VIX", "VIX", "^VIX"),
]

_CONCLUSION_TEMPLATE = {
    "偏空防禦": "今天不加碼，守好停損位。",
    "中性": "盤勢中性，維持既有部位觀察。",
    "偏多進攻": "偏多格局，可留意進場機會。",
}


# ---------- 共用小工具 ----------
def _today() -> str:
    return datetime.now(_TPE).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(_TPE).isoformat(timespec="seconds")


def _num(x) -> Optional[float]:
    """寬鬆轉數值；非數字（如「樣本不足」字串、None）一律回 None，不得編數字。"""
    if x is None:
        return None
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def build_meta(sources: List[str], data_date: Optional[str] = None) -> Dict:
    # data_date＝行情資料日（契約定義），不是產生日；抓不到行情日才 fallback 今天。
    return {
        "schema_version": 1,
        "data_date": data_date or _today(),
        "generated_at": _now_iso(),
        "sources": sources,
    }


def write_json(path: str, obj: Dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------- 讀個股引擎產物 ----------
def discover_stock_files(data_dir: str = DATA_DIR) -> Dict[str, str]:
    """回 {stock_id: path}，只取檔名為純數字（4-6 碼）的個股 json，
    排除 investor_profile.json／recommendation_log.json／*.narration.json 等設定或衍生檔。"""
    out = {}
    for path in sorted(glob.glob(os.path.join(data_dir, "*.json"))):
        stem = os.path.splitext(os.path.basename(path))[0]
        if STOCK_ID_RE.match(stem):
            out[stem] = path
    return out


def is_new_format(res) -> bool:
    return (isinstance(res, dict) and "primary_decision" in res
            and "context" in res and "evidence" in res)


def load_stock_results(stock_files: Dict[str, str]) -> Tuple[Dict[str, Dict], List[Tuple[str, str]]]:
    """讀每檔 data/<id>.json；缺新欄位（舊格式）或讀檔失敗都跳過該股，記警告，不中斷整批。"""
    results, skipped = {}, []
    for sid, path in stock_files.items():
        try:
            with open(path, encoding="utf-8") as f:
                res = json.load(f)
        except Exception as e:
            skipped.append((sid, f"讀檔失敗：{type(e).__name__} {e}"))
            continue
        if not is_new_format(res):
            skipped.append((sid, "缺 primary_decision/context/evidence（舊格式引擎產物），跳過"))
            continue
        results[sid] = res
    return results, skipped


# ---------- 大盤區塊 ----------
def _daily_change_finmind(stock_id: str = "TAIEX") -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """回 (今日收盤, 日漲跌%, 行情日 YYYY-MM-DD)。抓失敗或資料不足 2 天 → (None, None, None)。"""
    try:
        start = (datetime.now(_TPE) - timedelta(days=14)).strftime("%Y-%m-%d")
        df = cached_fetch("taiwan_stock_daily", stock_id=stock_id, start_date=start)
        df = df.sort_values("date")
        if len(df) < 2:
            return None, None, None
        last = float(df.iloc[-1]["close"])
        prev = float(df.iloc[-2]["close"])
        chg = round((last / prev - 1) * 100, 2) if prev else None
        trade_date = str(df.iloc[-1]["date"])[:10]
        return round(last, 1), chg, trade_date
    except Exception:
        return None, None, None


def _daily_change_yf(ticker: str) -> Optional[float]:
    """回美股/總經指數日漲跌%。抓失敗或資料不足 → None。"""
    try:
        import yfinance as yf
        c = yf.Ticker(ticker).history(period="10d")["Close"].dropna()
        if len(c) < 2:
            return None
        last, prev = float(c.iloc[-1]), float(c.iloc[-2])
        return round((last / prev - 1) * 100, 2) if prev else None
    except Exception:
        return None


def fetch_market_inputs() -> Dict:
    """打網路：TAIEX 當日漲跌%（FinMind）＋ US 四指數當日漲跌%（yfinance）＋外資買賣超
    （沿用 warroom.market.fetch_market() 的合計，避免重算）。任何一段失敗都給 None，
    不讓整批 build 失敗（契約硬規則 3）。"""
    taiex_close, taiex_chg, trade_date = _daily_change_finmind("TAIEX")
    us = [{"id": id_, "name": name, "change_pct": _daily_change_yf(ticker)}
          for id_, name, ticker in _US_INDEXES]
    foreign_net_yi = None
    try:
        m = fetch_market()
        foreign_net_yi = (m.get("foreign") or {}).get("net_yi")
    except Exception:
        pass
    return {"taiex": {"close": taiex_close, "change_pct": taiex_chg},
            "us": us, "foreign_net_yi": foreign_net_yi,
            "trade_date": trade_date}


def compute_market_status(taiex_chg, sox_chg, vix_chg, foreign_net_yi) -> str:
    """三檔 status（偏多進攻｜中性｜偏空防禦），固定規則、可揭露：
    以台股加權指數、費半 SOX 當日漲跌，及外資買賣超（億元）為三個主訊號，
    VIX 大幅跳動為輔助訊號；同向訊號 ≥2 個且多於反向訊號 → 偏多/偏空，否則中性。"""
    bearish = sum([
        taiex_chg is not None and taiex_chg <= -1.0,
        sox_chg is not None and sox_chg <= -1.0,
        foreign_net_yi is not None and foreign_net_yi <= -100,
    ])
    bullish = sum([
        taiex_chg is not None and taiex_chg >= 1.0,
        sox_chg is not None and sox_chg >= 1.0,
        foreign_net_yi is not None and foreign_net_yi >= 100,
    ])
    if vix_chg is not None and vix_chg >= 8:
        bearish += 1
    if vix_chg is not None and vix_chg <= -8:
        bullish += 1
    if bearish >= 2 and bearish > bullish:
        return "偏空防禦"
    if bullish >= 2 and bullish > bearish:
        return "偏多進攻"
    return "中性"


def compute_risk_temp(status: str, taiex_chg, vix_chg) -> int:
    """1-10 風險溫度：以狀態為基準（偏空防禦 7／中性 5／偏多進攻 3），
    再依 VIX／TAIEX 波動幅度微調 ±1，夾在 1-10。"""
    base = {"偏空防禦": 7, "中性": 5, "偏多進攻": 3}[status]
    if vix_chg is not None:
        base += 1 if vix_chg >= 10 else -1 if vix_chg <= -10 else 0
    if taiex_chg is not None:
        base += 1 if taiex_chg <= -2 else -1 if taiex_chg >= 2 else 0
    return max(1, min(10, base))


def compute_conclusion(status: str) -> str:
    """一句話結論（≤20 字），純模板、不依賴人工 narration。"""
    return _CONCLUSION_TEMPLATE.get(status, "盤勢待觀察，紀律優先。")


def build_market_block(market_inputs: Dict) -> Dict:
    """純函式：由 fetch_market_inputs() 的資料組契約 market 區塊，離線可測。"""
    taiex = market_inputs.get("taiex") or {}
    us = market_inputs.get("us") or []
    foreign_net_yi = market_inputs.get("foreign_net_yi")
    by_id = {u.get("id"): u.get("change_pct") for u in us}
    taiex_chg = taiex.get("change_pct")
    status = compute_market_status(taiex_chg, by_id.get("SOX"), by_id.get("VIX"), foreign_net_yi)
    risk_temp = compute_risk_temp(status, taiex_chg, by_id.get("VIX"))
    return {
        "status": status,
        "risk_temp": risk_temp,
        "conclusion": compute_conclusion(status),
        "taiex": {"close": _num(taiex.get("close")), "change_pct": _num(taiex_chg)},
        "us": [{"id": u.get("id"), "name": u.get("name"), "change_pct": _num(u.get("change_pct"))}
               for u in us],
    }


# ---------- core_holdings ----------
def build_core_holdings(profile: Dict, results: Dict[str, Dict]) -> List[Dict]:
    out = []
    for sid in profile.get("core_holdings", []):
        if sid in results:
            name = results[sid].get("name", sid)
            out.append({"id": sid, "name": name, "action": "核心續扣", "note": "波段不加碼"})
        else:
            name = _KNOWN_UNTRACKED_NAMES.get(sid, sid)
            out.append({"id": sid, "name": name, "action": "定期定額照常",
                        "note": "不受本週訊號影響"})
    return out


# ---------- tracked / alerts ----------
def build_tracked_entry(stock_id: str, res: Dict) -> Dict:
    primary = res["primary_decision"]
    dec = res.get("decision") or {}
    return {
        "id": stock_id,
        "name": res.get("name", stock_id),
        "close": _num(dec.get("as_of_price")),
        "change_pct": None,  # 已知缺口：引擎目前不產出個股日漲跌%，見模組尾端說明
        "decision": {
            "action": primary["action"],
            "readable_reason": primary["readable_reason"],
            "defense_price": _num(primary.get("defense_price")),
        },
    }


def build_alerts_for_stock(stock_id: str, name: str, primary: Dict) -> List[Dict]:
    """從 primary_decision 的 defense_price/entry_condition 提取，不重算。"""
    out = []
    dp = _num(primary.get("defense_price"))
    if dp is not None:
        out.append({"id": stock_id, "name": name, "type": "defense",
                    "price": dp, "direction": "below"})
    ec = primary.get("entry_condition")
    if ec and ec.get("price") is not None:
        out.append({"id": stock_id, "name": name, "type": "entry",
                    "price": _num(ec["price"]), "direction": "above"})
    return out


# ---------- v1.1 daily：曝險規則 / 未來事件 / 戰績統計 ----------
def build_exposure_guidance(risk_temp: int) -> Dict:
    """風險溫度 → 白話曝險規則（規則表寫死、可揭露）：
    1-3→80%/可正常布局；4-6→60%/僅限試單；7-8→50%/僅限試單；9-10→40%/禁止新增部位。"""
    rt = int(risk_temp)
    if rt <= 3:
        max_equity, new_pos = 80, "可正常布局"
        note = f"風險溫度 {rt}/10：市場穩定，股票曝險可到 8 成，維持紀律正常布局。"
    elif rt <= 6:
        max_equity, new_pos = 60, "僅限試單"
        note = f"風險溫度 {rt}/10：波動升高，股票曝險控在 6 成，新倉僅限試單、分批進。"
    elif rt <= 8:
        max_equity, new_pos = 50, "僅限試單"
        note = f"風險溫度 {rt}/10：市場偏弱，現金至少留 5 成，只做小量試單、不追高。"
    else:
        max_equity, new_pos = 40, "禁止新增部位"
        note = f"風險溫度 {rt}/10：市場劇烈波動，現金至少留六成，今天不開新倉。"
    return {"risk_temp": rt, "max_equity_pct": max_equity,
            "min_cash_pct": 100 - max_equity, "new_position": new_pos, "note": note}


def _within_window(date_str: str, today: str, window_days: int) -> bool:
    """date_str 是否落在 [today, today+window_days]（含端點）。格式非 ISO 或缺值 → False。"""
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        t = datetime.strptime(today[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False
    return t <= d <= t + timedelta(days=window_days)


def build_events(results: Dict[str, Dict], today: Optional[str] = None,
                 calendar_path: str = EARNINGS_CALENDAR,
                 window_days: int = EVENTS_WINDOW_DAYS) -> List[Dict]:
    """未來 window_days 天、追蹤清單股票的事件。來源①法說會行事曆 latest.json、
    ②個股 data/<id>.json 的 evidence.events。抓不到一律空陣列，不編。"""
    today = today or _today()
    tracked = set(results.keys())
    names = {sid: res.get("name", sid) for sid, res in results.items()}
    seen, out = set(), []

    def _add(date, sid, name, label):
        etype = _EVENT_TYPE_MAP.get(label, "event")
        key = (date[:10], sid, label)
        if key in seen:
            return
        seen.add(key)
        out.append({"date": date[:10], "id": sid, "name": name, "type": etype, "label": label})

    # 來源①：法說會行事曆（只取追蹤清單、且在未來 window 內）
    if os.path.exists(calendar_path):
        try:
            with open(calendar_path, encoding="utf-8") as f:
                cal = json.load(f)
            for ev in cal.get("events") or []:
                sid = str(ev.get("id") or "")
                date = str(ev.get("date") or "")
                if sid in tracked and _within_window(date, today, window_days):
                    _add(date, sid, names.get(sid, sid), ev.get("type") or "法說會")
        except Exception:
            pass

    # 來源②：個股既有 events / 除息資料
    for sid, res in results.items():
        for ev in (res.get("evidence") or {}).get("events") or []:
            date = str(ev.get("date") or "")
            if _within_window(date, today, window_days):
                _add(date, sid, names.get(sid, sid), ev.get("label") or "事件")

    out.sort(key=lambda e: (e["date"], e["id"]))
    return out


def _add_calendar_days(date_str: str, days: int) -> str:
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        return (d + timedelta(days=days)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return ""


# 命中率方向感知（見 build_track_stats._rate）：看多動作（買進/續抱/試單）猜對＝股價漲，
# r>0 算命中；防禦動作（減碼——含出場，兩者 apply_derivations 都存成「減碼」——與觀望）
# 猜對＝股價沒漲甚至跌，r<=0 才算命中。不分方向、一律「r>0 算命中」會系統性低估防禦建議
# 的命中率（正確喊「先撤」結果股價真的跌，照舊規則反而算「沒中」）。未知/缺 rating 一律
# 照舊視為看多，維持既有預設行為。
_DEFENSIVE_RATINGS = {"減碼", "觀望"}


def _is_hit(rating: Optional[str], r: float) -> bool:
    if rating in _DEFENSIVE_RATINGS:
        return r <= 0
    return r > 0


def build_track_stats(log_path: str = RECOMMENDATION_LOG) -> Dict:
    """戰績統計：n＝總建議數；closed＝outcome.r5 非 null 的筆數；各期命中率＝該期報酬方向
    對（見 _is_hit：看多 r>0、防禦 r<=0）的比例，樣本 <5 給 null。note 動態寫最快回填日
    （最早 pending 日 +7 曆日 ≈ +5 交易日）。"""
    entries = []
    if os.path.exists(log_path):
        try:
            with open(log_path, encoding="utf-8") as f:
                entries = json.load(f) or []
        except Exception:
            entries = []
    n = len(entries)

    def _rate(field: str) -> Optional[float]:
        pairs = [(_num((e.get("outcome") or {}).get(field)), e.get("rating")) for e in entries]
        pairs = [(v, rating) for v, rating in pairs if v is not None]
        if len(pairs) < 5:
            return None
        return round(sum(1 for v, rating in pairs if _is_hit(rating, v)) / len(pairs), 3)

    closed = sum(1 for e in entries if _num((e.get("outcome") or {}).get("r5")) is not None)
    pending_dates = [e.get("date") for e in entries
                     if _num((e.get("outcome") or {}).get("r5")) is None and e.get("date")]
    if closed >= 5:
        note = f"已結算 {closed} 筆，命中率＝各期報酬為正的比例。"
    elif pending_dates:
        refill = _add_calendar_days(min(pending_dates), 7)
        note = f"樣本累積中，5 日結果最快 {refill} 開始回填"
    else:
        note = "尚無建議樣本，戰績待累積。"
    return {"n": n, "closed": closed,
            "hit_rate_5d": _rate("r5"), "hit_rate_20d": _rate("r20"),
            "hit_rate_60d": _rate("r60"), "note": note}


# ---------- daily.json ----------
def build_daily(profile: Dict, results: Dict[str, Dict], meta: Dict, market_block: Dict) -> Dict:
    tracked, alerts = [], []
    for sid in sorted(results):
        res = results[sid]
        tracked.append(build_tracked_entry(sid, res))
        alerts.extend(build_alerts_for_stock(sid, res.get("name", sid), res["primary_decision"]))
    return {
        "meta": meta,
        "market": market_block,
        "core_holdings": build_core_holdings(profile, results),
        "tracked": tracked,
        # 已知缺口：目前無 watchlist 資料源（無 config 記錄「有等待條件但無完整報告」的
        # 股票清單），保守回空陣列，不得編造清單內容，見模組尾端說明。
        "watch": [],
        "alerts_snapshot": alerts,
        "exposure_guidance": build_exposure_guidance(market_block["risk_temp"]),
        "events": build_events(results),
        "track_stats": build_track_stats(),
    }


# ---------- stocks/<id>.json ----------
def _parse_news_date(raw: Optional[str]) -> str:
    """把 news.py 給的 date（RFC822 或 GDELT %Y%m%dT%H%M%SZ）盡量轉 ISO；轉不了原樣回傳。"""
    if not raw:
        return ""
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_TPE).isoformat(timespec="seconds")
    except Exception:
        pass
    try:
        dt = datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return dt.astimezone(_TPE).isoformat(timespec="seconds")
    except Exception:
        return raw


def build_context(ctx: Dict) -> Dict:
    lights = ctx.get("lights") or {}

    def _light(key):
        block = lights.get(key) or {}
        return {"color": _COLOR_MAP.get(block.get("color")),  # 未知/na → None，不編色
                "facts": list(block.get("facts") or [])}

    val = ctx.get("valuation") or {}
    return {
        "timeframes": ctx.get("timeframes") or {},
        "lights": {
            "fundamental": _light("fundamental"),
            "technical": _light("technical"),
            "chips": _light("chips"),
        },
        "valuation": {
            "band": val.get("band"),
            "base": _num(val.get("base")),
            "bull": _num(val.get("bull")),
            "bear": _num(val.get("bear")),
            "regime": val.get("regime"),
            "warning": val.get("warning"),
        },
        "rr": _num(ctx.get("rr")),
    }


def build_evidence(evidence: Dict) -> Dict:
    news = []
    for n in (evidence.get("news") or []):
        news.append({
            "title": n.get("title", ""),
            "source": n.get("source") or n.get("src") or "—",
            "url": n.get("url", "") or "",
            "published_at": n.get("published_at") or _parse_news_date(n.get("date")),
        })
    events = []
    for e in (evidence.get("events") or []):
        events.append({
            "date": e.get("date", ""),
            "label": e.get("label", ""),
            "impact_note": e.get("impact_note", ""),
        })
    return {"roles": evidence.get("roles") or [], "news": news, "events": events}


def build_track(stock_id: str, log_path: str = RECOMMENDATION_LOG) -> List[Dict]:
    if not os.path.exists(log_path):
        return []
    try:
        with open(log_path, encoding="utf-8") as f:
            log = json.load(f)
    except Exception:
        return []
    entries = [e for e in log if e.get("stock_id") == stock_id]
    entries.sort(key=lambda e: e.get("date", ""), reverse=True)
    out = []
    for e in entries:
        price = _num(e.get("price"))
        if price is None:
            continue  # price_at_rec 契約要求 number，缺值的舊紀錄跳過（不編數字）
        outcome = e.get("outcome") or {}
        status = "pending" if outcome.get("hit") is None else "done"
        out.append({
            "date": e.get("date", ""),
            "action": e.get("rating", ""),
            "price_at_rec": price,
            "outcome": {"r5": _num(outcome.get("r5")), "r20": _num(outcome.get("r20")),
                        "r60": _num(outcome.get("r60"))},
            "status": status,
        })
    return out


def _clean_primary(primary: Dict) -> Dict:
    """契約 primary_decision 只收固定欄位；引擎 position 目前多帶一個 tier（人讀用途，
    非契約欄位），這裡重建 position 只留 tier_amount/lots/odd_shares，其餘照抄。"""
    out = dict(primary)
    out["defense_price"] = _num(out.get("defense_price"))
    out["confidence"] = int(out.get("confidence") or 0)
    src_pos = out.get("position") or {}
    out["position"] = {
        "tier_amount": _num(src_pos.get("tier_amount")) or 0,
        "lots": int(src_pos.get("lots") or 0),
        "odd_shares": int(src_pos.get("odd_shares") or 0),
    }
    ec = out.get("entry_condition")
    if ec:
        out["entry_condition"] = {"price": _num(ec.get("price")), "condition": ec.get("condition", "")}
    return out


def _build_advice_and_defense(res: Dict, is_core: bool,
                              market_new_position: Optional[str] = None) -> Tuple[Dict, str]:
    """v1.1：由已存的 primary_decision（唯一結論源）＋context facts＋decision.stop 派生
    雙版建議與防守價說明。全部從權威欄位重算，故與 primary 不會打架（契約硬規則 1）。

    market_new_position＝當下 exposure_guidance.new_position（見 build_exposure_guidance）：
    大盤「禁止新增部位」或「僅限試單」時，個股層級的 action 不該自己算出跟大盤矛盾的
    空手建議（例如大盤禁新倉，個股卻叫空手的人試單），交給 build_advice 依此收斂
    nonholder 那一版（見該函式 market_new_position 參數說明）。"""
    primary = res["primary_decision"]
    ctx = res.get("context") or {}
    dec = res.get("decision") or {}
    tech_facts = ((ctx.get("lights") or {}).get("technical") or {}).get("facts") or []
    price = _num(dec.get("as_of_price"))
    defense_price = _num(primary.get("defense_price"))
    advice = build_advice(
        action=primary["action"], reason_codes=primary.get("reason_codes") or [],
        price=price, defense_price=defense_price, tech_facts=tech_facts,
        entry_condition=primary.get("entry_condition"), is_core_holding=is_core,
        valuation=ctx.get("valuation"),
        tier_amount=(primary.get("position") or {}).get("tier_amount"),
        market_new_position=market_new_position)
    defense_explain = build_defense_explain(defense_price, dec.get("stop"))
    return advice, defense_explain


def build_stock_detail(stock_id: str, res: Dict, profile: Dict, meta: Dict,
                       market_new_position: Optional[str] = None) -> Dict:
    t_ev = (res.get("technical") or {}).get("ev") or {}
    dec = res.get("decision") or {}
    is_core = stock_id in profile.get("core_holdings", [])
    primary = _clean_primary(res["primary_decision"])
    advice, defense_explain = _build_advice_and_defense(res, is_core, market_new_position)
    primary["advice"] = advice
    primary["defense_explain"] = defense_explain
    # 角色觀點由權威 reason_codes＋facts 重新生成（升級版六角色人話文案），不用舊 narration。
    # generate_roles 的 lights_facts 形狀＝{key: [facts...]}；context.lights 是 {key: {color, facts}}，
    # 先攤平成前者（見 primary_decision._facts_of）。
    ctx = res.get("context") or {}
    ctx_lights = ctx.get("lights") or {}
    lights_facts = {k: (ctx_lights.get(k) or {}).get("facts") or []
                    for k in ("fundamental", "technical", "chips")}
    roles = generate_roles(res["primary_decision"].get("reason_codes") or [],
                           lights_facts, res["primary_decision"]["action"])
    evidence = build_evidence(res.get("evidence") or {})
    evidence["roles"] = roles
    return {
        "meta": meta,
        "profile": {"id": stock_id, "name": res.get("name", stock_id),
                    "market": "TWSE", "is_core_holding": is_core},
        "price": {
            "close": _num(dec.get("as_of_price")),
            "change_pct": None,  # 已知缺口：見模組尾端說明
            "ma20": _num(t_ev.get("MA20")),
            "ma60": _num(t_ev.get("MA60")),
        },
        "primary_decision": primary,
        "context": build_context(res["context"]),
        "evidence": evidence,
        "track": build_track(stock_id),
        "forecast": res.get("forecast"),  # v1.2：整組可為 null（樣本不足/引擎產物缺該欄位）
        # v1.4：短線劇本推演，整組由 warroom/short_scenarios.py 在 analyze 階段算好（含機率
        # 查表、大盤新倉閘門 proxy），這裡純透傳，不重算（見該檔與 analyze_tw.py 掛載點說明）。
        "short_scenarios": res.get("short_scenarios"),
    }


# ---------- v1.3 forecast_log 準確度管線 ----------
# 每次 build 對每檔有 forecast 的股票 append/覆蓋當日一筆預估紀錄（week/m1/m3 的
# prob_range_70），並檢查既有紀錄是否到期（date+5/21/63 交易日）可用實際收盤回填
# hit（true＝實際收盤落在 [p15,p85] 內）。抓不到收盤價（未到期或資料源失敗）就跳過該
# 欄位、留待下次 build 重試，不炸整批（契約 v1.3：forecast_log 段落）。
# entry 形狀：{date, stock_id, week/m1/m3:[p15,p85], week_hit/m1_hit/m3_hit: bool|null}
# （後三個 _hit 欄位是本管線的內部擴充，不在契約範例裡，因為 forecast_log.json 本來就
# 是「引擎內部檔，非前端契約」，可自由擴充只要不違反契約列出的必要欄位）。

def _load_forecast_log(path: str = FORECAST_LOG) -> List[Dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []


def update_forecast_log(log: List[Dict], stock_id: str, forecast: Optional[Dict],
                        date: str) -> List[Dict]:
    """append 一筆（同 (date, stock_id) 覆蓋）；forecast 缺 week/m1/m3 區間（None 或形狀不
    對）就跳過不記，不編數字。回新 list（不就地改傳入的 log，呼叫端自行接手）。"""
    if not forecast or not date or not stock_id:
        return log
    week = forecast.get("week_range_70")
    horizons = forecast.get("horizons") or {}
    m1 = (horizons.get("m1") or {}).get("prob_range_70")
    m3 = (horizons.get("m3") or {}).get("prob_range_70")

    def _valid_range(r):
        return isinstance(r, (list, tuple)) and len(r) == 2

    if not (_valid_range(week) and _valid_range(m1) and _valid_range(m3)):
        return log
    out = [e for e in log if not (e.get("date") == date and e.get("stock_id") == stock_id)]
    out.append({
        "date": date, "stock_id": stock_id,
        "week": [_num(week[0]), _num(week[1])],
        "m1": [_num(m1[0]), _num(m1[1])],
        "m3": [_num(m3[0]), _num(m3[1])],
        "week_hit": None, "m1_hit": None, "m3_hit": None,
    })
    return out


def _finmind_close_after(stock_id: str, entry_date: str, n_trading_days: int) -> Optional[float]:
    """entry_date 之後第 n_trading_days 個交易日的實際收盤價；抓不到／還沒到那天 → None
    （graceful：呼叫端把 None 當『暫時不能回填，下次再試』，不當錯誤處理）。"""
    try:
        d0 = datetime.strptime(entry_date[:10], "%Y-%m-%d")
        # 交易日→曆日的緩衝窗（含週末／國定假日空檔），寧可多抓不要抓不夠。
        end = (d0 + timedelta(days=int(n_trading_days * 1.6) + 14)).strftime("%Y-%m-%d")
        df = cached_fetch("taiwan_stock_daily", stock_id=stock_id, start_date=entry_date, end_date=end)
        df = df[df["date"].astype(str) > entry_date].sort_values("date")
        if len(df) < n_trading_days:
            return None
        return float(df.iloc[n_trading_days - 1]["close"])
    except Exception:
        return None


def backfill_forecast_log(log: List[Dict], price_lookup=_finmind_close_after,
                          today: Optional[str] = None) -> List[Dict]:
    """就地回填每筆 entry 的 week_hit/m1_hit/m3_hit（已回填過的欄位跳過不重算）。
    price_lookup(stock_id, entry_date, n_trading_days) -> 收盤價|None，預設走 FinMind；
    測試可注入假 lookup 離線跑（沿用 warroom.track_record.backfill_outcomes 的同款寫法）。"""
    for e in log:
        sid, date = e.get("stock_id"), e.get("date")
        if not sid or not date:
            continue
        for key, n_days in FORECAST_HORIZON_TRADING_DAYS.items():
            hit_key = f"{key}_hit"
            if e.get(hit_key) is not None:
                continue
            rng = e.get(key)
            if not (isinstance(rng, (list, tuple)) and len(rng) == 2
                    and rng[0] is not None and rng[1] is not None):
                continue
            try:
                close = price_lookup(sid, date, n_days)
            except Exception:
                close = None
            if close is None:
                continue
            lo, hi = rng
            e[hit_key] = bool(lo <= close <= hi)
    return log


def build_forecast_accuracy(stock_id: str, log: List[Dict],
                            min_samples: int = FORECAST_ACCURACY_MIN_SAMPLES) -> Dict:
    """該股所有已回填（非 None）hit 樣本的命中率；樣本 <10 給 rate=null＋note（契約
    v1.3：「樣本 <10 給 null」）。"""
    hits = []
    for e in log:
        if e.get("stock_id") != stock_id:
            continue
        for key in ("week_hit", "m1_hit", "m3_hit"):
            v = e.get(key)
            if v is not None:
                hits.append(bool(v))
    n = len(hits)
    if n < min_samples:
        return {"n_evaluated": n, "hit_rate_70": None, "note": FORECAST_ACCURACY_NOTE_INSUFFICIENT}
    rate = round(sum(1 for h in hits if h) / n, 3)
    return {"n_evaluated": n, "hit_rate_70": rate,
           "note": f"已回填 {n} 筆樣本，命中率＝實際收盤落在 70% 機率區間內的比例。"}


# ---------- 組裝入口 ----------
def build_all(data_dir: str = DATA_DIR,
             market_inputs: Optional[Dict] = None) -> Tuple[Dict, Dict[str, Dict], List[Tuple[str, str]]]:
    """回 (daily_dict, {stock_id: stock_detail_dict}, skipped)。
    market_inputs=None → 打網路抓；測試可傳固定 dict 全離線跑。"""
    profile = load_profile()
    stock_files = discover_stock_files(data_dir)
    results, skipped = load_stock_results(stock_files)
    if market_inputs is None:
        market_inputs = fetch_market_inputs()
    meta = build_meta(sources=["FinMind", "yfinance"],
                      data_date=market_inputs.get("trade_date"))
    market_block = build_market_block(market_inputs)
    daily = build_daily(profile, results, meta, market_block)
    # 個股 advice 要跟大盤 exposure_guidance 一致（見 _build_advice_and_defense docstring）：
    # 直接重用 daily 已算好的那份，不重算一次（同一份 risk_temp 只該有一個真結果）。
    market_new_position = daily["exposure_guidance"]["new_position"]
    stock_details = {sid: build_stock_detail(sid, res, profile, meta, market_new_position)
                     for sid, res in results.items()}
    return daily, stock_details, skipped


def main() -> None:
    daily, stock_details, skipped = build_all()
    today = daily["meta"]["data_date"]

    # v1.3 forecast_log 準確度管線：build_all() 保持純函式（不打網路、不寫檔，見模組頂
    # 端「設計原則」），實際的 log 落檔＋FinMind 回填只在 main()（真正跑批次）這裡做，
    # 才不會讓 tests/test_build_snapshots.py 的 build_all() 呼叫意外打網路。
    log = _load_forecast_log()
    for sid, detail in stock_details.items():
        log = update_forecast_log(log, sid, detail.get("forecast"), today)
    log = backfill_forecast_log(log, today=today)
    for sid, detail in stock_details.items():
        forecast = detail.get("forecast")
        if forecast:
            forecast["accuracy"] = build_forecast_accuracy(sid, log)
    write_json(FORECAST_LOG, log)

    write_json(os.path.join(OUT_DIR, "daily.json"), daily)
    for sid, detail in stock_details.items():
        write_json(os.path.join(OUT_DIR, "stocks", f"{sid}.json"), detail)
    for sid, reason in skipped:
        print(f"[build_snapshots] 跳過 {sid}：{reason}", file=sys.stderr)
    print(f"[build_snapshots] 完成：daily.json ＋ {len(stock_details)} 檔個股快照", file=sys.stderr)


if __name__ == "__main__":
    main()


# ---------- 已知缺口（契約 vs 引擎現況，非本模組能補；回報時一併說明）----------
# 1. price.change_pct / tracked[].change_pct：引擎（analyze_tw.technical()）目前只輸出
#    最新收盤，不含前一日收盤或日漲跌%，故本模組一律回 null（符合契約硬規則 3：缺資料
#    給 null、不編數字）。若要補齊，需在 analyze_tw.py 補算（不在本次授權可動檔案內）。
# 2. daily.watch：目前 repo 內無「有等待條件但無完整報告」的股票清單資料源，回空陣列。
# 3. context.lights.color / valuation.band 為 null（na／資料不足）時：app/src/types/
#    contract.ts 的 Zod LightSchema.color、ValuationSchema.band 目前宣告非 nullable
#    enum；若引擎真的輸出 null（na 燈或估值樣本不足），前端會判為 schema 不符、整頁
#    顯示「請更新 App」。本模組＋schema/stock.schema.json 都已允許 null（照契約硬規則
#    3：缺資料給 null），這裡只能照實傳，前端 Zod 需要另行同步（不在本次授權可動 app/）。
