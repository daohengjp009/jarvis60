"""Daily stock-side capital flow by trade size, per symbol, ~250 trading days.
Source: get_capital_flow(period_type="DAY"). Costs no history quota.
Futu serves a rolling window, so this must be rerun regularly or the tail is lost.
Writes data/capital_flow/.  Usage: python3 backfill_capital_flow.py"""
import os, time, datetime
import pandas as pd
from futu import OpenQuoteContext, SysConfig

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "data", "capital_flow")
KEY = "/Users/leolo/.openclaw/futu/conn_key_1024.pem"
SYMBOLS = "TSLA NVDA AAPL MSFT GOOGL SPY QQQ SPCX INTC MU SKHY COHR BE AMZN META AMD NFLX AVGO COIN PLTR MSTR ARM IWM SMCI CRWD ORCL LLY XOM".split()
os.makedirs(OUT, exist_ok=True)

def main():
    SysConfig.enable_proto_encrypt(True); SysConfig.set_init_rsa_file(KEY)
    ctx = OpenQuoteContext(host="127.0.0.1", port=11112)
    T = datetime.date.today()
    start = str(T - datetime.timedelta(days=400))
    try:
        for s in SYMBOLS:
            time.sleep(0.5)
            r, d = ctx.get_capital_flow(f"US.{s}", period_type="DAY",
                                        start=start, end=str(T))
            if r != 0:
                print(f"  {s}: ERR {str(d)[:60]}", flush=True); continue
            d = d.rename(columns={"capital_flow_item_time": "time"})
            d["time"] = pd.to_datetime(d["time"]).dt.strftime("%Y-%m-%d")
            d = d.drop(columns=[c for c in ("last_valid_time",) if c in d.columns])
            path = os.path.join(OUT, f"US_{s}_flow.csv")
            if os.path.exists(path):
                d = pd.concat([pd.read_csv(path), d], ignore_index=True)
            d = d.drop_duplicates(subset=["time"], keep="last").sort_values("time")
            d.to_csv(path, index=False)
            print(f"  {s:6s} {len(d):>4} rows  {d.time.min()} .. {d.time.max()}", flush=True)
    finally:
        ctx.close()

if __name__ == "__main__":
    main()
