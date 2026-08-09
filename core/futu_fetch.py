"""Jarvis_60 fetcher — pulls an option chain from Futu OpenD and saves it as CSV.
Thin pipe only: no scoring logic here. Saved files become fixed test data."""
import sys, os, datetime
from futu import OpenQuoteContext, SysConfig

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
KEY = "/Users/leolo/.openclaw/futu/conn_key_1024.pem"

def fetch_chain(ticker: str = "US.TSLA", days_ahead: int = 28) -> str:
    SysConfig.enable_proto_encrypt(True)
    SysConfig.set_init_rsa_file(KEY)
    ctx = OpenQuoteContext(host="127.0.0.1", port=11112)
    try:
        start = datetime.date.today()
        end = start + datetime.timedelta(days=days_ahead)
        ret, chain = ctx.get_option_chain(
            code=ticker, start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d")
        )
        if ret != 0:
            print("Chain fetch FAILED:", chain); return ""
        codes = list(chain["code"])
        print(f"contracts found: {len(codes)}")
        rows = []
        for i in range(0, len(codes), 200):  # snapshot API caps per call
            r, snap = ctx.get_market_snapshot(codes[i:i+200])
            if r != 0:
                print("Snapshot FAILED:", snap); return ""
            rows.append(snap)
        import pandas as pd
        df = pd.concat(rows, ignore_index=True)
        out = os.path.join(DATA_DIR, f"{ticker.replace('.','_')}_{start}.csv")
        df.to_csv(out, index=False)
        print(f"saved: {out}  rows={len(df)}  cols={len(df.columns)}")
        print("columns:", ", ".join(list(df.columns)[:25]))
        return out
    finally:
        ctx.close()

if __name__ == "__main__":
    fetch_chain(sys.argv[1] if len(sys.argv) > 1 else "US.TSLA")
