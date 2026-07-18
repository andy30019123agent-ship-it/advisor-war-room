"""到價提醒管線：讀 public/data/daily.json 的 alerts_snapshot，比對即時價，
觸發時發 Telegram。用法：
  python -m warroom.alerts            # 正常執行（非盤中直接略過）
  python -m warroom.alerts --force    # 略過盤中時段檢查（本機測試用）

即時價：優先 TWSE 官方即時報價 API，失敗 fallback FinMind 當日收盤（REST，純 stdlib）。
去重：data/alerts_state.json 記錄「哪個 alert 哪天已發過」，同一 alert 同一天只發一次。
無 TG_BOT_TOKEN/TG_CHAT_ID 環境變數時 dry-run 印 stdout，不報錯（本機測試用）。
"""
import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

_TPE = timezone(timedelta(hours=8))

DEFAULT_DATA_PATH = "public/data/daily.json"
DEFAULT_STATE_PATH = "data/alerts_state.json"

_TWSE_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={prefix}_{id}.tw"
_TAIEX_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw"
_FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
_TG_URL = "https://api.telegram.org/bot{token}/sendMessage"

MARKET_MOVE_THRESHOLD_PCT = 2.0


def _today_str(now=None):
    now = now or datetime.now(_TPE)
    return now.strftime("%Y-%m-%d")


def is_trading_window(now=None):
    """平日台北 09:00-13:30 內回 True（含首尾）。"""
    now = now or datetime.now(_TPE)
    if now.weekday() >= 5:  # 週六=5, 週日=6
        return False
    start = now.replace(hour=9, minute=0, second=0, microsecond=0)
    end = now.replace(hour=13, minute=30, second=0, microsecond=0)
    return start <= now <= end


