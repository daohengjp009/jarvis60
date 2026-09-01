"""Jarvis_60 daily chain snapshot — OI/IV/greeks for the full watchlist.
Irreplaceable: this data cannot be backfilled. Run once daily AFTER the US open
(OI settles overnight and republishes in the US morning).
Usage: python3 snapshot.py"""
import argparse, os, sys, time, datetime, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from futu import OpenQuoteContext, SysConfig

BASE = os.path.dirname(os.path.abspath(__file__))
SNAPS = os.path.join(BASE, "data", "snapshots")
KEY = "/Users/leolo/.openclaw/futu/conn_key_1024.pem"
os.makedirs(SNAPS, exist_ok=True)

SYMBOLS = "TSLA NVDA AAPL MSFT GOOGL SPY QQQ SPCX INTC MU SKHY COHR BE AMZN META AMD NFLX AVGO COIN PLTR MSTR ARM IWM SMCI CRWD ORCL LLY XOM".split()
COLS = ["code","option_type","option_strike_price","option_open_interest",
        "option_implied_volatility","option_premium","option_delta","option_gamma",
        "option_vega","option_theta","option_rho","option_expiry_date_distance",
        "strike_time","bid_price","ask_price","volume","turnover","last_price"]
DTE_MAX = 365
CHAIN_SPAN = 30
CHAIN_SLEEP = 3.5

def _windows(today, dte_max=DTE_MAX, span=CHAIN_SPAN):
    d, out = today, []
    while (d - today).days <= dte_max:
        end = min(d + datetime.timedelta(days=span - 1),
                  today + datetime.timedelta(days=dte_max))
        out.append((str(d), str(end)))
        d = end + datetime.timedelta(days=1)
    return out

def snapshot(ctx, ticker: str, dte_max=DTE_MAX) -> int:
    code = f"US.{ticker}"
    today = datetime.date.today()
    codes = []
    for start, end in _windows(today, dte_max):
        ret, chain = ctx.get_option_chain(code=code, start=start, end=end)
        if ret != 0:
            print(f"{ticker:6s} chain {start}..{end} FAILED: {chain}")
        else:
            codes.extend(chain["code"])
        time.sleep(CHAIN_SLEEP)
    codes = sorted(set(codes))
    rows = []
    for i in range(0, len(codes), 400):
        r, s = ctx.get_market_snapshot(codes[i:i+400])
        if r == 0: rows.append(s)
        else: print(f"{ticker:6s} snapshot batch failed: {s}")
        time.sleep(0.6)          # stay clear of the snapshot rate limit
    if not rows: return 0
    df = pd.concat(rows, ignore_index=True)
    keep = [c for c in COLS if c in df.columns]
    path = os.path.join(SNAPS, f"US_{ticker}_{today}.csv")
    df[keep].to_csv(path, index=False)
    return len(df)

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dte-max", type=int, default=DTE_MAX)
    parser.add_argument("--symbols", nargs="+", default=SYMBOLS)
    args = parser.parse_args(argv)
    if args.dte_max < 0:
        parser.error("--dte-max must be non-negative")
    SysConfig.enable_proto_encrypt(True)
    SysConfig.set_init_rsa_file(KEY)
    ctx = OpenQuoteContext(host="127.0.0.1", port=11112)
    t0, total = time.time(), 0
    try:
        for s in args.symbols:
            n = snapshot(ctx, s, args.dte_max); total += n
            print(f"{s:6s} {n:6,d} contracts   ({time.time()-t0:.0f}s elapsed)")
    finally:
        ctx.close()
    print(f"\nTOTAL {total:,} contracts in {time.time()-t0:.0f}s")
    try:
        from core.notify import send
        send(f"Chain snapshot done: {total:,} contracts across {len(args.symbols)} symbols")
    except Exception:
        pass

if __name__ == "__main__":
    main()
