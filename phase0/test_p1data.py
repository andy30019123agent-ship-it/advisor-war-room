"""Phase 1 資料集驗證 — 實際打 FinMind API，驗證未來要用的新資料集是否可得、欄位是否齊。
只讀不寫、每次呼叫間 sleep 1 秒，總呼叫數控制在 ~40 次內。
"""
import time, sys, traceback, json
from datetime import datetime, timezone, timedelta

from FinMind.data import DataLoader

TPE = timezone(timedelta(hours=8))
def now_tpe(): return datetime.now(TPE).strftime("%Y-%m-%d %H:%M:%S")

dl = DataLoader()

call_count = 0
def call(label, fn, *args, **kwargs):
    global call_count
    call_count += 1
    print(f"\n{'='*70}\n[{call_count}] {label}  @ {now_tpe()}\n{'='*70}")
    try:
        df = fn(*args, **kwargs)
        if df is None or len(df) == 0:
            print(f"❌ 空結果 (None 或 0 筆) — args={args} kwargs={kwargs}")
            return None
        print(f"✅ {len(df)} 筆")
        print(f"欄位: {list(df.columns)}")
        print("最後一列樣本:")
        print(df.iloc[-1].to_dict())
        if len(df) > 1:
            print("第一列樣本:")
            print(df.iloc[0].to_dict())
        return df
    except Exception as e:
        print(f"❌ EXCEPTION {type(e).__name__}: {str(e)[:300]}")
        traceback.print_exc(limit=2)
        return None
    finally:
        time.sleep(1)

tickers = ["2330", "2882", "8299"]

# 1. TaiwanStockFinancialStatements — 三檔都測
for t in tickers:
    call(f"1. FinancialStatement {t}", dl.taiwan_stock_financial_statement, stock_id=t, start_date="2024-01-01")

# 2. TaiwanStockBalanceSheet — 2330 + 8299
for t in ["2330", "8299"]:
    call(f"2. BalanceSheet {t}", dl.taiwan_stock_balance_sheet, stock_id=t, start_date="2024-01-01")

# 3. TaiwanStockCashFlowsStatement — 2330 + 2882
for t in ["2330", "2882"]:
    call(f"3. CashFlowsStatement {t}", dl.taiwan_stock_cash_flows_statement, stock_id=t, start_date="2024-01-01")

# 4. TaiwanStockInstitutionalInvestorsBuySell — 三檔都測，近10天
recent_start = (datetime.now(TPE) - timedelta(days=14)).strftime("%Y-%m-%d")
for t in tickers:
    call(f"4. InstitutionalInvestors {t} (近14天含非交易日緩衝)", dl.taiwan_stock_institutional_investors, stock_id=t, start_date=recent_start)

# 5. TaiwanStockPER — 2330 抓 2021-01-01 至今（測歷史量+速度），8299 抓近期
t0 = time.time()
df_per = call("5a. PER/PBR 2330 (2021-01-01至今，測長區間速度)", dl.taiwan_stock_per_pbr, stock_id="2330", start_date="2021-01-01")
elapsed = time.time() - t0
print(f"⏱ 2330 長區間 PER/PBR 耗時: {elapsed:.2f} 秒" + (f"，{len(df_per)} 筆" if df_per is not None else ""))
call("5b. PER/PBR 8299 (近期)", dl.taiwan_stock_per_pbr, stock_id="8299", start_date="2026-06-01")

# 6. TaiwanStockInfo — 全市場一次撈，查 industry_category 欄位
df_info = call("6. TaiwanStockInfo (全市場)", dl.taiwan_stock_info)
if df_info is not None:
    for t in tickers:
        row = df_info[df_info["stock_id"] == t]
        print(f"  {t} info: {row.to_dict('records')}")

# 7. TaiwanStockDividend + TaiwanStockDividendResult — 2330
call("7a. Dividend 2330 (公告面，含未來除權息)", dl.taiwan_stock_dividend, stock_id="2330", start_date="2024-01-01")
call("7b. DividendResult 2330 (除權息結果)", dl.taiwan_stock_dividend_result, stock_id="2330", start_date="2024-01-01")

# 8. TaiwanStockMonthRevenue — 確認 date 欄位語意
call("8. MonthRevenue 2330 (查date欄位語意)", dl.taiwan_stock_month_revenue, stock_id="2330", start_date="2025-01-01")

print(f"\n\n總呼叫次數: {call_count}")
print(f"完成時間: {now_tpe()}")
