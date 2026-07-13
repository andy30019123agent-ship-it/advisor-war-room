"""Phase 3 — 主題雷達（看未來）。紀律：熱度用真實新聞聲量趨勢算，
且『熱度上升 + 個股確認』才成案，只有噪音的僅進觀察。附 thesis log 防事後諸葛。
熱度：GDELT timelinevol（近7日均量 vs 基準）；個股確認：美股領頭股 20 日動能（yfinance，快、不吃 FinMind 額度）。
"""
import json, time, os, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
import yfinance as yf

TPE = timezone(timedelta(hours=8))
LOG_PATH = "data/theme_log.json"

# 人工維護的候選主題（可隨新聞增修）。query=GDELT英文詞、lead=領頭美股、tw=台股供應鏈
THEMES = [
    {"name": "矽光子 / CPO", "query": "silicon photonics", "lead": "COHR", "tw": "聯亞 · 光聖 · 華星光"},
    {"name": "AI ASIC 客製晶片", "query": "AI ASIC chip", "lead": "AVGO", "tw": "世芯 · 創意 · M31"},
    {"name": "先進封裝 / CoWoS", "query": "CoWoS advanced packaging", "lead": "NVDA", "tw": "台積電 · 日月光 · 辛耘"},
    {"name": "HBM 高頻寬記憶體", "query": "HBM memory AI", "lead": "MU", "tw": "群聯 · 南亞科 · 華邦電"},
    {"name": "人形機器人", "query": "humanoid robot", "lead": "TSLA", "tw": "上銀 · 所羅門 · 廣達"},
    {"name": "資料中心液冷", "query": "data center liquid cooling", "lead": "VRT", "tw": "奇鋐 · 雙鴻 · 高力"},
]


def gdelt_heat(query, tries=4):
    u = ("https://api.gdeltproject.org/api/v2/doc/doc?query=" + urllib.parse.quote(query) +
         "&mode=timelinevol&format=json&timespan=3m")
    for i in range(tries):
        try:
            d = json.loads(urllib.request.urlopen(
                urllib.request.Request(u, headers={"User-Agent": "advisor-war-room/1.0"}), timeout=25).read())
            pts = (d.get("timeline") or [{}])[0].get("data", [])
            vals = [p["value"] for p in pts]
            if len(vals) < 14:
                return None
            recent = sum(vals[-7:]) / 7
            base = sum(vals[:-7]) / max(1, len(vals) - 7)
            return round((recent - base) / (base + 1e-6), 2)
        except Exception:
            time.sleep((i + 1) * 3)  # GDELT 限流退避
    return None


def us_mom(ticker):
    try:
        c = yf.Ticker(ticker).history(period="1mo")["Close"]
        return round((c.iloc[-1] / c.iloc[0] - 1) * 100, 1) if len(c) > 1 else None
    except Exception:
        return None


def load_log():
    if os.path.exists(LOG_PATH):
        return json.load(open(LOG_PATH, encoding="utf-8"))
    return {}


def fetch_themes():
    log = load_log()
    today = datetime.now(TPE).strftime("%Y-%m-%d")
    out = []
    for t in THEMES:
        heat = gdelt_heat(t["query"])
        mom = us_mom(t["lead"])
        time.sleep(2)  # 主題間隔，避開 GDELT 429
        rising = heat is not None and heat > 0.3
        confirmed = mom is not None and mom > 0
        if rising and confirmed:
            status, reason = "成案", "熱度上升＋領頭股動能正向"
        elif rising and not confirmed:
            status, reason = "觀察", "熱度上升但個股未確認（領頭股走弱）"
        elif not rising and confirmed:
            status, reason = "觀察", "個股有動能但話題熱度未起"
        else:
            status, reason = "觀察", "熱度未起、個股未確認"
        # thesis log：第一次見到記下日期
        key = t["name"]
        if key not in log:
            log[key] = {"first_seen": today, "first_heat": heat}
        out.append({**t, "heat": heat, "mom": mom, "status": status, "reason": reason,
                    "first_seen": log[key]["first_seen"]})
    os.makedirs("data", exist_ok=True)
    json.dump(log, open(LOG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    # 排序：成案優先，再依熱度
    out.sort(key=lambda x: (x["status"] != "成案", -(x["heat"] or -9)))
    return out


if __name__ == "__main__":
    res = fetch_themes()
    for t in res:
        h = f'{t["heat"]:+.0%}' if t["heat"] is not None else "—"
        m = f'{t["mom"]:+.1f}%' if t["mom"] is not None else "—"
        print(f'  [{t["status"]}] {t["name"]}: 熱度 {h} · 領頭{t["lead"]} {m} · {t["reason"]}')
    json.dump(res, open("data/themes.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("→ 已寫 data/themes.json")
