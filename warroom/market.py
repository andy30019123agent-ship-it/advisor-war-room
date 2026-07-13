"""大盤層：台股（TAIEX/TPEx via FinMind）＋美股與總經（yfinance）＋外資買賣超。
每個指標給週變化與紅綠燈點；並綜合出一個「大盤環境」燈與備註。
"""
import yfinance as yf
from FinMind.data import DataLoader

US = [("S&P 500", "^GSPC", "up_good"), ("Nasdaq", "^IXIC", "up_good"),
      ("費半 SOX", "^SOX", "up_good"), ("VIX 波動率", "^VIX", "down_good"),
      ("美 10Y 殖利率", "^TNX", "down_good"), ("美元 DXY", "DX-Y.NYB", "down_good"),
      ("美元/台幣", "TWD=X", "down_good")]


def _dot(wk, kind):
    """kind: up_good=漲好, down_good=跌好（如 VIX/殖利率/美元對台股是逆風）。"""
    good = wk if kind == "up_good" else -wk
    return "g" if good > 0.5 else "r" if good < -0.5 else "y"


def fetch_market():
    dl = DataLoader()
    items = []
    # 台股指數（FinMind）
    for name, sid in [("加權指數", "TAIEX"), ("櫃買 TPEx", "TPEx")]:
        try:
            df = dl.taiwan_stock_daily(stock_id=sid, start_date="2026-05-01").sort_values("date").reset_index(drop=True)
            last = df.iloc[-1]["close"]
            wk = (last / df.iloc[-6]["close"] - 1) * 100
            ma20 = df["close"].rolling(20).mean().iloc[-1]
            dot = "g" if (wk > 0.5 and last > ma20) else "r" if (wk < -0.5 and last < ma20) else "y"
            items.append({"name": name, "value": f"{last:,.0f}", "wk": round(wk, 2), "dot": dot, "grp": "tw"})
        except Exception as e:
            items.append({"name": name, "value": "—", "wk": None, "dot": "y", "grp": "tw", "err": str(e)[:40]})
    # 美股 / 總經（yfinance）
    for name, t, kind in US:
        try:
            h = yf.Ticker(t).history(period="7d")
            last = float(h["Close"].iloc[-1]); wk = (last / float(h["Close"].iloc[0]) - 1) * 100
            unit = "%" if t == "^TNX" else ""
            items.append({"name": name, "value": f"{last:,.2f}{unit}", "wk": round(wk, 2),
                          "dot": _dot(wk, kind), "grp": "us"})
        except Exception as e:
            items.append({"name": name, "value": "—", "wk": None, "dot": "y", "grp": "us", "err": str(e)[:40]})
    # 外資買賣超（FinMind 全市場合計）
    foreign = None
    try:
        fdf = dl.taiwan_stock_institutional_investors_total(start_date="2026-07-01")
        f = fdf[fdf["name"].str.contains("Foreign", case=False, na=False)]
        if len(f):
            latest_date = f["date"].max()
            net = (f[f["date"] == latest_date]["buy"].sum() - f[f["date"] == latest_date]["sell"].sum()) / 1e8
            foreign = {"date": latest_date, "net_yi": round(net, 1)}
    except Exception:
        pass

    # 綜合大盤燈：以台股指數 + SOX + VIX 為主
    dots = [i["dot"] for i in items if i["name"] in ("加權指數", "費半 SOX", "VIX 波動率")]
    score = dots.count("g") - dots.count("r")
    light = "green" if score >= 2 else "red" if score <= -2 else "amber"
    return {"items": items, "foreign": foreign, "light": light}


if __name__ == "__main__":
    import json
    m = fetch_market()
    for i in m["items"]:
        print(f"  [{i['dot']}] {i['name']}: {i['value']}  週 {i['wk']}%")
    print("外資:", m["foreign"])
    print("大盤燈:", m["light"])
