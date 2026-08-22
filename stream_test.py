"""Jarvis_60 streaming test — does push delivery beat sequential polling?
Writes NOTHING into data/ticks. Safe to run alongside the HYP-001 collector.
Usage: python3 stream_test.py [seconds]"""
import sys, os, time, datetime, threading, collections
import pandas as pd
from futu import OpenQuoteContext, SysConfig, SubType, TickerHandlerBase, RET_OK

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "data", "ticks_stream")
KEY = "/Users/leolo/.openclaw/futu/conn_key_1024.pem"
os.makedirs(OUT, exist_ok=True)

lock = threading.Lock()
counts = collections.Counter()
rows = collections.defaultdict(list)
seen = collections.defaultdict(set)
dupes = collections.Counter()

class Ticks(TickerHandlerBase):
    def on_recv_rsp(self, rsp):
        ret, data = super(Ticks, self).on_recv_rsp(rsp)
        if ret != RET_OK:
            print("push error:", data); return ret, data
        with lock:
            for _, r in data.iterrows():
                c, s = r["code"], r["sequence"]
                if s in seen[c]:
                    dupes[c] += 1; continue
                seen[c].add(s)
                counts[c] += 1
                rows[c].append(dict(r))
        return ret, data

def main(seconds=180, per_symbol=40):
    SysConfig.enable_proto_encrypt(True); SysConfig.set_init_rsa_file(KEY)
    ctx = OpenQuoteContext(host="127.0.0.1", port=11112)
    ctx.set_handler(Ticks())

    today = datetime.date.today(); end = today + datetime.timedelta(days=21)
    watch = []
    for sym in ("TSLA", "NVDA", "GOOGL"):
        r, ch = ctx.get_option_chain(code=f"US.{sym}", start=str(today), end=str(end))
        if r != 0: print(f"{sym} chain failed:", ch); continue
        codes = list(ch["code"])
        picked = []
        for i in range(0, len(codes), 200):
            rr, snap = ctx.get_market_snapshot(codes[i:i+200])
            if rr == 0: picked.append(snap)
        if not picked: continue
        df = pd.concat(picked, ignore_index=True)
        df = df[(df["option_premium"] > 0) & (df["volume"] > 0) &
                (df["option_expiry_date_distance"] > 1)]
        watch += list(df.sort_values("volume", ascending=False)["code"].head(per_symbol))

    print(f"subscribing to {len(watch)} contracts (vs 50 in the polling collector)")
    t0 = time.time()
    r, d = ctx.subscribe(watch, [SubType.TICKER])
    print(f"subscribe: {'OK' if r == 0 else d}   took {time.time()-t0:.1f}s")
    if r != 0: ctx.close(); return

    r, q = ctx.query_subscription()
    print("quota:", q if r == 0 else q)
    def flush():
        """Append buffered ticks to per-contract, per-trade-date files."""
        with lock:
            pending = {c: rs for c, rs in rows.items() if rs}
            for c in pending: rows[c] = []
        n = 0
        session = datetime.date.today()
        for c, rs in pending.items():
            df = pd.DataFrame(rs)
            df["trade_date"] = pd.to_datetime(df["time"], format="mixed").dt.date
            df = df[df["trade_date"] == session]          # seal: prior sessions ignored
            if not len(df): continue
            for d, grp in df.groupby("trade_date"):
                path = os.path.join(OUT, f"{c.replace('.','_')}_{d}.csv")
                grp.to_csv(path, mode="a", header=not os.path.exists(path), index=False)
            n += len(df)
        return n

    print(f"\nlistening {seconds}s — push only, flushing to disk every 60s\n")
    written = 0
    t_end = time.time() + seconds
    try:
        while time.time() < t_end:
            time.sleep(min(60, max(1, t_end - time.time())))
            written += flush()
            with lock:
                tot, act, dup = sum(counts.values()), len(counts), sum(dupes.values())
            print(f"  {datetime.datetime.now():%H:%M:%S}  ticks {tot:>8,}  "
                  f"active {act:>3}/{len(watch)}  dupes {dup}  written {written:,}", flush=True)
    except KeyboardInterrupt:
        print("\nstopped by user")
    finally:
        written += flush()
        with lock:
            print(f"\nTOTAL {sum(counts.values()):,} ticks from {len(counts)} contracts")
            print(f"written to disk: {written:,}")
            print(f"silent contracts: {len(watch) - len(counts)}")
            print("top 5:", counts.most_common(5))
        ctx.close()

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 180)
