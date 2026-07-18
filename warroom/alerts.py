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

_TWSE_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{id}.tw"
_FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
_TG_URL = "https://api.telegram.org/bot{token}/sendMessage"


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


def fetch_price_twse(stock_id, timeout=6):
    """TWSE 官方即時報價；z=成交價，若尚未開盤成交則退回 y=昨收。查無資料回 None。"""
    url = _TWSE_URL.format(id=stock_id)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    arr = payload.get("msgArray") or []
    if not arr:
        return None
    info = arr[0]
    for field in ("z", "y"):
        v = info.get(field)
        if v and v != "-":
            try:
                return float(v)
            except ValueError:
                continue
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


def get_price(stock_id):
    """優先 TWSE 即時，失敗 fallback FinMind 收盤；兩者皆失敗回 None（不炸主流程）。"""
    try:
        p = fetch_price_twse(stock_id)
        if p is not None:
            return p
    except Exception as e:
        print(f"  [warn] TWSE 即時價失敗 {stock_id}: {type(e).__name__} {str(e)[:60]}")
    try:
        p = fetch_price_finmind(stock_id)
        if p is not None:
            return p
    except Exception as e:
        print(f"  [warn] FinMind fallback 失敗 {stock_id}: {type(e).__name__} {str(e)[:60]}")
    return None


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

    alerts = load_snapshot(data_path)
    if not alerts:
        print(f"{data_path} 無 alerts_snapshot 資料，略過本輪。")
        return 0

    today = _today_str(now)
    state = load_state(state_path)
    sent = 0
    for alert in alerts:
        key = alert_key(alert)
        if already_sent(state, today, key):
            continue
        price = get_price(alert.get("id"))
        if price is None:
            print(f"  [warn] {alert.get('name')} {alert.get('id')} 抓不到即時價，跳過本輪。")
            continue
        if evaluate(alert, price):
            msg = build_message(alert, price)
            send_telegram(msg)
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
