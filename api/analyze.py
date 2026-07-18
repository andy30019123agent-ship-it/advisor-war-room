"""GET /api/analyze?stock=<id> — 即時單股分析（契約 v1 stocks/<id>.json 同構）。

即時查詢路徑：追蹤清單以外的股票沒有預先算好的 public/data/stocks/<id>.json，
使用者查詢時才現算。直接複用 warroom/analyze_tw.py 的 analyze()（規則引擎本體：
primary_decision/context/evidence 六層優先序）與 warroom/build_snapshots.py 的
build_stock_detail()（legacy → 契約 JSON 的組裝邏輯），不重寫任何決策規則。

serverless 限制下的兩個妥協（都是為了不把 FinMind SDK／yfinance 那堆重依賴
——pyarrow 108MB／aiohttp／lxml／curl_cffi 等——塞進 250MB bundle，見
api/_lib/finmind_lite.py 檔頭說明）：
1. FinMind 改走 REST API 直連（見 finmind_lite.LiteLoader），不用官方 SDK。
2. 大盤燈號改讀已部署的 public/data/daily.json（每日排程算好的真結果），
   不現場打 yfinance；讀不到就降級 amber（跟原本 warroom/market.py 失敗時的
   行為一致，見 warroom/analyze_tw.py _decide() 的 try/except）。

限流（2026-07-18 大檢查 🔴1）：跟 api/track.py 同款 per-instance /tmp 計數，每
instance 每小時最多 30 次「冷查」（快取命中不計）；超限回 429。侷限跟 track.py
一樣——不是全域限流，Vercel 流量大時開多個 instance 各自獨立的 /tmp，額度會隨
instance 數放大，冷啟或換 instance 就歸零。這對單人使用的戰情室工具可接受（治本
需要 Vercel Edge Config/KV 等跨 instance 共享狀態），先擋掉最省事的「換代號連續
打」cost-DoS 攻擊面（見 _reports/大檢查_安全_2026-07-18.md 第 2 節）。
"""
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_TPE = timezone(timedelta(hours=8))
_STOCK_ID_RE = re.compile(r"^\d{4,6}$")
_TMP_CACHE_DIR = "/tmp/analyze_cache"

# 每 instance（warm lambda 共用同一個 /tmp）簡單限流，只擋「冷查」（快取沒命中，真的
# 要打 FinMind 的請求）——快取命中不消耗額度，不然常查的熱門股會不必要地把額度用光。
# 跟 api/track.py 的 _RATE_LIMIT_PATH 同款設計，見檔頭說明的侷限。
_RATE_LIMIT_PATH = "/tmp/analyze_rate_limit.json"
_RATE_LIMIT_MAX_PER_HOUR = 30

# 整體查詢時間預算：Vercel serverless 硬限 30s，冷查最壞序列要打 8 個 FinMind dataset
# （每個最久 6s，見 finmind_lite._TIMEOUT），22s 留 8s buffer 給 build_stock_detail 組裝、
# 寫快取等其餘開銷（2026-07-18 聯測 #1：8×8s 舊序列會直接 FUNCTION_INVOCATION_TIMEOUT）。
_ANALYZE_DEADLINE_SECONDS = 22

_ready = False  # 冷啟只需設一次的 lite 環境（見 _setup_lite_env）


def _today() -> str:
    return datetime.now(_TPE).strftime("%Y-%m-%d")


def _lite_market_light() -> str:
    """讀已部署的 public/data/daily.json（每日排程真算出來的大盤燈），
    讀不到／格式不對一律降級 amber（不現場打 yfinance）。"""
    try:
        path = os.path.join(_ROOT, "public", "data", "daily.json")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        status = (d.get("market") or {}).get("status")
        return {"偏多進攻": "green", "中性": "amber", "偏空防禦": "red"}.get(status, "amber")
    except Exception:
        return "amber"


def _lite_exposure_new_position():
    """讀已部署 daily.json 的 exposure_guidance.new_position，讓即時查詢（非追蹤清單股票）
    的 advice 也跟大盤當下的曝險規則一致，不會出現「大盤禁新倉，即時查某股卻叫空手試單」
    的矛盾（見 warroom.build_snapshots._build_advice_and_defense 同語意用法）。
    讀不到／格式不對回 None＝不受限（build_advice 的 market_new_position=None 就是原行為），
    寧可不限制也不要資料源掛掉時錯誤鎖死所有查詢。"""
    try:
        path = os.path.join(_ROOT, "public", "data", "daily.json")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return (d.get("exposure_guidance") or {}).get("new_position")
    except Exception:
        return None


def _setup_lite_env() -> None:
    """把 warroom.finmind_cache 的單例換成 REST 直連 loader、把 warroom.market
    換成讀靜態快照的假模組，避免 import 到真 FinMind SDK／yfinance。
    只需做一次；同一個 warm lambda 實例重複呼叫時直接略過。"""
    global _ready
    if _ready:
        return
    import types

    from api._lib.finmind_lite import LiteLoader
    import warroom.finmind_cache as fc
    if fc._LOADER is None:
        fc._LOADER = LiteLoader()

    fake_market = types.ModuleType("warroom.market")
    fake_market.fetch_market = lambda: {"light": _lite_market_light()}
    sys.modules["warroom.market"] = fake_market

    _ready = True


