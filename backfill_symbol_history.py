"""Save 1 year of daily symbol-level option history for all 28 symbols.
Futu serves a rolling 252-day window, so run this regularly or the tail is lost.
Costs no history-K-line quota. Writes data/symbol_history/.
Usage: python3 backfill_symbol_history.py"""
import os, time, datetime
import pandas as pd
from futu import OpenQuoteContext, SysConfig

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "data", "symbol_history")
KEY = "/Users/leolo/.openclaw/futu/conn_key_1024.pem"
SYMBOLS = "TSLA NVDA AAPL MSFT GOOGL SPY QQQ SPCX INTC MU SKHY COHR BE AMZN META AMD NFLX AVGO COIN PLTR MSTR ARM IWM SMCI CRWD ORCL LLY XOM".split()
os.makedirs(OUT, exist_ok=True)

def merge(path, new, key="time"):
    """Append-only: keep every row ever seen, newest values win on conflict."""
    if os.path.exists(path):
        old = pd.read_csv(path)
        new = pd.concat([old, new], ignore_index=True)
    new = new.drop_duplicates(subset=[key], keep="last").sort_values(key)
    new.to_csv(path, index=False)
    return len(new)

def main():
    SysConfig.enable_proto_encrypt(True); SysConfig.set_init_rsa_file(KEY)
    ctx = OpenQuoteContext(host="127.0.0.1", port=11112)
    start = "2025-01-01"
    end = str(datetime.date.today())
    try:
        for sym in SYMBOLS:
            for label, fn in (("stat", ctx.get_option_underlying_his_statistic),
                              ("vol",  ctx.get_option_underlying_his_volatility)):
                time.sleep(0.5)
                res = fn(f"US.{sym}", begin_time=start, end_time=end)
                r, d = res[0], res[1]
                if r != 0:
                    print(f"  {sym} {label}: ERR {d}", flush=True); continue
                n = merge(os.path.join(OUT, f"US_{sym}_{label}.csv"), d)
                print(f"  {sym:6s} {label:5s} +{len(d):>4} rows -> {n} total", flush=True)
    finally:
        ctx.close()

if __name__ == "__main__":
    main()
