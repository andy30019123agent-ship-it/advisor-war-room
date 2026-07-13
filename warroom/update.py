"""一鍵更新戰情室：抓資料 → 跑個股引擎 → 掃主題 → 抓大盤/類股 → 印數據摘要。
用法：
  python -m warroom.update              # 用選股器機會清單當個股，含主題
  python -m warroom.update --stocks 2330,2454,3661
  python -m warroom.update --no-themes  # 略過主題（GDELT 慢）
流程：跑完這支 → Claude 讀下方 DIGEST 寫 data/weekly_narration.json 的團隊觀點
     → python -m warroom.build_weekly → 出 reports/weekly.html。
"""
import sys, os, json, argparse
from warroom.analyze_tw import analyze
from warroom.market import fetch_market
from warroom.sectors import fetch_sectors

OPPS = os.path.expanduser("~/Desktop/agent/tw-stock-screener/dist/data/opportunities.json")
LZH = {"green": "🟢", "amber": "🟡", "red": "🔴"}


def stocks_from_opps():
    try:
        d = json.load(open(OPPS, encoding="utf-8"))
        return [p["id"] for p in d.get("picks", [])]
    except Exception:
        return []


def run(stock_ids, with_themes):
    os.makedirs("data", exist_ok=True)
    print("=" * 60)
    print("  更新戰情室 · 數據摘要（給 Claude 寫團隊觀點用）")
    print("=" * 60)

    # 個股
    print("\n── 個股引擎 ──")
    for sid in stock_ids:
        try:
            res = analyze(sid)
            json.dump(res, open(f"data/{sid}.json", "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2, default=str)
            s = res["summary"]
            fl, tl, cl = res["fundamental"]["light"], res["technical"]["light"], res["chips"]["light"]
            print(f"  {res['name']}({sid}): 基本{LZH[fl]} 技術{LZH[tl]} 籌碼{LZH[cl]} → {s['direction']}（分{s['score']}/信心{s['confidence']}）")
        except Exception as e:
            print(f"  {sid}: 失敗 {type(e).__name__} {str(e)[:60]}")

    # 主題
    if with_themes:
        print("\n── 主題雷達 ──")
        try:
            from warroom.themes import fetch_themes
            themes = fetch_themes()
            json.dump(themes, open("data/themes.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            for t in themes:
                h = f'{t["heat"]:+.0%}' if t.get("heat") is not None else "—"
                print(f'  [{t["status"]}] {t["name"]}: 熱度{h} 領頭{t["lead"]} {t.get("mom","?")}% · {t["reason"]}')
        except Exception as e:
            print(f"  主題失敗: {type(e).__name__} {str(e)[:60]}")
    else:
        print("\n── 主題雷達：略過（用既有 data/themes.json）──")

    # 大盤 + 類股
    print("\n── 大盤 ──")
    try:
        m = fetch_market()
        for i in m["items"]:
            wk = f'{i["wk"]:+.1f}%' if i["wk"] is not None else "—"
            print(f'  {LZH.get({"g":"green","y":"amber","r":"red"}[i["dot"]])} {i["name"]}: {i["value"]} ({wk})')
        if m.get("foreign"):
            print(f'  外資: {m["foreign"]["net_yi"]:+.0f} 億 ({m["foreign"]["date"]})')
        print(f'  → 大盤燈: {LZH[m["light"]]}')
    except Exception as e:
        print(f"  大盤失敗: {str(e)[:60]}")

    print("\n── 類股輪動（美股領先）──")
    try:
        for r in fetch_sectors():
            m5 = f'{r["m5"]:+.1f}%' if r["m5"] is not None else "—"
            print(f'  #{r["rank"]} [{r["tier"]}] {r["group"]}: 5日{m5} → {r["tw"]}')
    except Exception as e:
        print(f"  類股失敗: {str(e)[:60]}")

    print("\n" + "=" * 60)
    print("  下一步：Claude 依上方摘要更新 data/weekly_narration.json，")
    print("         再跑 python -m warroom.build_weekly")
    print("=" * 60)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stocks", default="")
    ap.add_argument("--no-themes", action="store_true")
    a = ap.parse_args()
    ids = [s.strip() for s in a.stocks.split(",") if s.strip()] or stocks_from_opps() or ["2330"]
    run(ids, not a.no_themes)
