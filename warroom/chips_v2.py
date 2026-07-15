"""籌碼拆解 v2（規格 §3.3）：三大法人分「外資／投信／自營」三組，
各給買賣超（股）、連續同向天數、佔 20 日均量比、分歧標記（外資賣投信買 或反向）。
輸入 FinMind taiwan_stock_institutional_investors 長表（欄 date/buy/sell/name，單位=股）。
純函式、缺資料降級：空表回 0 結構、不 crash。additive 併進 analyze 的 chips 區塊。
"""
from typing import Dict, List, Optional

import pandas as pd

# 5 類法人聚成 3 組（2026-07-15 真 API 實測 name 值）
GROUP_MAP = {
    "外資": ["Foreign_Investor", "Foreign_Dealer_Self"],
    "投信": ["Investment_Trust"],
    "自營": ["Dealer_self", "Dealer_Hedging"],
}
_NAME_TO_GROUP = {n: g for g, names in GROUP_MAP.items() for n in names}


def _dir(net: float) -> str:
    return "買" if net > 0 else "賣" if net < 0 else "平"


def _empty_group() -> Dict:
    return {"net_latest": 0, "net_5d": 0, "streak": 0, "dir": "平", "ratio_20d_vol": None}


def _streak(daily_nets: List[float]) -> int:
    """從最新日往回數連續同向（同號、非 0）天數；最新日為 0 → streak 0。"""
    if not daily_nets or daily_nets[-1] == 0:
        return 0
    sign = daily_nets[-1] > 0
    s = 0
    for v in reversed(daily_nets):
        if v != 0 and (v > 0) == sign:
            s += 1
        else:
            break
    return s


def chips_breakdown(chip_df, vol20: Optional[float] = None) -> Dict:
    """三大法人分組拆解。vol20＝20 日均量（股），用來算佔量比；缺則 ratio 為 None。"""
    groups = {g: _empty_group() for g in GROUP_MAP}
    if chip_df is None or len(chip_df) == 0 or "name" not in chip_df.columns:
        return {"as_of": None, "groups": groups, "divergence": False, "divergence_note": ""}

    df = chip_df.copy()
    df["buy"] = pd.to_numeric(df["buy"], errors="coerce").fillna(0)
    df["sell"] = pd.to_numeric(df["sell"], errors="coerce").fillna(0)
    df["net"] = df["buy"] - df["sell"]
    df["group"] = df["name"].map(_NAME_TO_GROUP)
    df = df.dropna(subset=["group"])
    if len(df) == 0:
        return {"as_of": None, "groups": groups, "divergence": False, "divergence_note": ""}

    as_of = str(df["date"].max())
    # 每組：每日淨額序列（依日期排序）
    for g in GROUP_MAP:
        sub = df[df["group"] == g]
        if len(sub) == 0:
            continue
        daily = sub.groupby("date")["net"].sum().sort_index()
        nets = [float(x) for x in daily.tolist()]
        net_latest = int(round(nets[-1]))
        net_5d = int(round(sum(nets[-5:])))
        ratio = None
        if vol20 is not None and pd.notna(vol20) and vol20 > 0:
            ratio = round(abs(net_latest) / float(vol20), 4)
        groups[g] = {"net_latest": net_latest, "net_5d": net_5d,
                     "streak": _streak(nets), "dir": _dir(net_latest),
                     "ratio_20d_vol": ratio}

    # 分歧：外資與投信最新日方向相反（且都非平）
    fd = groups["外資"]["dir"]
    td = groups["投信"]["dir"]
    divergence = fd != "平" and td != "平" and fd != td
    note = ""
    if divergence:
        note = f"外資{fd}、投信{td}（主力分歧）"
    return {"as_of": as_of, "groups": groups,
            "divergence": divergence, "divergence_note": note}
