"""Jarvis_60 tick collector — records what cannot be fetched retroactively.
Usage: python3 collect.py TSLA NVDA          (runs until Ctrl-C)
Saves: data/ticks/<CODE>_<date>.csv  and  data/snapshots/<TICKER>_<date>.csv"""
import sys, os, time, datetime, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from futu import OpenQuoteContext, SysConfig, SubType

KEY = "/Users/leolo/.openclaw/futu/conn_key_1024.pem"
BASE = os.path.dirname(os.path.abspath(__file__))
TICKS = os.path.join(BASE, "data", "ticks")
SNAPS = os.path.join(BASE, "data", "snapshots")
COLS = ["option_type","option_strike_price","option_open_interest","option_implied_volatility",
        "option_premium","option_delta","option_gamma","option_vega","option_theta",
        "option_expiry_date_distance","bid_price","ask_price","volume","turnover","last_price","code"]
POLL_SECONDS = 30
TOP_N = 12  # contracts watched per ticker

def _ctx():
    SysConfig.enable_proto_encrypt(True)
    SysConfig.set_init_rsa_file(KEY)
    return OpenQuoteContext(host="127.0.0.1", port=11112)

def pick_contracts(ctx, ticker: str) -> list:
    """Daily snapshot + choose the most liquid contracts to watch."""
    today = datetime.date.today()
    end = today + datetime.timedelta(days=28)
    ret, chain = ctx.get_option_chain(code=ticker, start=str(today), end=str(end))
    if ret != 0:
        print(f"[{ticker}] chain failed:", chain); return []
    codes = list(chain["code"])
    rows = []
    for i in range(0, len(codes), 200):
        r, s = ctx.get_market_snapshot(codes[i:i+200])
        if r == 0: rows.append(s)
    if not rows: return []
    df = pd.concat(rows, ignore_index=True)
    keep = [c for c in COLS if c in df.columns]
    snap_path = os.path.join(SNAPS, f"{ticker.replace('.','_')}_{today}.csv")
    df[keep].to_csv(snap_path, index=False)
    print(f"[{ticker}] snapshot saved: {len(df)} contracts -> {os.path.basename(snap_path)}")
    live = df[(df["option_premium"] > 0) & (df["volume"] > 0)].copy()
    live = live.sort_values("volume", ascending=False)
    return list(live["code"].head(TOP_N))

def append_ticks(ctx, code: str, seen: set):
    r, t = ctx.get_rt_ticker(code, 500)
    if r != 0 or t is None or len(t) == 0: return 0
    t = t[~t["sequence"].isin(seen)]
    if len(t) == 0: return 0
    seen.update(t["sequence"].tolist())
    t["trade_date"] = pd.to_datetime(t["time"], format="mixed").dt.date
    for d, grp in t.groupby("trade_date"):
        path = os.path.join(TICKS, f"{code.replace('.','_')}_{d}.csv")
        grp.to_csv(path, mode="a", header=not os.path.exists(path), index=False)
    return len(t)

def main(tickers):
    ctx = _ctx()
    watch = []
    for t in tickers:
        code = t if "." in t else f"US.{t.upper()}"
        watch += pick_contracts(ctx, code)
    if not watch:
        print("nothing to watch."); ctx.close(); return
    print(f"watching {len(watch)} contracts, polling every {POLL_SECONDS}s. Ctrl-C to stop.\n")
    ctx.subscribe(watch, [SubType.TICKER])
    seen = set()
    import glob
    for f in glob.glob(os.path.join(TICKS, "*.csv")):   # survive restarts
        try:
            seen.update(pd.read_csv(f, usecols=["sequence"])["sequence"].tolist())
        except Exception:
            pass
    print(f"loaded {len(seen)} previously-seen ticks from disk")
    try:
        while True:
            total = sum(append_ticks(ctx, c, seen) for c in watch)
            print(f"{datetime.datetime.now():%H:%M:%S}  new ticks: {total}  (cumulative unique: {len(seen)})")
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("\nstopped by user.")
    finally:
        ctx.close()

if __name__ == "__main__":
    main(sys.argv[1:] or ["TSLA"])
