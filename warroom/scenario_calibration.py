"""劇本機率自我校正管線（規格：Andy 拍板，v1.4 short_scenarios 的姊妹管線）。

流程（比照 warroom/build_snapshots.py 既有 forecast_log／warroom/track_record.py
recommendation_log 兩支既有準確度管線的既定模式，三選其優，不重造輪子）：

1. 每次 build_snapshots.main() 對每檔有 short_scenarios（status=ok）的股票，把當天
   的劇本機率＋關鍵位 append 進 data/scenario_log.json（同 (date, stock_id) 覆蓋，
   比照 forecast_log 模式）。
2. 每筆 entry 滿 20 個交易日（用 28 曆日粗略估）後，抓該股 entry 日以來的日線，
   依「時間序第一觸發」判定 realized ∈ {base, risk, bull}（見 determine_realized；
   跟『任一觸發就算』不同——先跌破防守 realized=risk，即使之後又站上 R1，因為先觸發
   者已經決定當時的紀律動作對不對）。抓不到資料（還沒到期／FinMind 失敗）留待下次
   build 重試，不當錯誤處理。
3. 對每個 bucket（技術燈×籌碼燈，如 "yellow_x_red"）統計已回填樣本的 realized 頻率，
   n≥20 才產生校正條目：校正值＝規則表值（short_scenarios._PROB_TABLE）與觀察頻率的
   收縮混合（λ=n/(n+20)），且偏離規則表值不得超過 ±15 個百分點，最後仍套 short_
   scenarios._finalize_probs 的 10-65% clamp＋normalize（跟引擎機率算法同一套收斂
   邏輯，不另造一套）。結果落 data/prob_calibration.json，每個 bucket 記
   {adjusted, n, observed, updated_at}，可回溯。
4. warroom/short_scenarios.py 查表時若有該 bucket 的 adjusted 就用它取代規則表值
   （見該檔 _resolve_probs），後續大盤/防守/突破/籌碼修正項照舊疊加在 adjusted 值上。

log 檔壞掉時 fail-closed：跳過本次寫入並警告，不覆寫既有毀損檔（比照
warroom.track_record 的 recommendation_log 模式——注意 forecast_log 那支管線是
「壞檔當空清單」，不是本管線要仿的對象，兩者刻意不同，見各自檔案的說明）。
"""
import json
import os
import warnings
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

_TPE = timezone(timedelta(hours=8))

SCENARIO_LOG = "data/scenario_log.json"
CALIBRATION_PATH = "data/prob_calibration.json"

REALIZE_MIN_CALENDAR_DAYS = 28   # 20 交易日粗算（含週末/假日緩衝）
REALIZE_WINDOW_TRADING_DAYS = 20
CALIBRATION_MIN_SAMPLES = 20
CALIBRATION_MAX_DEVIATION_PCT = 15.0
SHRINKAGE_K = 20  # λ = n/(n+K)；n=20 時 λ=0.5


def _now_iso() -> str:
    return datetime.now(_TPE).isoformat(timespec="seconds")


def format_bucket(technical_color: Optional[str], chips_color: Optional[str]) -> str:
    """技術燈×籌碼燈 → bucket key（如 "yellow_x_red"）。未知/na 一律退回 yellow
    （跟 warroom.short_scenarios._prob_lookup 對未知色的 fallback 語意一致）。"""
    t = technical_color if technical_color in ("green", "yellow", "red") else "yellow"
    c = chips_color if chips_color in ("green", "yellow", "red") else "yellow"
    return f"{t}_x_{c}"


# ---------- 每日記錄 ----------
def append_scenario_log(log: List[Dict], stock_id: str, date: str, bucket: str,
                        scenarios: List[Dict], levels: Dict) -> List[Dict]:
    """append 一筆（同 (date, stock_id) 覆蓋，比照 forecast_log／recommendation_log
    模式）；新 entry 的 realized 一律 None（回填由 backfill_scenario_log 另外做，
    重跑同一天的 build 不該動到過去已回填的舊 entry，那些是不同的 date key，本函式
    只碰今天這一筆，天然不會誤觸）。回新 list，不就地改傳入的 log。"""
    if not date or not stock_id:
        return log
    out = [e for e in log if not (e.get("date") == date and e.get("stock_id") == stock_id)]
    out.append({
        "date": date, "stock_id": stock_id, "bucket": bucket,
        "scenarios": scenarios, "levels": levels, "realized": None,
    })
    return out


# ---------- 回填 realized ----------
def determine_realized(closes: List[Optional[float]], defense: float, r1: float) -> str:
    """時間序第一觸發定生死：依序看每個交易日收盤，第一個 close < defense → risk；
    第一個 close > r1 → bull；先到者定生死，不是「任一天滿足就算」（例：先跌破防守，
    後面又站回 R1 之上，realized 仍是 risk——先觸發的當下紀律動作已經對/錯，後面的
    反彈不能倒果為因洗白）。整段都沒觸發（在 defense~r1 區間內盤整）→ base。
    缺值（None，資料源缺這天）的交易日跳過不判定，看下一天。"""
    for c in closes:
        if c is None:
            continue
        if c < defense:
            return "risk"
        if c > r1:
            return "bull"
    return "base"


