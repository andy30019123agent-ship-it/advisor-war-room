"""POST /api/track — 一鍵加入監控（契約 v1.1「新 API：POST /api/track」節）。

流程：驗代號格式 → 驗 Origin/Referer（擋跨站濫用）→ 驗代號真的存在（複用
api/analyze.py 的 lite 環境呼叫 stock_exists()）→ 用 GitHub contents API（token 來自
env GH_PAT）讀 data/tracked_stocks.json（拿 sha）→ 已在清單內回 200 idempotent →
滿 20 檔回 409 → 每 instance 每小時最多 10 次寫入，超過回 429 → 否則 append 後 PUT
回寫（commit message 註明來源）→ 201。

GH_PAT 缺失或 GitHub API 任何一步失敗都回 503，不把 token 洩進回應或 log
（例外訊息一律用固定文案，不夾帶 urllib 例外物件裡可能帶到的 header/url）。
"""
import json
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_STOCK_ID_RE = re.compile(r"^\d{4,6}$")
_MAX_BODY_BYTES = 1024
_MAX_TRACKED = 20

_GH_REPO = "andy30019123agent-ship-it/advisor-war-room"
_GH_PATH = "data/tracked_stocks.json"
_GH_API_BASE = f"https://api.github.com/repos/{_GH_REPO}/contents/{_GH_PATH}"
_GH_TIMEOUT = 10

# 單人工具的基本防濫用：不擋 curl／伺服器對呼叫（無 Origin/Referer），只擋惡意網頁
# 從別的網域用使用者瀏覽器發跨站請求。
_ALLOWED_ORIGIN = "https://advisor-war-room.vercel.app"

# 每 instance（warm lambda 共用同一個 /tmp）簡單限流，不是全域限流——冷啟或換 instance
# 就歸零，只防單一 instance 被打爆，不是嚴謹的分散式 rate limit。
_RATE_LIMIT_PATH = "/tmp/track_rate_limit.json"
_RATE_LIMIT_MAX_PER_HOUR = 10


class _NotFound(Exception):
    pass


class _ListFull(Exception):
    pass


class _Unavailable(Exception):
    pass


class _RateLimited(Exception):
    pass


def _origin_allowed(headers) -> bool:
    """有 Origin 頭就必須是本站；沒有 Origin 才看 Referer 開頭；兩者都沒有＝非瀏覽器
    請求（curl/伺服器），放行。瀏覽器的跨站 fetch 一定會帶 Origin，擋不了的只有
    刻意偽造 header 的攻擊者——這不是本工具的威脅模型（單人使用），只防隨手跨站呼叫。"""
    origin = headers.get("Origin")
    if origin:
        return origin == _ALLOWED_ORIGIN
    referer = headers.get("Referer")
    if referer:
        return referer.startswith(_ALLOWED_ORIGIN)
    return True


def _check_stock_exists(stock_id: str):
    """代號是否真的存在：複用 api/analyze.py 的 lite 環境設定（_setup_lite_env，換掉
    warroom.finmind_cache／warroom.market 的重依賴），呼叫 warroom.analyze_tw.stock_exists()。
    回 True／False／None（查不了：額度用完或網路問題，見 stock_exists() docstring）。"""
    from api.analyze import _setup_lite_env
    _setup_lite_env()
    from warroom.analyze_tw import stock_exists
    return stock_exists(stock_id)


def _rate_limit_ok(path: str = _RATE_LIMIT_PATH) -> bool:
    """回 True 並把這次計入額度；額度用完回 False（呼叫方不得寫入）。以 UTC 小時分桶存
    在 /tmp，同一 instance warm 重用會累加，跨小時或冷啟自動歸零。寫檔失敗（/tmp 滿等）
    採寬鬆放行，不因限流機制本身壞掉擋住正常使用。"""
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


