"""每週日「下週劇本」：讀 public/data/daily.json 最近一次快照（＋每檔 stocks/<id>.json 補充計畫），
規則生成純文字劇本發 Telegram。用法：
  python -m warroom.weekly_brief            # 正常執行（非週日直接略過）
  python -m warroom.weekly_brief --force    # 略過「週日」檢查（本機測試／手動觸發用）

無 TG_BOT_TOKEN/TG_CHAT_ID 環境變數時 dry-run 印 stdout，不報錯（沿用 warroom.alerts.send_telegram）。

daily.json 的 events／exposure_guidance、stocks/<id>.json 的 primary_decision.advice 都是選填欄位
（另一支管線正在補齊中）——任一欄位缺席時對應區塊直接跳過，不得 crash。
"""
import argparse
import json
from datetime import datetime, timedelta, timezone

from warroom.alerts import send_telegram

_TPE = timezone(timedelta(hours=8))
_WEEKDAY_ZH = "一二三四五六日"

DEFAULT_DATA_PATH = "public/data/daily.json"
DEFAULT_STOCKS_DIR = "public/data/stocks"

MAX_MESSAGE_LEN = 900


def is_brief_day(now=None):
    """台北時間週日回 True（週日晚上由 workflow 排程觸發，這裡只做日期閘門）。"""
    now = now or datetime.now(_TPE)
    return now.weekday() == 6


def load_json(path):
    """graceful：檔案不存在／壞掉一律回 None，不炸主流程。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _weekday_zh(date_str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return ""
    return _WEEKDAY_ZH[d.weekday()]


def _fmt_date(date_str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return date_str or ""
    return d.strftime("%m/%d")


def _fmt_price(v):
    if not isinstance(v, (int, float)):
        return "—"
    return f"{v:,.1f}" if not float(v).is_integer() else f"{int(v):,}"


# ── 各區塊產生器：daily 缺欄位一律回 None，呼叫方自動跳過該區塊 ──────────

def build_market_section(daily, stocks_dir=None):
    market = daily.get("market")
    if not market:
        return None
    status = market.get("status")
    risk_temp = market.get("risk_temp")
    conclusion = market.get("conclusion")
    head_parts = []
    if status:
        head_parts.append(str(status))
    if risk_temp is not None:
        head_parts.append(f"風險溫度 {risk_temp}/10")
    head = "，".join(head_parts)
    if head and conclusion:
        line = f"{head}。{conclusion}"
    else:
        line = head or conclusion
    if not line:
        return None
    return "【上週收盤定位】\n" + line


def build_events_section(daily, stocks_dir=None):
    events = daily.get("events")
    if not events:
        return None
    lines = ["【本週事件】"]
    for ev in events:
        date_disp = _fmt_date(ev.get("date"))
        wd = _weekday_zh(ev.get("date"))
        wd_disp = f"（{wd}）" if wd else ""
        name = ev.get("name") or ""
        label = ev.get("label") or ""
        entry = " ".join(p for p in (f"{date_disp}{wd_disp}", name, label) if p)
        if entry:
            lines.append(entry)
    if len(lines) == 1:
        return None
    return "\n".join(lines)


def _stock_plan_line(stock_id, stocks_dir):
    """試著從 stocks/<id>.json 撈 advice.holder.plan[0] 當「一句 plan」；
    這個欄位由另一支管線補齊中，檔案／欄位缺席都回 None，讓呼叫方退而求其次。"""
    if not stock_id:
        return None
    data = load_json(f"{stocks_dir}/{stock_id}.json")
    if not data:
        return None
    advice = ((data.get("primary_decision") or {}).get("advice")) or {}
    plan = (advice.get("holder") or {}).get("plan") or []
    if not plan:
        return None
    first = plan[0] or {}
    trigger, act = first.get("trigger"), first.get("act")
    if trigger and act:
        return f"{trigger}→{act}"
    return None


def build_holdings_section(daily, stocks_dir=DEFAULT_STOCKS_DIR):
    tracked = daily.get("tracked")
    if not tracked:
        return None
    lines = ["【持股劇本】"]
    for stock in tracked:
        name = stock.get("name") or ""
        sid = stock.get("id") or ""
        decision = stock.get("decision") or {}
        action = decision.get("action") or "—"
        defense_s = _fmt_price(decision.get("defense_price"))
        plan_line = _stock_plan_line(sid, stocks_dir)
        if not plan_line:
            reason = decision.get("readable_reason") or ""
            plan_line = reason.split("；")[0].split("。")[0].strip() if reason else ""
        head = f"{name}（{sid}）：{action}，防守價 {defense_s}"
        lines.append(f"{head}。{plan_line}" if plan_line else head)
    if len(lines) == 1:
        return None
    return "\n".join(lines)


def build_principle_section(daily, stocks_dir=None):
    exposure = daily.get("exposure_guidance") or {}
    note = exposure.get("note")
    if not note:
        note = (daily.get("market") or {}).get("conclusion")
    if not note:
        return None
    return "【本週原則】\n" + note


_SECTION_BUILDERS = (
    build_market_section,
    build_events_section,
    build_holdings_section,
    build_principle_section,
)


def build_brief(daily, stocks_dir=DEFAULT_STOCKS_DIR):
    """組出完整「下週劇本」純文字；daily 為 None／空 dict 時回 None（呼叫方略過發送）。"""
    if not daily:
        return None
    data_date = (daily.get("meta") or {}).get("data_date")
    header = f"📅 下週劇本（{data_date} 收盤資料）" if data_date else "📅 下週劇本"

    sections = [header]
    for builder in _SECTION_BUILDERS:
        sec = builder(daily, stocks_dir)
        if sec:
            sections.append(sec)

    if len(sections) == 1:
        return None

    msg = "\n\n".join(sections)
    if len(msg) > MAX_MESSAGE_LEN:
        msg = msg[: MAX_MESSAGE_LEN - 1].rstrip() + "…"
    return msg


def run(data_path=DEFAULT_DATA_PATH, stocks_dir=DEFAULT_STOCKS_DIR, force=False, now=None):
    now = now or datetime.now(_TPE)
    if not force and not is_brief_day(now):
        print("非週日，略過本輪（用 --force 可強制執行）。")
        return 0

    daily = load_json(data_path)
    if not daily:
        print(f"{data_path} 讀取失敗或不存在，略過本輪。")
        return 0

    msg = build_brief(daily, stocks_dir=stocks_dir)
    if not msg:
        print("劇本內容為空，略過發送。")
        return 0

    send_telegram(msg)
    return 0


def main():
    ap = argparse.ArgumentParser(description="每週日下週劇本")
    ap.add_argument("--force", action="store_true", help="跳過「週日」檢查")
    ap.add_argument("--data", default=DEFAULT_DATA_PATH, help="daily.json 路徑")
    ap.add_argument("--stocks-dir", default=DEFAULT_STOCKS_DIR, help="stocks/<id>.json 所在目錄")
    a = ap.parse_args()
    return run(data_path=a.data, stocks_dir=a.stocks_dir, force=a.force)


if __name__ == "__main__":
    raise SystemExit(main())
