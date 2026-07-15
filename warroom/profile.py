"""投資人參數（Andy 問卷 2026-07-15，存 data/investor_profile.json）的讀取工具。
規格 §1：三時間框架、停損 -8%~-15%、部位金額檔位 0/10萬/20萬/40萬/60萬、
核心持股 2330/0050。本模組只負責讀，不含任何運算規則。
"""
import json
from typing import Dict, List

DEFAULT_PROFILE_PATH = "data/investor_profile.json"


def load_profile(path: str = DEFAULT_PROFILE_PATH) -> Dict:
    """讀投資人參數 JSON。找不到檔或格式錯會直接拋例外（讓上層明確失敗，不吞錯）。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def is_core_holding(profile: Dict, stock_id: str) -> bool:
    """是否為核心持股（定期定額續買，加減碼建議不影響核心部位）。"""
    return stock_id in profile.get("core_holdings", [])


def position_tiers(profile: Dict) -> List[Dict]:
    """部位金額檔位清單：[{"name":..., "amount":...}, ...]。"""
    return profile.get("position_tiers", [])