def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "advisor-war-room-track-api",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gh_get_file(token: str) -> tuple[dict, str]:
    """讀 tracked_stocks.json 內容與 sha。失敗一律拋 _Unavailable（不夾 token）。"""
    req = Request(_GH_API_BASE, headers=_gh_headers(token), method="GET")
    try:
        with urlopen(req, timeout=_GH_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError) as e:
        raise _Unavailable(f"讀取追蹤清單失敗：{type(e).__name__}") from None

    sha = payload.get("sha")
    content_b64 = payload.get("content", "")
    try:
        import base64
        raw = base64.b64decode(content_b64.encode("ascii")).decode("utf-8")
        data = json.loads(raw)
    except Exception as e:
        raise _Unavailable(f"解析追蹤清單失敗：{type(e).__name__}") from None

    if not sha or not isinstance(data, dict) or not isinstance(data.get("stocks"), list):
        raise _Unavailable("追蹤清單格式異常")
    return data, sha


def _gh_put_file(token: str, data: dict, sha: str, stock_id: str) -> None:
    body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    import base64
    payload = {
        "message": f"chore: 新增追蹤 {stock_id}（來源：/api/track 一鍵加入監控）",
        "content": base64.b64encode(body).decode("ascii"),
        "sha": sha,
    }
    req = Request(
        _GH_API_BASE,
        data=json.dumps(payload).encode("utf-8"),
        headers=_gh_headers(token),
        method="PUT",
    )
    try:
        with urlopen(req, timeout=_GH_TIMEOUT) as resp:
            resp.read()
    except (HTTPError, URLError, TimeoutError) as e:
        raise _Unavailable(f"寫入追蹤清單失敗：{type(e).__name__}") from None


def run_track(stock_id: str) -> dict:
    """回成功時的 body dict（200 idempotent 或 201 新增）。
    失敗拋 _NotFound（代號不存在）／_ListFull／_RateLimited／_Unavailable。"""
    exists = _check_stock_exists(stock_id)
    if exists is False:
        raise _NotFound(stock_id)
    if exists is None:
        # 查不了（額度用完／網路問題）跟「查得到但確定不存在」是兩件事，不誤判成 404，
        # 也不能沒驗證就寫入——回 503 讓使用者稍後再試（見 api/analyze.py 同語意用法）。
        raise _Unavailable("暫時無法確認股票代號，請稍後再試")

    token = os.environ.get("GH_PAT", "").strip()
    if not token:
        raise _Unavailable("缺少 GitHub token")

    data, sha = _gh_get_file(token)
    stocks = data["stocks"]

    if stock_id in stocks:
        return {"ok": True, "already": True}

    if len(stocks) >= _MAX_TRACKED:
        raise _ListFull()

    if not _rate_limit_ok():
        raise _RateLimited()

    stocks.append(stock_id)
    _gh_put_file(token, data, sha, stock_id)
    return {
        "ok": True,
        "pending": "次一交易日 14:30 起納入每日更新與防守價監控",
    }


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
        self._send_json(405, {"error": "method_not_allowed"})

    def do_POST(self):
        if not _origin_allowed(self.headers):
            self._send_json(403, {"error": "forbidden"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = 0

        if length <= 0 or length > _MAX_BODY_BYTES:
            self._send_json(404, {"error": "not_found"})
            return

        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._send_json(404, {"error": "not_found"})
            return

        stock_id = str((body or {}).get("stock", "")).strip()
        if not _STOCK_ID_RE.match(stock_id):
            self._send_json(404, {"error": "not_found"})
            return

        try:
            result = run_track(stock_id)
        except _NotFound:
            self._send_json(404, {"error": "not_found"})
        except _ListFull:
            self._send_json(409, {"error": "list_full"})
        except _RateLimited:
            self._send_json(429, {"error": "rate_limited"})
        except _Unavailable as e:
            print(f"[api/track] {stock_id} 失敗：{e}", file=sys.stderr)
            self._send_json(503, {"error": "暫時無法加入監控，請稍後再試"})
        except Exception as e:  # 任何未預期例外都不能讓前端拿到 500 白屏
            print(f"[api/track] {stock_id} 未預期失敗：{e}\n{traceback.format_exc()}", file=sys.stderr)
            self._send_json(503, {"error": "暫時無法加入監控，請稍後再試"})
        else:
            status = 200 if result.get("already") else 201
            self._send_json(status, result)
