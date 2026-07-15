"""事件日曆（規格 §3.3）＋除權息調整支援（規格 §3.2.1 終審移交第 2 項）。
未來 7/14 天：法說（鄰專案 tw-earnings-calendar/latest.json）／除息（FinMind，僅已公告）／
月營收公布（規則：次月 10 日前）／FOMC・CPI（2026H2 寫死日程）。
「事件前高估值＋籌碼弱」→ decision 降一級（event_risk_downgrade）。
純函式、缺源降級：法說檔缺→標 degraded 不編造；除息未來可靠性有限→只顯示已公告者。
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

# 2026 下半年 FOMC 利率決議（第二日公布）與美國 CPI 公布日（寫死）。
# 來源：Fed 2026 FOMC 會議日程、BLS 2026 CPI release schedule（執行前建議上官網複核；
# https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm、https://www.bls.gov/schedule/）。
MACRO_EVENTS_2026H2 = [
    {"date": "2026-07-29", "type": "FOMC", "name": "FOMC 利率決議", "detail": "2026-07 會議（第二日）"},
    {"date": "2026-09-16", "type": "FOMC", "name": "FOMC 利率決議", "detail": "2026-09 會議（第二日）"},
    {"date": "2026-10-28", "type": "FOMC", "name": "FOMC 利率決議", "detail": "2026-10 會議（第二日）"},
    {"date": "2026-12-09", "type": "FOMC", "name": "FOMC 利率決議", "detail": "2026-12 會議（第二日）"},
    {"date": "2026-07-14", "type": "CPI", "name": "美國 6 月 CPI", "detail": "BLS 公布"},
    {"date": "2026-08-12", "type": "CPI", "name": "美國 7 月 CPI", "detail": "BLS 公布"},
    {"date": "2026-09-11", "type": "CPI", "name": "美國 8 月 CPI", "detail": "BLS 公布"},
    {"date": "2026-10-14", "type": "CPI", "name": "美國 9 月 CPI", "detail": "BLS 公布"},
    {"date": "2026-11-10", "type": "CPI", "name": "美國 10 月 CPI", "detail": "BLS 公布"},
    {"date": "2026-12-10", "type": "CPI", "name": "美國 11 月 CPI", "detail": "BLS 公布"},
]

_DEGRADE_DIV = "除息僅顯示已公告者（未來除息可靠性 P0 未 100% 實測）"
# 五檔 rating 由強到弱（降一級用）
_RATING_ORDER = ["買進", "試單", "續抱", "觀望", "減碼"]


def _iso(d) -> Optional[str]:
    s = str(d).strip()
    return s[:10] if len(s) >= 10 and s[4] == "-" else None


def _in_window(date_iso: str, today: str, horizon_days: int) -> bool:
    if not date_iso:
        return False
    end = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=horizon_days)).strftime("%Y-%m-%d")
    return today <= date_iso <= end


def _days_ahead(date_iso: str, today: str) -> int:
    a = datetime.strptime(date_iso, "%Y-%m-%d")
    b = datetime.strptime(today, "%Y-%m-%d")
    return (a - b).days


def build_ex_div_map(div_df) -> Dict[str, float]:
    """{現金除息交易日: 每股現金股利}。缺欄或空表 → {}。
    P1 fix #5：除息日欄位若為 NaN（缺值）先以 pd.notna() 濾掉，
    再交給 _iso() 解析（解析失敗一樣不進 map），避免 NaN 被字串化後誤判。"""
    if div_df is None or len(div_df) == 0:
        return {}
    if "CashExDividendTradingDate" not in div_df.columns:
        return {}
    out = {}
    for _, r in div_df.iterrows():
        ex_raw = r.get("CashExDividendTradingDate")
        if pd.isna(ex_raw):
            continue
        ex = _iso(ex_raw)
        amt = pd.to_numeric(pd.Series([r.get("CashEarningsDistribution")]),
                            errors="coerce").iloc[0]
        if ex and pd.notna(amt) and amt > 0:
            out[ex] = float(amt)
    return out


def parse_earnings(latest_json: Optional[Dict], today: str, horizon_days: int) -> List[Dict]:
    """鄰專案 latest.json → 未來窗口內法說事件。"""
    if not latest_json or "events" not in latest_json:
        return []
    out, seen = [], set()
    for e in latest_json["events"]:
        if e.get("type") != "法說會":
            continue
        d = _iso(e.get("date"))
        if not (d and _in_window(d, today, horizon_days)):
            continue
        key = (e.get("id"), d)
        if key in seen:
            continue
        seen.add(key)
        out.append({"date": d, "days_ahead": _days_ahead(d, today), "type": "法說會",
                    "stock_id": e.get("id"), "name": e.get("name", ""), "detail": "法說會",
                    "source": "tw-earnings-calendar/latest.json", "confidence": "confirmed"})
    return out


def parse_dividends(div_df, name: str, today: str, horizon_days: int) -> List[Dict]:
    """僅『已公告（AnnouncementDate 非空）且除息日在未來窗口內』的除息事件。
    P1 fix #5：AnnouncementDate 為 NaN 時，舊寫法 `str(NaN or "")` 會變成非空字串 "nan"，
    被誤判為「已公告」。改用 pd.notna() 直接驗證，NaN 一律視為未公告不進事件；
    除息日一樣先過 pd.notna() 再交給 _iso()，解析失敗（含 NaN）不進事件。"""
    if div_df is None or len(div_df) == 0 or "CashExDividendTradingDate" not in div_df.columns:
        return []
    out = []
    for _, r in div_df.iterrows():
        ann_raw = r.get("AnnouncementDate")
        ex_raw = r.get("CashExDividendTradingDate")
        if pd.isna(ann_raw) or pd.isna(ex_raw):
            continue
        announced = str(ann_raw).strip()
        ex = _iso(ex_raw)
        amt = pd.to_numeric(pd.Series([r.get("CashEarningsDistribution")]),
                            errors="coerce").iloc[0]
        if not announced or not ex or not _in_window(ex, today, horizon_days):
            continue
        amt_str = f"{float(amt):.2f}" if pd.notna(amt) else "—"
        out.append({"date": ex, "days_ahead": _days_ahead(ex, today), "type": "除息",
                    "stock_id": str(r.get("stock_id", "")), "name": name,
                    "detail": f"現金股利 {amt_str} 元",
                    "source": "FinMind taiwan_stock_dividend（已公告）", "confidence": "scheduled"})
    return out


def revenue_publish_events(stock_map: Dict[str, str], today: str, horizon_days: int) -> List[Dict]:
    """月營收公布規則：每月 10 日前公布上月營收。取今日之後最近的 10 號，落在窗口內就列。"""
    t = datetime.strptime(today, "%Y-%m-%d")
    # 今日之後最近的「10 號」
    if t.day < 10:
        pub = t.replace(day=10)
    else:
        y, mth = (t.year + 1, 1) if t.month == 12 else (t.year, t.month + 1)
        pub = datetime(y, mth, 10)
    pub_iso = pub.strftime("%Y-%m-%d")
    if not _in_window(pub_iso, today, horizon_days):
        return []
    out = []
    prev_month = 12 if pub.month == 1 else pub.month - 1
    for sid, nm in stock_map.items():
        out.append({"date": pub_iso, "days_ahead": _days_ahead(pub_iso, today),
                    "type": "月營收公布", "stock_id": sid, "name": nm,
                    "detail": f"{prev_month} 月營收（次月 10 日前公布規則）",
                    "source": "台股公告時程規則", "confidence": "estimated"})
    return out


def macro_events(today: str, horizon_days: int) -> List[Dict]:
    out = []
    for e in MACRO_EVENTS_2026H2:
        if _in_window(e["date"], today, horizon_days):
            out.append({"date": e["date"], "days_ahead": _days_ahead(e["date"], today),
                        "type": e["type"], "stock_id": None, "name": e["name"],
                        "detail": e["detail"],
                        "source": "Fed/BLS 2026 官方日程（寫死，見程式註解）",
                        "confidence": "scheduled"})
    return out


def build_event_calendar(earnings_json, div_by_stock: Dict, stock_map: Dict,
                         today: str, horizon_days: int = 14) -> Dict:
    """彙整四類事件、依日期排序。div_by_stock: {stock_id: (name, div_df)}。"""
    events = []
    events += parse_earnings(earnings_json, today, horizon_days)
    for sid, (nm, df) in (div_by_stock or {}).items():
        events += parse_dividends(df, nm, today, horizon_days)
    events += revenue_publish_events(stock_map or {}, today, horizon_days)
    events += macro_events(today, horizon_days)
    events.sort(key=lambda e: (e["date"], e["type"]))
    return {"generated": today, "horizon_days": horizon_days,
            "events": events, "degraded": [_DEGRADE_DIV]}


def has_upcoming_event(stock_id: str, div_df, earnings_json, stock_map,
                       today: str, horizon_days: int = 14) -> bool:
    """該股未來窗口內是否有『確認』事件（法說／已公告除息），供 decision 事件降級判斷。
    P1 fix #6：月營收公布是「每月10日前」的估計性規則事件（confidence=estimated），
    不是確認事件，不該讓事件降級每逢月初對全市場觸發——故此處不看月營收（維持在
    build_event_calendar 顯示，但不進降級判斷）。stock_map 參數保留供呼叫端相容，
    此函式不再使用它。"""
    if parse_dividends(div_df, "", today, horizon_days):
        return True
    for e in parse_earnings(earnings_json, today, horizon_days):
        if e["stock_id"] == stock_id:
            return True
    return False


def event_risk_downgrade(rating: str, has_event: bool, per_percentile,
                         chip_light: str) -> Tuple[str, str]:
    """事件前 + 高估值（分位>0.85）+ 籌碼弱（red/na）→ rating 降一級。否則原樣。"""
    weak_chip = chip_light in ("red", "na")
    high_val = per_percentile is not None and per_percentile > 0.85
    if has_event and high_val and weak_chip and rating in _RATING_ORDER:
        idx = _RATING_ORDER.index(rating)
        if idx < len(_RATING_ORDER) - 1:
            new = _RATING_ORDER[idx + 1]
            return new, f"事件前高估值（分位 {per_percentile:.0%}）＋籌碼弱，自動由「{rating}」降為「{new}」"
    return rating, ""