def _cache_path(stock_id: str) -> str:
    return os.path.join(_TMP_CACHE_DIR, _today(), f"{stock_id}.json")


def _read_cache(stock_id: str):
    path = _cache_path(stock_id)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _write_cache(stock_id: str, payload) -> None:
    path = _cache_path(stock_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception:
        pass  # /tmp 快取只是防連點，寫失敗不影響本次回應


def _rate_limit_ok(path: str = _RATE_LIMIT_PATH) -> bool:
    """回 True 並把這次冷查計入額度；額度用完回 False（呼叫方不得往下打 FinMind）。
    以 UTC 小時分桶存在 /tmp，同一 instance warm 重用會累加，跨小時或冷啟自動歸零。
    寫檔失敗（/tmp 滿等）採寬鬆放行，不因限流機制本身壞掉擋住正常使用。"""
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


def run_analyze(stock_id: str) -> dict:
    """回 (status_code, body_dict)。同一代號同一天命中 /tmp 快取直接回，
    防連點轟炸 FinMind 免費額度。快取沒命中（冷查）才過限流閘門——超限拋
    _RateLimited，403 前不會碰到 FinMind。"""
    cached = _read_cache(stock_id)
    if cached is not None:
        return cached

    if not _rate_limit_ok():
        raise _RateLimited()

    _setup_lite_env()
    from warroom.analyze_tw import analyze, stock_exists, FinMindUnavailable
    from warroom.build_snapshots import build_meta, build_stock_detail
    from warroom.profile import load_profile
    import warroom.finmind_cache as fc

    # 每次請求重設整體查詢時間預算（不能塞進 _setup_lite_env：那支只在冷啟跑一次，
    # warm lambda 會重用同一個 LiteLoader 實例）。LiteLoader._fetch 靠這個時間戳
    # 判斷「非必要」dataset（財報/月營收/法人/股利）該不該跳過（見 finmind_lite.py）。
    fc._LOADER.deadline = time.time() + _ANALYZE_DEADLINE_SECONDS

    # 先確認代號存在，區分「查無此股票」(404) 和「查得到但這次抓資料失敗」(503)。
    # stock_exists() 查不了（額度/網路問題）時回 None，此時不誤判成不存在，照舊往下試抓資料。
    if stock_exists(stock_id) is False:
        raise _NotFound(stock_id)

    try:
        # with_news=False：news.py 打 GDELT/Google 序列重試最壞近 1 分鐘，不符合即時查詢的延遲預算
        res = analyze(stock_id, with_news=False)
    except FinMindUnavailable:
        # fetch() 辨識出額度用完/429/402 等「全域不可用」訊號才會冒泡到這裡（見
        # warroom/analyze_tw.py），跟一般缺資料降級分開處理，給使用者明確訊息而非猜測。
        raise _UpstreamUnavailable("FinMind 額度用完，請稍後再試")

    if not res.get("data_flags", {}).get("technical"):
        # 日線資料抓不到：代號存在但這次抓不到股價（deadline 到了或其他非額度性失敗），
        # 引擎雖然會降級成一筆「觀望」，但對即時查詢來說這不是可用結果。
        raise _UpstreamUnavailable(f"抓不到 {stock_id} 的股價資料，可能是 FinMind 額度用完，請稍後再試")

    profile = load_profile(os.path.join(_ROOT, "data", "investor_profile.json"))
    meta = build_meta(sources=["FinMind REST (lite)"], data_date=res.get("as_of_date"))
    detail = build_stock_detail(stock_id, res, profile, meta, _lite_exposure_new_position())
    _write_cache(stock_id, detail)
    return detail


class _UpstreamUnavailable(Exception):
    pass


class _NotFound(Exception):
    pass


class _RateLimited(Exception):
    pass


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
        stock_id = (qs.get("stock") or [""])[0].strip()

        if not _STOCK_ID_RE.match(stock_id):
            # 格式不對＝不可能是台股代號，跟「查得到清單但代號不存在」同一類前端呈現。
            self._send_json(404, {"error": "not_found"})
            return

        try:
            detail = run_analyze(stock_id)
            self._send_json(200, detail)
        except _NotFound:
            self._send_json(404, {"error": "not_found"})
        except _RateLimited:
            self._send_json(429, {"error": "查詢太頻繁，請稍後再試"})
        except _UpstreamUnavailable as e:
            self._send_json(503, {"error": str(e)})
        except Exception as e:  # 任何未預期例外都不能讓前端拿到 500 白屏
            print(f"[api/analyze] {stock_id} 失敗：{e}\n{traceback.format_exc()}", file=sys.stderr)
            self._send_json(503, {"error": "查詢時發生問題，請稍後再試"})