def load_snapshot(path=DEFAULT_DATA_PATH):
    """讀 alerts_snapshot；檔案不存在或壞掉一律回空陣列（graceful degrade，不炸主流程）。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    return data.get("alerts_snapshot") or []


def load_state(path=DEFAULT_STATE_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_state(state, path=DEFAULT_STATE_PATH):
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    except OSError as e:
        print(f"  [warn] 寫入去重狀態檔失敗: {type(e).__name__} {str(e)[:60]}")


def alert_key(alert):
    return f"{alert.get('id')}:{alert.get('type')}:{alert.get('price')}"


def already_sent(state, date_str, key):
    return key in (state.get(date_str) or [])


def mark_sent(state, date_str, key):
    day = state.setdefault(date_str, [])
    if key not in day:
        day.append(key)
    # 衛生：只保留最近 3 天，避免檔案無限長大
    keep = sorted(state.keys())[-3:]
    for k in list(state.keys()):
        if k not in keep:
            del state[k]


def evaluate(alert, price):
    """type=defense 且現價 < price → 觸發；type=entry 且現價 > price → 觸發。"""
    if price is None:
        return False
    t = alert.get("type")
    p = alert.get("price")
    if p is None:
        return False
    if t == "defense":
        return price < p
    if t == "entry":
        return price > p
    return False


def fmt_price(v):
    if v is None:
        return "—"
    v = float(v)
    if v.is_integer():
        return f"{int(v):,}"
    return f"{v:,.2f}"


def build_message(alert, price):
    name = alert.get("name", "")
    sid = alert.get("id", "")
    target = fmt_price(alert.get("price"))
    cur = fmt_price(price)
    if alert.get("type") == "defense":
        return f"⚠️ {name} {sid} 跌破防守價 {target}（現價 {cur}）——照紀律先降波段部位，核心定期定額不動。"
    if alert.get("type") == "entry":
        return f"🎯 {name} {sid} 觸發進場條件 {target}（現價 {cur}）——可依計畫分批進場，記得同步設好防守價。"
    return f"ℹ️ {name} {sid} 到價提醒：{target}（現價 {cur}）。"


def _fetch_price_twse_exchange(stock_id, prefix, timeout=6):
    """打單一交易所前綴（tse=上市／otc=上櫃），只取 z=即時成交價。
    z 無效（尚未成交／假日休市：值為空或 "-"）一律回 None，**不得**退回 y=昨收（大檢查・
    邏輯組修復 12：假日用昨收會誤觸防守警報，用戶收到早已知道的「跌破」——寧可跳過該檔）。
    查無資料（該股不在這個交易所）也回 None，讓呼叫方接著試下一個交易所。"""
    url = _TWSE_URL.format(prefix=prefix, id=stock_id)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    arr = payload.get("msgArray") or []
    if not arr:
        return None
    v = arr[0].get("z")
    if v and v != "-":
        try:
            return float(v)
        except ValueError:
            return None
    return None


def fetch_price_twse(stock_id, timeout=6):
    """TWSE 官方即時報價：先試上市（tse_），查無（該股其實是上櫃）再試上櫃（otc_）。
    兩個交易所都查無資料回 None（2026-07-18 聯測 #5：舊版只打 tse_，上櫃股永遠抓不到價，
    到價提醒對上櫃持股形同虛設）。第一個交易所連線／逾時失敗也還是要試第二個，不能直接
    放棄——只有兩個都失敗才把最後一個例外往上丟，讓 get_price() 的既有 try/except
    接手 fallback FinMind。"""
    last_exc = None
    for prefix in ("tse", "otc"):
        try:
            price = _fetch_price_twse_exchange(stock_id, prefix, timeout=timeout)
        except Exception as e:
            last_exc = e
            continue
        if price is not None:
            return price
    if last_exc is not None:
        raise last_exc
    return None


def fetch_price_finmind(stock_id, timeout=8, token=None):
    """Fallback：FinMind 公開 REST API 抓當日（或最近一個交易日）收盤價。"""
    token = token if token is not None else os.environ.get("FINMIND_TOKEN", "")
    start = (datetime.now(_TPE) - timedelta(days=7)).strftime("%Y-%m-%d")
    params = {"dataset": "TaiwanStockPrice", "data_id": stock_id, "start_date": start}
    if token:
        params["token"] = token
    url = _FINMIND_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    rows = payload.get("data") or []
    if not rows:
        return None
    rows.sort(key=lambda r: r.get("date", ""))
    close = rows[-1].get("close")
    return float(close) if close is not None else None


def get_price(stock_id, allow_finmind=True):
    """優先 TWSE 即時成交價（z）；抓不到時，只有在 allow_finmind=True（確定是交易日時段，
    由 run() 依大盤即時值判定）才 fallback FinMind 收盤。allow_finmind=False（假日/非交易
    時段）時不用 FinMind 昨收，直接回 None（跳過該檔），避免用陳舊收盤誤觸警報（修復 12）。
    兩者皆失敗回 None（不炸主流程）。"""
    try:
        p = fetch_price_twse(stock_id)
        if p is not None:
            return p
    except Exception as e:
        print(f"  [warn] TWSE 即時價失敗 {stock_id}: {type(e).__name__} {str(e)[:60]}")
    if not allow_finmind:
        return None
    try:
        p = fetch_price_finmind(stock_id)
        if p is not None:
            return p
    except Exception as e:
        print(f"  [warn] FinMind fallback 失敗 {stock_id}: {type(e).__name__} {str(e)[:60]}")
    return None


def fetch_taiex(timeout=6):
    """加權指數即時值：TWSE MIS tse_t00.tw；z=現值，y=昨收。
    任何失敗（連線／格式）一律 graceful 回 (None, None)，不炸主流程——
    大盤警報是「順帶」功能，不該讓既有到價提醒因此掛掉。"""
    req = urllib.request.Request(_TAIEX_URL, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [warn] 大盤即時值抓取失敗: {type(e).__name__} {str(e)[:60]}")
        return None, None
    arr = payload.get("msgArray") or []
    if not arr:
        return None, None
    info = arr[0]

    def _num(field):
        v = info.get(field)
        if not v or v == "-":
            return None
        try:
            return float(v)
        except ValueError:
            return None

    return _num("z"), _num("y")


def compute_change_pct(current, prev_close):
    """回傳漲跌百分比；current／prev_close 任一缺失或昨收為 0 回 None。"""
    if current is None or prev_close is None or prev_close == 0:
        return None
    return (current - prev_close) / prev_close * 100


def evaluate_market_move(change_pct, threshold=MARKET_MOVE_THRESHOLD_PCT):
    """|change_pct| ≥ threshold 才算「劇烈波動」，回傳 'up'/'down'；否則回 None。"""
    if change_pct is None:
        return None
    if change_pct >= threshold:
        return "up"
    if change_pct <= -threshold:
        return "down"
    return None


def build_market_move_message(direction, price, change_pct):
    price_s = fmt_price(price)
    pct_s = f"{change_pct:+.1f}%"
    if direction == "up":
        return (
            f"📈 大盤劇烈波動：加權指數 {price_s}（{pct_s}）。"
            "留意追高風險，紀律優先，記得回 App 看持股計畫。"
        )
    return (
        f"📉 大盤劇烈波動：加權指數 {price_s}（{pct_s}）。"
        "盤中波動放大，記得回 App 看持股防守價。"
    )


def check_market_move(state, today_str, taiex=None):
    """抓 TAIEX（或用 run() 已抓好的 taiex=(current, prev_close)，避免一輪抓兩次）、判斷
    是否劇烈波動、依 state 去重後發送。回傳已發送則數（0 或 1）。
    send_telegram 失敗（回 False）不 mark_sent——留到下一輪再試，不能把「發送失敗」
    誤標成「已發過」，否則這則警報就永久消失，使用者永遠收不到。"""
    current, prev_close = taiex if taiex is not None else fetch_taiex()
    change_pct = compute_change_pct(current, prev_close)
    direction = evaluate_market_move(change_pct)
    if direction is None:
        return 0
    key = f"market_move_{direction}"
    if already_sent(state, today_str, key):
        return 0
    msg = build_market_move_message(direction, current, change_pct)
    if not send_telegram(msg):
        return 0
    mark_sent(state, today_str, key)
    return 1


def send_telegram(message, token=None, chat_id=None, timeout=8):
    """回 True 表示訊息已處理完畢（含 dry-run）；實際發送失敗回 False。"""
    token = token if token is not None else os.environ.get("TG_BOT_TOKEN")
    chat_id = chat_id if chat_id is not None else os.environ.get("TG_CHAT_ID")
    if not token or not chat_id:
        print(f"[dry-run] {message}")
        return True
    url = _TG_URL.format(token=token)
    body = json.dumps({"chat_id": chat_id, "text": message}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
        return True
    except (urllib.error.URLError, OSError) as e:
        print(f"  [warn] Telegram 發送失敗: {type(e).__name__} {str(e)[:80]}")
        return False


def run(data_path=DEFAULT_DATA_PATH, state_path=DEFAULT_STATE_PATH, force=False, now=None):
    now = now or datetime.now(_TPE)
    if not force and not is_trading_window(now):
        print("非盤中時段，略過本輪（用 --force 可強制執行）。")
        return 0

    today = _today_str(now)
    state = load_state(state_path)
    sent = 0

    # 大盤即時值抓一次，供「大盤劇烈波動警報」與「交易日時段確認」共用。TAIEX z 有效＝
    # 確實在交易時段（非假日休市），此時才允許個股用 FinMind 昨收 fallback（修復 12）。
    taiex_current, taiex_prev = fetch_taiex()
    market_live = taiex_current is not None
    sent += check_market_move(state, today, taiex=(taiex_current, taiex_prev))

    alerts = load_snapshot(data_path)
    if not alerts:
        print(f"{data_path} 無 alerts_snapshot 資料，略過個股到價提醒。")
    else:
        for alert in alerts:
            key = alert_key(alert)
            if already_sent(state, today, key):
                continue
            price = get_price(alert.get("id"), allow_finmind=market_live)
            if price is None:
                print(f"  [warn] {alert.get('name')} {alert.get('id')} 抓不到即時價，跳過本輪。")
                continue
            if evaluate(alert, price):
                msg = build_message(alert, price)
                # send_telegram 失敗（回 False）不 mark_sent：留到下一輪重試，不能把
                # 「發送失敗」誤標成「已發過」，否則這則到價提醒就永久消失（見 check_market_move 同語意）。
                if send_telegram(msg):
                    mark_sent(state, today, key)
                    sent += 1

    save_state(state, state_path)
    print(f"本輪觸發並發送 {sent} 則提醒。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="到價提醒管線")
    ap.add_argument("--force", action="store_true", help="跳過盤中時段檢查")
    ap.add_argument("--data", default=DEFAULT_DATA_PATH, help="daily.json 路徑")
    ap.add_argument("--state", default=DEFAULT_STATE_PATH, help="去重狀態檔路徑")
    a = ap.parse_args()
    return run(data_path=a.data, state_path=a.state, force=a.force)


if __name__ == "__main__":
    raise SystemExit(main())
