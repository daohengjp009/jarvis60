"""Jarvis_60 intraday chain state — captures IV/greeks/spread through the day.
Daily snapshots only show the close; an IV spike that reverts is invisible without this.
Writes to data/intraday/ only. Does not touch HYP-001 collection.
Usage: python3 intraday.py [minutes_between_passes]"""
import os, sys, re, time, datetime
import pandas as pd
from futu import OpenQuoteContext, SysConfig

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "data", "intraday")
KEY = "/Users/leolo/.openclaw/futu/conn_key_1024.pem"
SYMBOLS = "TSLA NVDA AAPL MSFT GOOGL SPY QQQ SPCX INTC MU SKHY COHR BE AMZN META AMD NFLX AVGO COIN PLTR MSTR ARM IWM SMCI CRWD ORCL LLY XOM".split()
STRIKES_EACH_SIDE = 10      # ATM +/- N strikes per expiry
MAX_DTE = 45
BATCH, PACE = 200, 0.4
CHAIN_PACE = 1.5   # pacing between chain calls
WINDOW = 28        # get_option_chain rejects spans over 30 days
os.makedirs(OUT, exist_ok=True)

KEEP = ["code", "update_time", "last_price", "bid_price", "ask_price", "bid_vol", "ask_vol",
        "volume", "turnover", "option_implied_volatility", "option_delta", "option_gamma",
        "option_vega", "option_theta", "option_rho", "option_open_interest",
        "option_strike_price", "option_type", "option_expiry_date_distance"]

def build_universe(ctx):
    """Chain contracts near the money. Fetched once, reused for every pass."""
    today = datetime.date.today()
    end = today + datetime.timedelta(days=MAX_DTE)
    universe = []
    for sym in SYMBOLS:
        r, spot = ctx.get_market_snapshot([f"US.{sym}"])
        if r != 0:
            print(f"  {sym}: spot failed", flush=True); continue
        px = float(spot["last_price"].iloc[0])
        parts, cur = [], today
        while cur <= end:
            stop = min(cur + datetime.timedelta(days=WINDOW), end)
            time.sleep(CHAIN_PACE)
            r, ch = ctx.get_option_chain(code=f"US.{sym}", start=str(cur), end=str(stop))
            if r == 0 and len(ch): parts.append(ch)
            elif r != 0: print(f"  {sym} {cur}..{stop}: {ch}", flush=True)
            cur = stop + datetime.timedelta(days=1)
        if not parts:
            print(f"  {sym}: no chain data", flush=True); continue
        ch = pd.concat(parts, ignore_index=True).drop_duplicates(subset=["code"])
        ch["expiry"] = ch["code"].str.extract(r"[A-Z]+(\d{6})[CP]")
        picked = []
        for exp, grp in ch.groupby("expiry"):
            for typ, g2 in grp.groupby("option_type"):
                g2 = g2.assign(d=(g2["strike_price"] - px).abs()).nsmallest(STRIKES_EACH_SIDE * 2, "d")
                picked += list(g2["code"])
        universe += picked
        print(f"  {sym:6s} spot {px:>8.2f}  {len(picked):>4d} contracts", flush=True)
    return sorted(set(universe))

def one_pass(ctx, codes, stamp):
    frames = []
    for i in range(0, len(codes), BATCH):
        r, snap = ctx.get_market_snapshot(codes[i:i + BATCH])
        if r == 0: frames.append(snap)
        time.sleep(PACE)
    if not frames: return 0
    df = pd.concat(frames, ignore_index=True)
    df = df[[c for c in KEEP if c in df.columns]].copy()
    df["snap_time"] = stamp
    day = str(datetime.date.today())
    df["sym"] = df["code"].str.extract(r"US\.([A-Z]+)\d{6}[CP]")
    n = 0
    for sym, grp in df.groupby("sym"):
        path = os.path.join(OUT, f"US_{sym}_{day}.csv")
        grp.drop(columns=["sym"]).to_csv(path, mode="a", header=not os.path.exists(path), index=False)
        n += len(grp)
    return n

def main(every_min=30):
    SysConfig.enable_proto_encrypt(True); SysConfig.set_init_rsa_file(KEY)
    ctx = OpenQuoteContext(host="127.0.0.1", port=11112)
    try:
        print(f"building universe (ATM +/-{STRIKES_EACH_SIDE} strikes, DTE<={MAX_DTE})...", flush=True)
        t0 = time.time()
        codes = build_universe(ctx)
        print(f"universe: {len(codes)} contracts in {time.time()-t0:.0f}s\n", flush=True)
        if not codes: return

        total = 0
        while True:
            now = datetime.datetime.now()
            stamp = now.strftime("%Y-%m-%d %H:%M:%S")
            t0 = time.time()
            n = one_pass(ctx, codes, stamp)
            total += n
            print(f"{now:%H:%M:%S}  wrote {n:,} rows in {time.time()-t0:.0f}s  (total {total:,})", flush=True)
            time.sleep(max(5, every_min * 60 - (time.time() - t0)))
    except KeyboardInterrupt:
        print("\nstopped by user", flush=True)
    finally:
        ctx.close()

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 30)
