"""一致性檢查：narration（Claude 手寫敘事）數字/日期 vs 引擎 JSON（規格 §4）。
關鍵字後方數字差>1%、或敘事 as_of 日期早於引擎最新資料日 → 記 diff。
build 前呼叫 assert_consistent，有 diff 就中止（非零 exit）並印 diff，禁止舊敘事上線。
"""
import re
import sys
from typing import Dict, List, Optional

_NUM = re.compile(r"(?<![A-Za-z0-9])-?\d[\d,]*\.?\d*")
_DATE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")


def _to_float(tok: str) -> Optional[float]:
    try:
        return float(tok.replace(",", ""))
    except ValueError:
        return None


def _numbers_after(text: str, keyword: str, window: int = 20) -> List[float]:
    """關鍵字後方 window 字內的第一個數字（可能多處出現，逐一取）。"""
    out = []
    for m in re.finditer(re.escape(keyword), text):
        seg = text[m.end(): m.end() + window]
        nm = _NUM.search(seg)
        if nm:
            v = _to_float(nm.group())
            if v is not None:
                out.append(v)
    return out


def _parse_date(text: str):
    m = _DATE.search(text or "")
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def build_stock_anchors(engine: Dict) -> Dict[str, float]:
    """從引擎 JSON 取可比對的錨點數字。"""
    a = {}
    t = engine.get("technical", {}).get("ev", {})
    for k in ("MA20", "MA60", "MA120", "收盤"):
        if isinstance(t.get(k), (int, float)):
            a[k] = float(t[k])
    dec = engine.get("decision", {}) or {}
    fv = dec.get("fair_value")
    if fv:
        for k, label in (("bear", "Bear"), ("base", "Base"), ("bull", "Bull")):
            if isinstance(fv.get(k), (int, float)):
                a[label] = float(fv[k])
    stop = dec.get("stop") or {}
    if isinstance(stop.get("price"), (int, float)):
        a["停損"] = float(stop["price"])
    if isinstance(dec.get("risk_reward"), (int, float)):
        a["R/R"] = float(dec["risk_reward"])
    pos = dec.get("position") or {}
    if isinstance(pos.get("amount"), (int, float)):
        a["部位金額"] = float(pos["amount"])
    conf = dec.get("confidence") or {}
    if isinstance(conf.get("total"), (int, float)):
        a["信心"] = float(conf["total"])
    return a


def check_numbers(text: str, anchors: Dict[str, float], tol: float = 0.01) -> List[str]:
    """關鍵字後方數字 vs 錨點，相對差>tol 記 diff。錨點在敘事沒出現則跳過（不強制提及）。"""
    diffs = []
    for kw, truth in anchors.items():
        if truth == 0:
            continue
        for got in _numbers_after(text, kw):
            if abs(got - truth) / abs(truth) > tol:
                diffs.append(f"[數字不符] 敘事「{kw} {got}」≠ 引擎 {truth}"
                             f"（差 {abs(got - truth) / abs(truth) * 100:.1f}%）")
    return diffs


def _iter_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_strings(v)


def _latest_engine_date(engine: Dict):
    c = engine.get("chips", {}).get("ev", {}).get("最新日")
    return _parse_date(str(c)) if c else None


def check_stock_consistency(engine: Dict, narration: Dict) -> List[str]:
    """單檔：數字錨點 + as_of 日期不得早於引擎最新資料日。"""
    diffs = []
    text = " ".join(_iter_strings(narration))
    diffs += check_numbers(text, build_stock_anchors(engine))
    nd = _parse_date(narration.get("as_of", ""))
    ed = _latest_engine_date(engine)
    if nd and ed and nd < ed:
        diffs.append(f"[日期落後] 敘事 as_of {nd} 早於引擎最新資料日 {ed}")
    return diffs


def check_weekly_consistency(engine_by_id: Dict[str, Dict], weekly: Dict) -> List[str]:
    """週報：每檔個股一句 vs 該檔引擎錨點。"""
    diffs = []
    for sid, text in (weekly.get("stocks", {}) or {}).items():
        eng = engine_by_id.get(sid)
        if not eng:
            continue
        diffs += [f"({sid}) " + d for d in check_numbers(str(text), build_stock_anchors(eng))]
    return diffs


def assert_consistent(diffs: List[str], context: str) -> None:
    """有 diff → 印 stderr 並 sys.exit(1)（build 中止）；無 → 印通過。"""
    if diffs:
        print(f"✗ 一致性檢查失敗（{context}）：", file=sys.stderr)
        for d in diffs:
            print("  - " + d, file=sys.stderr)
        sys.exit(1)
    print(f"✓ 一致性檢查通過（{context}）")