def _eligible_for_backfill(entry_date: str, today: str,
                           min_calendar_days: int = REALIZE_MIN_CALENDAR_DAYS) -> bool:
    try:
        d0 = datetime.strptime(entry_date[:10], "%Y-%m-%d").date()
        t = datetime.strptime(today[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False
    return (t - d0).days >= min_calendar_days


def _finmind_closes_after(stock_id: str, entry_date: str,
                          n_trading_days: int = REALIZE_WINDOW_TRADING_DAYS
                          ) -> Optional[List[float]]:
    """entry_date 之後前 n_trading_days 個交易日的收盤價 list（依日期排序）；資料還沒
    到齊或抓取失敗 → None（graceful：呼叫端當『這次先跳過，下次再試』，不當錯誤處理，
    寫法比照 warroom.build_snapshots._finmind_close_after）。"""
    try:
        from warroom.finmind_cache import cached_fetch
        d0 = datetime.strptime(entry_date[:10], "%Y-%m-%d")
        end = (d0 + timedelta(days=int(n_trading_days * 1.6) + 14)).strftime("%Y-%m-%d")
        df = cached_fetch("taiwan_stock_daily", stock_id=stock_id,
                          start_date=entry_date, end_date=end)
        df = df[df["date"].astype(str) > entry_date].sort_values("date")
        if len(df) < n_trading_days:
            return None
        return [float(c) for c in df["close"].iloc[:n_trading_days]]
    except Exception:
        return None


def backfill_scenario_log(log: List[Dict], price_lookup=_finmind_closes_after,
                          today: Optional[str] = None) -> List[Dict]:
    """就地回填每筆 entry 的 realized（已回填過的跳過不重算）。price_lookup(stock_id,
    entry_date) -> [close, ...] | None，預設走 FinMind；測試可注入假 lookup 離線跑
    （沿用 warroom.track_record.backfill_outcomes 的同款寫法）。"""
    today = today or datetime.now(_TPE).strftime("%Y-%m-%d")
    for e in log:
        if e.get("realized") is not None:
            continue
        sid, date = e.get("stock_id"), e.get("date")
        levels = e.get("levels") or {}
        defense, r1 = levels.get("defense"), levels.get("r1")
        if not sid or not date or defense is None or r1 is None:
            continue
        if not _eligible_for_backfill(date, today):
            continue
        try:
            closes = price_lookup(sid, date)
        except Exception:
            closes = None
        if closes is None:
            continue
        e["realized"] = determine_realized(closes, defense, r1)
    return log


# ---------- log I/O（fail-closed，比照 recommendation_log 模式） ----------
def _load_scenario_log(path: str = SCENARIO_LOG) -> List[Dict]:
    """讀既有 log。檔案不存在 → []（正常初始狀態）。JSON 壞掉 → 往上拋例外，讓呼叫端
    fail-closed（不得吞掉後當空清單——那樣後續寫入會把壞檔覆寫成只剩本次新資料，
    等於毀損既有歷史樣本；比照 warroom.track_record._load，刻意不學 forecast_log 那支
    「壞檔當空清單」的寫法）。"""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json_atomic(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def sync_scenario_log(stock_details: Dict[str, Dict], today: str,
                      log_path: str = SCENARIO_LOG, price_lookup=None
                      ) -> Optional[List[Dict]]:
    """每日記錄＋回填的整合入口，供 warroom/build_snapshots.py main() 掛鉤呼叫（比照
    forecast_log 掛鉤模式）。log 檔壞掉時 fail-closed：跳過本次寫入、警告，回 None
    （不覆寫既有毀損檔）；正常情況回寫入後的完整 log（供呼叫端接著算 calibration）。
    price_lookup=None → 走 FinMind 正式抓；測試可傳假 lookup 離線跑。"""
    try:
        log = _load_scenario_log(log_path)
    except Exception as ex:
        warnings.warn(
            f"scenario_log 讀取失敗（{log_path}）：{type(ex).__name__} {ex}；"
            "本次跳過寫入，避免覆寫毀損既有紀錄（fail-closed）")
        return None

    for sid, detail in stock_details.items():
        ss = detail.get("short_scenarios")
        if not ss or ss.get("status") != "ok":
            continue
        ctx_lights = (detail.get("context") or {}).get("lights") or {}
        tech_color = (ctx_lights.get("technical") or {}).get("color")
        chips_color = (ctx_lights.get("chips") or {}).get("color")
        bucket = format_bucket(tech_color, chips_color)
        scenarios = [{"id": sc.get("id"), "prob_pct": sc.get("probability_pct")}
                    for sc in ss.get("scenarios") or []]
        primary = detail.get("primary_decision") or {}
        price = detail.get("price") or {}
        resistances = (ss.get("key_levels") or {}).get("resistances") or []
        defense = primary.get("defense_price")
        r1 = resistances[0] if resistances else None
        close = price.get("close")
        if defense is None or r1 is None or close is None:
            continue  # 缺關鍵位無法做未來回填判定，不記半套資料（不編數字）
        levels = {"defense": defense, "r1": r1, "close": close}
        log = append_scenario_log(log, sid, today, bucket, scenarios, levels)

    log = backfill_scenario_log(log, price_lookup=price_lookup or _finmind_closes_after,
                                today=today)
    try:
        _write_json_atomic(log_path, log)
    except Exception:
        pass  # 寫檔失敗不讓整批 build 中斷（契約硬規則 3 精神：graceful degrade）
    return log


# ---------- 校正表 ----------
def _shrinkage_lambda(n: int, k: int = SHRINKAGE_K) -> float:
    return n / (n + k)


def compute_calibration(log: List[Dict], min_samples: int = CALIBRATION_MIN_SAMPLES,
                        max_deviation_pct: float = CALIBRATION_MAX_DEVIATION_PCT,
                        now_iso: Optional[str] = None) -> Dict[str, Dict]:
    """對每個 bucket 統計已回填（realized 非 None）樣本，n>=min_samples 才產生校正
    條目（見模組頂端說明 3）。校正值＝規則表值（short_scenarios._PROB_TABLE）與觀察
    頻率的收縮混合（λ=n/(n+20)），偏離規則表值不得超過 ±max_deviation_pct 個百分點，
    最後套 short_scenarios._finalize_probs 的 10-65% clamp＋normalize（重用引擎既有
    收斂邏輯，不另造一套）。回 {bucket: {adjusted, n, observed, updated_at}}，
    n<min_samples 的 bucket 不出現在回傳裡（不是給 adjusted=None，是整條不產生，
    避免呼叫端誤用未達樣本門檻的半成品）。"""
    from warroom.short_scenarios import _PROB_TABLE, _COLOR_KEY, _finalize_probs

    by_bucket: Dict[str, List[str]] = {}
    for e in log:
        realized = e.get("realized")
        bucket = e.get("bucket")
        if realized not in ("base", "risk", "bull") or not bucket:
            continue
        by_bucket.setdefault(bucket, []).append(realized)

    out: Dict[str, Dict] = {}
    for bucket, realized_list in by_bucket.items():
        n = len(realized_list)
        if n < min_samples:
            continue
        parts = bucket.split("_x_")
        if len(parts) != 2:
            continue
        key = _COLOR_KEY.get(parts[0], "y") + _COLOR_KEY.get(parts[1], "y")
        rule = _PROB_TABLE.get(key)
        if rule is None:
            continue
        rule_base, rule_risk, rule_bull = rule
        observed = {
            "base": round(realized_list.count("base") / n, 4),
            "risk": round(realized_list.count("risk") / n, 4),
            "bull": round(realized_list.count("bull") / n, 4),
        }
        lam = _shrinkage_lambda(n)
        mixed = {}
        for k, rule_val in (("base", rule_base), ("risk", rule_risk), ("bull", rule_bull)):
            mix_val = rule_val * (1 - lam) + observed[k] * 100.0 * lam
            lo, hi = rule_val - max_deviation_pct, rule_val + max_deviation_pct
            mixed[k] = max(lo, min(hi, mix_val))
        b_p, r_p, u_p = _finalize_probs(mixed["base"], mixed["risk"], mixed["bull"])
        out[bucket] = {
            "adjusted": {"base": b_p, "risk": r_p, "bull": u_p},
            "n": n,
            "observed": observed,
            "updated_at": now_iso or _now_iso(),
        }
    return out


def write_calibration(calibration: Dict, path: str = CALIBRATION_PATH) -> None:
    _write_json_atomic(path, calibration)


def sync_calibration(log_path: str = SCENARIO_LOG, calibration_path: str = CALIBRATION_PATH
                     ) -> Optional[Dict]:
    """讀 scenario_log → 算 calibration → 寫 prob_calibration.json。log 讀不到（壞檔）
    一律跳過不寫、回 None（fail-closed，同 sync_scenario_log 的精神）。供
    build_snapshots.main() 在 sync_scenario_log 之後呼叫。"""
    try:
        log = _load_scenario_log(log_path)
    except Exception as ex:
        warnings.warn(
            f"scenario_log 讀取失敗（{log_path}）：{type(ex).__name__} {ex}；"
            "本次跳過校正表更新（fail-closed）")
        return None
    calibration = compute_calibration(log)
    try:
        write_calibration(calibration, calibration_path)
    except Exception:
        pass
    return calibration
