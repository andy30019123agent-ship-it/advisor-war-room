"""GET /api/quote?ids=2330,2454 — serverless 代理 TWSE MIS 即時報價（契約 v1.7「新
API：GET /api/quote」節）。

瀏覽器直打 mis.twse.com.tw 有 CORS 擋，所以走這支純 stdlib 代理。ids 逗號分隔、每個
過 ^\\d{4,6}$、上限 12 檔（超過回 400，格式不對也回 400）。

非交易時段（沿用 warroom/alerts.py 的 is_trading_window 邏輯，import 它不重寫）整批
回 stale=true, price=null，**不現場打 MIS**——收盤後價格不會變，沒必要每次都打上游，
也能避免使用者把盤後撈到的「昨收/上個交易日收盤」誤看成盤中價（跟 warroom/alerts.py
的 z 值 fallback 顧慮同語意，見該檔 _fetch_price_twse_exchange docstring）。實測發現
MIS 在非交易時段仍會回傳上個交易日的收盤資料（z 是有效數字，不是 "-"），如果只靠
z 是否有效判斷 stale 會誤判成「盤中有效價」，所以 staleness 判斷交給呼叫方（本檔）
用 is_trading_window() 整批決定，不依賴 MIS 回應內容。

TWSE MIS 只能用 tse_/otc_ 前綴分市場查，不知道某代號是上市還上櫃時，先把全部代號當
tse_ 一次查完（一個 query 可混列多檔，ex_ch 用 `|` 分隔），查無資料的代號（不在回傳
msgArray 裡、或 MIS 回傳 c 為空字串的 placeholder 項——實測對不存在/查無的代號行為）
再補一次 otc_ 查詢。兩邊都查無資料的代號回 {price:null, stale:true}。z（成交價）欄位
本身無效（"-" 或缺）時該檔也回 {price:null, stale:true}。

限流／快取仿 api/analyze.py 同款 per-instance /tmp 設計（見該檔檔頭說明的侷限：不是
全域限流，冷啟或換 instance 會歸零）：per-instance 60 秒快取（key=排序後 ids 字串），
60 秒內同一組 ids 重複查詢直接回快取，不重打 MIS，也不消耗限流額度（跟 analyze 的
快取命中不計數同語意）。限流每 instance 每小時 120 次——比 analyze 寬鬆，因為這支
只代理即時報價、沒有 FinMind 額度顧慮，只防單一 instance 被打爆。非交易時段的整批
stale 回應同樣視為快取命中的資格（會寫入快取），因為沒打上游，不必消耗限流額度。
"""
import hashlib
import json
import os
import re
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_STOCK_ID_RE = re.compile(r"^\d{4,6}$")
_MAX_IDS = 12

_MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={pairs}"
_MIS_TIMEOUT = 6

# per-instance（warm lambda 共用同一個 /tmp）60 秒快取，key=排序後 ids 字串（見檔頭
# 說明）。用 sha1 當檔名，避免 ids 字串本身含特殊字元造成路徑問題。
_CACHE_DIR = "/tmp/quote_cache"
_CACHE_TTL_SECONDS = 60

# 跟 api/analyze.py／api/track.py 同款 per-instance /tmp 限流設計（見該二檔檔頭說明的
# 侷限），這裡放寬到每小時 120 次——沒有 FinMind 額度顧慮，只防單一 instance 被打爆。
_RATE_LIMIT_PATH = "/tmp/quote_rate_limit.json"
_RATE_LIMIT_MAX_PER_HOUR = 120


class _TooManyIds(Exception):
    pass


class _RateLimited(Exception):
    pass


def _empty_quote() -> dict:
    return {"price": None, "change_pct": None, "at": None, "stale": True}


def _cache_key(ids) -> str:
    return ",".join(sorted(ids))


def _cache_path(key: str) -> str:
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return os.path.join(_CACHE_DIR, f"{h}.json")


def _read_cache(key: str):
    path = _cache_path(key)
    try:
        with open(path, encoding="utf-8") as f:
            entry = json.load(f)
    except Exception:
        return None
    if time.time() - entry.get("ts", 0) > _CACHE_TTL_SECONDS:
        return None
    return entry.get("data")


def _write_cache(key: str, data: dict) -> None:
    path = _cache_path(key)
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "data": data}, f, ensure_ascii=False)
    except Exception:
        pass  # /tmp 快取只是省重複打 MIS，寫失敗不影響本次回應


