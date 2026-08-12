"""Jarvis_60 tick collector — records what cannot be fetched retroactively.
Usage: python3 collect.py TSLA NVDA          (runs until Ctrl-C)
Saves: data/ticks/<CODE>_<date>.csv  and  data/snapshots/<TICKER>_<date>.csv"""
import sys, os, time, datetime, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from futu import OpenQuoteContext, SysConfig, SubType
from core.notify import send

KEY = "/Users/leolo/.openclaw/futu/conn_key_1024.pem"
BASE = os.path.dirname(os.path.abspath(__file__))
TICKS = os.path.join(BASE, "data", "ticks")
SNAPS = os.path.join(BASE, "data", "snapshots")
UNDER = os.path.join(BASE, "data", "underlying")
os.makedirs(UNDER, exist_ok=True)
COLS = ["option_type","option_strike_price","option_open_interest","option_implied_volatility",
        "option_premium","option_delta","option_gamma","option_vega","option_theta",
        "option_expiry_date_distance","bid_price","ask_price","volume","turnover","last_price","code"]
POLL_SECONDS = 30
TOP_N = 12  # contracts watched per ticker

def _ctx():
    SysConfig.enable_proto_encrypt(True)
    SysConfig.set_init_rsa_file(KEY)
    return OpenQuoteContext(host="127.0.0.1", port=11112)

def pick_contracts(ctx, ticker: str, tag: str = "") -> list:
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
    snap_path = os.path.join(SNAPS, f"{ticker.replace('.','_')}_{today}{tag}.csv")
    df[keep].to_csv(snap_path, index=False)
    print(f"[{ticker}] snapshot saved: {len(df)} contracts -> {os.path.basename(snap_path)}")
    live = df[(df["option_premium"] > 0) & (df["volume"] > 0) &
              (df["option_expiry_date_distance"] > 1)].copy()
    live = live.sort_values("volume", ascending=False)
    return list(live["code"].head(TOP_N))

def append_ticks(ctx, code: str, seen: set):
    r, t = ctx.get_rt_ticker(code, 1000)
    if r != 0 or t is None or len(t) == 0: return 0
    s_ = seen.setdefault(code, set())          # per-contract: sequences collide across contracts
    t = t[~t["sequence"].isin(s_)]
    if len(t) == 0: return 0
    s_.update(t["sequence"].tolist())
    t["trade_date"] = pd.to_datetime(t["time"], format="mixed").dt.date
    for d, grp in t.groupby("trade_date"):
        path = os.path.join(TICKS, f"{code.replace('.','_')}_{d}.csv")
        grp.to_csv(path, mode="a", header=not os.path.exists(path), index=False)
    return len(t)

UNDER_COLS = ["code", "update_time", "last_price", "bid_price", "ask_price",
               "volume", "turnover", "high_price", "low_price", "open_price",
               "prev_close_price"]

def record_underlying(ctx, codes):
    """Append a price row per underlying each poll. Never raises."""
    try:
        r, snap = ctx.get_market_snapshot(codes)
        if r != 0:
            return 0
        keep = [c for c in UNDER_COLS if c in snap.columns]
        snap = snap[keep].copy()
        snap["poll_time"] = datetime.datetime.now().isoformat(timespec="seconds")
        today = datetime.date.today()
        for c, grp in snap.groupby("code"):
            path = os.path.join(UNDER, f"{c.replace('.','_')}_{today}.csv")
            grp.to_csv(path, mode="a", header=not os.path.exists(path), index=False)
        return len(snap)
    except Exception:
        return 0


def main(tickers):
    ctx = _ctx()
    under_codes = [t if "." in t else f"US.{t.upper()}" for t in tickers]
    watch = []
    for t in tickers:
        code = t if "." in t else f"US.{t.upper()}"
        watch += pick_contracts(ctx, code)
    if not watch:
        print("nothing to watch."); ctx.close(); return
    print(f"watching {len(watch)} contracts, polling every {POLL_SECONDS}s. Ctrl-C to stop.\n")
    send(f"Collector STARTED\n{len(watch)} contracts: {', '.join(tickers)}")
    last_beat = time.time(); beat_ticks = 0; quiet_polls = 0
    start_time = time.time(); repicked = False
    ctx.subscribe(watch, [SubType.TICKER])
    seen = {}
    import glob, re
    for f in glob.glob(os.path.join(TICKS, "*.csv")):   # survive restarts, per contract
        mm = re.match(r"(US)_(.+)_\d{4}-\d{2}-\d{2}\.csv$", os.path.basename(f))
        if not mm: continue
        c_ = f"{mm.group(1)}.{mm.group(2)}"
        try:
            seen.setdefault(c_, set()).update(pd.read_csv(f, usecols=["sequence"])["sequence"].tolist())
        except Exception:
            pass
    print(f"loaded prior ticks for {len(seen)} contracts from disk")
    try:
        while True:
            total = sum(append_ticks(ctx, c, seen) for c in watch)
            print(f"{datetime.datetime.now():%H:%M:%S}  new ticks: {total}  (cumulative: {sum(len(v) for v in seen.values())})")
            beat_ticks += total
            quiet_polls = quiet_polls + 1 if total == 0 else 0
            if quiet_polls == 40:   # ~20 min of silence during a session
                send("WARNING: no new ticks for 20 minutes. Feed may be down.")
            if not repicked and time.time() - start_time >= 2700:   # 45 min
                fresh = []
                for t in tickers:
                    c = t if "." in t else f"US.{t.upper()}"
                    fresh += pick_contracts(ctx, c, tag="_repick")
                added = [c for c in fresh if c not in watch]
                if added:
                    ctx.subscribe(added, [SubType.TICKER])
                    watch.extend(added)
                    send(f"Watchlist re-picked on live volume: +{len(added)} contracts (now {len(watch)})")
                repicked = True
            if time.time() - last_beat >= 3600:
                send(f"Heartbeat: +{beat_ticks} ticks this hour (total {sum(len(v) for v in seen.values())})")
                last_beat = time.time(); beat_ticks = 0
            record_underlying(ctx, under_codes)
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("\nstopped by user.")
        send(f"Collector STOPPED by user. Total ticks: {sum(len(v) for v in seen.values())}")
    except Exception as e:
        send(f"Collector CRASHED: {type(e).__name__}: {e}")
        raise
    finally:
        ctx.close()

if __name__ == "__main__":
    main(sys.argv[1:] or ["TSLA", "NVDA", "GOOGL"])
