"""Jarvis_60 daily chain snapshot — OI/IV/greeks for the full watchlist.
Irreplaceable: this data cannot be backfilled. Run once daily AFTER the US open
(OI settles overnight and republishes in the US morning).
Usage: python3 snapshot.py"""
import os, sys, time, datetime, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from futu import OpenQuoteContext, SysConfig

BASE = os.path.dirname(os.path.abspath(__file__))
SNAPS = os.path.join(BASE, "data", "snapshots")
KEY = "/Users/leolo/.openclaw/futu/conn_key_1024.pem"
os.makedirs(SNAPS, exist_ok=True)

SYMBOLS = "TSLA NVDA AAPL MSFT GOOGL SPY QQQ SPCX INTC MU SKHY COHR BE".split()
COLS = ["code","option_type","option_strike_price","option_open_interest",
        "option_implied_volatility","option_premium","option_delta","option_gamma",
        "option_vega","option_theta","option_rho","option_expiry_date_distance",
        "strike_time","bid_price","ask_price","volume","turnover","last_price"]

def snapshot(ctx, ticker: str) -> int:
    code = f"US.{ticker}"
    today = datetime.date.today()
    end = today + datetime.timedelta(days=28)
    ret, chain = ctx.get_option_chain(code=code, start=str(today), end=str(end))
    if ret != 0:
        print(f"{ticker:6s} chain FAILED: {chain}"); return 0
    codes = list(chain["code"])
    rows = []
    for i in range(0, len(codes), 200):
        r, s = ctx.get_market_snapshot(codes[i:i+200])
        if r == 0: rows.append(s)
        else: print(f"{ticker:6s} snapshot batch failed: {s}")
        time.sleep(0.6)          # stay clear of the snapshot rate limit
    if not rows: return 0
    df = pd.concat(rows, ignore_index=True)
    keep = [c for c in COLS if c in df.columns]
    path = os.path.join(SNAPS, f"US_{ticker}_{today}.csv")
    df[keep].to_csv(path, index=False)
    return len(df)

def main():
    SysConfig.enable_proto_encrypt(True)
    SysConfig.set_init_rsa_file(KEY)
    ctx = OpenQuoteContext(host="127.0.0.1", port=11112)
    t0, total = time.time(), 0
    try:
        for s in SYMBOLS:
            n = snapshot(ctx, s); total += n
            print(f"{s:6s} {n:6,d} contracts   ({time.time()-t0:.0f}s elapsed)")
    finally:
        ctx.close()
    print(f"\nTOTAL {total:,} contracts in {time.time()-t0:.0f}s")
    try:
        from core.notify import send
        send(f"Chain snapshot done: {total:,} contracts across {len(SYMBOLS)} symbols")
    except Exception:
        pass

if __name__ == "__main__":
    main()