def _rate_limit_ok(path: str = _RATE_LIMIT_PATH) -> bool:
    """回 True 並把這次計入額度；額度用完回 False。以 UTC 小時分桶存在 /tmp，同一
    instance warm 重用會累加，跨小時或冷啟自動歸零。寫檔失敗（/tmp 滿等）採寬鬆放行，
    不因限流機制本身壞掉擋住正常使用（跟 api/analyze.py 同款設計）。"""
    from datetime import datetime, timezone

    bucket = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {}
    if state.get("bucket") != bucket:
        state = {"bucket": bucket, "count": 0}
    if state.get("count", 0) >= _RATE_LIMIT_MAX_PER_HOUR:
        return False
    state["count"] = state.get("count", 0) + 1
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass
    return True


def _fetch_mis(stock_ids, prefix: str, timeout: int = _MIS_TIMEOUT) -> dict:
    """打單一交易所前綴（tse=上市／otc=上櫃），一次查多檔（ex_ch 用 `|` 分隔多組
    <prefix>_<id>.tw）。回 {stock_id: msgArray 項目}；查無資料的代號（該股不在這個
    交易所——MIS 回傳的 placeholder 項 c 為空字串，或該代號整個沒出現在 msgArray）
    不會出現在回傳 dict 裡，讓呼叫方接著試下一個交易所。"""
    pairs = "|".join(f"{prefix}_{sid}.tw" for sid in stock_ids)
    url = _MIS_URL.format(pairs=pairs)
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    result = {}
    for item in payload.get("msgArray") or []:
        sid = item.get("c")
        if sid:
            result[sid] = item
    return result


def _parse_quote(item: dict) -> dict:
    """z=成交價（可能 "-" 或缺）、y=昨收、t=時間（"HH:MM:SS"，裁成 "HH:MM"）。
    z 無效 → {price:null, stale:true}；z 有效但 y 無效/為 0 → change_pct 為 null。"""
    z = item.get("z")
    y = item.get("y")
    t = item.get("t")

    price = None
    if z and z != "-":
        try:
            price = float(z)
        except (TypeError, ValueError):
            price = None

    if price is None:
        return _empty_quote()

    change_pct = None
    if y and y != "-":
        try:
            prev = float(y)
            if prev:
                change_pct = round((price / prev - 1) * 100, 2)
        except (TypeError, ValueError):
            change_pct = None

    at = t[:5] if isinstance(t, str) and t else None
    return {"price": price, "change_pct": change_pct, "at": at, "stale": False}


def run_quote(ids) -> dict:
    """回 {stock_id: {price, change_pct, at, stale}}。快取命中直接回，不消耗限流額度。
    非交易時段整批回 stale（見檔頭說明），一樣不打 MIS、不消耗限流額度。"""
    key = _cache_key(ids)
    cached = _read_cache(key)
    if cached is not None:
        return cached

    from warroom.alerts import is_trading_window
    if not is_trading_window():
        result = {sid: _empty_quote() for sid in ids}
        _write_cache(key, result)
        return result

    if not _rate_limit_ok():
        raise _RateLimited()

    try:
        tse_items = _fetch_mis(ids, "tse")
    except Exception as e:
        print(f"[api/quote] tse 查詢失敗：{type(e).__name__} {str(e)[:80]}", file=sys.stderr)
        tse_items = {}

    missing = [sid for sid in ids if sid not in tse_items]
    otc_items = {}
    if missing:
        try:
            otc_items = _fetch_mis(missing, "otc")
        except Exception as e:
            print(f"[api/quote] otc 查詢失敗：{type(e).__name__} {str(e)[:80]}", file=sys.stderr)
            otc_items = {}

    result = {}
    for sid in ids:
        item = tse_items.get(sid) or otc_items.get(sid)
        result[sid] = _parse_quote(item) if item is not None else _empty_quote()

    _write_cache(key, result)
    return result


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        raw_ids = (qs.get("ids") or [""])[0]
        ids = [s.strip() for s in raw_ids.split(",") if s.strip()]

        if not ids or any(not _STOCK_ID_RE.match(sid) for sid in ids):
            self._send_json(400, {"error": "invalid_ids"})
            return
        if len(ids) > _MAX_IDS:
            self._send_json(400, {"error": "too_many_ids"})
            return

        try:
            result = run_quote(ids)
            self._send_json(200, result)
        except _RateLimited:
            self._send_json(429, {"error": "查詢太頻繁，請稍後再試"})
        except Exception as e:  # 任何未預期例外都不能讓前端拿到 500 白屏
            print(f"[api/quote] 失敗：{e}\n{traceback.format_exc()}", file=sys.stderr)
            self._send_json(503, {"error": "查詢時發生問題，請稍後再試"})
